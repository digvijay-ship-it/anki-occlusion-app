import copy
import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import sm2_engine


class SchedulerTransitionTests(unittest.TestCase):
    def test_new_card_good_graduates_to_next_learning_step(self):
        card = {}

        updated = sm2_engine.sched_update(card, 4)

        self.assertEqual(updated["sched_state"], "learning")
        self.assertEqual(updated["sched_step"], 1)
        due = datetime.fromisoformat(updated["sm2_due"])
        delta_minutes = round((due - datetime.now()).total_seconds() / 60)
        self.assertGreaterEqual(delta_minutes, 9)
        self.assertLessEqual(delta_minutes, 10)

    def test_learning_hard_uses_midpoint_between_first_two_steps(self):
        card = sm2_engine.sched_init({})

        updated = sm2_engine.sched_update(card, 3)

        self.assertEqual(updated["sched_state"], "learning")
        self.assertEqual(updated["sched_step"], 0)
        due = datetime.fromisoformat(updated["sm2_due"])
        delta_minutes = round((due - datetime.now()).total_seconds() / 60)
        self.assertGreaterEqual(delta_minutes, 4)
        self.assertLessEqual(delta_minutes, 5)

    def test_learning_good_on_last_step_graduates_to_review(self):
        card = sm2_engine.sched_init({})
        card["sched_state"] = "learning"
        card["sched_step"] = len(sm2_engine.LEARNING_STEPS) - 1

        updated = sm2_engine.sched_update(card, 4)

        self.assertEqual(updated["sched_state"], "review")
        self.assertEqual(updated["sm2_interval"], sm2_engine.GRADUATING_IV)
        due = datetime.fromisoformat(updated["sm2_due"])
        expected = datetime.combine(date.today() + timedelta(days=1), time.min)
        self.assertEqual(due, expected)


class ReviewSchedulingTests(unittest.TestCase):
    def _review_card(self, *, interval=10, ease=2.5, repetitions=5):
        return {
            "sched_state": "review",
            "sched_step": 0,
            "sm2_interval": interval,
            "sm2_ease": ease,
            "sm2_due": sm2_engine._now_iso(),
            "sm2_repetitions": repetitions,
            "sm2_last_quality": 4,
            "reviews": 5,
        }

    @patch("sm2_engine.random.randint", return_value=0)
    def test_review_hard_applies_interval_multiplier_and_ef_penalty(self, _mock_randint):
        card = self._review_card(interval=10, ease=2.5)

        updated = sm2_engine.sched_update(card, 3)

        self.assertEqual(updated["sched_state"], "review")
        self.assertEqual(updated["sm2_interval"], 12)
        self.assertEqual(updated["sm2_ease"], 2.35)

    @patch("sm2_engine.random.randint", return_value=0)
    def test_review_easy_applies_bonus_and_stays_at_least_as_large_as_good(self, _mock_randint):
        card = self._review_card(interval=10, ease=2.5)

        updated = sm2_engine.sched_update(copy.deepcopy(card), 5)
        good = sm2_engine.sched_update(copy.deepcopy(card), 4)

        self.assertEqual(updated["sm2_ease"], 2.5)
        self.assertGreaterEqual(updated["sm2_interval"], good["sm2_interval"])

    @patch("sm2_engine.random.randint", return_value=0)
    def test_review_again_enters_relearn_and_penalizes_ef(self, _mock_randint):
        card = self._review_card(interval=10, ease=2.3)

        updated = sm2_engine.sched_update(card, 1)

        self.assertEqual(updated["sched_state"], "relearn")
        self.assertEqual(updated["sched_step"], 0)
        self.assertEqual(updated["sm2_ease"], 2.1)


class DueLogicTests(unittest.TestCase):
    def test_learning_card_rated_today_is_due_today_even_if_due_time_is_future(self):
        card = sm2_engine.sched_init({})
        card["sched_state"] = "learning"
        card["sm2_last_quality"] = 4
        card["sm2_due"] = (datetime.now() + timedelta(minutes=15)).isoformat(timespec="seconds")

        self.assertTrue(sm2_engine.is_due_today(card))

    def test_review_card_due_tomorrow_is_not_due_today(self):
        card = {
            "sched_state": "review",
            "sm2_due": datetime.combine(date.today() + timedelta(days=1), time.min).isoformat(timespec="seconds"),
        }

        self.assertFalse(sm2_engine.is_due_today(card))

    def test_days_left_uses_due_date(self):
        card = {
            "sm2_due": datetime.combine(date.today() + timedelta(days=3), time.min).isoformat(timespec="seconds")
        }

        self.assertEqual(sm2_engine.sm2_days_left(card), 3)


class PreviewTests(unittest.TestCase):
    @patch("sm2_engine.random.randint", side_effect=[2, -2, 0, -2, 2, 0])
    def test_preview_ordering_enforces_hard_le_good_lt_easy(self, _mock_randint):
        card = {
            "sched_state": "review",
            "sched_step": 0,
            "sm2_interval": 10,
            "sm2_ease": 1.3,
            "sm2_due": sm2_engine._now_iso(),
            "sm2_repetitions": 5,
            "sm2_last_quality": 4,
            "reviews": 5,
        }

        previews = sm2_engine._fmt_due_interval(card)

        hard = int(previews[3][:-1])
        good = int(previews[4][:-1])
        easy = int(previews[5][:-1])
        self.assertLessEqual(hard, good)
        self.assertGreater(easy, good)


if __name__ == "__main__":
    unittest.main()
