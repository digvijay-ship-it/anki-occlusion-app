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

    def test_dynamic_filtering_by_context(self):
        from PyQt5.QtWidgets import QWidget
        
        class MockReviewScreen(QWidget):
            pass

        class MockHomeScreen(QWidget):
            pass

        # Keep parent references alive during the test
        self.parent_review = MockReviewScreen()
        dialog_review = ShortcutSettingsDialog(self.parent_review)
        self.assertEqual(dialog_review._active_context, "Review")
        
        # Default is "current", so only Review shortcuts should be visible (not hidden)
        for row in dialog_review._shortcut_rows:
            expected_hidden = (row["context"] != "Review")
            self.assertEqual(row["frame"].isHidden(), expected_hidden)
            if row["header"] is not None:
                self.assertEqual(row["header"].isHidden(), expected_hidden)

        # Toggle to full app
        dialog_review._show_full_app()
        for row in dialog_review._shortcut_rows:
            self.assertFalse(row["frame"].isHidden())

        # Toggle back to current screen (Review)
        dialog_review._show_current_screen_only()
        for row in dialog_review._shortcut_rows:
            expected_hidden = (row["context"] != "Review")
            self.assertEqual(row["frame"].isHidden(), expected_hidden)
            if row["header"] is not None:
                self.assertEqual(row["header"].isHidden(), expected_hidden)

        # 2. Test when opened from Home Screen context / other parent
        self.parent_home = MockHomeScreen()
        dialog_home = ShortcutSettingsDialog(self.parent_home)
        self.assertEqual(dialog_home._active_context, "Home")

        # Filter to current screen (Home)
        dialog_home._show_current_screen_only()
        for row in dialog_home._shortcut_rows:
            expected_hidden = (row["context"] != "Home")
            self.assertEqual(row["frame"].isHidden(), expected_hidden)

        # Explicitly close dialogs before parent widgets go out of scope
        dialog_review.close()
        dialog_home.close()

    def test_quick_note_context_detection(self):
        from PyQt5.QtWidgets import QWidget
        
        class MockQuickNoteDialog(QWidget):
            pass

        self.parent_qn = MockQuickNoteDialog()
        dialog = ShortcutSettingsDialog(self.parent_qn)
        self.assertEqual(dialog._active_context, "Review")
        dialog.close()

    def test_shortcut_search_and_header_hiding(self):
        from PyQt5.QtWidgets import QLabel, QKeySequenceEdit
        dialog = ShortcutSettingsDialog()
        self.addCleanup(dialog.close)

        # Show all shortcuts first
        dialog._show_full_app()

        # 1. Type "Save" into search
        dialog.search_input.setText("Save")
        
        # Verify that only rows containing "save" are shown (not hidden)
        for row in dialog._shortcut_rows:
            label_text = row["frame"].findChild(QLabel).text().lower()
            edit_widget = row["frame"].findChild(QKeySequenceEdit)
            key_text = edit_widget.keySequence().toString().lower() if edit_widget else ""
            matches = ("save" in label_text or "save" in key_text)
            self.assertEqual(row["frame"].isHidden(), not matches)

        # 2. Type "rate" (only Review shortcuts have "rate")
        # In this case, all Home shortcuts should be hidden, and the HOME header should be hidden!
        dialog.search_input.setText("rate")
        
        # Find the HOME header widget
        home_header = None
        for row in dialog._shortcut_rows:
            if row["context"] == "Home" and row["header"] is not None:
                home_header = row["header"]
                break
                
        # Since no Home shortcuts match "rate", the HOME header must be hidden!
        if home_header is not None:
            self.assertTrue(home_header.isHidden())

    def test_themed_naming_and_views(self):
        # 1. Test Dojo Theme
        _APP._active_theme = "dojo"
        try:
            dialog = ShortcutSettingsDialog()
            self.assertEqual(dialog.windowTitle(), "Quick Moves")
            self.assertEqual(dialog.btn_full_app.text(), "🌍 All Dojo Moves")
            dialog.close()
            
            # Context specific review button text in Dojo
            from PyQt5.QtWidgets import QWidget
            class MockReviewScreen(QWidget):
                pass
            parent = MockReviewScreen()
            dialog_review = ShortcutSettingsDialog(parent)
            self.assertEqual(dialog_review.btn_current_screen.text(), "⚔ Training Dojo Only")
            dialog_review.close()
        finally:
            if hasattr(_APP, "_active_theme"):
                delattr(_APP, "_active_theme")

        # 2. Test Arcanum Theme
        _APP._active_theme = "arcanum"
        try:
            dialog = ShortcutSettingsDialog()
            self.assertEqual(dialog.windowTitle(), "Glyph Keys")
            self.assertEqual(dialog.btn_full_app.text(), "🌍 All Magic Glyphs")
            dialog.close()
        finally:
            if hasattr(_APP, "_active_theme"):
                delattr(_APP, "_active_theme")


if __name__ == "__main__":
    unittest.main()
