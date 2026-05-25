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

    def test_replace_page_same_dimensions_updates_only_that_page(self):
        canvas = PdfAnnotationCanvas()
        canvas.load_pages([QPixmap(100, 120), QPixmap(80, 90)])
        replacement = QPixmap(100, 120)

        with patch.object(canvas, "load_pages", side_effect=AssertionError):
            canvas.replace_page(0, replacement)

        self.assertIs(canvas._pages[0], replacement)
        self.assertEqual(canvas._page_screen_rect(0).height(), 120)

    def test_replace_page_dimension_change_rebuilds_layout(self):
        canvas = PdfAnnotationCanvas()
        canvas.load_pages([QPixmap(100, 120), QPixmap(80, 90)])
        replacement = QPixmap(120, 140)

        with patch.object(canvas, "load_pages", wraps=canvas.load_pages) as load_pages:
            canvas.replace_page(0, replacement)

        load_pages.assert_called_once()
        self.assertIs(canvas._pages[0], replacement)


class PdfAnnotationDialogTests(unittest.TestCase):
    def test_target_page_window_prefetches_current_plus_neighbors(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog.session = type("Session", (), {"page_count": 5})()

        self.assertEqual(dialog._target_page_window(0), [0, 1])
        self.assertEqual(dialog._target_page_window(2), [1, 2, 3])
        self.assertEqual(dialog._target_page_window(4), [3, 4])

    def test_on_scroll_changed_requests_new_window_when_page_changes(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog._current_page_zero = 1
        dialog.canvas = type("Canvas", (), {"get_current_page": lambda self, value: 2})()
        dialog._debug = lambda *args, **kwargs: None
        dialog._ensure_annotation_window = MagicMock()
        dialog._ensure_render_window = MagicMock()
        dialog._viewer = type("Viewer", (), {"set_page_ui": MagicMock()})()
        dialog.return_page = 1

        dialog._on_scroll_changed(350)

        dialog._ensure_annotation_window.assert_called_once_with(2, reason="scroll")
        dialog._ensure_render_window.assert_called_once_with(2, reason="scroll")
        dialog._viewer.set_page_ui.assert_called_once_with(2)
        self.assertEqual(dialog._current_page_zero, 2)
        self.assertEqual(dialog.return_page, 2)

    def test_on_page_ready_prints_lazy_load_debug_when_verbose_enabled(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog.canvas = type("Canvas", (), {"replace_page": MagicMock()})()
        dialog._debug = lambda *args, **kwargs: None
        pixmap = QPixmap(120, 180)
        pixmap.fill()

        with patch.dict(os.environ, {"ANKI_ANNOTATION_VERBOSE": "1"}, clear=False), \
             patch("builtins.print") as fake_print:
            dialog._on_page_ready(2, pixmap)

        dialog.canvas.replace_page.assert_called_once_with(2, pixmap)
        debug_line = fake_print.call_args_list[0][0][0]
        self.assertEqual(debug_line, "[DEBUG][annotation_lazy] 👀 p.3")

    def test_on_page_ready_is_quiet_without_verbose_debug(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog.canvas = type("Canvas", (), {"replace_page": MagicMock()})()
        dialog._debug = lambda *args, **kwargs: None
        pixmap = QPixmap(120, 180)
        pixmap.fill()

        with patch.dict(os.environ, {"ANKI_ANNOTATION_VERBOSE": ""}, clear=False), \
             patch("builtins.print") as fake_print:
            dialog._on_page_ready(2, pixmap)

        dialog.canvas.replace_page.assert_called_once_with(2, pixmap)
        fake_print.assert_not_called()

    def test_apply_initial_anchor_position_uses_image_space_y(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog.initial_anchor_y = 240.0
        dialog.canvas = type("Canvas", (), {"_scale": 1.25})()
        bar = MagicMock()
        dialog.scroll = type("Scroll", (), {"verticalScrollBar": lambda self: bar})()

        applied = dialog._apply_initial_anchor_position("test_anchor", finalize=True)

        self.assertTrue(applied)
        bar.setValue.assert_called_once_with(300)
        self.assertIsNone(dialog.initial_anchor_y)

    def test_retarget_from_review_updates_page_and_image_space_anchor(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog.session = type("Session", (), {"page_count": 8})()
        dialog.canvas = type("Canvas", (), {"_scale": 1.5})()
        bar = MagicMock()
        dialog.scroll = type("Scroll", (), {"verticalScrollBar": lambda self: bar})()
        dialog._viewer = type("Viewer", (), {"set_page_ui": MagicMock(), "go_to_page": MagicMock()})()
        dialog._ensure_annotation_window = MagicMock()
        dialog._ensure_render_window = MagicMock()

        with patch("ui.pdf_annotation_dialog.QTimer.singleShot", side_effect=lambda _delay, fn: fn()):
            dialog.retarget_from_review(3, 200.0)

        dialog._ensure_annotation_window.assert_called_once_with(3, reason="review_handoff")
        dialog._ensure_render_window.assert_called_once_with(3, reason="review_handoff")
        dialog._viewer.set_page_ui.assert_called_with(3)
        dialog._viewer.go_to_page.assert_not_called()
        bar.setValue.assert_called_with(300)
        self.assertEqual(dialog._current_page_zero, 3)
        self.assertEqual(dialog.return_page, 3)
        self.assertEqual(dialog.return_anchor_y, 200.0)

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

    def test_save_pdf_ignores_reentrant_call(self):
        dialog = PdfAnnotationDialog.__new__(PdfAnnotationDialog)
        dialog._save_in_progress = True
        dialog.session = MagicMock()

        dialog._save_pdf()

        dialog.session.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
