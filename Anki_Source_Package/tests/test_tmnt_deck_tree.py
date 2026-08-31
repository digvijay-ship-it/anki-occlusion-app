import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import data_manager


from PyQt5.QtCore import QAbstractAnimation, QEvent, QRect, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import (
    QApplication,
    QMessageBox,
    QPushButton,
    QStyleOptionViewItem,
    QTreeWidget,
    QWidget,
)

from data_manager import deck_history, find_deck_by_id, store
from theme_manager import get_palette
from ui.tmnt_home import (
    T_PIXEL,
    TMNTBangaDrawer,
    TMNTDeckItemDelegate,
    TMNTMissionBanner,
    TMNTHomeLayout,
    TMNTSidebar,
    TMNTTopBar,
)


_APP = QApplication.instance() or QApplication([])


def _deck(deck_id, name, children=None):
    return {
        "_id": deck_id,
        "name": name,
        "cards": [],
        "children": children or [],
        "created": "2026-05-09T00:00:00",
    }


class TMNTDeckTreeTests(unittest.TestCase):
    def setUp(self):
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        self.addCleanup(self.print_patch.stop)
        self.data = {
            "decks": [
                _deck(1, "Math", [_deck(2, "Algebra")]),
                _deck(3, "Physics"),
            ],
            "_font_size": 11,
        }
        self.sidebar = TMNTSidebar(self.data)
        self.addCleanup(self.sidebar.close)

    def _top_item_by_id(self, deck_id):
        tree = self.sidebar._engine.tree
        for row in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(row)
            if item.data(0, 0x0100) == deck_id:
                return item
        return None

    def test_search_expansion_and_selection_survive_refresh(self):
        engine = self.sidebar._engine
        math_item = self._top_item_by_id(1)
        algebra_item = math_item.child(0)
        physics_item = self._top_item_by_id(3)
        math_item.setExpanded(True)
        engine.tree.setCurrentItem(algebra_item)

        self.sidebar.search_in.setText("alg")
        self.sidebar.refresh()

        math_item = self._top_item_by_id(1)
        algebra_item = math_item.child(0)
        physics_item = self._top_item_by_id(3)
        self.assertTrue(math_item.isExpanded())
        self.assertFalse(math_item.isHidden())
        self.assertFalse(algebra_item.isHidden())
        self.assertTrue(physics_item.isHidden())
        self.assertEqual(engine._get_selected_id(), 2)

    def test_tmnt_footer_delete_uses_shared_deck_delete_logic(self):
        engine = self.sidebar._engine
        physics_item = self._top_item_by_id(3)
        engine.tree.setCurrentItem(physics_item)

        with patch("ui.deck_tree.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("ui.deck_tree.store.mark_dirty"):
            self.sidebar._delete_selected()

        self.assertIsNone(find_deck_by_id(3, self.data["decks"]))

    def test_deck_bookmarking_load_save_toggle_and_undo(self):
        # Initialize store
        store.set(self.data)
        
        # Initial state: not bookmarked
        deck = find_deck_by_id(1, self.data["decks"])
        self.assertFalse(deck.get("bookmarked", False))

        # Check item data role 5 is False
        item = self._top_item_by_id(1)
        self.assertIsNotNone(item)
        self.assertFalse(item.data(0, Qt.UserRole + 5))

        # Toggle bookmark
        engine = self.sidebar._engine
        deck_history._undo_stack.clear()
        
        with patch("ui.deck_tree.store.mark_dirty"), \
             patch("ui.deck_tree.store.save_soon"):
            engine._toggle_bookmark_by_id(1)

        # Verify bookmarked
        self.data = store.get()
        deck = find_deck_by_id(1, self.data["decks"])
        self.assertTrue(deck.get("bookmarked", False))
        
        # Verify tree item is updated
        item = self._top_item_by_id(1)
        self.assertTrue(item.data(0, Qt.UserRole + 5))

        # Test Undo
        self.assertEqual(len(deck_history._undo_stack), 1)
        with patch("ui.deck_tree.store.mark_dirty"):
            deck_history.undo(store)
            # Sync local test data with store
            self.data = store.get()
            engine._data = self.data
            engine.refresh()

        # Verify undo works
        deck = find_deck_by_id(1, self.data["decks"])
        self.assertFalse(deck.get("bookmarked", False))
        item = self._top_item_by_id(1)
        self.assertFalse(item.data(0, Qt.UserRole + 5))

    def test_deck_tree_ignores_printable_character_keypress_so_it_bubbles_up(self):
        from PyQt5.QtGui import QKeyEvent
        from PyQt5.QtCore import QEvent, Qt
        
        tree = self.sidebar._engine.tree
        
        # Alphanumeric character key event
        event_e = QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier, "e")
        event_e.accept()
        tree.keyPressEvent(event_e)
        self.assertFalse(event_e.isAccepted())  # should be ignored/not accepted so it propagates
        
        # Navigation key event (e.g. Down arrow)
        event_down = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        event_down.accept()
        tree.keyPressEvent(event_down)
        self.assertTrue(event_down.isAccepted())  # navigation keys should be handled by QTreeWidget

    def test_due_badge_row_rect_extends_to_viewport_right_edge(self):
        tree = QTreeWidget()
        tree.resize(400, 200)
        tree.viewport().resize(400, 200)
        self.addCleanup(tree.close)
        delegate = TMNTDeckItemDelegate(scale=1.0, parent=tree)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 120, 44)

        rect = delegate._row_rect(option)

        self.assertEqual(rect.right(), tree.viewport().width() - 6)


