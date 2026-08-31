import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent

from services import shortcut_manager


class ShortcutManagerTests(unittest.TestCase):
    def setUp(self):
        shortcut_manager.reset_shortcuts()
        self.addCleanup(shortcut_manager.reset_shortcuts)

    def test_shortcut_text_uses_default_until_overridden(self):
        self.assertEqual(shortcut_manager.shortcut_text("review.reveal"), "Space")
        self.assertEqual(shortcut_manager.shortcut_text("home.redo"), "Ctrl+Y")

        shortcut_manager.set_shortcut("review.reveal", "R")

        self.assertEqual(shortcut_manager.shortcut_text("review.reveal"), "R")

    def test_event_matches_saved_shortcut(self):
        shortcut_manager.set_shortcut("home.save", "Ctrl+J")
        event = QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_J,
            Qt.ControlModifier,
        )

        self.assertTrue(shortcut_manager.event_matches(event, "home.save"))
        self.assertFalse(shortcut_manager.event_matches(event, "home.undo"))

    def test_ctrl_equal_matches_ctrl_plus_shortcut(self):
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Equal, Qt.ControlModifier)

        self.assertTrue(shortcut_manager.event_matches(event, "review.zoom_in"))

    def test_keypad_modifier_is_ignored_for_matches(self):
        # Keypad 1 key event
        event = QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_1,
            Qt.KeypadModifier
        )
        self.assertTrue(shortcut_manager.event_matches(event, "review.rate_again"))

    def test_ctrl_question_matches_ctrl_question_shortcut(self):
        # Ctrl+? (represented as Ctrl+Shift+Question or Ctrl+Question)
        event1 = QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Question,
            Qt.ControlModifier | Qt.ShiftModifier
        )
        self.assertIn("Ctrl+?", shortcut_manager._event_sequence_texts(event1))

        event2 = QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Question,
            Qt.ControlModifier
        )
        self.assertIn("Ctrl+?", shortcut_manager._event_sequence_texts(event2))

        # Also support Shift+Slash with Control
        event3 = QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Slash,
            Qt.ControlModifier | Qt.ShiftModifier
        )
        self.assertIn("Ctrl+?", shortcut_manager._event_sequence_texts(event3))


if __name__ == "__main__":
    unittest.main()
