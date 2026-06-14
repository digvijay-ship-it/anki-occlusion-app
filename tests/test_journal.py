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
        self.assertEqual(dialog._ninja_topbar.height(), _journal_font_size(104))
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

    @patch('data_manager.store')
    @patch('ui.journal._load_journal')
    def test_daily_activity_stats_parsing(self, mock_load_journal, mock_store):
        mock_load_journal.return_value = {
            "2026-06-10": {"focus_seconds": 120}
        }
        # Mock the store data
        mock_store.get.return_value = {
            "decks": [
                {
                    "name": "Surgical Anatomy",
                    "cards": [
                        {
                            "title": "Heart",
                            "reviewed_at": "2026-06-10T12:00:00",
                            "last_quality": 4, # Good
                            "boxes": [
                                {
                                    "box_id": "b1",
                                    "reviewed_at": "2026-06-10T12:01:00",
                                    "last_quality": 6 # Perfect
                                },
                                {
                                    "box_id": "b2",
                                    "reviewed_at": "2026-06-09T12:01:00", # Yesterday
                                    "last_quality": 1
                                }
                            ]
                        }
                    ],
                    "children": []
                }
            ]
        }
        
        with patch('ui.journal.date') as mock_date, patch('os.path.exists', return_value=False):
            mock_date.today.return_value.isoformat.return_value = "2026-06-10"
            
            dialog = JournalDialog()
            dialog._load_date("2026-06-10")
            
            # Verify the stats values computed
            stats = dialog._get_activity_stats("2026-06-10")
            self.assertEqual(stats["total"], 2) # 1 card review + 1 box review
            self.assertEqual(stats["good"], 1)
            self.assertEqual(stats["perfect"], 1)
            self.assertEqual(stats["again"], 0)
            self.assertIn("Surgical Anatomy", stats["decks"])
            self.assertEqual(stats["decks"]["Surgical Anatomy"], 2)
            
            # Verify UI labels show correct values
            self.assertEqual(dialog._lbl_cards_val.text(), "2")
            self.assertEqual(dialog._lbl_succ_val.text(), "100%")
            self.assertEqual(dialog._lbl_focus_val.text(), "2m")

    @patch('ui.journal._save_journal')
    @patch('ui.journal._load_journal')
    def test_save_current_merges_background_updates(self, mock_load_journal, mock_save_journal):
        # 1. Dialog initialized with initial journal state
        mock_load_journal.return_value = {
            "2026-06-10": {"focus_seconds": 60}
        }
        
        with patch('ui.journal.date') as mock_date, patch('os.path.exists', return_value=False):
            mock_date.today.return_value.isoformat.return_value = "2026-06-10"
            dialog = JournalDialog()
            dialog._load_date("2026-06-10")
            
            # Simulate background update writing to the file on disk (i.e. next load will return a new value)
            mock_load_journal.return_value = {
                "2026-06-10": {
                    "focus_seconds": 180,
                    "texts": [
                        {
                            "x": 60,
                            "y": 80,
                            "text": "\u23f1 Focus today: 3m",
                            "color": "#7C6AF7",
                            "size": 15
                        }
                    ]
                }
            }
            
            # Add some strokes / texts to dialog canvas and trigger save
            dialog._canvas.get_strokes = MagicMock(return_value=[])
            dialog._canvas.get_texts = MagicMock(return_value=[
                {"x": 10, "y": 20, "text": "User note", "color": "#FFFFFF", "size": 12}
            ])
            
            dialog._save_current()
            
            # Check what got saved to mock_save_journal
            self.assertTrue(mock_save_journal.called)
            saved_data = mock_save_journal.call_args[0][0]
            
            entry = saved_data["2026-06-10"]
            self.assertEqual(entry["focus_seconds"], 180) # Maintained background focus_seconds
            
            # Maintained background text AND user note
            saved_texts = entry["texts"]
            self.assertEqual(len(saved_texts), 2)
            self.assertTrue(any(t["text"].startswith("User note") for t in saved_texts))
            self.assertTrue(any(t["text"].startswith("\u23f1 Focus today:") for t in saved_texts))
            
if __name__ == '__main__':
    unittest.main()
