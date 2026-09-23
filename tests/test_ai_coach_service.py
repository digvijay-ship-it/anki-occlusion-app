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

        # Test list input (the root cause of the previous TypeError)
        list_input = ["<p>Point 1</p>", "<b>Point 2</b>", "Point 3"]
        list_res = strip_html_tags(list_input)
        self.assertIn("Point 1", list_res)
        self.assertIn("Point 2", list_res)
        self.assertIn("Point 3", list_res)
        self.assertNotIn("<p>", list_res)

        # Test dict and non-string inputs
        dict_input = {"note1": "<b>Detail A</b>", "note2": "Detail B"}
        dict_res = strip_html_tags(dict_input)
        self.assertIn("note1: Detail A", dict_res)
        self.assertEqual(strip_html_tags(12345), "12345")
        self.assertEqual(strip_html_tags(None), "")

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
                "key_points": ["Never invoked so far in India.", "Declared by the President."]
            }
        }
        ctx = build_card_context(card, deck_name="Polity")
        self.assertEqual(ctx["card_type"], "mcq")
        self.assertEqual(ctx["correct_answer"], "C")
        self.assertEqual(len(ctx["options"]), 4)
        self.assertIn("Never invoked so far in India.", ctx["key_points"])
        self.assertIn("Declared by the President.", ctx["key_points"])

    def test_save_and_get_ai_settings(self):
        save_ai_settings(api_key="AIzaSyMockKey1", model_name="gemini-3.8-flash", auto_listen=True, voice_lang="hi-IN")
        cfg = get_ai_settings()
        self.assertEqual(cfg["api_key"], "AIzaSyMockKey1")
        self.assertEqual(cfg["model_name"], "gemini-3.8-flash")
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

        save_ai_settings(api_key="AIzaSyMockKey2")
        ctx = {"question": "Test Question", "answer": "Test Answer"}
        worker = AICoachWorker(ctx, user_message="आर्टिकल 360", prompt_mode="recall")

        results = []
        worker.response_ready.connect(results.append)
        worker.run()

        self.assertEqual(len(results), 1)
        self.assertIn("शाबाश भाई", results[0])

    def test_parse_api_keys(self):
        from services.ai_coach_service import parse_api_keys
        raw = "AIzaSyKey1, AIzaSyKey2\nAIzaSyKey3; 'AIzaSyKey1'\nAIzaSyKey4"
        keys = parse_api_keys(raw)
        self.assertEqual(len(keys), 4)
        self.assertEqual(keys, ["AIzaSyKey1", "AIzaSyKey2", "AIzaSyKey3", "AIzaSyKey4"])

    def test_multi_key_rotation_and_cycling(self):
        from services.ai_coach_service import (
            save_ai_settings, get_ai_settings, cycle_next_key,
            get_api_key_pool, set_active_key_index
        )
        save_ai_settings(api_key="KEY_A, KEY_B, KEY_C")
        pool = get_api_key_pool()
        self.assertEqual(pool, ["KEY_A", "KEY_B", "KEY_C"])

        set_active_key_index(0)
        idx, total, new_k = cycle_next_key()
        self.assertEqual(idx, 2)
        self.assertEqual(total, 3)
        self.assertEqual(new_k, "KEY_B")

        idx2, total2, new_k2 = cycle_next_key()
        self.assertEqual(idx2, 3)
        self.assertEqual(new_k2, "KEY_C")

        # Wraps around
        idx3, total3, new_k3 = cycle_next_key()
        self.assertEqual(idx3, 1)
        self.assertEqual(new_k3, "KEY_A")

    @patch("requests.post")
    def test_ai_coach_worker_multi_key_failover_on_429(self, mock_post):
        """Verify worker automatically fails over to Key 2 when Key 1 gets 429 rate limit."""
        save_ai_settings(api_key="EXHAUSTED_KEY_1, WORKING_KEY_2")
        from services.ai_coach_service import set_active_key_index
        set_active_key_index(0)

        # First call (EXHAUSTED_KEY_1) returns 429
        resp_429 = MagicMock()
        resp_429.status_code = 429

        # Second call (WORKING_KEY_2) returns 200
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "🟢 जवाब सफल रहा!"}]
                    }
                }
            ]
        }

        mock_post.side_effect = [resp_429, resp_200]

        ctx = {"question": "Test Q", "answer": "Test A"}
        worker = AICoachWorker(ctx, user_message="टेस्ट", prompt_mode="recall")

        switches = []
        replies = []
        worker.key_switched.connect(lambda n, t, r: switches.append((n, t, r)))
        worker.response_ready.connect(replies.append)

        worker.run()

        # Should have switched once to key 2/2
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0][0], 2)
        self.assertEqual(switches[0][1], 2)
        # Should have obtained the reply from Key 2
        self.assertEqual(len(replies), 1)
        self.assertIn("जवाब सफल रहा", replies[0])
        # Two POST requests were made
        self.assertEqual(mock_post.call_count, 2)

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

    def test_continuous_mode_toggle_and_voice_config(self):
        from services.voice_input_service import VoiceInputWorker
        worker = VoiceInputWorker(language="hi-IN", phrase_limit=60, pause_threshold=2.0)
        self.assertEqual(worker.pause_threshold, 2.0)
        self.assertEqual(worker.phrase_limit, 60)
        self.assertEqual(worker.language, "hi-IN")

        parent_w = QWidget()
        parent_w.resize(1000, 700)
        drawer = AIBuddyDrawer(parent_w, parent=parent_w)
        self.assertFalse(drawer._continuous_active)

        # Test toggle continuous mode ON
        drawer.toggle_continuous_mode(True)
        self.assertTrue(drawer._continuous_active)
        self.assertIn("ON", drawer.btn_live_mode.text())

        # Test toggle continuous mode OFF
        drawer.toggle_continuous_mode(False)
        self.assertFalse(drawer._continuous_active)
        self.assertIn("लाइव बातचीत", drawer.btn_live_mode.text())


if __name__ == "__main__":
    unittest.main()
