"""
Unit tests for Socratic AI Study Buddy (services/ai_coach_service.py,
services/voice_input_service.py, and ui/review/ai_buddy_drawer.py).
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from PyQt5.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication(sys.argv)

from services.ai_coach_service import (
    get_ai_settings, save_ai_settings, strip_html_tags, build_card_context,
    AICoachWorker, DEFAULT_MODEL
)
from ui.review.ai_buddy_drawer import AIBuddyDrawer, AISettingsDialog


class TestAICoachService(unittest.TestCase):

    def test_strip_html_tags(self):
        html_input = "<p>Hello <b>World</b>!<br>Next line <div>Item</div></p>"
        res = strip_html_tags(html_input)
        self.assertIn("Hello World!", res)
        self.assertIn("Next line", res)
        self.assertNotIn("<p>", res)
        self.assertNotIn("<b>", res)

    def test_build_card_context_text_card(self):
        card = {
            "card_type": "text",
            "question": "<b>Who was Chandragupta I?</b>",
            "answer": "Founder of <span style='color:red;'>Gupta Era</span> in 319-320 AD",
            "notes": "Title: Maharajadhiraja",
            "mnemonics": "Chandra = Moon = Gold/Gupta",
            "tags": ["Ancient_History", "Gupta_Era"]
        }
        ctx = build_card_context(card, deck_name="Ancient History")
        self.assertEqual(ctx["deck_name"], "Ancient History")
        self.assertEqual(ctx["card_type"], "text")
        self.assertEqual(ctx["question"], "Who was Chandragupta I?")
        self.assertEqual(ctx["answer"], "Founder of Gupta Era in 319-320 AD")
        self.assertEqual(ctx["mnemonic"], "Chandra = Moon = Gold/Gupta")

    def test_build_card_context_mcq_card(self):
        card = {
            "card_type": "mcq",
            "question": "Which article deals with Financial Emergency?",
            "options": [
                {"label": "A", "text": "Article 352", "hindi": "राष्ट्रीय आपातकाल"},
                {"label": "B", "text": "Article 356", "hindi": "राष्ट्रपति शासन"},
                {"label": "C", "text": "Article 360", "hindi": "वित्तीय आपातकाल"},
                {"label": "D", "text": "Article 368", "hindi": "संविधान संशोधन"}
            ],
            "correct_option": "C",
            "solution_data": {
                "statement": "Article 360 deals with Financial Emergency in India.",
                "key_points": "Never invoked so far in India."
            }
        }
        ctx = build_card_context(card, deck_name="Polity")
        self.assertEqual(ctx["card_type"], "mcq")
        self.assertEqual(ctx["correct_answer"], "C")
        self.assertEqual(len(ctx["options"]), 4)
        self.assertIn("Never invoked", ctx["key_points"])

    def test_save_and_get_ai_settings(self):
        save_ai_settings(api_key="test_fake_key_123", model_name="gemini-2.0-flash", auto_listen=True, voice_lang="hi-IN")
        cfg = get_ai_settings()
        self.assertEqual(cfg["api_key"], "test_fake_key_123")
        self.assertEqual(cfg["model_name"], "gemini-2.0-flash")
        self.assertTrue(cfg["auto_listen"])
        self.assertEqual(cfg["voice_lang"], "hi-IN")

    @patch("requests.post")
    def test_ai_coach_worker_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "🟢 शाबाश भाई! आर्टिकल 360 बिल्कुल सही है।"}]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        save_ai_settings(api_key="valid_dummy_key")
        ctx = {"question": "Test Question", "answer": "Test Answer"}
        worker = AICoachWorker(ctx, user_message="आर्टिकल 360", prompt_mode="recall")

        results = []
        worker.response_ready.connect(results.append)
        worker.run()

        self.assertEqual(len(results), 1)
        self.assertIn("शाबाश भाई", results[0])

    def test_ai_buddy_drawer_init(self):
        parent_w = QWidget()
        parent_w.resize(1000, 700); parent_w.show()
        drawer = AIBuddyDrawer(parent_w, parent=parent_w)
        self.assertEqual(drawer.objectName(), "ai_buddy_drawer")
        self.assertFalse(drawer.isVisible())

        # Test set current card
        dummy_card = {
            "card_type": "text",
            "question": "What is Repo Rate?",
            "answer": "Rate at which RBI lends to commercial banks."
        }
        drawer.set_current_card(dummy_card)
        self.assertIn("Repo Rate", drawer.chat_view.toHtml())

        # Test toggle drawer
        drawer.toggle_drawer()
        self.assertTrue(drawer.isVisible())
        drawer.toggle_drawer()
        self.assertFalse(drawer.isVisible())


if __name__ == "__main__":
    unittest.main()
