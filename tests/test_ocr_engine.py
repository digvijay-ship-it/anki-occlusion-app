import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QCoreApplication

from services.ocr_engine import OcrNumberThread
from services import ocr_engine


_APP = QCoreApplication.instance() or QCoreApplication([])


class OcrEngineTests(unittest.TestCase):
    def tearDown(self):
        ocr_engine._reset_worker_state()

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

    def test_ocr_number_resets_dead_worker_after_communication_error(self):
        fake_img = MagicMock()
        fake_img.save.side_effect = lambda buf, format: buf.write(b"png")
        fake_proc = MagicMock()
        fake_proc.stdin.write.side_effect = BrokenPipeError("closed")
        fake_proc.poll.return_value = None
        ocr_engine._worker_process = fake_proc
        ocr_engine._worker_ready = True
        ocr_engine._worker_started = True

        with patch("services.ocr_engine._ensure_worker_started"):
            result = ocr_engine.ocr_number(fake_img)

        self.assertEqual(result, "")
        self.assertIsNone(ocr_engine._worker_process)
        self.assertFalse(ocr_engine._worker_ready)
        self.assertFalse(ocr_engine._worker_started)
        fake_proc.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
