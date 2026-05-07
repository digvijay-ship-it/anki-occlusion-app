import os
import unittest
from unittest import mock

from services import native_pdf_backend as backend


class NativePdfBackendTests(unittest.TestCase):
    def setUp(self):
        backend.get_native_backend.cache_clear()

    def tearDown(self):
        backend.get_native_backend.cache_clear()

    def test_requested_backend_defaults_to_native(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual(backend.requested_backend(), "native")

    def test_requested_backend_accepts_python_override(self):
        with mock.patch.dict(os.environ, {"ANKI_PDF_BACKEND": "python"}, clear=False):
            self.assertEqual(backend.requested_backend(), "python")

    def test_status_falls_back_when_dll_missing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch.object(backend, "_find_native_backend_dll", return_value=""):
                status = backend.native_backend_status()
                active = backend.active_pdf_backend_name()
        self.assertFalse(status.available)
        self.assertFalse(status.active)
        self.assertFalse(status.is_stub)
        self.assertEqual(active, "python")

    def test_render_helper_returns_empty_when_native_inactive(self):
        with mock.patch.object(backend, "native_backend_status", return_value=backend.NativePdfBackendStatus(
            requested="native",
            available=False,
            active=False,
            is_stub=False,
            error="missing",
        )):
            pages = backend.render_pdf_pages_native("demo.pdf", [0, 1], zoom=2.0)
        self.assertEqual(pages, {})


if __name__ == "__main__":
    unittest.main()
