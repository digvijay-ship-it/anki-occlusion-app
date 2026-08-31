import unittest
from data_manager import get_or_create_deck_by_path, import_json_cards, find_deck_by_id


class DeckRoutingAndUniqueIdTests(unittest.TestCase):
    def setUp(self):
        # Create a database where:
        # Deck 1: Root "Geography" (id: 1)
        # Deck 2: Root "GK" (id: 2) -> Subdeck "Geography" (id: 3)
        self.data = {
            "decks": [
                {
                    "_id": 1,
                    "name": "Geography",
                    "cards": [{"title": "Old Root Card", "question": "Capital of France?", "answer": "Paris"}],
                    "children": []
                },
                {
                    "_id": 2,
                    "name": "GK",
                    "cards": [],
                    "children": [
                        {
                            "_id": 3,
                            "name": "Geography",
                            "cards": [{"title": "GK Card", "question": "Longest River?", "answer": "Nile"}],
                            "children": []
                        }
                    ]
                }
            ]
        }

    def test_context_deck_preserves_unique_id_on_duplicate_name(self):
        gk_geography = find_deck_by_id(3, self.data["decks"])
        root_geography = find_deck_by_id(1, self.data["decks"])

        # When resolving "Geography" with context_deck = gk_geography (id 3)
        resolved = get_or_create_deck_by_path(self.data, "Geography", context_deck=gk_geography)
        self.assertEqual(resolved["_id"], 3)
        self.assertEqual(resolved["name"], "Geography")

        # Root deck must NOT be returned
        self.assertNotEqual(resolved["_id"], 1)

    def test_context_deck_subdeck_routes_under_correct_parent(self):
        gk_geography = find_deck_by_id(3, self.data["decks"])
        root_geography = find_deck_by_id(1, self.data["decks"])

        # When resolving "Geography::Rivers" with context_deck = gk_geography (id 3)
        resolved = get_or_create_deck_by_path(self.data, "Geography::Rivers", context_deck=gk_geography)
        self.assertEqual(resolved["name"], "Rivers")
        
        # Verify "Rivers" is in gk_geography's children
        child_names = [c["name"] for c in gk_geography.get("children", [])]
        self.assertIn("Rivers", child_names)

        # Root geography must NOT have "Rivers"
        root_child_names = [c["name"] for c in root_geography.get("children", [])]
        self.assertNotIn("Rivers", root_child_names)

    def test_lineage_path_routes_to_correct_context_deck(self):
        gk_geography = find_deck_by_id(3, self.data["decks"])
        
        # "GK::Geography" matching full lineage of id 3
        resolved = get_or_create_deck_by_path(self.data, "GK::Geography", context_deck=gk_geography)
        self.assertEqual(resolved["_id"], 3)

        # "GK::Geography::Mountains" extends lineage of id 3
        sub = get_or_create_deck_by_path(self.data, "GK::Geography::Mountains", context_deck=gk_geography)
        self.assertEqual(sub["name"], "Mountains")
        self.assertIn(sub, gk_geography.get("children", []))

    def test_import_json_cards_respects_default_deck_id(self):
        root_geography = find_deck_by_id(1, self.data["decks"])
        gk_geography = find_deck_by_id(3, self.data["decks"])

        initial_root_cards = len(root_geography["cards"])
        initial_gk_cards = len(gk_geography["cards"])

        new_cards = [
            {
                "deck_name": "Geography",
                "question": "Largest Ocean?",
                "answer": "Pacific Ocean"
            },
            {
                "deck_name": "Subject::Chapter_Name",
                "question": "Highest Peak?",
                "answer": "Mount Everest"
            }
        ]

        # Import into default_deck_id = 3 (GK > Geography)
        res = import_json_cards(self.data, new_cards, default_deck_id=3)
        self.assertEqual(res["imported"], 2)

        # Root geography card count must NOT change
        self.assertEqual(len(root_geography["cards"]), initial_root_cards)

        # GK geography must have gained 2 cards
        self.assertEqual(len(gk_geography["cards"]), initial_gk_cards + 2)
        gk_questions = [c["question"] for c in gk_geography["cards"]]
        self.assertIn("Largest Ocean?", gk_questions)
        self.assertIn("Highest Peak?", gk_questions)


if __name__ == "__main__":
    unittest.main()
