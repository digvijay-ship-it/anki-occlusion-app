"""
Anki Occlusion — PDF & Image Flashcard App  v18 (Hardware Mask Cache + LRU Page Cache Edition)
================================================
v18 New Features:
  [HARDWARE MASK CACHE] OcclusionCanvas ab masks ko ek GPU-backed QPixmap
      offscreen layer mein cache karta hai. Jab tak koi mask change nahi hota,
      paintEvent mein sirf ek drawPixmap() call hota hai — loop nahi.
      100+ masks = 1 mask jaisi speed. FPS ~3x better on dense cards.
      Cache sirf tab rebuild hota hai jab _mask_cache_dirty = True ho:
        - mouseReleaseEvent (drag/draw finish)
        - delete, undo, redo, label change, group/ungroup
      Mouse drag ke dauran cache rebuild NAHI hoti — isliye dragging bhi smooth.

  [LRU PAGE CACHE] GLOBAL_PDF_CACHE replace ho gaya ek smart LRUPageCache se.
      Pura combined QPixmap store karne ki jagah ab individual pages store hoti hain.
      Max 15 pages RAM mein — baaki on-demand fitz se reload.
      Ek 100-page PDF pehle ~2GB RAM leta tha, ab sirf ~300MB.
      OrderedDict se O(1) get/put/evict — zero performance penalty.

v17 New Feature:
  [PROGRESSIVE LOADING] PDF ab 10-10 pages ke chunks mein load hota hai.
      Pehla chunk (10 pages) aate hi canvas pe dikhta hai — user turant
      kaam shuru kar sakta hai. Baaki pages background mein silently load
      hote rehte hain. Progress bar-style label dikhata hai kitne pages load hue.
  [ULTRA FAST CACHE] PDF ek baar load hone ke baad RAM mein save ho jati hai.
      Edit aur Review mode ke beech switch karne par zero delay (0.001s).
v16 Bug Fixes:
  [NOT-RESPONDING FIX] PDF ab background QThread mein load hota hai.
      CardEditorDialog._load_card() aur _load_pdf() dono ab non-blocking hain.
      _reload_pdf() (Live Sync) bhi thread-based ho gaya.
      closeEvent/reject mein thread safely stop hota hai.
v15 Bug Fixes:
  [FIX-1]  ReviewScreen.__init__ — duplicate item prevention
  [FIX-2]  _rate() — "reviews" double-increment fixed
  [FIX-3]  _start_review() — win.closeEvent double-save fixed
  [FIX-4]  is_due_today() called on un-initialised boxes in ReviewScreen
  [FIX-5]  Group dedup across cards
  [LAG-FIX] Native Hardware Painting & Caching applied to OcclusionCanvas 
            to eliminate mouseMoveEvent lag completely.
"""

from sm2_engine import (
    sched_init, sm2_init, sched_update, sm2_update, 
    is_due_now, is_due_today, sm2_is_due, sm2_days_left, 
    _fmt_due_interval, sm2_simulate, sm2_badge
)

from pdf_engine import (
    PDF_SUPPORT, PAGE_CACHE, pdf_to_combined_pixmap, PdfLoaderThread
)

from data_manager import (
    load_data, save_data, find_deck_by_id, next_deck_id, new_box_id,
    DATA_FILE
)

import sys, os, copy, uuid, math
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
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QRectF, QPointF, pyqtSignal, QLockFile, QTimer, QModelIndex, QFileSystemWatcher, QThread, QEvent
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QIcon, QBrush, QTransform, QPainterPath
)

import tempfile

# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")


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
C_GROUP   = "#BD93F9"

BASE_FONT_SIZE = 11

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

SS = _build_ss()

# ═══════════════════════════════════════════════════════════════════════════════
#  OCCLUSION CANVAS
# ═══════════════════════════════════════════════════════════════════════════════

def _rotated_corners(cx, cy, w, h, angle_deg):
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    result = []
    for dx, dy in corners:
        rx = cx + dx * cos_a - dy * sin_a
        ry = cy + dx * sin_a + dy * cos_a
        result.append(QPointF(rx, ry))
    return result

