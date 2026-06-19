import os
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication


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


    def test_inject_page_replaces_page_and_refreshes_same_size_scaled_cache(self):
        self.canvas.load_pages([self._pixmap(50, 40)])
        self.canvas._spx_cache[0] = (1.0, Qt.SmoothTransformation, self._pixmap(50, 40))

        replacement = self._pixmap(50, 40)
        self.canvas.inject_page(0, replacement)

        self.assertIs(self.canvas._pages[0], replacement)
        self.assertIn(0, self.canvas._spx_cache)

    def test_inject_page_clears_scaled_cache_when_dimensions_change(self):
        self.canvas.load_pages([self._pixmap(50, 40)])
        self.canvas._spx_cache[0] = (1.0, Qt.SmoothTransformation, self._pixmap(50, 40))

        self.canvas.inject_page(0, self._pixmap(60, 40))

        self.assertNotIn(0, self.canvas._spx_cache)

    def test_load_pages_clears_scaled_cache_when_dimensions_change(self):
        self.canvas.set_mode("review")
        self.canvas._current_pdf_path = "deck.pdf"
        self.canvas.load_pages([self._pixmap(50, 40)])
        self.canvas._spx_cache[0] = (1.0, Qt.SmoothTransformation, self._pixmap(50, 40))

        self.canvas.load_pages([self._pixmap(60, 50)])

        self.assertEqual(self.canvas._spx_cache, {})

    def test_load_pages_preserves_scaled_cache_for_same_pdf_and_dimensions(self):
        self.canvas.set_mode("review")
        self.canvas._current_pdf_path = "deck.pdf"
        self.canvas.load_pages([self._pixmap(50, 40)])
        self.canvas._spx_cache[0] = (1.0, Qt.SmoothTransformation, self._pixmap(50, 40))
        self.canvas._spx_cache_pdf_path = "deck.pdf"

        self.canvas.load_pages([self._pixmap(50, 40)])

        self.assertIn(0, self.canvas._spx_cache)

    def test_inject_page_refreshes_scaled_cache_entry(self):
        self.canvas.set_mode("review")
        self.canvas._current_pdf_path = "deck.pdf"
        self.canvas.load_pages([self._pixmap(50, 40)])
        self.canvas._spx_cache[0] = (1.0, Qt.SmoothTransformation, self._pixmap(50, 40))

        self.canvas.inject_page(0, self._pixmap(50, 40))

        self.assertIn(0, self.canvas._spx_cache)

    def test_get_scaled_page_populates_scaled_cache_on_miss(self):
        self.canvas.set_mode("review")
        self.canvas.load_pages([self._pixmap(50, 40)])

        scaled = self.canvas._get_scaled_page(0)

        self.assertFalse(scaled.isNull())
        self.assertIn(0, self.canvas._spx_cache)

    def test_spx_cache_lru_eviction(self):
        self.canvas.set_mode("review")
        self.canvas.load_pages([self._pixmap(50, 40)] * 30)
        
        # Populate cache up to the limit (24 entries)
        for i in range(24):
            self.canvas._get_scaled_page(i)
        
        self.assertEqual(len(self.canvas._spx_cache), 24)
        
        # Access page 0 to make it most recently used
        self.canvas._get_scaled_page(0)
        
        # Access page 24, which will cause eviction of page 1 (since 0 was moved to end)
        self.canvas._get_scaled_page(24)
        
        self.assertEqual(len(self.canvas._spx_cache), 24)
        self.assertIn(0, self.canvas._spx_cache)
        self.assertIn(24, self.canvas._spx_cache)
        self.assertNotIn(1, self.canvas._spx_cache)





    def test_canvas_paint_profile_includes_phase_timings(self):
        self.canvas.set_mode("review")
        phases = {
            "scale_miss": 1,
            "page_scale_ms": 2.0,
            "page_draw_ms": 3.0,
            "mask_ms": 4.0,
            "mask_clip": "10x10@0,0",
            "boxes_ms": 5.0,
            "boxes_drawn": 2,
            "overlay_ms": 6.0,
            "ink_ms": 7.0,
        }

        with patch.dict(os.environ, {"ANKI_CANVAS_PAINT_PROFILE": "1"}, clear=False), patch(
            "builtins.print"
        ) as printed:
            self.canvas._log_canvas_paint_profile(13.0, QRect(0, 0, 100, 100), 1, phases)

        output = "\n".join(call.args[0] for call in printed.call_args_list)
        self.assertIn("[PROFILE][canvas_paint]", output)
        self.assertIn("page_draw=3.0ms", output)
        self.assertIn("mask=4.0ms", output)
        self.assertIn("ink=7.0ms", output)

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
            Qt.ControlModifier,
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(5, 5),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.ControlModifier,
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
                return Qt.ControlModifier

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

    def test_inject_page_layout_shift_updates_box_coordinates(self):
        # 1. Load initial skeleton placeholders (two 100x100 pages)
        self.canvas.load_pages([self._pixmap(100, 100), self._pixmap(100, 100)])

        # 2. Add box A on page 0 (rect: [10, 50, 20, 20])
        # Add box B on page 1 (rect: [10, 120, 20, 20]) -> Y-center is 130, which is >= page 1 top (112)
        self.canvas._debug_page_num = False
        self.canvas.set_boxes([
            {"rect": [10, 50, 20, 20], "label": "A", "shape": "rect", "angle": 0, "group_id": "", "box_id": "a"},
            {"rect": [10, 120, 20, 20], "label": "B", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b"},
        ])

        # 3. Inject a new pixmap for page 0 with size 100x120 (height shifted from 100 to 120)
        new_page_0 = self._pixmap(100, 120)
        self.canvas.inject_page(0, new_page_0)

        boxes = self.canvas.get_boxes()
        self.assertEqual(len(boxes), 2)

        # Box A: on page 0. Height scaled by 120/100 = 1.2
        # Y should be 50 * 1.2 = 60.0
        # Height should be 20 * 1.2 = 24.0
        self.assertAlmostEqual(boxes[0]["rect"][1], 60.0)
        self.assertAlmostEqual(boxes[0]["rect"][3], 24.0)

        # Box B: on page 1. Page 1 top shifted from 112 to 132 (+20px).
        # Box local Y was 120 - 112 = 8. It should remain 8.
        # New Y should be 132 + 8 = 140.0. Width and height should be unchanged.
        self.assertAlmostEqual(boxes[1]["rect"][1], 140.0)
        self.assertAlmostEqual(boxes[1]["rect"][3], 20.0)



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
        canvas._smooth_timer = SimpleNamespace(start=MagicMock())

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
        canvas._smooth_timer.start.assert_not_called()


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

    def test_l_key_copies_current_pdf_file_in_editor(self):
        with patch.object(self.dialog, "_copy_current_pdf_file_to_clipboard") as copy_pdf:
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_L, Qt.NoModifier)
            self.dialog.keyPressEvent(event)

        copy_pdf.assert_called_once_with()

    def test_ctrl_l_reveals_current_pdf_folder_in_editor(self):
        with patch.object(self.dialog, "_reveal_current_pdf_in_folder") as reveal_pdf:
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_L, Qt.ControlModifier)
            self.dialog.keyPressEvent(event)

        reveal_pdf.assert_called_once_with()

    def test_editor_copy_pdf_file_places_file_url_on_clipboard(self):
        self.dialog.card["pdf_path"] = self.pdf_path
        fake_clipboard = MagicMock()

        with patch("ui.editor_dialog.QApplication.clipboard", return_value=fake_clipboard):
            self.dialog._copy_current_pdf_file_to_clipboard()

        mime = fake_clipboard.setMimeData.call_args.args[0]
        self.assertEqual(
            [os.path.normpath(url.toLocalFile()) for url in mime.urls()],
            [os.path.normpath(self.pdf_path)],
        )
        self.assertEqual(self.dialog.lbl_sync.text(), "Copied PDF file")

    def test_editor_hint_label_mentions_pdf_shortcuts(self):
        hint_text = self.dialog._hint_label.text()

        self.assertIn("L=copy PDF", hint_text)
        self.assertIn("Ctrl+L=open folder", hint_text)

    def test_editor_recovery_draft_includes_current_boxes_and_metadata(self):
        self.dialog.card["pdf_path"] = "pdfs/sample.pdf"
        self.dialog.inp_title.setText("Recovered PDF")
        self.dialog.canvas.set_boxes(
            [{"rect": [1, 2, 30, 40], "label": "m1", "box_id": "box-1"}]
        )

        with patch("ui.editor_dialog.recovery_manager.save_editor_draft") as save_draft:
            save_draft.side_effect = lambda payload: payload
            self.dialog._write_recovery_draft()

        payload = save_draft.call_args.args[0]
        self.assertEqual(payload["mode"], "add")
        self.assertEqual(payload["card"]["title"], "Recovered PDF")
        self.assertEqual(payload["card"]["pdf_path"], "pdfs/sample.pdf")
        self.assertEqual(payload["card"]["boxes"][0]["box_id"], "box-1")
        self.dialog._recovery_draft_cleared = True

    def test_editor_recovery_draft_skips_unchanged_duplicate_write(self):
        self.dialog.card["pdf_path"] = "pdfs/sample.pdf"
        self.dialog.inp_title.setText("Recovered PDF")
        self.dialog.canvas.set_boxes(
            [{"rect": [1, 2, 30, 40], "label": "m1", "box_id": "box-1"}]
        )

        with patch("ui.editor_dialog.recovery_manager.save_editor_draft") as save_draft, patch(
            "builtins.print"
        ) as printed:
            save_draft.side_effect = lambda payload: payload
            first = self.dialog._write_recovery_draft()
            second = self.dialog._write_recovery_draft()

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        save_draft.assert_called_once()
        output = "\n".join(call.args[0] for call in printed.call_args_list)
        self.assertIn("[DEBUG][recovery] editor_draft_skipped reason=unchanged", output)
        self.dialog._recovery_draft_cleared = True

    def test_editor_recovery_created_timestamp_is_stable_for_new_card(self):
        self.dialog.card["pdf_path"] = "pdfs/sample.pdf"

        first = self.dialog._current_recovery_card()["created"]
        second = self.dialog._current_recovery_card()["created"]

        self.assertEqual(first, second)

    def test_editor_box_changes_debounce_recovery_draft_writes(self):
        with patch.object(self.dialog, "_schedule_recovery_draft") as schedule_draft, \
             patch.object(self.dialog, "_write_recovery_checkpoint") as write_checkpoint:
            self.dialog.canvas.boxes_changed.emit([])

        schedule_draft.assert_called_once_with("boxes")
        write_checkpoint.assert_not_called()

    def test_editor_clear_recovery_draft_deletes_record(self):
        with patch("ui.editor_dialog.recovery_manager.delete_editor_draft") as delete_draft:
            self.dialog.clear_recovery_draft()

        delete_draft.assert_called_once_with(self.dialog._recovery_draft_id)
        self.assertTrue(self.dialog._recovery_draft_cleared)

    def test_open_annotation_beta_passes_image_space_anchor_y(self):
        self.dialog.card["pdf_path"] = self.pdf_path
        self.dialog.canvas._scale = 1.25
        bar = MagicMock()
        bar.value.return_value = 250
        self.dialog._sc = MagicMock()
        self.dialog._sc.verticalScrollBar.return_value = bar

        with patch.object(self.dialog, "_current_visible_page", return_value=3), \
             patch("ui.editor_dialog.PdfAnnotationDialog") as dialog_cls:
            dialog_instance = MagicMock()
            dialog_instance._saved_pages = []
            dialog_instance.return_page = None
            dialog_instance.return_anchor_y = None
            dialog_cls.return_value = dialog_instance

            self.dialog._open_annotation_beta()

        self.assertEqual(dialog_cls.call_args.kwargs["initial_page"], 3)
        self.assertAlmostEqual(dialog_cls.call_args.kwargs["initial_anchor_y"], 200.0)

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

    def test_exec_opens_editor_in_fullscreen_by_default(self):
        with patch.object(self.dialog, "showFullScreen") as show_fullscreen, \
             patch("ui.editor_dialog.QDialog.exec_", return_value=321) as qdialog_exec, \
             patch("builtins.print") as fake_print:
            result = self.dialog.exec_()

        show_fullscreen.assert_called_once_with()
        qdialog_exec.assert_called_once_with()
        fake_print.assert_any_call("[DEBUG][editor_mode] enter_fullscreen_default")
        self.assertEqual(result, 321)

    def test_recovery_draft_keeps_original_draft_identity(self):
        dialog = CardEditorDialog(
            card={"title": "Recovered Draft", "boxes": []},
            recovery_draft={
                "draft_id": "draft-123",
                "mode": "add",
                "card": {"title": "Recovered Draft"},
            },
        )
        self.addCleanup(dialog.close)

        self.assertTrue(dialog._opened_from_recovery)
        self.assertEqual(dialog._recovery_draft_id, "draft-123")
        self.assertEqual(dialog._recovery_mode, "add")
        self.assertIn("Restoring recovered draft", dialog.windowTitle())
        self.assertIn("Restoring recovered draft", dialog._hint_label.text())

    def test_load_pdf_direct_uses_skeleton_and_wires_ondemand(self):
        pages = [self._pixmap(50, 60), self._pixmap(50, 60), self._pixmap(50, 60)]
        skeleton = SimpleNamespace(placeholders=pages, page_dims=[], error=None)

        with patch("ui.editor_dialog.get_pdf_page_count", return_value=3), \
             patch("ui.editor_dialog.choose_pdf_render_zoom", return_value=2.0), \
             patch("ui.editor_dialog.ensure_pdf_cache_profile", return_value=False), \
             patch("ui.editor_dialog.load_pdf_skeleton", return_value=skeleton), \
             patch("ui.editor_dialog.QTimer.singleShot", side_effect=lambda delay, fn: None) as single_shot, \
             patch.object(self.dialog, "_wire_editor_scroll_ondemand") as wire_ondemand, \
             patch("builtins.print") as fake_print:
            self.dialog._load_pdf_direct(self.pdf_path)

        self.assertEqual(len(self.dialog.canvas._pages), 3)
        wire_ondemand.assert_called_once_with(self.pdf_path, 3)
        single_shot.assert_called()
        self.assertEqual(self.dialog.lbl_sync.text(), "⏳ PDF ready on demand")
        printed = "\n".join(call.args[0] for call in fake_print.call_args_list)
        self.assertIn("[DEBUG][editor_cache_profile]", printed)
        self.assertIn("[DEBUG][editor_skeleton] ready", printed)
        self.assertIn("[DEBUG][editor_load] finish", printed)

    def test_editor_pages_needing_render_logs_skip_counts(self):
        self.dialog._editor_canvas_real_pages = {1}
        self.dialog._editor_render_inflight_pages = {2}
        self.dialog._editor_pending_visible_request = (self.pdf_path, [3])
        cached = self._pixmap(40, 50)

        def fake_cache_get(_path, page_num, *args, **kwargs):
            return cached if page_num == 4 else None

        with patch.dict(os.environ, {"ANKI_EDITOR_VERBOSE": "1"}, clear=False), \
             patch("ui.editor_dialog.PAGE_CACHE.get", side_effect=fake_cache_get), \
             patch("builtins.print") as fake_print:
            needed = self.dialog._editor_pages_needing_render(
                self.pdf_path, [0, 1, 2, 3, 4], context="visible"
            )

        self.assertEqual(needed, [0])
        debug_line = fake_print.call_args.args[0]
        self.assertIn("[DEBUG][editor_decision]", debug_line)
        self.assertIn("need=p.1", debug_line)
        self.assertIn("skip_canvas=1", debug_line)
        self.assertIn("skip_cache=1", debug_line)
        self.assertIn("skip_inflight=1", debug_line)
        self.assertIn("skip_pending=1", debug_line)

    def test_editor_pages_needing_render_quiet_without_verbose_debug(self):
        self.dialog._editor_canvas_real_pages = set()
        self.dialog._editor_render_inflight_pages = set()
        self.dialog._editor_pending_visible_request = None

        with patch.dict(os.environ, {"ANKI_EDITOR_VERBOSE": ""}, clear=False), \
             patch("ui.editor_dialog.PAGE_CACHE.get", return_value=None), \
             patch("builtins.print") as fake_print:
            needed = self.dialog._editor_pages_needing_render(
                self.pdf_path, [0], context="visible"
            )

        self.assertEqual(needed, [0])
        fake_print.assert_not_called()

    def test_editor_ondemand_requested_pages_are_tracked_per_thread(self):
        old_thread = MagicMock()
        old_thread.isRunning.return_value = False
        current_thread = MagicMock()
        current_thread.isRunning.return_value = False
        self.dialog._pdf_ondemand_thread = current_thread
        self.dialog._editor_ondemand_requested_pages = {3}
        self.dialog._editor_ondemand_request_pages_by_thread = {
            id(old_thread): {1},
            id(current_thread): {2},
        }

        old_requested = self.dialog._editor_requested_pages_for_thread(old_thread)
        current_requested = self.dialog._editor_requested_pages_for_thread(current_thread)

        self.assertEqual(old_requested, {1})
        self.assertEqual(current_requested, {2, 3})

    def test_stale_editor_ondemand_batch_does_not_consume_current_pending(self):
        old_thread = MagicMock()
        old_thread.isRunning.return_value = False
        current_thread = MagicMock()
        current_thread.isRunning.return_value = False
        self.dialog._pdf_ondemand_thread = current_thread
        self.dialog._editor_ondemand_request_pages_by_thread = {id(old_thread): {0}}
        self.dialog._editor_ondemand_requested_pages = {1}
        self.dialog._editor_render_inflight_pages = {0, 1}
        self.dialog._editor_pending_visible_request = (self.pdf_path, [2])
        self.dialog._start_editor_visible_page_request = MagicMock()

        self.dialog._on_editor_visible_pages_batch_done([0], thread=old_thread)

        self.assertEqual(self.dialog._editor_render_inflight_pages, {1})
        self.assertEqual(self.dialog._editor_pending_visible_request, (self.pdf_path, [2]))
        self.assertEqual(self.dialog._editor_ondemand_requested_pages, {1})
        self.assertIs(self.dialog._pdf_ondemand_thread, current_thread)
        self.dialog._start_editor_visible_page_request.assert_not_called()

    def test_editor_visible_pages_changed_injects_cache_hot_gray_pages(self):
        self.dialog._editor_ondemand_path = self.pdf_path
        self.dialog._editor_ondemand_total = 5
        self.dialog._editor_canvas_real_pages = set()
        self.dialog._editor_render_inflight_pages = set()
        self.dialog._editor_visible_debug_seen_pages = set()
        placeholder = self._pixmap(40, 50)
        self.dialog.canvas.load_pages([placeholder for _ in range(5)])
        cached = self._pixmap(40, 50)

        with patch("ui.editor_dialog.PAGE_CACHE.get", side_effect=lambda path, pn, *args, **kwargs: cached if pn == 2 else None):
            self.dialog._start_editor_visible_page_request = MagicMock()
            self.dialog._on_editor_visible_pages_changed(2, 2)

        self.assertIs(self.dialog.canvas._pages[2], cached)
        self.dialog._start_editor_visible_page_request.assert_not_called()
        self.assertIn(2, self.dialog._editor_canvas_real_pages)

    def test_editor_visible_pages_changed_requests_missing_visible_pages(self):
        self.dialog._editor_ondemand_path = self.pdf_path
        self.dialog._editor_ondemand_total = 5
        self.dialog._editor_canvas_real_pages = set()
        self.dialog._editor_render_inflight_pages = set()
        self.dialog._editor_visible_debug_seen_pages = set()
        placeholder = self._pixmap(40, 50)
        self.dialog.canvas.load_pages([placeholder for _ in range(5)])
        self.dialog._start_editor_visible_page_request = MagicMock()

        with patch("ui.editor_dialog.PAGE_CACHE.get", return_value=None):
            self.dialog._on_editor_visible_pages_changed(1, 3)

        self.dialog._start_editor_visible_page_request.assert_called_once_with(self.pdf_path, [1, 2, 3])

    def test_editor_visible_pages_changed_logs_scroll_profile(self):
        self.dialog._editor_ondemand_path = self.pdf_path
        self.dialog._editor_ondemand_total = 2
        self.dialog._editor_canvas_real_pages = {0}
        self.dialog._editor_render_inflight_pages = set()
        self.dialog._editor_pending_visible_request = None
        self.dialog._editor_visible_debug_seen_pages = set()
        self.dialog._editor_scroll_profile_last_log_ts = 0.0
        self.dialog._editor_scroll_profile_last_event_ts = None
        self.dialog.canvas.load_pages([self._pixmap(40, 50), self._pixmap(40, 50)])
        self.dialog._start_editor_visible_page_request = MagicMock()

        with patch.dict(os.environ, {"ANKI_EDITOR_SCROLL_PROFILE": "1"}, clear=False), \
             patch("ui.editor_dialog.PAGE_CACHE.get", return_value=None), \
             patch("builtins.print") as fake_print:
            self.dialog._on_editor_visible_pages_changed(0, 0)

        printed = "\n".join(call.args[0] for call in fake_print.call_args_list)
        self.assertIn("[PROFILE][editor_scroll]", printed)
        self.assertIn("visible=p.1-p.1", printed)
        self.assertIn("need=none", printed)
        self.dialog._start_editor_visible_page_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
