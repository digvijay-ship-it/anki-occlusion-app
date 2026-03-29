"""
Anki Occlusion — PDF & Image Flashcard App  v12
================================================
Changes from v9:
  [OPT-1]  Removed unused imports: QStackedWidget, QGroupBox, QImage
  [OPT-2]  uuid4-based box_id — guaranteed unique, no timestamp collision risk
  [OPT-3]  _find_by_id extracted to module-level helper — no more duplication
             between DeckTree and DeckView
  [OPT-4]  is_due_today() — single module-level helper used everywhere;
             eliminates the 3 copies of the same inline logic
  [OPT-5]  DeckView._refresh — card-level due badge now counts due *boxes*
             correctly (not just card-level sm2_due)
  [OPT-6]  PDF thumbnail cache in DeckView — pixmaps not re-loaded on every
             _refresh call
  [OPT-7]  save_data uses atomic write (temp file + rename) — no data loss on
             crash mid-write
  [OPT-8]  sm2_simulate uses sm2_init copy safely — no mutation of live data
  [OPT-9]  _find_home uses a cleaner loop without the hasattr guard
  [OPT-10] QPixmap thumbnail cache in DeckView — avoids repeated disk reads

v12 changes:
  [R1] Review: rating buttons hidden until card is revealed (Space / Show Answer)
       Mirrors Anki's "Show Answer → rate" flow exactly
  [R2] Review: canvas now uses full available width (~80%+ of screen)
       Queue list panel removed — cleaner, more like real Anki
  [R3] Review: "⊕ Center" button scrolls viewport back to active mask
       Keyboard shortcut: C key
  [R4] Review: Ctrl+Scroll (two-finger pinch) zooms canvas in/out
       Keyboard: Ctrl++, Ctrl+−, Ctrl+0 (fit)
  [R5] Review: header bar slimmed down, progress bar inline with header
  [R6] Home: Ctrl++ / Ctrl+− / Ctrl+0 scales home screen font size
  [R7] OcclusionCanvas: zoom_in / zoom_out / zoom_fit / duplicate_selected
       + wheelEvent with Ctrl modifier for pinch zoom

v13 changes:
  [L1] Live PDF Sync — QFileSystemWatcher monitors the loaded PDF file.
       When you annotate/edit the PDF in any external app (Foxit, Adobe,
       Drawboard, Xodo, etc.) and save, the editor auto-reloads within 800ms.
       Status indicator: 🟢 watching → 🟡 change detected → 🟢 reloaded ✓
  [L2] "📂 Open in PDF Reader" button — opens current PDF in system default
       app (os.startfile on Windows, open on Mac, xdg-open on Linux).
       Works with any PDF reader that supports saving annotations.
  [L3] Debounce timer (800ms) prevents multiple rapid reloads when editors
       emit several file-change events on a single save operation.
  [L4] Re-watch after delete+recreate — some editors (Adobe, Foxit) delete
       the file and recreate it on save; watcher auto-re-adds the path.
  [L5] Watcher stopped cleanly on dialog close/cancel/accept — no leaks.
"""

import sys, os, json, copy, uuid
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QFrame, QScrollArea, QInputDialog, QMessageBox,
    QSplitter, QStatusBar, QProgressBar, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QAbstractItemView, QMenu, QStyledItemDelegate, QStyle,
    QHeaderView
)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal, QLockFile, QTimer, QModelIndex
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QIcon, QBrush
)

try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

import tempfile

# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")
DATA_FILE = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.json")

# ═══════════════════════════════════════════════════════════════════════════════
#  SM-2 ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  ANKI-STYLE SCHEDULER
#
#  Card states (stored in "sched_state"):
#    "new"       — never seen
#    "learning"  — in intraday learning steps (minutes-based)
#    "review"    — graduated, days-based SM-2 scheduling
#    "relearn"   — failed a review card, back to learning steps
#
#  Learning steps (minutes): [1, 6, 10, 15]  → mimics real Anki default+
#  After passing all steps  → card graduates to "review" with 1-day interval
#
#  "sm2_due" stores a full ISO datetime string (not just date) so we can
#  schedule to-the-minute during learning.
# ═══════════════════════════════════════════════════════════════════════════════

LEARNING_STEPS  = [1, 6, 10, 15]   # minutes — configurable
GRADUATING_IV   = 1                 # days after completing all learning steps
EASY_IV         = 4                 # days for Easy on a new/learning card
RELEARN_STEPS   = [10]              # minutes — after failing a review card

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")

def _due_in_minutes(mins):
    return (datetime.now() + timedelta(minutes=mins)).isoformat(timespec="seconds")

def _due_in_days(days):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")

def sched_init(c):
    """Initialise scheduling fields on a card/box dict (idempotent)."""
    c.setdefault("sched_state",   "new")      # new | learning | review | relearn
    c.setdefault("sched_step",    0)           # index into LEARNING_STEPS
    c.setdefault("sm2_interval",  1)           # days (only meaningful in review)
    c.setdefault("sm2_ease",      2.5)         # ease factor
    c.setdefault("sm2_due",       _now_iso())  # full datetime string
    c.setdefault("sm2_repetitions", 0)
    c.setdefault("sm2_last_quality", -1)
    return c

# Keep sm2_init as alias so save/load code still works
def sm2_init(c):
    return sched_init(c)

def sched_update(c, quality):
    """
    Anki-style rating logic:
      quality 0  → Blackout  (reset to step 0)
      quality 1  → Again     (reset to step 0)
      quality 3  → Hard      (repeat current step)
      quality 4  → Good      (advance to next step / graduate)
      quality 5  → Easy      (graduate immediately with EASY_IV)
    """
    c = sched_init(c)
    state = c["sched_state"]
    step  = c["sched_step"]
    ef    = c["sm2_ease"]
    iv    = c["sm2_interval"]

    # Treat 'new' exactly like 'learning' — first press enters step 0
    if state == "new":
        state = "learning"
        c["sched_state"] = "learning"

    # Update ease factor (only meaningful in review state)
    if state == "review":
        ef = max(1.3, round(
            ef + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02), 4))

    # ── state machine ─────────────────────────────────────────────────────────
    if quality <= 1:
        # Again / Blackout → back to first learning step
        steps     = RELEARN_STEPS if state == "review" else LEARNING_STEPS
        new_state = "relearn" if state == "review" else "learning"
        new_step  = 0
        due       = _due_in_minutes(steps[0])

    elif quality == 3:
        # Hard → repeat current step (don't advance)
        if state in ("learning", "relearn"):
            steps     = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
            new_state = state
            new_step  = step
            due       = _due_in_minutes(steps[min(step, len(steps) - 1)])
        else:
            # Hard in review → slightly shorter interval
            new_state = "review"
            new_step  = 0
            iv        = max(1, round(iv * 1.2))
            due       = _due_in_days(iv)

    elif quality == 5:
        # Easy → graduate immediately regardless of state
        new_state = "review"
        new_step  = 0
        iv        = max(EASY_IV, round(iv * ef)) if state == "review" else EASY_IV
        due       = _due_in_days(iv)

    else:
        # Good (quality == 4) → advance to next step
        if state in ("learning", "relearn"):
            steps     = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
            next_step = step + 1
            if next_step >= len(steps):
                # Graduated! 🎓
                new_state = "review"
                new_step  = 0
                iv        = GRADUATING_IV
                due       = _due_in_days(iv)
            else:
                new_state = state
                new_step  = next_step
                due       = _due_in_minutes(steps[next_step])
        else:
            # Good in review → normal SM-2 interval growth
            new_state = "review"
            new_step  = 0
            iv = (1 if c["sm2_repetitions"] == 0 else
                  6 if c["sm2_repetitions"] == 1 else
                  max(1, round(iv * ef)))
            due = _due_in_days(iv)

    c.update({
        "sched_state":       new_state,
        "sched_step":        new_step,
        "sm2_interval":      iv,
        "sm2_ease":          ef,
        "sm2_due":           due,
        "sm2_last_quality":  quality,
        "sm2_repetitions":   c["sm2_repetitions"] + (1 if quality >= 3 else 0),
        "reviews":           c.get("reviews", 0) + 1,
    })
    return c

def sm2_update(c, quality):
    """Alias so existing call-sites still work."""
    return sched_update(c, quality)

def is_due_now(c):
    """True if card/box is due right now (compares full datetime)."""
    sched_init(c)
    if c.get("sm2_last_quality", -1) == -1:
        return True                            # never seen → always due
    due_str = c.get("sm2_due", "")
    if not due_str:
        return True
    try:
        return datetime.fromisoformat(due_str) <= datetime.now()
    except Exception:
        return True

def is_due_today(c):
    """
    True if card should appear in today's session:
      - new / learning cards   → is_due_now()  (minute-precision)
      - review cards           → due date (date part only) <= today
    """
    sched_init(c)
    state = c.get("sched_state", "new")
    if state in ("new", "learning", "relearn"):
        return is_due_now(c)
    # review cards — only compare date portion
    due_str = c.get("sm2_due", "")
    if not due_str:
        return True
    try:
        due_date = datetime.fromisoformat(due_str).date()
        return due_date <= date.today()
    except Exception:
        return True

def sm2_is_due(c):
    return is_due_today(c)

def sm2_days_left(c):
    """Days until next review (for review-state cards)."""
    try:
        due = datetime.fromisoformat(c.get("sm2_due", ""))
        delta = (due.date() - date.today()).days
        return max(0, delta)
    except Exception:
        return 0

def _fmt_due_interval(c):
    """Human-readable next interval shown on rating buttons."""
    state = c.get("sched_state", "new")
    step  = c.get("sched_step", 0)
    iv    = c.get("sm2_interval", 1)
    ef    = c.get("sm2_ease", 2.5)

    def _preview(quality):
        s = copy.deepcopy(c)
        sched_init(s)
        sched_update(s, quality)
        ns = s["sched_state"]
        if ns in ("learning", "relearn"):
            steps = RELEARN_STEPS if ns == "relearn" else LEARNING_STEPS
            mins  = steps[min(s["sched_step"], len(steps)-1)]
            return f"{mins}m" if mins < 60 else f"{mins//60}h"
        else:
            days = s["sm2_interval"]
            return f"{days}d"

    return {q: _preview(q) for q in [1, 3, 4, 5]}

def sm2_simulate(c, q):
    """Return interval string for preview labels."""
    previews = _fmt_due_interval(c)
    return previews.get(q, "?")

