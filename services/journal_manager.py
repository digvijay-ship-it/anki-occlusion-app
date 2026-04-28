import os
import json
import tempfile
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QColor

# ── Storage ───────────────────────────────────────────────────────────────────
JOURNAL_FILE = os.path.join(os.path.expanduser("~"), "anki_journal.json")

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════════

def _load_journal() -> dict:
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_journal(data: dict):
    dir_ = os.path.dirname(JOURNAL_FILE) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, JOURNAL_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _strokes_to_json(strokes):
    result = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        color = stroke[0]
        pts   = stroke[1:]
        result.append({
            "color": color.name(),
            "pts":   [[p.x(), p.y()] for p in pts],
        })
    return result


def _strokes_from_json(data):
    result = []
    for s in data:
        color = QColor(s.get("color", "#CDD6F4"))
        pts   = [QPointF(p[0], p[1]) for p in s.get("pts", [])]
        if pts:
            result.append([color] + pts)
    return result


def _texts_to_json(texts):
    return [{"x": t["x"], "y": t["y"], "text": t["text"],
             "color": t["color"], "size": t.get("size", 14)} for t in texts]


def _texts_from_json(data):
    return [{"x": d["x"], "y": d["y"], "text": d["text"],
             "color": d.get("color", "#CDD6F4"), "size": d.get("size", 14)}
            for d in data]


