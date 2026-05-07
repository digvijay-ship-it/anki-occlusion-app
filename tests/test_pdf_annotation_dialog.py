import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from ui.pdf_annotation_dialog import PdfAnnotationCanvas, PdfAnnotationDialog


_APP = QApplication.instance() or QApplication([])


class _FakeWheelEvent:
    def __init__(self, delta_y):
        self._delta_y = int(delta_y)
        self.accepted = False

    class _Delta:
        def __init__(self, value):
            self._value = value

        def y(self):
            return self._value

    def angleDelta(self):
        return self._Delta(self._delta_y)

    def accept(self):
        self.accepted = True


class PdfAnnotationCanvasTests(unittest.TestCase):
    def test_ctrl_wheel_zoom_changes_scale(self):
        canvas = PdfAnnotationCanvas()
        canvas.load_pages([QPixmap(100, 120)])
        start = canvas._scale
        event = _FakeWheelEvent(120)

        canvas.handle_ctrl_wheel_zoom(event)

        self.assertGreater(canvas._scale, start)
        self.assertTrue(event.accepted)

    def test_native_zoom_changes_scale(self):
        canvas = PdfAnnotationCanvas()
        canvas.load_pages([QPixmap(100, 120)])
        start = canvas._scale

        canvas.handle_native_zoom(0.2)

        self.assertGreater(canvas._scale, start)


class PdfAnnotationDialogTests(unittest.TestCase):
    def test_pen_style_override_is_annotation_only(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog._annotation_pen_color = "#11AAFF"
        dialog._annotation_pen_width = 6.2

        style = dialog._annotation_pen_style_override("pen")
        highlight_style = dialog._annotation_pen_style_override("highlight")

        self.assertEqual(style, {"color": "#11AAFF", "width": 6.2})
        self.assertIsNone(highlight_style)

    def test_adjust_pen_width_and_reset_are_saved_separately(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog._annotation_pen_color = "#11AAFF"
        dialog._annotation_pen_width = 3.0
        dialog.canvas = type("Canvas", (), {"_tool": "pen"})()
        dialog.lbl_status = MagicMock()
        dialog.btn_color = MagicMock()
        dialog._debug = lambda *args, **kwargs: None
        dialog._update_pen_controls = PdfAnnotationDialog._update_pen_controls.__get__(dialog, PdfAnnotationDialog)
        dialog._save_annotation_pen_settings = PdfAnnotationDialog._save_annotation_pen_settings.__get__(dialog, PdfAnnotationDialog)

        fake_settings = MagicMock()
        with patch("ui.pdf_annotation_dialog.QSettings", return_value=fake_settings):
            dialog._adjust_pen_width(0.4)
            self.assertAlmostEqual(dialog._annotation_pen_width, 3.4)
            dialog._reset_pen_style()

        fake_settings.setValue.assert_any_call("annotation/pen_color", "#11AAFF")
        fake_settings.setValue.assert_any_call("annotation/pen_width", 3.4)
        self.assertEqual(dialog._annotation_pen_color, PdfAnnotationDialog.PEN_DEFAULT_COLOR)
        self.assertEqual(dialog._annotation_pen_width, PdfAnnotationDialog.PEN_DEFAULT_WIDTH)

    def test_choose_pen_color_updates_annotation_pen_only(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog._annotation_pen_color = "#FF4444"
        dialog._annotation_pen_width = 2.8
        dialog.canvas = type("Canvas", (), {"_tool": "pen"})()
        dialog.lbl_status = MagicMock()
        dialog.btn_color = MagicMock()
        dialog._debug = lambda *args, **kwargs: None
        dialog._update_pen_controls = PdfAnnotationDialog._update_pen_controls.__get__(dialog, PdfAnnotationDialog)
        dialog._save_annotation_pen_settings = lambda: None

        fake_color = type("Color", (), {"isValid": lambda self: True, "name": lambda self: "#00FFAA"})()
        with patch("ui.pdf_annotation_dialog.QColorDialog.getColor", return_value=fake_color):
            dialog._choose_pen_color()

        self.assertEqual(dialog._annotation_pen_color, "#00FFAA")


if __name__ == "__main__":
    unittest.main()
