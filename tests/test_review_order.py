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

    def test_parent_deck_review_due_least_mature_flattens(self):
        c1 = {"id": "c1", "sched_state": "new", "reviews": 0}
        c2 = {"id": "c2", "sched_state": "review", "reviews": 5, "sm2_interval": 30}
        sub1 = {"_id": "sub1", "name": "Percentage", "cards": [c1]}
        sub2 = {"_id": "sub2", "name": "Trigonometry", "cards": [c2]}
        parent_deck = {"_id": "parent", "name": "Math", "children": [sub1, sub2]}

        dv = DeckView()
        dv.deck = parent_deck
        dv._data = {"decks": [parent_deck]}

        with patch.object(dv, "_card_has_due_today", return_value=True), \
             patch.object(dv, "_prompt_selective_cards", side_effect=lambda cards, is_due: cards), \
             patch.object(dv, "_start_review") as mock_start_review:
            dv._review_due(order_mode="least_mature")

            mock_start_review.assert_called_once()
            args, kwargs = mock_start_review.call_args
            called_cards = args[0]
            # Must contain both cards from both subdecks flattened together
            self.assertEqual(len(called_cards), 2)
            self.assertEqual({c["id"] for c in called_cards}, {"c1", "c2"})
            self.assertEqual(kwargs.get("order_mode"), "least_mature")
            self.assertFalse(kwargs.get("is_practice", False))

    def test_parent_deck_practice_least_mature_flattens(self):
        c1 = {"id": "c1", "sched_state": "new", "reviews": 0}
        c2 = {"id": "c2", "sched_state": "review", "reviews": 5, "sm2_interval": 30}
        sub1 = {"_id": "sub1", "name": "Percentage", "cards": [c1]}
        sub2 = {"_id": "sub2", "name": "Trigonometry", "cards": [c2]}
        parent_deck = {"_id": "parent", "name": "Math", "children": [sub1, sub2]}

        dv = DeckView()
        dv.deck = parent_deck
        dv._data = {"decks": [parent_deck]}

        with patch.object(dv, "_prompt_selective_cards", side_effect=lambda cards, is_due: cards), \
             patch.object(dv, "_start_review") as mock_start_review:
            dv._practice_deck(order_mode="least_mature")

            mock_start_review.assert_called_once()
            args, kwargs = mock_start_review.call_args
            called_cards = args[0]
            # Must contain both cards from both subdecks flattened together
            self.assertEqual(len(called_cards), 2)
            self.assertEqual({c["id"] for c in called_cards}, {"c1", "c2"})
            self.assertEqual(kwargs.get("order_mode"), "least_mature")
            self.assertTrue(kwargs.get("is_practice"))

    def test_home_screen_show_review_sequential_least_mature(self):
        from ui.home_screen import HomeScreen
        home = MagicMock(spec=HomeScreen)
        c1 = {"id": "c1"}
        c2 = {"id": "c2"}
        groups = [[c1], [c2]]

        HomeScreen.show_review_sequential(
            home,
            groups,
            data={},
            is_practice=True,
            order_mode="least_mature",
            deck_id="parent_id",
            deck_name="Math",
        )

        home.show_review.assert_called_once_with(
            [c1, c2],
            {},
            is_practice=True,
            order_mode="least_mature",
            default_daily_target=None,
            default_session_target=None,
            auto_exit_session=None,
            deck_id="parent_id",
            deck_name="Math",
        )


    def test_tmnt_banner_least_mature_button(self):
        from ui.tmnt_home import TMNTMainContent
        c1 = {"id": "c1", "sched_state": "new", "reviews": 0}
        deck = {"_id": "math_sub", "name": "Percentage", "cards": [c1]}

        main = TMNTMainContent(data={"decks": [deck]})
        with patch.object(main, "_collect_due_by_pdf", return_value=[c1]):
            main.load_deck(deck, {"decks": [deck]})

            # Check button text and tooltip
            self.assertIn("REVIEW LEAST MATURE", main.btn_all.text())
            self.assertTrue(main.btn_all.isEnabled())
            self.assertIn("Review cards", main.btn_all.toolTip())
            self.assertNotIn("Practice cards", main.btn_all.toolTip())

            # Clicking btn_all triggers _review_due with order_mode="least_mature"
            with patch.object(main, "_review_due") as mock_review:
                main.btn_all.click()
                mock_review.assert_called_once_with(order_mode="least_mature")

    def test_tmnt_banner_review_new_button(self):
        from ui.tmnt_home import TMNTMainContent
        c1 = {"id": "c1", "sched_state": "new", "reviews": 0}
        c2 = {"id": "c2", "sched_state": "new", "reviews": 0}
        deck = {"_id": "math_sub", "name": "Percentage", "cards": [c1, c2]}

        main = TMNTMainContent(data={"decks": [deck]})
        main.load_deck(deck, {"decks": [deck]})

        # Check button text shows count of new cards
        self.assertEqual(main.btn_review_new.text(), "✨  REVIEW NEW (2)")
        self.assertTrue(main.btn_review_new.isEnabled())
        self.assertIn("Review only brand-new cards", main.btn_review_new.toolTip())

        # Clicking btn_review_new triggers _start_review with is_practice=False
        with patch.object(main, "_prompt_selective_cards", side_effect=lambda cards, is_due: cards), \
             patch.object(main, "_start_review") as mock_start_review:
            main.btn_review_new.click()
            mock_start_review.assert_called_once()
            args, kwargs = mock_start_review.call_args
            self.assertFalse(kwargs.get("is_practice", False))
            self.assertEqual(len(args[0]), 2)

        # When cleared, count resets to 0 and disabled
        main.clear()
        self.assertEqual(main.btn_review_new.text(), "✨  REVIEW NEW (0)")
        self.assertFalse(main.btn_review_new.isEnabled())

    def test_review_new_cards_not_practice(self):
        c1 = {"id": "c1", "sched_state": "new", "reviews": 0}
        deck = {"_id": "leaf", "name": "Algebra", "cards": [c1]}

        dv = DeckView()
        dv.deck = deck
        dv._data = {"decks": [deck]}

        with patch.object(dv, "_prompt_selective_cards", side_effect=lambda cards, is_due: cards), \
             patch.object(dv, "_start_review") as mock_start_review:
            dv._review_new_cards()

            mock_start_review.assert_called_once()
            args, kwargs = mock_start_review.call_args
            # Must be review (is_practice=False), not practice!
            self.assertFalse(kwargs.get("is_practice", False))
            self.assertEqual(args[0], [c1])


    def test_least_mature_excludes_new_cards(self):
        # c_new is brand new, c_due is reviewed and due
        c_new = {"id": "c_new", "sched_state": "new", "reviews": 0, "sm2_last_quality": -1}
        c_due = {"id": "c_due", "sched_state": "review", "reviews": 3, "sm2_last_quality": 4, "sm2_due": "2020-01-01"}
        deck = {"_id": "math_sub", "name": "Geometry", "cards": [c_new, c_due]}

        dv = DeckView()
        dv.deck = deck
        dv._data = {"decks": [deck]}

        # When reviewing due in least_mature mode, it should ONLY include c_due, excluding c_new!
        with patch.object(dv, "_prompt_selective_cards", side_effect=lambda cards, is_due: cards), \
             patch.object(dv, "_start_review") as mock_start_review:
            dv._review_due_least_mature()

            mock_start_review.assert_called_once()
            args, kwargs = mock_start_review.call_args
            self.assertEqual(kwargs.get("order_mode"), "least_mature")
            self.assertFalse(kwargs.get("is_practice", True))
            reviewed_cards = args[0]
            self.assertEqual(len(reviewed_cards), 1)
            self.assertEqual(reviewed_cards[0]["id"], "c_due")


if __name__ == "__main__":
    unittest.main()
