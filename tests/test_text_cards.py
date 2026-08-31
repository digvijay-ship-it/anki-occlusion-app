import unittest
from models import Card
from ui.text_review_widget import TextReviewWidget

class TestTextCards(unittest.TestCase):
    def test_card_model_text_fields(self):
        # 1. Create a card with text fields
        card = Card(
            _id="text_card_1",
            title="Python Dataclasses",
            card_type="text",
            question="What is a dataclass?",
            answer="A class decorator that automates boilerplate like __init__ and __repr__.",
            notes="Introduced in Python 3.7",
            tags=["python", "oop"]
        )
        
        # 2. Convert to dictionary
        data_dict = card.to_dict()
        self.assertEqual(data_dict["card_type"], "text")
        self.assertEqual(data_dict["question"], "What is a dataclass?")
        self.assertEqual(data_dict["answer"], "A class decorator that automates boilerplate like __init__ and __repr__.")
        
        # 3. Load back from dict
        loaded_card = Card.from_dict(data_dict)
        self.assertEqual(loaded_card.card_type, "text")
        self.assertEqual(loaded_card.question, "What is a dataclass?")
        self.assertEqual(loaded_card.answer, "A class decorator that automates boilerplate like __init__ and __repr__.")
        self.assertEqual(loaded_card.notes, "Introduced in Python 3.7")
        self.assertEqual(loaded_card.tags, ["python", "oop"])

    def test_text_review_widget_load_and_reveal(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        card = {
            "card_type": "text",
            "question": "What is 2+2?",
            "answer": "4",
            "notes": "Basic addition"
        }
        
        widget.load_card(card)
        self.assertFalse(widget.is_revealed)
        self.assertTrue(widget.answer_container.isHidden())
        self.assertIn("What is 2+2?", widget.q_browser.toPlainText())
        
        widget.reveal_answer()
        self.assertTrue(widget.is_revealed)
        self.assertFalse(widget.answer_container.isHidden())
        self.assertIn("4", widget.a_browser.toPlainText())
        self.assertIn("Basic addition", widget.notes_browser.toPlainText())

    def test_text_review_widget_hide_answer_toggle(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        card = {
            "card_type": "text",
            "question": "What is the capital of India?",
            "answer": "New Delhi",
            "trap_note": "Don't confuse with Mumbai",
            "notes": "Established in 1911"
        }
        
        widget.load_card(card)
        self.assertFalse(widget.is_revealed)
        self.assertTrue(widget.answer_container.isHidden())
        
        # 1. Reveal
        widget.reveal_answer()
        self.assertTrue(widget.is_revealed)
        self.assertFalse(widget.answer_container.isHidden())
        self.assertIn("New Delhi", widget.a_browser.toPlainText())
        self.assertIn("Mumbai", widget.trap_browser.toPlainText())
        
        # 2. Hide (toggle back on space)
        widget.hide_answer()
        self.assertFalse(widget.is_revealed)
        self.assertTrue(widget.answer_container.isHidden())
        self.assertEqual(widget.a_browser.toPlainText().strip(), "")
        self.assertEqual(widget.trap_browser.toPlainText().strip(), "")
        self.assertEqual(widget.notes_browser.toPlainText().strip(), "")
        
        # 3. Reveal again
        widget.reveal_answer()
        self.assertTrue(widget.is_revealed)
        self.assertFalse(widget.answer_container.isHidden())
        self.assertIn("New Delhi", widget.a_browser.toPlainText())
        self.assertIn("Mumbai", widget.trap_browser.toPlainText())

    def test_image_scaling_replaces_with_pixel_width(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        html_input = '<p>Check this image:</p><img src="images/test.png" style="max-width: 100%;" />'
        widget._scale_and_load_html(widget.q_browser, html_input, 1200)
        
        # Verify the HTML in the browser has style removed from img tags
        html_output = widget.q_browser.toHtml()
        self.assertNotIn('max-width', html_output)
        self.assertIn('test.png', html_output)

    def test_text_card_zoom_persistence(self):
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        # Reset and verify default
        TextReviewWidget.save_zoom_factor(1.0)
        widget1 = TextReviewWidget()
        self.assertAlmostEqual(widget1._zoom_factor, 1.0)

        # Zoom in twice (1.0 -> 1.1 -> 1.2)
        widget1.zoom_in()
        widget1.zoom_in()
        self.assertAlmostEqual(widget1._zoom_factor, 1.2)
        self.assertAlmostEqual(TextReviewWidget.get_saved_zoom_factor(), 1.2)

        # Create a new widget (simulating opening another deck or next review session)
        widget2 = TextReviewWidget()
        self.assertAlmostEqual(widget2._zoom_factor, 1.2)

        card = {
            "card_type": "text",
            "question": "What is Python?",
            "answer": "A programming language."
        }
        widget2.load_card(card)
        self.assertAlmostEqual(widget2._zoom_factor, 1.2)

        # Test zoom reset
        widget2.zoom_reset()
        self.assertAlmostEqual(widget2._zoom_factor, 1.0)
        self.assertAlmostEqual(TextReviewWidget.get_saved_zoom_factor(), 1.0)


if __name__ == "__main__":
    unittest.main()
