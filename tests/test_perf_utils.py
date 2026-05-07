import unittest

from perf_utils import build_deck_rollups, card_has_due_today, count_due_units_in_card


class PerfUtilsTests(unittest.TestCase):
    def test_grouped_boxes_count_as_one_due_card_and_one_due_unit(self):
        card = {
            "boxes": [
                {"group_id": "g1", "sm2_due": "2000-01-01T00:00:00", "sched_state": "review"},
                {"group_id": "g1", "sm2_due": "2999-01-01T00:00:00", "sched_state": "review"},
            ]
        }

        self.assertTrue(card_has_due_today(card))
        self.assertEqual(count_due_units_in_card(card), 1)

    def test_rollups_include_children_once(self):
        decks = [
            {
                "_id": 1,
                "cards": [
                    {"sm2_due": "2000-01-01T00:00:00", "sched_state": "review"},
                ],
                "children": [
                    {
                        "_id": 2,
                        "cards": [
                            {"sm2_due": "2999-01-01T00:00:00", "sched_state": "review"},
                            {"sm2_due": "2000-01-01T00:00:00", "sched_state": "review"},
                        ],
                        "children": [],
                    }
                ],
            }
        ]

        rollups = build_deck_rollups(decks)
        self.assertEqual(rollups["total_cards"][1], 3)
        self.assertEqual(rollups["total_cards"][2], 2)
        self.assertEqual(rollups["due_cards"][1], 2)
        self.assertEqual(rollups["due_cards"][2], 1)
        self.assertEqual(rollups["due_units"][1], 2)
        self.assertEqual(rollups["due_units"][2], 1)


if __name__ == "__main__":
    unittest.main()
