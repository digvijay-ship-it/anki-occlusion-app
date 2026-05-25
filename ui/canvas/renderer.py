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

    def _canvas_paint_profile_enabled(self):
        raw = os.environ.get(self.CANVAS_PAINT_PROFILE_ENV, "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _mask_cache_source_rect(self, clip, pixmap):
        if pixmap is None or pixmap.isNull():
            return QRect()
        pixmap_rect = QRect(0, 0, pixmap.width(), pixmap.height())
        return clip.intersected(pixmap_rect)

    def _draw_mask_cache_layer(self, painter, clip):
        source = self._mask_cache_source_rect(clip, self._mask_cache_layer)
        if source.isEmpty():
            return QRect()
        painter.drawPixmap(source, self._mask_cache_layer, source)
        return source

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

        p.fillRect(clip, QColor("#1E1E2E"))

        if self._px and not self._px.isNull():
            cached_scale, cached_spx = self._spx_cache.get("_px", (None, None))
            if cached_scale != self._scale or cached_spx is None:
                phases["scale_miss"] += 1
                scale_t0 = time.perf_counter()
                cached_spx = self._px.scaled(
                    max(int(self._px.width() * self._scale), 1),
                    max(int(self._px.height() * self._scale), 1),
                    Qt.KeepAspectRatio,
                    Qt.FastTransformation,
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

        if self._mask_cache_layer and not self._mask_cache_layer.isNull():
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
        cx, cy = sr.center().x(), sr.center().y()
        ang = b.get("angle", 0.0)
        lbl = b.get("label") or f"#{i+1}"
        shape = b.get("shape", "rect")
        sel = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        local = QRectF(-sr.width() / 2, -sr.height() / 2, sr.width(), sr.height())

        if self._mode == "review":
            revealed = b.get("revealed", False)
            is_target = self._is_current_target(i, b)
            is_peek_target = self._is_peek_target(i, b)
            hide_one = self._review_mode_style == "hide_one"

            if hide_one and not is_target and not is_peek_target:
                if not revealed:
                    p.setPen(QPen(QColor(C_GREEN), 1, Qt.DotLine))
                    p.setBrush(Qt.NoBrush)
                    (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
                p.restore()
                return

            if not revealed:
                color = QColor(
                    "#D64545" if is_peek_target else (C_GREEN if is_target else C_MASK)
                )
                text_col = "#1E1E2E" if (is_target or is_peek_target) else "#FFF"
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(text_col), 2))
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            else:
                p.setPen(QPen(QColor("#D64545" if is_peek_target else C_GREEN), 2))
                p.setBrush(Qt.NoBrush)
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
        else:
            gid = b.get("group_id", "")
            grouped = bool(gid)
            fill = QColor("#50FA7B" if sel else "#6EB5FF" if grouped else C_MASK)
            fill.setAlpha(155)
            p.setBrush(QBrush(fill))
            border_col = QColor(C_GREEN if sel else "#2288FF" if grouped else "#FFF")
            p.setPen(QPen(border_col, 2, Qt.DashLine if not grouped else Qt.SolidLine))
            (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            p.setPen(QPen(border_col, 1))
            p.setFont(QFont("Segoe UI", 9))
            dlbl = (
                f"[{gid[:4]}] {lbl}" if gid and lbl else f"[{gid[:4]}]" if gid else lbl
            )
            p.drawText(local, Qt.AlignCenter, dlbl)

        p.restore()
        if self._mode == "edit" and i == self._selected_idx:
            self._draw_handles(p, i)

    def _draw_box_at_rect(self, p: QPainter, i: int, b: dict, rect: QRectF):
        sr = self._sr(rect)
        cx, cy = sr.center().x(), sr.center().y()
        ang = b.get("angle", 0.0)
        lbl = b.get("label") or f"#{i+1}"
        shape = b.get("shape", "rect")
        sel = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        local = QRectF(-sr.width() / 2, -sr.height() / 2, sr.width(), sr.height())

        if self._mode == "review":
            revealed = b.get("revealed", False)
            is_target = self._is_current_target(i, b)
            is_peek_target = self._is_peek_target(i, b)
            hide_one = self._review_mode_style == "hide_one"

            if hide_one and not is_target and not is_peek_target:
                color = QColor("#3A3A4F")
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(color), 2, Qt.SolidLine))
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            else:
                color = QColor(
                    "#D64545" if is_peek_target else (C_GREEN if is_target else C_MASK)
                )
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor("#D64545" if is_peek_target else C_GREEN), 2))
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
                if revealed:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor("#4CAF50"), 2, Qt.DashLine))
                    (p.drawEllipse if shape == "ellipse" else p.drawRect)(
                        local.adjusted(2, 2, -2, -2)
                    )
        else:
            gid = b.get("group_id", "")
            grouped = bool(gid)
            fill = QColor("#50FA7B" if sel else "#6EB5FF" if grouped else C_MASK)
            fill.setAlpha(155)
            p.setBrush(QBrush(fill))
            border_col = QColor(C_GREEN if sel else "#2288FF" if grouped else "#FFF")
            p.setPen(QPen(border_col, 2, Qt.DashLine if not grouped else Qt.SolidLine))
            (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            p.setPen(QPen(border_col, 1))
            p.setFont(QFont("Segoe UI", 9))
            dlbl = (
                f"[{gid[:4]}] {lbl}"
                if gid and lbl
                else (f"[{gid[:4]}]" if gid else lbl)
            )
            p.drawText(local, Qt.AlignCenter, dlbl)

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
        p.drawText(QRectF(rpt.x() - 6, rpt.y() - 6, 12, 12), Qt.AlignCenter, "↻")

    def _draw_live(self, p: QPainter):
        sr = self._sr(self._live_rect)
        c = QColor(C_ACCENT)
        c.setAlpha(110)
        p.setBrush(QBrush(c))
        p.setPen(QPen(QColor(C_ACCENT), 2))
        (p.drawEllipse if self._tool == "ellipse" else p.drawRect)(sr)

    def _draw_ink_layer(self, p: QPainter):
        if not self._ink_strokes and not self._ink_current:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pen_w = max(1.0, self._ink_width * self._scale)
        sc = self._scale
        for stroke in list(self._ink_strokes) + (
            [self._ink_current] if self._ink_current else []
        ):
            if len(stroke) < 2:
                continue
            color = stroke[0]
            pts = stroke[1:]
            if not pts:
                continue
            p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(pts) == 1:
                p.drawPoint(QPointF(pts[0].x() * sc, pts[0].y() * sc))
            else:
                # ⚡ FIX: Use drawPolyline instead of N individual drawLine calls.
                # drawLine in a loop = N separate QPainter state flushes.
                # drawPolyline = 1 GPU call for the entire stroke. For a 200-point
                # stroke this is ~200x fewer GPU round-trips.
                poly = QPolygonF([QPointF(pt.x() * sc, pt.y() * sc) for pt in pts])
                p.drawPolyline(poly)
        p.restore()

    def _redraw(self):
        """Legacy shim — ReviewScreen calls this after revealing a mask."""
        self._invalidate_mask_cache()
        self.update()
