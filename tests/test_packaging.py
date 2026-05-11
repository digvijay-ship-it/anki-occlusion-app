import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PyInstallerSpecTests(unittest.TestCase):
    def test_spec_builds_current_app_entrypoint(self):
        spec = (ROOT / "AnkiOcclusion.spec").read_text(encoding="utf-8")

        self.assertIn("anki_occlusion_v19.py", spec)
        self.assertNotIn("anki_occlusion_v17.py", spec)
        self.assertNotIn("anki_pdf_native.dll", spec)

    def test_spec_does_not_reference_missing_icon_file(self):
        spec_path = ROOT / "AnkiOcclusion.spec"
        spec = spec_path.read_text(encoding="utf-8")
        tree = ast.parse(spec)

        icon_values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "icon":
                icon_values.append(ast.literal_eval(node.value))

        for value in icon_values:
            if value in (None, []):
                continue
            icons = value if isinstance(value, list) else [value]
            for icon in icons:
                self.assertTrue((ROOT / icon).exists(), f"Missing icon referenced by {spec_path.name}: {icon}")

    def test_spec_collects_assets_and_multimedia_plugin(self):
        spec = (ROOT / "AnkiOcclusion.spec").read_text(encoding="utf-8")

        self.assertIn('ASSET_ROOT = ROOT / "assets"', spec)
        self.assertIn('hiddenimports=["PyQt5.QtMultimedia"]', spec)
        self.assertIn("COLLECT(", spec)

    def test_build_script_uses_pyinstaller_and_iexpress(self):
        script = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")

        self.assertIn("pyinstaller --noconfirm AnkiOcclusion.spec", script)
        self.assertIn("iexpress.exe", script)
        self.assertIn("[DEBUG][installer]", script)


if __name__ == "__main__":
    unittest.main()
