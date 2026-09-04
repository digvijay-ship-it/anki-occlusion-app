import os
import sys
import unittest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor

from ui.canvas.core import OcclusionCanvas as Canvas
from ui.text_review_widget import ScratchpadOverlay, TextReviewWidget
from ui.review_screen import ReviewScreen

app = QApplication.instance() or QApplication(sys.argv)

class TestDrawingToolStatePreservation(unittest.TestCase):
    def test_canvas_ink_mode_not_clobbered_by_set_active(self):
        canvas = Canvas()
        canvas.ink_set_active(True, mode="pen")
        self.assertTrue(canvas._ink_active)
        self.assertEqual(canvas.ink_get_mode(), "pen")

        canvas.ink_set_mode("eraser")
        self.assertEqual(canvas.ink_get_mode(), "eraser")

        canvas.ink_set_active(False)
        self.assertFalse(canvas._ink_active)
        self.assertEqual(canvas.ink_get_mode(), "eraser", "Deactivating ink must NOT clobber eraser mode to pen")

        canvas.ink_set_active(True)
        self.assertTrue(canvas._ink_active)
        self.assertEqual(canvas.ink_get_mode(), "eraser", "Reactivating ink must preserve eraser mode")

    def test_canvas_set_mode_review_preserves_eraser_cursor(self):
        canvas = Canvas()
        canvas.ink_set_active(True, mode="eraser")
        canvas.set_mode("review")
        self.assertTrue(canvas._ink_active)
        self.assertEqual(canvas.ink_get_mode(), "eraser")

    def test_scratchpad_overlay_undo_redo(self):
        overlay = ScratchpadOverlay()
        overlay.set_pen_active(True, mode="pen")
        self.assertEqual(overlay.mode, "pen")
        self.assertFalse(overlay.has_undo())
        self.assertFalse(overlay.has_redo())

        overlay.strokes.append({
            "color": QColor("#FF0000"),
            "width": 2.0,
            "points": [QPointF(10, 10), QPointF(20, 20)]
        })
        self.assertTrue(overlay.has_undo())
        self.assertEqual(len(overlay.strokes), 1)

        undone = overlay.undo()
        self.assertTrue(undone)
        self.assertEqual(len(overlay.strokes), 0)
        self.assertTrue(overlay.has_redo())

        redone = overlay.redo()
        self.assertTrue(redone)
        self.assertEqual(len(overlay.strokes), 1)
        self.assertFalse(overlay.has_redo())

    def test_scratchpad_overlay_mode_preservation(self):
        overlay = ScratchpadOverlay()
        overlay.set_pen_active(True, mode="eraser")
        self.assertEqual(overlay.mode, "eraser")
        overlay.set_pen_active(True, mode="pen")
        self.assertEqual(overlay.mode, "pen")

    def test_review_screen_tool_persistence(self):
        cards = [
            {"_id": "c1", "card_type": "text", "question": "Q1", "answer": "A1"},
            {"_id": "c2", "card_type": "text", "question": "Q2", "answer": "A2"}
        ]
        rs = ReviewScreen(cards=cards)
        try:
            # Default tool on review start is pen
            self.assertEqual(rs.get_active_tool(), "pen")

            # Switch to mouse
            rs.set_active_tool("mouse")
            self.assertEqual(rs.get_active_tool(), "mouse")

            # Switch back to pen
            rs.set_active_tool("pen")
            self.assertEqual(rs.get_active_tool(), "pen")

            rs._idx = 1
            rs._load_item()
            self.assertEqual(rs.get_active_tool(), "pen", "Pen mode must persist across card transitions")
            self.assertTrue(rs._text_review_widget.scratchpad.mode == "pen")

            rs.set_active_tool("eraser")
            self.assertEqual(rs.get_active_tool(), "eraser")

            rs._idx = 0
            rs._load_item()
            self.assertEqual(rs.get_active_tool(), "eraser", "Eraser mode must persist across card transitions")
            self.assertTrue(rs._text_review_widget.scratchpad.mode == "eraser")

            rs._review_undo()
            self.assertEqual(rs.get_active_tool(), "eraser", "Eraser mode must persist after undo")

            rs._review_redo()
            self.assertEqual(rs.get_active_tool(), "eraser", "Eraser mode must persist after redo")

            rs._toggle_pen_drawing()
            self.assertEqual(rs.get_active_tool(), "pen", "Toggling pen from eraser must switch to pen")

            rs._review_undo()
            self.assertEqual(rs.get_active_tool(), "pen", "Pen mode must persist after undo")
            rs._review_redo()
            self.assertEqual(rs.get_active_tool(), "pen", "Pen mode must persist after redo")

            # Test text card scratchpad stroke undo
            rs._idx = 0
            rs._load_item()
            sp = rs._text_review_widget.scratchpad
            sp.strokes.append({
                "color": QColor("#FF0000"),
                "width": 2.0,
                "points": [QPointF(0, 0), QPointF(10, 10)]
            })
            self.assertEqual(len(sp.strokes), 1)
            # When stroke exists, _review_undo() must NOT undo ink strokes
            rs._review_undo()
            self.assertEqual(len(sp.strokes), 1, "Review undo must NOT undo scratchpad strokes; ink is only erased with eraser/clear")
            self.assertEqual(rs.get_active_tool(), "pen", "Tool mode should remain pen")

            # Redo must also NOT affect scratchpad strokes
            rs._review_redo()
            self.assertEqual(len(sp.strokes), 1, "Review redo must NOT affect scratchpad strokes")
            self.assertEqual(rs.get_active_tool(), "pen", "Tool mode should remain pen")

            # Test editor dialog finish preservation
            from PyQt5.QtWidgets import QDialog
            class MockDialog:
                def get_card(self):
                    return {"_id": "c1", "card_type": "text", "question": "Q1 edited", "answer": "A1"}
                def deleteLater(self):
                    pass
            rs.set_active_tool("eraser")
            rs._finish_edit_current_text_card(MockDialog(), rs._items[0][0], QDialog.Accepted)
            self.assertEqual(rs.get_active_tool(), "eraser", "Eraser mode must persist after card editor save")
        finally:
            rs.close()

if __name__ == "__main__":
    unittest.main()
