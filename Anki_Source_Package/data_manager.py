# -*- coding: utf-8 -*-
import os
import json
import tempfile
import uuid
import threading
import time
import shutil
import sqlite3
from datetime import datetime
from perf_utils import trace_perf


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
def is_running_tests() -> bool:
    import sys
    if os.environ.get("ANKI_TESTING") == "1":
        return True
    if not sys.argv:
        return False
    main_script = sys.argv[0].replace("\\", "/").lower()
    main_basename = os.path.basename(main_script)
    parts = main_script.split("/")
    if "unittest" in main_script or "pytest" in main_script:
        return True
    if "tests" in parts or "test" in parts:
        if main_basename.startswith("test_") or main_basename.endswith("_test.py") or "tests" in parts:
            return True
    return False

_TEST_TEMP_DIR = None
def _get_test_temp_dir() -> str:
    global _TEST_TEMP_DIR
    if _TEST_TEMP_DIR is None:
        import tempfile
        _TEST_TEMP_DIR = tempfile.TemporaryDirectory()
    return _TEST_TEMP_DIR.name

if is_running_tests():
    DATA_FILE = os.path.join(_get_test_temp_dir(), "anki_occlusion_data_test.db")
else:
    DATA_FILE = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.db")
AUTO_SAVE_INTERVAL = 60  # seconds
BACKUP_DIR_NAME = "anki_occlusion_data.backups"
MAX_SAVE_BACKUPS = 50
SAVE_BACKUP_MIN_INTERVAL = 300.0
SAVE_BACKUP_INTERVAL_ENV = "ANKI_SAVE_BACKUP_MIN_INTERVAL"
_LAST_SAVE_BACKUP_TS_BY_FILE = {}
_SAVE_BACKUP_THROTTLE_LOGGED = set()