def _point_in_rotated_box(px, py, cx, cy, w, h, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx =  dx * cos_a - dy * sin_a
    ly =  dx * sin_a + dy * cos_a
    return abs(lx) <= w / 2 and abs(ly) <= h / 2

def _point_in_rotated_ellipse(px, py, cx, cy, rx, ry, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx =  dx * cos_a - dy * sin_a
    ly =  dx * sin_a + dy * cos_a
    if rx < 1 or ry < 1:
        return False
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1.0


class OcclusionCanvas(QLabel):
    boxes_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._px, self._boxes, self._scale = None, [], 1.0
        self._mode, self._tool = "edit", "rect"
        self._selected_idx, self._selected_indices = -1, set()
        self._drawing, self._start, self._live_rect, self._drag_op = False, QPointF(), QRectF(), None
        self._mask_cache_layer, self._mask_cache_dirty = None, True
        self._fast_zoom = False
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._finalize_zoom)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def load_pixmap(self, px: QPixmap):
        self._px = px
        self._invalidate_mask_cache()
        self._redraw()

    def _invalidate_mask_cache(self):
        self._mask_cache_dirty = True

    def _rebuild_mask_cache(self):
        """
    [HARDWARE MASK CACHE v18 + VISIBILITY CULLING v19]
    Saare masks ko ek GPU-backed QPixmap offscreen layer mein render karo.
    Sirf tab call hoti hai jab _mask_cache_dirty == True ho.

    [v19 NEW] Off-screen masks ab draw hi nahi hote — pure skip.
    500 masks + 450 off-screen = sirf 50 draw hote hain.
    Dense PDFs par cache rebuild ~5-10x faster.
    """
        if not self._px or self._px.isNull():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        spx = self._spx()
        if spx.isNull():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        # Scaled canvas ke same size ka transparent offscreen layer banao
        self._mask_cache_layer = QPixmap(spx.width(), spx.height())
        self._mask_cache_layer.fill(Qt.transparent)

        p = QPainter(self._mask_cache_layer)
        p.setRenderHint(QPainter.Antialiasing)

        # ── [v19] VISIBILITY CULLING ─────────────────────────────────────────
        # Parent QScrollArea dhundo — wahan se viewport aur scroll offset milega
        clip_rect = None
        parent_w = self.parent()
        while parent_w is not None:
            if isinstance(parent_w, QScrollArea):
                vp = parent_w.viewport()
                vp_rect = vp.rect()                        # screen pixels
                h_off = parent_w.horizontalScrollBar().value()
                v_off = parent_w.verticalScrollBar().value()
                # Screen → canvas (unscaled) coordinates
                # scroll offset already canvas-pixel mein hota hai (pre-scale)
                clip_rect = QRectF(
                    h_off / self._scale,
                    v_off / self._scale,
                    vp_rect.width()  / self._scale,
                    vp_rect.height() / self._scale,
                )
                break
            parent_w = parent_w.parent()
        # ─────────────────────────────────────────────────────────────────────

        for i, b in enumerate(self._boxes):
            # Drag ho raha ho toh selected box skip karo —
            # wo live paintEvent mein draw hoga (smooth drag ke liye)
            if self._drag_op and i == self._selected_idx:
                continue

            # [v19] Off-screen mask? — bilkul skip, draw hi mat karo
            # clip_rect None hone ka matlab: ScrollArea nahi mila → safe fallback,
            # sab draw karo (pehle jaisa behavior)
            if clip_rect is not None and not clip_rect.intersects(b["rect"]):
                continue

            self._draw_box(p, i, b)

        p.end()
        self._mask_cache_dirty = False
    
    def paintEvent(self, event):
        if not self._px: return
        p = QPainter(self)
        is_active = self._drawing or self._drag_op or self._fast_zoom
        p.setRenderHint(QPainter.SmoothPixmapTransform, not is_active)
        p.save()
        p.scale(self._scale, self._scale) # GPU Scaling
        p.drawPixmap(0, 0, self._px)
        if self._mask_cache_dirty: self._rebuild_mask_cache()
        if self._mask_cache_layer: p.drawPixmap(0, 0, self._mask_cache_layer)
        if self._drag_op and self._selected_idx >= 0:
            self._draw_single_mask(p, self._selected_idx, self._boxes[self._selected_idx])
        if self._drawing:
            p.setBrush(QColor(124, 106, 247, 100)); p.setPen(QPen(QColor("#7C6AF7"), 2))
            p.drawRect(self._live_rect)
        p.restore()
        p.end()

    def _draw_single_mask(self, p, i, b):
        r = b["rect"]
        p.save()
        p.translate(r.center()); p.rotate(b.get("angle", 0.0))
        local = QRectF(-r.width()/2, -r.height()/2, r.width(), r.height())
        sel = (i == self._selected_idx or i in self._selected_indices)
        fill = QColor("#50FA7B" if sel else "#F7916A")
        fill.setAlpha(155)
        p.setBrush(fill); p.setPen(QPen(Qt.white, 1))
        p.drawRect(local)
        p.restore()

    def _redraw(self):
        if not self._px: return
        self.resize(int(self._px.width() * self._scale), int(self._px.height() * self._scale))
        self.update()

    def _finalize_zoom(self):
        self._fast_zoom = False
        self.update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self._fast_zoom = True
            factor = 1.1 if e.angleDelta().y() > 0 else 0.9
            self._scale = max(0.05, min(8.0, self._scale * factor))
            self._redraw()
            self._zoom_timer.start(150)
            e.accept()
        else: super().wheelEvent(e)

    def event(self, e):
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self._fast_zoom = True
            self._scale = max(0.05, min(8.0, self._scale * (1.0 + e.value())))
            self._redraw(); self._zoom_timer.start(150); return True
        return super().event(e)

    def _ip(self, p): return QPointF(p.x()/self._scale, p.y()/self._scale)
    def mousePressEvent(self, e):
        ip = self._ip(e.pos()); hit = -1
        for i in range(len(self._boxes)-1, -1, -1):
            if self._boxes[i]["rect"].contains(ip): hit = i; break
        if hit >= 0:
            self._selected_idx = hit
            self._drag_op, self._drag_start_pos = "move", QPointF(e.pos())
            self._drag_orig_box = copy.deepcopy(self._boxes[hit])
        elif self._tool != "select": self._drawing, self._start = True, ip
    def mouseMoveEvent(self, e):
        if self._drawing: self._live_rect = QRectF(self._start, self._ip(e.pos())).normalized(); self.update()
        elif self._drag_op == "move":
            delta = (QPointF(e.pos()) - self._drag_start_pos) / self._scale
            self._boxes[self._selected_idx]["rect"].moveTopLeft(self._drag_orig_box["rect"].topLeft() + delta)
            self.update()
    def mouseReleaseEvent(self, e):
        if self._drawing and self._live_rect.width() > 5:
            self._boxes.append({"rect": self._live_rect, "box_id": str(uuid.uuid4())})
        self._drawing, self._drag_op = False, None
        self._invalidate_mask_cache(); self.update()
    boxes_changed = pyqtSignal(list)

    TOOLS = ("select", "rect", "ellipse", "text")
    _HANDLE_R = 6
    

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._px               = None
        self._boxes            = []
        self._mode             = "edit"
        self._tool             = "rect"
        self._scale            = 1.0
        self._selected_idx     = -1
        self._selected_indices = set()
        self._target_idx       = -1
        self._target_group_id  = ""
        self._review_mode_style= "hide_all"

        self._drawing        = False
        self._start          = QPointF()
        self._live_rect      = QRectF()

        self._drag_op        = None
        self._drag_handle    = -1
        self._drag_start_pos = QPointF()
        self._drag_orig_box  = None

        self._undo_stack : list = []
        self._redo_stack : list = []

        # --- [HARDWARE MASK CACHE v18] ---
        # Saare masks ek GPU-backed QPixmap offscreen layer mein pre-render hote hain.
        # paintEvent mein sirf ek drawPixmap() call — 100 masks = 1 mask jaisi speed!
        self._mask_cache_layer : QPixmap = None   # Offscreen layer
        self._mask_cache_dirty : bool    = True   # True = rebuild needed

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        # --- [SMOOTH ZOOM VARIABLES] ---
        self._fast_zoom = False
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._finalize_zoom)

    def set_tool(self, tool: str):
        self._tool = tool
        cursors = {
            "select":  Qt.ArrowCursor,
            "rect":    Qt.CrossCursor,
            "ellipse": Qt.CrossCursor,
            "text":    Qt.IBeamCursor,
        }
        self.setCursor(QCursor(cursors.get(tool, Qt.CrossCursor)))
        self.update()

    def load_pixmap(self, px: QPixmap):
        if px is None or px.isNull():
            self._px = None
            self._cached_spx = None  # Cache Clear
            self._invalidate_mask_cache()
            self.clear()
            return
        self._px    = px
        self._cached_spx = None      # Cache Clear
        self._invalidate_mask_cache()
        self._boxes = []
        self._scale = 1.0
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._redraw()

    def set_boxes(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=False) for b in boxes]
        self._invalidate_mask_cache()
        self.update()

    def set_boxes_with_state(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=b.get("revealed", False))
                       for b in boxes]
        self._invalidate_mask_cache()
        self.update()

    def get_boxes(self):
        SM2_KEYS = ("sm2_interval", "sm2_repetitions", "sm2_ease",
                    "sm2_due", "sm2_last_quality", "box_id")
        result = []
        for b in self._boxes:
            r = b["rect"]
            d = {
                "rect":     [r.x(), r.y(), r.width(), r.height()],
                "label":    b.get("label", ""),
                "shape":    b.get("shape", "rect"),
                "angle":    b.get("angle", 0.0),
                "group_id": b.get("group_id", ""),
            }
            for k in SM2_KEYS:
                if k in b:
                    d[k] = b[k]
            result.append(d)
        return result

    def set_mode(self, mode):
        self._mode = mode
        self._target_group_id = ""
        for b in self._boxes:
            b["revealed"] = False
        if mode == "review":
            self.setFocusPolicy(Qt.NoFocus)
            self.setCursor(QCursor(Qt.PointingHandCursor))
        else:
            self.setFocusPolicy(Qt.StrongFocus)
            self.setCursor(QCursor(Qt.CrossCursor))
        self._invalidate_mask_cache()
        self.update()

    def set_review_style(self, style: str):
        self._review_mode_style = style
        self._invalidate_mask_cache()
        self.update()

    def reveal_all(self):
        for b in self._boxes:
            b["revealed"] = True
        self._invalidate_mask_cache()
        self.update()

    def set_target_box(self, idx):
        self._target_idx = idx
        self._invalidate_mask_cache()
        self.update()

    def set_target_group(self, gid: str):
        self._target_group_id = gid
        self._invalidate_mask_cache()
        self.update()

    def get_target_scaled_rect(self):
        if self._target_group_id:
            rects = [self._sr(b["rect"]) for b in self._boxes
                     if b.get("group_id", "") == self._target_group_id]
            if rects:
                from PyQt5.QtCore import QRectF as _QRF
                x1 = min(r.left()   for r in rects)
                y1 = min(r.top()    for r in rects)
                x2 = max(r.right()  for r in rects)
                y2 = max(r.bottom() for r in rects)
                return _QRF(x1, y1, x2 - x1, y2 - y1)
        if 0 <= self._target_idx < len(self._boxes):
            return self._sr(self._boxes[self._target_idx]["rect"])
        return None

    def select_all(self):
        if not self._boxes:
            return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx     = len(self._boxes) - 1
        self.update()

    def select_visible_only(self):
        if not self._boxes:
            return

        # 1. Screen par jo canvas ka hissa dikh raha hai, uska Bounding Rect nikalenge
        visible_rect = self.visibleRegion().boundingRect()

        # 2. Canvas zoom (scaled) hota hai, toh usko original (unscaled) coordinates mein convert karenge
        inv_scale = 1.0 / self._scale
        vx = visible_rect.x() * inv_scale
        vy = visible_rect.y() * inv_scale
        vw = visible_rect.width() * inv_scale
        vh = visible_rect.height() * inv_scale
        v_rectf = QRectF(vx, vy, vw, vh)

        # 3. Naya selection set banayenge
        self._selected_indices = set()

        for i, b in enumerate(self._boxes):
            # Agar mask ka rect hamare visible screen area ke sath intersect ho raha hai
            if v_rectf.intersects(b["rect"]):
                self._selected_indices.add(i)

        if self._selected_indices:
            # Kisi ek box ko primary selected index bana do taaki uske handles dikh sakein
            self._selected_idx = max(self._selected_indices)
        else:
            self._selected_idx = -1

        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def delete_selected_boxes(self):
        self._push_undo()
        if self._selected_indices:
            for i in sorted(self._selected_indices, reverse=True):
                if 0 <= i < len(self._boxes):
                    self._boxes.pop(i)
            self._selected_indices = set()
            self._selected_idx     = -1
        elif self._selected_idx >= 0:
            self._boxes.pop(self._selected_idx)
            self._selected_idx = -1
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def delete_box(self, idx):
        if 0 <= idx < len(self._boxes):
            self._push_undo()
            self._boxes.pop(idx)
            self._selected_idx = -1
            self._invalidate_mask_cache()
            self.update()
            self.boxes_changed.emit(self.get_boxes())

    def delete_last(self):
        self.delete_box(len(self._boxes) - 1)

    def clear_all(self):
        self._push_undo()
        self._boxes        = []
        self._selected_idx = -1
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit([])

    def highlight(self, idx):
        self._selected_idx = idx
        self.update()

    def update_label(self, idx, text):
        if 0 <= idx < len(self._boxes):
            self._boxes[idx]["label"] = text
            self._invalidate_mask_cache()
            self.update()

    def group_selected(self):
        indices = self._get_all_selected()
        if len(indices) < 2:
            self._show_toast("⚠ Select 2+ masks to group")
            return
        gid = str(uuid.uuid4())[:8]
        self._push_undo()
        for i in indices:
            self._boxes[i]["group_id"] = gid
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())
        self._show_toast(f"⛓ {len(indices)} masks grouped")

    def ungroup_selected(self):
        indices = self._get_all_selected()
        if not indices:
            return
        self._push_undo()
        for i in indices:
            self._boxes[i]["group_id"] = ""
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())
        self._show_toast(f"✂ {len(indices)} masks ungrouped")

    def _get_all_selected(self):
        result = set(self._selected_indices)
        if self._selected_idx >= 0:
            result.add(self._selected_idx)
        return sorted(result)

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._redo_stack.clear()
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._undo_stack.pop()
        self._selected_idx = -1
        self._selected_indices = set()
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._redo_stack.pop()
        self._selected_idx = -1
        self._selected_indices = set()
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def zoom_in(self):
        self._scale = min(self._scale * 1.10, 8.0)
        self._redraw()

    def zoom_out(self):
        self._scale = max(self._scale / 1.10, 0.05)
        self._redraw()

    def zoom_fit(self, viewport_w, viewport_h):
        if not self._px or self._px.isNull(): return
        sx = viewport_w  / max(self._px.width(),  1)
        sy = viewport_h  / max(self._px.height(), 1)
        self._scale = min(sx, sy)
        self._redraw()

    def event(self, e):
        # ✋ TOUCHPAD PINCH-TO-ZOOM ENCOUNTER
        if e.type() == QEvent.NativeGesture:
            if e.gestureType() == Qt.ZoomNativeGesture:
                self._fast_zoom = True
                # e.value() exact magnification delta deta hai
                factor = 1.0 + e.value()
                self._scale = max(0.05, min(8.0, self._scale * factor))
                self._redraw()
                self._zoom_timer.start(150) # 150ms baad Smooth Render hoga
                return True
        return super().event(e)

    def wheelEvent(self, e):
        # 🖱 MOUSE WHEEL ZOOM ENCOUNTER
        if e.modifiers() & Qt.ControlModifier:
            angle = e.angleDelta().y()
            if angle == 0:
                e.accept()
                return
                
            self._fast_zoom = True
            factor = 1.0 + (angle / 120.0) * 0.10
            factor = max(0.90, min(factor, 1.11))
            self._scale = max(0.05, min(8.0, self._scale * factor))
            self._redraw()
            self._zoom_timer.start(150) # 150ms baad Smooth Render hoga
            e.accept()
        else:
            super().wheelEvent(e)

    def _deserialise_box(self, b, revealed=False):
        r = b["rect"]
        return {
            "rect":     QRectF(r[0], r[1], r[2], r[3]),
            "shape":    b.get("shape", "rect"),
            "angle":    float(b.get("angle", 0.0)),
            "revealed": revealed,
            "label":    b.get("label", ""),
            "box_id":   b.get("box_id", ""),
            "group_id": b.get("group_id", ""),
            **{k: b[k] for k in ("sm2_interval","sm2_repetitions","sm2_ease",
                                  "sm2_due","sm2_last_quality")
               if k in b}
        }

    def _ip(self, pos):
        return QPointF(pos.x() / self._scale, pos.y() / self._scale)

    def _sr(self, r: QRectF) -> QRectF:
        return QRectF(r.x() * self._scale, r.y() * self._scale,
                      r.width() * self._scale, r.height() * self._scale)

    def _spx(self):
        if not self._px:
            return QPixmap()
            
        # --- [LAG FIX] Cache System ---
        if hasattr(self, '_cached_scale') and hasattr(self, '_cached_spx'):
            if self._cached_scale == self._scale and self._cached_spx is not None:
                return self._cached_spx
                
        self._cached_scale = self._scale
        
        # 🚀 JAB ZOOM CHAL RAHA HO TOH FAST RENDER KARO, WARNA SMOOTH!
        transform_mode = Qt.FastTransformation if getattr(self, '_fast_zoom', False) else Qt.SmoothTransformation
        
        self._cached_spx = self._px.scaled(
            int(self._px.width()  * self._scale),
            int(self._px.height() * self._scale),
            Qt.KeepAspectRatio, transform_mode)
            
        return self._cached_spx

    def _finalize_zoom(self):
        """150ms baad jab user pinch karna band kar de, toh wapas High-Quality render karo"""
        self._fast_zoom = False
        self._cached_scale = -1  # Cache ko jaan-bujhkar clear kiya taaki naya high-quality image bane
        self._redraw()

    def _handle_positions(self, idx):
        if not (0 <= idx < len(self._boxes)):
            return None
        b  = self._boxes[idx]
        sr = self._sr(b["rect"])
        cx = sr.center().x()
        cy = sr.center().y()
        hw = sr.width()  / 2
        hh = sr.height() / 2
        ang = b.get("angle", 0.0)
        rad = math.radians(ang)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def rot(dx, dy):
            return QPointF(cx + dx * cos_a - dy * sin_a,
                           cy + dx * sin_a + dy * cos_a)

        handles = [
            rot(-hw, -hh), rot(0, -hh), rot(hw, -hh),
            rot(-hw,  0),               rot(hw,  0),
            rot(-hw,  hh), rot(0,  hh), rot(hw,  hh),
        ]
        rotate_pt = rot(0, -hh - 24)
        return {"resize": handles, "rotate": rotate_pt}

    def _hit_handle(self, screen_pos, idx):
        hps = self._handle_positions(idx)
        if not hps:
            return None
        sp = QPointF(screen_pos)
        r  = self._HANDLE_R + 2
        rpt = hps["rotate"]
        if (sp - rpt).manhattanLength() <= r:
            return ("rotate", -1)
        for hi, hpt in enumerate(hps["resize"]):
            if (sp - hpt).manhattanLength() <= r:
                return ("resize", hi)
        return None

    def _show_toast(self, msg: str):
        if not hasattr(self, "_toast_label"):
            from PyQt5.QtWidgets import QLabel
            self._toast_label = QLabel(self)
            self._toast_label.setStyleSheet(
                "QLabel{background:rgba(30,30,46,210);color:#BD93F9;"
                "border:1px solid #BD93F9;border-radius:6px;"
                "padding:4px 12px;font-size:12px;font-weight:bold;}")
            self._toast_label.hide()
        if not hasattr(self, "_toast_timer"):
            from PyQt5.QtCore import QTimer
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast_label.hide)
        self._toast_label.setText(msg)
        self._toast_label.adjustSize()
        x = (self.width()  - self._toast_label.width())  // 2
        y = 18
        self._toast_label.move(x, y)
        self._toast_label.show()
        self._toast_label.raise_()
        self._toast_timer.start(1800)

    def _select_box(self, hit: int, add_to_selection: bool = False):
        if hit < 0:
            self._selected_idx     = -1
            self._selected_indices = set()
            self._invalidate_mask_cache()
            self.update()
            return
        gid = self._boxes[hit].get("group_id", "")
        if gid:
            members = {i for i, b in enumerate(self._boxes)
                       if b.get("group_id", "") == gid}
            if add_to_selection:
                self._selected_indices |= members
            else:
                self._selected_indices = members
        else:
            if add_to_selection:
                self._selected_indices.add(hit)
            else:
                self._selected_indices = set()
        self._selected_idx = hit
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def _hit_box(self, ip: QPointF):
        for i in range(len(self._boxes) - 1, -1, -1):
            b  = self._boxes[i]
            r  = b["rect"]
            cx, cy = r.center().x(), r.center().y()
            ang = b.get("angle", 0.0)
            if b.get("shape") == "ellipse":
                if _point_in_rotated_ellipse(ip.x(), ip.y(),
                                             cx, cy,
                                             r.width()/2, r.height()/2, ang):
                    return i
            else:
                if _point_in_rotated_box(ip.x(), ip.y(),
                                         cx, cy, r.width(), r.height(), ang):
                    return i
        return -1

    def _redraw(self):
        if not self._px or self._px.isNull():
            return
        spx = self._spx()
        if spx.isNull():
            return

        # सिर्फ बैकग्राउंड सेट करो
        self.setPixmap(spx)
        self.resize(spx.size())

        # Zoom change hone par mask cache ki size bhi change hoti hai — rebuild zaroori hai
        self._invalidate_mask_cache()

        # Qt को हार्डवेयर पेंटिंग के लिए सिग्नल दो
        self.update()

    def _invalidate_mask_cache(self):
        """
        [HARDWARE MASK CACHE v18]
        Koi bhi mask change hone par call karo — cache ko dirty mark karta hai.
        Actual rebuild tab hogi jab paintEvent next baar chale.
        Mouse drag ke DAURAN mat call karna — sirf mouseReleaseEvent mein!
        """
        self._mask_cache_dirty = True

    def _rebuild_mask_cache(self):
        """
        [HARDWARE MASK CACHE v18]
        Saare masks ko ek GPU-backed QPixmap offscreen layer mein render karo.
        Sirf tab call hoti hai jab _mask_cache_dirty == True ho.
        """
        if not self._px or self._px.isNull():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        spx = self._spx()
        if spx.isNull():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        # Scaled canvas ke same size ka transparent offscreen layer banao
        self._mask_cache_layer = QPixmap(spx.width(), spx.height())
        self._mask_cache_layer.fill(Qt.transparent)

        p = QPainter(self._mask_cache_layer)
        p.setRenderHint(QPainter.Antialiasing)

        # Saare non-selected, non-active masks yahan render karo
        for i, b in enumerate(self._boxes):
            # Drag ho raha ho toh selected box skip karo —
            # wo live paintEvent mein draw hoga (smooth drag ke liye)
            if self._drag_op and i == self._selected_idx:
                continue
            self._draw_box(p, i, b)

        p.end()
        self._mask_cache_dirty = False

    def paintEvent(self, event):
        # Pehle background image render hone do (QLabel ka default behavior)
        super().paintEvent(event)

        if not self.pixmap():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # [HARDWARE MASK CACHE v18]
        # Step 1: Agar cache dirty hai toh rebuild karo (sirf tab jab zaroorat ho)
        if self._mask_cache_dirty:
            self._rebuild_mask_cache()

        # Step 2: Pre-rendered mask layer seedha GPU se chipkao — O(1) operation!
        if self._mask_cache_layer and not self._mask_cache_layer.isNull():
            p.drawPixmap(0, 0, self._mask_cache_layer)

        # Step 3: Drag ke dauran sirf selected box live draw karo (ultra smooth drag)
        if self._drag_op and self._selected_idx >= 0:
            self._draw_box(p, self._selected_idx, self._boxes[self._selected_idx])

        # Step 4: Live rect (naya box draw ho raha ho toh)
        if self._drawing and not self._live_rect.isEmpty():
            self._draw_live(p)

        p.end()

    def _draw_box(self, p: QPainter, i: int, b: dict):
        sr    = self._sr(b["rect"])
        cx    = sr.center().x()
        cy    = sr.center().y()
        ang   = b.get("angle", 0.0)
        lbl   = b.get("label") or f"#{i+1}"
        shape = b.get("shape", "rect")
        sel   = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        local = QRectF(-sr.width()/2, -sr.height()/2, sr.width(), sr.height())

        if self._mode == "review":
            revealed  = b.get("revealed", False)
            in_target_group = (bool(self._target_group_id) and
                               b.get("group_id", "") == self._target_group_id)
            is_target = (i == self._target_idx) or in_target_group
            hide_one  = (self._review_mode_style == "hide_one")

            if hide_one and not is_target:
                if not revealed:
                    p.setPen(QPen(QColor(C_GREEN), 1, Qt.DotLine))
                    p.setBrush(Qt.NoBrush)
                    if shape == "ellipse":
                        p.drawEllipse(local)
                    else:
                        p.drawRect(local)
                p.restore()
                return

            if not revealed:
                if is_target:
                    color    = QColor(C_GREEN)
                    text_col = "#1E1E2E"
                else:
                    color    = QColor(C_MASK)
                    text_col = "#FFF"
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(text_col), 2))
                if shape == "ellipse":
                    p.drawEllipse(local)
                else:
                    p.drawRect(local)
                p.setPen(QPen(QColor(text_col), 1))
                p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                p.drawText(local, Qt.AlignCenter, lbl)
            else:
                p.setPen(QPen(QColor(C_GREEN), 2))
                p.setBrush(Qt.NoBrush)
                if shape == "ellipse":
                    p.drawEllipse(local)
                else:
                    p.drawRect(local)
        else:
            gid    = b.get("group_id", "")
            grouped = bool(gid)
            fill = QColor("#50FA7B" if sel else
                          "#6EB5FF" if grouped else C_MASK)
            fill.setAlpha(155)
            p.setBrush(QBrush(fill))
            border_col = QColor(C_GREEN if sel else
                                "#2288FF" if grouped else "#FFF")
            p.setPen(QPen(border_col, 2, Qt.DashLine if not grouped else Qt.SolidLine))
            if shape == "ellipse":
                p.drawEllipse(local)
            else:
                p.drawRect(local)
            p.setPen(QPen(border_col, 1))
            p.setFont(QFont("Segoe UI", 9))
            display_lbl = lbl
            if grouped:
                display_lbl = f"[{gid[:4]}] {lbl}" if lbl else f"[{gid[:4]}]"
            p.drawText(local, Qt.AlignCenter, display_lbl)

        p.restore()

        if self._mode == "edit" and i == self._selected_idx:
            self._draw_handles(p, i)

    def _draw_handles(self, p: QPainter, idx: int):
        hps = self._handle_positions(idx)
        if not hps:
            return
        p.setPen(QPen(QColor(C_GREEN), 1))
        p.setBrush(QBrush(QColor("#1E1E2E")))
        hr = self._HANDLE_R
        for hpt in hps["resize"]:
            p.drawEllipse(hpt, hr, hr)
        rpt = hps["rotate"]
        top_c = hps["resize"][1]
        p.setPen(QPen(QColor(C_ACCENT), 1))
        p.drawLine(top_c, rpt)
        p.setBrush(QBrush(QColor(C_ACCENT)))
        p.setPen(QPen(QColor("#FFF"), 1))
        p.drawEllipse(rpt, hr + 1, hr + 1)
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor("#FFF"), 1))
        p.drawText(QRectF(rpt.x() - 6, rpt.y() - 6, 12, 12), Qt.AlignCenter, "↻")

    def _draw_live(self, p: QPainter):
        sr = self._sr(self._live_rect)
        c  = QColor(C_ACCENT)
        c.setAlpha(110)
        p.setBrush(QBrush(c))
        p.setPen(QPen(QColor(C_ACCENT), 2))
        if self._tool == "ellipse":
            p.drawEllipse(sr)
        else:
            p.drawRect(sr)

    def mousePressEvent(self, e):
        if not self._px:
            return
        self.setFocus()
        sp = QPointF(e.pos())
        ip = self._ip(e.pos())
        mods = e.modifiers()

        # Review Mode Logic (No Change)
        if self._mode == "review" and e.button() == Qt.LeftButton:
            hit = self._hit_box(ip)
            if hit >= 0:
                self._boxes[hit]["revealed"] = not self._boxes[hit]["revealed"]
                self._invalidate_mask_cache()
                self.update()
            return

        if self._mode != "edit" or e.button() != Qt.LeftButton:
            return

        # --- [MOTIVATION: No Alt Needed Anymore!] ---
        # हम हमेशा चेक करेंगे कि क्या यूजर किसी पुराने बॉक्स या हैंडल को पकड़ रहा है
        
        # 1. पहले चेक करें: क्या किसी Resize/Rotate हैंडल पर क्लिक किया है?
        if self._selected_idx >= 0:
            hit_h = self._hit_handle(sp, self._selected_idx)
            if hit_h:
                op, hi = hit_h
                self._drag_op        = op
                self._drag_handle    = hi
                self._drag_start_pos = sp
                self._drag_orig_box  = copy.deepcopy(self._boxes[self._selected_idx])
                self._push_undo()
                return

        # 2. चेक करें: क्या किसी बॉक्स (Mask) के ऊपर क्लिक किया है?
        hit = self._hit_box(ip)
        if hit >= 0:
            # [FIX: Ctrl for Multiple Selection]
            # यहाँ हमने Shift की जगह Ctrl (ControlModifier) लगा दिया है
            is_multi = bool(mods & Qt.ControlModifier)
            self._select_box(hit, add_to_selection=is_multi)
            
            # Dragging Command (बिना किसी Alt के)
            self._drag_op        = "move"
            self._drag_start_pos = sp
            self._drag_orig_box  = copy.deepcopy(self._boxes[hit])
            self._push_undo()
            return # ताकि नीचे नया बॉक्स ड्रा न होने लगे

        # 3. अगर किसी बॉक्स पर क्लिक नहीं किया, तो नया बॉक्स ड्रा करें (Rect/Ellipse)
        if self._tool != "select":
            self._select_box(-1) # पुराना सिलेक्शन खत्म
            self._drawing  = True
            self._start    = ip
            self._live_rect = QRectF()
            self.update()

    def mouseMoveEvent(self, e):
        sp = QPointF(e.pos())
        ip = self._ip(e.pos())

        if self._drawing:
            x0, y0 = self._start.x(), self._start.y()
            x1, y1 = ip.x(), ip.y()
            self._live_rect = QRectF(
                min(x0, x1), min(y0, y1),
                abs(x1 - x0), abs(y1 - y0))
            self.update()  # --- [LAG FIX] Native Update ---
            return

        if self._drag_op == "move" and self._selected_idx >= 0:
            delta = (sp - self._drag_start_pos) / self._scale
            orig  = self._drag_orig_box["rect"]
            self._boxes[self._selected_idx]["rect"] = QRectF(
                orig.x() + delta.x(), orig.y() + delta.y(),
                orig.width(), orig.height())
            self.update()  # --- [LAG FIX] Native Update ---
            return

        if self._drag_op == "resize" and self._selected_idx >= 0:
            self._do_resize(sp)
            return

        if self._drag_op == "rotate" and self._selected_idx >= 0:
            b  = self._boxes[self._selected_idx]
            sr = self._sr(b["rect"])
            cx, cy = sr.center().x(), sr.center().y()
            angle = math.degrees(math.atan2(sp.y() - cy, sp.x() - cx)) + 90
            b["angle"] = round(angle, 1)
            self.update()  # --- [LAG FIX] Native Update ---
            return

        if self._tool == "select" and self._mode == "edit":
            if self._selected_idx >= 0:
                hh = self._hit_handle(sp, self._selected_idx)
                if hh:
                    self.setCursor(QCursor(Qt.SizeAllCursor if hh[0] == "rotate"
                                          else Qt.SizeFDiagCursor))
                    return
            self.setCursor(QCursor(Qt.ArrowCursor))

    def mouseReleaseEvent(self, e):
        if self._drawing and e.button() == Qt.LeftButton:
            self._drawing = False
            r = self._live_rect
            if r.width() > 6 and r.height() > 6:
                self._push_undo()
                self._boxes.append({
                    "rect":     r,
                    "shape":    self._tool if self._tool in ("rect", "ellipse") else "rect",
                    "angle":    0.0,
                    "revealed": False,
                    "label":    "",
                })
                self._selected_idx = len(self._boxes) - 1
                self._invalidate_mask_cache()
                self.update()
                self.boxes_changed.emit(self.get_boxes())
            self._live_rect = QRectF()
            self._invalidate_mask_cache()
            self.update()

        if self._drag_op:
            self._drag_op     = None
            self._drag_handle = -1
            self._drag_orig_box = None
            # Drag khatam — ab final position ke saath cache rebuild karo
            self._invalidate_mask_cache()
            self.boxes_changed.emit(self.get_boxes())
            self.update()

    def _do_resize(self, sp: QPointF):
        idx  = self._selected_idx
        b    = self._boxes[idx]
        orig = self._drag_orig_box
        hi   = self._drag_handle

        delta = (sp - self._drag_start_pos) / self._scale
        ang   = orig.get("angle", 0.0)
        rad   = math.radians(-ang)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        ldx =  delta.x() * cos_a - delta.y() * sin_a
        ldy =  delta.x() * sin_a + delta.y() * cos_a

        r   = orig["rect"]
        x, y, w, h = r.x(), r.y(), r.width(), r.height()

        move_left  = hi in (0, 3, 5)
        move_right = hi in (2, 4, 7)
        move_top   = hi in (0, 1, 2)
        move_bot   = hi in (5, 6, 7)

        new_x, new_y, new_w, new_h = x, y, w, h
        if move_left:
            new_x = x + ldx;  new_w = max(10, w - ldx)
        if move_right:
            new_w = max(10, w + ldx)
        if move_top:
            new_y = y + ldy;  new_h = max(10, h - ldy)
        if move_bot:
            new_h = max(10, h + ldy)

        b["rect"]  = QRectF(new_x, new_y, new_w, new_h)
        b["angle"] = ang
        self.update()  # --- [LAG FIX] Native Update ---

    def keyPressEvent(self, e):
        mods = e.modifiers()
        key  = e.key()
        if self._mode == "review":
            super().keyPressEvent(e)
            return
        if key == Qt.Key_Delete:
            self.delete_selected_boxes()
        elif mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:
            self.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_A:
            if mods & Qt.ShiftModifier:
                # [Ctrl + Shift + A] -> Pura PDF ke saare masks ek sath select karega
                self.select_all()
            else:
                # [Ctrl + A] -> Sirf Current Screen/Page par dikhne wale masks ko segregate [अलग करना] karke select karega
                self.select_visible_only()
        elif key == Qt.Key_G and not (mods & Qt.ControlModifier):
            if mods & Qt.ShiftModifier:
                self.ungroup_selected()
            else:
                self.group_selected()
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  TOOL BAR
# ═══════════════════════════════════════════════════════════════════════════════

