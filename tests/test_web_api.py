import json
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_BACKEND = ROOT / "web" / "backend"
if str(WEB_BACKEND) not in sys.path:
    sys.path.insert(0, str(WEB_BACKEND))

from anki_web.main import create_app
from anki_web.schemas import RateRequest
from anki_web.commercial_store import CommercialWebStore
from anki_web.store import AnkiWebStore


class AnkiWebStoreTests(unittest.TestCase):
    def make_store(self, data):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        data_path = Path(tmpdir.name) / "anki_occlusion_data.json"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        return AnkiWebStore(data_path)

    def sample_data(self):
        tomorrow = datetime.combine(
            date.today() + timedelta(days=1), datetime.min.time()
        ).isoformat(timespec="seconds")
        return {
            "decks": [
                {
                    "_id": 1,
                    "name": "Math",
                    "cards": [
                        {
                            "_id": "card-1",
                            "title": "Integrals",
                            "pdf_path": "C:\\notes\\math.pdf",
                            "boxes": [
                                {
                                    "box_id": "box-1",
                                    "label": "formula",
                                    "rect": [10, 20, 100, 40],
                                    "shape": "ellipse",
                                    "angle": 15,
                                    "page_num": 2,
                                    "sched_state": "new",
                                    "sm2_last_quality": -1,
                                },
                                {
                                    "box_id": "box-2",
                                    "label": "future",
                                    "sched_state": "review",
                                    "sm2_last_quality": 4,
                                    "sm2_due": tomorrow,
                                },
                            ],
                        }
                    ],
                    "children": [
                        {
                            "_id": 2,
                            "name": "Algebra",
                            "cards": [
                                {
                                    "_id": "card-2",
                                    "title": "Matrices",
                                    "sched_state": "new",
                                    "sm2_last_quality": -1,
                                }
                            ],
                            "children": [],
                        }
                    ],
                }
            ]
        }

    def test_summary_counts_nested_decks_cards_and_due_items(self):
        store = self.make_store(self.sample_data())

        summary = store.summary()

        self.assertEqual(summary["deck_count"], 2)
        self.assertEqual(summary["card_count"], 2)
        self.assertEqual(summary["occlusion_count"], 2)
        self.assertEqual(summary["due_items"], 2)

    def test_deck_tree_includes_recursive_counts(self):
        store = self.make_store(self.sample_data())

        decks = store.list_decks()

        self.assertEqual(decks[0]["name"], "Math")
        self.assertEqual(decks[0]["direct_cards"], 1)
        self.assertEqual(decks[0]["total_cards"], 2)
        self.assertEqual(decks[0]["due_items"], 2)
        self.assertEqual(decks[0]["children"][0]["name"], "Algebra")

    def test_review_items_return_due_boxes_and_card_items(self):
        store = self.make_store(self.sample_data())

        items = store.review_items()

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["card_id"], "card-1")
        self.assertEqual(items[0]["box_id"], "box-1")
        self.assertEqual(items[0]["rect"], [10, 20, 100, 40])
        self.assertEqual(items[0]["shape"], "ellipse")
        self.assertEqual(items[0]["angle"], 15.0)
        self.assertEqual(items[0]["page_num"], 2)
        self.assertEqual(items[0]["pdf_path"], "C:\\notes\\math.pdf")
        self.assertEqual(len(items[0]["boxes"]), 2)
        self.assertEqual(items[0]["target_kind"], "box")
        self.assertEqual(items[0]["target_box_ids"], ["box-1"])
        self.assertEqual(items[0]["rating_previews"]["1"], "1m")
        self.assertEqual(items[0]["rating_previews"]["3"], "5m")
        self.assertEqual(items[0]["rating_previews"]["4"], "10m")
        self.assertIn("rating_previews", items[0]["boxes"][0])
        self.assertEqual(items[1]["card_id"], "card-2")
        self.assertIsNone(items[1]["box_id"])

    def test_review_items_can_be_filtered_to_one_deck(self):
        store = self.make_store(self.sample_data())

        items = store.review_items(deck_id=2)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["deck_name"], "Algebra")
        self.assertEqual(items[0]["card_id"], "card-2")

    def test_review_items_can_be_limited_to_control_payload_cost(self):
        store = self.make_store(self.sample_data())

        items = store.review_items(limit=1)

        self.assertEqual(len(items), 1)

    def test_rate_updates_target_box_and_saves_data(self):
        store = self.make_store(self.sample_data())

        result = store.rate(
            RateRequest(card_id="card-1", box_id="box-1", deck_id=1, quality=4)
        )

        saved = store.load()
        box = saved["decks"][0]["cards"][0]["boxes"][0]
        self.assertTrue(result["updated"])
        self.assertEqual(box["sm2_last_quality"], 4)
        self.assertGreaterEqual(box["reviews"], 1)
        self.assertIn(box["sched_state"], {"learning", "review"})
        self.assertEqual(box["last_quality"], 4)
        self.assertIn("reviewed_at", box)
        self.assertIn("last_reviewed_at", saved["decks"][0]["cards"][0])

    def test_review_rating_can_be_undone_and_redone(self):
        store = self.make_store(self.sample_data())
        original = deepcopy(store.load())

        rate_result = store.rate(
            RateRequest(card_id="card-1", box_id="box-1", deck_id=1, quality=4)
        )
        undo_result = store.undo_review_rating()
        undone = store.load()
        redo_result = store.redo_review_rating()
        redone = store.load()

        self.assertTrue(rate_result["can_undo"])
        self.assertTrue(undo_result["updated"])
        self.assertTrue(undo_result["can_redo"])
        self.assertEqual(undone, original)
        self.assertTrue(redo_result["updated"])
        self.assertEqual(
            redone["decks"][0]["cards"][0]["boxes"][0]["sm2_last_quality"],
            4,
        )

    def test_grouped_review_items_rate_all_sibling_boxes(self):
        data = {
            "decks": [
                {
                    "_id": 1,
                    "name": "Grouped",
                    "cards": [
                        {
                            "_id": "card-1",
                            "title": "Grouped masks",
                            "pdf_path": "C:\\notes\\grouped.pdf",
                            "boxes": [
                                {
                                    "box_id": "b1",
                                    "group_id": "g1",
                                    "rect": [10, 20, 100, 40],
                                    "sched_state": "new",
                                    "sm2_last_quality": -1,
                                },
                                {
                                    "box_id": "b2",
                                    "group_id": "g1",
                                    "rect": [150, 20, 100, 40],
                                    "sched_state": "new",
                                    "sm2_last_quality": -1,
                                },
                            ],
                        }
                    ],
                    "children": [],
                }
            ]
        }
        store = self.make_store(data)

        items = store.review_items()
        result = store.rate(
            RateRequest(card_id="card-1", deck_id=1, group_id="g1", quality=5)
        )

        saved_boxes = store.load()["decks"][0]["cards"][0]["boxes"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_kind"], "group")
        self.assertEqual(items[0]["target_box_ids"], ["b1", "b2"])
        self.assertTrue(result["updated"])
        self.assertEqual({box["last_quality"] for box in saved_boxes}, {5})
        self.assertEqual({box["sm2_last_quality"] for box in saved_boxes}, {5})

    def test_rate_returns_not_updated_for_missing_target(self):
        store = self.make_store(self.sample_data())

        result = store.rate(RateRequest(card_id="missing", deck_id=1, quality=4))

        self.assertFalse(result["updated"])
        self.assertEqual(result["target"], {})

    def test_create_app_registers_web_api_routes(self):
        app = create_app()
        paths = {route.path for route in app.routes}

        self.assertIn("/api/health", paths)
        self.assertIn("/api/me", paths)
        self.assertIn("/api/decks", paths)
        self.assertIn("/api/review/items", paths)
        self.assertIn("/api/review/rate", paths)
        self.assertIn("/api/review/undo", paths)
        self.assertIn("/api/review/redo", paths)
        self.assertIn("/api/media", paths)
        self.assertIn("/api/media/reveal", paths)
        self.assertIn("/api/sync/pull", paths)
        self.assertIn("/api/sync/push", paths)
        self.assertIn("/api/metrics/client", paths)
        self.assertIn("/api/metrics/cost", paths)


class CommercialWebStoreTests(unittest.TestCase):
    def make_store(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        return CommercialWebStore(Path(tmpdir.name) / "web.sqlite3")

    def test_dev_user_is_entitled_for_local_testing(self):
        store = self.make_store()

        user = store.ensure_dev_user("local-user")

        self.assertEqual(user["user_id"], "local-user")
        self.assertEqual(user["plan"], "dev")
        self.assertTrue(user["entitled"])

    def test_push_and_pull_revision_metadata(self):
        store = self.make_store()
        user = store.ensure_dev_user("sync-user")

        result = store.push_changes(
            user["user_id"],
            [
                {
                    "collection": "cards",
                    "item_id": "card-1",
                    "payload": {"title": "Integrals"},
                },
                {
                    "collection": "masks",
                    "item_id": "mask-1",
                    "payload": {"card_id": "card-1", "rect": [0, 0, 10, 10]},
                },
            ],
        )
        pulled = store.pull_changes(user["user_id"], since_revision=0)

        self.assertEqual(result["accepted"], 2)
        self.assertEqual(pulled["revision"], result["revision"])
        self.assertEqual([change["collection"] for change in pulled["changes"]], ["cards", "masks"])
        self.assertEqual(pulled["changes"][0]["payload"]["title"], "Integrals")

    def test_rejects_large_file_sync_collections(self):
        store = self.make_store()
        user = store.ensure_dev_user("sync-user")

        with self.assertRaises(ValueError):
            store.push_changes(
                user["user_id"],
                [
                    {
                        "collection": "files",
                        "item_id": "pdf-1",
                        "payload": {"name": "huge.pdf"},
                    }
                ],
            )

    def test_cost_snapshot_tracks_request_metrics(self):
        store = self.make_store()
        user = store.ensure_dev_user("metrics-user")

        store.record_request_metric(
            user_id=user["user_id"],
            method="POST",
            path="/api/sync/push",
            status_code=200,
            duration_ms=12.5,
            request_bytes=100,
            response_bytes=50,
            db_reads=1,
            db_writes=3,
        )
        snapshot = store.cost_snapshot(user["user_id"])

        self.assertEqual(snapshot["request_count"], 1)
        self.assertEqual(snapshot["request_bytes"], 100)
        self.assertEqual(snapshot["response_bytes"], 50)
        self.assertEqual(snapshot["db_reads"], 1)
        self.assertEqual(snapshot["db_writes"], 3)


if __name__ == "__main__":
    unittest.main()