# ═══════════════════════════════════════════════════════════════════════════════
#  DirtyStore
# ═══════════════════════════════════════════════════════════════════════════════
class DirtyStore:
    """
    Single source of truth for app data + dirty flag.

    Typical usage:
        store.load()              # on app start
        store.start_autosave()    # begin background thread

        store.mark_dirty()        # after any in-place mutation
        store.get()               # read current data

        store.stop_autosave()     # on app exit (triggers final save)
    """

    def __init__(self):
        self._data = {"decks": []}
        self._dirty = False
        self.revision = 0
        self._lock = threading.Lock()
        self._auto_thread = None
        self._stop_event = threading.Event()
        self._save_thread = None
        self._save_thread_lock = threading.Lock()
        self._save_timer = None
        self._write_lock = threading.Lock()
        self._save_seq = 0
        self._latest_save_request_seq = 0
        self._last_async_save_ts = 0.0
        self._card_index = {}
        self._sqlite_initialized_paths = set()

    # ── Load / Get / Set ──────────────────────────────────────────────────────

    def _rebuild_card_index(self) -> None:
        new_index = {}
        def _walk(decks):
            for deck in decks or []:
                if not isinstance(deck, dict):
                    continue
                for card in deck.get("cards", []) or []:
                    if isinstance(card, dict):
                        c_id = card.get("_id")
                        if c_id is not None:
                            try:
                                c_id = int(c_id)
                            except (ValueError, TypeError):
                                pass
                            new_index[c_id] = (card, deck)
                children = deck.get("children", []) or deck.get("subdecks", []) or []
                _walk(children)
        _walk(self._data.get("decks", []))
        self._card_index = new_index

    def get_card_by_id(self, card_id) -> tuple:
        if card_id is None:
            return None, None
        try:
            card_id = int(card_id)
        except (ValueError, TypeError):
            pass
        with self._lock:
            if not hasattr(self, "_card_index") or self._card_index is None:
                self._rebuild_card_index()
            return self._card_index.get(card_id, (None, None))

    def _initialize_sm2_states(self, data):
        if not isinstance(data, dict):
            return
        try:
            from sm2_engine import sched_init
            def _walk(decks):
                for deck in decks or []:
                    if not isinstance(deck, dict):
                        continue
                    for card in deck.get("cards", []) or []:
                        if isinstance(card, dict):
                            sched_init(card)
                            for box in card.get("boxes", []) or []:
                                if isinstance(box, dict):
                                    sched_init(box)
                    children = deck.get("children", []) or deck.get("subdecks", []) or []
                    _walk(children)
            _walk(data.get("decks", []))
        except Exception as e:
            print(f"[DEBUG][data_manager] SM2 state initialization failed: {e}")

    def _get_db_path(self):
        if DATA_FILE.endswith(".json"):
            return DATA_FILE[:-5] + ".db"
        return DATA_FILE

    def _get_legacy_json_path(self):
        if DATA_FILE.endswith(".db"):
            return DATA_FILE[:-3] + ".json"
        return DATA_FILE

    def _is_db_empty(self, db_path):
        if not os.path.exists(db_path):
            return True
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM decks;")
            count = cursor.fetchone()[0]
            conn.close()
            return count == 0
        except Exception:
            return True

    def _init_sqlite(self, db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS decks (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id INTEGER REFERENCES decks(id) ON DELETE CASCADE,
            meta TEXT
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER REFERENCES decks(id) ON DELETE CASCADE,
            pdf_path TEXT,
            image_path TEXT,
            pdf_box_render_zoom REAL,
            due TEXT,
            interval INTEGER,
            factor REAL,
            reps INTEGER,
            lapses INTEGER,
            state INTEGER,
            meta TEXT
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS boxes (
            box_id TEXT PRIMARY KEY,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            rect_x REAL,
            rect_y REAL,
            rect_w REAL,
            rect_h REAL,
            page_num INTEGER,
            group_id TEXT,
            shape TEXT,
            angle REAL,
            due TEXT,
            interval INTEGER,
            factor REAL,
            reps INTEGER,
            lapses INTEGER,
            state INTEGER,
            meta TEXT
        );
        """)
        conn.commit()
        conn.close()

    def _save_to_sqlite(self, db_path, data):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF;")
        try:
            cursor.execute("BEGIN TRANSACTION;")
            
            # --- 1. Reconcile Settings ---
            active_settings_keys = [k for k in data.keys() if k != "decks"]
            if active_settings_keys:
                placeholders = ",".join("?" for _ in active_settings_keys)
                cursor.execute(f"DELETE FROM settings WHERE key NOT IN ({placeholders});", active_settings_keys)
            else:
                cursor.execute("DELETE FROM settings;")
                
            for key in active_settings_keys:
                val_str = json.dumps(data[key], ensure_ascii=False)
                cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);", (key, val_str))
                
            # --- 2. Walk Tree and Gather Active and New Entities ---
            active_deck_ids = []
            active_card_ids = []
            active_box_ids = []
            
            decks_to_save = []
            cards_to_save = []
            boxes_to_save = []
            
            def collect_active(deck, parent_id=None):
                deck_id = deck.get("_id")
                if deck_id is not None:
                    active_deck_ids.append(deck_id)
                    decks_to_save.append((deck, parent_id))
                    
                for card in deck.get("cards", []) or []:
                    card_id = card.get("_id")
                    is_valid_id = False
                    if card_id is not None and card_id != "":
                        try:
                            card_id = int(card_id)
                            is_valid_id = True
                        except ValueError:
                            pass
                    
                    if is_valid_id:
                        active_card_ids.append(card_id)
                        
                    cards_to_save.append((card, is_valid_id, card_id, deck_id))
                    
                    for box in card.get("boxes", []) or []:
                        box_id = box.get("box_id")
                        if box_id:
                            active_box_ids.append(box_id)
                            boxes_to_save.append((box, box_id, card))
                            
                children = deck.get("children", []) or deck.get("subdecks", []) or []
                for child in children:
                    collect_active(child, deck_id)
                    
            for d in data.get("decks", []) or []:
                collect_active(d, None)
                
            # --- 3. Upsert Active Decks ---
            for deck, parent_id in decks_to_save:
                deck_id = deck.get("_id")
                name = deck.get("name", "")
                meta_dict = {k: v for k, v in deck.items() if k not in ["_id", "name", "cards", "children", "subdecks"]}
                meta_str = json.dumps(meta_dict, ensure_ascii=False) if meta_dict else None
                cursor.execute("INSERT OR REPLACE INTO decks (id, name, parent_id, meta) VALUES (?, ?, ?, ?);",
                               (deck_id, name, parent_id, meta_str))
                               
            # --- 4. Upsert Active and New Cards ---
            for card, is_valid_id, card_id, deck_id in cards_to_save:
                pdf_path = card.get("pdf_path")
                image_path = card.get("image_path")
                zoom = card.get("_pdf_box_render_zoom")
                due = card.get("due")
                interval = card.get("interval")
                factor = card.get("factor")
                reps = card.get("reps")
                lapses = card.get("lapses")
                state = card.get("state")
                
                meta_card = {k: v for k, v in card.items() if k not in [
                    "pdf_path", "image_path", "_pdf_box_render_zoom", "_id", "boxes",
                    "due", "interval", "factor", "reps", "lapses", "state"
                ]}
                meta_card_str = json.dumps(meta_card, ensure_ascii=False) if meta_card else None
                
                if is_valid_id:
                    cursor.execute("""
                    INSERT OR REPLACE INTO cards (id, deck_id, pdf_path, image_path, pdf_box_render_zoom,
                                       due, interval, factor, reps, lapses, state, meta)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (card_id, deck_id, pdf_path, image_path, zoom, due, interval, factor, reps, lapses, state, meta_card_str))
                else:
                    cursor.execute("""
                    INSERT INTO cards (deck_id, pdf_path, image_path, pdf_box_render_zoom,
                                       due, interval, factor, reps, lapses, state, meta)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (deck_id, pdf_path, image_path, zoom, due, interval, factor, reps, lapses, state, meta_card_str))
                    card_id = cursor.lastrowid
                    card["_id"] = card_id
                    active_card_ids.append(card_id)
                    
            # --- 5. Upsert Active Boxes ---
            for box, box_id, card in boxes_to_save:
                # Retrieve the newly generated or resolved card ID
                card_id = card.get("_id")
                try:
                    card_id = int(card_id)
                except (ValueError, TypeError):
                    continue
                    
                rect = list(box.get("rect") or [0, 0, 0, 0])
                if len(rect) < 4:
                    rect = rect + [0] * (4 - len(rect))
                rect = rect[:4]
                rect_x, rect_y, rect_w, rect_h = rect[0], rect[1], rect[2], rect[3]
                page_num = box.get("page_num", 0)
                group_id = box.get("group_id")
                shape = box.get("shape", "rect")
                angle = box.get("angle", 0.0)
                b_due = box.get("due")
                b_interval = box.get("interval")
                b_factor = box.get("factor")
                b_reps = box.get("reps")
                b_lapses = box.get("lapses")
                b_state = box.get("state")
                
                meta_box = {k: v for k, v in box.items() if k not in [
                    "box_id", "rect", "page_num", "group_id", "shape", "angle",
                    "due", "interval", "factor", "reps", "lapses", "state"
                ]}
                meta_box_str = json.dumps(meta_box, ensure_ascii=False) if meta_box else None
                
                cursor.execute("""
                INSERT OR REPLACE INTO boxes (box_id, card_id, rect_x, rect_y, rect_w, rect_h, page_num,
                                             group_id, shape, angle, due, interval, factor, reps, lapses, state, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (box_id, card_id, rect_x, rect_y, rect_w, rect_h, page_num,
                      group_id, shape, angle, b_due, b_interval, b_factor, b_reps, b_lapses, b_state, meta_box_str))
                      
            # --- 6. Bulk Delete Stale Entities ---
            # Avoid SQLite parameterized NOT IN variable limit crashes (max 999 host parameters)
            # by fetching current database IDs, calculating stale ones via set difference in Python,
            # and executing chunked deletes in safe batches of 500.
            cursor.execute("SELECT box_id FROM boxes;")
            db_box_ids = {row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT id FROM cards;")
            db_card_ids = {row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT id FROM decks;")
            db_deck_ids = {row[0] for row in cursor.fetchall()}

            stale_box_ids = list(db_box_ids - set(active_box_ids))
            stale_card_ids = list(db_card_ids - set(active_card_ids))
            stale_deck_ids = list(db_deck_ids - set(active_deck_ids))

            if stale_box_ids:
                for i in range(0, len(stale_box_ids), 500):
                    chunk = stale_box_ids[i:i+500]
                    placeholders = ",".join("?" for _ in chunk)
                    cursor.execute(f"DELETE FROM boxes WHERE box_id IN ({placeholders});", chunk)

            if stale_card_ids:
                for i in range(0, len(stale_card_ids), 500):
                    chunk = stale_card_ids[i:i+500]
                    placeholders = ",".join("?" for _ in chunk)
                    cursor.execute(f"DELETE FROM cards WHERE id IN ({placeholders});", chunk)

            if stale_deck_ids:
                for i in range(0, len(stale_deck_ids), 500):
                    chunk = stale_deck_ids[i:i+500]
                    placeholders = ",".join("?" for _ in chunk)
                    cursor.execute(f"DELETE FROM decks WHERE id IN ({placeholders});", chunk)
                
            conn.commit()
            with self._lock:
                self._rebuild_card_index()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @trace_perf
    def _load_from_sqlite(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT key, value FROM settings")
        settings_dict = {}
        for row in cursor.fetchall():
            try:
                settings_dict[row["key"]] = json.loads(row["value"])
            except Exception:
                settings_dict[row["key"]] = row["value"]
                
        cursor.execute("SELECT id, name, parent_id, meta FROM decks")
        decks_rows = cursor.fetchall()
        decks_by_id = {}
        for row in decks_rows:
            meta_val = row["meta"]
            deck = {
                "_id": row["id"],
                "name": row["name"],
                "cards": [],
                "children": []
            }
            if meta_val:
                try:
                    deck.update(json.loads(meta_val))
                except Exception:
                    pass
            decks_by_id[row["id"]] = (deck, row["parent_id"])
            
        cursor.execute("""
        SELECT id, deck_id, pdf_path, image_path, pdf_box_render_zoom,
               due, interval, factor, reps, lapses, state, meta 
        FROM cards
        """)
        cards_rows = cursor.fetchall()
        cards_by_id = {}
        for row in cards_rows:
            meta_val = row["meta"]
            card = {
                "pdf_path": row["pdf_path"],
                "image_path": row["image_path"],
                "_pdf_box_render_zoom": row["pdf_box_render_zoom"],
                "boxes": []
            }
            if meta_val:
                try:
                    card.update(json.loads(meta_val))
                except Exception:
                    pass
            for field in ["due", "interval", "factor", "reps", "lapses", "state"]:
                if row[field] is not None:
                    card[field] = row[field]
            # Ensure permanent card_uid is tracked
            c_uid = card.get("card_uid") or (card.get("_id") if isinstance(card.get("_id"), str) else None)
            if c_uid:
                card["card_uid"] = c_uid
            card["_id"] = row["id"]
            cards_by_id[row["id"]] = card
            
            deck_id = row["deck_id"]
            if deck_id in decks_by_id:
                decks_by_id[deck_id][0]["cards"].append(card)
                
        cursor.execute("""
        SELECT box_id, card_id, rect_x, rect_y, rect_w, rect_h, page_num,
               group_id, shape, angle, due, interval, factor, reps, lapses, state, meta
        FROM boxes
        """)
        boxes_rows = cursor.fetchall()
        for row in boxes_rows:
            meta_val = row["meta"]
            box = {
                "box_id": row["box_id"],
                "rect": [row["rect_x"], row["rect_y"], row["rect_w"], row["rect_h"]],
                "page_num": row["page_num"],
                "group_id": row["group_id"],
                "shape": row["shape"],
                "angle": row["angle"]
            }
            if meta_val:
                try:
                    box.update(json.loads(meta_val))
                except Exception:
                    pass
            for field in ["due", "interval", "factor", "reps", "lapses", "state"]:
                if row[field] is not None:
                    box[field] = row[field]
            card_id = row["card_id"]
            if card_id in cards_by_id:
                cards_by_id[card_id]["boxes"].append(box)
                
        conn.close()
        
        root_decks = []
        for deck, parent_id in decks_by_id.values():
            if parent_id is None or parent_id not in decks_by_id:
                root_decks.append(deck)
            else:
                decks_by_id[parent_id][0]["children"].append(deck)
                
        data = {"decks": root_decks}
        data.update(settings_dict)
        return data

    def _backup_db_file(self, db_path):
        if not os.path.exists(db_path):
            return None
        key = DirtyStore._backup_throttle_key(db_path)
        now = time.monotonic()
        min_interval = DirtyStore._save_backup_min_interval()
        last_backup_ts = _LAST_SAVE_BACKUP_TS_BY_FILE.get(key)
        if (
            min_interval > 0
            and last_backup_ts is not None
            and now - last_backup_ts < min_interval
        ):
            return None
        backup_dir = DirtyStore._backup_dir_for(db_path)
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"anki_occlusion_data.{stamp}.db")
        counter = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(
                backup_dir, f"anki_occlusion_data.{stamp}_{counter}.db"
            )
            counter += 1
        shutil.copy2(db_path, backup_path)
        _LAST_SAVE_BACKUP_TS_BY_FILE[key] = now
        DirtyStore._prune_backups_db(backup_dir)
        return backup_path

    @staticmethod
    def _prune_backups_db(backup_dir):
        try:
            backups = [
                os.path.join(backup_dir, name)
                for name in os.listdir(backup_dir)
                if name.startswith("anki_occlusion_data.") and name.endswith(".db")
            ]
            backups.sort(key=lambda path: os.path.getmtime(path), reverse=True)
            for old_path in backups[MAX_SAVE_BACKUPS:]:
                try:
                    os.unlink(old_path)
                except Exception:
                    pass
        except Exception:
            pass

    @trace_perf
    def load(self):
        """Load from disk. Clears dirty flag."""
        db_path = self._get_db_path()
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        self._init_sqlite(db_path)
        self._sqlite_initialized_paths.add(db_path)
        
        # Check if we should migrate legacy JSON
        legacy_json_path = self._get_legacy_json_path()
        if self._is_db_empty(db_path) and os.path.exists(legacy_json_path):
            try:
                print(f"[DEBUG][data_manager] Migrating legacy JSON to SQLite: {legacy_json_path}")
                with open(legacy_json_path, "r", encoding="utf-8-sig") as f:
                    legacy_data = json.load(f)
                if legacy_data and isinstance(legacy_data, dict):
                    self._save_to_sqlite(db_path, legacy_data)
                    print("[DEBUG][data_manager] Legacy JSON migration completed successfully.")
            except Exception as e:
                print(f"[DEBUG][data_manager] Legacy JSON migration failed: {e}")
                
        try:
            if DATA_FILE.endswith(".json") and os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8-sig") as f:
                    self._data = json.load(f)
            else:
                self._data = self._load_from_sqlite(db_path)
        except Exception as e:
            print(f"[DEBUG][data_safety] load_failed using_empty_default: {e}")
            self._data = {"decks": []}
            
        self._initialize_sm2_states(self._data)
        from ui.settings_proxy import SettingsProxyDict
        self._data = SettingsProxyDict(self._data)
        with self._lock:
            self._dirty = False
            self.revision += 1
            self._rebuild_card_index()
        return self._data

    def get(self):
        """Return current in-memory data dict."""
        return self._data

    def set(self, data):
        """Replace entire data dict and mark dirty."""
        self._initialize_sm2_states(data)
        from ui.settings_proxy import SettingsProxyDict
        with self._lock:
            self._data = SettingsProxyDict(data) if not isinstance(data, SettingsProxyDict) else data
            self._dirty = True
            self.revision += 1
            self._rebuild_card_index()

    # ── Dirty flag ────────────────────────────────────────────────────────────

    def mark_dirty(self):
        """Call after any in-place mutation of data."""
        with self._lock:
            self._dirty = True
            self.revision += 1

    def is_dirty(self):
        return self._dirty

    def save_if_dirty(self, force_gdrive=False):
        """
        Write to disk only if dirty.
        Returns True if save happened, False if skipped.
        """
        with self._lock:
            if not self._dirty:
                return False
            self._save_seq += 1
            save_seq = self._save_seq
            self._latest_save_request_seq = save_seq
            self._dirty = False
        try:
            return self._write_snapshot_to_disk(save_seq, force_gdrive=force_gdrive)
        except Exception:
            with self._lock:
                self._dirty = True
            raise

    def save_force(self, async_save=False, force_gdrive=True):
        """Force write regardless of dirty flag (use on app exit, or async in UI)."""
        with self._lock:
            self._save_seq += 1
            save_seq = self._save_seq
            self._latest_save_request_seq = save_seq
            self._dirty = False

        if async_save:
            def _bg_write():
                try:
                    self._write_snapshot_to_disk(save_seq, force_gdrive=force_gdrive)
                except Exception as e:
                    print(f"[data_manager] Async save_force failed: {e}")
                    with self._lock:
                        self._dirty = True
            threading.Thread(target=_bg_write, daemon=True, name="DirtyStore-AsyncSaveForce").start()
        else:
            try:
                return self._write_snapshot_to_disk(save_seq, force_gdrive=force_gdrive)
            except Exception:
                with self._lock:
                    self._dirty = True
                raise

    def _write_snapshot_to_disk(self, save_seq, force_gdrive=False):
        with self._write_lock:
            with self._lock:
                if save_seq < self._latest_save_request_seq:
                    return False
                data_str = json.dumps(self._data)
            
            data_snapshot = json.loads(data_str)
            
            db_path = self._get_db_path()
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
                
            if db_path not in self._sqlite_initialized_paths:
                self._init_sqlite(db_path)
                self._sqlite_initialized_paths.add(db_path)

            # Perform SQLite backup if needed
            self._backup_db_file(db_path)
            
            # Save data to SQLite
            self._save_to_sqlite(db_path, data_snapshot)
            
            # JSON Compatibility Mode
            if DATA_FILE.endswith(".json"):
                indent_val = 2 if os.environ.get("ANKI_PRETTY_JSON") == "1" else None
                snapshot_text = json.dumps(data_snapshot, ensure_ascii=False, indent=indent_val)
                snapshot_summary = DirtyStore._data_summary(data_snapshot)
                self._write_serialized_to_disk(snapshot_text, snapshot_summary)
                
            # Asynchronous Google Drive Sync (Runs in a background thread)
            try:
                from services.gdrive_service import gdrive_store
                if gdrive_store.is_linked() and force_gdrive:
                    def _bg_upload():
                        try:
                            gdrive_store.upload_file_to_drive(db_path)
                            if DATA_FILE.endswith(".json") and os.path.exists(DATA_FILE):
                                gdrive_store.upload_file_to_drive(DATA_FILE)
                        except Exception as ex:
                            print(f"[data_manager] GDrive background upload failed: {ex}")
                    
                    threading.Thread(target=_bg_upload, daemon=True, name="GDrive-AutoSync").start()
            except Exception as e:
                print(f"[data_manager] Failed to initialize GDrive sync: {e}")
                
            return True

    def save_soon(self, min_interval: float = 3.0, delay_from_now: bool = False):
        """
        Schedule a background save without blocking the UI thread.
        Rapid repeated calls are coalesced, but a trailing save is kept so the
        newest dirty data is not stranded in RAM if another save is in flight.
        Set delay_from_now for flows that already have their own immediate
        checkpoint and should keep disk writes away from the current UI action.
        """
        now = time.monotonic()
        with self._lock:
            if not self._dirty:
                return False
            min_interval = float(min_interval)
            if delay_from_now:
                delay = max(0.0, min_interval)
            else:
                delay = max(0.0, min_interval - (now - self._last_async_save_ts))

        with self._save_thread_lock:
            if self._save_thread and self._save_thread.is_alive():
                self._schedule_save_timer_locked(delay)
                print(
                    f"[DEBUG][data_save] save_soon_trailing delay={delay:.2f}s"
                )
                return True
            if delay > 0:
                self._schedule_save_timer_locked(delay)
                print(f"[DEBUG][data_save] save_soon_delayed delay={delay:.2f}s")
                return True
            self._last_async_save_ts = now
            self._start_save_thread_locked()
        print("[DEBUG][data_save] save_soon_started")
        return True

    def _start_save_thread_locked(self):
        self._save_thread = threading.Thread(
            target=self._save_soon_worker, daemon=True, name="DirtyStore-SaveSoon"
        )
        self._save_thread.start()

    def _save_soon_worker(self):
        try:
            self.save_if_dirty()
        except Exception as e:
            print(f"[DEBUG][data_save] save_soon_worker notice: {e}")
            with self._lock:
                self._dirty = True
        finally:
            with self._save_thread_lock:
                self._save_thread = None
                with self._lock:
                    needs_trailing_save = self._dirty
                if needs_trailing_save:
                    self._last_async_save_ts = time.monotonic()
                    self._start_save_thread_locked()
                    print("[DEBUG][data_save] save_soon_followup_started")

    def _schedule_save_timer_locked(self, delay: float):
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(max(0.0, delay), self._save_timer_fired)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _save_timer_fired(self):
        with self._save_thread_lock:
            self._save_timer = None
            with self._lock:
                if not self._dirty:
                    return
            if self._save_thread and self._save_thread.is_alive():
                self._schedule_save_timer_locked(0.25)
                return
            self._last_async_save_ts = time.monotonic()
            self._start_save_thread_locked()
        print("[DEBUG][data_save] save_soon_timer_started")

    # ── Auto-save background thread ───────────────────────────────────────────

    def start_autosave(self, interval: int = AUTO_SAVE_INTERVAL):
        """Start background thread - disabled by default to prevent excessive saves."""
        return

    def stop_autosave(self):
        """Stop background thread + final force save. Call on app shutdown."""
        self._stop_event.set()
        with self._save_thread_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self.save_force()

    def _autosave_loop(self, interval):
        while not self._stop_event.wait(interval):
            saved = self.save_if_dirty()
            if saved:
                print(f"[AutoSave] Saved at {time.strftime('%H:%M:%S')}")

    # ── Atomic write + local safety backups ───────────────────────────────────

    @staticmethod
    def _write_serialized_to_disk(serialized_text, new_summary):
        dir_ = os.path.dirname(DATA_FILE) or "."
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized_text)
                f.flush()
                os.fsync(f.fileno())

            DirtyStore._validate_saved_json(tmp)
            existing_data = DirtyStore._read_json_file(DATA_FILE)
            existing_summary = DirtyStore._data_summary(existing_data)
            if existing_summary["decks"] > 0 and new_summary["decks"] == 0:
                print(
                    "[DEBUG][data_safety] refused_empty_overwrite "
                    f"existing_decks={existing_summary['decks']} "
                    f"new_decks={new_summary['decks']}"
                )
                raise RuntimeError(
                    "Refusing to overwrite non-empty Anki Occlusion data with an empty deck list."
                )

            backup_path = DirtyStore._backup_existing_file(DATA_FILE, existing_data)
            DirtyStore._replace_file_with_retry(tmp, DATA_FILE)
            backup_name = os.path.basename(backup_path) if backup_path else "none"
            print(
                "[DEBUG][data_save] saved "
                f"decks={new_summary['decks']} cards={new_summary['cards']} "
                f"boxes={new_summary['boxes']} backup={backup_name}"
            )
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise

    @staticmethod
    def _write_to_disk(data):
        db_path = DATA_FILE[:-5] + ".db" if DATA_FILE.endswith(".json") else DATA_FILE
        store = DirtyStore()
        store._init_sqlite(db_path)
        store._sqlite_initialized_paths.add(db_path)
        store._save_to_sqlite(db_path, data)
        if DATA_FILE.endswith(".json"):
            indent_val = 2 if os.environ.get("ANKI_PRETTY_JSON") == "1" else None
            serialized_text = json.dumps(data, ensure_ascii=False, indent=indent_val)
            new_summary = DirtyStore._data_summary(data)
            DirtyStore._write_serialized_to_disk(serialized_text, new_summary)

    @staticmethod
    def _replace_file_with_retry(src, dst, attempts=20, delay=0.1):
        for attempt in range(attempts):
            try:
                os.replace(src, dst)
                return
            except (PermissionError, OSError) as e:
                if attempt == attempts - 1:
                    # Final fallback on Windows: try direct copy/overwrite if os.replace fails
                    try:
                        import shutil
                        shutil.copyfile(src, dst)
                        try:
                            os.unlink(src)
                        except Exception:
                            pass
                        return
                    except Exception:
                        raise e
                time.sleep(delay * (1 + attempt * 0.4))

    @staticmethod
    def _read_json_file(path):
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _validate_saved_json(path):
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict) or not isinstance(
            loaded.get("decks", []), list
        ):
            raise ValueError("Saved data must be a JSON object with a deck list.")

    @staticmethod
    def _backup_dir_for(data_file):
        try:
            from storage_paths import current_backup_dir, current_data_file

            normalized = os.path.normcase(os.path.normpath(data_file or ""))
            current = os.path.normcase(os.path.normpath(current_data_file()))
            if normalized == current:
                return current_backup_dir()
        except Exception:
            pass
        return os.path.join(os.path.dirname(data_file) or ".", BACKUP_DIR_NAME)

    @staticmethod
    def _backup_existing_file(data_file, existing_data=None):
        if not os.path.exists(data_file):
            return None
        key = DirtyStore._backup_throttle_key(data_file)
        now = time.monotonic()
        min_interval = DirtyStore._save_backup_min_interval()
        last_backup_ts = _LAST_SAVE_BACKUP_TS_BY_FILE.get(key)
        if (
            min_interval > 0
            and last_backup_ts is not None
            and now - last_backup_ts < min_interval
        ):
            if key not in _SAVE_BACKUP_THROTTLE_LOGGED:
                print(
                    "[DEBUG][data_backup] throttled_recent "
                    f"min_interval={min_interval:.0f}s"
                )
                _SAVE_BACKUP_THROTTLE_LOGGED.add(key)
            return None
        backup_dir = DirtyStore._backup_dir_for(data_file)
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"anki_occlusion_data.{stamp}.json")
        counter = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(
                backup_dir, f"anki_occlusion_data.{stamp}_{counter}.json"
            )
            counter += 1

        shutil.copy2(data_file, backup_path)
        summary = DirtyStore._data_summary(existing_data)
        print(
            "[DEBUG][data_backup] created "
            f"{os.path.basename(backup_path)} decks={summary['decks']} "
            f"cards={summary['cards']} boxes={summary['boxes']}"
        )
        _LAST_SAVE_BACKUP_TS_BY_FILE[key] = now
        _SAVE_BACKUP_THROTTLE_LOGGED.discard(key)
        DirtyStore._prune_backups(backup_dir)
        return backup_path

    @staticmethod
    def _backup_throttle_key(data_file):
        return os.path.normcase(os.path.abspath(os.path.normpath(data_file or "")))

    @staticmethod
    def _save_backup_min_interval():
        raw = os.environ.get(SAVE_BACKUP_INTERVAL_ENV, "").strip()
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                pass
        return max(0.0, float(SAVE_BACKUP_MIN_INTERVAL))

    @staticmethod
    def _prune_backups(backup_dir):
        try:
            backups = [
                os.path.join(backup_dir, name)
                for name in os.listdir(backup_dir)
                if name.startswith("anki_occlusion_data.") and name.endswith(".json")
            ]
            backups.sort(key=lambda path: os.path.getmtime(path), reverse=True)
            for old_path in backups[MAX_SAVE_BACKUPS:]:
                try:
                    os.unlink(old_path)
                    print(f"[DEBUG][data_backup] pruned {os.path.basename(old_path)}")
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def _is_dangerous_empty_overwrite(existing_data, new_data):
        existing_summary = DirtyStore._data_summary(existing_data)
        new_summary = DirtyStore._data_summary(new_data)
        return existing_summary["decks"] > 0 and new_summary["decks"] == 0

    @staticmethod
    def _data_summary(data):
        if not isinstance(data, dict):
            return {"decks": 0, "cards": 0, "boxes": 0}

        def walk(decks):
            deck_count = 0
            card_count = 0
            box_count = 0
            for deck in decks or []:
                if not isinstance(deck, dict):
                    continue
                deck_count += 1
                cards = deck.get("cards", []) or []
                card_count += len(cards)
                for card in cards:
                    if isinstance(card, dict):
                        box_count += len(card.get("boxes", []) or [])
                child_decks = deck.get("children", []) or deck.get("subdecks", []) or []
                child_summary = walk(child_decks)
                deck_count += child_summary["decks"]
                card_count += child_summary["cards"]
                box_count += child_summary["boxes"]
            return {"decks": deck_count, "cards": card_count, "boxes": box_count}

        return walk(data.get("decks", []) or [])


# Singleton - import `store` everywhere
store = DirtyStore()


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKWARD-COMPATIBLE WRAPPERS
#  Purane load_data() / save_data() calls bina kisi change ke kaam karte rahenge
# ═══════════════════════════════════════════════════════════════════════════════
def load_data():
    return store.load()


def save_data(data=None):
    if data is not None:
        store.set(data)
    store.save_if_dirty()


# ═══════════════════════════════════════════════════════════════════════════════
#  DECK TREE HELPERS  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════
def find_deck_by_id(deck_id, lst):
    for d in lst:
        if d.get("_id") == deck_id:
            return d
        found = find_deck_by_id(deck_id, d.get("children", []))
        if found:
            return found
    return None


def next_deck_id(data):
    max_id = [0]

    def _walk(lst):
        for d in lst:
            try:
                val = int(d.get("_id", 0))
                max_id[0] = max(max_id[0], val)
            except (ValueError, TypeError):
                pass
            _walk(d.get("children", []))

    _walk(data.get("decks", []))
    return max_id[0] + 1

def new_box_id():
    return str(uuid.uuid4())

def compute_file_sha256(filepath: str) -> str:
    """Compute the SHA-256 hash of a file's content."""
    import hashlib
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        print(f"[ERROR] Failed to compute SHA-256 for {filepath}: {e}")
        return ""

def compute_image_dhash(image_path) -> str:
    """Compute the difference hash (dHash) of an image for visual similarity."""
    if not image_path or not os.path.exists(image_path):
        return ""
    try:
        from PIL import Image
        img = Image.open(image_path)
        # Convert to grayscale and resize to 9x8 using Lanczos filtering
        img = img.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(img.getdata())
        
        # Compare adjacent pixels in each row
        diff = []
        for row in range(8):
            for col in range(8):
                pixel_left = pixels[row * 9 + col]
                pixel_right = pixels[row * 9 + col + 1]
                diff.append(pixel_left > pixel_right)
                
        # Convert the 64 boolean differences to a 16-character hex string
        decimal_value = 0
        for bit in diff:
            decimal_value = (decimal_value << 1) | bit
        return f"{decimal_value:016x}"
    except Exception as e:
        print(f"[ERROR] Failed to compute dHash for {image_path}: {e}")
        return ""

def hamming_distance(hash1, hash2) -> int:
    """Calculate the Hamming distance between two 16-character hex dHashes."""
    if not hash1 or not hash2 or len(hash1) != 16 or len(hash2) != 16:
        return 999
    try:
        h1 = int(hash1, 16)
        h2 = int(hash2, 16)
        return bin(h1 ^ h2).count('1')
    except Exception:
        return 999

def find_duplicate_card(data: dict, file_sha: str, dhash: str, title: str, target_deck_id=None) -> tuple:
    # We return tuple (card, deck)
    if not isinstance(data, dict):
        return None, None
        
    normalized_title = title.strip().lower() if title else ""
    is_default_title = normalized_title in ("", "untitled", "pasted image")

    if data is store.get():
        with store._lock:
            if not hasattr(store, "_card_index") or store._card_index is None:
                store._rebuild_card_index()
            # Snapshot primitive fields to minimize work done under the lock
            card_items = []
            for card_id, (card, deck) in store._card_index.items():
                card_items.append((
                    card,
                    deck,
                    card.get("file_hash"),
                    card.get("visual_hash"),
                    card.get("image_path") or card.get("pdf_path"),
                    bool(card.get("image_path")),
                    card.get("title", "")
                ))
        
        for card, deck, c_sha, c_dhash, path, is_image, card_title in card_items:
            # 1. Check exact byte hash (SHA-256)
            # Lazy load SHA-256
            if file_sha and not c_sha and path:
                from storage_paths import resolve_asset_path
                abs_path = resolve_asset_path(path)
                if os.path.exists(abs_path):
                    c_sha = compute_file_sha256(abs_path)
                    if c_sha:
                        with store._lock:
                            card["file_hash"] = c_sha
                            store.mark_dirty()
                        
            if file_sha and c_sha == file_sha:
                return card, deck
                
            # 2. Check visual similarity (dHash) for image cards
            if dhash and is_image:
                # Lazy load dHash
                if not c_dhash and path:
                    from storage_paths import resolve_asset_path
                    abs_path = resolve_asset_path(path)
                    if os.path.exists(abs_path):
                        c_dhash = compute_image_dhash(abs_path)
                        if c_dhash:
                            with store._lock:
                                card["visual_hash"] = c_dhash
                                store.mark_dirty()
                            
                if c_dhash and hamming_distance(dhash, c_dhash) <= 2:
                    return card, deck
                    
            # 3. Check title duplicate (only in target deck if specified)
            if not is_default_title:
                c_title_norm = card_title.strip().lower()
                if c_title_norm == normalized_title:
                    if target_deck_id is None or deck.get("_id") == target_deck_id:
                        return card, deck
        return None, None

    # Fallback path for arbitrary dictionaries (not store.get())
    lazy_cache_updated = [False]

    def _walk(decks):
        for deck in decks:
            for card in deck.get("cards", []) or []:
                # 1. Check exact byte hash (SHA-256)
                c_sha = card.get("file_hash")
                path = card.get("image_path") or card.get("pdf_path")
                
                # Lazy load SHA-256
                if file_sha and not c_sha and path:
                    from storage_paths import resolve_asset_path
                    abs_path = resolve_asset_path(path)
                    if os.path.exists(abs_path):
                        c_sha = compute_file_sha256(abs_path)
                        if c_sha:
                            card["file_hash"] = c_sha
                            lazy_cache_updated[0] = True
                            
                if file_sha and c_sha == file_sha:
                    return card, deck
                    
                # 2. Check visual similarity (dHash) for image cards
                if dhash and card.get("image_path"):
                    c_dhash = card.get("visual_hash")
                    # Lazy load dHash
                    if not c_dhash and path:
                        from storage_paths import resolve_asset_path
                        abs_path = resolve_asset_path(path)
                        if os.path.exists(abs_path):
                            c_dhash = compute_image_dhash(abs_path)
                            if c_dhash:
                                card["visual_hash"] = c_dhash
                                lazy_cache_updated[0] = True
                                
                    if c_dhash and hamming_distance(dhash, c_dhash) <= 2:
                        return card, deck
                        
                # 3. Check title duplicate (only in target deck if specified)
                if not is_default_title:
                    c_title = card.get("title", "").strip().lower()
                    if c_title == normalized_title:
                        if target_deck_id is None or deck.get("_id") == target_deck_id:
                            return card, deck
                            
            # Check subdecks
            found_card, found_deck = _walk(deck.get("children", []) or deck.get("subdecks", []) or [])
            if found_card:
                return found_card, found_deck
        return None, None

    res_card, res_deck = _walk(data.get("decks", []) or [])
    
    if lazy_cache_updated[0]:
        store.mark_dirty()
        
    return res_card, res_deck

def find_card_and_deck_by_id(data: dict, card_id) -> tuple:
    if not isinstance(data, dict) or card_id is None:
        return None, None
        
    try:
        card_id = int(card_id)
    except (ValueError, TypeError):
        pass

    if data is store.get():
        return store.get_card_by_id(card_id)

    def _walk(decks):
        for deck in decks:
            for card in deck.get("cards", []):
                c_id = card.get("_id")
                try:
                    c_id = int(c_id)
                except (ValueError, TypeError):
                    pass
                if c_id == card_id:
                    return card, deck
            found_card, found_deck = _walk(deck.get("children", []) or deck.get("subdecks", []) or [])
            if found_card:
                return found_card, found_deck
        return None, None

    return _walk(data.get("decks", []) or [])

class _DeckHistory:
    MAX = 50

    def __init__(self):
        from collections import deque

        self._undo_stack = deque(maxlen=self.MAX)
        self._redo_stack = deque(maxlen=self.MAX)
        self._lock = threading.Lock()

    @staticmethod
    def _snapshot(data: dict) -> dict:
        return json.loads(json.dumps(data))

    @staticmethod
    def _restore(snapshot: dict) -> dict:
        return json.loads(json.dumps(snapshot))

    def push(self, data: dict):
        """Mutate se PEHLE call karo."""
        with self._lock:
            self._undo_stack.append(self._snapshot(data))
            self._redo_stack.clear()
            print(
                f"[DeckHistory][push] ✅ snapshot saved - "
                f"undo={len(self._undo_stack)}, redo=0"
            )

    def undo(self, store_ref) -> bool:
        with self._lock:
            if not self._undo_stack:
                print("[DeckHistory][undo] ⚠ stack empty")
                return False
            self._redo_stack.append(self._snapshot(store_ref.get()))
            snap = self._restore(self._undo_stack.pop())
            store_ref.set(snap)
            print(
                f"[DeckHistory][undo] ↩ restored - "
                f"undo={len(self._undo_stack)}, redo={len(self._redo_stack)}"
            )
            return True

    def redo(self, store_ref) -> bool:
        with self._lock:
            if not self._redo_stack:
                print("[DeckHistory][redo] ⚠ stack empty")
                return False
            self._undo_stack.append(self._snapshot(store_ref.get()))
            snap = self._restore(self._redo_stack.pop())
            store_ref.set(snap)
            print(
                f"[DeckHistory][redo] ↪ re-applied - "
                f"undo={len(self._undo_stack)}, redo={len(self._redo_stack)}"
            )
            return True

    @property
    def can_undo(self):
        return bool(self._undo_stack)

    @property
    def can_redo(self):
        return bool(self._redo_stack)



deck_history = _DeckHistory()


def _get_deck_lineage_names(data: dict, target_id) -> list:
    """Return list of deck names from root to target_id (e.g. ['GK', 'Geography'])."""
    path = []
    def _walk(nodes):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if n.get("_id") == target_id:
                path.append(n.get("name", ""))
                return True
            if _walk(n.get("children", [])):
                path.insert(0, n.get("name", ""))
                return True
        return False
    _walk(data.get("decks", []))
    return path


def get_or_create_deck_by_path(data: dict, deck_path: str, context_deck: dict = None) -> dict:
    """
    Resolve or create hierarchical deck path like 'Biology::Genetics::Mendel'.
    Strict ID & Context Anchoring:
    1. If context_deck is provided (e.g. user right-clicked 'GK > Geography'):
       - If deck_path is generic (Default Deck, Subject::Chapter) or matches context_deck's name/lineage, returns context_deck directly.
       - If deck_path defines relative subdecks, creates/resolves strictly under context_deck (never hijacking other root decks).
    2. If context_deck is None:
       - Resolves strictly top-down from root data['decks'].
    """
    if "decks" not in data:
        data["decks"] = []

    clean_path = str(deck_path or "").strip()
    generic_placeholders = {"", "default deck", "vocabulary", "imported cards", "subject::chapter", "subject::chapter_name"}

    if not clean_path or clean_path.lower() in generic_placeholders:
        if context_deck:
            return context_deck
        clean_path = "Default Deck"

    parts = [p.strip() for p in clean_path.split("::") if p.strip()]
    if not parts:
        return context_deck if context_deck else get_or_create_deck_by_path(data, "Default Deck")

    # If context_deck is provided, enforce strict context routing
    if context_deck:
        ctx_id = context_deck.get("_id")
        ctx_name = str(context_deck.get("name", "")).strip().lower()
        ctx_lineage = [name.strip().lower() for name in _get_deck_lineage_names(data, ctx_id)]
        parts_lower = [p.lower() for p in parts]

        # Case 1: deck_path is single part matching context_deck's name exactly
        if len(parts) == 1 and parts_lower[0] == ctx_name:
            return context_deck

        # Case 2: deck_path matches the full lineage of context_deck (e.g. "GK::Geography")
        if parts_lower == ctx_lineage:
            return context_deck

        # Case 3: deck_path extends the context_deck lineage (e.g. "GK::Geography::Rivers")
        if len(parts_lower) > len(ctx_lineage) and parts_lower[:len(ctx_lineage)] == ctx_lineage:
            remaining_parts = parts[len(ctx_lineage):]
            current_deck = context_deck
            current_level = context_deck.setdefault("children", [])
            for part in remaining_parts:
                found = next((d for d in current_level if d.get("name", "").strip().lower() == part.lower()), None)
                if not found:
                    found = {
                        "_id": next_deck_id(data),
                        "name": part,
                        "cards": [],
                        "children": [],
                        "expanded": False
                    }
                    current_level.append(found)
                current_deck = found
                current_level = found.setdefault("children", [])
            return current_deck

        # Case 4: deck_path starts with context_deck's name (e.g. "Geography::Rivers" inside context_deck "Geography")
        if parts_lower[0] == ctx_name:
            remaining_parts = parts[1:]
            current_deck = context_deck
            current_level = context_deck.setdefault("children", [])
            for part in remaining_parts:
                found = next((d for d in current_level if d.get("name", "").strip().lower() == part.lower()), None)
                if not found:
                    found = {
                        "_id": next_deck_id(data),
                        "name": part,
                        "cards": [],
                        "children": [],
                        "expanded": False
                    }
                    current_level.append(found)
                current_deck = found
                current_level = found.setdefault("children", [])
            return current_deck

        # Case 5: context_deck has a child matching parts[0] (e.g. context_deck is "GK", parts=["Geography", "Rivers"])
        first_child = next((d for d in context_deck.get("children", []) if d.get("name", "").strip().lower() == parts_lower[0]), None)
        if first_child:
            remaining_parts = parts[1:]
            current_deck = first_child
            current_level = first_child.setdefault("children", [])
            for part in remaining_parts:
                found = next((d for d in current_level if d.get("name", "").strip().lower() == part.lower()), None)
                if not found:
                    found = {
                        "_id": next_deck_id(data),
                        "name": part,
                        "cards": [],
                        "children": [],
                        "expanded": False
                    }
                    current_level.append(found)
                current_deck = found
                current_level = found.setdefault("children", [])
            return current_deck

        # Case 6: Relative subdeck path intended strictly under context_deck
        current_deck = context_deck
        current_level = context_deck.setdefault("children", [])
        for part in parts:
            found = next((d for d in current_level if d.get("name", "").strip().lower() == part.lower()), None)
            if not found:
                found = {
                    "_id": next_deck_id(data),
                    "name": part,
                    "cards": [],
                    "children": [],
                    "expanded": False
                }
                current_level.append(found)
            current_deck = found
            current_level = found.setdefault("children", [])
        return current_deck

    # Standard root-level resolution (context_deck is None)
    current_level = data["decks"]
    current_deck = None
    for part in parts:
        found = next((d for d in current_level if d.get("name", "").strip().lower() == part.lower()), None)
        if not found:
            found = {
                "_id": next_deck_id(data),
                "name": part,
                "cards": [],
                "children": [],
                "expanded": False
            }
            current_level.append(found)
        current_deck = found
        current_level = found.setdefault("children", [])

    return current_deck


def import_json_cards(data: dict, raw_json, default_deck_id=None, dup_policy: str = "skip") -> dict:
    """
    Import structured cards from JSON data (string or list of dicts).
    Supports:
    - deck_name (with '::' subdeck hierarchy)
    - context_anchor (high-level topic/context)
    - question, answer, trap_note (or notes)
    - chain_order & parent_chain_id (for sequential linked cards)
    - Automatic chain creation when items share context_anchor and have sequential chain_order
    
    dup_policy: 'skip' | 'update' | 'add'
    Returns:
    {
        "imported": int,
        "updated": int,
        "skipped": int,
        "chains_created": int,
        "created_cards": list,
        "target_deck_ids": list
    }
    """
    if isinstance(raw_json, str):
        try:
            items = json.loads(raw_json)
        except Exception as e:
            raise ValueError(f"Invalid JSON syntax: {e}")
    elif isinstance(raw_json, list):
        items = raw_json
    elif isinstance(raw_json, dict):
        items = raw_json.get("cards", [raw_json])
    else:
        raise ValueError("Invalid JSON data format")

    if not isinstance(items, list):
        raise ValueError("JSON must contain a list of card objects")

    from sm2_engine import sm2_init

    # Grouping for auto-chaining:
    # If cards share same deck and have chain_order > 0 without parent_chain_id,
    # generate a shared parent_chain_id so progressive chains (1..N) stay grouped together.
    chain_id_map = {}
    deck_orders = {}
    for item in items:
        if isinstance(item, dict):
            d_name = str(item.get("deck_name", "")).strip()
            c_order = item.get("chain_order", 0)
            if c_order:
                deck_orders.setdefault(d_name, []).append(c_order)

    for item in items:
        if not isinstance(item, dict):
            continue
        c_anchor = str(item.get("context_anchor", "")).strip()
        c_order = item.get("chain_order", 0)
        c_parent = item.get("parent_chain_id")
        d_name = str(item.get("deck_name", "")).strip()
        if not c_parent and c_order:
            orders = deck_orders.get(d_name, [])
            if len(orders) > 1 and max(orders) > 1:
                group_key = (d_name, "deck_chain")
            else:
                group_key = (d_name, c_anchor or "default_chain")
            if group_key not in chain_id_map:
                chain_id_map[group_key] = str(uuid.uuid4())
            item["parent_chain_id"] = chain_id_map[group_key]

    default_deck = find_deck_by_id(default_deck_id, data.get("decks", [])) if default_deck_id else None
    
    imported_count = 0
    updated_count = 0
    skipped_count = 0
    chains_set = set()
    target_deck_ids = set()
    created_cards = []

    # Map existing questions and UIDs for duplicate checking
    existing_uid_map = {}
    existing_question_map = {}
    def _index_deck(deck):
        for c in deck.get("cards", []):
            c_uid = str(c.get("card_uid") or "").strip()
            if not c_uid and isinstance(c.get("_id"), str):
                c_uid = c.get("_id").strip()
            if c_uid:
                existing_uid_map[c_uid] = (c, deck)
            q_norm = str(c.get("question", "")).strip().lower()
            if q_norm:
                existing_question_map[q_norm] = (c, deck)
        for child in deck.get("children", []):
            _index_deck(child)
            
    for root_deck in data.get("decks", []):
        _index_deck(root_deck)

    for item in items:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        a = str(item.get("answer", "")).strip()
        if not q and not a:
            continue

        c_anchor = str(item.get("context_anchor", "")).strip()
        trap_note = str(item.get("trap_note", "")).strip()
        notes = str(item.get("notes", "")).strip()
        if trap_note and not notes:
            notes = trap_note
        elif notes and not trap_note:
            trap_note = notes

        try:
            chain_order = int(item.get("chain_order", 0) or 0)
        except (ValueError, TypeError):
            chain_order = 0

        try:
            priority_tier = int(item.get("priority_tier", 1) or 1)
        except (ValueError, TypeError):
            priority_tier = 1

        parent_chain_id = item.get("parent_chain_id")
        if parent_chain_id:
            chains_set.add(parent_chain_id)

        # Determine target deck
        deck_name_field = item.get("deck_name")
        if deck_name_field:
            target_deck = get_or_create_deck_by_path(data, deck_name_field, context_deck=default_deck)
        elif default_deck:
            target_deck = default_deck
        else:
            target_deck = get_or_create_deck_by_path(data, "Default Deck")
            
        target_deck_ids.add(target_deck.get("_id"))

        # Duplicate checking: match by card_uid first, then question text
        item_uid = str(item.get("card_uid") or item.get("_id") or "").strip()
        q_norm = q.lower()
        matched_c = None
        matched_d = None
        if item_uid and item_uid in existing_uid_map:
            matched_c, matched_d = existing_uid_map[item_uid]
        elif q_norm in existing_question_map:
            matched_c, matched_d = existing_question_map[q_norm]

        if matched_c is not None:
            existing_c = matched_c
            if dup_policy == "skip":
                skipped_count += 1
                continue
            elif dup_policy in ("update", "add"):
                existing_c["question"] = q
                existing_c["answer"] = a
                first_line = [line.strip() for line in q.split("\n") if line.strip()]
                existing_c["title"] = (first_line[0][:45] + "...") if first_line and len(first_line[0]) > 45 else (first_line[0] if first_line else "Untitled")
                if notes:
                    existing_c["notes"] = notes
                if trap_note:
                    existing_c["trap_note"] = trap_note
                if c_anchor:
                    existing_c["context_anchor"] = c_anchor
                if chain_order:
                    existing_c["chain_order"] = chain_order
                if parent_chain_id:
                    existing_c["parent_chain_id"] = parent_chain_id
                existing_c["priority_tier"] = priority_tier
                if "related_concepts" in item:
                    existing_c["related_concepts"] = item.get("related_concepts", [])
                if "tags" in item:
                    existing_c["tags"] = item.get("tags", [])
                if item_uid and not existing_c.get("card_uid"):
                    existing_c["card_uid"] = item_uid
                # CRITICAL: SM-2 fields (interval, factor, reps, lapses, state, due) are NEVER touched!
                updated_count += 1
                continue

        # Build card
        first_line = [line.strip() for line in q.split("\n") if line.strip()]
        title = (first_line[0][:45] + "...") if first_line and len(first_line[0]) > 45 else (first_line[0] if first_line else "Untitled")
        
        card_unique_id = item_uid or str(uuid.uuid4())
        card = {
            "_id": str(uuid.uuid4()),
            "card_uid": card_unique_id,
            "card_type": "text",
            "title": title,
            "question": q,
            "answer": a,
            "notes": notes,
            "trap_note": trap_note,
            "context_anchor": c_anchor,
            "chain_order": chain_order,
            "parent_chain_id": parent_chain_id,
            "priority_tier": priority_tier,
            "tags": item.get("tags", []),
            "related_concepts": item.get("related_concepts", []),
            "created": datetime.now().isoformat(),
            "reviews": 0,
            "pdf_path": None,
            "image_path": None,
            "boxes": [],
            "is_formula": False
        }
        sm2_init(card)
        target_deck.setdefault("cards", []).append(card)
        if card_unique_id:
            existing_uid_map[card_unique_id] = (card, target_deck)
        existing_question_map[q_norm] = (card, target_deck)
        created_cards.append(card)
        imported_count += 1

    return {
        "imported": imported_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "chains_created": len(chains_set),
        "created_cards": created_cards,
        "target_deck_ids": list(target_deck_ids)
    }


def _natural_sort_key(s: str):
    import re
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


def parse_single_file_cards(file_path: str, context_tags: list = None) -> list:
    """
    Parses a single .csv, .tsv, .txt, or .json file into standard card dictionaries.
    Handles encoding fallback, RFC 4180 CSV quoting, and auto-detects column layout.
    """
    if not os.path.exists(file_path):
        return []

    content = ""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            break
        except Exception:
            continue

    if not content or not content.strip():
        return []

    ext = os.path.splitext(file_path)[1].lower()
    results = []

    # 1. JSON parsing
    if ext == ".json":
        try:
            raw = json.loads(content)
            items = []
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                if "questions" in raw and isinstance(raw["questions"], list):
                    items = raw["questions"]
                elif "cards" in raw and isinstance(raw["cards"], list):
                    items = raw["cards"]
                elif "question" in raw or "front" in raw:
                    items = [raw]

            for it in items:
                if not isinstance(it, dict):
                    continue
                q = str(it.get("question") or it.get("front") or it.get("word") or it.get("title") or "").strip()
                a = str(it.get("answer") or it.get("back") or it.get("meaning") or it.get("definition") or "").strip()
                if not q and not a:
                    continue
                notes = str(it.get("notes") or it.get("explanation") or it.get("detailed_solution") or "").strip()
                trap = str(it.get("trap_note") or "").strip()
                tags = list(context_tags or [])
                if isinstance(it.get("tags"), list):
                    tags.extend(it["tags"])

                is_mcq = "options" in it or "correct_option" in it
                card_uid = str(it.get("card_uid") or it.get("_id") or "").strip()
                deck_name = str(it.get("deck_name") or (raw.get("deck_name") if isinstance(raw, dict) else "") or "").strip()
                deck_uid = str(it.get("deck_uid") or (raw.get("deck_uid") if isinstance(raw, dict) else "") or "").strip()
                card_item = {
                    "card_uid": card_uid,
                    "deck_name": deck_name,
                    "deck_uid": deck_uid,
                    "question": q,
                    "answer": a,
                    "notes": notes,
                    "trap_note": trap,
                    "tags": tags,
                    "context_anchor": it.get("context_anchor", ""),
                    "related_concepts": it.get("related_concepts", []),
                    "chain_order": it.get("chain_order", 0),
                    "priority_tier": it.get("priority_tier", 1),
                    "is_mcq": is_mcq,
                    "source_file": file_path
                }
                if is_mcq:
                    card_item["options"] = it.get("options", [])
                    card_item["correct_option"] = it.get("correct_option")
                    card_item["solution_data"] = it.get("solution_data", {})
                    card_item["exam_meta"] = it.get("exam_meta", {})
                    card_item["question_html"] = it.get("question_html", "")
                results.append(card_item)
            return results
        except Exception as ex:
            print(f"[parse_single_file_cards] JSON parse error in {file_path}: {ex}")
            return []

    # 2. Delimited text / CSV parsing
    import csv
    import io

    delim = "\t" if ext == ".tsv" else ","
    # Simple delimiter probe if not .tsv
    if ext != ".tsv":
        first_line = content.splitlines()[0] if content.splitlines() else ""
        if "\t" in first_line and "," not in first_line:
            delim = "\t"
        elif ";" in first_line and "," not in first_line:
            delim = ";"

    rows = []
    try:
        f = io.StringIO(content)
        reader = csv.reader(f, delimiter=delim, skipinitialspace=True)
        rows = list(reader)
    except Exception:
        for line in content.splitlines():
            line_str = line.strip()
            if line_str:
                rows.append(line_str.split(delim))

    if not rows:
        return []

    # Check header
    first_row = [str(c).strip().lower() for c in rows[0]]
    header_keywords = {"front", "back", "question", "answer", "word", "meaning", "definition", "term", "notes", "prompt"}
    if any(col in header_keywords for col in first_row):
        rows = rows[1:]

    for row in rows:
        if not row:
            continue
        cleaned = [str(c).strip() for c in row]
        while cleaned and cleaned[-1] == "":
            cleaned.pop()
        if not cleaned:
            continue

        q = cleaned[0] if len(cleaned) > 0 else ""
        a = cleaned[1] if len(cleaned) > 1 else ""
        notes = cleaned[2] if len(cleaned) > 2 else ""

        # A valid flashcard MUST have both non-empty front (q) and back (a)
        if not q.strip() or not a.strip():
            continue

        results.append({
            "question": q,
            "answer": a,
            "notes": notes,
            "tags": list(context_tags or []),
            "is_mcq": False,
            "source_file": file_path
        })

    return results


def scan_and_parse_data_folder(
    folder_path: str,
    base_deck_path: str = "",
    create_subdecks: bool = True,
    context_tags: list = None
) -> dict:
    """
    Recursively scans folder_path for supported files (.csv, .tsv, .txt, .json).
    Automatically identifies and parses cards and mirrors directory hierarchy into sub-deck paths.
    Filters out system, build, and documentation files (e.g. instruction.txt, readme.md).
    """
    if not folder_path or not os.path.exists(folder_path):
        return {
            "root_folder": folder_path,
            "total_files": 0,
            "total_cards": 0,
            "files_summary": [],
            "cards": [],
            "suggested_deck_name": ""
        }

    norm_root = os.path.normpath(folder_path).replace("\\", "/")
    root_basename = os.path.basename(norm_root) or "Imported Folder"
    effective_base = base_deck_path.strip() if base_deck_path and base_deck_path.strip() else root_basename

    supported_exts = {".csv", ".tsv", ".txt", ".json"}
    ignored_dirnames = {
        "__pycache__", "node_modules", ".git", ".vscode", ".idea", "venv", "env", ".pytest_cache", ".gemini", "build", "dist"
    }
    ignored_file_stems = {
        "instruction", "instructions", "readme", "license", "todo", "requirements", "changelog", "notes", "config", "setup"
    }

    discovered_files = []

    for root, dirs, files in os.walk(norm_root):
        # Skip hidden and system/build directories
        dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ignored_dirnames]
        for f in files:
            if f.startswith(".") or f.startswith("~"):
                continue
            stem, ext = os.path.splitext(f)
            stem_lower = stem.strip().lower()
            if stem_lower in ignored_file_stems or stem_lower.startswith(("instruction", "readme", "license")):
                continue
            if ext.lower() in supported_exts:
                abs_f = os.path.normpath(os.path.join(root, f)).replace("\\", "/")
                discovered_files.append(abs_f)

    # Sort files naturally (e.g. A.csv, B.csv ... Z.csv, 1.csv, 2.csv, 10.csv)
    discovered_files.sort(key=lambda p: _natural_sort_key(os.path.basename(p)))

    all_cards = []
    files_summary = []

    for f_path in discovered_files:
        rel_to_root = os.path.relpath(f_path, norm_root).replace("\\", "/")
        rel_dir = os.path.dirname(rel_to_root)
        file_stem = os.path.splitext(os.path.basename(f_path))[0]

        tags = list(context_tags or [])
        if not create_subdecks:
            tags.append(f"file:{file_stem}")

        file_cards = parse_single_file_cards(f_path, context_tags=tags)
        if not file_cards:
            continue

        # Determine clean subdeck name and deck_uid from parsed cards
        target_subdeck_name = None
        target_deck_uid = None
        for c in file_cards:
            if c.get("deck_name") and not target_subdeck_name:
                target_subdeck_name = c["deck_name"].strip()
            if c.get("deck_uid") and not target_deck_uid:
                target_deck_uid = c["deck_uid"].strip()
            if target_subdeck_name and target_deck_uid:
                break

        if not target_subdeck_name:
            clean_stem = file_stem
            for sfx in ["_App_Import", "_app_import", "_Import", "_import"]:
                if clean_stem.endswith(sfx):
                    clean_stem = clean_stem[:-len(sfx)]
            clean_stem = clean_stem.replace("_", " ").strip()
            target_subdeck_name = clean_stem

        # Build sub-deck path
        if create_subdecks:
            deck_parts = [effective_base]
            if rel_dir and rel_dir != ".":
                for part in rel_dir.split("/"):
                    if part.strip():
                        deck_parts.append(part.strip())
            deck_parts.append(target_subdeck_name)
            deck_path = "::".join(deck_parts)
        else:
            deck_path = effective_base

        for c in file_cards:
            c["deck_path"] = deck_path
            c["source_relative_path"] = rel_to_root
            if target_deck_uid and not c.get("deck_uid"):
                c["deck_uid"] = target_deck_uid
            if target_subdeck_name and not c.get("deck_name"):
                c["deck_name"] = target_subdeck_name
            if not c.get("context_anchor"):
                c["context_anchor"] = target_subdeck_name

        all_cards.extend(file_cards)
        files_summary.append({
            "file_path": f_path,
            "relative_path": rel_to_root,
            "deck_path": deck_path,
            "subdeck_name": target_subdeck_name,
            "deck_uid": target_deck_uid,
            "cards_count": len(file_cards)
        })

    return {
        "root_folder": norm_root,
        "total_files": len(discovered_files),
        "total_cards": len(all_cards),
        "files_summary": files_summary,
        "cards": all_cards,
        "suggested_deck_name": effective_base
    }


