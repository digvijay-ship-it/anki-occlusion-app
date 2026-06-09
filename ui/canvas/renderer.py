from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRect, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import (
    QCursor,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPixmap,
    QPainterPath,
    QTransform,
    QFont,
    QImage,
    QPolygonF,
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
C_MASK = "#F7916A"
C_GROUP = "#BD93F9"


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


class CanvasRendererMixin:
    CANVAS_PAINT_PROFILE_ENV = "ANKI_CANVAS_PAINT_PROFILE"
    _LABEL_FONT = QFont("Segoe UI", 9)
    _SMALL_FONT = QFont("Segoe UI", 7)

    def _canvas_paint_profile_enabled(self):
        raw = os.environ.get("ANKI_CANVAS_PAINT_PROFILE", "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _mask_cache_source_rect(self, clip, pixmap):
        if pixmap is None or pixmap.isNull():
            return QRect()
        pixmap_rect = QRect(0, 0, pixmap.width(), pixmap.height())
        return clip.intersected(pixmap_rect)

    def _draw_mask_cache_layer(self, painter, clip):
        if self._mask_cache_layer is None or self._mask_cache_layer.isNull():
            return QRect()
        offset = self._mask_cache_offset
        cache_rect = QRect(
            int(offset.x()),
            int(offset.y()),
            self._mask_cache_layer.width(),
            self._mask_cache_layer.height(),
        )
        canvas_intersection = clip.intersected(cache_rect)
        if canvas_intersection.isEmpty():
            return QRect()
        source_rect = canvas_intersection.translated(
            -int(offset.x()), -int(offset.y())
        )
        painter.drawPixmap(canvas_intersection, self._mask_cache_layer, source_rect)
        return canvas_intersection

    def _log_canvas_paint_profile(self, elapsed_ms, clip, pages_drawn, phases):
        if getattr(self, "_mode", "") != "review":
            return
        if not self._canvas_paint_profile_enabled():
            return
        now = time.perf_counter()
        last = float(getattr(self, "_last_canvas_paint_profile_log_ts", 0.0) or 0.0)
        if elapsed_ms < 12.0 and (now - last) < 1.0:
            return
        self._last_canvas_paint_profile_log_ts = now
        cache_entries = len(getattr(self, "_spx_cache", {}) or {})
        print(
            "[PROFILE][canvas_paint] "
            f"mode={getattr(self, '_mode', '')} "
            f"total={elapsed_ms:.1f}ms "
            f"clip={clip.width()}x{clip.height()}@{clip.x()},{clip.y()} "
            f"pages_drawn={pages_drawn} "
            f"boxes={len(getattr(self, '_boxes', []) or [])} "
            f"mask_cache={'yes' if getattr(self, '_mask_cache_layer', None) else 'no'} "
            f"scale={float(getattr(self, '_scale', 1.0) or 1.0):.4f} "
            f"scaled_cache={cache_entries} "
            f"scale_miss={int((phases or {}).get('scale_miss', 0))} "
            f"page_scale={float((phases or {}).get('page_scale_ms', 0.0)):.1f}ms "
            f"page_draw={float((phases or {}).get('page_draw_ms', 0.0)):.1f}ms "
            f"mask={float((phases or {}).get('mask_ms', 0.0)):.1f}ms "
            f"mask_clip={phases.get('mask_clip', 'none') if phases else 'none'} "
            f"boxes_draw={float((phases or {}).get('boxes_ms', 0.0)):.1f}ms "
            f"boxes_drawn={int((phases or {}).get('boxes_drawn', 0))} "
            f"overlay={float((phases or {}).get('overlay_ms', 0.0)):.1f}ms "
            f"ink={float((phases or {}).get('ink_ms', 0.0)):.1f}ms"
        )

    def paintEvent(self, event):
        """File: editor_ui.py -> Class: OcclusionCanvas -> Fixed paintEvent"""
        paint_t0 = time.perf_counter()
        pages_drawn = 0
        phases = {
            "page_scale_ms": 0.0,
            "page_draw_ms": 0.0,
            "mask_ms": 0.0,
            "boxes_ms": 0.0,
            "boxes_drawn": 0,
            "overlay_ms": 0.0,
            "ink_ms": 0.0,
            "scale_miss": 0,
            "mask_clip": "none",
        }
        p = QPainter(self)
        clip = event.rect()

        # Viewport check: Rebuild mask cache only when dirty or uninitialized.
        # We do not force-rebuild on viewport offset shifts, which eliminates scroll lag.
        if (
            self._mask_cache_dirty
            or self._mask_cache_layer is None
            or self._mask_cache_layer.isNull()
        ):
            self._rebuild_mask_cache()

        p.fillRect(clip, QColor("#1E1E2E"))

        if self._px and not self._px.isNull():
            cached_scale, cached_spx = self._spx_cache.get("_px", (None, None))
            if cached_scale != self._scale or cached_spx is None:
                phases["scale_miss"] += 1
                scale_t0 = time.perf_counter()
                transform_type = Qt.FastTransformation if getattr(self, "_fast_zoom", False) else Qt.SmoothTransformation
                cached_spx = self._px.scaled(
                    max(int(self._px.width() * self._scale), 1),
                    max(int(self._px.height() * self._scale), 1),
                    Qt.KeepAspectRatio,
                    transform_type,
                )
                self._spx_cache["_px"] = (self._scale, cached_spx)
                phases["page_scale_ms"] += (time.perf_counter() - scale_t0) * 1000.0
            draw_t0 = time.perf_counter()
            p.drawPixmap(0, 0, cached_spx)
            phases["page_draw_ms"] += (time.perf_counter() - draw_t0) * 1000.0

        elif self._pages:
            sep_pen = QPen(QColor("#45475A"), 2)
            for i, page_px in enumerate(self._pages):
                scr_top = int(self._page_tops[i] * self._scale)
                scr_h = int(page_px.height() * self._scale)
                scr_bot = scr_top + scr_h

                if scr_bot < clip.top():
                    continue
                if scr_top > clip.bottom():
                    break

                cached_scale, cached_spx = self._spx_cache.get(i, (None, None))
                cache_hit = (
                    cached_scale == self._scale
                    and cached_spx is not None
                    and not cached_spx.isNull()
                )
                scale_t0 = time.perf_counter()
                scaled_page = self._get_scaled_page(i)
                phases["page_scale_ms"] += (time.perf_counter() - scale_t0) * 1000.0
                if not cache_hit:
                    phases["scale_miss"] += 1
                draw_t0 = time.perf_counter()
                p.drawPixmap(0, scr_top, scaled_page)
                phases["page_draw_ms"] += (time.perf_counter() - draw_t0) * 1000.0
                pages_drawn += 1

                if i < len(self._pages) - 1:
                    sep_y = scr_bot + int(PAGE_GAP * self._scale) // 2
                    p.setPen(sep_pen)
                    p.drawLine(0, sep_y, self.width(), sep_y)

        # ⚡ OPTIMIZATION: Render boxes/masks directly to the screen painter.
        # Allocating and copying QPixmaps on the fly is extremely slow and causes scroll lag.
        # Direct QPainter calls are extremely fast and automatically clipped.
        if False and self._mask_cache_layer and not self._mask_cache_layer.isNull():
            mask_t0 = time.perf_counter()
            mask_clip = self._draw_mask_cache_layer(p, clip)
            phases["mask_ms"] += (time.perf_counter() - mask_t0) * 1000.0
            if not mask_clip.isEmpty():
                phases["mask_clip"] = (
                    f"{mask_clip.width()}x{mask_clip.height()}"
                    f"@{mask_clip.x()},{mask_clip.y()}"
                )
        else:
            p.setRenderHint(QPainter.Antialiasing)
            boxes_t0 = time.perf_counter()
            for i, b in enumerate(self._boxes):
                if self._drag_op and (
                    i == self._selected_idx or i in self._selected_indices
                ):
                    continue
                sr = self._sr(b["rect"])
                if not clip.intersects(sr.toRect()):
                    continue
                self._draw_box(p, i, b)
                phases["boxes_drawn"] += 1
            phases["boxes_ms"] += (time.perf_counter() - boxes_t0) * 1000.0

        p.setRenderHint(QPainter.Antialiasing)
        overlay_t0 = time.perf_counter()
        if self._drag_op == "move" and self._drag_orig_boxes:
            drag_pos = self._drag_current_pos or self._drag_start_pos
            delta = (drag_pos - self._drag_start_pos) / self._scale
            for i, orig_box in self._drag_orig_boxes.items():
                live_rect = QRectF(
                    orig_box["rect"].x() + delta.x(),
                    orig_box["rect"].y() + delta.y(),
                    orig_box["rect"].width(),
                    orig_box["rect"].height(),
                )
                if clip.intersects(self._sr(live_rect).toRect()):
                    self._draw_box_at_rect(p, i, orig_box, live_rect)
        elif self._drag_op and self._selected_idx >= 0:
            self._draw_box(p, self._selected_idx, self._boxes[self._selected_idx])

        if self._drawing and not self._live_rect.isEmpty():
            self._draw_live(p)
        phases["overlay_ms"] += (time.perf_counter() - overlay_t0) * 1000.0

        ink_t0 = time.perf_counter()
        self._draw_ink_layer(p)
        phases["ink_ms"] += (time.perf_counter() - ink_t0) * 1000.0
        p.end()
        self._log_canvas_paint_profile(
            (time.perf_counter() - paint_t0) * 1000.0,
            clip,
            pages_drawn,
            phases,
        )

    def _draw_box(self, p: QPainter, i: int, b: dict):
        sr = self._sr(b["rect"])
        self._draw_box_impl(p, i, b, sr)

    def _draw_box_at_rect(self, p: QPainter, i: int, b: dict, rect: QRectF):
        sr = self._sr(rect)
        self._draw_box_impl(p, i, b, sr)

    def _get_canvas_colors(self):
        from cache_manager import get_pdf_invert_setting
        if get_pdf_invert_setting():
            return {
                "C_MASK": "#8E4A35",        # Dark muted brick orange/rust
                "C_GREEN": "#2E7D32",       # Medium-dark forest green (visible but soft)
                "C_RED": "#8B0000",         # Dark red
                "C_ACCENT": "#512DA8",      # Dark purple
                "C_GROUP": "#5c3f91",       # Dark muted group purple
                "C_BLUE": "#1565C0",        # Dark muted group blue
                "C_BORDER": "#555555",      # Muted dark grey border for non-target masks
                "C_TARGET_BORDER": "#FFFFFF", # Clear white border for target mask
                "C_TEXT": "#E0E0E0",
                "C_YELLOW": "#9E9D24"
            }
        else:
            return {
                "C_MASK": "#8E4A35",        # Dark muted brick orange/rust
                "C_GREEN": "#2E7D32",       # Medium-dark forest green
                "C_RED": "#8B0000",         # Dark red
                "C_ACCENT": "#512DA8",      # Dark purple
                "C_GROUP": "#5c3f91",       # Dark muted group purple
                "C_BLUE": "#1565C0",        # Dark muted blue
                "C_BORDER": "#555555",      # Muted dark grey border
                "C_TARGET_BORDER": "#1E1E2E",  # Dark border for target mask
                "C_TEXT": "#E0E0E0",
                "C_YELLOW": "#9E9D24"
            }

    def _draw_box_impl(self, p: QPainter, i: int, b: dict, sr: QRectF):
        cx, cy = sr.center().x(), sr.center().y()
        ang = b.get("angle", 0.0)
        lbl = b.get("label") or f"#{i+1}"
        shape = b.get("shape", "rect")
        sel = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        local = QRectF(-sr.width() / 2, -sr.height() / 2, sr.width(), sr.height())

        cc = self._get_canvas_colors()
        if self._mode == "review":
            revealed = b.get("revealed", False)
            is_target = self._is_current_target(i, b)
            is_peek_target = self._is_peek_target(i, b)
            hide_one = self._review_mode_style == "hide_one"

            if hide_one and not is_target and not is_peek_target:
                if not revealed:
                    p.setPen(QPen(QColor(cc["C_GREEN"]), 1, Qt.DotLine))
                    p.setBrush(Qt.NoBrush)
                    (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
                p.restore()
                return

            if not revealed:
                color = QColor(
                    cc["C_RED"] if is_peek_target else (cc["C_GREEN"] if is_target else cc["C_MASK"])
                )
                border_col = QColor(
                    cc["C_TARGET_BORDER"] if (is_target or is_peek_target) else cc["C_BORDER"]
                )
                p.setBrush(QBrush(color))
                p.setPen(QPen(border_col, 2))
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            else:
                p.setPen(QPen(QColor(cc["C_RED"] if is_peek_target else cc["C_GREEN"]), 2))
                p.setBrush(Qt.NoBrush)
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
        else:
            gid = b.get("group_id", "")
            grouped = bool(gid)
            fill = QColor(cc["C_GREEN"] if sel else cc["C_BLUE"] if grouped else cc["C_MASK"])
            fill.setAlpha(155)
            p.setBrush(QBrush(fill))
            border_col = QColor(cc["C_GREEN"] if sel else cc["C_BLUE"] if grouped else cc["C_BORDER"])
            p.setPen(QPen(border_col, 2, Qt.DashLine if not grouped else Qt.SolidLine))
            (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            p.setPen(QPen(border_col, 1))
            p.setFont(self._LABEL_FONT)
            dlbl = (
                f"[{gid[:4]}] {lbl}" if gid and lbl else f"[{gid[:4]}]" if gid else lbl
            )
            p.drawText(local, Qt.AlignCenter, dlbl)

        p.restore()
        if self._mode == "edit" and i == self._selected_idx:
            self._draw_handles(p, i)

    def _draw_handles(self, p: QPainter, idx: int):
        hps = self._handle_positions(idx)
        if not hps:
            return
        cc = self._get_canvas_colors()
        p.setPen(QPen(QColor(cc["C_GREEN"]), 1))
        p.setBrush(QBrush(QColor("#1E1E2E")))
        hr = self._HANDLE_R
        for hpt in hps["resize"]:
            p.drawEllipse(hpt, hr, hr)
        rpt = hps["rotate"]
        top_c = hps["resize"][1]
        p.setPen(QPen(QColor(cc["C_ACCENT"]), 1))
        p.drawLine(top_c, rpt)
        p.setBrush(QBrush(QColor(cc["C_ACCENT"])))
        p.setPen(QPen(QColor("#FFF"), 1))
        p.drawEllipse(rpt, hr + 1, hr + 1)
        p.setFont(self._SMALL_FONT)
        p.drawText(QRectF(rpt.x() - 6, rpt.y() - 6, 12, 12), Qt.AlignCenter, "↻")

    def _draw_live(self, p: QPainter):
        sr = self._sr(self._live_rect)
        cc = self._get_canvas_colors()
        c = QColor(cc["C_ACCENT"])
        c.setAlpha(110)
        p.setBrush(QBrush(c))
        p.setPen(QPen(QColor(cc["C_ACCENT"]), 2))
        (p.drawEllipse if self._tool == "ellipse" else p.drawRect)(sr)

    def _smooth_points_to_path(self, pts, sc) -> QPainterPath:
        path = QPainterPath()
        if not pts:
            return path
        
        # Scale points to screen space
        spts = [QPointF(pt.x() * sc, pt.y() * sc) for pt in pts]
        
        path.moveTo(spts[0])
        if len(spts) == 1:
            return path
        if len(spts) == 2:
            path.lineTo(spts[1])
            return path
            
        p0 = spts[0]
        p1 = spts[1]
        first_mid = QPointF((p0.x() + p1.x()) / 2.0, (p0.y() + p1.y()) / 2.0)
        path.lineTo(first_mid)
        
        for i in range(1, len(spts) - 1):
            curr = spts[i]
            nxt = spts[i + 1]
            mid = QPointF((curr.x() + nxt.x()) / 2.0, (curr.y() + nxt.y()) / 2.0)
            path.quadTo(curr, mid)
            
        path.lineTo(spts[-1])
        return path

    def _draw_ink_layer(self, p: QPainter):
        if not self._ink_strokes and not self._ink_current:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pen_w = max(1.0, self._ink_width * self._scale)
        sc = self._scale
        
        # Initialize the path cache if not present
        if not hasattr(self, "_ink_path_cache"):
            self._ink_path_cache = {}

        # Draw completed strokes using cached QPainterPath
        for stroke in self._ink_strokes:
            if len(stroke) < 2:
                continue
            color = stroke[0]
            pts = stroke[1:]
            if not pts:
                continue
            
            # Cache check by object id and scale
            stroke_id = id(stroke)
            cached_scale, path = self._ink_path_cache.get(stroke_id, (None, None))
            if cached_scale != sc or path is None:
                path = self._smooth_points_to_path(pts, sc)
                self._ink_path_cache[stroke_id] = (sc, path)
                
            p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            
        # Draw current stroke (live drawing)
        if self._ink_current and len(self._ink_current) >= 2:
            color = self._ink_current[0]
            pts = self._ink_current[1:]
            if pts:
                p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                if len(pts) == 1:
                    p.drawPoint(QPointF(pts[0].x() * sc, pts[0].y() * sc))
                else:
                    path = self._smooth_points_to_path(pts, sc)
                    p.drawPath(path)
        p.restore()

    def _redraw(self):
        """Legacy shim — ReviewScreen calls this after revealing a mask."""
        self._invalidate_mask_cache()
        self.update()
