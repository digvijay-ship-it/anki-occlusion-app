"""
Anki Occlusion — PDF & Image Flashcard App
Fixes:
  1. PDF crash fixed — safe page rendering with proper QImage lifetime
  2. Single instance lock — only one window allowed via QLockFile
  3. Nested decks — tree-based deck browser (parent > child)
  4. Proper Anki-style Image Occlusion editor with mask panel
+ SM-2 Spaced Repetition
"""

import sys, os, json, copy, tempfile
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QStackedWidget, QFrame, QScrollArea, QInputDialog, QMessageBox,
    QSplitter, QStatusBar, QProgressBar, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QGroupBox, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QAbstractItemView, QMenu, QAction
)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QPointF, pyqtSignal, QLockFile, QTimer
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QImage, QFont, QCursor, QIcon,
    QBrush, QPolygon, QPainterPath
)

try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE  = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")
DATA_FILE  = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.json")

# ═══════════════════════════════════════════════════════════════════════════════
#  SM-2 ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def sm2_init(c):
    c.setdefault("sm2_interval",    1)
    c.setdefault("sm2_repetitions", 0)
    c.setdefault("sm2_ease",        2.5)
    c.setdefault("sm2_due",         date.today().isoformat())
    c.setdefault("sm2_last_quality",-1)
    return c

def sm2_update(c, quality):
    c = sm2_init(c)
    ef, rep, iv = c["sm2_ease"], c["sm2_repetitions"], c["sm2_interval"]
    if quality >= 3:
        iv = 1 if rep==0 else 6 if rep==1 else max(1, round(iv*ef))
        rep += 1
    else:
        rep, iv = 0, 1
    ef = max(1.3, round(ef + 0.1 - (5-quality)*(0.08+(5-quality)*0.02), 4))
    c.update({"sm2_interval":iv,"sm2_repetitions":rep,"sm2_ease":ef,
              "sm2_last_quality":quality,"reviews":c.get("reviews",0)+1,
              "sm2_due":(date.today()+timedelta(days=iv)).isoformat()})
    return c

def sm2_is_due(c):
    due_str = c.get("sm2_due", "")
    if not due_str:
        return True   # no due date = never scheduled = always due
    try:
        return date.fromisoformat(due_str) <= date.today()
    except:
        return True

def sm2_days_left(c):
    try:    return max(0,(date.fromisoformat(c.get("sm2_due",""))-date.today()).days)
    except: return 0

def sm2_simulate(c, q):
    s = copy.deepcopy(c); sm2_update(s,q); return s["sm2_interval"]

def sm2_badge(c):
    rep=c.get("sm2_repetitions",0); iv=c.get("sm2_interval",1); ef=c.get("sm2_ease",2.5)
    if rep==0:          return "🆕 New"
    if sm2_is_due(c):   return f"🔴 Due  iv:{iv}d  EF:{ef:.2f}"
    return f"✅ {sm2_days_left(c)}d  iv:{iv}d  EF:{ef:.2f}"

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════════════

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except: pass
    return {"decks":[]}

