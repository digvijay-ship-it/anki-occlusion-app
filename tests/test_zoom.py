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
        debug_line = fake_print.call_args_list[0][0][0]
        self.assertEqual(debug_line, "[DEBUG][review_lazy] 👀 p.2")

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

    def test_review_reload_requested_is_suppressed_after_internal_edit_refresh(self):
        screen = UiReviewScreen.__new__(UiReviewScreen)
        screen._reload_current_canvas = MagicMock()
        key = os.path.abspath("deck.pdf")
        screen._suppress_pdf_reload_until = {key: time.monotonic() + 10.0}

        screen._on_pdf_reload_requested("deck.pdf", None, 5)

        screen._reload_current_canvas.assert_not_called()

if __name__ == "__main__":
    unittest.main()
