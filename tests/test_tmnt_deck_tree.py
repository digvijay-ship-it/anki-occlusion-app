import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton

from data_manager import deck_history, find_deck_by_id, store
from theme_manager import get_palette
from ui.tmnt_home import T_PIXEL, TMNTHomeLayout, TMNTSidebar, TMNTTopBar


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


class TMNTTopBarTests(unittest.TestCase):
    def test_tmnt_headers_use_math_dojo_header_font(self):
        self.assertEqual(T_PIXEL, get_palette("tmnt")["header_font"])
        self.assertIn("Orbitron", T_PIXEL)

    def test_more_menu_contains_shortcuts_action(self):
        topbar = TMNTTopBar({"_font_size": 11})
        self.addCleanup(topbar.close)

        labels = [button.text() for button in topbar._more_panel.findChildren(QPushButton)]

        self.assertTrue(any("SHORTCUTS" in label for label in labels))

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


if __name__ == "__main__":
    unittest.main()
