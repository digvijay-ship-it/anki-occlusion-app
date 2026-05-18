import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent

from services import shortcut_manager
from ui.review_screen import ReviewScreen


class ReviewScreenRatingButtonTests(unittest.TestCase):
    def setUp(self):
        shortcut_manager.reset_shortcuts()
        self.addCleanup(shortcut_manager.reset_shortcuts)

    def test_review_mode_exposes_five_rating_buttons_and_shortcuts(self):
        self.assertEqual(len(ReviewScreen.RATINGS), 5)
        self.assertEqual(ReviewScreen.RATINGS[-1], ("5  ⭐ Perfect", "perfect", 6))
        self.assertEqual(ReviewScreen.RATING_SHORTCUTS[Qt.Key_5], 6)
        self.assertEqual(ReviewScreen.RATING_LABELS[-1], "Perfect")

    def test_rating_shortcut_uses_saved_binding(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        shortcut_manager.set_shortcut("review.rate_perfect", "P")
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_P, Qt.NoModifier)

        self.assertEqual(screen._rating_quality_for_event(event), 6)


if __name__ == "__main__":
    unittest.main()
