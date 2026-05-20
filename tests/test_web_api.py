import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_BACKEND = ROOT / "web" / "backend"
if str(WEB_BACKEND) not in sys.path:
    sys.path.insert(0, str(WEB_BACKEND))

from anki_web.main import create_app
from anki_web.schemas import RateRequest
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
                            "boxes": [
                                {
                                    "box_id": "box-1",
                                    "label": "formula",
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
        self.assertEqual(items[1]["card_id"], "card-2")
        self.assertIsNone(items[1]["box_id"])

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

    def test_create_app_registers_web_api_routes(self):
        app = create_app()
        paths = {route.path for route in app.routes}

        self.assertIn("/api/health", paths)
        self.assertIn("/api/decks", paths)
        self.assertIn("/api/review/items", paths)
        self.assertIn("/api/review/rate", paths)


if __name__ == "__main__":
    unittest.main()

