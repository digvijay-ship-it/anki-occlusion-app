import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextBrowser, QFrame, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QUrl, QEvent
from PyQt5.QtGui import QFont, QColor, QPen, QPainter
from theme_manager import get_palette

def get_base_url():
    from storage_paths import get_mission_archive_root, current_data_file
    root = get_mission_archive_root()
    if not root:
        root = os.path.dirname(current_data_file())
    if root:
        return QUrl.fromLocalFile(os.path.abspath(root) + "/")
    return QUrl()

class ZoomableTextBrowser(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            p = self.parentWidget()
            while p and not hasattr(p, "zoom_in"):
                p = p.parentWidget()
            if p:
                p.wheelEvent(e)
            e.accept()
        else:
            super().wheelEvent(e)

    def event(self, e):
        if e.type() == QEvent.NativeGesture:
            p = self.parentWidget()
            while p and not hasattr(p, "zoom_in"):
                p = p.parentWidget()
            if p:
                p.event(e)
            return True
        return super().event(e)

class TextReviewWidget(QWidget):
    answer_submitted = pyqtSignal() # Emitted if needed for compatibility/actions

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card = None
        self.is_revealed = False
        self._zoom_factor = 1.0
        self._setup_ui()
        self.scratchpad = ScratchpadOverlay(self)
        self.scratchpad.setGeometry(self.rect())
        
    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        # Dynamic fonts based on theme
        self._font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        self._header_font_family = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        
        # Set transparent background to blend directly with the main screen background
        self.setStyleSheet(f"""
            QWidget {{ background: transparent; color: {p['C_TEXT']}; }}
            QTextBrowser {{
                background: transparent;
                border: none;
                color: {p['C_TEXT']};
                font-family: {self._font_family};
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 20, 40, 20)
        main_layout.setSpacing(20)
        
        # Scrollable Question text
        self.q_browser = ZoomableTextBrowser()
        self.q_browser.setOpenExternalLinks(True)
        self.q_browser.setFont(QFont(self._font_family, 16))
        self.q_browser.document().setDocumentMargin(0)
        self.q_browser.document().setDefaultStyleSheet("img { width: 100%; }")
        main_layout.addWidget(self.q_browser, stretch=1)
        
        # Reveal Section (initially hidden)
        self.answer_container = QWidget()
        ans_layout = QVBoxLayout(self.answer_container)
        ans_layout.setContentsMargins(0, 0, 0, 0)
        ans_layout.setSpacing(20)
        
        # Separator line
        self.sep = QFrame()
        self.sep.setFrameShape(QFrame.HLine)
        self.sep.setStyleSheet(f"background: {p['C_BORDER']}; height: 1px;")
        ans_layout.addWidget(self.sep)
        
        # Answer QTextBrowser
        self.a_browser = ZoomableTextBrowser()
        self.a_browser.setOpenExternalLinks(True)
        self.a_browser.setFont(QFont(self._font_family, 16))
        self.a_browser.document().setDocumentMargin(0)
        self.a_browser.document().setDefaultStyleSheet("img { width: 100%; }")
        ans_layout.addWidget(self.a_browser, stretch=1)
        
        # Notes Section (if any)
        self.notes_container = QWidget()
        notes_layout = QVBoxLayout(self.notes_container)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(8)
        
        self.lbl_notes_title = QLabel("Notes / Hints:")
        self.lbl_notes_title.setStyleSheet(f"""
            color: {p['C_SUBTEXT']};
            font-size: 13px;
            font-family: {self._header_font_family};
            font-weight: bold;
        """)
        notes_layout.addWidget(self.lbl_notes_title)
        
        self.notes_browser = ZoomableTextBrowser()
        self.notes_browser.setFont(QFont(self._font_family, 12))
        self.notes_browser.document().setDocumentMargin(0)
        self.notes_browser.setFixedHeight(80)
        notes_layout.addWidget(self.notes_browser)
        ans_layout.addWidget(self.notes_container)
        
        main_layout.addWidget(self.answer_container)
        self.answer_container.hide()

    def keyPressEvent(self, e):
        # Forward keyboard events to the parent (review_screen) so that shortcuts work correctly
        if self.parent():
            self.parent().keyPressEvent(e)
        else:
            super().keyPressEvent(e)
        
    def load_card(self, card):
        self.card = card
        self.is_revealed = False
        if hasattr(self, "scratchpad"):
            self.scratchpad.clear()
        
        self.q_browser.document().setBaseUrl(get_base_url())
        self.a_browser.document().setBaseUrl(get_base_url())
        self.notes_browser.document().setBaseUrl(get_base_url())
        
        self._update_scaled_html()
        
        # Clear/Hide answer container
        self.answer_container.hide()
        self.a_browser.clear()
        self.notes_browser.clear()
        
    def reveal_answer(self):
        if self.is_revealed:
            return
        self.is_revealed = True
        
        self._update_scaled_html()
        self.answer_container.show()
        
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scaled_html()
        if hasattr(self, "scratchpad"):
            self.scratchpad.setGeometry(self.rect())
        
    def _update_scaled_html(self):
        if not self.card:
            return
            
        # Dynamically calculate the actual available width in pixels
        # Margins are 40px left and 40px right, so available width is self.width() - 80.
        target_width = int(max(200, (self.width() - 80) * self._zoom_factor))
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        text_color = "#CDD6F4" if theme != "classic" else p['C_TEXT']
        
        # Update fonts on browsers based on zoom factor
        font_size = int(16 * self._zoom_factor)
        self.q_browser.setFont(QFont(self._font_family, font_size))
        self.a_browser.setFont(QFont(self._font_family, font_size))
        self.notes_browser.setFont(QFont(self._font_family, int(12 * self._zoom_factor)))
        
        # Load Question
        question = self.card.get('question', '')
        if "<img" in question or "<html>" in question:
            self._scale_and_load_html(self.q_browser, question, target_width)
        else:
            question_html = f"<div style='font-size: {font_size}px; color: {text_color};'>{self._escape_and_format(question)}</div>"
            self.q_browser.setHtml(question_html)
            
        # Load Answer if revealed
        if self.is_revealed:
            answer = self.card.get("answer", "")
            if "<img" in answer or "<html>" in answer:
                self._scale_and_load_html(self.a_browser, answer, target_width)
            else:
                answer_html = f"<div style='font-size: {font_size}px; color: {text_color};'>{self._escape_and_format(answer)}</div>"
                self.a_browser.setHtml(answer_html)
                
            # Load Notes
            notes = self.card.get("notes", "").strip()
            if notes:
                notes_color = "#A6ADC8" if theme != "classic" else p['C_TEXT']
                notes_html = f"<div style='color: {notes_color}; font-size: {int(13 * self._zoom_factor)}px;'>{self._escape_and_format(notes)}</div>"
                self.notes_browser.setHtml(notes_html)
                self.notes_container.show()
            else:
                self.notes_container.hide()
        
    def _scale_and_load_html(self, browser, html_content, target_width):
        import re
        from PyQt5.QtGui import QPixmap, QTextDocument
        from PyQt5.QtCore import QUrl
        
        # 1. Parse img tags and their src attributes
        img_pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
        sources = img_pattern.findall(html_content)
        
        base_url = get_base_url()
        base_path = ""
        if base_url.isLocalFile():
            base_path = base_url.toLocalFile()
            
        for src in sources:
            # Resolve the absolute path of the image
            abs_path = src
            if not os.path.isabs(src):
                if base_path:
                    abs_path = os.path.join(base_path, src)
                else:
                    from storage_paths import get_mission_archive_root
                    root = get_mission_archive_root()
                    if root:
                        abs_path = os.path.join(root, src)
            abs_path = os.path.normpath(abs_path)
            
            if os.path.exists(abs_path):
                pixmap = QPixmap(abs_path)
                if not pixmap.isNull():
                    w = pixmap.width()
                    if w > 0:
                        # Scale pixmap smoothly to target_width
                        scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
                        # Register in document cache
                        browser.document().addResource(QTextDocument.ImageResource, QUrl(src), scaled_pixmap)
                        browser.document().addResource(QTextDocument.ImageResource, QUrl.fromLocalFile(abs_path), scaled_pixmap)
                        
        # 2. Clean width/height/style attributes specifically on img tags
        def clean_img_tags(match):
            tag = match.group(0)
            tag = re.sub(r'width\s*=\s*["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
            tag = re.sub(r'height\s*=\s*["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
            tag = re.sub(r'style\s*=\s*["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
            return tag
            
        cleaned = re.compile(r'<img\s+[^>]+>', re.IGNORECASE).sub(clean_img_tags, html_content)
        
        # 3. Clean inline font-size styles to let the QTextBrowser font scale handle text size
        cleaned = re.sub(r'font-size\s*:\s*[^;\'"]+;?', '', cleaned, flags=re.IGNORECASE)
        
        browser.setHtml(cleaned)
        
    def _escape_and_format(self, text):
        import html
        escaped = html.escape(text)
        return escaped.replace("\n", "<br>")

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            angle = e.angleDelta().y()
            if angle > 0:
                self.zoom_in()
            elif angle < 0:
                self.zoom_out()
            e.accept()
        else:
            super().wheelEvent(e)

    def event(self, e):
        if e.type() == QEvent.NativeGesture:
            if e.gestureType() == Qt.ZoomNativeGesture:
                factor = 1.0 + e.value()
                self._zoom_factor = max(0.5, min(3.0, self._zoom_factor * factor))
                self._update_scaled_html()
                return True
        return super().event(e)

    def zoom_in(self):
        self._zoom_factor = min(self._zoom_factor + 0.1, 3.0)
        self._update_scaled_html()

    def zoom_out(self):
        self._zoom_factor = max(self._zoom_factor - 0.1, 0.5)
        self._update_scaled_html()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._update_scaled_html()

class ScratchpadOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)
        self.strokes = []
        self.current_stroke = []
        self.active_color = QColor("#FF4444")
        self.active_width = 2.0
        
    def set_pen_active(self, active):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not active)
        self.setVisible(active)
        if active:
            self.raise_()
            self.update()
            
    def clear(self):
        self.strokes = []
        self.current_stroke = []
        self.update()
        
    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        for stroke in self.strokes:
            pen = QPen(stroke["color"], stroke["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            points = stroke["points"]
            if len(points) > 1:
                for i in range(len(points) - 1):
                    painter.drawLine(points[i], points[i+1])
                    
        if len(self.current_stroke) > 1:
            pen = QPen(self.active_color, self.active_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            for i in range(len(self.current_stroke) - 1):
                painter.drawLine(self.current_stroke[i], self.current_stroke[i+1])
                
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.current_stroke = [e.pos()]
            self.update()
            e.accept()
        else:
            e.ignore()
            
    def mouseMoveEvent(self, e):
        if self.current_stroke:
            self.current_stroke.append(e.pos())
            self.update()
            e.accept()
        else:
            e.ignore()
            
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.current_stroke:
            self.strokes.append({
                "color": QColor(self.active_color),
                "width": self.active_width,
                "points": self.current_stroke
            })
            self.current_stroke = []
            self.update()
            e.accept()
        else:
            e.ignore()
