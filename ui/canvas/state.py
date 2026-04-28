from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath, QTransform, QCursor

import uuid
import time
import math
import copy

from cache_manager import MASK_REGISTRY, PIXMAP_REGISTRY
C_BG      = '#1E1E2E'
C_SURFACE = '#2A2A3E'
C_CARD    = '#313145'
C_ACCENT  = '#7C6AF7'
C_GREEN   = '#50FA7B'
C_RED     = '#FF5555'
C_YELLOW  = '#F1FA8C'
C_TEXT    = '#CDD6F4'
C_SUBTEXT = '#A6ADC8'
C_BORDER  = '#45475A'


# Dummy values that were in editor_ui
PAGE_GAP = 12
REVEAL_COLOR = "#00000000"  # transparent

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
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1


class CanvasStateMixin:
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

    def _compute_layout(self):
        """Rebuild page top offsets and total virtual height from _pages."""
        self._page_tops = []
        top = 0
        max_w = 0
        for i, px in enumerate(self._pages):
            self._page_tops.append(top)
            if px and not px.isNull():
                top += px.height()
                max_w = max(max_w, px.width())
                if i < len(self._pages) - 1:
                    top += PAGE_GAP
        self._total_h = top
        self._total_w = max_w

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

    def has_content(self):
        return bool(self._px is not None or self._pages)

    def _canvas_wh(self):
        if self._pages:
            return self._total_w or 1, self._total_h or 1
        if self._px is not None and not self._px.isNull():
            return self._px.width(), self._px.height()
        return 1, 1

    def _sr(self, r):
        """Scale an image-space rect into screen-space."""
        return QRectF(r.x() * self._scale, r.y() * self._scale,
                      r.width() * self._scale, r.height() * self._scale)

    def _ip(self, p):
        """Convert a screen-space point back to image-space."""
        inv = 1.0 / max(self._scale, 0.01)
        return QPointF(p.x() * inv, p.y() * inv)

    def _resize_canvas(self):
        """Resize the widget to match the current logical canvas size.
        Canvas is always at least as large as the viewport so ink strokes
        can be drawn in the grey area outside the image/PDF.
        """
        w, h = self._canvas_wh()
        w = max(int(w * self._scale), 1)
        h = max(int(h * self._scale), 1)
        # Extend to fill viewport so grey area is also drawable
        sc = self._scroll_area()
        if sc is not None:
            vp = sc.viewport()
            w = max(w, vp.width())
            h = max(h, vp.height())
        self.setMinimumSize(w, h)
        self.resize(w, h)

    def _get_scaled_page(self, idx: int) -> QPixmap:
        """Return a cached scaled QPixmap for the given page index."""
        if not (0 <= idx < len(self._pages)):
            return QPixmap()
        page_px = self._pages[idx]
        if not page_px or page_px.isNull():
            return QPixmap()

        # QImage guard — convert to QPixmap if it slipped through
        from PyQt5.QtGui import QImage as _QImage
        if isinstance(page_px, _QImage):
            page_px = QPixmap.fromImage(page_px)
            self._pages[idx] = page_px   # fix in place

        cached_scale, cached_spx = self._spx_cache.get(idx, (None, None))
        if cached_scale == self._scale and cached_spx is not None and not cached_spx.isNull():
            return cached_spx
        sw = max(int(page_px.width() * self._scale), 1)
        sh = max(int(page_px.height() * self._scale), 1)
        cached_spx = page_px.scaled(sw, sh, Qt.KeepAspectRatio, Qt.FastTransformation)
        self._spx_cache[idx] = (self._scale, cached_spx)
        return cached_spx

    def inject_page(self, page_num: int, qpx):
        import time
        t_start = time.perf_counter()

        # QImage guard
        from PyQt5.QtGui import QImage as _QImage
        if isinstance(qpx, _QImage):
            qpx = QPixmap.fromImage(qpx)
        """
        STEP 3 — Replace a placeholder QPixmap with the real rendered page.

        Called by PdfOnDemandThread.page_ready signal.
        Layout (page_tops, total_h) does NOT change — placeholder was same size.
        Only the visual content of that one page slot updates.

        Terminal debug shows: which page, old size vs new size, timing.
        """
        import time
        t_start = time.perf_counter()

        # ── Bounds check ──────────────────────────────────────────────────────
        if page_num < 0 or page_num >= len(self._pages):
            print(f"[DEBUG][inject_page] ❌ page_num={page_num} out of range "
                  f"(canvas has {len(self._pages)} pages) — ignored")
            return

        if qpx is None or qpx.isNull():
            print(f"[DEBUG][inject_page] ❌ p.{page_num+1} — null QPixmap received — ignored")
            return

        old_px  = self._pages[page_num]
        old_w   = old_px.width()  if old_px else 0
        old_h   = old_px.height() if old_px else 0
        new_w   = qpx.width()
        new_h   = qpx.height()

        # ── Dimension sanity check ────────────────────────────────────────────
        # Skeleton aur real page same zoom se bane hain — should always match.
        # Agar mismatch hai toh recompute layout (shouldn't happen in practice).
        dims_match = (old_w == new_w and old_h == new_h)

        # ── Inject ────────────────────────────────────────────────────────────
        self._pages[page_num] = qpx

        # Invalidate scaled cache for this page only
        self._spx_cache.pop(page_num, None)

        if not dims_match:
            # ── JITTER MONITOR — before ──────────────────────────────────────
            canvas_h_before = self.height()
            tops_before     = list(self._page_tops) if self._page_tops else []
            _scroll_before  = None
            try:
                _sa = self.parent()
                while _sa and not hasattr(_sa, "verticalScrollBar"):
                    _sa = _sa.parent()
                if _sa:
                    _scroll_before = _sa.verticalScrollBar().value()
            except Exception:
                pass
            # ────────────────────────────────────────────────────────────────

            self._compute_layout()
            self._resize_canvas()
            self._invalidate_mask_cache()

            # ── JITTER MONITOR — after ───────────────────────────────────────
            canvas_h_after = self.height()
            _scroll_after  = None
            try:
                _sa = self.parent()
                while _sa and not hasattr(_sa, "verticalScrollBar"):
                    _sa = _sa.parent()
                if _sa:
                    _scroll_after = _sa.verticalScrollBar().value()
            except Exception:
                pass
            canvas_h_delta = canvas_h_after - canvas_h_before
            scroll_delta   = (_scroll_after - _scroll_before) if (_scroll_after is not None and _scroll_before is not None) else "N/A"
            top_before_pg  = tops_before[page_num] if page_num < len(tops_before) else "N/A"
            top_after_pg   = self._page_tops[page_num] if self._page_tops and page_num < len(self._page_tops) else "N/A"
            top_delta_pg   = (top_after_pg - top_before_pg) if isinstance(top_before_pg, int) and isinstance(top_after_pg, int) else "N/A"
            shifted_pages  = sum(
                1 for pi in range(page_num, min(len(tops_before), len(self._page_tops)))
                if tops_before[pi] != self._page_tops[pi]
            ) if tops_before and self._page_tops else 0
            # ────────────────────────────────────────────────────────────────
        else:
            # Fast path — only repaint the dirty page region
            # No layout recompute needed — sizes match exactly
            if self._page_tops and page_num < len(self._page_tops):
                top_img  = self._page_tops[page_num]
                top_scr  = int(top_img  * self._scale)
                h_scr    = int(new_h    * self._scale)
                from PyQt5.QtCore import QRect
                self.update(QRect(0, top_scr, self.width(), h_scr))
            else:
                self.update()

        t_ms = (time.perf_counter() - t_start) * 1000

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
        _QT_MAX_PX = 32767
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

    def zoom_fit_width(self, viewport_w):
        w, h = self._canvas_wh()
        if w < 1 or h < 1:
            return
        self._scale = max(viewport_w / w, 0.05)
        self._on_zoom()

    def _on_zoom(self):
        # Don't clear _spx_cache here — _get_scaled_page checks scale per entry
        self._invalidate_mask_cache()
        self._resize_canvas()
        self.update()

    def _finalize_zoom(self):
        self._fast_zoom = False
        self._smooth_timer.start(300)   # switch to smooth quality after zoom settles

    def _apply_smooth(self):
        """Clear fast-scaled cache and repaint with SmoothTransformation."""
        self._spx_cache.clear()
        self.update()

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
                    "sm2_due","sm2_last_quality","box_id",
                    "sched_state","sched_step","reviews")
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

            # ── STEP 1: page_num calculation ──────────────────────────────────
            # Box rect Y-center se _page_tops ka reverse-lookup karke page number
            # nikaalte hain. Yeh field lazy loading ke Phase 2 mein use hogi —
            # bina full PDF load kiye pata chalega ki aaj ke due masks kahan hain.
            # Agar _page_tops available nahi (single-image mode) toh page_num = 0.
            page_num = 0
            if self._page_tops:
                cy = r.y() + r.height() / 2   # box ka Y-center (image-space)
                for pi, top in enumerate(self._page_tops):
                    if cy >= top:
                        page_num = pi
                    else:
                        break
            d["page_num"] = page_num

            result.append(d)

        # ── DEBUG ─────────────────────────────────────────────────────────────
        # Har get_boxes() call pe terminal mein page distribution dikhao.
        # Production mein yeh block hata dena ya DEBUG_PAGE_NUM = False kar dena.
        if getattr(self, "_debug_page_num", True) and result:
            from collections import Counter
            dist = Counter(b["page_num"] for b in result)
            has_tops = bool(self._page_tops)
            print(f"[DEBUG][get_boxes] total_boxes={len(result)} | "
                  f"page_tops_available={has_tops} | "
                  f"page_distribution={dict(sorted(dist.items()))}")
            for b in result:
                bid  = b.get("box_id", "no-id")[:8]
                rect = b["rect"]
                print(f"  box={bid}  rect_y={rect[1]:.0f}  "
                      f"page_num={b['page_num']}  "
                      f"group={b.get('group_id','')[:6] or 'none'}")
        # ─────────────────────────────────────────────────────────────────────

        return result

    def set_mode(self, mode):
        self._mode = mode
        self._target_group_id = ""
        self._peek_target_idx = -1
        self._peek_target_group_id = ""
        self._peek_active = False
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

    def set_peek_target_box(self, idx):
        self._peek_target_idx = idx
        self._peek_target_group_id = ""
        self._invalidate_mask_cache()
        self.update()

    def set_peek_target_group(self, gid: str):
        self._peek_target_group_id = gid
        self._peek_target_idx = -1
        self._invalidate_mask_cache()
        self.update()

    def clear_peek_target(self):
        self._peek_target_idx = -1
        self._peek_target_group_id = ""
        self._invalidate_mask_cache()
        self.update()

    def set_peek_active(self, active: bool):
        self._peek_active = bool(active)
        self._invalidate_mask_cache()
        self.update()

    def get_target_scaled_rect(self):
        def _rect_for(idx: int, gid: str):
            if gid:
                rects = [self._sr(b["rect"]) for b in self._boxes if b.get("group_id", "") == gid]
                if rects:
                    x1, y1 = min(r.left() for r in rects), min(r.top() for r in rects)
                    x2, y2 = max(r.right() for r in rects), max(r.bottom() for r in rects)
                    return QRectF(x1, y1, x2 - x1, y2 - y1)
            elif 0 <= idx < len(self._boxes):
                return self._sr(self._boxes[idx]["rect"])
            return None

        if self._peek_active:
            peek_r = _rect_for(self._peek_target_idx, self._peek_target_group_id)
            if peek_r is not None:
                return peek_r

        return _rect_for(self._target_idx, self._target_group_id)

    def _is_current_target(self, i: int, b: dict) -> bool:
        return (i == self._target_idx) or (
            bool(self._target_group_id) and b.get("group_id", "") == self._target_group_id
        )

    def _is_peek_target(self, i: int, b: dict) -> bool:
        return self._peek_active and (
            (i == self._peek_target_idx) or (
                bool(self._peek_target_group_id) and
                b.get("group_id", "") == self._peek_target_group_id
            )
        )

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

    def get_current_page(self, scroll_y: int) -> int:
        """Return the 0-based page index visible at the given vertical scroll position."""
        if not self._page_tops:
            return 0
        # Convert screen scroll_y → image-space y
        img_y = scroll_y / max(self._scale, 0.01)
        page = 0
        for i, top in enumerate(self._page_tops):
            if img_y >= top:
                page = i
            else:
                break
        return page

    def scroll_to_page(self, page: int, scroll_area) -> None:
        """Scroll the given QScrollArea so that page `page` is at the top."""
        if not self._page_tops or page >= len(self._page_tops):
            return
        y = int(self._page_tops[page] * self._scale)
        scroll_area.verticalScrollBar().setValue(y)

    def select_all(self):
        if not self._boxes: return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx     = len(self._boxes) - 1
        self._selection_scope  = "pdf"
        self.update()

    def select_all_in_view(self):
        if not self._boxes: return
        sc = self._scroll_area()
        if sc:
            vp = sc.viewport()
            inv = 1.0 / self._scale
            sx = sc.horizontalScrollBar().value()
            sy = sc.verticalScrollBar().value()
            vf = QRectF(sx * inv, sy * inv, vp.width() * inv, vp.height() * inv)
        else:
            vr = self.visibleRegion().boundingRect()
            inv = 1.0 / self._scale
            vf = QRectF(vr.x() * inv, vr.y() * inv, vr.width() * inv, vr.height() * inv)
        self._selected_indices = {i for i, b in enumerate(self._boxes)
                                  if vf.intersects(b["rect"])}
        self._selected_idx = (max(self._selected_indices)
                              if self._selected_indices else -1)
        self._selection_scope = "view"
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def select_all_on_pdf(self):
        self.select_all()

    def select_visible_only(self):
        if not self._boxes: return
        vr = self.visibleRegion().boundingRect()
        inv = 1.0 / self._scale
        vf = QRectF(vr.x()*inv, vr.y()*inv, vr.width()*inv, vr.height()*inv)
        self._selected_indices = {i for i,b in enumerate(self._boxes)
                                  if vf.intersects(b["rect"])}
        self._selected_idx = (max(self._selected_indices)
                              if self._selected_indices else -1)
        self._selection_scope = ""
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
        # Reuse existing group_id if any selected mask already belongs to a group.
        # This allows adding new masks into an existing group without breaking it.
        existing_gids = [self._boxes[i]["group_id"] for i in indices
                         if self._boxes[i].get("group_id", "")]
        gid = existing_gids[0] if existing_gids else str(uuid.uuid4())[:8]
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

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._redo_stack.clear()
        if len(self._undo_stack) > 100: self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack: return
        self._redo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._undo_stack.pop()
        self._selected_idx = -1; self._selected_indices = set()
        self._selection_scope = ""
        self._invalidate_mask_cache(); self.update()
        self.boxes_changed.emit(self.get_boxes())

    def redo(self):
        if not self._redo_stack: return
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._redo_stack.pop()
        self._selected_idx = -1; self._selected_indices = set()
        self._selection_scope = ""
        self._invalidate_mask_cache(); self.update()
        self.boxes_changed.emit(self.get_boxes())

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

