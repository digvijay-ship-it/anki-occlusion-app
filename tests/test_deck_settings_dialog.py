import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QScrollArea, QPushButton, QLineEdit

_APP = QApplication.instance() or QApplication([])

from ui.deck_tree import DeckSettingsDialog


class DeckSettingsDialogTests(unittest.TestCase):
    def setUp(self):
        self.deck = {
            "_id": 101,
            "name": "General Science Test Deck",
            "daily_new_limit": 15,
            "daily_review_limit": 50,
            "daily_limit": 65,
            "session_limit": 20,
            "paused": False,
            "review_order": "default"
        }
        self.dialog = DeckSettingsDialog(deck=self.deck)

    def tearDown(self):
        self.dialog.deleteLater()

    def test_dialog_dimensions_and_scroll_area(self):
        """Verify dialog has generous dimensions and a dedicated QScrollArea."""
        self.assertGreaterEqual(self.dialog.minimumWidth(), 860)
        self.assertGreaterEqual(self.dialog.minimumHeight(), 740)

        scroll_areas = self.dialog.findChildren(QScrollArea)
        self.assertGreaterEqual(len(scroll_areas), 1)
        scroll = scroll_areas[0]
        self.assertTrue(scroll.widgetResizable())

    def test_save_and_cancel_buttons_present(self):
        """Verify Save and Cancel buttons exist and have user-friendly labels."""
        self.assertIsNotNone(self.dialog.btn_save)
        self.assertIsNotNone(self.dialog.btn_cancel)
        self.assertIn("SAVE SETTINGS", self.dialog.btn_save.text())
        self.assertIn("CANCEL", self.dialog.btn_cancel.text())

    def test_input_boxes_have_generous_widths(self):
        """Verify input boxes are wide enough (>= 200px) so placeholders are never clipped."""
        for inp in [
            self.dialog.inp_daily_new_limit,
            self.dialog.inp_daily_review_limit,
            self.dialog.inp_daily_limit,
            self.dialog.inp_session_limit,
            self.dialog.inp_learning_window_limit,
        ]:
            self.assertIsInstance(inp, QLineEdit)
            self.assertGreaterEqual(inp.width(), 200)

    def test_save_settings_logic(self):
        """Verify modifying fields and saving correctly updates deck dict and store."""
        self.dialog.inp_daily_new_limit.setText("25")
        self.dialog.inp_daily_review_limit.setText("80")
        self.dialog.inp_daily_limit.setText("105")
        self.dialog.inp_session_limit.setText("35")
        self.dialog.inp_learning_window_limit.setText("12")
        self.dialog.chk_pause.setChecked(True)
        
        least_mature_idx = self.dialog.combo_order.findData("least_mature")
        self.assertGreaterEqual(least_mature_idx, 0)
        self.dialog.combo_order.setCurrentIndex(least_mature_idx)

        fsrs_idx = self.dialog.combo_scheduler.findData("fsrs")
        self.assertGreaterEqual(fsrs_idx, 0)
        self.dialog.combo_scheduler.setCurrentIndex(fsrs_idx)

        ret_idx = self.dialog.combo_retention.findData(0.95)
        self.assertGreaterEqual(ret_idx, 0)
        self.dialog.combo_retention.setCurrentIndex(ret_idx)

        with patch("services.review_manager.store.save_force") as mock_save:
            with patch.object(self.dialog, "accept") as mock_accept:
                self.dialog._save_settings()
                self.assertEqual(self.deck["daily_new_limit"], 25)
                self.assertEqual(self.deck["daily_review_limit"], 80)
                self.assertEqual(self.deck["daily_limit"], 105)
                self.assertEqual(self.deck["session_limit"], 35)
                self.assertEqual(self.deck["learning_window_limit"], 12)
                self.assertEqual(self.deck["scheduler_type"], "fsrs")
                self.assertEqual(self.deck["request_retention"], 0.95)
                self.assertTrue(self.deck["is_paused"])
                self.assertEqual(self.deck["review_order"], "least_mature")
                mock_save.assert_called_once_with(async_save=True)
                mock_accept.assert_called_once()

    def test_default_selection_clears_override_to_inherit_global(self):
        """Selecting 'Default (Follow Main Settings)' clears deck-level override."""
        self.deck["scheduler_type"] = "sm2"
        self.deck["request_retention"] = 0.85
        dlg = DeckSettingsDialog(deck=self.deck)

        # Select index 0 ("Default (Follow Main Settings)")
        dlg.combo_scheduler.setCurrentIndex(0)
        dlg.combo_retention.setCurrentIndex(0)

        with patch("services.review_manager.store.save_force"):
            dlg._save_settings()

        self.assertNotIn("scheduler_type", self.deck)
        self.assertNotIn("request_retention", self.deck)
        dlg.deleteLater()

    def test_deck_view_resolves_global_defaults_when_unset(self):
        """DeckView._resolve_deck_limits returns global defaults when deck has no override."""
        from ui.deck_view import DeckView
        dv = DeckView()
        deck = {"_id": 1, "name": "Test", "cards": []}
        data = {
            "decks": [deck],
            "_scheduler_type": "sm2",
            "_request_retention": 0.92,
        }
        dv.deck = deck
        dv._data = data

        limits = dv._resolve_deck_limits()
        self.assertEqual(limits["scheduler_type"], "sm2")
        self.assertEqual(limits["request_retention"], 0.92)

        # If deck explicitly overrides, override takes precedence:
        deck["scheduler_type"] = "fsrs"
        deck["request_retention"] = 0.95
        limits_override = dv._resolve_deck_limits()
        self.assertEqual(limits_override["scheduler_type"], "fsrs")
        self.assertEqual(limits_override["request_retention"], 0.95)


if __name__ == "__main__":
    unittest.main()
