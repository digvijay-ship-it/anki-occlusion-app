# -*- coding: utf-8 -*-
"""
tests/test_study_flow.py
~~~~~~~~~~~~~~~~~~~~~~~~
Unit test suite for the Daily Study Flow & Session Tile Planner service and UI.
"""

import sys
import unittest
from PyQt5.QtWidgets import QApplication
from services.study_flow_service import StudyFlowService, FlowTile, DailyStudyPlan
from data_manager import store

_app = QApplication.instance() or QApplication(sys.argv)


class TestStudyFlowService(unittest.TestCase):
    def setUp(self):
        store._data = {"decks": []}

    def test_chunk_generation_exact_multiple(self):
        """100 cards with chunk size 25 should yield exactly 4 tiles of 25."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=1,
            deck_name="Math",
            deck_path="Exams / Math",
            total_target=100,
            chunk_size=25,
            mode="due",
        )
        self.assertEqual(len(tiles), 4)
        for t in tiles:
            self.assertEqual(t.target_cards, 25)
            self.assertEqual(t.deck_name, "Math")
            self.assertEqual(t.mode, "due")

    def test_chunk_generation_remainder(self):
        """70 cards with chunk size 25 should yield tiles: 25, 25, 20."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=2,
            deck_name="English",
            deck_path="Languages / English",
            total_target=70,
            chunk_size=25,
            mode="new",
        )
        self.assertEqual(len(tiles), 3)
        self.assertEqual(tiles[0].target_cards, 25)
        self.assertEqual(tiles[1].target_cards, 25)
        self.assertEqual(tiles[2].target_cards, 20)

    def test_parts_division_user_scenario(self):
        """User scenario: 105 cards divided into 4 parts yields [26, 26, 26, 27] where remainder is added to final session."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=3,
            deck_name="Math",
            deck_path="Exams / Math",
            total_target=105,
            parts=4,
            mode="due",
        )
        self.assertEqual(len(tiles), 4)
        self.assertEqual([t.target_cards for t in tiles], [26, 26, 26, 27])
        self.assertEqual(sum(t.target_cards for t in tiles), 105)

    def test_parts_division_exact(self):
        """100 cards divided into 4 parts yields [25, 25, 25, 25]."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=4,
            deck_name="Science",
            deck_path="Exams / Science",
            total_target=100,
            parts=4,
            mode="new",
        )
        self.assertEqual(len(tiles), 4)
        self.assertEqual([t.target_cards for t in tiles], [25, 25, 25, 25])
        self.assertEqual(sum(t.target_cards for t in tiles), 100)

    def test_parts_division_large_386(self):
        """386 cards divided into 5 parts yields [77, 77, 77, 77, 78]."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=5,
            deck_name="Math Backlog",
            deck_path="Exams / Math",
            total_target=386,
            parts=5,
            mode="due",
        )
        self.assertEqual(len(tiles), 5)
        self.assertEqual([t.target_cards for t in tiles], [77, 77, 77, 77, 78])
        self.assertEqual(sum(t.target_cards for t in tiles), 386)

    def test_dual_target_mixed_generation(self):
        """User scenario: 100 Due + 100 New divided into 4 mixed parts yields 4 tiles of 50 (25 due + 25 new each)."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=6,
            deck_name="BlackBook OWS",
            deck_path="English / BlackBook / OWS",
            target_due=100,
            target_new=100,
            parts=4,
            mode="all",
            mix_style="mixed",
        )
        self.assertEqual(len(tiles), 4)
        for t in tiles:
            self.assertEqual(t.target_cards, 50)
            self.assertEqual(t.target_due, 25)
            self.assertEqual(t.target_new, 25)
            self.assertEqual(t.mode, "all")

    def test_dual_target_separate_generation(self):
        """100 Due + 100 New in separate mode with 4 parts yields 2 New tiles (50 each) + 2 Due tiles (50 each)."""
        tiles = StudyFlowService.generate_tiles(
            deck_id=7,
            deck_name="BlackBook OWS",
            deck_path="English / BlackBook / OWS",
            target_due=100,
            target_new=100,
            parts=4,
            mode="all",
            mix_style="separate",
        )
        self.assertEqual(len(tiles), 4)
        self.assertEqual(tiles[0].mode, "new")
        self.assertEqual(tiles[0].target_cards, 50)
        self.assertEqual(tiles[1].mode, "new")
        self.assertEqual(tiles[1].target_cards, 50)
        self.assertEqual(tiles[2].mode, "due")
        self.assertEqual(tiles[2].target_cards, 50)
        self.assertEqual(tiles[3].mode, "due")
        self.assertEqual(tiles[3].target_cards, 50)

    def test_plan_persistence_and_retrieval(self):
        """Plan should persist into store and be retrieved cleanly."""
        plan = StudyFlowService.get_or_create_today_plan()
        self.assertEqual(len(plan.tiles), 0)

        t1 = FlowTile(deck_id=10, deck_name="History", target_cards=20)
        t2 = FlowTile(deck_id=20, deck_name="Geography", target_cards=15)
        StudyFlowService.add_tiles_to_today_plan([t1, t2])

        loaded = StudyFlowService.get_or_create_today_plan()
        self.assertEqual(len(loaded.tiles), 2)
        self.assertEqual(loaded.total_target_cards, 35)
        self.assertEqual(loaded.tiles[0].deck_name, "History")

    def test_reorder_tiles(self):
        """Reordering should swap tiles in the daily playlist."""
        t1 = FlowTile(deck_id=1, deck_name="Tile1", target_cards=10)
        t2 = FlowTile(deck_id=2, deck_name="Tile2", target_cards=20)
        StudyFlowService.add_tiles_to_today_plan([t1, t2])

        StudyFlowService.reorder_tiles(0, 1)
        plan = StudyFlowService.get_or_create_today_plan()
        self.assertEqual(plan.tiles[0].deck_name, "Tile2")
        self.assertEqual(plan.tiles[1].deck_name, "Tile1")

    def test_tile_advancement(self):
        """Marking tile completed should advance index and mark all_completed when done."""
        t1 = FlowTile(deck_id=1, deck_name="Math Chunk 1", target_cards=25)
        t2 = FlowTile(deck_id=2, deck_name="GK Chunk 1", target_cards=20)
        StudyFlowService.add_tiles_to_today_plan([t1, t2])

        is_done, comp_tile, next_tile = StudyFlowService.advance_tile_progress(t1.id, 25)
        self.assertFalse(is_done)
        self.assertEqual(comp_tile.status, "completed")
        self.assertEqual(next_tile.id, t2.id)

        is_done2, comp_tile2, next_tile2 = StudyFlowService.advance_tile_progress(t2.id, 20)
        self.assertTrue(is_done2)
        self.assertEqual(comp_tile2.status, "completed")
        self.assertIsNone(next_tile2)

    def test_routine_preset_save_and_apply(self):
        """Saving as routine preset should allow instant re-instantiation."""
        t1 = FlowTile(deck_id=101, deck_name="Morning Math", target_cards=25)
        t2 = FlowTile(deck_id=102, deck_name="Morning Vocab", target_cards=30)
        StudyFlowService.save_routine_preset("Morning Drill", [t1, t2])

        presets = StudyFlowService.load_routine_presets()
        self.assertIn("Morning Drill", presets)
        self.assertEqual(len(presets["Morning Drill"]), 2)

        fresh_plan = StudyFlowService.apply_routine_preset("Morning Drill")
        self.assertIsNotNone(fresh_plan)
        self.assertEqual(len(fresh_plan.tiles), 2)
        self.assertEqual(fresh_plan.tiles[0].deck_name, "Morning Math")

    def test_card_deduplication_across_tiles(self):
        """Ensure two tiles pulling from the same deck get completely disjoint card sets."""
        deck = {
            "_id": 500,
            "name": "Math Test Deck",
            "cards": [
                {"_id": 1, "sched_state": "new", "reviews": 0},
                {"_id": 2, "sched_state": "new", "reviews": 0},
                {"_id": 3, "sched_state": "new", "reviews": 0},
                {"_id": 4, "sched_state": "new", "reviews": 0},
            ]
        }
        data = {"decks": [deck]}

        tile1 = FlowTile(deck_id=500, deck_name="Math Test", target_cards=2, mode="new")
        tile2 = FlowTile(deck_id=500, deck_name="Math Test", target_cards=2, mode="new")

        excluded_ids = set()
        cards1 = StudyFlowService.get_cards_for_tile(tile1, data, excluded_card_ids=excluded_ids)
        self.assertEqual(len(cards1), 2)
        self.assertEqual({c["_id"] for c in cards1}, {1, 2})
        self.assertEqual(excluded_ids, {1, 2})

        cards2 = StudyFlowService.get_cards_for_tile(tile2, data, excluded_card_ids=excluded_ids)
        self.assertEqual(len(cards2), 2)
        self.assertEqual({c["_id"] for c in cards2}, {3, 4})
        self.assertEqual(excluded_ids, {1, 2, 3, 4})

    def test_flow_transition_dialog_init(self):
        """FlowTransitionDialog should instantiate cleanly without error."""
        from ui.study_flow_transition_dialog import FlowTransitionDialog
        t1 = FlowTile(deck_id=1, deck_name="Math", target_cards=25)
        t2 = FlowTile(deck_id=2, deck_name="GK", target_cards=20)
        dlg = FlowTransitionDialog(completed_tile=t1, next_tile=t2, current_idx=1, total_tiles=2)
        self.assertIsNotNone(dlg)
        dlg.close()

    def test_study_flow_dialog_init(self):
        """StudyFlowDialog should instantiate cleanly and display the playlist."""
        from ui.study_flow_dialog import StudyFlowDialog
        dlg = StudyFlowDialog()
        self.assertIsNotNone(dlg)
        self.assertIsNotNone(dlg.plan)
        dlg.close()

    def test_review_screen_study_flow_context(self):
        """ReviewScreen should store study_flow_context and declare flow_tile_completed."""
        from ui.review_screen import ReviewScreen
        self.assertTrue(hasattr(ReviewScreen, "flow_tile_completed"))

    def test_subject_theme_color_assignment(self):
        """Distinct subjects get distinct colors, subdecks share parent subject color."""
        from ui.study_flow_dialog import StudyFlowDialog, SUBJECT_THEMES
        dlg = StudyFlowDialog()
        theme_bb = dlg._get_theme_for_deck("BlackBook / English / OWS", "OWS")
        theme_bb_sub = dlg._get_theme_for_deck("BlackBook / English / Idioms", "Idioms")
        theme_gk = dlg._get_theme_for_deck("Gk / Ancient History", "Ancient History")
        theme_math = dlg._get_theme_for_deck("Math / Algebra", "Algebra")

        # Subdecks of BlackBook must have the exact same color theme
        self.assertEqual(theme_bb["primary"], theme_bb_sub["primary"])
        self.assertEqual(theme_bb["name"], theme_bb_sub["name"])

        # Different root decks must receive distinct color themes
        self.assertNotEqual(theme_bb["primary"], theme_gk["primary"])
        self.assertNotEqual(theme_gk["primary"], theme_math["primary"])
        self.assertNotEqual(theme_bb["primary"], theme_math["primary"])
        dlg.close()

    def test_left_panel_scroll_and_unclipped_labels(self):
        """Left panel has 680px width, scroll area, and dual total label with height >= 44px."""
        from ui.study_flow_dialog import StudyFlowDialog
        dlg = StudyFlowDialog()
        self.assertTrue(hasattr(dlg, "_scroll_left"))
        self.assertGreaterEqual(dlg._lbl_dual_total.maximumHeight(), 44)
        self.assertTrue(dlg._scroll_left.widgetResizable())
        dlg.close()

    def test_reformat_plan_flow_due_first(self):
        """reformat_plan_flow with due_first and interleave=True produces interleaved due then interleaved new."""
        t_math = FlowTile(deck_id=1, deck_name="Math", deck_path="Exams / Math", target_cards=50, mode="all", target_due=30, target_new=20)
        t_bb = FlowTile(deck_id=2, deck_name="BlackBook", deck_path="English / BlackBook", target_cards=40, mode="all", target_due=25, target_new=15)
        t_gk = FlowTile(deck_id=3, deck_name="GK", deck_path="General / GK", target_cards=20, mode="due", target_due=20, target_new=0)

        plan = DailyStudyPlan(tiles=[t_math, t_bb, t_gk])
        StudyFlowService.save_today_plan(plan)

        reformatted = StudyFlowService.reformat_plan_flow(plan, mode="due_first", interleave=True)
        self.assertEqual(len(reformatted.tiles), 5)

        # Due phase is interleaved: Math (30) -> BlackBook (25) -> GK (20)
        self.assertEqual(reformatted.tiles[0].deck_name, "Math")
        self.assertEqual(reformatted.tiles[0].target_cards, 30)
        self.assertEqual(reformatted.tiles[0].mode, "due")

        self.assertEqual(reformatted.tiles[1].deck_name, "BlackBook")
        self.assertEqual(reformatted.tiles[1].target_cards, 25)
        self.assertEqual(reformatted.tiles[1].mode, "due")

        self.assertEqual(reformatted.tiles[2].deck_name, "GK")
        self.assertEqual(reformatted.tiles[2].target_cards, 20)
        self.assertEqual(reformatted.tiles[2].mode, "due")

        # New phase is interleaved: Math (20) -> BlackBook (15)
        self.assertEqual(reformatted.tiles[3].deck_name, "Math")
        self.assertEqual(reformatted.tiles[3].target_cards, 20)
        self.assertEqual(reformatted.tiles[3].mode, "new")

        self.assertEqual(reformatted.tiles[4].deck_name, "BlackBook")
        self.assertEqual(reformatted.tiles[4].target_cards, 15)
        self.assertEqual(reformatted.tiles[4].mode, "new")

    def test_reformat_plan_flow_blocked(self):
        """reformat_plan_flow with interleave=False groups by subject blocks."""
        t_math = FlowTile(deck_id=1, deck_name="Math", deck_path="Exams / Math", target_cards=50, mode="all", target_due=30, target_new=20)
        t_bb = FlowTile(deck_id=2, deck_name="BlackBook", deck_path="English / BlackBook", target_cards=40, mode="all", target_due=25, target_new=15)

        plan = DailyStudyPlan(tiles=[t_math, t_bb])
        StudyFlowService.save_today_plan(plan)

        reformatted = StudyFlowService.reformat_plan_flow(plan, mode="due_first", interleave=False)
        self.assertEqual(len(reformatted.tiles), 4)

        # Subject 1 (Math): Due (30) -> New (20)
        self.assertEqual(reformatted.tiles[0].deck_name, "Math")
        self.assertEqual(reformatted.tiles[0].mode, "due")
        self.assertEqual(reformatted.tiles[1].deck_name, "Math")
        self.assertEqual(reformatted.tiles[1].mode, "new")

        # Subject 2 (BlackBook): Due (25) -> New (15)
        self.assertEqual(reformatted.tiles[2].deck_name, "BlackBook")
        self.assertEqual(reformatted.tiles[2].mode, "due")
        self.assertEqual(reformatted.tiles[3].deck_name, "BlackBook")
        self.assertEqual(reformatted.tiles[3].mode, "new")

    def test_reformat_plan_flow_new_first(self):
        """reformat_plan_flow with new_first places new before due while preserving subject order."""
        t_math = FlowTile(deck_id=1, deck_name="Math", deck_path="Exams / Math", target_cards=50, mode="all", target_due=30, target_new=20)
        t_bb = FlowTile(deck_id=2, deck_name="BlackBook", deck_path="English / BlackBook", target_cards=40, mode="all", target_due=25, target_new=15)

        plan = DailyStudyPlan(tiles=[t_math, t_bb])
        StudyFlowService.save_today_plan(plan)

        reformatted = StudyFlowService.reformat_plan_flow(plan, mode="new_first")
        self.assertEqual(len(reformatted.tiles), 4)

        # New tiles first
        self.assertEqual(reformatted.tiles[0].deck_name, "Math")
        self.assertEqual(reformatted.tiles[0].mode, "new")
        self.assertEqual(reformatted.tiles[0].target_cards, 20)

        self.assertEqual(reformatted.tiles[1].deck_name, "BlackBook")
        self.assertEqual(reformatted.tiles[1].mode, "new")
        self.assertEqual(reformatted.tiles[1].target_cards, 15)

        # Due tiles second
        self.assertEqual(reformatted.tiles[2].deck_name, "Math")
        self.assertEqual(reformatted.tiles[2].mode, "due")
        self.assertEqual(reformatted.tiles[2].target_cards, 30)

        self.assertEqual(reformatted.tiles[3].deck_name, "BlackBook")
        self.assertEqual(reformatted.tiles[3].mode, "due")
        self.assertEqual(reformatted.tiles[3].target_cards, 25)

    def test_reformat_plan_flow_mixed_merge(self):
        """reformat_plan_flow with mixed merges separate due and new tiles of same deck back into mixed tiles."""
        t_math_d = FlowTile(deck_id=1, deck_name="Math", deck_path="Math", target_cards=30, mode="due", target_due=30, target_new=0)
        t_bb_d = FlowTile(deck_id=2, deck_name="BlackBook", deck_path="BlackBook", target_cards=25, mode="due", target_due=25, target_new=0)
        t_math_n = FlowTile(deck_id=1, deck_name="Math", deck_path="Math", target_cards=20, mode="new", target_due=0, target_new=20)
        t_bb_n = FlowTile(deck_id=2, deck_name="BlackBook", deck_path="BlackBook", target_cards=15, mode="new", target_due=0, target_new=15)

        plan = DailyStudyPlan(tiles=[t_math_d, t_bb_d, t_math_n, t_bb_n])
        StudyFlowService.save_today_plan(plan)

        merged_plan = StudyFlowService.reformat_plan_flow(plan, mode="mixed")
        self.assertEqual(len(merged_plan.tiles), 2)

        self.assertEqual(merged_plan.tiles[0].deck_name, "Math")
        self.assertEqual(merged_plan.tiles[0].target_cards, 50)
        self.assertEqual(merged_plan.tiles[0].target_due, 30)
        self.assertEqual(merged_plan.tiles[0].target_new, 20)
        self.assertEqual(merged_plan.tiles[0].mode, "all")

        self.assertEqual(merged_plan.tiles[1].deck_name, "BlackBook")
        self.assertEqual(merged_plan.tiles[1].target_cards, 40)
        self.assertEqual(merged_plan.tiles[1].target_due, 25)
        self.assertEqual(merged_plan.tiles[1].target_new, 15)

    def test_interleave_plan_tiles(self):
        """interleave_plan_tiles round-robins across distinct root subjects."""
        t1 = FlowTile(deck_id=1, deck_name="Math 1", deck_path="Math", target_cards=20)
        t2 = FlowTile(deck_id=1, deck_name="Math 2", deck_path="Math", target_cards=20)
        t3 = FlowTile(deck_id=2, deck_name="BB 1", deck_path="BlackBook", target_cards=25)
        t4 = FlowTile(deck_id=2, deck_name="BB 2", deck_path="BlackBook", target_cards=25)
        t5 = FlowTile(deck_id=3, deck_name="GK 1", deck_path="GK", target_cards=15)

        plan = DailyStudyPlan(tiles=[t1, t2, t3, t4, t5])
        StudyFlowService.save_today_plan(plan)

        interleaved = StudyFlowService.interleave_plan_tiles(plan)
        expected_names = ["Math 1", "BB 1", "GK 1", "Math 2", "BB 2"]
        self.assertEqual([t.deck_name for t in interleaved.tiles], expected_names)

    def test_flow_sorter_buttons_and_nofocus_anchoring(self):
        """StudyFlowDialog has flow buttons, NoFocus buttons on tiles, and preserves scroll."""
        from PyQt5.QtCore import Qt
        from ui.study_flow_dialog import StudyFlowDialog
        t1 = FlowTile(deck_id=1, deck_name="Math", target_cards=25)
        t2 = FlowTile(deck_id=2, deck_name="BlackBook", target_cards=20)
        StudyFlowService.save_today_plan(DailyStudyPlan(tiles=[t1, t2]))

        dlg = StudyFlowDialog()
        self.assertTrue(hasattr(dlg, "_btn_flow_mixed"))
        self.assertTrue(hasattr(dlg, "_btn_flow_due"))
        self.assertTrue(hasattr(dlg, "_btn_flow_new"))
        self.assertTrue(hasattr(dlg, "_btn_interleave_toggle"))

        # Verify buttons are enabled when tiles are present
        self.assertTrue(dlg._btn_flow_mixed.isEnabled())
        self.assertTrue(dlg._btn_flow_due.isEnabled())
        self.assertTrue(dlg._btn_interleave_toggle.isEnabled())
        self.assertTrue(dlg._interleave_active)

        # Toggle interleave
        dlg._on_interleave_toggled()
        self.assertFalse(dlg._interleave_active)
        self.assertIn("OFF", dlg._btn_interleave_toggle.text())

        dlg.close()

    def test_reformat_plan_flow_with_practice_all_cards(self):
        """A subject with practice/all mode tiles must interleave during primary phase, not be exiled to the end."""
        tiles = []
        for i in range(3):
            tiles.append(FlowTile(deck_id=1, deck_name="GK", deck_path="GK", target_cards=50, mode="due", target_due=50, target_new=0))
        for i in range(3):
            tiles.append(FlowTile(deck_id=2, deck_name="BlackBook", deck_path="BlackBook", target_cards=50, mode="due", target_due=50, target_new=0))
        for i in range(3):
            tiles.append(FlowTile(deck_id=2, deck_name="BlackBook", deck_path="BlackBook", target_cards=20, mode="new", target_due=0, target_new=20))
        for i in range(3):
            tiles.append(FlowTile(deck_id=3, deck_name="Math", deck_path="Math", target_cards=25, mode="all", target_due=0, target_new=0))

        plan = DailyStudyPlan(tiles=tiles)
        reordered = StudyFlowService.reformat_plan_flow(plan, mode="due_first", interleave=True)

        # Primary phase should rotate GK, BlackBook, and Math!
        names = [t.deck_name for t in reordered.tiles]
        # First 9 tiles must contain 3 GK, 3 BlackBook (due), and 3 Math!
        self.assertEqual(names[0:3], ["GK", "BlackBook", "Math"])
        self.assertEqual(names[3:6], ["GK", "BlackBook", "Math"])
        self.assertEqual(names[6:9], ["GK", "BlackBook", "Math"])
        # Last 3 tiles are BlackBook (new)
        self.assertEqual(names[9:12], ["BlackBook", "BlackBook", "BlackBook"])

    def test_subject_progress_dashboard_strip(self):
        """Option A: Subject Progress Dashboard Strip renders accurate aggregates and chip counts."""
        from ui.study_flow_dialog import StudyFlowDialog
        t1 = FlowTile(deck_id=1, deck_name="GK", deck_path="GK", target_cards=50, mode="due", completed_cards=50, status="completed")
        t2 = FlowTile(deck_id=1, deck_name="GK", deck_path="GK", target_cards=50, mode="due", completed_cards=0, status="pending")
        t3 = FlowTile(deck_id=2, deck_name="BlackBook", deck_path="BlackBook", target_cards=100, mode="due", completed_cards=0, status="pending")
        t4 = FlowTile(deck_id=3, deck_name="Math", deck_path="Math", target_cards=24, mode="all", completed_cards=0, status="pending")

        StudyFlowService.save_today_plan(DailyStudyPlan(tiles=[t1, t2, t3, t4]))
        dlg = StudyFlowDialog()
        self.assertTrue(hasattr(dlg, "_subject_progress_frame"))
        self.assertTrue(dlg._subject_progress_frame.isVisible())

        # Check chips inside _subject_progress_layout
        from PyQt5.QtWidgets import QPushButton
        chips = dlg._subject_progress_frame.findChildren(QPushButton)
        self.assertEqual(len(chips), 3)

        chip_texts = [c.text() for c in chips]
        # GK has 50/100 completed (50%) • 1/2 Done
        gk_chip = next(t for t in chip_texts if "GK" in t)
        self.assertIn("50/100", gk_chip)
        self.assertIn("50%", gk_chip)
        self.assertIn("1/2 Done", gk_chip)

        # BlackBook has 0/100 (0%) • 0/1 Done
        bb_chip = next(t for t in chip_texts if "BlackBook" in t)
        self.assertIn("0/100", bb_chip)
        self.assertIn("0/1 Done", bb_chip)

        # Math has 0/24 (0%) • 0/1 Done
        math_chip = next(t for t in chip_texts if "Math" in t)
        self.assertIn("0/24", math_chip)

        dlg.close()

    def test_study_flow_tile_launch_shows_interval_times(self):
        """Verify that cards reviewed in Study Flow have active FSRS/SM-2 intervals on rating buttons."""
        from ui.review_screen import ReviewScreen
        card = {
            "id": "c_flow_1",
            "title": "ECI Question",
            "sm2_state": "review",
            "interval": 4,
            "reps": 2,
            "ease": 2.5,
            "sm2_due": "2026-09-24",
            "boxes": []
        }
        tile = FlowTile(deck_id=1, deck_name="GK", target_cards=1, mode="all", target_due=1)
        ctx = {"tile": tile, "tile_index": 0, "total_tiles": 1}

        # Study flow launches with is_practice=False
        rs = ReviewScreen([card], {}, is_practice=False, is_new_only=False, study_flow_context=ctx)
        self.assertFalse(rs.is_practice)
        self.assertFalse(getattr(rs.mgr, "is_practice", False))

        # Check button texts: must contain interval preview values like '1m', '5m', '10m', '4d', etc.
        btn_texts = [btn.text() for btn, q in rs._prev_lbls]
        self.assertEqual(len(btn_texts), 5)
        for txt in btn_texts:
            # Format: '{num} {icon} {interval_val} {label}'
            parts = txt.split()
            # Must have at least 4 tokens: number, icon, interval time, and label (e.g. "1 🔁 1m AGAIN")
            self.assertGreaterEqual(len(parts), 4, f"Button text '{txt}' is missing interval time preview!")
            # Label must be one of AGAIN, HARD, GOOD, EASY, PERFECT
            self.assertIn(parts[-1].upper(), ["AGAIN", "HARD", "GOOD", "EASY", "PERFECT"])
            # The interval time preview must be non-empty and not '?'
            interval_str = parts[2]
            self.assertNotEqual(interval_str, "?")
            self.assertTrue(any(c in interval_str for c in ("m", "d", "y")), f"Interval '{interval_str}' not formatted as time")

        rs.close()


if __name__ == "__main__":
    unittest.main()
