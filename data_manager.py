import os
import json
import tempfile
import uuid
import threading
import time

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
DATA_FILE          = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.json")
AUTO_SAVE_INTERVAL = 60   # seconds

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
        self._data        = {"decks": []}
        self._dirty       = False
        self._lock        = threading.Lock()
        self._auto_thread = None
        self._stop_event  = threading.Event()

    # ── Load / Get / Set ──────────────────────────────────────────────────────

    def load(self):
        """Load from disk. Clears dirty flag."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"decks": []}
        self._dirty = False
        return self._data

    def get(self):
        """Return current in-memory data dict."""
        return self._data

    def set(self, data):
        """Replace entire data dict and mark dirty."""
        with self._lock:
            self._data  = data
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
            self._write_to_disk(self._data)
            self._dirty = False
            return True

    def save_force(self):
        """Force write regardless of dirty flag (use on app exit)."""
        with self._lock:
            self._write_to_disk(self._data)
            self._dirty = False

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
            name="DirtyStore-AutoSave"
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

    # ── Atomic write (crash-safe) — unchanged from original ───────────────────

    @staticmethod
    def _write_to_disk(data):
        dir_ = os.path.dirname(DATA_FILE) or "."
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise


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
import copy

class _DeckHistory:
    MAX = 50

    def __init__(self):
        self._undo_stack = []
        self._redo_stack = []
        self._lock       = threading.Lock()

    def push(self, data: dict):
        """Mutate se PEHLE call karo."""
        with self._lock:
            self._undo_stack.append(copy.deepcopy(data))
            if len(self._undo_stack) > self.MAX:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
            print(f"[DeckHistory][push] ✅ snapshot saved — "
                  f"undo={len(self._undo_stack)}, redo=0")

    def undo(self, store_ref) -> bool:
        with self._lock:
            if not self._undo_stack:
                print("[DeckHistory][undo] ⚠ stack empty")
                return False
            self._redo_stack.append(copy.deepcopy(store_ref.get()))
            snap = self._undo_stack.pop()
            store_ref.set(snap)
            print(f"[DeckHistory][undo] ↩ restored — "
                  f"undo={len(self._undo_stack)}, redo={len(self._redo_stack)}")
            return True

    def redo(self, store_ref) -> bool:
        with self._lock:
            if not self._redo_stack:
                print("[DeckHistory][redo] ⚠ stack empty")
                return False
            self._undo_stack.append(copy.deepcopy(store_ref.get()))
            snap = self._redo_stack.pop()
            store_ref.set(snap)
            print(f"[DeckHistory][redo] ↪ re-applied — "
                  f"undo={len(self._undo_stack)}, redo={len(self._redo_stack)}")
            return True

    @property
    def can_undo(self): return bool(self._undo_stack)

    @property
    def can_redo(self): return bool(self._redo_stack)


deck_history = _DeckHistory()