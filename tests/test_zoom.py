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

if __name__ == "__main__":
    unittest.main()