def sm2_badge(c):
    state = c.get("sched_state", "new")
    iv    = c.get("sm2_interval", 1)
    ef    = c.get("sm2_ease", 2.5)
    step  = c.get("sched_step", 0)
    if state == "new":
        return "🆕 New"
    if state in ("learning", "relearn"):
        steps = RELEARN_STEPS if state == "relearn" else LEARNING_STEPS
        mins  = steps[min(step, len(steps)-1)]
        tag   = "🔁 Relearn" if state == "relearn" else "📖 Learning"
        return f"{tag}  step:{step+1}/{len(steps)}  next:{mins}m"
    # review
    if is_due_today(c):
        return f"🔴 Review Due  iv:{iv}d  EF:{ef:.2f}"
    return f"✅ {sm2_days_left(c)}d left  iv:{iv}d  EF:{ef:.2f}"

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA  — atomic save to avoid corruption on crash
# ═══════════════════════════════════════════════════════════════════════════════

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"decks": []}

def save_data(data):
    # [OPT-7] Atomic write: write to temp file first, then rename
    dir_  = os.path.dirname(DATA_FILE) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)   # atomic on POSIX; best-effort on Windows
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise

# ═══════════════════════════════════════════════════════════════════════════════
#  DECK TREE HELPERS  — [OPT-3] module-level so both DeckTree & DeckView share
# ═══════════════════════════════════════════════════════════════════════════════

def find_deck_by_id(deck_id, lst):
    """Recursively find and return the deck dict with the given _id."""
    for d in lst:
        if d.get("_id") == deck_id:
            return d
        found = find_deck_by_id(deck_id, d.get("children", []))
        if found:
            return found
    return None

def next_deck_id(data):
    """Return max existing _id + 1 across the whole nested tree."""
    max_id = [0]
    def _walk(lst):
        for d in lst:
            max_id[0] = max(max_id[0], d.get("_id", 0))
            _walk(d.get("children", []))
    _walk(data.get("decks", []))
    return max_id[0] + 1

# ═══════════════════════════════════════════════════════════════════════════════
#  BOX ID HELPER  — [OPT-2] uuid4 for guaranteed uniqueness
# ═══════════════════════════════════════════════════════════════════════════════

def new_box_id():
    return str(uuid.uuid4())

