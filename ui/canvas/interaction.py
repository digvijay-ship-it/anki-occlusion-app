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


class CanvasInteractionMixin:
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

    def _select_box(self, hit: int, add_to_selection: bool = False, solo: bool = False):
        if hit < 0:
            self._selected_idx = -1; self._selected_indices = set()
            self._selection_scope = ""
            self._invalidate_mask_cache(); self.update(); return
        gid = self._boxes[hit].get("group_id","")
        if gid and not solo:
            members = {i for i,b in enumerate(self._boxes)
                       if b.get("group_id","") == gid}
            if add_to_selection:
                # Keep existing selection, add previous _selected_idx too
                if self._selected_idx >= 0:
                    self._selected_indices.add(self._selected_idx)
                self._selected_indices |= members
            else:
                self._selected_indices = members
        else:
            if add_to_selection:
                # Keep existing selection, add previous _selected_idx too
                if self._selected_idx >= 0:
                    self._selected_indices.add(self._selected_idx)
                self._selected_indices.add(hit)
            else:
                self._selected_indices = set()
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

    def _ink_press(self, ip):   self._ink_current = [self._ink_pen_color, ip]

    def _ink_move(self, ip):
        if not self._ink_current:
            return
        self._ink_current.append(ip)
        # ⚡ FIX: Only repaint the tiny bounding rect of the last segment,
        # not the entire canvas. This is the primary cause of pen lag —
        # a full-canvas update() on every mouseMoveEvent is 10–50x more work
        # than needed. A 2-point segment bbox is typically <50×50px.
        pts = self._ink_current[1:]
        if len(pts) >= 2:
            p0, p1 = pts[-2], pts[-1]
            pen_w = max(2.0, self._ink_width * self._scale) + 4  # padding
            x0 = int(min(p0.x(), p1.x()) * self._scale - pen_w)
            y0 = int(min(p0.y(), p1.y()) * self._scale - pen_w)
            x1 = int(max(p0.x(), p1.x()) * self._scale + pen_w)
            y1 = int(max(p0.y(), p1.y()) * self._scale + pen_w)
            from PyQt5.QtCore import QRect
            self.update(QRect(x0, y0, x1 - x0, y1 - y0))
        else:
            self.update()

    def _ink_release(self):
        if len(self._ink_current) >= 2: self._ink_strokes.append(list(self._ink_current))
        self._ink_current = []; self.update()

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

        if self._mode == "review" and e.button() == Qt.RightButton:
            self.right_clicked.emit(); return

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
            if self._selection_scope and hit in self._selected_indices:
                self._selected_idx = hit
                self._invalidate_mask_cache()
                self.update()
            else:
                self._selection_scope = ""
                # solo=True on plain click — move single box even inside a group
                is_plain_click = not bool(mods & Qt.ControlModifier)
                self._select_box(hit, add_to_selection=bool(mods & Qt.ControlModifier),
                                 solo=is_plain_click)
            self._drag_op = "move"; self._drag_start_pos = sp
            selected = self._get_all_selected()
            if not selected:
                selected = [hit]
            self._drag_orig_boxes = {i: copy.deepcopy(self._boxes[i]) for i in selected}
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
        self._drag_current_pos = sp

        if self._drawing:
            x0,y0 = self._start.x(), self._start.y()
            x1,y1 = ip.x(), ip.y()
            old_rect = self._live_rect
            self._live_rect = QRectF(min(x0,x1),min(y0,y1),abs(x1-x0),abs(y1-y0))
            # ⚡ FIX: Only repaint the union of old and new live_rect — not full canvas
            dirty = self._sr(self._live_rect).united(self._sr(old_rect)).adjusted(-4,-4,4,4)
            self.update(dirty.toRect()); return

        if self._drag_op == "move" and self._selected_idx >= 0:
            delta = (sp - self._drag_start_pos) / self._scale
            orig_map = self._drag_orig_boxes or {}
            if not orig_map:
                return

            dirty = None
            for i, orig_box in orig_map.items():
                old_sr = self._sr(orig_box["rect"])
                new_rect = QRectF(
                    orig_box["rect"].x() + delta.x(),
                    orig_box["rect"].y() + delta.y(),
                    orig_box["rect"].width(),
                    orig_box["rect"].height())
                self._boxes[i]["rect"] = new_rect
                new_sr = self._sr(new_rect)
                box_dirty = old_sr.united(new_sr).adjusted(-20, -20, 20, 20)
                dirty = box_dirty if dirty is None else dirty.united(box_dirty)

            if dirty is None:
                dirty = self.rect()

            # ⚡ FIX: Only repaint union of old+new box position + handle padding
            self.update(dirty.toRect()); return

        if self._drag_op == "resize" and self._selected_idx >= 0:
            self._do_resize(sp); return

        if self._drag_op == "rotate" and self._selected_idx >= 0:
            b  = self._boxes[self._selected_idx]
            sr = self._sr(b["rect"])
            cx, cy = sr.center().x(), sr.center().y()
            b["angle"] = round(math.degrees(math.atan2(sp.y()-cy, sp.x()-cx))+90, 1)
            # ⚡ FIX: Only repaint the rotating box area + rotate handle overhead
            dirty = sr.adjusted(-40, -40, 40, 40)
            self.update(dirty.toRect()); return

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
            self._drag_op = None; self._drag_handle = -1; self._drag_orig_box = None; self._drag_orig_boxes = None; self._drag_current_pos = None
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
        elif mods & Qt.ControlModifier and key == Qt.Key_X:    self.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_A:
            if mods & Qt.AltModifier:
                self.select_all_on_pdf()
            elif mods & Qt.ShiftModifier:
                self.select_all_in_view()
            else:
                self.select_visible_only()
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

