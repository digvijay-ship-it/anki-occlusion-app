import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QListWidget
from editor_ui import OcclusionCanvas, MaskPanel
from services.review_manager import ReviewSessionManager

_APP = QApplication.instance() or QApplication([])


class PersistentMaskNumberingTests(unittest.TestCase):
    def test_legacy_boxes_auto_assigned_mask_numbers(self):
        canvas = OcclusionCanvas()
        legacy_boxes = [
            {"rect": [10, 10, 50, 50], "label": ""},
            {"rect": [20, 20, 50, 50], "label": ""},
            {"rect": [30, 30, 50, 50], "label": ""},
        ]
        canvas.set_boxes(legacy_boxes)
        boxes = canvas.get_boxes()
        self.assertEqual(boxes[0]["mask_num"], 1)
        self.assertEqual(boxes[1]["mask_num"], 2)
        self.assertEqual(boxes[2]["mask_num"], 3)

    def test_deleting_intermediate_mask_preserves_higher_mask_numbers(self):
        canvas = OcclusionCanvas()
        boxes = [{"rect": [i * 10, 10, 50, 50], "label": ""} for i in range(15)]
        canvas.set_boxes(boxes)

        self.assertEqual(canvas.get_boxes()[13]["mask_num"], 14)
        self.assertEqual(canvas.get_boxes()[14]["mask_num"], 15)

        # Delete box 14 (index 13)
        canvas.delete_box(13)

        remaining = canvas.get_boxes()
        self.assertEqual(len(remaining), 14)
        # Box that was previously at index 14 is now at index 13, but its mask_num MUST still be 15
        self.assertEqual(remaining[13]["mask_num"], 15)

    def test_mask_panel_displays_stable_mask_numbers(self):
        canvas = OcclusionCanvas()
        boxes = [{"rect": [i * 10, 10, 50, 50], "label": ""} for i in range(15)]
        canvas.set_boxes(boxes)
        panel = MaskPanel(canvas)
        panel._refresh(canvas.get_boxes())

        self.assertIn("Mask #14", panel.list_w.item(13).text())
        self.assertIn("Mask #15", panel.list_w.item(14).text())

        # Delete box 14 (index 13)
        canvas.delete_box(13)
        panel._refresh(canvas.get_boxes())

        self.assertEqual(panel.list_w.count(), 14)
        # The last item (index 13) must still be Mask #15!
        self.assertIn("Mask #15", panel.list_w.item(13).text())

    def test_new_mask_after_deletion_takes_next_highest_number(self):
        canvas = OcclusionCanvas()
        boxes = [{"rect": [i * 10, 10, 50, 50], "label": ""} for i in range(15)]
        canvas.set_boxes(boxes)
        canvas.delete_box(13)

        existing_nums = [
            bx.get("mask_num") for bx in canvas._boxes
            if isinstance(bx.get("mask_num"), int) and bx.get("mask_num") > 0
        ]
        next_num = (max(existing_nums) + 1) if existing_nums else (len(canvas._boxes) + 1)
        self.assertEqual(next_num, 16)

    def test_review_manager_queue_label_uses_mask_num(self):
        rs = MagicMock()
        rs._queue_list = QListWidget()
        manager = ReviewSessionManager(rs)
        card = {
            "_id": 1,
            "boxes": [
                {"box_id": "b1", "mask_num": 1, "sched_state": "review"},
                {"box_id": "b15", "mask_num": 15, "sched_state": "review"},
            ]
        }
        manager._items = [(card, 1, card["boxes"][1])]
        manager._idx = 0
        manager._rebuild_queue()

        item_text = rs._queue_list.item(0).text()
        self.assertIn("#15", item_text)


if __name__ == "__main__":
    unittest.main()
