from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPixmap,
    QPainterPath,
    QTransform,
    QCursor,
    QImage,
)

import uuid
import time
import math
import copy
import os

from cache_manager import MASK_REGISTRY, PIXMAP_REGISTRY

# ── Theme constants — single source of truth is theme_manager.PALETTES["dark"] ──
from theme_manager import get_palette as _get_palette

_DARK = _get_palette("dark")
C_BG = _DARK["C_BG"]
C_SURFACE = _DARK["C_SURFACE"]
C_CARD = _DARK["C_CARD"]
C_ACCENT = _DARK["C_ACCENT"]
C_GREEN = _DARK["C_GREEN"]
C_RED = _DARK["C_RED"]
C_YELLOW = _DARK["C_YELLOW"]
C_TEXT = _DARK["C_TEXT"]
C_SUBTEXT = _DARK["C_SUBTEXT"]
C_BORDER = _DARK["C_BORDER"]


# Dummy values that were in editor_ui
PAGE_GAP = 12
REVEAL_COLOR = "#00000000"  # transparent


def _point_in_rotated_box(px, py, cx, cy, w, h, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    return abs(lx) <= w / 2 and abs(ly) <= h / 2


def _point_in_rotated_ellipse(px, py, cx, cy, rx, ry, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    if rx < 1 or ry < 1:
        return False
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1


class CanvasStateMixin:
    def load_pixmap(self, px: QPixmap):
        """Single-image mode (non-PDF). Clears any page list."""
        self._pages = []
        self._page_tops = []
        self._total_h = 0
        self._total_w = 0
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
        cache_before = len(self._spx_cache)
        old_dims = [(p.width(), p.height()) for p in self._pages if p and not p.isNull()]
        new_pages = [p for p in pages if p and not p.isNull()]
        new_dims = [(p.width(), p.height()) for p in new_pages]
        current_pdf = getattr(self, "_current_pdf_path", "") or ""
        cache_pdf = getattr(self, "_spx_cache_pdf_path", "") or ""
        preserve_scaled = bool(
            cache_before
            and cache_pdf
            and current_pdf
            and cache_pdf == current_pdf
            and old_dims == new_dims
        )
        self._pages = new_pages
        if not preserve_scaled:
            self._spx_cache.clear()
        self._spx_cache_pdf_path = current_pdf
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
        return QRectF(
            r.x() * self._scale,
            r.y() * self._scale,
            r.width() * self._scale,
            r.height() * self._scale,
        )

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
        if isinstance(page_px, QImage):
            page_px = QPixmap.fromImage(page_px)
            self._pages[idx] = page_px

        cached_scale, cached_spx = self._spx_cache.get(idx, (None, None))
        if (
            cached_scale == self._scale
            and cached_spx is not None
            and not cached_spx.isNull()
        ):
            return cached_spx
        sw = max(int(page_px.width() * self._scale), 1)
        sh = max(int(page_px.height() * self._scale), 1)
        transform_type = Qt.FastTransformation if getattr(self, "_fast_zoom", False) else Qt.SmoothTransformation
        cached_spx = page_px.scaled(sw, sh, Qt.KeepAspectRatio, transform_type)
        self._spx_cache[idx] = (self._scale, cached_spx)
        self._spx_cache_pdf_path = getattr(self, "_current_pdf_path", "") or ""
        return cached_spx

    def inject_page(self, page_num: int, qpx):
        """
        Replace a placeholder QPixmap with the real rendered page.

        Called by PdfOnDemandThread.page_ready signal.
        Layout (page_tops, total_h) does NOT change — placeholder was same size.
        Only the visual content of that one page slot updates.

        Terminal debug shows: which page, old size vs new size, timing.
        """
        # ── Bounds check ──────────────────────────────────────────────────────
        if page_num < 0 or page_num >= len(self._pages):
            return

        if qpx is None or qpx.isNull():
            return

        old_px = self._pages[page_num]
        old_w = old_px.width() if old_px else 0
        old_h = old_px.height() if old_px else 0
        new_w = qpx.width()
        new_h = qpx.height()

        # ── Dimension sanity check ────────────────────────────────────────────
        # Skeleton aur real page same zoom se bane hain — should always match.
        # Agar mismatch hai toh recompute layout (shouldn't happen in practice).
        dims_match = old_w == new_w and old_h == new_h

        # ── Inject ────────────────────────────────────────────────────────────
        self._pages[page_num] = qpx

        # Refresh or invalidate scaled cache for this page only.
        cached_scale, _cached_spx = self._spx_cache.get(page_num, (None, None))
        had_scaled_cache = cached_scale is not None
        if had_scaled_cache and dims_match and cached_scale == self._scale:
            sw = max(int(new_w * self._scale), 1)
            sh = max(int(new_h * self._scale), 1)
            transform_type = Qt.FastTransformation if getattr(self, "_fast_zoom", False) else Qt.SmoothTransformation
            self._spx_cache[page_num] = (
                self._scale,
                qpx.scaled(sw, sh, Qt.KeepAspectRatio, transform_type),
            )
            self._spx_cache_pdf_path = getattr(self, "_current_pdf_path", "") or ""
        else:
            self._spx_cache.pop(page_num, None)
        if not dims_match:
            # 1. Capture old layout properties
            old_page_tops = list(self._page_tops)

            # 2. Map boxes to their pages using old tops
            box_pages = []
            for b in self._boxes:
                r = b["rect"]
                cy = r.y() + r.height() / 2
                p_num = 0
                if old_page_tops:
                    for pi, top in enumerate(old_page_tops):
                        if cy >= top:
                            p_num = pi
                        else:
                            break
                box_pages.append(p_num)

            # 3. Update layout
            self._compute_layout()

            # 4. Map box coordinates to new page tops and scale if on the changed page
            for i, b in enumerate(self._boxes):
                p_num = box_pages[i]
                r = b["rect"]

                old_top = old_page_tops[p_num] if p_num < len(old_page_tops) else 0
                local_y = r.y() - old_top
                new_top = self._page_tops[p_num] if p_num < len(self._page_tops) else 0

                if p_num == page_num:
                    sy = new_h / max(old_h, 1.0)
                    sx = new_w / max(old_w, 1.0)
                    new_local_y = local_y * sy
                    new_x = r.x() * sx
                    new_w_val = r.width() * sx
                    new_h_val = r.height() * sy
                else:
                    new_local_y = local_y
                    new_x = r.x()
                    new_w_val = r.width()
                    new_h_val = r.height()

                from PyQt5.QtCore import QRectF
                b["rect"] = QRectF(new_x, new_top + new_local_y, new_w_val, new_h_val)

            self._resize_canvas()
            self._invalidate_mask_cache()

        else:
            # Fast path — only repaint the dirty page region
            # No layout recompute needed — sizes match exactly
            if self._page_tops and page_num < len(self._page_tops):
                top_img = self._page_tops[page_num]
                top_scr = int(top_img * self._scale)
                h_scr = int(new_h * self._scale)
                from PyQt5.QtCore import QRect

                self.update(QRect(0, top_scr, self.width(), h_scr))
            else:
                self.update()

    def _invalidate_mask_cache(self):
        self._mask_cache_dirty = True
        if getattr(self, "_mask_cache_rebuild_pending", False):
            return
        self._mask_cache_rebuild_pending = True
        QTimer.singleShot(0, self._rebuild_mask_cache_if_dirty)

    def _rebuild_mask_cache_if_dirty(self):
        self._mask_cache_rebuild_pending = False
        if self._mask_cache_dirty:
            self._rebuild_mask_cache()
            self.update()

    def _get_viewport_rect(self):
        """Return the visible viewport rectangle in screen-space coordinates."""
        sc = self._scroll_area()
        if sc is not None:
            vp = sc.viewport()
            sx = sc.horizontalScrollBar().value()
            sy = sc.verticalScrollBar().value()
            from PyQt5.QtCore import QRect
            return QRect(sx, sy, vp.width(), vp.height())
        # Fallback: use widget's visible region
        vr = self.visibleRegion().boundingRect()
        if vr.isEmpty():
            w, h = self._canvas_wh()
            from PyQt5.QtCore import QRect
            return QRect(0, 0, max(int(w * self._scale), 1), max(int(h * self._scale), 1))
        return vr

    def _rebuild_mask_cache(self):
        if not self.has_content():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return
        # Get viewport rect in screen-space
        viewport = self._get_viewport_rect()
        if viewport is None or viewport.width() < 1 or viewport.height() < 1:
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return
        sw, sh = viewport.width(), viewport.height()
        _QT_MAX_PX = 32767
        if sh > _QT_MAX_PX or sw > _QT_MAX_PX:
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return
        self._mask_cache_layer = QPixmap(sw, sh)
        self._mask_cache_layer.fill(Qt.transparent)
        self._mask_cache_offset = viewport.topLeft()
        mp = QPainter(self._mask_cache_layer)
        mp.setRenderHint(QPainter.Antialiasing)
        mp.translate(-viewport.x(), -viewport.y())
        for i, b in enumerate(self._boxes):
            if self._drag_op and i == self._selected_idx:
                continue
            box_sr = self._sr(b["rect"])
            if box_sr.toRect().intersects(viewport):
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
        self.zoom_changed.emit(self._scale)

    def _finalize_zoom(self):
        self._fast_zoom = False
        self._smooth_timer.start(300)  # switch to smooth quality after zoom settles

    def _apply_smooth(self):
        """Clear fast-scaled cache and repaint with SmoothTransformation."""
        self._spx_cache.clear()
        self.update()

    def set_tool(self, tool: str):
        self._tool = tool
        cursors = {
            "select": Qt.ArrowCursor,
            "rect": Qt.CrossCursor,
            "ellipse": Qt.CrossCursor,
            "text": Qt.IBeamCursor,
        }
        self.setCursor(QCursor(cursors.get(tool, Qt.CrossCursor)))

    def set_boxes(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=False) for b in boxes]
        self._invalidate_mask_cache()
        self.update()

    def set_boxes_with_state(self, boxes):
        self._boxes = [
            self._deserialise_box(b, revealed=b.get("revealed", False)) for b in boxes
        ]
        if self._mode != "review":
            self._ink_strokes.clear()
            self._ink_current.clear()
        self._invalidate_mask_cache()
        self.update()

    def get_boxes(self):
        SM2_KEYS = (
            "sm2_interval",
            "sm2_repetitions",
            "sm2_ease",
            "sm2_due",
            "sm2_last_quality",
            "box_id",
            "sched_state",
            "sched_step",
            "reviews",
        )
        result = []
        for b in self._boxes:
            r = b["rect"]
            d = {
                "rect": [r.x(), r.y(), r.width(), r.height()],
                "label": b.get("label", ""),
                "shape": b.get("shape", "rect"),
                "angle": b.get("angle", 0.0),
                "group_id": b.get("group_id", ""),
            }
            for k in SM2_KEYS:
                if k in b:
                    d[k] = b[k]

            # ── STEP 1: page_num calculation ──────────────────────────────────
            # Box rect Y-center se _page_tops ka reverse-lookup karke page number
            # nikaalte hain. Yeh field lazy loading ke Phase 2 mein use hogi —
            # bina full PDF load kiye pata chalega ki aaj ke due masks kahan hain.
            # Agar _page_tops available nahi (single-image mode) toh page_num = 0.
            page_num = 0
            if self._page_tops:
                cy = r.y() + r.height() / 2  # box ka Y-center (image-space)
                for pi, top in enumerate(self._page_tops):
                    if cy >= top:
                        page_num = pi
                    else:
                        break
            d["page_num"] = page_num

            result.append(d)

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
            self.setCursor(
                QCursor(
                    Qt.CrossCursor
                    if getattr(self, "_ink_active", False)
                    else Qt.PointingHandCursor
                )
            )
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
                rects = [
                    self._sr(b["rect"])
                    for b in self._boxes
                    if b.get("group_id", "") == gid
                ]
                if rects:
                    x1, y1 = min(r.left() for r in rects), min(r.top() for r in rects)
                    x2, y2 = max(r.right() for r in rects), max(
                        r.bottom() for r in rects
                    )
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
            bool(self._target_group_id)
            and b.get("group_id", "") == self._target_group_id
        )

    def _is_peek_target(self, i: int, b: dict) -> bool:
        return self._peek_active and (
            (i == self._peek_target_idx)
            or (
                bool(self._peek_target_group_id)
                and b.get("group_id", "") == self._peek_target_group_id
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
        epsilon = 0.75
        import bisect
        idx = bisect.bisect_right(self._page_tops, img_y + epsilon)
        return max(0, idx - 1)

    def scroll_to_page(self, page: int, scroll_area) -> None:
        """Scroll the given QScrollArea so that page `page` is at the top."""
        if not self._page_tops or page >= len(self._page_tops):
            return
        y = math.ceil(self._page_tops[page] * self._scale)
        scroll_area.verticalScrollBar().setValue(y)

    def select_all(self):
        if not self._boxes:
            return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx = len(self._boxes) - 1
        self._selection_scope = "pdf"
        self.update()

    def select_all_in_view(self):
        if not self._boxes:
            return
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
        self._selected_indices = {
            i for i, b in enumerate(self._boxes) if vf.intersects(b["rect"])
        }
        self._selected_idx = (
            max(self._selected_indices) if self._selected_indices else -1
        )
        self._selection_scope = "view"
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def select_all_on_pdf(self):
        self.select_all()

    def select_visible_only(self):
        if not self._boxes:
            return
        vr = self.visibleRegion().boundingRect()
        inv = 1.0 / self._scale
        vf = QRectF(vr.x() * inv, vr.y() * inv, vr.width() * inv, vr.height() * inv)
        self._selected_indices = {
            i for i, b in enumerate(self._boxes) if vf.intersects(b["rect"])
        }
        self._selected_idx = (
            max(self._selected_indices) if self._selected_indices else -1
        )
        self._selection_scope = ""
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
            self._selected_idx = -1
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
        self._boxes = []
        self._selected_idx = -1
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit([])

    def highlight(self, idx):
        old_idx = self._selected_idx
        self._selected_idx = idx
        # Only repaint affected boxes, not entire canvas
        from PyQt5.QtCore import QRect
        dirty = QRect()
        if 0 <= old_idx < len(self._boxes):
            dirty = dirty.united(self._sr(self._boxes[old_idx]["rect"]).toRect().adjusted(-10, -10, 10, 10))
        if 0 <= idx < len(self._boxes):
            dirty = dirty.united(self._sr(self._boxes[idx]["rect"]).toRect().adjusted(-10, -10, 10, 10))
        if dirty.isEmpty():
            self.update()
        else:
            self.update(dirty)

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
        # Reuse existing group_id if any selected mask already belongs to a group.
        # This allows adding new masks into an existing group without breaking it.
        existing_gids = [
            self._boxes[i]["group_id"]
            for i in indices
            if self._boxes[i].get("group_id", "")
        ]
        gid = existing_gids[0] if existing_gids else str(uuid.uuid4())[:8]
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

    def _clone_box(self, b):
        if b is None:
            return None
        cb = b.copy()
        if "rect" in cb:
            cb["rect"] = QRectF(cb["rect"])
        return cb

    def _clone_boxes(self, boxes):
        if boxes is None:
            return None
        return [self._clone_box(b) for b in boxes]

    def _push_undo(self):
        self._undo_stack.append(self._clone_boxes(self._boxes))
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._clone_boxes(self._boxes))
        self._boxes = self._undo_stack.pop()
        self._selected_idx = -1
        self._selected_indices = set()
        self._selection_scope = ""
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._clone_boxes(self._boxes))
        self._boxes = self._redo_stack.pop()
        self._selected_idx = -1
        self._selected_indices = set()
        self._selection_scope = ""
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def _get_all_selected(self):
        r = set(self._selected_indices)
        if self._selected_idx >= 0:
            r.add(self._selected_idx)
        return sorted(r)

    def _deserialise_box(self, b, revealed=False):
        r = b["rect"]
        return {
            "rect": QRectF(r[0], r[1], r[2], r[3]),
            "shape": b.get("shape", "rect"),
            "angle": float(b.get("angle", 0.0)),
            "revealed": revealed,
            "label": b.get("label", ""),
            "box_id": b.get("box_id", ""),
            "group_id": b.get("group_id", ""),
            **{
                k: b[k]
                for k in (
                    "sm2_interval",
                    "sm2_repetitions",
                    "sm2_ease",
                    "sm2_due",
                    "sm2_last_quality",
                )
                if k in b
            },
        }

    def _qt_object_alive(self, obj) -> bool:
        if obj is None:
            return False
        try:
            obj.objectName()
            return True
        except RuntimeError:
            return False

    def _hide_toast(self):
        label = getattr(self, "_toast_label", None)
        if not self._qt_object_alive(label):
            self._toast_label = None
            return
        label.hide()

    def _show_toast(self, msg: str):
        if not self._qt_object_alive(self):
            return
        if not self._qt_object_alive(getattr(self, "_toast_label", None)):
            self._toast_label = QLabel(self)
            self._toast_label.setStyleSheet(
                "QLabel{background:rgba(30,30,46,210);color:#BD93F9;"
                "border:1px solid #BD93F9;border-radius:6px;"
                "padding:4px 12px;font-size:12px;font-weight:bold;}"
            )
            self._toast_label.hide()
        if not self._qt_object_alive(getattr(self, "_toast_timer", None)):
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._hide_toast)
        try:
            self._toast_label.setText(msg)
            self._toast_label.adjustSize()
            self._toast_label.move((self.width() - self._toast_label.width()) // 2, 18)
            self._toast_label.show()
            self._toast_label.raise_()
            self._toast_timer.start(1800)
        except RuntimeError:
            # Background PDF work can finish while the canvas is closing.
            self._toast_label = None
            self._toast_timer = None
