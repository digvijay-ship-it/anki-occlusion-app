import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.review_manager import ReviewSessionManager
import sm2_engine


class ReviewSessionManagerPersistenceTests(unittest.TestCase):
    def test_rating_requests_immediate_checkpoint_save(self):
        rs = MagicMock()
        card = {
            "sched_state": "review",
            "sched_step": 0,
            "sm2_interval": 10,
            "sm2_ease": 2.5,
            "sm2_due": sm2_engine._now_iso(),
            "sm2_repetitions": 5,
            "sm2_last_quality": 4,
            "reviews": 5,
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card], "children": []}]}
        manager = ReviewSessionManager(rs)
        manager._items = [(card, None, card)]

        with patch("services.review_manager.store.mark_dirty") as mark_dirty, patch(
            "services.review_manager.store.save_soon"
        ) as save_soon, patch(
            "services.review_manager.recovery_manager.record_review_event"
        ) as record_event, patch("builtins.print"):
            manager._rate(5)

        mark_dirty.assert_called_once_with()
        save_soon.assert_called_once_with(min_interval=0.0)
        record_event.assert_called_once()
        rs._load_item.assert_called_once_with()

    def test_group_rating_records_all_affected_boxes_in_recovery_event(self):
        rs = MagicMock()
        card = {
            "title": "Grouped",
            "created": "2026-05-15T10:00:00",
            "boxes": [
                {
                    "box_id": "b1",
                    "group_id": "g1",
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 10,
                    "sm2_ease": 2.5,
                    "sm2_due": sm2_engine._now_iso(),
                    "sm2_repetitions": 5,
                    "sm2_last_quality": 4,
                    "reviews": 5,
                },
                {
                    "box_id": "b2",
                    "group_id": "g1",
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 10,
                    "sm2_ease": 2.5,
                    "sm2_due": sm2_engine._now_iso(),
                    "sm2_repetitions": 5,
                    "sm2_last_quality": 4,
                    "reviews": 5,
                },
            ],
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card], "children": []}]}
        manager = ReviewSessionManager(rs)
        manager._items = [(card, ("group", "g1"), card["boxes"][0])]

        with patch("services.review_manager.store.mark_dirty"), patch(
            "services.review_manager.store.save_soon"
        ), patch(
            "services.review_manager.recovery_manager.record_review_event"
        ) as record_event, patch("builtins.print"):
            manager._rate(5)

        event = record_event.call_args.args[0]
        box_updates = [
            update for update in event["updates"] if update.get("target") == "box"
        ]
        self.assertEqual(len(box_updates), 2)
        self.assertEqual(
            {update["box_locator"]["box_id"] for update in box_updates},
            {"b1", "b2"},
        )


if __name__ == "__main__":
    unittest.main()