def sync_deck_from_source_folder(
    data: dict,
    deck: dict = None,
    deck_id: int = None,
    custom_folder_path: str = None,
    create_subdecks: bool = True
) -> dict:
    """
    Incrementally synchronizes a deck (and its subdecks) from a local source folder or file.
    CRITICAL REQUIREMENT:
    - Preserves 100% of Spaced Repetition (SM-2) scheduling for existing cards.
    - Adds newly found words as fresh cards with sm2_init.
    - Updates card definitions/answers without touching review dates.
    """
    if "decks" not in data:
        data["decks"] = []

    target_deck = deck
    if target_deck is None and deck_id is not None:
        target_deck = find_deck_by_id(deck_id, data.get("decks", []))

    if target_deck is None:
        if data.get("decks"):
            target_deck = data["decks"][0]
        else:
            return {"status": "error", "message": "No target deck found to sync."}

    source_path = custom_folder_path or target_deck.get("source_folder_path") or target_deck.get("source_file_path")
    if not source_path or not os.path.exists(source_path):
        return {
            "status": "error",
            "message": f"Source path '{source_path}' does not exist or has not been set."
        }

    norm_source = os.path.normpath(source_path).replace("\\", "/")
    # Save source folder path on the root deck for future 1-click syncs
    target_deck["source_folder_path"] = norm_source

    from sm2_engine import sm2_init

    # Snapshot history for undo
    deck_history.push(data)

    # 1. Scan and parse files
    if os.path.isdir(norm_source):
        scan_res = scan_and_parse_data_folder(
            norm_source,
            base_deck_path=target_deck.get("name", ""),
            create_subdecks=create_subdecks
        )
        parsed_cards = scan_res["cards"]
    else:
        file_cards = parse_single_file_cards(norm_source)
        for c in file_cards:
            c["deck_path"] = target_deck.get("name", "Imported Deck")
            c["source_relative_path"] = os.path.basename(norm_source)
        parsed_cards = file_cards

    # 2. Build index of all existing cards in the target deck & all its sub-decks
    existing_uid_map = {}   # card_uid -> (card_dict, deck_dict)
    existing_cards_map = {} # norm_q -> (card_dict, deck_dict)

    def _walk_tree(d):
        if not isinstance(d, dict):
            return
        for card in d.get("cards", []) or []:
            if isinstance(card, dict):
                c_uid = str(card.get("card_uid") or "").strip()
                if not c_uid and isinstance(card.get("_id"), str):
                    c_uid = card.get("_id").strip()
                if c_uid:
                    existing_uid_map[c_uid] = (card, d)
                q = (card.get("question") or card.get("title") or "").strip().lower()
                if q:
                    existing_cards_map[q] = (card, d)
        for child in d.get("children", []) or []:
            _walk_tree(child)

    _walk_tree(target_deck)

    new_count = 0
    updated_count = 0
    unchanged_count = 0

    # 3. Process parsed cards
    for item in parsed_cards:
        q = item.get("question", "").strip()
        a = item.get("answer", "").strip()
        if not q and not a:
            continue

        item_uid = str(item.get("card_uid") or item.get("_id") or "").strip()
        norm_q = q.lower()
        matched_card = None
        parent_subdeck = None
        if item_uid and item_uid in existing_uid_map:
            matched_card, parent_subdeck = existing_uid_map[item_uid]
        elif norm_q in existing_cards_map:
            matched_card, parent_subdeck = existing_cards_map[norm_q]

        if matched_card is not None:
            # Card already exists!
            # CRITICAL: Preserve all SM-2 fields (interval, repetitions, ease, due, last_quality, reviews, etc.)
            existing_card = matched_card
            changed = False

            if item.get("deck_uid") and parent_subdeck and not parent_subdeck.get("deck_uid"):
                parent_subdeck["deck_uid"] = item["deck_uid"].strip()
            if item.get("source_file") and parent_subdeck and not parent_subdeck.get("source_file_path"):
                parent_subdeck["source_file_path"] = item["source_file"].replace("\\", "/")

            if existing_card.get("question") != q:
                existing_card["question"] = q
                first_line = [line.strip() for line in q.split("\n") if line.strip()]
                existing_card["title"] = (first_line[0][:45] + "...") if first_line and len(first_line[0]) > 45 else (first_line[0] if first_line else "Untitled")
                changed = True
            if existing_card.get("answer") != a:
                existing_card["answer"] = a
                changed = True
            if item.get("notes") and existing_card.get("notes") != item["notes"]:
                existing_card["notes"] = item["notes"]
                changed = True
            if item.get("trap_note") and existing_card.get("trap_note") != item["trap_note"]:
                existing_card["trap_note"] = item["trap_note"]
                changed = True
            if item.get("context_anchor") and existing_card.get("context_anchor") != item["context_anchor"]:
                existing_card["context_anchor"] = item["context_anchor"]
                changed = True
            if item.get("tags") and existing_card.get("tags") != item["tags"]:
                existing_card["tags"] = item["tags"]
                changed = True
            if item.get("related_concepts") and existing_card.get("related_concepts") != item["related_concepts"]:
                existing_card["related_concepts"] = item["related_concepts"]
                changed = True
            if item_uid and not existing_card.get("card_uid"):
                existing_card["card_uid"] = item_uid
                changed = True
            if item.get("is_mcq"):
                if item.get("options"):
                    existing_card["options"] = item["options"]
                if item.get("correct_option"):
                    existing_card["correct_option"] = item["correct_option"]
                if item.get("solution_data"):
                    existing_card["solution_data"] = item["solution_data"]
                if item.get("question_html"):
                    existing_card["question_html"] = item["question_html"]
                changed = True

            if changed:
                updated_count += 1
            else:
                unchanged_count += 1
        else:
            # New card!
            first_line = [line.strip() for line in q.split("\n") if line.strip()]
            title = (first_line[0][:45] + "...") if first_line and len(first_line[0]) > 45 else (first_line[0] if first_line else "Untitled")

            card_unique_id = item_uid or str(uuid.uuid4())
            new_card = {
                "_id": str(uuid.uuid4()),
                "card_uid": card_unique_id,
                "card_type": "mcq" if item.get("is_mcq") else "text",
                "title": title,
                "question": q,
                "answer": a,
                "notes": item.get("notes", ""),
                "trap_note": item.get("trap_note", ""),
                "context_anchor": item.get("context_anchor", ""),
                "tags": item.get("tags", []),
                "related_concepts": item.get("related_concepts", []),
                "created": datetime.now().isoformat(),
                "reviews": 0,
                "pdf_path": None,
                "image_path": None,
                "boxes": [],
                "is_formula": False
            }
            if item.get("is_mcq"):
                new_card["options"] = item.get("options", [])
                new_card["correct_option"] = item.get("correct_option")
                new_card["solution_data"] = item.get("solution_data", {})
                new_card["exam_meta"] = item.get("exam_meta", {})
                new_card["question_html"] = item.get("question_html", "")

            # Fresh Spaced Repetition initialization for new card
            sm2_init(new_card)

            # Route into target subdeck path
            target_subdeck_path = item.get("deck_path") or target_deck.get("name", "Default Deck")
            dest_deck = None
            item_deck_uid = str(item.get("deck_uid") or "").strip()
            item_deck_name = str(item.get("deck_name") or "").strip()

            # 1. Match subdeck by deck_uid within target_deck's subtree
            if item_deck_uid:
                def _find_by_uid(d):
                    for child in d.get("children", []) or []:
                        if str(child.get("deck_uid") or "").strip() == item_deck_uid:
                            return child
                        res = _find_by_uid(child)
                        if res:
                            return res
                    return None
                dest_deck = _find_by_uid(target_deck)

            # 2. Match subdeck by deck_name within target_deck's subtree
            if dest_deck is None and item_deck_name:
                def _find_by_name(d):
                    for child in d.get("children", []) or []:
                        if str(child.get("name", "")).strip().lower() == item_deck_name.lower():
                            return child
                        res = _find_by_name(child)
                        if res:
                            return res
                    return None
                dest_deck = _find_by_name(target_deck)

            # 3. Fallback to get_or_create_deck_by_path
            if dest_deck is None:
                dest_deck = get_or_create_deck_by_path(data, target_subdeck_path, context_deck=target_deck)

            # Ensure deck_uid, source_file_path, and source_folder_path are set on dest_deck
            if item_deck_uid and not dest_deck.get("deck_uid"):
                dest_deck["deck_uid"] = item_deck_uid
            if item.get("source_file"):
                src_norm = item["source_file"].replace("\\", "/")
                dest_deck["source_file_path"] = src_norm
                if not dest_deck.get("source_folder_path"):
                    dest_deck["source_folder_path"] = src_norm

            dest_deck.setdefault("cards", []).append(new_card)

            if card_unique_id:
                existing_uid_map[card_unique_id] = (new_card, dest_deck)
            existing_cards_map[norm_q] = (new_card, dest_deck)
            new_count += 1

    # 4. Pruning obsolete text cards when syncing from a single file
    removed_count = 0
    if not os.path.isdir(norm_source):
        valid_source_uids = set()
        valid_source_qs = set()
        for item in parsed_cards:
            u = str(item.get("card_uid") or item.get("_id") or "").strip()
            if u:
                valid_source_uids.add(u)
            q = (item.get("question") or "").strip().lower()
            if q:
                valid_source_qs.add(q)

        def _prune_deck_cards(d):
            nonlocal removed_count
            kept_cards = []
            for card in d.get("cards", []) or []:
                c_uid = str(card.get("card_uid") or card.get("_id") or "").strip()
                c_q = (card.get("question") or card.get("title") or "").strip().lower()
                # Preserve image occlusion cards with boxes or images
                if card.get("boxes") or card.get("image_path") or card.get("pdf_path"):
                    kept_cards.append(card)
                    continue
                # For text cards: keep only if present in the source file
                if (c_uid and c_uid in valid_source_uids) or (c_q and c_q in valid_source_qs):
                    kept_cards.append(card)
                else:
                    removed_count += 1
            d["cards"] = kept_cards
            for child in d.get("children", []) or []:
                _prune_deck_cards(child)

        _prune_deck_cards(target_deck)

    store.mark_dirty()

    return {
        "status": "ok",
        "new_count": new_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "removed_count": removed_count,
        "total_cards_scanned": len(parsed_cards),
        "deck_name": target_deck.get("name", "Deck"),
        "source_path": norm_source
    }


