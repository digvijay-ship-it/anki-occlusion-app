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

    def test_visual_diff_helper(self):
        # Instantiating widget (no parent needed for basic helper testing)
        import sys
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        
        widget = TextReviewWidget()
        
        # Exact match
        res_perfect = widget._generate_diff_html("apple", "apple")
        self.assertIn("Perfect Match!", res_perfect)
        self.assertIn("apple", res_perfect)
        
        # Diff matches
        res_diff = widget._generate_diff_html("aple", "apple")
        import re
        plain_text = re.sub('<[^<]+?>', '', res_diff)
        self.assertIn("aple", plain_text)
        self.assertIn("apple", plain_text)
        
if __name__ == "__main__":
    unittest.main()
