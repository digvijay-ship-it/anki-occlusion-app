import os
import contextlib
import io
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage

import cache_manager
import pdf_engine


_APP = QApplication.instance() or QApplication([])


@unittest.skipUnless(pdf_engine.PDF_SUPPORT, "PyMuPDF not installed")
class PdfEngineTests(unittest.TestCase):
    def setUp(self):
        import fitz

        pdf_engine._SKELETON_CACHE.clear()
        pdf_engine._SKELETON_DIMS_CACHE.clear()
        self.addCleanup(pdf_engine._SKELETON_CACHE.clear)
        self.addCleanup(pdf_engine._SKELETON_DIMS_CACHE.clear)

        tmp_root = Path(__file__).resolve().parent / "_tmp_files"
        tmp_root.mkdir(exist_ok=True)
        self.pdf_path = tmp_root / f"sample_{uuid.uuid4().hex}.pdf"
        self.addCleanup(lambda: self.pdf_path.exists() and self.pdf_path.unlink())

        doc = fitz.open()
        page1 = doc.new_page(width=200, height=300)
        page1.insert_text((40, 40), "Page 1")
        page2 = doc.new_page(width=320, height=180)
        page2.insert_text((40, 40), "Page 2")
        doc.save(str(self.pdf_path))
        doc.close()

    def test_load_pdf_skeleton_returns_placeholders_and_dimensions(self):
        import fitz

        with contextlib.redirect_stdout(io.StringIO()):
            result = pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=1.0)

        self.assertIsNone(result.error)
        self.assertEqual(result.total_pages, 2)
        self.assertEqual(len(result.placeholders), 2)
        self.assertEqual(len(result.page_dims), 2)

        doc = fitz.open(str(self.pdf_path))
        expected_dims = []
        matrix = fitz.Matrix(1.0, 1.0)
        for i in range(len(doc)):
            pix = doc[i].get_pixmap(matrix=matrix, alpha=False)
            expected_dims.append((pix.width, pix.height))
        doc.close()

        self.assertEqual(result.page_dims, expected_dims)
        self.assertTrue(all(not px.isNull() for px in result.placeholders))

    def test_load_pdf_skeleton_reuses_shared_placeholder_for_same_size_pages(self):
        import fitz

        same_size_path = self.pdf_path.with_name(f"same_size_{uuid.uuid4().hex}.pdf")
        self.addCleanup(lambda: same_size_path.exists() and same_size_path.unlink())

        doc = fitz.open()
        doc.new_page(width=240, height=240).insert_text((40, 40), "Page 1")
        doc.new_page(width=240, height=240).insert_text((40, 40), "Page 2")
        doc.save(str(same_size_path))
        doc.close()

        with contextlib.redirect_stdout(io.StringIO()):
            result = pdf_engine.load_pdf_skeleton(str(same_size_path), zoom=1.0)

        self.assertEqual(result.total_pages, 2)
        self.assertEqual(result.page_dims[0], result.page_dims[1])
        self.assertIs(result.placeholders[0], result.placeholders[1])

    def test_load_pdf_skeleton_returns_error_for_missing_file(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = pdf_engine.load_pdf_skeleton(str(self.pdf_path) + ".missing")

        self.assertIsNotNone(result.error)
        self.assertEqual(result.total_pages, 0)

    def test_load_pdf_skeleton_reuses_cached_result_for_same_file(self):
        original_open = pdf_engine.fitz.open

        with patch.object(pdf_engine.fitz, "open", wraps=original_open) as open_mock:
            with contextlib.redirect_stdout(io.StringIO()):
                first = pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=1.0)
                second = pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=1.0)

        self.assertIsNone(first.error)
        self.assertIsNone(second.error)
        self.assertEqual(open_mock.call_count, 1)
        self.assertEqual(first.page_dims, second.page_dims)
        self.assertIsNot(first.placeholders, second.placeholders)

    def test_invalidate_pdf_skeleton_forces_reopen(self):
        original_open = pdf_engine.fitz.open

        with patch.object(pdf_engine.fitz, "open", wraps=original_open) as open_mock:
            with contextlib.redirect_stdout(io.StringIO()):
                pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=1.0)
                pdf_engine.invalidate_pdf_skeleton(str(self.pdf_path))
                pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=1.0)

        self.assertEqual(open_mock.call_count, 2)

    def test_pdf_page_to_pixmap_renders_page(self):
        import fitz

        doc = fitz.open(str(self.pdf_path))
        qpx = pdf_engine.pdf_page_to_pixmap(doc[0], fitz.Matrix(1.0, 1.0))
        doc.close()

        self.assertFalse(qpx.isNull())
        self.assertGreater(qpx.width(), 0)
        self.assertGreater(qpx.height(), 0)

    def test_choose_pdf_render_zoom_uses_3x_below_40_pages(self):
        self.assertEqual(pdf_engine.choose_pdf_render_zoom(1), 3.0)
        self.assertEqual(pdf_engine.choose_pdf_render_zoom(39), 3.0)

    def test_choose_pdf_render_zoom_uses_2x_at_or_above_40_pages(self):
        self.assertEqual(pdf_engine.choose_pdf_render_zoom(40), 2.0)
        self.assertEqual(pdf_engine.choose_pdf_render_zoom(250), 2.0)

    def test_adapt_pdf_boxes_to_render_zoom_remaps_legacy_box_positions(self):
        boxes = [{
            "rect": [40.0, 60.0, 50.0, 30.0],
            "label": "Mask 1",
            "page_num": 0,
        }]

        adapted = pdf_engine.adapt_pdf_boxes_to_render_zoom(
            str(self.pdf_path),
            boxes,
            source_zoom=1.5,
            target_zoom=3.0,
        )

        self.assertEqual(boxes[0]["rect"], [40.0, 60.0, 50.0, 30.0])
        self.assertAlmostEqual(adapted[0]["rect"][0], 80.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][1], 120.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][2], 100.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][3], 60.0, places=1)

    def test_adapt_pdf_boxes_uses_dimension_only_skeletons(self):
        boxes = [{
            "rect": [40.0, 60.0, 50.0, 30.0],
            "label": "Mask 1",
        }]

        with patch.object(pdf_engine, "_get_skeleton_placeholder") as placeholder:
            adapted = pdf_engine.adapt_pdf_boxes_to_render_zoom(
                str(self.pdf_path),
                boxes,
                source_zoom=1.5,
                target_zoom=3.0,
            )

        placeholder.assert_not_called()
        self.assertEqual(adapted[0]["page_num"], 0)

    def test_skeleton_thread_uses_dimension_cache(self):
        thread = pdf_engine.PdfSkeletonThread(str(self.pdf_path), zoom=1.0)
        emitted = []
        thread.done.connect(emitted.append)
        with patch.object(pdf_engine, "load_pdf_page_dims") as load_dims:
            load_dims.return_value = pdf_engine.PdfSkeletonResult(
                [], [(200, 300)], 1, None
            )

            thread.run()

        load_dims.assert_called_once_with(str(self.pdf_path), zoom=1.0)
        self.assertEqual(emitted[0].page_dims, [(200, 300)])

    def test_adapt_pdf_boxes_to_render_zoom_recomputes_page_for_later_masks(self):
        src = pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=1.5)
        first_h = src.page_dims[0][1]
        second_top = first_h + 12
        boxes = [{
            "rect": [30.0, float(second_top + 20.0), 40.0, 25.0],
            "label": "Mask 2",
            # stale / wrong saved page_num on purpose
            "page_num": 0,
        }]

        adapted = pdf_engine.adapt_pdf_boxes_to_render_zoom(
            str(self.pdf_path),
            boxes,
            source_zoom=1.5,
            target_zoom=3.0,
        )

        dst = pdf_engine.load_pdf_skeleton(str(self.pdf_path), zoom=3.0)
        expected_second_top = dst.page_dims[0][1] + 12

        self.assertEqual(adapted[0]["page_num"], 1)
        self.assertAlmostEqual(adapted[0]["rect"][0], 60.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][1], expected_second_top + 40.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][2], 80.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][3], 50.0, places=1)

    def test_get_cached_pdf_page_set_reports_hit_and_miss_counts(self):
        doc = pdf_engine.fitz.open(str(self.pdf_path))
        px = pdf_engine.pdf_page_to_pixmap(doc[0], pdf_engine.fitz.Matrix(1.0, 1.0))
        doc.close()
        cache = cache_manager.LRUPageCache()
        cache.put(str(self.pdf_path), 0, px, render_zoom=1.0)

        with patch.object(pdf_engine, "PAGE_CACHE", cache):
            state = pdf_engine.get_cached_pdf_page_set(
                str(self.pdf_path), total_pages=2, hydrate_pages=True
            )

        self.assertEqual(state["total_pages"], 2)
        self.assertEqual(state["cache_hit_count"], 1)
        self.assertEqual(state["cache_miss_count"], 1)
        self.assertEqual(state["cached_page_indices"], [0])
        self.assertIn(0, state["cached_pages_by_index"])

    def test_get_cached_pdf_page_set_counts_without_hydrating_pages(self):
        cache = MagicMock()
        cache.cached_page_indices.return_value = [0, 2]

        with patch.object(pdf_engine, "PAGE_CACHE", cache):
            state = pdf_engine.get_cached_pdf_page_set("doc.pdf", total_pages=4)

        cache.cached_page_indices.assert_called_once_with("doc.pdf", 4, variant=None)
        cache.get.assert_not_called()
        self.assertEqual(state["total_pages"], 4)
        self.assertEqual(state["cached_page_indices"], [0, 2])
        self.assertEqual(state["cached_pages_by_index"], {})
        self.assertEqual(state["cache_hit_count"], 2)
        self.assertEqual(state["cache_miss_count"], 2)

    def test_on_demand_thread_emits_rendered_pages_and_skips_out_of_range(self):
        emitted_pages = []
        completed = []
        errors = []

        with patch.object(pdf_engine, "PAGE_CACHE", cache_manager.LRUPageCache()):
            thread = pdf_engine.PdfOnDemandThread(str(self.pdf_path), [0, 5], zoom=1.0)
            thread.page_ready.connect(lambda page_num, px: emitted_pages.append((page_num, px.width(), px.height())))
            thread.batch_done.connect(lambda pages: completed.append(list(pages)))
            thread.error.connect(errors.append)
            with contextlib.redirect_stdout(io.StringIO()):
                thread.run()

        self.assertEqual(errors, [])
        self.assertEqual([page for page, *_ in emitted_pages], [0])
        self.assertEqual(completed, [[0]])

    def test_loader_thread_emits_chunks_and_final_pages(self):
        chunks = []
        done = []

        with patch.object(pdf_engine, "PAGE_CACHE", cache_manager.LRUPageCache()):
            thread = pdf_engine.PdfLoaderThread(str(self.pdf_path), zoom=1.0, chunk_size=1)
            thread.pages_ready.connect(lambda pages, loaded, total: chunks.append((len(pages), loaded, total, all(isinstance(page, QImage) for page in pages))))
            thread.done.connect(lambda pages, err: done.append((len(pages), err, all(isinstance(page, QImage) for page in pages))))
            thread.run()

        self.assertEqual(chunks, [(1, 1, 2, True), (2, 2, 2, True)])
        self.assertEqual(done, [(2, None, True)])

    def test_adapt_pdf_boxes_to_render_zoom_fallback_scaling_corrects_page_gap(self):
        # Using a non-existent path ensures fallback linear scaling is triggered
        boxes = [{
            "rect": [10.0, 100.0, 50.0, 30.0],
            "label": "Mask 1",
            "page_num": 1,
        }]

        adapted = pdf_engine.adapt_pdf_boxes_to_render_zoom(
            str(self.pdf_path) + ".nonexistent",
            boxes,
            source_zoom=1.5,
            target_zoom=3.0,
            page_gap=12,
        )

        self.assertEqual(len(adapted), 1)
        self.assertAlmostEqual(adapted[0]["rect"][0], 20.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][1], 188.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][2], 100.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][3], 60.0, places=1)

    def test_adapt_pdf_boxes_to_render_zoom_auto_heals_mismatched_source_zoom(self):
        # Page 0 is 200x300, page 1 is 320x180 at 1.0 zoom.
        # At 3.0 zoom:
        # page 0 height = 300 * 3.0 = 900
        # page 1 top = 900 + 12 = 912
        # page 1 height = 180 * 3.0 = 540
        # Let's put a box on page 1 with Y = 1000 (which is inside 912 to 1452).
        boxes = [{
            "rect": [20.0, 1000.0, 50.0, 30.0],
            "label": "Mask on Page 1",
            "page_num": 1,
        }]

        # Call with incorrect source_zoom=1.5 and target_zoom=3.0.
        # Without auto-healing, Y would be incorrectly scaled.
        # With auto-healing, it will infer the source zoom as 3.0, matching target_zoom.
        adapted = pdf_engine.adapt_pdf_boxes_to_render_zoom(
            str(self.pdf_path),
            boxes,
            source_zoom=1.5,
            target_zoom=3.0,
            page_gap=12,
        )

        self.assertEqual(len(adapted), 1)
        self.assertAlmostEqual(adapted[0]["rect"][0], 20.0, places=1)
        self.assertAlmostEqual(adapted[0]["rect"][1], 1000.0, places=1)




if __name__ == "__main__":
    unittest.main()
