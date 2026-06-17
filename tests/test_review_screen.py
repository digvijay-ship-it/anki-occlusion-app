import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, Qt
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

    def test_review_control_metrics_scale_reveal_and_rating_buttons(self):
        classic = ReviewScreen._review_control_metrics(dojo=False)
        dojo = ReviewScreen._review_control_metrics(dojo=True)

        self.assertEqual(classic["reveal_padding_y"], round(8 * 1.3))
        self.assertEqual(classic["reveal_padding_x"], round(40 * 1.3))
        self.assertEqual(classic["reveal_font"], round(13 * 1.3))
        self.assertEqual(classic["rating_height"], round(40 * 1.3))
        self.assertEqual(classic["rating_min_width"], round(140 * 1.3))
        self.assertEqual(classic["rating_font"], round(13 * 1.3))
        self.assertEqual(dojo["rating_height"], round(44 * 1.3))

    def test_rating_shortcut_uses_saved_binding(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        shortcut_manager.set_shortcut("review.rate_perfect", "P")
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_P, Qt.NoModifier)

        self.assertEqual(screen._rating_quality_for_event(event), 6)

    def test_review_profile_enables_for_matching_pdf_filter(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        cards = [{"title": "Biology", "pdf_path": "pdfs/Cell Structure.pdf"}]

        with patch.dict(
            os.environ,
            {"ANKI_REVIEW_PROFILE": "1", "ANKI_REVIEW_PROFILE_PDF": "cell"},
            clear=False,
        ), patch("builtins.print") as printed:
            screen._init_review_profile(cards)
            screen._review_profile_log("probe", file="Cell Structure.pdf")

        self.assertTrue(screen._review_profile_active())
        self.assertGreaterEqual(printed.call_count, 2)

    def test_review_profile_stays_quiet_when_pdf_filter_does_not_match(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        cards = [{"title": "Chemistry", "pdf_path": "pdfs/Atoms.pdf"}]

        with patch.dict(
            os.environ,
            {"ANKI_REVIEW_PROFILE": "1", "ANKI_REVIEW_PROFILE_PDF": "cell"},
            clear=False,
        ), patch("builtins.print") as printed:
            screen._init_review_profile(cards)
            screen._review_profile_log("probe", file="Atoms.pdf")

        self.assertFalse(screen._review_profile_active())
        printed.assert_not_called()

    def test_review_profile_log_includes_memory_when_available(self):
        screen = ReviewScreen.__new__(ReviewScreen)

        with patch.dict(os.environ, {"ANKI_REVIEW_PROFILE": "1"}, clear=False), patch.object(
            ReviewScreen, "_review_profile_rss_mb", return_value=123.4
        ), patch("builtins.print") as printed:
            screen._init_review_profile([{"title": "Cell", "pdf_path": "cell.pdf"}])
            screen._review_profile_log("probe")

        output = "\n".join(call.args[0] for call in printed.call_args_list)
        self.assertIn("rss=123.4MB", output)
        self.assertIn("peak_rss=123.4MB", output)

    def test_review_viewport_debug_is_quiet_unless_verbose_enabled(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._note_user_activity = MagicMock()
        screen._ondemand_path = "sample.pdf"
        screen._ondemand_total = 2
        screen._review_defer_visible_until_centered = False
        screen._visible_debug_seen_pages = set()
        screen._inject_cached_visible_pages = MagicMock()
        screen._review_pages_needing_render = MagicMock(return_value=[])
        screen._review_page_view_state = MagicMock(return_value="canvas_real")

        with patch.dict(os.environ, {"ANKI_REVIEW_VERBOSE": ""}, clear=False), patch(
            "builtins.print"
        ) as printed:
            screen._on_visible_pages_changed(0, 0)

        printed.assert_not_called()

    def test_review_viewport_debug_prints_when_verbose_enabled(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._note_user_activity = MagicMock()
        screen._ondemand_path = "sample.pdf"
        screen._ondemand_total = 2
        screen._review_defer_visible_until_centered = False
        screen._visible_debug_seen_pages = set()
        screen._inject_cached_visible_pages = MagicMock()
        screen._review_pages_needing_render = MagicMock(return_value=[])
        screen._review_page_view_state = MagicMock(return_value="canvas_real")

        with patch.dict(os.environ, {"ANKI_REVIEW_VERBOSE": "1"}, clear=False), patch(
            "builtins.print"
        ) as printed:
            screen._on_visible_pages_changed(0, 0)

        output = "\n".join(call.args[0] for call in printed.call_args_list)
        self.assertIn("[DEBUG][review_viewport]", output)

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

    def test_alt_t_shortcut_toggles_floating_timer(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._mode = "review"
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._toggle_floating_timer_visibility = MagicMock()
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_T, Qt.AltModifier)

        screen.keyPressEvent(event)

        screen._toggle_floating_timer_visibility.assert_called_once()

    def test_toggle_floating_timer_visibility_toggles_state_and_toasts(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen._floating_timer_frame = MagicMock()
        screen._floating_timer_sync_timer = MagicMock()
        screen._set_floating_timer_sync_enabled = MagicMock()
        screen._update_floating_timer_visibility = MagicMock()

        screen._user_timer_hidden = False

        # Toggle to hide
        screen._toggle_floating_timer_visibility()
        self.assertTrue(screen._user_timer_hidden)
        screen._floating_timer_frame.hide.assert_called_once()
        screen._set_floating_timer_sync_enabled.assert_called_once_with(False)
        screen.canvas._show_toast.assert_called_once_with("⏱ Timer Hidden (Press Alt+T to show)")

        # Reset mocks
        screen._floating_timer_frame.hide.reset_mock()
        screen._set_floating_timer_sync_enabled.reset_mock()
        screen.canvas._show_toast.reset_mock()

        # Toggle to show
        screen._toggle_floating_timer_visibility()
        self.assertFalse(screen._user_timer_hidden)
        screen._update_floating_timer_visibility.assert_called_once()

    def test_draggable_frame_drag_events(self):
        from PyQt5.QtGui import QMouseEvent
        from ui.review_screen import DraggableFrame
        
        parent = QWidget()
        parent.resize(800, 600)

        on_release_called = []
        def on_release(x, y):
            on_release_called.append((x, y))

        frame = DraggableFrame(parent, on_release=on_release)
        frame.resize(100, 50)
        frame.show()

        # Test press event
        press_event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPoint(10, 10),
            QPoint(100, 100),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier
        )
        frame.mousePressEvent(press_event)
        self.assertEqual(frame._drag_start_pos, QPoint(100, 100) - frame.frameGeometry().topLeft())

        # Test move event (drag)
        move_event = QMouseEvent(
            QEvent.MouseMove,
            QPoint(20, 20),
            QPoint(150, 120),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier
        )
        frame.mouseMoveEvent(move_event)

        # New pos should be updated based on drag
        self.assertEqual(frame.x(), 150 - frame._drag_start_pos.x())
        self.assertEqual(frame.y(), 120 - frame._drag_start_pos.y())

        # Test release event
        release_event = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(20, 20),
            QPoint(150, 120),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier
        )
        frame.mouseReleaseEvent(release_event)
        self.assertIsNone(frame._drag_start_pos)
        self.assertEqual(len(on_release_called), 1)
        self.assertEqual(on_release_called[0], (frame.x(), frame.y()))

    def test_reposition_respects_and_saves_settings(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._floating_timer_frame = MagicMock()
        screen._floating_timer_frame.width.return_value = 100
        screen._floating_timer_frame.height.return_value = 50
        screen._canvas_stage = MagicMock()
        screen._canvas_stage.width.return_value = 800
        screen._canvas_stage.height.return_value = 600

        with patch('ui.review_screen.QSettings') as MockQSettings:
            settings_mock = MockQSettings.return_value
            settings_mock.value.side_effect = lambda key, default: 0.5

            screen._timer_x_pct = 0.5
            screen._timer_y_pct = 0.5
            screen._reposition_floating_timer()

            # x = 0.5 * (800 - 100) = 350
            # y = 0.5 * (600 - 50) = 275
            screen._floating_timer_frame.move.assert_called_once_with(350, 275)

        # Test save method
        screen._floating_timer_frame.x.return_value = 350
        screen._floating_timer_frame.y.return_value = 275
        with patch('ui.review_screen.QSettings') as MockQSettings:
            settings_mock = MockQSettings.return_value
            screen._save_floating_timer_position(350, 275)

            self.assertEqual(screen._timer_x_pct, 0.5)
            self.assertEqual(screen._timer_y_pct, 0.5)
            settings_mock.setValue.assert_any_call("review/timer_x_pct", 0.5)
            settings_mock.setValue.assert_any_call("review/timer_y_pct", 0.5)

    def test_show_session_summary_shown_for_pdf_cards(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.finished = MagicMock()
        screen.prog = MagicMock()
        screen.mgr = MagicMock()

        card1 = {"pdf_path": "some_doc.pdf"}
        screen.mgr._items = [(card1, 0, {})]

        with patch("ui.review.summary_dialog.ReviewSessionSummaryDialog") as MockDialog:
            dialog_instance = MockDialog.return_value
            screen._show_session_summary()

            MockDialog.assert_called_once_with(screen)
            dialog_instance.exec_.assert_called_once()
            screen.finished.emit.assert_called_once()

    def test_show_session_summary_skipped_for_image_cards(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.finished = MagicMock()
        screen.prog = MagicMock()
        screen.mgr = MagicMock()

        card1 = {"image_path": "some_image.png"}
        card2 = {"title": "Text Card"}
        screen.mgr._items = [(card1, 0, {}), (card2, 1, {})]

        with patch("ui.review.summary_dialog.ReviewSessionSummaryDialog") as MockDialog:
            screen._show_session_summary()

            MockDialog.assert_not_called()
            screen.finished.emit.assert_called_once()

    def test_apply_annotation_beta_refresh_invalidates_cache_and_emits_pages(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen._canvas_scroll = MagicMock()
        screen._pdf_render_zoom = 2.0
        screen._review_canvas_real_pages = {0, 1}
        screen._start_review_lazy_trace = MagicMock()
        screen._update_review_page_nav_ui = MagicMock()
        screen._trigger_center_fit = MagicMock()
        screen._pdf_watcher = MagicMock()

        path = "test_path.pdf"
        changed_pages = [0]

        from ui.review.annotation_handler import apply_annotation_beta_refresh

        with patch("ui.review.annotation_handler.PAGE_CACHE") as MockCache:
            apply_annotation_beta_refresh(screen, path, changed_pages, None)

            # 1. PAGE_CACHE.invalidate_pages called for zoom variant
            MockCache.invalidate_pages.assert_any_call(path, [0], variant=2.0)
            # 2. Page 0 discarded from real pages
            self.assertEqual(screen._review_canvas_real_pages, {1})
            # 3. _canvas_scroll._emit_visible_pages called
            screen._canvas_scroll._emit_visible_pages.assert_called_once()

    def test_reload_current_canvas_prefers_pdf_over_image(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.mgr = MagicMock()
        screen.mgr._idx = 0
        screen._bg_pending_inserts = MagicMock()
        screen._close_bg_prefetch_dialog = MagicMock()
        screen._stop_skeleton_thread = MagicMock()
        screen._pdf_watcher = MagicMock()
        screen._start_review_skeleton_thread = MagicMock()

        card = {
            "card_type": "occlusion",
            "image_path": "test_image.png",
            "pdf_path": "test_pdf.pdf"
        }
        screen._items = [(card, 0, {})]

        with patch("ui.review_screen.os.path.exists", return_value=True), \
             patch("ui.review_screen.PDF_SUPPORT", True), \
             patch("ui.review_screen.resolve_asset_path", side_effect=lambda x: x):

            screen._reload_current_canvas()
            screen._pdf_watcher.watch_pdf.assert_called_once_with("test_pdf.pdf")

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
        screen._floating_timer_sync_timer = MagicMock()
        screen._floating_timer_sync_timer.isActive.return_value = False
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
        screen._floating_timer_sync_timer.start.assert_called_once_with()

    def test_floating_timer_waits_until_startup_overlay_positioned(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._review_overlays_ready = False
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._floating_timer_visible = True
        screen._canvas_stage = QWidget()
        screen._canvas_stage.resize(640, 480)
        screen._floating_timer_frame = QWidget(screen._canvas_stage)
        screen._floating_timer_frame.show()
        screen._floating_timer_sync_timer = MagicMock()
        screen._floating_timer_sync_timer.isActive.return_value = True
        screen._stimer = MagicMock()

        screen._update_floating_timer_visibility()

        self.assertTrue(screen._floating_timer_frame.isHidden())
        self.assertFalse(screen._floating_timer_visible)
        screen._floating_timer_sync_timer.stop.assert_called_once_with()

    def test_finish_initial_overlay_placement_shows_corner_timer_after_layout(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._review_overlays_ready = False
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_auto_hide_timer = MagicMock()
        screen._queue_edge_button = None
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
        screen._floating_timer_queue = QLabel()
        screen._floating_timer_sync_timer = MagicMock()
        screen._floating_timer_sync_timer.isActive.return_value = False
        screen._queue_timer_count = None
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

        screen._finish_initial_overlay_placement()

        self.assertTrue(screen._review_overlays_ready)
        self.assertFalse(screen._queue_panel.isVisible())
        self.assertFalse(screen._floating_timer_frame.isHidden())
        screen._floating_timer_sync_timer.start.assert_called_once_with()

    def test_floating_timer_hides_when_queue_is_open(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = True
        screen._queue_drawer_open = True
        screen._floating_timer_visible = False
        screen._canvas_stage = QWidget()
        screen._canvas_stage.resize(640, 480)
        screen._floating_timer_frame = QWidget(screen._canvas_stage)
        screen._floating_timer_frame.hide()
        screen._floating_timer_session = QLabel()
        screen._floating_timer_today = QLabel()
        screen._floating_timer_queue = QLabel()
        screen._floating_timer_sync_timer = MagicMock()
        screen._floating_timer_sync_timer.isActive.return_value = True
        screen._stimer = MagicMock()
        screen._stimer.label_session.text.return_value = "0:00:17"
        screen._stimer.label_today.text.return_value = "0:22:00"
        screen._queue_list = QListWidget()
        for label in ("p.5 - #57", "p.5 - #58", "p.5 - #61"):
            screen._queue_list.addItem(label)

        screen._update_floating_timer_visibility()

        self.assertTrue(screen._floating_timer_frame.isHidden())
        screen._floating_timer_sync_timer.stop.assert_called_once_with()

    def test_queue_label_updates_timer_queue_counts(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_label = QLabel()
        screen._floating_timer_queue = QLabel()
        screen._queue_timer_count = QLabel()

        screen._update_queue_label(3)

        self.assertIn("(3)", screen._queue_label.text())
        self.assertEqual(screen._floating_timer_queue.text(), "QUEUE (3)")
        self.assertEqual(screen._queue_timer_count.text(), "TO REVIEW: 3")

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

        self.assertEqual(screen._reposition_floating_timer.call_count, 1)

    def test_review_scroll_page_changed_skips_same_page_ui_update(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas.get_current_page.return_value = 2
        screen._review_ui_page_zero = 2
        screen._pdf_viewer = MagicMock()
        screen._keep_floating_timer_on_top = MagicMock()

        with patch.dict(os.environ, {"ANKI_REVIEW_SCROLL_PROFILE": "0"}, clear=False):
            screen._on_review_scroll_page_changed(1200)

        screen._pdf_viewer.set_page_ui.assert_not_called()
        screen._keep_floating_timer_on_top.assert_not_called()

    def test_review_scroll_profile_logs_compact_timing(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._review_scroll_profile_last_event_ts = None
        screen._review_scroll_profile_last_log_ts = 0.0

        with patch.dict(os.environ, {"ANKI_REVIEW_SCROLL_PROFILE": "1"}, clear=False), patch(
            "builtins.print"
        ) as printed:
            screen._log_review_scroll_profile(
                value=123,
                page_zero=4,
                page_changed=True,
                page_calc_ms=1.2,
                page_ui_ms=0.4,
                overlay_ms=0.3,
                total_ms=2.1,
            )

        output = "\n".join(call.args[0] for call in printed.call_args_list)
        self.assertIn("[PROFILE][review_scroll]", output)
        self.assertIn("page=p.5", output)
        self.assertIn("overlay=0.3ms", output)

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

    def test_queue_edge_handle_hides_when_cursor_leaves_right_edge(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_edge_handle_visible = True
        screen._queue_panel = QWidget()
        screen._queue_panel.hide()
        screen._queue_edge_button = MagicMock()
        screen.width = MagicMock(return_value=1000)
        screen.mapFromGlobal = MagicMock()
        event = MagicMock()
        event.pos.return_value = QPoint(800, 250)
        event.globalPos.side_effect = AttributeError()

        screen._maybe_show_queue_edge_handle(event)

        self.assertFalse(screen._queue_edge_handle_visible)
        screen._queue_edge_button.hide.assert_called_once_with()

    def test_queue_edge_handle_stays_visible_while_cursor_is_over_button(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_locked = False
        screen._queue_drawer_open = False
        screen._queue_edge_handle_visible = True
        screen._queue_panel = QWidget()
        screen._queue_panel.hide()
        screen._queue_edge_button = QWidget()
        screen._queue_edge_button.setGeometry(970, 250, 28, 58)
        screen._queue_edge_button.show()
        screen._reposition_queue_edge_handle = MagicMock()
        screen.width = MagicMock(return_value=1000)
        screen.mapFromGlobal = MagicMock()
        event = MagicMock()
        event.pos.return_value = QPoint(972, 260)
        event.globalPos.side_effect = AttributeError()

        screen._maybe_show_queue_edge_handle(event)

        self.assertTrue(screen._queue_edge_handle_visible)
        self.assertFalse(screen._queue_edge_button.isHidden())

    def test_queue_edge_handle_sits_flush_to_right_edge(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._queue_edge_button = QWidget()
        screen.width = MagicMock(return_value=1000)
        screen.height = MagicMock(return_value=600)

        screen._reposition_queue_edge_handle()

        self.assertEqual(
            screen._queue_edge_button.x(),
            1000 - screen._queue_edge_button.width(),
        )

    def test_event_pos_in_self_maps_button_local_mouse_position(self):
        screen = QWidget()
        button = QWidget(screen)
        button.setGeometry(972, 250, 28, 58)
        event = MagicMock()
        event.pos.return_value = QPoint(4, 10)
        event.globalPos.side_effect = AttributeError()

        pos = ReviewScreen._event_pos_in_self(screen, event, source=button)

        self.assertEqual(pos, QPoint(976, 260))

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


class ReviewScreenSequentialTests(unittest.TestCase):
    def test_state_to_restore_restores_all_fields_and_calls_undo(self):
        with patch.object(ReviewScreen, "_setup_ui"), \
             patch.object(ReviewScreen, "_review_undo") as mock_undo, \
             patch.object(ReviewScreen, "_init_review_profile"):
            
            cards = []
            state = {
                "items": [("card", None, "box")],
                "idx": 1,
                "done": 1,
                "undo_stack": ["snap"],
                "redo_stack": [],
                "queued_ids": {"box_id"},
                "deleted_ids": set(),
            }
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = MagicMock()
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            
            screen.__init__(cards, state_to_restore=state)
            
            self.assertEqual(screen._items, state["items"])
            self.assertEqual(screen._idx, 1)
            self.assertEqual(screen._done, 1)
            self.assertEqual(screen._review_undo_stack, ["snap"])
            self.assertEqual(screen._review_redo_stack, [])
            self.assertEqual(screen._queued_ids, {"box_id"})
            self.assertEqual(screen._deleted_ids, set())
            mock_undo.assert_called_once()

    def test_undo_requested_when_empty_signal_emitted(self):
        with patch.object(ReviewScreen, "_setup_ui"), \
             patch.object(ReviewScreen, "_init_review_profile"), \
             patch.object(ReviewScreen, "_load_item"):
            
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = MagicMock()
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            
            screen.__init__([])
            self.assertEqual(screen._review_undo_stack, [])
            
            # Setup signal listener
            listener = MagicMock()
            screen.undo_requested_when_empty.connect(listener)
            
            # Run undo when empty
            screen._review_undo()
            
            listener.assert_called_once()

    def test_undo_handled_flag_prevents_toast_on_empty_stack(self):
        with patch.object(ReviewScreen, "_setup_ui"), \
             patch.object(ReviewScreen, "_init_review_profile"), \
             patch.object(ReviewScreen, "_load_item"):
            
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = MagicMock()
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            
            screen.__init__([])
            
            def handle_undo():
                screen._undo_handled = True
            
            screen.undo_requested_when_empty.connect(handle_undo)
            
            screen._review_undo()
            
            screen.canvas._show_toast.assert_not_called()

    def test_undo_handled_when_rs_becomes_none_during_emit(self):
        with patch.object(ReviewScreen, "_setup_ui"), \
             patch.object(ReviewScreen, "_init_review_profile"), \
             patch.object(ReviewScreen, "_load_item"):
            
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = MagicMock()
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            
            screen.__init__([])
            
            def handle_undo():
                screen.mgr.rs = None
            
            screen.undo_requested_when_empty.connect(handle_undo)
            
            screen._review_undo()
            
            self.assertIsNone(screen.mgr.rs)


class ReviewScreenSummaryToggleTests(unittest.TestCase):
    def test_summary_toggle_initialization_defaults_to_true(self):
        with patch.object(ReviewScreen, "_setup_ui"), \
             patch.object(ReviewScreen, "_init_review_profile"), \
             patch.object(ReviewScreen, "_load_item"), \
             patch("ui.review_screen.QSettings") as MockQSettings:
             
            # Setup settings mock to return None/True by default
            settings_instance = MockQSettings.return_value
            settings_instance.value.return_value = True
            
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = MagicMock()
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            
            screen.__init__([])
            self.assertTrue(screen._show_summary_popup)

    def test_toggle_summary_popup_updates_state_and_settings(self):
        with patch.object(ReviewScreen, "_setup_ui"), \
             patch.object(ReviewScreen, "_init_review_profile"), \
             patch.object(ReviewScreen, "_load_item"), \
             patch("ui.review_screen.QSettings") as MockQSettings:
             
            settings_instance = MockQSettings.return_value
            screen = ReviewScreen.__new__(ReviewScreen)
            screen.canvas = MagicMock()
            screen._canvas_scroll = MagicMock()
            screen._queue_panel = MagicMock()
            screen._queue_list = MagicMock()
            screen._queue_edge_button = MagicMock()
            screen._queue_lock_button = MagicMock()
            screen._queue_hide_button = MagicMock()
            
            screen.__init__([])
            screen._btn_summary_toggle = MagicMock()
            
            # Toggle OFF
            screen._btn_summary_toggle.isChecked.return_value = False
            screen._toggle_summary_popup()
            self.assertFalse(screen._show_summary_popup)
            settings_instance.setValue.assert_called_with("review/show_summary_popup", False)
            
            # Toggle ON
            screen._btn_summary_toggle.isChecked.return_value = True
            screen._toggle_summary_popup()
            self.assertTrue(screen._show_summary_popup)
            settings_instance.setValue.assert_called_with("review/show_summary_popup", True)


if __name__ == "__main__":
    unittest.main()
