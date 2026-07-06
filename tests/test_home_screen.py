import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QApplication, QLabel, QListWidgetItem, QDialog, QWidget

# Ensure QApplication exists before importing HomeScreen
_APP = QApplication.instance() or QApplication([])

from anki_occlusion_v19 import HomeScreen
import anki_occlusion_v19
from ui.home_screen import AboutDialog, MusicWidget, REVIEW_SAVE_MIN_INTERVAL
from ui.deck_view import DeckView
from ui.deck_tree import CACHE_AUTO_REFRESH_MS, CacheWidget, DeckTree

class HomeScreenJournalTests(unittest.TestCase):
    def setUp(self):
        self.home_screen = HomeScreen.__new__(HomeScreen)

    @patch('ui.home_screen.JournalDialog')
    @patch('ui.home_screen._JOURNAL_AVAILABLE', True)
    def test_show_journal_opens_dialog_when_available(self, mock_journal_dialog_class):
        # Setup mock dialog instance
        mock_dialog_instance = MagicMock()
        mock_journal_dialog_class.return_value = mock_dialog_instance

        # Mock HomeScreen dependencies
        self.home_screen._current_theme = "classic"
        self.home_screen._tmnt_layout = None
        self.home_screen._ensure_classic_layout = MagicMock()
        self.home_screen._get_splitter = MagicMock(return_value=None)

        # Call the method
        self.home_screen._show_journal()

        # Verify dialog was instantiated with self as parent
        mock_journal_dialog_class.assert_called_once_with(parent=self.home_screen)

    @patch('PyQt5.QtWidgets.QMessageBox.warning')
    @patch('ui.home_screen._JOURNAL_AVAILABLE', False)
    def test_show_journal_shows_warning_when_not_available(self, mock_warning):
        # Call the method
        self.home_screen._show_journal()

        # Verify QMessageBox.warning was called
        mock_warning.assert_called_once()
        args, _ = mock_warning.call_args
        self.assertEqual(args[0], self.home_screen)
        self.assertEqual(args[1], "Journal")
        self.assertTrue("journal.py not found" in args[2])


class HomeScreenMusicWidgetTests(unittest.TestCase):
    def test_music_audio_initializes_only_when_playback_is_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "theme.mp3"), "wb") as fh:
                fh.write(b"audio")

            with patch.object(MusicWidget, "MUSIC_DIR", tmpdir), patch.object(
                MusicWidget, "_init_audio"
            ) as init_audio:
                widget = MusicWidget()
                self.addCleanup(widget.close)

                init_audio.assert_not_called()
                self.assertFalse(widget._audio_initialized)

                widget.toggle()

                init_audio.assert_called_once_with()
                self.assertTrue(widget._audio_initialized)

    def test_music_scan_excludes_math_trainer_sound_effects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in (
                "Teenage Mutant Ninja Turtles III - Scene 1.mp3",
                "ambient.ogg",
                "pickupCoin.wav",
                "powerUp.wav",
                "hitHurt.wav",
            ):
                with open(os.path.join(tmpdir, name), "wb") as fh:
                    fh.write(b"audio")

            with patch.object(MusicWidget, "MUSIC_DIR", tmpdir), patch.object(
                MusicWidget, "_init_audio", lambda self: None
            ):
                widget = MusicWidget()
                self.addCleanup(widget.close)

        self.assertEqual(
            {os.path.basename(path) for path in widget._tracks},
            {
                "Teenage Mutant Ninja Turtles III - Scene 1.mp3",
                "ambient.ogg",
            },
        )


