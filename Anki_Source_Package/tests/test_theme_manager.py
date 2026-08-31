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

    def test_arcanum_theme_passes_cleanly(self):
        self.assertEqual(normalize_theme("arcanum"), "arcanum")
        stylesheet = build_stylesheet("arcanum", 12)
        self.assertIn("#0E0B1A", stylesheet)        # midnight indigo bg
        self.assertIn("Cinzel", stylesheet)          # arcanum display font

    def test_is_retro_theme_helper(self):
        from theme_manager import is_retro_theme
        self.assertTrue(is_retro_theme("arcanum"))
        self.assertTrue(is_retro_theme("tmnt"))
        self.assertTrue(is_retro_theme("manhattan"))
        self.assertFalse(is_retro_theme("classic"))
        self.assertFalse(is_retro_theme("dojo"))     # disabled → not retro

    def test_arcanum_contains_no_third_party_ip(self):
        from theme_manager import LABELS
        blob = build_stylesheet("arcanum", 12) + " " + str(LABELS["arcanum"]).lower()
        for forbidden in ("cowabunga", "shredder", "pizza", "sewer",
                          "ninja", "turtle", "foot clan", "donatello", "splinter"):
            self.assertNotIn(forbidden, blob, f"ARCANUM must not contain '{forbidden}'")


if __name__ == "__main__":
    unittest.main()
