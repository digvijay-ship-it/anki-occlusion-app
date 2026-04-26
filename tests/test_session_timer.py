import os
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Enable headless Qt tests
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication

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
    def test_SessionTimer_initializes_with_loaded_state(self, mock_load):
        timer = SessionTimer()
        self.assertEqual(timer.elapsed_seconds, 10)
        self.assertEqual(timer.elapsed_str(), "0:00:10")
        
        # Verify the timer tick increments state
        timer._tick()
        self.assertEqual(timer.elapsed_seconds, 11)
        self.assertEqual(timer.elapsed_str(), "0:00:11")
        self.assertEqual(timer.label.text(), "0:00:11")

if __name__ == "__main__":
    unittest.main()
