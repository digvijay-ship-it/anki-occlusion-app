import unittest
from datetime import datetime, timedelta
import fsrs_engine


class TestFsrsEngine(unittest.TestCase):
    def test_fsrs_init_populates_fields(self):
        card = {}
        fsrs_engine.fsrs_init(card)
        self.assertIn("fsrs_stability", card)
        self.assertIn("fsrs_difficulty", card)
        self.assertIn("fsrs_due", card)
        self.assertEqual(card["sched_state"], "new")

    def test_fsrs_init_converts_existing_sm2(self):
        card = {
            "sm2_interval": 14,
            "sm2_ease": 2.5,
            "reviews": 5,
        }
        fsrs_engine.fsrs_init(card)
        self.assertEqual(card["fsrs_stability"], 14.0)
        # Higher ease (2.5) should yield lower difficulty (~1.0)
        self.assertAlmostEqual(card["fsrs_difficulty"], 1.0, places=1)

    def test_fsrs_learning_steps_on_first_touch(self):
        # Again -> 1m
        c_again = {"sched_state": "new"}
        fsrs_engine.fsrs_update(c_again, quality=1)
        self.assertEqual(c_again["sched_state"], "learning")
        self.assertEqual(c_again["sched_step"], 0)

        # Hard -> 5m
        c_hard = {"sched_state": "new"}
        fsrs_engine.fsrs_update(c_hard, quality=3)
        self.assertEqual(c_hard["sched_state"], "learning")
        self.assertEqual(c_hard["sched_step"], 0)

        # Good -> 10m
        c_good = {"sched_state": "new"}
        fsrs_engine.fsrs_update(c_good, quality=4)
        self.assertEqual(c_good["sched_state"], "learning")
        self.assertEqual(c_good["sched_step"], 1)

        # Easy -> graduates to review immediately
        c_easy = {"sched_state": "new"}
        fsrs_engine.fsrs_update(c_easy, quality=5)
        self.assertEqual(c_easy["sched_state"], "review")
        self.assertGreater(c_easy["sm2_interval"], 1)

    def test_fsrs_graduation_to_review(self):
        card = {"sched_state": "learning", "sched_step": 1, "reviews": 1}
        fsrs_engine.fsrs_update(card, quality=4)
        self.assertEqual(card["sched_state"], "review")
        self.assertEqual(card["sched_step"], 0)
        self.assertGreaterEqual(card["sm2_interval"], 1)

    def test_fsrs_review_recall_increases_stability(self):
        now_iso = (datetime.now() - timedelta(days=5)).isoformat()
        card_good = {
            "sched_state": "review",
            "sched_step": 0,
            "fsrs_stability": 5.0,
            "fsrs_difficulty": 5.0,
            "fsrs_last_review": now_iso,
            "reviews": 3,
        }
        card_easy = dict(card_good)

        fsrs_engine.fsrs_update(card_good, quality=4)
        fsrs_engine.fsrs_update(card_easy, quality=5)

        self.assertGreater(card_good["fsrs_stability"], 5.0)
        self.assertGreater(card_easy["fsrs_stability"], card_good["fsrs_stability"])

    def test_fsrs_review_lapse_drops_stability_and_relearns(self):
        now_iso = (datetime.now() - timedelta(days=10)).isoformat()
        card = {
            "sched_state": "review",
            "sched_step": 0,
            "fsrs_stability": 10.0,
            "fsrs_difficulty": 5.0,
            "fsrs_last_review": now_iso,
            "reviews": 5,
        }
        fsrs_engine.fsrs_update(card, quality=1)

        self.assertEqual(card["sched_state"], "relearn")
        self.assertEqual(card["sched_step"], 0)
        self.assertLess(card["fsrs_stability"], 10.0)
        self.assertEqual(card["fsrs_lapses"], 1)

    def test_fsrs_retention_scaling(self):
        s = 10.0
        # Lower target retention = longer intervals (fewer reviews)
        # Higher target retention = shorter intervals (more reviews)
        iv_85 = fsrs_engine._interval_for_retention(s, request_retention=0.85)
        iv_90 = fsrs_engine._interval_for_retention(s, request_retention=0.90)
        iv_95 = fsrs_engine._interval_for_retention(s, request_retention=0.95)

        self.assertGreater(iv_85, iv_90)
        self.assertGreater(iv_90, iv_95)

    def test_fsrs_fmt_due_interval_previews(self):
        card = {
            "sched_state": "review",
            "sched_step": 0,
            "fsrs_stability": 8.0,
            "fsrs_difficulty": 5.0,
            "reviews": 4,
        }
        previews = fsrs_engine.fsrs_fmt_due_interval(card)
        self.assertIn(1, previews)
        self.assertIn(3, previews)
        self.assertIn(4, previews)
        self.assertIn(5, previews)

        # Again should be intraday (relearn step = 10m)
        self.assertEqual(previews[1], "10m")

        # Hard, Good, Easy should be days and strictly ordered: Hard <= Good <= Easy
        def to_days(label):
            return int(label[:-1]) if label.endswith("d") else 0

        self.assertLessEqual(to_days(previews[3]), to_days(previews[4]))
        self.assertLessEqual(to_days(previews[4]), to_days(previews[5]))


if __name__ == "__main__":
    unittest.main()
