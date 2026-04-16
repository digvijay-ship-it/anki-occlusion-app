import os
import contextlib
import io
import tempfile
import unittest
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

        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)
        self.pdf_path = Path(self.tmpdir.name) / "sample.pdf"

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

    def test_load_pdf_skeleton_returns_error_for_missing_file(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = pdf_engine.load_pdf_skeleton(str(self.pdf_path) + ".missing")

        self.assertIsNotNone(result.error)
        self.assertEqual(result.total_pages, 0)

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
