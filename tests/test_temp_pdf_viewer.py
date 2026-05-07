import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QApplication

from temp import MainWindow, PdfTileCanvas


_APP = QApplication.instance() or QApplication([])


class PdfTileCanvasNavTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)
        self.canvas = PdfTileCanvas()
        self.addCleanup(self.canvas.close)
        self.canvas._page_rects = [
            QRect(8, 8, 100, 100),
            QRect(8, 116, 100, 100),
            QRect(8, 224, 100, 100),
        ]

    def test_current_page_index_uses_scroll_position(self):
        self.assertEqual(self.canvas.current_page_index(0), 0)
        self.assertEqual(self.canvas.current_page_index(118), 1)
        self.assertEqual(self.canvas.current_page_index(260), 2)


class MainWindowNavTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.window.canvas._page_rects = [
            QRect(8, 8, 100, 100),
            QRect(8, 116, 100, 100),
            QRect(8, 224, 100, 100),
        ]
        self.window._set_page_ui(0)

    def test_next_page_updates_page_box(self):
        self.window._go_next_page()

        self.assertEqual(self.window._ui_page_zero, 1)
        self.assertEqual(self.window.page_jump.text(), "2")
        self.assertEqual(self.window.lbl_page_total.text(), "/ 3")


if __name__ == "__main__":
    unittest.main()
