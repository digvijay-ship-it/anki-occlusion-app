import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QCoreApplication

from services.ocr_engine import OcrNumberThread
from services import ocr_engine


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

    def test_preprocess_digit_image_extracts_correct_digits(self):
        from PIL import Image
        fake_img = Image.new("L", (10, 10), color=255)
        with patch("services.ocr_engine.cv2.findContours", return_value=([], None)):
            res = ocr_engine.preprocess_digit_image(fake_img)
            self.assertIsNone(res)

    def test_clean_ocr_title_handles_multiline_text(self):
        text = "This is a question?\nSome details.\nMore details."
        cleaned = ocr_engine.clean_ocr_title(text)
        self.assertEqual(cleaned, "This is a question?")

    def test_clean_ocr_title_truncates_long_text(self):
        text = "This is an extremely long question without any question marks that should be truncated to some word boundary near sixty characters"
        cleaned = ocr_engine.clean_ocr_title(text)
        self.assertTrue(cleaned.endswith("..."))
        self.assertLessEqual(len(cleaned), 64)

    def test_ocr_text_thread_emits_result(self):
        results = []
        thread = ocr_engine.OcrTextThread("some_image.png", "Pasted Image")
        thread.result.connect(lambda raw, default: results.append((raw, default)))

        with patch("services.ocr_engine.run_native_ocr", return_value="Extracted text"):
            thread.run()

        self.assertEqual(results, [("Extracted text", "Pasted Image")])



if __name__ == "__main__":
    unittest.main()
