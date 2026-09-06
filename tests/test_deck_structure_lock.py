import sys
import unittest
from PyQt5.QtWidgets import QApplication, QAbstractItemView
from PyQt5.QtCore import QSettings, QMimeData

app = QApplication.instance() or QApplication(sys.argv)

from ui.deck_tree import DeckTree
from ui.deck_view import DeckView
from ui.tmnt_home import TMNTSidebar

class TestDeckStructureLock(unittest.TestCase):
    def setUp(self):
        self.settings = QSettings('AnkiOcclusion', 'App')
        self.orig_locked = self.settings.value('deck_structure_locked', None)
        self.dummy_data = {
            'decks': [
                {
                    '_id': 'deck_1',
                    'name': 'Test Deck 1',
                    'cards': [{'question': 'Q1', 'answer': 'A1'}],
                    'children': []
                },
                {
                    '_id': 'deck_2',
                    'name': 'Test Deck 2',
                    'cards': [],
                    'children': []
                }
            ]
        }

    def tearDown(self):
        if self.orig_locked is not None:
            self.settings.setValue('deck_structure_locked', self.orig_locked)
        else:
            self.settings.remove('deck_structure_locked')

    def test_deck_tree_lock_and_unlock(self):
        self.settings.setValue('deck_structure_locked', False)
        dt = DeckTree(self.dummy_data, theme='dojo')

        self.assertFalse(dt._structure_locked)
        self.assertEqual(dt.btn_lock_structure.text(), '🔓')
        self.assertTrue(dt.tree.dragEnabled())
        self.assertTrue(dt.tree.acceptDrops())
        self.assertEqual(dt.tree.dragDropMode(), QAbstractItemView.InternalMove)

        dt._toggle_structure_lock()
        self.assertTrue(dt._structure_locked)
        self.assertEqual(dt.btn_lock_structure.text(), '🔒')
        self.assertFalse(dt.tree.dragEnabled())
        self.assertFalse(dt.tree.acceptDrops())
        self.assertEqual(dt.tree.dragDropMode(), QAbstractItemView.NoDragDrop)
        self.assertTrue(self.settings.value('deck_structure_locked', False, type=bool))

        class FakeEvent:
            def __init__(self):
                self.accepted = False
            def accept(self):
                self.accepted = True
            def ignore(self):
                self.accepted = False
            def mimeData(self):
                return QMimeData()

        ev = FakeEvent()
        dt._on_drag_enter(ev)
        self.assertFalse(ev.accepted)

        ev_drop = FakeEvent()
        dt._on_tree_drop(ev_drop)
        self.assertFalse(ev_drop.accepted)

        dt._toggle_structure_lock()
        self.assertFalse(dt._structure_locked)
        self.assertEqual(dt.btn_lock_structure.text(), '🔓')
        self.assertTrue(dt.tree.dragEnabled())
        self.assertTrue(dt.tree.acceptDrops())
        self.assertEqual(dt.tree.dragDropMode(), QAbstractItemView.InternalMove)
        self.assertFalse(self.settings.value('deck_structure_locked', True, type=bool))

    def test_deck_view_card_drag_lock(self):
        self.settings.setValue('deck_structure_locked', True)
        dv = DeckView()
        self.assertTrue(dv._structure_locked)
        self.assertFalse(dv.card_list.dragEnabled())
        self.assertEqual(dv.card_list.dragDropMode(), QAbstractItemView.NoDragDrop)

        dv.deck = self.dummy_data['decks'][0]
        dv._start_card_drag(None)

        dv.set_structure_locked(False)
        self.assertFalse(dv._structure_locked)
        self.assertTrue(dv.card_list.dragEnabled())
        self.assertEqual(dv.card_list.dragDropMode(), QAbstractItemView.DragOnly)

    def test_tmnt_sidebar_lock_toggle(self):
        self.settings.setValue('deck_structure_locked', True)
        sidebar = TMNTSidebar(self.dummy_data)
        self.assertTrue(sidebar._deck_structure_locked)
        self.assertEqual(sidebar.btn_lock_structure.text(), '🔒')
        self.assertFalse(sidebar._engine.tree.dragEnabled())
        self.assertEqual(sidebar._engine.tree.dragDropMode(), QAbstractItemView.NoDragDrop)

        sidebar._toggle_deck_structure_lock()
        self.assertFalse(sidebar._deck_structure_locked)
        self.assertEqual(sidebar.btn_lock_structure.text(), '🔓')
        self.assertTrue(sidebar._engine.tree.dragEnabled())
        self.assertEqual(sidebar._engine.tree.dragDropMode(), QAbstractItemView.InternalMove)
        self.assertFalse(self.settings.value('deck_structure_locked', True, type=bool))

if __name__ == '__main__':
    unittest.main()