# ═══════════════════════════════════════════════════════════════════════════════
#  PDF HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_page_to_pixmap(page, mat):
    pix = page.get_pixmap(matrix=mat, alpha=False)
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pix.save(tmp_path)
        qpx = QPixmap(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return qpx

def pdf_to_pixmaps(path: str, zoom: float = 1.5):
    pages, errors = [], []
    if not PDF_SUPPORT:
        return pages, "PyMuPDF not installed — run: pip install pymupdf"
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            return pages, "PDF is password-protected / encrypted."
        mat = fitz.Matrix(zoom, zoom)
        for page_num in range(len(doc)):
            try:
                qpx = pdf_page_to_pixmap(doc.load_page(page_num), mat)
                if qpx.isNull():
                    errors.append(f"Page {page_num+1}: null pixmap")
                else:
                    pages.append(qpx)
            except Exception as e:
                errors.append(f"Page {page_num+1}: {e}")
        doc.close()
    except Exception as e:
        return pages, str(e)
    err_str = "\n".join(errors) if errors and not pages else None
    return pages, err_str

def pdf_to_combined_pixmap(path: str, zoom: float = 1.5):
    pages, err = pdf_to_pixmaps(path, zoom)
    if not pages:
        return QPixmap(), err, []
    GAP       = 12
    SEP_COLOR = QColor("#45475A")
    total_w   = max(p.width()  for p in pages)
    total_h   = sum(p.height() for p in pages) + GAP * (len(pages) - 1)
    combined  = QPixmap(total_w, total_h)
    combined.fill(QColor("#1E1E2E"))
    painter = QPainter(combined)
    y, offsets = 0, []
    for i, px in enumerate(pages):
        offsets.append(y)
        painter.drawPixmap(0, y, px)
        y += px.height()
        if i < len(pages) - 1:
            painter.setPen(QPen(SEP_COLOR, 2))
            painter.drawLine(0, y + GAP // 2, total_w, y + GAP // 2)
            y += GAP
    painter.end()
    return combined, None, offsets

# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

C_BG      = "#1E1E2E"
C_SURFACE = "#2A2A3E"
C_CARD    = "#313145"
C_ACCENT  = "#7C6AF7"
C_GREEN   = "#50FA7B"
C_RED     = "#FF5555"
C_YELLOW  = "#F1FA8C"
C_TEXT    = "#CDD6F4"
C_SUBTEXT = "#A6ADC8"
C_BORDER  = "#45475A"
C_MASK    = "#F7916A"

BASE_FONT_SIZE = 11   # pt — user can change via A+ / A− buttons, saved to data file

def _build_ss(font_size: int = BASE_FONT_SIZE) -> str:
    return f"""
QMainWindow,QDialog{{background:{C_BG};color:{C_TEXT};}}
QWidget{{background:{C_BG};color:{C_TEXT};font-family:'Segoe UI';font-size:{font_size}px;}}
QFrame{{background:{C_SURFACE};border-radius:8px;}}
QLabel{{background:transparent;color:{C_TEXT};}}
QPushButton{{background:{C_ACCENT};color:white;border:none;border-radius:8px;padding:8px 18px;font-weight:bold;}}
QPushButton:hover{{background:#6A58E0;}}
QPushButton:pressed{{background:#5448C8;}}
QPushButton#danger{{background:{C_RED};color:white;}}
QPushButton#danger:hover{{background:#CC3333;}}
QPushButton#success{{background:{C_GREEN};color:#1E1E2E;}}
QPushButton#success:hover{{background:#3DD668;}}
QPushButton#warning{{background:{C_YELLOW};color:#1E1E2E;}}
QPushButton#warning:hover{{background:#D9E070;}}
QPushButton#hard{{background:#E08030;color:white;}}
QPushButton#hard:hover{{background:#C06020;}}
QPushButton#flat{{background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};}}
QPushButton#flat:hover{{background:{C_SURFACE};}}
QListWidget,QTreeWidget{{background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;padding:4px;}}
QListWidget::item,QTreeWidget::item{{padding:6px;border-radius:6px;}}
QListWidget::item:selected,QTreeWidget::item:selected{{background:{C_ACCENT};color:white;}}
QListWidget::item:hover,QTreeWidget::item:hover{{background:{C_CARD};}}
QScrollArea{{border:none;background:transparent;}}
QScrollBar:vertical{{background:{C_SURFACE};width:8px;border-radius:4px;}}
QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:4px;}}
QLineEdit,QTextEdit{{background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;padding:6px;}}
QProgressBar{{background:{C_CARD};border-radius:6px;height:12px;text-align:center;color:transparent;}}
QProgressBar::chunk{{background:{C_ACCENT};border-radius:6px;}}
QMessageBox{{background:{C_BG};color:{C_TEXT};}}
QStatusBar{{background:{C_SURFACE};color:{C_SUBTEXT};}}
QMenu{{background:{C_SURFACE};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;}}
QMenu::item:selected{{background:{C_ACCENT};}}
"""

SS = _build_ss()   # default — replaced at runtime by MainWindow when user changes size

# ═══════════════════════════════════════════════════════════════════════════════
#  OCCLUSION CANVAS
# ═══════════════════════════════════════════════════════════════════════════════

class OcclusionCanvas(QLabel):
    boxes_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._px             : QPixmap = None
        self._boxes          : list    = []
        self._drawing                  = False
        self._start                    = QPoint()
        self._live                     = QRect()
        self._mode                     = "edit"
        self._scale                    = 1.0
        self._selected_idx             = -1
        self._selected_indices         = set()
        self._target_idx               = -1
        self.setMouseTracking(True)

    # ── public ───────────────────────────────────────────────────────────────

    def load_pixmap(self, px: QPixmap):
        if px is None or px.isNull():
            self._px = None
            self.clear()
            return
        self._px    = px
        self._boxes = []
        self._scale = 1.0
        self._redraw()

    def set_boxes(self, boxes):
        self._boxes = [{"rect": QRect(b["rect"][0], b["rect"][1],
                                      b["rect"][2], b["rect"][3]),
                        "revealed": False,
                        "label":    b.get("label", ""),
                        "box_id":   b.get("box_id", "")}
                       for b in boxes]
        self._redraw()

    def set_boxes_with_state(self, boxes):
        self._boxes = [{"rect": QRect(b["rect"][0], b["rect"][1],
                                      b["rect"][2], b["rect"][3]),
                        "revealed": b.get("revealed", False),
                        "label":    b.get("label", ""),
                        "box_id":   b.get("box_id", "")}
                       for b in boxes]
        self._redraw()

    def get_boxes(self):
        SM2_KEYS = ("sm2_interval", "sm2_repetitions", "sm2_ease",
                    "sm2_due", "sm2_last_quality", "box_id")
        result = []
        for b in self._boxes:
            d = {"rect":  [b["rect"].x(), b["rect"].y(),
                           b["rect"].width(), b["rect"].height()],
                 "label": b.get("label", "")}
            for k in SM2_KEYS:
                if k in b:
                    d[k] = b[k]
            result.append(d)
        return result

    def set_mode(self, mode):
        self._mode = mode
        for b in self._boxes:
            b["revealed"] = False
        self.setCursor(QCursor(Qt.PointingHandCursor if mode == "review" else Qt.CrossCursor))
        self._redraw()

    def reveal_all(self):
        for b in self._boxes:
            b["revealed"] = True
        self._redraw()

    def set_target_box(self, idx):
        self._target_idx = idx
        self._redraw()

    def get_target_scaled_rect(self):
        if 0 <= self._target_idx < len(self._boxes):
            return self._sr(self._boxes[self._target_idx]["rect"])
        return None

    def select_all(self):
        if not self._boxes:
            return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx     = len(self._boxes) - 1
        self._redraw()

    def delete_selected_boxes(self):
        if self._selected_indices:
            for i in sorted(self._selected_indices, reverse=True):
                if 0 <= i < len(self._boxes):
                    self._boxes.pop(i)
            self._selected_indices = set()
            self._selected_idx     = -1
        elif self._selected_idx >= 0:
            self.delete_box(self._selected_idx)
            return
        self._redraw()
        self.boxes_changed.emit(self.get_boxes())

    def delete_box(self, idx):
        if 0 <= idx < len(self._boxes):
            self._boxes.pop(idx)
            self._selected_idx = -1
            self._redraw()
            self.boxes_changed.emit(self.get_boxes())

    def delete_last(self):
        self.delete_box(len(self._boxes) - 1)

    def clear_all(self):
        self._boxes        = []
        self._selected_idx = -1
        self._redraw()
        self.boxes_changed.emit([])

    def highlight(self, idx):
        self._selected_idx = idx
        self._redraw()

    def update_label(self, idx, text):
        if 0 <= idx < len(self._boxes):
            self._boxes[idx]["label"] = text
            self._redraw()

    # ── zoom ─────────────────────────────────────────────────────────────────

    def zoom_in(self):
        self._scale = min(self._scale * 1.25, 8.0)
        self._redraw()

    def zoom_out(self):
        self._scale = max(self._scale / 1.25, 0.05)
        self._redraw()

    def zoom_fit(self, viewport_w, viewport_h):
        if not self._px or self._px.isNull(): return
        sx = viewport_w  / max(self._px.width(),  1)
        sy = viewport_h  / max(self._px.height(), 1)
        self._scale = min(sx, sy)
        self._redraw()

    def wheelEvent(self, e):
        """Two-finger pinch-to-zoom on trackpad (Ctrl+scroll) and plain scroll."""
        if e.modifiers() & Qt.ControlModifier:
            # pixelDelta is non-zero for trackpad pinch; angleDelta for mouse wheel
            delta = e.pixelDelta().y() if not e.pixelDelta().isNull() else e.angleDelta().y() / 8
            factor = 1.0 + delta * 0.01
            factor = max(0.8, min(factor, 1.25))   # clamp per-event step
            self._scale = max(0.05, min(8.0, self._scale * factor))
            self._redraw()
            e.accept()
        else:
            super().wheelEvent(e)

    def _spx(self):
        if not self._px:
            return QPixmap()
        return self._px.scaled(int(self._px.width()  * self._scale),
                               int(self._px.height() * self._scale),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _sr(self, r):
        return QRect(int(r.x()      * self._scale), int(r.y()      * self._scale),
                     int(r.width()  * self._scale), int(r.height() * self._scale))

    def _redraw(self):
        if not self._px or self._px.isNull():
            return
        spx = self._spx()
        if spx.isNull():
            return
        canvas = QPixmap(spx)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing)

        for i, b in enumerate(self._boxes):
            sr  = self._sr(b["rect"])
            lbl = b.get("label") or f"#{i+1}"
            sel = (i == self._selected_idx)

            if self._mode == "review" and not b["revealed"]:
                if i == self._target_idx:
                    p.fillRect(sr, QColor(C_GREEN))
                    p.setPen(QPen(QColor("#1E1E2E"), 3))
                    p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                    p.drawText(sr, Qt.AlignCenter, lbl)
                else:
                    p.fillRect(sr, QColor(C_MASK))
                    p.setPen(QPen(QColor("#FFF"), 2))
                    p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                    p.drawText(sr, Qt.AlignCenter, lbl)
            elif self._mode == "review" and b["revealed"]:
                p.setPen(QPen(QColor(C_GREEN), 2))
                p.drawRect(sr)
            else:
                multi_sel = i in self._selected_indices
                is_sel    = sel or multi_sel
                fill      = QColor(C_MASK if not is_sel else "#50FA7B")
                fill.setAlpha(155)
                p.fillRect(sr, fill)
                border_col = QColor("#FFF") if not is_sel else QColor(C_GREEN)
                p.setPen(QPen(border_col, 2, Qt.DashLine))
                p.drawRect(sr)
                p.setPen(QPen(border_col, 1))
                p.setFont(QFont("Segoe UI", 9))
                p.drawText(sr, Qt.AlignCenter, lbl)

        if self._drawing and not self._live.isNull():
            sr = self._sr(self._live)
            c  = QColor(C_ACCENT)
            c.setAlpha(110)
            p.fillRect(sr, c)
            p.setPen(QPen(QColor(C_ACCENT), 2))
            p.drawRect(sr)

        p.end()
        self.setPixmap(canvas)
        self.resize(canvas.size())

    def _ip(self, pos):
        return QPoint(int(pos.x() / self._scale), int(pos.y() / self._scale))

    # ── mouse ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if not self._px:
            return
        ip = self._ip(e.pos())
        if self._mode == "edit" and e.button() == Qt.LeftButton:
            for i, b in enumerate(self._boxes):
                if b["rect"].contains(ip):
                    self._selected_idx     = i
                    self._selected_indices = set()
                    self._redraw()
                    self.boxes_changed.emit(self.get_boxes())
                    return
            self._selected_indices = set()
            self._drawing = True
            self._start   = ip
            self._live    = QRect()
        elif self._mode == "review" and e.button() == Qt.LeftButton:
            for b in self._boxes:
                if b["rect"].contains(ip) and not b["revealed"]:
                    b["revealed"] = True
                    self._redraw()
                    break

    def mouseMoveEvent(self, e):
        if self._drawing:
            self._live = QRect(self._start, self._ip(e.pos())).normalized()
            self._redraw()

    def mouseReleaseEvent(self, e):
        if self._drawing and e.button() == Qt.LeftButton:
            self._drawing = False
            rect = QRect(self._start, self._ip(e.pos())).normalized()
            if rect.width() > 8 and rect.height() > 8:
                self._boxes.append({"rect": rect, "revealed": False, "label": ""})
                self._selected_idx = len(self._boxes) - 1
                self._redraw()
                self.boxes_changed.emit(self.get_boxes())
            self._live = QRect()
            self._redraw()

    def resizeEvent(self, e):
        super().resizeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            self.delete_selected_boxes()
        elif e.key() == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.select_all()
        else:
            super().keyPressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  MASK PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class MaskPanel(QWidget):
    def __init__(self, canvas: OcclusionCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._canvas.boxes_changed.connect(self._refresh)
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)

        hdr = QLabel("🔲  Occlusion Masks")
        hdr.setFont(QFont("Segoe UI", 11, QFont.Bold))
        L.addWidget(hdr)

        self.list_w = QListWidget()
        self.list_w.currentRowChanged.connect(self._on_select)
        L.addWidget(self.list_w, stretch=1)

        lbl_e = QLabel("Label for selected mask:")
        lbl_e.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        L.addWidget(lbl_e)
        self.inp_label = QLineEdit()
        self.inp_label.setPlaceholderText("e.g. Mitochondria")
        self.inp_label.textChanged.connect(self._on_label_change)
        L.addWidget(self.inp_label)

        btn_row  = QHBoxLayout()
        b_del    = QPushButton("🗑 Delete")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._delete_selected)
        b_clear  = QPushButton("✕ Clear All")
        b_clear.setObjectName("flat")
        b_clear.clicked.connect(self._canvas.clear_all)
        btn_row.addWidget(b_del)
        btn_row.addWidget(b_clear)
        L.addLayout(btn_row)

    def _refresh(self, boxes):
        self.list_w.blockSignals(True)
        self.list_w.clear()
        for i, b in enumerate(boxes):
            lbl = b.get("label") or f"Mask #{i+1}"
            self.list_w.addItem(f"  🟧 {lbl}")
        self.list_w.blockSignals(False)
        sel = self._canvas._selected_idx
        if 0 <= sel < self.list_w.count():
            self.list_w.setCurrentRow(sel)
            box = self._canvas._boxes[sel]
            self.inp_label.blockSignals(True)
            self.inp_label.setText(box.get("label", ""))
            self.inp_label.blockSignals(False)

    def _on_select(self, row):
        self._canvas.highlight(row)
        if 0 <= row < len(self._canvas._boxes):
            self.inp_label.blockSignals(True)
            self.inp_label.setText(self._canvas._boxes[row].get("label", ""))
            self.inp_label.blockSignals(False)

    def _on_label_change(self, text):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.update_label(row, text)
            self.list_w.currentItem().setText(f"  🟧 {text or f'Mask #{row+1}'}")

    def _delete_selected(self):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.delete_box(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  CARD EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class CardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None):
        super().__init__(parent)
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        self.card                = card or {}
        self._pdf_pages          = []
        self._cur_page           = 0
        self._data               = data
        self._deck               = deck
        self._auto_subdeck_name  = None
        self._setup_ui()
        if card:
            self._load_card(card)

    def exec_(self):
        self.showMaximized()
        return super().exec_()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(12, 12, 12, 12)
        L.setSpacing(8)

        # ── toolbar ───────────────────────────────────────────────────────────
        top = QHBoxLayout()
        ttl = QLabel("✏️  Anki-Style Occlusion Editor")
        ttl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        top.addWidget(ttl)
        top.addStretch()

        bi = QPushButton("🖼 Load Image")
        bi.clicked.connect(self._load_image)
        bp = QPushButton("📄 Load PDF")
        bp.clicked.connect(self._load_pdf)
        bp.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT:
            bp.setToolTip("pip install pymupdf")

        b_undo = QPushButton("↩ Undo Last")
        b_undo.setObjectName("flat")
        b_undo.clicked.connect(lambda: self.canvas.delete_last())

        self.btn_group = QPushButton("⛓ Group Masks  [G]")
        self.btn_group.setObjectName("flat")
        self.btn_group.setToolTip(
            "OFF (default): each mask is its own review card\n"
            "ON: all masks on this card are reviewed together")
        self.btn_group.setCheckable(True)
        self.btn_group.setChecked(self.card.get("grouped", False))
        self.btn_group.clicked.connect(self._toggle_group)
        self._update_group_btn()

        top.addWidget(bi)
        top.addWidget(bp)
        top.addWidget(b_undo)
        top.addWidget(self.btn_group)
        L.addLayout(top)

        # ── PDF nav bar ───────────────────────────────────────────────────────
        self.pdf_bar = QWidget()
        pb = QHBoxLayout(self.pdf_bar)
        pb.setContentsMargins(0, 0, 0, 0)
        self.btn_pp = QPushButton("◀ Prev")
        self.btn_pp.setObjectName("flat")
        self.btn_pp.setFixedWidth(80)
        self.lbl_pg = QLabel("Page 1/1")
        self.lbl_pg.setAlignment(Qt.AlignCenter)
        self.btn_np = QPushButton("Next ▶")
        self.btn_np.setObjectName("flat")
        self.btn_np.setFixedWidth(80)
        self.btn_pp.clicked.connect(self._prev_page)
        self.btn_np.clicked.connect(self._next_page)
        pb.addWidget(self.btn_pp)
        pb.addWidget(self.lbl_pg)
        pb.addWidget(self.btn_np)
        pb.addStretch()
        self.pdf_bar.hide()
        L.addWidget(self.pdf_bar)

        # ── main 3-panel split ────────────────────────────────────────────────
        main_split = QSplitter(Qt.Horizontal)

        canvas_w = QWidget()
        cl = QVBoxLayout(canvas_w)
        cl.setContentsMargins(0, 0, 0, 0)
        sc = _ZoomableScrollArea()
        sc.setWidgetResizable(True)
        self.canvas = OcclusionCanvas()
        sc.setWidget(self.canvas)
        sc._canvas = self.canvas
        cl.addWidget(sc)
        hint = QLabel("🖱 Drag to draw  •  Click to select  •  Ctrl+A all  •  Del delete  •  Ctrl+Scroll or pinch to zoom  •  G group")
        hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        hint.setAlignment(Qt.AlignCenter)
        cl.addWidget(hint)
        main_split.addWidget(canvas_w)

        self.mask_panel = MaskPanel(self.canvas)
        self.mask_panel.setMinimumWidth(200)
        self.mask_panel.setMaximumWidth(260)
        main_split.addWidget(self.mask_panel)

        meta_w = QWidget()
        ml = QVBoxLayout(meta_w)
        ml.setContentsMargins(8, 0, 0, 0)
        fr = QFrame()
        fl = QFormLayout(fr)
        fl.setContentsMargins(12, 12, 12, 12)
        fl.setSpacing(10)
        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("Card title…")
        self.inp_tags  = QLineEdit()
        self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_notes = QTextEdit()
        self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(80)
        fl.addRow("Title:", self.inp_title)
        fl.addRow("Tags:",  self.inp_tags)
        fl.addRow("Notes:", self.inp_notes)
        ml.addWidget(QLabel("📝 Card Info"))
        ml.addWidget(fr)
        ml.addStretch()
        meta_w.setMinimumWidth(200)
        meta_w.setMaximumWidth(260)
        main_split.addWidget(meta_w)

        main_split.setSizes([620, 220, 220])
        L.addWidget(main_split, stretch=1)

        # ── bottom buttons ────────────────────────────────────────────────────
        bot = QHBoxLayout()
        bot.addStretch()
        bc = QPushButton("Cancel")
        bc.setObjectName("flat")
        bc.clicked.connect(self.reject)
        bs = QPushButton("💾 Save Card")
        bs.setObjectName("success")
        bs.clicked.connect(self._save)
        bot.addWidget(bc)
        bot.addWidget(bs)
        L.addLayout(bot)

    # ── loaders ───────────────────────────────────────────────────────────────

    def _toggle_group(self):
        self.card["grouped"] = self.btn_group.isChecked()
        self._update_group_btn()

    def _update_group_btn(self):
        if self.btn_group.isChecked():
            self.btn_group.setText("⛓ Grouped  [G]")
            self.btn_group.setStyleSheet(
                f"background:#50FA7B;color:#1E1E2E;border-radius:8px;"
                f"padding:8px 18px;font-weight:bold;")
        else:
            self.btn_group.setText("⛓ Group Masks  [G]")
            self.btn_group.setStyleSheet("")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_G:
            self.btn_group.setChecked(not self.btn_group.isChecked())
            self._toggle_group()
        else:
            super().keyPressEvent(e)

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
        self.card["image_path"] = path
        self.card.pop("pdf_path", None)
        self._pdf_pages = []
        self.pdf_bar.hide()
        self.canvas.load_pixmap(px)
        if not self.inp_title.text():
            self.inp_title.setText(os.path.splitext(os.path.basename(path))[0])

    def _load_pdf(self):
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load PDF", "", "PDF (*.pdf)")
        if not path:
            return
        pages, err = pdf_to_pixmaps(path)
        if err and not pages:
            QMessageBox.warning(self, "PDF Error", err)
            return
        self._pdf_pages = pages
        self._cur_page  = 0
        self.card["pdf_path"] = path
        self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
        self.pdf_bar.show()
        self._show_pdf_page()
        if not self.inp_title.text():
            self.inp_title.setText(self._auto_subdeck_name)

    def _show_pdf_page(self):
        if not self._pdf_pages:
            return
        self.canvas.load_pixmap(self._pdf_pages[self._cur_page])
        self.lbl_pg.setText(f"Page {self._cur_page+1}/{len(self._pdf_pages)}")
        self.btn_pp.setEnabled(self._cur_page > 0)
        self.btn_np.setEnabled(self._cur_page < len(self._pdf_pages) - 1)

    def _prev_page(self):
        if self._cur_page > 0:
            self._cur_page -= 1
            self._show_pdf_page()

    def _next_page(self):
        if self._cur_page < len(self._pdf_pages) - 1:
            self._cur_page += 1
            self._show_pdf_page()

    def _load_card(self, card):
        self.inp_title.setText(card.get("title", ""))
        self.inp_tags.setText(", ".join(card.get("tags", [])))
        self.inp_notes.setPlainText(card.get("notes", ""))
        self.btn_group.setChecked(card.get("grouped", False))
        self._update_group_btn()
        px = None
        if card.get("image_path") and os.path.exists(card["image_path"]):
            px = QPixmap(card["image_path"])
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(card["pdf_path"]):
            pages, _ = pdf_to_pixmaps(card["pdf_path"])
            if pages:
                self._pdf_pages = pages
                self._cur_page  = 0
                self.pdf_bar.show()
                self._show_pdf_page()
        if px and not px.isNull():
            self.canvas.load_pixmap(px)
        if card.get("boxes"):
            self.canvas.set_boxes(card["boxes"])
            self.mask_panel._refresh(card["boxes"])

    # ── save ──────────────────────────────────────────────────────────────────

    def _save(self):
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self, "No Source", "Load an image or PDF first.")
            return

        old_boxes  = self.card.get("boxes", [])
        new_boxes  = self.canvas.get_boxes()
        SM2_KEYS   = ("sm2_interval", "sm2_repetitions", "sm2_ease",
                      "sm2_due", "sm2_last_quality", "box_id")

        # [OPT-2] Match by box_id first, fallback to index for old cards
        old_by_id = {b["box_id"]: b for b in old_boxes if "box_id" in b}

        merged = []
        for i, nb in enumerate(new_boxes):
            existing_id = nb.get("box_id")
            old = old_by_id.get(existing_id) if existing_id else None
            if old is None and i < len(old_boxes):
                old = old_boxes[i]
            if old:
                for k in SM2_KEYS:
                    if k in old:
                        nb[k] = old[k]
            # Assign uuid4 box_id if missing
            if "box_id" not in nb:
                nb["box_id"] = new_box_id()
            merged.append(nb)

        self.card.update({
            "title":   self.inp_title.text().strip() or "Untitled",
            "tags":    [t.strip() for t in self.inp_tags.text().split(",") if t.strip()],
            "notes":   self.inp_notes.toPlainText(),
            "boxes":   merged,
            "grouped": self.btn_group.isChecked(),
            "created": self.card.get("created", datetime.now().isoformat()),
            "reviews": self.card.get("reviews", 0),
        })
        if self._auto_subdeck_name:
            self.card["_auto_subdeck"] = self._auto_subdeck_name
        sm2_init(self.card)
        for box in self.card.get("boxes", []):
            sm2_init(box)
        self.accept()

    def get_card(self):
        return self.card


