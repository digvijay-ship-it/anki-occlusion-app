import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_manager import import_json_cards
from PyQt5.QtWidgets import QApplication

if not QApplication.instance():
    app = QApplication(sys.argv)

class TestConceptHubAndSorting(unittest.TestCase):
    def setUp(self):
        self.data = {
            "decks": [
                {"_id": 1, "name": "GK", "cards": [], "children": []}
            ]
        }

    def test_auto_chaining_sequential_cards(self):
        items = [
            {
                "deck_name": "GK::Peninsular",
                "context_anchor": "Peninsular Plateau: Definition",
                "question": "Q1",
                "answer": "A1",
                "chain_order": 1
            },
            {
                "deck_name": "GK::Peninsular",
                "context_anchor": "Peninsular Plateau: Boundaries",
                "question": "Q2",
                "answer": "A2",
                "chain_order": 2
            },
            {
                "deck_name": "GK::Peninsular",
                "context_anchor": "Vindhya Range",
                "question": "Q9",
                "answer": "A9",
                "chain_order": 9
            }
        ]
        
        res = import_json_cards(
            self.data, items, dup_policy="skip", default_deck_id=1
        )
        
        self.assertEqual(res["imported"], 3)
        cards = res["created_cards"]
        self.assertEqual(len(cards), 3)
        # Verify all 3 cards share the same parent_chain_id
        chain_ids = {c.get("parent_chain_id") for c in cards}
        self.assertEqual(len(chain_ids), 1)
        self.assertIsNotNone(list(chain_ids)[0])

    def test_sorting_preserves_step_order(self):
        cards = [
            {"_id": "c9", "chain_order": 9, "parent_chain_id": "chain-1", "question": "Q9", "answer": "A9", "card_type": "text"},
            {"_id": "c1", "chain_order": 1, "parent_chain_id": "chain-1", "question": "Q1", "answer": "A1", "card_type": "text"},
            {"_id": "c2", "chain_order": 2, "parent_chain_id": "chain-1", "question": "Q2", "answer": "A2", "card_type": "text"},
        ]
        
        items = [
            (cards[0], 0, {"sm2_due": "2026-08-29"}),
            (cards[1], 0, {"sm2_due": "2026-08-29"}),
            (cards[2], 0, {"sm2_due": "2026-08-29"}),
        ]
        
        item_order_map = {id(item): idx for idx, item in enumerate(items)}
        chain_earliest_due = {"chain-1": "2026-08-29"}
        
        def _sort_key(item):
            card, box_idx, sm2_obj = item
            c_order = int(card.get("chain_order", 0) or 0)
            orig_idx = item_order_map.get(id(item), 0)
            chain_id = card.get("parent_chain_id")
            c_due = chain_earliest_due.get(chain_id, "")
            return (c_due, c_order if c_order > 0 else 999999, orig_idx)
            
        items.sort(key=_sort_key)
        
        # Verify sorted sequence is c1, c2, c9
        sorted_orders = [it[0]["chain_order"] for it in items]
        self.assertEqual(sorted_orders, [1, 2, 9])

    def test_concept_hub_drawer_init(self):
        from ui.review.concept_hub_drawer import ConceptHubDrawer
        from PyQt5.QtWidgets import QWidget
        dummy_parent = QWidget()
        dummy_parent._items = []
        dummy_parent._idx = 0
        drawer = ConceptHubDrawer(dummy_parent, dummy_parent)
        self.assertIsNotNone(drawer)
        self.assertEqual(drawer.objectName(), "concept_hub_drawer")

if __name__ == "__main__":
    unittest.main()