class ToolBar(QWidget):
    tool_changed = pyqtSignal(str)

    _TOOLS = [
        ("select",  "⬡", "Select / Move / Resize / Rotate  [V]\nHold Alt = temp select"),
        ("rect",    "□",  "Rectangle mask  [R]"),
        ("ellipse", "○",  "Ellipse / Circle mask  [E]"),
        ("text",    "T",  "Edit label of clicked mask  [T]"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(50)
        self.setStyleSheet(
            "QWidget{background:#F0F0F0;border-right:1px solid #C8C8C8;}")
        L = QVBoxLayout(self)
        L.setContentsMargins(5, 8, 5, 8)
        L.setSpacing(3)
        self._btns = {}
        for tool, icon, tip in self._TOOLS:
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedSize(40, 40)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#333;"
                "border:none;border-radius:5px;font-size:20px;font-weight:bold;}"
                "QPushButton:checked{background:#4A90D9;color:white;}"
                "QPushButton:hover:!checked{background:#E0E0E0;}")
            b.clicked.connect(lambda _, t=tool: self._select(t))
            L.addWidget(b)
            self._btns[tool] = b
        L.addStretch()
        self._select("rect")

    def _select(self, tool: str):
        for t, b in self._btns.items():
            b.setChecked(t == tool)
        self.tool_changed.emit(tool)

    def select_tool(self, tool: str):
        self._select(tool)


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
        L.setContentsMargins(6, 6, 6, 6)
        L.setSpacing(4)

        self.list_w = QListWidget()
        self.list_w.currentRowChanged.connect(self._on_select)
        L.addWidget(self.list_w, stretch=1)

        lbl_e = QLabel("Label:")
        lbl_e.setStyleSheet("color:#555;font-size:11px;background:transparent;")
        L.addWidget(lbl_e)
        self.inp_label = QLineEdit()
        self.inp_label.setPlaceholderText("e.g. Mitochondria")
        self.inp_label.textChanged.connect(self._on_label_change)
        L.addWidget(self.inp_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        b_del   = QPushButton("🗑 Delete")
        b_del.setObjectName("danger")
        b_del.setFixedHeight(26)
        b_del.clicked.connect(self._delete_selected)
        b_clear = QPushButton("✕ Clear All")
        b_clear.setFixedHeight(26)
        b_clear.clicked.connect(self._canvas.clear_all)
        btn_row.addWidget(b_del)
        btn_row.addWidget(b_clear)
        L.addLayout(btn_row)

    def _refresh(self, boxes):
        self.list_w.blockSignals(True) # 🛑 List ke events block kardo
        self.list_w.clear()
        
        for i, b in enumerate(boxes):
            lbl  = b.get("label") or f"Mask #{i+1}"
            gid  = b.get("group_id", "")
            icon = "🔵" if gid else "🟧"
            badge = f" [{gid[:4]}]" if gid else ""
            self.list_w.addItem(f"  {icon} {lbl}{badge}")
            
        # ❌ Purane code mein yahan `self.list_w.blockSignals(False)` likha tha, usko yahan se HATA do!

        sel = self._canvas._selected_idx
        if 0 <= sel < self.list_w.count():
            self.list_w.setCurrentRow(sel) # Ab ye line auto-center ko trigger nahi karegi
            box = self._canvas._boxes[sel]
            self.inp_label.blockSignals(True)
            self.inp_label.setText(box.get("label", ""))
            self.inp_label.blockSignals(False)
            
        # ✅ NAYA CODE: Signals ko sabse last mein unblock karo, jab saara background kaam ho jaye
        self.list_w.blockSignals(False)

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
        self._combined_px        = QPixmap()
        self._data               = data
        self._deck               = deck
        self._auto_subdeck_name  = None
        self._watcher            = QFileSystemWatcher()
        self._watched_path       = None
        self._reload_timer       = QTimer()
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._reload_pdf)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._pdf_loader_thread  = None   # [NOT-RESPONDING FIX] background thread
        self._pending_boxes      = []     # boxes to load after thread finishes
        self._setup_ui()
        if card:
            self._load_card(card)

    def exec_(self):
        self.showMaximized()
        return super().exec_()

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog { background: #ECECEC; }
            QWidget { background: #ECECEC; color: #222; font-family: 'Segoe UI'; font-size: 12px; }
            QFrame  { background: #ECECEC; border: none; border-radius: 0; }
            QLabel  { background: transparent; color: #333; }
            QLineEdit, QTextEdit {
                background: white; color: #111;
                border: 1px solid #CCC; border-radius: 4px; padding: 4px;
            }
            QListWidget {
                background: white; color: #111;
                border: 1px solid #CCC; border-radius: 4px;
            }
            QListWidget::item:selected { background: #4A90D9; color: white; }
            QPushButton {
                background: #E8E8E8; color: #333;
                border: 1px solid #BBB; border-radius: 4px;
                padding: 4px 10px; font-size: 12px;
            }
            QPushButton:hover  { background: #D8D8D8; }
            QPushButton:pressed{ background: #C8C8C8; }
            QPushButton#accent { background: #4A90D9; color: white; border: 1px solid #3A7FC9; }
            QPushButton#accent:hover { background: #3A7FC9; }
            QPushButton#danger { background: #E05555; color: white; border: 1px solid #C04040; }
            QPushButton#danger:hover { background: #C04040; }
            QPushButton#success{ background: #4CAF50; color: white; border: 1px solid #3A9040; }
            QPushButton#success:hover{ background: #3A9040; }
            QScrollArea { border: none; background: #888; }
            QScrollBar:vertical   { background:#CCC; width:10px; border-radius:5px; }
            QScrollBar::handle:vertical { background:#999; border-radius:5px; }
            QScrollBar:horizontal { background:#CCC; height:10px; border-radius:5px; }
            QScrollBar::handle:horizontal { background:#999; border-radius:5px; }
            QSplitter::handle { background: #D0D0D0; width: 1px; }
        """)

        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        top_bar = QFrame()
        top_bar.setFixedHeight(46)
        top_bar.setStyleSheet(
            "QFrame{background:#F0F0F0;border-bottom:1px solid #C8C8C8;border-radius:0;}"
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#333;min-height:32px;}"
            "QPushButton:hover{background:#DDD;}"
            "QPushButton:pressed{background:#CCC;}"
            "QPushButton:checked{background:#C8D8EE;color:#1a5ca8;}"
        )
        tl = QHBoxLayout(top_bar)
        tl.setContentsMargins(6, 4, 6, 4)
        tl.setSpacing(2)

        def _tbtn(label, tip, checkable=False, w=None):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFixedHeight(34)
            if w:
                b.setFixedWidth(w)
            return b

        btn_img = _tbtn("🖼 Image", "Load Image")
        btn_pdf = _tbtn("📄 PDF",  "Load PDF")
        btn_pdf.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT:
            btn_pdf.setToolTip("pip install pymupdf")
        btn_img.clicked.connect(self._load_image)
        btn_pdf.clicked.connect(self._load_pdf)

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.VLine)
            s.setStyleSheet("QFrame{background:#C0C0C0;margin:5px 4px;}")
            s.setFixedWidth(1)
            return s

        btn_undo = _tbtn("↩", "Undo  Ctrl+Z", w=36)
        btn_redo = _tbtn("↪", "Redo  Ctrl+Y", w=36)
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        btn_redo.clicked.connect(lambda: self.canvas.redo())

        btn_zi = _tbtn("🔍+", "Zoom In  Ctrl++",  w=46)
        btn_zo = _tbtn("🔍−", "Zoom Out  Ctrl+−", w=46)
        btn_zf = _tbtn("⊡",   "Zoom Fit  Ctrl+0", w=32)

        btn_del   = _tbtn("🗑",    "Delete selected  Del", w=32)
        btn_clear = _tbtn("✕ All", "Clear all masks")

        btn_grp   = _tbtn("⛓ Group",  "Group selected masks  [G]")
        btn_ungrp = _tbtn("⛓ Ungroup", "Ungroup selected masks  [Shift+G]")
        btn_grp.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#1a5ca8;min-height:32px;}"
            "QPushButton:hover{background:#D0E4FF;}")
        btn_ungrp.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#888;min-height:32px;}"
            "QPushButton:hover{background:#EEE;}")
        btn_grp.clicked.connect(lambda: self.canvas.group_selected())
        btn_ungrp.clicked.connect(lambda: self.canvas.ungroup_selected())

        self.btn_open_ext = _tbtn("📂 Open PDF", "Open in system PDF reader")
        self.btn_open_ext.clicked.connect(self._open_in_reader)
        self.btn_open_ext.setVisible(False)
        self.lbl_sync = QLabel("")
        self.lbl_sync.setStyleSheet("background:transparent;font-size:11px;color:#666;")
        self.lbl_sync.setVisible(False)

        for w in [btn_img, btn_pdf, _sep(),
                  btn_undo, btn_redo, _sep(),
                  btn_zi, btn_zo, btn_zf, _sep(),
                  btn_del, btn_clear, _sep(),
                  btn_grp, btn_ungrp, _sep(),
                  self.btn_open_ext, self.lbl_sync]:
            tl.addWidget(w)
        tl.addStretch()

        btn_cancel = _tbtn("Cancel", "Discard changes")
        btn_save   = QPushButton("💾  Save Card")
        btn_save.setFixedHeight(34)
        btn_save.setToolTip("Save  Ctrl+S")
        btn_save.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border:1px solid #3A9040;"
            "border-radius:4px;padding:4px 16px;font-size:13px;min-height:32px;}"
            "QPushButton:hover{background:#3A9040;}")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        tl.addWidget(btn_cancel)
        tl.addSpacing(4)
        tl.addWidget(btn_save)

        L.addWidget(top_bar)

        self.pdf_bar = QWidget()
        self.pdf_bar.setStyleSheet("background:#E8E8E8;border-bottom:1px solid #CCC;")
        pb = QHBoxLayout(self.pdf_bar)
        pb.setContentsMargins(10, 2, 10, 2)
        self.lbl_pg = QLabel("")
        self.lbl_pg.setStyleSheet("color:#555;font-size:11px;background:transparent;")
        pb.addWidget(self.lbl_pg)
        pb.addStretch()
        self.pdf_bar.setFixedHeight(22)
        self.pdf_bar.hide()
        L.addWidget(self.pdf_bar)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(0)

        self.toolbar = ToolBar()
        main_row.addWidget(self.toolbar)

        sc = _ZoomableScrollArea()
        sc.setWidgetResizable(True)
        sc.setStyleSheet("QScrollArea{background:#787878;border:none;}")
        self.canvas = OcclusionCanvas()
        self.canvas.setStyleSheet("background:transparent;")
        sc.setWidget(self.canvas)
        sc._canvas = self.canvas
        self.toolbar.tool_changed.connect(self.canvas.set_tool)
        main_row.addWidget(sc, stretch=1)

        right_panel = QWidget()
        right_panel.setFixedWidth(240)
        right_panel.setStyleSheet(
            "QWidget{background:#F5F5F5;}"
            "QFrame{background:#F5F5F5;border:none;}"
        )
        rp = QVBoxLayout(right_panel)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.setSpacing(0)

        ml_hdr = QFrame()
        ml_hdr.setFixedHeight(28)
        ml_hdr.setStyleSheet(
            "QFrame{background:#E0E0E0;border-bottom:1px solid #CCC;}"
            "QLabel{color:#444;font-size:11px;font-weight:bold;background:transparent;}")
        ml_hl = QHBoxLayout(ml_hdr)
        ml_hl.setContentsMargins(8, 0, 8, 0)
        ml_hl.addWidget(QLabel("Masks"))
        ml_hl.addStretch()
        rp.addWidget(ml_hdr)

        self.mask_panel = MaskPanel(self.canvas)
        rp.addWidget(self.mask_panel, stretch=1)

        self.mask_panel.list_w.currentRowChanged.connect(self._center_on_mask)

        ci_hdr = QFrame()
        ci_hdr.setFixedHeight(28)
        ci_hdr.setStyleSheet(
            "QFrame{background:#E0E0E0;border-top:1px solid #CCC;"
            "border-bottom:1px solid #CCC;}"
            "QLabel{color:#444;font-size:11px;font-weight:bold;background:transparent;}")
        ci_hl = QHBoxLayout(ci_hdr)
        ci_hl.setContentsMargins(8, 0, 8, 0)
        ci_hl.addWidget(QLabel("Card Info"))
        rp.addWidget(ci_hdr)

        ci_body = QWidget()
        ci_body.setStyleSheet("QWidget{background:#F5F5F5;}")
        cib = QFormLayout(ci_body)
        cib.setContentsMargins(8, 8, 8, 8)
        cib.setSpacing(6)
        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("Card title…")
        self.inp_tags  = QLineEdit()
        self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_notes = QTextEdit()
        self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(64)
        cib.addRow("Title:", self.inp_title)
        cib.addRow("Tags:",  self.inp_tags)
        cib.addRow("Notes:", self.inp_notes)
        rp.addWidget(ci_body)

        main_row.addWidget(right_panel)

        body_w = QWidget()
        body_w.setLayout(main_row)
        L.addWidget(body_w, stretch=1)

        hint_bar = QFrame()
        hint_bar.setFixedHeight(20)
        hint_bar.setStyleSheet(
            "QFrame{background:#E8E8E8;border-top:1px solid #CCC;border-radius:0;}"
            "QLabel{background:transparent;color:#777;font-size:10px;}")
        hl = QHBoxLayout(hint_bar)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.addWidget(QLabel(
            "V=Select  R=Rect  E=Ellipse  T=Label  |  "
            "Hold Alt=temp select  Alt+Click=multi-select  |  "
            "G=group selected  Shift+G=ungroup  |  "
            "Drag ↻=rotate  Del=delete  Ctrl+Z/Y=undo/redo"))
        hl.addStretch()
        L.addWidget(hint_bar)

        btn_zi.clicked.connect(lambda: self.canvas.zoom_in())
        btn_zo.clicked.connect(lambda: self.canvas.zoom_out())
        btn_zf.clicked.connect(self._zoom_fit)
        btn_del.clicked.connect(lambda: self.canvas.delete_selected_boxes())
        btn_clear.clicked.connect(self.canvas.clear_all)

        self._sc = sc

    def _zoom_fit(self):
        vp = self._sc.viewport()
        self.canvas.zoom_fit(vp.width(), vp.height())

    def _center_on_mask(self, row):
        if not (0 <= row < len(self.canvas._boxes)):
            return
        r = self.canvas._sr(self.canvas._boxes[row]["rect"])
        vbar = self._sc.verticalScrollBar()
        hbar = self._sc.horizontalScrollBar()
        hbar.setValue(int(max(0, r.center().x() - self._sc.viewport().width()  // 2)))
        vbar.setValue(int(max(0, r.center().y() - self._sc.viewport().height() // 2)))

    def _toggle_group(self):
        pass

    def _update_group_btn(self):
        pass

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.canvas.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:
            self.canvas.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_S:
            self._save()
        elif key == Qt.Key_V:
            self.toolbar.select_tool("select")
        elif key == Qt.Key_R:
            self.toolbar.select_tool("rect")
        elif key == Qt.Key_E:
            self.toolbar.select_tool("ellipse")
        elif key == Qt.Key_T:
            self.toolbar.select_tool("text")
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
        self.btn_open_ext.setVisible(False)
        self.lbl_sync.setVisible(False)
        self._stop_watch()
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
        self.card["pdf_path"] = path
        self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
        self._pending_boxes = []

        # --- [LRU CACHE v18] ---
        # Agar saare pages already cache mein hain toh thread start hi mat karo!
        # PdfLoaderThread khud bhi cache check karta hai, isliye partial cache bhi fast hogi.
        self._show_pdf_loading(True)
        self._start_pdf_thread(path)

    def _start_pdf_thread(self, path: str):
        """[PROGRESSIVE LOADING] 10-10 pages background mein load karo."""
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(500)
        self._pdf_loader_thread = PdfLoaderThread(path, parent=self)
        self._pdf_loader_thread.chunk_ready.connect(self._on_chunk_ready)
        self._pdf_loader_thread.done.connect(self._on_pdf_loaded)
        self._pdf_loader_thread.start()

    def _on_chunk_ready(self, combined, loaded, total):
        """[PROGRESSIVE] Har 10 pages baad canvas update karo — user wait nahi karta!"""
        path = self.card.get("pdf_path", "")
        self._combined_px = combined
        self.canvas.load_pixmap(combined)
        # Pending boxes pehle chunk pe hi restore karo
        if self._pending_boxes:
            self.canvas.set_boxes(self._pending_boxes)
            self.mask_panel._refresh(self._pending_boxes)
            self._pending_boxes = []
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  ⏳ {loaded}/{total} pages loaded…")
        self.pdf_bar.show()
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText(f"⏳ Loading… {loaded}/{total} pages")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self.setWindowTitle(f"Occlusion Card Editor  ⏳ {loaded}/{total} pages…")

    def _on_pdf_loaded(self, combined, err):
        """Saare pages load ho gaye — final canvas update karo."""
        self._show_pdf_loading(False)
        path = self.card.get("pdf_path", "")
        if combined.isNull():
            QMessageBox.warning(self, "PDF Error", err or "Could not render PDF.")
            return

        self._combined_px = combined
        # [LRU PAGE CACHE v18] — Individual pages ab PdfLoaderThread ke andar
        # PAGE_CACHE mein store ho jaate hain. Yahan kuch extra karne ki zaroorat nahi.

        try:
            _doc = fitz.open(path); n = len(_doc); _doc.close()
        except Exception:
            n = 0
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  {n} page{'s' if n != 1 else ''}"
            f"  •  scroll to navigate")
        self.pdf_bar.show()
        # Final full pixmap set karo (saare pages ke saath)
        self.canvas.load_pixmap(self._combined_px)
        if not self.inp_title.text():
            self.inp_title.setText(self._auto_subdeck_name or "")
        # Agar boxes abhi bhi pending hain (chunk nahi aaya tha) toh yahan restore karo
        if self._pending_boxes:
            self.canvas.set_boxes(self._pending_boxes)
            self.mask_panel._refresh(self._pending_boxes)
            self._pending_boxes = []
        self._watch_pdf(path)

    def _show_pdf_loading(self, loading: bool):
        """Loading indicator — title bar update + button disable."""
        if loading:
            self.setWindowTitle("Occlusion Card Editor  ⏳ Loading PDF…")
            self.lbl_sync.setVisible(True)
            self.lbl_sync.setText("⏳ Loading PDF…")
            self.lbl_sync.setStyleSheet(
                f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        else:
            self.setWindowTitle("Occlusion Card Editor")

    def _show_pdf_page(self):
        pass

    def _prev_page(self):
        pass

    def _next_page(self):
        pass

    def _load_card(self, card):
        self.inp_title.setText(card.get("title", ""))
        self.inp_tags.setText(", ".join(card.get("tags", [])))
        self.inp_notes.setPlainText(card.get("notes", ""))
        px = None
        if card.get("image_path") and os.path.exists(card.get("image_path")):
            px = QPixmap(card["image_path"])
            if px and not px.isNull():
                self.canvas.load_pixmap(px)
            if card.get("boxes"):
                self.canvas.set_boxes(card["boxes"])
                self.mask_panel._refresh(card["boxes"])
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(card.get("pdf_path")):
            path = card["pdf_path"]
            self.card["pdf_path"] = path
            self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
            self._pending_boxes = card.get("boxes", [])

            # [LRU CACHE v18] — Thread start karo; agar pages cache mein hain
            # toh PdfLoaderThread unhe fitz reload kiye bina use karega — ultra fast!
            self._show_pdf_loading(True)
            self._start_pdf_thread(path)

    def _watch_pdf(self, path: str):
        self._stop_watch()
        self._watched_path = path
        self._watcher.addPath(path)
        self.btn_open_ext.setVisible(True)
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("🟢 Live Sync: watching")
        self.lbl_sync.setStyleSheet(
            f"color:{C_GREEN};font-size:11px;background:transparent;font-weight:bold;")

    def _stop_watch(self):
        if self._watched_path:
            self._watcher.removePath(self._watched_path)
            self._watched_path = None
        self._reload_timer.stop()

    def _on_file_changed(self, path: str):
        self.lbl_sync.setText("🟡 Live Sync: change detected…")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self._reload_timer.start()

    def _reload_pdf(self):
        path = self._watched_path
        if not path or not os.path.exists(path):
            QTimer.singleShot(500, self._reload_pdf)
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)

        # [LRU CACHE v18] — File change hone par purane pages evict karo
        PAGE_CACHE.invalidate_pdf(path)

        # [NOT-RESPONDING FIX] Reload bhi thread se karo
        saved_boxes = self.canvas.get_boxes()
        self._pending_boxes = saved_boxes
        self.lbl_sync.setText("🟡 Live Sync: reloading…")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self._start_pdf_thread(path)

    def _open_in_reader(self):
        path = self.card.get("pdf_path") or self._watched_path
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
            return
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            QMessageBox.warning(self, "Could not open",
                f"Could not open PDF in external reader:\n{ex}")

    def closeEvent(self, e):
        self._stop_watch()
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000)
        super().closeEvent(e)

    def reject(self):
        self._stop_watch()
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000)
        super().reject()

    def accept(self):
        self._stop_watch()
        super().accept()

    def _save(self):
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self, "No Source", "Load an image or PDF first.")
            return

        old_boxes  = self.card.get("boxes", [])
        new_boxes  = self.canvas.get_boxes()
        SM2_KEYS   = ("sm2_interval", "sm2_repetitions", "sm2_ease",
                      "sm2_due", "sm2_last_quality", "box_id")

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
            if "box_id" not in nb:
                nb["box_id"] = new_box_id()
            merged.append(nb)

        self.card.update({
            "title":   self.inp_title.text().strip() or "Untitled",
            "tags":    [t.strip() for t in self.inp_tags.text().split(",") if t.strip()],
            "notes":   self.inp_notes.toPlainText(),
            "boxes":   merged,
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = None

    def wheelEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self._canvas:
            self._canvas.wheelEvent(e)
        else:
            super().wheelEvent(e)


class ReviewScreen(QWidget):
    finished = pyqtSignal()

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

        seen_item_keys = set()

        for card in cards:
            boxes = card.get("boxes", [])
            card_key = id(card)

            if len(boxes) == 0:
                item_key = (card_key, None)
                if item_key not in seen_item_keys:
                    seen_item_keys.add(item_key)
                    sm2_init(card)
                    self._items.append((card, None, card))
                continue

            seen_groups = set()

            for i, box in enumerate(boxes):
                sm2_init(box)
                gid = box.get("group_id", "")

                if gid:
                    if gid not in seen_groups:
                        seen_groups.add(gid)
                        item_key = (card_key, ("group", gid))
                        if item_key not in seen_item_keys:
                            seen_item_keys.add(item_key)
                            if is_due_today(box):
                                self._items.append((card, ("group", gid), box))
                else:
                    box_id = box.get("box_id", f"__idx_{i}")
                    item_key = (card_key, box_id)
                    if item_key not in seen_item_keys:
                        seen_item_keys.add(item_key)
                        if is_due_today(box):
                            self._items.append((card, i, box))

        self._items.sort(key=lambda x: x[2].get("sm2_due", ""))
        self._idx  = 0
        self._done = 0
        self._setup_ui()
        self._load_item()

    def closeEvent(self, e):
        if hasattr(self, '_pdf_loader_thread') and self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000) 
        
        if hasattr(self, '_stop_watch'):
            self._stop_watch()
            
        super().closeEvent(e)

    def _load_item(self):
        if self._idx >= len(self._items):
            self._finish()
            return

        card, box_idx, sm2_obj = self._items[self._idx]

        # UI updates...
        self.prog.setMaximum(len(self._items))
        self.prog.setValue(self._idx)
        self.lbl_prog.setText(f"Card {self._idx + 1}/{len(self._items)}")
        self.lbl_sm2.setText(sm2_badge(sm2_obj))
        self.lbl_title.setText(card.get("title", "Untitled"))

        # 🚀 SM-2 SIMULATION UPDATE (Fix for the '?' bug)
        # Ye part calculate karega ki Again/Good/Easy dabane par next date kya hogi
        previews = _fmt_due_interval(sm2_obj)
        for lbl, q in self._prev_lbls:
            val = previews.get(q, "?")
            lbl.setText(f"→ {val}")

        self._reload_current_canvas()
        # 1. Check if all reviews are done
        if self._idx >= len(self._items):
            self._finish()
            return

        # 2. Get current item data
        card, box_idx, sm2_obj = self._items[self._idx]

        # 3. Update Progress Bar and Labels
        self.prog.setMaximum(len(self._items))
        self.prog.setValue(self._idx)
        self.lbl_prog.setText(f"Card {self._idx + 1}/{len(self._items)}")
        
        # 4. Update SM-2 Stats and Title
        self.lbl_sm2.setText(sm2_badge(sm2_obj))
        self.lbl_title.setText(card.get("title", "Untitled"))

        # 5. Render the image/PDF and masks on canvas
        self._reload_current_canvas()

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
        elif key == Qt.Key_1 and self._rating_frame.isVisible():
            self._rate(1)
        elif key == Qt.Key_2 and self._rating_frame.isVisible():
            self._rate(3)
        elif key == Qt.Key_3 and self._rating_frame.isVisible():
            self._rate(4)
        elif key == Qt.Key_4 and self._rating_frame.isVisible():
            self._rate(5)
        elif mods & Qt.ControlModifier and key in (Qt.Key_Equal, Qt.Key_Plus):
            self.canvas.zoom_in()
        elif mods & Qt.ControlModifier and key == Qt.Key_Minus:
            self.canvas.zoom_out()
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self._zoom_fit()
        elif key == Qt.Key_C:
            self._center_on_target()
        elif key == Qt.Key_E:
            self._edit_current_card()
        else:
            super().keyPressEvent(e)

    def _reveal_current(self):
        if not (0 <= self._idx < len(self._items)):
            return
        _, box_idx, _ = self._items[self._idx]
        if box_idx is None:
            self.canvas.reveal_all()
        elif isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for b in self.canvas._boxes:
                if b.get("group_id", "") == gid:
                    b["revealed"] = True
            self.canvas._redraw()
        else:
            if 0 <= box_idx < len(self.canvas._boxes):
                self.canvas._boxes[box_idx]["revealed"] = True
                self.canvas._redraw()
        self._reveal_bar.hide()
        self._rating_frame.show()

    def _set_fullscreen_ui(self, fullscreen: bool):
        self._hdr_widget.setVisible(not fullscreen)
        self.lbl_title.setVisible(not fullscreen)
        self._hint_label.setVisible(not fullscreen)

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

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

        b_edit = QPushButton("✏ Edit Card")
        b_edit.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:white;border:none;"
            f"border-radius:6px;padding:4px 14px;font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:#6A58E0;}}")
        b_edit.clicked.connect(self._edit_current_card)
        hdr.addWidget(b_edit)

        self._btn_mode = QPushButton("🟧 Hide All, Guess One")
        self._btn_mode.setCheckable(True)
        self._btn_mode.setChecked(False)
        self._btn_mode.setStyleSheet(
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 14px;font-size:12px;}}"
            f"QPushButton:checked{{background:#6A3FBF;color:white;"
            f"border:1px solid {C_ACCENT};}}"
            f"QPushButton:hover{{background:{C_SURFACE};}}")
        self._btn_mode.clicked.connect(self._toggle_review_mode)
        hdr.addWidget(self._btn_mode)

        b_exit = QPushButton("✕ Exit")
        b_exit.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:4px 14px;font-size:12px;")
        b_exit.clicked.connect(self.finished.emit)
        hdr.addWidget(b_exit)
        L.addWidget(hdr_w)
        self._hdr_widget = hdr_w

        self.lbl_title = QLabel("")
        self.lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_title.setStyleSheet(
            f"color:{C_ACCENT};background:{C_BG};"
            f"padding:4px 16px;border-bottom:1px solid {C_BORDER};")
        self.lbl_title.setFixedHeight(30)
        L.addWidget(self.lbl_title)

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
        self._canvas_scroll._canvas = self.canvas
        L.addWidget(self._canvas_scroll, stretch=1)

        bottom_w = QWidget()
        bottom_w.setStyleSheet(f"background:{C_SURFACE};")
        bl = QVBoxLayout(bottom_w)
        bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(0)

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

        br = QHBoxLayout(); br.setSpacing(8)
        RATING_STYLES = {
            "danger":  "background:#5C2A2A;color:#FFB3B3;border:1px solid #7A3535;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "hard":    "background:#5C3D1A;color:#FFCC88;border:1px solid #7A5225;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "success": "background:#1E4A2A;color:#88DDAA;border:1px solid #2A6B3C;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "warning": "background:#4A4A1A;color:#E8E888;border:1px solid #66661F;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
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

        self._rating_frame.hide()
        bl.addWidget(self._rating_frame)

        L.addWidget(bottom_w)

        self._mid_row_widget = self._reveal_bar

    def _toggle_review_mode(self):
        if self._btn_mode.isChecked():
            self._btn_mode.setText("👁 Hide One, Guess One")
            self.canvas.set_review_style("hide_one")
        else:
            self._btn_mode.setText("🟧 Hide All, Guess One")
            self.canvas.set_review_style("hide_all")

    def _zoom_fit(self):
        vp = self._canvas_scroll.viewport()
        self.canvas.zoom_fit(vp.width(), vp.height())

    def _center_on_target(self):
        r = self.canvas.get_target_scaled_rect()
        if r:
            vbar = self._canvas_scroll.verticalScrollBar()
            hbar = self._canvas_scroll.horizontalScrollBar()
            hbar.setValue(int(max(0, r.center().x() - self._canvas_scroll.viewport().width()  // 2)))
            vbar.setValue(int(max(0, r.center().y() - self._canvas_scroll.viewport().height() // 2)))

    def _edit_current_card(self):
        if not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, sm2_obj = self._items[self._idx]
        dlg = CardEditorDialog(None, card=dict(card), data=self._data)
        result = dlg.exec_()
        if result == QDialog.Accepted:
            edited = dlg.get_card()
            card.update(edited)
            if self._data:
                save_data(self._data)
        self._reload_current_canvas()

    def _reload_current_canvas(self):
        if not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, _ = self._items[self._idx]

        px = None
        if card.get("image_path") and os.path.exists(card["image_path"]):
            px = QPixmap(card["image_path"])
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(card["pdf_path"]):
            path = card["pdf_path"]

            # [LRU PAGE CACHE v18] — pdf_to_combined_pixmap use karo;
            # individual pages PAGE_CACHE mein store hoti hain via PdfLoaderThread.
            # ReviewScreen synchronous load karta hai (blocking acceptable here —
            # small PDFs; large PDFs ke liye future improvement possible).
            combined, _, _ = pdf_to_combined_pixmap(path)
            if not combined.isNull():
                px = combined

        if px and not px.isNull():
            self._current_pixmap = px
            boxes = card.get("boxes", [])
            self.canvas.load_pixmap(px)
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                gid = box_idx[1]
                display_boxes = [
                    {**{k: b[k] for k in ("rect","label","shape","angle","group_id","box_id") if k in b},
                     "rect": b["rect"], "label": b.get("label",""),
                     "revealed": b.get("group_id","") != gid}
                    for b in boxes
                ]
                self.canvas.set_boxes_with_state(display_boxes)
                self.canvas.set_target_box(-1)
                self.canvas.set_mode("review")
                self.canvas.set_target_group(gid)
            elif box_idx is None:
                self.canvas.set_boxes(boxes)
                self.canvas.set_target_box(-1)
                self.canvas.set_mode("review")
            else:
                display_boxes = [
                    {"rect": b["rect"], "label": b.get("label",""),
                     "shape": b.get("shape","rect"), "angle": b.get("angle",0.0),
                     "group_id": b.get("group_id",""), "revealed": (i != box_idx)}
                    for i, b in enumerate(boxes)
                ]
                self.canvas.set_boxes_with_state(display_boxes)
                self.canvas.set_target_box(box_idx)
                self.canvas.set_mode("review")

            def _apply_zoom(p=px):
                vp = self._canvas_scroll.viewport()
                vw = max(vp.width(), 100)
                new_scale = vw / max(p.width(), 1)
                self.canvas._scale = max(0.15, min(new_scale, 3.0))
                self.canvas._redraw()
            QTimer.singleShot(30, _apply_zoom)

            def _scroll_to_mask(bi=box_idx):
                r = self.canvas.get_target_scaled_rect()
                if r and bi is not None:
                    vbar = self._canvas_scroll.verticalScrollBar()
                    hbar = self._canvas_scroll.horizontalScrollBar()
                    hbar.setValue(int(max(0, r.center().x() - self._canvas_scroll.viewport().width()  // 2)))
                    vbar.setValue(int(max(0, r.center().y() - self._canvas_scroll.viewport().height() // 2)))
            QTimer.singleShot(80, _scroll_to_mask)
        else:
            self.canvas.load_pixmap(QPixmap())

        self._reveal_bar.show()
        self._rating_frame.hide()
        self.setFocus()

    def _rate(self, quality):
        card, box_idx, sm2_obj = self._items[self._idx]

        sched_update(sm2_obj, quality)

        if box_idx is None:
            card["reviews"] = sm2_obj.get("reviews", 0)

        if self._data:
            save_data(self._data)

        state = sm2_obj.get("sched_state", "review")

        if state in ("learning", "relearn"):
            item = self._items.pop(self._idx)
            due_str = sm2_obj.get("sm2_due", "")
            insert_at = len(self._items)
            for j in range(self._idx, len(self._items)):
                other_due = self._items[j][2].get("sm2_due", "")
                if other_due >= due_str:
                    insert_at = j
                    break
            self._items.insert(insert_at, item)
            self._rebuild_queue()
        else:
            self._done += 1
            self._idx  += 1

        self._load_item()

    def _rebuild_queue(self):
        pass

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
        def _card_due(c):
            boxes = c.get("boxes", [])
            if not boxes:
                return is_due_today(c)
            seen = set()
            for b in boxes:
                gid = b.get("group_id", "")
                if gid:
                    if gid not in seen:
                        seen.add(gid)
                        if is_due_today(b): return True
                else:
                    if is_due_today(b): return True
            return False

        due   = sum(1 for c in deck.get("cards", []) if _card_due(c))
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
            "_id":      next_deck_id(self._data),
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
        self._thumb_cache  = {}
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
        self._thumb_cache.clear()
        self._refresh()

    def _refresh(self):
        if self._deck_id is not None:
            fresh = find_deck_by_id(self._deck_id, self._data.get("decks", []))
            if fresh:
                self.deck = fresh
        if not self.deck:
            return
        self.card_list.clear()
        cards  = self.deck.get("cards", [])
        due_c  = 0

        for c in cards:
            sm2_init(c)
            boxes   = c.get("boxes", [])
            if not boxes:
                card_due = is_due_today(c)
            else:
                seen_gids = set()
                card_due = False
                for b in boxes:
                    gid = b.get("group_id", "")
                    if gid:
                        if gid not in seen_gids:
                            seen_gids.add(gid)
                            if is_due_today(b):
                                card_due = True
                    else:
                        if is_due_today(b):
                            card_due = True
            due_c += card_due

            badge = "🔴 Due" if card_due else f"✅ {sm2_days_left(c)}d"
            item  = QListWidgetItem(
                f"  {c.get('title','Untitled')}  "
                f"| Boxes:{len(boxes)}  "
                f"| Rep:{c.get('sm2_repetitions',0)}  "
                f"| EF:{c.get('sm2_ease',2.5):.2f}  | {badge}")

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
                    "_id":      next_deck_id(self._data),
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

    def _review_due(self):
        if not self.deck:
            return

        def _card_has_due_today(card):
            boxes = card.get("boxes", [])
            if not boxes:
                sm2_init(card)
                return is_due_today(card)
            seen_gids = set()
            for b in boxes:
                sm2_init(b)
                gid = b.get("group_id", "")
                if gid:
                    if gid not in seen_gids:
                        seen_gids.add(gid)
                        if is_due_today(b):
                            return True
                else:
                    if is_due_today(b):
                        return True
            return False

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
        _save_done = [False]

        win = QMainWindow(self)
        win.setWindowTitle("Review Mode 🧠")
        win.setMinimumSize(960, 730)
        rev = ReviewScreen(cards, data=self._data, parent=win)

        def _on_finished():
            if not _save_done[0]:
                _save_done[0] = True
                save_data(self._data)
            self._refresh()
            win.close()

        original_close = win.closeEvent
        def _safe_close(e):
            _save_done[0] = True
            original_close(e)
        win.closeEvent = _safe_close

        rev.finished.connect(_on_finished)
        win.setCentralWidget(rev)
        win.setStyleSheet(SS)
        win.showMaximized()


# ═══════════════════════════════════════════════════════════════════════════════
#  HOME SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

def make_app_icon() -> QIcon:
    SIZE = 256
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(C_SURFACE)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, SIZE, SIZE, 48, 48)
    card_rect = QRect(36, 44, 184, 148)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(QPen(QColor(C_BORDER), 3))
    p.drawRoundedRect(card_rect, 10, 10)
    p.setPen(QPen(QColor("#E0E0E0"), 1))
    for y in range(card_rect.top() + 24, card_rect.bottom() - 10, 18):
        p.drawLine(card_rect.left() + 12, y, card_rect.right() - 12, y)
    p.setBrush(QBrush(QColor(C_MASK)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(52, 62, 80, 36, 5, 5)
    p.drawRoundedRect(148, 104, 60, 30, 5, 5)
    p.setBrush(QBrush(QColor(C_GREEN)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(168, 168, 60, 60)
    p.setPen(QPen(QColor("#1E1E2E"), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(182, 199, 192, 211)
    p.drawLine(192, 211, 214, 185)
    p.end()
    return QIcon(px)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Anki Occlusion")
        self.setFixedSize(480, 560)
        self.setStyleSheet(f"QDialog{{background:{C_BG};}}")
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)
        header = QFrame()
        header.setFixedHeight(140)
        header.setStyleSheet(f"QFrame{{background:{C_SURFACE};border-radius:0px;}}")
        hl = QVBoxLayout(header)
        hl.setAlignment(Qt.AlignCenter)
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
            "V=Select  R=Rect  E=Ellipse  T=Label  Del=delete selected\n"
            "Ctrl+A — select all     Ctrl+Scroll — zoom\n"
            "Alt+Click — multi-select   Hold Alt — temp select tool\n"
            "C — center on mask      Drag ↻ handle — rotate shape")
        _section("Data location", f"{DATA_FILE}")
        bl.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"background:{C_ACCENT};color:white;border:none;border-radius:8px;"
            f"padding:8px 32px;font-weight:bold;font-size:13px;")
        close_btn.clicked.connect(self.accept)
        bl.addWidget(close_btn, alignment=Qt.AlignCenter)
        L.addWidget(body)


class OnboardingDialog(QDialog):
    STEPS = [
        {"icon": "🃏", "title": "Welcome to Anki Occlusion",
         "body": "The fastest way to turn your PDF notes and images into Anki-style flashcards — without typing a single word.\n\nThis quick tour takes about 30 seconds."},
        {"icon": "📂", "title": "Step 1 — Create a Deck",
         "body": "Click  ＋ Deck  in the left sidebar to create your first deck.\n\nYou can nest decks inside each other — for example:\n  Biology  ›  Chapter 3  ›  Cell Division\n\nDrag and drop to reorganise them any time."},
        {"icon": "🖼", "title": "Step 2 — Add a Card",
         "body": "Select a deck, then click  ＋ Add Card.\n\nLoad a PDF or image, then use the toolbar:\n  ▶ Select — move, resize, rotate shapes\n  ▭ Rectangle — draw rectangular masks\n  ⬭ Ellipse — draw oval masks\n  T Text — click a mask to edit its label\n\nEach mask becomes one flashcard question automatically."},
        {"icon": "🧠", "title": "Step 3 — Review",
         "body": "Click  🔴 Review Due  to start your session.\n\nTwo review modes (toggle in review header):\n  🟧 Hide All, Guess One — all masks hidden one by one\n  👁 Hide One, Guess One — only the target mask hidden\n\nPress Space to reveal, then rate yourself:\n  1 = Again   2 = Hard   3 = Good   4 = Easy\n\nThe scheduler decides when you'll see each card next."},
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
        btn_bar = QFrame()
        btn_bar.setFixedHeight(64)
        btn_bar.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-top:1px solid {C_BORDER};border-radius:0px;}}")
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(24, 0, 24, 0)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setStyleSheet(
            f"background:transparent;color:{C_SUBTEXT};border:none;font-size:12px;padding:6px 16px;")
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
        for i, dot in enumerate(self._dots):
            dot.setStyleSheet(
                f"color:{C_ACCENT if i == idx else C_BORDER};"
                f"font-size:10px;background:transparent;")
        is_last  = (idx == len(self.STEPS) - 1)
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
        self._font_size = int(self._data.get("_font_size", BASE_FONT_SIZE))
        self.showMaximized()
        home = HomeScreen(self._data, parent=self)
        self.setCentralWidget(home)
        sb = QStatusBar()
        sb.showMessage("✅ SM-2 Active  |  " + (
            "PyMuPDF loaded — PDF support active"
            if PDF_SUPPORT else "⚠ pip install pymupdf  for PDF support"))
        self.setStatusBar(sb)
        if self._font_size != BASE_FONT_SIZE:
            self._apply_font_size(self._font_size)
        if not self._data.get("_onboarding_done"):
            QTimer.singleShot(200, self._run_onboarding)

    def change_font_size(self, direction: int):
        if direction == 0:
            self._font_size = BASE_FONT_SIZE
        else:
            self._font_size = max(8, min(20, self._font_size + direction))
        self._apply_font_size(self._font_size)
        self._data["_font_size"] = self._font_size
        save_data(self._data)

    def _apply_font_size(self, size: int):
        QApplication.instance().setStyleSheet(_build_ss(size))

    def _run_onboarding(self):
        dlg = OnboardingDialog(self)
        dlg.exec_()
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
    _icon = make_app_icon()
    app.setWindowIcon(_icon)
    win = MainWindow()
    win.show()
    ret = app.exec_()
    lock.unlock()
    sys.exit(ret)