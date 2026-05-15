import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import recovery_manager


class RecoveryManagerTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.drafts = self.root / "drafts"
        self.pending = self.root / "pending"
        self.applied = self.root / "applied"

        def ensure_dirs():
            self.drafts.mkdir(parents=True, exist_ok=True)
            self.pending.mkdir(parents=True, exist_ok=True)
            self.applied.mkdir(parents=True, exist_ok=True)
            return {
                "drafts": str(self.drafts),
                "pending_events": str(self.pending),
                "applied_events": str(self.applied),
            }

        patches = [
            patch.object(
                recovery_manager, "current_recovery_drafts_dir", lambda: str(self.drafts)
            ),
            patch.object(
                recovery_manager,
                "current_recovery_pending_events_dir",
                lambda: str(self.pending),
            ),
            patch.object(
                recovery_manager,
                "current_recovery_applied_events_dir",
                lambda: str(self.applied),
            ),
            patch.object(recovery_manager, "ensure_recovery_dirs", ensure_dirs),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        ensure_dirs()

    def test_editor_draft_write_load_and_delete(self):
        draft = recovery_manager.save_editor_draft(
            {
                "draft_id": "draft-a",
                "mode": "add",
                "card": {"title": "Speed", "boxes": [{"box_id": "b1"}]},
            }
        )

        loaded = recovery_manager.load_editor_drafts()

        self.assertEqual(draft["draft_id"], "draft-a")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["card"]["title"], "Speed")
        self.assertTrue(recovery_manager.delete_editor_draft("draft-a"))
        self.assertEqual(recovery_manager.load_editor_drafts(), [])

    def test_atomic_recovery_write_retries_transient_permission_error(self):
        original_replace = recovery_manager.os.replace
        calls = []

        def flaky_replace(src, dst):
            calls.append((src, dst))
            if len(calls) == 1:
                raise PermissionError("file is briefly locked")
            return original_replace(src, dst)

        with patch.object(recovery_manager.os, "replace", side_effect=flaky_replace):
            draft = recovery_manager.save_editor_draft(
                {
                    "draft_id": "draft-retry",
                    "mode": "add",
                    "card": {"title": "Retry"},
                }
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(draft["draft_id"], "draft-retry")
        self.assertTrue(Path(recovery_manager.draft_path("draft-retry")).exists())

    def test_prune_old_recovery_records(self):
        recovery_manager._atomic_write_json(
            str(self.drafts / "draft_old.json"),
            {
                "record_type": "editor_draft",
                "draft_id": "old",
                "updated_at": "2000-01-01T00:00:00",
                "card": {},
            },
        )
        recovery_manager.save_editor_draft(
            {"draft_id": "new", "mode": "add", "card": {"title": "Keep"}}
        )

        deleted = recovery_manager.prune_old_records(days=30)

        self.assertEqual(deleted, 1)
        self.assertFalse((self.drafts / "draft_old.json").exists())
        self.assertTrue(Path(recovery_manager.draft_path("new")).exists())

    def test_review_event_apply_is_idempotent(self):
        box = {
            "box_id": "box-1",
            "sched_state": "review",
            "sm2_interval": 4,
            "reviews": 1,
            "reviewed_at": "2026-05-15T10:00:00",
        }
        card = {
            "title": "Time",
            "created": "2026-05-15T09:00:00",
            "pdf_path": "pdfs/time.pdf",
            "boxes": [box],
            "last_reviewed_at": "2026-05-15T10:00:00",
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        event = recovery_manager.build_review_event(
            data, card, 0, 5, "2026-05-15T10:00:00"
        )
        recovery_manager.record_review_event(event)

        box.update({"sched_state": "new", "sm2_interval": 1, "reviews": 0})
        card.pop("last_reviewed_at", None)

        first = recovery_manager.apply_pending_review_events(data)
        second = recovery_manager.apply_pending_review_events(data)

        self.assertEqual(first["applied"], 1)
        self.assertEqual(second["applied"], 0)
        self.assertEqual(second["already_applied"], 0)
        self.assertEqual(box["sm2_interval"], 4)
        self.assertEqual(card["last_reviewed_at"], "2026-05-15T10:00:00")
        self.assertEqual(len(list(self.applied.glob("*.json"))), 1)

    def test_ambiguous_review_event_is_not_applied(self):
        data = {
            "decks": [
                {
                    "_id": 1,
                    "name": "Math",
                    "cards": [
                        {"title": "Same", "boxes": [{"reviews": 0}]},
                        {"title": "Same", "boxes": [{"reviews": 0}]},
                    ],
                    "children": [],
                }
            ]
        }
        event = {
            "record_type": "review_event",
            "event_id": "ambiguous",
            "timestamp": "2026-05-15T10:00:00",
            "card_locator": {"title": "Same"},
            "updates": [{"target": "card_meta", "fields": {"last_reviewed_at": "x"}}],
        }
        recovery_manager.record_review_event(event)

        result = recovery_manager.apply_pending_review_events(data)

        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["blocked"][0]["status"], "ambiguous")
        self.assertNotIn("last_reviewed_at", data["decks"][0]["cards"][0])
        self.assertEqual(len(list(self.pending.glob("*.json"))), 1)

    def test_scan_moves_already_reflected_event_to_applied(self):
        card = {
            "title": "Done",
            "created": "2026-05-15T09:00:00",
            "last_reviewed_at": "2026-05-15T10:00:00",
            "boxes": [],
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        event = {
            "record_type": "review_event",
            "event_id": "done",
            "timestamp": "2026-05-15T10:00:00",
            "card_locator": {
                "deck_id": 1,
                "card_index": 0,
                "title": "Done",
                "created": "2026-05-15T09:00:00",
            },
            "updates": [
                {
                    "target": "card_meta",
                    "fields": {"last_reviewed_at": "2026-05-15T10:00:00"},
                }
            ],
        }
        recovery_manager.record_review_event(event)

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(summary["review_events"], [])
        self.assertEqual(summary["moved_applied"], 1)
        self.assertEqual(len(list(self.pending.glob("*.json"))), 0)
        self.assertEqual(len(list(self.applied.glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
