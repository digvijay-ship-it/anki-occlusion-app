import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import unittest
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent

from anki_occlusion_v19 import ReviewScreen

class ReviewScreenZoomTests(unittest.TestCase):
    def test_user_zoom_scale_tracked_on_canvas_zoom(self):
        # Create a blank instance without calling __init__ to avoid GUI complexities
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 1.5
        
        # Simulate the timer callback from the canvas
        screen._on_canvas_zoom_settled()
        
        # Verify the screen remembered the user zoom
        self.assertEqual(screen._user_zoom_scale, 1.5)

    def test_ctrl_zero_resets_user_zoom_scale(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 2.0
        screen._user_zoom_scale = 2.0
        screen._zoom_fit = MagicMock()
        
        # Mock attributes that keyPressEvent might touch
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        
        # Simulate Ctrl+0
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_0, Qt.ControlModifier)
        
        # Call the event handler directly
        screen.keyPressEvent(event)
            
        # Verify the user zoom was reset to auto-fit (None)
        self.assertIsNone(screen._user_zoom_scale)
        screen._zoom_fit.assert_called_once()

    def test_ctrl_plus_sets_user_zoom_scale(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 1.25 # New scale after zoom_in
        screen._user_zoom_scale = None
        
        # Mock attributes
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        
        # Simulate Ctrl+=
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Equal, Qt.ControlModifier)
        
        screen.keyPressEvent(event)
            
        # Verify the user zoom was saved
        self.assertEqual(screen._user_zoom_scale, 1.25)
        screen.canvas.zoom_in.assert_called_once()

    def test_review_pen_width_persists_separately(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._review_ink_width = 1.2
        screen.canvas = MagicMock()
        screen.canvas._ink_width = 2.6

        fake_settings = MagicMock()
        fake_settings.value.return_value = "2.6"

        with patch("ui.review_screen.QSettings", return_value=fake_settings):
            screen._capture_review_ink_width("test")
            loaded = screen._load_review_ink_width()

        self.assertAlmostEqual(screen._review_ink_width, 2.6)
        fake_settings.setValue.assert_called_with("review/ink_width", 2.6)
        self.assertAlmostEqual(loaded, 2.6)

    def test_plus_key_updates_and_saves_review_pen_width(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._ink_active = True
        screen.canvas._ink_width = 1.2
        screen._review_ink_width = 1.2
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        screen._capture_review_ink_width = ReviewScreen._capture_review_ink_width.__get__(screen, ReviewScreen)

        def adjust(delta):
            screen.canvas._ink_width += delta

        screen.canvas.ink_adjust_width.side_effect = adjust

        fake_settings = MagicMock()
        with patch("ui.review_screen.QSettings", return_value=fake_settings):
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Plus, Qt.NoModifier)
            screen.keyPressEvent(event)

        screen.canvas.ink_adjust_width.assert_called_once_with(0.4)
        self.assertAlmostEqual(screen._review_ink_width, 1.6)
        fake_settings.setValue.assert_called_with("review/ink_width", 1.6)

if __name__ == "__main__":
    unittest.main()
