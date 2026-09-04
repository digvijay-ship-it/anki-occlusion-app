import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QWidget

from ui.review_screen import ReviewScreen
from ui.text_review_widget import TextReviewWidget

_APP = QApplication.instance() or QApplication([])


class ReviewScreenSyncTests(unittest.TestCase):
    def test_sync_button_exists_on_text_review_widget(self):
        widget = TextReviewWidget()
        self.assertTrue(hasattr(widget, "btn_sync_deck"))
        self.assertIn("Sync Deck", widget.btn_sync_deck.text())

    def test_sync_shortcut_keys(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        QWidget.__init__(screen)
        screen._sync_current_deck_from_source = MagicMock()
        
        # Test F5
        f5_event = QKeyEvent(QEvent.KeyPress, Qt.Key_F5, Qt.NoModifier)
        ReviewScreen.keyPressEvent(screen, f5_event)
        screen._sync_current_deck_from_source.assert_called_once()
        
        # Test Alt+R
        screen._sync_current_deck_from_source.reset_mock()
        alt_r_event = QKeyEvent(QEvent.KeyPress, Qt.Key_R, Qt.AltModifier)
        ReviewScreen.keyPressEvent(screen, alt_r_event)
        screen._sync_current_deck_from_source.assert_called_once()

    def test_sync_current_deck_updates_card_and_reloads(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        QWidget.__init__(screen)
        test_card = {
            "_id": "card-123",
            "card_uid": "card-123",
            "card_type": "text",
            "question": "Old Q",
            "answer": "Old A",
            "deck_uid": "deck-456",
            "deck_name": "Test Deck"
        }
        test_deck = {
            "name": "Test Deck",
            "deck_uid": "deck-456",
            "source_file_path": "test.json",
            "cards": [test_card]
        }
        
        mock_mgr = MagicMock()
        mock_mgr._items = [(test_card, None, {})]
        mock_mgr._idx = 0
        screen.mgr = mock_mgr
        screen._data = {"decks": [test_deck]}
        screen._text_card_cache = {}
        screen._show_review_toast = MagicMock()
        screen._load_item = MagicMock()
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = True
        screen._reveal_current = MagicMock()

        with patch("data_manager.sync_deck_from_source_folder") as mock_sync, \
             patch("data_manager.store.save_force"), \
             patch("os.path.exists", return_value=True):
            
            mock_sync.return_value = {"status": "ok", "updated_count": 1, "new_count": 0}
            
            screen._sync_current_deck_from_source()
            
            mock_sync.assert_called_once()
            screen._load_item.assert_called_once()
            screen._reveal_current.assert_called_once()
            screen._show_review_toast.assert_called_once()
            self.assertIn("Synced", screen._show_review_toast.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
