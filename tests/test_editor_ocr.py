import os
import unittest
from unittest.mock import MagicMock, patch
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure QApp exists
_APP = QApplication.instance() or QApplication([])

from ui.editor_dialog import CardEditorDialog

class EditorOcrTests(unittest.TestCase):
    def setUp(self):
        self.dialog = CardEditorDialog()
        self.dialog.inp_title = MagicMock()
        self.dialog.inp_title.text.return_value = ""
        self.dialog._trigger_ocr_for_image = MagicMock()
        self.dialog._schedule_recovery_draft = MagicMock()

    def test_on_ocr_result_updates_title_if_default_or_empty(self):
        # Case 1: Empty title
        self.dialog.inp_title.text.return_value = ""
        self.dialog._on_ocr_result("This is a question?", "Pasted Image")
        self.dialog.inp_title.setText.assert_called_with("This is a question?")
        self.dialog._schedule_recovery_draft.assert_called_with("title")

        # Reset mocks
        self.dialog.inp_title.setText.reset_mock()
        self.dialog._schedule_recovery_draft.reset_mock()

        # Case 2: Title is default "Pasted Image"
        self.dialog.inp_title.text.return_value = "Pasted Image"
        self.dialog._on_ocr_result("This is a question?", "Pasted Image")
        self.dialog.inp_title.setText.assert_called_with("This is a question?")
        self.dialog._schedule_recovery_draft.assert_called_with("title")

        # Reset mocks
        self.dialog.inp_title.setText.reset_mock()
        self.dialog._schedule_recovery_draft.reset_mock()

        # Case 3: Title is default file name
        self.dialog.inp_title.text.return_value = "test_image"
        self.dialog._on_ocr_result("This is a question?", "test_image")
        self.dialog.inp_title.setText.assert_called_with("This is a question?")
        self.dialog._schedule_recovery_draft.assert_called_with("title")

    def test_on_ocr_result_does_not_overwrite_user_edited_title(self):
        self.dialog.inp_title.text.return_value = "User Custom Title"
        self.dialog._on_ocr_result("This is a question?", "Pasted Image")
        self.dialog.inp_title.setText.assert_not_called()
        self.dialog._schedule_recovery_draft.assert_not_called()

    def test_on_ocr_result_handles_empty_ocr_text(self):
        self.dialog.inp_title.text.return_value = ""
        self.dialog._on_ocr_result("", "Pasted Image")
        self.dialog.inp_title.setText.assert_not_called()
        self.dialog._schedule_recovery_draft.assert_not_called()

if __name__ == "__main__":
    unittest.main()
