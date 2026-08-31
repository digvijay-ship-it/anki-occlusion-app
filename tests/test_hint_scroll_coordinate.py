# -*- coding: utf-8 -*-
import sys
import unittest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication

from ui.review_screen import ReviewScreen

app = QApplication.instance() or QApplication(sys.argv)

class TestHintScrollCoordinate(unittest.TestCase):
    def setUp(self):
        self.deck = {
            "_id": 999,
            "name": "Test Hint Deck",
            "cards": [
                {
                    "_id": "card_1",
                    "card_type": "text",
                    "question": "Question 1",
                    "answer": "Answer 1",
                    "notes": "<p>" + "Long note line content<br>" * 50 + "</p>"
                },
                {
                    "_id": "card_2",
                    "card_type": "text",
                    "question": "Question 2",
                    "answer": "Answer 2",
                    "notes": "<p>" + "Another note content<br>" * 50 + "</p>"
                }
            ]
        }
        self.screen = ReviewScreen(self.deck["cards"], data={"decks": [self.deck]}, parent=None)
        self.screen.resize(1000, 800)
        self.screen.show()
        QCoreApplication.processEvents()

    def tearDown(self):
        self.screen.hide()
        self.screen.deleteLater()

    def test_hint_scroll_preserved_on_toggle_and_reset_on_question_change(self):
        QCoreApplication.processEvents()

        self.assertEqual(self.screen._idx, 0)
        self.assertFalse(self.screen._hint_panel.isVisible())

        # 1. Press 'N' to open hint panel
        self.screen._toggle_hint_panel()
        QCoreApplication.processEvents()
        self.assertTrue(self.screen._hint_panel.isVisible())

        # 2. Scroll hint browser down to coordinate 250
        max_scroll = self.screen._hint_browser.verticalScrollBar().maximum()
        target_pos = min(250, max_scroll) if max_scroll > 0 else 100
        self.screen._hint_browser.verticalScrollBar().setValue(target_pos)
        self.screen._on_hint_scrolled(target_pos)
        QCoreApplication.processEvents()

        curr_key_0 = self.screen._get_current_hint_key()
        self.assertEqual(self.screen._hint_scroll_positions.get(curr_key_0), target_pos)

        # 3. Press 'N' to close hint panel
        self.screen._toggle_hint_panel()
        QCoreApplication.processEvents()
        self.assertFalse(self.screen._hint_panel.isVisible())
        # The coordinate is still remembered in RAM for question 0
        self.assertEqual(self.screen._hint_scroll_positions.get(curr_key_0), target_pos)

        # 4. Press 'N' again to reopen hint panel on the same card
        self.screen._toggle_hint_panel()
        for _ in range(10):
            QCoreApplication.processEvents()
            app.processEvents()

        self.assertTrue(self.screen._hint_panel.isVisible())
        restored_pos = self.screen._hint_browser.verticalScrollBar().value()
        self.assertEqual(restored_pos, target_pos)

        # 5. Move to NEXT question (advance to card index 1)
        self.screen._idx = 1
        self.screen._load_item()
        QCoreApplication.processEvents()

        # Coordinate from card 0 was wiped from RAM
        self.assertIsNone(self.screen._hint_scroll_positions.get(curr_key_0))
        # Card 1 starts at top (0)
        self.assertEqual(self.screen._hint_scroll_positions.get(1, 0), 0)
        self.assertEqual(self.screen._hint_browser.verticalScrollBar().value(), 0)

if __name__ == "__main__":
    unittest.main()
