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

    def test_reveal_and_next_shortcuts(self):
        from ui.math_trainer import MathTrainerPage
        from PyQt5.QtTest import QTest
        page = MathTrainerPage()
        try:
            page._mode = 3
            page._custom_nums = [14]
            page._start_practice()

            # Verify initial state
            self.assertTrue("?" in page._q_lbl.text())
            self.assertEqual(page._ans_in.text(), "")
            self.assertTrue(page._reveal_card.isHidden())
            self.assertEqual(page._reveal_bar_btn.text(), "REVEAL 👁 (Space)")

            # Press Space in answer box -> Reveals answer
            page._ans_in.setFocus()
            QTest.keyClick(page._ans_in, Qt.Key_Space)

            self.assertTrue(getattr(page, "_is_revealed", False))
            self.assertFalse("?" in page._q_lbl.text())
            self.assertEqual(page._ans_in.text(), str(page._ans))
            self.assertFalse(page._reveal_card.isHidden())
            self.assertEqual(page._reveal_bar_btn.text(), "NEXT ➔ (Space)")
            self.assertIn("REVEALED", page._fb_lbl.text())

            # Press Space again -> Advances to next question
            QTest.keyClick(page._ans_in, Qt.Key_Space)

            self.assertFalse(getattr(page, "_is_revealed", False))
            self.assertTrue("?" in page._q_lbl.text())
            self.assertEqual(page._ans_in.text(), "")
            self.assertTrue(page._reveal_card.isHidden())
            self.assertEqual(page._reveal_bar_btn.text(), "REVEAL 👁 (Space)")
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_misread_clipboard_capture_preserves_ink(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            page._ans = 6859
            page._q_lbl.setText("19³ = ?")
            
            # Simulate user drawing strokes on the scratchpad
            p1 = QPointF(100.0, 100.0)
            p2 = QPointF(150.0, 150.0)
            page._scratchpad._strokes = [[p1, p2]]
            page._scratchpad._stroke_widths = [[2.5]]
            
            # Simulate OCR returning a misread "6858"
            page._on_ocr_result("6858")
            self.assertEqual(page._ans_in.text(), "6858")
            self.assertEqual(page._last_predicted_ocr, "6858")
            
            # Run check -> wrong answer
            page._check()
            self.assertEqual(page._last_wrong_text, "6858")
            
            # Simulate the 1000ms timer triggering _clear_wrong_answer
            page._clear_wrong_answer()
            # Answer input cleared so user can re-try, BUT ink must NOT be destroyed!
            self.assertEqual(page._ans_in.text(), "")
            self.assertEqual(len(page._scratchpad._strokes), 1, "Ink strokes must not be wiped out by wrong answer clearing!")
            self.assertTrue(page._scratchpad._clear_on_next_press)
            
            # User copies misread card
            page._copy_misread_to_clipboard()
            
            # Verify clipboard got a valid QPixmap
            cb_pix = QApplication.clipboard().pixmap()
            self.assertFalse(cb_pix.isNull())
            self.assertEqual(cb_pix.width(), 640)
            self.assertEqual(cb_pix.height(), 420)
            
            # Even if scratchpad is subsequently cleared, last_strokes retains it
            page._scratchpad.clear()
            self.assertEqual(len(page._scratchpad._strokes), 0)
            self.assertEqual(len(page._scratchpad._last_strokes), 1)
            
            # Copying misread again should still succeed and find the ink in _last_strokes!
            page._copy_misread_to_clipboard()
            cb_pix2 = QApplication.clipboard().pixmap()
            self.assertFalse(cb_pix2.isNull())
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_escape_clears_both_scratchpads(self):
        from ui.math_trainer import MathTrainerPage
        from PyQt5.QtTest import QTest
        page = MathTrainerPage()
        try:
            page._mode = 3
            page._start_practice()

            # 1. Add strokes to BOTH pads and text to answer box
            p1 = QPointF(10, 10)
            p2 = QPointF(20, 20)
            page._scratchpad._strokes = [[p1, p2]]
            page._side_scratchpad._strokes = [[p1, p2]]
            page._ans_in.setText("1234")

            # Press Escape while focused on answer box
            page._ans_in.setFocus()
            QTest.keyClick(page._ans_in, Qt.Key_Escape)

            # Both pads and input must be cleared
            self.assertEqual(len(page._scratchpad._strokes), 0)
            self.assertEqual(len(page._side_scratchpad._strokes), 0)
            self.assertEqual(page._ans_in.text(), "")

            # 2. Add strokes ONLY to rough pad
            page._side_scratchpad._strokes = [[p1, p2]]
            page._ans_in.setFocus()
            QTest.keyClick(page._ans_in, Qt.Key_Escape)

            # Rough pad must be cleared, session must stay in practice mode (_p2 visible)
            self.assertEqual(len(page._side_scratchpad._strokes), 0)
            self.assertFalse(page._p2.isHidden())

            # 3. Double-clicking main scratchpad clears only main pad
            page._scratchpad._strokes = [[p1, p2]]
            page._side_scratchpad._strokes = [[p1, p2]]
            page._clear_main_scratchpad()

            self.assertEqual(len(page._scratchpad._strokes), 0)
            self.assertEqual(len(page._side_scratchpad._strokes), 1, "Rough pad should remain intact on main pad clear!")
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_per_item_streak_retirement_and_celebration(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            page._mode = 2  # Squares
            page._rchk = {"11-12": True}  # Small pool of 2 items: 11, 12
            page._streak_target = 5
            page._start_practice()

            self.assertEqual(len(page._all_pool), 2)
            self.assertEqual(set(page._all_pool), {11, 12})
            self.assertEqual(page._item_streaks[11], 0)
            self.assertEqual(page._item_streaks[12], 0)

            # 1. Answer question 11 correctly 4 times
            page._current_q_item = 11
            page._ans = 121
            for streak_step in range(1, 5):
                page._ans_in.setText("121")
                page._check()
                self.assertEqual(page._item_streaks[11], streak_step)
                self.assertIn("STREAK: {}/5".format(streak_step), page._q_mastery_badge.text())
                self.assertIn(11, page._all_pool)

            # 2. Test that app does NOT decrease or wipe streak on wrong answer (user-controlled streak)
            page._ans_in.setText("999")
            page._check()
            # Streak must NOT decrease or wipe out; stays intact at 4!
            self.assertEqual(page._item_streaks[11], 4)
            self.assertIn("STREAK: 4/5", page._q_mastery_badge.text())

            # 3. Test misread reporting (Ctrl+C): advances streak to 5 and retires 11!
            page._scratchpad._strokes = [[QPointF(10, 10), QPointF(20, 20)]]
            page._copy_misread_to_clipboard()
            # Since streak was 4, reporting misread credits it to 5 and retires 11!
            self.assertEqual(page._item_streaks[11], 5)
            self.assertIn(11, page._mastered_items)
            self.assertNotIn(11, page._all_pool)
            self.assertEqual(len(page._all_pool), 1)
            self.assertIn(12, page._all_pool)

            # Verify that _pick_next_item NEVER revives 11
            for _ in range(5):
                next_item = page._pick_next_item()
                self.assertEqual(next_item, 12)

            # 5. Now answer 12 correctly 5 times to master ALL targets
            page._current_q_item = 12
            page._ans = 144
            for streak_step in range(1, 6):
                page._ans_in.setText("144")
                page._check()

            # Pool should be empty now
            self.assertEqual(len(page._all_pool), 0)
            self.assertIn(12, page._mastered_items)

            # Trigger celebration
            page._show_all_mastered_celebration()

            # Page 3 must be visible and have celebration content
            self.assertFalse(page._p3.isHidden())
            self.assertEqual(page._p3_title.text(), "MASTERY CELEBRATION")
            self.assertEqual(page._rep_trophy.text(), "🏆")
            self.assertEqual(page._rep_badge.text(), "ALL TARGETS MASTERED!")
            self.assertTrue(len(page._quote_text_lbl.text()) > 0)
            self.assertTrue(len(page._quote_author_lbl.text()) > 0)
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_custom_streak_target_retirement(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            page._mode = 2  # Squares
            page._rchk = {"11-12": True}
            page._streak_target = 3  # Custom target: 3
            page._start_practice()

            page._current_q_item = 11
            page._ans = 121

            # Answer 1 & 2
            page._ans_in.setText("121")
            page._check()
            self.assertIn("STREAK: 1/3", page._q_mastery_badge.text())
            page._ans_in.setText("121")
            page._check()
            self.assertIn("STREAK: 2/3", page._q_mastery_badge.text())
            self.assertIn(11, page._all_pool)

            # Answer 3 -> Should retire immediately!
            page._ans_in.setText("121")
            page._check()
            self.assertEqual(page._item_streaks[11], 3)
            self.assertIn(11, page._mastered_items)
            self.assertNotIn(11, page._all_pool)
            self.assertIn("MASTERED! 3/3", page._q_mastery_badge.text())
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_endless_streak_mode(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            page._mode = 2  # Squares
            page._rchk = {"11-12": True}
            page._streak_target = 0  # Endless mode: 0
            page._start_practice()

            page._current_q_item = 11
            page._ans = 121

            # Answer correctly 10 times -> Card should NEVER retire!
            for s in range(1, 11):
                page._ans_in.setText("121")
                page._check()
                self.assertEqual(page._item_streaks[11], s)
                self.assertIn(11, page._all_pool)
                self.assertNotIn(11, page._mastered_items)
                self.assertIn(f"STREAK: {s} (ENDLESS ∞)", page._q_mastery_badge.text())
                self.assertIn("ACTIVE TARGETS: 2 (ENDLESS)", page._q_pool_progress_lbl.text())
        finally:
            page.deleteLater()
            QApplication.processEvents()

    def test_timer_and_streak_buttons_page1(self):
        from ui.math_trainer import MathTrainerPage
        page = MathTrainerPage()
        try:
            # 10 timer options
            expected_timers = [0, 1, 2, 3, 5, 10, 15, 20, 25, 30]
            self.assertEqual(set(page._timer_btns.keys()), set(expected_timers))

            # 8 streak options
            expected_streaks = [1, 2, 3, 4, 5, 7, 10, 0]
            self.assertEqual(set(page._streak_btns.keys()), set(expected_streaks))

            # Test clicking streak button sets target
            page._streak_btns[7].click()
            self.assertEqual(page._streak_target, 7)
            self.assertTrue(page._streak_btns[7].isChecked())
            self.assertFalse(page._streak_btns[5].isChecked())

            # Reset back to defaults for persistent config cleanliness
            page._streak_btns[5].click()
            page._timer_btns[0].click()
        finally:
            page.deleteLater()
            QApplication.processEvents()



