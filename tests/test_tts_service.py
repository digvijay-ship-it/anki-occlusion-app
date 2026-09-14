"""
Unit tests for TTSEngine and text cleaner in services/tts_service.py
"""

import unittest
from services.tts_service import clean_text_for_speech, TTSEngine, DEFAULT_VOICE, AVAILABLE_VOICES


class TestTTSService(unittest.TestCase):

    def test_clean_text_for_speech(self):
        sample = (
            "🟢 **शाबाश भाई! बिल्कुल सही पकड़ा...**\n"
            "Abate का अर्थ होता है कम होना।\n"
            "⚠️ **छूटे हुए ट्रैप्स:**\n"
            "• परीक्षा में इसे [Abet](https://example.com) (उकसाना) से कन्फ़्यूज़ मत करना!\n"
            "💡 **मेमोरी एंकर:**\n"
            "'Ate' खा गया तो कम हो गया!"
        )
        cleaned = clean_text_for_speech(sample)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("🟢", cleaned)
        self.assertNotIn("⚠️", cleaned)
        self.assertNotIn("💡", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertIn("शाबाश भाई", cleaned)
        self.assertIn("Abate का अर्थ होता है कम होना", cleaned)
        self.assertIn("Abet", cleaned)

    def test_voices_available(self):
        self.assertTrue(len(AVAILABLE_VOICES) >= 2)
        voices = [v[1] for v in AVAILABLE_VOICES]
        self.assertIn(DEFAULT_VOICE, voices)

    def test_tts_engine_init_and_stop(self):
        from PyQt5.QtWidgets import QApplication
        import sys
        app = QApplication.instance() or QApplication(sys.argv)

        engine = TTSEngine()
        self.assertFalse(engine.is_speaking())
        engine.stop()
        self.assertFalse(engine.is_speaking())


if __name__ == "__main__":
    unittest.main()