class TMNTTopBarTests(unittest.TestCase):
    def test_tmnt_headers_use_math_dojo_header_font(self):
        self.assertEqual(T_PIXEL, get_palette("tmnt")["header_font"])
        self.assertIn("Orbitron", T_PIXEL)

    def test_more_menu_contains_shortcuts_action(self):
        topbar = TMNTTopBar({"_font_size": 11})
        self.addCleanup(topbar.close)

        labels = [button.text() for button in topbar._more_panel.findChildren(QPushButton)]

        self.assertTrue(any("SHORTCUTS" in label for label in labels))

    def test_brand_title_uses_one_and_half_times_base_size(self):
        topbar = TMNTTopBar({"_font_size": 11})
        self.addCleanup(topbar.close)

        expected_px = int(
            round(TMNTTopBar.BRAND_BASE_FONT_PX * TMNTTopBar.BRAND_TITLE_SCALE)
        )

        self.assertEqual(TMNTTopBar.BRAND_TITLE_SCALE, 1.5)
        self.assertEqual(expected_px, 27)
        self.assertIn(f"font-size: {expected_px}px", topbar._brand_name_ss())

    def test_brand_animation_timers_are_idle_by_default(self):
        topbar = TMNTTopBar({"_font_size": 11})
        self.addCleanup(topbar.close)

        self.assertFalse(topbar._brand_glitch_timer.isActive())
        self.assertFalse(topbar._brand_flicker_timer.isActive())
        self.assertFalse(topbar._quote_timer.isActive())

    def test_shortcuts_signal_is_forwarded_to_home_layout(self):
        layout = TMNTHomeLayout({"decks": [], "_font_size": 11})
        self.addCleanup(layout.close)
        emitted = []
        layout.btn_shortcuts_clicked.connect(lambda: emitted.append(True))

        layout.topbar._emit_shortcuts()

        self.assertEqual(emitted, [True])

    def test_dojo_cave_ctrl_z_and_ctrl_y_apply_deck_history(self):
        deck_history._undo_stack.clear()
        deck_history._redo_stack.clear()
        self.addCleanup(deck_history._undo_stack.clear)
        self.addCleanup(deck_history._redo_stack.clear)

        initial = {
            "decks": [_deck(1, "Math")],
            "_font_size": 11,
        }
        store.set(initial)
        layout = TMNTHomeLayout(store.get())
        self.addCleanup(layout.close)

        deck_history.push(store.get())
        store.get()["decks"].append(_deck(2, "Physics"))
        store.mark_dirty()
        layout.refresh()

        undo_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)
        layout.keyPressEvent(undo_event)

        self.assertIsNone(find_deck_by_id(2, store.get()["decks"]))
        self.assertIsNone(find_deck_by_id(2, layout._data["decks"]))

        redo_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Y, Qt.ControlModifier)
        layout.keyPressEvent(redo_event)

        self.assertIsNotNone(find_deck_by_id(2, store.get()["decks"]))
        self.assertIsNotNone(find_deck_by_id(2, layout._data["decks"]))

    def test_dojo_cave_ctrl_shift_z_still_redoes_deck_history(self):
        deck_history._undo_stack.clear()
        deck_history._redo_stack.clear()
        self.addCleanup(deck_history._undo_stack.clear)
        self.addCleanup(deck_history._redo_stack.clear)

        initial = {"decks": [_deck(1, "Math")], "_font_size": 11}
        store.set(initial)
        layout = TMNTHomeLayout(store.get())
        self.addCleanup(layout.close)

        deck_history.push(store.get())
        store.get()["decks"].append(_deck(2, "Physics"))
        store.mark_dirty()
        layout.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier))

        redo_event = QKeyEvent(
            QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier
        )
        layout.keyPressEvent(redo_event)

        self.assertIsNotNone(find_deck_by_id(2, store.get()["decks"]))

    def test_tmnt_main_content_bookmark_button_exists_and_loads(self):
        initial = {
            "decks": [_deck(1, "Math")],
            "_font_size": 11,
        }
        store.set(initial)
        layout = TMNTHomeLayout(store.get())
        self.addCleanup(layout.close)

        # Select the deck
        layout.select_deck_by_id(1)
        self.assertFalse(layout.main.btn_bookmark.isHidden())
        
        # Verify initial button text
        self.assertEqual(layout.main.btn_bookmark.text(), "🔖 BOOKMARK DECK")

        # Toggle it and verify text updates
        layout.main._toggle_bookmark()
        self.assertEqual(layout.main.btn_bookmark.text(), "🔖 UNMASKED QUESTIONS")


