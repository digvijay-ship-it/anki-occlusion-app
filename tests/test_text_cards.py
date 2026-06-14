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
        
if __name__ == "__main__":
    unittest.main()
