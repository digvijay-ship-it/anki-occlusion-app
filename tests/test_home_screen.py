import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication, QLabel

# Ensure QApplication exists before importing HomeScreen
_APP = QApplication.instance() or QApplication([])

from anki_occlusion_v19 import HomeScreen
import anki_occlusion_v19
from ui.home_screen import AboutDialog, MusicWidget

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


class HomeScreenMusicWidgetTests(unittest.TestCase):
    def test_music_scan_excludes_math_trainer_sound_effects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in (
                "Teenage Mutant Ninja Turtles III - Scene 1.mp3",
                "ambient.ogg",
                "pickupCoin.wav",
                "powerUp.wav",
                "hitHurt.wav",
            ):
                with open(os.path.join(tmpdir, name), "wb") as fh:
                    fh.write(b"audio")

            with patch.object(MusicWidget, "MUSIC_DIR", tmpdir), patch.object(
                MusicWidget, "_init_audio", lambda self: None
            ):
                widget = MusicWidget()
                self.addCleanup(widget.close)

        self.assertEqual(
            {os.path.basename(path) for path in widget._tracks},
            {
                "Teenage Mutant Ninja Turtles III - Scene 1.mp3",
                "ambient.ogg",
            },
        )


class HomeScreenClassicUiTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)
        self.home_screen = HomeScreen({"decks": [], "_theme": "classic"})
        self.addCleanup(self.home_screen.close)

    def test_classic_topbar_has_save_and_settings_controls(self):
        self.assertEqual(self.home_screen._btn_save.text(), "💾 SAVE")
        self.assertEqual(self.home_screen._btn_settings.text(), "⚙ SETTINGS")
        self.assertIsNotNone(self.home_screen._classic_settings_panel)

    def test_classic_settings_panel_toggles_and_shows_archive_controls(self):
        self.home_screen._toggle_classic_settings_panel()

        self.assertTrue(self.home_screen._classic_settings_panel.isVisible())
        self.assertEqual(self.home_screen._classic_archive_btn.text(), "SET")
        self.assertTrue(self.home_screen._classic_archive_value.text())

        self.home_screen._toggle_classic_settings_panel()
        self.assertFalse(self.home_screen._classic_settings_panel.isVisible())

    def test_classic_save_button_delegates_to_manual_save(self):
        with patch.object(self.home_screen, "_save_current_data_now") as save_now:
            self.home_screen._on_classic_save_clicked()

        save_now.assert_called_once_with()

    def test_about_dialog_shortcuts_include_pdf_copy_and_open_folder(self):
        dialog = AboutDialog(self.home_screen)
        self.addCleanup(dialog.close)

        label_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn("L — copy current PDF file", label_text)
        self.assertIn("Ctrl+L — open current PDF folder", label_text)

if __name__ == "__main__":
    unittest.main()
