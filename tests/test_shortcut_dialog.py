import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from services import shortcut_manager
from ui.shortcut_dialog import ShortcutSettingsDialog


_APP = QApplication.instance() or QApplication([])


class ShortcutSettingsDialogTests(unittest.TestCase):
    def setUp(self):
        shortcut_manager.reset_shortcuts()
        self.addCleanup(shortcut_manager.reset_shortcuts)

    def test_dialog_builds_all_shortcut_editors(self):
        dialog = ShortcutSettingsDialog()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.windowTitle(), "Shortcuts")
        self.assertEqual(len(dialog._edits), len(shortcut_manager.all_actions()))

    def test_default_shortcuts_save_without_cross_context_conflict(self):
        dialog = ShortcutSettingsDialog()
        self.addCleanup(dialog.close)

        dialog._save()

        self.assertEqual(dialog.result(), ShortcutSettingsDialog.Accepted)


if __name__ == "__main__":
    unittest.main()
