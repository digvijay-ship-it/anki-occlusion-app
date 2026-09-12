import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap

_APP = QApplication.instance() or QApplication([])

from ui.review_screen import ReviewScreen
from ui.editor_dialog import CardEditorDialog


class ImageCardCoordinatesTests(unittest.TestCase):
    def setUp(self):
        # Create a small dummy image for testing
        self.test_img_path = os.path.abspath("test_dummy_img.png")
        pix = QPixmap(800, 400)
        pix.fill()
        pix.save(self.test_img_path, "PNG")

        self.card = {
            "_id": 99999,
            "title": "Math Formulas Trigonometry",
            "image_path": self.test_img_path,
            "pdf_path": "some_stale_temp.pdf",
            "boxes": [
                {"rect": [100.0, 50.0, 200.0, 60.0], "box_id": "box-1", "mask_num": 1},
                {"rect": [120.0, 150.0, 250.0, 70.0], "box_id": "box-2", "mask_num": 2},
            ]
        }

    def tearDown(self):
        if os.path.exists(self.test_img_path):
            try:
                os.remove(self.test_img_path)
            except Exception:
                pass

    def test_review_screen_prioritizes_image_path_over_pdf(self):
        """Verify ReviewScreen._load_card chooses image branch even if pdf_path is present."""
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [self.card], "children": []}]}
        rs = ReviewScreen([self.card], data=data)
        
        with patch.object(rs, "_apply_canvas") as mock_apply_canvas, \
             patch.object(rs, "_start_review_skeleton_thread") as mock_start_skel:
            rs._items = [(self.card, 0, self.card)]
            rs._idx = 0
            rs._reload_current_canvas(0)
            mock_apply_canvas.assert_called_once()
            mock_start_skel.assert_not_called()
            # Verify the pixmap passed is the actual image
            args, _ = mock_apply_canvas.call_args
            loaded_card, box_idx, px = args
            self.assertEqual(loaded_card["_id"], self.card["_id"])
            self.assertEqual(px.width(), 800)
            self.assertEqual(px.height(), 400)
        rs.deleteLater()

    def test_editor_dialog_clears_stale_pdf_path_on_load_and_save(self):
        """Verify CardEditorDialog purges stale pdf_path when an image card is edited."""
        card_copy = dict(self.card)
        dialog = CardEditorDialog(card=card_copy)
        # On load, stale pdf_path should be cleared
        self.assertNotIn("pdf_path", dialog.card)
        self.assertNotIn("_pdf_box_render_zoom", dialog.card)

        # On save, stale pdf_path should remain purged
        with patch.object(dialog, "_write_recovery_checkpoint"), \
             patch("data_manager.store.mark_dirty"), \
             patch("data_manager.store.save_soon"):
            dialog._save(keep_open=True)
            self.assertNotIn("pdf_path", dialog.card)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