class DeckViewRefreshTests(unittest.TestCase):
    def test_hidden_dojo_banner_does_not_run_glow_timer_by_default(self):
        view = DeckView()
        self.addCleanup(view.close)

        self.assertFalse(view.dojo_banner._glow_timer.isActive())

    def test_edit_card_refreshes_home_tree_rollups(self):
        deck = {
            "_id": 2,
            "name": "Permutation",
            "cards": [
                {
                    "title": "Q1",
                    "boxes": [
                        {
                            "box_id": "b1",
                            "sched_state": "review",
                            "sm2_due": "2026-05-23T00:00:00",
                        }
                    ],
                }
            ],
            "children": [],
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [], "children": [deck]}]}
        view = DeckView()
        self.addCleanup(view.close)
        view.deck = deck
        view._data = data
        view.card_list.addItem(QListWidgetItem("Q1"))
        edited_card = {
            "title": "Q1 edited",
            "boxes": [
                {"box_id": "b1"},
                {"box_id": "b2", "sched_state": "new"},
            ],
        }
        dialog = MagicMock()
        dialog.exec_.return_value = QDialog.Accepted
        dialog.get_card.return_value = edited_card
        home = MagicMock()

        with patch("ui.deck_view._load_card_editor_dialog", return_value=MagicMock(return_value=dialog)), \
             patch.object(view, "_find_home", return_value=home), \
             patch.object(view, "_refresh") as local_refresh, \
             patch("ui.deck_view.store.mark_dirty") as mark_dirty, \
             patch("ui.deck_view.store.save_force") as save_force, \
             patch("perf_utils.invalidate_deck_stats") as invalidate:
            view._edit_card(view.card_list.item(0))

        invalidate.assert_called_once_with()
        home.refresh.assert_called_once_with()
        local_refresh.assert_not_called()
        mark_dirty.assert_called_once_with()
        save_force.assert_called_once_with(async_save=True)
        dialog.clear_recovery_draft.assert_called_once_with()
        self.assertEqual(deck["cards"][0]["title"], "Q1 edited")
        self.assertEqual(deck["cards"][0]["boxes"][0]["sched_state"], "review")


class HomeScreenIdleTimerTests(unittest.TestCase):
    def test_deck_tree_blink_timer_is_idle_by_default(self):
        with patch.dict(os.environ, {"ANKI_HOME_ANIMATIONS": ""}, clear=False):
            tree = DeckTree({"decks": []})
            self.addCleanup(tree.close)

            tree.show()
            _APP.processEvents()

        self.assertFalse(tree._blink_timer.isActive())

    def test_deck_tree_blink_timer_only_runs_when_home_animations_are_enabled(self):
        with patch.dict(os.environ, {"ANKI_HOME_ANIMATIONS": "1"}, clear=False):
            tree = DeckTree({"decks": []})
            self.addCleanup(tree.close)

            self.assertFalse(tree._blink_timer.isActive())

            tree.show()
            _APP.processEvents()
            self.assertTrue(tree._blink_timer.isActive())

            tree.hide()
            _APP.processEvents()
            self.assertFalse(tree._blink_timer.isActive())

    def test_cache_widget_polls_only_visible_theme_at_slow_interval(self):
        widget = CacheWidget()
        self.addCleanup(widget.close)

        self.assertEqual(widget.classic_widget._auto_timer.interval(), CACHE_AUTO_REFRESH_MS)
        self.assertEqual(widget.dojo_widget._auto_timer.interval(), CACHE_AUTO_REFRESH_MS)
        self.assertFalse(widget.classic_widget._auto_timer.isActive())
        self.assertFalse(widget.dojo_widget._auto_timer.isActive())

        widget.show()
        _APP.processEvents()

        self.assertTrue(widget.classic_widget._auto_timer.isActive())
        self.assertFalse(widget.dojo_widget._auto_timer.isActive())

        widget.set_theme("tmnt")
        _APP.processEvents()

        self.assertTrue(widget.classic_widget._auto_timer.isActive())
        self.assertFalse(widget.dojo_widget._auto_timer.isActive())

        widget.hide()
        _APP.processEvents()

        self.assertFalse(widget.classic_widget._auto_timer.isActive())
        self.assertFalse(widget.dojo_widget._auto_timer.isActive())


class HomeScreenClassicUiTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)
        self.home_screen = HomeScreen({"decks": [], "_theme": "classic"})
        self.addCleanup(self.home_screen.close)

    def test_classic_topbar_has_save_and_settings_controls(self):
        self.assertEqual(self.home_screen._btn_save.text(), "💾 SAVE")
        self.assertEqual(self.home_screen._btn_settings.text(), "⚙ SETTINGS")
        self.assertEqual(self.home_screen._btn_shortcuts.text(), "⌨ SHORTCUTS")
        self.assertIsNotNone(self.home_screen._classic_settings_panel)

    def test_e_key_press_edits_card_when_deck_selected(self):
        from PyQt5.QtGui import QKeyEvent
        from PyQt5.QtCore import QEvent, Qt
        
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier)
        
        deck_view = MagicMock()
        deck_view.isVisible.return_value = True
        item = MagicMock()
        deck_view.card_list.currentItem.return_value = item
        
        self.home_screen.deck_view = deck_view
        self.home_screen._deck_view = deck_view
        self.home_screen._active_review = None
        
        def mock_event_matches(event_obj, action_id):
            return action_id == "home.edit_card"
            
        with patch("ui.home_screen.shortcut_manager.event_matches", side_effect=mock_event_matches):
            self.home_screen.keyPressEvent(event)
            
        deck_view._edit_card.assert_called_once_with(item)

    def test_classic_settings_panel_toggles_and_shows_archive_controls(self):
        self.home_screen._toggle_classic_settings_panel()

        self.assertTrue(self.home_screen._classic_settings_panel.isVisible())
        self.assertEqual(self.home_screen._classic_archive_btn.text(), "SET")
        self.assertTrue(self.home_screen._classic_archive_value.text())

        self.home_screen._toggle_classic_settings_panel()
        self.assertFalse(self.home_screen._classic_settings_panel.isVisible())

    def test_classic_settings_panel_fullscreen_toggle(self):
        self.assertFalse(self.home_screen._data.get("_keep_fullscreen", False))
        self.home_screen._cb_keep_fullscreen.setChecked(True)
        self.assertTrue(self.home_screen._data.get("_keep_fullscreen", False))
        
        self.home_screen._cb_keep_fullscreen.setChecked(False)
        self.assertFalse(self.home_screen._data.get("_keep_fullscreen", False))

    def test_classic_save_button_delegates_to_manual_save(self):
        with patch.object(self.home_screen, "_save_current_data_now") as save_now:
            self.home_screen._on_classic_save_clicked()

        save_now.assert_called_once_with()

    def test_recovery_center_opens_when_startup_scan_finds_draft(self):
        summary = {
            "drafts": [
                {
                    "draft_id": "d1",
                    "mode": "add",
                    "card": {"title": "Recovered", "boxes": []},
                    "deck": {"name": "Math"},
                }
            ],
            "review_events": [],
        }
        dialog = MagicMock()
        dialog.action = "close"

        with patch("ui.home_screen.recovery_manager.scan_recovery", return_value=summary), \
             patch("ui.home_screen.RecoveryDialog", return_value=dialog) as dialog_cls:
            shown = self.home_screen.show_recovery_center(startup=True)

        self.assertTrue(shown)
        dialog_cls.assert_called_once()
        dialog.exec_.assert_called_once_with()

    def test_startup_review_only_recovery_auto_applies_without_dialog(self):
        summary = {
            "drafts": [],
            "review_events": [
                {"event_id": "r1", "status": "recoverable"},
                {"event_id": "r2", "status": "recoverable"},
            ],
        }
        empty_summary = {"drafts": [], "review_events": []}
        result = {"applied": 2, "already_applied": 0, "blocked": []}

        with patch(
            "ui.home_screen.recovery_manager.scan_recovery",
            side_effect=[summary, empty_summary],
        ), patch(
            "ui.home_screen.recovery_manager.apply_pending_review_events",
            return_value=result,
        ) as apply_events, patch(
            "ui.home_screen.store.mark_dirty"
        ) as mark_dirty, patch(
            "ui.home_screen.store.save_force"
        ) as save_force, patch.object(
            self.home_screen, "refresh"
        ) as refresh, patch(
            "ui.home_screen.store.save_soon"
        ) as save_soon, patch(
            "ui.home_screen.RecoveryDialog"
        ) as dialog_cls:
            shown = self.home_screen.show_recovery_center(startup=True)

        self.assertTrue(shown)
        apply_events.assert_called_once()
        mark_dirty.assert_called_once_with()
        save_force.assert_called_once_with()
        save_soon.assert_not_called()
        refresh.assert_not_called()
        dialog_cls.assert_not_called()

    def test_startup_review_recovery_with_blocked_event_still_opens_dialog(self):
        summary = {
            "drafts": [],
            "review_events": [{"event_id": "r1", "status": "missing_card"}],
        }
        dialog = MagicMock()
        dialog.action = "close"

        with patch("ui.home_screen.recovery_manager.scan_recovery", return_value=summary), \
             patch("ui.home_screen.recovery_manager.apply_pending_review_events") as apply_events, \
             patch("ui.home_screen.RecoveryDialog", return_value=dialog) as dialog_cls:
            shown = self.home_screen.show_recovery_center(startup=True)

        self.assertTrue(shown)
        apply_events.assert_not_called()
        dialog_cls.assert_called_once()
        dialog.exec_.assert_called_once_with()

    def test_review_cancel_without_changes_does_not_force_save(self):
        class FakeReview(QWidget):
            finished = pyqtSignal()
            cancelled = pyqtSignal()
            undo_requested_when_empty = pyqtSignal()

            def __init__(self, *args, **kwargs):
                super().__init__()
                self.canvas = MagicMock()

        with patch("ui.home_screen._load_review_screen", return_value=FakeReview), \
             patch("ui.home_screen.store.is_dirty", return_value=False) as is_dirty, \
             patch("ui.home_screen.store.save_force") as save_force, \
             patch("ui.home_screen.store.save_soon") as save_soon, \
             patch.object(
                 self.home_screen,
                 "window",
                 return_value=MagicMock(statusBar=MagicMock(return_value=MagicMock())),
             ):
            self.home_screen.show_review([{"title": "Card"}], self.home_screen._data)
            self.home_screen._active_review.cancelled.emit()

        is_dirty.assert_called_once_with()
        save_force.assert_not_called()
        save_soon.assert_not_called()

    def test_review_cancel_with_dirty_store_delays_heavy_save(self):
        class FakeReview(QWidget):
            finished = pyqtSignal()
            cancelled = pyqtSignal()
            undo_requested_when_empty = pyqtSignal()

            def __init__(self, *args, **kwargs):
                super().__init__()
                self.canvas = MagicMock()

        with patch("ui.home_screen._load_review_screen", return_value=FakeReview), \
             patch("ui.home_screen.store.is_dirty", return_value=True), \
             patch("ui.home_screen.store.save_force") as save_force, \
             patch("ui.home_screen.store.save_soon") as save_soon, \
             patch.object(
                 self.home_screen,
                 "window",
                 return_value=MagicMock(statusBar=MagicMock(return_value=MagicMock())),
             ):
            self.home_screen.show_review([{"title": "Card"}], self.home_screen._data)
            self.home_screen._active_review.cancelled.emit()

        save_force.assert_called_once_with(async_save=True, force_gdrive=True)
        save_soon.assert_not_called()

    def test_recovery_center_delete_all_drafts_deletes_every_selected_draft(self):
        first_summary = {
            "drafts": [
                {"draft_id": "d1", "card": {"title": "One"}, "deck": {}},
                {"draft_id": "d2", "card": {"title": "Two"}, "deck": {}},
            ],
            "review_events": [],
        }
        empty_summary = {"drafts": [], "review_events": []}
        dialog = MagicMock()
        dialog.action = "delete_all_drafts"
        dialog.selected_drafts = first_summary["drafts"]

        with patch(
            "ui.home_screen.recovery_manager.scan_recovery",
            side_effect=[first_summary, empty_summary],
        ), patch(
            "ui.home_screen.RecoveryDialog", return_value=dialog
        ), patch(
            "ui.home_screen.recovery_manager.delete_editor_draft",
            return_value=True,
        ) as delete_draft, patch(
            "ui.home_screen.QMessageBox.information"
        ) as info:
            shown = self.home_screen.show_recovery_center(startup=False)

        self.assertTrue(shown)
        self.assertEqual(
            [call.args[0] for call in delete_draft.call_args_list], ["d1", "d2"]
        )
        info.assert_called()

    def test_about_dialog_shortcuts_include_pdf_copy_and_open_folder(self):
        dialog = AboutDialog(self.home_screen)
        self.addCleanup(dialog.close)

        label_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn("L — copy current PDF file", label_text)
        self.assertIn("Ctrl+L — open current PDF folder", label_text)


