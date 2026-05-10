import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import unittest
import time
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent

from anki_occlusion_v19 import ReviewScreen
from ui.review_screen import ReviewScreen as UiReviewScreen

class ReviewScreenZoomTests(unittest.TestCase):
    def test_user_zoom_scale_tracked_on_canvas_zoom(self):
        # Create a blank instance without calling __init__ to avoid GUI complexities
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 1.5
        
        # Simulate the timer callback from the canvas
        screen._on_canvas_zoom_settled()
        
        # Verify the screen remembered the user zoom
        self.assertEqual(screen._user_zoom_scale, 1.5)

    def test_ctrl_zero_resets_user_zoom_scale(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 2.0
        screen._user_zoom_scale = 2.0
        screen._zoom_fit = MagicMock()
        
        # Mock attributes that keyPressEvent might touch
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        
        # Simulate Ctrl+0
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_0, Qt.ControlModifier)
        
        # Call the event handler directly
        screen.keyPressEvent(event)
            
        # Verify the user zoom was reset to auto-fit (None)
        self.assertIsNone(screen._user_zoom_scale)
        screen._zoom_fit.assert_called_once()

    def test_review_image_zoom_fit_uses_available_width_not_height(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._pages = []
        screen.canvas._scale = 1.0
        screen.canvas._canvas_wh.return_value = (400, 1200)
        viewport = MagicMock()
        viewport.width.return_value = 1000
        viewport.height.return_value = 800
        screen._canvas_scroll = MagicMock()
        screen._canvas_scroll.viewport.return_value = viewport

        with patch("builtins.print") as fake_print:
            screen._zoom_fit()

        self.assertAlmostEqual(screen.canvas._scale, 2.5)
        screen.canvas._on_zoom.assert_called_once()
        self.assertIn("[DEBUG][review_image_fit]", fake_print.call_args.args[0])

    def test_ctrl_plus_sets_user_zoom_scale(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 1.25 # New scale after zoom_in
        screen._user_zoom_scale = None
        
        # Mock attributes
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        
        # Simulate Ctrl+=
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Equal, Qt.ControlModifier)
        
        screen.keyPressEvent(event)
            
        # Verify the user zoom was saved
        self.assertEqual(screen._user_zoom_scale, 1.25)
        screen.canvas.zoom_in.assert_called_once()

    def test_c_key_recenters_without_printing_debug_report(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._scale = 1.1
        screen._user_zoom_scale = None
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        screen._zoom_fit = MagicMock()
        screen._center_on_target = MagicMock()
        screen._debug_report = MagicMock()

        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_C, Qt.NoModifier)

        screen.keyPressEvent(event)

        screen._zoom_fit.assert_called_once()
        screen._center_on_target.assert_called_once()
        screen._debug_report.assert_not_called()
        self.assertEqual(screen._user_zoom_scale, 1.1)

    def test_l_key_copies_current_pdf_file_in_review(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        screen._copy_current_pdf_file_to_clipboard = MagicMock()

        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_L, Qt.NoModifier)

        screen.keyPressEvent(event)

        screen._copy_current_pdf_file_to_clipboard.assert_called_once()

    def test_review_copy_pdf_file_places_file_url_on_clipboard(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen.canvas = MagicMock()
        screen._current_pdf_path_for_shortcuts = MagicMock(return_value=r"C:\tmp\deck.pdf")
        fake_clipboard = MagicMock()

        with patch("ui.review_screen.QApplication.clipboard", return_value=fake_clipboard):
            screen._copy_current_pdf_file_to_clipboard()

        mime = fake_clipboard.setMimeData.call_args.args[0]
        self.assertEqual(
            [os.path.normpath(url.toLocalFile()) for url in mime.urls()],
            [os.path.normpath(r"C:\tmp\deck.pdf")],
        )

    def test_ctrl_l_reveals_current_pdf_folder_in_review(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        screen._reveal_current_pdf_in_folder = MagicMock()

        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_L, Qt.ControlModifier)

        screen.keyPressEvent(event)

        screen._reveal_current_pdf_in_folder.assert_called_once()

    def test_open_annotation_beta_passes_image_space_anchor_y_from_review(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen.mgr = MagicMock()
        screen.mgr._idx = 0
        screen._items = [({"pdf_path": "deck.pdf"}, 0, {})]
        screen.canvas = MagicMock()
        screen.canvas._scale = 1.25
        screen.canvas.get_current_page.return_value = 2
        bar = MagicMock()
        bar.value.return_value = 250
        screen._canvas_scroll = MagicMock()
        screen._canvas_scroll.verticalScrollBar.return_value = bar
        screen._pause_review_lazy_activity_for_annotation = MagicMock()
        screen._resume_review_lazy_activity_after_annotation = MagicMock()
        screen._apply_annotation_beta_refresh = MagicMock()

        with patch("ui.review_screen.resolve_asset_path", return_value=r"C:\tmp\deck.pdf"), \
             patch("ui.review_screen.os.path.exists", return_value=True), \
             patch("ui.review_screen.PdfAnnotationDialog") as dialog_cls:
            dialog_instance = MagicMock()
            dialog_instance._saved_pages = []
            dialog_instance.return_page = None
            dialog_cls.return_value = dialog_instance

            screen._open_annotation_beta()

        self.assertEqual(dialog_cls.call_args.kwargs["initial_page"], 2)
        self.assertAlmostEqual(dialog_cls.call_args.kwargs["initial_anchor_y"], 200.0)

    def test_queue_jump_does_not_print_debug_report(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen.mgr = MagicMock()
        screen.mgr._items = [({"title": "Card"}, 23, {})]
        screen.mgr._idx = 0
        screen._peek_origin_idx = None
        screen._peek_idx = None
        screen.canvas = MagicMock()
        screen._rebuild_queue = MagicMock()
        screen._center_on_target = MagicMock()
        screen._debug_report = MagicMock()

        screen._jump_to_queue_index(0)

        screen._rebuild_queue.assert_called_once_with(peek_idx=0)
        screen._center_on_target.assert_called_once()
        screen._debug_report.assert_not_called()

    def test_review_pen_width_persists_separately(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen._review_ink_width = 1.2
        screen.canvas = MagicMock()
        screen.canvas._ink_width = 2.6

        fake_settings = MagicMock()
        fake_settings.value.return_value = "2.6"

        with patch("ui.review_screen.QSettings", return_value=fake_settings):
            screen._capture_review_ink_width("test")
            loaded = screen._load_review_ink_width()

        self.assertAlmostEqual(screen._review_ink_width, 2.6)
        fake_settings.setValue.assert_called_with("review/ink_width", 2.6)
        self.assertAlmostEqual(loaded, 2.6)

    def test_plus_key_updates_and_saves_review_pen_width(self):
        screen = ReviewScreen.__new__(ReviewScreen)
        screen.canvas = MagicMock()
        screen.canvas._ink_active = True
        screen.canvas._ink_width = 1.2
        screen._review_ink_width = 1.2
        screen._rating_frame = MagicMock()
        screen._rating_frame.isVisible.return_value = False
        screen._peek_idx = None
        screen._capture_review_ink_width = ReviewScreen._capture_review_ink_width.__get__(screen, ReviewScreen)

        def adjust(delta):
            screen.canvas._ink_width += delta

        screen.canvas.ink_adjust_width.side_effect = adjust

        fake_settings = MagicMock()
        with patch("ui.review_screen.QSettings", return_value=fake_settings):
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Plus, Qt.NoModifier)
            screen.keyPressEvent(event)

        screen.canvas.ink_adjust_width.assert_called_once_with(0.4)
        self.assertAlmostEqual(screen._review_ink_width, 1.6)
        fake_settings.setValue.assert_called_with("review/ink_width", 1.6)

    def test_review_on_page_ready_prints_lazy_load_debug(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._canvas_pdf_path = "deck.pdf"
        screen._ondemand_path = "deck.pdf"
        screen._ondemand_kind = "visible"
        screen._bg_pending_inserts = {}
        screen._update_review_page_nav_ui = MagicMock()
        screen.canvas = MagicMock()
        screen.canvas._pages = [None, None, None]
        screen.canvas.width.return_value = 900
        screen.canvas.height.return_value = 1400
        pixmap = MagicMock()
        pixmap.width.return_value = 200
        pixmap.height.return_value = 300

        with patch("builtins.print") as fake_print:
            screen._on_page_ready(1, pixmap)

        screen.canvas.inject_page.assert_called_once_with(1, pixmap)
        screen._update_review_page_nav_ui.assert_called_once()
        printed = [call.args[0] for call in fake_print.call_args_list]
        self.assertEqual(printed[0], "[DEBUG][review_lazy] 👀 p.2")
        self.assertEqual(printed[1], "[DEBUG][review_inject] p.2 injected=yes kind=visible")
        self.assertEqual(printed[2], "[DEBUG][review_ondemand] loaded p.2")

    def test_review_on_page_ready_prints_not_injected_for_background_queue(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._canvas_pdf_path = "deck.pdf"
        screen._ondemand_path = "deck.pdf"
        screen._ondemand_kind = "background"
        screen._bg_pending_inserts = {}
        screen.canvas = MagicMock()
        screen.canvas._pages = [None, None, None]
        screen.canvas.width.return_value = 900
        screen.canvas.height.return_value = 1400
        screen._update_review_page_nav_ui = MagicMock()
        pixmap = MagicMock()

        with patch("builtins.print") as fake_print:
            screen._on_page_ready(1, pixmap)

        self.assertIs(screen._bg_pending_inserts[1], pixmap)
        screen.canvas.inject_page.assert_not_called()
        printed = [call.args[0] for call in fake_print.call_args_list]
        self.assertEqual(printed[0], "[DEBUG][review_lazy] 👀 p.2")
        self.assertEqual(printed[1], "[DEBUG][review_inject] p.2 injected=no kind=background reason=queued_pending_insert")

    def test_review_start_visible_page_request_prints_ondemand_render_request(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._pdf_render_zoom = 2.0
        screen._on_visible_pages_batch_done = MagicMock()

        fake_thread = MagicMock()
        fake_thread.page_ready = MagicMock()
        fake_thread.batch_done = MagicMock()

        with patch("ui.review_screen.PdfOnDemandThread", return_value=fake_thread), \
             patch("builtins.print") as fake_print:
            screen._start_visible_page_request("deck.pdf", [3, 1, 3])

        fake_print.assert_any_call("[DEBUG][review_ondemand] render_request p.2, p.4")
        fake_thread.start.assert_called_once()
        self.assertEqual(screen._ondemand_kind, "visible")

    def test_visible_pages_changed_prints_only_newly_entered_pages(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._ondemand_path = "deck.pdf"
        screen._ondemand_total = 18
        screen._note_user_activity = MagicMock()
        screen._start_visible_page_request = MagicMock()
        screen._ondemand_thread = None
        screen._visible_debug_seen_pages = set()
        screen._review_canvas_real_pages = set()
        screen._review_render_inflight_pages = set()
        screen.canvas = MagicMock()
        placeholder = MagicMock()
        placeholder.isNull.return_value = False
        screen.canvas._pages = [placeholder for _ in range(18)]

        with patch("ui.review_screen.PAGE_CACHE.get", return_value=None), \
             patch("builtins.print") as fake_print:
            screen._on_visible_pages_changed(1, 3)
            screen._start_visible_page_request.reset_mock()
            screen._on_visible_pages_changed(2, 4)

        fake_print.assert_any_call("[DEBUG][review_viewport] visible=p.2-p.4 current=p.3:placeholder_gray entered=p.2:placeholder_gray, p.3:placeholder_gray, p.4:placeholder_gray")
        fake_print.assert_any_call("[DEBUG][review_viewport] visible=p.3-p.5 current=p.4:placeholder_gray entered=p.5:placeholder_gray")
        screen._start_visible_page_request.assert_called_once_with("deck.pdf", [2, 3, 4])

    def test_review_page_view_state_reports_cache_hot_gray_canvas(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._review_canvas_real_pages = set()
        screen._review_render_inflight_pages = set()
        screen._bg_pending_inserts = {}
        screen._pending_visible_request = None
        screen.canvas = MagicMock()
        placeholder = MagicMock()
        placeholder.isNull.return_value = False
        screen.canvas._pages = [placeholder]
        cached = MagicMock()
        cached.isNull.return_value = False

        with patch("ui.review_screen.PAGE_CACHE.get", return_value=cached):
            state = screen._review_page_view_state("deck.pdf", 0)

        self.assertEqual(state, "cache_hot_canvas_gray")

    def test_visible_pages_changed_injects_cache_hot_gray_pages(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._ondemand_path = "deck.pdf"
        screen._ondemand_total = 18
        screen._note_user_activity = MagicMock()
        screen._start_visible_page_request = MagicMock()
        screen._update_review_page_nav_ui = MagicMock()
        screen._ondemand_thread = None
        screen._visible_debug_seen_pages = set()
        screen._review_canvas_real_pages = set()
        screen._review_render_inflight_pages = set()
        screen._bg_pending_inserts = {}
        screen.canvas = MagicMock()
        screen.canvas.width.return_value = 900
        screen.canvas.height.return_value = 1400
        placeholder = MagicMock()
        placeholder.isNull.return_value = False
        screen.canvas._pages = [placeholder for _ in range(18)]
        cached = MagicMock()
        cached.isNull.return_value = False

        def fake_cache_get(path, page_num):
            return cached if page_num == 2 else None

        with patch("ui.review_screen.PAGE_CACHE.get", side_effect=fake_cache_get), \
             patch("builtins.print") as fake_print:
            screen._on_visible_pages_changed(2, 2)

        screen.canvas.inject_page.assert_called_once_with(2, cached)
        screen._start_visible_page_request.assert_not_called()
        screen._update_review_page_nav_ui.assert_called_once()
        self.assertIn(2, screen._review_canvas_real_pages)
        printed = [call.args[0] for call in fake_print.call_args_list]
        self.assertIn("[DEBUG][review_lazy] ⚡ p.3", printed)
        self.assertIn("[DEBUG][review_inject] p.3 injected=yes kind=visible_cache", printed)
        self.assertIn("[DEBUG][review_visible_cache] hydrate p.3", printed)

    def test_review_priority_pages_use_only_same_pdf_queue_pages(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen.mgr = MagicMock()
        same_pdf_a = {
            "pdf_path": "deck.pdf",
            "boxes": [
                {"page_num": 2},
                {"page_num": 5},
            ],
        }
        same_pdf_b = {
            "pdf_path": "deck.pdf",
            "boxes": [
                {"page_num": 6},
                {"page_num": 7},
                {"page_num": 8},
            ],
        }
        other_pdf = {
            "pdf_path": "other.pdf",
            "boxes": [
                {"page_num": 0},
            ],
        }
        screen.mgr._items = [
            (same_pdf_a, 0, {}),
            (same_pdf_a, 1, {}),
            (same_pdf_b, 0, {}),
            (same_pdf_b, 1, {}),
            (same_pdf_b, 2, {}),
            (other_pdf, 0, {}),
        ]

        with patch("builtins.print") as fake_print:
            result = screen._get_priority_pages(same_pdf_b, 1, 18, "deck.pdf")

        self.assertEqual(result, [2, 5, 6, 7, 8])
        fake_print.assert_any_call("[DEBUG][review_queue_pages] priority p.3, p.6, p.7, p.8, p.9")

    def test_review_priority_batch_done_does_not_start_background_fill(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._canvas_pdf_path = "deck.pdf"
        screen._start_background_fill = MagicMock()
        screen._background_fill_state = ("deck.pdf", [1, 2], 18)
        screen._ondemand_kind = "priority"

        screen._on_priority_batch_done("deck.pdf", [2, 5, 6], 18)

        screen._start_background_fill.assert_not_called()
        self.assertIsNone(screen._background_fill_state)
        self.assertIsNone(screen._ondemand_kind)

    def test_review_cache_debug_helper_prints_source_cache(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        pixmap = MagicMock()
        pixmap.width.return_value = 160
        pixmap.height.return_value = 240

        with patch("builtins.print") as fake_print:
            screen._debug_review_lazy_page_loaded(
                source="cache",
                page_num=0,
                pixmap=pixmap,
                kind="priority",
                canvas_wh="900x1400px",
            )

        debug_line = fake_print.call_args_list[0][0][0]
        self.assertEqual(debug_line, "[DEBUG][review_lazy] ⚡ p.1")

    def test_review_bulk_cache_debug_helper_prints_each_page(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)

        with patch("builtins.print") as fake_print:
            screen._debug_review_lazy_pages_loaded(source="cache", page_nums=[0, 2])

        printed = [call.args[0] for call in fake_print.call_args_list]
        self.assertEqual(printed, ["[DEBUG][review_lazy] ⚡ p.1", "[DEBUG][review_lazy] ⚡ p.3"])

    def test_review_annotation_refresh_prints_rendered_pages_after_edit(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._pdf_watcher = MagicMock()
        screen._update_review_page_nav_ui = MagicMock()
        screen.canvas = MagicMock()
        pixmap = MagicMock()
        pixmap.isNull.return_value = False

        with patch("ui.review_screen.PAGE_CACHE.get", return_value=pixmap), \
             patch("builtins.print") as fake_print:
            screen._apply_annotation_beta_refresh("deck.pdf", [1, 3], None)

        printed = [call.args[0] for call in fake_print.call_args_list]
        self.assertEqual(printed[0], "[DEBUG][review_after_edit] p.2, p.4")
        self.assertEqual(printed[1:], ["[DEBUG][review_lazy] 👀 p.2", "[DEBUG][review_lazy] 👀 p.4"])
        screen.canvas.inject_page.assert_any_call(1, pixmap)
        screen.canvas.inject_page.assert_any_call(3, pixmap)

    def test_review_annotation_pause_stops_and_resumes_pdf_watcher(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._pdf_watcher = MagicMock()
        screen._ui_idle_timer = MagicMock()
        screen._bg_pending_inserts = {}
        screen._stop_ondemand_thread = MagicMock()

        screen._pause_review_lazy_activity_for_annotation()
        screen._resume_review_lazy_activity_after_annotation("deck.pdf")

        screen._pdf_watcher.stop_watch.assert_called_once()
        screen._pdf_watcher.watch_pdf.assert_called_once_with("deck.pdf")
        self.assertFalse(screen._review_lazy_trace_suspended)

    def test_review_background_ready_pages_auto_insert_without_prefetch_acceptance(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        pixmap = MagicMock()
        pixmap.isNull.return_value = False
        screen._bg_pending_inserts = {2: pixmap}
        screen._bg_accept_mode = False
        screen._canvas_pdf_path = "deck.pdf"
        screen._pending_visible_request = None
        screen._ondemand_thread = None
        screen._ondemand_kind = None
        screen._canvas_alive = MagicMock(return_value=True)
        screen._debug_review_lazy_page_loaded = MagicMock()
        screen._safe_canvas_toast = MagicMock()
        screen.canvas = MagicMock()
        screen.canvas.width.return_value = 900
        screen.canvas.height.return_value = 1400

        screen._flush_pending_background_inserts()

        screen.canvas.inject_page.assert_called_once_with(2, pixmap)
        screen._safe_canvas_toast.assert_called_once_with("Inserted p.3")
        self.assertEqual(screen._bg_pending_inserts, {})

    def test_review_reload_requested_is_suppressed_after_internal_edit_refresh(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._reload_current_canvas = MagicMock()
        key = os.path.abspath("deck.pdf")
        screen._suppress_pdf_reload_until = {key: time.monotonic() + 10.0}

        screen._on_pdf_reload_requested("deck.pdf", None, 5)

        screen._reload_current_canvas.assert_not_called()

if __name__ == "__main__":
    unittest.main()
