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

from cache_manager import PIXMAP_REGISTRY

from .colors import (
    C_BG, C_SURFACE, C_CARD, C_ACCENT, C_GREEN, C_RED, C_YELLOW,
    C_TEXT, C_SUBTEXT, C_BORDER, PAGE_GAP, REVEAL_COLOR
)
C_MASK = "#F7916A"
C_GROUP = "#BD93F9"

_C_BG_CANVAS = QColor("#1E1E2E")
_SEP_PEN = QPen(QColor("#45475A"), 2)

_CANVAS_COLORS_CACHE = {}

def _get_canvas_colors_objects(invert: bool):
    if invert in _CANVAS_COLORS_CACHE:
        return _CANVAS_COLORS_CACHE[invert]
    
    if invert:
        c_dict = {
            "C_MASK": "#8E4A35",        # Dark muted brick orange/rust
            "C_GREEN": "#2E7D32",       # Medium-dark forest green (visible but soft)
            "C_RED": "#8B0000",         # Dark red
            "C_ACCENT": "#512DA8",      # Dark purple
            "C_GROUP": "#5c3f91",       # Dark muted group purple
            "C_BLUE": "#1565C0",        # Dark muted group blue
            "C_BORDER": "#555555",      # Muted dark grey border for non-target masks
            "C_TARGET_BORDER": "#FFFFFF", # Clear white border for target mask
            "C_TEXT": "#E0E0E0",
            "C_YELLOW": "#9E9D24",
            "C_HANDLE_BG": "#1E1E2E",
            "C_WHITE": "#FFFFFF"
        }
    else:
        c_dict = {
            "C_MASK": "#8E4A35",        # Dark muted brick orange/rust
            "C_GREEN": "#2E7D32",       # Medium-dark forest green
            "C_RED": "#8B0000",         # Dark red
            "C_ACCENT": "#512DA8",      # Dark purple
            "C_GROUP": "#5c3f91",       # Dark muted group purple
            "C_BLUE": "#1565C0",        # Dark muted blue
            "C_BORDER": "#555555",      # Muted dark grey border
            "C_TARGET_BORDER": "#1E1E2E",  # Dark border for target mask
            "C_TEXT": "#E0E0E0",
            "C_YELLOW": "#9E9D24",
            "C_HANDLE_BG": "#1E1E2E",
            "C_WHITE": "#FFFFFF"
        }
        
    obj_dict = {}
    for name, hex_str in c_dict.items():
        color = QColor(hex_str)
        obj_dict[name] = color
        obj_dict[f"{name}_PEN_1"] = QPen(color, 1)
        obj_dict[f"{name}_PEN_2"] = QPen(color, 2)
        obj_dict[f"{name}_PEN_1_DOT"] = QPen(color, 1, Qt.DotLine)
        obj_dict[f"{name}_PEN_1_DASH"] = QPen(color, 1, Qt.DashLine)
        obj_dict[f"{name}_PEN_2_DASH"] = QPen(color, 2, Qt.DashLine)
        obj_dict[f"{name}_PEN_2_SOLID"] = QPen(color, 2, Qt.SolidLine)
        obj_dict[f"{name}_BRUSH"] = QBrush(color)
        
        # Add transparent variations
        alpha_155 = QColor(color)
        alpha_155.setAlpha(155)
        obj_dict[f"{name}_ALPHA_155_COLOR"] = alpha_155
        obj_dict[f"{name}_ALPHA_155_BRUSH"] = QBrush(alpha_155)
        
        alpha_110 = QColor(color)
        alpha_110.setAlpha(110)
        obj_dict[f"{name}_ALPHA_110_COLOR"] = alpha_110
        obj_dict[f"{name}_ALPHA_110_BRUSH"] = QBrush(alpha_110)
        
    obj_dict["NO_BRUSH"] = QBrush(Qt.NoBrush)
    _CANVAS_COLORS_CACHE[invert] = obj_dict
    return obj_dict


