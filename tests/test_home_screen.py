import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication

# Ensure QApplication exists before importing HomeScreen
_APP = QApplication.instance() or QApplication([])

from anki_occlusion_v19 import HomeScreen
import anki_occlusion_v19

class HomeScreenJournalTests(unittest.TestCase):
    def setUp(self):
        self.home_screen = HomeScreen.__new__(HomeScreen)

    @patch('ui.home_screen.JournalDialog')
    @patch('ui.home_screen._JOURNAL_AVAILABLE', True)
    def test_show_journal_opens_dialog_when_available(self, mock_journal_dialog_class):
        # Setup mock dialog instance
        mock_dialog_instance = MagicMock()
        mock_journal_dialog_class.return_value = mock_dialog_instance

        # Call the method
        self.home_screen._show_journal()

        # Verify dialog was instantiated with self as parent and exec_ was called
        mock_journal_dialog_class.assert_called_once_with(self.home_screen)
        mock_dialog_instance.exec_.assert_called_once()

    @patch('PyQt5.QtWidgets.QMessageBox.warning')
    @patch('ui.home_screen._JOURNAL_AVAILABLE', False)
    def test_show_journal_shows_warning_when_not_available(self, mock_warning):
        # Call the method
        self.home_screen._show_journal()

        # Verify QMessageBox.warning was called
        mock_warning.assert_called_once()
        args, _ = mock_warning.call_args
        self.assertEqual(args[0], self.home_screen)
        self.assertEqual(args[1], "Journal")
        self.assertTrue("journal.py not found" in args[2])

if __name__ == "__main__":
    unittest.main()
