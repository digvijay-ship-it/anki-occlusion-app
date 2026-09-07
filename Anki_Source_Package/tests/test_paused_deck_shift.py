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

        today = date(2026, 9, 7)
        shifted = apply_paused_decks_timeline_shift(decks, reference_date=today)

        self.assertEqual(shifted, 5)
        self.assertEqual(decks[0]["cards"][0]["sm2_due"], "2026-09-06")
        self.assertEqual(decks[0]["cards"][1]["sm2_due"], "2026-09-08")
        self.assertEqual(decks[0]["cards"][2]["sm2_due"], "2026-09-09")
        self.assertEqual(decks[0]["cards"][3]["sm2_due"], "2026-09-10")

        child_boxes = decks[0]["children"][0]["cards"][0]["boxes"]
        self.assertEqual(child_boxes[0]["sm2_due"], "2026-09-06")
        self.assertEqual(child_boxes[1]["sm2_due"], "2026-09-08")
        self.assertEqual(child_boxes[2]["sm2_due"], "2026-09-11")

        self.assertEqual(decks[0]["pause_last_shift_date"], "2026-09-07")

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


if __name__ == "__main__":
    unittest.main()
