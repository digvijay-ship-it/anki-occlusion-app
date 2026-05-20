import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from services import shortcut_manager
from services.review_manager import QUEUE_ROLE, ReviewSessionManager
from ui.review_screen import ReviewScreen

_APP = QApplication.instance() or QApplication([])


class ReviewScreenRatingButtonTests(unittest.TestCase):
    def setUp(self):
        shortcut_manager.reset_shortcuts()
        self.addCleanup(shortcut_manager.reset_shortcuts)

    def test_review_mode_exposes_five_rating_buttons_and_shortcuts(self):
        self.assertEqual(len(ReviewScreen.RATINGS), 5)
        self.assertEqual(ReviewScreen.RATINGS[-1], ("5  ⭐ Perfect", "perfect", 6))
        self.assertEqual(ReviewScreen.RATING_SHORTCUTS[Qt.Key_5], 6)
        self.assertEqual(ReviewScreen.RATING_LABELS[-1], "Perfect")

    def test_rating_shortcut_uses_saved_binding(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        shortcut_manager.set_shortcut("review.rate_perfect", "P")
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_P, Qt.NoModifier)

        self.assertEqual(screen._rating_quality_for_event(event), 6)

    def test_t_shortcut_opens_annotation_from_review_mode(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._mode = "review"
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._open_annotation_beta = MagicMock()
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_T, Qt.NoModifier)

        screen.keyPressEvent(event)

        screen._open_annotation_beta.assert_called_once_with()

    def test_queue_drawer_locked_keeps_queue_visible(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = True
        screen._queue_drawer_open = False
        screen._queue_panel = MagicMock()
        screen._queue_list = MagicMock()
        screen._queue_edge_button = MagicMock()
        screen._queue_lock_button = MagicMock()
        screen._queue_hide_button = MagicMock()

        screen._apply_queue_drawer_state(recenter=False)

        screen._queue_panel.setVisible.assert_called_once_with(True)
        screen._queue_list.setVisible.assert_called_once_with(True)
        screen._queue_lock_button.setText.assert_called_once_with("🔒")
        screen._queue_hide_button.setVisible.assert_called_once_with(False)
        screen._queue_edge_button.setVisible.assert_called_once_with(False)

    def test_queue_drawer_unlocked_hides_panel_until_opened(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_panel = MagicMock()
        screen._queue_list = MagicMock()
        screen._queue_edge_button = MagicMock()
        screen._queue_lock_button = MagicMock()
        screen._queue_hide_button = MagicMock()

        screen._hide_queue_drawer()

        self.assertFalse(screen._queue_drawer_open)
        screen._queue_panel.setVisible.assert_called_with(False)
        screen._queue_list.setVisible.assert_called_with(False)
        screen._queue_lock_button.setText.assert_called_with("🔓")
        screen._queue_hide_button.setVisible.assert_called_with(True)
        screen._queue_hide_button.setText.assert_called_with("‹")
        screen._queue_hide_button.setToolTip.assert_called_with("Show queue items")

        screen._open_queue_drawer()

        self.assertTrue(screen._queue_drawer_open)
        screen._queue_panel.setVisible.assert_called_with(True)
        screen._queue_list.setVisible.assert_called_with(True)
        screen._queue_hide_button.setVisible.assert_called_with(True)
        screen._queue_hide_button.setText.assert_called_with("›")
        screen._queue_hide_button.setToolTip.assert_called_with("Hide queue items")

    def test_queue_drawer_toggle_only_changes_queue_list_visibility(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_panel = MagicMock()
        screen._queue_list = MagicMock()
        screen._queue_edge_button = MagicMock()
        screen._queue_lock_button = MagicMock()
        screen._queue_hide_button = MagicMock()
        screen._queue_auto_hide_timer = MagicMock()

        screen._toggle_queue_drawer()

        self.assertFalse(screen._queue_drawer_open)
        screen._queue_panel.setVisible.assert_called_with(False)
        screen._queue_list.setVisible.assert_called_with(False)

        screen._toggle_queue_drawer()

        self.assertTrue(screen._queue_drawer_open)
        screen._queue_panel.setVisible.assert_called_with(True)
        screen._queue_list.setVisible.assert_called_with(True)

    def test_unlocked_hidden_queue_panel_stays_off_pdf_canvas(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_edge_button = MagicMock()
        screen._queue_lock_button = MagicMock()
        screen._queue_hide_button = MagicMock()

        screen._mid_widget = QWidget()
        screen._mid_layout = QHBoxLayout(screen._mid_widget)
        screen._mid_layout.setContentsMargins(0, 0, 0, 0)
        screen._canvas_stage = QWidget()
        screen._canvas_stage.resize(640, 480)
        screen._queue_panel = QWidget()
        qp_l = QVBoxLayout(screen._queue_panel)
        qp_l.addWidget(QLabel("timer"))
        qp_l.addWidget(QLabel("queue header"))
        screen._queue_list = QListWidget()
        screen._queue_list.addItem("p. 2 - #5")
        qp_l.addWidget(screen._queue_list, stretch=1)
        screen._mid_layout.addWidget(screen._canvas_stage)
        screen._mid_layout.addWidget(screen._queue_panel)
        screen._queue_panel_docked = True

        screen._apply_queue_drawer_state(recenter=False)

        self.assertFalse(screen._queue_panel_docked)
        self.assertIs(screen._queue_panel.parent(), screen._canvas_stage)
        self.assertTrue(screen._queue_list.isHidden())
        self.assertTrue(screen._queue_panel.isHidden())
        self.assertEqual(screen._queue_panel.width(), 200)
        self.assertEqual(screen._queue_panel.x(), screen._canvas_stage.width() - 208)

    def test_unlocked_open_queue_panel_moves_before_showing_as_overlay(self):
        class RecordingPanel(QWidget):
            def __init__(self):
                super().__init__()
                self.events = []

            def hide(self):
                self.events.append(("visible", False))
                super().hide()

            def show(self):
                self.events.append(("visible", True))
                super().show()

            def setVisible(self, visible):
                self.events.append(("visible", bool(visible)))
                super().setVisible(visible)

            def move(self, *args):
                self.events.append(("move", args))
                super().move(*args)

        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_edge_button = MagicMock()
        screen._queue_lock_button = MagicMock()
        screen._queue_hide_button = MagicMock()

        screen._mid_widget = QWidget()
        screen._mid_layout = QHBoxLayout(screen._mid_widget)
        screen._mid_layout.setContentsMargins(0, 0, 0, 0)
        screen._canvas_stage = QWidget()
        screen._canvas_stage.resize(640, 480)
        screen._queue_panel = RecordingPanel()
        qp_l = QVBoxLayout(screen._queue_panel)
        qp_l.addWidget(QLabel("timer"))
        screen._queue_list = QListWidget()
        qp_l.addWidget(screen._queue_list, stretch=1)
        screen._mid_layout.addWidget(screen._canvas_stage)
        screen._mid_layout.addWidget(screen._queue_panel)
        screen._queue_panel_docked = True

        screen._apply_queue_drawer_state(recenter=False)

        first_move = next(
            i for i, event in enumerate(screen._queue_panel.events) if event[0] == "move"
        )
        first_visible_true = next(
            i
            for i, event in enumerate(screen._queue_panel.events)
            if event == ("visible", True)
        )
        self.assertLess(first_move, first_visible_true)

    def test_unlocked_closed_queue_panel_shows_compact_timer_only(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_edge_button = MagicMock()
        screen._queue_lock_button = MagicMock()
        screen._queue_hide_button = MagicMock()
        screen._floating_timer_visible = False

        screen._mid_widget = QWidget()
        screen._mid_layout = QHBoxLayout(screen._mid_widget)
        screen._mid_layout.setContentsMargins(0, 0, 0, 0)
        screen._canvas_stage = QWidget()
        screen._canvas_stage.resize(640, 480)
        screen._floating_timer_frame = QWidget(screen._canvas_stage)
        screen._floating_timer_frame.hide()
        screen._floating_timer_session = QLabel()
        screen._floating_timer_today = QLabel()
        screen._stimer = MagicMock()
        screen._stimer.label_session.text.return_value = "0:01:02"
        screen._stimer.label_today.text.return_value = "0:03:04"
        screen._queue_panel = QWidget()
        qp_l = QVBoxLayout(screen._queue_panel)
        qp_l.addWidget(QLabel("timer"))
        screen._queue_list = QListWidget()
        qp_l.addWidget(screen._queue_list, stretch=1)
        screen._mid_layout.addWidget(screen._canvas_stage)
        screen._mid_layout.addWidget(screen._queue_panel)
        screen._queue_panel_docked = True

        screen._apply_queue_drawer_state(recenter=False)

        self.assertFalse(screen._queue_panel.isVisible())
        self.assertFalse(screen._floating_timer_frame.isHidden())
        self.assertEqual(screen._floating_timer_session.text(), "0:01:02")
        self.assertEqual(screen._floating_timer_today.text(), "0:03:04")

    def test_floating_timer_uses_large_readable_font(self):
        self.assertEqual(ReviewScreen.FLOATING_TIMER_SESSION_FONT_PX, 36)
        self.assertEqual(ReviewScreen.FLOATING_TIMER_TODAY_FONT_PX, 30)

    def test_floating_timer_is_raised_again_after_page_scroll(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._floating_timer_frame = MagicMock()
        screen._floating_timer_frame.isHidden.return_value = False
        screen._reposition_floating_timer = MagicMock()

        with patch(
            "ui.review_screen.QTimer.singleShot",
            side_effect=lambda _delay, fn: fn(),
        ):
            screen._keep_floating_timer_on_top()

        self.assertEqual(screen._reposition_floating_timer.call_count, 2)

    def test_queue_edge_handle_shows_at_right_border_when_unlocked_hidden(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_panel = QWidget()
        screen._queue_panel.hide()
        screen._queue_edge_button = MagicMock()
        screen._reposition_queue_edge_handle = MagicMock()
        screen.width = MagicMock(return_value=1000)
        screen.height = MagicMock(return_value=600)
        screen.mapFromGlobal = MagicMock()
        event = MagicMock()
        event.pos.return_value.x.return_value = 995
        event.globalPos.side_effect = AttributeError()

        screen._maybe_show_queue_edge_handle(event)

        screen._queue_edge_button.show.assert_called_once_with()
        screen._queue_edge_button.raise_.assert_called_once_with()

    def test_queue_edge_handle_stays_hidden_when_panel_visible(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_panel = QWidget()
        screen._queue_panel.show()
        screen._queue_edge_button = MagicMock()
        event = MagicMock()

        screen._maybe_show_queue_edge_handle(event)

        screen._queue_edge_button.show.assert_not_called()

    def test_unlocked_queue_starts_auto_hide_timer_when_cursor_leaves(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_panel = MagicMock()
        screen._queue_panel.isVisible.return_value = True
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_auto_hide_timer.isActive.return_value = False
        screen._queue_contains_global_pos = MagicMock(return_value=False)
        event = MagicMock()

        screen._update_queue_auto_hide_from_event(event)

        screen._queue_auto_hide_timer.start.assert_called_once_with(
            ReviewScreen.QUEUE_AUTO_HIDE_MS
        )

    def test_unlocked_queue_does_not_restart_active_auto_hide_timer_outside(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_panel = MagicMock()
        screen._queue_panel.isVisible.return_value = True
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_auto_hide_timer.isActive.return_value = True
        screen._queue_contains_global_pos = MagicMock(return_value=False)
        event = MagicMock()

        screen._update_queue_auto_hide_from_event(event)

        screen._queue_auto_hide_timer.start.assert_not_called()

    def test_unlocked_queue_cancels_auto_hide_when_cursor_returns(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_panel = MagicMock()
        screen._queue_panel.isVisible.return_value = True
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_contains_global_pos = MagicMock(return_value=True)
        event = MagicMock()

        screen._update_queue_auto_hide_from_event(event)

        screen._queue_auto_hide_timer.stop.assert_called_once_with()
        screen._queue_auto_hide_timer.start.assert_not_called()

    def test_queue_auto_hide_timer_hides_only_if_cursor_stays_outside(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_contains_global_pos = MagicMock(return_value=False)
        screen._hide_queue_drawer = MagicMock()

        screen._hide_queue_drawer_after_delay()

        screen._hide_queue_drawer.assert_called_once_with()

    def test_queue_auto_hide_timer_resets_if_cursor_returns_before_timeout(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = True
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_contains_global_pos = MagicMock(return_value=True)
        screen._hide_queue_drawer = MagicMock()

        screen._hide_queue_drawer_after_delay()

        screen._queue_auto_hide_timer.stop.assert_called_once_with()
        screen._hide_queue_drawer.assert_not_called()

    def test_default_review_pen_is_active(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._review_ink_width = 2.6
        screen.canvas = MagicMock()

        screen._activate_default_review_pen()

        self.assertEqual(screen.canvas._ink_width, 2.6)
        screen.canvas.ink_set_active.assert_called_once_with(True)

    def test_queue_state_sync_updates_only_changed_rows(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_list = QListWidget()
        screen._update_queue_label = MagicMock()
        mgr = ReviewSessionManager(screen)
        mgr._items = [
            ({"title": "A"}, None, {"sm2_due": "2000-01-01T00:00:00"}),
            ({"title": "B"}, None, {"sm2_due": "2000-01-01T00:00:00"}),
        ]
        mgr._idx = 0
        mgr._rebuild_queue()
        first_item = screen._queue_list.item(0)
        second_item = screen._queue_list.item(1)

        mgr._idx = 1
        mgr._sync_queue_state()

        self.assertIs(screen._queue_list.item(0), first_item)
        self.assertIs(screen._queue_list.item(1), second_item)
        self.assertEqual(first_item.data(QUEUE_ROLE), "done")
        self.assertEqual(second_item.data(QUEUE_ROLE), "current")

    def test_adapt_review_boxes_reuses_cached_result(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._pdf_render_zoom = 2.0
        screen._review_adapted_boxes_cache = {}
        card = {
            "_pdf_box_render_zoom": 1.5,
            "boxes": [
                {
                    "box_id": "b1",
                    "group_id": "",
                    "rect": [1, 2, 3, 4],
                    "page_num": 0,
                }
            ],
        }
        adapted = [{"box_id": "b1", "rect": [2, 4, 6, 8], "page_num": 0}]

        with patch(
            "ui.review_screen.adapt_pdf_boxes_to_render_zoom",
            return_value=adapted,
        ) as adapt:
            first = screen._adapt_review_boxes(card, r"C:\tmp\deck.pdf")
            second = screen._adapt_review_boxes(card, r"C:\tmp\deck.pdf")

        self.assertEqual(adapt.call_count, 1)
        self.assertEqual(first, adapted)
        self.assertEqual(second, adapted)
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
