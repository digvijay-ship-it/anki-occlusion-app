import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QFrame, QApplication, QScrollArea, QSizePolicy,
    QMenu, QAction
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
            p = self.parentWidget()
            while p and not isinstance(p, QScrollArea) and not hasattr(p, "scroll_area"):
                p = p.parentWidget()
            if p:
                sa = p if isinstance(p, QScrollArea) else getattr(p, "scroll_area", None)
                if sa and sa.verticalScrollBar():
                    sa.verticalScrollBar().setValue(sa.verticalScrollBar().value() - e.angleDelta().y())
                    e.accept()
                    return
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

    def contextMenuEvent(self, e):
        tc = self.textCursor()
        selected_text = tc.selectedText().strip() if tc.hasSelection() else ""
        
        # Build quick action review context menu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1E2333;
                color: #FFFFFF;
                border: 1.5px solid #5C7CFA;
                border-radius: 8px;
                padding: 6px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #5C7CFA;
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.12);
                margin: 4px 8px;
            }
        """)

        # 1. Text selection items
        if selected_text:
            act_copy = QAction("📋 Copy Selected Text  (Ctrl+C)", menu)
            act_copy.triggered.connect(self.copy)
            menu.addAction(act_copy)

            clean_term = " ".join(selected_text.split()[:5])
            act_explore = QAction(f"🧠 Explore '{clean_term}' in Mind-Map", menu)
            def _open_term():
                p = self.parent()
                while p and not hasattr(p, "_open_concept_hub"):
                    p = p.parent()
                if p and hasattr(p, "_open_concept_hub"):
                    p._open_concept_hub(clean_term)
            act_explore.triggered.connect(_open_term)
            menu.addAction(act_explore)
            menu.addSeparator()

        # 2. Main review actions
        p = self.parent()
        while p and not hasattr(p, "_toggle_chrome") and not hasattr(p, "_reveal_current"):
            p = p.parent()

        if p:
            # Toggle Top Toolbar
            act_toolbar = QAction("🎛️ Toggle Top Toolbar", menu)
            act_toolbar.triggered.connect(lambda: p._toggle_chrome() if hasattr(p, "_toggle_chrome") else None)
            menu.addAction(act_toolbar)

            # Toggle Pen Drawing
            act_pen = QAction("✏️ Toggle Pen Drawing  (P / Alt)", menu)
            act_pen.triggered.connect(lambda: p._toggle_pen_drawing() if hasattr(p, "_toggle_pen_drawing") else None)
            menu.addAction(act_pen)

            # Clear Pen Strokes
            act_clear_pen = QAction("🧹 Clear Pen Strokes", menu)
            act_clear_pen.triggered.connect(lambda: p._clear_pen_strokes() if hasattr(p, "_clear_pen_strokes") else None)
            menu.addAction(act_clear_pen)

            menu.addSeparator()

            # Sync Deck from Source
            act_sync = QAction("🔄 Sync & Reload Deck from Source  (F5)", menu)
            act_sync.triggered.connect(lambda: p._sync_current_deck_from_source() if hasattr(p, "_sync_current_deck_from_source") else None)
            menu.addAction(act_sync)

            # Mind Map Hub
            act_mindmap = QAction("🧠 Open Mind-Map Concept Hub  (Alt+M)", menu)
            act_mindmap.triggered.connect(lambda: p._toggle_concept_hub() if hasattr(p, "_toggle_concept_hub") else None)
            menu.addAction(act_mindmap)

            # Toggle Card Width
            pw = self.parentWidget()
            while pw and not hasattr(pw, "_cycle_width_mode"):
                pw = pw.parentWidget()
            if pw and hasattr(pw, "_cycle_width_mode"):
                act_width = QAction("↔️ Cycle Card Width  (Alt+W)", menu)
                act_width.triggered.connect(pw._cycle_width_mode)
                menu.addAction(act_width)

            menu.addSeparator()

            # Zoom In / Out / Reset
            act_zin = QAction("🔍 Zoom In  (Ctrl + +)", menu)
            act_zin.triggered.connect(lambda: p._zoom_in() if hasattr(p, "_zoom_in") else None)
            menu.addAction(act_zin)

            act_zout = QAction("🔍 Zoom Out  (Ctrl + -)", menu)
            act_zout.triggered.connect(lambda: p._zoom_out() if hasattr(p, "_zoom_out") else None)
            menu.addAction(act_zout)

            act_zreset = QAction("↺ Reset Zoom  (Ctrl + 0)", menu)
            act_zreset.triggered.connect(lambda: p._zoom_fit() if hasattr(p, "_zoom_fit") else None)
            menu.addAction(act_zreset)

        menu.exec_(e.globalPos())

    def keyPressEvent(self, e):
        # Allow Ctrl+C for copying selected text
        if e.matches(QKeySequence.Copy):
            super().keyPressEvent(e)
            return

        # Alt+W toggle card width mode
        if e.modifiers() & Qt.AltModifier and e.key() == Qt.Key_W:
            p = self.parentWidget()
            while p and not hasattr(p, "_cycle_width_mode"):
                p = p.parentWidget()
            if p and hasattr(p, "_cycle_width_mode"):
                p._cycle_width_mode()
                e.accept()
                return

        # Handle scroll navigation keys (Up, Down, PageUp, PageDown, Home, End)
        k = e.key()
        if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp, Qt.Key_Home, Qt.Key_End) and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            p = self.parentWidget()
            while p and not isinstance(p, QScrollArea) and not hasattr(p, "scroll_area"):
                p = p.parentWidget()
            if p:
                sa = p if isinstance(p, QScrollArea) else getattr(p, "scroll_area", None)
                if sa and sa.verticalScrollBar():
                    vb = sa.verticalScrollBar()
                    if k == Qt.Key_Down:
                        vb.setValue(vb.value() + 60)
                    elif k == Qt.Key_Up:
                        vb.setValue(vb.value() - 60)
                    elif k == Qt.Key_PageDown:
                        vb.setValue(vb.value() + 300)
                    elif k == Qt.Key_PageUp:
                        vb.setValue(vb.value() - 300)
                    elif k == Qt.Key_Home:
                        vb.setValue(vb.minimum())
                    elif k == Qt.Key_End:
                        vb.setValue(vb.maximum())
                    e.accept()
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
    _universal_zoom_factor = None
    _universal_width_mode = None

    @classmethod
    def get_saved_zoom_factor(cls) -> float:
        """Retrieves universally persisted zoom factor across all text decks and app restarts."""
        if cls._universal_zoom_factor is not None:
            return cls._universal_zoom_factor
        try:
            from storage_paths import _settings
            val = _settings().value("text_card_zoom_factor", None)
            if val is not None:
                f_val = float(val)
                if 0.4 <= f_val <= 4.0:
                    cls._universal_zoom_factor = f_val
                    return f_val
        except Exception:
            pass
        cls._universal_zoom_factor = 1.0
        return 1.0

    @classmethod
    def save_zoom_factor(cls, factor: float):
        """Universally persists zoom factor so all text cards and future app sessions retain it."""
        try:
            cls._universal_zoom_factor = float(round(factor, 2))
            from storage_paths import _settings
            _settings().setValue("text_card_zoom_factor", cls._universal_zoom_factor)
        except Exception:
            pass

    @classmethod
    def get_saved_width_mode(cls) -> str:
        """Retrieves universally persisted width mode ('standard', 'wide', 'max')."""
        if cls._universal_width_mode is not None:
            return cls._universal_width_mode
        try:
            from storage_paths import _settings
            val = _settings().value("text_card_width_mode", None)
            if val in ("standard", "wide", "max"):
                cls._universal_width_mode = str(val)
                return str(val)
        except Exception:
            pass
        cls._universal_width_mode = "wide"
        return "wide"

    @classmethod
    def save_width_mode(cls, mode: str):
        """Universally persists width mode ('standard', 'wide', 'max')."""
        try:
            if mode in ("standard", "wide", "max"):
                cls._universal_width_mode = mode
                from storage_paths import _settings
                _settings().setValue("text_card_width_mode", mode)
        except Exception:
            pass

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card = None
        self.is_revealed = False
        self._zoom_factor = TextReviewWidget.get_saved_zoom_factor()
        self._setup_ui()
        self._apply_width_mode()
        self.scratchpad = ScratchpadOverlay(self.scroll_content)
        self.scratchpad.setGeometry(0, 0, self.scroll_content.width(), self.scroll_content.height())
        self.scratchpad.raise_()

    def _get_width_button_text(self) -> str:
        mode = self.get_saved_width_mode()
        if mode == "standard":
            return "↔️ Standard"
        elif mode == "max":
            return "↔️ Max Width"
        else:
            return "↔️ Wide"

    def _get_max_content_width(self) -> int:
        viewport_w = (
            self.scroll_area.viewport().width()
            if hasattr(self, "scroll_area") and self.scroll_area.viewport() and self.scroll_area.viewport().width() > 100
            else self.width()
        )
        if viewport_w <= 100:
            viewport_w = 900
        mode = self.get_saved_width_mode()
        avail_frame_w = max(300, viewport_w - 40)
        if mode == "standard":
            frame_w = min(avail_frame_w, 960)
        elif mode == "max":
            w = max(1100, int(viewport_w * 0.96)) if viewport_w > 500 else 1650
            frame_w = min(avail_frame_w, w)
        else:  # "wide" (default)
            frame_w = min(avail_frame_w, 1380)
        content_w = max(200, frame_w - 80)
        return int(content_w)

    def _apply_width_mode(self):
        mode = self.get_saved_width_mode()
        viewport_w = (
            self.scroll_area.viewport().width()
            if hasattr(self, "scroll_area") and self.scroll_area.viewport() and self.scroll_area.viewport().width() > 100
            else self.width()
        )
        if viewport_w <= 100:
            viewport_w = 900
        avail_frame_w = max(340, viewport_w - 40)
        if mode == "standard":
            self.card_frame.setMaximumWidth(min(avail_frame_w, 960))
        elif mode == "max":
            w = max(1100, int(viewport_w * 0.96)) if viewport_w > 500 else 1650
            self.card_frame.setMaximumWidth(min(avail_frame_w, w))
        else:  # "wide" (default)
            self.card_frame.setMaximumWidth(min(avail_frame_w, 1380))

    def _cycle_width_mode(self):
        modes = ["wide", "max", "standard"]
        curr = self.get_saved_width_mode()
        idx = modes.index(curr) if curr in modes else 0
        next_mode = modes[(idx + 1) % len(modes)]
        self.save_width_mode(next_mode)
        self._apply_width_mode()
        if hasattr(self, "btn_width_mode"):
            self.btn_width_mode.setText(self._get_width_button_text())
        self._update_scaled_html()
        
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
        
        # Main Layout with Single Outer Scroll Area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: rgba(255, 255, 255, 0.04);
                width: 10px;
                margin: 4px 2px 4px 2px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(92, 124, 250, 0.45);
                min-height: 36px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self.badge_color};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(self.scroll_content)
        # Extra 180px bottom padding so card content never gets covered by floating rating bar!
        content_layout.setContentsMargins(20, 16, 20, 180)
        content_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # Centered Card Frame
        self.card_frame = QFrame()
        self.card_frame.setObjectName("card_frame")
        self.card_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.card_frame.setMaximumWidth(960)
        self.card_frame.setMinimumWidth(340)
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
        
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(36, 28, 36, 28)
        card_layout.setSpacing(14)
        
        # Header Row with Badges
        self.hdr_layout = QHBoxLayout()
        self.hdr_layout.setContentsMargins(0, 0, 0, 0)
        self.hdr_layout.setSpacing(8)

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

        self.btn_width_mode = QPushButton(self._get_width_button_text())
        self.btn_width_mode.setCursor(Qt.PointingHandCursor)
        self.btn_width_mode.setToolTip("Toggle Card Width: Standard (960px) → Wide (1380px) → Max Width (Alt+W)")
        self.btn_width_mode.setStyleSheet("""
            QPushButton {
                color: #A6ADC8;
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                color: #FFFFFF;
            }
        """)
        self.btn_width_mode.clicked.connect(self._cycle_width_mode)
        self.hdr_layout.addWidget(self.btn_width_mode)

        self.btn_mindmap = QPushButton("🧠 Mind-Map (Alt+M)")
        self.btn_mindmap.setCursor(Qt.PointingHandCursor)
        self.btn_mindmap.setToolTip("Open Mind-Map Concept Hub & Story Chain (Alt+M)")
        self.btn_mindmap.setStyleSheet("""
            QPushButton {
                color: #70A5FD;
                background: rgba(92, 124, 250, 0.15);
                border: 1px solid #5C7CFA;
                border-radius: 6px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(92, 124, 250, 0.35);
                border: 1px solid #91A7FF;
                color: #FFFFFF;
            }
        """)
        self.btn_mindmap.clicked.connect(lambda: self._on_open_mindmap())
        self.hdr_layout.addWidget(self.btn_mindmap)

        self.btn_sync_deck = QPushButton("🔄 Sync Deck (F5)")
        self.btn_sync_deck.setCursor(Qt.PointingHandCursor)
        self.btn_sync_deck.setToolTip("Sync and refresh deck directly from linked source file (F5 / Alt+R)")
        self.btn_sync_deck.setStyleSheet("""
            QPushButton {
                color: #50FA7B;
                background: rgba(80, 250, 123, 0.15);
                border: 1px solid #50FA7B;
                border-radius: 6px;
                padding: 3px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(80, 250, 123, 0.35);
                border: 1px solid #69FF94;
                color: #FFFFFF;
            }
        """)
        self.btn_sync_deck.clicked.connect(lambda: self._on_sync_deck())
        self.hdr_layout.addWidget(self.btn_sync_deck)

        card_layout.addLayout(self.hdr_layout)

        # Interactive Tag & Connected Concepts Pill Row
        self.tags_container = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(6)
        self.tags_container.hide()
        card_layout.addWidget(self.tags_container)
        
        # Question text (no internal scrollbar, expands vertically)
        self.q_browser = ZoomableTextBrowser()
        self.q_browser.setOpenExternalLinks(True)
        self.q_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.q_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.q_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.q_browser.setFont(QFont(self._font_family, 18))
        self.q_browser.document().setDocumentMargin(0)
        self.q_browser.document().setDefaultStyleSheet("img { width: 100%; }")
        card_layout.addWidget(self.q_browser)
        
        # Reveal Section (initially hidden)
        self.answer_container = QWidget()
        ans_layout = QVBoxLayout(self.answer_container)
        ans_layout.setContentsMargins(0, 0, 0, 0)
        ans_layout.setSpacing(12)
        
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
        
        # Answer QTextBrowser (no internal scrollbar, expands vertically)
        self.a_browser = ZoomableTextBrowser()
        self.a_browser.setOpenExternalLinks(True)
        self.a_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.a_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.a_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.a_browser.setFont(QFont(self._font_family, 20))
        self.a_browser.document().setDocumentMargin(0)
        self.a_browser.document().setDefaultStyleSheet("img { width: 100%; }")
        ans_layout.addWidget(self.a_browser)
        
        # Trap / Pitfall Note Section
        self.trap_container = QWidget()
        trap_layout = QVBoxLayout(self.trap_container)
        trap_layout.setContentsMargins(0, 0, 0, 0)
        trap_layout.setSpacing(4)

        self.lbl_trap_title = QLabel("⚠️ TRAP / PITFALL NOTE:")
        self.lbl_trap_title.setStyleSheet(f"""
            color: #FFB86C;
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 0.8px;
            border: none;
            background: transparent;
        """)
        trap_layout.addWidget(self.lbl_trap_title)

        self.trap_browser = ZoomableTextBrowser()
        self.trap_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.trap_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.trap_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.trap_browser.setFont(QFont(self._font_family, 20))
        self.trap_browser.document().setDocumentMargin(0)
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
            font-size: 14px;
            font-weight: bold;
            letter-spacing: 0.8px;
            border: none;
            background: transparent;
        """)
        notes_layout.addWidget(self.lbl_notes_title)
        
        self.notes_browser = ZoomableTextBrowser()
        self.notes_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.notes_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.notes_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.notes_browser.setFont(QFont(self._font_family, 20))
        self.notes_browser.document().setDocumentMargin(0)
        notes_layout.addWidget(self.notes_browser)
        ans_layout.addWidget(self.notes_container)
        
        card_layout.addWidget(self.answer_container)
        self.answer_container.hide()
        
        content_layout.addWidget(self.card_frame)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

    def keyPressEvent(self, e):
        # Handle scroll navigation keys (Up, Down, PageUp, PageDown, Home, End)
        k = e.key()
        if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp, Qt.Key_Home, Qt.Key_End) and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            if hasattr(self, "scroll_area") and self.scroll_area and self.scroll_area.verticalScrollBar():
                vb = self.scroll_area.verticalScrollBar()
                if k == Qt.Key_Down:
                    vb.setValue(vb.value() + 60)
                elif k == Qt.Key_Up:
                    vb.setValue(vb.value() - 60)
                elif k == Qt.Key_PageDown:
                    vb.setValue(vb.value() + 300)
                elif k == Qt.Key_PageUp:
                    vb.setValue(vb.value() - 300)
                elif k == Qt.Key_Home:
                    vb.setValue(vb.minimum())
                elif k == Qt.Key_End:
                    vb.setValue(vb.maximum())
                e.accept()
                return

        # Forward keyboard events to the parent (review_screen) so that shortcuts work correctly
        p = self.parent()
        while p and not hasattr(p, "_reveal_current") and not hasattr(p, "_rate"):
            p = p.parent()
        if p and hasattr(p, "keyPressEvent"):
            p.keyPressEvent(e)
        else:
            super().keyPressEvent(e)
        
    def _on_open_mindmap(self, tag=None):
        p = self.parent()
        while p and not hasattr(p, "_toggle_concept_hub") and not hasattr(p, "_open_concept_hub"):
            p = p.parent()
        if p and hasattr(p, "_open_concept_hub"):
            p._open_concept_hub(tag=tag if isinstance(tag, str) else None)

    def _on_sync_deck(self):
        p = self.parent()
        while p and not hasattr(p, "_sync_current_deck_from_source"):
            p = p.parent()
        if p and hasattr(p, "_sync_current_deck_from_source"):
            p._sync_current_deck_from_source()

    def load_card(self, card):
        self.card = card
        self.is_revealed = False
        self._zoom_factor = TextReviewWidget.get_saved_zoom_factor()
        if hasattr(self, "scratchpad"):
            self.scratchpad.clear()
            self.scratchpad.sync_geometry_with_parent()
        
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
            self.lbl_context_badge.setToolTip(f"Topic Context: {anchor} (Click to open Mind-Map)")
            self.lbl_context_badge.setCursor(Qt.PointingHandCursor)
            self.lbl_context_badge.mousePressEvent = lambda e: self._on_open_mindmap(anchor)
            self.lbl_context_badge.show()
        else:
            self.lbl_context_badge.hide()

        chain_order = card.get("chain_order", 0)
        parent_chain = card.get("parent_chain_id")
        if parent_chain or chain_order:
            order_str = f"Step {chain_order}" if chain_order else "Linked Chain"
            self.lbl_chain_badge.setText(f"🔗 {order_str}")
            self.lbl_chain_badge.setToolTip(f"Sequential Linked Card ({order_str} in topic sequence - Click to view chain)")
            self.lbl_chain_badge.setCursor(Qt.PointingHandCursor)
            self.lbl_chain_badge.mousePressEvent = lambda e: self._on_open_mindmap()
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

        # Populate Connected Concept & Tag Pills
        while self.tags_layout.count():
            it = self.tags_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        tags = card.get("tags", []) or []
        related = card.get("related_concepts", []) or []
        has_pills = False

        for t in tags[:5]:
            t_str = str(t).strip()
            if not t_str:
                continue
            btn_t = QPushButton(f"🏷️ {t_str}")
            btn_t.setCursor(Qt.PointingHandCursor)
            btn_t.setToolTip(f"Explore concept web for '{t_str}' (Click to open Mind-Map)")
            btn_t.setStyleSheet("""
                QPushButton {
                    color: #A0AEC0;
                    background: rgba(160, 174, 192, 0.12);
                    border: 1px solid rgba(160, 174, 192, 0.25);
                    border-radius: 4px;
                    padding: 2px 7px;
                    font-size: 10px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background: rgba(160, 174, 192, 0.28);
                    color: #FFFFFF;
                }
            """)
            btn_t.clicked.connect(lambda _, tag=t_str: self._on_open_mindmap(tag))
            self.tags_layout.addWidget(btn_t)
            has_pills = True

        for r in related[:4]:
            r_str = str(r).strip()
            if not r_str:
                continue
            btn_r = QPushButton(f"🌐 {r_str}")
            btn_r.setCursor(Qt.PointingHandCursor)
            btn_r.setToolTip(f"Explore connected concept '{r_str}'")
            btn_r.setStyleSheet("""
                QPushButton {
                    color: #70A5FD;
                    background: rgba(112, 165, 253, 0.12);
                    border: 1px solid rgba(112, 165, 253, 0.3);
                    border-radius: 4px;
                    padding: 2px 7px;
                    font-size: 10px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background: rgba(112, 165, 253, 0.30);
                    color: #FFFFFF;
                }
            """)
            btn_r.clicked.connect(lambda _, rel=r_str: self._on_open_mindmap(rel))
            self.tags_layout.addWidget(btn_r)
            has_pills = True

        if has_pills:
            self.tags_layout.addStretch()
            self.tags_container.show()
        else:
            self.tags_container.hide()
        
        # Reset scroll position to top
        if hasattr(self, "scroll_area") and self.scroll_area.verticalScrollBar() is not None:
            self.scroll_area.verticalScrollBar().setValue(0)

        self._update_scaled_html()
        
        # Clear/Hide answer container
        self.answer_container.hide()
        self.a_browser.clear()
        self.notes_browser.clear()
        self._adjust_browser_heights()
        
    def reveal_answer(self):
        if self.is_revealed:
            return
        self.is_revealed = True
        
        self._update_scaled_html()
        self.answer_container.show()
        self._adjust_browser_heights()
        if hasattr(self, "scratchpad"):
            self.scratchpad.sync_geometry_with_parent()
            self.scratchpad.raise_()
        
    def hide_answer(self):
        if not self.is_revealed:
            return
        self.is_revealed = False
        self.answer_container.hide()
        self.a_browser.clear()
        if hasattr(self, "trap_browser"):
            self.trap_browser.clear()
        if hasattr(self, "trap_container"):
            self.trap_container.hide()
        if hasattr(self, "notes_browser"):
            self.notes_browser.clear()
        if hasattr(self, "notes_container"):
            self.notes_container.hide()
        self._adjust_browser_heights()
        if hasattr(self, "scratchpad"):
            self.scratchpad.sync_geometry_with_parent()
        
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_width_mode()
        self._update_scaled_html()
        self._adjust_browser_heights()
        if hasattr(self, "scratchpad"):
            self.scratchpad.sync_geometry_with_parent()
        
    def _adjust_browser_heights(self):
        import math
        target_w = self._get_max_content_width()
        for browser in (self.q_browser, self.a_browser, getattr(self, "trap_browser", None), getattr(self, "notes_browser", None)):
            if browser is not None:
                browser.document().setTextWidth(target_w)
                doc_layout = browser.document().documentLayout()
                if doc_layout is not None:
                    doc_h = int(math.ceil(doc_layout.documentSize().height()))
                else:
                    doc_h = int(math.ceil(browser.document().size().height()))
                browser.setFixedHeight(max(32, doc_h + 16))
        if hasattr(self, "scratchpad"):
            self.scratchpad.sync_geometry_with_parent()

    def _update_scaled_html(self):
        if not self.card:
            return
            
        target_width = self._get_max_content_width()
        
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
            
        q_font_size = max(18, int(22 * self._zoom_factor))
        a_font_size = max(18, int(21 * self._zoom_factor))
        t_font_size = max(18, int(20 * self._zoom_factor))
        n_font_size = max(18, int(20 * self._zoom_factor))
        title_font_size = max(12, int(14 * self._zoom_factor))
        
        # Update section title headers proportionally
        self.lbl_card_type.setStyleSheet(f"color: {self.badge_color}; font-size: {title_font_size}px; font-weight: bold; letter-spacing: 1.2px; border: none; background: transparent;")
        self.lbl_ans_title.setStyleSheet(f"color: {self.badge_color}; font-size: {title_font_size}px; font-weight: bold; letter-spacing: 1.2px; border: none; background: transparent;")
        self.lbl_trap_title.setStyleSheet(f"color: #FFB86C; font-size: {title_font_size}px; font-weight: bold; letter-spacing: 0.8px; border: none; background: transparent;")
        self.lbl_notes_title.setStyleSheet(f"color: {self.notes_color}; font-size: {title_font_size}px; font-weight: bold; letter-spacing: 0.8px; border: none; background: transparent;")

        # Update fonts & default document stylesheets on browsers based on zoom factor
        for browser, f_size, color in (
            (self.q_browser, q_font_size, front_color),
            (self.a_browser, a_font_size, answer_color),
            (getattr(self, "trap_browser", None), t_font_size, trap_color),
            (getattr(self, "notes_browser", None), n_font_size, notes_color)
        ):
            if browser is not None:
                browser.setFont(QFont(self._font_family, f_size))
                browser.document().setDefaultFont(QFont(self._font_family, f_size))
                browser.document().setDefaultStyleSheet(f"""
                    body, div, p, span, li, td, th, code, pre {{
                        font-family: '{self._font_family}', 'Segoe UI', sans-serif;
                        font-size: {f_size}px;
                        color: {color};
                        line-height: 1.6;
                    }}
                    img {{
                        max-width: 100%;
                        margin-top: 10px;
                        border-radius: 8px;
                    }}
                """)
        
        # Load Question
        question = self.card.get('question', '')
        if "<img" in question or "![" in question or "<html>" in question:
            self._scale_and_load_html(self.q_browser, question, target_width, font_size=q_font_size, default_color=front_color, is_answer=False)
        else:
            question_html = self._format_content(question, is_answer=False, default_color=front_color, font_size=q_font_size)
            self.q_browser.setHtml(question_html)
            
        # Load Answer if revealed
        if self.is_revealed:
            answer = self.card.get("answer", "")
            if "<img" in answer or "![" in answer or "<html>" in answer:
                self._scale_and_load_html(self.a_browser, answer, target_width, font_size=a_font_size, default_color=answer_color, is_answer=True)
            else:
                answer_html = self._format_content(answer, is_answer=True, default_color=answer_color, font_size=a_font_size)
                self.a_browser.setHtml(answer_html)

            # Load Trap Note (if any)
            trap_note = str(self.card.get("trap_note", "") or "").strip()
            if trap_note and hasattr(self, "trap_browser"):
                if "<img" in trap_note or "![" in trap_note or "<html>" in trap_note:
                    self._scale_and_load_html(self.trap_browser, trap_note, target_width, font_size=t_font_size, default_color=trap_color, is_answer=False)
                else:
                    trap_html = self._format_content(trap_note, is_answer=False, default_color=trap_color, font_size=t_font_size)
                    self.trap_browser.setHtml(trap_html)
                self.trap_container.show()
            elif hasattr(self, "trap_container"):
                self.trap_container.hide()
                
            # Load Notes
            notes = str(self.card.get("notes", "") or "").strip()
            # Only show separate notes if it differs from trap_note
            if notes and (not trap_note or notes != trap_note):
                if "<img" in notes or "![" in notes or "<html>" in notes:
                    self._scale_and_load_html(self.notes_browser, notes, target_width, font_size=n_font_size, default_color=notes_color, is_answer=False)
                else:
                    notes_html = self._format_content(notes, is_answer=False, default_color=notes_color, font_size=n_font_size)
                    self.notes_browser.setHtml(notes_html)
                self.notes_container.show()
            else:
                self.notes_container.hide()

        self._adjust_browser_heights()
        
    def _scale_and_load_html(self, browser, html_content, target_width, font_size=19, default_color="#FFFFFF", is_answer=False):
        import re
        import base64
        from PyQt5.QtGui import QPixmap, QImage, QTextDocument, QFont
        from PyQt5.QtCore import QUrl, Qt
        
        # 1. Convert markdown images ![alt](src) to <img> tags
        html_content = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', r'<img src="\1" />', html_content)
        
        # 2. Parse img tags and their src attributes
        img_pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
        sources = img_pattern.findall(html_content)
        
        base_url = get_base_url()
        base_path = ""
        if base_url.isLocalFile():
            base_path = base_url.toLocalFile()
            
        img_dims = {}
        for src in sources:
            pixmap = None
            if src.startswith("data:image"):
                try:
                    comma_idx = src.find(",")
                    if comma_idx != -1:
                        b64_data = src[comma_idx + 1:]
                        raw_bytes = base64.b64decode(b64_data)
                        img = QImage()
                        if img.loadFromData(raw_bytes):
                            pixmap = QPixmap.fromImage(img)
                except Exception:
                    pass
            else:
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
            
            if pixmap and not pixmap.isNull():
                orig_w = pixmap.width()
                if orig_w > 0:
                    if orig_w > target_width:
                        scaled_w = target_width
                    else:
                        if getattr(self, "_zoom_factor", 1.0) != 1.0:
                            scaled_w = min(target_width, max(40, int(orig_w * self._zoom_factor)))
                        else:
                            scaled_w = min(target_width, orig_w)
                    img_dims[src] = scaled_w
                    scaled_pixmap = pixmap.scaledToWidth(scaled_w, Qt.SmoothTransformation)
                    browser.document().addResource(QTextDocument.ImageResource, QUrl(src), scaled_pixmap)
                    if not src.startswith("data:image"):
                        browser.document().addResource(QTextDocument.ImageResource, QUrl.fromLocalFile(abs_path), scaled_pixmap)
                        
        # 3. Clean and size img tags with explicit width attribute bounded by target_width
        def clean_and_size_img_tags(match):
            tag = match.group(0)
            src_m = re.search(r'src=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            src_val = src_m.group(1) if src_m else ""
            w_val = img_dims.get(src_val, target_width)
            return f'<img src="{src_val}" width="{w_val}" style="max-width: 100%; border-radius: 8px; margin: 10px 0;" />'
            
        cleaned = re.compile(r'<img\s+[^>]+>', re.IGNORECASE).sub(clean_and_size_img_tags, html_content)
        
        # 4. Format markdown and syntax if mixed with HTML
        formatted = self._format_content(cleaned, is_answer=is_answer, default_color=default_color, font_size=font_size)
        
        # 5. Set document default font and style sheet so ALL tags inherit
        browser.document().setDefaultFont(QFont(self._font_family, font_size))
        browser.document().setDefaultStyleSheet(f"""
            body, div, p, span, li, td, th, code, pre {{
                font-family: '{self._font_family}', 'Segoe UI', sans-serif;
                font-size: {font_size}px;
                color: {default_color};
                line-height: 1.6;
            }}
            img {{
                max-width: 100%;
                margin-top: 10px;
                border-radius: 8px;
            }}
        """)
        
        browser.setHtml(formatted)
        
    @staticmethod
    def _has_html_markup(text: str) -> bool:
        if not text:
            return False
        import re
        return bool(re.search(r'<(br|b|i|u|p|div|span|strong|em|ul|ol|li|h[1-6]|table|img|font)\b[^>]*>', text, re.IGNORECASE))

    def _format_content(self, text: str, is_answer: bool = False, default_color: str = "#FFFFFF", font_size: int = 20) -> str:
        if not text:
            return ""
        import re
        import html

        formatted = text.strip()

        # 0. Sanitize legacy embedded HTML wrapper & strip hardcoded font sizes/families
        body_match = re.search(r'<body[^>]*>(.*?)</body>', formatted, flags=re.DOTALL | re.IGNORECASE)
        if body_match:
            formatted = body_match.group(1).strip()
        else:
            formatted = re.sub(r'<!DOCTYPE[^>]*>', '', formatted, flags=re.IGNORECASE)
            formatted = re.sub(r'</?(?:html|head|body|meta|style)[^>]*>', '', formatted, flags=re.IGNORECASE)
            formatted = re.sub(r'<head>.*?</head>', '', formatted, flags=re.DOTALL | re.IGNORECASE)

        # Strip hardcoded font-family and font-size from all style attributes
        formatted = re.sub(r'font-family\s*:\s*[^;\'"]+;?', '', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'font-size\s*:\s*[^;\'"]+;?', '', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'style\s*=\s*["\']\s*["\']', '', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'<span>(.*?)</span>', r'\1', formatted, flags=re.DOTALL | re.IGNORECASE)

        # Convert Markdown image ![alt](url) to <img src="url" />
        formatted = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', r'<img src="\1" />', formatted)

        # 1. Convert ==highlight== syntax to <mark> tags
        formatted = re.sub(r'==([^=\n]+)==', r'<mark>\1</mark>', formatted)

        # 2. Convert Markdown bold **text** to <b> tags
        formatted = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', formatted)

        # 3. Convert Markdown italic *text* or _text_ to <i> tags
        formatted = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', formatted)

        # 4. Highlight styling for <mark>...</mark> (Glowing Golden Amber Highlighter)
        mark_style = (
            "background-color: rgba(255, 214, 10, 0.28); "
            "color: #FFE600; "
            "font-weight: 700; "
            "padding: 2px 7px; "
            "border-radius: 4px; "
            "border: 1px solid rgba(255, 214, 10, 0.60);"
        )
        formatted = re.sub(r'<mark>(.*?)</mark>', f'<span style="{mark_style}">\\1</span>', formatted, flags=re.IGNORECASE | re.DOTALL)

        # 5. Crisp Bold Styling
        bold_color = "#50FA7B" if is_answer else "#FFFFFF"
        bold_style = f"color: {bold_color}; font-weight: 700;"
        formatted = re.sub(r'<b>(.*?)</b>', f'<b style="{bold_style}">\\1</b>', formatted, flags=re.IGNORECASE | re.DOTALL)

        # 6. PDF Reference Tag Styling (Cyan/Teal Badge)
        pdf_style = (
            "display: inline-block; "
            "margin-top: 6px; "
            "padding: 3px 10px; "
            "background: rgba(99, 230, 190, 0.16); "
            "color: #63E6BE; "
            "border: 1px solid rgba(99, 230, 190, 0.45); "
            "border-radius: 5px; "
            "font-weight: 600; "
            f"font-size: {font_size}px;"
        )
        formatted = re.sub(
            r'(📖\s*(?:PDF\s*Ref(?:erence)?|Ref(?:erence)?)\s*:[^\n<]+)',
            f'<span style="{pdf_style}">\\1</span>',
            formatted,
            flags=re.IGNORECASE
        )

        # 7. TRAP / Pitfall Note Styling (Alert Red/Coral Badge)
        trap_style = (
            "display: inline-block; "
            "margin-top: 4px; "
            "padding: 3px 10px; "
            "background: rgba(255, 107, 107, 0.16); "
            "color: #FF6B6B; "
            "border: 1px solid rgba(255, 107, 107, 0.45); "
            "border-radius: 5px; "
            "font-weight: 700; "
            f"font-size: {font_size}px;"
        )
        formatted = re.sub(
            r'(\bTRAP\b\s*:[^\n<]+)',
            f'<span style="{trap_style}">⚠️ \\1</span>',
            formatted,
            flags=re.IGNORECASE
        )

        # 8. Mnemonic / Example enhancement
        formatted = re.sub(
            r'<b>\s*(?:💡\s*)?(?:Mnemonics?|Mnemonic Trick|Trick):\s*</b>|(?:\b💡\s*Mnemonics?:)',
            f"<div style='margin-top:14px; margin-bottom:6px; padding:4px 10px; background:rgba(255, 184, 108, 0.16); border-left:3.5px solid #FFB86C; border-radius:5px; font-weight:bold; font-size:{font_size}px; color:#FFB86C;'>💡 Mnemonics:</div>",
            formatted,
            flags=re.IGNORECASE
        )
        formatted = re.sub(
            r'<b>\s*(?:📝\s*)?(?:Examples?|Sample Sentences?):\s*</b>|(?:\b📝\s*Examples?:)',
            f"<div style='margin-top:14px; margin-bottom:6px; padding:4px 10px; background:rgba(80, 250, 123, 0.14); border-left:3.5px solid #50FA7B; border-radius:5px; font-weight:bold; font-size:{font_size}px; color:#50FA7B;'>📝 Example:</div>",
            formatted,
            flags=re.IGNORECASE
        )

        # 9. Handle newlines
        formatted = formatted.replace("\n", "<br>")

        return f"<div style='font-family: {self._font_family}; font-size: {font_size}px; color: {default_color}; line-height: 1.6;'>{formatted}</div>"

    def _escape_and_format(self, text):
        return self._format_content(text)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            angle = e.angleDelta().y()
            if angle > 0:
                self.zoom_in()
            elif angle < 0:
                self.zoom_out()
            e.accept()
        else:
            if hasattr(self, "scroll_area") and self.scroll_area and self.scroll_area.verticalScrollBar():
                self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().value() - e.angleDelta().y()
                )
                e.accept()
                return
            super().wheelEvent(e)

    def event(self, e):
        if e.type() == QEvent.NativeGesture:
            if e.gestureType() == Qt.ZoomNativeGesture:
                factor = 1.0 + e.value()
                self._zoom_factor = max(0.5, min(3.0, round(self._zoom_factor * factor, 2)))
                TextReviewWidget.save_zoom_factor(self._zoom_factor)
                self._update_scaled_html()
                return True
        return super().event(e)

    def zoom_in(self):
        self._zoom_factor = min(round(self._zoom_factor + 0.1, 2), 3.0)
        TextReviewWidget.save_zoom_factor(self._zoom_factor)
        self._update_scaled_html()

    def zoom_out(self):
        self._zoom_factor = max(round(self._zoom_factor - 0.1, 2), 0.5)
        TextReviewWidget.save_zoom_factor(self._zoom_factor)
        self._update_scaled_html()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        TextReviewWidget.save_zoom_factor(self._zoom_factor)
        self._update_scaled_html()

class ScratchpadOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)
        self.strokes = []
        self.redo_stack = []
        self.current_stroke = []
        self.active_color = QColor("#FF4444")
        self.active_width = 2.0
        self.mode = "pen"  # "pen" or "eraser"
        if parent is not None:
            try:
                parent.installEventFilter(self)
            except Exception:
                pass
            self.sync_geometry_with_parent()

    def setParent(self, parent):
        old_p = self.parent()
        if old_p is not None:
            try:
                old_p.removeEventFilter(self)
            except Exception:
                pass
        super().setParent(parent)
        if parent is not None:
            try:
                parent.installEventFilter(self)
            except Exception:
                pass
            self.sync_geometry_with_parent()

    def eventFilter(self, obj, event):
        if obj == self.parent() and event.type() == QEvent.Resize:
            self.sync_geometry_with_parent()
        return super().eventFilter(obj, event)

    def sync_geometry_with_parent(self):
        p = self.parent()
        if p is not None:
            self.setGeometry(0, 0, p.width(), p.height())
        
    def set_pen_active(self, active, mode="pen"):
        self.mode = mode
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not active)
        self.setVisible(True)
        if active:
            self.raise_()
            if mode == "eraser":
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)
            self.update()
        else:
            self.setCursor(Qt.ArrowCursor)

    def undo(self):
        if self.strokes:
            self.redo_stack.append(self.strokes.pop())
            self.update()
            return True
        return False

    def redo(self):
        if self.redo_stack:
            self.strokes.append(self.redo_stack.pop())
            self.update()
            return True
        return False

    def has_undo(self):
        return bool(self.strokes)

    def has_redo(self):
        return bool(self.redo_stack)

    def wheelEvent(self, e):
        # 1. Forward Ctrl+Wheel to parent/ancestor for zoom in/out
        if e.modifiers() & Qt.ControlModifier:
            p = self.parent()
            while p and not hasattr(p, "zoom_in") and not hasattr(p, "wheelEvent"):
                p = p.parent()
            if p:
                if hasattr(p, "zoom_in") and hasattr(p, "zoom_out"):
                    if e.angleDelta().y() > 0:
                        p.zoom_in()
                    elif e.angleDelta().y() < 0:
                        p.zoom_out()
                    e.accept()
                    return
                elif hasattr(p, "wheelEvent"):
                    p.wheelEvent(e)
                    e.accept()
                    return

        # 2. Forward vertical wheel scrolling to QScrollArea
        p = self.parent()
        sa = None
        while p:
            if hasattr(p, "scroll_area") and p.scroll_area:
                sa = p.scroll_area
                break
            if isinstance(p, QScrollArea):
                sa = p
                break
            p = p.parent()

        if sa and sa.verticalScrollBar():
            sa.verticalScrollBar().setValue(sa.verticalScrollBar().value() - e.angleDelta().y())
            e.accept()
            return
        e.ignore()
            
    def clear(self):
        self.strokes = []
        self.redo_stack = []
        self.current_stroke = []
        self.update()

    def erase_at(self, pos, radius=24):
        new_strokes = []
        changed = False
        for s in self.strokes:
            keep = True
            for pt in s.get("points", []):
                if (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= radius ** 2:
                    keep = False
                    changed = True
                    break
            if keep:
                new_strokes.append(s)
        if changed:
            self.strokes = new_strokes
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
        if e.button() == Qt.RightButton:
            p = self.parent()
            while p and not hasattr(p, "_toggle_chrome"):
                p = p.parent()
            if p and hasattr(p, "_toggle_chrome"):
                p._toggle_chrome()
                e.accept()
                return
        if e.button() == Qt.LeftButton:
            if self.mode == "eraser":
                self.erase_at(e.pos())
            else:
                self.current_stroke = [e.pos()]
            self.update()
            e.accept()
        else:
            e.ignore()
            
    def mouseMoveEvent(self, e):
        if self.mode == "eraser" and (e.buttons() & Qt.LeftButton):
            self.erase_at(e.pos())
            e.accept()
        elif self.current_stroke:
            self.current_stroke.append(e.pos())
            self.update()
            e.accept()
        else:
            e.ignore()
            
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.mode != "eraser" and self.current_stroke:
                self.strokes.append({
                    "color": QColor(self.active_color),
                    "width": self.active_width,
                    "points": self.current_stroke
                })
                self.current_stroke = []
                self.redo_stack.clear()
            self.update()
            e.accept()
        else:
            e.ignore()
