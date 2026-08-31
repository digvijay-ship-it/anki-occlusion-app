import unittest
import importlib.util
from pathlib import Path

class UnhandledExceptionScrubTests(unittest.TestCase):
    def test_scrub_traceback_redacts_bearer_tokens_and_secrets(self):
        # Dynamically import anki_occlusion_v19.pyw
        pyw_path = Path(__file__).resolve().parent.parent / "anki_occlusion_v19.py"
        if not pyw_path.exists():
            pyw_path = Path(__file__).resolve().parent.parent / "anki_occlusion_v19.pyw"
        spec = importlib.util.spec_from_file_location("anki_occlusion_v19", str(pyw_path))
        anki_occlusion_v19 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(anki_occlusion_v19)

        # Test token redacting
        raw_traceback = (
            "Traceback (most recent call last):\n"
            "  File \"gdrive_service.py\", line 12\n"
            "Bearer Token: ya29.a0AfB_abcdefghijklmnopqrstuvwxyz1234567890\n"
            "Client Secret: client_secret='my-super-secret-123'\n"
            "Authorization: Bearer ya29.another_token"
        )
        scrubbed = anki_occlusion_v19._scrub_traceback(raw_traceback)

        self.assertNotIn("ya29.a0AfB_", scrubbed)
        self.assertNotIn("my-super-secret-123", scrubbed)
        self.assertIn("[REDACTED BEARER TOKEN]", scrubbed)
        self.assertIn("[REDACTED SECRET]", scrubbed)

if __name__ == "__main__":
    unittest.main()
