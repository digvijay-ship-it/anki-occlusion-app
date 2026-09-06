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



    def test_ocr_number_recognizes_synthetic_digits_0_to_9(self):
        from PIL import Image, ImageDraw
        def make_digit(d, w=6):
            img = Image.new("RGB", (100, 100), "white")
            draw = ImageDraw.Draw(img)
            if d == 0:
                draw.ellipse((20, 15, 80, 85), outline="black", width=w)
            elif d == 1:
                draw.line([(35, 30), (50, 15), (50, 85)], fill="black", width=w, joint="curve")
            elif d == 2:
                draw.line([(25, 30), (40, 15), (70, 15), (75, 35), (25, 85), (75, 85)], fill="black", width=w, joint="curve")
            elif d == 3:
                draw.line([(25, 20), (75, 20), (50, 50), (75, 65), (65, 85), (25, 85)], fill="black", width=w, joint="curve")
            elif d == 4:
                draw.line([(60, 15), (25, 60), (75, 60)], fill="black", width=w, joint="curve")
                draw.line([(60, 40), (60, 85)], fill="black", width=w, joint="curve")
            elif d == 5:
                draw.line([(70, 20), (35, 20), (30, 48), (68, 48), (72, 70), (60, 85), (25, 85)], fill="black", width=w, joint="curve")
            elif d == 6:
                draw.line([(65, 15), (35, 50), (30, 70), (50, 85), (70, 80), (75, 60), (60, 50), (35, 55)], fill="black", width=w, joint="curve")
            elif d == 7:
                draw.line([(25, 20), (75, 20), (45, 85)], fill="black", width=w, joint="curve")
            elif d == 8:
                draw.ellipse((35, 15, 65, 48), outline="black", width=w)
                draw.ellipse((30, 48, 70, 85), outline="black", width=w)
            elif d == 9:
                draw.ellipse((32, 15, 68, 52), outline="black", width=w)
                draw.line([(68, 30), (68, 85)], fill="black", width=w, joint="curve")
            return img

        for digit in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
            img = make_digit(digit)
            pred = ocr_engine.ocr_number(img)
            self.assertEqual(pred, str(digit), f"Failed recognizing synthetic digit {digit}")

    def test_ocr_multidigit_cube_predictions(self):
        from PIL import Image, ImageDraw
        # Test 729 and 6859
        def make_number(num_str, w=6):
            canvas_w = 20 + len(num_str) * 60
            img = Image.new("RGB", (canvas_w, 100), "white")
            draw = ImageDraw.Draw(img)
            for idx, ch in enumerate(num_str):
                ox = 10 + idx * 60
                d = int(ch)
                if d == 2:
                    draw.line([(ox+10, 30), (ox+25, 15), (ox+45, 15), (ox+50, 35), (ox+10, 85), (ox+50, 85)], fill="black", width=w, joint="curve")
                elif d == 5:
                    draw.line([(ox+45, 20), (ox+20, 20), (ox+18, 48), (ox+42, 48), (ox+48, 70), (ox+40, 85), (ox+15, 85)], fill="black", width=w, joint="curve")
                elif d == 6:
                    draw.line([(ox+45, 15), (ox+20, 50), (ox+18, 70), (ox+35, 85), (ox+48, 80), (ox+50, 60), (ox+40, 50), (ox+20, 55)], fill="black", width=w, joint="curve")
                elif d == 7:
                    draw.line([(ox+10, 20), (ox+50, 20), (ox+30, 85)], fill="black", width=w, joint="curve")
                elif d == 8:
                    draw.ellipse((ox+20, 15, ox+45, 48), outline="black", width=w)
                    draw.ellipse((ox+15, 48, ox+50, 85), outline="black", width=w)
                elif d == 9:
                    draw.ellipse((ox+18, 15, ox+48, 52), outline="black", width=w)
                    draw.line([(ox+48, 30), (ox+48, 85)], fill="black", width=w, joint="curve")
            return img

        self.assertEqual(ocr_engine.ocr_number(make_number("729")), "729")
        self.assertEqual(ocr_engine.ocr_number(make_number("6859")), "6859")



if __name__ == "__main__":
    unittest.main()

