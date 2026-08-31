import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt, QPointF
from PyQt5.QtWidgets import QApplication
from ui.math_trainer import MathScratchpad

_APP = QApplication.instance() or QApplication([])

class MathTrainerPenTests(unittest.TestCase):
    def setUp(self):
        self.scratchpad = MathScratchpad()
        self.scratchpad._trigger_ocr = MagicMock()

    def tearDown(self):
        self.scratchpad.deleteLater()
        QApplication.processEvents()

    class _MockMouseEvent:
        def __init__(self, event_type, pos, button, buttons, modifiers):
            self._type = event_type
            self._pos = QPointF(pos)
            self._button = button
            self._buttons = buttons
            self._modifiers = modifiers
            self.accepted = False
            self.ignored = False

        def type(self):
            return self._type

        def button(self):
            return self._button

        def buttons(self):
            return self._buttons

        def localPos(self):
            return self._pos

        def accept(self):
            self.accepted = True

        def ignore(self):
            self.ignored = True

    def test_mouse_events_work_normally(self):
        # Press mouse
        press = self._MockMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        self.scratchpad.mousePressEvent(press)
        self.assertEqual(len(self.scratchpad._current), 1)
        self.assertEqual(self.scratchpad._current[0], QPointF(10, 10))

        # Move mouse
        move = self._MockMouseEvent(
            QEvent.MouseMove,
            QPointF(20, 20),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        self.scratchpad.mouseMoveEvent(move)
        self.assertEqual(len(self.scratchpad._current), 2)
        self.assertEqual(self.scratchpad._current[1], QPointF(20, 20))

        # Release mouse
        release = self._MockMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
        self.scratchpad.mouseReleaseEvent(release)
        self.assertEqual(len(self.scratchpad._current), 0)
        self.assertEqual(len(self.scratchpad._strokes), 1)
        self.assertEqual(len(self.scratchpad._strokes[0]), 2)

    def test_clear_resets_scratchpad(self):
        self.scratchpad._strokes = [[QPointF(0, 0), QPointF(1, 1)]]
        self.scratchpad._current = [QPointF(2, 2)]
        self.scratchpad.clear()
        self.assertEqual(self.scratchpad._strokes, [])
        self.assertEqual(self.scratchpad._current, [])


class MathTrainerVerificationTests(unittest.TestCase):
    def test_wrong_answer_clearing(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            page._ans = 42
            page._ans_in.setText("45")
            page._check()
            
            # Verify it set self._last_wrong_text
            self.assertEqual(page._last_wrong_text, "45")
            
            # Manually invoke clearing when text hasn't changed
            page._clear_wrong_answer()
            self.assertEqual(page._ans_in.text(), "")
            self.assertEqual(len(page._scratchpad._strokes), 0)
            
            # Test that if the text has changed, it does NOT clear
            page._ans_in.setText("47")
            page._last_wrong_text = "45"
            page._clear_wrong_answer()
            self.assertEqual(page._ans_in.text(), "47")
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_solo_mode_generation(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            page._mode = 1
            # Enable solo mode and set target table to 27
            page._solo_btn.setChecked(True)
            idx = page._solo_combo.findData(27)
            page._solo_combo.setCurrentIndex(idx)
            
            # Generate a question and check if it starts with "27 ×"
            page._gen_q()
            self.assertTrue(page._q_lbl.text().startswith("27 ×"))
            
            # Disable solo mode and select only table 23
            page._solo_btn.setChecked(False)
            for i in page._tchk:
                page._tchk[i] = (i == 23)
            page._gen_q()
            self.assertTrue(page._q_lbl.text().startswith("23 ×"))
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_preset_and_range_selection(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            # 1. Test custom range selection
            page._apply_range_selection(6, 12)
            for i in range(1, 46):
                if 6 <= i <= 12:
                    self.assertTrue(page._tchk[i])
                    self.assertTrue(page._tab_btns[i].isChecked())
                else:
                    self.assertFalse(page._tchk[i])
                    self.assertFalse(page._tab_btns[i].isChecked())
                    
            # 2. Test clearing
            page._apply_range_selection(0, 0)
            for i in range(1, 46):
                self.assertFalse(page._tchk[i])
                self.assertFalse(page._tab_btns[i].isChecked())
        finally:
            page.deleteLater()
            QApplication.processEvents()
