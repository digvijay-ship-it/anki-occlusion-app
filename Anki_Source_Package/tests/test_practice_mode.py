import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
_APP = QApplication.instance() or QApplication([])

from services.review_manager import ReviewSessionManager
import sm2_engine
from ui.deck_view import DeckView
from ui.review.summary_dialog import ReviewSessionSummaryDialog
from ui.review_screen import ReviewScreen


class PracticeModeTests(unittest.TestCase):
    def test_practice_mode_does_not_affect_sm2_schedule(self):
        rs = MagicMock()
        original_due = "2026-05-20T00:00:00"
        card = {
            "title": "Practice Card 1",
            "sched_state": "review",
            "sched_step": 0,
            "sm2_interval": 10,
            "sm2_ease": 2.5,
            "sm2_due": original_due,
            "sm2_repetitions": 3,
            "sm2_last_quality": 4,
            "reviews": 3,
            "reviewed_at": "2026-05-10T00:00:00",
            "last_reviewed_at": "2026-05-10T00:00:00",
        }
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card], "children": []}]}
        manager = ReviewSessionManager(rs)
        manager.is_practice = True
        manager._items = [(card, None, card)]

        with patch("services.review_manager.store.mark_dirty") as mark_dirty, \
             patch("services.review_manager.store.save_soon") as save_soon, \
             patch("services.review_manager.recovery_manager.record_review_event") as record_event:
            manager._rate(1)  # Rate Again (in normal mode this would reset SM-2)

        # Assert zero SM-2 mutations
        self.assertEqual(card["sched_state"], "review")
        self.assertEqual(card["sm2_interval"], 10)
        self.assertEqual(card["sm2_ease"], 2.5)
        self.assertEqual(card["sm2_due"], original_due)
        self.assertEqual(card["sm2_repetitions"], 3)
        self.assertEqual(card["reviews"], 3)
        self.assertEqual(card["reviewed_at"], "2026-05-10T00:00:00")
        self.assertEqual(card["last_reviewed_at"], "2026-05-10T00:00:00")

        # Assert no persistence side-effects
        mark_dirty.assert_not_called()
        save_soon.assert_not_called()
        record_event.assert_not_called()

        # Assert progress was tracked
        self.assertEqual(manager._done, 1)
        self.assertEqual(manager._idx, 1)
        self.assertEqual(len(manager._session_ratings), 1)
        self.assertEqual(manager._session_ratings[0]["quality"], 1)
        rs._load_item.assert_called_once_with()

    def test_practice_mode_undo_redo(self):
        rs = MagicMock()
        card1 = {"title": "C1", "sched_state": "review", "sm2_interval": 5, "sm2_due": "2026-05-20T00:00:00"}
        card2 = {"title": "C2", "sched_state": "review", "sm2_interval": 8, "sm2_due": "2026-05-21T00:00:00"}
        rs._data = {"decks": [{"_id": 1, "name": "Deck", "cards": [card1, card2], "children": []}]}

        manager = ReviewSessionManager(rs)
        manager.is_practice = True
        manager._items = [(card1, None, card1), (card2, None, card2)]

        # Rate card 1 with Good (4)
        manager._rate(4)
        self.assertEqual(manager._idx, 1)
        self.assertEqual(manager._done, 1)
        self.assertEqual(len(manager._session_ratings), 1)
        self.assertEqual(manager._session_ratings[0]["quality"], 4)

        # Undo rating
        manager._review_undo()
        self.assertEqual(manager._idx, 0)
        self.assertEqual(manager._done, 0)
        self.assertEqual(len(manager._session_ratings), 0)

        # Redo rating
        manager._review_redo()
        self.assertEqual(manager._idx, 1)
        self.assertEqual(manager._done, 1)
        self.assertEqual(len(manager._session_ratings), 1)
        self.assertEqual(manager._session_ratings[0]["quality"], 4)

        # SM-2 remains untouched throughout
        self.assertEqual(card1["sm2_interval"], 5)
        self.assertEqual(card1["sm2_due"], "2026-05-20T00:00:00")

    def test_practice_performance_report_card(self):
        rs = MagicMock()
        rs.is_practice = True
        rs._done = 5
        rs._stimer = MagicMock()
        rs._stimer._session_elapsed = 120
        rs._stimer._pdf_seconds = {}
        rs._stimer._pdf_cards_today = {}
        
        card1 = {"title": "C1"}
        card2 = {"title": "C2"}
        card3 = {"title": "C3"}
        card4 = {"title": "C4"}
        card5 = {"title": "C5"}
        rs._items = [
            (card1, None, card1),
            (card2, None, card2),
            (card3, None, card3),
            (card4, None, card4),
            (card5, None, card5),
        ]
        rs.mgr = MagicMock()
        rs.mgr.is_practice = True
        rs.mgr._session_ratings = [
            {"card": card1, "box_idx": None, "quality": 1, "sm2_obj": card1},  # Again
            {"card": card2, "box_idx": None, "quality": 3, "sm2_obj": card2},  # Hard
            {"card": card3, "box_idx": None, "quality": 4, "sm2_obj": card3},  # Good
            {"card": card4, "box_idx": None, "quality": 5, "sm2_obj": card4},  # Easy
            {"card": card5, "box_idx": None, "quality": 6, "sm2_obj": card5},  # Perfect
        ]

        dlg = ReviewSessionSummaryDialog(rs)
        self.assertIn("Practice", dlg.windowTitle())

    def test_deck_view_collect_all_by_pdf(self):
        dv = DeckView()
        deck = {
            "_id": 1,
            "name": "Parent",
            "cards": [
                {"title": "Card 1", "pdf_path": "docA.pdf"},
                {"title": "Card 2", "pdf_path": "docA.pdf"},
            ],
            "children": [
                {
                    "_id": 2,
                    "name": "Child",
                    "cards": [
                        {"title": "Card 3", "pdf_path": "docB.pdf"},
                        {"title": "Card Formula", "is_formula": True},
                    ],
                    "children": []
                }
            ]
        }

        groups = dv._collect_all_by_pdf(deck)
        self.assertEqual(len(groups), 2)  # Group for docA, Group for docB
        self.assertEqual(len(groups[0]), 2)  # Card 1 and 2
        self.assertEqual(len(groups[1]), 1)  # Card 3 (formula card excluded)

    def test_deck_view_practice_deck_invokes_review_with_practice_true(self):
        dv = DeckView()
        deck = {
            "_id": 10,
            "name": "Physics",
            "cards": [{"title": "Newton", "pdf_path": "phys.pdf"}],
            "children": []
        }
        dv.deck = deck
        dv._data = {"decks": [deck]}

        with patch.object(dv, "_start_review") as mock_start:
            dv._practice_deck()
            mock_start.assert_called_once()
            args, kwargs = mock_start.call_args
            self.assertEqual(kwargs.get("is_practice"), True)

    def test_deck_tree_practice_deck_by_id(self):
        from ui.deck_tree import DeckTree
        deck = {
            "_id": 42,
            "name": "Polity",
            "cards": [{"title": "Amendments", "pdf_path": "polity.pdf"}],
            "children": []
        }
        data = {"decks": [deck]}
        dt = DeckTree(data=data)

        mock_home = MagicMock()
        mock_home._tmnt_layout = MagicMock()
        mock_home._tmnt_layout.main = MagicMock()

        with patch.object(dt, "_find_home", return_value=mock_home):
            dt._practice_deck_by_id(42)
            self.assertEqual(mock_home._tmnt_layout.main.deck, deck)
            mock_home._tmnt_layout.main._practice_deck.assert_called_once()

    def test_tmnt_main_content_practice_button_enabled_for_parent_deck(self):
        from ui.tmnt_home import TMNTMainContent
        deck = {
            "_id": 100,
            "name": "GK Parent",
            "cards": [],  # direct cards empty
            "children": [
                {
                    "_id": 101,
                    "name": "Polity Subdeck",
                    "cards": [{"title": "Emergency", "pdf_path": "law.pdf"}],
                    "children": []
                }
            ]
        }
        data = {"decks": [deck]}
        tmnt_main = TMNTMainContent(data=data)
        tmnt_main.load_deck(deck, data)
        self.assertTrue(tmnt_main.btn_practice.isEnabled())

    def test_practice_mode_queue_count_is_not_zero(self):
        rs = MagicMock()
        rs.is_practice = True
        rs._queue_list.count.return_value = 2
        card1 = {"title": "C1", "sm2_due": "2099-01-01T00:00:00"}
        card2 = {"title": "C2", "sm2_due": "2099-01-01T00:00:00"}
        rs._items = [(card1, None, card1), (card2, None, card2)]
        rs._idx = 0

        mgr = ReviewSessionManager(rs)
        mgr.is_practice = True
        mgr._items = rs._items
        mgr._idx = 0

        # When rebuilding queue in practice mode, active_count must be 2 (not 0)
        with patch.object(rs, "_update_queue_label") as mock_update:
            mgr._rebuild_queue()
            mock_update.assert_called_once_with(2)

    def test_json_import_preserves_related_concepts_and_chain(self):
        from data_manager import import_json_cards
        data = {"decks": []}
        json_cards = [
            {
                "deck_name": "Polity::Executive",
                "context_anchor": "Polity::President_Term",
                "chain_order": 1,
                "priority_tier": 1,
                "question": "What is Article 56?",
                "answer": "Term of President",
                "notes": "• Connected: Article 55 and Article 65",
                "trap_note": "TRAP: Article 56(1)(c)",
                "related_concepts": ["Article 55 (Manner)", "Article 65 (VP Acting)"],
                "tags": ["Article 56", "President"]
            }
        ]
        res = import_json_cards(data, json_cards)
        self.assertEqual(res["imported"], 1)
        card = data["decks"][0]["children"][0]["cards"][0]
        self.assertEqual(card["related_concepts"], ["Article 55 (Manner)", "Article 65 (VP Acting)"])
        self.assertEqual(card["chain_order"], 1)
        self.assertTrue(bool(card["parent_chain_id"]))

    def test_pdf_occlusion_boxes_queued_in_practice_mode_when_not_due(self):
        """Verify that cards with PDF occlusion boxes are queued in practice mode even if not due today."""
        card = {
            "title": "Ratio and Proportion (Type 5)",
            "pdf_path": "ratio.pdf",
            "boxes": [
                {"box_id": "b1", "rect": [10, 10, 50, 50], "sm2_due": "2099-01-01T00:00:00"},
                {"box_id": "b2", "rect": [10, 70, 50, 50], "sm2_due": "2099-01-01T00:00:00"},
                {"box_id": "b3", "group_id": "g1", "rect": [10, 130, 50, 50], "sm2_due": "2099-01-01T00:00:00"},
            ]
        }
        with patch.object(ReviewScreen, "_setup_ui"), patch.object(ReviewScreen, "_load_item"):
            def make_screen(is_prac):
                s = ReviewScreen.__new__(ReviewScreen)
                s.canvas = MagicMock()
                s._canvas_scroll = MagicMock()
                s._queue_panel = MagicMock()
                s._queue_list = MagicMock()
                s._queue_edge_button = MagicMock()
                s._queue_lock_button = MagicMock()
                s._queue_hide_button = MagicMock()
                s.__init__([card], is_practice=is_prac)
                return s

            # Practice mode: all 3 items (2 single boxes + 1 group) must be queued!
            screen_practice = make_screen(True)
            self.assertEqual(len(screen_practice._items), 3)
            self.assertEqual(screen_practice._active_queue_count(), 3)

            # Normal due mode: 0 items queued because all are future due
            screen_normal = make_screen(False)
            self.assertEqual(len(screen_normal._items), 0)


if __name__ == "__main__":
    unittest.main()
