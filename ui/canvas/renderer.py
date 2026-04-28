from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import QCursor, QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath, QTransform, QFont

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
C_MASK    = '#F7916A'
C_GROUP   = '#BD93F9'


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


class CanvasRendererMixin:
    def paintEvent(self, event):
        """File: editor_ui.py -> Class: OcclusionCanvas -> Fixed paintEvent"""
        p = QPainter(self)
        clip = event.rect()

        p.fillRect(clip, QColor("#1E1E2E"))

        if self._px and not self._px.isNull():
            cached_scale, cached_spx = self._spx_cache.get("_px", (None, None))
            if cached_scale != self._scale or cached_spx is None:
                cached_spx = self._px.scaled(
                    max(int(self._px.width() * self._scale), 1),
                    max(int(self._px.height() * self._scale), 1),
                    Qt.KeepAspectRatio, Qt.FastTransformation)
                self._spx_cache["_px"] = (self._scale, cached_spx)
            p.drawPixmap(0, 0, cached_spx)

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

                p.drawPixmap(0, scr_top, self._get_scaled_page(i))

                if i < len(self._pages) - 1:
                    sep_y = scr_bot + int(PAGE_GAP * self._scale) // 2
                    p.setPen(sep_pen)
                    p.drawLine(0, sep_y, self.width(), sep_y)

        if self._mask_cache_layer and not self._mask_cache_layer.isNull():
            p.drawPixmap(0, 0, self._mask_cache_layer)
        else:
            p.setRenderHint(QPainter.Antialiasing)
            for i, b in enumerate(self._boxes):
                if self._drag_op and (i == self._selected_idx or i in self._selected_indices):
                    continue
                sr = self._sr(b["rect"])
                if not clip.intersects(sr.toRect()):
                    continue
                self._draw_box(p, i, b)

        p.setRenderHint(QPainter.Antialiasing)
        if self._drag_op == "move" and self._drag_orig_boxes:
            drag_pos = self._drag_current_pos or self._drag_start_pos
            delta = (drag_pos - self._drag_start_pos) / self._scale
            for i, orig_box in self._drag_orig_boxes.items():
                live_rect = QRectF(
                    orig_box["rect"].x() + delta.x(),
                    orig_box["rect"].y() + delta.y(),
                    orig_box["rect"].width(),
                    orig_box["rect"].height())
                if clip.intersects(self._sr(live_rect).toRect()):
                    self._draw_box_at_rect(p, i, orig_box, live_rect)
        elif self._drag_op and self._selected_idx >= 0:
            self._draw_box(p, self._selected_idx, self._boxes[self._selected_idx])

        if self._drawing and not self._live_rect.isEmpty():
            self._draw_live(p)

        self._draw_ink_layer(p)
        p.end()

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
            is_target = self._is_current_target(i, b)
            is_peek_target = self._is_peek_target(i, b)
            hide_one  = (self._review_mode_style == "hide_one")

            if hide_one and not is_target and not is_peek_target:
                if not revealed:
                    p.setPen(QPen(QColor(C_GREEN), 1, Qt.DotLine))
                    p.setBrush(Qt.NoBrush)
                    (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
                p.restore(); return

            if not revealed:
                color    = QColor("#D64545" if is_peek_target else (C_GREEN if is_target else C_MASK))
                text_col = "#1E1E2E" if (is_target or is_peek_target) else "#FFF"
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(text_col), 2))
                (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
            else:
                p.setPen(QPen(QColor("#D64545" if is_peek_target else C_GREEN), 2)); p.setBrush(Qt.NoBrush)
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

    def _draw_box_at_rect(self, p: QPainter, i: int, b: dict, rect: QRectF):
        sr    = self._sr(rect)
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
            is_target = self._is_current_target(i, b)
            is_peek_target = self._is_peek_target(i, b)
            hide_one  = (self._review_mode_style == "hide_one")

            if hide_one and not is_target and not is_peek_target:
                color    = QColor("#3A3A4F")
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(color), 2, Qt.SolidLine))
                (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
            else:
                color    = QColor("#D64545" if is_peek_target else (C_GREEN if is_target else C_MASK))
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor("#D64545" if is_peek_target else C_GREEN), 2))
                (p.drawEllipse if shape=="ellipse" else p.drawRect)(local)
                if revealed:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor("#4CAF50"), 2, Qt.DashLine))
                    (p.drawEllipse if shape=="ellipse" else p.drawRect)(local.adjusted(2,2,-2,-2))
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
                    else (f"[{gid[:4]}]" if gid else lbl))
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

    def _draw_ink_layer(self, p: QPainter):
        if not self._ink_strokes and not self._ink_current: return
        p.save(); p.setRenderHint(QPainter.Antialiasing)
        pen_w = max(1.0, self._ink_width * self._scale)
        sc = self._scale
        for stroke in list(self._ink_strokes) + ([self._ink_current] if self._ink_current else []):
            if len(stroke) < 2: continue
            color = stroke[0]; pts = stroke[1:]
            if not pts: continue
            p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(pts) == 1:
                p.drawPoint(QPointF(pts[0].x() * sc, pts[0].y() * sc))
            else:
                # ⚡ FIX: Use drawPolyline instead of N individual drawLine calls.
                # drawLine in a loop = N separate QPainter state flushes.
                # drawPolyline = 1 GPU call for the entire stroke. For a 200-point
                # stroke this is ~200x fewer GPU round-trips.
                from PyQt5.QtGui import QCursor, QPolygonF
                poly = QPolygonF([QPointF(pt.x() * sc, pt.y() * sc) for pt in pts])
                p.drawPolyline(poly)
        p.restore()

    def _redraw(self):
        """Legacy shim — ReviewScreen calls this after revealing a mask."""
        self._invalidate_mask_cache()
        self.update()

