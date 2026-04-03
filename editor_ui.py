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
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal, QSize, QEvent, QFileSystemWatcher
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap, QFont, QCursor, QBrush

from sm2_engine import sm2_init
from pdf_engine import PDF_SUPPORT, PdfLoaderThread, PAGE_CACHE, pdf_page_to_pixmap, pdf_to_combined_pixmap
from data_manager import new_box_id

C_GREEN   = "#50FA7B"
C_MASK    = "#F7916A"
C_ACCENT  = "#7C6AF7"
C_YELLOW  = "#F1FA8C"


class OcclusionCanvas(QLabel):
    boxes_changed = pyqtSignal(list)

    TOOLS = ("select", "rect", "ellipse", "text")
    _HANDLE_R = 6
    

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._px               = None
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

        self._undo_stack : list = []
        self._redo_stack : list = []

        # --- [HARDWARE MASK CACHE v18] ---
        # Saare masks ek GPU-backed QPixmap offscreen layer mein pre-render hote hain.
        # paintEvent mein sirf ek drawPixmap() call — 100 masks = 1 mask jaisi speed!
        self._mask_cache_layer : QPixmap = None   # Offscreen layer
        self._mask_cache_dirty : bool    = True   # True = rebuild needed

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        # --- [SMOOTH ZOOM VARIABLES] ---
        self._fast_zoom = False
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._finalize_zoom)

        # ── INK LAYER (review-mode freehand drawing) ─────────────────────────
        # Strokes stored in image-space (unscaled) so they survive zoom changes.
        # Each stroke = list of QPointF in image coords.
        self._ink_active   = False          # True = pen mode on
        self._ink_strokes  : list = []      # committed strokes [[QPointF, ...], ...]
        self._ink_current  : list = []      # stroke being drawn right now
        self._ink_color_idx = 0
        self._ink_colors   = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]
        self._ink_width    = 1.2            # pen width in image-space pixels
        # Ctrl+Ctrl detection
        self._ink_ctrl_last_time = 0.0

    def set_tool(self, tool: str):
        self._tool = tool
        cursors = {
            "select":  Qt.ArrowCursor,
            "rect":    Qt.CrossCursor,
            "ellipse": Qt.CrossCursor,
            "text":    Qt.IBeamCursor,
        }
        self.setCursor(QCursor(cursors.get(tool, Qt.CrossCursor)))
        self.update()

    def load_pixmap(self, px: QPixmap):
        if px is None or px.isNull():
            self._px = None
            self._cached_spx = None  # Cache Clear
            self._invalidate_mask_cache()
            self.clear()
            return
        self._px    = px
        self._cached_spx = None      # Cache Clear
        self._invalidate_mask_cache()
        self._boxes = []
        self._scale = 1.0
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._redraw()

    def set_boxes(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=False) for b in boxes]
        self._invalidate_mask_cache()
        self.update()

    def set_boxes_with_state(self, boxes):
        self._boxes = [self._deserialise_box(b, revealed=b.get("revealed", False))
                       for b in boxes]
        # Clear ink when a new card loads
        self._ink_strokes.clear()
        self._ink_current.clear()
        self._invalidate_mask_cache()
        self.update()

    def get_boxes(self):
        SM2_KEYS = ("sm2_interval", "sm2_repetitions", "sm2_ease",
                    "sm2_due", "sm2_last_quality", "box_id")
        result = []
        for b in self._boxes:
            r = b["rect"]
            d = {
                "rect":     [r.x(), r.y(), r.width(), r.height()],
                "label":    b.get("label", ""),
                "shape":    b.get("shape", "rect"),
                "angle":    b.get("angle", 0.0),
                "group_id": b.get("group_id", ""),
            }
            for k in SM2_KEYS:
                if k in b:
                    d[k] = b[k]
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

    def get_target_scaled_rect(self):
        if self._target_group_id:
            rects = [self._sr(b["rect"]) for b in self._boxes
                     if b.get("group_id", "") == self._target_group_id]
            if rects:
                from PyQt5.QtCore import QRectF as _QRF
                x1 = min(r.left()   for r in rects)
                y1 = min(r.top()    for r in rects)
                x2 = max(r.right()  for r in rects)
                y2 = max(r.bottom() for r in rects)
                return _QRF(x1, y1, x2 - x1, y2 - y1)
        if 0 <= self._target_idx < len(self._boxes):
            return self._sr(self._boxes[self._target_idx]["rect"])
        return None

    def select_all(self):
        if not self._boxes:
            return
        self._selected_indices = set(range(len(self._boxes)))
        self._selected_idx     = len(self._boxes) - 1
        self.update()

    def select_visible_only(self):
        if not self._boxes:
            return

        # 1. Screen par jo canvas ka hissa dikh raha hai, uska Bounding Rect nikalenge
        visible_rect = self.visibleRegion().boundingRect()

        # 2. Canvas zoom (scaled) hota hai, toh usko original (unscaled) coordinates mein convert karenge
        inv_scale = 1.0 / self._scale
        vx = visible_rect.x() * inv_scale
        vy = visible_rect.y() * inv_scale
        vw = visible_rect.width() * inv_scale
        vh = visible_rect.height() * inv_scale
        v_rectf = QRectF(vx, vy, vw, vh)

        # 3. Naya selection set banayenge
        self._selected_indices = set()

        for i, b in enumerate(self._boxes):
            # Agar mask ka rect hamare visible screen area ke sath intersect ho raha hai
            if v_rectf.intersects(b["rect"]):
                self._selected_indices.add(i)

        if self._selected_indices:
            # Kisi ek box ko primary selected index bana do taaki uske handles dikh sakein
            self._selected_idx = max(self._selected_indices)
        else:
            self._selected_idx = -1

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
            self._show_toast("⚠ Select 2+ masks to group")
            return
        gid = str(uuid.uuid4())[:8]
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

    def _get_all_selected(self):
        result = set(self._selected_indices)
        if self._selected_idx >= 0:
            result.add(self._selected_idx)
        return sorted(result)

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._redo_stack.clear()
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._undo_stack.pop()
        self._selected_idx = -1
        self._selected_indices = set()
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self._boxes))
        self._boxes = self._redo_stack.pop()
        self._selected_idx = -1
        self._selected_indices = set()
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def zoom_in(self):
        self._scale = min(self._scale * 1.10, 8.0)
        self._redraw()

    def zoom_out(self):
        self._scale = max(self._scale / 1.10, 0.05)
        self._redraw()

    def zoom_fit(self, viewport_w, viewport_h):
        if not self._px or self._px.isNull(): return
        sx = viewport_w  / max(self._px.width(),  1)
        sy = viewport_h  / max(self._px.height(), 1)
        self._scale = min(sx, sy)
        self._redraw()

    def event(self, e):
        # ✋ TOUCHPAD PINCH-TO-ZOOM ENCOUNTER
        if e.type() == QEvent.NativeGesture:
            if e.gestureType() == Qt.ZoomNativeGesture:
                self._fast_zoom = True
                # e.value() exact magnification delta deta hai
                factor = 1.0 + e.value()
                self._scale = max(0.05, min(8.0, self._scale * factor))
                self._redraw()
                self._zoom_timer.start(150) # 150ms baad Smooth Render hoga
                return True
        return super().event(e)

    def wheelEvent(self, e):
        # 🖱 MOUSE WHEEL ZOOM ENCOUNTER
        if e.modifiers() & Qt.ControlModifier:
            angle = e.angleDelta().y()
            if angle == 0:
                e.accept()
                return
                
            self._fast_zoom = True
            factor = 1.0 + (angle / 120.0) * 0.10
            factor = max(0.90, min(factor, 1.11))
            self._scale = max(0.05, min(8.0, self._scale * factor))
            self._redraw()
            self._zoom_timer.start(150) # 150ms baad Smooth Render hoga
            e.accept()
        else:
            super().wheelEvent(e)

    def _deserialise_box(self, b, revealed=False):
        r = b["rect"]
        return {
            "rect":     QRectF(r[0], r[1], r[2], r[3]),
            "shape":    b.get("shape", "rect"),
            "angle":    float(b.get("angle", 0.0)),
            "revealed": revealed,
            "label":    b.get("label", ""),
            "box_id":   b.get("box_id", ""),
            "group_id": b.get("group_id", ""),
            **{k: b[k] for k in ("sm2_interval","sm2_repetitions","sm2_ease",
                                  "sm2_due","sm2_last_quality")
               if k in b}
        }

    def _ip(self, pos):
        return QPointF(pos.x() / self._scale, pos.y() / self._scale)

    def _sr(self, r: QRectF) -> QRectF:
        return QRectF(r.x() * self._scale, r.y() * self._scale,
                      r.width() * self._scale, r.height() * self._scale)

    def _spx(self):
        if not self._px:
            return QPixmap()
            
        # --- [LAG FIX] Cache System ---
        if hasattr(self, '_cached_scale') and hasattr(self, '_cached_spx'):
            if self._cached_scale == self._scale and self._cached_spx is not None:
                return self._cached_spx
                
        self._cached_scale = self._scale
        
        # 🚀 JAB ZOOM CHAL RAHA HO TOH FAST RENDER KARO, WARNA SMOOTH!
        transform_mode = Qt.FastTransformation if getattr(self, '_fast_zoom', False) else Qt.SmoothTransformation
        
        self._cached_spx = self._px.scaled(
            int(self._px.width()  * self._scale),
            int(self._px.height() * self._scale),
            Qt.KeepAspectRatio, transform_mode)
            
        return self._cached_spx

    def _finalize_zoom(self):
        """150ms baad jab user pinch karna band kar de, toh wapas High-Quality render karo"""
        self._fast_zoom = False
        self._cached_scale = -1  # Cache ko jaan-bujhkar clear kiya taaki naya high-quality image bane
        self._redraw()

    def _handle_positions(self, idx):
        if not (0 <= idx < len(self._boxes)):
            return None
        b  = self._boxes[idx]
        sr = self._sr(b["rect"])
        cx = sr.center().x()
        cy = sr.center().y()
        hw = sr.width()  / 2
        hh = sr.height() / 2
        ang = b.get("angle", 0.0)
        rad = math.radians(ang)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def rot(dx, dy):
            return QPointF(cx + dx * cos_a - dy * sin_a,
                           cy + dx * sin_a + dy * cos_a)

        handles = [
            rot(-hw, -hh), rot(0, -hh), rot(hw, -hh),
            rot(-hw,  0),               rot(hw,  0),
            rot(-hw,  hh), rot(0,  hh), rot(hw,  hh),
        ]
        rotate_pt = rot(0, -hh - 24)
        return {"resize": handles, "rotate": rotate_pt}

    def _hit_handle(self, screen_pos, idx):
        hps = self._handle_positions(idx)
        if not hps:
            return None
        sp = QPointF(screen_pos)
        r  = self._HANDLE_R + 2
        rpt = hps["rotate"]
        if (sp - rpt).manhattanLength() <= r:
            return ("rotate", -1)
        for hi, hpt in enumerate(hps["resize"]):
            if (sp - hpt).manhattanLength() <= r:
                return ("resize", hi)
        return None

    def _show_toast(self, msg: str):
        if not hasattr(self, "_toast_label"):
            from PyQt5.QtWidgets import QLabel
            self._toast_label = QLabel(self)
            self._toast_label.setStyleSheet(
                "QLabel{background:rgba(30,30,46,210);color:#BD93F9;"
                "border:1px solid #BD93F9;border-radius:6px;"
                "padding:4px 12px;font-size:12px;font-weight:bold;}")
            self._toast_label.hide()
        if not hasattr(self, "_toast_timer"):
            from PyQt5.QtCore import QTimer
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast_label.hide)
        self._toast_label.setText(msg)
        self._toast_label.adjustSize()
        x = (self.width()  - self._toast_label.width())  // 2
        y = 18
        self._toast_label.move(x, y)
        self._toast_label.show()
        self._toast_label.raise_()
        self._toast_timer.start(1800)

    def _select_box(self, hit: int, add_to_selection: bool = False):
        if hit < 0:
            self._selected_idx     = -1
            self._selected_indices = set()
            self._invalidate_mask_cache()
            self.update()
            return
        gid = self._boxes[hit].get("group_id", "")
        if gid:
            members = {i for i, b in enumerate(self._boxes)
                       if b.get("group_id", "") == gid}
            if add_to_selection:
                self._selected_indices |= members
            else:
                self._selected_indices = members
        else:
            if add_to_selection:
                self._selected_indices.add(hit)
            else:
                self._selected_indices = set()
        self._selected_idx = hit
        self._invalidate_mask_cache()
        self.update()
        self.boxes_changed.emit(self.get_boxes())

    def _hit_box(self, ip: QPointF):
        for i in range(len(self._boxes) - 1, -1, -1):
            b  = self._boxes[i]
            r  = b["rect"]
            cx, cy = r.center().x(), r.center().y()
            ang = b.get("angle", 0.0)
            if b.get("shape") == "ellipse":
                if _point_in_rotated_ellipse(ip.x(), ip.y(),
                                             cx, cy,
                                             r.width()/2, r.height()/2, ang):
                    return i
            else:
                if _point_in_rotated_box(ip.x(), ip.y(),
                                         cx, cy, r.width(), r.height(), ang):
                    return i
        return -1

    def _redraw(self):
        if not self._px or self._px.isNull():
            return
        spx = self._spx()
        if spx.isNull():
            return

        # सिर्फ बैकग्राउंड सेट करो
        self.setPixmap(spx)
        self.resize(spx.size())

        # Zoom change hone par mask cache ki size bhi change hoti hai — rebuild zaroori hai
        self._invalidate_mask_cache()

        # Qt को हार्डवेयर पेंटिंग के लिए सिग्नल दो
        self.update()

    def _invalidate_mask_cache(self):
        """
        [HARDWARE MASK CACHE v18]
        Koi bhi mask change hone par call karo — cache ko dirty mark karta hai.
        Actual rebuild tab hogi jab paintEvent next baar chale.
        Mouse drag ke DAURAN mat call karna — sirf mouseReleaseEvent mein!
        """
        self._mask_cache_dirty = True

    def _rebuild_mask_cache(self):
        """
        [HARDWARE MASK CACHE v18]
        Saare masks ko ek GPU-backed QPixmap offscreen layer mein render karo.
        Sirf tab call hoti hai jab _mask_cache_dirty == True ho.
        """
        if not self._px or self._px.isNull():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        spx = self._spx()
        if spx.isNull():
            self._mask_cache_layer = None
            self._mask_cache_dirty = False
            return

        # Scaled canvas ke same size ka transparent offscreen layer banao
        self._mask_cache_layer = QPixmap(spx.width(), spx.height())
        self._mask_cache_layer.fill(Qt.transparent)

        p = QPainter(self._mask_cache_layer)
        p.setRenderHint(QPainter.Antialiasing)

        # Saare non-selected, non-active masks yahan render karo
        for i, b in enumerate(self._boxes):
            # Drag ho raha ho toh selected box skip karo —
            # wo live paintEvent mein draw hoga (smooth drag ke liye)
            if self._drag_op and i == self._selected_idx:
                continue
            self._draw_box(p, i, b)

        p.end()
        self._mask_cache_dirty = False

    def paintEvent(self, event):
        # Pehle background image render hone do (QLabel ka default behavior)
        super().paintEvent(event)

        if not self.pixmap():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # [HARDWARE MASK CACHE v18]
        # Step 1: Agar cache dirty hai toh rebuild karo (sirf tab jab zaroorat ho)
        if self._mask_cache_dirty:
            self._rebuild_mask_cache()

        # Step 2: Pre-rendered mask layer seedha GPU se chipkao — O(1) operation!
        if self._mask_cache_layer and not self._mask_cache_layer.isNull():
            p.drawPixmap(0, 0, self._mask_cache_layer)

        # Step 3: Drag ke dauran sirf selected box live draw karo (ultra smooth drag)
        if self._drag_op and self._selected_idx >= 0:
            self._draw_box(p, self._selected_idx, self._boxes[self._selected_idx])

        # Step 4: Live rect (naya box draw ho raha ho toh)
        if self._drawing and not self._live_rect.isEmpty():
            self._draw_live(p)

        # Step 5: Ink layer — freehand strokes on top of everything
        self._draw_ink_layer(p)

        p.end()

    def _draw_box(self, p: QPainter, i: int, b: dict):
        sr    = self._sr(b["rect"])
        cx    = sr.center().x()
        cy    = sr.center().y()
        ang   = b.get("angle", 0.0)
        lbl   = b.get("label") or f"#{i+1}"
        shape = b.get("shape", "rect")
        sel   = (i == self._selected_idx) or (i in self._selected_indices)

        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        local = QRectF(-sr.width()/2, -sr.height()/2, sr.width(), sr.height())

        if self._mode == "review":
            revealed  = b.get("revealed", False)
            in_target_group = (bool(self._target_group_id) and
                               b.get("group_id", "") == self._target_group_id)
            is_target = (i == self._target_idx) or in_target_group
            hide_one  = (self._review_mode_style == "hide_one")

            if hide_one and not is_target:
                if not revealed:
                    p.setPen(QPen(QColor(C_GREEN), 1, Qt.DotLine))
                    p.setBrush(Qt.NoBrush)
                    if shape == "ellipse":
                        p.drawEllipse(local)
                    else:
                        p.drawRect(local)
                p.restore()
                return

            if not revealed:
                if is_target:
                    color    = QColor(C_GREEN)
                    text_col = "#1E1E2E"
                else:
                    color    = QColor(C_MASK)
                    text_col = "#FFF"
                p.setBrush(QBrush(color))
                p.setPen(QPen(QColor(text_col), 2))
                if shape == "ellipse":
                    p.drawEllipse(local)
                else:
                    p.drawRect(local)
                p.setPen(QPen(QColor(text_col), 1))
                p.setFont(QFont("Segoe UI", 10, QFont.Bold))
                p.drawText(local, Qt.AlignCenter, lbl)
            else:
                p.setPen(QPen(QColor(C_GREEN), 2))
                p.setBrush(Qt.NoBrush)
                if shape == "ellipse":
                    p.drawEllipse(local)
                else:
                    p.drawRect(local)
        else:
            gid    = b.get("group_id", "")
            grouped = bool(gid)
            fill = QColor("#50FA7B" if sel else
                          "#6EB5FF" if grouped else C_MASK)
            fill.setAlpha(155)
            p.setBrush(QBrush(fill))
            border_col = QColor(C_GREEN if sel else
                                "#2288FF" if grouped else "#FFF")
            p.setPen(QPen(border_col, 2, Qt.DashLine if not grouped else Qt.SolidLine))
            if shape == "ellipse":
                p.drawEllipse(local)
            else:
                p.drawRect(local)
            p.setPen(QPen(border_col, 1))
            p.setFont(QFont("Segoe UI", 9))
            display_lbl = lbl
            if grouped:
                display_lbl = f"[{gid[:4]}] {lbl}" if lbl else f"[{gid[:4]}]"
            p.drawText(local, Qt.AlignCenter, display_lbl)

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
        p.setPen(QPen(QColor("#FFF"), 1))
        p.drawText(QRectF(rpt.x() - 6, rpt.y() - 6, 12, 12), Qt.AlignCenter, "↻")

    # ── INK LAYER METHODS ────────────────────────────────────────────────────────

    def ink_toggle(self):
        """Toggle ink/pen mode on or off."""
        self._ink_active = not self._ink_active
        if self._ink_active:
            self.setCursor(QCursor(Qt.CrossCursor))
        else:
            # Restore review cursor
            self.setCursor(QCursor(Qt.PointingHandCursor))

    def ink_cycle_color(self):
        """Cycle to the next ink color."""
        self._ink_color_idx = (self._ink_color_idx + 1) % len(self._ink_colors)
        self._show_toast(f"✏ Ink: {self._ink_colors[self._ink_color_idx]}")

    def ink_clear(self):
        """Clear all ink strokes on the current card."""
        self._ink_strokes.clear()
        self._ink_current.clear()
        self.update()
        self._show_toast("🧹 Ink cleared")

    def ink_undo_stroke(self):
        """Remove the last committed ink stroke."""
        if self._ink_strokes:
            self._ink_strokes.pop()
            self.update()

    @property
    def _ink_pen_color(self):
        return QColor(self._ink_colors[self._ink_color_idx])

    def _draw_ink_layer(self, p: QPainter):
        """Draw all committed strokes + the current in-progress stroke."""
        if not self._ink_strokes and not self._ink_current:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        # Scale pen width with canvas zoom
        pen_w = max(1.0, self._ink_width * self._scale)
        all_strokes = list(self._ink_strokes)
        if self._ink_current:
            all_strokes.append(self._ink_current)
        for stroke_data in all_strokes:
            if len(stroke_data) < 2:
                # Single dot
                if stroke_data:
                    color, pts = stroke_data[0], stroke_data[1:]
                    if not pts:
                        continue
                else:
                    continue
            # Each stroke is stored as [QColor, QPointF, QPointF, ...]
            color = stroke_data[0]
            pts   = stroke_data[1:]
            if not pts:
                continue
            pen = QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            if len(pts) == 1:
                sp = QPointF(pts[0].x() * self._scale, pts[0].y() * self._scale)
                p.drawPoint(sp)
            else:
                for i in range(len(pts) - 1):
                    p1 = QPointF(pts[i].x()   * self._scale, pts[i].y()   * self._scale)
                    p2 = QPointF(pts[i+1].x() * self._scale, pts[i+1].y() * self._scale)
                    p.drawLine(p1, p2)
        p.restore()

    def _ink_press(self, ip: QPointF):
        """Start a new ink stroke at image-space point ip."""
        self._ink_current = [self._ink_pen_color, ip]

    def _ink_move(self, ip: QPointF):
        """Extend the current ink stroke."""
        if self._ink_current:
            self._ink_current.append(ip)
            self.update()

    def _ink_release(self):
        """Commit the current stroke."""
        if len(self._ink_current) >= 2:
            self._ink_strokes.append(list(self._ink_current))
        self._ink_current = []
        self.update()

    def _draw_live(self, p: QPainter):
        sr = self._sr(self._live_rect)
        c  = QColor(C_ACCENT)
        c.setAlpha(110)
        p.setBrush(QBrush(c))
        p.setPen(QPen(QColor(C_ACCENT), 2))
        if self._tool == "ellipse":
            p.drawEllipse(sr)
        else:
            p.drawRect(sr)

    def mousePressEvent(self, e):
        if not self._px:
            return

        # Pan mode check — Space held or H locked or middle button
        # Pass event to parent ScrollArea so it can pan
        scroll = self.parent()
        while scroll is not None and not hasattr(scroll, "pan_mode"):
            scroll = scroll.parent()
        if scroll is not None and (scroll.pan_mode or e.button() == Qt.MiddleButton):
            e.ignore()
            return

        self.setFocus()
        sp = QPointF(e.pos())
        ip = self._ip(e.pos())
        mods = e.modifiers()

        # Review Mode Logic
        if self._mode == "review" and e.button() == Qt.LeftButton:
            # Ink mode intercepts ALL left-clicks when active
            if self._ink_active:
                self._ink_press(ip)
                e.accept()
                return
            hit = self._hit_box(ip)
            if hit >= 0:
                self._boxes[hit]["revealed"] = not self._boxes[hit]["revealed"]
                self._invalidate_mask_cache()
                self.update()
                return
            # Empty area in review → pass to scroll area for pan
            e.ignore()
            return

        if self._mode != "edit" or e.button() != Qt.LeftButton:
            return

        # --- [MOTIVATION: No Alt Needed Anymore!] ---
        # हम हमेशा चेक करेंगे कि क्या यूजर किसी पुराने बॉक्स या हैंडल को पकड़ रहा है
        
        # 1. पहले चेक करें: क्या किसी Resize/Rotate हैंडल पर क्लिक किया है?
        if self._selected_idx >= 0:
            hit_h = self._hit_handle(sp, self._selected_idx)
            if hit_h:
                op, hi = hit_h
                self._drag_op        = op
                self._drag_handle    = hi
                self._drag_start_pos = sp
                self._drag_orig_box  = copy.deepcopy(self._boxes[self._selected_idx])
                self._push_undo()
                return

        # 2. चेक करें: क्या किसी बॉक्स (Mask) के ऊपर क्लिक किया है?
        hit = self._hit_box(ip)
        if hit >= 0:
            # [FIX: Ctrl for Multiple Selection]
            # यहाँ हमने Shift की जगह Ctrl (ControlModifier) लगा दिया है
            is_multi = bool(mods & Qt.ControlModifier)
            self._select_box(hit, add_to_selection=is_multi)
            
            # Dragging Command (बिना किसी Alt के)
            self._drag_op        = "move"
            self._drag_start_pos = sp
            self._drag_orig_box  = copy.deepcopy(self._boxes[hit])
            self._push_undo()
            return # ताकि नीचे नया बॉक्स ड्रा न होने लगे

        # 3. अगर किसी बॉक्स पर क्लिक नहीं किया, तो नया बॉक्स ड्रा करें (Rect/Ellipse)
        if self._tool != "select":
            self._select_box(-1) # पुराना सिलेक्शन खत्म
            self._drawing  = True
            self._start    = ip
            self._live_rect = QRectF()
            self.update()

    def mouseMoveEvent(self, e):
        # Ink mode: draw stroke
        if self._mode == "review" and self._ink_active and self._ink_current:
            self._ink_move(self._ip(e.pos()))
            e.accept()
            return
        # If scroll area is panning, ignore canvas move events entirely
        scroll = self.parent()
        while scroll is not None and not hasattr(scroll, "_pan_active"):
            scroll = scroll.parent()
        if scroll is not None and scroll._pan_active:
            e.ignore()
            return

        sp = QPointF(e.pos())
        ip = self._ip(e.pos())

        if self._drawing:
            x0, y0 = self._start.x(), self._start.y()
            x1, y1 = ip.x(), ip.y()
            self._live_rect = QRectF(
                min(x0, x1), min(y0, y1),
                abs(x1 - x0), abs(y1 - y0))
            self.update()  # --- [LAG FIX] Native Update ---
            return

        if self._drag_op == "move" and self._selected_idx >= 0:
            delta = (sp - self._drag_start_pos) / self._scale
            orig  = self._drag_orig_box["rect"]
            self._boxes[self._selected_idx]["rect"] = QRectF(
                orig.x() + delta.x(), orig.y() + delta.y(),
                orig.width(), orig.height())
            self.update()  # --- [LAG FIX] Native Update ---
            return

        if self._drag_op == "resize" and self._selected_idx >= 0:
            self._do_resize(sp)
            return

        if self._drag_op == "rotate" and self._selected_idx >= 0:
            b  = self._boxes[self._selected_idx]
            sr = self._sr(b["rect"])
            cx, cy = sr.center().x(), sr.center().y()
            angle = math.degrees(math.atan2(sp.y() - cy, sp.x() - cx)) + 90
            b["angle"] = round(angle, 1)
            self.update()  # --- [LAG FIX] Native Update ---
            return

        if self._tool == "select" and self._mode == "edit":
            if self._selected_idx >= 0:
                hh = self._hit_handle(sp, self._selected_idx)
                if hh:
                    self.setCursor(QCursor(Qt.SizeAllCursor if hh[0] == "rotate"
                                          else Qt.SizeFDiagCursor))
                    return
            self.setCursor(QCursor(Qt.ArrowCursor))

    def mouseReleaseEvent(self, e):
        # Ink stroke commit
        if self._mode == "review" and self._ink_active and e.button() == Qt.LeftButton:
            self._ink_release()
            e.accept()
            return
        if self._drawing and e.button() == Qt.LeftButton:
            self._drawing = False
            r = self._live_rect
            if r.width() > 6 and r.height() > 6:
                self._push_undo()
                self._boxes.append({
                    "rect":     r,
                    "shape":    self._tool if self._tool in ("rect", "ellipse") else "rect",
                    "angle":    0.0,
                    "revealed": False,
                    "label":    "",
                })
                self._selected_idx = len(self._boxes) - 1
                self._invalidate_mask_cache()
                self.update()
                self.boxes_changed.emit(self.get_boxes())
            self._live_rect = QRectF()
            self._invalidate_mask_cache()
            self.update()

        if self._drag_op:
            self._drag_op     = None
            self._drag_handle = -1
            self._drag_orig_box = None
            # Drag khatam — ab final position ke saath cache rebuild karo
            self._invalidate_mask_cache()
            self.boxes_changed.emit(self.get_boxes())
            self.update()

    def _do_resize(self, sp: QPointF):
        idx  = self._selected_idx
        b    = self._boxes[idx]
        orig = self._drag_orig_box
        hi   = self._drag_handle

        delta = (sp - self._drag_start_pos) / self._scale
        ang   = orig.get("angle", 0.0)
        rad   = math.radians(-ang)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        ldx =  delta.x() * cos_a - delta.y() * sin_a
        ldy =  delta.x() * sin_a + delta.y() * cos_a

        r   = orig["rect"]
        x, y, w, h = r.x(), r.y(), r.width(), r.height()

        move_left  = hi in (0, 3, 5)
        move_right = hi in (2, 4, 7)
        move_top   = hi in (0, 1, 2)
        move_bot   = hi in (5, 6, 7)

        new_x, new_y, new_w, new_h = x, y, w, h
        if move_left:
            new_x = x + ldx;  new_w = max(10, w - ldx)
        if move_right:
            new_w = max(10, w + ldx)
        if move_top:
            new_y = y + ldy;  new_h = max(10, h - ldy)
        if move_bot:
            new_h = max(10, h + ldy)

        b["rect"]  = QRectF(new_x, new_y, new_w, new_h)
        b["angle"] = ang
        self.update()  # --- [LAG FIX] Native Update ---

    def keyPressEvent(self, e):
        mods = e.modifiers()
        key  = e.key()
        if self._mode == "review":
            super().keyPressEvent(e)
            return
        if key == Qt.Key_Delete:
            self.delete_selected_boxes()
        elif mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:
            self.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_A:
            if mods & Qt.ShiftModifier:
                # [Ctrl + Shift + A] -> Pura PDF ke saare masks ek sath select karega
                self.select_all()
            else:
                # [Ctrl + A] -> Sirf Current Screen/Page par dikhne wale masks ko segregate [अलग करना] karke select karega
                self.select_visible_only()
        elif key == Qt.Key_G and not (mods & Qt.ControlModifier):
            if mods & Qt.ShiftModifier:
                self.ungroup_selected()
            else:
                self.group_selected()
        else:
            super().keyPressEvent(e)

    def leaveEvent(self, e):
        """XP Pen / tablet: pen lift fires leaveEvent — restore cursor via scroll area."""
        scroll = self.parent()
        while scroll is not None and not hasattr(scroll, "_pan_active"):
            scroll = scroll.parent()
        if scroll is not None and scroll._pan_active:
            scroll._pan_active = False
            scroll._pan_start_pos = None
            scroll._is_actually_panning = False
            scroll._clear_pan_cursor()
        super().leaveEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)

