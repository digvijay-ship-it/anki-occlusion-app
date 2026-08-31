import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton
from ui.pdf_viewer_controller import PdfViewerController

_APP = QApplication.instance() or QApplication([])


class FakeCanvas:
    def __init__(self, pages=5):
        self._pages = [object() for _ in range(pages)]
        self._scale = 1.0
        self.last_scroll_page = None
        self.last_fit_width = None
        self.focus_called = False

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
        self.focus_called = True


class FakeScrollBar:
    def __init__(self):
        self._value = 0

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = int(value)


class FakeViewport:
    def __init__(self, width=800):
        self._width = width

    def width(self):
        return self._width


class FakeScrollArea:
    def __init__(self, width=800):
        self._bar = FakeScrollBar()
        self._viewport = FakeViewport(width)

    def verticalScrollBar(self):
        return self._bar

    def viewport(self):
        return self._viewport


class PdfCreatorRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.canvas = FakeCanvas(pages=5)
        self.scroll = FakeScrollArea(width=800)
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

    def test_navigation_boundary_limits(self):
        # Go to last page
        self.controller.go_to_page(4)
        self.assertEqual(self.controller.current_page(), 4)
        self.assertTrue(self.prev_button.isEnabled())
        self.assertFalse(self.next_button.isEnabled())

        # Next on last page should keep it on last page
        self.controller.go_next_page()
        self.assertEqual(self.controller.current_page(), 4)

        # Go to first page
        self.controller.go_to_page(0)
        self.assertEqual(self.controller.current_page(), 0)
        self.assertFalse(self.prev_button.isEnabled())
        self.assertTrue(self.next_button.isEnabled())

        # Prev on first page should keep it on first page
        self.controller.go_prev_page()
        self.assertEqual(self.controller.current_page(), 0)

        # Out-of-bounds index (too large) should clamp to last page
        self.controller.go_to_page(10)
        self.assertEqual(self.controller._ui_page_zero, 4)

        # Out-of-bounds index (negative) should clamp to first page
        self.controller.go_to_page(-5)
        self.assertEqual(self.controller._ui_page_zero, 0)

    def test_jump_from_input_robustness(self):
        # Valid input
        self.page_input.setText("3")
        self.controller.jump_from_input()
        self.assertEqual(self.controller.current_page(), 2)
        self.assertEqual(self.page_input.text(), "3")

        # Invalid non-numeric input (should revert to current page UI)
        self.page_input.setText("invalid")
        self.controller.jump_from_input()
        self.assertEqual(self.controller.current_page(), 2)
        self.assertEqual(self.page_input.text(), "3")

        # Empty input (should default to page 1 / index 0)
        self.page_input.setText("")
        self.controller.jump_from_input()
        self.assertEqual(self.controller.current_page(), 0)
        self.assertEqual(self.page_input.text(), "1")

        # Out-of-bounds input (too large, should clamp)
        self.page_input.setText("20")
        self.controller.jump_from_input()
        self.assertEqual(self.controller.current_page(), 4)

        # Out-of-bounds input (negative, should clamp)
        self.page_input.setText("-2")
        self.controller.jump_from_input()
        self.assertEqual(self.controller.current_page(), 0)

    def test_empty_state_handling(self):
        # Simulate empty state (0 pages)
        self.canvas._pages = []
        self.controller.refresh_page_ui()

        self.assertEqual(self.controller.page_count(), 0)
        self.assertEqual(self.controller.current_page(), 0)
        self.assertFalse(self.page_input.isEnabled())
        self.assertFalse(self.prev_button.isEnabled())
        self.assertFalse(self.next_button.isEnabled())
        self.assertEqual(self.page_total.text(), "/ 0")
        self.assertEqual(self.page_input.text(), "")

        # Calling navigation on empty state should be a safe no-op
        self.controller.go_to_page(0)
        self.controller.go_next_page()
        self.controller.go_prev_page()
        self.controller.jump_from_input()
        self.assertEqual(self.controller.current_page(), 0)


if __name__ == "__main__":
    unittest.main()
