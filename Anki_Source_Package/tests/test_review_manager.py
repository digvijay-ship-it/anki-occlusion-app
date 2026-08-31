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
        save_soon.assert_not_called()
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
        save_soon.assert_not_called()
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

    def test_skip_session_pops_item_and_can_be_undone(self):
        rs = MagicMock()
        card1 = {"title": "C1", "sched_state": "review", "sm2_due": "2026-05-23T00:00:00"}
        card2 = {"title": "C2", "sched_state": "review", "sm2_due": "2026-05-23T00:00:00"}
        manager = ReviewSessionManager(rs)
        manager._items = [
            (card1, None, card1),
            (card2, None, card2),
        ]
        manager._idx = 0

        # Skip first card
        manager.skip_session()

        # Should pop the first card from items
        self.assertEqual(len(manager._items), 1)
        self.assertEqual(manager._items[0][0]["title"], "C2")
        rs._load_item.assert_called_once_with()

        # Undo the skip
        rs._load_item.reset_mock()
        manager._review_undo()

        # Items should be restored
        self.assertEqual(len(manager._items), 2)
        self.assertEqual(manager._items[0][0]["title"], "C1")
        self.assertEqual(manager._items[1][0]["title"], "C2")
        self.assertEqual(manager._idx, 0)
        rs._load_item.assert_called_once_with()

    def test_super_skip_updates_due_date_and_pops_item_and_can_be_undone(self):
        rs = MagicMock()
        card = {"title": "C1", "sched_state": "review", "sm2_due": "2026-05-23T00:00:00"}
        manager = ReviewSessionManager(rs)
        manager._items = [(card, None, card)]
        manager._idx = 0

        with patch("services.review_manager.store.mark_dirty") as mark_dirty, patch(
            "services.review_manager.store.save_soon"
        ) as save_soon:
            manager.super_skip()

        # Card should be popped
        self.assertEqual(len(manager._items), 0)
        # Check that its due date is updated to tomorrow at 00:00:00
        from datetime import date, datetime, timedelta
        expected_due = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).isoformat(timespec="seconds")
        self.assertEqual(card["sm2_due"], expected_due)
        mark_dirty.assert_called_once()
        save_soon.assert_not_called()

        # Undo the super skip
        manager._review_undo()
        self.assertEqual(len(manager._items), 1)
        self.assertEqual(card["sm2_due"], "2026-05-23T00:00:00")

    def test_super_skip_reschedules_group_siblings(self):
        rs = MagicMock()
        card = {
            "title": "Grouped",
            "boxes": [
                {"box_id": "b1", "group_id": "g1", "sm2_due": "2026-05-23T00:00:00"},
                {"box_id": "b2", "group_id": "g1", "sm2_due": "2026-05-23T00:00:00"},
            ]
        }
        manager = ReviewSessionManager(rs)
        manager._items = [(card, ("group", "g1"), card["boxes"][0])]
        manager._idx = 0

        with patch("services.review_manager.store.mark_dirty"), patch(
            "services.review_manager.store.save_soon"
        ):
            manager.super_skip()

        from datetime import date, datetime, timedelta
        expected_due = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).isoformat(timespec="seconds")
        self.assertEqual(card["boxes"][0]["sm2_due"], expected_due)
        self.assertEqual(card["boxes"][1]["sm2_due"], expected_due)

        # Undo and verify restoration of both
        manager._review_undo()
        self.assertEqual(card["boxes"][0]["sm2_due"], "2026-05-23T00:00:00")
        self.assertEqual(card["boxes"][1]["sm2_due"], "2026-05-23T00:00:00")

    def test_super_skip_records_review_when_time_spent_ge_60_seconds(self):
        rs = MagicMock()
        stimer = MagicMock()
        stimer.get_current_mask_seconds.return_value = 65
        rs._stimer = stimer

        card = {
            "title": "Hard Question",
            "pdf_path": "dummy.pdf",
            "boxes": [
                {"box_id": "b1", "sched_state": "review", "sm2_due": "2026-05-23T00:00:00"}
            ]
        }
        manager = ReviewSessionManager(rs)
        manager._items = [(card, 0, card["boxes"][0])]
        manager._idx = 0
        manager._done = 0

        with patch("services.review_manager.store.mark_dirty"):
            manager.super_skip()

        # Should be popped
        self.assertEqual(len(manager._items), 0)
        # Should count as done review
        self.assertEqual(manager._done, 1)
        # Should have stamped reviewed_at
        self.assertTrue(bool(card["boxes"][0].get("reviewed_at")))
        self.assertTrue(bool(card.get("last_reviewed_at")))
        # Should record timer review
        stimer.record_card_review.assert_called_once_with("dummy.pdf")

        # Test Undo
        manager._review_undo()
        self.assertEqual(len(manager._items), 1)
        self.assertEqual(manager._done, 0)
        self.assertIsNone(card["boxes"][0].get("reviewed_at"))
        self.assertIsNone(card.get("last_reviewed_at"))
        stimer.undo_card_review.assert_called_once_with("dummy.pdf")

    def test_super_skip_does_not_record_review_when_time_spent_lt_60_seconds(self):
        rs = MagicMock()
        stimer = MagicMock()
        stimer.get_current_mask_seconds.return_value = 15
        rs._stimer = stimer

        card = {
            "title": "Quick Skip Card",
            "pdf_path": "dummy.pdf",
            "boxes": [
                {"box_id": "b1", "sched_state": "review", "sm2_due": "2026-05-23T00:00:00"}
            ]
        }
        manager = ReviewSessionManager(rs)
        manager._items = [(card, 0, card["boxes"][0])]
        manager._idx = 0
        manager._done = 0

        with patch("services.review_manager.store.mark_dirty"):
            manager.super_skip()

        # Should be popped
        self.assertEqual(len(manager._items), 0)
        # Should NOT count as done review
        self.assertEqual(manager._done, 0)
        # Should NOT have stamped reviewed_at
        self.assertIsNone(card["boxes"][0].get("reviewed_at"))
        self.assertIsNone(card.get("last_reviewed_at"))
        # Should NOT record timer review
        stimer.record_card_review.assert_not_called()

    def test_ungrouping_retains_scheduling_and_splits_queue(self):
        rs = MagicMock()
        card = {
            "_id": 101,
            "title": "Test PDF Card",
            "pdf_path": "dummy.pdf",
            "boxes": [
                {
                    "box_id": "box_a",
                    "group_id": "g1",
                    "rect": [10, 10, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 1,
                    "sm2_ease": 2.5,
                    "sm2_due": "2026-07-05T00:00:00",
                    "sm2_repetitions": 1,
                    "reviews": 1,
                },
                {
                    "box_id": "box_b",
                    "group_id": "g1",
                    "rect": [100, 100, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 1,
                    "sm2_ease": 2.5,
                    "sm2_due": "2026-07-05T00:00:00",
                    "sm2_repetitions": 1,
                    "reviews": 1,
                }
            ]
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card], "children": []}]}
        manager = ReviewSessionManager(rs)
        manager._items = [(card, ("group", "g1"), card["boxes"][0])]

        # 1. Simulate rating the group which updates SM2 parameters
        with patch("services.review_manager.store.mark_dirty"), patch(
            "services.review_manager.store.save_soon"
        ), patch(
            "services.review_manager.recovery_manager.record_review_event"
        ), patch("builtins.print"):
            manager._rate(4)

        # Repetitions should increase to 2 for both boxes in group
        self.assertEqual(card["boxes"][0]["sm2_repetitions"], 2)
        self.assertEqual(card["boxes"][1]["sm2_repetitions"], 2)

        # 2. Simulate ungrouping (editor clearing group_id)
        edited_card = {
            "_id": 101,
            "title": "Test PDF Card",
            "pdf_path": "dummy.pdf",
            "boxes": [
                {
                    "box_id": "box_a",
                    "group_id": "",
                    "rect": [10, 10, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                },
                {
                    "box_id": "box_b",
                    "group_id": "",
                    "rect": [100, 100, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                }
            ]
        }

        # Merge SM-2 state like the editor saving does
        old_boxes_by_id = {b.get("box_id", ""): b for b in card.get("boxes", [])}
        SM2_KEYS = (
            "sched_state",
            "sched_step",
            "sm2_interval",
            "sm2_ease",
            "sm2_due",
            "sm2_last_quality",
            "sm2_repetitions",
            "reviews",
        )
        for new_box in edited_card.get("boxes", []):
            bid = new_box.get("box_id", "")
            if bid and bid in old_boxes_by_id:
                old = old_boxes_by_id[bid]
                for k in SM2_KEYS:
                    if k in old:
                        new_box[k] = old[k]

        card.update(edited_card)

        # 3. Rebuild queue simulating ReviewScreen._finish_edit_current_card logic
        manager._items = [item for item in manager._items if id(item[0]) != id(card)]
        
        # Force due dates to be due today so they get queued in active items
        for box in card["boxes"]:
            box["sm2_due"] = sm2_engine._now_iso()

        # Re-queue active/due boxes
        for box in card.get("boxes", []):
            if sm2_engine.is_due_today(box):
                i = card.get("boxes", []).index(box)
                manager._items.append((card, i, box))

        # Check that both boxes are now in queue as separate items
        self.assertEqual(len(manager._items), 2)
        self.assertEqual(manager._items[0][1], 0)
        self.assertEqual(manager._items[1][1], 1)

    def test_grouping_collapses_queue(self):
        rs = MagicMock()
        card = {
            "_id": 102,
            "title": "Test Grouping PDF Card",
            "pdf_path": "dummy.pdf",
            "boxes": [
                {
                    "box_id": "box_a",
                    "group_id": "", # Ungrouped initially
                    "rect": [10, 10, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 1,
                    "sm2_ease": 2.5,
                    "sm2_due": "2026-07-05T00:00:00",
                    "sm2_repetitions": 1,
                    "reviews": 1,
                },
                {
                    "box_id": "box_b",
                    "group_id": "", # Ungrouped initially
                    "rect": [100, 100, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                    "sched_state": "review",
                    "sched_step": 0,
                    "sm2_interval": 1,
                    "sm2_ease": 2.5,
                    "sm2_due": "2026-07-05T00:00:00",
                    "sm2_repetitions": 1,
                    "reviews": 1,
                }
            ]
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card], "children": []}]}
        manager = ReviewSessionManager(rs)
        
        # Initially, both are in the queue as separate items
        manager._items = [
            (card, 0, card["boxes"][0]),
            (card, 1, card["boxes"][1])
        ]
        
        # 1. User groups them in the editor under group_id "g1" and saves
        edited_card = {
            "_id": 102,
            "title": "Test Grouping PDF Card",
            "pdf_path": "dummy.pdf",
            "boxes": [
                {
                    "box_id": "box_a",
                    "group_id": "g1",
                    "rect": [10, 10, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                },
                {
                    "box_id": "box_b",
                    "group_id": "g1",
                    "rect": [100, 100, 50, 50],
                    "page_num": 0,
                    "shape": "rect",
                    "angle": 0,
                }
            ]
        }
        
        # Merge SM-2 state like the editor saving does
        old_boxes_by_id = {b.get("box_id", ""): b for b in card.get("boxes", [])}
        SM2_KEYS = (
            "sched_state",
            "sched_step",
            "sm2_interval",
            "sm2_ease",
            "sm2_due",
            "sm2_last_quality",
            "sm2_repetitions",
            "reviews",
        )
        for new_box in edited_card.get("boxes", []):
            bid = new_box.get("box_id", "")
            if bid and bid in old_boxes_by_id:
                old = old_boxes_by_id[bid]
                for k in SM2_KEYS:
                    if k in old:
                        new_box[k] = old[k]
                        
        card.update(edited_card)
        
        # 2. Rebuild queue simulating ReviewScreen._finish_edit_current_card logic
        # Discard old queue items for this card
        manager._items = [item for item in manager._items if id(item[0]) != id(card)]
        manager._queued_ids = set()
        
        # Force due dates to be due today so they get queued in active items
        for box in card["boxes"]:
            box["sm2_due"] = sm2_engine._now_iso()
            
        # Re-queue active/due boxes with group collapsing logic
        seen_new_groups = set()
        for box in card.get("boxes", []):
            bid = box.get("box_id", "")
            gid = box.get("group_id", "")
            track_id = gid if gid else bid
            if not track_id:
                continue
                
            if track_id in seen_new_groups or track_id in manager._queued_ids:
                continue
                
            if sm2_engine.is_due_today(box):
                manager._queued_ids.add(track_id)
                if gid:
                    seen_new_groups.add(gid)
                    manager._items.append((card, ("group", gid), box))
                else:
                    i = card.get("boxes", []).index(box)
                    manager._items.append((card, i, box))
                    
        # Check that they have collapsed into a single item in the review queue
        self.assertEqual(len(manager._items), 1)
        self.assertEqual(manager._items[0][1], ("group", "g1"))


if __name__ == "__main__":
    unittest.main()
