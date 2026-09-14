import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QWidget
_APP = QApplication.instance() or QApplication([])

from ui.settings_proxy import SettingsProxyDict


class GlobalSettingsTests(unittest.TestCase):
    def setUp(self):
        settings = QSettings("AnkiOcclusionTest", "AppTest")
        settings.remove("settings/_scheduler_type")
        settings.remove("settings/_request_retention")

    def tearDown(self):
        settings = QSettings("AnkiOcclusionTest", "AppTest")
        settings.remove("settings/_scheduler_type")
        settings.remove("settings/_request_retention")

    def test_settings_proxy_defaults_and_updates(self):
        proxy = SettingsProxyDict()
        self.assertIn("_scheduler_type", proxy)
        self.assertIn("_request_retention", proxy)
        self.assertEqual(proxy["_scheduler_type"], "fsrs")
        self.assertEqual(proxy["_request_retention"], 0.90)

        # Update values
        proxy["_scheduler_type"] = "sm2"
        proxy["_request_retention"] = 0.95

        self.assertEqual(proxy["_scheduler_type"], "sm2")
        self.assertEqual(proxy["_request_retention"], 0.95)

    def test_classic_home_screen_settings_panel_controls(self):
        from ui.home_screen import HomeScreen
        hs = HomeScreen.__new__(HomeScreen)
        QWidget.__init__(hs)
        hs._data = {"_scheduler_type": "fsrs", "_request_retention": 0.92}
        hs._classic_archive_value = None
        hs._classic_archive_box = None
        hs._classic_archive_btn = None
        hs._btn_settings = MagicMock()

        panel = hs._build_classic_settings_panel()
        self.assertIsNotNone(panel)
        self.assertTrue(hasattr(hs, "_combo_global_scheduler"))
        self.assertTrue(hasattr(hs, "_combo_global_retention"))

        # Verify initial selection from _data
        self.assertEqual(hs._combo_global_scheduler.currentData(), "fsrs")
        self.assertEqual(hs._combo_global_retention.currentData(), 0.92)

        # Trigger scheduler change
        sm2_idx = hs._combo_global_scheduler.findData("sm2")
        self.assertGreaterEqual(sm2_idx, 0)
        with patch("services.review_manager.store.mark_dirty"):
            hs._combo_global_scheduler.setCurrentIndex(sm2_idx)
            self.assertEqual(hs._data["_scheduler_type"], "sm2")

        # Trigger retention change
        ret_idx = hs._combo_global_retention.findData(0.85)
        self.assertGreaterEqual(ret_idx, 0)
        with patch("services.review_manager.store.mark_dirty"):
            hs._combo_global_retention.setCurrentIndex(ret_idx)
            self.assertEqual(hs._data["_request_retention"], 0.85)


if __name__ == "__main__":
    unittest.main()
