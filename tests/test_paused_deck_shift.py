import unittest
from datetime import date, timedelta
from sm2_engine import shift_due_iso, apply_paused_decks_timeline_shift, is_due_today

class TestPausedDeckShift(unittest.TestCase):
    def test_shift_due_iso(self):
        self.assertEqual(shift_due_iso("2026-09-07", 2), "2026-09-09")
        self.assertEqual(shift_due_iso("2026-09-07T10:00:00", 3), "2026-09-10T10:00:00")
        self.assertEqual(shift_due_iso("2026-09-07", 0), "2026-09-07")
        self.assertEqual(shift_due_iso("", 5), "")

    def test_paused_deck_conveyor_belt(self):
        decks = [
            {
                "_id": 10,
                "name": "Math Test",
                "is_paused": True,
                "pause_backlog_cutoff": "2026-09-06",
                "pause_last_shift_date": "2026-09-06",
                "cards": [
                    {
                        "_id": 1,
                        "sched_state": "review",
                        "sm2_due": "2026-09-06",  # Backlog: already due yesterday
                    },
                    {
                        "_id": 2,
                        "sched_state": "review",
                        "sm2_due": "2026-09-07",  # Was scheduled for today (Sept 7)
                    },
                    {
                        "_id": 3,
                        "sched_state": "review",
                        "sm2_due": "2026-09-08",  # Was scheduled for tomorrow (Sept 8)
                    },
                    {
                        "_id": 4,
                        "sched_state": "review",
                        "sm2_due": "2026-09-09",  # Was scheduled for Day 3 (Sept 9)
                    },
                ],
                "children": [
                    {
                        "_id": 11,
                        "name": "Math Subdeck",
                        "cards": [
                            {
                                "_id": 5,
                                "sched_state": "review",
                                "boxes": [
                                    {"box_id": "b1", "sm2_due": "2026-09-06"},  # Backlog box
                                    {"box_id": "b2", "sm2_due": "2026-09-07"},  # Future box 1
                                    {"box_id": "b3", "sm2_due": "2026-09-10"},  # Future box 2
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

        # Simulate day roll from Sept 6 to Sept 7 (1 day passed)
        today = date(2026, 9, 7)
        shifted = apply_paused_decks_timeline_shift(decks, reference_date=today)

        # 3 cards in parent (ids 2, 3, 4) + 2 boxes in child (b2, b3) = 5 items shifted
        self.assertEqual(shifted, 5)

        # Card 1 (Backlog) must remain on 2026-09-06 so user can review it
        self.assertEqual(decks[0]["cards"][0]["sm2_due"], "2026-09-06")

        # Future cards must advance by 1 day, preserving exact intervals
        self.assertEqual(decks[0]["cards"][1]["sm2_due"], "2026-09-08")  # Sept 7 -> Sept 8
        self.assertEqual(decks[0]["cards"][2]["sm2_due"], "2026-09-09")  # Sept 8 -> Sept 9
        self.assertEqual(decks[0]["cards"][3]["sm2_due"], "2026-09-10")  # Sept 9 -> Sept 10

        # Subdeck boxes
        child_boxes = decks[0]["children"][0]["cards"][0]["boxes"]
        self.assertEqual(child_boxes[0]["sm2_due"], "2026-09-06")  # Backlog box untouched
        self.assertEqual(child_boxes[1]["sm2_due"], "2026-09-08")  # Shifted +1
        self.assertEqual(child_boxes[2]["sm2_due"], "2026-09-11")  # Shifted +1

        # Check pause_last_shift_date updated
        self.assertEqual(decks[0]["pause_last_shift_date"], "2026-09-07")

        # Running again on the same day must be idempotent (0 shifted)
        shifted_again = apply_paused_decks_timeline_shift(decks, reference_date=today)
        self.assertEqual(shifted_again, 0)

    def test_multi_day_gap_shift(self):
        decks = [
            {
                "_id": 30,
                "name": "Multi-Day Deck",
                "is_paused": True,
                "pause_backlog_cutoff": "2026-09-01",
                "pause_last_shift_date": "2026-09-01",
                "cards": [
                    {"_id": 1, "sm2_due": "2026-09-01"},  # Backlog
                    {"_id": 2, "sm2_due": "2026-09-02"},  # Future 1
                    {"_id": 3, "sm2_due": "2026-09-05"},  # Future 2
                ]
            }
        ]
        # 4 days pass: Sept 1 to Sept 5
        shifted = apply_paused_decks_timeline_shift(decks, reference_date=date(2026, 9, 5))
        self.assertEqual(shifted, 2)
        self.assertEqual(decks[0]["cards"][0]["sm2_due"], "2026-09-01")  # Backlog untouched
        self.assertEqual(decks[0]["cards"][1]["sm2_due"], "2026-09-06")  # 02 + 4 days = 06
        self.assertEqual(decks[0]["cards"][2]["sm2_due"], "2026-09-09")  # 05 + 4 days = 09
        self.assertEqual(decks[0]["pause_last_shift_date"], "2026-09-05")

    def test_super_skip_pause_exempt_in_paused_deck(self):
        decks = [
            {
                "_id": 40,
                "name": "Super Skip Test Deck",
                "is_paused": True,
                "pause_backlog_cutoff": "2026-09-06",
                "pause_last_shift_date": "2026-09-06",
                "cards": [
                    {
                        "_id": 1,
                        "sm2_due": "2026-09-06",  # Normal Backlog
                    },
                    {
                        "_id": 2,
                        # Card super-skipped on Sept 6 for tomorrow (Sept 7)
                        "sm2_due": "2026-09-07T00:00:00",
                        "pause_exempt_due": "2026-09-07",
                    },
                    {
                        "_id": 3,
                        # Normal future card scheduled for tomorrow (Sept 7)
                        "sm2_due": "2026-09-07T00:00:00",
                    },
                ]
            }
        ]
        # Day rolls over to Sept 7
        shifted = apply_paused_decks_timeline_shift(decks, reference_date=date(2026, 9, 7))

        self.assertEqual(shifted, 1)
        self.assertEqual(decks[0]["cards"][0]["sm2_due"], "2026-09-06")
        self.assertEqual(decks[0]["cards"][1]["sm2_due"], "2026-09-07T00:00:00")
        self.assertNotIn("pause_exempt_due", decks[0]["cards"][1])
        self.assertEqual(decks[0]["cards"][2]["sm2_due"], "2026-09-08T00:00:00")

    def test_unpaused_deck_untouched(self):
        decks = [
            {
                "_id": 20,
                "name": "Normal Deck",
                "is_paused": False,
                "cards": [
                    {"_id": 1, "sm2_due": "2026-09-07"}
                ]
            }
        ]
        shifted = apply_paused_decks_timeline_shift(decks, reference_date=date(2026, 9, 7))
        self.assertEqual(shifted, 0)
        self.assertEqual(decks[0]["cards"][0]["sm2_due"], "2026-09-07")

    def test_subdeck_unpause_precedence_over_paused_parent(self):
        """
        Verify that when a parent deck is paused (e.g. Maths),
        an explicitly unpaused subdeck (e.g. Ratio & Proportion with is_paused=False)
        takes highest precedence: its cards are NOT conveyor-belt shifted,
        while other subdecks (e.g. Algebra) and the parent deck ARE shifted.
        """
        decks = [
            {
                "_id": 100,
                "name": "Maths",
                "is_paused": True,
                "pause_backlog_cutoff": "2026-09-06",
                "pause_last_shift_date": "2026-09-06",
                "cards": [
                    {"_id": 101, "sm2_due": "2026-09-08"}  # Future card in parent Maths -> should shift +1
                ],
                "children": [
                    {
                        "_id": 110,
                        "name": "Algebra",
                        # Inherits pause from parent Maths
                        "cards": [
                            {"_id": 111, "sm2_due": "2026-09-08"}  # Future card in Algebra -> should shift +1
                        ]
                    },
                    {
                        "_id": 120,
                        "name": "Ratio & Proportion",
                        "is_paused": False,  # EXPLICITLY UNPAUSED BY USER
                        "cards": [
                            {"_id": 121, "sm2_due": "2026-09-08"}  # Future card in Ratio -> MUST NOT SHIFT
                        ]
                    }
                ]
            }
        ]

        # Day rolls over from Sept 6 to Sept 7 (+1 day)
        today = date(2026, 9, 7)
        shifted = apply_paused_decks_timeline_shift(decks, reference_date=today)

        # 1 card in Maths + 1 card in Algebra = 2 cards shifted. Ratio card must NOT shift.
        self.assertEqual(shifted, 2)
        self.assertEqual(decks[0]["cards"][0]["sm2_due"], "2026-09-09")  # Maths: 08 -> 09
        self.assertEqual(decks[0]["children"][0]["cards"][0]["sm2_due"], "2026-09-09")  # Algebra: 08 -> 09
        self.assertEqual(decks[0]["children"][1]["cards"][0]["sm2_due"], "2026-09-08")  # Ratio: UNTOUCHED

    def test_cascade_deck_pause_and_precedence_helpers(self):
        """
        Verify cascade_deck_pause and is_deck_effective_paused helper behaviors.
        """
        from data_manager import cascade_deck_pause, is_deck_effective_paused

        tree = [
            {
                "_id": 1,
                "name": "Parent Deck",
                "is_paused": False,
                "children": [
                    {
                        "_id": 2,
                        "name": "Child A",
                        "children": [
                            {"_id": 3, "name": "Grandchild A1"}
                        ]
                    }
                ]
            }
        ]

        # Initially all unpaused
        parent = tree[0]
        child = parent["children"][0]
        grandchild = child["children"][0]

        self.assertFalse(is_deck_effective_paused(parent, tree))
        self.assertFalse(is_deck_effective_paused(child, tree))
        self.assertFalse(is_deck_effective_paused(grandchild, tree))

        # Pause parent and cascade
        parent["is_paused"] = True
        cascade_deck_pause(parent, True, "2026-09-07")

        self.assertTrue(parent["is_paused"])
        self.assertTrue(child["is_paused"])
        self.assertTrue(grandchild["is_paused"])
        self.assertEqual(child.get("pause_backlog_cutoff"), "2026-09-07")
        self.assertEqual(grandchild.get("pause_backlog_cutoff"), "2026-09-07")

        # Selectively unpause Child A
        child["is_paused"] = False
        child.pop("pause_backlog_cutoff", None)
        child.pop("pause_last_shift_date", None)
        cascade_deck_pause(child, False, "2026-09-07")

        self.assertTrue(is_deck_effective_paused(parent, tree))
        self.assertFalse(is_deck_effective_paused(child, tree))
        self.assertFalse(is_deck_effective_paused(grandchild, tree))

    def test_mid_session_date_rollover_shift(self):
        from data_manager import DirtyStore
        from unittest.mock import patch
        store = DirtyStore()
        store._data = {
            "decks": [
                {
                    "_id": 10,
                    "name": "Math",
                    "is_paused": True,
                    "pause_backlog_cutoff": "2026-09-06",
                    "pause_last_shift_date": "2026-09-07",
                    "cards": [
                        {
                            "_id": 101,
                            "sm2_due": "2026-09-06T00:00:00",  # backlog item
                            "boxes": [
                                {"box_id": "b1", "sm2_due": "2026-09-06T00:00:00"}
                            ]
                        },
                        {
                            "_id": 102,
                            "sm2_due": "2026-09-08T00:00:00",  # future item due today
                            "boxes": [
                                {"box_id": "b2", "sm2_due": "2026-09-08T00:00:00"}
                            ]
                        }
                    ]
                }
            ]
        }
        with patch.object(store, "save_soon") as mock_save:
            shifted = store.check_and_apply_paused_decks_timeline_shift(reference_date=date(2026, 9, 8))
            self.assertEqual(shifted, 2)  # 1 card + 1 box shifted
            self.assertTrue(store.is_dirty())
            mock_save.assert_called_once_with(min_interval=3.0)

        deck = store.get()["decks"][0]
        self.assertEqual(deck["pause_last_shift_date"], "2026-09-08")
        # Backlog card stays 2026-09-06
        self.assertEqual(deck["cards"][0]["sm2_due"][:10], "2026-09-06")
        self.assertEqual(deck["cards"][0]["boxes"][0]["sm2_due"][:10], "2026-09-06")
        # Future card shifted +1 day to 2026-09-09
        self.assertEqual(deck["cards"][1]["sm2_due"][:10], "2026-09-09")
        self.assertEqual(deck["cards"][1]["boxes"][0]["sm2_due"][:10], "2026-09-09")

        # Calling again on same day should be idempotent (0 items shifted)
        with patch.object(store, "save_soon") as mock_save2:
            shifted_again = store.check_and_apply_paused_decks_timeline_shift(reference_date=date(2026, 9, 8))
            self.assertEqual(shifted_again, 0)
            mock_save2.assert_not_called()


if __name__ == "__main__":
    unittest.main()
