import unittest

from theme_manager import build_stylesheet, normalize_theme


class ThemeDisableTests(unittest.TestCase):
    def test_ninja_and_dojo_fall_back_to_classic(self):
        self.assertEqual(normalize_theme("ninja"), "classic")
        self.assertEqual(normalize_theme("dojo"), "classic")

    def test_disabled_ninja_stylesheet_does_not_reference_dojo_assets(self):
        stylesheet = build_stylesheet("dojo", 11)

        self.assertNotIn("assets/themes/dojo", stylesheet)
        self.assertEqual(normalize_theme("dojo"), "classic")

    def test_manhattan_theme_passes_cleanly(self):
        self.assertEqual(normalize_theme("manhattan"), "manhattan")
        stylesheet = build_stylesheet("manhattan", 12)
        self.assertIn("#080c10", stylesheet)  # deep background
        self.assertIn("Press Start 2P", stylesheet)


if __name__ == "__main__":
    unittest.main()
