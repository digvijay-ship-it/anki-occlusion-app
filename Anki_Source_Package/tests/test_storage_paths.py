import unittest
import tempfile
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

    def test_recovery_dirs_live_under_mission_archive_when_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            storage_paths, "get_mission_archive_root", return_value=tmpdir
        ):
            paths = storage_paths.ensure_recovery_dirs()

        self.assertTrue(paths["recovery"].endswith("recovery"))
        self.assertTrue(paths["drafts"].endswith(str(Path("recovery") / "drafts")))

    def test_recovery_dirs_live_next_to_legacy_data_file_without_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            storage_paths, "get_mission_archive_root", return_value=""
        ), patch.object(
            storage_paths,
            "current_data_file",
            lambda root=None: str(Path(tmpdir) / "anki_occlusion_data.json"),
        ):
            path = Path(storage_paths.current_recovery_dir())

        self.assertEqual(path, Path(tmpdir) / "anki_occlusion_recovery")


if __name__ == "__main__":
    unittest.main()
