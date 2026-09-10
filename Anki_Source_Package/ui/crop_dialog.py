from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget, QApplication
from PyQt5.QtCore import Qt, QRectF, QPointF, QSize, QSizeF
from PyQt5.QtGui import QPixmap, QColor, QPen, QBrush, QPainter, QPainterPath, QCursor

class CropCanvas(QWidget):
    def __init__(self, strokes, canvas_size, ink_width, accent_color, parent=None, card_img_size=None):
        super().__init__(parent)
        self._strokes = strokes
        self._ink_width = ink_width
        self._accent_color = accent_color
        
        # Calculate bounding box of all strokes to focus preview
        xs = []
        ys = []
        for stroke in strokes:
            if len(stroke) >= 2:
                for pt in stroke[1:]:
                    xs.append(pt.x())
                    ys.append(pt.y())
                    
        if not xs:
            min_x, min_y, max_x, max_y = 0, 0, canvas_size.width(), canvas_size.height()
        else:
            padding = 30
            min_x = max(0, min(xs) - padding)
            min_y = max(0, min(ys) - padding)
            max_x = min(canvas_size.width(), max(xs) + padding)
            max_y = min(canvas_size.height(), max(ys) + padding)
            
        self._src_rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

        # Paint the full drawing onto a temporary pixmap at original scale
        w = int(self._src_rect.width())
        h = int(self._src_rect.height())
        original_pixmap = QPixmap(w, h)
        
        p = QPainter(original_pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Render dark slate checkerboard background so white, black, and colored ink are all visible
        tile_size = 24
        bg_c1 = QColor("#2A2C3C")
        bg_c2 = QColor("#1C1D2A")
        for ty in range(0, h + tile_size, tile_size):
            for tx in range(0, w + tile_size, tile_size):
                c = bg_c1 if ((tx // tile_size) + (ty // tile_size)) % 2 == 0 else bg_c2
                p.fillRect(tx, ty, tile_size, tile_size, c)
                
        p.translate(-min_x, -min_y)
        
        pen_w = max(2.0, ink_width * 2.0)
        for stroke in strokes:
            if len(stroke) < 2:
                continue
            color = stroke[0]
            pts = stroke[1:]
            
            qc = QColor(color)
            if qc.lightness() < 80:
                qc = QColor(Qt.white)
                
            p.setPen(QPen(qc, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(pts) == 1:
                p.setBrush(qc)
                r = max(1.5, pen_w / 2.0)
                p.drawEllipse(pts[0], r, r)
                p.setBrush(Qt.NoBrush)
            else:
                try:
                    from ui.canvas.geometry import smooth_points_to_path
                    path = smooth_points_to_path(pts)
                except Exception:
                    path = QPainterPath()
                    path.moveTo(pts[0])
                    for pt in pts[1:]:
                        path.lineTo(pt)
                p.drawPath(path)
        p.end()
        
        # Scale to fit a comfortable maximum preview size
        max_w = 800
        max_h = 600
        self._preview_pixmap = original_pixmap.scaled(
            max_w, max_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        self._display_rect = self._preview_pixmap.rect()
        self._scale = self._display_rect.width() / self._src_rect.width()
        
        # Set fixed size of the widget to match the scaled preview
        self.setFixedSize(self._preview_pixmap.size())
        
        # Initialize crop rect to cover full preview by default
        self._crop_rect = QRectF(self._display_rect)
        
        # Mouse interaction states
        self._active_handle = None
        self._drag_start = QPointF()
        self._orig_crop_rect = QRectF()
        
        self.setMouseTracking(True)

    def _get_handle_at(self, pos):
        h_size = 14  # Active area size for handles
        rects = {
            "top-left": QRectF(self._crop_rect.left() - h_size/2, self._crop_rect.top() - h_size/2, h_size, h_size),
            "top-right": QRectF(self._crop_rect.right() - h_size/2, self._crop_rect.top() - h_size/2, h_size, h_size),
            "bottom-left": QRectF(self._crop_rect.left() - h_size/2, self._crop_rect.bottom() - h_size/2, h_size, h_size),
            "bottom-right": QRectF(self._crop_rect.right() - h_size/2, self._crop_rect.bottom() - h_size/2, h_size, h_size),
        }
        for name, r in rects.items():
            if r.contains(QPointF(pos)):
                return name
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            handle = self._get_handle_at(pos)
            if handle:
                self._active_handle = handle
            elif self._crop_rect.contains(QPointF(pos)):
                self._active_handle = "move"
            else:
                self._active_handle = "new"
                self._crop_rect = QRectF(pos, QSizeF(0, 0))
                
            self._drag_start = QPointF(pos)
            self._orig_crop_rect = QRectF(self._crop_rect)
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if not self._active_handle:
            # Change cursor to indicate resize/drag handles on hover
            handle = self._get_handle_at(pos)
            if handle in ("top-left", "bottom-right"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ("top-right", "bottom-left"):
                self.setCursor(Qt.SizeBDiagCursor)
            elif self._crop_rect.contains(QPointF(pos)):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)
            return

        diff = pos - self._drag_start
        r = QRectF(self._orig_crop_rect)
        
        if self._active_handle == "move":
            r.translate(diff.x(), diff.y())
            # Keep within bounds
            if r.left() < 0:
                r.moveLeft(0)
            if r.right() > self.width():
                r.moveRight(self.width())
            if r.top() < 0:
                r.moveTop(0)
            if r.bottom() > self.height():
                r.moveBottom(self.height())
            self._crop_rect = r
            
        elif self._active_handle == "new":
            x0 = max(0, min(self._drag_start.x(), pos.x()))
            y0 = max(0, min(self._drag_start.y(), pos.y()))
            x1 = min(self.width(), max(self._drag_start.x(), pos.x()))
            y1 = min(self.height(), max(self._drag_start.y(), pos.y()))
            self._crop_rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            
        else:
            left = r.left()
            right = r.right()
            top = r.top()
            bottom = r.bottom()
            min_size = 15
            
            if "left" in self._active_handle:
                left = min(right - min_size, max(0, left + diff.x()))
            elif "right" in self._active_handle:
                right = max(left + min_size, min(self.width(), right + diff.x()))
                
            if "top" in self._active_handle:
                top = min(bottom - min_size, max(0, top + diff.y()))
            elif "bottom" in self._active_handle:
                bottom = max(top + min_size, min(self.height(), bottom + diff.y()))
                
            self._crop_rect = QRectF(left, top, right - left, bottom - top)
            
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._active_handle = None
            # If the crop rect was clicked but not dragged (or too small), reset to display bounds
            if self._crop_rect.width() < 10 or self._crop_rect.height() < 10:
                self._crop_rect = QRectF(self._display_rect)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._preview_pixmap)
        
        # Dim outside crop box
        whole_path = QPainterPath()
        whole_path.addRect(QRectF(self.rect()))
        crop_path = QPainterPath()
        crop_path.addRect(self._crop_rect)
        dim_path = whole_path.subtracted(crop_path)
        painter.fillPath(dim_path, QBrush(QColor(0, 0, 0, 120)))
        
        # Border
        accent = QColor(self._accent_color)
        painter.setPen(QPen(accent, 2, Qt.SolidLine))
        painter.drawRect(self._crop_rect)
        
        # Handles
        h_size = 8
        painter.setBrush(QBrush(accent))
        painter.setPen(QPen(Qt.white, 1))
        corners = [
            self._crop_rect.topLeft(),
            self._crop_rect.topRight(),
            self._crop_rect.bottomLeft(),
            self._crop_rect.bottomRight()
        ]
        for c in corners:
            painter.drawRect(QRectF(c.x() - h_size/2, c.y() - h_size/2, h_size, h_size))

    def get_cropped_pixmap(self):
        orig_min_x = self._src_rect.x() + self._crop_rect.x() / self._scale
        orig_min_y = self._src_rect.y() + self._crop_rect.y() / self._scale
        orig_w = self._crop_rect.width() / self._scale
        orig_h = self._crop_rect.height() / self._scale
        
        size = QSize(max(10, int(orig_w)), max(10, int(orig_h)))
        px = QPixmap(size)
        px.fill(Qt.black)
        
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(-orig_min_x, -orig_min_y)
        
        pen_w = max(2.0, self._ink_width * 2.0)
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            color = stroke[0]
            pts = stroke[1:]
            
            # Map dark stroke colors to white for visibility on black background
            qc = QColor(color)
            if qc.lightness() < 80:
                qc = QColor(Qt.white)
                
            p.setPen(QPen(qc, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        p.end()
        return px

    def select_all(self):
        self._crop_rect = QRectF(self._display_rect)
        self.update()


class CropInkDialog(QDialog):
    def __init__(self, strokes, canvas_size, ink_width, parent=None, card_img_size=None):
        super().__init__(parent)
        self.setWindowTitle("Crop Drawing")
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        bg = p.get("C_BG", "#1E1E2E")
        surface = p.get("C_SURFACE", "#24283B")
        text = p.get("C_TEXT", "#CDD6F4")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        
        self.setStyleSheet(
            f"QDialog {{ background: {bg}; }}"
            f"QLabel {{ color: {text}; font-family: '{font_family}'; font-size: 13px; }}"
            f"QPushButton {{ font-family: '{font_family}'; font-size: 12px; font-weight: bold; }}"
        )
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        lbl_info = QLabel("Drag the borders/corners to crop your drawing. Press Enter/Ctrl+S to save.")
        layout.addWidget(lbl_info)
        
        # Center the CropCanvas inside a background container
        canvas_container = QWidget()
        canvas_container.setStyleSheet(f"background: {surface}; border: 1px solid {border}; border-radius: 6px;")
        cc_layout = QVBoxLayout(canvas_container)
        cc_layout.setContentsMargins(8, 8, 8, 8)
        cc_layout.setAlignment(Qt.AlignCenter)
        
        self.crop_canvas = CropCanvas(strokes, canvas_size, ink_width, accent, self, card_img_size=card_img_size)
        cc_layout.addWidget(self.crop_canvas)
        layout.addWidget(canvas_container, stretch=1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
            
        self.btn_save = QPushButton("📥 Crop & Insert")
        self.btn_save.setFixedHeight(34)
        if theme != "classic":
            self.btn_save.setStyleSheet(
                f"QPushButton {{ background: {accent}; color: {bg}; border: none; border-radius: 6px; padding: 0 20px; }}"
                f"QPushButton:hover {{ background: white; color: {bg}; }}"
            )
        else:
            self.btn_save.setStyleSheet(
                f"QPushButton {{ background: {accent}; color: white; border: none; border-radius: 6px; padding: 0 20px; }}"
                f"QPushButton:hover {{ background: #6A58E0; }}"
            )
        self.btn_save.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton("✕ Cancel")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 0 20px; }}"
            f"QPushButton:hover {{ background: {surface}; }}"
        )
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)
        
        # Setup shortcuts
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.accept)
        self.enter_shortcut = QShortcut(QKeySequence("Return"), self)
        self.enter_shortcut.activated.connect(self.accept)
        self.enter_shortcut_2 = QShortcut(QKeySequence("Enter"), self)
        self.enter_shortcut_2.activated.connect(self.accept)

    def _select_all(self):
        self.crop_canvas.select_all()

    def get_cropped_pixmap(self):
        return self.crop_canvas.get_cropped_pixmap()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            event.accept()
            return
        super().keyPressEvent(event)


class CropImageCanvas(QWidget):
    def __init__(self, pixmap, accent_color, parent=None):
        super().__init__(parent)
        self._original_pixmap = pixmap
        self._accent_color = accent_color
        
        # Scale to fit a comfortable maximum preview size
        max_w = 800
        max_h = 600
        self._preview_pixmap = self._original_pixmap.scaled(
            max_w, max_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        self._display_rect = self._preview_pixmap.rect()
        self._scale = self._preview_pixmap.width() / self._original_pixmap.width()
        
        # Set fixed size of the widget to match the scaled preview
        self.setFixedSize(self._preview_pixmap.size())
        
        # Initialize crop rect to cover the full preview
        self._crop_rect = QRectF(self._display_rect)
        
        # Mouse interaction states
        self._active_handle = None
        self._drag_start = QPointF()
        self._orig_crop_rect = QRectF()
        
        self.setMouseTracking(True)

    def _get_handle_at(self, pos):
        h_size = 14  # Active area size for handles
        rects = {
            "top-left": QRectF(self._crop_rect.left() - h_size/2, self._crop_rect.top() - h_size/2, h_size, h_size),
            "top-right": QRectF(self._crop_rect.right() - h_size/2, self._crop_rect.top() - h_size/2, h_size, h_size),
            "bottom-left": QRectF(self._crop_rect.left() - h_size/2, self._crop_rect.bottom() - h_size/2, h_size, h_size),
            "bottom-right": QRectF(self._crop_rect.right() - h_size/2, self._crop_rect.bottom() - h_size/2, h_size, h_size),
        }
        for name, r in rects.items():
            if r.contains(QPointF(pos)):
                return name
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            handle = self._get_handle_at(pos)
            if handle:
                self._active_handle = handle
            elif self._crop_rect.contains(QPointF(pos)):
                self._active_handle = "move"
            else:
                self._active_handle = "new"
                self._crop_rect = QRectF(pos, QSizeF(0, 0))
                
            self._drag_start = QPointF(pos)
            self._orig_crop_rect = QRectF(self._crop_rect)
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if not self._active_handle:
            handle = self._get_handle_at(pos)
            if handle in ("top-left", "bottom-right"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ("top-right", "bottom-left"):
                self.setCursor(Qt.SizeBDiagCursor)
            elif self._crop_rect.contains(QPointF(pos)):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.CrossCursor)
            return

        diff = pos - self._drag_start
        r = QRectF(self._orig_crop_rect)
        
        if self._active_handle == "move":
            r.translate(diff.x(), diff.y())
            if r.left() < 0:
                r.moveLeft(0)
            if r.right() > self.width():
                r.moveRight(self.width())
            if r.top() < 0:
                r.moveTop(0)
            if r.bottom() > self.height():
                r.moveBottom(self.height())
            self._crop_rect = r
            
        elif self._active_handle == "new":
            x0 = max(0, min(self._drag_start.x(), pos.x()))
            y0 = max(0, min(self._drag_start.y(), pos.y()))
            x1 = min(self.width(), max(self._drag_start.x(), pos.x()))
            y1 = min(self.height(), max(self._drag_start.y(), pos.y()))
            self._crop_rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            
        else:
            left = r.left()
            right = r.right()
            top = r.top()
            bottom = r.bottom()
            min_size = 15
            
            if "left" in self._active_handle:
                left = min(right - min_size, max(0, left + diff.x()))
            elif "right" in self._active_handle:
                right = max(left + min_size, min(self.width(), right + diff.x()))
                
            if "top" in self._active_handle:
                top = min(bottom - min_size, max(0, top + diff.y()))
            elif "bottom" in self._active_handle:
                bottom = max(top + min_size, min(self.height(), bottom + diff.y()))
                
            self._crop_rect = QRectF(left, top, right - left, bottom - top)
            
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._active_handle = None
            if self._crop_rect.width() < 10 or self._crop_rect.height() < 10:
                self._crop_rect = QRectF(self._display_rect)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._preview_pixmap)
        
        # Dim outside crop box
        whole_path = QPainterPath()
        whole_path.addRect(QRectF(self.rect()))
        crop_path = QPainterPath()
        crop_path.addRect(self._crop_rect)
        dim_path = whole_path.subtracted(crop_path)
        painter.fillPath(dim_path, QBrush(QColor(0, 0, 0, 120)))
        
        # Border
        accent = QColor(self._accent_color)
        painter.setPen(QPen(accent, 2, Qt.SolidLine))
        painter.drawRect(self._crop_rect)
        
        # Handles
        h_size = 8
        painter.setBrush(QBrush(accent))
        painter.setPen(QPen(Qt.white, 1))
        corners = [
            self._crop_rect.topLeft(),
            self._crop_rect.topRight(),
            self._crop_rect.bottomLeft(),
            self._crop_rect.bottomRight()
        ]
        for c in corners:
            painter.drawRect(QRectF(c.x() - h_size/2, c.y() - h_size/2, h_size, h_size))

    def get_crop_geometry(self):
        orig_min_x = self._crop_rect.x() / self._scale
        orig_min_y = self._crop_rect.y() / self._scale
        orig_w = self._crop_rect.width() / self._scale
        orig_h = self._crop_rect.height() / self._scale
        return int(orig_min_x), int(orig_min_y), int(orig_w), int(orig_h)

    def get_cropped_pixmap(self):
        x, y, w, h = self.get_crop_geometry()
        return self._original_pixmap.copy(x, y, w, h)


class CropImageDialog(QDialog):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crop Image")
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        bg = p.get("C_BG", "#1E1E2E")
        surface = p.get("C_SURFACE", "#24283B")
        text = p.get("C_TEXT", "#CDD6F4")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        
        self.setStyleSheet(
            f"QDialog {{ background: {bg}; }}"
            f"QLabel {{ color: {text}; font-family: '{font_family}'; font-size: 13px; }}"
            f"QPushButton {{ font-family: '{font_family}'; font-size: 12px; font-weight: bold; }}"
        )
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        lbl_info = QLabel("Drag borders/corners to crop the image. Press Enter/Ctrl+S to save.")
        layout.addWidget(lbl_info)
        
        # Center the CropImageCanvas inside a background container
        canvas_container = QWidget()
        canvas_container.setStyleSheet(f"background: {surface}; border: 1px solid {border}; border-radius: 6px;")
        cc_layout = QVBoxLayout(canvas_container)
        cc_layout.setContentsMargins(8, 8, 8, 8)
        cc_layout.setAlignment(Qt.AlignCenter)
        
        self.crop_canvas = CropImageCanvas(pixmap, accent, self)
        cc_layout.addWidget(self.crop_canvas)
        layout.addWidget(canvas_container, stretch=1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_save = QPushButton("📥 Crop Image")
        self.btn_save.setFixedHeight(34)
        if theme != "classic":
            self.btn_save.setStyleSheet(
                f"QPushButton {{ background: {accent}; color: {bg}; border: none; border-radius: 6px; padding: 0 20px; }}"
                f"QPushButton:hover {{ background: white; color: {bg}; }}"
            )
        else:
            self.btn_save.setStyleSheet(
                f"QPushButton {{ background: {accent}; color: white; border: none; border-radius: 6px; padding: 0 20px; }}"
                f"QPushButton:hover {{ background: #6A58E0; }}"
            )
        self.btn_save.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton("✕ Cancel")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 0 20px; }}"
            f"QPushButton:hover {{ background: {surface}; }}"
        )
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)
        
        # Setup shortcuts
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.accept)
        self.enter_shortcut = QShortcut(QKeySequence("Return"), self)
        self.enter_shortcut.activated.connect(self.accept)
        self.enter_shortcut_2 = QShortcut(QKeySequence("Enter"), self)
        self.enter_shortcut_2.activated.connect(self.accept)

    def get_cropped_pixmap(self):
        return self.crop_canvas.get_cropped_pixmap()

    def get_crop_geometry(self):
        return self.crop_canvas.get_crop_geometry()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            event.accept()
            return
        super().keyPressEvent(event)


