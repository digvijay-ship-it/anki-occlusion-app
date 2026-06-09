import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
_TEMP_DIR = tempfile.TemporaryDirectory()
import data_manager
data_manager.DATA_FILE = os.path.join(_TEMP_DIR.name, "anki_occlusion_data_test.db")


from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QWidget

from anki_occlusion_v19 import MainWindow
from ui.math_trainer import MathTrainerPage
from ui.tmnt_home import TMNTHomeLayout

_APP = QApplication.instance() or QApplication([])


class EscapeKeyTests(unittest.TestCase):
    def setUp(self):
        # Patch QTimer.singleShot to prevent async timer execution in tests
        self.single_shot_patcher = patch("PyQt5.QtCore.QTimer.singleShot")
        self.mock_single_shot = self.single_shot_patcher.start()
        
        # Patch store.start_autosave
        from data_manager import store
        self.autosave_patcher = patch.object(store, "start_autosave")
        self.mock_autosave = self.autosave_patcher.start()
        
        self.windows = []

    def tearDown(self):
        self.single_shot_patcher.stop()
        self.autosave_patcher.stop()
        for win in self.windows:
            win.close()
            win.deleteLater()
        QApplication.processEvents()

    def create_window(self):
        win = MainWindow()
        self.windows.append(win)
        return win

    def test_math_trainer_go_back_navigation(self):
        # Instantiate MathTrainerPage
        page = MathTrainerPage()
        
        # Test transition from Page 2 to Page 1
        page._show(2)
        self.assertTrue(not page._p2.isHidden())
        page.go_back()
        self.assertTrue(not page._p1.isHidden())
        self.assertTrue(page._p2.isHidden())
        
        # Test transition from Page 1 to Page 0
        page._show(1)
        self.assertTrue(not page._p1.isHidden())
        page.go_back()
        self.assertTrue(not page._p0.isHidden())
        self.assertTrue(page._p1.isHidden())
        
        # Test transition from Page 3 to Page 0
        page._show(3)
        self.assertTrue(not page._p3.isHidden())
        page.go_back()
        self.assertTrue(not page._p0.isHidden())
        self.assertTrue(page._p3.isHidden())

        # Test transition from Page 0 triggers closed signal
        page._show(0)
        closed_signal_mock = MagicMock()
        page.closed.connect(closed_signal_mock)
        page.go_back()
        closed_signal_mock.assert_called_once()

    def test_mainwindow_key_press_escape_closed_classic_settings(self):
        # Create MainWindow and mock components
        win = self.create_window()
        home = win.centralWidget()
        
        # Setup mock classic settings panel
        mock_panel = MagicMock()
        mock_panel.isVisible.return_value = True
        home._classic_settings_panel = mock_panel
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        win.keyPressEvent(event)
        
        mock_panel.hide.assert_called_once()
        self.assertTrue(event.isAccepted())

    def test_mainwindow_key_press_escape_cancels_review(self):
        win = self.create_window()
        home = win.centralWidget()
        
        # Setup mock active review
        mock_review = MagicMock()
        home._active_review = mock_review
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        win.keyPressEvent(event)
        
        mock_review.cancelled.emit.assert_called_once()
        self.assertTrue(event.isAccepted())

    def test_mainwindow_key_press_escape_delegates_to_math_trainer(self):
        win = self.create_window()
        home = win.centralWidget()
        
        # Setup mock math trainer
        mock_math_trainer = MagicMock()
        home._math_trainer = mock_math_trainer
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        win.keyPressEvent(event)
        
        mock_math_trainer.go_back.assert_called_once()
        self.assertTrue(event.isAccepted())

    def test_mainwindow_key_press_escape_closes_tmnt_panels(self):
        win = self.create_window()
        home = win.centralWidget()
        
        # Setup mock TMNT layout with settings and more panel
        mock_tmnt = MagicMock()
        mock_tmnt.isVisible.return_value = True
        
        mock_settings = MagicMock()
        mock_settings.isVisible.return_value = True
        mock_tmnt._settings_panel = mock_settings
        
        mock_more = MagicMock()
        mock_more.isVisible.return_value = True
        mock_tmnt._more_panel = mock_more
        
        home._tmnt_layout = mock_tmnt
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        win.keyPressEvent(event)
        
        mock_tmnt._hide_panel.assert_any_call(mock_settings)
        mock_tmnt._hide_panel.assert_any_call(mock_more)
        self.assertTrue(event.isAccepted())

    def test_home_cache_cleared_on_close_actions(self):
        win = self.create_window()
        home = win.centralWidget()
        home._clear_home_ram_caches = MagicMock()
        
        # Test Math Trainer exit clears cache
        home._math_trainer = MagicMock()
        home._hide_math_trainer()
        home._clear_home_ram_caches.assert_called()


if __name__ == "__main__":
    unittest.main()
