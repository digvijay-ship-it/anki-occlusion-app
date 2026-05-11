import unittest
from pathlib import Path
from unittest.mock import patch

import storage_paths


class AppResourcePathTests(unittest.TestCase):
    def test_app_resource_path_uses_repo_root_when_not_frozen(self):
        expected = Path(storage_paths.__file__).resolve().parent / "assets" / "music"

        actual = Path(storage_paths.app_resource_path("assets", "music"))

        self.assertEqual(actual, expected)

    def test_app_resource_path_prefers_meipass_when_frozen(self):
        fake_root = Path(r"C:\bundle_root")

        with patch.object(storage_paths.sys, "frozen", True, create=True):
            with patch.object(storage_paths.sys, "_MEIPASS", str(fake_root), create=True):
                actual = Path(storage_paths.app_resource_path("assets", "fonts"))

        self.assertEqual(actual, fake_root / "assets" / "fonts")

    def test_app_resource_url_normalizes_backslashes(self):
        with patch.object(storage_paths.sys, "frozen", True, create=True):
            with patch.object(storage_paths.sys, "_MEIPASS", r"C:\bundle_root", create=True):
                url = storage_paths.app_resource_url("assets", "themes", "dojo", "wall_main.png")

        self.assertNotIn("\\", url)
        self.assertTrue(url.endswith("assets/themes/dojo/wall_main.png"))


if __name__ == "__main__":
    unittest.main()
