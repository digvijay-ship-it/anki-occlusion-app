import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QCoreApplication

from services.ocr_engine import OcrNumberThread


_APP = QCoreApplication.instance() or QCoreApplication([])


class OcrEngineTests(unittest.TestCase):
    def test_ocr_number_thread_emits_result_without_blocking_caller_path(self):
        results = []
        failures = []
        thread = OcrNumberThread(object())
        thread.result.connect(results.append)
        thread.failed.connect(failures.append)

        with patch("services.ocr_engine.ocr_number", return_value="42"):
            thread.run()

        self.assertEqual(results, ["42"])
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
