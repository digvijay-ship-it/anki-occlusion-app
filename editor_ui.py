"""
editor_ui.py  —  v22  (Snappy Performance Edition)
================================================

v22 Performance Fixes (6 independent bottlenecks eliminated):
  [FIX-1] paintEvent: Single-image (_px) was re-scaled from scratch on EVERY
      paintEvent — scroll, drag, ink, everything. Now cached in _spx_cache
      same as PDF pages. Eliminates the #1 scroll lag source for image cards.

  [FIX-2] paintEvent direct-draw fallback (large PDFs): Was redrawing ALL
      masks on every scroll event regardless of clip rect. Now checks
      clip.intersects(sr) and skips off-screen boxes entirely.

  [FIX-3] Ink _ink_move: Was calling full-canvas update() on every mouse move.
      Now computes a tight bounding rect of just the last segment (typically
      <50×50px) and calls update(rect). 10–50x fewer pixels repainted per event.

  [FIX-4] _draw_ink_layer: Was calling drawLine() in a Python loop for every
      segment — N separate GPU round-trips per stroke. Now uses drawPolyline()
      for a single GPU call per stroke regardless of point count.

  [FIX-5] Mask drawing (_drawing mode): Was calling full-canvas update() on
      every mouseMoveEvent. Now only repaints the union of old+new live_rect.

  [FIX-6] Mask move drag: Was full-canvas update() on every pixel of drag.
      Now repaints only the union of old+new box screen rect + handle padding.

  [FIX-7] Mask rotate drag: Same as FIX-6 — partial rect update only.

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
import time
import fitz
import copy
import uuid

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QListWidget, QFrame, QScrollArea, QMessageBox, QFileDialog,
    QFormLayout, QTextEdit, QSizePolicy, QDialog, QApplication
)
from PyQt5.QtCore import (
    Qt, QPointF, QRectF, QTimer, pyqtSignal, QSize, QEvent, QUrl,
    QFileSystemWatcher
)
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QBrush, QDesktopServices
)

from sm2_engine import sm2_init
from pdf_engine import (
    PDF_SUPPORT,
    PdfLoaderThread,
    pdf_page_to_pixmap,
)
from cache_manager import PAGE_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY
from data_manager import new_box_id

C_GREEN  = "#50FA7B"
C_MASK   = "#F7916A"
C_ACCENT = "#7C6AF7"
C_YELLOW = "#F1FA8C"
PAGE_GAP = 12   # vertical gap between pages in image-space pixels
EDITOR_PDF_ZOOM = 1.5

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



from ui.canvas.core import OcclusionCanvas



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
#  ZOOMABLE SCROLL AREA  (unchanged from v19)
# ═══════════════════════════════════════════════════════════════════════════════

class _ZoomableScrollArea(QScrollArea):
    # ── NEW: emitted when vertical scroll position changes ────────────────────
    # Carries (first_visible_page, last_visible_page) — 0-based indices
    visible_pages_changed = pyqtSignal(int, int)

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
        self._last_scroll_value   = None
        self._last_scroll_ts      = None
        self._last_visible_emit_ts = None
        self._last_scroll_range   = None
        self._last_viewport_size  = None
        self._scroll_direction    = 0
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().installEventFilter(self)

        # ── Scroll debounce timer — avoids firing on every pixel of scroll ───
        self._scroll_debounce = QTimer(self)
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.setInterval(150)   # backup emit after motion settles
        self._scroll_debounce.timeout.connect(self._emit_visible_pages)

        # Connect scrollbar AFTER it exists (post __init__)
        # Done lazily in set_canvas() instead

    def set_canvas(self, canvas):
        self._canvas = canvas
        canvas.installEventFilter(self)
        # Hook scrollbar valueChanged → debounce → visible_pages_changed
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)

    @property
    def pan_mode(self): return self._pan_mode

    def _on_scroll(self, value):
        """Raw scroll event — debounce so we don't fire 60× per swipe."""
        vbar = self.verticalScrollBar()
        now = time.perf_counter()
        prev_value = self._last_scroll_value
        prev_ts = self._last_scroll_ts
        delta = 0 if prev_value is None else value - prev_value
        dt_ms = 0.0 if prev_ts is None else (now - prev_ts) * 1000.0
        if delta > 0:
            self._scroll_direction = 1
        elif delta < 0:
            self._scroll_direction = -1
        page = self._canvas.get_current_page(value) + 1 if self._canvas and self._canvas._page_tops else 0
        vp = self.viewport()
        range_now = (vbar.minimum(), vbar.maximum())
        viewport_now = (vp.width(), vp.height())

        self._last_scroll_value = value
        self._last_scroll_ts = now
        self._last_scroll_range = range_now
        self._last_viewport_size = viewport_now
        self._scroll_debounce.start()

        last_emit = self._last_visible_emit_ts
        if last_emit is None or (now - last_emit) * 1000.0 >= 100.0:
            self._emit_visible_pages()

    def _on_scroll_range_changed(self, minimum, maximum):
        prev = self._last_scroll_range
        value = self.verticalScrollBar().value()
        vp = self.viewport()
        self._last_scroll_range = (minimum, maximum)

    def _emit_visible_pages(self):
        """
        Called 120ms after scroll stops.
        Calculates which pages are currently visible in the viewport
        and emits visible_pages_changed(first, last).
        """
        if not self._canvas or not self._canvas._page_tops:
            return

        vp_h     = self.viewport().height()
        scroll_y = self.verticalScrollBar().value()
        scale    = self._canvas._scale

        # Convert screen coords → image-space
        img_top    = scroll_y / max(scale, 0.01)
        img_bottom = (scroll_y + vp_h) / max(scale, 0.01)

        page_tops = self._canvas._page_tops
        pages     = self._canvas._pages
        total     = len(page_tops)

        first = 0
        last  = total - 1

        for i, top in enumerate(page_tops):
            h        = pages[i].height() if i < len(pages) else 0
            page_bot = top + h
            if page_bot < img_top:
                first = i + 1     # this page is above viewport
            if top > img_bottom:
                last = i - 1      # this page is below viewport
                break

        first = max(0, min(first, total - 1))
        last  = max(0, min(last,  total - 1))

        # Prefetch just one page in the scroll direction so the current page
        # and its neighbor stay ready without adding extra render churn.
        PREFETCH_PAGES = 1
        if self._scroll_direction > 0:
            last = min(total - 1, last + PREFETCH_PAGES)
        elif self._scroll_direction < 0:
            first = max(0, first - PREFETCH_PAGES)

        self._last_visible_emit_ts = time.perf_counter()
        self.visible_pages_changed.emit(first, last)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        vp = self.viewport()
        size_now = (vp.width(), vp.height())
        prev = self._last_viewport_size
        self._last_viewport_size = size_now

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