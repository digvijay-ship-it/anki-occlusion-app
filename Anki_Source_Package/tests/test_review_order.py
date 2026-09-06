import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
_APP = QApplication.instance() or QApplication([])

from sm2_engine import get_card_maturity_score
from ui.review_screen import ReviewScreen
from ui.deck_view import DeckView
from ui.deck_tree import DeckTree


class TestReviewOrder(unittest.TestCase):
    def test_get_card_maturity_score_tiers(self):
        # 1. New card (reviews == 0, sched_state == "new")
        new_card = {"title": "New", "sched_state": "new", "reviews": 0}
        score_new = get_card_maturity_score(new_card)
        self.assertEqual(score_new[0], 0)  # tier 0
        self.assertEqual(score_new[1], 0)  # interval 0

        # 2. Learning card (sched_state == "learning")
        learning_card = {"title": "Learn", "sched_state": "learning", "reviews": 1, "sm2_last_quality": 3}
        score_learn = get_card_maturity_score(learning_card)
        self.assertEqual(score_learn[0], 1)  # tier 1
        self.assertEqual(score_learn[1], 0)  # interval 0

        # 3. Young review cards (1 day, 2 days)
        rev_1d = {"title": "1d", "sched_state": "review", "reviews": 2, "sm2_last_quality": 3, "sm2_interval": 1, "sm2_repetitions": 1}
        rev_2d = {"title": "2d", "sched_state": "review", "reviews": 3, "sm2_last_quality": 4, "sm2_interval": 2, "sm2_repetitions": 2}
        score_1d = get_card_maturity_score(rev_1d)
        score_2d = get_card_maturity_score(rev_2d)
        self.assertEqual(score_1d[0], 2)  # tier 2
        self.assertEqual(score_1d[1], 1)  # interval 1
        self.assertEqual(score_2d[0], 2)  # tier 2
        self.assertEqual(score_2d[1], 2)  # interval 2

        # 4. Mature review card (60 days)
        rev_60d = {"title": "60d", "sched_state": "review", "reviews": 8, "sm2_last_quality": 4, "sm2_interval": 60, "sm2_repetitions": 6}
        score_60d = get_card_maturity_score(rev_60d)
        self.assertEqual(score_60d[0], 2)
        self.assertEqual(score_60d[1], 60)

        # 5. Strict ordering: New < Learn < 1d < 2d < 60d
        self.assertLess(score_new, score_learn)
        self.assertLess(score_learn, score_1d)
        self.assertLess(score_1d, score_2d)
        self.assertLess(score_2d, score_60d)

    def test_maturity_score_sorting_list(self):
        c_60d = {"id": "mature", "sched_state": "review", "reviews": 10, "sm2_last_quality": 4, "sm2_interval": 60}
        c_new = {"id": "brand_new", "sched_state": "new", "reviews": 0}
        c_2d = {"id": "immature_2d", "sched_state": "review", "reviews": 2, "sm2_last_quality": 3, "sm2_interval": 2}
        c_1d = {"id": "immature_1d", "sched_state": "review", "reviews": 1, "sm2_last_quality": 3, "sm2_interval": 1}

        cards = [c_60d, c_new, c_2d, c_1d]
        sorted_cards = sorted(cards, key=lambda c: get_card_maturity_score(c))

        expected_ids = ["brand_new", "immature_1d", "immature_2d", "mature"]
        actual_ids = [c["id"] for c in sorted_cards]
        self.assertEqual(actual_ids, expected_ids)

    def test_resort_queue_by_order_mode(self):
        c_mature = {"id": "mature", "sched_state": "review", "reviews": 10, "sm2_last_quality": 4, "sm2_interval": 60, "sm2_due": "2026-05-01"}
        c_young = {"id": "young", "sched_state": "review", "reviews": 2, "sm2_last_quality": 3, "sm2_interval": 1, "sm2_due": "2026-05-10"}

        item_mature = (c_mature, None, c_mature)
        item_young = (c_young, None, c_young)

        rs = MagicMock(spec=ReviewScreen)
        rs._order_mode = "default"
        rs._idx = 0
        rs._done = 0
        rs._items = [item_mature, item_young]
        rs.mgr = MagicMock()
        rs._load_item = MagicMock()

        # Switch to least_mature and re-sort
        rs._order_mode = "least_mature"
        ReviewScreen._resort_queue_by_order_mode(rs)

        # In least_mature, item_young (1d) must be placed before item_mature (60d)
        self.assertEqual(rs._items[0], item_young)
        self.assertEqual(rs._items[1], item_mature)
        rs._load_item.assert_called_once()
        rs.mgr._rebuild_queue.assert_called_once()

        # Switch back to default and re-sort
        rs._order_mode = "default"
        ReviewScreen._resort_queue_by_order_mode(rs)

        # In default, item_mature (due 2026-05-01) comes before item_young (due 2026-05-10)
        self.assertEqual(rs._items[0], item_mature)
        self.assertEqual(rs._items[1], item_young)

    def test_deck_view_toggle_order_mode(self):
        dv = DeckView()
        deck = {"_id": "test_deck_1", "name": "Math", "cards": [], "review_order": "default"}
        dv.load_deck(deck, {"decks": [deck]})

        self.assertEqual(dv.btn_order_mode.text(), "📅 Due Order")
        self.assertEqual(deck.get("review_order"), "default")

        with patch("ui.deck_view.store.mark_dirty"), patch("ui.deck_view.store.save_soon"):
            dv._toggle_deck_order_mode()

        self.assertEqual(deck.get("review_order"), "least_mature")
        self.assertEqual(dv.btn_order_mode.text(), "🌱 Least Mature")

        with patch("ui.deck_view.store.mark_dirty"), patch("ui.deck_view.store.save_soon"):
            dv._toggle_deck_order_mode()

        self.assertEqual(deck.get("review_order"), "default")
        self.assertEqual(dv.btn_order_mode.text(), "📅 Due Order")

    def test_deck_tree_set_deck_order_mode(self):
        deck = {"_id": "math_subdeck", "name": "Algebra", "cards": []}
        dt = DeckTree(data={"decks": [deck]})

        with patch("ui.deck_tree.store.mark_dirty") as mark_dirty, \
             patch("ui.deck_tree.store.save_soon") as save_soon:
            dt._set_deck_order_mode("math_subdeck", "least_mature")

        self.assertEqual(deck.get("review_order"), "least_mature")
        mark_dirty.assert_called_once()
        save_soon.assert_called_once()


if __name__ == "__main__":
    unittest.main()
