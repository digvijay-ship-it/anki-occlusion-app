import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from services.review_manager import REVIEW_SAVE_MIN_INTERVAL, ReviewSessionManager
import sm2_engine


class ReviewSessionManagerPersistenceTests(unittest.TestCase):
    def test_rating_records_immediate_checkpoint_and_debounces_heavy_save(self):
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
        save_soon.assert_called_once_with(
            min_interval=REVIEW_SAVE_MIN_INTERVAL, delay_from_now=True
        )
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

    def test_undo_discards_pending_rating_event_and_force_saves_revert(self):
        rs = MagicMock()
        card = {
            "title": "Q1",
            "boxes": [
                {
                    "box_id": "b1",
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 10,
                    "sm2_ease": 2.5,
                    "sm2_due": sm2_engine._now_iso(),
                    "sm2_repetitions": 5,
                    "sm2_last_quality": 4,
                    "reviews": 5,
                }
            ],
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card], "children": []}]}
        manager = ReviewSessionManager(rs)
        manager._items = [(card, 0, card["boxes"][0])]
        recorded_event = {"event_id": "rating-event", "timestamp": "2026-05-25T10:00:00"}

        with patch("services.review_manager.store.mark_dirty"), \
             patch("services.review_manager.store.save_soon") as save_soon, \
             patch("services.review_manager.store.save_force") as save_force, \
             patch(
                 "services.review_manager.recovery_manager.record_review_event",
                 return_value=recorded_event,
             ), \
             patch(
                 "services.review_manager.recovery_manager.discard_review_event"
             ) as discard_event, \
             patch("builtins.print"):
            manager._rate(5)
            manager._review_undo()

        discard_event.assert_called_once_with(recorded_event)
        save_soon.assert_called_once_with(
            min_interval=REVIEW_SAVE_MIN_INTERVAL, delay_from_now=True
        )
        save_force.assert_called_once_with(async_save=True)
        self.assertEqual(card["boxes"][0]["reviews"], 5)

    def test_undo_redo_restores_the_same_rated_item(self):
        rs = MagicMock()
        card1 = {
            "title": "Q1",
            "boxes": [
                {
                    "box_id": "b1",
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 10,
                    "sm2_ease": 2.5,
                    "sm2_due": sm2_engine._now_iso(),
                    "sm2_repetitions": 5,
                    "sm2_last_quality": 4,
                    "reviews": 5,
                }
            ],
        }
        card2 = {
            "title": "Q2",
            "boxes": [
                {
                    "box_id": "b2",
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 10,
                    "sm2_ease": 2.5,
                    "sm2_due": sm2_engine._now_iso(),
                    "sm2_repetitions": 2,
                    "sm2_last_quality": 3,
                    "reviews": 2,
                }
            ],
        }
        rs._data = {
            "decks": [
                {"_id": 1, "name": "Deck", "cards": [card1, card2], "children": []}
            ]
        }
        manager = ReviewSessionManager(rs)
        manager._items = [
            (card1, 0, card1["boxes"][0]),
            (card2, 0, card2["boxes"][0]),
        ]

        with patch("services.review_manager.store.mark_dirty"), \
             patch("services.review_manager.store.save_soon"), \
             patch("services.review_manager.store.save_force"), \
             patch(
                 "services.review_manager.recovery_manager.record_review_event",
                 side_effect=[
                     {"event_id": "rating-event", "timestamp": "2026-05-25T10:00:00"},
                     {"event_id": "redo-event", "timestamp": "2026-05-25T10:00:05"},
                 ],
             ), \
             patch("services.review_manager.recovery_manager.discard_review_event"), \
             patch("builtins.print"):
            manager._rate(5)
            rated_reviews = card1["boxes"][0]["reviews"]
            manager._review_undo()
            undone_reviews = card1["boxes"][0]["reviews"]
            manager._review_redo()

        self.assertGreater(rated_reviews, undone_reviews)
        self.assertEqual(card1["boxes"][0]["reviews"], rated_reviews)
        self.assertEqual(card2["boxes"][0]["reviews"], 2)

    def test_delayed_learning_card_moves_back_one_slot_when_still_earliest(self):
        rs = MagicMock()
        q25 = {
            "title": "Q25",
            "sched_state": "review",
            "sm2_due": "2026-05-23T00:00:00",
            "sm2_interval": 1,
            "sm2_ease": 2.5,
            "sm2_repetitions": 1,
            "reviews": 1,
        }
        q24 = {
            "title": "Q24",
            "sched_state": "review",
            "sm2_due": "2100-01-01T00:00:00",
            "sm2_interval": 1,
            "sm2_ease": 2.5,
            "sm2_repetitions": 1,
            "reviews": 1,
        }
        q26_learning = {
            "title": "Q26",
            "sched_state": "learning",
            "sm2_due": "2099-01-02T00:00:00",
            "sm2_interval": 1,
            "sm2_ease": 2.5,
            "sm2_repetitions": 1,
            "reviews": 1,
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [q25, q24], "children": []}]}
        manager = ReviewSessionManager(rs)
        manager._items = [(q25, None, q25), (q24, None, q24), (q26_learning, None, q26_learning)]

        def make_learning(obj, _quality):
            obj["sched_state"] = "learning"
            obj["sm2_due"] = "2099-01-01T00:00:00"

        with patch("services.review_manager.sched_update", side_effect=make_learning), \
             patch("services.review_manager.store.mark_dirty"), \
             patch("services.review_manager.store.save_soon"), \
             patch("services.review_manager.recovery_manager.record_review_event"):
            manager._rate(1)

        self.assertEqual([item[0]["title"] for item in manager._items], ["Q24", "Q25", "Q26"])
        self.assertEqual(manager._idx, 0)
        rs._load_item.assert_called_once_with()

    def test_delayed_learning_insert_keeps_due_order_after_the_forced_swap(self):
        rs = MagicMock()
        manager = ReviewSessionManager(rs)
        manager._idx = 0
        delayed = ({"title": "M3"}, None, {"sched_state": "learning", "sm2_due": "2026-05-23T00:15:00"})
        manager._items = [
            ({"title": "M1"}, None, {"sched_state": "review", "sm2_due": "2026-05-23T00:10:00"}),
            ({"title": "M2"}, None, {"sched_state": "review", "sm2_due": "2026-05-23T00:20:00"}),
        ]

        manager._insert_delayed_learning_item(delayed)

        self.assertEqual([item[0]["title"] for item in manager._items], ["M1", "M3", "M2"])

    def test_delayed_learning_insert_stays_after_all_shorter_remaining_times(self):
        rs = MagicMock()
        manager = ReviewSessionManager(rs)
        manager._idx = 0
        delayed = ({"title": "M3"}, None, {"sched_state": "learning", "sm2_due": "2026-05-23T00:30:00"})
        manager._items = [
            ({"title": "M1"}, None, {"sched_state": "review", "sm2_due": "2026-05-23T00:10:00"}),
            ({"title": "M2"}, None, {"sched_state": "review", "sm2_due": "2026-05-23T00:20:00"}),
        ]

        manager._insert_delayed_learning_item(delayed)

        self.assertEqual([item[0]["title"] for item in manager._items], ["M1", "M2", "M3"])


if __name__ == "__main__":
    unittest.main()