def get_auto_crop_rect(strokes, canvas_size, card_img_size=None):
    from PyQt5.QtCore import QRectF
    xs = []
    ys = []
    for stroke in strokes:
        if len(stroke) >= 2:
            for pt in stroke[1:]:
                xs.append(pt.x())
                ys.append(pt.y())
                
    if not xs:
        return QRectF(0, 0, canvas_size.width(), canvas_size.height())
        
    pad = 15
    min_x = max(0, min(xs) - pad)
    min_y = max(0, min(ys) - pad)
    max_x = min(canvas_size.width(), max(xs) + pad)
    max_y = min(canvas_size.height(), max(ys) + pad)
    
    return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)


def render_cropped_strokes(strokes, crop_rect, ink_width):
    from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QPainterPath
    from PyQt5.QtCore import QSize, Qt
    
    orig_min_x = crop_rect.x()
    orig_min_y = crop_rect.y()
    orig_w = crop_rect.width()
    orig_h = crop_rect.height()
    
    size = QSize(max(10, int(orig_w)), max(10, int(orig_h)))
    px = QPixmap(size)
    px.fill(Qt.black)
    
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(-orig_min_x, -orig_min_y)
    
    pen_w = max(2.0, ink_width * 2.0)
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        color = stroke[0]
        pts = stroke[1:]
        
        # Map dark stroke colors to white for visibility on black background
        qc = QColor(color)
        if qc.lightness() < 80:
            qc = QColor(Qt.white)
            
        p.setPen(QPen(qc, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if len(pts) == 1:
            p.setBrush(qc)
            r = max(1.5, pen_w / 2.0)
            p.drawEllipse(pts[0], r, r)
            p.setBrush(Qt.NoBrush)
        else:
            try:
                from ui.canvas.geometry import smooth_points_to_path
                path = smooth_points_to_path(pts)
            except Exception:
                path = QPainterPath()
                path.moveTo(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
            p.drawPath(path)
    p.end()
    return px