# ═══════════════════════════════════════════════════════════════════════════════
#  TOOL BAR
# ═══════════════════════════════════════════════════════════════════════════════


class ToolBar(QWidget):
    tool_changed = pyqtSignal(str)

    _TOOLS = [
        ("select",  "⬡", "Select / Move / Resize / Rotate  [V]\nHold Alt = temp select"),
        ("rect",    "□",  "Rectangle mask  [R]"),
        ("ellipse", "○",  "Ellipse / Circle mask  [E]"),
        ("text",    "T",  "Edit label of clicked mask  [T]"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(50)
        self.setStyleSheet(
            "QWidget{background:#F0F0F0;border-right:1px solid #C8C8C8;}")
        L = QVBoxLayout(self)
        L.setContentsMargins(5, 8, 5, 8)
        L.setSpacing(3)
        self._btns = {}
        for tool, icon, tip in self._TOOLS:
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedSize(40, 40)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#333;"
                "border:none;border-radius:5px;font-size:20px;font-weight:bold;}"
                "QPushButton:checked{background:#4A90D9;color:white;}"
                "QPushButton:hover:!checked{background:#E0E0E0;}")
            b.clicked.connect(lambda _, t=tool: self._select(t))
            L.addWidget(b)
            self._btns[tool] = b
        L.addStretch()
        self._select("rect")

    def _select(self, tool: str):
        for t, b in self._btns.items():
            b.setChecked(t == tool)
        self.tool_changed.emit(tool)

    def select_tool(self, tool: str):
        self._select(tool)


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
        L = QVBoxLayout(self)
        L.setContentsMargins(6, 6, 6, 6)
        L.setSpacing(4)

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

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        b_del   = QPushButton("🗑 Delete")
        b_del.setObjectName("danger")
        b_del.setFixedHeight(26)
        b_del.clicked.connect(self._delete_selected)
        b_clear = QPushButton("✕ Clear All")
        b_clear.setFixedHeight(26)
        b_clear.clicked.connect(self._canvas.clear_all)
        btn_row.addWidget(b_del)
        btn_row.addWidget(b_clear)
        L.addLayout(btn_row)

    def _refresh(self, boxes):
        self.list_w.blockSignals(True) # 🛑 List ke events block kardo
        self.list_w.clear()
        
        for i, b in enumerate(boxes):
            lbl  = b.get("label") or f"Mask #{i+1}"
            gid  = b.get("group_id", "")
            icon = "🔵" if gid else "🟧"
            badge = f" [{gid[:4]}]" if gid else ""
            self.list_w.addItem(f"  {icon} {lbl}{badge}")
            
        # ❌ Purane code mein yahan `self.list_w.blockSignals(False)` likha tha, usko yahan se HATA do!

        sel = self._canvas._selected_idx
        if 0 <= sel < self.list_w.count():
            self.list_w.setCurrentRow(sel) # Ab ye line auto-center ko trigger nahi karegi
            box = self._canvas._boxes[sel]
            self.inp_label.blockSignals(True)
            self.inp_label.setText(box.get("label", ""))
            self.inp_label.blockSignals(False)
            
        # ✅ NAYA CODE: Signals ko sabse last mein unblock karo, jab saara background kaam ho jaye
        self.list_w.blockSignals(False)

    def _on_select(self, row):
        self._canvas.highlight(row)
        if 0 <= row < len(self._canvas._boxes):
            self.inp_label.blockSignals(True)
            self.inp_label.setText(self._canvas._boxes[row].get("label", ""))
            self.inp_label.blockSignals(False)

    def _on_label_change(self, text):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.update_label(row, text)
            self.list_w.currentItem().setText(f"  🟧 {text or f'Mask #{row+1}'}")

    def _delete_selected(self):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.delete_box(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  CARD EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class CardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None):
        super().__init__(parent)
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        self.card                = card or {}
        self._pdf_pages          = []
        self._cur_page           = 0
        self._combined_px        = QPixmap()
        self._data               = data
        self._deck               = deck
        self._auto_subdeck_name  = None
        self._watcher            = QFileSystemWatcher()
        self._watched_path       = None
        self._reload_timer       = QTimer()
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._reload_pdf)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._pdf_loader_thread  = None   # [NOT-RESPONDING FIX] background thread
        self._pending_boxes      = []     # boxes to load after thread finishes
        self._setup_ui()
        if card:
            self._load_card(card)

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
                border: 1px solid #CCC; border-radius: 4px; padding: 4px;
            }
            QListWidget {
                background: white; color: #111;
                border: 1px solid #CCC; border-radius: 4px;
            }
            QListWidget::item:selected { background: #4A90D9; color: white; }
            QPushButton {
                background: #E8E8E8; color: #333;
                border: 1px solid #BBB; border-radius: 4px;
                padding: 4px 10px; font-size: 12px;
            }
            QPushButton:hover  { background: #D8D8D8; }
            QPushButton:pressed{ background: #C8C8C8; }
            QPushButton#accent { background: #4A90D9; color: white; border: 1px solid #3A7FC9; }
            QPushButton#accent:hover { background: #3A7FC9; }
            QPushButton#danger { background: #E05555; color: white; border: 1px solid #C04040; }
            QPushButton#danger:hover { background: #C04040; }
            QPushButton#success{ background: #4CAF50; color: white; border: 1px solid #3A9040; }
            QPushButton#success:hover{ background: #3A9040; }
            QScrollArea { border: none; background: #888; }
            QScrollBar:vertical   { background:#CCC; width:10px; border-radius:5px; }
            QScrollBar::handle:vertical { background:#999; border-radius:5px; }
            QScrollBar:horizontal { background:#CCC; height:10px; border-radius:5px; }
            QScrollBar::handle:horizontal { background:#999; border-radius:5px; }
            QSplitter::handle { background: #D0D0D0; width: 1px; }
        """)

        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        top_bar = QFrame()
        top_bar.setFixedHeight(46)
        top_bar.setStyleSheet(
            "QFrame{background:#F0F0F0;border-bottom:1px solid #C8C8C8;border-radius:0;}"
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#333;min-height:32px;}"
            "QPushButton:hover{background:#DDD;}"
            "QPushButton:pressed{background:#CCC;}"
            "QPushButton:checked{background:#C8D8EE;color:#1a5ca8;}"
        )
        tl = QHBoxLayout(top_bar)
        tl.setContentsMargins(6, 4, 6, 4)
        tl.setSpacing(2)

        def _tbtn(label, tip, checkable=False, w=None):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFixedHeight(34)
            if w:
                b.setFixedWidth(w)
            return b

        btn_img = _tbtn("🖼 Image", "Load Image")
        btn_pdf = _tbtn("📄 PDF",  "Load PDF")
        btn_pdf.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT:
            btn_pdf.setToolTip("pip install pymupdf")
        btn_img.clicked.connect(self._load_image)
        btn_pdf.clicked.connect(self._load_pdf)

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.VLine)
            s.setStyleSheet("QFrame{background:#C0C0C0;margin:5px 4px;}")
            s.setFixedWidth(1)
            return s

        btn_undo = _tbtn("↩", "Undo  Ctrl+Z", w=36)
        btn_redo = _tbtn("↪", "Redo  Ctrl+Y", w=36)
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        btn_redo.clicked.connect(lambda: self.canvas.redo())

        btn_zi = _tbtn("🔍+", "Zoom In  Ctrl++",  w=46)
        btn_zo = _tbtn("🔍−", "Zoom Out  Ctrl+−", w=46)
        btn_zf = _tbtn("⊡",   "Zoom Fit  Ctrl+0", w=32)

        btn_del   = _tbtn("🗑",    "Delete selected  Del", w=32)
        btn_clear = _tbtn("✕ All", "Clear all masks")

        btn_grp   = _tbtn("⛓ Group",  "Group selected masks  [G]")
        btn_ungrp = _tbtn("⛓ Ungroup", "Ungroup selected masks  [Shift+G]")
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

        for w in [btn_img, btn_pdf, _sep(),
                  btn_undo, btn_redo, _sep(),
                  btn_zi, btn_zo, btn_zf, _sep(),
                  btn_del, btn_clear, _sep(),
                  btn_grp, btn_ungrp, _sep(),
                  self.btn_open_ext, self.lbl_sync]:
            tl.addWidget(w)
        tl.addStretch()

        btn_cancel = _tbtn("Cancel", "Discard changes")
        btn_save   = QPushButton("💾  Save Card")
        btn_save.setFixedHeight(34)
        btn_save.setToolTip("Save  Ctrl+S")
        btn_save.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border:1px solid #3A9040;"
            "border-radius:4px;padding:4px 16px;font-size:13px;min-height:32px;}"
            "QPushButton:hover{background:#3A9040;}")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        tl.addWidget(btn_cancel)
        tl.addSpacing(4)
        tl.addWidget(btn_save)

        L.addWidget(top_bar)

        self.pdf_bar = QWidget()
        self.pdf_bar.setStyleSheet("background:#E8E8E8;border-bottom:1px solid #CCC;")
        pb = QHBoxLayout(self.pdf_bar)
        pb.setContentsMargins(10, 2, 10, 2)
        self.lbl_pg = QLabel("")
        self.lbl_pg.setStyleSheet("color:#555;font-size:11px;background:transparent;")
        pb.addWidget(self.lbl_pg)
        pb.addStretch()
        self.pdf_bar.setFixedHeight(22)
        self.pdf_bar.hide()
        L.addWidget(self.pdf_bar)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(0)

        self.toolbar = ToolBar()
        main_row.addWidget(self.toolbar)

        sc = _ZoomableScrollArea()
        sc.setWidgetResizable(True)
        sc.setStyleSheet("QScrollArea{background:#787878;border:none;}")
        self.canvas = OcclusionCanvas()
        self.canvas.setStyleSheet("background:transparent;")
        sc.setWidget(self.canvas)
        sc.set_canvas(self.canvas)
        self.toolbar.tool_changed.connect(self.canvas.set_tool)
        main_row.addWidget(sc, stretch=1)

        right_panel = QWidget()
        right_panel.setFixedWidth(240)
        right_panel.setStyleSheet(
            "QWidget{background:#F5F5F5;}"
            "QFrame{background:#F5F5F5;border:none;}"
        )
        rp = QVBoxLayout(right_panel)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.setSpacing(0)

        ml_hdr = QFrame()
        ml_hdr.setFixedHeight(28)
        ml_hdr.setStyleSheet(
            "QFrame{background:#E0E0E0;border-bottom:1px solid #CCC;}"
            "QLabel{color:#444;font-size:11px;font-weight:bold;background:transparent;}")
        ml_hl = QHBoxLayout(ml_hdr)
        ml_hl.setContentsMargins(8, 0, 8, 0)
        ml_hl.addWidget(QLabel("Masks"))
        ml_hl.addStretch()
        rp.addWidget(ml_hdr)

        self.mask_panel = MaskPanel(self.canvas)
        rp.addWidget(self.mask_panel, stretch=1)

        self.mask_panel.list_w.currentRowChanged.connect(self._center_on_mask)

        ci_hdr = QFrame()
        ci_hdr.setFixedHeight(28)
        ci_hdr.setStyleSheet(
            "QFrame{background:#E0E0E0;border-top:1px solid #CCC;"
            "border-bottom:1px solid #CCC;}"
            "QLabel{color:#444;font-size:11px;font-weight:bold;background:transparent;}")
        ci_hl = QHBoxLayout(ci_hdr)
        ci_hl.setContentsMargins(8, 0, 8, 0)
        ci_hl.addWidget(QLabel("Card Info"))
        rp.addWidget(ci_hdr)

        ci_body = QWidget()
        ci_body.setStyleSheet("QWidget{background:#F5F5F5;}")
        cib = QFormLayout(ci_body)
        cib.setContentsMargins(8, 8, 8, 8)
        cib.setSpacing(6)
        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("Card title…")
        self.inp_tags  = QLineEdit()
        self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_notes = QTextEdit()
        self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(64)
        cib.addRow("Title:", self.inp_title)
        cib.addRow("Tags:",  self.inp_tags)
        cib.addRow("Notes:", self.inp_notes)
        rp.addWidget(ci_body)

        main_row.addWidget(right_panel)

        body_w = QWidget()
        body_w.setLayout(main_row)
        L.addWidget(body_w, stretch=1)

        hint_bar = QFrame()
        hint_bar.setFixedHeight(20)
        hint_bar.setStyleSheet(
            "QFrame{background:#E8E8E8;border-top:1px solid #CCC;border-radius:0;}"
            "QLabel{background:transparent;color:#777;font-size:10px;}")
        hl = QHBoxLayout(hint_bar)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.addWidget(QLabel(
            "V=Select  R=Rect  E=Ellipse  T=Label  |  "
            "Hold Alt=temp select  Alt+Click=multi-select  |  "
            "G=group  Shift+G=ungroup  |  "
            "Drag ↻=rotate  Del=delete  Ctrl+Z/Y=undo/redo  |  "
            "Middle-click drag or H = Pan  (tablet/stylus)"))
        hl.addStretch()
        L.addWidget(hint_bar)

        btn_zi.clicked.connect(lambda: self.canvas.zoom_in())
        btn_zo.clicked.connect(lambda: self.canvas.zoom_out())
        btn_zf.clicked.connect(self._zoom_fit)
        btn_del.clicked.connect(lambda: self.canvas.delete_selected_boxes())
        btn_clear.clicked.connect(self.canvas.clear_all)

        self._sc = sc

    def _zoom_fit(self):
        vp = self._sc.viewport()
        self.canvas.zoom_fit(vp.width(), vp.height())

    def _center_on_mask(self, row):
        if not (0 <= row < len(self.canvas._boxes)):
            return
        r = self.canvas._sr(self.canvas._boxes[row]["rect"])
        vbar = self._sc.verticalScrollBar()
        hbar = self._sc.horizontalScrollBar()
        hbar.setValue(int(max(0, r.center().x() - self._sc.viewport().width()  // 2)))
        vbar.setValue(int(max(0, r.center().y() - self._sc.viewport().height() // 2)))

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.canvas.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:
            self.canvas.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_S:
            self._save()
        elif key == Qt.Key_V:
            self.toolbar.select_tool("select")
        elif key == Qt.Key_R:
            self.toolbar.select_tool("rect")
        elif key == Qt.Key_E:
            self.toolbar.select_tool("ellipse")
        elif key == Qt.Key_T:
            self.toolbar.select_tool("text")
        else:
            super().keyPressEvent(e)

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
        self.card["image_path"] = path
        self.card.pop("pdf_path", None)
        self._pdf_pages = []
        self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False)
        self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        if not self.inp_title.text():
            self.inp_title.setText(os.path.splitext(os.path.basename(path))[0])

    def _load_pdf(self):
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load PDF", "", "PDF (*.pdf)")
        if not path:
            return
        self.card["pdf_path"] = path
        self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
        self._pending_boxes = []

        # --- [LRU CACHE v18] ---
        # Agar saare pages already cache mein hain toh thread start hi mat karo!
        # PdfLoaderThread khud bhi cache check karta hai, isliye partial cache bhi fast hogi.
        self._show_pdf_loading(True)
        self._start_pdf_thread(path)

    def _start_pdf_thread(self, path: str):
        """[PROGRESSIVE LOADING] 10-10 pages background mein load karo."""
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(500)
        self._pdf_loader_thread = PdfLoaderThread(path, parent=self)
        self._pdf_loader_thread.chunk_ready.connect(self._on_chunk_ready)
        self._pdf_loader_thread.done.connect(self._on_pdf_loaded)
        self._pdf_loader_thread.start()

    def _on_chunk_ready(self, combined, loaded, total):
        """[PROGRESSIVE] Har 10 pages baad canvas update karo — user wait nahi karta!"""
        path = self.card.get("pdf_path", "")
        self._combined_px = combined
        self.canvas.load_pixmap(combined)
        # Pending boxes pehle chunk pe hi restore karo
        if self._pending_boxes:
            self.canvas.set_boxes(self._pending_boxes)
            self.mask_panel._refresh(self._pending_boxes)
            self._pending_boxes = []
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  ⏳ {loaded}/{total} pages loaded…")
        self.pdf_bar.show()
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText(f"⏳ Loading… {loaded}/{total} pages")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self.setWindowTitle(f"Occlusion Card Editor  ⏳ {loaded}/{total} pages…")

    def _on_pdf_loaded(self, combined, err):
        """Saare pages load ho gaye — final canvas update karo."""
        self._show_pdf_loading(False)
        path = self.card.get("pdf_path", "")
        if combined.isNull():
            QMessageBox.warning(self, "PDF Error", err or "Could not render PDF.")
            return

        self._combined_px = combined
        # [LRU PAGE CACHE v18] — Individual pages ab PdfLoaderThread ke andar
        # PAGE_CACHE mein store ho jaate hain. Yahan kuch extra karne ki zaroorat nahi.

        try:
            _doc = fitz.open(path); n = len(_doc); _doc.close()
        except Exception:
            n = 0
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  {n} page{'s' if n != 1 else ''}"
            f"  •  scroll to navigate")
        self.pdf_bar.show()
        # Final full pixmap set karo (saare pages ke saath)
        self.canvas.load_pixmap(self._combined_px)
        if not self.inp_title.text():
            self.inp_title.setText(self._auto_subdeck_name or "")
        # Agar boxes abhi bhi pending hain (chunk nahi aaya tha) toh yahan restore karo
        if self._pending_boxes:
            self.canvas.set_boxes(self._pending_boxes)
            self.mask_panel._refresh(self._pending_boxes)
            self._pending_boxes = []
        self._watch_pdf(path)

    def _show_pdf_loading(self, loading: bool):
        """Loading indicator — title bar update + button disable."""
        if loading:
            self.setWindowTitle("Occlusion Card Editor  ⏳ Loading PDF…")
            self.lbl_sync.setVisible(True)
            self.lbl_sync.setText("⏳ Loading PDF…")
            self.lbl_sync.setStyleSheet(
                f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        else:
            self.setWindowTitle("Occlusion Card Editor")

    def _load_card(self, card):
        self.inp_title.setText(card.get("title", ""))
        self.inp_tags.setText(", ".join(card.get("tags", [])))
        self.inp_notes.setPlainText(card.get("notes", ""))
        px = None
        if card.get("image_path") and os.path.exists(card.get("image_path")):
            px = QPixmap(card["image_path"])
            if px and not px.isNull():
                self.canvas.load_pixmap(px)
            if card.get("boxes"):
                self.canvas.set_boxes(card["boxes"])
                self.mask_panel._refresh(card["boxes"])
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(card.get("pdf_path")):
            path = card["pdf_path"]
            self.card["pdf_path"] = path
            self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
            self._pending_boxes = card.get("boxes", [])

            # [LRU CACHE v18] — Thread start karo; agar pages cache mein hain
            # toh PdfLoaderThread unhe fitz reload kiye bina use karega — ultra fast!
            self._show_pdf_loading(True)
            self._start_pdf_thread(path)

    def _watch_pdf(self, path: str):
        self._stop_watch()
        self._watched_path = path
        self._watcher.addPath(path)
        self.btn_open_ext.setVisible(True)
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("🟢 Live Sync: watching")
        self.lbl_sync.setStyleSheet(
            f"color:{C_GREEN};font-size:11px;background:transparent;font-weight:bold;")

    def _stop_watch(self):
        if self._watched_path:
            self._watcher.removePath(self._watched_path)
            self._watched_path = None
        self._reload_timer.stop()

    def _on_file_changed(self, path: str):
        self.lbl_sync.setText("🟡 Live Sync: change detected…")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self._reload_timer.start()

    def _reload_pdf(self):
        path = self._watched_path
        if not path or not os.path.exists(path):
            QTimer.singleShot(500, self._reload_pdf)
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)

        # [LRU CACHE v18] — File change hone par purane pages evict karo
        PAGE_CACHE.invalidate_pdf(path)

        # [NOT-RESPONDING FIX] Reload bhi thread se karo
        saved_boxes = self.canvas.get_boxes()
        self._pending_boxes = saved_boxes
        self.lbl_sync.setText("🟡 Live Sync: reloading…")
        self.lbl_sync.setStyleSheet(
            f"color:{C_YELLOW};font-size:11px;background:transparent;font-weight:bold;")
        self._start_pdf_thread(path)

    def _open_in_reader(self):
        path = self.card.get("pdf_path") or self._watched_path
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
            return
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            QMessageBox.warning(self, "Could not open",
                f"Could not open PDF in external reader:\n{ex}")

    def closeEvent(self, e):
        self._stop_watch()
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000)
        super().closeEvent(e)

    def reject(self):
        self._stop_watch()
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000)
        super().reject()

    def accept(self):
        self._stop_watch()
        super().accept()

    def _save(self):
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self, "No Source", "Load an image or PDF first.")
            return

        old_boxes  = self.card.get("boxes", [])
        new_boxes  = self.canvas.get_boxes()
        SM2_KEYS   = ("sm2_interval", "sm2_repetitions", "sm2_ease",
                      "sm2_due", "sm2_last_quality", "box_id")

        old_by_id = {b["box_id"]: b for b in old_boxes if "box_id" in b}

        merged = []
        for i, nb in enumerate(new_boxes):
            existing_id = nb.get("box_id")
            old = old_by_id.get(existing_id) if existing_id else None
            if old is None and i < len(old_boxes):
                old = old_boxes[i]
            if old:
                for k in SM2_KEYS:
                    if k in old:
                        nb[k] = old[k]
            if "box_id" not in nb:
                nb["box_id"] = new_box_id()
            merged.append(nb)

        self.card.update({
            "title":   self.inp_title.text().strip() or "Untitled",
            "tags":    [t.strip() for t in self.inp_tags.text().split(",") if t.strip()],
            "notes":   self.inp_notes.toPlainText(),
            "boxes":   merged,
            "created": self.card.get("created", datetime.now().isoformat()),
            "reviews": self.card.get("reviews", 0),
        })
        if self._auto_subdeck_name:
            self.card["_auto_subdeck"] = self._auto_subdeck_name
        sm2_init(self.card)
        for box in self.card.get("boxes", []):
            sm2_init(box)
        self.accept()

    def get_card(self):
        return self.card

class _ZoomableScrollArea(QScrollArea):
    """ScrollArea with:
       - Ctrl+Scroll       → zoom canvas
       - Middle-click drag → pan
       - Space hold + drag → pan  (Photoshop-style, works with XP Pen tablet)
       - H key toggle      → pan mode lock (tablet workflow)
    Pan mode is exposed via pan_mode property so OcclusionCanvas
    can check it before consuming left-click events.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas        = None
        self._pan_active    = False
        self._pan_start_pos = None
        self._pan_hval      = 0
        self._pan_vval      = 0
        self._pan_mode      = False   # True = pan locked (H key toggle)
        self._space_held    = False   # True = Space held down
        # Must accept focus so keyPress/keyRelease events are received

        # XP Pen / tablet threshold
        self._drag_threshold = 10
        self._is_actually_panning = False

        self.setFocusPolicy(Qt.StrongFocus)
        # Install event filter on viewport — tablet/pen events land here, not on self
        self.viewport().installEventFilter(self)

    @property
    def pan_mode(self):
        """Canvas checks this — if True, left-click should pan not draw."""
        return self._pan_mode

    def eventFilter(self, obj, e):
        """Catch mouse/tablet release and leave on the viewport AND canvas —
        XP Pen fires events on whichever surface the pen is over."""
        if obj is self.viewport() or obj is self._canvas:
            t = e.type()
            if t == QEvent.MouseButtonRelease:
                if self._pan_active:
                    self._pan_active = False
                    self._pan_start_pos = None
                    self._is_actually_panning = False
                    self._clear_pan_cursor()
                    if self._pan_mode:
                        self._enter_pan_cursor()
                    return False   # let event propagate normally
            elif t in (QEvent.Leave, QEvent.HoverLeave):
                if self._pan_active:
                    self._pan_active = False
                    self._pan_start_pos = None
                    self._is_actually_panning = False
                    self._clear_pan_cursor()
                return False
        return super().eventFilter(obj, e)

    def set_canvas(self, canvas):
        """Call this instead of sc._canvas = canvas so we can install event filters."""
        self._canvas = canvas
        canvas.installEventFilter(self)

    def _set_pan_cursor(self, shape):
        """Set cursor on every relevant surface — viewport, scroll area, and canvas."""
        c = QCursor(shape)
        self.viewport().setCursor(c)
        self.setCursor(c)
        if self._canvas:
            self._canvas.setCursor(c)

    def _clear_pan_cursor(self):
        """Restore cursors after pan ends."""
        self.viewport().unsetCursor()
        self.unsetCursor()
        if self._canvas:
            in_review = getattr(self._canvas, '_mode', '') == "review"
            if in_review:
                self._canvas.setCursor(QCursor(Qt.PointingHandCursor))
            else:
                self._canvas.set_tool(self._canvas._tool)

    def _enter_pan_cursor(self):
        self._set_pan_cursor(Qt.OpenHandCursor)

    def _exit_pan_cursor(self):
        self._clear_pan_cursor()

    def wheelEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self._canvas:
            self._canvas.wheelEvent(e)
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):
        # Space is reserved for card reveal in review mode — never capture it here
        if e.key() == Qt.Key_H and not e.isAutoRepeat():
            # H = toggle pan mode lock (like Photoshop hand tool)
            self._pan_mode = not self._pan_mode
            if self._pan_mode:
                self._enter_pan_cursor()
            else:
                self._exit_pan_cursor()
            e.accept()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        # Space key is not used for pan — pass through always
        super().keyReleaseEvent(e)

    def _should_pan(self, e):
        """Review mode में Touchpad पर Left Click को 'Pan' की परमिशन दो!"""
        # 🚀 जादू यहाँ है: अगर कैनवास 'review' मोड में है, तो Left Click = Pan
        if self._canvas and getattr(self._canvas, '_mode', '') == "review":
            if e.button() == Qt.LeftButton:
                return True

        # अगर मिडिल बटन है (कभी माउस लगाओ तो), वो भी काम करेगा
        if e.button() == Qt.MiddleButton:
            return True
        
        # Edit mode में Space/H दबा होने पर ही Left Click पैन करेगा
        if e.button() == Qt.LeftButton and self.pan_mode:
            return True
            
        return False
    
    def mousePressEvent(self, e):
        if self._should_pan(e):
            self._pan_active = True
            self._pan_start_pos = e.globalPos()
            self._pan_hval = self.horizontalScrollBar().value()
            self._pan_vval = self.verticalScrollBar().value()
            self._is_actually_panning = False
            self._set_pan_cursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan_active and self._pan_start_pos is not None:
            delta_vec = e.globalPos() - self._pan_start_pos
            
            # 🚀 [ENCOUNTER] चेक करो क्या पेन थ्रेशोल्ड से ज़्यादा चला है?
            if not self._is_actually_panning:
                if delta_vec.manhattanLength() > self._drag_threshold:
                    self._is_actually_panning = True
                    self._set_pan_cursor(Qt.ClosedHandCursor)
                else:
                    return # अभी पैन शुरू नहीं करना, सिर्फ टैप हो सकता है

            # एक्चुअल पैनिंग
            self.horizontalScrollBar().setValue(self._pan_hval - delta_vec.x())
            self.verticalScrollBar().setValue(self._pan_vval - delta_vec.y())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan_active:
            self._pan_active = False
            self._pan_start_pos = None
            self._is_actually_panning = False

            self._clear_pan_cursor()

            # If H-lock pan mode is still on in edit mode, re-enter open hand
            if self._pan_mode:
                self._enter_pan_cursor()

            e.accept()
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        """XP Pen / tablet: pen lifting off surface fires leaveEvent before or
        instead of mouseRelease in some driver versions. Clean up any stuck pan."""
        if self._pan_active:
            self._pan_active = False
            self._pan_start_pos = None
            self._is_actually_panning = False
            self._clear_pan_cursor()
        super().leaveEvent(e)
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