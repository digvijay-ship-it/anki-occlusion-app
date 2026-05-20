import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import unittest
from unittest.mock import patch, MagicMock

from PyQt5.QtWidgets import QApplication, QPushButton

_APP = QApplication.instance() or QApplication([])

from ui.journal import (
    JOURNAL_FONT_SCALE,
    JOURNAL_WINDOW_SIZE,
    JournalDialog,
    _journal_font_size,
)

class JournalDialogFocusTimeTests(unittest.TestCase):
    @patch('ui.journal._load_journal')
    def test_focus_time_displays_correctly(self, mock_load_journal):
        # Mock the journal data with different focus times
        mock_load_journal.return_value = {
            "2026-04-26": {"focus_seconds": 3660},  # 1h 01m
            "2026-04-25": {"focus_seconds": 1500},  # 25m
            "2026-04-24": {"focus_seconds": 45},    # 45s
            "2026-04-23": {"focus_seconds": 0},     # 0s (should hide)
        }
        
        with patch('ui.journal.date') as mock_date, patch('os.path.exists', return_value=False):
            # Set today's date so it loads 2026-04-26 by default
            mock_date.today.return_value.isoformat.return_value = "2026-04-26"
            
            dialog = JournalDialog()
            
            # Initially it should load 2026-04-26 (today). It will show >0 or 0s
            self.assertFalse(dialog._lbl_focus.isHidden())
            self.assertEqual(dialog._lbl_focus.text(), "⏱ 1h 01m")
            
            # Switch to 2026-04-25
            dialog._load_date("2026-04-25")
            self.assertFalse(dialog._lbl_focus.isHidden())
            self.assertEqual(dialog._lbl_focus.text(), "⏱ 25m")
            
            # Switch to 2026-04-24
            dialog._load_date("2026-04-24")
            self.assertFalse(dialog._lbl_focus.isHidden())
            self.assertEqual(dialog._lbl_focus.text(), "⏱ 45s")
            
            # Switch to 2026-04-23 (0 seconds, NOT today)
            dialog._load_date("2026-04-23")
            self.assertTrue(dialog._lbl_focus.isHidden())

    @patch('ui.journal._load_journal')
    def test_ninja_toolbar_moves_secondary_actions_to_more_menu(self, mock_load_journal):
        mock_load_journal.return_value = {}
        previous_theme = getattr(_APP, "_active_theme", "classic")
        _APP._active_theme = "tmnt"
        self.addCleanup(setattr, _APP, "_active_theme", previous_theme)

        with patch('os.path.exists', return_value=False):
            dialog = JournalDialog()
        self.addCleanup(dialog.close)

        button_labels = [button.text() for button in dialog.findChildren(QPushButton)]
        overflow_labels = [action.text() for action in dialog._overflow_menu.actions()]

        self.assertEqual(dialog.minimumWidth(), JOURNAL_WINDOW_SIZE[0])
        self.assertEqual(dialog.minimumHeight(), JOURNAL_WINDOW_SIZE[1])
        self.assertEqual(dialog._ninja_topbar.height(), _journal_font_size(84))
        self.assertEqual(dialog._ninja_topbar.layout().count(), 2)
        self.assertEqual(dialog._btn_date.minimumWidth(), _journal_font_size(230))
        self.assertEqual(_journal_font_size(10), 14)
        self.assertEqual(JOURNAL_FONT_SCALE, 1.4)
        self.assertIn("MORE", button_labels)
        self.assertIn("PURGE", button_labels)
        self.assertNotIn("REWIND", button_labels)
        self.assertNotIn("GRID", button_labels)
        self.assertNotIn("EXPORT SCROLL", button_labels)
        self.assertEqual(overflow_labels, ["REWIND", "GRID", "EXPORT SCROLL"])
            
if __name__ == '__main__':
    unittest.main()
