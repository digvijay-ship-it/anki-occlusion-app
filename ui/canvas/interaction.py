from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRect, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPixmap,
    QPainterPath,
    QTransform,
    QCursor,
)

import time
import math
import copy

from cache_manager import PIXMAP_REGISTRY

from .colors import (
    C_BG, C_SURFACE, C_CARD, C_ACCENT, C_GREEN, C_RED, C_YELLOW,
    C_TEXT, C_SUBTEXT, C_BORDER, PAGE_GAP, REVEAL_COLOR
)
from .geometry import _point_in_rotated_box, _point_in_rotated_ellipse


class StrokeList(list):
    def __init__(self, seq=None):
        super().__init__(seq or [])
        self._path_key = None

    def __getitem__(self, key):
        if key == "_path_key":
            return self._path_key
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key == "_path_key":
            self._path_key = value
        else:
            super().__setitem__(key, value)

    def get(self, key, default=None):
        if key == "_path_key":
            return self._path_key if self._path_key is not None else default
        return default


class CanvasInteractionMixin:
    _STYLUS_SUPPRESS_WINDOW_S = 0.35
    _INK_MASK_TAP_THRESHOLD_S = 0.22
    _INK_MASK_DRAG_THRESHOLD_PX = 8

    def event(self, e):
        if e.type() == QEvent.NativeGesture:
            if e.gestureType() == Qt.ZoomNativeGesture:
                self._fast_zoom = True
                self._scale = max(0.05, min(8.0, self._scale * (1.0 + e.value())))
                self._on_zoom()
                self._zoom_timer.start(150)
                return True
        return super().event(e)

    def tabletEvent(self, e):
        # Track recent tablet/stylus activity so review ink can ignore the
        # synthesized mouse events that often follow a pen drag on Windows.
        self._last_tablet_event_time = time.monotonic()
        if e.type() == QEvent.TabletMove:
            self._last_tablet_move_time = time.monotonic()
        if not self._handle_review_tablet_ink(e):
            e.ignore()

    def _tablet_pos(self, e):
        for name in ("posF", "position", "pos"):
            attr = getattr(e, name, None)
            if attr is None:
                continue
            try:
                value = attr()
            except TypeError:
                value = attr
            return QPointF(value)
        return QPointF()

    def _tablet_pressure(self, e) -> float:
        try:
            return float(e.pressure())
        except Exception:
            return 0.0

    def _handle_review_tablet_ink(self, e) -> bool:
        if self._mode != "review" or not self._ink_active or not self.has_content():
            return False

        et = e.type()
        sp = self._tablet_pos(e)
        ip = self._ip(sp)
        pressure = self._tablet_pressure(e)

        if et == QEvent.TabletPress:
            hit = self._hit_box(ip)
            if hit >= 0 and bool(e.modifiers() & Qt.ControlModifier):
                self._ink_pending_mask_idx = hit
                self._ink_pending_press_ip = QPointF(ip)
                self._ink_pending_press_sp = QPointF(sp)
                self._ink_pending_press_time = time.monotonic()
            elif getattr(self, "_ink_mode", "pen") == "eraser":
                self._ink_pre_erase_snapshot = self._clone_ink_strokes(self._ink_strokes)
                self._ink_erasing = True
                self._ink_erase_at(ip)
            else:
                self._ink_press(ip, input_kind="tablet")
            e.accept()
            return True

        if et == QEvent.TabletMove:
            if self._ink_pending_mask_idx >= 0:
                if self._start_pending_mask_ink_if_needed(sp, ip, input_kind="tablet"):
                    e.accept()
                    return True
            if getattr(self, "_ink_mode", "pen") == "eraser":
                if getattr(self, "_ink_erasing", False):
                    self._ink_erase_at(ip)
            elif self._ink_current and getattr(self, "_ink_input_kind", None) == "tablet":
                self._ink_move(ip)
            e.accept()
            return True

        if et == QEvent.TabletRelease:
            if self._ink_pending_mask_idx >= 0:
                elapsed = time.monotonic() - float(self._ink_pending_press_time or 0.0)
                hit = self._ink_pending_mask_idx
                self._clear_pending_ink_mask_action()
                if elapsed <= self._INK_MASK_TAP_THRESHOLD_S and 0 <= hit < len(
                    self._boxes
                ):
                    self._boxes[hit]["revealed"] = not self._boxes[hit]["revealed"]
                    self.update()
            elif getattr(self, "_ink_mode", "pen") == "eraser":
                self._ink_erasing = False
                self._ink_pre_erase_snapshot = None
            elif getattr(self, "_ink_input_kind", None) == "tablet":
                self._ink_release()
            e.accept()
            return True

        return False

    def _is_recent_stylus_mouse_event(self, e) -> bool:
        if getattr(self, "_mode", None) != "review":
            return False
        last_event = float(getattr(self, "_last_tablet_event_time", 0.0) or 0.0)
        last_move = float(getattr(self, "_last_tablet_move_time", 0.0) or 0.0)
        now = time.monotonic()

        # If tablet moves are actively firing (or just finished), suppress all mouse events
        # within the window to avoid echo duplicate strokes.
        if (now - last_move) < self._STYLUS_SUPPRESS_WINDOW_S:
            return True

        # If a tablet event (like TabletPress) just occurred but no moves did,
        # only suppress synthesized events briefly (within 0.1s) to allow fallback.
        if (now - last_event) < 0.1:
            try:
                source = e.source()
            except Exception:
                source = None
            if source != Qt.MouseEventNotSynthesized:
                return True

        return False

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            angle = e.angleDelta().y()
            if angle == 0:
                e.accept()
                return
            self._fast_zoom = True
            factor = max(0.90, min(1.0 + (angle / 120.0) * 0.10, 1.11))
            self._scale = max(0.05, min(8.0, self._scale * factor))
            self._on_zoom()
            self._zoom_timer.start(150)
            e.accept()
        else:
            # Let the surrounding scroll area own normal wheel / touchpad scroll
            # so two-finger scrolling still works while review ink is active.
            e.ignore()
            # Plain scrolling does not change scale or page quality. Starting the
            # smooth timer here clears the scaled-page cache after every scroll
            # pause, which makes the next paint rescale full PDF pages again.

    def _handle_positions(self, idx):
        if not (0 <= idx < len(self._boxes)):
            return None
        b = self._boxes[idx]
        sr = self._sr(b["rect"])
        cx, cy = sr.center().x(), sr.center().y()
        hw, hh = sr.width() / 2, sr.height() / 2
        ang = b.get("angle", 0.0)
        rad = math.radians(ang)
        ca, sa = math.cos(rad), math.sin(rad)

        def rot(dx, dy):
            return QPointF(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)

        handles = [
            rot(-hw, -hh),
            rot(0, -hh),
            rot(hw, -hh),
            rot(-hw, 0),
            rot(hw, 0),
            rot(-hw, hh),
            rot(0, hh),
            rot(hw, hh),
        ]
        return {"resize": handles, "rotate": rot(0, -hh - 24)}

    def _hit_handle(self, sp, idx):
        hps = self._handle_positions(idx)
        if not hps:
            return None
        sp = QPointF(sp)
        r = 14  # Grab tolerance: 14 pixels (up from 6px) to make grabbing easy and lenient
        r2 = r * r
        rot_pt = hps["rotate"]
        if (sp.x() - rot_pt.x())**2 + (sp.y() - rot_pt.y())**2 <= r2:
            return ("rotate", -1)
        for hi, hpt in enumerate(hps["resize"]):
            if (sp.x() - hpt.x())**2 + (sp.y() - hpt.y())**2 <= r2:
                return ("resize", hi)
        return None

    def _find_handle_hit(self, sp):
        if self._selected_idx >= 0:
            hit = self._hit_handle(sp, self._selected_idx)
            if hit:
                return self._selected_idx, hit
        for idx in range(len(self._boxes) - 1, -1, -1):
            if idx == self._selected_idx:
                continue
            hit = self._hit_handle(sp, idx)
            if hit:
                return idx, hit
        return None, None

    def _select_box(self, hit: int, add_to_selection: bool = False, solo: bool = False):
        if hit < 0:
            self._selected_idx = -1
            self._selected_indices = set()
            self._selection_scope = ""
            self.update()
            return
        gid = self._boxes[hit].get("group_id", "")
        if gid and not solo:
            members = {
                i for i, b in enumerate(self._boxes) if b.get("group_id", "") == gid
            }
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
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def _hit_box(self, ip: QPointF):
        for i in range(len(self._boxes) - 1, -1, -1):
            b = self._boxes[i]
            r = b["rect"]
            cx, cy = r.center().x(), r.center().y()
            ang = b.get("angle", 0.0)
            if b.get("shape") == "ellipse":
                if _point_in_rotated_ellipse(
                    ip.x(), ip.y(), cx, cy, r.width() / 2, r.height() / 2, ang
                ):
                    return i
            else:
                if _point_in_rotated_box(
                    ip.x(), ip.y(), cx, cy, r.width(), r.height(), ang
                ):
                    return i
        return -1

    def ink_toggle(self):
        if self._ink_active:
            self._clear_pending_ink_mask_action()
        self._ink_active = not self._ink_active
        if not hasattr(self, "_ink_mode") or not self._ink_mode:
            self._ink_mode = "pen"
        if self._ink_active:
            self._update_ink_cursor()
        else:
            self.setCursor(QCursor(Qt.PointingHandCursor))

    def ink_set_active(self, active: bool, mode: str = None):
        if not active:
            self._clear_pending_ink_mask_action()
        prev = getattr(self, "_ink_active", False)
        self._ink_active = bool(active)
        if mode is not None:
            self._ink_mode = mode
        elif not hasattr(self, "_ink_mode") or not self._ink_mode:
            self._ink_mode = "pen"
        if self._ink_active:
            self._update_ink_cursor()
        else:
            self.setCursor(QCursor(Qt.PointingHandCursor))
        if prev != self._ink_active and hasattr(self, "ink_changed"):
            self.ink_changed.emit()

    def ink_set_mode(self, mode: str):
        self._ink_mode = mode
        if self._ink_active:
            self._update_ink_cursor()
            if mode == "eraser":
                self._show_toast("🧹 Eraser Active")
            else:
                self._show_toast("✏ Pen Active")
        self.update()

    def ink_get_mode(self) -> str:
        return getattr(self, "_ink_mode", "pen")

    def _ink_erase_at(self, ip):
        erased_any = False
        i = len(self._ink_strokes) - 1
        while i >= 0:
            stroke = self._ink_strokes[i]
            pts = stroke[1:]
            
            # Use 15.0 pixels threshold in canvas coordinates for easy erasing
            threshold = 15.0
            close = False
            for pt in pts:
                dx = (ip.x() - pt.x()) * self._scale
                dy = (ip.y() - pt.y()) * self._scale
                if dx * dx + dy * dy < threshold * threshold:
                    close = True
                    break
            
            if close:
                if getattr(self, "_ink_pre_erase_snapshot", None) is not None:
                    if not hasattr(self, "_ink_undo_stack"):
                        self._ink_undo_stack = []
                    if not hasattr(self, "_ink_redo_stack"):
                        self._ink_redo_stack = []
                    self._ink_undo_stack.append(self._ink_pre_erase_snapshot)
                    self._ink_redo_stack.clear()
                    self._ink_pre_erase_snapshot = None

                self._ink_strokes.pop(i)
                if hasattr(self, "_ink_path_cache"):
                    stroke_id = stroke.get("_path_key") if hasattr(stroke, "get") else getattr(stroke, "_path_key", None)
                    if stroke_id is None:
                        stroke_id = id(stroke)
                    self._ink_path_cache.pop(stroke_id, None)
                erased_any = True
            i -= 1
            
        if erased_any:
            self._invalidate_ink_layer()
            self.repaint()

    def ink_cycle_color(self):
        self._ink_color_idx = (self._ink_color_idx + 1) % len(self._ink_colors)
        self._show_toast(f"✏ Ink: {self._ink_colors[self._ink_color_idx]}")

    def ink_adjust_width(self, delta: float):
        self._ink_width = max(0.4, min(12.0, float(self._ink_width) + float(delta)))
        if self._ink_active:
            self._update_ink_cursor()
        self.update()
        self._show_toast(f"Ink size: {self._ink_width:.1f}")

    def ink_clear(self):
        if self._ink_strokes:
            self._push_ink_undo()
        self._ink_strokes.clear()
        self._ink_current.clear()
        if hasattr(self, "_ink_path_cache"):
            self._ink_path_cache.clear()
        self._invalidate_ink_layer()
        self._clear_pending_ink_mask_action()
        self.update()
        self._show_toast("🧹 Ink cleared")

    def clear_review_ink_for_card_switch(self):
        had_ink = bool(self._ink_strokes or self._ink_current)
        self._ink_strokes.clear()
        self._ink_current.clear()
        if hasattr(self, "_ink_path_cache"):
            self._ink_path_cache.clear()
        self._invalidate_ink_layer()
        self._ink_input_kind = None
        self._clear_pending_ink_mask_action()
        if hasattr(self, "_ink_undo_stack"):
            self._ink_undo_stack.clear()
        if hasattr(self, "_ink_redo_stack"):
            self._ink_redo_stack.clear()
        self._ink_pre_erase_snapshot = None
        if had_ink:
            self.update()

    def _clone_ink_strokes(self, strokes):
        cloned = []
        for stroke in strokes:
            new_stroke = StrokeList()
            new_stroke._path_key = getattr(stroke, "_path_key", None)
            new_stroke._implementation = getattr(stroke, "_implementation", "filtered")
            new_stroke._bbox = getattr(stroke, "_bbox", None)
            for item in stroke:
                if isinstance(item, QColor):
                    new_stroke.append(QColor(item))
                elif isinstance(item, QPointF):
                    new_stroke.append(QPointF(item))
                else:
                    try:
                        new_stroke.append(copy.copy(item))
                    except Exception:
                        new_stroke.append(item)
            cloned.append(new_stroke)
        return cloned

    def _push_ink_undo(self):
        if not hasattr(self, "_ink_undo_stack"):
            self._ink_undo_stack = []
        if not hasattr(self, "_ink_redo_stack"):
            self._ink_redo_stack = []
        self._ink_undo_stack.append(self._clone_ink_strokes(self._ink_strokes))
        self._ink_redo_stack.clear()

    def has_ink_undo(self) -> bool:
        return bool(getattr(self, "_ink_undo_stack", None))

    def has_ink_redo(self) -> bool:
        return bool(getattr(self, "_ink_redo_stack", None))

    def ink_undo_stroke(self):
        if self.has_ink_undo():
            if not hasattr(self, "_ink_redo_stack"):
                self._ink_redo_stack = []
            self._ink_redo_stack.append(self._clone_ink_strokes(self._ink_strokes))
            self._ink_strokes = self._ink_undo_stack.pop()
            if hasattr(self, "_ink_path_cache"):
                self._ink_path_cache.clear()
            self._invalidate_ink_layer()
            self.update()

    def ink_redo_stroke(self):
        if self.has_ink_redo():
            if not hasattr(self, "_ink_undo_stack"):
                self._ink_undo_stack = []
            self._ink_undo_stack.append(self._clone_ink_strokes(self._ink_strokes))
            self._ink_strokes = self._ink_redo_stack.pop()
            if hasattr(self, "_ink_path_cache"):
                self._ink_path_cache.clear()
            self._invalidate_ink_layer()
            self.update()

    @property
    def _ink_pen_color(self):
        return QColor(self._ink_colors[self._ink_color_idx])

    def _ink_press(self, ip, input_kind="mouse"):
        self._ink_current = [self._ink_pen_color, ip]
        self._ink_input_kind = input_kind
        
        # Reset incremental path caches
        self._ink_current_stable_path = QPainterPath()
        self._ink_current_path = QPainterPath()
        self._ink_live_segment = None
        sc = self._scale
        p0 = QPointF(ip.x() * sc, ip.y() * sc)
        self._ink_last_mid = p0
        self._ink_current_stable_path.moveTo(p0)
        self._ink_current_path.moveTo(p0)

    def _ink_move(self, ip):
        if not self._ink_current:
            return
        
        # Distance filter for "filtered" mode
        impl = getattr(self, "_ink_implementation", "filtered")
        if impl == "filtered":
            last_ip = self._ink_current[-1]
            dx = ip.x() - last_ip.x()
            dy = ip.y() - last_ip.y()
            if dx * dx + dy * dy < 2.25:  # 1.5 pixels threshold -> squared distance is 2.25
                return

        self._ink_current.append(ip)
        sc = self._scale
        pen_w = max(1.0, self._ink_width * sc)
        pen_pad = max(2.0, pen_w) + 8  # generous AA padding
        
        # Incremental path building for non-classic modes
        if impl != "classic":
            p_new = QPointF(ip.x() * sc, ip.y() * sc)
            if impl in ("incremental", "filtered"):
                pts_count = len(self._ink_current) - 1
                if pts_count == 2:
                    p0 = QPointF(self._ink_current[1].x() * sc, self._ink_current[1].y() * sc)
                    p1 = p_new
                    mid = QPointF((p0.x() + p1.x()) / 2.0, (p0.y() + p1.y()) / 2.0)
                    
                    seg = QPainterPath()
                    seg.moveTo(p0)
                    seg.lineTo(mid)
                    seg.lineTo(p1)
                    self._ink_live_segment = seg
                    self._ink_last_mid = mid
                    
                    self._ink_current_stable_path = QPainterPath()
                    self._ink_current_stable_path.moveTo(p0)
                    self._ink_current_stable_path.lineTo(mid)
                    self._ink_current_path = seg
                    
                    xs = [p0.x(), mid.x(), p1.x()]
                    ys = [p0.y(), mid.y(), p1.y()]
                    dirty = QRect(
                        int(math.floor(min(xs) - pen_pad)),
                        int(math.floor(min(ys) - pen_pad)),
                        int(math.ceil(max(xs) - min(xs) + 2 * pen_pad)),
                        int(math.ceil(max(ys) - min(ys) + 2 * pen_pad)),
                    )
                    self.update(dirty)
                    return
                elif pts_count >= 3:
                    p_prev = QPointF(self._ink_current[-2].x() * sc, self._ink_current[-2].y() * sc)
                    p_curr = p_new
                    mid = QPointF((p_prev.x() + p_curr.x()) / 2.0, (p_prev.y() + p_curr.y()) / 2.0)
                    
                    seg = QPainterPath()
                    seg.moveTo(mid)
                    seg.lineTo(p_curr)
                    self._ink_live_segment = seg
                    
                    xs = [self._ink_last_mid.x(), p_prev.x(), mid.x(), p_curr.x()]
                    ys = [self._ink_last_mid.y(), p_prev.y(), mid.y(), p_curr.y()]
                    self._ink_last_mid = mid
                    
                    self._ink_current_stable_path.quadTo(p_prev, mid)
                    self._ink_current_path = seg
                    
                    dirty = QRect(
                        int(math.floor(min(xs) - pen_pad)),
                        int(math.floor(min(ys) - pen_pad)),
                        int(math.ceil(max(xs) - min(xs) + 2 * pen_pad)),
                        int(math.ceil(max(ys) - min(ys) + 2 * pen_pad)),
                    )
                    self.update(dirty)
                    return
            elif impl == "polyline":
                self._ink_current_path.lineTo(p_new)

        pts = self._ink_current[1:]
        if len(pts) >= 2:
            p0, p1 = pts[-2], pts[-1]
            x0 = math.floor(min(p0.x(), p1.x()) * sc - pen_pad)
            y0 = math.floor(min(p0.y(), p1.y()) * sc - pen_pad)
            x1 = math.ceil(max(p0.x(), p1.x()) * sc + pen_pad)
            y1 = math.ceil(max(p0.y(), p1.y()) * sc + pen_pad)
            self.update(QRect(x0, y0, x1 - x0, y1 - y0))
        else:
            self.update()

    def _ink_release(self):
        if len(self._ink_current) >= 2:
            self._push_ink_undo()
            if not hasattr(self, "_stroke_seq"):
                self._stroke_seq = 0
            self._stroke_seq += 1
            stroke = StrokeList(self._ink_current)
            stroke._path_key = self._stroke_seq
            stroke._implementation = getattr(self, "_ink_implementation", "filtered")
            pts = self._ink_current[1:]  # skip color element
            if pts:
                xs = [pt.x() for pt in pts]
                ys = [pt.y() for pt in pts]
                stroke._bbox = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                self._ink_strokes.append(stroke)
                
                sc = self._scale
                pen_w = max(1.0, self._ink_width * sc)
                pen_pad = max(2.0, pen_w) + 10
                
                self._ink_current = []
                self._ink_live_segment = None
                self._ink_current_stable_path = QPainterPath()
                self._ink_current_path = QPainterPath()
                self._ink_last_mid = None
                self._ink_input_kind = None
                
                sc_xs = [pt.x() * sc for pt in pts]
                sc_ys = [pt.y() * sc for pt in pts]
                dirty = QRect(
                    int(math.floor(min(sc_xs) - pen_pad)),
                    int(math.floor(min(sc_ys) - pen_pad)),
                    int(math.ceil(max(sc_xs) - min(sc_xs) + 2 * pen_pad)),
                    int(math.ceil(max(sc_ys) - min(sc_ys) + 2 * pen_pad)),
                )
                self.update(dirty)
                return
            self._ink_strokes.append(stroke)
        self._ink_current = []
        self._ink_live_segment = None
        self._ink_last_mid = None
        self._ink_input_kind = None
        self.update()

    def _clear_pending_ink_mask_action(self):
        self._ink_pending_mask_idx = -1
        self._ink_pending_press_ip = None
        self._ink_pending_press_sp = None
        self._ink_pending_press_time = 0.0

    def _start_pending_mask_ink_if_needed(self, sp, ip, input_kind="mouse"):
        if (
            self._ink_pending_mask_idx < 0
            or self._ink_pending_press_sp is None
            or self._ink_pending_press_ip is None
        ):
            return False
        elapsed = time.monotonic() - float(self._ink_pending_press_time or 0.0)
        moved = (QPointF(sp) - QPointF(self._ink_pending_press_sp)).manhattanLength()
        if (
            moved < self._INK_MASK_DRAG_THRESHOLD_PX
            and elapsed < self._INK_MASK_TAP_THRESHOLD_S
        ):
            return False
        start_ip = QPointF(self._ink_pending_press_ip)
        mask_idx = self._ink_pending_mask_idx
        self._clear_pending_ink_mask_action()
        self._ink_press(start_ip, input_kind=input_kind)
        if QPointF(ip) != start_ip:
            self._ink_move(ip)
        return True

    def _scroll_area(self):
        w = self.parent()
        while w and not hasattr(w, "pan_mode"):
            w = w.parent()
        return w

    def mousePressEvent(self, e):
        if not self.has_content():
            return
        sc = self._scroll_area()
        if sc and (sc.pan_mode or e.button() == Qt.MiddleButton):
            e.ignore()
            return

        self.setFocus()
        sp = QPointF(e.pos())
        ip = self._ip(e.pos())
        mods = e.modifiers()
        stylus_like = self._is_recent_stylus_mouse_event(e)

        if self._mode == "review" and e.button() == Qt.LeftButton:
            if self._ink_active and stylus_like:
                e.accept()
                return
            if self._ink_active:
                hit = self._hit_box(ip)
                if hit >= 0 and bool(mods & Qt.ControlModifier):
                    self._ink_pending_mask_idx = hit
                    self._ink_pending_press_ip = QPointF(ip)
                    self._ink_pending_press_sp = QPointF(sp)
                    self._ink_pending_press_time = time.monotonic()
                    e.accept()
                    return
                if getattr(self, "_ink_mode", "pen") == "eraser":
                    self._ink_pre_erase_snapshot = self._clone_ink_strokes(self._ink_strokes)
                    self._ink_erasing = True
                    self._ink_erase_at(ip)
                else:
                    self._ink_press(ip)
                e.accept()
                return
            hit = self._hit_box(ip)
            if hit >= 0:
                self._boxes[hit]["revealed"] = not self._boxes[hit]["revealed"]
                self.update()
                return
            e.ignore()
            return

        if self._mode == "review" and e.button() == Qt.RightButton:
            hit = self._hit_box(ip)
            if hit >= 0:
                self.right_clicked_box.emit(hit, e.globalPos())
                e.accept()
                return
            self.right_clicked.emit()
            return

        if self._mode != "edit" or e.button() != Qt.LeftButton:
            return

        idx, hit_h = self._find_handle_hit(sp)
        if idx is not None and hit_h:
            if self._selected_idx != idx:
                self._select_box(idx)
            op, hi = hit_h
            self._drag_op = op
            self._drag_handle = hi
            self._drag_start_pos = sp
            self._drag_orig_box = self._clone_box(self._boxes[idx])
            self._push_undo()
            return

        hit = self._hit_box(ip)
        if hit >= 0:
            if self._selection_scope and hit in self._selected_indices:
                self._selected_idx = hit
                self.update()
            else:
                self._selection_scope = ""
                # solo=True on plain click — move single box even inside a group
                is_plain_click = not bool(mods & Qt.ControlModifier)
                self._select_box(
                    hit,
                    add_to_selection=bool(mods & Qt.ControlModifier),
                    solo=is_plain_click,
                )
            self._drag_op = "move"
            self._drag_start_pos = sp
            selected = self._get_all_selected()
            if not selected:
                selected = [hit]
            self._drag_orig_boxes = {i: self._clone_box(self._boxes[i]) for i in selected}
            self._drag_orig_box = self._clone_box(self._boxes[hit])
            self._push_undo()
            return

        if self._tool != "select":
            self._select_box(-1)
            self._drawing = True
            self._start = ip
            self._live_rect = QRectF()
            self.update()

    def mouseMoveEvent(self, e):
        sp = QPointF(e.pos())
        ip = self._ip(e.pos())
        stylus_like = self._is_recent_stylus_mouse_event(e)
        if self._mode == "review" and self._ink_active and stylus_like:
            e.accept()
            return
        if (
            self._mode == "review"
            and self._ink_active
            and self._ink_pending_mask_idx >= 0
        ):
            if self._start_pending_mask_ink_if_needed(sp, ip):
                e.accept()
                return
        if (
            self._mode == "review"
            and self._ink_active
            and getattr(self, "_ink_mode", "pen") == "eraser"
        ):
            if getattr(self, "_ink_erasing", False):
                self._ink_erase_at(ip)
                e.accept()
                return
        if (
            self._mode == "review"
            and self._ink_active
            and self._ink_current
        ):
            # Fallback to mouse drawing if we are in tablet mode but not receiving tablet moves
            if getattr(self, "_ink_input_kind", None) == "tablet":
                last_move = float(getattr(self, "_last_tablet_move_time", 0.0) or 0.0)
                if (time.monotonic() - last_move) > 0.1:
                    self._ink_input_kind = "mouse"

            if getattr(self, "_ink_input_kind", None) == "mouse":
                self._ink_move(ip)
                e.accept()
                return

        sc = self.parent()
        while sc and not hasattr(sc, "_pan_active"):
            sc = sc.parent()
        if sc and sc._pan_active:
            e.ignore()
            return

        self._drag_current_pos = sp

        if self._drawing:
            x0, y0 = self._start.x(), self._start.y()
            x1, y1 = ip.x(), ip.y()
            old_rect = self._live_rect
            self._live_rect = QRectF(
                min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
            )
            # ⚡ FIX: Only repaint the union of old and new live_rect — not full canvas
            dirty = (
                self._sr(self._live_rect)
                .united(self._sr(old_rect))
                .adjusted(-4, -4, 4, 4)
            )
            self.update(dirty.toRect())
            return

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
                    orig_box["rect"].height(),
                )
                self._boxes[i]["rect"] = new_rect
                new_sr = self._sr(new_rect)
                box_dirty = old_sr.united(new_sr).adjusted(-20, -20, 20, 20)
                dirty = box_dirty if dirty is None else dirty.united(box_dirty)

            if dirty is None:
                dirty = self.rect()

            # ⚡ FIX: Only repaint union of old+new box position + handle padding
            self.update(dirty.toRect())
            return

        if self._drag_op == "resize" and self._selected_idx >= 0:
            self._do_resize(sp)
            return

        if self._drag_op == "rotate" and self._selected_idx >= 0:
            b = self._boxes[self._selected_idx]
            sr = self._sr(b["rect"])
            cx, cy = sr.center().x(), sr.center().y()
            b["angle"] = round(
                math.degrees(math.atan2(sp.y() - cy, sp.x() - cx)) + 90, 1
            )
            # ⚡ FIX: Only repaint the rotating box area + rotate handle overhead
            dirty = sr.adjusted(-40, -40, 40, 40)
            self.update(dirty.toRect())
            return

        self._update_cursor_for_position(e.pos())

    def mouseReleaseEvent(self, e):
        stylus_like = self._is_recent_stylus_mouse_event(e)
        if (
            self._mode == "review"
            and self._ink_active
            and e.button() == Qt.LeftButton
            and stylus_like
        ):
            e.accept()
            return
        if (
            self._mode == "review"
            and self._ink_active
            and e.button() == Qt.LeftButton
            and self._ink_pending_mask_idx >= 0
        ):
            elapsed = time.monotonic() - float(self._ink_pending_press_time or 0.0)
            hit = self._ink_pending_mask_idx
            self._clear_pending_ink_mask_action()
            if elapsed <= self._INK_MASK_TAP_THRESHOLD_S and 0 <= hit < len(
                self._boxes
            ):
                self._boxes[hit]["revealed"] = not self._boxes[hit]["revealed"]
                self.update()
            e.accept()
            return
        if (
            self._mode == "review"
            and self._ink_active
            and e.button() == Qt.LeftButton
        ):
            if getattr(self, "_ink_mode", "pen") == "eraser":
                self._ink_erasing = False
                self._ink_pre_erase_snapshot = None
                e.accept()
                return
            elif getattr(self, "_ink_input_kind", None) == "mouse":
                self._ink_release()
                e.accept()
                return

        if self._drawing and e.button() == Qt.LeftButton:
            self._drawing = False
            r = self._live_rect
            if r.width() > 6 and r.height() > 6:
                self._push_undo()
                new_box = {
                    "rect": r,
                    "shape": (
                        self._tool if self._tool in ("rect", "ellipse") else "rect"
                    ),
                    "angle": 0.0,
                    "revealed": False,
                    "label": "",
                }
                self._update_box_page_num(new_box)
                self._boxes.append(new_box)
                self._selected_idx = len(self._boxes) - 1
                self.update()
                self.boxes_changed.emit(self.get_boxes())
            self._live_rect = QRectF()
            self.update()

        if self._drag_op:
            if self._drag_op in ("move", "resize"):
                if self._selected_idx >= 0 and self._selected_idx < len(self._boxes):
                    self._update_box_page_num(self._boxes[self._selected_idx])
                if self._drag_orig_boxes:
                    for i in self._drag_orig_boxes:
                        if i >= 0 and i < len(self._boxes):
                            self._update_box_page_num(self._boxes[i])
            self._drag_op = None
            self._drag_handle = -1
            self._drag_orig_box = None
            self._drag_orig_boxes = None
            self._drag_current_pos = None
            self.boxes_changed.emit(self.get_boxes())
            self.update()
            self._update_cursor_for_position(e.pos())

    def focusOutEvent(self, e):
        if getattr(self, "_mode", None) == "review" and getattr(self, "_ink_active", False):
            if getattr(self, "_ink_current", None):
                self._ink_release()
            self._ink_erasing = False
            self._ink_pre_erase_snapshot = None
            self._clear_pending_ink_mask_action()
        if getattr(self, "_drawing", False):
            self._drawing = False
        super().focusOutEvent(e)

    def _do_resize(self, sp: QPointF):
        idx = self._selected_idx
        b = self._boxes[idx]
        orig = self._drag_orig_box
        hi = self._drag_handle
        delta = (sp - self._drag_start_pos) / self._scale
        ang = orig.get("angle", 0.0)
        rad = math.radians(-ang)
        ca, sa = math.cos(rad), math.sin(rad)
        ldx = delta.x() * ca - delta.y() * sa
        ldy = delta.x() * sa + delta.y() * ca
        r = orig["rect"]
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        nx, ny, nw, nh = x, y, w, h
        if hi in (0, 3, 5):
            nx = x + ldx
            nw = max(10, w - ldx)
        if hi in (2, 4, 7):
            nw = max(10, w + ldx)
        if hi in (0, 1, 2):
            ny = y + ldy
            nh = max(10, h - ldy)
        if hi in (5, 6, 7):
            nh = max(10, h + ldy)
        old_sr = self._sr(b["rect"])
        b["rect"] = QRectF(nx, ny, nw, nh)
        b["angle"] = ang
        new_sr = self._sr(b["rect"])
        dirty = old_sr.united(new_sr).adjusted(-30, -30, 30, 30)
        self.update(dirty.toRect())

    def keyPressEvent(self, e):
        mods = e.modifiers()
        key = e.key()
        if self._mode == "review":
            parent = self.parent()
            while parent is not None:
                if parent.__class__.__name__ == "ReviewScreen":
                    parent.keyPressEvent(e)
                    return
                parent = parent.parent()
            e.ignore()
            return
        if key == Qt.Key_Delete:
            self.delete_selected_boxes()
        elif mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:
            self.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_A:
            if mods & Qt.AltModifier:
                self.select_all_on_pdf()
            elif mods & Qt.ShiftModifier:
                self.select_all_in_view()
            else:
                self.select_visible_only()
        elif key == Qt.Key_G and not (mods & Qt.ControlModifier):
            (
                self.ungroup_selected()
                if mods & Qt.ShiftModifier
                else self.group_selected()
            )
        else:
            super().keyPressEvent(e)

    def leaveEvent(self, e):
        self._ink_erasing = False
        self._ink_pre_erase_snapshot = None
        self._hovered_box_idx = -1
        self._hovered_handle_idx = None
        self.update()
        sc = self.parent()
        while sc and not hasattr(sc, "_pan_active"):
            sc = sc.parent()
        if sc and sc._pan_active:
            sc._pan_active = False
            sc._pan_start_pos = None
            sc._is_actually_panning = False
            sc._clear_pan_cursor()
        super().leaveEvent(e)

    def enterEvent(self, e):
        super().enterEvent(e)
        if getattr(self, "_ink_active", False):
            self._update_ink_cursor()

    def _update_ink_cursor(self):
        if not getattr(self, "_ink_active", False):
            return
            
        mode = getattr(self, "_ink_mode", "pen")
        if mode == "eraser":
            w = 24
        else:
            w = max(4, min(8, int(self._ink_width * getattr(self, "_scale", 1.0))))
            
        # Add a margin of 10 pixels around the shape to fit the crosshair lines cleanly
        margin = 10
        pix_size = w + 2 * margin
        pix = QPixmap(pix_size, pix_size)
        pix.fill(Qt.transparent)
        
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        
        cx = margin + w // 2
        cy = margin + w // 2
        r = w // 2
        gap = 2
        length = 6
        
        # Draw a white outline (width 3) for the entire cursor (circle/rect and crosshairs)
        painter.setPen(QPen(Qt.white, 3))
        if mode == "eraser":
            painter.drawRect(margin, margin, w, w)
        else:
            painter.drawEllipse(margin, margin, w, w)
        # White crosshair lines
        painter.drawLine(cx - r - gap - length, cy, cx - r - gap, cy)
        painter.drawLine(cx + r + gap, cy, cx + r + gap + length, cy)
        painter.drawLine(cx, cy - r - gap - length, cx, cy - r - gap)
        painter.drawLine(cx, cy + r + gap, cx, cy + r + gap + length)
            
        # Draw a black inner line (width 1) for contrast on light backgrounds
        painter.setPen(QPen(Qt.black, 1))
        if mode == "eraser":
            painter.drawRect(margin, margin, w, w)
        else:
            painter.drawEllipse(margin, margin, w, w)
        # Black crosshair lines
        painter.drawLine(cx - r - gap - length, cy, cx - r - gap, cy)
        painter.drawLine(cx + r + gap, cy, cx + r + gap + length, cy)
        painter.drawLine(cx, cy - r - gap - length, cx, cy - r - gap)
        painter.drawLine(cx, cy + r + gap, cx, cy + r + gap + length)
            
        painter.end()
        
        # Center the cursor hot spot exactly
        self.setCursor(QCursor(pix, cx, cy))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_invalidate_ink_layer"):
            self._invalidate_ink_layer()

    def _update_cursor_for_position(self, pos):
        if getattr(self, "_ink_active", False):
            self._update_ink_cursor()
            return
        if self._mode == "edit":
            drag_op = getattr(self, "_drag_op", None)
            old_box = getattr(self, "_hovered_box_idx", -1)
            old_handle = getattr(self, "_hovered_handle_idx", None)

            if drag_op == "resize":
                hi = getattr(self, "_drag_handle", -1)
                self._hovered_box_idx = self._selected_idx
                self._hovered_handle_idx = ("resize", hi)
                if hi in (0, 7):
                    self.setCursor(QCursor(Qt.SizeFDiagCursor))
                elif hi in (2, 5):
                    self.setCursor(QCursor(Qt.SizeBDiagCursor))
                elif hi in (1, 6):
                    self.setCursor(QCursor(Qt.SizeVerCursor))
                elif hi in (3, 4):
                    self.setCursor(QCursor(Qt.SizeHorCursor))
                if self._hovered_box_idx != old_box or self._hovered_handle_idx != old_handle:
                    self.update()
                return
            elif drag_op == "move":
                self._hovered_box_idx = -1
                self._hovered_handle_idx = None
                self.setCursor(QCursor(Qt.SizeAllCursor))
                if self._hovered_box_idx != old_box or self._hovered_handle_idx != old_handle:
                    self.update()
                return
            elif drag_op == "rotate":
                self._hovered_box_idx = self._selected_idx
                self._hovered_handle_idx = ("rotate", -1)
                self.setCursor(QCursor(Qt.PointingHandCursor))
                if self._hovered_box_idx != old_box or self._hovered_handle_idx != old_handle:
                    self.update()
                return

            sp = QPointF(pos)
            ip = self._ip(pos)
            idx, handle_hit = self._find_handle_hit(sp)
            self._hovered_box_idx = idx if idx is not None else -1
            self._hovered_handle_idx = handle_hit

            if self._hovered_box_idx != old_box or self._hovered_handle_idx != old_handle:
                self.update()

            if handle_hit:
                op, hi = handle_hit
                if op == "rotate":
                    self.setCursor(QCursor(Qt.PointingHandCursor))
                elif op == "resize":
                    if hi in (0, 7):
                        self.setCursor(QCursor(Qt.SizeFDiagCursor))
                    elif hi in (2, 5):
                        self.setCursor(QCursor(Qt.SizeBDiagCursor))
                    elif hi in (1, 6):
                        self.setCursor(QCursor(Qt.SizeVerCursor))
                    elif hi in (3, 4):
                        self.setCursor(QCursor(Qt.SizeHorCursor))
            else:
                if self._tool == "select":
                    hit_box = self._hit_box(ip)
                    if hit_box >= 0 and (hit_box == self._selected_idx or hit_box in getattr(self, "_selected_indices", set())):
                        self.setCursor(QCursor(Qt.SizeAllCursor))
                    else:
                        self.setCursor(QCursor(Qt.ArrowCursor))
                elif self._tool in ("rect", "ellipse"):
                    self.setCursor(QCursor(Qt.CrossCursor))
