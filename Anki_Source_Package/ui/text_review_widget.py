import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextBrowser, QFrame, QApplication, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QUrl, QEvent
from PyQt5.QtGui import QFont, QColor, QPen, QPainter, QKeySequence
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
        self.setFocusPolicy(Qt.ClickFocus)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByMouse
        )
        self.viewport().setCursor(Qt.IBeamCursor)
        self.setCursor(Qt.IBeamCursor)

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

    def keyPressEvent(self, e):
        # Allow Ctrl+C for copying selected text
        if e.matches(QKeySequence.Copy):
            super().keyPressEvent(e)
            return
        
        # Forward review navigation/rating keys (Space, 1-5, S, etc.) to review_screen
        p = self.parent()
        while p and not hasattr(p, "_reveal_current") and not hasattr(p, "_rate"):
            p = p.parent()
        if p and hasattr(p, "keyPressEvent"):
            p.keyPressEvent(e)
        else:
            super().keyPressEvent(e)

class TextReviewWidget(QWidget):
    answer_submitted = pyqtSignal()  # Emitted if needed for compatibility/actions

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
        
        if theme in ("tmnt", "manhattan"):
            card_bg = "#121622"
            card_border = "#00F0FF"
            self.badge_color = "#00F0FF"
            self.ans_color = "#39FF14"
            self.notes_color = "#8FA4BF"
        elif theme == "dojo":
            card_bg = "#0F0F17"
            card_border = "#A86CFF"
            self.badge_color = "#A86CFF"
            self.ans_color = "#72FF4F"
            self.notes_color = "#8C9BB4"
        elif theme == "arcanum":
            card_bg = "#16131D"
            card_border = "#C89B3C"
            self.badge_color = "#C89B3C"
            self.ans_color = "#FFD700"
            self.notes_color = "#B09F8C"
        else:
            card_bg = "#1E202C"
            card_border = "#5C7CFA"
            self.badge_color = "#5C7CFA"
            self.ans_color = "#50FA7B"
            self.notes_color = "#A6ADC8"

        self.setStyleSheet(f"""
            QWidget {{ background: transparent; color: #FFFFFF; }}
        """)
        
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(40, 24, 40, 24)
        outer_layout.setAlignment(Qt.AlignCenter)
        
        # Centered Card Frame
        self.card_frame = QFrame()
        self.card_frame.setStyleSheet(f"""
            QFrame#card_frame {{
                background-color: {card_bg};
                border: 1.5px solid {card_border};
                border-radius: 12px;
            }}
            QTextBrowser {{
                background: transparent;
                border: none;
                color: #FFFFFF;
                font-family: {self._font_family};
                selection-background-color: #5C7CFA;
                selection-color: #FFFFFF;
            }}
        """)
        self.card_frame.setObjectName("card_frame")
        self.card_frame.setMaximumWidth(960)
        self.card_frame.setMinimumWidth(340)
        
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(40, 32, 40, 32)
        card_layout.setSpacing(16)
        
        # Header Row with Badges
        self.hdr_layout = QHBoxLayout()
        self.hdr_layout.setContentsMargins(0, 0, 0, 0)
        self.hdr_layout.setSpacing(10)

        self.lbl_card_type = QLabel("🗂️ FRONT (WORD / PROMPT)")
        self.lbl_card_type.setStyleSheet(f"""
            color: {self.badge_color};
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 1.2px;
            border: none;
            background: transparent;
        """)
        self.hdr_layout.addWidget(self.lbl_card_type)

        self.lbl_context_badge = QLabel("")
        self.lbl_context_badge.setStyleSheet(f"""
            color: {self.badge_color};
            background: rgba(92, 124, 250, 0.18);
            border: 1px solid {self.badge_color};
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_context_badge.hide()
        self.hdr_layout.addWidget(self.lbl_context_badge)

        self.lbl_tier_badge = QLabel("")
        self.lbl_tier_badge.setStyleSheet("""
            color: #FFB86C;
            background: rgba(255, 184, 108, 0.18);
            border: 1px solid #FFB86C;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_tier_badge.hide()
        self.hdr_layout.addWidget(self.lbl_tier_badge)

        self.lbl_chain_badge = QLabel("")
        self.lbl_chain_badge.setStyleSheet(f"""
            color: #FFD700;
            background: rgba(255, 215, 0, 0.18);
            border: 1px solid #FFD700;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_chain_badge.hide()
        self.hdr_layout.addWidget(self.lbl_chain_badge)

        self.hdr_layout.addStretch()
        card_layout.addLayout(self.hdr_layout)
        
        # Scrollable Question text
        self.q_browser = ZoomableTextBrowser()
        self.q_browser.setOpenExternalLinks(True)
        self.q_browser.setFont(QFont(self._font_family, 18))
        self.q_browser.document().setDocumentMargin(0)
        self.q_browser.document().setDefaultStyleSheet("img { width: 100%; }")
        card_layout.addWidget(self.q_browser, stretch=1)
        
        # Reveal Section (initially hidden)
        self.answer_container = QWidget()
        ans_layout = QVBoxLayout(self.answer_container)
        ans_layout.setContentsMargins(0, 0, 0, 0)
        ans_layout.setSpacing(14)
        
        # Separator line
        self.sep = QFrame()
        self.sep.setFrameShape(QFrame.HLine)
        self.sep.setStyleSheet(f"background: {p.get('C_BORDER', '#374158')}; height: 1px; border: none;")
        ans_layout.addWidget(self.sep)
        
        self.lbl_ans_title = QLabel("💡 BACK (MEANING / ANSWER)")
        self.lbl_ans_title.setStyleSheet(f"""
            color: {self.badge_color};
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 1.2px;
            border: none;
            background: transparent;
        """)
        ans_layout.addWidget(self.lbl_ans_title)
        
        # Answer QTextBrowser
        self.a_browser = ZoomableTextBrowser()
        self.a_browser.setOpenExternalLinks(True)
        self.a_browser.setFont(QFont(self._font_family, 16))
        self.a_browser.document().setDocumentMargin(0)
        self.a_browser.document().setDefaultStyleSheet("img { width: 100%; }")
        ans_layout.addWidget(self.a_browser, stretch=1)
        
        # Trap / Pitfall Note Section
        self.trap_container = QWidget()
        trap_layout = QVBoxLayout(self.trap_container)
        trap_layout.setContentsMargins(0, 0, 0, 0)
        trap_layout.setSpacing(4)

        self.lbl_trap_title = QLabel("⚠️ TRAP / PITFALL NOTE:")
        self.lbl_trap_title.setStyleSheet(f"""
            color: #FFB86C;
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 0.8px;
            border: none;
            background: transparent;
        """)
        trap_layout.addWidget(self.lbl_trap_title)

        self.trap_browser = ZoomableTextBrowser()
        self.trap_browser.setFont(QFont(self._font_family, 13))
        self.trap_browser.document().setDocumentMargin(0)
        self.trap_browser.setMaximumHeight(80)
        trap_layout.addWidget(self.trap_browser)
        ans_layout.addWidget(self.trap_container)

        # Notes Section (if any)
        self.notes_container = QWidget()
        notes_layout = QVBoxLayout(self.notes_container)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(6)
        
        self.lbl_notes_title = QLabel("📝 NOTES / HINTS:")
        self.lbl_notes_title.setStyleSheet(f"""
            color: {self.notes_color};
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 0.8px;
            border: none;
            background: transparent;
        """)
        notes_layout.addWidget(self.lbl_notes_title)
        
        self.notes_browser = ZoomableTextBrowser()
        self.notes_browser.setFont(QFont(self._font_family, 13))
        self.notes_browser.document().setDocumentMargin(0)
        self.notes_browser.setMaximumHeight(90)
        notes_layout.addWidget(self.notes_browser)
        ans_layout.addWidget(self.notes_container)
        
        card_layout.addWidget(self.answer_container)
        self.answer_container.hide()
        
        outer_layout.addWidget(self.card_frame)

    def keyPressEvent(self, e):
        # Forward keyboard events to the parent (review_screen) so that shortcuts work correctly
        p = self.parent()
        while p and not hasattr(p, "_reveal_current") and not hasattr(p, "_rate"):
            p = p.parent()
        if p and hasattr(p, "keyPressEvent"):
            p.keyPressEvent(e)
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
        if hasattr(self, "trap_browser"):
            self.trap_browser.document().setBaseUrl(get_base_url())
            self.trap_browser.clear()
            self.trap_container.hide()

        # Update Header Badges
        anchor = str(card.get("context_anchor", "") or "").strip()
        if anchor:
            self.lbl_context_badge.setText(f"📌 {anchor}")
            self.lbl_context_badge.setToolTip(f"Topic Context: {anchor}")
            self.lbl_context_badge.show()
        else:
            self.lbl_context_badge.hide()

        chain_order = card.get("chain_order", 0)
        parent_chain = card.get("parent_chain_id")
        if parent_chain or chain_order:
            order_str = f"Step {chain_order}" if chain_order else "Linked Chain"
            self.lbl_chain_badge.setText(f"🔗 {order_str}")
            self.lbl_chain_badge.setToolTip(f"Sequential Linked Card ({order_str} in topic sequence)")
            self.lbl_chain_badge.show()
        else:
            self.lbl_chain_badge.hide()

        # Update Priority Tier Badge
        p_tier = card.get("priority_tier")
        if p_tier is not None:
            try:
                p_tier = int(p_tier)
            except (ValueError, TypeError):
                p_tier = 1
            if p_tier == 1:
                self.lbl_tier_badge.setText("🔥 80/20 CORE")
                self.lbl_tier_badge.setToolTip("🔥 80/20 High-Yield Core Question — 80% Exam Value")
                self.lbl_tier_badge.setStyleSheet("""
                    color: #FFB86C;
                    background: rgba(255, 184, 108, 0.18);
                    border: 1px solid #FFB86C;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                """)
                self.lbl_tier_badge.show()
            elif p_tier == 2:
                self.lbl_tier_badge.setText("⚡ 80/20 DETAIL")
                self.lbl_tier_badge.setToolTip("⚡ Secondary Elimination Detail — Supporting Concept")
                self.lbl_tier_badge.setStyleSheet("""
                    color: #8BE9FD;
                    background: rgba(139, 233, 253, 0.18);
                    border: 1px solid #8BE9FD;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                """)
                self.lbl_tier_badge.show()
            else:
                self.lbl_tier_badge.hide()
        else:
            self.lbl_tier_badge.hide()
        
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
            
        target_width = int(max(200, (self.card_frame.width() - 80) * self._zoom_factor)) if hasattr(self, "card_frame") else 600
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        if theme in ("tmnt", "manhattan"):
            front_color = "#FFFFFF"
            answer_color = "#39FF14"
            notes_color = "#8FA4BF"
            trap_color = "#FFA066"
        elif theme == "dojo":
            front_color = "#FFFFFF"
            answer_color = "#72FF4F"
            notes_color = "#8C9BB4"
            trap_color = "#FF9E64"
        elif theme == "arcanum":
            front_color = "#F5E6C8"
            answer_color = "#FFD700"
            notes_color = "#B09F8C"
            trap_color = "#FFB86C"
        else:
            front_color = "#FFFFFF"
            answer_color = "#50FA7B"
            notes_color = "#A6ADC8"
            trap_color = "#FFB86C"
            
        q_font_size = int(28 * self._zoom_factor)
        a_font_size = int(22 * self._zoom_factor)
        n_font_size = int(14 * self._zoom_factor)
        
        # Update fonts on browsers based on zoom factor
        self.q_browser.setFont(QFont(self._font_family, q_font_size))
        self.a_browser.setFont(QFont(self._font_family, a_font_size))
        self.notes_browser.setFont(QFont(self._font_family, n_font_size))
        if hasattr(self, "trap_browser"):
            self.trap_browser.setFont(QFont(self._font_family, n_font_size))
        
        # Load Question
        question = self.card.get('question', '')
        if "<img" in question or "<html>" in question:
            self._scale_and_load_html(self.q_browser, question, target_width)
        else:
            question_html = f"<div style='font-family: {self._font_family}; font-size: {q_font_size}px; font-weight: bold; color: {front_color}; line-height: 1.4;'>{self._escape_and_format(question)}</div>"
            self.q_browser.setHtml(question_html)
            
        # Load Answer if revealed
        if self.is_revealed:
            answer = self.card.get("answer", "")
            if "<img" in answer or "<html>" in answer:
                self._scale_and_load_html(self.a_browser, answer, target_width)
            else:
                answer_html = f"<div style='font-family: {self._font_family}; font-size: {a_font_size}px; font-weight: 500; color: {answer_color}; line-height: 1.5;'>{self._escape_and_format(answer)}</div>"
                self.a_browser.setHtml(answer_html)

            # Load Trap Note (if any)
            trap_note = str(self.card.get("trap_note", "") or "").strip()
            if trap_note and hasattr(self, "trap_browser"):
                trap_html = f"<div style='font-family: {self._font_family}; color: {trap_color}; font-size: {n_font_size}px; font-weight: bold; line-height: 1.4;'>{self._escape_and_format(trap_note)}</div>"
                self.trap_browser.setHtml(trap_html)
                self.trap_container.show()
            elif hasattr(self, "trap_container"):
                self.trap_container.hide()
                
            # Load Notes
            notes = str(self.card.get("notes", "") or "").strip()
            # Only show separate notes if it differs from trap_note
            if notes and (not trap_note or notes != trap_note):
                notes_html = f"<div style='font-family: {self._font_family}; color: {notes_color}; font-size: {n_font_size}px; line-height: 1.4;'>{self._escape_and_format(notes)}</div>"
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
