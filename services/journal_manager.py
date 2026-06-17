import os
import json
import tempfile
import shutil
import time
import threading
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QColor

# ── Storage ───────────────────────────────────────────────────────────────────
JOURNAL_FILE = os.path.join(os.path.expanduser("~"), "anki_journal.json")

# Thread safety lock for concurrent reads/writes
JOURNAL_LOCK = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════════


def _load_journal() -> dict:
    with JOURNAL_LOCK:
        if os.path.exists(JOURNAL_FILE):
            if os.path.getsize(JOURNAL_FILE) <= 4:
                try:
                    with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content in ("", "{}", "[]"):
                            return {}
                except Exception:
                    pass
            try:
                with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CRITICAL][journal_manager] Failed to load journal file: {e}")
                raise RuntimeError(f"Journal decoding failed: {e}") from e
        return {}


def _save_journal(data: dict):
    with JOURNAL_LOCK:
        if not isinstance(data, dict):
            raise TypeError("Journal data must be a dictionary.")

        # 1. Create automatic dated backup before overwriting existing data
        if os.path.exists(JOURNAL_FILE) and os.path.getsize(JOURNAL_FILE) > 4:
            try:
                backup_dir = os.path.join(os.path.dirname(JOURNAL_FILE), "backups")
                os.makedirs(backup_dir, exist_ok=True)
                
                # Check if a backup for the current day already exists
                today_prefix = f"anki_journal.{time.strftime('%Y%m%d')}_"
                has_today_backup = False
                if os.path.exists(backup_dir):
                    for f in os.listdir(backup_dir):
                        if f.startswith(today_prefix) and f.endswith(".json"):
                            has_today_backup = True
                            break

                if not has_today_backup:
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    shutil.copy2(JOURNAL_FILE, os.path.join(backup_dir, f"anki_journal.{ts}.json"))
                
                # Keep last 30 backups to save disk space
                backups = sorted([
                    os.path.join(backup_dir, f) 
                    for f in os.listdir(backup_dir) 
                    if f.startswith("anki_journal.") and f.endswith(".json")
                ])
                while len(backups) > 30:
                    os.remove(backups.pop(0))
            except Exception as ex:
                print(f"[WARNING][journal_manager] Backup creation failed: {ex}")

        # 2. Perform atomic write
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
        pts = stroke[1:]
        result.append(
            {
                "color": color.name(),
                "pts": [[p.x(), p.y()] for p in pts],
            }
        )
    return result


def _strokes_from_json(data):
    result = []
    for s in data:
        color = QColor(s.get("color", "#CDD6F4"))
        pts = [QPointF(p[0], p[1]) for p in s.get("pts", [])]
        if pts:
            result.append([color] + pts)
    return result


def _texts_to_json(texts):
    return [
        {
            "x": t["x"],
            "y": t["y"],
            "text": t["text"],
            "color": t["color"],
            "size": t.get("size", 14),
        }
        for t in texts
    ]


def _texts_from_json(data):
    return [
        {
            "x": d["x"],
            "y": d["y"],
            "text": d["text"],
            "color": d.get("color", "#CDD6F4"),
            "size": d.get("size", 14),
        }
        for d in data
    ]
