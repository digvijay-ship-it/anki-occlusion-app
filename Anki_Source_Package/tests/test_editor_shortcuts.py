import os
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt, QPointF, QEvent
from PyQt5.QtGui import QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication, QLineEdit

from editor_ui import OcclusionCanvas, MaskPanel, _ZoomableScrollArea
from ui.editor_dialog import CardEditorDialog

_APP = QApplication.instance() or QApplication([])


class EditorShortcutsTests(unittest.TestCase):
    def setUp(self):
        self.canvas = OcclusionCanvas()
        self.canvas._show_toast = lambda _msg: None
        px = QPixmap(200, 200)
        px.fill(Qt.white)
        self.canvas.load_pixmap(px)
        self.canvas.set_boxes([
            {"rect": [10, 10, 30, 30], "label": "Box1", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b1"},
            {"rect": [50, 50, 30, 30], "label": "Box2", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b2"},
            {"rect": [90, 90, 30, 30], "label": "Box3", "shape": "rect", "angle": 0, "group_id": "", "box_id": "b3"},
        ])

    def test_canvas_key_press_g_groups_selected_boxes(self):
        self.canvas._selected_indices = {0, 1}
        self.canvas._selected_idx = 1
        
        # Press G
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.NoModifier)
        self.canvas.keyPressEvent(event)
        
        boxes = self.canvas.get_boxes()
        self.assertTrue(bool(boxes[0].get("group_id")))
        self.assertEqual(boxes[0]["group_id"], boxes[1]["group_id"])
        self.assertEqual(boxes[2].get("group_id", ""), "")

    def test_canvas_key_press_shift_g_ungroups_selected_boxes(self):
        self.canvas._boxes[0]["group_id"] = "group_123"
        self.canvas._boxes[1]["group_id"] = "group_123"
        self.canvas._selected_indices = {0, 1}
        self.canvas._selected_idx = 1
        
        # Press Shift+G
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.ShiftModifier)
        self.canvas.keyPressEvent(event)
        
        boxes = self.canvas.get_boxes()
        self.assertEqual(boxes[0].get("group_id", ""), "")
        self.assertEqual(boxes[1].get("group_id", ""), "")

    def test_canvas_key_release_no_crash(self):
        # Previously keyReleaseEvent crashed with NameError: name 'key' is not defined
        event = QKeyEvent(QEvent.KeyRelease, Qt.Key_G, Qt.NoModifier)
        try:
            self.canvas.keyReleaseEvent(event)
        except Exception as e:
            self.fail(f"keyReleaseEvent raised unexpected exception: {e}")

    def test_canvas_delete_and_backspace_keys(self):
        self.canvas._selected_indices = {1}
        self.canvas._selected_idx = 1
        
        del_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        self.canvas.keyPressEvent(del_event)
        self.assertEqual(len(self.canvas.get_boxes()), 2)
        
        self.canvas._selected_indices = {0}
        self.canvas._selected_idx = 0
        backspace_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier)
        self.canvas.keyPressEvent(backspace_event)
        self.assertEqual(len(self.canvas.get_boxes()), 1)

    def test_canvas_alt_click_multi_selection(self):
        # Plain click selects box 0 solo
        ev1 = QMouseEvent(QEvent.MouseButtonPress, QPointF(25, 25), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        self.canvas.mousePressEvent(ev1)
        self.assertEqual(self.canvas._selected_idx, 0)
        
        # Alt+Click on box 1 adds box 1 to selection
        ev2 = QMouseEvent(QEvent.MouseButtonPress, QPointF(65, 65), Qt.LeftButton, Qt.LeftButton, Qt.AltModifier)
        self.canvas.mousePressEvent(ev2)
        all_selected = self.canvas._get_all_selected()
        self.assertIn(0, all_selected)
        self.assertIn(1, all_selected)

    def test_mask_panel_multi_selection_and_g_key(self):
        panel = MaskPanel(self.canvas)
        # Select items 0 and 1 in list
        panel.list_w.item(0).setSelected(True)
        panel.list_w.item(1).setSelected(True)
        
        all_selected = self.canvas._get_all_selected()
        self.assertIn(0, all_selected)
        self.assertIn(1, all_selected)
        
        # Send G key event to list_w
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.NoModifier)
        res = panel.eventFilter(panel.list_w, event)
        self.assertTrue(res)
        
        boxes = self.canvas.get_boxes()
        self.assertTrue(bool(boxes[0].get("group_id")))
        self.assertEqual(boxes[0]["group_id"], boxes[1]["group_id"])

    def test_editor_dialog_key_press_g_groups_masks(self):
        with patch.object(CardEditorDialog, "_setup_recovery_autosave"):
            dlg = CardEditorDialog(card={"boxes": [
                {"rect": [10, 10, 20, 20], "label": "", "group_id": "", "box_id": "1"},
                {"rect": [40, 40, 20, 20], "label": "", "group_id": "", "box_id": "2"},
            ]})
            dlg.canvas.load_pixmap(self.canvas._px)
            dlg.canvas.set_boxes([
                {"rect": [10, 10, 20, 20], "label": "", "group_id": "", "box_id": "1"},
                {"rect": [40, 40, 20, 20], "label": "", "group_id": "", "box_id": "2"},
            ])
            dlg.canvas._selected_indices = {0, 1}
            dlg.canvas._selected_idx = 1
            
            # Press G on dialog
            event = QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.NoModifier)
            dlg.keyPressEvent(event)
            
            boxes = dlg.canvas.get_boxes()
            self.assertTrue(bool(boxes[0].get("group_id")))
            self.assertEqual(boxes[0]["group_id"], boxes[1]["group_id"])

    def test_editor_dialog_plain_t_selects_text_tool_without_opening_annotate(self):
        with patch.object(CardEditorDialog, "_setup_recovery_autosave"), \
             patch.object(CardEditorDialog, "_open_annotation_beta") as mock_annot:
            dlg = CardEditorDialog(card={})
            
            # Press T on dialog
            event = QKeyEvent(QEvent.KeyPress, Qt.Key_T, Qt.NoModifier)
            dlg.keyPressEvent(event)
            
            mock_annot.assert_not_called()
            self.assertEqual(dlg.canvas._tool, "text")

    def test_editor_dialog_typing_guard_prevents_shortcuts_when_input_focused(self):
        with patch.object(CardEditorDialog, "_setup_recovery_autosave"):
            dlg = CardEditorDialog(card={"boxes": [
                {"rect": [10, 10, 20, 20], "label": "", "group_id": "", "box_id": "1"},
                {"rect": [40, 40, 20, 20], "label": "", "group_id": "", "box_id": "2"},
            ]})
            dlg.canvas.load_pixmap(self.canvas._px)
            dlg.canvas.set_boxes([
                {"rect": [10, 10, 20, 20], "label": "", "group_id": "", "box_id": "1"},
                {"rect": [40, 40, 20, 20], "label": "", "group_id": "", "box_id": "2"},
            ])
            dlg.canvas._selected_indices = {0, 1}
            
            # Focus on title input
            dlg.inp_title.setFocus()
            with patch.object(dlg, "focusWidget", return_value=dlg.inp_title):
                # Press G while typing
                event = QKeyEvent(QEvent.KeyPress, Qt.Key_G, Qt.NoModifier)
                dlg.keyPressEvent(event)
                
                # Masks should NOT be grouped!
                boxes = dlg.canvas.get_boxes()
                self.assertEqual(boxes[0].get("group_id", ""), "")


if __name__ == "__main__":
    unittest.main()
