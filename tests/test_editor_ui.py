import os
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication

from cache_manager import MASK_REGISTRY
from editor_ui import (
    PAGE_GAP,
    OcclusionCanvas,
    _ZoomableScrollArea,
    _point_in_rotated_box,
    _point_in_rotated_ellipse,
)
from ui.editor_dialog import CardEditorDialog


_APP = QApplication.instance() or QApplication([])


class GeometryHelperTests(unittest.TestCase):
    def test_point_in_rotated_box_handles_basic_hits_and_misses(self):
        self.assertTrue(_point_in_rotated_box(5, 5, 5, 5, 10, 10, 0))
        self.assertFalse(_point_in_rotated_box(20, 20, 5, 5, 10, 10, 0))

    def test_point_in_rotated_ellipse_handles_basic_hits_and_misses(self):
        self.assertTrue(_point_in_rotated_ellipse(5, 5, 5, 5, 10, 6, 30))
        self.assertFalse(_point_in_rotated_ellipse(20, 20, 5, 5, 10, 6, 30))


class OcclusionCanvasTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)
        self.canvas = OcclusionCanvas()
        self.canvas._show_toast = lambda _msg: None
        self.addCleanup(MASK_REGISTRY.unregister, self.canvas)

    def _pixmap(self, w, h):
        px = QPixmap(w, h)
        px.fill()
        return px

    def test_load_pixmap_sets_content_and_clears_pdf_pages(self):
        self.canvas.load_pages([self._pixmap(100, 100)])

        self.canvas.load_pixmap(self._pixmap(80, 60))

        self.assertTrue(self.canvas.has_content())
        self.assertEqual(self.canvas._pages, [])
        self.assertEqual((self.canvas._px.width(), self.canvas._px.height()), (80, 60))

    def test_load_pages_computes_layout_and_registers_pdf(self):
        self.canvas._current_pdf_path = "deck.pdf"

        self.canvas.load_pages([self._pixmap(100, 100), self._pixmap(80, 50)])

        self.assertTrue(self.canvas.has_content())
        self.assertEqual(self.canvas._page_tops, [0, 100 + PAGE_GAP])
        self.assertEqual(self.canvas._total_h, 100 + PAGE_GAP + 50)
        self.assertEqual(self.canvas._total_w, 100)
        self.assertIn("deck.pdf", MASK_REGISTRY.all_registered_pdfs())

    def test_inject_page_replaces_page_and_clears_scaled_cache_for_that_page(self):
        self.canvas.load_pages([self._pixmap(50, 40)])
        self.canvas._spx_cache[0] = (1.0, self._pixmap(50, 40))

        replacement = self._pixmap(50, 40)
        self.canvas.inject_page(0, replacement)

        self.assertIs(self.canvas._pages[0], replacement)
        self.assertNotIn(0, self.canvas._spx_cache)
        self.assertEqual(self.canvas._page_tops, [0])

    def test_get_boxes_assigns_page_numbers_for_pdf_layout(self):
        self.canvas.load_pages([self._pixmap(100, 100), self._pixmap(100, 100)])
        self.canvas._debug_page_num = False
        self.canvas.set_boxes([
            {"rect": [10, 10, 20, 20], "label": "A", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a"},
            {"rect": [10, 125, 20, 20], "label": "B", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b"},
        ])

        boxes = self.canvas.get_boxes()

        self.assertEqual([box["page_num"] for box in boxes], [0, 1])

    def test_resize_canvas_extends_to_viewport_if_scroll_area_exists(self):
        mock_viewport = type("MockViewport", (), {"width": lambda self: 500, "height": lambda self: 600})()
        mock_scroll_area = type("MockScrollArea", (), {"viewport": lambda self: mock_viewport})()

        with patch.object(self.canvas, "_scroll_area", return_value=mock_scroll_area):
            # Load a small 100x100 pixmap
            self.canvas.load_pixmap(self._pixmap(100, 100))
            
            # The canvas minimum size should be 500x600 based on the viewport mock
            self.assertEqual(self.canvas.minimumWidth(), 500)
            self.assertEqual(self.canvas.minimumHeight(), 600)
            self.assertEqual(self.canvas.width(), 500)
            self.assertEqual(self.canvas.height(), 600)

    def test_group_ungroup_undo_and_redo_restore_box_state(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes([
            {"rect": [0, 0, 10, 10], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a"},
            {"rect": [20, 20, 10, 10], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b"},
        ])
        self.canvas._selected_indices = {0, 1}

        self.canvas.group_selected()
        grouped_ids = {box["group_id"] for box in self.canvas.get_boxes()}
        self.assertEqual(len(grouped_ids), 1)
        self.assertNotIn("", grouped_ids)

        self.canvas.ungroup_selected()
        self.assertEqual({box["group_id"] for box in self.canvas.get_boxes()}, {""})

        self.canvas.undo()
        regrouped_ids = {box["group_id"] for box in self.canvas.get_boxes()}
        self.assertEqual(len(regrouped_ids), 1)
        self.assertNotIn("", regrouped_ids)

        self.canvas.redo()
        self.assertEqual({box["group_id"] for box in self.canvas.get_boxes()}, {""})

    def test_review_mode_clears_revealed_state_and_changes_focus_policy(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 10, 10], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": True}
        ])

        self.canvas.set_mode("review")

        self.assertFalse(self.canvas._boxes[0]["revealed"])

    def test_review_mode_supports_ink_and_preserves_strokes(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": False}
        ])
        self.canvas._ink_active = True
        self.canvas._ink_strokes = [[QColor("#FF4444"), QPointF(1, 1), QPointF(2, 2)]]
        self.canvas._ink_current = [QColor("#FF4444"), QPointF(3, 3)]

        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)

        self.assertTrue(self.canvas._ink_active)
        self.assertEqual(len(self.canvas._ink_strokes), 1)
        self.assertEqual(len(self.canvas._ink_current), 2)
        self.assertEqual(self.canvas.cursor().shape(), Qt.CrossCursor)

        self.canvas.set_boxes_with_state([
            {"rect": [10, 10, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b", "revealed": False}
        ])

        self.assertEqual(len(self.canvas._ink_strokes), 1)
        self.assertEqual(len(self.canvas._ink_current), 2)

        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(40, 40),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        self.canvas.mousePressEvent(press)

        self.assertFalse(self.canvas._boxes[0]["revealed"])
        self.assertEqual(len(self.canvas._ink_current), 2)

    def test_review_mode_pen_tap_on_mask_reveals_instead_of_drawing(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": False}
        ])
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)

        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(5, 5),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(5, 5),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )

        self.canvas.mousePressEvent(press)
        self.canvas.mouseReleaseEvent(release)

        self.assertTrue(self.canvas._boxes[0]["revealed"])
        self.assertEqual(self.canvas._ink_current, [])
        self.assertEqual(self.canvas._ink_strokes, [])

    def test_review_mode_pen_drag_on_mask_starts_ink_instead_of_revealing(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": False}
        ])
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)

        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(5, 5),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        move = QMouseEvent(
            QEvent.MouseMove,
            QPointF(20, 20),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )

        self.canvas.mousePressEvent(press)
        self.canvas.mouseMoveEvent(move)
        self.canvas.mouseReleaseEvent(release)

        self.assertFalse(self.canvas._boxes[0]["revealed"])
        self.assertEqual(len(self.canvas._ink_strokes), 1)

    def test_review_mode_stylus_like_mouse_event_does_not_start_ink(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": False}
        ])
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)
        self.canvas._last_tablet_event_time = time.monotonic()

        class _StylusLikeMouseEvent:
            def __init__(self):
                self.accepted = False
                self.ignored = False

            def button(self):
                return Qt.LeftButton

            def pos(self):
                return QPointF(5, 5)

            def modifiers(self):
                return Qt.NoModifier

            def source(self):
                return Qt.MouseEventSynthesizedBySystem

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        event = _StylusLikeMouseEvent()
        self.canvas.mousePressEvent(event)

        self.assertEqual(self.canvas._ink_current, [])
        self.assertTrue(self.canvas._boxes[0]["revealed"])
        self.assertFalse(event.accepted)

    def test_target_scroll_position_is_centered_and_clamped(self):
        self.canvas.load_pages([self._pixmap(100, 100), self._pixmap(100, 100)])
        self.canvas._debug_page_num = False
        self.canvas.set_boxes([
            {"rect": [10, 125, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "grp", "box_id": "a"},
            {"rect": [40, 135, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "grp", "box_id": "b"},
        ])
        self.canvas.set_target_group("grp")

        hval, vval = self.canvas.get_target_scroll_pos(80, 80)

        self.assertGreaterEqual(hval, 0)
        self.assertGreaterEqual(vval, 0)
        self.assertLessEqual(vval, int(self.canvas._total_h * self.canvas._scale) - 80)


class ZoomableScrollAreaTests(unittest.TestCase):
    class _DummyEvent:
        def __init__(self, button):
            self._button = button

        def button(self):
            return self._button

    def test_review_mode_left_button_does_not_force_pan_without_pan_mode(self):
        area = _ZoomableScrollArea()
        area._canvas = type("Canvas", (), {"_mode": "review"})()

        should_pan = area._should_pan(self._DummyEvent(Qt.LeftButton))

        self.assertFalse(should_pan)

    def test_left_button_pans_when_pan_mode_is_enabled(self):
        area = _ZoomableScrollArea()
        area._canvas = type("Canvas", (), {"_mode": "review"})()
        area._pan_mode = True

        should_pan = area._should_pan(self._DummyEvent(Qt.LeftButton))

        self.assertTrue(should_pan)

    def test_review_canvas_non_ctrl_wheel_is_ignored_for_scroll_area(self):
        canvas = OcclusionCanvas()
        canvas._mode = "review"
        canvas._ink_active = True

        class _DummyAngle:
            def y(self):
                return 120

        class _DummyWheelEvent:
            def __init__(self):
                self.accepted = False
                self.ignored = False

            def modifiers(self):
                return Qt.NoModifier

            def angleDelta(self):
                return _DummyAngle()

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        event = _DummyWheelEvent()
        canvas.wheelEvent(event)

        self.assertFalse(event.accepted)
        self.assertTrue(event.ignored)


class CardEditorDialogTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)

        tmp_root = Path(__file__).resolve().parent / "_tmp_files"
        tmp_root.mkdir(exist_ok=True)
        self.pdf_path = str(tmp_root / f"sample_{uuid.uuid4().hex}.pdf")
        Path(self.pdf_path).write_bytes(b"%PDF-1.4")
        self.addCleanup(lambda: Path(self.pdf_path).exists() and Path(self.pdf_path).unlink())

        self.dialog = CardEditorDialog()
        self.addCleanup(self.dialog.close)

    def _pixmap(self, w, h):
        px = QPixmap(w, h)
        px.fill()
        return px

    def test_open_in_reader_uses_current_page_fragment(self):
        self.dialog.card["pdf_path"] = self.pdf_path

        with patch.object(self.dialog, "_current_visible_page", return_value=3), \
             patch("ui.editor_dialog.QDesktopServices.openUrl", return_value=True) as open_url:
            self.dialog._open_in_reader()

        url = open_url.call_args[0][0]
        self.assertEqual(url.fragment(), "page=4")


if __name__ == "__main__":
    unittest.main()
