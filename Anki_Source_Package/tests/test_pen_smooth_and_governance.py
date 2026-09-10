import unittest
import sys
import os
from unittest.mock import MagicMock, patch
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap, QColor, QPaintEvent, QMouseEvent
from PyQt5.QtCore import QPointF, QRect, Qt, QEvent, QObject

app = QApplication.instance() or QApplication(sys.argv)

from ui.canvas.core import OcclusionCanvas
from session_timer import SessionTimer, _ActivityEventFilter, _ACTIVITY_EVENTS
from ui.review_screen import ReviewScreen


class TestPenSmoothingAndGovernance(unittest.TestCase):
    def setUp(self):
        self.canvas = OcclusionCanvas()
        self.canvas.resize(800, 600)
        self.canvas.set_mode("review")
        px = QPixmap(800, 600)
        px.fill(QColor("#FFFFFF"))
        self.canvas.load_pages([px])

    def test_incremental_segment_and_direct_rendering(self):
        """Verify that drawing points builds live segment and renders directly with zero lag."""
        self.canvas._ink_implementation = "filtered"
        self.canvas.ink_set_active(True, mode="pen")
        
        # 1. Press
        self.canvas._ink_press(QPointF(100, 100), input_kind="mouse")
        self.assertIsNotNone(self.canvas._ink_current)
        self.assertEqual(len(self.canvas._ink_current), 2)
        
        # 2. Second point (pts_count == 2)
        self.canvas._ink_move(QPointF(105, 105))
        self.assertIsNotNone(self.canvas._ink_live_segment)
        self.assertFalse(self.canvas._ink_live_segment.isEmpty())
        
        # 3. Third and further points (pts_count >= 3)
        for i in range(10):
            pt = QPointF(110 + i * 5, 110 + (i % 2) * 5)
            self.canvas._ink_move(pt)
            self.assertIsNotNone(self.canvas._ink_live_segment)
            # Verify paintEvent executes without errors
            clip = QRect(int(pt.x()) - 20, int(pt.y()) - 20, 40, 40)
            self.canvas.paintEvent(QPaintEvent(clip))
            
        # 4. Release
        self.canvas._ink_release()
        self.assertEqual(len(self.canvas._ink_current), 0)
        self.assertIsNone(self.canvas._ink_live_segment)
        self.assertEqual(len(self.canvas._ink_strokes), 1)

    def test_ink_stroke_lifecycle_undo_redo_and_clear(self):
        """Verify that undo, redo, and clear correctly manage ink strokes."""
        self.canvas._ink_implementation = "filtered"
        self.canvas.ink_set_active(True, mode="pen")
        
        # Draw stroke 1
        self.canvas._ink_press(QPointF(50, 50))
        self.canvas._ink_move(QPointF(60, 60))
        self.canvas._ink_move(QPointF(70, 70))
        self.canvas._ink_release()
        self.assertEqual(len(self.canvas._ink_strokes), 1)
        
        # Undo
        self.assertTrue(self.canvas.has_ink_undo())
        self.canvas.ink_undo_stroke()
        self.assertEqual(len(self.canvas._ink_strokes), 0)
        
        # Redo
        self.assertTrue(self.canvas.has_ink_redo())
        self.canvas.ink_redo_stroke()
        self.assertEqual(len(self.canvas._ink_strokes), 1)
        
        # Clear
        self.canvas.ink_clear()
        self.assertEqual(len(self.canvas._ink_strokes), 0)

    def test_session_timer_event_filter_fast_path(self):
        """Verify that _ActivityEventFilter fast-bypasses scope checks when _idle_seconds == 0."""
        parent_widget = QObject()
        stimer = SessionTimer(parent_widget)
        event_filter = _ActivityEventFilter(stimer)
        
        # Initially active: _idle_seconds is 0
        stimer._idle_seconds = 0
        
        dummy_event = QMouseEvent(QEvent.MouseMove, QPointF(10, 10), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        dummy_target = QObject()
        
        with patch.object(stimer, "_is_activity_scope") as mock_scope:
            res = event_filter.eventFilter(dummy_target, dummy_event)
            self.assertFalse(res)
            # Scope check should NOT have been called because _idle_seconds == 0!
            mock_scope.assert_not_called()
            
        # When idle: _idle_seconds > 0
        stimer._idle_seconds = 5
        with patch.object(stimer, "_is_activity_scope", return_value=True) as mock_scope:
            res = event_filter.eventFilter(dummy_target, dummy_event)
            self.assertFalse(res)
            # Scope check SHOULD have been called
            mock_scope.assert_called_once_with(dummy_target)
            self.assertEqual(stimer._idle_seconds, 0)

    def test_timer_governance_during_inking(self):
        """Verify that ReviewScreen pauses background timers when pen mode activates."""
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = self.canvas
        screen._data = {"theme": "retro"}
        screen._prog_timer = MagicMock()
        screen._prog_timer.isActive.return_value = True
        screen._proximity_timer = MagicMock()
        screen._proximity_timer.isActive.return_value = True
        
        # Activating pen: timers should stop
        self.canvas._ink_active = True
        screen._on_ink_active_changed()
        screen._prog_timer.stop.assert_called_once()
        screen._proximity_timer.stop.assert_called_once()
        
        # Deactivating pen: timers should restart
        screen._prog_timer.isActive.return_value = False
        screen._proximity_timer.isActive.return_value = False
        self.canvas._ink_active = False
        with patch("theme_manager.is_retro_theme", return_value=True), patch("ui.canvas.retro_effects._home_animations_enabled", return_value=True):
            screen._on_ink_active_changed()
        screen._prog_timer.start.assert_called_once_with(40)
        screen._proximity_timer.start.assert_called_once()

    def test_on_page_ready_defers_during_stroke(self):
        """Verify that _on_page_ready queues page injection into _bg_pending_inserts if mid-stroke."""
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = self.canvas
        screen._canvas_pdf_path = "test.pdf"
        screen._ondemand_path = "test.pdf"
        screen._ondemand_kind = "visible"
        screen._bg_pending_inserts = {}
        screen._update_review_page_nav_ui = MagicMock()
        screen._debug_review_lazy_page_loaded = MagicMock()
        screen._debug_review_page_injection = MagicMock()
        
        pixmap = QPixmap(100, 100)
        
        # Mid-stroke: canvas._ink_current has >= 2 elements
        self.canvas._ink_current = [QColor("#FF0000"), QPointF(10, 10), QPointF(20, 20)]
        
        with patch.object(self.canvas, "inject_page") as mock_inject:
            screen._on_page_ready(2, pixmap)
            # Should NOT inject directly during stroke
            mock_inject.assert_not_called()
            # Should be in pending inserts
            self.assertIn(2, screen._bg_pending_inserts)
            self.assertIs(screen._bg_pending_inserts[2], pixmap)

    def test_review_undo_when_mgr_cleared_on_sequential_undo(self):
        """Verify that when sequential undo closes the current screen and clears self.mgr, no AttributeError occurs."""
        with patch.object(ReviewScreen, "_setup_ui"), patch.object(ReviewScreen, "_load_item"):
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = self.canvas
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            screen.__init__([])

            mock_mgr = MagicMock()
            def simulate_sequential_undo():
                screen.mgr = None
                screen._closed = True
                
            mock_mgr._review_undo.side_effect = simulate_sequential_undo
            screen.mgr = mock_mgr
            screen.get_active_tool = MagicMock(return_value="pen")
            screen.set_active_tool = MagicMock()
            
            # Calling _review_undo should cleanly handle mgr being cleared without raising AttributeError
            screen._review_undo()
            mock_mgr._review_undo.assert_called_once()
            screen.set_active_tool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
