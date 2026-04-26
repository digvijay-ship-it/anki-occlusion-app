import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import data_manager


class DirtyStoreTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)
        self.data_file = Path(self.tmpdir.name) / "anki_occlusion_data.json"

    def test_load_missing_file_returns_default_data(self):
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            loaded = store.load()

        self.assertEqual(loaded, {"decks": []})
        self.assertFalse(store.is_dirty())

    def test_load_invalid_json_falls_back_to_default(self):
        self.data_file.write_text("{bad json", encoding="utf-8")
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            loaded = store.load()

        self.assertEqual(loaded, {"decks": []})
        self.assertFalse(store.is_dirty())

    def test_save_if_dirty_writes_json_and_clears_dirty_flag(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 1, "name": "Biology"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store.set(payload)
            saved = store.save_if_dirty()

        self.assertTrue(saved)
        self.assertFalse(store.is_dirty())
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)

    def test_save_if_dirty_uses_snapshot_to_prevent_race_conditions(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 1, "name": "Biology"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            import copy
            store.set(copy.deepcopy(payload))

            original_write = store._write_to_disk
            def side_effect_write(data_snapshot):
                # Modify the in-memory data during the write to simulate a race condition
                store._data["decks"][0]["name"] = "Hacked"
                original_write(data_snapshot)

            with patch.object(store, "_write_to_disk", side_effect=side_effect_write):
                saved = store.save_if_dirty()

        self.assertTrue(saved)
        # Disk should have the original payload because a deep copy was used
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)
        # The in-memory data should be modified
        self.assertEqual(store._data["decks"][0]["name"], "Hacked")

    def test_save_force_writes_even_without_dirty_flag(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 2, "name": "Chemistry"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store._data = payload
            store.save_force()

        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)

    def test_save_force_uses_snapshot_to_prevent_race_conditions(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 2, "name": "Chemistry"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            import copy
            store._data = copy.deepcopy(payload)
            store._dirty = True

            original_write = store._write_to_disk
            def side_effect_write(data_snapshot):
                store._data["decks"][0]["name"] = "Hacked"
                original_write(data_snapshot)

            with patch.object(store, "_write_to_disk", side_effect=side_effect_write):
                store.save_force()

        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)


class WrapperAndHelperTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)
        self.data_file = Path(self.tmpdir.name) / "anki_occlusion_data.json"

    def test_load_data_and_save_data_wrappers_use_singleton_store(self):
        replacement_store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 4, "name": "Physics"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)), \
             patch.object(data_manager, "store", replacement_store):
            data_manager.save_data(payload)
            loaded = data_manager.load_data()

        self.assertEqual(loaded, payload)

    def test_find_deck_by_id_recurses_through_children(self):
        decks = [
            {"_id": 1, "name": "Root", "children": [
                {"_id": 2, "name": "Child", "children": []}
            ]}
        ]

        found = data_manager.find_deck_by_id(2, decks)

        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Child")

    def test_next_deck_id_returns_max_nested_plus_one(self):
        data = {
            "decks": [
                {"_id": 4, "children": [{"_id": 7, "children": []}]},
                {"_id": 6, "children": []},
            ]
        }

        self.assertEqual(data_manager.next_deck_id(data), 8)

    def test_new_box_id_returns_unique_uuid_strings(self):
        first = data_manager.new_box_id()
        second = data_manager.new_box_id()

        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 36)
        self.assertEqual(len(second), 36)


if __name__ == "__main__":
    unittest.main()
