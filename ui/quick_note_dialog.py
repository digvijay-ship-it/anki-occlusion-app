# -*- coding: utf-8 -*-
import os
import uuid
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QStackedWidget, QSlider, QFrame, QApplication
)
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QPixmap, QColor, QPainter, QPen, QTextCharFormat, QKeySequence

import storage_paths


class DrawingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 260)
        self.setAttribute(Qt.WA_StaticContents)
        self._pixmap = QPixmap(360, 260)
        self._pixmap.fill(Qt.white)
        self._last_point = QPoint()
        self._drawing = False
        self._pen_color = QColor("#000000")
        self._pen_width = 3
        self._has_drawn = False

    def set_pen_color(self, color):
        self._pen_color = QColor(color)

    def set_pen_width(self, width):
        self._pen_width = width

    def clear(self):
        self._pixmap.fill(Qt.white)
        self._has_drawn = False
        self.update()

    def resizeEvent(self, event):
        if event.size().width() > self._pixmap.width() or event.size().height() > self._pixmap.height():
            new_width = max(self._pixmap.width(), event.size().width())
            new_height = max(self._pixmap.height(), event.size().height())
            new_pix = QPixmap(new_width, new_height)
            new_pix.fill(Qt.white)
            painter = QPainter(new_pix)
            painter.drawPixmap(0, 0, self._pixmap)
            painter.end()
            self._pixmap = new_pix
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_point = event.pos()
            self._drawing = True

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.LeftButton) and self._drawing:
            painter = QPainter(self._pixmap)
            pen = QPen(self._pen_color, self._pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.drawLine(self._last_point, event.pos())
            painter.end()
            self._last_point = event.pos()
            self._has_drawn = True
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drawing = False

    def get_image(self):
        img = self._pixmap.toImage()
        width = img.width()
        height = img.height()
        
        # Scan to crop unnecessary white space
        min_y = 0
        found = False
        for y in range(height):
            for x in range(width):
                if (img.pixel(x, y) & 0x00ffffff) != 0x00ffffff:
                    min_y = y
                    found = True
                    break
            if found:
                break
        if not found:
            return img
            
        max_y = height - 1
        for y in range(height - 1, min_y - 1, -1):
            found = False
            for x in range(width):
                if (img.pixel(x, y) & 0x00ffffff) != 0x00ffffff:
                    max_y = y
                    found = True
                    break
            if found:
                break
                
        min_x = 0
        for x in range(width):
            found = False
            for y in range(min_y, max_y + 1):
                if (img.pixel(x, y) & 0x00ffffff) != 0x00ffffff:
                    min_x = x
                    found = True
                    break
            if found:
                break
                
        max_x = width - 1
        for x in range(width - 1, min_x - 1, -1):
            found = False
            for y in range(min_y, max_y + 1):
                if (img.pixel(x, y) & 0x00ffffff) != 0x00ffffff:
                    max_x = x
                    found = True
                    break
            if found:
                break
                
        # Add 15px padding
        padding = 15
        p_min_x = max(0, min_x - padding)
        p_max_x = min(width - 1, max_x + padding)
        p_min_y = max(0, min_y - padding)
        p_max_y = min(height - 1, max_y + padding)
        
        cropped_w = p_max_x - p_min_x + 1
        cropped_h = p_max_y - p_min_y + 1
        
        return img.copy(p_min_x, p_min_y, cropped_w, cropped_h)

    def is_empty(self) -> bool:
        if not getattr(self, "_has_drawn", False):
            return True
        img = self._pixmap.toImage()
        width = img.width()
        height = img.height()
        for y in range(height):
            for x in range(width):
                if (img.pixel(x, y) & 0x00ffffff) != 0x00ffffff:
                    return False
        return True


class QuickNoteDialog(QDialog):
    def __init__(self, current_note, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Mask Note / Hint")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowState(Qt.WindowMaximized)
        
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
            f"QDialog{{background:{bg};}}"
            f"QLabel{{color:{text};font-family:'{font_family}';font-size:12px;font-weight:bold;}}"
            f"QPushButton{{font-family:'{font_family}';font-size:12px;font-weight:bold;}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Segmented toggle button group at the top
        toggle_container = QWidget()
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(0)
        toggle_layout.setAlignment(Qt.AlignCenter)

        self.btn_toggle_text = QPushButton("📝 Text & Images")
        self.btn_toggle_text.setFixedHeight(34)
        self.btn_toggle_text.setFixedWidth(240)
        self.btn_toggle_text.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_text.clicked.connect(lambda: self.set_view(0))

        self.btn_toggle_draw = QPushButton("🎨 Sketch Canvas")
        self.btn_toggle_draw.setFixedHeight(34)
        self.btn_toggle_draw.setFixedWidth(240)
        self.btn_toggle_draw.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_draw.clicked.connect(lambda: self.set_view(1))

        toggle_layout.addWidget(self.btn_toggle_text)
        toggle_layout.addWidget(self.btn_toggle_draw)
        layout.addWidget(toggle_container)

        # Central stacked widget
        self.stacked_widget = QStackedWidget()

        # 1. Text View Widget
        self.text_view_widget = QWidget()
        text_v = QVBoxLayout(self.text_view_widget)
        text_v.setContentsMargins(0, 0, 0, 0)
        text_v.setSpacing(8)

        from editor_ui import RichTextEdit
        self.note_edit = RichTextEdit()
        self.note_edit.setPlaceholderText("Type a hint, explanation, paste clipboard images (Ctrl+V), or drag and drop images here...")
        self.note_edit.setStyleSheet(
            f"QTextEdit{{background:{surface};color:{text};border:1px solid {border};"
            f"border-radius:6px;padding:8px;font-size:13px;}}"
        )
        if "<img" in current_note or "<html>" in current_note or "<p>" in current_note:
            self.note_edit.setHtml(current_note)
        else:
            self.note_edit.setPlainText(current_note)
        text_v.addWidget(self.note_edit, stretch=1)

        # Dashboard dashed button
        self.btn_goto_sketch = QPushButton("➕ Draw a Sketch / Diagram")
        self.btn_goto_sketch.setFixedHeight(30)
        self.btn_goto_sketch.setCursor(Qt.PointingHandCursor)
        self.btn_goto_sketch.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {accent}; border: 1px dashed {border}; border-radius: 4px; font-weight: bold; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {surface}; border-color: {accent}; }}"
        )
        self.btn_goto_sketch.clicked.connect(lambda: self.set_view(1))
        text_v.addWidget(self.btn_goto_sketch)

        self.stacked_widget.addWidget(self.text_view_widget)

        # 2. Sketchpad View Widget
        self.sketch_view_widget = QWidget()
        sketch_v = QVBoxLayout(self.sketch_view_widget)
        sketch_v.setContentsMargins(0, 0, 0, 0)
        sketch_v.setSpacing(8)

        canvas_frame = QFrame()
        canvas_frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {border}; border-radius: 6px; background: white; }}"
        )
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(1, 1, 1, 1)
        
        self.draw_canvas = DrawingCanvas()
        canvas_layout.addWidget(self.draw_canvas)
        sketch_v.addWidget(canvas_frame, stretch=1)

        # Controls
        controls_h = QHBoxLayout()
        controls_h.setSpacing(10)

        # Color palette
        colors_layout = QHBoxLayout()
        colors_layout.setSpacing(6)
        
        self.color_buttons = []
        palette_colors = [
            ("black", "#1E1E2E", "#1E1E2E"),
            ("red", "#F38BA8", "#F38BA8"),
            ("blue", "#89B4FA", "#89B4FA"),
            ("green", "#A6E3A1", "#A6E3A1"),
            ("yellow", "#F9E2AF", "#F9E2AF"),
        ]
        
        for name, hex_val, display_color in palette_colors:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("color_val", hex_val)
            btn.clicked.connect(self._change_pen_color)
            colors_layout.addWidget(btn)
            self.color_buttons.append(btn)

        self._selected_color_hex = "#1E1E2E"
        self._update_color_buttons_style()
        controls_h.addLayout(colors_layout)

        # Pen Size
        lbl_size = QLabel("Size:")
        lbl_size.setStyleSheet(f"color:{text}; font-size:11px;")
        controls_h.addWidget(lbl_size)

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(1, 20)
        self.size_slider.setValue(3)
        self.size_slider.setFixedWidth(80)
        self.size_slider.valueChanged.connect(self._change_pen_width)
        controls_h.addWidget(self.size_slider)

        controls_h.addStretch()

        # Clear
        self.btn_clear_draw = QPushButton("🧹 Clear")
        self.btn_clear_draw.setFixedHeight(28)
        self.btn_clear_draw.setStyleSheet(
            f"QPushButton{{background:transparent;color:{text};border:1px solid {border};border-radius:4px;padding:0 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{surface};}}"
        )
        self.btn_clear_draw.clicked.connect(self.draw_canvas.clear)
        controls_h.addWidget(self.btn_clear_draw)

        # Insert Drawing
        self.btn_insert_draw = QPushButton("📥 Insert Drawing")
        self.btn_insert_draw.setFixedHeight(28)
        if theme != "classic":
            self.btn_insert_draw.setStyleSheet(
                f"QPushButton{{background:{accent};color:{bg};border:none;border-radius:4px;padding:0 14px;font-weight:bold;font-size:11px;}}"
                f"QPushButton:hover{{background:white;color:{bg};}}"
            )
        else:
            self.btn_insert_draw.setStyleSheet(
                f"QPushButton{{background:{accent};color:white;border:none;border-radius:4px;padding:0 14px;font-weight:bold;font-size:11px;}}"
                f"QPushButton:hover{{background:#6A58E0;}}"
            )
        self.btn_insert_draw.clicked.connect(self._insert_drawing_to_editor)
        controls_h.addWidget(self.btn_insert_draw)

        sketch_v.addLayout(controls_h)
        self.stacked_widget.addWidget(self.sketch_view_widget)

        layout.addWidget(self.stacked_widget, stretch=1)

        # Update initial toggle buttons state
        self.set_view(0)

        # Bottom save/cancel buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_save = QPushButton("💾 Save Note")
        self.btn_save.setFixedHeight(34)
        if theme != "classic":
            self.btn_save.setStyleSheet(
                f"QPushButton{{background:{accent};color:{bg};border:none;border-radius:6px;padding:0 24px;font-size:13px;font-weight:bold;}}"
                f"QPushButton:hover{{background:white;color:{bg};}}"
            )
        else:
            self.btn_save.setStyleSheet(
                f"QPushButton{{background:{accent};color:white;border:none;border-radius:6px;padding:0 24px;font-size:13px;font-weight:bold;}}"
                f"QPushButton:hover{{background:#6A58E0;}}"
            )
        self.btn_save.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("✕ Cancel")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{text};border:1px solid {border};border-radius:6px;padding:0 24px;font-size:13px;}}"
            f"QPushButton:hover{{background:{surface};}}"
        )
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        # Dialog-level shortcut to save with Ctrl+S
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.accept)

    def set_view(self, index):
        self.stacked_widget.setCurrentIndex(index)
        self._update_toggle_buttons_style()

    def _update_toggle_buttons_style(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        bg = p.get("C_BG", "#1E1E2E")
        surface = p.get("C_SURFACE", "#24283B")
        text = p.get("C_TEXT", "#CDD6F4")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        
        active_idx = self.stacked_widget.currentIndex()
        
        if active_idx == 0:
            if theme != "classic":
                left_style = f"background:{accent}; color:{bg}; border: 1px solid {accent}; border-top-left-radius: 6px; border-bottom-left-radius: 6px; border-top-right-radius: 0px; border-bottom-right-radius: 0px; font-weight: bold;"
            else:
                left_style = f"background:{accent}; color:white; border: 1px solid {accent}; border-top-left-radius: 6px; border-bottom-left-radius: 6px; border-top-right-radius: 0px; border-bottom-right-radius: 0px; font-weight: bold;"
            
            right_style = f"background:transparent; color:{text}; border: 1px solid {border}; border-left: none; border-top-right-radius: 6px; border-bottom-right-radius: 6px; border-top-left-radius: 0px; border-bottom-left-radius: 0px;"
        else:
            left_style = f"background:transparent; color:{text}; border: 1px solid {border}; border-right: none; border-top-left-radius: 6px; border-bottom-left-radius: 6px; border-top-right-radius: 0px; border-bottom-right-radius: 0px;"
            
            if theme != "classic":
                right_style = f"background:{accent}; color:{bg}; border: 1px solid {accent}; border-top-right-radius: 6px; border-bottom-right-radius: 6px; border-top-left-radius: 0px; border-bottom-left-radius: 0px; font-weight: bold;"
            else:
                right_style = f"background:{accent}; color:white; border: 1px solid {accent}; border-top-right-radius: 6px; border-bottom-right-radius: 6px; border-top-left-radius: 0px; border-bottom-left-radius: 0px; font-weight: bold;"
                
        self.btn_toggle_text.setStyleSheet(left_style)
        self.btn_toggle_draw.setStyleSheet(right_style)

    def _change_pen_color(self):
        btn = self.sender()
        if btn:
            color_hex = btn.property("color_val")
            self._selected_color_hex = color_hex
            self.draw_canvas.set_pen_color(color_hex)
            self._update_color_buttons_style()

    def _update_color_buttons_style(self):
        for btn in self.color_buttons:
            c = btn.property("color_val")
            if c == self._selected_color_hex:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {c}; border: 2px solid white; border-radius: 10px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {c}; border: 1px solid #45475A; border-radius: 10px; }}"
                )

    def _change_pen_width(self, val):
        self.draw_canvas.set_pen_width(val)

    def _insert_drawing_to_editor(self):
        if hasattr(self.draw_canvas, "is_empty") and self.draw_canvas.is_empty():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Empty Drawing", "Please draw something on the canvas before inserting.")
            return
            
        import os
        import uuid
        
        image_dir = storage_paths.archive_image_dir()
        if not image_dir:
            return
            
        os.makedirs(image_dir, exist_ok=True)
        filename = f"sketch_{uuid.uuid4().hex[:8]}.png"
        file_path = os.path.join(image_dir, filename)
        
        img = self.draw_canvas.get_image()
        img.save(file_path, "PNG")
        
        relative_path = f"images/{filename}"
        cursor = self.note_edit.textCursor()
        cursor.insertHtml(f'<img src="{relative_path}" width="{img.width()}" height="{img.height()}">&nbsp;')
        from PyQt5.QtGui import QTextCharFormat
        cursor.setCharFormat(QTextCharFormat())
        self.note_edit.setTextCursor(cursor)
        self.draw_canvas.clear()
        
        # Automatically switch back to the text view
        self.set_view(0)

    def exec_(self):
        parent_win = self.parent().window() if self.parent() else None
        if parent_win and parent_win.isFullScreen():
            self.showFullScreen()
        else:
            self.showMaximized()
        return super().exec_()

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        
        if key == Qt.Key_F11:
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
            e.accept()
            return

        is_ctrl_question = (
            (clean_mods & Qt.ControlModifier) and
            not (clean_mods & Qt.AltModifier) and
            not (clean_mods & Qt.MetaModifier) and
            (key == Qt.Key_Question or (key == Qt.Key_Slash and (clean_mods & Qt.ShiftModifier)))
        )
        if is_ctrl_question:
            from ui.shortcut_dialog import ShortcutSettingsDialog
            dlg = ShortcutSettingsDialog(self)
            dlg.exec_()
            dlg.deleteLater()
            e.accept()
            return
        super().keyPressEvent(e)

    def accept(self):
        if self.stacked_widget.currentIndex() == 1:
            if hasattr(self.draw_canvas, "is_empty") and not self.draw_canvas.is_empty():
                self._insert_drawing_to_editor()
        super().accept()