def write_back_card_to_source(card: dict, deck: dict = None) -> dict:
    """
    Writes back a single modified card to its linked source JSON file on disk immediately.
    Ensures user edits in Anki (mnemonics, notes, formatting) override and persist to disk JSON.
    """
    if not isinstance(card, dict):
        return {"status": "error", "message": "Invalid card"}

    # 1. Resolve source file path
    source_p = None
    if deck and isinstance(deck, dict):
        source_p = deck.get("source_file_path") or deck.get("source_folder_path")
    if not source_p and card.get("source_file"):
        source_p = card.get("source_file")

    # If deck didn't have it or not found, try finding via deck_uid / deck_name or card_uid
    if not source_p or not os.path.isfile(source_p):
        data = store.get()
        c_uid = card.get("card_uid") or card.get("_id")
        _, found_deck = find_card_and_deck_by_id(data, c_uid) if c_uid else (None, None)
        if found_deck:
            source_p = found_deck.get("source_file_path") or found_deck.get("source_folder_path")

    # Fallback to searching in data/generated_flashcards
    if not source_p or not os.path.isfile(source_p):
        deck_name = (deck.get("name") if deck else None) or card.get("deck_name", "")
        clean_name = deck_name
        for pfx in [f"{i}." for i in range(1, 30)] + [f"{i:02d}." for i in range(1, 30)]:
            if clean_name.startswith(pfx):
                clean_name = clean_name[len(pfx):].strip()
        parts = clean_name.split(None, 1)
        if parts and parts[0].isdigit() and len(parts) > 1:
            clean_name = parts[1]

        cand_dirs = [
            r"c:\Users\Digvijay\Downloads\SSC-Copilot\data\generated_flashcards",
            r"C:\Users\Digvijay\Downloads\SSC-Copilot\data\generated_flashcards",
            r"E:\GK"
        ]
        for c_dir in cand_dirs:
            if os.path.exists(c_dir):
                for root_d, _, files in os.walk(c_dir):
                    for fn in files:
                        if fn.endswith(".json") and clean_name and (clean_name.lower().replace(" ", "_") in fn.lower() or fn.lower().replace("_", " ") in clean_name.lower()):
                            source_p = os.path.join(root_d, fn).replace("\\", "/")
                            break
                    if source_p and os.path.isfile(source_p):
                        break
            if source_p and os.path.isfile(source_p):
                break

    if not source_p or not os.path.isfile(source_p):
        return {"status": "error", "message": "Could not find linked JSON file for deck/card."}

    # 2. Read existing JSON file
    try:
        with open(source_p, "r", encoding="utf-8") as f:
            disk_cards = json.load(f)
    except Exception as e:
        return {"status": "error", "message": f"Failed reading source file: {e}"}

    if not isinstance(disk_cards, list):
        return {"status": "error", "message": "Source JSON is not a card list"}

    # 3. Locate card in disk list by card_uid or question
    c_uid = str(card.get("card_uid") or card.get("_id") or "").strip()
    norm_q = (card.get("question") or card.get("title") or "").strip().lower()

    target_idx = None
    for idx, dc in enumerate(disk_cards):
        dc_uid = str(dc.get("card_uid") or dc.get("_id") or "").strip()
        if c_uid and dc_uid and c_uid == dc_uid:
            target_idx = idx
            break
        dc_q = (dc.get("question") or dc.get("title") or "").strip().lower()
        if norm_q and dc_q and norm_q == dc_q:
            target_idx = idx
            break

    fields_to_sync = [
        "question", "answer", "title", "notes", "trap_note",
        "tags", "related_concepts", "context_anchor", "is_mcq",
        "options", "correct_option", "is_formula"
    ]

    import datetime
    now_iso = datetime.datetime.now().isoformat()

    if target_idx is not None:
        target_disk_card = disk_cards[target_idx]
        for f in fields_to_sync:
            if f in card:
                target_disk_card[f] = card[f]
        target_disk_card["user_modified"] = True
        target_disk_card["last_user_edit"] = now_iso
    else:
        new_disk_entry = dict(card)
        new_disk_entry["user_modified"] = True
        new_disk_entry["last_user_edit"] = now_iso
        disk_cards.append(new_disk_entry)

    # 4. Atomic write back to disk
    try:
        tmp_p = source_p + ".tmp"
        with open(tmp_p, "w", encoding="utf-8") as f:
            json.dump(disk_cards, f, ensure_ascii=False, indent=2)
        if os.path.exists(source_p):
            os.replace(tmp_p, source_p)
        else:
            os.rename(tmp_p, source_p)
    except Exception as e:
        return {"status": "error", "message": f"Failed writing to source file: {e}"}

    return {"status": "ok", "source_file": source_p, "card_uid": c_uid}


