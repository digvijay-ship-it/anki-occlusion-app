import json
import os
import tempfile
import unittest
from datetime import datetime
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
            patch.object(recovery_manager, "RETENTION_DAYS", 99999),
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

    def test_scan_moves_review_event_superseded_by_newer_loaded_review(self):
        box = {
            "box_id": "box-1",
            "sched_state": "review",
            "sm2_interval": 4,
            "sm2_repetitions": 4,
            "reviews": 4,
            "reviewed_at": "2026-05-19T11:57:52",
        }
        card = {
            "title": "Superseded",
            "created": "2026-05-15T09:00:00",
            "last_reviewed_at": "2026-05-20T10:00:00",
            "boxes": [box],
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        event = {
            "record_type": "review_event",
            "event_id": "old-review",
            "timestamp": "2026-05-15T12:17:42",
            "card_locator": {
                "deck_id": 1,
                "card_index": 0,
                "title": "Superseded",
                "created": "2026-05-15T09:00:00",
            },
            "updates": [
                {
                    "target": "box",
                    "box_locator": {"box_id": "box-1", "box_index": 0},
                    "fields": {
                        "sched_state": "review",
                        "sm2_interval": 4,
                        "sm2_repetitions": 3,
                        "reviews": 3,
                        "reviewed_at": "2026-05-15T12:17:42",
                    },
                },
                {
                    "target": "card_meta",
                    "fields": {"last_reviewed_at": "2026-05-15T12:17:42"},
                },
            ],
        }
        recovery_manager.record_review_event(event)

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(summary["review_events"], [])
        self.assertEqual(summary["moved_applied"], 1)
        self.assertEqual(len(list(self.pending.glob("*.json"))), 0)
        self.assertEqual(len(list(self.applied.glob("*.json"))), 1)

    def test_scan_moves_review_event_when_only_legacy_alias_fields_are_missing(self):
        box = {
            "box_id": "box-1",
            "sched_state": "review",
            "sched_step": 0,
            "sm2_interval": 4,
            "sm2_repetitions": 3,
            "sm2_last_quality": 4,
            "reviews": 3,
        }
        card = {
            "title": "Legacy Alias",
            "created": "2026-05-15T09:00:00",
            "last_reviewed_at": "2026-05-20T10:00:00",
            "boxes": [box],
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        event = {
            "record_type": "review_event",
            "event_id": "legacy-alias",
            "timestamp": "2026-05-15T12:17:42",
            "card_locator": {
                "deck_id": 1,
                "card_index": 0,
                "title": "Legacy Alias",
                "created": "2026-05-15T09:00:00",
            },
            "updates": [
                {
                    "target": "box",
                    "box_locator": {"box_id": "box-1", "box_index": 0},
                    "fields": {
                        "sched_state": "review",
                        "sched_step": 0,
                        "sm2_interval": 4,
                        "sm2_repetitions": 3,
                        "sm2_last_quality": 4,
                        "reviews": 3,
                        "reviewed_at": "2026-05-15T12:17:42",
                        "last_quality": 4,
                    },
                },
                {
                    "target": "card_meta",
                    "fields": {"last_reviewed_at": "2026-05-15T12:17:42"},
                },
            ],
        }
        recovery_manager.record_review_event(event)

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(summary["review_events"], [])
        self.assertEqual(summary["moved_applied"], 1)
        self.assertEqual(len(list(self.pending.glob("*.json"))), 0)
        self.assertEqual(len(list(self.applied.glob("*.json"))), 1)

    def test_scan_keeps_review_event_when_target_box_is_not_newer(self):
        box = {
            "box_id": "box-1",
            "sched_state": "new",
            "reviews": 0,
            "reviewed_at": "2026-05-15T09:00:00",
        }
        card = {
            "title": "Still Needed",
            "created": "2026-05-15T09:00:00",
            "last_reviewed_at": "2026-05-20T10:00:00",
            "boxes": [box],
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        event = {
            "record_type": "review_event",
            "event_id": "needed-review",
            "timestamp": "2026-05-15T12:17:42",
            "card_locator": {
                "deck_id": 1,
                "card_index": 0,
                "title": "Still Needed",
                "created": "2026-05-15T09:00:00",
            },
            "updates": [
                {
                    "target": "box",
                    "box_locator": {"box_id": "box-1", "box_index": 0},
                    "fields": {
                        "sched_state": "review",
                        "reviews": 1,
                        "reviewed_at": "2026-05-15T12:17:42",
                    },
                },
                {
                    "target": "card_meta",
                    "fields": {"last_reviewed_at": "2026-05-15T12:17:42"},
                },
            ],
        }
        recovery_manager.record_review_event(event)

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(len(summary["review_events"]), 1)
        self.assertEqual(summary["review_events"][0]["status"], "recoverable")
        self.assertEqual(summary["moved_applied"], 0)
        self.assertEqual(len(list(self.pending.glob("*.json"))), 1)
        self.assertEqual(len(list(self.applied.glob("*.json"))), 0)

    def test_scan_deletes_editor_draft_already_reflected_in_loaded_data(self):
        card = {
            "title": "Saved",
            "created": "2026-05-20T10:00:00",
            "pdf_path": "pdfs/saved.pdf",
            "notes": "done",
            "boxes": [{"box_id": "b1", "rect": [1, 2, 3, 4]}],
            "reviews": 0,
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        recovery_manager.save_editor_draft(
            {
                "draft_id": "already-saved",
                "mode": "edit",
                "initial_card_locator": {
                    "deck_id": 1,
                    "card_index": 0,
                    "title": "Saved",
                    "created": "2026-05-20T10:00:00",
                    "pdf_path": "pdfs/saved.pdf",
                },
                "card": dict(card),
            }
        )

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(summary["drafts"], [])
        self.assertEqual(summary["moved_saved_drafts"], 1)
        self.assertFalse(Path(recovery_manager.draft_path("already-saved")).exists())

    def test_scan_ignores_review_metadata_when_matching_editor_draft(self):
        draft_card = {
            "title": "Reviewed Later",
            "created": "2026-05-20T10:00:00",
            "pdf_path": "pdfs/reviewed.pdf",
            "notes": "same editor content",
            "boxes": [{"box_id": "b1", "rect": [1, 2, 3, 4]}],
            "reviews": 0,
        }
        saved_card = {
            "title": "Reviewed Later",
            "created": "2026-05-20T10:00:00",
            "pdf_path": "pdfs/reviewed.pdf",
            "notes": "same editor content",
            "boxes": [
                {
                    "box_id": "b1",
                    "rect": [1, 2, 3, 4],
                    "sched_state": "review",
                    "reviews": 4,
                    "reviewed_at": "2026-05-20T19:00:00",
                }
            ],
            "reviews": 4,
            "last_reviewed_at": "2026-05-20T19:00:00",
        }
        data = {
            "decks": [
                {"_id": 1, "name": "Math", "cards": [saved_card], "children": []}
            ]
        }
        recovery_manager.save_editor_draft(
            {
                "draft_id": "review-metadata-only",
                "mode": "edit",
                "initial_card_locator": {
                    "deck_id": 1,
                    "card_index": 0,
                    "title": "Reviewed Later",
                    "created": "2026-05-20T10:00:00",
                    "pdf_path": "pdfs/reviewed.pdf",
                },
                "card": draft_card,
            }
        )

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(summary["drafts"], [])
        self.assertEqual(summary["moved_saved_drafts"], 1)
        self.assertFalse(Path(recovery_manager.draft_path("review-metadata-only")).exists())

    def test_scan_deletes_add_draft_already_saved_as_new_card(self):
        card = {
            "title": "New Saved",
            "created": "2026-05-20T11:00:00",
            "image_path": "images/new.png",
            "notes": "already in deck",
            "tags": ["math"],
            "boxes": [{"box_id": "b2", "rect": [4, 3, 2, 1]}],
        }
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [card], "children": []}]}
        recovery_manager.save_editor_draft(
            {
                "draft_id": "add-already-saved",
                "mode": "add",
                "card": dict(card),
            }
        )

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(summary["drafts"], [])
        self.assertEqual(summary["moved_saved_drafts"], 1)
        self.assertFalse(Path(recovery_manager.draft_path("add-already-saved")).exists())

    def test_scan_keeps_editor_draft_with_unsaved_changes(self):
        saved_card = {
            "title": "Saved",
            "created": "2026-05-20T10:00:00",
            "pdf_path": "pdfs/saved.pdf",
            "notes": "old",
            "boxes": [{"box_id": "b1", "rect": [1, 2, 3, 4]}],
            "reviews": 0,
        }
        draft_card = dict(saved_card)
        draft_card["notes"] = "new unsaved note"
        data = {
            "decks": [
                {"_id": 1, "name": "Math", "cards": [saved_card], "children": []}
            ]
        }
        recovery_manager.save_editor_draft(
            {
                "draft_id": "unsaved",
                "mode": "edit",
                "initial_card_locator": {
                    "deck_id": 1,
                    "card_index": 0,
                    "title": "Saved",
                    "created": "2026-05-20T10:00:00",
                    "pdf_path": "pdfs/saved.pdf",
                },
                "card": draft_card,
            }
        )

        summary = recovery_manager.scan_recovery(data)

        self.assertEqual(len(summary["drafts"]), 1)
        self.assertEqual(summary["drafts"][0]["draft_id"], "unsaved")
        self.assertEqual(summary["drafts"][0]["status"], "recoverable")
        self.assertTrue(Path(recovery_manager.draft_path("unsaved")).exists())

    def test_startup_scan_skips_stale_draft_older_than_loaded_data_file(self):
        data_file = self.root / "anki_occlusion_data.json"
        data_file.write_text("{}", encoding="utf-8")
        old_time = datetime(2026, 5, 20, 10, 0, 0).timestamp()
        new_time = datetime(2026, 5, 20, 11, 0, 0).timestamp()
        draft = recovery_manager.save_editor_draft(
            {
                "draft_id": "old-add",
                "mode": "add",
                "card": {"title": "Old unsaved", "boxes": [{"box_id": "b1"}]},
            }
        )
        draft["updated_at"] = "2026-05-20T10:00:00"
        recovery_manager._atomic_write_json(recovery_manager.draft_path("old-add"), draft)
        os.utime(recovery_manager.draft_path("old-add"), (old_time, old_time))
        os.utime(data_file, (new_time, new_time))
        data = {"decks": [{"_id": 1, "name": "Math", "cards": [], "children": []}]}

        with patch.object(recovery_manager, "current_data_file", lambda: str(data_file)):
            startup_summary = recovery_manager.scan_recovery(data, startup=True)
            manual_summary = recovery_manager.scan_recovery(data, startup=False)

        self.assertEqual(startup_summary["drafts"], [])
        self.assertEqual(startup_summary["skipped_stale_drafts"], 1)
        self.assertEqual(len(manual_summary["drafts"]), 1)
        self.assertTrue(Path(recovery_manager.draft_path("old-add")).exists())

    def test_record_review_event_batched(self):
        # Clear any existing pending events or timers
        recovery_manager.flush()
        
        event = {
            "record_type": "review_event",
            "event_id": "batched-1",
            "timestamp": "2026-05-20T10:00:00",
            "quality": 4,
            "card_locator": {"title": "Test"},
            "updates": []
        }
        
        # Record event. It should go to memory, not disk.
        payload = recovery_manager.record_review_event(event)
        
        # Verify it's in memory
        with recovery_manager._LOCK:
            self.assertEqual(len(recovery_manager._PENDING_EVENTS), 1)
            self.assertEqual(recovery_manager._PENDING_EVENTS[0]["event_id"], "batched-1")
            
        # Verify no file on disk yet
        self.assertEqual(len(list(self.pending.glob("*.json"))), 0)
        
        # Force flush and verify it's written to disk
        recovery_manager.flush()
        with recovery_manager._LOCK:
            self.assertEqual(len(recovery_manager._PENDING_EVENTS), 0)
        self.assertEqual(len(list(self.pending.glob("*.json"))), 1)
        
    def test_record_review_event_force_flush(self):
        # Clear any existing pending events or timers
        recovery_manager.flush()
        
        # Record 25 events, which should force immediate write to disk
        for i in range(25):
            event = {
                "record_type": "review_event",
                "event_id": f"event-{i}",
                "timestamp": "2026-05-20T10:00:00",
                "quality": 4,
                "card_locator": {"title": "Test"},
                "updates": []
            }
            recovery_manager.record_review_event(event)
            
        # Verify memory is empty and disk has 25 files
        with recovery_manager._LOCK:
            self.assertEqual(len(recovery_manager._PENDING_EVENTS), 0)
        self.assertEqual(len(list(self.pending.glob("*.json"))), 25)
        
    def test_discard_review_event_removes_from_memory(self):
        # Clear any existing pending events or timers
        recovery_manager.flush()
        
        event = {
            "record_type": "review_event",
            "event_id": "discard-mem",
            "timestamp": "2026-05-20T10:00:00",
            "quality": 4,
            "card_locator": {"title": "Test"},
            "updates": []
        }
        recovery_manager.record_review_event(event)
        
        # Discard it
        deleted = recovery_manager.discard_review_event(event)
        self.assertTrue(deleted)
        
        # Verify it's no longer in memory
        with recovery_manager._LOCK:
            self.assertEqual(len(recovery_manager._PENDING_EVENTS), 0)
            
        # Verify not on disk
        self.assertEqual(len(list(self.pending.glob("*.json"))), 0)


if __name__ == "__main__":
    unittest.main()
