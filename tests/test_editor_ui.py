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

    def test_review_ink_clear_for_card_switch_preserves_pen_mode(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)
        self.canvas._ink_strokes = [[QColor("#FF4444"), QPointF(1, 1), QPointF(2, 2)]]
        self.canvas._ink_current = [QColor("#FF4444"), QPointF(3, 3), QPointF(4, 4)]
        self.canvas._ink_pending_mask_idx = 0
        self.canvas._ink_input_kind = "tablet"

        self.canvas.clear_review_ink_for_card_switch()

        self.assertTrue(self.canvas._ink_active)
        self.assertEqual(self.canvas._ink_strokes, [])
        self.assertEqual(self.canvas._ink_current, [])
        self.assertEqual(self.canvas._ink_pending_mask_idx, -1)
        self.assertIsNone(self.canvas._ink_input_kind)

    def test_ink_release_commits_same_points_without_mutating_geometry(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)
        points = [QPointF(10, 10), QPointF(20, 20), QPointF(30, 20)]
        self.canvas._ink_current = [QColor("#FF4444"), *points]
        self.canvas._ink_input_kind = "tablet"

        self.canvas._ink_release()

        committed = self.canvas._ink_strokes[0][1:]
        self.assertEqual([(p.x(), p.y()) for p in committed], [(p.x(), p.y()) for p in points])
        self.assertEqual(self.canvas._ink_current, [])
        self.assertIsNone(self.canvas._ink_input_kind)

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

    def test_review_mode_synthesized_mouse_fallback_tap_on_mask_reveals(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": False}
        ])
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)
        self.canvas._last_tablet_event_time = 0.0

        class _StylusLikeMouseEvent:
            def __init__(self, pos):
                self._pos = QPointF(pos)
                self.accepted = False
                self.ignored = False

            def button(self):
                return Qt.LeftButton

            def pos(self):
                return self._pos

            def modifiers(self):
                return Qt.NoModifier

            def source(self):
                return Qt.MouseEventSynthesizedBySystem

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        press = _StylusLikeMouseEvent(QPointF(5, 5))
        release = _StylusLikeMouseEvent(QPointF(5, 5))

        self.canvas.mousePressEvent(press)
        self.canvas.mouseReleaseEvent(release)

        self.assertEqual(self.canvas._ink_current, [])
        self.assertEqual(len(self.canvas._ink_strokes), 0)
        self.assertTrue(self.canvas._boxes[0]["revealed"])
        self.assertTrue(press.accepted)
        self.assertTrue(release.accepted)

    def test_review_mode_synthesized_mouse_fallback_drag_on_mask_starts_ink(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_boxes_with_state([
            {"rect": [0, 0, 20, 20], "label": "", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a", "revealed": False}
        ])
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)
        self.canvas._last_tablet_event_time = 0.0

        class _StylusLikeMouseEvent:
            def __init__(self, pos):
                self._pos = QPointF(pos)
                self.accepted = False
                self.ignored = False

            def button(self):
                return Qt.LeftButton

            def pos(self):
                return self._pos

            def modifiers(self):
                return Qt.NoModifier

            def source(self):
                return Qt.MouseEventSynthesizedBySystem

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        press = _StylusLikeMouseEvent(QPointF(5, 5))
        move = _StylusLikeMouseEvent(QPointF(30, 30))
        release = _StylusLikeMouseEvent(QPointF(30, 30))

        self.canvas.mousePressEvent(press)
        self.canvas.mouseMoveEvent(move)
        self.canvas.mouseReleaseEvent(release)

        self.assertEqual(self.canvas._ink_current, [])
        self.assertFalse(self.canvas._boxes[0]["revealed"])
        self.assertEqual(len(self.canvas._ink_strokes), 1)
        self.assertTrue(press.accepted)
        self.assertTrue(move.accepted)
        self.assertTrue(release.accepted)

    def test_review_mode_tablet_events_draw_with_light_pressure(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)

        class _TabletEvent:
            def __init__(self, event_type, pos, pressure=0.05):
                self._type = event_type
                self._pos = QPointF(pos)
                self._pressure = pressure
                self.accepted = False
                self.ignored = False

            def type(self):
                return self._type

            def posF(self):
                return self._pos

            def pressure(self):
                return self._pressure

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        press = _TabletEvent(QEvent.TabletPress, QPointF(5, 5), pressure=0.02)
        move = _TabletEvent(QEvent.TabletMove, QPointF(20, 20), pressure=0.03)
        release = _TabletEvent(QEvent.TabletRelease, QPointF(20, 20), pressure=0.0)

        self.canvas.tabletEvent(press)
        self.canvas.tabletEvent(move)
        self.canvas.tabletEvent(release)

        self.assertEqual(self.canvas._ink_current, [])
        self.assertEqual(len(self.canvas._ink_strokes), 1)
        self.assertTrue(press.accepted)
        self.assertTrue(move.accepted)
        self.assertTrue(release.accepted)

    def test_review_mode_tablet_events_suppress_duplicate_synthesized_mouse(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)

        class _TabletEvent:
            def __init__(self, event_type, pos, pressure=0.05):
                self._type = event_type
                self._pos = QPointF(pos)
                self._pressure = pressure
                self.accepted = False

            def type(self):
                return self._type

            def posF(self):
                return self._pos

            def pressure(self):
                return self._pressure

            def accept(self):
                self.accepted = True

            def ignore(self):
                pass

        class _StylusLikeMouseEvent:
            def __init__(self, event_type, pos, button=Qt.NoButton):
                self._type = event_type
                self._pos = QPointF(pos)
                self._button = button
                self.accepted = False

            def type(self):
                return self._type

            def button(self):
                return self._button

            def pos(self):
                return self._pos

            def modifiers(self):
                return Qt.NoModifier

            def source(self):
                return Qt.MouseEventSynthesizedBySystem

            def accept(self):
                self.accepted = True

            def ignore(self):
                pass

        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletPress, QPointF(5, 5)))
        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletMove, QPointF(20, 20)))
        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletRelease, QPointF(20, 20)))

        press = _StylusLikeMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.LeftButton)
        move = _StylusLikeMouseEvent(QEvent.MouseMove, QPointF(25, 25))
        release = _StylusLikeMouseEvent(QEvent.MouseButtonRelease, QPointF(25, 25), Qt.LeftButton)

        self.canvas.mousePressEvent(press)
        self.canvas.mouseMoveEvent(move)
        self.canvas.mouseReleaseEvent(release)

        self.assertEqual(len(self.canvas._ink_strokes), 1)
        self.assertTrue(press.accepted)
        self.assertTrue(move.accepted)
        self.assertTrue(release.accepted)

    def test_review_mode_tablet_events_suppress_plain_mouse_echo(self):
        self.canvas._debug_page_num = False
        self.canvas.load_pixmap(self._pixmap(100, 100))
        self.canvas.set_mode("review")
        self.canvas.ink_set_active(True)

        class _TabletEvent:
            def __init__(self, event_type, pos, pressure=0.05):
                self._type = event_type
                self._pos = QPointF(pos)
                self._pressure = pressure

            def type(self):
                return self._type

            def posF(self):
                return self._pos

            def pressure(self):
                return self._pressure

            def accept(self):
                pass

            def ignore(self):
                pass

        class _PlainMouseEvent:
            def __init__(self, event_type, pos, button=Qt.NoButton):
                self._type = event_type
                self._pos = QPointF(pos)
                self._button = button
                self.accepted = False

            def type(self):
                return self._type

            def button(self):
                return self._button

            def pos(self):
                return self._pos

            def modifiers(self):
                return Qt.NoModifier

            def source(self):
                return getattr(Qt, "MouseEventNotSynthesized", None)

            def accept(self):
                self.accepted = True

            def ignore(self):
                pass

        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletPress, QPointF(5, 5)))
        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletMove, QPointF(12, 16)))
        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletMove, QPointF(20, 20)))
        self.canvas.tabletEvent(_TabletEvent(QEvent.TabletRelease, QPointF(20, 20)))

        press = _PlainMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.LeftButton)
        move = _PlainMouseEvent(QEvent.MouseMove, QPointF(30, 30))
        release = _PlainMouseEvent(QEvent.MouseButtonRelease, QPointF(30, 30), Qt.LeftButton)

        self.canvas.mousePressEvent(press)
        self.canvas.mouseMoveEvent(move)
        self.canvas.mouseReleaseEvent(release)

        self.assertEqual(len(self.canvas._ink_strokes), 1)
        committed = self.canvas._ink_strokes[0][1:]
        self.assertEqual([(p.x(), p.y()) for p in committed], [(5.0, 5.0), (12.0, 16.0), (20.0, 20.0)])
        self.assertTrue(press.accepted)
        self.assertTrue(move.accepted)
        self.assertTrue(release.accepted)

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

    def test_apply_initial_view_position_uses_current_canvas_scale_for_img_y(self):
        self.dialog._initial_img_y = 240.0
        self.dialog.canvas._scale = 0.5
        self.dialog._sc.verticalScrollBar().setRange(0, 1000)

        applied = self.dialog._apply_initial_view_position("test_scale_restore")

        self.assertTrue(applied)
        self.assertEqual(self.dialog._sc.verticalScrollBar().value(), 120)
        self.assertEqual(self.dialog._initial_img_y, 240.0)

    def test_schedule_initial_view_restore_final_pass_consumes_initial_img_y(self):
        calls = []
        self.dialog._initial_img_y = 180.0
        self.dialog.canvas._scale = 1.25
        self.dialog._sc.verticalScrollBar().setRange(0, 1000)

        with patch("ui.editor_dialog.QTimer.singleShot", side_effect=lambda delay, fn: (calls.append(delay), fn())):
            self.dialog._schedule_initial_view_restore("review_handoff", delays_ms=(0, 25, 50))

        self.assertEqual(calls, [0, 25, 50])
        self.assertEqual(self.dialog._sc.verticalScrollBar().value(), 225)
        self.assertIsNone(self.dialog._initial_img_y)


if __name__ == "__main__":
    unittest.main()
