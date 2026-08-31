# -*- coding: utf-8 -*-
import unittest
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QKeyEvent

os.environ["QT_QPA_PLATFORM"] = "offscreen"


class TestMissionReportDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_instantiation(self):
        from ui.mission_report_dialog import MissionReportDialog
        dlg = MissionReportDialog(initial_date="2026-08-22")
        self.assertIsNotNone(dlg)
        self.assertEqual(dlg._current_date, "2026-08-22")
        dlg.close()

    def test_keyboard_arrow_navigation(self):
        from ui.mission_report_dialog import MissionReportDialog
        dlg = MissionReportDialog(initial_date="2026-08-22")
        dlg.show()
        
        # Press Left Arrow -> should go to 2026-08-21
        event_left = QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier)
        dlg.eventFilter(dlg, event_left)
        self.assertEqual(dlg._current_date, "2026-08-21")
        
        # Press Right Arrow -> should go back to 2026-08-22
        event_right = QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier)
        dlg.eventFilter(dlg, event_right)
        self.assertEqual(dlg._current_date, "2026-08-22")
        
        dlg.close()

    def test_animation_suspension(self):
        from ui.mission_report_dialog import MissionReportDialog
        from ui.canvas.retro_effects import animations_suspended
        
        dlg = MissionReportDialog(initial_date="2026-08-22")
        dlg.show()
        self.assertTrue(animations_suspended())
        
        dlg.close()
        self.assertFalse(animations_suspended())

    def test_tree_columns_and_time_display(self):
        from ui.mission_report_dialog import MissionReportDialog
        dlg = MissionReportDialog(initial_date="2026-08-22")
        self.assertEqual(dlg._tree_widget.columnCount(), 3)
        self.assertEqual(dlg._tree_widget.headerItem().text(0), "Deck / Topic")
        self.assertEqual(dlg._tree_widget.headerItem().text(1), "Time Spent")
        self.assertEqual(dlg._tree_widget.headerItem().text(2), "Reviews")
        dlg.close()

    def test_clipboard_copy_includes_time(self):
        from ui.mission_report_dialog import MissionReportDialog
        from unittest.mock import patch
        mock_stats = {
            "date": "2026-08-22",
            "total": 5,
            "again": 0,
            "hard": 0,
            "good": 5,
            "easy": 0,
            "perfect": 0,
            "retention": 100,
            "tree": [
                {
                    "name": "Math",
                    "total_reviews": 5,
                    "total_seconds": 3600,
                    "time_str": "1h",
                    "children": []
                }
            ],
            "decks": {"Math": 5}
        }
        with patch("ui.mission_report_dialog.get_daily_activity_stats", return_value=mock_stats), \
             patch("ui.mission_report_dialog.get_daily_focus_seconds", return_value=3600):
            dlg = MissionReportDialog(initial_date="2026-08-22")
            dlg._copy_summary_to_clipboard()
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            self.assertIn("• Math: ⏱ 1h · 5 review(s)", text)
            dlg.close()


if __name__ == "__main__":
    unittest.main()

