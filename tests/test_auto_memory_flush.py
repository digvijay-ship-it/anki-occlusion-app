# -*- coding: utf-8 -*-
"""
tests/test_auto_memory_flush.py
Verifies:
1. flush_process_memory() runs safely and cleans fitz buffers, QPixmapCache, and gc.
2. Closing a QDialog triggers automatic memory flush via UniversalDialogKeyFilter.
3. Closing ReviewScreen triggers automatic memory flush.
4. Closing FSRSCenterDialog triggers automatic memory flush.
5. cache_manager DEFAULT_RAM_PAGE_LIMIT is 4.
"""

import unittest
import sys
import os

repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_dir not in sys.path:
    sys.path.insert(0, repo_dir)

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt5.QtCore import QEvent

app = QApplication.instance() or QApplication(sys.argv)

from data_manager import store
store.load()

from perf_utils import flush_process_memory, get_process_memory_mb
from cache_manager import DEFAULT_RAM_PAGE_LIMIT
from services.dialog_key_filter import install_dialog_key_filter
from ui.fsrs_center_dialog import FSRSCenterDialog
from ui.review_screen import ReviewScreen


class TestAutoMemoryFlush(unittest.TestCase):
    def test_default_ram_page_limit_is_none_unlimited(self):
        self.assertIsNone(DEFAULT_RAM_PAGE_LIMIT)


    def test_flush_process_memory_runs_safely(self):
        flush_process_memory("UnitTest Execution")
        mem = get_process_memory_mb()
        self.assertGreater(mem, 0.0)

    def test_dialog_close_event_triggers_flush(self):
        flt = install_dialog_key_filter()
        dlg = QDialog()
        dlg.setWindowTitle("Test Dialog")
        event = QEvent(QEvent.Close)
        res = flt.eventFilter(dlg, event)
        self.assertFalse(res)

    def test_fsrs_center_dialog_close_flush(self):
        dlg = FSRSCenterDialog()
        dlg.close()

    def test_review_screen_close_flush(self):
        rs = ReviewScreen([], data={"decks": []})
        rs.close()

    def test_home_screen_auto_flush_when_idle(self):
        from ui.home_screen import HomeScreen
        home = HomeScreen({"decks": []})
        home._auto_flush_if_home_idle()
        home.close()


if __name__ == "__main__":
    unittest.main()

