import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from ui.pdf_annotation_dialog import PdfAnnotationCanvas


_APP = QApplication.instance() or QApplication([])


class _FakeWheelEvent:
    def __init__(self, delta_y):
        self._delta_y = int(delta_y)
        self.accepted = False

    class _Delta:
        def __init__(self, value):
            self._value = value

        def y(self):
            return self._value

    def angleDelta(self):
        return self._Delta(self._delta_y)

    def accept(self):
        self.accepted = True


class PdfAnnotationCanvasTests(unittest.TestCase):
    def test_ctrl_wheel_zoom_changes_scale(self):
        canvas = PdfAnnotationCanvas()
        canvas.load_pages([QPixmap(100, 120)])
        start = canvas._scale
        event = _FakeWheelEvent(120)

        canvas.handle_ctrl_wheel_zoom(event)

        self.assertGreater(canvas._scale, start)
        self.assertTrue(event.accepted)

    def test_native_zoom_changes_scale(self):
        canvas = PdfAnnotationCanvas()
        canvas.load_pages([QPixmap(100, 120)])
        start = canvas._scale

        canvas.handle_native_zoom(0.2)

        self.assertGreater(canvas._scale, start)


if __name__ == "__main__":
    unittest.main()
