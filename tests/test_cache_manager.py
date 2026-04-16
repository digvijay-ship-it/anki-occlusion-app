import gc
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

import cache_manager


_APP = QApplication.instance() or QApplication([])


class CacheHelperTests(unittest.TestCase):
    def test_fmt_bytes_covers_common_ranges(self):
        self.assertEqual(cache_manager._fmt_bytes(512), "512 B")
        self.assertEqual(cache_manager._fmt_bytes(2048), "2.0 KB")
        self.assertEqual(cache_manager._fmt_bytes(3 * 1024 ** 2), "3.0 MB")

    def test_short_name_truncates_long_paths(self):
        long_name = "a" * 50 + ".pdf"

        shortened = cache_manager._short_name(long_name)

        self.assertTrue(shortened.endswith("..."))
        self.assertLessEqual(len(shortened), 36)


class LRUPageCacheTests(unittest.TestCase):
    def test_put_get_and_invalidate_pdf(self):
        cache = cache_manager.LRUPageCache()
        px = QPixmap(10, 20)
        px.fill()

        cache.put("doc1.pdf", 0, px)

        self.assertIs(cache.get("doc1.pdf", 0), px)
        self.assertEqual(cache.ram_bytes_for_pdf("doc1.pdf"), 10 * 20 * 4)
        cache.invalidate_pdf("doc1.pdf")
        self.assertIsNone(cache.get("doc1.pdf", 0))

    def test_cache_evicts_least_recently_used_page_at_limit(self):
        cache = cache_manager.LRUPageCache(max_pages=2)
        first = QPixmap(10, 10)
        second = QPixmap(10, 10)
        third = QPixmap(10, 10)

        cache.put("doc.pdf", 0, first)
        cache.put("doc.pdf", 1, second)
        cache.put("doc.pdf", 2, third)

        self.assertIsNone(cache.get("doc.pdf", 0))
        self.assertIs(cache.get("doc.pdf", 1), second)
        self.assertIs(cache.get("doc.pdf", 2), third)

    def test_get_refreshes_recency_before_eviction(self):
        cache = cache_manager.LRUPageCache(max_pages=2)
        first = QPixmap(10, 10)
        second = QPixmap(10, 10)
        third = QPixmap(10, 10)

        cache.put("doc.pdf", 0, first)
        cache.put("doc.pdf", 1, second)
        self.assertIs(cache.get("doc.pdf", 0), first)
        cache.put("doc.pdf", 2, third)

        self.assertIs(cache.get("doc.pdf", 0), first)
        self.assertIsNone(cache.get("doc.pdf", 1))
        self.assertIs(cache.get("doc.pdf", 2), third)


class DiskCombinedCacheTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)

    def test_put_get_invalidate_and_clear(self):
        with patch.object(cache_manager.tempfile, "gettempdir", return_value=self.tmpdir.name):
            cache = cache_manager.DiskCombinedCache()
            px = QPixmap(12, 18)
            px.fill()

            cache.put("doc.pdf", px, total_pages=2)
            loaded = cache.get("doc.pdf")

            self.assertIsNotNone(loaded)
            loaded_px, total_pages = loaded
            self.assertEqual(total_pages, 2)
            self.assertFalse(loaded_px.isNull())

            cache.invalidate("doc.pdf")
            self.assertIsNone(cache.get("doc.pdf"))

            cache.put("doc-a.pdf", px, total_pages=1)
            cache.put("doc-b.pdf", px, total_pages=1)
            cache.clear()
            self.assertIsNone(cache.get("doc-a.pdf"))
            self.assertIsNone(cache.get("doc-b.pdf"))


class RegistryTests(unittest.TestCase):
    def test_mask_registry_tracks_and_invalidates_canvas_layers(self):
        registry = cache_manager._MaskRegistry()

        class FakeCanvas:
            def __init__(self):
                self._mask_cache_layer = QPixmap(5, 6)
                self._mask_cache_layer.fill()
                self._mask_cache_dirty = False
                self.updated = False

            def update(self):
                self.updated = True

        canvas = FakeCanvas()
        registry.register("doc.pdf", canvas)

        self.assertEqual(registry.mask_bytes_for_pdf("doc.pdf"), 5 * 6 * 4)
        registry.invalidate_masks_for_pdf("doc.pdf")
        self.assertIsNone(canvas._mask_cache_layer)
        self.assertTrue(canvas._mask_cache_dirty)
        self.assertTrue(canvas.updated)

    def test_pixmap_registry_reports_bytes_and_cleans_dead_entries(self):
        registry = cache_manager._PixmapRegistry()

        class Holder:
            pass

        holder = Holder()
        holder.preview = QPixmap(7, 8)
        holder.preview.fill()
        registry.register("preview", holder, "preview", "doc.pdf")

        self.assertEqual(registry.bytes_for_pdf("doc.pdf"), 7 * 8 * 4)
        self.assertIn("doc.pdf", registry.all_registered_pdfs())
        self.assertEqual(registry.breakdown("doc.pdf")["preview"], 7 * 8 * 4)

        del holder
        gc.collect()

        self.assertEqual(registry.total_bytes(), 0)


if __name__ == "__main__":
    unittest.main()