class TMNTMissionBannerTests(unittest.TestCase):
    def test_glow_timer_stays_idle_by_default(self):
        banner = TMNTMissionBanner({"_font_size": 11})
        self.addCleanup(banner.close)

        self.assertFalse(banner._glow_timer.isActive())

        banner.set_animation_enabled(True)

        self.assertTrue(banner._glow_timer.isActive())

    def test_glow_timer_runs_when_home_animations_are_enabled(self):
        with patch.dict(os.environ, {"ANKI_HOME_ANIMATIONS": "1"}, clear=False):
            banner = TMNTMissionBanner({"_font_size": 11})
            self.addCleanup(banner.close)

            self.assertFalse(banner._glow_timer.isActive())

            banner.set_animation_enabled(True)

            self.assertTrue(banner._glow_timer.isActive())

            banner.set_animation_enabled(False)

            self.assertFalse(banner._glow_timer.isActive())


class TMNTBangaDrawerTests(unittest.TestCase):
    def setUp(self):
        self.load_locked_patch = patch.object(
            TMNTBangaDrawer, "_load_locked", return_value=False
        )
        self.save_locked_patch = patch.object(TMNTBangaDrawer, "_save_locked")
        self.load_locked = self.load_locked_patch.start()
        self.save_locked = self.save_locked_patch.start()
        self.addCleanup(self.load_locked_patch.stop)
        self.addCleanup(self.save_locked_patch.stop)

    def test_cache_drawer_starts_closed_with_floating_total_memory(self):
        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer({"_font_size": 11}, parent=host)
        self.addCleanup(drawer.close)

        self.assertFalse(drawer._drawer_open)
        self.assertTrue(drawer.isHidden())
        self.assertFalse(drawer._edge_button.isHidden())
        self.assertLess(drawer._edge_button.height(), 50)
        self.assertTrue(drawer._lock_button.isHidden())
        self.assertFalse(drawer._memory_chip.isHidden())
        self.assertIn("TOTAL", drawer._memory_chip.text())
        self.assertEqual(drawer._edge_pulse.state(), QAbstractAnimation.Stopped)
        self.assertFalse(drawer.lab._auto_timer.isActive())

    def test_cache_drawer_does_not_reserve_width_until_locked(self):
        host = QWidget()
        host.resize(900, 600)
        reserve = QWidget()
        reserve.setFixedWidth(99)
        self.addCleanup(host.close)
        self.addCleanup(reserve.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer(
                {"_font_size": 11}, parent=host, reserve_widget=reserve
            )
            drawer.open_drawer()

        self.addCleanup(drawer.close)
        self.assertEqual(reserve.width(), 0)
        self.assertTrue(reserve.isHidden())

    def test_cache_drawer_opens_from_right_edge_and_closes(self):
        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer({"_font_size": 11}, parent=host)
            drawer.eventFilter(drawer._edge_button, QEvent(QEvent.Enter))

        self.addCleanup(drawer.close)
        self.assertTrue(drawer._drawer_open)
        self.assertFalse(drawer.isHidden())
        self.assertEqual(drawer._edge_button.text(), "›")
        self.assertTrue(drawer._edge_button.isHidden())
        self.assertTrue(drawer._memory_chip.isHidden())
        self.assertFalse(drawer._lock_button.isHidden())
        self.assertEqual(drawer._edge_pulse.state(), QAbstractAnimation.Stopped)
        self.assertTrue(drawer.lab._auto_timer.isActive())

        with patch("builtins.print"):
            drawer.close_drawer()

        self.assertFalse(drawer._drawer_open)
        self.assertTrue(drawer.isHidden())
        self.assertEqual(drawer._edge_button.text(), "‹")
        self.assertFalse(drawer._edge_button.isHidden())
        self.assertFalse(drawer._memory_chip.isHidden())
        self.assertTrue(drawer._lock_button.isHidden())
        self.assertEqual(drawer._edge_pulse.state(), QAbstractAnimation.Stopped)
        self.assertFalse(drawer.lab._auto_timer.isActive())

    def test_cache_drawer_lock_keeps_panel_open(self):
        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer({"_font_size": 11}, parent=host)
            drawer.open_drawer()
            drawer._toggle_lock()

        self.addCleanup(drawer.close)
        self.assertTrue(drawer._drawer_locked)
        self.assertTrue(drawer._drawer_open)
        self.assertFalse(drawer.isHidden())
        self.assertEqual(drawer._lock_button.text(), "🔒")
        self.assertTrue(drawer._edge_button.isHidden())
        self.assertTrue(drawer._memory_chip.isHidden())
        self.assertTrue(drawer.lab._auto_timer.isActive())
        self.save_locked.assert_called_with(True)

        with patch.object(drawer, "_contains_cursor", return_value=False):
            drawer._hide_if_cursor_outside()

        self.assertTrue(drawer._drawer_open)
        self.assertFalse(drawer.isHidden())

    def test_cache_drawer_lock_reserves_layout_width(self):
        host = QWidget()
        host.resize(900, 600)
        reserve = QWidget()
        reserve.setFixedWidth(0)
        reserve.hide()
        self.addCleanup(host.close)
        self.addCleanup(reserve.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer(
                {"_font_size": 11}, parent=host, reserve_widget=reserve
            )
            drawer.open_drawer()
            drawer._toggle_lock()

        self.addCleanup(drawer.close)
        self.assertEqual(reserve.width(), drawer._open_width)
        self.assertFalse(reserve.isHidden())

        with patch("builtins.print"), patch.object(
            drawer, "_contains_cursor", return_value=True
        ):
            drawer._toggle_lock()

        self.assertEqual(reserve.width(), 0)
        self.assertTrue(reserve.isHidden())

    def test_cache_drawer_unlock_allows_close(self):
        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer({"_font_size": 11}, parent=host)
            drawer.open_drawer()
            drawer._toggle_lock()
            drawer._toggle_lock()
            drawer.close_drawer()

        self.addCleanup(drawer.close)
        self.assertFalse(drawer._drawer_locked)
        self.assertFalse(drawer._drawer_open)
        self.assertTrue(drawer.isHidden())
        self.assertEqual(drawer._lock_button.text(), "🔓")
        self.save_locked.assert_called_with(False)

    def test_cache_drawer_restores_locked_open_state(self):
        self.load_locked.return_value = True
        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer({"_font_size": 11}, parent=host)

        self.addCleanup(drawer.close)
        self.assertTrue(drawer._drawer_locked)
        self.assertTrue(drawer._drawer_open)
        self.assertFalse(drawer.isHidden())
        self.assertEqual(drawer._lock_button.text(), "🔒")
        self.assertTrue(drawer._edge_button.isHidden())
        self.assertTrue(drawer._memory_chip.isHidden())
        self.assertTrue(drawer.lab._auto_timer.isActive())

    def test_cache_drawer_restores_locked_state_with_reserved_width(self):
        self.load_locked.return_value = True
        host = QWidget()
        host.resize(900, 600)
        reserve = QWidget()
        reserve.setFixedWidth(0)
        reserve.hide()
        self.addCleanup(host.close)
        self.addCleanup(reserve.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer(
                {"_font_size": 11}, parent=host, reserve_widget=reserve
            )

        self.addCleanup(drawer.close)
        self.assertEqual(reserve.width(), drawer._open_width)
        self.assertFalse(reserve.isHidden())

    def test_cache_drawer_updates_floating_total_memory_label(self):
        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.close)

        with patch("builtins.print"):
            drawer = TMNTBangaDrawer({"_font_size": 11}, parent=host)
        self.addCleanup(drawer.close)

        drawer.lab.resources_refreshed.emit("42.5 MB")

        self.assertEqual(drawer._memory_chip.text(), "TOTAL 42.5 MB")

    def test_tmnt_layout_uses_overlay_cache_drawer(self):
        with patch("builtins.print"):
            layout = TMNTHomeLayout({"decks": [], "_font_size": 11})
        self.addCleanup(layout.close)

        self.assertIsInstance(layout.banga, TMNTBangaDrawer)
        self.assertFalse(layout.banga._drawer_open)
        self.assertTrue(layout._banga_reserve.isHidden())

    def test_tmnt_layout_splits_sidebar_and_main_30_70_when_cache_hidden(self):
        with patch("builtins.print"):
            layout = TMNTHomeLayout({"decks": [], "_font_size": 11})
        self.addCleanup(layout.close)

        self.assertEqual(layout._body_layout.stretch(0), 30)
        self.assertEqual(layout._body_layout.stretch(1), 70)
        self.assertEqual(layout._body_layout.stretch(2), 0)
        self.assertLess(layout.sidebar.minimumWidth(), 300)
        self.assertGreater(layout.sidebar.maximumWidth(), 1000)

    def test_tmnt_layout_sidebar_hover_expand_logic(self):
        with patch("builtins.print"):
            layout = TMNTHomeLayout({"decks": [], "_font_size": 11})
        self.addCleanup(layout.close)

        layout.resize(1000, 600)
        layout.show()
        QApplication.processEvents()

        body = layout._body_w
        self.assertIsNotNone(body)

        # Initially, sidebar is not expanded
        self.assertFalse(layout._sidebar_expanded)

        from PyQt5.QtCore import QPoint
        # Hover inside the collapsed sidebar zone (< 30% of body width, e.g. x = 50)
        with patch.object(body, "mapFromGlobal", return_value=QPoint(50, 300)):
            layout._check_sidebar_hover()

        self.assertTrue(layout._sidebar_expanded)

        # Manually force the sidebar width to simulate the expanded state (600px width)
        layout.sidebar.setFixedWidth(600)

        # Hover inside the expanded width (e.g. x = 450, which is > 30% of body, but < 600)
        # It should NOT trigger/start the collapse delay
        if layout._collapse_delay.isActive():
            layout._collapse_delay.stop()

        with patch.object(body, "mapFromGlobal", return_value=QPoint(450, 300)):
            layout._check_sidebar_hover()

        self.assertFalse(layout._collapse_delay.isActive())

        # Hover outside the expanded width (e.g. x = 700, which is > 600)
        # It should trigger/start the collapse delay
        with patch.object(body, "mapFromGlobal", return_value=QPoint(700, 300)):
            layout._check_sidebar_hover()

        self.assertTrue(layout._collapse_delay.isActive())

    def test_collect_due_by_pdf_preserves_subdeck_order(self):
        from ui.deck_view import DeckView
        from ui.import_cards_dialog import build_text_card
        
        card_n1 = build_text_card("N1", "Meaning N1")
        card_n2 = build_text_card("N2", "Meaning N2")
        card_p1 = build_text_card("P1", "Meaning P1")
        card_p2 = build_text_card("P2", "Meaning P2")

        deck_n = {"_id": 101, "name": "N", "cards": [card_n1, card_n2], "children": []}
        deck_p = {"_id": 102, "name": "P", "cards": [card_p1, card_p2], "children": []}
        deck_a1 = {"_id": 100, "name": "A1", "cards": [], "children": [deck_n, deck_p]}
        parent_deck = {"_id": 10, "name": "BLACKBOOK", "cards": [], "children": [deck_a1]}

        dv = DeckView()
        groups = dv._collect_due_by_pdf(parent_deck)

        # Groups must be 2 separate lists: [ [N1, N2], [P1, P2] ] preserving subdeck DFS order
        self.assertEqual(len(groups), 2)
        self.assertEqual([c["question"] for c in groups[0]], ["N1", "N2"])
        self.assertEqual([c["question"] for c in groups[1]], ["P1", "P2"])


if __name__ == "__main__":
    unittest.main()
