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


if __name__ == "__main__":
    unittest.main()
