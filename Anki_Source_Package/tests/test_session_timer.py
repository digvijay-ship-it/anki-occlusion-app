import os
import json
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Enable headless Qt tests
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

_APP = QApplication.instance() or QApplication([])

from session_timer import (
    _load_state, _save_state, _atomic_write, _fmt_human,
    _write_focus_to_journal, SessionTimer, _JOURNAL_TAG,
    _STATE_FILE, _JOURNAL_FILE
)
import session_timer

class SessionTimerTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)
        
        self.test_state_file = str(Path(self.tmpdir.name) / "test_timer_state.json")
        self.test_journal_file = str(Path(self.tmpdir.name) / "test_journal.json")

        import services.journal_manager as jm
        self.old_jm_file = jm.JOURNAL_FILE
        jm.JOURNAL_FILE = self.test_journal_file
        self.addCleanup(setattr, jm, "JOURNAL_FILE", self.old_jm_file)

    def test_fmt_human_returns_correct_string(self):
        self.assertEqual(_fmt_human(5), "5s")
        self.assertEqual(_fmt_human(65), "1m")
        self.assertEqual(_fmt_human(3600), "1h 00m")
        self.assertEqual(_fmt_human(3665), "1h 01m")
        
    def test_SessionTimer_format_method(self):
        self.assertEqual(SessionTimer._fmt(5), "0:00:05")
        self.assertEqual(SessionTimer._fmt(65), "0:01:05")
        self.assertEqual(SessionTimer._fmt(3665), "1:01:05")

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    def test_load_state_missing_file_returns_0(self, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        self.assertEqual(_load_state(), 0)

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    def test_load_state_with_valid_today_returns_seconds(self, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        
        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-04-26"
            
            _atomic_write(self.test_state_file, {"date": "2026-04-26", "seconds": 120})
            self.assertEqual(_load_state(), 120)

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    def test_load_state_with_different_day_returns_0(self, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        
        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-04-26"
            
            # Wrote yesterday's data
            _atomic_write(self.test_state_file, {"date": "2026-04-25", "seconds": 120})
            self.assertEqual(_load_state(), 0)

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    def test_save_state_writes_correct_file(self, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        
        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-04-26"
            
            _save_state(300)
            
            with open(self.test_state_file, "r") as f:
                data = json.load(f)
            
            self.assertEqual(data["date"], "2026-04-26")
            self.assertEqual(data["seconds"], 300)

    @patch('session_timer._JOURNAL_FILE', new_callable=lambda: None)
    def test_write_focus_to_journal_updates_file(self, mock_journal_file):
        session_timer._JOURNAL_FILE = self.test_journal_file
        
        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-04-26"
            
            _write_focus_to_journal(3665)
            
            with open(self.test_journal_file, "r") as f:
                data = json.load(f)
            
            entry = data["2026-04-26"]
            self.assertEqual(entry["focus_seconds"], 3665)
            
            # Verify the text was inserted
            texts = entry["texts"]
            self.assertEqual(len(texts), 1)
            self.assertTrue(texts[0]["text"].startswith(_JOURNAL_TAG))
            self.assertTrue("1h 01m" in texts[0]["text"])
            
            # Call again to ensure it updates instead of duplicating
            _write_focus_to_journal(4000)
            with open(self.test_journal_file, "r") as f:
                data = json.load(f)
            
            entry = data["2026-04-26"]
            self.assertEqual(entry["focus_seconds"], 4000)
            self.assertEqual(len(entry["texts"]), 1) # Still 1 item

    @patch('session_timer._load_state', return_value=10)
    @patch('session_timer.QApplication.activeWindow', return_value=True)
    def test_SessionTimer_initializes_with_loaded_state(self, mock_active_window, mock_load):
        timer = SessionTimer()
        self.assertEqual(timer.elapsed_seconds, 10)
        self.assertEqual(timer.elapsed_str(), "0:00:10")
        
        # Verify the timer tick increments state
        timer._tick()
        self.assertEqual(timer.elapsed_seconds, 11)
        self.assertEqual(timer.elapsed_str(), "0:00:11")
        self.assertEqual(timer.label.text(), "0:00:11")

    @patch('session_timer._load_state', return_value=0)
    @patch('session_timer.QApplication.activeWindow', return_value=True)
    def test_SessionTimer_pauses_after_three_minutes_without_activity(self, mock_active_window, mock_load):
        timer = SessionTimer()

        for _ in range(180):
            timer._tick()
        self.assertEqual(timer.elapsed_seconds, 180)

        timer._tick()
        self.assertEqual(timer.elapsed_seconds, 180)

        timer.note_activity()
        timer._tick()
        self.assertEqual(timer.elapsed_seconds, 181)

    @patch('session_timer._load_state', return_value=0)
    def test_activity_filter_resets_idle_for_child_widget_mouse_activity(self, mock_load):
        parent = QWidget()
        self.addCleanup(parent.close)
        child = QLabel(parent)
        timer = SessionTimer(parent)
        timer._idle_seconds = 42

        timer._activity_filter.eventFilter(child, QEvent(QEvent.MouseMove))

        self.assertEqual(timer._idle_seconds, 0)

    @patch('session_timer._load_state', return_value=0)
    def test_activity_filter_ignores_widgets_outside_timer_scope(self, mock_load):
        parent = QWidget()
        other = QWidget()
        self.addCleanup(parent.close)
        self.addCleanup(other.close)
        timer = SessionTimer(parent)
        timer._idle_seconds = 42

        timer._activity_filter.eventFilter(other, QEvent(QEvent.MouseMove))

        self.assertEqual(timer._idle_seconds, 42)

    @patch('session_timer._load_state', return_value=0)
    def test_labels_are_unparented_until_embedded(self, mock_load):
        parent = QWidget()
        self.addCleanup(parent.close)
        timer = SessionTimer(parent)

        self.assertIsNone(timer.label.parent())
        self.assertIsNone(timer.label_session.parent())
        self.assertIsNone(timer.label_today.parent())

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    @patch('session_timer._JOURNAL_FILE', new_callable=lambda: None)
    @patch('session_timer.QApplication.activeWindow', return_value=True)
    def test_SessionTimer_rolls_over_at_midnight(self, mock_active_window, mock_journal_file, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        session_timer._JOURNAL_FILE = self.test_journal_file

        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-05-04"
            timer = SessionTimer()
            timer._elapsed = 120
            timer._session_elapsed = 30

            mock_date.today.return_value.isoformat.return_value = "2026-05-05"
            timer._tick()

            self.assertEqual(timer.elapsed_seconds, 1)
            self.assertEqual(timer.label_today.text(), "0:00:01")
            self.assertEqual(timer.label_session.text(), "0:00:31")

        with open(self.test_journal_file, "r", encoding="utf-8") as f:
            journal = json.load(f)
        self.assertEqual(journal["2026-05-04"]["focus_seconds"], 120)

        with open(self.test_state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state["date"], "2026-05-05")
        self.assertEqual(state["seconds"], 0)

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    @patch('session_timer.QApplication.activeWindow', return_value=True)
    def test_SessionTimer_pdf_tracking(self, mock_active_window, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        timer = SessionTimer()
        
        timer.set_current_pdf("C:\\Path\\To\\File.pdf")
        self.assertEqual(timer._current_pdf, "c:/path/to/file.pdf")
        
        timer._tick()
        self.assertEqual(timer._pdf_seconds["c:/path/to/file.pdf"], 1)
        self.assertEqual(timer._session_pdf_seconds["c:/path/to/file.pdf"], 1)
        
        timer.record_card_review("C:\\Path\\To\\File.pdf")
        self.assertEqual(timer._pdf_cards_today["c:/path/to/file.pdf"], 1)
        self.assertEqual(timer._session_pdf_cards["c:/path/to/file.pdf"], 1)
        
        timer.undo_card_review("C:\\Path\\To\\File.pdf")
        self.assertEqual(timer._pdf_cards_today["c:/path/to/file.pdf"], 0)
        self.assertEqual(timer._session_pdf_cards["c:/path/to/file.pdf"], 0)

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    @patch('session_timer.QApplication.activeWindow', return_value=True)
    def test_SessionTimer_mask_tracking(self, mock_active_window, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        
        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-05-04"
            timer = SessionTimer()
            
            timer.set_current_mask("card1_box_123")
            self.assertEqual(timer._current_mask, "card1_box_123")
            self.assertEqual(timer.label_mask.text(), "0:00:00")
            
            timer._tick()
            self.assertEqual(timer._mask_seconds["card1_box_123"], 1)
            self.assertEqual(timer.label_mask.text(), "0:00:01")
            
            # Switch mask and verify timer values update
            timer.set_current_mask("card1_box_456")
            self.assertEqual(timer._current_mask, "card1_box_456")
            self.assertEqual(timer.label_mask.text(), "0:00:00")
            
            # Verify state was saved to state file
            with open(self.test_state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertEqual(state["mask_seconds"]["card1_box_123"], 1)
            self.assertEqual(state["mask_seconds"].get("card1_box_456", 0), 0)
            
            # Tick new mask
            timer._tick()
            self.assertEqual(timer._mask_seconds["card1_box_456"], 1)
            self.assertEqual(timer.label_mask.text(), "0:00:01")
            
            # Roll over to next day and check if mask times are reset
            timer.set_current_mask("")
            mock_date.today.return_value.isoformat.return_value = "2026-05-05"
            timer._tick()
            
            self.assertEqual(timer._mask_seconds, {})
            self.assertEqual(timer.label_mask.text(), "0:00:00")

    @patch('session_timer._STATE_FILE', new_callable=lambda: None)
    @patch('session_timer._JOURNAL_FILE', new_callable=lambda: None)
    @patch('session_timer.QApplication.activeWindow', return_value=True)
    def test_SessionTimer_deck_tracking(self, mock_active_window, mock_journal_file, mock_state_file):
        session_timer._STATE_FILE = self.test_state_file
        session_timer._JOURNAL_FILE = self.test_journal_file
        
        with patch('session_timer.date') as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2026-05-04"
            timer = SessionTimer()
            
            timer.set_current_deck("Math")
            self.assertEqual(timer._current_deck, "Math")
            self.assertEqual(timer.get_current_deck_seconds(), 0)
            
            timer._tick()
            self.assertEqual(timer._deck_seconds["Math"], 1)
            self.assertEqual(timer._session_deck_seconds["Math"], 1)
            self.assertEqual(timer.get_current_deck_seconds(), 1)
            
            # Switch deck
            timer.set_current_deck("static")
            self.assertEqual(timer._current_deck, "static")
            self.assertEqual(timer.get_current_deck_seconds(), 0)
            
            timer._tick()
            self.assertEqual(timer._deck_seconds["static"], 1)
            self.assertEqual(timer._deck_seconds["Math"], 1)
            
            # Flush to journal and check journal content
            timer.flush_to_journal()
            with open(self.test_journal_file, "r", encoding="utf-8") as f:
                journal = json.load(f)
            self.assertEqual(journal["2026-05-04"]["deck_seconds"]["Math"], 1)
            self.assertEqual(journal["2026-05-04"]["deck_seconds"]["static"], 1)


if __name__ == "__main__":
    unittest.main()
