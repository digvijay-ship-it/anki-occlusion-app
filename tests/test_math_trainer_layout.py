import os
import sys
import unittest
import unittest.mock as mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QPointF
from ui.math_trainer import MathTrainerPage

class TestMathTrainerLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.page = MathTrainerPage()
        self.page.show()

    def tearDown(self):
        self.page.deleteLater()
        self.app.processEvents()

    def test_compact_dimensions(self):
        # Scan card height should be 150 (compacted from 200)
        self.assertEqual(self.page._scan_card.height(), 150)
        # Answer box height should be 88 (compacted from 120)
        self.assertEqual(self.page._ans_in.height(), 88)
        # Main scratchpad minimum height should be >= 240
        self.assertGreaterEqual(self.page._scratchpad.minimumHeight(), 240)

    def test_secondary_rough_pad_presence(self):
        self.assertTrue(hasattr(self.page, "_side_scratchpad"))
        self.assertFalse(self.page._side_scratchpad._enable_ocr)
        self.assertIn("ROUGH", self.page._side_scratchpad._label_text)

    def test_mode2_reveal_compact_card(self):
        self.page._mode = 2
        self.page._ans = 196
        self.page._q_lbl.setText("14² = ?")
        self.page._reveal()

        self.assertFalse(self.page._reveal_card.isHidden())
        self.assertTrue(self.page._reveal_scroll.isHidden())
        self.assertTrue(self.page._reveal_hint.isHidden())
        self.assertIn("196", self.page._reveal_card_val.text())

    def test_gen_q_resets_panels(self):
        self.page._gen_q()
        self.assertTrue(self.page._reveal_card.isHidden())
        self.assertTrue(self.page._reveal_scroll.isHidden())
        self.assertFalse(self.page._reveal_hint.isHidden())

    def test_rough_pad_clear_isolation(self):
        self.page._scratchpad._strokes = [[QPointF(1, 1), QPointF(2, 2)]]
        self.page._side_scratchpad._strokes = [[QPointF(5, 5), QPointF(6, 6)]]
        self.page._clear_side_scratchpad()

        self.assertEqual(len(self.page._side_scratchpad._strokes), 0)
        self.assertEqual(len(self.page._scratchpad._strokes), 1)

    def test_mode1_table_reveal_uses_scroll(self):
        self.page._mode = 1
        self.page._ans = 196
        self.page._q_lbl.setText("14 × 14 = ?")
        self.page._reveal()

        self.assertFalse(self.page._reveal_scroll.isHidden())
        self.assertTrue(self.page._reveal_card.isHidden())

    def test_back_button_exits_without_confirmation(self):
        self.page._mode = 2
        self.page._rchk = {"11-12": True}
        self.page._start_practice()
        self.assertFalse(self.page._p2.isHidden())

        with mock.patch.object(self.page, "_prompt_exit_confirmation") as mock_prompt:
            self.page._back_btn_p2.click()
            mock_prompt.assert_not_called()
            self.assertTrue(self.page._p2.isHidden())
            self.assertFalse(self.page._p1.isHidden())

    def test_escape_in_practice_mode_prompts_confirmation(self):
        from PyQt5.QtGui import QKeyEvent
        from PyQt5.QtCore import QEvent, Qt
        self.page._mode = 2
        self.page._rchk = {"11-12": True}
        self.page._start_practice()
        self.assertFalse(self.page._p2.isHidden())

        # With empty pads, pressing Escape calls _prompt_exit_confirmation
        with mock.patch.object(self.page, "_prompt_exit_confirmation") as mock_prompt:
            esc_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
            self.page.keyPressEvent(esc_event)
            mock_prompt.assert_called_once()

    def test_escape_confirmation_accepted_and_rejected_flow(self):
        from PyQt5.QtWidgets import QDialog
        self.page._mode = 2
        self.page._rchk = {"11-12": True}
        self.page._start_practice()
        self.assertFalse(self.page._p2.isHidden())

        # 1. Rejected -> Stays on page 2
        with mock.patch("ui.math_trainer.DojoExitConfirmationDialog.exec_", return_value=QDialog.Rejected):
            self.page._prompt_exit_confirmation()
            self.assertFalse(self.page._p2.isHidden())

        # 2. Accepted -> Navigates to page 1
        with mock.patch("ui.math_trainer.DojoExitConfirmationDialog.exec_", return_value=QDialog.Accepted):
            self.page._prompt_exit_confirmation()
            self.assertTrue(self.page._p2.isHidden())
            self.assertFalse(self.page._p1.isHidden())

    def test_manual_reset_button_and_streak_persistence(self):
        self.page._mode = 2
        self.page._rchk = {"11-12": True}
        self.page._start_practice()
        
        # Verify reset button exists
        self.assertTrue(hasattr(self.page, "_reset_streak_btn"))
        self.assertIn("RESET", self.page._reset_streak_btn.text())

        # Set up a positive streak on current question and combo
        cur_item = self.page._current_q_item
        self.page._item_streaks[cur_item] = 3
        self.page._streak = 5
        self.page._combo_val.setText("5")
        self.page._update_mastery_ui()
        self.assertIn("3/", self.page._q_mastery_badge.text())

        # 1. Wrong answer entered in _check() -> STREAK AND COMBO MUST PERSIST (not decrease or wipe automatically)
        wrong_ans = "999" if self.page._ans != 999 else "111"
        self.page._ans_in.setText(wrong_ans)
        self.page._check()

        self.assertEqual(self.page._item_streaks[cur_item], 3, "Question streak should NOT decrease automatically on wrong answer")
        self.assertEqual(self.page._streak, 5, "Combo streak should NOT reset automatically on wrong answer")
        self.assertIn("3/", self.page._q_mastery_badge.text())

        # 2. Reveal answer -> STREAK AND COMBO MUST PERSIST
        self.page._reveal()
        self.assertEqual(self.page._item_streaks[cur_item], 3, "Question streak should NOT reset automatically on reveal")
        self.assertEqual(self.page._streak, 5, "Combo streak should NOT reset automatically on reveal")

        # 3. Manual Reset button click -> EXPLICIT RESET of both streak and combo
        self.page._reset_streak_btn.click()
        self.assertEqual(self.page._item_streaks[cur_item], 0, "Question streak must reset to 0 upon clicking Reset button")
        self.assertEqual(self.page._streak, 0, "Combo must reset to 0 upon clicking Reset button")
        self.assertEqual(self.page._combo_val.text(), "0")
        self.assertIn("0/", self.page._q_mastery_badge.text())

if __name__ == "__main__":
    unittest.main()
