import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from perf_utils import (
    build_deck_rollups,
    card_has_due_today,
    count_due_units_in_card,
    maybe_perf_breakpoint,
    perf_log,
    perf_timer,
)


class PerfUtilsTests(unittest.TestCase):
    def test_grouped_boxes_count_as_one_due_card_and_one_due_unit(self):
        card = {
            "boxes": [
                {"group_id": "g1", "sm2_due": "2000-01-01T00:00:00", "sched_state": "review"},
                {"group_id": "g1", "sm2_due": "2999-01-01T00:00:00", "sched_state": "review"},
            ]
        }

        self.assertTrue(card_has_due_today(card))
        self.assertEqual(count_due_units_in_card(card), 1)

    def test_rollups_include_children_once(self):
        decks = [
            {
                "_id": 1,
                "cards": [
                    {"sm2_due": "2000-01-01T00:00:00", "sched_state": "review"},
                ],
                "children": [
                    {
                        "_id": 2,
                        "cards": [
                            {"sm2_due": "2999-01-01T00:00:00", "sched_state": "review"},
                            {"sm2_due": "2000-01-01T00:00:00", "sched_state": "review"},
                        ],
                        "children": [],
                    }
                ],
            }
        ]

        rollups = build_deck_rollups(decks)
        self.assertEqual(rollups["total_cards"][1], 3)
        self.assertEqual(rollups["total_cards"][2], 2)
        self.assertEqual(rollups["due_cards"][1], 2)
        self.assertEqual(rollups["due_cards"][2], 1)
        self.assertEqual(rollups["due_units"][1], 2)
        self.assertEqual(rollups["due_units"][2], 1)

    def test_perf_log_writes_jsonl_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "perf.jsonl"
            env = {
                "ANKI_PERF_LOG_PATH": str(log_path),
                "ANKI_PERF_DEBUG": "",
                "ANKI_PERF_BREAKPOINT": "",
            }
            with patch.dict(os.environ, env, clear=False):
                perf_log("unit_event", value=3, nested={"ok": True})

            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["event"], "unit_event")
            self.assertEqual(record["value"], 3)
            self.assertEqual(record["nested"], {"ok": True})

    def test_perf_timer_records_elapsed_ms(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "perf.jsonl"
            env = {"ANKI_PERF_LOG_PATH": str(log_path), "ANKI_PERF_BREAKPOINT": ""}
            with patch.dict(os.environ, env, clear=False):
                with perf_timer("timed_event", label="demo"):
                    pass

            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["event"], "timed_event")
            self.assertEqual(record["label"], "demo")
            self.assertIn("elapsed_ms", record)

    def test_perf_breakpoint_is_conditional_by_event(self):
        with patch.dict(os.environ, {"ANKI_PERF_BREAKPOINT": "target_event"}, clear=False):
            with patch("builtins.breakpoint") as mocked_breakpoint:
                maybe_perf_breakpoint("other_event")
                mocked_breakpoint.assert_not_called()
                maybe_perf_breakpoint("target_event")
                mocked_breakpoint.assert_called_once()


if __name__ == "__main__":
    unittest.main()
