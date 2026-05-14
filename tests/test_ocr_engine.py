import unittest
from unittest.mock import patch


class OcrEngineTests(unittest.TestCase):
    def test_import_does_not_start_tensorflow_worker(self):
        with patch("services.ocr_engine.subprocess.Popen") as popen:
            import services.ocr_engine as ocr_engine

            self.assertFalse(ocr_engine._worker_started)
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
