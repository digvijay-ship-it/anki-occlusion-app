import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class WebScriptTests(unittest.TestCase):
    def test_start_script_launches_backend_frontend_and_browser(self):
        script = (WEB / "start_web_app.ps1").read_text(encoding="utf-8")

        self.assertIn("uvicorn", script)
        self.assertIn("run:app", script)
        self.assertIn("npm run dev", script)
        self.assertIn("VITE_API_BASE", script)
        self.assertIn("Start-Process \"http://127.0.0.1:$FrontendPort\"", script)
        self.assertIn("backend.pid", script)
        self.assertIn("frontend.pid", script)

    def test_stop_script_stops_pid_files_without_requiring_port_kill(self):
        script = (WEB / "stop_web_app.ps1").read_text(encoding="utf-8")

        self.assertIn("frontend.pid", script)
        self.assertIn("backend.pid", script)
        self.assertIn("Stop-Process -Id $processId -Force", script)
        self.assertIn("AlsoStopKnownPorts", script)

    def test_cmd_wrappers_run_powershell_with_execution_policy_bypass(self):
        for filename in ("start_web_app.cmd", "stop_web_app.cmd"):
            script = (WEB / filename).read_text(encoding="utf-8")

            self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass", script)
            self.assertIn("%~dp0", script)


if __name__ == "__main__":
    unittest.main()