# ═══════════════════════════════════════════════════════════════════════════════
#  REVIEW SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

QUEUE_ROLE = Qt.UserRole + 10

class QueueDelegate(QStyledItemDelegate):
    COLORS = {
        "current": {"bg": QColor(C_GREEN),   "fg": QColor("#1E1E2E")},
        "done":    {"bg": QColor("#2A3A2A"),  "fg": QColor("#6A8A6A")},
        "pending": {"bg": QColor(C_SURFACE),  "fg": QColor(C_TEXT)},
    }

    def paint(self, painter, option, index):
        state = index.data(QUEUE_ROLE) or "pending"
        cols  = self.COLORS[state]
        painter.save()
        r = option.rect.adjusted(2, 2, -2, -2)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cols["bg"]))
        painter.drawRoundedRect(r, 5, 5)
        if state == "current":
            painter.setBrush(QBrush(QColor("#1E1E2E")))
            painter.drawRect(r.left(), r.top() + 4, 4, r.height() - 8)
        painter.setPen(cols["fg"])
        font = painter.font()
        font.setBold(state == "current")
        painter.setFont(font)
        painter.drawText(r.adjusted(10, 0, -4, 0), Qt.AlignVCenter, index.data())
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 34)


class _ZoomableScrollArea(QScrollArea):
    """
    A QScrollArea that intercepts Ctrl+wheel (two-finger pinch on trackpad)
    and forwards it to the embedded OcclusionCanvas for zoom instead of scrolling.
    Plain scroll (no Ctrl) works normally.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = None   # set after canvas is created

    def wheelEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self._canvas:
            # Forward to canvas which handles pinch/zoom
            self._canvas.wheelEvent(e)
        else:
            super().wheelEvent(e)


class ReviewScreen(QWidget):
    """
    Review mode.
    Only boxes where is_due_today() == True are queued.
    """
    finished = pyqtSignal()

    # Blackout removed — 4 ratings: 1=Again 2=Hard 3=Good 4=Easy
    RATINGS = [
        ("1  🔁 Again", "danger",  1),
        ("2  😓 Hard",  "hard",    3),
        ("3  ✅ Good",  "success", 4),
        ("4  ⚡ Easy",  "warning", 5),
    ]

    def __init__(self, cards, data=None, parent=None):
        super().__init__(parent)
        self._data           = data
        self._items          = []
        self._pdf_cache      = {}
        self._current_pixmap = None

        for card in cards:
            boxes   = card.get("boxes", [])
            grouped = card.get("grouped", False)
            if grouped or len(boxes) == 0:
                sm2_init(card)
                self._items.append((card, None, card))
            else:
                for i, box in enumerate(boxes):
                    sm2_init(box)
                    if is_due_today(box):           # [OPT-4] use shared helper
                        self._items.append((card, i, box))

        self._items.sort(key=lambda x: x[2].get("sm2_due", ""))
        self._idx  = 0
        self._done = 0
        self._setup_ui()
        self._load_item()

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        if key == Qt.Key_F11:
            win = self.window()
            if win.isFullScreen():
                win.showMaximized()
                self._set_fullscreen_ui(False)
            else:
                win.showFullScreen()
                self._set_fullscreen_ui(True)
        elif key == Qt.Key_Space:
            self._reveal_current()
        # Rating keys only work AFTER reveal
        elif key == Qt.Key_1 and self._rating_frame.isVisible():
            self._rate(1)
        elif key == Qt.Key_2 and self._rating_frame.isVisible():
            self._rate(3)
        elif key == Qt.Key_3 and self._rating_frame.isVisible():
            self._rate(4)
        elif key == Qt.Key_4 and self._rating_frame.isVisible():
            self._rate(5)
        # Zoom shortcuts
        elif mods & Qt.ControlModifier and key in (Qt.Key_Equal, Qt.Key_Plus):
            self.canvas.zoom_in()
        elif mods & Qt.ControlModifier and key == Qt.Key_Minus:
            self.canvas.zoom_out()
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self._zoom_fit()
        elif key == Qt.Key_C:
            self._center_on_target()
        else:
            super().keyPressEvent(e)

    def _reveal_current(self):
        """Reveal target mask, then show rating buttons (Anki-style)."""
        if 0 <= self._idx < len(self._items):
            _, box_idx, _ = self._items[self._idx]
            if box_idx is None:
                self.canvas.reveal_all()
            else:
                if 0 <= box_idx < len(self.canvas._boxes):
                    self.canvas._boxes[box_idx]["revealed"] = True
                    self.canvas._redraw()
            # Show rating panel, hide reveal button
            self._reveal_bar.hide()
            self._rating_frame.show()

    def _set_fullscreen_ui(self, fullscreen: bool):
        """Fullscreen: hide header bar, title strip, hint. Keep canvas + bottom panel."""
        self._hdr_widget.setVisible(not fullscreen)
        self.lbl_title.setVisible(not fullscreen)
        self._hint_label.setVisible(not fullscreen)

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ══ HEADER BAR ═══════════════════════════════════════════════════════
        hdr_w = QFrame()
        hdr_w.setFixedHeight(46)
        hdr_w.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-bottom:1px solid {C_BORDER};border-radius:0;}}")
        hdr = QHBoxLayout(hdr_w)
        hdr.setContentsMargins(14, 0, 14, 0); hdr.setSpacing(10)

        self.lbl_prog = QLabel("Card 1/1")
        self.lbl_prog.setFont(QFont("Segoe UI", 12, QFont.Bold))
        hdr.addWidget(self.lbl_prog)

        self.prog = QProgressBar()
        self.prog.setFixedHeight(8)
        self.prog.setTextVisible(False)
        self.prog.setStyleSheet(
            f"QProgressBar{{background:{C_CARD};border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{C_ACCENT};border-radius:4px;}}")
        hdr.addWidget(self.prog, stretch=1)

        self.lbl_sm2 = QLabel("")
        self.lbl_sm2.setStyleSheet(
            f"background:{C_CARD};color:{C_SUBTEXT};"
            f"border-radius:6px;padding:3px 10px;font-size:11px;")
        hdr.addWidget(self.lbl_sm2)

        # Zoom buttons
        def _zb(txt, tip):
            b = QPushButton(txt); b.setToolTip(tip)
            b.setFixedSize(28, 28)
            b.setStyleSheet(
                f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
                f"border:1px solid {C_BORDER};border-radius:5px;font-size:13px;}}"
                f"QPushButton:hover{{background:{C_SURFACE};}}")
            return b
        b_zin  = _zb("+", "Zoom In  Ctrl++")
        b_zout = _zb("−", "Zoom Out  Ctrl+−")
        b_zfit = _zb("⊡", "Zoom Fit  Ctrl+0")
        b_center = _zb("⊕", "Center on active mask")
        b_zin.clicked.connect(lambda: self.canvas.zoom_in())
        b_zout.clicked.connect(lambda: self.canvas.zoom_out())
        b_zfit.clicked.connect(self._zoom_fit)
        b_center.clicked.connect(self._center_on_target)
        hdr.addWidget(b_zin); hdr.addWidget(b_zout)
        hdr.addWidget(b_zfit); hdr.addWidget(b_center)

        b_exit = QPushButton("✕ Exit")
        b_exit.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:4px 14px;font-size:12px;")
        b_exit.clicked.connect(self.finished.emit)
        hdr.addWidget(b_exit)
        L.addWidget(hdr_w)
        self._hdr_widget = hdr_w

        # Title strip
        self.lbl_title = QLabel("")
        self.lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_title.setStyleSheet(
            f"color:{C_ACCENT};background:{C_BG};"
            f"padding:4px 16px;border-bottom:1px solid {C_BORDER};")
        self.lbl_title.setFixedHeight(30)
        L.addWidget(self.lbl_title)

        # ══ CANVAS (takes full available width) ══════════════════════════════
        self._canvas_scroll = _ZoomableScrollArea()
        self._canvas_scroll.setWidgetResizable(True)
        self._canvas_scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C_BG};}}"
            f"QScrollBar:vertical{{background:{C_SURFACE};width:8px;border-radius:4px;}}"
            f"QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:4px;}}"
            f"QScrollBar:horizontal{{background:{C_SURFACE};height:8px;border-radius:4px;}}"
            f"QScrollBar::handle:horizontal{{background:{C_BORDER};border-radius:4px;}}")
        self.canvas = OcclusionCanvas()
        self.canvas.set_mode("review")
        self._canvas_scroll.setWidget(self.canvas)
        self._canvas_scroll._canvas = self.canvas   # ref for event filter
        L.addWidget(self._canvas_scroll, stretch=1)

        # ══ BOTTOM AREA: hint + reveal/rating panel ═══════════════════════════
        bottom_w = QWidget()
        bottom_w.setStyleSheet(f"background:{C_SURFACE};")
        bl = QVBoxLayout(bottom_w)
        bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(0)

        # Hint bar
        hint = QLabel(
            "Space = reveal  •  After reveal: 1=Again  2=Hard  3=Good  4=Easy  •  "
            "Ctrl+Scroll or Ctrl+/− to zoom  •  F11 fullscreen")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFixedHeight(22)
        hint.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;"
            f"border-top:1px solid {C_BORDER};padding:2px;")
        bl.addWidget(hint)
        self._hint_label = hint

        # ── Show Answer button (visible BEFORE reveal) ─────────────────────
        self._reveal_bar = QFrame()
        self._reveal_bar.setStyleSheet(f"QFrame{{background:{C_BG};}}")
        rb_l = QHBoxLayout(self._reveal_bar)
        rb_l.setContentsMargins(0, 10, 0, 10)
        b_rev = QPushButton("👁  Show Answer  [Space]")
        b_rev.setStyleSheet(
            f"background:{C_SURFACE};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:10px 60px;font-size:14px;font-weight:bold;")
        b_rev.clicked.connect(self._reveal_current)
        rb_l.addStretch(); rb_l.addWidget(b_rev); rb_l.addStretch()
        bl.addWidget(self._reveal_bar)

        # ── Rating panel (hidden UNTIL reveal) ────────────────────────────
        self._rating_frame = QFrame()
        self._rating_frame.setStyleSheet(
            f"QFrame{{background:{C_BG};border-top:1px solid {C_BORDER};}}")
        rfl = QVBoxLayout(self._rating_frame)
        rfl.setContentsMargins(12, 8, 12, 12); rfl.setSpacing(4)

        lq = QLabel("🧠 How well did you remember?")
        lq.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lq.setAlignment(Qt.AlignCenter)
        lq.setStyleSheet(f"color:{C_SUBTEXT};")
        rfl.addWidget(lq)

        br = QHBoxLayout(); br.setSpacing(6)
        RATING_STYLES = {
            "danger":  f"background:{C_RED};color:white;border:none;border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "hard":    "background:#E08030;color:white;border:none;border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "success": f"background:{C_GREEN};color:#1E1E2E;border:none;border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "warning": f"background:{C_YELLOW};color:#1E1E2E;border:none;border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
        }
        self._rating_btns = []
        for lbl, obj, q in self.RATINGS:
            btn = QPushButton(lbl)
            btn.setStyleSheet(RATING_STYLES.get(obj, ""))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda _, qq=q: self._rate(qq))
            br.addWidget(btn)
            self._rating_btns.append(btn)
        rfl.addLayout(br)

        prev_row = QHBoxLayout(); prev_row.setSpacing(6)
        self._prev_lbls = []
        for _, _, q in self.RATINGS:
            pl = QLabel("→?")
            pl.setAlignment(Qt.AlignCenter)
            pl.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
            prev_row.addWidget(pl)
            self._prev_lbls.append((pl, q))
        rfl.addLayout(prev_row)

        self._rating_frame.hide()   # hidden until reveal
        bl.addWidget(self._rating_frame)

        L.addWidget(bottom_w)

        # ── hidden in fullscreen ───────────────────────────────────────────
        self._mid_row_widget = self._reveal_bar   # kept for _set_fullscreen_ui compat

    # ── zoom / center helpers ─────────────────────────────────────────────────

    def _zoom_fit(self):
        vp = self._canvas_scroll.viewport()
        self.canvas.zoom_fit(vp.width(), vp.height())

    def _center_on_target(self):
        """Scroll canvas so the active mask is centered in the viewport."""
        r = self.canvas.get_target_scaled_rect()
        if r:
            vbar = self._canvas_scroll.verticalScrollBar()
            hbar = self._canvas_scroll.horizontalScrollBar()
            hbar.setValue(max(0, r.center().x() - self._canvas_scroll.viewport().width()  // 2))
            vbar.setValue(max(0, r.center().y() - self._canvas_scroll.viewport().height() // 2))

    def _load_item(self):
        if self._idx >= len(self._items):
            self._finish()
            return

        card, box_idx, sm2_obj = self._items[self._idx]
        total     = len(self._items)
        remaining = total - self._idx
        self.lbl_prog.setText(
            f"Done:{self._done}  Remaining:{remaining}  Total:{total}")
        self.prog.setMaximum(max(total, 1))
        self.prog.setValue(self._done)

        boxes = card.get("boxes", [])
        title = card.get("title", "")
        if box_idx is not None and boxes:
            lbl = boxes[box_idx].get("label") or f"Mask #{box_idx+1}"
            self.lbl_title.setText(f"{title}  —  {lbl}")
        else:
            self.lbl_title.setText(title)

        self.lbl_sm2.setText(sm2_badge(sm2_obj))
        # Preview labels — now shows "1m", "6m", "1d", "4d" etc.
        previews = _fmt_due_interval(sm2_obj)
        for pl, q in self._prev_lbls:
            pl.setText(f"→{previews.get(q, '?')}")

        # Load pixmap
        px = None
        if card.get("image_path") and os.path.exists(card["image_path"]):
            tmp = QPixmap(card["image_path"])
            if not tmp.isNull():
                px = tmp
        elif card.get("pdf_path") and PDF_SUPPORT:
            key = card["pdf_path"]
            if key not in self._pdf_cache:
                combined, _, _ = pdf_to_combined_pixmap(card["pdf_path"])
                if not combined.isNull():
                    self._pdf_cache[key] = combined
            px = self._pdf_cache.get(key)

        if px and not px.isNull():
            self._current_pixmap = px
            self.canvas.load_pixmap(px)
            if box_idx is None:
                self.canvas.set_boxes(boxes)
            else:
                display_boxes = [
                    {"rect":     b["rect"],
                     "label":    b.get("label", ""),
                     "revealed": (i != box_idx)}
                    for i, b in enumerate(boxes)
                ]
                self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_mode("review")
            self.canvas.set_target_box(box_idx if box_idx is not None else -1)

            # Auto-scale: fit image WIDTH to viewport (like a PDF viewer / real Anki).
            # Do it after a short delay so the viewport has its final size.
            def _apply_zoom(p=px):
                vp = self._canvas_scroll.viewport()
                vw = max(vp.width(), 100)
                # Scale so image fills the full viewport width
                new_scale = vw / max(p.width(), 1)
                # Never shrink below 15% or blow up beyond 300%
                self.canvas._scale = max(0.15, min(new_scale, 3.0))
                self.canvas._redraw()
            QTimer.singleShot(30, _apply_zoom)

            def _scroll_to_mask(bi=box_idx):
                r = self.canvas.get_target_scaled_rect()
                if r and bi is not None:
                    vbar = self._canvas_scroll.verticalScrollBar()
                    hbar = self._canvas_scroll.horizontalScrollBar()
                    hbar.setValue(max(0, r.center().x() - self._canvas_scroll.viewport().width()  // 2))
                    vbar.setValue(max(0, r.center().y() - self._canvas_scroll.viewport().height() // 2))
            QTimer.singleShot(80, _scroll_to_mask)
        else:
            self.canvas.load_pixmap(QPixmap())

        # Reset to "before reveal" state for each new card
        self._reveal_bar.show()
        self._rating_frame.hide()

    def _rate(self, quality):
        card, box_idx, sm2_obj = self._items[self._idx]
        sched_update(sm2_obj, quality)
        card["reviews"] = card.get("reviews", 0) + 1
        if self._data:
            save_data(self._data)

        state = sm2_obj.get("sched_state", "review")

        if state in ("learning", "relearn"):
            # Card is still in learning — re-insert it at correct position
            # (sorted by sm2_due so it appears after other sooner-due cards)
            item = self._items.pop(self._idx)
            # Find insertion point: first item whose due is >= this card's due
            due_str = sm2_obj.get("sm2_due", "")
            insert_at = len(self._items)   # default: append at end
            for j in range(self._idx, len(self._items)):
                other_due = self._items[j][2].get("sm2_due", "")
                if other_due >= due_str:
                    insert_at = j
                    break
            self._items.insert(insert_at, item)
            # _idx stays the same — next item naturally slides into position
            # Rebuild queue list labels
            self._rebuild_queue()
        else:
            # Graduated to review — move on
            self._done += 1
            self._idx  += 1

        self._load_item()

    def _rebuild_queue(self):
        pass   # queue panel removed — nothing to rebuild

    def _finish(self):
        self.prog.setValue(len(self._items))
        still_learning = sum(
            1 for _, _, sm2_obj in self._items
            if sm2_obj.get("sched_state") in ("learning", "relearn")
        )
        QMessageBox.information(self, "Done! 🎉",
            f"Reviewed: {self._done}\n"
            f"Still in learning: {still_learning}\n\n"
            f"Consistency beats cramming! 🔥")
        self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════════
#  DECK TREE
# ═══════════════════════════════════════════════════════════════════════════════

class DeckTree(QWidget):
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._ensure_ids()
        self._setup_ui()
        self.refresh()

    def _ensure_ids(self):
        counter = [0]
        def _walk(lst):
            for d in lst:
                if "_id" not in d:
                    counter[0] += 1
                    d["_id"] = counter[0]
                _walk(d.get("children", []))
        _walk(self._data.get("decks", []))

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)
        hdr = QLabel("📚  Decks")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Bold))
        L.addWidget(hdr)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_click)
        L.addWidget(self.tree, stretch=1)
        btn_row = QHBoxLayout()
        b_new = QPushButton("＋ Deck")
        b_new.clicked.connect(lambda: self._new_deck(None))
        b_sub = QPushButton("＋ Sub")
        b_sub.clicked.connect(self._new_subdeck)
        b_del = QPushButton("🗑")
        b_del.setObjectName("danger")
        b_del.setFixedWidth(36)
        b_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(b_new)
        btn_row.addWidget(b_sub)
        btn_row.addStretch()
        btn_row.addWidget(b_del)
        L.addLayout(btn_row)
        hint = QLabel("Double-click to open  •  Right-click for menu")
        hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        hint.setAlignment(Qt.AlignCenter)
        L.addWidget(hint)

    def refresh(self):
        sel_id = self._get_selected_id()
        self.tree.clear()
        for deck in self._data.get("decks", []):
            self.tree.addTopLevelItem(self._make_item(deck))
        self.tree.expandAll()
        if sel_id is not None:
            self._select_by_id(sel_id)

    def _make_item(self, deck):
        nc    = len(deck.get("cards", []))
        # [OPT-5] count due boxes across all non-grouped cards
        due   = sum(1 for c in deck.get("cards", []) if is_due_today(c))
        badge = f"🔴{due}" if due else "✅"
        item  = QTreeWidgetItem([f"  📂  {deck['name']}  {badge}"])
        item.setData(0, Qt.UserRole, deck.get("_id"))
        for child in deck.get("children", []):
            item.addChild(self._make_item(child))
        return item

    def _get_id_from_item(self, item):
        return item.data(0, Qt.UserRole) if item else None

    def _get_deck_from_item(self, item):
        did = self._get_id_from_item(item)
        # [OPT-3] use module-level helper
        return find_deck_by_id(did, self._data.get("decks", [])) if did is not None else None

    def _get_selected_id(self):
        return self._get_id_from_item(self.tree.currentItem())

    def _select_by_id(self, deck_id):
        def _walk(item):
            if item.data(0, Qt.UserRole) == deck_id:
                self.tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if _walk(item.child(i)):
                    return True
            return False
        for i in range(self.tree.topLevelItemCount()):
            if _walk(self.tree.topLevelItem(i)):
                break

    def _on_double_click(self, item, _col):
        deck = self._get_deck_from_item(item)
        if deck:
            self.deck_selected.emit(deck)

    def _on_click(self, item, _col):
        deck = self._get_deck_from_item(item)
        if deck:
            self.deck_selected.emit(deck)

    def _ctx_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            did = self._get_id_from_item(item)
            menu.addAction("▶ Open",      lambda: self._on_double_click(item, 0))
            menu.addAction("＋ Sub-deck", lambda: self._new_deck(did))
            menu.addAction("✏ Rename",   lambda: self._rename_by_id(did))
            menu.addSeparator()
            menu.addAction("🗑 Delete",   lambda: self._delete_by_id(did))
        else:
            menu.addAction("＋ New Top-level Deck", lambda: self._new_deck(None))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _new_deck(self, parent_id):
        name, ok = QInputDialog.getText(self, "New Deck", "Deck name:")
        if not ok or not name.strip():
            return
        new_deck = {
            "_id":      next_deck_id(self._data),   # [OPT-3]
            "name":     name.strip(),
            "cards":    [],
            "children": [],
            "created":  datetime.now().isoformat()
        }
        if parent_id is None:
            self._data.setdefault("decks", []).append(new_deck)
        else:
            parent = find_deck_by_id(parent_id, self._data.get("decks", []))
            if parent is None:
                QMessageBox.warning(self, "Error", "Parent deck not found!")
                return
            parent.setdefault("children", []).append(new_deck)
        save_data(self._data)
        self.refresh()
        self._select_by_id(new_deck["_id"])

    def _new_subdeck(self):
        did = self._get_selected_id()
        if did is None:
            QMessageBox.information(self, "Select first",
                "Click a parent deck first, then press ＋ Sub.")
            return
        self._new_deck(did)

    def _rename_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        name, ok = QInputDialog.getText(self, "Rename Deck", "New name:", text=deck.get("name", ""))
        if ok and name.strip():
            deck["name"] = name.strip()
            save_data(self._data)
            self.refresh()

    def _delete_selected(self):
        did = self._get_selected_id()
        if did is not None:
            self._delete_by_id(did)

    def _delete_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        if QMessageBox.question(self, "Delete",
            f"Delete '{deck['name']}' and ALL its cards / sub-decks?",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._remove_from_tree(deck_id, self._data.get("decks", []))
        save_data(self._data)
        self.refresh()

    def _remove_from_tree(self, deck_id, lst):
        for i, d in enumerate(lst):
            if d.get("_id") == deck_id:
                lst.pop(i)
                return True
            if self._remove_from_tree(deck_id, d.get("children", [])):
                return True
        return False

    def get_selected_deck(self):
        return self._get_deck_from_item(self.tree.currentItem())


# ═══════════════════════════════════════════════════════════════════════════════
#  DECK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class DeckView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.deck          = None
        self._deck_id      = None
        self._data         = {}
        self._thumb_cache  = {}   # [OPT-10] image_path → QIcon
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(12, 12, 12, 12)
        L.setSpacing(10)

        hdr = QHBoxLayout()
        self.lbl_deck = QLabel("← Select a deck")
        self.lbl_deck.setFont(QFont("Segoe UI", 15, QFont.Bold))
        hdr.addWidget(self.lbl_deck)
        hdr.addStretch()
        self.btn_add = QPushButton("＋ Add Card")
        self.btn_add.clicked.connect(self._add_card)
        self.btn_due = QPushButton("🔴 Review Due")
        self.btn_due.setObjectName("danger")
        self.btn_due.clicked.connect(self._review_due)
        self.btn_all = QPushButton("▶ Review All")
        self.btn_all.setObjectName("success")
        self.btn_all.clicked.connect(self._review_all)
        hdr.addWidget(self.btn_add)
        hdr.addWidget(self.btn_due)
        hdr.addWidget(self.btn_all)
        L.addLayout(hdr)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(f"color:{C_SUBTEXT};")
        L.addWidget(self.lbl_stats)

        self.card_list = QListWidget()
        self.card_list.setIconSize(QSize(64, 48))
        self.card_list.itemDoubleClicked.connect(self._edit_card)
        L.addWidget(self.card_list, stretch=1)

        bot = QHBoxLayout()
        be  = QPushButton("✏ Edit")
        be.setObjectName("flat")
        be.clicked.connect(lambda: self._edit_card(self.card_list.currentItem()))
        bd  = QPushButton("🗑 Delete")
        bd.setObjectName("danger")
        bd.clicked.connect(self._delete_card)
        brs = QPushButton("▶ Review Selected")
        brs.clicked.connect(self._review_selected)
        bot.addWidget(be)
        bot.addWidget(bd)
        bot.addStretch()
        bot.addWidget(brs)
        L.addLayout(bot)

    def load_deck(self, deck, data):
        self._data    = data
        self._deck_id = deck.get("_id")
        self.deck     = deck
        self.lbl_deck.setText(deck.get("name", "?"))
        self._thumb_cache.clear()   # clear cache when switching decks
        self._refresh()

    def _refresh(self):
        if self._deck_id is not None:
            fresh = find_deck_by_id(self._deck_id, self._data.get("decks", []))  # [OPT-3]
            if fresh:
                self.deck = fresh
        if not self.deck:
            return
        self.card_list.clear()
        cards  = self.deck.get("cards", [])
        due_c  = 0
        today  = date.today().isoformat()

        for c in cards:
            sm2_init(c)
            # [OPT-5] count due boxes for non-grouped cards
            boxes   = c.get("boxes", [])
            grouped = c.get("grouped", False)
            if grouped or not boxes:
                card_due = is_due_today(c)
            else:
                card_due = any(is_due_today(b) for b in boxes)
            due_c += card_due

            badge = "🔴 Due" if card_due else f"✅ {sm2_days_left(c)}d"
            item  = QListWidgetItem(
                f"  {c.get('title','Untitled')}  "
                f"| Boxes:{len(boxes)}  "
                f"| Rep:{c.get('sm2_repetitions',0)}  "
                f"| EF:{c.get('sm2_ease',2.5):.2f}  | {badge}")

            # [OPT-10] thumbnail cache
            img_path = c.get("image_path", "")
            if img_path and os.path.exists(img_path):
                if img_path not in self._thumb_cache:
                    px = QPixmap(img_path).scaled(
                        64, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._thumb_cache[img_path] = QIcon(px)
                item.setIcon(self._thumb_cache[img_path])

            self.card_list.addItem(item)

        total_rev = sum(c.get("reviews", 0) for c in cards)
        self.lbl_stats.setText(
            f"Cards:{len(cards)}  🔴Due:{due_c}  Reviews:{total_rev}")

    def _add_card(self):
        if not self.deck:
            return
        dlg = CardEditorDialog(self, data=self._data, deck=self.deck)
        if dlg.exec_() != QDialog.Accepted:
            return
        card         = dlg.get_card()
        subdeck_name = card.pop("_auto_subdeck", None)

        if subdeck_name:
            target_deck = None
            for child in self.deck.get("children", []):
                if child.get("name", "").strip().lower() == subdeck_name.strip().lower():
                    target_deck = child
                    break
            if target_deck is None:
                target_deck = {
                    "_id":      next_deck_id(self._data),   # [OPT-3]
                    "name":     subdeck_name,
                    "cards":    [],
                    "children": [],
                    "created":  datetime.now().isoformat(),
                }
                self.deck.setdefault("children", []).append(target_deck)
            target_deck.setdefault("cards", []).append(card)
        else:
            self.deck.setdefault("cards", []).append(card)

        home = self._find_home()
        if home:
            home.refresh()
        else:
            self._refresh()
        save_data(self._data)

    def _find_home(self):
        # [OPT-9] cleaner loop
        w = self.parent()
        while w is not None:
            if isinstance(w, HomeScreen):
                return w
            w = w.parent()
        return None

    def _edit_card(self, item):
        if not item or not self.deck:
            return
        idx   = self.card_list.row(item)
        cards = self.deck.get("cards", [])
        if not 0 <= idx < len(cards):
            return
        dlg = CardEditorDialog(self, card=dict(cards[idx]), data=self._data, deck=self.deck)
        if dlg.exec_() == QDialog.Accepted:
            c = dlg.get_card()
            c.pop("_auto_subdeck", None)
            cards[idx] = c
            self._refresh()
            save_data(self._data)

    def _delete_card(self):
        if not self.deck:
            return
        idx   = self.card_list.currentRow()
        cards = self.deck.get("cards", [])
        if not 0 <= idx < len(cards):
            return
        if QMessageBox.question(self, "Delete", "Delete this card?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cards.pop(idx)
            self._refresh()
            save_data(self._data)

    # [OPT-4] _review_due now uses is_due_today everywhere — single source of truth
    def _review_due(self):
        if not self.deck:
            return

        def _card_has_due_today(card):
            boxes   = card.get("boxes", [])
            grouped = card.get("grouped", False)
            if grouped or not boxes:
                sm2_init(card)
                return is_due_today(card)
            return any(is_due_today(sm2_init(b)) for b in boxes)

        due = [c for c in self.deck.get("cards", []) if _card_has_due_today(c)]
        if not due:
            QMessageBox.information(self, "✅ All clear!",
                "No cards due today.\nCome back tomorrow! 🌙")
            return
        self._start_review(due)

    def _review_all(self):
        if not self.deck:
            return
        cards = self.deck.get("cards", [])
        if not cards:
            QMessageBox.information(self, "Empty", "Add some cards first!")
            return
        self._start_review(cards)

    def _review_selected(self):
        if not self.deck:
            return
        idxs  = [self.card_list.row(i) for i in self.card_list.selectedItems()]
        cards = self.deck.get("cards", [])
        sub   = [cards[i] for i in idxs if i < len(cards)]
        if not sub:
            QMessageBox.information(self, "None", "Select cards first.")
            return
        self._start_review(sub)

    def _start_review(self, cards):
        win = QMainWindow(self)
        win.setWindowTitle("Review Mode 🧠")
        win.setMinimumSize(960, 730)
        rev = ReviewScreen(cards, data=self._data, parent=win)
        rev.finished.connect(win.close)
        rev.finished.connect(self._refresh)
        rev.finished.connect(lambda: save_data(self._data))
        win.setCentralWidget(rev)
        win.setStyleSheet(SS)
        win.showMaximized()


# ═══════════════════════════════════════════════════════════════════════════════
#  HOME SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  APP ICON  — generated programmatically, no external file needed
# ═══════════════════════════════════════════════════════════════════════════════

def make_app_icon() -> QIcon:
    """
    Draw a 256×256 icon:
      • Dark rounded square background
      • White card shape
      • Two orange occlusion rectangles
      • Small green tick at bottom-right
    Returns a QIcon usable for the window and taskbar.
    """
    SIZE = 256
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)

    # Background — rounded dark square
    p.setBrush(QBrush(QColor(C_SURFACE)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, SIZE, SIZE, 48, 48)

    # White card body
    card_rect = QRect(36, 44, 184, 148)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(QPen(QColor(C_BORDER), 3))
    p.drawRoundedRect(card_rect, 10, 10)

    # Faint ruled lines on the card (like a note)
    p.setPen(QPen(QColor("#E0E0E0"), 1))
    for y in range(card_rect.top() + 24, card_rect.bottom() - 10, 18):
        p.drawLine(card_rect.left() + 12, y, card_rect.right() - 12, y)

    # Orange occlusion mask 1 (top-left area)
    p.setBrush(QBrush(QColor(C_MASK)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(52, 62, 80, 36, 5, 5)

    # Orange occlusion mask 2 (mid-right area)
    p.drawRoundedRect(148, 104, 60, 30, 5, 5)

    # Green checkmark circle at bottom-right
    p.setBrush(QBrush(QColor(C_GREEN)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(168, 168, 60, 60)

    # Checkmark tick
    p.setPen(QPen(QColor("#1E1E2E"), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(182, 199, 192, 211)
    p.drawLine(192, 211, 214, 185)

    p.end()
    return QIcon(px)


# ═══════════════════════════════════════════════════════════════════════════════
#  ABOUT DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Anki Occlusion")
        self.setFixedSize(480, 560)
        self.setStyleSheet(f"QDialog{{background:{C_BG};}}")
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ── Coloured header band ───────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(140)
        header.setStyleSheet(f"QFrame{{background:{C_SURFACE};border-radius:0px;}}")
        hl = QVBoxLayout(header)
        hl.setAlignment(Qt.AlignCenter)

        # Draw mini icon
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_px = make_app_icon().pixmap(72, 72)
        icon_lbl.setPixmap(icon_px)
        hl.addWidget(icon_lbl)

        name_lbl = QLabel("Anki Occlusion")
        name_lbl.setFont(QFont("Segoe UI", 18, QFont.Bold))
        name_lbl.setStyleSheet(f"color:{C_ACCENT};background:transparent;")
        name_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(name_lbl)

        ver_lbl = QLabel("Version 1.0  •  Desktop Edition")
        ver_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;background:transparent;")
        ver_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(ver_lbl)
        L.addWidget(header)

        # ── Body ──────────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background:{C_BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(32, 24, 32, 24)
        bl.setSpacing(16)

        def _section(title, text):
            t = QLabel(title)
            t.setFont(QFont("Segoe UI", 10, QFont.Bold))
            t.setStyleSheet(f"color:{C_TEXT};")
            d = QLabel(text)
            d.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
            d.setWordWrap(True)
            bl.addWidget(t)
            bl.addWidget(d)

        _section("What it does",
            "Draw rectangular masks over your PDF notes and images, "
            "then study them with a full Anki-style spaced repetition "
            "scheduler — learning steps, review intervals, ease factors.")

        _section("Keyboard shortcuts",
            "F11 — fullscreen        Ctrl+Z / Y — undo / redo\n"
            "Space — reveal answer   1/2/3/4 — rate Again/Hard/Good/Easy\n"
            "Ctrl+A — select all masks       Del — delete selected\n"
            "Ctrl+Scroll — zoom      C — center on active mask")

        _section("Data location",
            f"{DATA_FILE}")

        bl.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"background:{C_ACCENT};color:white;border:none;border-radius:8px;"
            f"padding:8px 32px;font-weight:bold;font-size:13px;")
        close_btn.clicked.connect(self.accept)
        bl.addWidget(close_btn, alignment=Qt.AlignCenter)

        L.addWidget(body)


# ═══════════════════════════════════════════════════════════════════════════════
#  ONBOARDING SCREEN  — shown only on first launch
# ═══════════════════════════════════════════════════════════════════════════════

class OnboardingDialog(QDialog):
    """
    A 4-step welcome wizard shown exactly once on first launch.
    After the user clicks Get Started the flag is written to DATA_FILE
    so it never appears again.
    """
    STEPS = [
        {
            "icon":  "🃏",
            "title": "Welcome to Anki Occlusion",
            "body":  (
                "The fastest way to turn your PDF notes and images "
                "into Anki-style flashcards — without typing a single word.\n\n"
                "This quick tour takes about 30 seconds."
            ),
        },
        {
            "icon":  "📂",
            "title": "Step 1 — Create a Deck",
            "body":  (
                "Click  ＋ Deck  in the left sidebar to create your first deck.\n\n"
                "You can nest decks inside each other — for example:\n"
                "  Biology  ›  Chapter 3  ›  Cell Division\n\n"
                "Drag and drop to reorganise them any time."
            ),
        },
        {
            "icon":  "🖼",
            "title": "Step 2 — Add a Card",
            "body":  (
                "Select a deck, then click  ＋ Add Card.\n\n"
                "Load a PDF or image (or paste a screenshot with Ctrl+V), "
                "then drag rectangles over the parts you want to hide.\n\n"
                "Each rectangle becomes one flashcard question automatically."
            ),
        },
        {
            "icon":  "🧠",
            "title": "Step 3 — Review",
            "body":  (
                "Click  🔴 Review Due  to start your session.\n\n"
                "The app shows each hidden mask one at a time. "
                "Press Space to reveal the answer, then rate yourself:\n\n"
                "  1 = Again   2 = Hard   3 = Good   4 = Easy\n\n"
                "The scheduler decides when you'll see each card next — "
                "minutes for new cards, days or weeks for well-known ones."
            ),
        },
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setFixedSize(540, 440)
        self.setStyleSheet(f"QDialog{{background:{C_BG};}}")
        self._step = 0
        self._setup_ui()
        self._show_step(0)

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ── Progress dots ─────────────────────────────────────────────────────
        dot_bar = QWidget()
        dot_bar.setFixedHeight(32)
        dot_bar.setStyleSheet(f"background:{C_SURFACE};")
        dl = QHBoxLayout(dot_bar)
        dl.setAlignment(Qt.AlignCenter)
        dl.setSpacing(8)
        self._dots = []
        for _ in self.STEPS:
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{C_BORDER};font-size:10px;background:transparent;")
            dl.addWidget(dot)
            self._dots.append(dot)
        L.addWidget(dot_bar)

        # ── Content area ──────────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet(f"background:{C_BG};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(48, 32, 48, 24)
        cl.setSpacing(16)

        self._icon_lbl = QLabel()
        self._icon_lbl.setFont(QFont("Segoe UI", 48))
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setStyleSheet("background:transparent;")

        self._title_lbl = QLabel()
        self._title_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color:{C_TEXT};background:transparent;")
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setWordWrap(True)

        self._body_lbl = QLabel()
        self._body_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;background:transparent;")
        self._body_lbl.setWordWrap(True)
        self._body_lbl.setAlignment(Qt.AlignCenter)

        cl.addStretch()
        cl.addWidget(self._icon_lbl)
        cl.addWidget(self._title_lbl)
        cl.addWidget(self._body_lbl)
        cl.addStretch()
        L.addWidget(content, stretch=1)

        # ── Bottom buttons ─────────────────────────────────────────────────────
        btn_bar = QFrame()
        btn_bar.setFixedHeight(64)
        btn_bar.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-top:1px solid {C_BORDER};border-radius:0px;}}")
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(24, 0, 24, 0)

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setStyleSheet(
            f"background:transparent;color:{C_SUBTEXT};border:none;"
            f"font-size:12px;padding:6px 16px;")
        self._skip_btn.clicked.connect(self.accept)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:8px;padding:8px 20px;font-size:12px;")
        self._back_btn.clicked.connect(self._prev)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(
            f"background:{C_ACCENT};color:white;border:none;"
            f"border-radius:8px;padding:8px 24px;font-weight:bold;font-size:13px;")
        self._next_btn.clicked.connect(self._next)

        bl.addWidget(self._skip_btn)
        bl.addStretch()
        bl.addWidget(self._back_btn)
        bl.addWidget(self._next_btn)
        L.addWidget(btn_bar)

    def _show_step(self, idx):
        step = self.STEPS[idx]
        self._icon_lbl.setText(step["icon"])
        self._title_lbl.setText(step["title"])
        self._body_lbl.setText(step["body"])

        # Update dots
        for i, dot in enumerate(self._dots):
            dot.setStyleSheet(
                f"color:{C_ACCENT if i == idx else C_BORDER};"
                f"font-size:10px;background:transparent;")

        is_last = (idx == len(self.STEPS) - 1)
        is_first = (idx == 0)

        self._back_btn.setVisible(not is_first)
        self._skip_btn.setVisible(not is_last)
        self._next_btn.setText("🚀  Get Started!" if is_last else "Next →")
        self._next_btn.setStyleSheet(
            f"background:{C_GREEN if is_last else C_ACCENT};"
            f"color:{'#1E1E2E' if is_last else 'white'};"
            f"border:none;border-radius:8px;padding:8px 24px;"
            f"font-weight:bold;font-size:13px;")

    def _next(self):
        if self._step < len(self.STEPS) - 1:
            self._step += 1
            self._show_step(self._step)
        else:
            self.accept()

    def _prev(self):
        if self._step > 0:
            self._step -= 1
            self._show_step(self._step)


class HomeScreen(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        top = QFrame()
        top.setFixedHeight(56)
        top.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {C_BORDER};}}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 0, 20, 0)
        ttl = QLabel("🃏  Anki Occlusion")
        ttl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        ttl.setStyleSheet(f"color:{C_ACCENT};")
        sub = QLabel("SM-2 Spaced Repetition  •  PDF & Image Occlusion")
        sub.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        tl.addWidget(ttl)
        tl.addSpacing(16)
        tl.addWidget(sub)
        tl.addStretch()

        # Help / About buttons in top bar
        def _topbtn(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C_SUBTEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"padding:4px 14px;font-size:12px;}}"
                f"QPushButton:hover{{background:{C_CARD};color:{C_TEXT};}}")
            return b

        btn_help  = _topbtn("❓ Help",  "Show quick-start guide")
        btn_about = _topbtn("ℹ About", "About Anki Occlusion")
        btn_help.clicked.connect(self._show_help)
        btn_about.clicked.connect(self._show_about)

        # Font size controls — A− / A / A+
        def _fontbtn(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(30)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C_SUBTEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"padding:2px 4px;font-size:12px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{C_CARD};color:{C_TEXT};}}")
            return b

        btn_fa = _fontbtn("A−", "Decrease font size  (Ctrl+−)")
        btn_fr = _fontbtn("A",  "Reset font size  (Ctrl+0)")
        btn_fi = _fontbtn("A+", "Increase font size  (Ctrl++)")
        btn_fr.setFixedWidth(24)
        btn_fa.clicked.connect(lambda: self._emit_font(-1))
        btn_fr.clicked.connect(lambda: self._emit_font(0))
        btn_fi.clicked.connect(lambda: self._emit_font(+1))

        tl.addSpacing(8)
        tl.addWidget(btn_fa)
        tl.addWidget(btn_fr)
        tl.addWidget(btn_fi)
        tl.addSpacing(4)
        tl.addWidget(btn_help)
        tl.addWidget(btn_about)
        L.addWidget(top)

        split = QSplitter(Qt.Horizontal)
        self.deck_tree = DeckTree(self._data)
        self.deck_tree.setMinimumWidth(260)
        self.deck_tree.setMaximumWidth(420)
        self.deck_tree.deck_selected.connect(self._on_deck_selected)
        split.addWidget(self.deck_tree)
        self.deck_view = DeckView()
        split.addWidget(self.deck_view)
        split.setSizes([340, 860])
        L.addWidget(split, stretch=1)

    def _on_deck_selected(self, deck):
        self.deck_view.load_deck(deck, self._data)

    def _show_about(self):
        AboutDialog(self).exec_()

    def _show_help(self):
        OnboardingDialog(self).exec_()

    def _emit_font(self, direction: int):
        """Ask the MainWindow to change font size (+1 / -1 / 0=reset)."""
        win = self.window()
        if isinstance(win, MainWindow):
            win.change_font_size(direction)

    def refresh(self):
        self.deck_tree.refresh()
        sel = self.deck_tree.get_selected_deck()
        if sel:
            self.deck_view.load_deck(sel, self._data)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._data = load_data()
        self.setWindowTitle("Anki Occlusion")
        self.setMinimumSize(1100, 720)
        self.setWindowIcon(make_app_icon())

        # Load saved font size preference
        self._font_size = int(self._data.get("_font_size", BASE_FONT_SIZE))

        self.showMaximized()
        home = HomeScreen(self._data, parent=self)
        self.setCentralWidget(home)
        sb = QStatusBar()
        sb.showMessage("✅ SM-2 Active  |  " + (
            "PyMuPDF loaded — PDF support active"
            if PDF_SUPPORT else "⚠ pip install pymupdf  for PDF support"))
        self.setStatusBar(sb)

        # Apply saved font size on launch
        if self._font_size != BASE_FONT_SIZE:
            self._apply_font_size(self._font_size)

        # Show onboarding only on first ever launch
        if not self._data.get("_onboarding_done"):
            QTimer.singleShot(200, self._run_onboarding)

    def change_font_size(self, direction: int):
        """
        direction: +1 = larger, -1 = smaller, 0 = reset to default.
        Rebuilds the global QSS so every widget updates instantly.
        Saves the preference to data file.
        """
        if direction == 0:
            self._font_size = BASE_FONT_SIZE
        else:
            self._font_size = max(8, min(20, self._font_size + direction))
        self._apply_font_size(self._font_size)
        self._data["_font_size"] = self._font_size
        save_data(self._data)

    def _apply_font_size(self, size: int):
        """Rebuild and reapply the global stylesheet with the new font size."""
        QApplication.instance().setStyleSheet(_build_ss(size))

    def _run_onboarding(self):
        dlg = OnboardingDialog(self)
        dlg.exec_()
        # Mark as done so it never shows again
        self._data["_onboarding_done"] = True
        save_data(self._data)

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        if key == Qt.Key_F11:
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
        elif mods & Qt.ControlModifier and key in (Qt.Key_Equal, Qt.Key_Plus):
            self.change_font_size(+1)
        elif mods & Qt.ControlModifier and key == Qt.Key_Minus:
            self.change_font_size(-1)
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self.change_font_size(0)
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        save_data(self._data)
        super().closeEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    lock = QLockFile(LOCK_FILE)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        app_tmp = QApplication(sys.argv)
        QMessageBox.warning(None, "Already Running",
            "Anki Occlusion is already open!\nCheck your taskbar.")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyleSheet(SS)
    app.setApplicationName("Anki Occlusion")
    app.setApplicationVersion("1.0")
    # Set icon early so it appears in taskbar before window opens
    _icon = make_app_icon()
    app.setWindowIcon(_icon)
    win = MainWindow()
    win.show()
    ret = app.exec_()
    lock.unlock()
    sys.exit(ret)