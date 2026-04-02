import os
import json
import tempfile
import uuid

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════════════
DATA_FILE = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"decks": []}

def save_data(data):
    dir_  = os.path.dirname(DATA_FILE) or "."
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

# ═══════════════════════════════════════════════════════════════════════════════
#  DECK TREE HELPERS
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