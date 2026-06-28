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
        with self._lock:
            self._data = data
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
                snapshot_text = json.dumps(data_snapshot, ensure_ascii=False, indent=2)
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
            serialized_text = json.dumps(data, ensure_ascii=False, indent=2)
            new_summary = DirtyStore._data_summary(data)
            DirtyStore._write_serialized_to_disk(serialized_text, new_summary)

    @staticmethod
    def _replace_file_with_retry(src, dst, attempts=8, delay=0.05):
        for attempt in range(attempts):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(delay * (attempt + 1))

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
            max_id[0] = max(max_id[0], d.get("_id", 0))
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
