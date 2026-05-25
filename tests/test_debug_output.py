import builtins
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import debug_output


class DebugOutputFilterTests(unittest.TestCase):
    def test_filter_suppresses_debug_and_profile_lines(self):
        original_print = builtins.print
        stream = io.StringIO()
        try:
            with patch.dict(os.environ, {"ANKI_ALLOW_DEBUG_LOGS": ""}, clear=False):
                debug_output.install_debug_output_filter()
                with redirect_stdout(stream):
                    print("[DEBUG][canvas_cache] noisy")
                    print("[PROFILE][canvas_paint] noisy")
                    print("normal output")
        finally:
            builtins.print = original_print

        self.assertEqual(stream.getvalue(), "normal output\n")


if __name__ == "__main__":
    unittest.main()
