import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from ui.pdf_viewer_controller import PdfViewerController


_APP = QApplication.instance() or QApplication([])


class _FakeBar:
    def __init__(self):
        self._value = 0

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = int(value)


class _FakeViewport:
    def __init__(self, width=900):
        self._width = width

    def width(self):
        return self._width


class _FakeScrollArea:
    def __init__(self, width=900):
        self._bar = _FakeBar()
        self._viewport = _FakeViewport(width)

    def verticalScrollBar(self):
        return self._bar

    def viewport(self):
        return self._viewport


class _FakeCanvas:
    def __init__(self, pages=4):
        self._pages = [object() for _ in range(pages)]
        self._scale = 1.0
        self.last_fit_width = None
        self.last_scroll_page = None

    def get_current_page(self, scroll_value):
        return max(0, min(int(scroll_value), len(self._pages) - 1))

    def scroll_to_page(self, page_zero, scroll_area):
        self.last_scroll_page = int(page_zero)
        scroll_area.verticalScrollBar().setValue(page_zero)

    def zoom_fit_width(self, viewport_width):
        self.last_fit_width = int(viewport_width)
        self._scale = float(viewport_width) / 100.0

    def zoom_in(self):
        self._scale *= 1.10

    def zoom_out(self):
        self._scale /= 1.10

    def setFocus(self):
        return None


class PdfViewerControllerTests(unittest.TestCase):
    def setUp(self):
        self.canvas = _FakeCanvas()
        self.scroll = _FakeScrollArea(width=960)
        self.page_input = QLineEdit()
        self.page_total = QLabel()
        self.prev_button = QPushButton()
        self.next_button = QPushButton()
        self.controller = PdfViewerController(
            canvas=self.canvas,
            scroll_area=self.scroll,
            page_input=self.page_input,
            page_total_label=self.page_total,
            prev_button=self.prev_button,
            next_button=self.next_button,
        )

    def test_reset_fit_uses_full_viewport_width(self):
        self.controller.reset_fit()

        self.assertEqual(self.canvas.last_fit_width, 960)

    def test_jump_from_input_updates_scroll_and_page_ui(self):
        self.page_input.setText("3")

        self.controller.jump_from_input()
        QApplication.processEvents()

        self.assertEqual(self.scroll.verticalScrollBar().value(), 2)
        self.assertEqual(self.page_input.text(), "3")
        self.assertEqual(self.page_total.text(), "/ 4")

    def test_resize_does_not_override_manual_zoom(self):
        self.controller.reset_fit()
        first_fit = self.canvas.last_fit_width

        self.controller.zoom_in()
        self.canvas.last_fit_width = None
        self.controller.on_resize()

        self.assertIsNone(self.canvas.last_fit_width)
        self.assertEqual(first_fit, 960)


if __name__ == "__main__":
    unittest.main()
