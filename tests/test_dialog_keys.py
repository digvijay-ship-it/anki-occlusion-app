import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget
from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtGui import QKeyEvent

from services.dialog_key_filter import UniversalDialogKeyFilter, install_dialog_key_filter

_APP = QApplication.instance() or QApplication(sys.argv)
install_dialog_key_filter(_APP)


class DialogKeyFilterTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance()
        install_dialog_key_filter(self.app)

    def test_enter_key_triggers_yes_on_standard_question(self):
        box = QMessageBox(QMessageBox.Question, "Delete Cards Confirmation", "Are you sure?", QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Yes))

    def test_enter_key_triggers_yes_even_if_default_was_no(self):
        box = QMessageBox(QMessageBox.Question, "Delete Cards Confirmation", "Are you sure?", QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Yes))

    def test_escape_key_triggers_no_on_standard_question(self):
        box = QMessageBox(QMessageBox.Question, "Delete Cards Confirmation", "Are you sure?", QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.No))

    def test_enter_key_on_yes_no_cancel_dialog(self):
        box = QMessageBox(QMessageBox.Warning, "Duplicate Card", "Edit existing?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Yes))

    def test_escape_key_on_yes_no_cancel_dialog_triggers_cancel(self):
        box = QMessageBox(QMessageBox.Warning, "Duplicate Card", "Edit existing?", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Cancel))

    def test_enter_key_on_information_dialog_triggers_ok(self):
        box = QMessageBox(QMessageBox.Information, "Info", "Operation complete.", QMessageBox.Ok)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Ok))

    def test_escape_key_on_information_dialog(self):
        box = QMessageBox(QMessageBox.Information, "Info", "Operation complete.", QMessageBox.Ok)
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.app.sendEvent(box, event)
        
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Ok))

    def test_custom_roles_dialog(self):
        box = QMessageBox()
        discard_btn = box.addButton("Discard", QMessageBox.DestructiveRole)
        keep_btn = box.addButton("Keep Draft", QMessageBox.AcceptRole)
        cancel_btn = box.addButton("Cancel Close", QMessageBox.RejectRole)
        
        # Test Enter
        event_enter = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.app.sendEvent(box, event_enter)
        self.assertEqual(box.clickedButton(), keep_btn)
        
        # Reset and test Escape
        box2 = QMessageBox()
        discard_btn2 = box2.addButton("Discard", QMessageBox.DestructiveRole)
        keep_btn2 = box2.addButton("Keep Draft", QMessageBox.AcceptRole)
        cancel_btn2 = box2.addButton("Cancel Close", QMessageBox.RejectRole)
        
        event_esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.app.sendEvent(box2, event_esc)
        self.assertEqual(box2.clickedButton(), cancel_btn2)

    def test_event_sent_to_child_button_still_filters_correctly(self):
        box = QMessageBox(QMessageBox.Question, "Confirm", "Proceed?", QMessageBox.Yes | QMessageBox.No)
        no_btn = box.button(QMessageBox.No)
        no_btn.setFocus()
        
        # Press Enter while No button is focused
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.app.sendEvent(no_btn, event)
        
        # Should click YES, not NO
        self.assertEqual(box.clickedButton(), box.button(QMessageBox.Yes))


if __name__ == "__main__":
    unittest.main()
