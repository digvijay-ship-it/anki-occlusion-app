"""
editor_ui.py  —  v21  (Mask Cache Qt-Limit Fix)
================================================

v21 Bug Fix:
  PROBLEM: Masks were not loading after a certain page number.
  ROOT CAUSE: _rebuild_mask_cache() created QPixmap(sw, sh) for the ENTIRE
  canvas height. Qt silently fails / truncates any QPixmap whose height
  exceeds 32 767 px (GPU texture limit) — the same limit that broke pages
  in v17. A 42-page PDF at 1.5x zoom = ~50 000 px tall mask cache → all
  masks on pages beyond ~27 were invisible.

  FIX:
    • _rebuild_mask_cache() now checks: if sh > 32 767, skip the cache and
      set _mask_cache_layer = None (direct-draw signal).
    • paintEvent mask section: if cache is None, draws all masks directly
      onto the painter — no single giant QPixmap ever created.
    • Performance: for normal PDFs (< ~27 pages at 1.5x) the GPU cache path
      is unchanged. Only large PDFs fall back to direct draw.

v20 (Virtual Page Renderer):
  v17 introduced _build_combined_from_pages() which creates ONE giant QPixmap
  from all PDF pages stacked vertically. Qt silently truncates any QPixmap
  whose height exceeds 32 767 px (GPU texture limit). A 42-page A4 PDF at
  1.5x zoom = ~50 000 px tall → bottom ~12 pages were invisible black.

HOW IT'S FIXED — Virtual Page Renderer:
  OcclusionCanvas now stores  self._pages : list[QPixmap]  — one per PDF page.
  paintEvent draws ONLY the pages whose screen rect intersects the clip region.
  The widget is resized to the full virtual height (sum of all page heights +
  gaps), so the QScrollArea scrollbar is always correct — giving the same
  smooth continuous-scroll feeling as before.
  No single pixmap is ever larger than one page (~1 200 px) — Qt limit bypassed.

BACKWARD COMPATIBILITY:
  • load_pixmap(px)  — single-image mode, unchanged
  • load_pages(pages) — new; replaces load_pixmap(combined_px)
  • append_pages(pages) — progressive loading chunks
  • All box / mask / zoom / ink / undo APIs identical
  • CardEditorDialog, MaskPanel, ToolBar, _ZoomableScrollArea — unchanged
  • anki_occlusion_v19.py requires two small edits (see bottom of this file)
"""

import sys
from datetime import datetime
import math
import os
import fitz
import copy
import uuid

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QListWidget, QFrame, QScrollArea, QMessageBox, QFileDialog,
    QFormLayout, QTextEdit, QSizePolicy, QDialog, QApplication
)
from PyQt5.QtCore import (
    Qt, QPointF, QRectF, QTimer, pyqtSignal, QSize, QEvent,
    QFileSystemWatcher
)
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QBrush
)

from sm2_engine import sm2_init
from pdf_engine import PDF_SUPPORT, PdfLoaderThread, pdf_page_to_pixmap
from cache_manager import PAGE_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY
from data_manager import new_box_id

C_GREEN  = "#50FA7B"
C_MASK   = "#F7916A"
C_ACCENT = "#7C6AF7"
C_YELLOW = "#F1FA8C"
PAGE_GAP = 12   # vertical gap between pages in image-space pixels

_QT_MAX_PX = 32_767  # Qt GPU texture hard limit — QPixmap silently fails above this


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
#  OCCLUSION CANVAS  —  Virtual Page Renderer
# ═══════════════════════════════════════════════════════════════════════════════