class CanvasRendererMixin:
    CANVAS_PAINT_PROFILE_ENV = "ANKI_CANVAS_PAINT_PROFILE"
    _LABEL_FONT = QFont("Segoe UI", 12, QFont.Bold)
    _SMALL_FONT = QFont("Segoe UI", 7)

    def _canvas_paint_profile_enabled(self):
        raw = os.environ.get("ANKI_CANVAS_PAINT_PROFILE", "").strip().lower()
        return raw in {"1", "true", "yes", "on"}


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
            f"mask_cache=no "
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
        profile = self._canvas_paint_profile_enabled()
        if profile:
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
        else:
            phases = None

        pages_drawn = 0
        p = QPainter(self)
        clip = event.rect()
        cc = self._get_canvas_colors()

        p.fillRect(clip, _C_BG_CANVAS)

        is_review = (getattr(self, "_mode", "review") == "review")
        is_ultra = is_review and (
            getattr(self, "_ultra_focus_mode", False)
            or (getattr(self, "_focus_mode", False) and getattr(self, "_bg_opacity", 0.2) <= 0.0)
        )

        if is_ultra:
            # Ultra Focus Mode: render underlying page exclusively inside revealed target/peek boxes
            revealed_targets = []
            for i, b in enumerate(self._boxes):
                if (self._is_current_target(i, b) or self._is_peek_target(i, b)) and b.get("revealed", False):
                    sr = self._sr(b["rect"])
                    if clip.intersects(sr.toRect()):
                        revealed_targets.append((i, b, sr))

            if revealed_targets:
                transform_type = Qt.FastTransformation if getattr(self, "_fast_zoom", False) else Qt.SmoothTransformation
                combined_path = QPainterPath()
                for i, b, sr in revealed_targets:
                    ang = b.get("angle", 0.0)
                    shape = b.get("shape", "rect")
                    if ang != 0.0:
                        cx, cy = sr.center().x(), sr.center().y()
                        t = QTransform()
                        t.translate(cx, cy)
                        t.rotate(ang)
                        local_r = QRectF(-sr.width() / 2.0, -sr.height() / 2.0, sr.width(), sr.height())
                        if shape == "ellipse":
                            local_path = QPainterPath()
                            local_path.addEllipse(local_r)
                            combined_path.addPath(t.map(local_path))
                        else:
                            poly = t.map(QPolygonF(local_r))
                            combined_path.addPolygon(poly)
                    else:
                        if shape == "ellipse":
                            combined_path.addEllipse(sr)
                        else:
                            combined_path.addRect(sr)

                p.save()
                p.setClipPath(combined_path)
                p.setOpacity(1.0)

                if self._px and not self._px.isNull():
                    cached_scale, cached_tt, cached_spx = self._spx_cache.get("_px", (None, None, None))
                    if cached_spx is not None:
                        self._spx_cache.move_to_end("_px", last=True)
                    if cached_scale != self._scale or cached_tt != transform_type or cached_spx is None:
                        if profile:
                            phases["scale_miss"] += 1
                            scale_t0 = time.perf_counter()
                        cached_spx = self._px.scaled(
                            max(int(self._px.width() * self._scale), 1),
                            max(int(self._px.height() * self._scale), 1),
                            Qt.KeepAspectRatio,
                            transform_type,
                        )
                        self._spx_cache["_px"] = (self._scale, transform_type, cached_spx)
                        self._spx_cache.move_to_end("_px", last=True)
                        while len(self._spx_cache) > self.SPX_CACHE_MAX:
                            self._spx_cache.popitem(last=False)
                        if profile:
                            phases["page_scale_ms"] += (time.perf_counter() - scale_t0) * 1000.0
                    if profile:
                        draw_t0 = time.perf_counter()
                    p.drawPixmap(0, 0, cached_spx)
                    if profile:
                        phases["page_draw_ms"] += (time.perf_counter() - draw_t0) * 1000.0

                elif self._pages:
                    for i, page_px in enumerate(self._pages):
                        scr_top = int(self._page_tops[i] * self._scale)
                        scr_h = int(page_px.height() * self._scale)
                        scr_bot = scr_top + scr_h

                        if scr_bot < clip.top():
                            continue
                        if scr_top > clip.bottom():
                            break

                        cached_scale, cached_tt, cached_spx = self._spx_cache.get(i, (None, None, None))
                        if cached_spx is not None:
                            self._spx_cache.move_to_end(i, last=True)
                        cache_hit = (
                            cached_scale == self._scale
                            and cached_tt == transform_type
                            and cached_spx is not None
                            and not cached_spx.isNull()
                        )
                        if profile:
                            scale_t0 = time.perf_counter()
                        scaled_page = self._get_scaled_page(i)
                        if profile:
                            phases["page_scale_ms"] += (time.perf_counter() - scale_t0) * 1000.0
                            if not cache_hit:
                                phases["scale_miss"] += 1
                            draw_t0 = time.perf_counter()
                        p.drawPixmap(0, scr_top, scaled_page)
                        if profile:
                            phases["page_draw_ms"] += (time.perf_counter() - draw_t0) * 1000.0
                        pages_drawn += 1

                p.restore()
        else:
            p.save()
            if getattr(self, "_focus_mode", False) and is_review:
                p.setOpacity(getattr(self, "_bg_opacity", 0.2))

            if self._px and not self._px.isNull():
                transform_type = Qt.FastTransformation if getattr(self, "_fast_zoom", False) else Qt.SmoothTransformation
                cached_scale, cached_tt, cached_spx = self._spx_cache.get("_px", (None, None, None))
                if cached_spx is not None:
                    self._spx_cache.move_to_end("_px", last=True)
                if cached_scale != self._scale or cached_tt != transform_type or cached_spx is None:
                    if profile:
                        phases["scale_miss"] += 1
                        scale_t0 = time.perf_counter()
                    cached_spx = self._px.scaled(
                        max(int(self._px.width() * self._scale), 1),
                        max(int(self._px.height() * self._scale), 1),
                        Qt.KeepAspectRatio,
                        transform_type,
                    )
                    self._spx_cache["_px"] = (self._scale, transform_type, cached_spx)
                    self._spx_cache.move_to_end("_px", last=True)
                    while len(self._spx_cache) > self.SPX_CACHE_MAX:
                        self._spx_cache.popitem(last=False)
                    if profile:
                        phases["page_scale_ms"] += (time.perf_counter() - scale_t0) * 1000.0
                if profile:
                    draw_t0 = time.perf_counter()
                p.drawPixmap(0, 0, cached_spx)
                if profile:
                    phases["page_draw_ms"] += (time.perf_counter() - draw_t0) * 1000.0

            elif self._pages:
                for i, page_px in enumerate(self._pages):
                    scr_top = int(self._page_tops[i] * self._scale)
                    scr_h = int(page_px.height() * self._scale)
                    scr_bot = scr_top + scr_h

                    if scr_bot < clip.top():
                        continue
                    if scr_top > clip.bottom():
                        break

                    transform_type = Qt.FastTransformation if getattr(self, "_fast_zoom", False) else Qt.SmoothTransformation
                    cached_scale, cached_tt, cached_spx = self._spx_cache.get(i, (None, None, None))
                    if cached_spx is not None:
                        self._spx_cache.move_to_end(i, last=True)
                    cache_hit = (
                        cached_scale == self._scale
                        and cached_tt == transform_type
                        and cached_spx is not None
                        and not cached_spx.isNull()
                    )
                    if profile:
                        scale_t0 = time.perf_counter()
                    scaled_page = self._get_scaled_page(i)
                    if profile:
                        phases["page_scale_ms"] += (time.perf_counter() - scale_t0) * 1000.0
                        if not cache_hit:
                            phases["scale_miss"] += 1
                        draw_t0 = time.perf_counter()
                    p.drawPixmap(0, scr_top, scaled_page)
                    if profile:
                        phases["page_draw_ms"] += (time.perf_counter() - draw_t0) * 1000.0
                    pages_drawn += 1

                    if i < len(self._pages) - 1:
                        sep_y = scr_bot + int(PAGE_GAP * self._scale) // 2
                        p.setPen(_SEP_PEN)
                        p.drawLine(0, sep_y, self.width(), sep_y)

            p.restore()


        p.setRenderHint(QPainter.Antialiasing)
        if profile:
            boxes_t0 = time.perf_counter()
        for i, b in enumerate(self._boxes):
            if self._drag_op and (
                i == self._selected_idx or i in self._selected_indices
            ):
                continue
            sr = self._sr(b["rect"])
            if not clip.intersects(sr.toRect()):
                continue
            self._draw_box(p, i, b, cc)
            if profile:
                phases["boxes_drawn"] += 1
        if profile:
            phases["boxes_ms"] += (time.perf_counter() - boxes_t0) * 1000.0

        p.setRenderHint(QPainter.Antialiasing)
        if profile:
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
                    self._draw_box_at_rect(p, i, orig_box, live_rect, cc)
        elif self._drag_op and self._selected_idx >= 0:
            self._draw_box(p, self._selected_idx, self._boxes[self._selected_idx], cc)

        if self._drawing and not self._live_rect.isEmpty():
            self._draw_live(p, cc)
        if profile:
            phases["overlay_ms"] += (time.perf_counter() - overlay_t0) * 1000.0

        if profile:
            ink_t0 = time.perf_counter()
        self._draw_ink_layer(p, clip)
        if profile:
            phases["ink_ms"] += (time.perf_counter() - ink_t0) * 1000.0
        p.end()
        
        paint_elapsed_ms = (time.perf_counter() - paint_t0) * 1000.0
        if getattr(self, "_ink_active", False) or getattr(self, "_ink_strokes", None) or getattr(self, "_ink_current", None):
            try:
                from services.pen_profiler import pen_profiler
                pen_profiler.record_paint(
                    duration_ms=paint_elapsed_ms,
                    rect_w=clip.width(),
                    rect_h=clip.height(),
                    stroke_count=len(getattr(self, "_ink_strokes", []) or [])
                )
            except Exception:
                pass

        if profile:
            self._log_canvas_paint_profile(
                paint_elapsed_ms,
                clip,
                pages_drawn,
                phases,
            )

    def _draw_box(self, p: QPainter, i: int, b: dict, cc=None):
        sr = self._sr(b["rect"])
        self._draw_box_impl(p, i, b, sr, cc)

    def _draw_box_at_rect(self, p: QPainter, i: int, b: dict, rect: QRectF, cc=None):
        sr = self._sr(rect)
        self._draw_box_impl(p, i, b, sr, cc)

    def _get_canvas_colors(self):
        from cache_manager import get_pdf_invert_setting
        return _get_canvas_colors_objects(get_pdf_invert_setting())

    def _draw_box_impl(self, p: QPainter, i: int, b: dict, sr: QRectF, cc=None):
        cx, cy = sr.center().x(), sr.center().y()
        ang = b.get("angle", 0.0)
        mask_num = b.get("mask_num") or (i + 1)
        lbl = b.get("label") or f"#{mask_num}"
        shape = b.get("shape", "rect")
        sel = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        local = QRectF(-sr.width() / 2, -sr.height() / 2, sr.width(), sr.height())

        if cc is None:
            cc = self._get_canvas_colors()
        if self._mode == "review":
            revealed = b.get("revealed", False)
            is_target = self._is_current_target(i, b)
            is_peek_target = self._is_peek_target(i, b)
            hide_one = self._review_mode_style == "hide_one"
            is_ultra = (
                getattr(self, "_ultra_focus_mode", False)
                or (getattr(self, "_focus_mode", False) and getattr(self, "_bg_opacity", 0.2) <= 0.0)
            )

            if hide_one and not is_target and not is_peek_target:
                if not revealed and not is_ultra:
                    p.setPen(cc["C_GREEN_PEN_1_DOT"])
                    p.setBrush(cc["NO_BRUSH"])
                    (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
                p.restore()
                return

            if not revealed:
                if is_peek_target:
                    brush = cc["C_RED_BRUSH"]
                    pen = cc["C_TARGET_BORDER_PEN_2"]
                elif is_target:
                    brush = cc["C_GREEN_BRUSH"]
                    pen = cc["C_TARGET_BORDER_PEN_2"]
                else:
                    brush = cc["C_MASK_BRUSH"]
                    pen = cc["C_BORDER_PEN_2"]
                    if is_ultra:
                        brush = QBrush(_C_BG_CANVAS)
                        pen = cc["C_BORDER_PEN_2"]
                    elif getattr(self, "_focus_mode", False) and getattr(self, "_mode", "review") == "review":
                        factor = self._bg_opacity
                        bg = _C_BG_CANVAS
                        def blend(c1, c2, f):
                            return QColor(
                                int(c1.red() * f + c2.red() * (1.0 - f)),
                                int(c1.green() * f + c2.green() * (1.0 - f)),
                                int(c1.blue() * f + c2.blue() * (1.0 - f)),
                                int(c1.alpha() * f + c2.alpha() * (1.0 - f))
                            )
                        b_color = blend(brush.color(), bg, factor)
                        p_color = blend(pen.color(), bg, factor)
                        brush = QBrush(b_color)
                        pen = QPen(p_color, pen.widthF(), pen.style(), pen.capStyle(), pen.joinStyle())

                p.setBrush(brush)
                p.setPen(pen)
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
            else:
                p.setPen(cc["C_RED_PEN_2"] if is_peek_target else cc["C_GREEN_PEN_2"])
                p.setBrush(cc["NO_BRUSH"])
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)
        else:
            gid = b.get("group_id", "")
            grouped = bool(gid)
            if sel:
                brush = cc["C_GREEN_ALPHA_155_BRUSH"]
                pen = cc["C_GREEN_PEN_2_DASH"] if not grouped else cc["C_GREEN_PEN_2_SOLID"]
                pen_text = cc["C_GREEN_PEN_1"]
            elif grouped:
                brush = cc["C_BLUE_ALPHA_155_BRUSH"]
                pen = cc["C_BLUE_PEN_2_DASH"] if not grouped else cc["C_BLUE_PEN_2_SOLID"]
                pen_text = cc["C_BLUE_PEN_1"]
            else:
                brush = cc["C_MASK_ALPHA_155_BRUSH"]
                pen = cc["C_BORDER_PEN_2_DASH"] if not grouped else cc["C_BORDER_PEN_2_SOLID"]
                pen_text = cc["C_BORDER_PEN_1"]

            p.setBrush(brush)
            p.setPen(pen)
            (p.drawEllipse if shape == "ellipse" else p.drawRect)(local)

            if i == getattr(self, "_hovered_box_idx", -1):
                p.save()
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(cc["C_ACCENT_PEN_1"].color(), 2.0, Qt.SolidLine))
                (p.drawEllipse if shape == "ellipse" else p.drawRect)(local.adjusted(-2, -2, 2, 2))
                p.restore()

            p.setFont(self._LABEL_FONT)
            dlbl = (
                f"[{gid[:4]}] {lbl}" if gid and lbl else f"[{gid[:4]}]" if gid else lbl
            )
            # Draw outline/shadow (black)
            p.setPen(QColor("#000000"))
            p.drawText(local.translated(-1, -1), Qt.AlignCenter, dlbl)
            p.drawText(local.translated(1, -1), Qt.AlignCenter, dlbl)
            p.drawText(local.translated(-1, 1), Qt.AlignCenter, dlbl)
            p.drawText(local.translated(1, 1), Qt.AlignCenter, dlbl)
            # Draw main text (white)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(local, Qt.AlignCenter, dlbl)

        p.restore()
        if self._mode == "edit" and (i == self._selected_idx or i == getattr(self, "_hovered_box_idx", -1)):
            self._draw_handles(p, i, cc)

    def _draw_handles(self, p: QPainter, idx: int, cc=None):
        hps = self._handle_positions(idx)
        if not hps:
            return
        if cc is None:
            cc = self._get_canvas_colors()
        
        is_hovered_box = (idx == getattr(self, "_hovered_box_idx", -1))
        hovered_handle = getattr(self, "_hovered_handle_idx", None) if is_hovered_box else None
        
        hr = self._HANDLE_R
        for hi, hpt in enumerate(hps["resize"]):
            p.save()
            if hovered_handle == ("resize", hi):
                p.setPen(QPen(cc["C_ACCENT_PEN_1"].color(), 2.0))
                p.setBrush(cc["C_ACCENT_BRUSH"])
                p.drawEllipse(hpt, hr + 2, hr + 2)
            else:
                p.setPen(cc["C_GREEN_PEN_1"])
                p.setBrush(cc["C_HANDLE_BG_BRUSH"])
                p.drawEllipse(hpt, hr, hr)
            p.restore()

        rpt = hps["rotate"]
        top_c = hps["resize"][1]
        p.setPen(cc["C_ACCENT_PEN_1"])
        p.drawLine(top_c, rpt)
        
        p.save()
        if hovered_handle == ("rotate", -1):
            p.setPen(QPen(cc["C_ACCENT_PEN_1"].color(), 2.0))
            p.setBrush(cc["C_ACCENT_BRUSH"])
            p.drawEllipse(rpt, hr + 3, hr + 3)
        else:
            p.setBrush(cc["C_ACCENT_BRUSH"])
            p.setPen(cc["C_WHITE_PEN_1"])
            p.drawEllipse(rpt, hr + 1, hr + 1)
        p.restore()
        
        p.setFont(self._SMALL_FONT)
        p.setPen(cc["C_WHITE_PEN_1"])
        p.drawText(QRectF(rpt.x() - 6, rpt.y() - 6, 12, 12), Qt.AlignCenter, "↻")

    def _draw_live(self, p: QPainter, cc=None):
        sr = self._sr(self._live_rect)
        if cc is None:
            cc = self._get_canvas_colors()
        p.setBrush(cc["C_ACCENT_ALPHA_110_BRUSH"])
        p.setPen(cc["C_ACCENT_PEN_2_SOLID"])
        (p.drawEllipse if self._tool == "ellipse" else p.drawRect)(sr)

    def _smooth_points_to_path(self, pts, sc) -> QPainterPath:
        from .geometry import smooth_points_to_path
        return smooth_points_to_path(pts, scale=sc)

    def _stroke_to_path(self, stroke, sc) -> QPainterPath:
        pts = stroke[1:]
        if not pts:
            return QPainterPath()
        return self._smooth_points_to_path(pts, sc)

    def _invalidate_ink_layer(self):
        pass

    def _ensure_ink_layer(self):
        pass

    def _draw_ink_layer(self, p: QPainter, clip=None):
        if not self._ink_strokes and not self._ink_current:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pen_w = max(1.0, self._ink_width * self._scale)
        sc = self._scale

        if not hasattr(self, "_ink_path_cache"):
            self._ink_path_cache = {}

        # 1. Draw completed strokes using cached QPainterPath with bounding-box culling
        pad = max(4.0, pen_w + 6.0)
        for stroke in self._ink_strokes:
            if len(stroke) < 2:
                continue
            pts = stroke[1:]
            if not pts:
                continue
            
            # Spatial culling check if clip rect is provided
            if clip is not None:
                bbox = getattr(stroke, "_bbox", None)
                if bbox is None:
                    xs = [pt.x() for pt in pts]
                    ys = [pt.y() for pt in pts]
                    bbox = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                    stroke._bbox = bbox
                sr_bbox = QRectF(
                    bbox.x() * sc - pad,
                    bbox.y() * sc - pad,
                    bbox.width() * sc + 2 * pad,
                    bbox.height() * sc + 2 * pad,
                )
                if not clip.intersects(sr_bbox.toRect()):
                    continue

            color = stroke[0]
            # Cache check by stable key and scale
            stroke_id = stroke.get("_path_key") if hasattr(stroke, "get") else getattr(stroke, "_path_key", None)
            if stroke_id is None:
                stroke_id = id(stroke)
            cached_scale, path = self._ink_path_cache.get(stroke_id, (None, None))
            if cached_scale != sc or path is None:
                path = self._stroke_to_path(stroke, sc)
                self._ink_path_cache[stroke_id] = (sc, path)
                
            p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

        # 2. Draw live stroke segment
        if self._ink_current and len(self._ink_current) >= 2:
            color = self._ink_current[0]
            pts = self._ink_current[1:]
            if pts:
                p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                stable_path = getattr(self, "_ink_current_stable_path", None)
                live_seg = getattr(self, "_ink_live_segment", None)
                drawn = False
                if stable_path is not None and not stable_path.isEmpty():
                    p.drawPath(stable_path)
                    drawn = True
                if live_seg is not None and not live_seg.isEmpty():
                    p.drawPath(live_seg)
                    drawn = True
                if not drawn:
                    if len(pts) == 1:
                        p.drawPoint(QPointF(pts[0].x() * sc, pts[0].y() * sc))
                    else:
                        path = self._smooth_points_to_path(pts, sc)
                        p.drawPath(path)
        p.restore()

    def _redraw(self):
        """Legacy shim — ReviewScreen calls this after revealing a mask."""
        self.update()
