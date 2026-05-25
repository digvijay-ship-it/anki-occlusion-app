import json
import tempfile
import threading
import time
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
        data_manager._LAST_SAVE_BACKUP_TS_BY_FILE.clear()
        data_manager._SAVE_BACKUP_THROTTLE_LOGGED.clear()

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

    def test_load_accepts_utf8_bom_files(self):
        payload = {"decks": [{"_id": 1, "name": "Safe"}]}
        self.data_file.write_text(json.dumps(payload), encoding="utf-8-sig")
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            loaded = store.load()

        self.assertEqual(loaded, payload)
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

    def test_save_creates_timestamped_backup_before_replacing_existing_data(self):
        existing = {"decks": [{"_id": 1, "name": "Old"}]}
        payload = {"decks": [{"_id": 2, "name": "New"}]}
        self.data_file.write_text(json.dumps(existing), encoding="utf-8")
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store.set(payload)
            saved = store.save_if_dirty()

        backup_dir = self.data_file.parent / data_manager.BACKUP_DIR_NAME
        backups = list(backup_dir.glob("anki_occlusion_data.*.json"))
        self.assertTrue(saved)
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), existing)

    def test_save_backups_are_throttled_for_rapid_review_saves(self):
        existing = {"decks": [{"_id": 1, "name": "Old"}]}
        first_payload = {"decks": [{"_id": 2, "name": "First"}]}
        second_payload = {"decks": [{"_id": 3, "name": "Second"}]}
        self.data_file.write_text(json.dumps(existing), encoding="utf-8")
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store.set(first_payload)
            self.assertTrue(store.save_if_dirty())
            store.set(second_payload)
            self.assertTrue(store.save_if_dirty())

        backup_dir = self.data_file.parent / data_manager.BACKUP_DIR_NAME
        backups = list(backup_dir.glob("anki_occlusion_data.*.json"))
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), second_payload)
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), existing)

    def test_save_refuses_to_replace_non_empty_data_with_empty_decks(self):
        existing = {"decks": [{"_id": 1, "name": "Important"}]}
        payload = {"decks": []}
        self.data_file.write_text(json.dumps(existing), encoding="utf-8")
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store.set(payload)
            with self.assertRaises(RuntimeError):
                store.save_if_dirty()

        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), existing)
        self.assertTrue(store.is_dirty())

    def test_save_force_keeps_dirty_flag_when_protected_write_fails(self):
        existing = {"decks": [{"_id": 1, "name": "Important"}]}
        payload = {"decks": []}
        self.data_file.write_text(json.dumps(existing), encoding="utf-8")
        store = data_manager.DirtyStore()

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store._data = payload
            with self.assertRaises(RuntimeError):
                store.save_force()

        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), existing)
        self.assertTrue(store.is_dirty())

    def test_save_if_dirty_uses_snapshot_to_prevent_race_conditions(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 1, "name": "Biology"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            import copy
            store.set(copy.deepcopy(payload))

            original_write = store._write_serialized_to_disk
            def side_effect_write(serialized_snapshot, snapshot_summary):
                # Modify the in-memory data during the write to simulate a race condition
                store._data["decks"][0]["name"] = "Hacked"
                original_write(serialized_snapshot, snapshot_summary)

            with patch.object(store, "_write_serialized_to_disk", side_effect=side_effect_write):
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

    def test_atomic_replace_retries_transient_permission_error(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 2, "name": "Chemistry"}]}
        original_replace = data_manager.os.replace
        calls = []

        def flaky_replace(src, dst):
            calls.append((src, dst))
            if len(calls) == 1:
                raise PermissionError("file is briefly locked")
            return original_replace(src, dst)

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)), patch.object(
            data_manager.os, "replace", side_effect=flaky_replace
        ):
            store._data = payload
            store.save_force()

        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)

    def test_save_force_uses_snapshot_to_prevent_race_conditions(self):
        store = data_manager.DirtyStore()
        payload = {"decks": [{"_id": 2, "name": "Chemistry"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            import copy
            store._data = copy.deepcopy(payload)
            store._dirty = True

            original_write = store._write_serialized_to_disk
            def side_effect_write(serialized_snapshot, snapshot_summary):
                store._data["decks"][0]["name"] = "Hacked"
                original_write(serialized_snapshot, snapshot_summary)

            with patch.object(store, "_write_serialized_to_disk", side_effect=side_effect_write):
                store.save_force()

        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), payload)

    def test_newer_save_request_prevents_older_snapshot_from_writing_last(self):
        store = data_manager.DirtyStore()
        old_payload = {"decks": [{"_id": 1, "name": "Old"}]}
        new_payload = {"decks": [{"_id": 2, "name": "New"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store._write_lock.acquire()
            try:
                store.set(old_payload)
                old_done = []
                old_thread = threading.Thread(
                    target=lambda: old_done.append(store.save_if_dirty())
                )
                old_thread.start()

                deadline = time.time() + 2
                while store._latest_save_request_seq < 1 and time.time() < deadline:
                    time.sleep(0.01)
                self.assertEqual(store._latest_save_request_seq, 1)

                store.set(new_payload)
                force_thread = threading.Thread(target=store.save_force)
                force_thread.start()

                deadline = time.time() + 2
                while store._latest_save_request_seq < 2 and time.time() < deadline:
                    time.sleep(0.01)
                self.assertEqual(store._latest_save_request_seq, 2)
            finally:
                store._write_lock.release()

            old_thread.join(2)
            force_thread.join(2)

        self.assertEqual(old_done, [False])
        self.assertEqual(json.loads(self.data_file.read_text(encoding="utf-8")), new_payload)

    def test_save_soon_flushes_mutation_made_during_active_save(self):
        store = data_manager.DirtyStore()
        old_payload = {"decks": [{"_id": 1, "name": "Old"}]}
        new_payload = {"decks": [{"_id": 2, "name": "New"}]}

        with patch.object(data_manager, "DATA_FILE", str(self.data_file)):
            store._write_lock.acquire()
            try:
                store.set(old_payload)
                self.assertTrue(store.save_soon(min_interval=0.0))

                deadline = time.time() + 2
                while store._latest_save_request_seq < 1 and time.time() < deadline:
                    time.sleep(0.01)
                self.assertEqual(store._latest_save_request_seq, 1)

                store.set(new_payload)
                self.assertTrue(store.save_soon(min_interval=0.0))
            finally:
                store._write_lock.release()

            deadline = time.time() + 2
            while time.time() < deadline:
                if self.data_file.exists():
                    try:
                        saved = json.loads(self.data_file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        saved = None
                    if saved == new_payload:
                        break
                time.sleep(0.01)
            else:
                self.fail("save_soon did not flush the trailing dirty payload")

        self.assertFalse(store.is_dirty())

    def test_save_soon_can_delay_background_save_from_now(self):
        store = data_manager.DirtyStore()
        store.set({"decks": [{"_id": 1, "name": "Review"}]})
        store._last_async_save_ts = time.monotonic() - 120.0

        with patch.object(store, "_schedule_save_timer_locked") as schedule_timer, \
             patch.object(store, "_start_save_thread_locked") as start_thread:
            self.assertTrue(store.save_soon(min_interval=8.0, delay_from_now=True))

        schedule_timer.assert_called_once_with(8.0)
        start_thread.assert_not_called()
        self.assertTrue(store.is_dirty())


class WrapperAndHelperTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(exist_ok=True)
        self.tmpdir = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(self.tmpdir.cleanup)
        self.data_file = Path(self.tmpdir.name) / "anki_occlusion_data.json"
        data_manager._LAST_SAVE_BACKUP_TS_BY_FILE.clear()
        data_manager._SAVE_BACKUP_THROTTLE_LOGGED.clear()

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


class DeckHistoryTests(unittest.TestCase):
    def test_undo_restores_snapshot_even_after_source_dict_is_mutated(self):
        history = data_manager._DeckHistory()
        store = data_manager.DirtyStore()
        data = {"decks": [{"_id": 1, "name": "Alpha"}]}

        store.set(data)
        history.push(store.get())
        data["decks"][0]["name"] = "Beta"
        store.set(data)

        restored = history.undo(store)

        self.assertTrue(restored)
        self.assertEqual(store.get()["decks"][0]["name"], "Alpha")

    def test_redo_restores_forward_snapshot_after_undo(self):
        history = data_manager._DeckHistory()
        store = data_manager.DirtyStore()
        original = {"decks": [{"_id": 1, "name": "Alpha"}]}
        updated = {"decks": [{"_id": 1, "name": "Beta"}]}

        store.set(original)
        history.push(store.get())
        store.set(updated)
        history.undo(store)

        redone = history.redo(store)

        self.assertTrue(redone)
        self.assertEqual(store.get()["decks"][0]["name"], "Beta")


if __name__ == "__main__":
    unittest.main()
