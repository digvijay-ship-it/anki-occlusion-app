import sys
import unittest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPoint, QPointF
from PyQt5.QtGui import QColor, QWheelEvent
from PyQt5.QtTest import QTest

from ui.text_review_widget import TextReviewWidget, ScratchpadOverlay
from ui.mcq_review_widget import MCQReviewWidget

app = QApplication.instance() or QApplication(sys.argv)

class TestScratchpadScroll(unittest.TestCase):
    def test_scratchpad_parentage_and_dynamic_growth(self):
        trw = TextReviewWidget()
        try:
            # Scratchpad must be parented to scroll_content
            self.assertEqual(trw.scratchpad.parent(), trw.scroll_content)

            # Load a text card
            long_answer = "<p>Answer Line</p>\n" * 40
            card = {
                "_id": "test_card_1",
                "card_type": "text",
                "question": "Test Question Header",
                "answer": long_answer,
                "context_anchor": "Economics"
            }
            trw.load_card(card)
            trw.resize(800, 600)
            trw.show()
            app.processEvents()

            initial_height = trw.scroll_content.height()
            self.assertEqual(trw.scratchpad.height(), initial_height)

            # Reveal answer - card expands vertically
            trw.reveal_answer()
            app.processEvents()

            revealed_height = trw.scroll_content.height()
            self.assertGreaterEqual(revealed_height, initial_height)
            self.assertEqual(trw.scratchpad.height(), revealed_height,
                             "Scratchpad height must dynamically match the expanded card scroll content height")
            self.assertEqual(trw.scratchpad.width(), trw.scroll_content.width())
        finally:
            trw.close()

    def test_scratchpad_scrolls_with_page(self):
        trw = TextReviewWidget()
        try:
            long_text = "<p>Line</p>\n" * 80
            card = {
                "_id": "test_card_2",
                "card_type": "text",
                "question": long_text,
                "answer": "Short Answer"
            }
            trw.load_card(card)
            trw.resize(800, 500)
            trw.show()
            app.processEvents()

            # Confirm scrollable
            vb = trw.scroll_area.verticalScrollBar()
            self.assertGreater(vb.maximum(), 0, "Card content must be tall enough to produce a vertical scrollbar")

            # Check initial position relative to scroll area viewport
            initial_overlay_pos_in_viewport = trw.scratchpad.mapTo(trw.scroll_area.viewport(), QPoint(0, 0))
            self.assertEqual(initial_overlay_pos_in_viewport.y(), 0)

            # Scroll down by 150px
            vb.setValue(150)
            app.processEvents()

            # The overlay must have scrolled up by 150px relative to the viewport
            scrolled_overlay_pos_in_viewport = trw.scratchpad.mapTo(trw.scroll_area.viewport(), QPoint(0, 0))
            self.assertEqual(scrolled_overlay_pos_in_viewport.y(), -150,
                             "Scratchpad overlay must move directly with the scrollbar value relative to the viewport")
        finally:
            trw.close()

    def test_strokes_anchor_to_content(self):
        trw = TextReviewWidget()
        try:
            long_text = "<p>Line</p>\n" * 80
            card = {
                "_id": "test_card_3",
                "card_type": "text",
                "question": long_text,
                "answer": "Answer"
            }
            trw.load_card(card)
            trw.resize(800, 500)
            trw.show()
            app.processEvents()

            # Activate pen
            trw.scratchpad.set_pen_active(True, mode="pen")
            self.assertFalse(trw.scratchpad.testAttribute(Qt.WA_TransparentForMouseEvents))

            # Simulate drawing a stroke at content coordinate (100, 50)
            stroke_point = QPoint(100, 50)
            QTest.mousePress(trw.scratchpad, Qt.LeftButton, pos=stroke_point)
            stroke_point_2 = QPoint(120, 70)
            QTest.mouseMove(trw.scratchpad, pos=stroke_point_2)
            QTest.mouseRelease(trw.scratchpad, Qt.LeftButton, pos=stroke_point_2)

            self.assertEqual(len(trw.scratchpad.strokes), 1)
            first_stroke_points = trw.scratchpad.strokes[0]["points"]
            self.assertEqual(first_stroke_points[0], stroke_point)

            # Scroll down
            vb = trw.scroll_area.verticalScrollBar()
            vb.setValue(100)
            app.processEvents()

            # Stroke points in scratchpad local coordinates remain anchored
            self.assertEqual(trw.scratchpad.strokes[0]["points"][0], stroke_point)

            # In viewport coordinates, the stroke has shifted up by 100px with the text!
            pt_in_viewport = trw.scratchpad.mapTo(trw.scroll_area.viewport(), first_stroke_points[0])
            self.assertEqual(pt_in_viewport.y(), 50 - 100)
        finally:
            trw.close()

    def test_mcq_scratchpad_parentage_and_dynamic_growth(self):
        mcq = MCQReviewWidget()
        try:
            self.assertEqual(mcq.scratchpad.parent(), mcq.scroll_content)

            card = {
                "_id": "mcq_1",
                "card_type": "mcq",
                "question": "What is the capital of France?",
                "options": [
                    {"label": "A", "text": "Paris", "is_correct": True},
                    {"label": "B", "text": "London"},
                    {"label": "C", "text": "Berlin"},
                    {"label": "D", "text": "Madrid"}
                ],
                "explanation": "<p>Detailed explanation line</p>\n" * 30
            }
            mcq.load_card(card)
            mcq.resize(800, 500)
            mcq.show()
            app.processEvents()

            initial_h = mcq.scroll_content.height()
            self.assertEqual(mcq.scratchpad.height(), initial_h)

            mcq.reveal_answer()
            app.processEvents()

            rev_h = mcq.scroll_content.height()
            self.assertGreaterEqual(rev_h, initial_h)
            self.assertEqual(mcq.scratchpad.height(), rev_h)
        finally:
            mcq.close()

    def test_wheel_event_scrolling_when_pen_active(self):
        trw = TextReviewWidget()
        try:
            long_text = "<p>Line</p>\n" * 80
            card = {
                "_id": "test_card_4",
                "card_type": "text",
                "question": long_text,
                "answer": "Answer"
            }
            trw.load_card(card)
            trw.resize(800, 500)
            trw.show()
            app.processEvents()

            trw.scratchpad.set_pen_active(True, mode="pen")
            vb = trw.scroll_area.verticalScrollBar()
            initial_val = vb.value()

            # Synthesize wheel down event (-120 angle delta)
            wheel_event = QWheelEvent(
                QPointF(200, 200),
                QPointF(200, 200),
                QPoint(0, 0),
                QPoint(0, -120),
                0,
                Qt.Vertical,
                Qt.NoButton,
                Qt.NoModifier
            )
            trw.scratchpad.wheelEvent(wheel_event)
            self.assertGreater(vb.value(), initial_val, "Wheel event on scratchpad must scroll the scroll area")
        finally:
            trw.close()

if __name__ == "__main__":
    unittest.main()