class _FakeTMNTHomeLayout(QWidget):
    btn_save_clicked = pyqtSignal()
    btn_math_clicked = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_theme_clicked = pyqtSignal()
    btn_help_clicked = pyqtSignal()
    btn_about_clicked = pyqtSignal()
    btn_shortcuts_clicked = pyqtSignal()
    btn_resume_clicked = pyqtSignal()
    font_change = pyqtSignal(int)
    bgm_toggle = pyqtSignal()
    bgm_volume_changed = pyqtSignal(int)

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data = data
        self.refresh_count = 0
        self.bgm_state = None

    def set_bgm_state(self, state):
        self.bgm_state = state

    def refresh(self):
        self.refresh_count += 1

    def get_selected_deck(self):
        return None

    def set_resume_enabled(self, enabled):
        pass


class HomeScreenStartupLazyTests(unittest.TestCase):
    def test_tmnt_startup_does_not_build_classic_body(self):
        with patch("ui.home_screen._load_tmnt_home_layout", return_value=_FakeTMNTHomeLayout), \
             patch("ui.home_screen._load_classic_home_classes") as load_classic:
            home = HomeScreen({"decks": [], "_theme": "tmnt"})
            self.addCleanup(home.close)

        load_classic.assert_not_called()
        self.assertIsNone(home._splitter_widget)
        self.assertIsNotNone(home._tmnt_layout)
        self.assertIs(home._body_stack.currentWidget(), home._tmnt_layout)

    def test_classic_startup_does_not_build_tmnt_body(self):
        with patch("ui.home_screen._load_tmnt_home_layout") as load_tmnt:
            home = HomeScreen({"decks": [], "_theme": "classic"})
            self.addCleanup(home.close)

        load_tmnt.assert_not_called()
        self.assertIsNotNone(home._splitter_widget)
        self.assertIsNone(home._tmnt_layout)
        self.assertIs(home._body_stack.currentWidget(), home._splitter_widget)

class HomeScreenResumeSessionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "anki_data.db")
        self.patch_db = patch("storage_paths.current_data_file", return_value=self.db_path)
        self.patch_db.start()

    def tearDown(self):
        self.patch_db.stop()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_load_clear_session(self):
        home = HomeScreen({"decks": [], "_theme": "classic"})
        self.addCleanup(home.close)
        
        home._btn_resume = MagicMock()
        
        cards = [
            {"pdf_path": "lecture.pdf", "title": "Page 1", "visual_hash": "vh1"},
            {"image_path": "img.png", "title": "My Image"}
        ]
        
        home.save_last_review_session(cards, 1)
        
        # Load and verify
        session = home.load_last_review_session()
        self.assertIsNotNone(session)
        self.assertEqual(session["idx"], 1)
        self.assertEqual(len(session["card_identifiers"]), 2)
        self.assertEqual(session["card_identifiers"][0]["pdf_path"], "lecture.pdf")
        self.assertEqual(session["card_identifiers"][0]["visual_hash"], "vh1")
        self.assertEqual(session["card_identifiers"][1]["image_path"], "img.png")
        
        # Clear and verify
        home.clear_last_review_session()
        self.assertIsNone(home.load_last_review_session())
        home._btn_resume.setEnabled.assert_called_with(False)

    def test_resume_last_review_success(self):
        card1 = {"pdf_path": "lec.pdf", "title": "Card 1", "visual_hash": "h1"}
        card2 = {"image_path": "pic.png", "title": "Card 2", "visual_hash": "h2"}
        
        data = {
            "decks": [
                {
                    "_id": 1,
                    "name": "Main Deck",
                    "cards": [card1],
                    "children": [
                        {
                            "_id": 2,
                            "name": "Sub Deck",
                            "cards": [card2],
                            "children": []
                        }
                     ]
                }
            ],
            "_theme": "classic"
        }
        
        home = HomeScreen(data)
        self.addCleanup(home.close)
        
        home._btn_resume = MagicMock()
        home.show_review = MagicMock()
        home._active_review = MagicMock()
        home._active_review._items = [(card2, 0, card2), (card1, 1, card1)]
        
        # Save session with card2 first, then card1
        home.save_last_review_session([card2, card1], 1)
        
        # Resume session
        home.resume_last_review()
        
        # Verify show_review is called with the resolved card dictionaries in order
        home.show_review.assert_called_once_with([card2, card1], home._data)
        self.assertEqual(home._active_review._idx, 1)
        home._active_review._load_item.assert_called_once()

    def test_global_resume_shortcut_setup(self):
        from ui.home_screen import HomeScreen
        from PyQt5.QtWidgets import QShortcut
        
        data = {
            "decks": [],
            "_theme": "classic"
        }
        
        home = HomeScreen(data)
        self.addCleanup(home.close)
        
        # Verify shortcut is created and connected
        self.assertTrue(hasattr(home, "_resume_review_shortcut"))
        self.assertIsInstance(home._resume_review_shortcut, QShortcut)
        self.assertEqual(home._resume_review_shortcut.context(), Qt.WindowShortcut)


if __name__ == "__main__":
    unittest.main()
