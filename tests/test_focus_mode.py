import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt, QSettings
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication

from services import shortcut_manager
from ui.canvas.core import OcclusionCanvas
from ui.review_screen import ReviewScreen

_APP = QApplication.instance() or QApplication([])


class FocusModeTests(unittest.TestCase):
    def setUp(self):
        shortcut_manager.reset_shortcuts()
        self.addCleanup(shortcut_manager.reset_shortcuts)
        # Clear FocusModeSettings to ensure clean state
        QSettings("AnkiOcclusion", "FocusModeSettings").clear()

    def test_canvas_focus_mode_defaults(self):
        canvas = OcclusionCanvas()
        self.assertFalse(canvas.is_focus_mode())
        # Default opacity is 0.2
        self.assertEqual(canvas.get_bg_opacity(), 0.2)

    def test_canvas_focus_mode_toggling(self):
        canvas = OcclusionCanvas()
        canvas.set_focus_mode(True)
        self.assertTrue(canvas.is_focus_mode())
        canvas.set_focus_mode(False)
        self.assertFalse(canvas.is_focus_mode())

    def test_canvas_opacity_clamping(self):
        canvas = OcclusionCanvas()
        canvas.set_bg_opacity(0.5)
        self.assertEqual(canvas.get_bg_opacity(), 0.5)
        
        # Clamp to 1.0
        canvas.set_bg_opacity(1.5)
        self.assertEqual(canvas.get_bg_opacity(), 1.0)
        
        # Clamp to 0.0
        canvas.set_bg_opacity(-0.5)
        self.assertEqual(canvas.get_bg_opacity(), 0.0)

    def test_review_screen_focus_toggle_shortcut(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = OcclusionCanvas()
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._btn_focus_canvas = MagicMock()
        screen._update_focus_mode_button_style = MagicMock()
        screen._btn_focus_opacity_minus = MagicMock()
        screen._btn_focus_opacity_plus = MagicMock()
        
        # Initial state
        self.assertFalse(screen.canvas.is_focus_mode())
        
        # Press Ctrl+F
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_F, Qt.ControlModifier)
        screen.keyPressEvent(event)
        
        self.assertTrue(screen.canvas.is_focus_mode())
        screen._update_focus_mode_button_style.assert_called_once()
        
        # Press Ctrl+F again
        screen.keyPressEvent(event)
        self.assertFalse(screen.canvas.is_focus_mode())

    def test_review_screen_keyboard_opacity_adjustment(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = OcclusionCanvas()
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._btn_focus_canvas = MagicMock()
        screen._update_focus_mode_button_style = MagicMock()
        screen._btn_focus_opacity_minus = MagicMock()
        screen._btn_focus_opacity_plus = MagicMock()
        
        # Enable focus mode
        screen.canvas.set_focus_mode(True)
        screen.canvas.set_bg_opacity(0.2)
        
        # Press '+' (Key_Plus)
        event_plus = QKeyEvent(QEvent.KeyPress, Qt.Key_Plus, Qt.NoModifier)
        screen.keyPressEvent(event_plus)
        self.assertAlmostEqual(screen.canvas.get_bg_opacity(), 0.25)
        
        # Press '-' (Key_Minus)
        event_minus = QKeyEvent(QEvent.KeyPress, Qt.Key_Minus, Qt.NoModifier)
        screen.keyPressEvent(event_minus)
        self.assertAlmostEqual(screen.canvas.get_bg_opacity(), 0.20)

    def test_adjust_opacity_turns_on_focus_mode(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = OcclusionCanvas()
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._btn_focus_canvas = MagicMock()
        screen._update_focus_mode_button_style = MagicMock()
        screen._btn_focus_opacity_minus = MagicMock()
        screen._btn_focus_opacity_plus = MagicMock()
        
        # Focus mode is OFF
        self.assertFalse(screen.canvas.is_focus_mode())
        
        # Adjust opacity
        screen._adjust_focus_opacity(0.1)
        
        # Should now be ON and opacity adjusted
        self.assertTrue(screen.canvas.is_focus_mode())
        self.assertAlmostEqual(screen.canvas.get_bg_opacity(), 0.3)
