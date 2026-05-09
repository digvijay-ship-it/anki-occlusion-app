import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox

from data_manager import find_deck_by_id
from ui.tmnt_home import TMNTSidebar


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


if __name__ == "__main__":
    unittest.main()
