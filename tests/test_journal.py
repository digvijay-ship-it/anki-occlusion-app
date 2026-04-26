import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import unittest
from unittest.mock import patch, MagicMock

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

from journal import JournalDialog

class JournalDialogFocusTimeTests(unittest.TestCase):
    @patch('journal._load_journal')
    def test_focus_time_displays_correctly(self, mock_load_journal):
        # Mock the journal data with different focus times
        mock_load_journal.return_value = {
            "2026-04-26": {"focus_seconds": 3660},  # 1h 01m
            "2026-04-25": {"focus_seconds": 1500},  # 25m
            "2026-04-24": {"focus_seconds": 45},    # 45s
            "2026-04-23": {"focus_seconds": 0},     # 0s (should hide)
        }
        
        with patch('journal.date') as mock_date, patch('os.path.exists', return_value=False):
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
            
if __name__ == '__main__':
    unittest.main()
