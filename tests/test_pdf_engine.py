import os
import contextlib
import io
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

import cache_manager
import pdf_engine


_APP = QApplication.instance() or QApplication([])


@unittest.skipUnless(pdf_engine.PDF_SUPPORT, "PyMuPDF not installed")
class PdfEngineTests(unittest.TestCase):
    def setUp(self):
        import fitz

        pdf_engine._SKELETON_CACHE.clear()
        self.addCleanup(pdf_engine._SKELETON_CACHE.clear)

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
            thread.pages_ready.connect(lambda pages, loaded, total: chunks.append((len(pages), loaded, total)))
            thread.done.connect(lambda pages, err: done.append((len(pages), err)))
            thread.run()

        self.assertEqual(chunks, [(1, 1, 2), (2, 2, 2)])
        self.assertEqual(done, [(2, None)])


if __name__ == "__main__":
    unittest.main()