def export_deck_to_source_file(data: dict, deck: dict = None, deck_id: int = None, custom_file_path: str = None) -> dict:
    """
    Pushes all cards from a deck to its linked source JSON file on disk.
    Preserves existing entries while updating modified questions, answers, and notes.
    """
    target_deck = deck
    if target_deck is None and deck_id is not None:
        target_deck = find_deck_by_id(deck_id, data.get("decks", []))
    if target_deck is None:
        if data.get("decks"):
            target_deck = data["decks"][0]
        else:
            return {"status": "error", "message": "No deck found."}

    source_p = custom_file_path or target_deck.get("source_file_path") or target_deck.get("source_folder_path")
    if not source_p or not os.path.isfile(source_p) or not source_p.endswith(".json"):
        return {"status": "error", "message": f"Source file '{source_p}' is not a valid JSON file."}

    # Collect all cards in target deck and subdecks
    deck_cards = []
    def _collect(d):
        for c in d.get("cards", []):
            deck_cards.append(c)
        for child in d.get("children", []) or []:
            _collect(child)
    _collect(target_deck)

    try:
        with open(source_p, "r", encoding="utf-8") as f:
            disk_cards = json.load(f)
    except Exception:
        disk_cards = []

    disk_uid_map = {}
    disk_q_map = {}
    for idx, dc in enumerate(disk_cards):
        uid = str(dc.get("card_uid") or dc.get("_id") or "").strip()
        if uid:
            disk_uid_map[uid] = idx
        q = (dc.get("question") or dc.get("title") or "").strip().lower()
        if q:
            disk_q_map[q] = idx

    fields_to_sync = [
        "question", "answer", "title", "notes", "trap_note",
        "tags", "related_concepts", "context_anchor", "is_mcq",
        "options", "correct_option", "is_formula"
    ]

    import datetime
    now_iso = datetime.datetime.now().isoformat()
    updated_count = 0
    added_count = 0

    for c in deck_cards:
        uid = str(c.get("card_uid") or c.get("_id") or "").strip()
        norm_q = (c.get("question") or c.get("title") or "").strip().lower()
        target_idx = None
        if uid and uid in disk_uid_map:
            target_idx = disk_uid_map[uid]
        elif norm_q and norm_q in disk_q_map:
            target_idx = disk_q_map[norm_q]

        if target_idx is not None:
            dc = disk_cards[target_idx]
            for f in fields_to_sync:
                if f in c:
                    dc[f] = c[f]
            dc["user_modified"] = True
            dc["last_user_edit"] = now_iso
            updated_count += 1
        else:
            new_entry = dict(c)
            new_entry["user_modified"] = True
            new_entry["last_user_edit"] = now_iso
            disk_cards.append(new_entry)
            added_count += 1

    tmp_p = source_p + ".tmp"
    with open(tmp_p, "w", encoding="utf-8") as f:
        json.dump(disk_cards, f, ensure_ascii=False, indent=2)
    os.replace(tmp_p, source_p)

    return {
        "status": "ok",
        "source_file": source_p,
        "updated_count": updated_count,
        "added_count": added_count,
        "total_cards": len(disk_cards)
    }



