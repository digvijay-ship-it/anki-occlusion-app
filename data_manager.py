import os
import json
import tempfile
import uuid
import threading
import time
import shutil
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
DATA_FILE = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.json")
AUTO_SAVE_INTERVAL = 60  # seconds
BACKUP_DIR_NAME = "anki_occlusion_data.backups"
MAX_SAVE_BACKUPS = 50


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
        self._lock = threading.Lock()
        self._auto_thread = None
        self._stop_event = threading.Event()
        self._save_thread = None
        self._save_thread_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._save_seq = 0
        self._latest_save_request_seq = 0
        self._last_async_save_ts = 0.0

    # ── Load / Get / Set ──────────────────────────────────────────────────────

    def load(self):
        """Load from disk. Clears dirty flag."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8-sig") as f:
                    self._data = json.load(f)
            except Exception:
                print("[DEBUG][data_safety] load_failed using_empty_default")
                self._data = {"decks": []}
        self._dirty = False
        return self._data

    def get(self):
        """Return current in-memory data dict."""
        return self._data

    def set(self, data):
        """Replace entire data dict and mark dirty."""
        with self._lock:
            self._data = data
            self._dirty = True

    # ── Dirty flag ────────────────────────────────────────────────────────────

    def mark_dirty(self):
        """Call after any in-place mutation of data."""
        with self._lock:
            self._dirty = True

    def is_dirty(self):
        return self._dirty

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_if_dirty(self):
        """
        Write to disk only if dirty.
        Returns True if save happened, False if skipped.
        """
        with self._lock:
            if not self._dirty:
                return False
            snapshot_text = json.dumps(self._data, ensure_ascii=False, indent=2)
            snapshot_summary = DirtyStore._data_summary(self._data)
            self._save_seq += 1
            save_seq = self._save_seq
            self._latest_save_request_seq = save_seq
            self._dirty = False
        try:
            return self._write_snapshot_to_disk(
                save_seq, snapshot_text, snapshot_summary
            )
        except Exception:
            with self._lock:
                self._dirty = True
            raise

    def save_force(self):
        """Force write regardless of dirty flag (use on app exit)."""
        with self._lock:
            snapshot_text = json.dumps(self._data, ensure_ascii=False, indent=2)
            snapshot_summary = DirtyStore._data_summary(self._data)
            self._save_seq += 1
            save_seq = self._save_seq
            self._latest_save_request_seq = save_seq
            self._dirty = False
        try:
            self._write_snapshot_to_disk(save_seq, snapshot_text, snapshot_summary)
        except Exception:
            with self._lock:
                self._dirty = True
            raise

    def _write_snapshot_to_disk(self, save_seq, snapshot_text, snapshot_summary):
        with self._write_lock:
            with self._lock:
                if save_seq < self._latest_save_request_seq:
                    return False
            self._write_serialized_to_disk(snapshot_text, snapshot_summary)
            return True

    def save_soon(self, min_interval: float = 3.0):
        """
        Schedule a background save without blocking the UI thread.
        Rapid repeated calls are coalesced into a single write.
        """
        now = time.monotonic()
        with self._lock:
            if not self._dirty:
                return False
            if (now - self._last_async_save_ts) < min_interval:
                return False
            self._last_async_save_ts = now

        with self._save_thread_lock:
            if self._save_thread and self._save_thread.is_alive():
                return False
            self._save_thread = threading.Thread(
                target=self.save_if_dirty, daemon=True, name="DirtyStore-SaveSoon"
            )
            self._save_thread.start()
            return True

    # ── Auto-save background thread ───────────────────────────────────────────

    def start_autosave(self, interval: int = AUTO_SAVE_INTERVAL):
        """Start background thread — saves every `interval` seconds if dirty."""
        if self._auto_thread and self._auto_thread.is_alive():
            return
        self._stop_event.clear()
        self._auto_thread = threading.Thread(
            target=self._autosave_loop,
            args=(interval,),
            daemon=True,
            name="DirtyStore-AutoSave",
        )
        self._auto_thread.start()

    def stop_autosave(self):
        """Stop background thread + final force save. Call on app shutdown."""
        self._stop_event.set()
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
            os.replace(tmp, DATA_FILE)
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
        serialized_text = json.dumps(data, ensure_ascii=False, indent=2)
        new_summary = DirtyStore._data_summary(data)
        DirtyStore._write_serialized_to_disk(serialized_text, new_summary)

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
        DirtyStore._prune_backups(backup_dir)
        return backup_path

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


# Singleton — import `store` everywhere
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


# ═══════════════════════════════════════════════════════════════════════════════
#  DECK HISTORY  — Deck reorder / rename / delete / create ke liye Undo / Redo
#  Usage:
#      deck_history.push(store.get())   # mutate se PEHLE call karo
#      deck_history.undo(store)         # Ctrl+Z
#      deck_history.redo(store)         # Ctrl+Shift+Z
# ═══════════════════════════════════════════════════════════════════════════════


class _DeckHistory:
    MAX = 50

    def __init__(self):
        from collections import deque

        self._undo_stack = deque(maxlen=self.MAX)
        self._redo_stack = deque(maxlen=self.MAX)
        self._lock = threading.Lock()

    @staticmethod
    def _snapshot(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _restore(snapshot: str) -> dict:
        return json.loads(snapshot)

    def push(self, data: dict):
        """Mutate se PEHLE call karo."""
        with self._lock:
            self._undo_stack.append(self._snapshot(data))
            self._redo_stack.clear()
            print(
                f"[DeckHistory][push] ✅ snapshot saved — "
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
                f"[DeckHistory][undo] ↩ restored — "
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
                f"[DeckHistory][redo] ↪ re-applied — "
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