def save_data(data):
    with open(DATA_FILE,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
#  APP-LEVEL UNDO / REDO  — snapshots entire data dict on every mutating action
# ═══════════════════════════════════════════════════════════════════════════════

class AppHistory:
    """
    Global undo/redo for ALL app actions (deck CRUD, card edits, reviews).
    Usage:
        AppHistory.push(data)          # before any mutation
        AppHistory.undo(data, callback) # restore + call callback() to refresh UI
        AppHistory.redo(data, callback)
    """
    _undo : list = []
    _redo : list = []
    MAX   : int  = 50

    @classmethod
    def push(cls, data: dict):
        cls._undo.append(copy.deepcopy(data))
        if len(cls._undo) > cls.MAX: cls._undo.pop(0)
        cls._redo.clear()

    @classmethod
    def undo(cls, data: dict, refresh_cb):
        if not cls._undo: return False
        cls._redo.append(copy.deepcopy(data))
        snap = cls._undo.pop()
        data.clear(); data.update(snap)
        save_data(data)
        refresh_cb()
        return True

    @classmethod
    def redo(cls, data: dict, refresh_cb):
        if not cls._redo: return False
        cls._undo.append(copy.deepcopy(data))
        snap = cls._redo.pop()
        data.clear(); data.update(snap)
        save_data(data)
        refresh_cb()
        return True

    @classmethod
    def can_undo(cls): return bool(cls._undo)

    @classmethod
    def can_redo(cls): return bool(cls._redo)

# ═══════════════════════════════════════════════════════════════════════════════
#  PDF HELPER  — safe rendering, returns list[QPixmap]
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_page_to_pixmap(page, mat):
    """
    Convert a single fitz page to QPixmap via a temp PNG file.
    This is the most reliable method across ALL PyMuPDF versions and avoids
    every buffer-lifetime / memoryview issue with QImage.
    """
    import tempfile, os
    pix = page.get_pixmap(matrix=mat, alpha=False)
    # Write to a temp PNG file, then load with QPixmap (which handles its own memory)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
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
    """
    Render every page of a PDF to a list of QPixmap.
    Returns (pages_list, error_string_or_None).
    """
    pages  = []
    errors = []
    if not PDF_SUPPORT:
        return pages, "PyMuPDF not installed — run: pip install pymupdf"
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            return pages, "PDF is password-protected / encrypted."
        mat = fitz.Matrix(zoom, zoom)
        for page_num in range(len(doc)):
            try:
                page = doc.load_page(page_num)
                qpx  = pdf_page_to_pixmap(page, mat)
                if qpx.isNull():
                    errors.append(f"Page {page_num+1}: QPixmap is null after conversion")
                else:
                    pages.append(qpx)
            except Exception as page_err:
                errors.append(f"Page {page_num+1}: {page_err}")
        doc.close()
    except Exception as e:
        return pages, str(e)

    err_str = ("\n".join(errors)) if errors and not pages else None
    return pages, err_str

def pdf_to_combined_pixmap(path: str, zoom: float = 1.5):
    """
    Render all pages of a PDF and stitch them into ONE tall QPixmap
    with a visible separator line between pages.
    Returns (combined_QPixmap, error_string_or_None, page_heights_list).
    page_heights_list[i] = y offset where page i starts, useful for debug.
    """
    pages, err = pdf_to_pixmaps(path, zoom)
    if not pages:
        return QPixmap(), err, []

    GAP         = 12          # px gap between pages
    SEP_COLOR   = QColor("#45475A")
    total_w     = max(p.width()  for p in pages)
    total_h     = sum(p.height() for p in pages) + GAP * (len(pages) - 1)

    combined = QPixmap(total_w, total_h)
    combined.fill(QColor("#1E1E2E"))   # dark background fills gaps

    painter = QPainter(combined)
    y = 0
    offsets = []
    for i, px in enumerate(pages):
        offsets.append(y)
        painter.drawPixmap(0, y, px)
        y += px.height()
        if i < len(pages) - 1:
            # Draw a subtle separator line
            painter.setPen(QPen(SEP_COLOR, 2))
            painter.drawLine(0, y + GAP // 2, total_w, y + GAP // 2)
            y += GAP
    painter.end()
    return combined, None, offsets

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

SS = f"""
QMainWindow,QDialog{{background:{C_BG};color:{C_TEXT};}}
QWidget{{background:{C_BG};color:{C_TEXT};font-family:'Segoe UI';font-size:13px;}}
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
QGroupBox{{color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;margin-top:8px;padding-top:4px;}}
QMenu{{background:{C_SURFACE};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;}}
QMenu::item:selected{{background:{C_ACCENT};}}
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  OCCLUSION CANVAS
# ═══════════════════════════════════════════════════════════════════════════════

class OcclusionCanvas(QLabel):
    """
    The main drawing surface.
    edit mode  : drag to draw boxes
    review mode: click box to reveal
    """
    boxes_changed = pyqtSignal(list)

    # Anki-style mask colours (light yellow fill, dark border)
    MASK_FILL   = QColor(255, 255, 153)   # light yellow
    MASK_ALPHA  = 200
    MASK_BORDER = QColor(30, 30, 30)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._px      : QPixmap = None
        self._boxes   : list    = []
        self._drawing           = False   # drawing a new box
        self._start             = QPoint()
        self._live              = QRect()
        self._mode              = "edit"
        self._scale             = 1.0
        self._selected_idx      = -1
        self._selected_indices  = set()
        self._target_idx        = -1
        self._masks_visible     = True
        self._undo_stack        = []
        self._redo_stack        = []
        # drag/resize state
        self._drag_mode         = None    # None | "move" | "resize"
        self._drag_box_idx      = -1
        self._drag_start_ip     = QPoint()
        self._drag_orig_rect    = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)   # so Del key works when canvas is clicked

    # ── undo / redo ──────────────────────────────────────────────────────────

    def _snap(self):
        """Save current boxes to undo stack."""
        import copy
        self._undo_stack.append(copy.deepcopy(self._serialize()))
        if len(self._undo_stack) > 60: self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _serialize(self):
        out = []
        for b in self._boxes:
            r = b["rect"]
            out.append({"rect": [r.x(),r.y(),r.width(),r.height()],
                        "label": b.get("label",""),
                        "revealed": b.get("revealed", False),
                        **{k: b[k] for k in ("sm2_interval","sm2_repetitions","sm2_ease",
                           "sm2_due","sm2_last_quality","box_id") if k in b}})
        return out

    def _restore(self, snap):
        self._boxes = [{"rect": QRect(b["rect"][0],b["rect"][1],b["rect"][2],b["rect"][3]),
                        "label": b.get("label",""),
                        "revealed": b.get("revealed", False),
                        **{k: b[k] for k in ("sm2_interval","sm2_repetitions","sm2_ease",
                           "sm2_due","sm2_last_quality","box_id") if k in b}}
                       for b in snap]

    def undo(self):
        if not self._undo_stack: return
        self._redo_stack.append(self._serialize())
        self._restore(self._undo_stack.pop())
        self._selected_idx = -1; self._selected_indices = set()
        self._redraw(); self.boxes_changed.emit(self.get_boxes())

    def redo(self):
        if not self._redo_stack: return
        self._undo_stack.append(self._serialize())
        self._restore(self._redo_stack.pop())
        self._selected_idx = -1; self._selected_indices = set()
        self._redraw(); self.boxes_changed.emit(self.get_boxes())

    def duplicate_selected(self):
        """Duplicate selected boxes, offset by 12px."""
        import copy
        idxs = self._selected_indices if self._selected_indices else (
               {self._selected_idx} if self._selected_idx >= 0 else set())
        if not idxs: return
        self._snap()
        new_sel = set()
        for i in sorted(idxs):
            b = copy.deepcopy(self._boxes[i])
            r = b["rect"]; b["rect"] = QRect(r.x()+12, r.y()+12, r.width(), r.height())
            b.pop("box_id", None)   # new box gets new id on save
            self._boxes.append(b)
            new_sel.add(len(self._boxes)-1)
        self._selected_indices = new_sel
        self._selected_idx = max(new_sel)
        self._redraw(); self.boxes_changed.emit(self.get_boxes())

    def toggle_masks_visible(self):
        """Show/hide all masks (eye button)."""
        self._masks_visible = not self._masks_visible
        self._redraw()

    def zoom_in(self):
        self._scale = min(self._scale * 1.25, 5.0)
        self._redraw()

    def zoom_out(self):
        self._scale = max(self._scale / 1.25, 0.2)
        self._redraw()

    def zoom_fit(self, viewport_w, viewport_h):
        if not self._px or self._px.isNull(): return
        sx = viewport_w  / max(self._px.width(),  1)
        sy = viewport_h / max(self._px.height(), 1)
        self._scale = min(sx, sy, 1.0)
        self._redraw()

    # ── public ───────────────────────────────────────────────────────────────

    def load_pixmap(self, px: QPixmap):
        if px is None or px.isNull():
            self._px = None
            self.clear()
            return
        self._px    = px
        self._boxes = []
        self._scale = 1.0
        self._fit()
        self._redraw()

    def set_boxes(self, boxes):
        self._boxes = [{"rect": QRect(b["rect"][0],b["rect"][1],
                                      b["rect"][2],b["rect"][3]),
                        "revealed": False,
                        "label": b.get("label","")}
                       for b in boxes]
        self._redraw()

    def set_boxes_with_state(self, boxes):
        """Like set_boxes but respects the 'revealed' field already set."""
        self._boxes = [{"rect": QRect(b["rect"][0],b["rect"][1],
                                      b["rect"][2],b["rect"][3]),
                        "revealed": b.get("revealed", False),
                        "label": b.get("label","")}
                       for b in boxes]
        self._redraw()

    def get_boxes(self):
        SM2_KEYS = ("sm2_interval","sm2_repetitions","sm2_ease","sm2_due","sm2_last_quality","box_id")
        result = []
        for b in self._boxes:
            d = {"rect":[b["rect"].x(),b["rect"].y(),
                         b["rect"].width(),b["rect"].height()],
                 "label":b.get("label","")}
            for k in SM2_KEYS:
                if k in b:
                    d[k] = b[k]
            result.append(d)
        return result

    def set_mode(self, mode):
        self._mode = mode
        for b in self._boxes: b["revealed"] = False
        self.setCursor(QCursor(Qt.PointingHandCursor if mode=="review" else Qt.CrossCursor))
        self._redraw()

    def reveal_all(self):
        for b in self._boxes: b["revealed"] = True
        self._redraw()

    def set_target_box(self, idx):
        """Mark which box is the current review target (painted green instead of orange)."""
        self._target_idx = idx
        self._redraw()

    def get_target_scaled_rect(self):
        """Return the scaled QRect of the target box, or None."""
        if 0 <= self._target_idx < len(self._boxes):
            return self._sr(self._boxes[self._target_idx]["rect"])
        return None

    def select_all(self):
        """Select all boxes (Ctrl+A)."""
        if not self._boxes: return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx = len(self._boxes) - 1
        self._redraw()

    def delete_selected_boxes(self):
        """Delete all currently selected boxes (Del key)."""
        if not hasattr(self, '_selected_indices') or not self._selected_indices:
            # Fall back to single selection
            if self._selected_idx >= 0:
                self.delete_box(self._selected_idx)
            return
        # Delete in reverse order so indices stay valid
        for i in sorted(self._selected_indices, reverse=True):
            if 0 <= i < len(self._boxes):
                self._boxes.pop(i)
        self._selected_indices = set()
        self._selected_idx = -1
        self._redraw()
        self.boxes_changed.emit(self.get_boxes())

    def delete_box(self, idx):
        if 0 <= idx < len(self._boxes):
            self._boxes.pop(idx); self._selected_idx=-1
            self._redraw(); self.boxes_changed.emit(self.get_boxes())

    def delete_last(self):
        self.delete_box(len(self._boxes)-1)

    def clear_all(self):
        self._boxes=[]; self._selected_idx=-1
        self._redraw(); self.boxes_changed.emit([])

    def highlight(self, idx):
        self._selected_idx = idx; self._redraw()

    def update_label(self, idx, text):
        if 0 <= idx < len(self._boxes):
            self._boxes[idx]["label"] = text; self._redraw()

    # ── internal ─────────────────────────────────────────────────────────────

    def _fit(self):
        # Don't try to read parent width — it may be 0 during initial layout
        # and causes zero-size pixmaps that crash QPainter.
        # Always render at natural size; the QScrollArea handles scrolling.
        self._scale = 1.0

    def _spx(self):
        if not self._px: return QPixmap()
        return self._px.scaled(int(self._px.width()*self._scale),
                               int(self._px.height()*self._scale),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _sr(self, r):
        return QRect(int(r.x()*self._scale), int(r.y()*self._scale),
                     int(r.width()*self._scale), int(r.height()*self._scale))

    def _redraw(self):
        if not self._px or self._px.isNull():
            return
        spx = self._spx()
        if spx.isNull():
            return
        canvas = QPixmap(spx)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing)

        # Anki yellow fill (semi-transparent)
        anki_fill = QColor(self.MASK_FILL); anki_fill.setAlpha(self.MASK_ALPHA)

        for i, b in enumerate(self._boxes):
            sr  = self._sr(b["rect"])
            lbl = b.get("label") or f"#{i+1}"
            sel = (i == self._selected_idx) or (
                  hasattr(self,"_selected_indices") and i in self._selected_indices)

            if self._mode == "review":
                if not b["revealed"]:
                    if not getattr(self, "_masks_visible", True):
                        pass   # hidden — show nothing
                    elif i == self._target_idx:
                        # Current target — green
                        p.fillRect(sr, QColor(C_GREEN))
                        p.setPen(QPen(QColor("#1E1E2E"), 3))
                        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                        p.drawText(sr, Qt.AlignCenter, lbl)
                    else:
                        # Other hidden — Anki yellow
                        p.fillRect(sr, anki_fill)
                        p.setPen(QPen(self.MASK_BORDER, 2))
                        p.drawRect(sr)
                        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
                        p.drawText(sr, Qt.AlignCenter, lbl)
                else:
                    # Revealed — green border only
                    p.setPen(QPen(QColor(C_GREEN), 2))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(sr)

            else:  # edit mode
                if sel:
                    sel_fill = QColor(100, 180, 255, 160)
                    p.fillRect(sr, sel_fill)
                    p.setPen(QPen(QColor("#6495ED"), 2, Qt.DashLine))
                    p.drawRect(sr)
                    p.setPen(QPen(QColor("#6495ED"), 1))
                    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    p.drawText(sr, Qt.AlignCenter, lbl)
                    # Resize handle — solid white square with blue border, bottom-right
                    h = self._handle_rect(sr)
                    p.setPen(QPen(QColor("#6495ED"), 2))
                    p.setBrush(QBrush(Qt.white))
                    p.drawRect(h)
                    # Corner triangle inside handle to make it obvious
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor("#6495ED")))
                    tri = QPolygon([
                        QPoint(h.right()-1, h.top()+3),
                        QPoint(h.right()-1, h.bottom()-1),
                        QPoint(h.left()+3,  h.bottom()-1),
                    ])
                    p.drawPolygon(tri)
                else:
                    # Anki-style: light yellow fill, dark border
                    p.fillRect(sr, anki_fill)
                    p.setPen(QPen(self.MASK_BORDER, 2))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(sr)
                    p.setFont(QFont("Segoe UI", 9))
                    p.drawText(sr, Qt.AlignCenter, lbl)

        # Live drawing preview
        if self._drawing and not self._live.isNull():
            sr = self._sr(self._live)
            prev = QColor(100, 149, 237, 100)
            p.fillRect(sr, prev)
            p.setPen(QPen(QColor("#6495ED"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(sr)

        p.end(); self.setPixmap(canvas); self.resize(canvas.size())

    def _ip(self, pos):
        return QPoint(int(pos.x()/self._scale), int(pos.y()/self._scale))

    def _handle_rect(self, sr):
        """Screen-space resize handle rect at bottom-right of a scaled rect."""
        return QRect(sr.right()-7, sr.bottom()-7, 14, 14)

    def _hit_handle(self, sr, screen_pos):
        """True if screen_pos is inside the resize handle of sr."""
        return self._handle_rect(sr).contains(screen_pos)

    # ── keyboard ─────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete or e.key() == Qt.Key_Backspace:
            self.delete_selected_boxes()
        elif e.key() == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.select_all()
        elif e.key() == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self.undo()
        elif e.key() == Qt.Key_Y and e.modifiers() & Qt.ControlModifier:
            self.redo()
        else:
            super().keyPressEvent(e)

    # ── mouse ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if not self._px: return
        self.setFocus()   # grab keyboard focus so Del works
        ip  = self._ip(e.pos())      # image-space point
        sp  = e.pos()                # screen-space point
        ctrl = bool(e.modifiers() & Qt.ControlModifier)

        if self._mode == "edit" and e.button() == Qt.LeftButton:
            # Check each box from top (last drawn) to bottom
            for i in range(len(self._boxes)-1, -1, -1):
                b  = self._boxes[i]
                sr = self._sr(b["rect"])

                # ── resize handle hit ──────────────────────────────────────
                if i == self._selected_idx and self._hit_handle(sr, sp):
                    self._snap()
                    self._drag_mode      = "resize"
                    self._drag_box_idx   = i
                    self._drag_start_ip  = ip
                    self._drag_orig_rect = QRect(b["rect"])
                    self.setCursor(Qt.SizeFDiagCursor)
                    return

                # ── box body hit ───────────────────────────────────────────
                if b["rect"].contains(ip):
                    if ctrl:
                        # Ctrl+click: toggle this box in multi-selection
                        if i in self._selected_indices:
                            self._selected_indices.discard(i)
                        else:
                            self._selected_indices.add(i)
                        self._selected_idx = i
                    else:
                        # Plain click: select only this box, clear multi
                        self._selected_indices = set()
                        self._selected_idx = i

                    # Start move drag
                    self._snap()
                    self._drag_mode     = "move"
                    self._drag_box_idx  = i
                    self._drag_start_ip = ip
                    # Store original rects for ALL selected boxes
                    sel_ids = self._selected_indices | {self._selected_idx}
                    self._drag_orig_rects = {
                        j: QRect(self._boxes[j]["rect"])
                        for j in sel_ids if 0 <= j < len(self._boxes)
                    }
                    self._redraw()
                    self.boxes_changed.emit(self.get_boxes())
                    return

            # Clicked empty space — start drawing a new box
            if not ctrl:
                self._selected_indices = set()
                self._selected_idx = -1
            self._drag_mode = None
            self._drawing = True
            self._start = ip
            self._live  = QRect()

        elif self._mode == "review" and e.button() == Qt.LeftButton:
            for b in self._boxes:
                if b["rect"].contains(ip) and not b["revealed"]:
                    b["revealed"] = True; self._redraw(); break

    def mouseMoveEvent(self, e):
        sp = e.pos()
        ip = self._ip(sp)

        if self._drag_mode == "move":
            dx = ip.x() - self._drag_start_ip.x()
            dy = ip.y() - self._drag_start_ip.y()
            for j, orig in self._drag_orig_rects.items():
                if 0 <= j < len(self._boxes):
                    self._boxes[j]["rect"] = QRect(
                        orig.x()+dx, orig.y()+dy, orig.width(), orig.height())
            self._redraw()
            return

        if self._drag_mode == "resize":
            idx  = self._drag_box_idx
            orig = self._drag_orig_rect
            dx   = ip.x() - self._drag_start_ip.x()
            dy   = ip.y() - self._drag_start_ip.y()
            new_w = max(12, orig.width()  + dx)
            new_h = max(12, orig.height() + dy)
            self._boxes[idx]["rect"] = QRect(orig.x(), orig.y(), new_w, new_h)
            self._redraw()
            return

        if self._drawing:
            self._live = QRect(self._start, ip).normalized()
            self._redraw()
            return

        # Cursor hint: change to resize cursor when hovering over handle
        if self._mode == "edit" and self._selected_idx >= 0:
            idx = self._selected_idx
            if 0 <= idx < len(self._boxes):
                sr = self._sr(self._boxes[idx]["rect"])
                if self._hit_handle(sr, sp):
                    self.setCursor(Qt.SizeFDiagCursor); return
        self.setCursor(Qt.CrossCursor if self._mode == "edit" else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton: return

        if self._drag_mode in ("move", "resize"):
            self._drag_mode = None
            self._drag_orig_rects = {}
            self._drag_orig_rect  = None
            self.setCursor(Qt.CrossCursor)
            self.boxes_changed.emit(self.get_boxes())
            return

        if self._drawing:
            self._drawing = False
            rect = QRect(self._start, self._ip(e.pos())).normalized()
            if rect.width() > 8 and rect.height() > 8:
                self._snap()
                self._boxes.append({"rect": rect, "revealed": False, "label": ""})
                self._selected_idx = len(self._boxes) - 1
                self._selected_indices = set()
                self._redraw()
                self.boxes_changed.emit(self.get_boxes())
            self._live = QRect()
            self._redraw()

    def resizeEvent(self, e):
        super().resizeEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  MASK PANEL  — right-side list of boxes (Anki-style)
# ═══════════════════════════════════════════════════════════════════════════════

class MaskPanel(QWidget):
    """
    Right panel — Anki-style layout matching the screenshot:
      ┌─────────────────────┐
      │  📋 Occlusion Masks │
      │  [list of masks]    │
      │─────────────────────│
      │  Label for mask:    │
      │  [input]            │
      │  [Delete] [ClearAll]│
      ├─────────────────────┤
      │  📝 Card Info       │
      │  Title / Tags /Notes│
      └─────────────────────┘
    """
    def __init__(self, canvas: OcclusionCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._canvas.boxes_changed.connect(self._refresh)
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        # ── TOP: Occlusion Masks section ──────────────────────────────────────
        mask_frame = QFrame()
        mask_frame.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border:none;"
            f"border-bottom:1px solid {C_BORDER};}}")
        mfl = QVBoxLayout(mask_frame); mfl.setContentsMargins(12,10,12,10); mfl.setSpacing(6)

        hdr = QLabel("📋  Occlusion Masks")
        hdr.setFont(QFont("Segoe UI", 11, QFont.Bold))
        hdr.setStyleSheet(f"color:{C_TEXT};background:transparent;border:none;")
        mfl.addWidget(hdr)

        self.list_w = QListWidget()
        self.list_w.setStyleSheet(f"""
            QListWidget {{
                background:{C_BG};
                border:1px solid {C_BORDER};
                border-radius:6px;
                padding:2px;
                font-size:13px;
            }}
            QListWidget::item {{
                padding:5px 8px;
                border-radius:4px;
                color:{C_TEXT};
            }}
            QListWidget::item:selected {{
                background:{C_ACCENT};
                color:white;
            }}
            QListWidget::item:hover:!selected {{
                background:{C_CARD};
            }}
        """)
        self.list_w.currentRowChanged.connect(self._on_select)
        mfl.addWidget(self.list_w, stretch=1)

        # Label editor
        lbl_e = QLabel("Label for selected mask:")
        lbl_e.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;background:transparent;border:none;")
        mfl.addWidget(lbl_e)
        self.inp_label = QLineEdit()
        self.inp_label.setPlaceholderText("e.g. Mitochondria")
        self.inp_label.setStyleSheet(
            f"background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:6px;font-size:13px;")
        self.inp_label.textChanged.connect(self._on_label_change)
        mfl.addWidget(self.inp_label)

        # Delete / Clear All buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        b_del = QPushButton("🗑  Delete")
        b_del.setStyleSheet(
            f"background:{C_RED};color:white;border:none;border-radius:6px;"
            f"padding:7px 12px;font-weight:bold;font-size:12px;")
        b_del.clicked.connect(self._delete_selected)
        b_clear = QPushButton("✕  Clear All")
        b_clear.setStyleSheet(
            f"background:{C_SURFACE};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:7px 12px;font-size:12px;")
        b_clear.clicked.connect(self._canvas.clear_all)
        btn_row.addWidget(b_del); btn_row.addWidget(b_clear)
        mfl.addLayout(btn_row)

        L.addWidget(mask_frame, stretch=2)

        # ── BOTTOM: Card Info section ─────────────────────────────────────────
        info_frame = QFrame()
        info_frame.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border:none;}}")
        ifl = QVBoxLayout(info_frame); ifl.setContentsMargins(12,10,12,10); ifl.setSpacing(8)

        info_hdr = QLabel("📝  Card Info")
        info_hdr.setFont(QFont("Segoe UI", 11, QFont.Bold))
        info_hdr.setStyleSheet(f"color:{C_TEXT};background:transparent;border:none;")
        ifl.addWidget(info_hdr)

        def _lbl(t):
            l = QLabel(t)
            l.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;background:transparent;border:none;")
            return l

        inp_ss = (f"background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER};"
                  f"border-radius:6px;padding:6px;font-size:13px;")

        self.inp_title = QLineEdit(); self.inp_title.setPlaceholderText("Card title…")
        self.inp_title.setStyleSheet(inp_ss)
        self.inp_tags  = QLineEdit(); self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_tags.setStyleSheet(inp_ss)
        self.inp_notes = QTextEdit(); self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setStyleSheet(inp_ss); self.inp_notes.setMaximumHeight(80)

        ifl.addWidget(_lbl("Title:"));  ifl.addWidget(self.inp_title)
        ifl.addWidget(_lbl("Tags:"));   ifl.addWidget(self.inp_tags)
        ifl.addWidget(_lbl("Notes:"));  ifl.addWidget(self.inp_notes)
        ifl.addStretch()
        L.addWidget(info_frame, stretch=1)

    # ── data access helpers for CardEditorDialog ──────────────────────────────
    def get_title(self):  return self.inp_title.text().strip()
    def get_tags(self):   return [t.strip() for t in self.inp_tags.text().split(",") if t.strip()]
    def get_notes(self):  return self.inp_notes.toPlainText()
    def set_title(self, v): self.inp_title.setText(v)
    def set_tags(self, v):  self.inp_tags.setText(", ".join(v))
    def set_notes(self, v): self.inp_notes.setPlainText(v)

    def _refresh(self, boxes):
        self.list_w.blockSignals(True)
        self.list_w.clear()
        for i, b in enumerate(boxes):
            lbl = b.get("label") or f"Mask #{i+1}"
            item = QListWidgetItem(f"  {lbl}")
            # Orange square icon for mask
            px = QPixmap(14,14); px.fill(QColor(C_MASK))
            item.setIcon(QIcon(px))
            self.list_w.addItem(item)
        self.list_w.blockSignals(False)
        sel = self._canvas._selected_idx
        if 0 <= sel < self.list_w.count():
            self.list_w.setCurrentRow(sel)
            box = self._canvas._boxes[sel]
            self.inp_label.blockSignals(True)
            self.inp_label.setText(box.get("label",""))
            self.inp_label.blockSignals(False)

    def _on_select(self, row):
        self._canvas.highlight(row)
        if 0 <= row < len(self._canvas._boxes):
            self.inp_label.blockSignals(True)
            self.inp_label.setText(self._canvas._boxes[row].get("label",""))
            self.inp_label.blockSignals(False)

    def _on_label_change(self, text):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.update_label(row, text)
            item = self.list_w.item(row)
            if item:
                item.setText(f"  {text or f'Mask #{row+1}'}")

    def _delete_selected(self):
        row = self.list_w.currentRow()
        if row >= 0: self._canvas.delete_box(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  CARD EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class CardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None):
        super().__init__(parent)
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        # Will be shown maximized in exec_maximized()
        self.card       = card or {}
        self._pdf_pages = []
        self._cur_page  = 0
        self._data      = data   # full data dict — needed to create sub-decks
        self._deck      = deck   # parent deck — card will be added here by default
        self._auto_subdeck_name = None   # set when PDF is loaded
        self._setup_ui()
        if card: self._load_card(card)

    def exec_(self):
        # Show maximized before entering event loop
        self.showMaximized()
        return super().exec_()

    def _setup_ui(self):
        # ── Overall dialog style: light/dark split like screenshot ────────────
        self.setStyleSheet(f"""
            QDialog {{ background:{C_BG}; }}
            QWidget {{ background:{C_BG}; color:{C_TEXT}; font-family:'Segoe UI'; font-size:13px; }}
            QLabel  {{ background:transparent; }}
        """)

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ══ HEADER BAR ════════════════════════════════════════════════════════
        hbar = QFrame()
        hbar.setFixedHeight(44)
        hbar.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-bottom:1px solid {C_BORDER};border-radius:0;}}")
        hl = QHBoxLayout(hbar); hl.setContentsMargins(14,0,14,0); hl.setSpacing(8)

        title_lbl = QLabel("🖼  Image Occlusion Editor")
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title_lbl.setStyleSheet(f"color:{C_TEXT};")
        hl.addWidget(title_lbl); hl.addStretch()

        # Image / PDF load buttons — top-right, flat style
        bi = QPushButton("🖼  Image")
        bi.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:5px 14px;font-size:12px;")
        bi.clicked.connect(self._load_image)
        bp = QPushButton("📄  PDF")
        bp.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:5px 14px;font-size:12px;")
        bp.clicked.connect(self._load_pdf); bp.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT: bp.setToolTip("pip install pymupdf")
        # Clipboard paste button
        bc_btn = QPushButton("📋  Paste")
        bc_btn.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:5px 14px;font-size:12px;")
        bc_btn.setToolTip("Paste image from clipboard  (Ctrl+V)")
        bc_btn.clicked.connect(self._paste_clipboard)
        hl.addWidget(bi); hl.addWidget(bp); hl.addWidget(bc_btn)
        root.addWidget(hbar)

        # ══ TOOLBAR ═══════════════════════════════════════════════════════════
        tbar = QFrame()
        tbar.setFixedHeight(46)
        tbar.setStyleSheet(
            f"QFrame{{background:{C_BG};"
            f"border-bottom:1px solid {C_BORDER};border-radius:0;}}")
        tl = QHBoxLayout(tbar); tl.setContentsMargins(10,4,10,4); tl.setSpacing(2)

        TB_SS_NORMAL = (
            f"QPushButton{{background:transparent;color:{C_TEXT};"
            f"border:1px solid transparent;border-radius:5px;"
            f"font-size:15px;min-width:32px;min-height:32px;"
            f"max-width:32px;max-height:32px;}}"
            f"QPushButton:hover{{background:{C_CARD};border:1px solid {C_BORDER};}}"
            f"QPushButton:pressed{{background:{C_SURFACE};}}"
        )
        TB_SS_DANGER = TB_SS_NORMAL.replace(
            "background:transparent", "background:transparent").replace(
            f"color:{C_TEXT}", f"color:{C_RED}")
        TB_SS_ACTIVE = (
            f"QPushButton{{background:{C_ACCENT};color:white;"
            f"border:1px solid {C_ACCENT};border-radius:5px;"
            f"font-size:15px;min-width:32px;min-height:32px;"
            f"max-width:32px;max-height:32px;}}"
        )

        def _tb(icon, tip, danger=False):
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setStyleSheet(TB_SS_DANGER if danger else TB_SS_NORMAL)
            b.setFixedSize(32, 32)
            return b

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.VLine)
            s.setFixedWidth(1); s.setFixedHeight(24)
            s.setStyleSheet(f"background:{C_BORDER};border:none;margin:0 4px;")
            return s

        # Undo / Redo
        b_undo = _tb("↩", "Undo  Ctrl+Z")
        b_redo = _tb("↪", "Redo  Ctrl+Y")
        b_undo.clicked.connect(lambda: self.canvas.undo())
        b_redo.clicked.connect(lambda: self.canvas.redo())

        # Zoom
        b_zfit = _tb("⊡", "Zoom to Fit")
        b_zin  = _tb("+", "Zoom In")
        b_zout = _tb("−", "Zoom Out")
        b_zfit.clicked.connect(self._zoom_fit)
        b_zin.clicked.connect(lambda: self.canvas.zoom_in())
        b_zout.clicked.connect(lambda: self.canvas.zoom_out())

        # Toggle masks visibility
        self.btn_eye = _tb("👁", "Toggle Masks Visible")
        self.btn_eye.setCheckable(True); self.btn_eye.setChecked(True)
        self.btn_eye.setStyleSheet(TB_SS_NORMAL)
        self.btn_eye.clicked.connect(self._toggle_eye)
        self._tb_normal_ss = TB_SS_NORMAL
        self._tb_active_ss = TB_SS_ACTIVE

        # Delete / Duplicate
        b_del = _tb("🗑", "Delete Selected  Del", danger=True)
        b_dup = _tb("⧉", "Duplicate  Ctrl+D")
        b_del.clicked.connect(lambda: self.canvas.delete_selected_boxes())
        b_dup.clicked.connect(lambda: self.canvas.duplicate_selected())

        # Group / Ungroup
        self.btn_group = _tb("⛓", "Group masks (review all as one card)")
        self.btn_group.setCheckable(True)
        self.btn_group.setChecked(self.card.get("grouped", False))
        self.btn_group.clicked.connect(self._toggle_group)
        self._update_group_btn()

        b_ungroup = _tb("⛓̶", "Ungroup (review each mask individually)")
        b_ungroup.clicked.connect(self._do_ungroup)

        for w in (b_undo, b_redo, _sep(), b_zfit, b_zin, b_zout,
                  _sep(), self.btn_eye, _sep(), b_del, b_dup,
                  _sep(), self.btn_group, b_ungroup):
            tl.addWidget(w)
        tl.addStretch()
        root.addWidget(tbar)

        # ── PDF navigation bar ────────────────────────────────────────────────
        self.pdf_bar = QWidget()
        self.pdf_bar.setStyleSheet(f"background:{C_SURFACE};border-bottom:1px solid {C_BORDER};")
        pb = QHBoxLayout(self.pdf_bar); pb.setContentsMargins(10,4,10,4)
        self.btn_pp = QPushButton("◀ Prev"); self.btn_pp.setObjectName("flat"); self.btn_pp.setFixedWidth(80)
        self.lbl_pg = QLabel("Page 1/1"); self.lbl_pg.setAlignment(Qt.AlignCenter)
        self.btn_np = QPushButton("Next ▶"); self.btn_np.setObjectName("flat"); self.btn_np.setFixedWidth(80)
        self.btn_pp.clicked.connect(self._prev_page)
        self.btn_np.clicked.connect(self._next_page)
        pb.addWidget(self.btn_pp); pb.addWidget(self.lbl_pg); pb.addWidget(self.btn_np); pb.addStretch()
        self.pdf_bar.hide(); root.addWidget(self.pdf_bar)

        # ══ MAIN AREA: canvas (left) + right panel ════════════════════════════
        main_split = QSplitter(Qt.Horizontal)
        main_split.setHandleWidth(1)
        main_split.setStyleSheet(f"QSplitter::handle{{background:{C_BORDER};}}")

        # ── Canvas area (white-ish background like screenshot) ─────────────────
        canvas_wrap = QWidget()
        canvas_wrap.setStyleSheet(f"background:#F0F0F0;")
        cw_l = QVBoxLayout(canvas_wrap); cw_l.setContentsMargins(0,0,0,0); cw_l.setSpacing(0)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(True)
        self._canvas_scroll.setStyleSheet(
            "QScrollArea{border:none;background:#F0F0F0;}"
            "QScrollBar:vertical{background:#E0E0E0;width:8px;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#AAAAAA;border-radius:4px;}"
            "QScrollBar:horizontal{background:#E0E0E0;height:8px;border-radius:4px;}"
            "QScrollBar::handle:horizontal{background:#AAAAAA;border-radius:4px;}")
        self.canvas = OcclusionCanvas()
        self.canvas.setStyleSheet("background:#F0F0F0;")
        self._canvas_scroll.setWidget(self.canvas)
        cw_l.addWidget(self._canvas_scroll, stretch=1)

        # Hint bar at bottom of canvas
        hint = QLabel("🖱 Drag to draw  •  Click to select  •  Ctrl+Click multi-select  •  Drag box to move  •  Drag ◢ corner to resize  •  Del to delete  •  Ctrl+A all")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFixedHeight(24)
        hint.setStyleSheet(
            f"background:{C_SURFACE};color:{C_SUBTEXT};"
            f"font-size:11px;border-top:1px solid {C_BORDER};padding:2px 8px;")
        cw_l.addWidget(hint)
        main_split.addWidget(canvas_wrap)

        # ── Right panel: MaskPanel (includes Card Info) ────────────────────────
        self.mask_panel = MaskPanel(self.canvas)
        self.mask_panel.setMinimumWidth(220)
        self.mask_panel.setMaximumWidth(300)
        self.mask_panel.setStyleSheet(
            f"QWidget{{background:{C_SURFACE};}}")
        main_split.addWidget(self.mask_panel)

        main_split.setSizes([900, 260])
        root.addWidget(main_split, stretch=1)

        # ══ BOTTOM BAR ════════════════════════════════════════════════════════
        bbar = QFrame()
        bbar.setFixedHeight(48)
        bbar.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-top:1px solid {C_BORDER};border-radius:0;}}")
        bl = QHBoxLayout(bbar); bl.setContentsMargins(16,0,16,0); bl.setSpacing(10)
        bl.addStretch()
        bc = QPushButton("  Cancel  ")
        bc.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:7px;padding:7px 20px;font-size:13px;")
        bc.clicked.connect(self.reject)
        bs = QPushButton("💾  Save Card")
        bs.setStyleSheet(
            f"background:{C_GREEN};color:#1E1E2E;border:none;"
            f"border-radius:7px;padding:7px 20px;font-weight:bold;font-size:13px;")
        bs.clicked.connect(self._save)
        bl.addWidget(bc); bl.addWidget(bs)
        root.addWidget(bbar)
    # ── loaders ───────────────────────────────────────────────────────────────

    def _toggle_group(self):
        self.card["grouped"] = self.btn_group.isChecked()
        self._update_group_btn()

    def _do_ungroup(self):
        """Ungroup: turn off grouped mode."""
        self.btn_group.setChecked(False)
        self.card["grouped"] = False
        self._update_group_btn()

    def _update_group_btn(self):
        if self.btn_group.isChecked():
            self.btn_group.setStyleSheet(
                "background:#50FA7B;color:#1E1E2E;border-radius:6px;"
                "font-weight:bold;font-size:16px;")
            self.btn_group.setToolTip("Grouped ON — click to ungroup")
        else:
            self.btn_group.setStyleSheet("")
            self.btn_group.setToolTip("Group: review all masks together as ONE card")

    def _toggle_eye(self):
        self.canvas.toggle_masks_visible()
        self.btn_eye.setStyleSheet(
            "" if self.btn_eye.isChecked() else
            f"background:{C_BORDER};color:{C_SUBTEXT};border-radius:6px;")

    def _zoom_fit(self):
        vp = self._canvas_scroll.viewport()
        self.canvas.zoom_fit(vp.width(), vp.height())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_G:
            self.btn_group.setChecked(not self.btn_group.isChecked())
            self._toggle_group()
        elif e.key() == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.canvas.select_all()
        elif e.key() == Qt.Key_Delete:
            self.canvas.delete_selected_boxes()
        elif e.key() == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self.canvas.undo()
        elif e.key() == Qt.Key_Y and e.modifiers() & Qt.ControlModifier:
            self.canvas.redo()
        elif e.key() == Qt.Key_D and e.modifiers() & Qt.ControlModifier:
            self.canvas.duplicate_selected()
        elif e.key() == Qt.Key_V and e.modifiers() & Qt.ControlModifier:
            self._paste_clipboard()
        else:
            super().keyPressEvent(e)

    def _paste_clipboard(self):
        """Load an image directly from the clipboard (Ctrl+V / screenshot paste)."""
        cb = QApplication.clipboard()
        img = cb.image()
        if img.isNull():
            # Try pixmap
            px = cb.pixmap()
            if px.isNull():
                QMessageBox.information(self, "Clipboard Empty",
                    "No image found in clipboard.\n\n"
                    "Copy an image or take a screenshot first,\n"
                    "then click Paste (or press Ctrl+V).")
                return
        else:
            px = QPixmap.fromImage(img)

        if px.isNull():
            QMessageBox.warning(self, "Error", "Could not read image from clipboard.")
            return

        # Save clipboard image to a temp file so card has a stable path
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False,
                                          dir=os.path.expanduser("~"))
        tmp_path = tmp.name; tmp.close()
        if not px.save(tmp_path, "PNG"):
            QMessageBox.warning(self, "Error", "Could not save clipboard image.")
            return

        self.card["image_path"] = tmp_path
        self.card.pop("pdf_path", None)
        self.card.pop("pdf_page", None)
        self.pdf_bar.hide()
        self._current_pixmap = px
        self.canvas.load_pixmap(self._current_pixmap)
        # Set title hint
        if not self.mask_panel.get_title():
            self.mask_panel.set_title("Clipboard image")

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif)")
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self, "Error", f"Could not load image:\n{path}")
            return
        self.card["image_path"] = path
        self.card.pop("pdf_path", None)
        self.card.pop("pdf_page", None)
        self.pdf_bar.hide()
        # Store on self so Python doesn't GC the pixmap before Qt finishes painting
        self._current_pixmap = px
        self.canvas.load_pixmap(self._current_pixmap)

    def _load_pdf(self):
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "Missing", "Run:  pip install pymupdf")
            return
        default_dir = r"C:\Users\Digvijay\Downloads"
        if not os.path.isdir(default_dir):
            default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(default_dir):
            default_dir = ""
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF", default_dir, "PDF (*.pdf)")
        if not path:
            return
        combined, err, _ = pdf_to_combined_pixmap(path)
        if combined.isNull():
            QMessageBox.warning(self, "Error",
                f"Could not render PDF:\n{path}\n\n"
                f"{err or 'Unknown error'}\n\n"
                f"PyMuPDF version: {fitz.version if PDF_SUPPORT else 'N/A'}")
            return

        self._pdf_pages = []          # not used anymore — combined replaces per-page
        self._cur_page  = 0
        self.card["pdf_path"] = path
        self.card.pop("image_path", None)
        self.card.pop("pdf_page", None)
        self.pdf_bar.hide()           # no page navigation needed — it's all one scroll

        pdf_name = os.path.splitext(os.path.basename(path))[0]
        self._auto_subdeck_name = pdf_name
        if not self.mask_panel.get_title():
            self.mask_panel.set_title(pdf_name)

        self._current_pixmap = combined
        self.canvas.load_pixmap(self._current_pixmap)

    def _show_pdf_page(self):
        if not self._pdf_pages: return
        # Store on self so it won't be GC'd while canvas is painting
        self._current_pixmap = self._pdf_pages[self._cur_page]
        self.canvas.load_pixmap(self._current_pixmap)
        self.lbl_pg.setText(f"Page {self._cur_page+1}/{len(self._pdf_pages)}")
        self.card["pdf_page"] = self._cur_page

    def _prev_page(self):
        if self._cur_page > 0: self._cur_page -= 1; self._show_pdf_page()

    def _next_page(self):
        if self._cur_page < len(self._pdf_pages)-1: self._cur_page += 1; self._show_pdf_page()

    # ── load existing card ────────────────────────────────────────────────────

    def _load_card(self, card):
        self.mask_panel.set_title(card.get("title", ""))
        self.mask_panel.set_tags(card.get("tags", []))
        self.mask_panel.set_notes(card.get("notes", ""))

        px = None
        if card.get("image_path") and os.path.exists(card["image_path"]):
            tmp = QPixmap(card["image_path"])
            if not tmp.isNull():
                px = tmp

        elif card.get("pdf_path") and os.path.exists(card["pdf_path"]) and PDF_SUPPORT:
            combined, _, _ = pdf_to_combined_pixmap(card["pdf_path"])
            if not combined.isNull():
                self.pdf_bar.hide()
                px = combined

        if px and not px.isNull():
            self._current_pixmap = px
            self.canvas.load_pixmap(self._current_pixmap)

        if card.get("boxes"):
            self.canvas.set_boxes(card["boxes"])
            self.mask_panel._refresh(card["boxes"])

    # ── save ──────────────────────────────────────────────────────────────────

    def _save(self):
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self, "No Source", "Load an image or PDF first."); return

        # Merge new box geometry with existing SM-2 state so reviews aren't lost.
        # Match by box_id first (stable across edits), fallback to position index.
        old_boxes = self.card.get("boxes", [])
        new_boxes = self.canvas.get_boxes()
        SM2_KEYS  = ("sm2_interval","sm2_repetitions","sm2_ease","sm2_due",
                     "sm2_last_quality","box_id")

        # Build lookup from box_id → old box for fast matching
        old_by_id = {b["box_id"]: b for b in old_boxes if "box_id" in b}

        merged = []
        for i, nb in enumerate(new_boxes):
            # Try to match by existing box_id first
            existing_id = nb.get("box_id")
            old = old_by_id.get(existing_id) if existing_id else None
            # Fallback: match by position index (old behaviour)
            if old is None and i < len(old_boxes):
                old = old_boxes[i]
            if old:
                for k in SM2_KEYS:
                    if k in old:
                        nb[k] = old[k]
            # Assign a new unique box_id if this box doesn't have one yet
            if "box_id" not in nb:
                nb["box_id"] = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{i}"
            merged.append(nb)

        self.card.update({
            "title":   self.mask_panel.get_title() or "Untitled",
            "tags":    self.mask_panel.get_tags(),
            "notes":   self.mask_panel.get_notes(),
            "boxes":   merged,
            "grouped": self.btn_group.isChecked(),
            "created": self.card.get("created", datetime.now().isoformat()),
            "reviews": self.card.get("reviews", 0),
        })
        if self._auto_subdeck_name:
            self.card["_auto_subdeck"] = self._auto_subdeck_name

        # Card-level SM-2: force due=today if never reviewed or reset
        today_iso = date.today().isoformat()
        if self.card.get("sm2_last_quality", -1) == -1 or self.card.get("sm2_repetitions", 0) == 0:
            self.card["sm2_due"]         = today_iso
            self.card["sm2_last_quality"] = self.card.get("sm2_last_quality", -1)
            self.card.setdefault("sm2_interval",    1)
            self.card.setdefault("sm2_repetitions", 0)
            self.card.setdefault("sm2_ease",        2.5)
        else:
            sm2_init(self.card)

        # Box-level SM-2: force due=today for new or reset boxes
        for box in self.card.get("boxes", []):
            if box.get("sm2_last_quality", -1) == -1 or box.get("sm2_repetitions", 0) == 0:
                box["sm2_due"] = today_iso
                box.setdefault("sm2_last_quality", -1)
                box.setdefault("sm2_interval",     1)
                box.setdefault("sm2_repetitions",  0)
                box.setdefault("sm2_ease",         2.5)
            else:
                sm2_init(box)

        self.accept()

    def get_card(self): return self.card


# ═══════════════════════════════════════════════════════════════════════════════
#  REVIEW SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

# ── Queue list delegate — paints item colors ignoring global QSS ─────────────
from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtCore    import QModelIndex

QUEUE_ROLE = Qt.UserRole + 10   # "done" | "current" | "pending"

class QueueDelegate(QStyledItemDelegate):
    """
    Paints each queue item with explicit colors that cannot be overridden
    by the global QSS stylesheet (which blocks setBackground/setForeground).
    """
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

        # Background
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cols["bg"]))
        painter.drawRoundedRect(r, 5, 5)

        # Left accent bar for current item
        if state == "current":
            painter.setBrush(QBrush(QColor("#1E1E2E")))
            painter.drawRect(r.left(), r.top()+4, 4, r.height()-8)

        # Text
        painter.setPen(cols["fg"])
        font = painter.font()
        font.setBold(state == "current")
        painter.setFont(font)
        painter.drawText(r.adjusted(10, 0, -4, 0), Qt.AlignVCenter, index.data())

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 34)


class ReviewScreen(QWidget):
    """
    Review mode.

    Card data model:
      card["boxes"]   = list of box dicts
      card["grouped"] = True  → treat all boxes as ONE card (old behaviour)
                        False / missing → each box is reviewed individually,
                        full document visible, only the target box is hidden.

    During review we expand each card into one "review item" per box
    (unless grouped=True, where it stays as one item with all boxes hidden).
    """
    finished = pyqtSignal()

    RATINGS = [
        ("🚫 Blackout","danger", 0),
        ("🔁 Again",   "danger", 1),
        ("😓 Hard",    "hard",   3),
        ("✅ Good",    "success",4),
        ("⚡ Easy",    "warning",5),
    ]

    def __init__(self, cards, data=None, parent=None):
        super().__init__(parent)
        self._data      = data   # full data dict — needed to save after each rating
        self._items     = []
        self._pdf_cache = {}
        self._current_pixmap = None

        today = date.today().isoformat()

        def _box_due_today(box):
            sm2_init(box)
            if box.get("sm2_last_quality", -1) == -1:
                return True   # never seen
            if box.get("sm2_repetitions", 0) == 0:
                return True   # failed/reset — due today
            due_str = box.get("sm2_due", "")
            return (not due_str) or (due_str <= today)

        for card in cards:
            boxes = card.get("boxes", [])
            if card.get("grouped", False) or len(boxes) == 0:
                sm2_init(card)
                self._items.append((card, None, card))
            else:
                for i, box in enumerate(boxes):
                    sm2_init(box)
                    if _box_due_today(box):          # ← only due/new boxes
                        self._items.append((card, i, box))

        self._items.sort(key=lambda x: x[2].get("sm2_due", ""))
        self._idx  = 0
        self._done = 0
        self._setup_ui()
        self._load_item()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F11:
            win = self.window()
            if win.isFullScreen():
                win.showMaximized()
            else:
                win.showFullScreen()
        else:
            super().keyPressEvent(e)

    def _setup_ui(self):
        L = QVBoxLayout(self); L.setContentsMargins(16,16,16,16); L.setSpacing(8)

        hdr = QHBoxLayout()
        self.lbl_prog = QLabel("Card 1/1"); self.lbl_prog.setFont(QFont("Segoe UI",12,QFont.Bold))
        hdr.addWidget(self.lbl_prog); hdr.addStretch()
        self.lbl_sm2 = QLabel("")
        self.lbl_sm2.setStyleSheet(f"background:{C_CARD};color:{C_SUBTEXT};border-radius:6px;padding:4px 10px;")
        hdr.addWidget(self.lbl_sm2)
        b_exit = QPushButton("✕ Exit"); b_exit.setObjectName("flat"); b_exit.clicked.connect(self.finished.emit)
        hdr.addWidget(b_exit); L.addLayout(hdr)

        self.prog = QProgressBar(); L.addWidget(self.prog)
        self.lbl_title = QLabel(""); self.lbl_title.setFont(QFont("Segoe UI",13,QFont.Bold))
        self.lbl_title.setStyleSheet(f"color:{C_ACCENT};"); L.addWidget(self.lbl_title)

        # ── main horizontal split: card list | canvas ──────────────────────────
        main_split = QSplitter(Qt.Horizontal)

        # Left: queue list
        queue_w = QWidget()
        ql = QVBoxLayout(queue_w); ql.setContentsMargins(0,0,0,0); ql.setSpacing(4)
        ql_hdr = QLabel("📋 Queue")
        ql_hdr.setFont(QFont("Segoe UI", 10, QFont.Bold))
        ql_hdr.setStyleSheet(f"color:{C_SUBTEXT};")
        ql.addWidget(ql_hdr)
        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.queue_list.setFocusPolicy(Qt.NoFocus)
        self.queue_list.setStyleSheet(
            f"QListWidget{{background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;padding:4px;}}"
        )
        self._queue_delegate = QueueDelegate(self.queue_list)
        self.queue_list.setItemDelegate(self._queue_delegate)
        # Populate queue list
        for i, (card, box_idx, _sm2) in enumerate(self._items):
            title = card.get("title", "Untitled")
            if box_idx is not None:
                boxes = card.get("boxes", [])
                lbl = boxes[box_idx].get("label") if boxes else None
                suffix = f"  #{lbl or box_idx+1}"
            else:
                suffix = ""
            item = QListWidgetItem(f"{i+1}. {title}{suffix}")
            self.queue_list.addItem(item)
        ql.addWidget(self.queue_list, stretch=1)
        queue_w.setMinimumWidth(180)
        queue_w.setMaximumWidth(260)
        main_split.addWidget(queue_w)

        # Right: canvas
        canvas_w = QWidget(); cl = QVBoxLayout(canvas_w); cl.setContentsMargins(0,0,0,0)
        self._canvas_scroll = QScrollArea(); self._canvas_scroll.setWidgetResizable(True)
        self.canvas = OcclusionCanvas(); self.canvas.set_mode("review")
        self._canvas_scroll.setWidget(self.canvas); cl.addWidget(self._canvas_scroll, stretch=1)
        main_split.addWidget(canvas_w)

        main_split.setSizes([220, 800])
        L.addWidget(main_split, stretch=1)

        hint = QLabel("👆 Click orange mask to reveal  •  Other masks shown as context  •  Then rate below  •  F11 fullscreen")
        hint.setAlignment(Qt.AlignCenter); hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        L.addWidget(hint)

        mid = QHBoxLayout()
        b_rev = QPushButton("👁 Reveal"); b_rev.setObjectName("warning")
        b_rev.clicked.connect(self.canvas.reveal_all); mid.addWidget(b_rev); mid.addStretch()
        L.addLayout(mid)

        rf = QFrame()
        rf.setStyleSheet(f"QFrame{{background:{C_CARD};border-radius:10px;}}")
        rfl = QVBoxLayout(rf); rfl.setContentsMargins(12,10,12,10); rfl.setSpacing(6)
        lq = QLabel("🧠 How well did you remember?")
        lq.setFont(QFont("Segoe UI",11,QFont.Bold)); lq.setAlignment(Qt.AlignCenter)
        rfl.addWidget(lq)
        br = QHBoxLayout(); br.setSpacing(8)
        for lbl,obj,q in self.RATINGS:
            btn = QPushButton(lbl); btn.setObjectName(obj)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumHeight(42)
            btn.clicked.connect(lambda _,qq=q: self._rate(qq)); br.addWidget(btn)
        rfl.addLayout(br)
        prev_row = QHBoxLayout(); prev_row.setSpacing(8)
        self._prev_lbls = []
        for _,_,q in self.RATINGS:
            pl = QLabel("→?d"); pl.setAlignment(Qt.AlignCenter)
            pl.setStyleSheet(f"color:{C_SUBTEXT};font-size:10px;")
            prev_row.addWidget(pl); self._prev_lbls.append((pl,q))
        rfl.addLayout(prev_row); L.addWidget(rf)

    def _load_item(self):
        if self._idx >= len(self._items):
            self._finish(); return

        card, box_idx, sm2_obj = self._items[self._idx]
        total = len(self._items)
        self.lbl_prog.setText(f"Item {self._idx+1}/{total}")
        self.prog.setMaximum(total); self.prog.setValue(self._idx)

        boxes = card.get("boxes", [])
        title = card.get("title", "")
        if box_idx is not None and len(boxes) > 0:
            lbl = boxes[box_idx].get("label") or f"Mask #{box_idx+1}"
            self.lbl_title.setText(f"{title}  —  {lbl}")
        else:
            self.lbl_title.setText(title)

        self.lbl_sm2.setText(sm2_badge(sm2_obj))
        for pl, q in self._prev_lbls:
            pl.setText(f"→{sm2_simulate(sm2_obj,q)}d")

        # ── highlight current card in queue list via delegate role ────────────
        for i in range(self.queue_list.count()):
            it = self.queue_list.item(i)
            if i == self._idx:
                it.setData(QUEUE_ROLE, "current")
            elif i < self._idx:
                it.setData(QUEUE_ROLE, "done")
            else:
                it.setData(QUEUE_ROLE, "pending")

        # Scroll to current item — use a timer so layout is settled on first load
        def _scroll():
            it = self.queue_list.item(self._idx)
            if it:
                self.queue_list.scrollToItem(it, QAbstractItemView.PositionAtCenter)
        QTimer.singleShot(50, _scroll)

        # Load pixmap
        px = None
        if card.get("image_path") and os.path.exists(card["image_path"]):
            tmp = QPixmap(card["image_path"])
            if not tmp.isNull(): px = tmp
        elif card.get("pdf_path") and PDF_SUPPORT:
            if not os.path.exists(card["pdf_path"]):
                self.lbl_title.setText(title + "  ⚠ PDF not found")
            else:
                key = card["pdf_path"]
                if key not in self._pdf_cache:
                    combined, _, _ = pdf_to_combined_pixmap(card["pdf_path"])
                    if not combined.isNull():
                        self._pdf_cache[key] = combined
                px = self._pdf_cache.get(key)

        if px and not px.isNull():
            self._current_pixmap = px
            self.canvas.load_pixmap(self._current_pixmap)

            # set_mode FIRST — it resets all revealed flags; then we apply state
            self.canvas.set_mode("review")

            if box_idx is None:
                # Grouped card — load all boxes, all hidden
                self.canvas.set_boxes(boxes)
            else:
                # Individual mode:
                # Only the target box is hidden (green mask = current question)
                # All other boxes shown as revealed context (green border only)
                display_boxes = []
                for i, b in enumerate(boxes):
                    display_boxes.append({
                        "rect":     b["rect"],
                        "label":    b.get("label", ""),
                        "revealed": (i != box_idx),   # only target is hidden
                    })
                self.canvas.set_boxes_with_state(display_boxes)

            # mark the target box green & scroll canvas to it
            self.canvas.set_target_box(box_idx if box_idx is not None else -1)

            def _scroll_to_mask(bi=box_idx):
                r = self.canvas.get_target_scaled_rect()
                if r and bi is not None:
                    # Centre the scroll area on the target rect
                    vbar = self._canvas_scroll.verticalScrollBar()
                    hbar = self._canvas_scroll.horizontalScrollBar()
                    cx = r.center().x() - self._canvas_scroll.viewport().width()  // 2
                    cy = r.center().y() - self._canvas_scroll.viewport().height() // 2
                    hbar.setValue(max(0, cx))
                    vbar.setValue(max(0, cy))
            QTimer.singleShot(80, _scroll_to_mask)
        else:
            self.canvas.load_pixmap(QPixmap())

    def _rate(self, quality):
        card, box_idx, sm2_obj = self._items[self._idx]
        if self._data:
            AppHistory.push(self._data)
        sm2_update(sm2_obj, quality)
        card["reviews"] = card.get("reviews", 0) + 1
        # Save immediately so SM-2 state is never lost
        if self._data:
            save_data(self._data)
        self._done += 1; self._idx += 1; self._load_item()

    def _finish(self):
        self.prog.setValue(len(self._items))
        due = sum(1 for _, _, sm2_obj in self._items if sm2_is_due(sm2_obj))
        QMessageBox.information(self, "Done! 🎉",
            f"Reviewed: {self._done}\nStill due: {due}\n\nConsistency beats cramming! 🔥")
        self.finished.emit()


# ═══════════════════════════════════════════════════════════════════════════════
#  NESTED DECK TREE  — supports parent > child decks
# ═══════════════════════════════════════════════════════════════════════════════

class DeckTree(QWidget):
    """
    Left-side deck browser — Anki-style:
      • Drag-and-drop to reparent any deck under another (or to top level)
      • ▶/▼ collapse/expand buttons per row (like Anki's arrow indicators)
      • Right-click context menu for full CRUD
      • Due counts shown like Anki: blue=new, red=due
    """
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data          = data
        self._drag_id       = None   # id of deck being dragged
        self._collapsed     = set()  # set of _ids that are collapsed
        self._ensure_ids()
        self._setup_ui()
        self.refresh()

    # ── id helpers ────────────────────────────────────────────────────────────

    def _ensure_ids(self):
        counter = [0]
        def _walk(lst):
            for d in lst:
                if "_id" not in d:
                    counter[0] += 1
                    d["_id"] = counter[0]
                _walk(d.get("children", []))
        _walk(self._data.get("decks", []))

    def _next_id(self):
        max_id = [0]
        def _walk(lst):
            for d in lst:
                max_id[0] = max(max_id[0], d.get("_id", 0))
                _walk(d.get("children", []))
        _walk(self._data.get("decks", []))
        return max_id[0] + 1

    def _find_by_id(self, deck_id, lst=None):
        if lst is None: lst = self._data.get("decks", [])
        for d in lst:
            if d.get("_id") == deck_id: return d
            found = self._find_by_id(deck_id, d.get("children", []))
            if found: return found
        return None

    def _find_parent_list(self, deck_id, lst=None):
        """Return (parent_list, index) where deck_id lives."""
        if lst is None: lst = self._data.get("decks", [])
        for i, d in enumerate(lst):
            if d.get("_id") == deck_id: return lst, i
            result = self._find_parent_list(deck_id, d.get("children", []))
            if result: return result
        return None, -1

    def _remove_from_tree(self, deck_id, lst=None):
        if lst is None: lst = self._data.get("decks", [])
        for i, d in enumerate(lst):
            if d.get("_id") == deck_id: return lst.pop(i)
            result = self._remove_from_tree(deck_id, d.get("children", []))
            if result: return result
        return None

    def _is_ancestor(self, ancestor_id, deck_id):
        """Return True if ancestor_id is an ancestor of deck_id."""
        deck = self._find_by_id(deck_id)
        if not deck: return False
        def _walk(lst):
            for d in lst:
                if d.get("_id") == deck_id:
                    return False   # found target, ancestor not in path
                if d.get("_id") == ancestor_id:
                    # Check if deck_id is in subtree of ancestor
                    return self._in_subtree(deck_id, d)
                r = _walk(d.get("children", []))
                if r is not None: return r
            return None
        return self._in_subtree(deck_id, self._find_by_id(ancestor_id)) if self._find_by_id(ancestor_id) else False

    def _in_subtree(self, deck_id, root):
        if root is None: return False
        if root.get("_id") == deck_id: return True
        return any(self._in_subtree(deck_id, c) for c in root.get("children", []))

    # ── setup ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        L = QVBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(4)

        # Header
        hdr_row = QHBoxLayout()
        hdr = QLabel("📚  Decks")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Bold))
        hdr_row.addWidget(hdr); hdr_row.addStretch()
        b_expand = QPushButton("⊞")
        b_expand.setToolTip("Expand all")
        b_expand.setFixedSize(24, 24)
        b_expand.setStyleSheet(f"QPushButton{{background:transparent;color:{C_SUBTEXT};border:none;font-size:14px;}}"
                               f"QPushButton:hover{{color:{C_TEXT};}}")
        b_expand.clicked.connect(self._expand_all)
        b_collapse = QPushButton("⊟")
        b_collapse.setToolTip("Collapse all")
        b_collapse.setFixedSize(24, 24)
        b_collapse.setStyleSheet(b_expand.styleSheet())
        b_collapse.clicked.connect(self._collapse_all)
        hdr_row.addWidget(b_collapse); hdr_row.addWidget(b_expand)
        L.addLayout(hdr_row)

        # Tree widget with drag-and-drop
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background:{C_SURFACE}; border:1px solid {C_BORDER};
                border-radius:8px; padding:4px; font-size:13px;
            }}
            QTreeWidget::item {{ padding:5px 4px; border-radius:5px; }}
            QTreeWidget::item:selected {{ background:{C_ACCENT}; color:white; }}
            QTreeWidget::item:hover:!selected {{ background:{C_CARD}; }}
            QTreeWidget::branch {{ background:{C_SURFACE}; }}
        """)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.itemCollapsed.connect(lambda item: self._collapsed.add(item.data(0, Qt.UserRole)))
        self.tree.itemExpanded.connect(lambda item: self._collapsed.discard(item.data(0, Qt.UserRole)))
        # Wire drop event to reparent in data model
        self.tree.model().rowsMoved.connect(self._on_rows_moved)
        L.addWidget(self.tree, stretch=1)

        # Bottom button row
        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        b_new = QPushButton("＋ Deck")
        b_new.setStyleSheet(f"background:{C_ACCENT};color:white;border:none;border-radius:6px;padding:5px 10px;font-size:12px;")
        b_new.clicked.connect(lambda: self._new_deck(None))
        b_sub = QPushButton("＋ Sub")
        b_sub.setStyleSheet(f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;padding:5px 10px;font-size:12px;")
        b_sub.clicked.connect(self._new_subdeck)
        b_del = QPushButton("🗑")
        b_del.setObjectName("danger"); b_del.setFixedWidth(32)
        b_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(b_new); btn_row.addWidget(b_sub)
        btn_row.addStretch(); btn_row.addWidget(b_del)
        L.addLayout(btn_row)

        hint = QLabel("Drag to reparent  •  Right-click for menu")
        hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:10px;"); hint.setAlignment(Qt.AlignCenter)
        L.addWidget(hint)

    # ── drag-drop: sync data model after Qt moves the tree item ───────────────

    def _on_rows_moved(self, src_parent, src_start, src_end, dst_parent, dst_row):
        """After Qt's internal drag-drop moves a row, rebuild data model to match the tree."""
        self._sync_tree_to_data()
        save_data(self._data)

    def _sync_tree_to_data(self):
        """Walk the QTreeWidget and rebuild self._data['decks'] to match."""
        # Collect all deck dicts by id so we don't lose card data
        all_decks = {}
        def _collect(lst):
            for d in lst:
                all_decks[d["_id"]] = d
                _collect(d.get("children", []))
        _collect(self._data.get("decks", []))

        def _build(item):
            did = item.data(0, Qt.UserRole)
            deck = all_decks.get(did, {"_id": did, "name": "?", "cards": [], "children": []})
            deck["children"] = [_build(item.child(i)) for i in range(item.childCount())]
            return deck

        new_decks = []
        for i in range(self.tree.topLevelItemCount()):
            new_decks.append(_build(self.tree.topLevelItem(i)))
        self._data["decks"] = new_decks

    # ── build tree ─────────────────────────────────────────────────────────────

    def refresh(self):
        sel_id = self._get_selected_id()
        self.tree.blockSignals(True)
        self.tree.clear()
        for deck in self._data.get("decks", []):
            self.tree.addTopLevelItem(self._make_item(deck))
        self.tree.blockSignals(False)
        # Restore collapse/expand state
        self._apply_collapse_state()
        if sel_id is not None:
            self._select_by_id(sel_id)

    def _make_item(self, deck):
        nc  = len(deck.get("cards", []))
        # Count new vs due for Anki-style display
        new_c = sum(1 for c in deck.get("cards", [])
                    if c.get("sm2_last_quality", -1) == -1)
        due_c = sum(1 for c in deck.get("cards", [])
                    if c.get("sm2_last_quality", -1) != -1 and sm2_is_due(c))

        badge_parts = []
        if new_c: badge_parts.append(f"🆕{new_c}")
        if due_c: badge_parts.append(f"🔴{due_c}")
        badge = "  ".join(badge_parts) if badge_parts else "✅"

        item = QTreeWidgetItem([f"  {deck['name']}   {badge}"])
        item.setData(0, Qt.UserRole, deck.get("_id"))
        item.setToolTip(0, f"{deck['name']} — {nc} cards")
        # Folder icon
        icon_px = QPixmap(14, 14); icon_px.fill(QColor(C_ACCENT))
        item.setIcon(0, QIcon(icon_px))
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        for child in deck.get("children", []):
            item.addChild(self._make_item(child))
        return item

    def _apply_collapse_state(self):
        def _walk(item):
            did = item.data(0, Qt.UserRole)
            if did in self._collapsed:
                item.setExpanded(False)
            else:
                item.setExpanded(True)
            for i in range(item.childCount()):
                _walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            _walk(self.tree.topLevelItem(i))

    def _expand_all(self):
        self._collapsed.clear()
        self.tree.expandAll()

    def _collapse_all(self):
        def _walk(item):
            self._collapsed.add(item.data(0, Qt.UserRole))
            for i in range(item.childCount()): _walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            _walk(self.tree.topLevelItem(i))
        self.tree.collapseAll()

    # ── item interactions ─────────────────────────────────────────────────────

    def _on_click(self, item, _col):
        deck = self._get_deck_from_item(item)
        if deck: self.deck_selected.emit(deck)

    def _get_id_from_item(self, item):
        return item.data(0, Qt.UserRole) if item else None

    def _get_deck_from_item(self, item):
        did = self._get_id_from_item(item)
        return self._find_by_id(did) if did is not None else None

    def _get_selected_id(self):
        return self._get_id_from_item(self.tree.currentItem())

    def _select_by_id(self, deck_id):
        def _walk(item):
            if item.data(0, Qt.UserRole) == deck_id:
                self.tree.setCurrentItem(item); return True
            for i in range(item.childCount()):
                if _walk(item.child(i)): return True
            return False
        for i in range(self.tree.topLevelItemCount()):
            if _walk(self.tree.topLevelItem(i)): break

    # ── context menu ──────────────────────────────────────────────────────────

    def _ctx_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            did = self._get_id_from_item(item)
            menu.addAction("▶ Open",       lambda: self._on_click(item, 0))
            menu.addAction("＋ Sub-deck",  lambda: self._new_deck_by_id(did))
            menu.addAction("✏ Rename",    lambda: self._rename_by_id(did))
            menu.addSeparator()
            # Move to top level option
            plist, pidx = self._find_parent_list(did)
            if plist is not self._data.get("decks"):
                menu.addAction("↑ Move to top level", lambda d=did: self._move_to_top(d))
            menu.addSeparator()
            menu.addAction("🗑 Delete",    lambda: self._delete_by_id(did))
        else:
            menu.addAction("＋ New Top-level Deck", lambda: self._new_deck(None))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _move_to_top(self, deck_id):
        deck = self._remove_from_tree(deck_id)
        if deck:
            self._data.setdefault("decks", []).append(deck)
            save_data(self._data)
            self.refresh()
            self._select_by_id(deck_id)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _new_deck(self, parent_id):
        name, ok = QInputDialog.getText(self, "New Deck", "Deck name:")
        if not ok or not name.strip(): return
        AppHistory.push(self._data)
        new_deck = {
            "_id":      self._next_id(),
            "name":     name.strip(),
            "cards":    [],
            "children": [],
            "created":  datetime.now().isoformat()
        }
        if parent_id is None:
            self._data.setdefault("decks", []).append(new_deck)
        else:
            parent = self._find_by_id(parent_id)
            if parent is None:
                QMessageBox.warning(self, "Error", "Parent deck not found!"); return
            parent.setdefault("children", []).append(new_deck)
        save_data(self._data)
        self.refresh()
        self._select_by_id(new_deck["_id"])

    def _new_deck_by_id(self, parent_id): self._new_deck(parent_id)

    def _new_subdeck(self):
        did = self._get_selected_id()
        if did is None:
            QMessageBox.information(self, "Select first", "Click a parent deck first."); return
        self._new_deck(did)

    def _rename_by_id(self, deck_id):
        deck = self._find_by_id(deck_id)
        if not deck: return
        name, ok = QInputDialog.getText(self, "Rename Deck", "New name:", text=deck.get("name",""))
        if ok and name.strip():
            AppHistory.push(self._data)
            deck["name"] = name.strip()
            save_data(self._data); self.refresh()

    def _delete_selected(self):
        did = self._get_selected_id()
        if did is not None: self._delete_by_id(did)

    def _delete_by_id(self, deck_id):
        deck = self._find_by_id(deck_id)
        if not deck: return
        if QMessageBox.question(self, "Delete",
            f"Delete '{deck['name']}' and ALL its cards / sub-decks?",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        AppHistory.push(self._data)
        self._remove_from_tree(deck_id)
        save_data(self._data); self.refresh()

    def get_selected_deck(self):
        return self._get_deck_from_item(self.tree.currentItem())


# ═══════════════════════════════════════════════════════════════════════════════
#  DECK VIEW  — right panel showing cards in selected deck
# ═══════════════════════════════════════════════════════════════════════════════

class DeckView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.deck     = None
        self._deck_id = None   # store id so we can re-lookup after tree refresh
        self._data    = {}
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self); L.setContentsMargins(12,12,12,12); L.setSpacing(10)

        hdr = QHBoxLayout()
        self.lbl_deck = QLabel("← Select a deck")
        self.lbl_deck.setFont(QFont("Segoe UI",15,QFont.Bold)); hdr.addWidget(self.lbl_deck)
        hdr.addStretch()
        self.btn_add = QPushButton("＋ Add Card"); self.btn_add.clicked.connect(self._add_card)
        self.btn_due = QPushButton("🔴 Review Due"); self.btn_due.setObjectName("danger")
        self.btn_due.clicked.connect(self._review_due)
        self.btn_all = QPushButton("▶ Review All"); self.btn_all.setObjectName("success")
        self.btn_all.clicked.connect(self._review_all)
        hdr.addWidget(self.btn_add); hdr.addWidget(self.btn_due); hdr.addWidget(self.btn_all)
        L.addLayout(hdr)

        self.lbl_stats = QLabel(""); self.lbl_stats.setStyleSheet(f"color:{C_SUBTEXT};")
        L.addWidget(self.lbl_stats)

        self.card_list = QListWidget(); self.card_list.setIconSize(QSize(64,48))
        self.card_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.card_list.itemDoubleClicked.connect(self._edit_card)
        self.card_list.itemSelectionChanged.connect(self._on_selection_changed)
        L.addWidget(self.card_list, stretch=1)

        self.lbl_sel = QLabel("")
        self.lbl_sel.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        L.addWidget(self.lbl_sel)

        bot = QHBoxLayout()
        be  = QPushButton("✏ Edit"); be.setObjectName("flat")
        be.clicked.connect(lambda: self._edit_card(self.card_list.currentItem()))
        bd  = QPushButton("🗑 Delete"); bd.setObjectName("danger"); bd.clicked.connect(self._delete_card)
        self.btn_group_sel = QPushButton("⛓ Group Selected"); self.btn_group_sel.setObjectName("flat")
        self.btn_group_sel.setToolTip("Merge selected cards' masks into one grouped card")
        self.btn_group_sel.clicked.connect(self._group_selected_cards)
        self.btn_group_sel.setEnabled(False)
        brs = QPushButton("▶ Review Selected"); brs.clicked.connect(self._review_selected)
        bot.addWidget(be); bot.addWidget(bd); bot.addWidget(self.btn_group_sel)
        bot.addStretch(); bot.addWidget(brs)
        L.addLayout(bot)

    def _find_deck_by_id(self, deck_id, lst=None):
        if lst is None: lst = self._data.get("decks", [])
        for d in lst:
            if d.get("_id") == deck_id: return d
            found = self._find_deck_by_id(deck_id, d.get("children", []))
            if found: return found
        return None

    def load_deck(self, deck, data):
        self._data    = data
        self._deck_id = deck.get("_id")
        self.deck     = deck
        self.lbl_deck.setText(deck.get("name","?"))
        self._refresh()

    def _refresh(self):
        # re-lookup the live deck dict from data (avoids stale reference after tree refresh)
        if self._deck_id is not None:
            fresh = self._find_deck_by_id(self._deck_id)
            if fresh: self.deck = fresh
        if not self.deck: return
        self.card_list.clear()
        cards = self.deck.get("cards",[])
        due_c = 0
        for c in cards:
            sm2_init(c)
            is_due = sm2_is_due(c); due_c += is_due
            badge  = "🔴 Due" if is_due else f"✅ {sm2_days_left(c)}d"
            item   = QListWidgetItem(
                f"  {c.get('title','Untitled')}  "
                f"| Boxes:{len(c.get('boxes',[]))}  "
                f"| Rep:{c.get('sm2_repetitions',0)}  "
                f"| EF:{c.get('sm2_ease',2.5):.2f}  | {badge}")
            if c.get("image_path") and os.path.exists(c["image_path"]):
                px = QPixmap(c["image_path"]).scaled(64,48,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                item.setIcon(QIcon(px))
            self.card_list.addItem(item)
        total_rev = sum(c.get("reviews",0) for c in cards)
        self.lbl_stats.setText(f"Cards:{len(cards)}  🔴Due:{due_c}  Reviews:{total_rev}")

    def _add_card(self):
        if not self.deck: return
        AppHistory.push(self._data)
        dlg = CardEditorDialog(self, data=self._data, deck=self.deck)
        if dlg.exec_() != QDialog.Accepted:
            return
        card = dlg.get_card()
        subdeck_name = card.pop("_auto_subdeck", None)

        if subdeck_name:
            # Find or create a child deck with this name under the current deck
            target_deck = None
            for child in self.deck.get("children", []):
                if child.get("name", "").strip().lower() == subdeck_name.strip().lower():
                    target_deck = child
                    break
            if target_deck is None:
                # Create a new child deck named after the PDF
                new_id = self._next_id()
                target_deck = {
                    "_id":      new_id,
                    "name":     subdeck_name,
                    "cards":    [],
                    "children": [],
                    "created":  datetime.now().isoformat(),
                }
                self.deck.setdefault("children", []).append(target_deck)
            target_deck.setdefault("cards", []).append(card)
        else:
            self.deck.setdefault("cards", []).append(card)

        # Refresh the tree so the new sub-deck appears immediately
        home = self._find_home()
        if home:
            home.refresh()
        else:
            self._refresh()
        save_data(self._data)

    def _next_id(self):
        """Return a unique id by walking the whole data tree."""
        max_id = [0]
        def _walk(lst):
            for d in lst:
                max_id[0] = max(max_id[0], d.get("_id", 0))
                _walk(d.get("children", []))
        _walk(self._data.get("decks", []))
        return max_id[0] + 1

    def _find_home(self):
        """Walk up the widget tree to find the HomeScreen."""
        w = self.parent()
        while w:
            if isinstance(w, HomeScreen):
                return w
            w = w.parent() if hasattr(w, 'parent') else None
        return None

    def _on_selection_changed(self):
        """Update hint label and enable/disable Group Selected button."""
        n = len(self.card_list.selectedItems())
        if n >= 2:
            self.lbl_sel.setText(f"  {n} cards selected — Shift+click to add/remove  •  ⛓ Group Selected merges their masks")
            self.btn_group_sel.setEnabled(True)
        elif n == 1:
            self.lbl_sel.setText("  1 card selected — hold Shift and click another to multi-select")
            self.btn_group_sel.setEnabled(False)
        else:
            self.lbl_sel.setText("")
            self.btn_group_sel.setEnabled(False)

    def _group_selected_cards(self):
        """Merge masks from all selected cards into a single new grouped card."""
        if not self.deck: return
        idxs  = sorted(set(self.card_list.row(i) for i in self.card_list.selectedItems()))
        cards = self.deck.get("cards", [])
        sel   = [cards[i] for i in idxs if i < len(cards)]
        if len(sel) < 2:
            QMessageBox.information(self, "Group Selected",
                "Select at least 2 cards to group."); return

        # Check all selected cards use the same image/pdf source
        sources = set()
        for c in sel:
            src = c.get("image_path") or c.get("pdf_path") or ""
            sources.add(src)
        if len(sources) > 1:
            QMessageBox.warning(self, "Cannot Group",
                "All selected cards must use the same image/PDF source to be grouped.")
            return

        # Ask for a name for the merged card
        title, ok = QInputDialog.getText(self, "Group Selected Cards",
            "Name for the new grouped card:",
            text=sel[0].get("title", "Grouped Card"))
        if not ok or not title.strip(): return

        # Merge all boxes from all selected cards
        all_boxes = []
        for c in sel:
            all_boxes.extend(c.get("boxes", []))

        # Build the new grouped card inheriting source from first selected card
        new_card = {
            "title":           title.strip(),
            "tags":            list({t for c in sel for t in c.get("tags", [])}),
            "notes":           "\n".join(filter(None, (c.get("notes","") for c in sel))),
            "boxes":           all_boxes,
            "grouped":         True,
            "created":         datetime.now().isoformat(),
            "reviews":         0,
        }
        # Copy source
        if sel[0].get("image_path"):
            new_card["image_path"] = sel[0]["image_path"]
        elif sel[0].get("pdf_path"):
            new_card["pdf_path"] = sel[0]["pdf_path"]

        sm2_init(new_card)
        new_card["sm2_due"] = date.today().isoformat()
        for box in new_card["boxes"]:
            sm2_init(box)
            box["sm2_due"] = date.today().isoformat()

        # Remove original cards (reverse order to keep indices valid)
        for i in reversed(idxs):
            if i < len(cards):
                cards.pop(i)

        cards.append(new_card)
        self._refresh(); save_data(self._data)
        QMessageBox.information(self, "Grouped!",
            f"✅ {len(sel)} cards merged into '{title.strip()}' with {len(all_boxes)} masks.")

    def _edit_card(self, item):
        if not item or not self.deck: return
        idx   = self.card_list.row(item)
        cards = self.deck.get("cards", [])
        if not 0 <= idx < len(cards): return
        AppHistory.push(self._data)
        dlg = CardEditorDialog(self, card=dict(cards[idx]), data=self._data, deck=self.deck)
        if dlg.exec_() == QDialog.Accepted:
            c = dlg.get_card()
            c.pop("_auto_subdeck", None)   # don't re-trigger subdeck logic on edit
            cards[idx] = c
            self._refresh(); save_data(self._data)

    def _delete_card(self):
        if not self.deck: return
        idx = self.card_list.currentRow(); cards = self.deck.get("cards",[])
        if not 0 <= idx < len(cards): return
        if QMessageBox.question(self,"Delete","Delete this card?",
            QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            AppHistory.push(self._data)
            cards.pop(idx); self._refresh(); save_data(self._data)

    def _review_due(self):
        if not self.deck: return

        today = date.today().isoformat()

        def _box_is_due_today(box):
            """True if box is new, failed/reset (rep==0), or due date <= today."""
            sm2_init(box)
            if box.get("sm2_last_quality", -1) == -1:
                return True   # never seen
            if box.get("sm2_repetitions", 0) == 0:
                return True   # failed/reset — always due today
            due_str = box.get("sm2_due", "")
            if not due_str:
                return True
            try:
                return due_str <= today
            except:
                return True

        def _card_has_due_today(card):
            boxes   = card.get("boxes", [])
            grouped = card.get("grouped", False)
            if grouped or len(boxes) == 0:
                sm2_init(card)
                if card.get("sm2_last_quality", -1) == -1:
                    return True   # never seen
                if card.get("sm2_repetitions", 0) == 0:
                    return True   # failed/reset — always due today
                due_str = card.get("sm2_due", "")
                if not due_str:
                    return True
                try:
                    return due_str <= today
                except:
                    return True
            return any(_box_is_due_today(box) for box in boxes)

        due = [c for c in self.deck.get("cards", []) if _card_has_due_today(c)]
        if not due:
            QMessageBox.information(self, "✅ All clear!",
                "No cards due today.\nCome back tomorrow! 🌙")
            return
        self._start_review(due)

    def _review_all(self):
        if not self.deck: return
        cards = self.deck.get("cards",[])
        if not cards: QMessageBox.information(self,"Empty","Add some cards first!"); return
        self._start_review(cards)

    def _review_selected(self):
        if not self.deck: return
        idxs  = [self.card_list.row(i) for i in self.card_list.selectedItems()]
        cards = self.deck.get("cards",[])
        sub   = [cards[i] for i in idxs if i < len(cards)]
        if not sub: QMessageBox.information(self,"None","Select cards first."); return
        self._start_review(sub)

    def _start_review(self, cards):
        win = QMainWindow(self); win.setWindowTitle("Review Mode 🧠"); win.setMinimumSize(960,730)
        rev = ReviewScreen(cards, data=self._data, parent=win)
        rev.finished.connect(win.close)
        rev.finished.connect(self._refresh)
        rev.finished.connect(lambda: save_data(self._data))
        win.setCentralWidget(rev); win.setStyleSheet(SS)
        win.showMaximized()


# ═══════════════════════════════════════════════════════════════════════════════
#  HOME SCREEN  — two-pane: tree left, card view right
# ═══════════════════════════════════════════════════════════════════════════════

class HomeScreen(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data; self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        # top bar
        top = QFrame(); top.setFixedHeight(56)
        top.setStyleSheet(f"QFrame{{background:{C_SURFACE};border-radius:0px;border-bottom:1px solid {C_BORDER};}}")
        tl = QHBoxLayout(top); tl.setContentsMargins(20,0,20,0)
        ttl = QLabel("🃏  Anki Occlusion"); ttl.setFont(QFont("Segoe UI",16,QFont.Bold))
        ttl.setStyleSheet(f"color:{C_ACCENT};")
        sub = QLabel("SM-2 Spaced Repetition  •  PDF & Image Occlusion")
        sub.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        tl.addWidget(ttl); tl.addSpacing(16); tl.addWidget(sub); tl.addStretch()
        L.addWidget(top)

        # main two-pane
        split = QSplitter(Qt.Horizontal)

        self.deck_tree = DeckTree(self._data)
        self.deck_tree.setMinimumWidth(240); self.deck_tree.setMaximumWidth(320)
        self.deck_tree.deck_selected.connect(self._on_deck_selected)
        split.addWidget(self.deck_tree)

        self.deck_view = DeckView()
        split.addWidget(self.deck_view)
        split.setSizes([280, 820])
        L.addWidget(split, stretch=1)

    def _on_deck_selected(self, deck):
        self.deck_view.load_deck(deck, self._data)

    def refresh(self):
        self.deck_tree.refresh()
        # re-load currently selected deck in right pane if one is selected
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
        self.setWindowTitle("Anki Occlusion — SM-2 Spaced Repetition")
        self.setMinimumSize(1100, 720)
        self.showMaximized()

        home = HomeScreen(self._data, parent=self)
        self.setCentralWidget(home)

        sb = QStatusBar()
        sb.showMessage("✅ SM-2 Active  |  " + (
            "PyMuPDF loaded — PDF support active"
            if PDF_SUPPORT else "⚠ pip install pymupdf  for PDF support"))
        self.setStatusBar(sb)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F11:
            if self.isFullScreen(): self.showMaximized()
            else: self.showFullScreen()
        elif e.key() == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            AppHistory.undo(self._data, self._refresh_home)
        elif e.key() == Qt.Key_Y and e.modifiers() & Qt.ControlModifier:
            AppHistory.redo(self._data, self._refresh_home)
        else:
            super().keyPressEvent(e)

    def _refresh_home(self):
        home = self.centralWidget()
        if isinstance(home, HomeScreen):
            home.refresh()

    def closeEvent(self, e):
        save_data(self._data); super().closeEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT  — single-instance guard
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── Single instance via lock file ─────────────────────────────────────────
    lock = QLockFile(LOCK_FILE)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        app_tmp = QApplication(sys.argv)
        QMessageBox.warning(None, "Already Running",
            "Anki Occlusion is already open!\nCheck your taskbar.")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyleSheet(SS)
    win = MainWindow()
    win.show()
    ret = app.exec_()
    lock.unlock()
    sys.exit(ret)