class OcclusionCanvas(QWidget):
    """
    Renders PDF pages as a continuous scrollable document without ever
    combining them into a single QPixmap. Each page is drawn independently
    in paintEvent, only when it intersects the visible clip region.

    Coordinate system:
      "image-space" — unscaled pixels (what _boxes store)
      "screen-space" — image-space × _scale (what Qt draws)
    """
    boxes_changed = pyqtSignal(list)

    TOOLS     = ("select", "rect", "ellipse", "text")
    _HANDLE_R = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tell Qt this widget paints every pixel itself — no background blend needed.
        # This eliminates the implicit background fill pass Qt does before paintEvent,
        # which is the main cause of scroll lag on large canvas widgets.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

        # ── image sources ─────────────────────────────────────────────────────
        self._px        = None   # QPixmap | None  — single-image mode
        self._pages     = []     # list[QPixmap]   — PDF page list (image-space)
        self._page_tops = []     # list[int]        — y-offset of each page (image-space)
        self._total_h   = 0      # int              — virtual canvas height (image-space)
        self._total_w   = 0      # int              — max page width (image-space)

        # ── interaction ───────────────────────────────────────────────────────
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

        self._undo_stack = []
        self._redo_stack = []

        # ── mask GPU cache ────────────────────────────────────────────────────
        self._mask_cache_layer = None   # QPixmap
        self._mask_cache_dirty = True

        # ── ink layer ─────────────────────────────────────────────────────────
        self._ink_active         = False
        self._ink_strokes        = []
        self._ink_current        = []
        self._ink_color_idx      = 0
        self._ink_colors         = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]
        self._ink_width          = 1.2
        self._ink_ctrl_last_time = 0.0

        # ── zoom ──────────────────────────────────────────────────────────────
        self._fast_zoom  = False
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._finalize_zoom)

        self._smooth_timer = QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.timeout.connect(self._apply_smooth)

        # ── per-page scaled pixmap cache ──────────────────────────────────────
        # dict: page_idx → (scale_at_cache_time, QPixmap)
        self._spx_cache = {}

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # =========================================================================
    #  LOAD API
    # =========================================================================

    def load_pixmap(self, px: QPixmap):
        """Single-image mode (non-PDF). Clears any page list."""
        self._pages     = []
        self._page_tops = []
        self._total_h   = 0
        self._total_w   = 0
        self._spx_cache.clear()
        if px is None or px.isNull():
            self._px = None
            self._boxes = []
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._invalidate_mask_cache()
            self.resize(1, 1)
            self.update()
            return
        self._px = px
        self._boxes = []
        self._scale = 1.0
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._invalidate_mask_cache()
        self._resize_canvas()
        self.update()

    def load_pages(self, pages: list):
        """File: editor_ui.py -> Class: OcclusionCanvas -> Function: load_pages"""
        self._px = None
        self._pages = [p for p in pages if p and not p.isNull()]
        self._spx_cache.clear()
        self._compute_layout()
        self._invalidate_mask_cache()
        self._resize_canvas()
        
        # ⚡ NEW: Registry ko inform karo (Requires a path variable)
        # Agar path available nahi hai toh placeholder use karein
        if hasattr(self, "_current_pdf_path") and self._current_pdf_path:
            MASK_REGISTRY.register(self._current_pdf_path, self)
            
        self.update()

    def append_pages(self, pages: list):
        """Add more pages (progressive loading). Preserves existing boxes."""
        new = [p for p in pages if p and not p.isNull()]
        if not new:
            return
        self._pages.extend(new)
        self._compute_layout()
        self._invalidate_mask_cache()
        self._resize_canvas()
        self.update()

    # =========================================================================
    #  LAYOUT
    # =========================================================================

    def _compute_layout(self):
        """File: editor_ui.py -> Class: OcclusionCanvas -> Function: _compute_layout"""
        if not self._pages:
            self._page_tops = []
            self._total_h = 0
            self._total_w = 0
            return
        tops = []
        y = 0
        max_w = 0
        for i, px in enumerate(self._pages):
            tops.append(y)
            max_w = max(max_w, px.width())
            y += px.height() # ⚡ Har page ki height judna MUST hai
            if i < len(self._pages) - 1:
                y += PAGE_GAP # Pages ke beech ka space
        self._page_tops = tops
        self._total_h = y # ⚡ Yahi height scrollbar banati hai
        self._total_w = max_w

    def _canvas_wh(self):
        """File: editor_ui.py -> Class: OcclusionCanvas -> Function: _canvas_wh"""
        if self._px and not self._px.isNull():
            return self._px.width(), self._px.height()
        return self._total_w, self._total_h # PDF के लिए सही डायमेंशन यहाँ से मिलेंगे

    def _resize_canvas(self):
        """File: editor_ui.py -> Class: OcclusionCanvas -> Function: _resize_canvas"""
        w, h = self._canvas_wh()
        new_w = max(int(w * self._scale), 1)
        new_h = max(int(h * self._scale), 1)
        self.resize(new_w, new_h)
        self.updateGeometry()

    def has_content(self):
        return bool((self._px and not self._px.isNull()) or self._pages)

    # =========================================================================
    #  COORDINATE HELPERS
    # =========================================================================

    def _ip(self, pos) -> QPointF:
        return QPointF(pos.x() / self._scale, pos.y() / self._scale)

    def _sr(self, r: QRectF) -> QRectF:
        return QRectF(r.x() * self._scale, r.y() * self._scale,
                      r.width() * self._scale, r.height() * self._scale)

    # =========================================================================
    #  SCALED PAGE CACHE  — avoids re-scaling unchanged pages every paintEvent
    # =========================================================================

    def _get_scaled_page(self, idx: int) -> QPixmap:
        cached_scale, cached_px = self._spx_cache.get(idx, (None, None))
        if cached_scale == self._scale and cached_px is not None:
            return cached_px
        src  = self._pages[idx]
        spx  = src.scaled(int(src.width()  * self._scale),
                          int(src.height() * self._scale),
                          Qt.KeepAspectRatio, Qt.FastTransformation)
        self._spx_cache[idx] = (self._scale, spx)
        return spx

    # =========================================================================
    #  PAINT EVENT  — the heart of the virtual renderer
    # =========================================================================

    def paintEvent(self, event):
        """File: editor_ui.py -> Class: OcclusionCanvas -> FIXED paintEvent"""
        p    = QPainter(self)
        clip = event.rect()

        # 1. Background Fill
        p.fillRect(clip, QColor("#1E1E2E"))

        # 2. Draw PDF Pages (Background Layer)
        if self._px and not self._px.isNull():
            spx  = self._px.scaled(int(self._px.width()  * self._scale),
                                   int(self._px.height() * self._scale),
                                   Qt.KeepAspectRatio, Qt.FastTransformation)
            p.drawPixmap(0, 0, spx)

        elif self._pages:
            sep_pen = QPen(QColor("#45475A"), 2)
            for i, page_px in enumerate(self._pages):
                scr_top = int(self._page_tops[i] * self._scale)
                scr_h   = int(page_px.height()   * self._scale)
                scr_bot = scr_top + scr_h

                if scr_bot < clip.top(): continue
                if scr_top > clip.bottom(): break

                p.drawPixmap(0, scr_top, self._get_scaled_page(i))

                if i < len(self._pages) - 1:
                    sep_y = scr_bot + int(PAGE_GAP * self._scale) // 2
                    p.setPen(sep_pen)
                    p.drawLine(0, sep_y, self.width(), sep_y)

        # 3. ⚡ MASK LAYER (Must be drawn AFTER pages to be visible)
        # Cache is rebuilt via QTimer in _invalidate_mask_cache, never during paint

        if self._mask_cache_layer and not self._mask_cache_layer.isNull():
            # Fast path: GPU-cached QPixmap (normal PDFs within Qt 32 767px limit)
            p.drawPixmap(0, 0, self._mask_cache_layer)
        else:
            # ✅ FIX (v21): Direct-draw fallback for large PDFs (sh > 32 767px).
            # _rebuild_mask_cache() sets _mask_cache_layer = None when canvas is too
            # tall for a single QPixmap. Draw every mask directly onto the painter
            # instead — no Qt texture limit, no invisible masks on later pages.
            p.setRenderHint(QPainter.Antialiasing)
            for i, b in enumerate(self._boxes):
                if self._drag_op and i == self._selected_idx:
                    continue   # skip dragged box — drawn live below
                self._draw_box(p, i, b)

        # 4. Interactive Elements (Top Layer)
        p.setRenderHint(QPainter.Antialiasing)
        if self._drag_op and self._selected_idx >= 0:
            self._draw_box(p, self._selected_idx, self._boxes[self._selected_idx])

        if self._drawing and not self._live_rect.isEmpty():
            self._draw_live(p)

        self._draw_ink_layer(p)
        p.end()
        
    # =========================================================================
    #  MASK GPU CACHE
    # =========================================================================

    def _invalidate_mask_cache(self):
        self._mask_cache_dirty = True
        QTimer.singleShot(0, self._rebuild_mask_cache_if_dirty)

    def _rebuild_mask_cache_if_dirty(self):
        if self._mask_cache_dirty:
            self._rebuild_mask_cache()
            self.update()

    def _rebuild_mask_cache(self):
        if not self.has_content():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return
        w, h = self._canvas_wh()
        sw, sh = int(w * self._scale), int(h * self._scale)
        if sw < 1 or sh < 1:
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        # ✅ FIX (v21): Agar canvas height Qt GPU limit (32 767px) se zyada ho,
        # QPixmap silently fail/truncate hota hai — same bug jo pages mein v17 mein tha.
        # Is case mein cache skip karo; paintEvent direct-draw fallback use karega.
        if sh > _QT_MAX_PX or sw > _QT_MAX_PX:
            self._mask_cache_layer = None   # None = direct-draw signal for paintEvent
            self._mask_cache_dirty = False
            return

        self._mask_cache_layer = QPixmap(sw, sh)
        self._mask_cache_layer.fill(Qt.transparent)
        mp = QPainter(self._mask_cache_layer)
        mp.setRenderHint(QPainter.Antialiasing)
        for i, b in enumerate(self._boxes):
            if self._drag_op and i == self._selected_idx:
                continue   # skip dragged box — drawn live in paintEvent
            self._draw_box(mp, i, b)
        mp.end()
        self._mask_cache_dirty = False

    # =========================================================================
    #  ZOOM
    # =========================================================================

    def zoom_in(self):
        self._scale = min(self._scale * 1.10, 8.0)
        self._on_zoom()

    def zoom_out(self):
        self._scale = max(self._scale / 1.10, 0.05)
        self._on_zoom()

    def zoom_fit(self, viewport_w, viewport_h):
        w, h = self._canvas_wh()
        if w < 1 or h < 1:
            return
        self._scale = min(viewport_w / w, viewport_h / h)
        self._on_zoom()

    def _on_zoom(self):
        # Don't clear _spx_cache here — _get_scaled_page checks scale per entry
        self._invalidate_mask_cache()
        self._resize_canvas()
        self.update()

    def event(self, e):
        if e.type() == QEvent.NativeGesture:
            if e.gestureType() == Qt.ZoomNativeGesture:
                self._fast_zoom = True
                self._scale = max(0.05, min(8.0, self._scale * (1.0 + e.value())))
                self._on_zoom()
                self._zoom_timer.start(150)
                return True
        return super().event(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            angle = e.angleDelta().y()
            if angle == 0:
                e.accept(); return
            self._fast_zoom = True
            factor = max(0.90, min(1.0 + (angle / 120.0) * 0.10, 1.11))
            self._scale = max(0.05, min(8.0, self._scale * factor))
            self._on_zoom()
            self._zoom_timer.start(150)
            e.accept()
        else:
            super().wheelEvent(e)
            self._smooth_timer.start(300)   # smooth re-render 300ms after scroll stops

    def _finalize_zoom(self):
        self._fast_zoom = False
        self._smooth_timer.start(300)   # switch to smooth quality after zoom settles

    def _apply_smooth(self):
        """Clear fast-scaled cache and repaint with SmoothTransformation."""
        self._spx_cache.clear()
        self.update()

    # =========================================================================
    #  PUBLIC BOX / MASK API  (identical to v19)
    # =========================================================================

    def set_tool(self, tool: str):
        self._tool = tool
        cursors = {"select": Qt.ArrowCursor, "rect": Qt.CrossCursor,
                   "ellipse": Qt.CrossCursor, "text": Qt.IBeamCursor}
        self.setCursor(QCursor(cursors.get(tool, Qt.CrossCursor)))
        self.update()

    def set_boxes(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=False) for b in boxes]
        self._invalidate_mask_cache()
        self.update()

    def set_boxes_with_state(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=b.get("revealed", False))
                       for b in boxes]
        self._ink_strokes.clear()
        self._ink_current.clear()
        self._invalidate_mask_cache()
        self.update()

    def get_boxes(self):
        SM2_KEYS = ("sm2_interval","sm2_repetitions","sm2_ease",
                    "sm2_due","sm2_last_quality","box_id")
        result = []
        for b in self._boxes:
            r = b["rect"]
            d = {"rect":  [r.x(), r.y(), r.width(), r.height()],
                 "label": b.get("label",""),
                 "shape": b.get("shape","rect"),
                 "angle": b.get("angle", 0.0),
                 "group_id": b.get("group_id","")}
            for k in SM2_KEYS:
                if k in b: d[k] = b[k]
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
        for b in self._boxes: b["revealed"] = True
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
        target_r = None
        if self._target_group_id:
            # Group वाले मास्क के लिए Bound निकालो
            rects = [self._sr(b["rect"]) for b in self._boxes if b.get("group_id","") == self._target_group_id]
            if rects:
                x1, y1 = min(r.left() for r in rects), min(r.top() for r in rects)
                x2, y2 = max(r.right() for r in rects), max(r.bottom() for r in rects)
                target_r = QRectF(x1, y1, x2-x1, y2-y1)
        elif 0 <= self._target_idx < len(self._boxes):
            # Single मास्क के लिए Rect लो
            target_r = self._sr(self._boxes[self._target_idx]["rect"])
        return target_r

    def get_target_scroll_pos(self, view_w: int, view_h: int):
        """
        Target mask ko viewport ke center mein laane ke liye chahiye
        scroll (hval, vval) return karta hai.

        Canvas ki logical size (_canvas_wh() * _scale) se calculate karta hai —
        self.width()/self.height() pe depend NAHI karta, kyunki woh values
        _resize_canvas() ke baad bhi Qt layout pass se pehle stale hoti hain.
        Isliye zoom + center ek hi frame mein bhi correctly kaam karta hai.

        Returns (hval, vval) ya None agar koi target nahi hai.
        """
        r = self.get_target_scaled_rect()
        if r is None:
            return None
        cx = r.center().x()
        cy = r.center().y()
        # Logical canvas size se clamp karo — widget geometry pe depend mat karo
        img_w, img_h = self._canvas_wh()
        canvas_w = max(int(img_w * self._scale), 1)
        canvas_h = max(int(img_h * self._scale), 1)
        hval = int(max(0, min(cx - view_w / 2, canvas_w - view_w)))
        vval = int(max(0, min(cy - view_h / 2, canvas_h - view_h)))
        return hval, vval

    def select_all(self):
        if not self._boxes: return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx     = len(self._boxes) - 1
        self.update()

    def select_visible_only(self):
        if not self._boxes: return
        vr = self.visibleRegion().boundingRect()
        inv = 1.0 / self._scale
        vf = QRectF(vr.x()*inv, vr.y()*inv, vr.width()*inv, vr.height()*inv)
        self._selected_indices = {i for i,b in enumerate(self._boxes)
                                  if vf.intersects(b["rect"])}
        self._selected_idx = (max(self._selected_indices)
                              if self._selected_indices else -1)
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def delete_selected_boxes(self):
        self._push_undo()
        if self._selected_indices:
            for i in sorted(self._selected_indices, reverse=True):
                if 0 <= i < len(self._boxes): self._boxes.pop(i)
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
            self._show_toast("⚠ Select 2+ masks to group"); return
        gid = str(uuid.uuid4())[:8]
        self._push_undo()
        for i in indices: self._boxes[i]["group_id"] = gid
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())
        self._show_toast(f"⛓ {len(indices)} masks grouped")

    def ungroup_selected(self):
        indices = self._get_all_selected()
        if not indices: return
        self._push_undo()
        for i in indices: self._boxes[i]["group_id"] = ""
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())
        self._show_toast(f"✂ {len(indices)} masks ungrouped")

    # =========================================================================
    #  UNDO / REDO
    # =========================================================================

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._redo_stack.clear()
        if len(self._undo_stack) > 100: self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack: return
        self._redo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._undo_stack.pop()
        self._selected_idx = -1; self._selected_indices = set()
        self._invalidate_mask_cache(); self.update()
        self.boxes_changed.emit(self.get_boxes())

    def redo(self):
        if not self._redo_stack: return
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._redo_stack.pop()
        self._selected_idx = -1; self._selected_indices = set()
        self._invalidate_mask_cache(); self.update()
        self.boxes_changed.emit(self.get_boxes())

    # =========================================================================
    #  INTERNAL DRAW HELPERS
    # =========================================================================

    def _get_all_selected(self):
        r = set(self._selected_indices)
        if self._selected_idx >= 0: r.add(self._selected_idx)
        return sorted(r)

    def _deserialise_box(self, b, revealed=False):
        r = b["rect"]
        return {"rect":     QRectF(r[0], r[1], r[2], r[3]),
                "shape":    b.get("shape","rect"),
                "angle":    float(b.get("angle",0.0)),
                "revealed": revealed,
                "label":    b.get("label",""),
                "box_id":   b.get("box_id",""),
                "group_id": b.get("group_id",""),
                **{k: b[k] for k in ("sm2_interval","sm2_repetitions","sm2_ease",
                                     "sm2_due","sm2_last_quality") if k in b}}

    def _handle_positions(self, idx):
        if not (0 <= idx < len(self._boxes)): return None
        b  = self._boxes[idx]
        sr = self._sr(b["rect"])
        cx, cy = sr.center().x(), sr.center().y()
        hw, hh = sr.width()/2, sr.height()/2
        ang = b.get("angle", 0.0)
        rad = math.radians(ang)
        ca, sa = math.cos(rad), math.sin(rad)
        def rot(dx, dy):
            return QPointF(cx + dx*ca - dy*sa, cy + dx*sa + dy*ca)
        handles = [rot(-hw,-hh), rot(0,-hh), rot(hw,-hh),
                   rot(-hw, 0),              rot(hw, 0),
                   rot(-hw, hh), rot(0, hh), rot(hw, hh)]
        return {"resize": handles, "rotate": rot(0, -hh-24)}

    def _hit_handle(self, sp, idx):
        hps = self._handle_positions(idx)
        if not hps: return None
        sp = QPointF(sp)
        r  = self._HANDLE_R + 2
        if (sp - hps["rotate"]).manhattanLength() <= r: return ("rotate", -1)
        for hi, hpt in enumerate(hps["resize"]):
            if (sp - hpt).manhattanLength() <= r: return ("resize", hi)
        return None

    def _show_toast(self, msg: str):
        if not hasattr(self, "_toast_label"):
            self._toast_label = QLabel(self)
            self._toast_label.setStyleSheet(
                "QLabel{background:rgba(30,30,46,210);color:#BD93F9;"
                "border:1px solid #BD93F9;border-radius:6px;"
                "padding:4px 12px;font-size:12px;font-weight:bold;}")
            self._toast_label.hide()
        if not hasattr(self, "_toast_timer"):
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast_label.hide)
        self._toast_label.setText(msg)
        self._toast_label.adjustSize()
        self._toast_label.move((self.width()-self._toast_label.width())//2, 18)
        self._toast_label.show(); self._toast_label.raise_()
        self._toast_timer.start(1800)

    def _select_box(self, hit: int, add_to_selection: bool = False):
        if hit < 0:
            self._selected_idx = -1; self._selected_indices = set()
            self._invalidate_mask_cache(); self.update(); return
        gid = self._boxes[hit].get("group_id","")
        if gid:
            members = {i for i,b in enumerate(self._boxes)
                       if b.get("group_id","") == gid}
            if add_to_selection: self._selected_indices |= members
            else:                self._selected_indices  = members
        else:
            if add_to_selection: self._selected_indices.add(hit)
            else:                self._selected_indices = set()
        self._selected_idx = hit
        self._invalidate_mask_cache(); self.update()
        self.boxes_changed.emit(self.get_boxes())

    def _hit_box(self, ip: QPointF):
        for i in range(len(self._boxes)-1, -1, -1):
            b = self._boxes[i]; r = b["rect"]
            cx, cy = r.center().x(), r.center().y()
            ang = b.get("angle", 0.0)
            if b.get("shape") == "ellipse":
                if _point_in_rotated_ellipse(ip.x(), ip.y(),
                                             cx, cy, r.width()/2, r.height()/2, ang):
                    return i
            else:
                if _point_in_rotated_box(ip.x(), ip.y(),
                                         cx, cy, r.width(), r.height(), ang):
                    return i
        return -1

    def _draw_box(self, p: QPainter, i: int, b: dict):
        sr    = self._sr(b["rect"])
        cx, cy = sr.center().x(), sr.center().y()
        ang   = b.get("angle", 0.0)
        lbl   = b.get("label") or f"#{i+1}"
        shape = b.get("shape","rect")
        sel   = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy); p.rotate(ang)
        local = QRectF(-sr.width()/2, -sr.height()/2, sr.width(), sr.height())

        if self._mode == "review":
            revealed = b.get("revealed", False)
            in_tg    = (bool(self._target_group_id) and
                        b.get("group_id","") == self._target_group_id)
            is_target = (i == self._target_idx) or in_tg
            hide_one  = (self._review_mode_style == "hide_one")

            if hide_one and not is_target:
                if not revealed:
                    p.setPen(QPen(QColor(C_GREEN), 1, Qt.DotLine))
                    p.setBrush(Qt.NoBrush)
                    (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
                p.restore(); return

            if not revealed:
                color    = QColor(C_GREEN if is_target else C_MASK)
                text_col = "#1E1E2E" if is_target else "#FFF"
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(text_col), 2))
                (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
                p.setPen(QPen(QColor(text_col), 1))
                p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                p.drawText(local, Qt.AlignCenter, lbl)
            else:
                p.setPen(QPen(QColor(C_GREEN), 2)); p.setBrush(Qt.NoBrush)
                (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
        else:
            gid     = b.get("group_id","")
            grouped = bool(gid)
            fill    = QColor("#50FA7B" if sel else "#6EB5FF" if grouped else C_MASK)
            fill.setAlpha(155)
            p.setBrush(QBrush(fill))
            border_col = QColor(C_GREEN if sel else "#2288FF" if grouped else "#FFF")
            p.setPen(QPen(border_col, 2,
                          Qt.DashLine if not grouped else Qt.SolidLine))
            (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
            p.setPen(QPen(border_col, 1))
            p.setFont(QFont("Segoe UI", 9))
            dlbl = (f"[{gid[:4]}] {lbl}" if gid and lbl
                    else f"[{gid[:4]}]" if gid else lbl)
            p.drawText(local, Qt.AlignCenter, dlbl)

        p.restore()
        if self._mode == "edit" and i == self._selected_idx:
            self._draw_handles(p, i)

    def _draw_handles(self, p: QPainter, idx: int):
        hps = self._handle_positions(idx)
        if not hps: return
        p.setPen(QPen(QColor(C_GREEN), 1))
        p.setBrush(QBrush(QColor("#1E1E2E")))
        hr = self._HANDLE_R
        for hpt in hps["resize"]: p.drawEllipse(hpt, hr, hr)
        rpt   = hps["rotate"]
        top_c = hps["resize"][1]
        p.setPen(QPen(QColor(C_ACCENT), 1)); p.drawLine(top_c, rpt)
        p.setBrush(QBrush(QColor(C_ACCENT)))
        p.setPen(QPen(QColor("#FFF"), 1)); p.drawEllipse(rpt, hr+1, hr+1)
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(QRectF(rpt.x()-6, rpt.y()-6, 12, 12), Qt.AlignCenter, "↻")

    def _draw_live(self, p: QPainter):
        sr = self._sr(self._live_rect)
        c  = QColor(C_ACCENT); c.setAlpha(110)
        p.setBrush(QBrush(c)); p.setPen(QPen(QColor(C_ACCENT), 2))
        (p.drawEllipse if self._tool=="ellipse" else p.drawRect)(sr)

    # =========================================================================
    #  INK LAYER
    # =========================================================================

    def ink_toggle(self):
        self._ink_active = not self._ink_active
        self.setCursor(QCursor(Qt.CrossCursor if self._ink_active
                               else Qt.PointingHandCursor))

    def ink_cycle_color(self):
        self._ink_color_idx = (self._ink_color_idx + 1) % len(self._ink_colors)
        self._show_toast(f"✏ Ink: {self._ink_colors[self._ink_color_idx]}")

    def ink_clear(self):
        self._ink_strokes.clear(); self._ink_current.clear()
        self.update(); self._show_toast("🧹 Ink cleared")

    def ink_undo_stroke(self):
        if self._ink_strokes: self._ink_strokes.pop(); self.update()

    @property
    def _ink_pen_color(self):
        return QColor(self._ink_colors[self._ink_color_idx])

    def _draw_ink_layer(self, p: QPainter):
        if not self._ink_strokes and not self._ink_current: return
        p.save(); p.setRenderHint(QPainter.Antialiasing)
        pen_w = max(1.0, self._ink_width * self._scale)
        for stroke in list(self._ink_strokes) + ([self._ink_current] if self._ink_current else []):
            if len(stroke) < 2: continue
            color = stroke[0]; pts = stroke[1:]
            if not pts: continue
            p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(pts) == 1:
                p.drawPoint(QPointF(pts[0].x()*self._scale, pts[0].y()*self._scale))
            else:
                for j in range(len(pts)-1):
                    p.drawLine(QPointF(pts[j].x()*self._scale,   pts[j].y()*self._scale),
                               QPointF(pts[j+1].x()*self._scale, pts[j+1].y()*self._scale))
        p.restore()

    def _ink_press(self, ip):   self._ink_current = [self._ink_pen_color, ip]
    def _ink_move(self, ip):
        if self._ink_current: self._ink_current.append(ip); self.update()
    def _ink_release(self):
        if len(self._ink_current) >= 2: self._ink_strokes.append(list(self._ink_current))
        self._ink_current = []; self.update()

    # =========================================================================
    #  MOUSE EVENTS
    # =========================================================================

    def _scroll_area(self):
        w = self.parent()
        while w and not hasattr(w, "pan_mode"): w = w.parent()
        return w

    def mousePressEvent(self, e):
        if not self.has_content(): return
        sc = self._scroll_area()
        if sc and (sc.pan_mode or e.button() == Qt.MiddleButton):
            e.ignore(); return

        self.setFocus()
        sp   = QPointF(e.pos())
        ip   = self._ip(e.pos())
        mods = e.modifiers()

        if self._mode == "review" and e.button() == Qt.LeftButton:
            if self._ink_active:
                self._ink_press(ip); e.accept(); return
            hit = self._hit_box(ip)
            if hit >= 0:
                self._boxes[hit]["revealed"] = not self._boxes[hit]["revealed"]
                self._invalidate_mask_cache(); self.update(); return
            e.ignore(); return

        if self._mode != "edit" or e.button() != Qt.LeftButton: return

        if self._selected_idx >= 0:
            hit_h = self._hit_handle(sp, self._selected_idx)
            if hit_h:
                op, hi = hit_h
                self._drag_op = op; self._drag_handle = hi
                self._drag_start_pos = sp
                self._drag_orig_box  = copy.deepcopy(self._boxes[self._selected_idx])
                self._push_undo(); return

        hit = self._hit_box(ip)
        if hit >= 0:
            self._select_box(hit, add_to_selection=bool(mods & Qt.ControlModifier))
            self._drag_op = "move"; self._drag_start_pos = sp
            self._drag_orig_box = copy.deepcopy(self._boxes[hit])
            self._push_undo(); return

        if self._tool != "select":
            self._select_box(-1)
            self._drawing = True; self._start = ip; self._live_rect = QRectF()
            self.update()

    def mouseMoveEvent(self, e):
        if self._mode == "review" and self._ink_active and self._ink_current:
            self._ink_move(self._ip(e.pos())); e.accept(); return

        sc = self.parent()
        while sc and not hasattr(sc, "_pan_active"): sc = sc.parent()
        if sc and sc._pan_active: e.ignore(); return

        sp = QPointF(e.pos()); ip = self._ip(e.pos())

        if self._drawing:
            x0,y0 = self._start.x(), self._start.y()
            x1,y1 = ip.x(), ip.y()
            self._live_rect = QRectF(min(x0,x1),min(y0,y1),abs(x1-x0),abs(y1-y0))
            self.update(); return

        if self._drag_op == "move" and self._selected_idx >= 0:
            delta = (sp - self._drag_start_pos) / self._scale
            orig  = self._drag_orig_box["rect"]
            self._boxes[self._selected_idx]["rect"] = QRectF(
                orig.x()+delta.x(), orig.y()+delta.y(), orig.width(), orig.height())
            self.update(); return

        if self._drag_op == "resize" and self._selected_idx >= 0:
            self._do_resize(sp); return

        if self._drag_op == "rotate" and self._selected_idx >= 0:
            b  = self._boxes[self._selected_idx]
            sr = self._sr(b["rect"])
            cx, cy = sr.center().x(), sr.center().y()
            b["angle"] = round(math.degrees(math.atan2(sp.y()-cy, sp.x()-cx))+90, 1)
            self.update(); return

        if self._tool == "select" and self._mode == "edit":
            if self._selected_idx >= 0 and self._hit_handle(sp, self._selected_idx):
                self.setCursor(QCursor(Qt.SizeFDiagCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))

    def mouseReleaseEvent(self, e):
        if self._mode == "review" and self._ink_active and e.button() == Qt.LeftButton:
            self._ink_release(); e.accept(); return

        if self._drawing and e.button() == Qt.LeftButton:
            self._drawing = False
            r = self._live_rect
            if r.width() > 6 and r.height() > 6:
                self._push_undo()
                self._boxes.append({"rect": r,
                                    "shape": self._tool if self._tool in ("rect","ellipse") else "rect",
                                    "angle": 0.0, "revealed": False, "label": ""})
                self._selected_idx = len(self._boxes) - 1
                self._invalidate_mask_cache(); self.update()
                self.boxes_changed.emit(self.get_boxes())
            self._live_rect = QRectF()
            self._invalidate_mask_cache(); self.update()

        if self._drag_op:
            self._drag_op = None; self._drag_handle = -1; self._drag_orig_box = None
            self._invalidate_mask_cache()
            self.boxes_changed.emit(self.get_boxes()); self.update()

    def _do_resize(self, sp: QPointF):
        idx  = self._selected_idx
        b    = self._boxes[idx]
        orig = self._drag_orig_box
        hi   = self._drag_handle
        delta = (sp - self._drag_start_pos) / self._scale
        ang  = orig.get("angle", 0.0)
        rad  = math.radians(-ang)
        ca, sa = math.cos(rad), math.sin(rad)
        ldx =  delta.x()*ca - delta.y()*sa
        ldy =  delta.x()*sa + delta.y()*ca
        r   = orig["rect"]
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        nx, ny, nw, nh = x, y, w, h
        if hi in (0,3,5): nx = x+ldx;  nw = max(10, w-ldx)
        if hi in (2,4,7): nw = max(10, w+ldx)
        if hi in (0,1,2): ny = y+ldy;  nh = max(10, h-ldy)
        if hi in (5,6,7): nh = max(10, h+ldy)
        b["rect"] = QRectF(nx, ny, nw, nh); b["angle"] = ang
        self.update()

    def keyPressEvent(self, e):
        mods = e.modifiers(); key = e.key()
        if self._mode == "review": e.ignore(); return
        if key == Qt.Key_Delete:                                self.delete_selected_boxes()
        elif mods & Qt.ControlModifier and key == Qt.Key_Z:    self.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:    self.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_A:
            self.select_all() if mods & Qt.ShiftModifier else self.select_visible_only()
        elif key == Qt.Key_G and not (mods & Qt.ControlModifier):
            self.ungroup_selected() if mods & Qt.ShiftModifier else self.group_selected()
        else: super().keyPressEvent(e)

    def leaveEvent(self, e):
        sc = self.parent()
        while sc and not hasattr(sc, "_pan_active"): sc = sc.parent()
        if sc and sc._pan_active:
            sc._pan_active = False; sc._pan_start_pos = None
            sc._is_actually_panning = False; sc._clear_pan_cursor()
        super().leaveEvent(e)

    def resizeEvent(self, e): super().resizeEvent(e)

    # ── legacy compat: ReviewScreen calls canvas._redraw() ───────────────────
    def _redraw(self):
        """Legacy shim — ReviewScreen calls this after revealing a mask."""
        self._invalidate_mask_cache()
        self.update()


# ═══════════════════════════════════════════════════════════════════════════════
#  TOOL BAR
# ═══════════════════════════════════════════════════════════════════════════════

class ToolBar(QWidget):
    tool_changed = pyqtSignal(str)
    _TOOLS = [("select","⬡","Select / Move / Resize / Rotate  [V]"),
              ("rect",  "□","Rectangle mask  [R]"),
              ("ellipse","○","Ellipse mask  [E]"),
              ("text",  "T","Edit label  [T]")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(50)
        self.setStyleSheet("QWidget{background:#F0F0F0;border-right:1px solid #C8C8C8;}")
        L = QVBoxLayout(self); L.setContentsMargins(5,8,5,8); L.setSpacing(3)
        self._btns = {}
        for tool, icon, tip in self._TOOLS:
            b = QPushButton(icon); b.setToolTip(tip); b.setCheckable(True)
            b.setFixedSize(40,40)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#333;border:none;"
                "border-radius:5px;font-size:20px;font-weight:bold;}"
                "QPushButton:checked{background:#4A90D9;color:white;}"
                "QPushButton:hover:!checked{background:#E0E0E0;}")
            b.clicked.connect(lambda _, t=tool: self._select(t))
            L.addWidget(b); self._btns[tool] = b
        L.addStretch(); self._select("rect")

    def _select(self, tool):
        for t, b in self._btns.items(): b.setChecked(t == tool)
        self.tool_changed.emit(tool)

    def select_tool(self, tool): self._select(tool)


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
        L = QVBoxLayout(self); L.setContentsMargins(6,6,6,6); L.setSpacing(4)
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
        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        b_del = QPushButton("🗑 Delete"); b_del.setObjectName("danger")
        b_del.setFixedHeight(26); b_del.clicked.connect(self._delete_selected)
        b_clr = QPushButton("✕ Clear All"); b_clr.setFixedHeight(26)
        b_clr.clicked.connect(self._canvas.clear_all)
        btn_row.addWidget(b_del); btn_row.addWidget(b_clr)
        L.addLayout(btn_row)

    def _refresh(self, boxes):
        self.list_w.blockSignals(True); self.list_w.clear()
        for i, b in enumerate(boxes):
            lbl   = b.get("label") or f"Mask #{i+1}"
            gid   = b.get("group_id","")
            icon  = "🔵" if gid else "🟧"
            badge = f" [{gid[:4]}]" if gid else ""
            self.list_w.addItem(f"  {icon} {lbl}{badge}")
        sel = self._canvas._selected_idx
        if 0 <= sel < self.list_w.count():
            self.list_w.setCurrentRow(sel)
            box = self._canvas._boxes[sel]
            self.inp_label.blockSignals(True)
            self.inp_label.setText(box.get("label",""))
            self.inp_label.blockSignals(False)
        self.list_w.blockSignals(False)

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
            self.list_w.currentItem().setText(
                f"  🟧 {text or f'Mask #{row+1}'}")

    def _delete_selected(self):
        row = self.list_w.currentRow()
        if row >= 0: self._canvas.delete_box(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  CARD EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class CardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None, initial_scroll=0):
        super().__init__(parent)
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        self.card               = card or {}
        self._initial_scroll    = initial_scroll
        self._pdf_pages         = []
        self._cur_page          = 0
        self._data              = data
        self._deck              = deck
        self._auto_subdeck_name = None
        self._watcher           = QFileSystemWatcher()
        self._watched_path      = None
        self._reload_timer      = QTimer()
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._reload_pdf)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._pdf_loader_thread = None
        self._pending_boxes     = []
        self._setup_ui()
        if card: self._load_card(card)

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
                border: 1px solid #CCC; border-radius: 4px; padding: 4px; }
            QListWidget {
                background: white; color: #111;
                border: 1px solid #CCC; border-radius: 4px; }
            QListWidget::item:selected { background: #4A90D9; color: white; }
            QPushButton {
                background: #E8E8E8; color: #333;
                border: 1px solid #BBB; border-radius: 4px;
                padding: 4px 10px; font-size: 12px; }
            QPushButton:hover   { background: #D8D8D8; }
            QPushButton:pressed { background: #C8C8C8; }
            QPushButton#accent  { background: #4A90D9; color: white; border: 1px solid #3A7FC9; }
            QPushButton#accent:hover { background: #3A7FC9; }
            QPushButton#danger  { background: #E05555; color: white; border: 1px solid #C04040; }
            QPushButton#danger:hover { background: #C04040; }
            QPushButton#success { background: #4CAF50; color: white; border: 1px solid #3A9040; }
            QPushButton#success:hover { background: #3A9040; }
            QScrollArea { border: none; background: #888; }
            QScrollBar:vertical   { background:#CCC; width:10px; border-radius:5px; }
            QScrollBar::handle:vertical { background:#999; border-radius:5px; }
            QScrollBar:horizontal { background:#CCC; height:10px; border-radius:5px; }
            QScrollBar::handle:horizontal { background:#999; border-radius:5px; }
        """)

        L = QVBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        # ── top bar ───────────────────────────────────────────────────────────
        top_bar = QFrame(); top_bar.setFixedHeight(46)
        top_bar.setStyleSheet(
            "QFrame{background:#F0F0F0;border-bottom:1px solid #C8C8C8;border-radius:0;}"
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#333;min-height:32px;}"
            "QPushButton:hover{background:#DDD;}"
            "QPushButton:pressed{background:#CCC;}"
            "QPushButton:checked{background:#C8D8EE;color:#1a5ca8;}")
        tl = QHBoxLayout(top_bar); tl.setContentsMargins(6,4,6,4); tl.setSpacing(2)

        def _tbtn(label, tip, checkable=False, w=None):
            b = QPushButton(label); b.setToolTip(tip)
            b.setCheckable(checkable); b.setFixedHeight(34)
            if w: b.setFixedWidth(w)
            return b

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.VLine)
            s.setStyleSheet("QFrame{background:#C0C0C0;margin:5px 4px;}")
            s.setFixedWidth(1); return s

        btn_img   = _tbtn("🖼 Image",     "Load Image")
        btn_paste = _tbtn("📋 Paste",     "Paste image from clipboard  Ctrl+V")
        btn_pdf   = _tbtn("📄 PDF",       "Load PDF")
        btn_pdf.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT: btn_pdf.setToolTip("pip install pymupdf")
        btn_img.clicked.connect(self._load_image)
        btn_paste.clicked.connect(self._paste_image)
        btn_pdf.clicked.connect(self._load_pdf)

        btn_undo = _tbtn("↩","Undo  Ctrl+Z", w=36)
        btn_redo = _tbtn("↪","Redo  Ctrl+Y", w=36)
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        btn_redo.clicked.connect(lambda: self.canvas.redo())

        btn_zi = _tbtn("🔍+","Zoom In",  w=46)
        btn_zo = _tbtn("🔍−","Zoom Out", w=46)
        btn_zf = _tbtn("⊡",  "Zoom Fit", w=32)
        btn_del   = _tbtn("🗑",    "Delete selected  Del", w=32)
        btn_clear = _tbtn("✕ All", "Clear all masks")
        btn_grp   = _tbtn("⛓ Group",   "Group selected masks  [G]")
        btn_ungrp = _tbtn("⛓ Ungroup", "Ungroup  [Shift+G]")
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

        for w in [btn_img, btn_paste, btn_pdf, _sep(),
                  btn_undo, btn_redo, _sep(),
                  btn_zi, btn_zo, btn_zf, _sep(),
                  btn_del, btn_clear, _sep(),
                  btn_grp, btn_ungrp, _sep(),
                  self.btn_open_ext, self.lbl_sync]:
            tl.addWidget(w)
        tl.addStretch()

        btn_cancel = _tbtn("Cancel", "Discard changes")
        btn_save   = QPushButton("💾  Save Card"); btn_save.setFixedHeight(34)
        btn_save.setToolTip("Save  Ctrl+S")
        btn_save.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border:1px solid #3A9040;"
            "border-radius:4px;padding:4px 16px;font-size:13px;min-height:32px;}"
            "QPushButton:hover{background:#3A9040;}")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        tl.addWidget(btn_cancel); tl.addSpacing(4); tl.addWidget(btn_save)
        L.addWidget(top_bar)

        # ── pdf bar ───────────────────────────────────────────────────────────
        self.pdf_bar = QWidget()
        self.pdf_bar.setStyleSheet("background:#E8E8E8;border-bottom:1px solid #CCC;")
        pb = QHBoxLayout(self.pdf_bar); pb.setContentsMargins(10,2,10,2)
        self.lbl_pg = QLabel("")
        self.lbl_pg.setStyleSheet("color:#555;font-size:11px;background:transparent;")
        pb.addWidget(self.lbl_pg); pb.addStretch()
        self.pdf_bar.setFixedHeight(22); self.pdf_bar.hide()
        L.addWidget(self.pdf_bar)

        # ── main row ──────────────────────────────────────────────────────────
        main_row = QHBoxLayout(); main_row.setContentsMargins(0,0,0,0); main_row.setSpacing(0)
        self.toolbar = ToolBar(); main_row.addWidget(self.toolbar)

        sc = _ZoomableScrollArea(); sc.setWidgetResizable(False)
        sc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc.setStyleSheet("QScrollArea{background:#787878;border:none;}")
        self.canvas = OcclusionCanvas()
        self.canvas.setStyleSheet("background:transparent;")
        sc.setWidget(self.canvas); sc.set_canvas(self.canvas)
        self.toolbar.tool_changed.connect(self.canvas.set_tool)
        main_row.addWidget(sc, stretch=1)
        self._sc = sc

        # ── right panel ───────────────────────────────────────────────────────
        right_panel = QWidget(); right_panel.setFixedWidth(240)
        right_panel.setStyleSheet("QWidget{background:#F5F5F5;}QFrame{background:#F5F5F5;border:none;}")
        rp = QVBoxLayout(right_panel); rp.setContentsMargins(0,0,0,0); rp.setSpacing(0)

        ml_hdr = QFrame(); ml_hdr.setFixedHeight(28)
        ml_hdr.setStyleSheet("QFrame{background:#E0E0E0;border-bottom:1px solid #CCC;}"
                             "QLabel{color:#444;font-size:11px;font-weight:bold;background:transparent;}")
        ml_hl = QHBoxLayout(ml_hdr); ml_hl.setContentsMargins(8,0,8,0)
        ml_hl.addWidget(QLabel("Masks")); ml_hl.addStretch()
        rp.addWidget(ml_hdr)

        self.mask_panel = MaskPanel(self.canvas); rp.addWidget(self.mask_panel, stretch=1)
        self.mask_panel.list_w.currentRowChanged.connect(self._center_on_mask)

        ci_hdr = QFrame(); ci_hdr.setFixedHeight(28)
        ci_hdr.setStyleSheet("QFrame{background:#E0E0E0;border-top:1px solid #CCC;"
                             "border-bottom:1px solid #CCC;}"
                             "QLabel{color:#444;font-size:11px;font-weight:bold;background:transparent;}")
        ci_hl = QHBoxLayout(ci_hdr); ci_hl.setContentsMargins(8,0,8,0)
        ci_hl.addWidget(QLabel("Card Info")); rp.addWidget(ci_hdr)

        ci_body = QWidget(); ci_body.setStyleSheet("QWidget{background:#F5F5F5;}")
        cib = QFormLayout(ci_body); cib.setContentsMargins(8,8,8,8); cib.setSpacing(6)
        self.inp_title = QLineEdit(); self.inp_title.setPlaceholderText("Card title…")
        self.inp_tags  = QLineEdit(); self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_notes = QTextEdit(); self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(64)
        cib.addRow("Title:", self.inp_title)
        cib.addRow("Tags:",  self.inp_tags)
        cib.addRow("Notes:", self.inp_notes)
        rp.addWidget(ci_body)
        main_row.addWidget(right_panel)

        body_w = QWidget(); body_w.setLayout(main_row)
        L.addWidget(body_w, stretch=1)

        hint_bar = QFrame(); hint_bar.setFixedHeight(20)
        hint_bar.setStyleSheet(
            "QFrame{background:#E8E8E8;border-top:1px solid #CCC;border-radius:0;}"
            "QLabel{background:transparent;color:#777;font-size:10px;}")
        hl = QHBoxLayout(hint_bar); hl.setContentsMargins(10,0,10,0)
        hl.addWidget(QLabel(
            "V=Select  R=Rect  E=Ellipse  T=Label  |  "
            "Hold Alt=temp select  Alt+Click=multi-select  |  "
            "G=group  Shift+G=ungroup  |  "
            "Drag ↻=rotate  Del=delete  Ctrl+Z/Y=undo/redo  |  "
            "Middle-click drag or H = Pan  (tablet/stylus)"))
        hl.addStretch(); L.addWidget(hint_bar)

        btn_zi.clicked.connect(lambda: self.canvas.zoom_in())
        btn_zo.clicked.connect(lambda: self.canvas.zoom_out())
        btn_zf.clicked.connect(self._zoom_fit)
        btn_del.clicked.connect(lambda: self.canvas.delete_selected_boxes())
        btn_clear.clicked.connect(self.canvas.clear_all)

    def _zoom_fit(self):
        vp = self._sc.viewport()
        self.canvas.zoom_fit(vp.width(), vp.height())

    def _center_on_mask(self, row):
        if not (0 <= row < len(self.canvas._boxes)): return
        r    = self.canvas._sr(self.canvas._boxes[row]["rect"])
        vbar = self._sc.verticalScrollBar()
        hbar = self._sc.horizontalScrollBar()
        hbar.setValue(int(max(0, r.center().x() - self._sc.viewport().width()  // 2)))
        vbar.setValue(int(max(0, r.center().y() - self._sc.viewport().height() // 2)))

    def keyPressEvent(self, e):
        key = e.key(); mods = e.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:  self.canvas.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y: self.canvas.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_S: self._save()
        elif mods & Qt.ControlModifier and key == Qt.Key_V: self._paste_image()
        elif key == Qt.Key_V: self.toolbar.select_tool("select")
        elif key == Qt.Key_R: self.toolbar.select_tool("rect")
        elif key == Qt.Key_E: self.toolbar.select_tool("ellipse")
        elif key == Qt.Key_T: self.toolbar.select_tool("text")
        else: super().keyPressEvent(e)

    # ── image / paste ─────────────────────────────────────────────────────────

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path: return
        px = QPixmap(path)
        if px.isNull(): QMessageBox.warning(self, "Error", "Could not load image."); return
        self.card["image_path"] = path; self.card.pop("pdf_path", None)
        self._pdf_pages = []; self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False); self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        if not self.inp_title.text():
            self.inp_title.setText(os.path.splitext(os.path.basename(path))[0])

    def _paste_image(self):
        clipboard = QApplication.clipboard()
        px = clipboard.pixmap()
        if px.isNull():
            img = clipboard.image()
            if not img.isNull(): px = QPixmap.fromImage(img)
        if px.isNull():
            QMessageBox.information(self, "Nothing to paste",
                "Clipboard mein koi image nahi hai."); return
        import tempfile as _tmp
        fd, tmp_path = _tmp.mkstemp(suffix=".png", prefix="anki_paste_",
                                    dir=os.path.expanduser("~"))
        os.close(fd)
        if not px.save(tmp_path, "PNG"):
            QMessageBox.warning(self, "Error", "Could not save pasted image."); return
        self.card["image_path"] = tmp_path; self.card.pop("pdf_path", None)
        self._pdf_pages = []; self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False); self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        if not self.inp_title.text(): self.inp_title.setText("Pasted Image")

    # ── PDF loading ───────────────────────────────────────────────────────────

    def _load_pdf(self):
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf"); return
        path, _ = QFileDialog.getOpenFileName(self, "Load PDF", "", "PDF (*.pdf)")
        if not path: return
        self.card["pdf_path"] = path; self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
        self._pending_boxes = []
        self._show_pdf_loading(True)
        self._start_pdf_thread(path)

    def _start_pdf_thread(self, path: str):
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(500)
        self._pdf_loader_thread = PdfLoaderThread(path, parent=self)
        # pages_ready → progressive update; done → final update
        self._pdf_loader_thread.pages_ready.connect(self._on_pages_ready)
        self._pdf_loader_thread.done.connect(self._on_pdf_done)
        self._pdf_loader_thread.start()

    def _on_pages_ready(self, pages: list, loaded: int, total: int):
        """Called every CHUNK_SIZE pages — update canvas progressively."""
        path = self.card.get("pdf_path","")
        # First chunk → call load_pages (resets layout); subsequent → append_pages
        if loaded <= len(pages) and loaded - len(pages) < 6:
            self.canvas.load_pages(pages)
        else:
            self.canvas.append_pages(pages[loaded - (loaded % 5 or 5):])

        # Restore pending boxes on the first chunk
        if self._pending_boxes:
            self.canvas.set_boxes(self._pending_boxes)
            self.mask_panel._refresh(self._pending_boxes)
            self._pending_boxes = []

        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  ⏳ {loaded}/{total} pages…")
        self.pdf_bar.show()
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText(f"⏳ Loading… {loaded}/{total}")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self.setWindowTitle(f"Occlusion Card Editor  ⏳ {loaded}/{total} pages…")

    def _on_pdf_done(self, pages: list, err):
        """Called once when all pages are loaded."""
        self._show_pdf_loading(False)
        path = self.card.get("pdf_path","")
        if not pages:
            QMessageBox.warning(self, "PDF Error", err or "Could not render PDF."); return

        # Load all pages at once (replaces any partial load)
        existing_boxes = self.canvas.get_boxes()
        self.canvas.load_pages(pages)

        try:
            _doc = fitz.open(path); n = len(_doc); _doc.close()
        except Exception:
            n = len(pages)
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  {n} page{'s' if n!=1 else ''}"
            f"  •  scroll to navigate")
        self.pdf_bar.show()

        if not self.inp_title.text():
            self.inp_title.setText(self._auto_subdeck_name or "")

        boxes_to_restore = self._pending_boxes or existing_boxes
        if boxes_to_restore:
            self.canvas.set_boxes(boxes_to_restore)
            self.mask_panel._refresh(boxes_to_restore)
            self._pending_boxes = []

        self._watch_pdf(path)
        if self._initial_scroll > 0:
            QTimer.singleShot(60, lambda:
                self._sc.verticalScrollBar().setValue(self._initial_scroll))
            self._initial_scroll = 0

    def _show_pdf_loading(self, loading: bool):
        if loading:
            self.setWindowTitle("Occlusion Card Editor  ⏳ Loading PDF…")
            self.lbl_sync.setVisible(True); self.lbl_sync.setText("⏳ Loading PDF…")
            self.lbl_sync.setStyleSheet(
                f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        else:
            self.setWindowTitle("Occlusion Card Editor")

    # ── card load ─────────────────────────────────────────────────────────────

    def _load_card(self, card):
        """File: editor_ui.py -> Class: CardEditorDialog"""
        self.inp_title.setText(card.get("title",""))
        self.inp_tags.setText(", ".join(card.get("tags",[])))
        self.inp_notes.setPlainText(card.get("notes",""))
        
        current_boxes = card.get("boxes", [])

        if card.get("image_path") and os.path.exists(card["image_path"]):
            px = QPixmap(card["image_path"])
            if px and not px.isNull(): self.canvas.load_pixmap(px)
            if current_boxes:
                self.canvas.set_boxes(current_boxes)
                self.mask_panel._refresh(current_boxes)
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(card["pdf_path"]):
            path = card["pdf_path"]
            self.card["pdf_path"] = path
            self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
            self._pending_boxes = current_boxes 
            self._show_pdf_loading(True)
            self._start_pdf_thread(path) # ⚡ Virtual Renderer se load karega

    # ── file watcher (live sync) ───────────────────────────────────────────────

    def _watch_pdf(self, path: str):
        self._stop_watch(); self._watched_path = path
        self._watcher.addPath(path); self.btn_open_ext.setVisible(True)
        self.lbl_sync.setVisible(True); self.lbl_sync.setText("🟢 Live Sync: watching")
        self.lbl_sync.setStyleSheet(
            f"color:{C_GREEN};font-size:11px;background:transparent;font-weight:bold;")

    def _stop_watch(self):
        if self._watched_path:
            self._watcher.removePath(self._watched_path); self._watched_path = None
        self._reload_timer.stop()

    def _on_file_changed(self, path: str):
        self.lbl_sync.setText("🟡 Live Sync: change detected…")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self._reload_timer.start()

    def _reload_pdf(self):
        path = self._watched_path
        if not path or not os.path.exists(path):
            QTimer.singleShot(500, self._reload_pdf); return
        if path not in self._watcher.files(): self._watcher.addPath(path)
        PAGE_CACHE.invalidate_pdf(path)
        saved_boxes = self.canvas.get_boxes()
        self._pending_boxes = saved_boxes
        self.lbl_sync.setText("🟡 Live Sync: reloading…")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self._start_pdf_thread(path)

    def _open_in_reader(self):
        path = self.card.get("pdf_path") or self._watched_path
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded."); return
        import subprocess
        try:
            if sys.platform == "win32":       os.startfile(path)
            elif sys.platform == "darwin":    subprocess.Popen(["open",     path])
            else:                             subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            QMessageBox.warning(self,"Could not open",f"Could not open PDF:\n{ex}")

    # ── save / close ──────────────────────────────────────────────────────────

    def _save(self):
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self,"No Source","Load an image or PDF first."); return
        old_boxes = self.card.get("boxes",[])
        new_boxes = self.canvas.get_boxes()
        SM2_KEYS  = ("sm2_interval","sm2_repetitions","sm2_ease",
                     "sm2_due","sm2_last_quality","box_id")
        old_by_id = {b["box_id"]: b for b in old_boxes if "box_id" in b}
        merged = []
        for i, nb in enumerate(new_boxes):
            old = old_by_id.get(nb.get("box_id")) or (old_boxes[i] if i < len(old_boxes) else None)
            if old:
                for k in SM2_KEYS:
                    if k in old: nb[k] = old[k]
            if "box_id" not in nb: nb["box_id"] = new_box_id()
            merged.append(nb)
        self.card.update({"title":   self.inp_title.text().strip() or "Untitled",
                          "tags":    [t.strip() for t in self.inp_tags.text().split(",") if t.strip()],
                          "notes":   self.inp_notes.toPlainText(),
                          "boxes":   merged,
                          "created": self.card.get("created", datetime.now().isoformat()),
                          "reviews": self.card.get("reviews", 0)})
        if self._auto_subdeck_name: self.card["_auto_subdeck"] = self._auto_subdeck_name
        sm2_init(self.card)
        for box in self.card.get("boxes",[]): sm2_init(box)
        self.accept()

    def get_card(self): return self.card

    def closeEvent(self, e):
        self._stop_watch()
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.quit(); self._pdf_loader_thread.wait(1000)
        super().closeEvent(e)

    def reject(self):
        self._stop_watch()
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.quit(); self._pdf_loader_thread.wait(1000)
        super().reject()

    def accept(self):
        self._stop_watch(); super().accept()


# ═══════════════════════════════════════════════════════════════════════════════
#  ZOOMABLE SCROLL AREA  (unchanged from v19)
# ═══════════════════════════════════════════════════════════════════════════════

class _ZoomableScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas              = None
        self._pan_active          = False
        self._pan_start_pos       = None
        self._pan_hval            = 0
        self._pan_vval            = 0
        self._pan_mode            = False
        self._space_held          = False
        self._drag_threshold      = 10
        self._is_actually_panning = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().installEventFilter(self)

    @property
    def pan_mode(self): return self._pan_mode

    def set_canvas(self, canvas):
        self._canvas = canvas
        canvas.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self.viewport() or obj is self._canvas:
            t = e.type()
            if t == QEvent.MouseButtonRelease:
                if self._pan_active:
                    self._pan_active = False; self._pan_start_pos = None
                    self._is_actually_panning = False; self._clear_pan_cursor()
                    if self._pan_mode: self._enter_pan_cursor()
                    return False
            elif t in (QEvent.Leave, QEvent.HoverLeave):
                if self._pan_active:
                    self._pan_active = False; self._pan_start_pos = None
                    self._is_actually_panning = False; self._clear_pan_cursor()
                return False
        return super().eventFilter(obj, e)

    def _set_pan_cursor(self, shape):
        c = QCursor(shape)
        self.viewport().setCursor(c); self.setCursor(c)
        if self._canvas: self._canvas.setCursor(c)

    def _clear_pan_cursor(self):
        self.viewport().unsetCursor(); self.unsetCursor()
        if self._canvas:
            if getattr(self._canvas, '_mode','') == "review":
                self._canvas.setCursor(QCursor(Qt.PointingHandCursor))
            else:
                self._canvas.set_tool(self._canvas._tool)

    def _enter_pan_cursor(self): self._set_pan_cursor(Qt.OpenHandCursor)
    def _exit_pan_cursor(self):  self._clear_pan_cursor()

    def wheelEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self._canvas:
            self._canvas.wheelEvent(e)
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_H and not e.isAutoRepeat():
            self._pan_mode = not self._pan_mode
            if self._pan_mode: self._enter_pan_cursor()
            else:              self._exit_pan_cursor()
            e.accept(); return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e): super().keyReleaseEvent(e)

    def _should_pan(self, e):
        if self._canvas and getattr(self._canvas,'_mode','') == "review":
            if e.button() == Qt.LeftButton: return True
        if e.button() == Qt.MiddleButton: return True
        if e.button() == Qt.LeftButton and self.pan_mode: return True
        return False

    def mousePressEvent(self, e):
        if self._should_pan(e):
            self._pan_active = True; self._pan_start_pos = e.globalPos()
            self._pan_hval = self.horizontalScrollBar().value()
            self._pan_vval = self.verticalScrollBar().value()
            self._is_actually_panning = False
            self._set_pan_cursor(Qt.OpenHandCursor); e.accept(); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan_active and self._pan_start_pos is not None:
            dv = e.globalPos() - self._pan_start_pos
            if not self._is_actually_panning:
                if dv.manhattanLength() > self._drag_threshold:
                    self._is_actually_panning = True
                    self._set_pan_cursor(Qt.ClosedHandCursor)
                else: return
            self.horizontalScrollBar().setValue(self._pan_hval - dv.x())
            self.verticalScrollBar().setValue(self._pan_vval   - dv.y())
            e.accept(); return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan_active:
            self._pan_active = False; self._pan_start_pos = None
            self._is_actually_panning = False; self._clear_pan_cursor()
            if self._pan_mode: self._enter_pan_cursor()
            e.accept(); return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        if self._pan_active:
            self._pan_active = False; self._pan_start_pos = None
            self._is_actually_panning = False; self._clear_pan_cursor()
        super().leaveEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  CHANGES NEEDED IN anki_occlusion_v19.py
# ═══════════════════════════════════════════════════════════════════════════════
#
#  1. The import at the top — remove pdf_to_combined_pixmap, add nothing:
#       BEFORE:  from pdf_engine import (PDF_SUPPORT, PAGE_CACHE, pdf_to_combined_pixmap, PdfLoaderThread)
#       AFTER:   from pdf_engine import (PDF_SUPPORT, PAGE_CACHE, PdfLoaderThread)
#
#  2. In ReviewScreen._reload_current_canvas() replace the pdf branch:
#
#       BEFORE:
#           combined, _, _ = pdf_to_combined_pixmap(path)
#           if not combined.isNull():
#               px = combined
#           else:
#               self._start_review_pdf_thread(card, box_idx)
#               return
#
#       AFTER:
#           cached_pages = [PAGE_CACHE.get(path, i)
#                           for i in range(1000)          # walk until None
#                           if PAGE_CACHE.get(path, i)]
#           # stop at first missing page
#           clean = []
#           for i in range(10000):
#               pg = PAGE_CACHE.get(path, i)
#               if pg is None: break
#               clean.append(pg)
#           if clean:
#               self._apply_canvas_pages(card, box_idx, clean)
#               return
#           else:
#               self._start_review_pdf_thread(card, box_idx)
#               return
#
#  3. Add _apply_canvas_pages() next to _apply_canvas():
#
#       def _apply_canvas_pages(self, card, box_idx, pages):
#           self.canvas.load_pages(pages)
#           self._apply_canvas_boxes(card, box_idx)
#           QTimer.singleShot(30,  lambda: self._fit_zoom_pages(pages))
#           QTimer.singleShot(80,  lambda: self._scroll_to_mask(box_idx))
#
#  See full patch in the README or ask for the updated anki_occlusion_v19.py.