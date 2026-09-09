import os
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.review_manager import ReviewSessionManager
import sm2_engine


class NumpadCustomRescheduleTests(unittest.TestCase):
    def setUp(self):
        self.rs = MagicMock()
        self.card = {
            "sched_state": "review",
            "sched_step": 0,
            "sm2_interval": 15,
            "sm2_ease": 2.5,
            "sm2_due": sm2_engine._now_iso(),
            "sm2_repetitions": 4,
            "sm2_last_quality": 4,
            "reviews": 4,
        }
        self.rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [self.card], "children": []}]}
        self.manager = ReviewSessionManager(self.rs)
        self.manager._items = [(self.card, None, self.card)]
        self.manager._idx = 0

    def test_custom_reschedule_preserves_sm2_stats(self):
        """Verify custom_reschedule sets due date N days ahead without touching EF or repetitions."""
        initial_ef = self.card.get("sm2_ease")
        initial_reps = self.card.get("sm2_repetitions")
        initial_interval = self.card.get("sm2_interval")

        with patch("services.review_manager.store.mark_dirty"):
            self.manager.custom_reschedule(days=4)

        expected_due_date = date.today() + timedelta(days=4)
        due_str = self.card.get("sm2_due")
        self.true = self.assertTrue(due_str.startswith(expected_due_date.isoformat()))

        # SM-2 stats must remain 100% frozen
        self.assertEqual(self.card.get("sm2_ease"), initial_ef)
        self.assertEqual(self.card.get("sm2_repetitions"), initial_reps)
        self.assertEqual(self.card.get("sm2_interval"), initial_interval)


        # Queue advanced and load_item called
        self.assertEqual(len(self.manager._items), 0)
        self.rs._load_item.assert_called_once()

    def test_custom_reschedule_supports_undo(self):
        """Verify _review_undo restores original item state and queue position."""
        original_due = self.card.get("sm2_due")

        with patch("services.review_manager.store.mark_dirty"):
            self.manager.custom_reschedule(days=3)
            self.assertEqual(len(self.manager._items), 0)

            # Perform undo
            self.manager._review_undo()

        self.assertEqual(len(self.manager._items), 1)
        restored_card = self.manager._items[0][0]
        self.assertEqual(restored_card.get("sm2_due"), original_due)

    def test_keypad_event_detection_when_enabled_and_disabled(self):
        """Verify keypad events trigger reschedule when setting is ON and pass through when OFF."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QKeyEvent
        from ui.review_screen import ReviewScreen

        mock_screen = MagicMock(spec=ReviewScreen)
        mock_screen.mgr = self.manager
        mock_screen._rating_frame = MagicMock()
        mock_screen._rating_frame.isVisible.return_value = False
        mock_screen._rating_quality_for_event.return_value = None

        # Key event on Numpad 4
        keypad_event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_4, Qt.KeypadModifier)
        toprow_event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_4, Qt.NoModifier)

        # 1. When disabled
        mock_screen._is_numpad_revision_enabled.return_value = False
        with patch("PyQt5.QtWidgets.QWidget.keyPressEvent"):
            ReviewScreen.keyPressEvent(mock_screen, keypad_event)
        self.assertEqual(len(self.manager._items), 1)

        # 2. When enabled with Numpad key
        mock_screen._is_numpad_revision_enabled.return_value = True
        with patch("services.review_manager.store.mark_dirty"), patch("PyQt5.QtWidgets.QWidget.keyPressEvent"):
            ReviewScreen.keyPressEvent(mock_screen, keypad_event)
            mock_screen._custom_reschedule.assert_called_once_with(4)

        # 3. When enabled but with top-row number key
        mock_screen._custom_reschedule.reset_mock()
        with patch("PyQt5.QtWidgets.QWidget.keyPressEvent"):
            ReviewScreen.keyPressEvent(mock_screen, toprow_event)
        mock_screen._custom_reschedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
