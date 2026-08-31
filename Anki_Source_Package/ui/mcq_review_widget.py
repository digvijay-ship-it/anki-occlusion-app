# -*- coding: utf-8 -*-
import os
import re
import html
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextBrowser, QFrame, QApplication, QScrollArea,
    QPushButton, QSizePolicy, QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QUrl, QEvent
from PyQt5.QtGui import QFont, QColor, QPalette, QKeySequence, QPixmap, QTextDocument
from theme_manager import get_palette
from ui.text_review_widget import ZoomableTextBrowser, ScratchpadOverlay, get_base_url


class AutoFitTextBrowser(ZoomableTextBrowser):
    """Text browser that dynamically matches document height with zero internal scrollbars."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.document().setDocumentMargin(0)
        self._adjusting = False
        self.document().documentLayout().documentSizeChanged.connect(self._adjust_height)

    def _adjust_height(self):
        if self._adjusting:
            return
        self._adjusting = True
        try:
            w = self.viewport().width()
            if w > 10:
                self.document().setTextWidth(w)
            h = int(self.document().documentLayout().documentSize().height())
            if h > 0 and abs(self.height() - (h + 8)) > 2:
                self.setFixedHeight(h + 8)
        finally:
            self._adjusting = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adjust_height()


class OptionButton(QPushButton):
    """Interactive Exam Option Button with Letter Badge and Status Pill."""
    def __init__(self, label: str, text: str, index: int = 0, parent=None):
        super().__init__(parent)
        self.option_label = label  # e.g., 'A', 'B', 'C', 'D'
        self.option_text = text
        self.option_index = index
        self.is_correct = False
        self.is_selected = False
        self.stat_text = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(42)
        self.setFocusPolicy(Qt.NoFocus)

        self._setup_ui()

    def _setup_ui(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 6, 12, 6)
        self.layout.setSpacing(10)

        # 1. Option Letter Badge (e.g. [ A ])
        self.lbl_badge = QLabel(f"{self.option_label}")
        self.lbl_badge.setAlignment(Qt.AlignCenter)
        self.lbl_badge.setFixedSize(26, 26)
        self.lbl_badge.setStyleSheet("""
            background: rgba(255, 255, 255, 0.08);
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 13px;
            font-weight: bold;
            font-size: 12px;
        """)
        self.layout.addWidget(self.lbl_badge)

        # 2. Option Text
        self.lbl_text = QLabel(self.option_text)
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setTextInteractionFlags(Qt.NoTextInteraction)
        self.lbl_text.setStyleSheet("color: #E2E8F0; font-size: 14px; font-weight: 500; background: transparent; border: none;")
        self.layout.addWidget(self.lbl_text, stretch=1)

        # 3. Status Pill / Icon (Hidden initially, shown after selection/reveal)
        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFixedHeight(22)
        self.lbl_status.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 7px; border-radius: 4px; background: transparent;")
        self.lbl_status.hide()
        self.layout.addWidget(self.lbl_status)
        self.apply_idle_style()

    @property
    def label(self):
        return self.option_label

    @property
    def text_content(self):
        return self.option_text

    @property
    def status_pill(self):
        return self.lbl_status

    def apply_idle_style(self, theme="classic"):
        p = get_palette(theme)
        accent = p.get("C_ACCENT", "#5C7CFA")
        card_bg = p.get("C_SURFACE", "#1E2333")
        border = p.get("C_BORDER", "#374158")

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {card_bg};
                border: 1.5px solid {border};
                border-radius: 8px;
                text-align: left;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: rgba(92, 124, 250, 0.12);
                border-color: {accent};
            }}
        """)
        self.lbl_badge.setStyleSheet("""
            background: rgba(255, 255, 255, 0.08);
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 13px;
            font-weight: bold;
            font-size: 12px;
        """)
        self.lbl_status.hide()

    def apply_correct_style(self, stat_text=""):
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(46, 204, 113, 0.18);
                border: 2px solid #2ECC71;
                border-radius: 8px;
                text-align: left;
                padding: 0;
            }
        """)
        self.lbl_badge.setStyleSheet("""
            background: #2ECC71;
            color: #0F172A;
            border: 1px solid #2ECC71;
            border-radius: 13px;
            font-weight: bold;
            font-size: 12px;
        """)
        if stat_text:
            self.lbl_status.setText(f"✓ {stat_text}")
        else:
            self.lbl_status.setText("✓ Correct Answer")
        self.lbl_status.setStyleSheet("""
            background: rgba(46, 204, 113, 0.25);
            color: #2ECC71;
            border: 1px solid #2ECC71;
            font-size: 11px;
            font-weight: bold;
            padding: 2px 7px;
            border-radius: 4px;
        """)
        self.lbl_status.show()

    def apply_incorrect_style(self):
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(239, 68, 68, 0.18);
                border: 2px solid #EF4444;
                border-radius: 8px;
                text-align: left;
                padding: 0;
            }
        """)
        self.lbl_badge.setStyleSheet("""
            background: #EF4444;
            color: #FFFFFF;
            border: 1px solid #EF4444;
            border-radius: 13px;
            font-weight: bold;
            font-size: 12px;
        """)
        self.lbl_status.setText("✕ Your Attempt")
        self.lbl_status.setStyleSheet("""
            background: rgba(239, 68, 68, 0.25);
            color: #EF4444;
            border: 1px solid #EF4444;
            font-size: 11px;
            font-weight: bold;
            padding: 2px 7px;
            border-radius: 4px;
        """)
        self.lbl_status.show()

    def apply_faded_style(self):
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                opacity: 0.6;
                padding: 0;
            }
        """)
        self.lbl_text.setStyleSheet("color: #718096; font-size: 14px; font-weight: 400; background: transparent; border: none;")
        self.lbl_badge.setStyleSheet("""
            background: rgba(255, 255, 255, 0.04);
            color: #718096;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 13px;
            font-weight: bold;
            font-size: 12px;
        """)
        self.lbl_status.hide()


class MCQReviewWidget(QWidget):
    """
    Full-featured Interactive Exam Paper / MCQ Review Widget.
    Provides:
    - Live Question display with 4 clickable options (A, B, C, D)
    - Keyboard shortcuts: A, B, C, D / 1, 2, 3, 4
    - Instant visual feedback: Green (Correct) / Red (Incorrect attempt) + Correct green highlight
    - Deep Testbook Exam Solution: Statement, Key Points, Additional Info, Important Points
    - Spaced Repetition (SM-2) integration signal
    """
    answer_submitted = pyqtSignal()
    option_selected = pyqtSignal(str, bool)  # (selected_label, is_correct)
    _stored_zoom_factor = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card = None
        self.is_revealed = False
        self.selected_label = None
        self._zoom_factor = getattr(MCQReviewWidget, "_stored_zoom_factor", 1.0)
        self._option_buttons = []

        self._setup_ui()
        self.scratchpad = ScratchpadOverlay(self)
        self.scratchpad.setGeometry(self.rect())

    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        self._theme_p = p

        self._font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        self._header_font_family = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")

        self.setStyleSheet(f"""
            QWidget {{ background: transparent; color: #FFFFFF; font-family: {self._font_family}; }}
        """)

        # Main Layout with Scroll Area
        main_l = QVBoxLayout(self)
        main_l.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent;")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        content_l = QVBoxLayout(self.scroll_content)
        content_l.setContentsMargins(20, 10, 20, 20)
        content_l.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # Centered Container Card
        self.card_frame = QFrame()
        self.card_frame.setObjectName("mcq_card_frame")
        self.card_frame.setMaximumWidth(980)
        self.card_frame.setMinimumWidth(360)
        self.card_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        accent = p.get("C_ACCENT", "#5C7CFA")
        surface = p.get("C_SURFACE", "#1E2333")
        border = p.get("C_BORDER", "#374158")

        self.card_frame.setStyleSheet(f"""
            QFrame#mcq_card_frame {{
                background-color: {surface};
                border: 1.5px solid {border};
                border-radius: 12px;
            }}
        """)

        card_inner_l = QVBoxLayout(self.card_frame)
        card_inner_l.setContentsMargins(18, 14, 18, 18)
        card_inner_l.setSpacing(10)
        card_inner_l.setAlignment(Qt.AlignTop)

        # ── 1. Top Badges Header Bar (Compact single row) ──
        self.hdr_bar = QWidget()
        self.hdr_bar.setFixedHeight(28)
        self.hdr_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hdr_layout = QHBoxLayout(self.hdr_bar)
        self.hdr_layout.setContentsMargins(0, 0, 0, 0)
        self.hdr_layout.setSpacing(6)

        self.lbl_section_badge = QLabel("📌 General Awareness")
        self.lbl_section_badge.setFixedHeight(24)
        self.lbl_section_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_section_badge.setStyleSheet(f"""
            color: {accent};
            background: rgba(92, 124, 250, 0.15);
            border: 1px solid {accent};
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.hdr_layout.addWidget(self.lbl_section_badge)

        self.lbl_qnum_badge = QLabel("🔢 Question")
        self.lbl_qnum_badge.setFixedHeight(24)
        self.lbl_qnum_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_qnum_badge.setStyleSheet("""
            color: #FFD700;
            background: rgba(255, 215, 0, 0.15);
            border: 1px solid #FFD700;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.hdr_layout.addWidget(self.lbl_qnum_badge)

        self.lbl_tier_badge = QLabel("🔥 80/20 CORE")
        self.lbl_tier_badge.setFixedHeight(24)
        self.lbl_tier_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_tier_badge.setStyleSheet("""
            color: #FFB86C;
            background: rgba(255, 184, 108, 0.15);
            border: 1px solid #FFB86C;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_tier_badge.hide()
        self.hdr_layout.addWidget(self.lbl_tier_badge)

        self.lbl_marks_badge = QLabel("")
        self.lbl_marks_badge.setFixedHeight(24)
        self.lbl_marks_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_marks_badge.setStyleSheet("""
            color: #A0AEC0;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_marks_badge.hide()
        self.hdr_layout.addWidget(self.lbl_marks_badge)

        self.lbl_time_badge = QLabel("")
        self.lbl_time_badge.setFixedHeight(24)
        self.lbl_time_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_time_badge.setStyleSheet("""
            color: #8BE9FD;
            background: rgba(139, 233, 253, 0.12);
            border: 1px solid #8BE9FD;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_time_badge.hide()
        self.hdr_layout.addWidget(self.lbl_time_badge)

        self.hdr_layout.addStretch(1)

        self.lbl_accuracy_stat = QLabel("")
        self.lbl_accuracy_stat.setFixedHeight(24)
        self.lbl_accuracy_stat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_accuracy_stat.setStyleSheet("""
            color: #2ECC71;
            background: rgba(46, 204, 113, 0.15);
            border: 1px solid #2ECC71;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_accuracy_stat.hide()
        self.hdr_layout.addWidget(self.lbl_accuracy_stat)

        # Font Size Controls Toolbar (A- / 100% / A+)
        self.font_controls = QWidget()
        self.font_controls.setFixedHeight(24)
        fc_layout = QHBoxLayout(self.font_controls)
        fc_layout.setContentsMargins(0, 0, 0, 0)
        fc_layout.setSpacing(2)

        self.btn_font_dec = QPushButton("A-")
        self.btn_font_dec.setToolTip("Decrease Font Size (Ctrl + -)")
        self.btn_font_dec.setFixedSize(26, 24)
        self.btn_font_dec.setCursor(Qt.PointingHandCursor)
        self.btn_font_dec.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.08);
                color: #E2E8F0;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: rgba(92, 124, 250, 0.25);
                border-color: {accent};
                color: #FFFFFF;
            }}
        """)
        self.btn_font_dec.clicked.connect(self.zoom_out)
        fc_layout.addWidget(self.btn_font_dec)

        self.btn_font_reset = QPushButton(f"{int(self._zoom_factor * 100)}%")
        self.btn_font_reset.setToolTip("Reset Font Size (Ctrl + 0)")
        self.btn_font_reset.setFixedHeight(24)
        self.btn_font_reset.setMinimumWidth(38)
        self.btn_font_reset.setCursor(Qt.PointingHandCursor)
        self.btn_font_reset.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: #A0AEC0;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
                padding: 0 4px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.15);
                color: #FFFFFF;
            }}
        """)
        self.btn_font_reset.clicked.connect(self.zoom_reset)
        fc_layout.addWidget(self.btn_font_reset)

        self.btn_font_inc = QPushButton("A+")
        self.btn_font_inc.setToolTip("Increase Font Size (Ctrl + +)")
        self.btn_font_inc.setFixedSize(26, 24)
        self.btn_font_inc.setCursor(Qt.PointingHandCursor)
        self.btn_font_inc.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.08);
                color: #E2E8F0;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: rgba(92, 124, 250, 0.25);
                border-color: {accent};
                color: #FFFFFF;
            }}
        """)
        self.btn_font_inc.clicked.connect(self.zoom_in)
        fc_layout.addWidget(self.btn_font_inc)

        self.hdr_layout.addWidget(self.font_controls)

        card_inner_l.addWidget(self.hdr_bar)

        # ── 2. Question Browser (High-contrast, auto-fit height) ──
        self.q_browser = AutoFitTextBrowser()
        self.q_browser.setOpenExternalLinks(True)
        self.q_browser.setFont(QFont(self._font_family, 18))
        self.q_browser.document().setDefaultStyleSheet("img { max-width: 100%; border-radius: 6px; }")
        card_inner_l.addWidget(self.q_browser)

        # ── 3. Options Container (A, B, C, D) ──
        self.options_container = QWidget()
        self.options_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.options_layout = QVBoxLayout(self.options_container)
        self.options_layout.setContentsMargins(0, 2, 0, 2)
        self.options_layout.setSpacing(8)
        card_inner_l.addWidget(self.options_container)

        # ── 4. Solution Section (Revealed on choice or space) ──
        self.solution_container = QWidget()
        self.solution_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.solution_layout = QVBoxLayout(self.solution_container)
        self.solution_layout.setContentsMargins(0, 6, 0, 0)
        self.solution_layout.setSpacing(8)

        # Solution Divider
        sol_sep = QFrame()
        sol_sep.setFrameShape(QFrame.HLine)
        sol_sep.setFixedHeight(1)
        sol_sep.setStyleSheet(f"background: {border}; border: none;")
        self.solution_layout.addWidget(sol_sep)

        # Solution Header Tab Banner
        sol_hdr_row = QHBoxLayout()
        sol_hdr_row.setContentsMargins(0, 0, 0, 0)
        lbl_sol_title = QLabel("📑 Detailed Solution")
        lbl_sol_title.setStyleSheet("""
            color: #5C7CFA;
            font-size: 13px;
            font-weight: bold;
            letter-spacing: 0.5px;
            padding-bottom: 2px;
        """)
        sol_hdr_row.addWidget(lbl_sol_title)
        sol_hdr_row.addStretch(1)
        self.solution_layout.addLayout(sol_hdr_row)

        # Solution Content Browser (auto-fit height)
        self.sol_browser = AutoFitTextBrowser()
        self.sol_browser.setOpenExternalLinks(True)
        self.sol_browser.setFont(QFont(self._font_family, 14))
        self.sol_browser.document().setDefaultStyleSheet("img { max-width: 100%; border-radius: 6px; }")
        self.solution_layout.addWidget(self.sol_browser)

        card_inner_l.addWidget(self.solution_container)
        self.solution_container.hide()

        content_l.addWidget(self.card_frame)
        content_l.addSpacing(140)
        self.scroll_area.setWidget(self.scroll_content)
        main_l.addWidget(self.scroll_area)

    def load_card(self, card: dict):
        self.card = card
        self.is_revealed = False
        self.selected_label = None

        if hasattr(self, "scratchpad"):
            self.scratchpad.clear()

        self.q_browser.document().setBaseUrl(get_base_url())
        self.sol_browser.document().setBaseUrl(get_base_url())

        # Badges
        exam_meta = card.get("exam_meta", {}) or {}
        section = card.get("context_anchor") or exam_meta.get("section") or "General Awareness"
        self.lbl_section_badge.setText(f"📌 {section}")

        q_no = exam_meta.get("question_no") or card.get("chain_order") or ""
        if q_no:
            self.lbl_qnum_badge.setText(f"🔢 Q{q_no}")
            self.lbl_qnum_badge.show()
        else:
            self.lbl_qnum_badge.hide()

        p_tier = card.get("priority_tier", 1)
        if p_tier == 1:
            self.lbl_tier_badge.setText("🔥 80/20 CORE")
            self.lbl_tier_badge.show()
        elif p_tier == 2:
            self.lbl_tier_badge.setText("⚡ 80/20 DETAIL")
            self.lbl_tier_badge.show()
        else:
            self.lbl_tier_badge.hide()

        marks = exam_meta.get("marks")
        if marks is not None and str(marks).strip():
            self.lbl_marks_badge.setText(f"⭐ Marks: {marks}")
            self.lbl_marks_badge.show()
        else:
            self.lbl_marks_badge.hide()

        avg_time = exam_meta.get("avg_time_raw")
        if avg_time:
            self.lbl_time_badge.setText(f"⏱️ Avg: {avg_time}")
            self.lbl_time_badge.show()
        else:
            self.lbl_time_badge.hide()

        acc_stat = card.get("percent_answered_correctly") or ""
        if acc_stat:
            self.lbl_accuracy_stat.setText(f"📊 {acc_stat}")
            self.lbl_accuracy_stat.show()
        else:
            self.lbl_accuracy_stat.hide()

        # Build Options
        self._build_options(card)

        # Render Question Text
        self._render_question_html()

        # Hide Solution
        self.solution_container.hide()
        self.sol_browser.clear()

        # Scroll to top
        self.scroll_area.verticalScrollBar().setValue(0)

    def _build_options(self, card: dict):
        # Clear existing buttons
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._option_buttons = []
        options = card.get("options", []) or []

        # Find correct option label
        correct_lbl = None
        c_opt = card.get("correct_option")
        if isinstance(c_opt, dict):
            correct_lbl = c_opt.get("label")
        elif isinstance(c_opt, str):
            correct_lbl = c_opt.strip()

        for idx, opt in enumerate(options):
            if isinstance(opt, dict):
                label = opt.get("label") or chr(65 + idx)
                text = opt.get("text") or ""
                is_correct = bool(opt.get("is_correct"))
                if not is_correct and correct_lbl and label.upper() == correct_lbl.upper():
                    is_correct = True
            else:
                label = chr(65 + idx)
                text = str(opt)
                is_correct = (correct_lbl and label.upper() == correct_lbl.upper())

            btn = OptionButton(label, text, idx, parent=self.options_container)
            btn.is_correct = is_correct
            btn.stat_text = card.get("percent_answered_correctly", "")
            btn.clicked.connect(lambda checked, l=label, b=btn: self.select_option(l))
            self.options_layout.addWidget(btn)
            self._option_buttons.append(btn)

        self._update_options_font()

    def select_option(self, label: str):
        """User chose an option button or pressed keyboard key A/B/C/D."""
        if self.is_revealed:
            return

        self.selected_label = label
        is_user_correct = False

        for btn in self._option_buttons:
            if btn.option_label.upper() == label.upper():
                btn.is_selected = True
                if btn.is_correct:
                    is_user_correct = True
                    btn.apply_correct_style(btn.stat_text)
                else:
                    btn.apply_incorrect_style()
            elif btn.is_correct:
                btn.apply_correct_style(btn.stat_text)
            else:
                btn.apply_faded_style()

        self.reveal_answer()
        self.option_selected.emit(label, is_user_correct)
        self.answer_submitted.emit()

    def reveal_answer(self):
        """Reveal solution and show correct option highlight."""
        if self.is_revealed:
            return
        self.is_revealed = True

        # Ensure correct option is highlighted if user didn't pick an option
        for btn in self._option_buttons:
            if btn.is_correct:
                btn.apply_correct_style(btn.stat_text)
            elif not btn.is_selected:
                btn.apply_faded_style()

        # Render Solution HTML
        self._render_solution_html()
        self.solution_container.show()

    def keyPressEvent(self, e):
        # 1. Font Zoom shortcuts: Ctrl + Plus, Ctrl + Minus, Ctrl + 0
        if e.modifiers() & Qt.ControlModifier:
            if e.key() in (Qt.Key_Plus, Qt.Key_Equal):
                self.zoom_in()
                e.accept()
                return
            elif e.key() in (Qt.Key_Minus, Qt.Key_Underscore):
                self.zoom_out()
                e.accept()
                return
            elif e.key() == Qt.Key_0:
                self.zoom_reset()
                e.accept()
                return

        # 2. Keyboard Option shortcuts: A, B, C, D or 1, 2, 3, 4
        if not self.is_revealed:
            key_map = {
                Qt.Key_A: "A",
                Qt.Key_B: "B",
                Qt.Key_C: "C",
                Qt.Key_D: "D",
                Qt.Key_1: "A",
                Qt.Key_2: "B",
                Qt.Key_3: "C",
                Qt.Key_4: "D",
            }
            if e.key() in key_map:
                lbl = key_map[e.key()]
                self.select_option(lbl)
                e.accept()
                return

        # Forward space and rating keys to review_screen
        p = self.parent()
        while p and not hasattr(p, "_reveal_current") and not hasattr(p, "_rate"):
            p = p.parent()
        if p and hasattr(p, "keyPressEvent"):
            p.keyPressEvent(e)
        else:
            super().keyPressEvent(e)

    def _scale_images_in_html(self, html_text: str, zoom_factor: float = 1.0) -> str:
        """Scales all img tags (including Base64 and local paths) directly proportional to zoom factor."""
        if not html_text:
            return ""

        import re
        import base64
        from PyQt5.QtGui import QImage, QPixmap

        if not hasattr(self, "_dim_cache"):
            self._dim_cache = {}
        dim_cache = self._dim_cache

        def repl_img(match):
            full_tag = match.group(0)
            src_match = re.search(r'src=["\']([^"\']+)["\']', full_tag, re.IGNORECASE)
            if not src_match:
                return full_tag
            src = src_match.group(1)

            w = dim_cache.get(src)
            if w is None:
                w = 0
                if src.startswith("data:image"):
                    try:
                        comma_idx = src.find(",")
                        if comma_idx != -1:
                            b64_data = src[comma_idx + 1:]
                            raw_bytes = base64.b64decode(b64_data)
                            img = QImage()
                            if img.loadFromData(raw_bytes):
                                w = img.width()
                    except Exception:
                        pass
                elif os.path.isabs(src) and os.path.exists(src):
                    pix = QPixmap(src)
                    if not pix.isNull():
                        w = pix.width()

                if w <= 0:
                    w = 340
                dim_cache[src] = w

            scaled_w = max(60, min(920, int(w * zoom_factor * 1.35)))
            return f'<img width="{scaled_w}" src="{src}" style="max-width: 100%; border-radius: 6px; background: white; padding: 4px; border: 1px solid rgba(255,255,255,0.15); margin: 6px 0;" />'

        html_text = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', r'<img src="\1" />', html_text)
        return re.sub(r'<img\s+[^>]+>', repl_img, html_text, flags=re.IGNORECASE)

    def _render_question_html(self):
        if not self.card:
            return

        q_text = self.card.get("question_html") or self.card.get("question", "")
        q_font_size = int(18 * self._zoom_factor)

        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        text_color = p.get("C_TEXT", "#FFFFFF")

        q_text_scaled = self._scale_images_in_html(q_text, self._zoom_factor)

        doc_css = f"""
            p, div {{ margin: 4px 0; padding: 0; line-height: 1.45; }}
            img {{ max-width: 100%; height: auto; border-radius: 6px; margin: 4px 0; }}
            p, div, span, li, td, th, label, font, b, strong {{ color: {text_color} !important; }}
        """
        self.q_browser.document().setDefaultStyleSheet(doc_css)
        formatted_q = self._format_exam_html(q_text_scaled, text_color, q_font_size)
        self.q_browser.setFont(QFont(self._font_family, q_font_size))
        self.q_browser.setHtml(formatted_q)
        self.q_browser._adjust_height()

    def _render_solution_html(self):
        if not self.card:
            return

        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)

        text_color = p.get("C_TEXT", "#FFFFFF")
        subtext_color = p.get("C_SUBTEXT", "#A0AEC0")
        accent = p.get("C_ACCENT", "#5C7CFA")
        sol_font_size = int(14 * self._zoom_factor)

        sol_data = self.card.get("solution_data", {}) or {}
        sol_html_raw = sol_data.get("html") or self.card.get("detailed_solution") or self.card.get("explanation") or ""
        sol_text = sol_data.get("text") or ""
        statement = sol_data.get("statement") or ""
        key_points = sol_data.get("key_points", []) or []
        additional_info = sol_data.get("additional_info", []) or []
        important_points = sol_data.get("important_points", []) or []

        # Fallback if solution_data empty
        if not statement and not key_points and not sol_html_raw:
            answer = self.card.get("answer", "")
            notes = self.card.get("notes", "")
            trap = self.card.get("trap_note", "")
            statement = f"The correct answer is {answer}." if answer else ""
            if notes:
                key_points = [line.strip().lstrip("•*- ") for line in notes.split("\n") if line.strip()]
            if trap and trap != notes:
                important_points = [trap]

        html_blocks = []

        # 1. Statement Banner
        if statement:
            html_blocks.append(f"""
                <div style="background-color: rgba(46, 204, 113, 0.14); border-left: 4px solid #2ECC71; border-radius: 6px; padding: 10px 14px; margin-bottom: 10px;">
                    <div style="color: #2ECC71 !important; font-size: {sol_font_size + 1}px; font-weight: bold; line-height: 1.4;">
                        {html.escape(statement)}
                    </div>
                </div>
            """)

        # 2. Rich Solution Content (HTML / Base64 Diagrams / Logic text)
        if sol_html_raw:
            formatted_sol = sol_html_raw
            # Strip inline hardcoded dark colors and backgrounds from Testbook
            formatted_sol = re.sub(r'style="[^"]*color:\s*[^;"]+;?[^"]*"', '', formatted_sol, flags=re.IGNORECASE)
            formatted_sol = re.sub(r'style="[^"]*background[^;"]*;?[^"]*"', '', formatted_sol, flags=re.IGNORECASE)
            formatted_sol = re.sub(r'color="[^"]*"', '', formatted_sol, flags=re.IGNORECASE)

            # Scale all images dynamically with zoom factor
            formatted_sol = self._scale_images_in_html(formatted_sol, self._zoom_factor)

            # Clean extra spacing & newlines without inserting double breaks
            if "<p" not in formatted_sol and "<div" not in formatted_sol and "<br" not in formatted_sol:
                formatted_sol = formatted_sol.replace("\n", "<br>")
            else:
                formatted_sol = re.sub(r'(\s*<br\s*/?>\s*){2,}', '<br>', formatted_sol, flags=re.IGNORECASE)
                formatted_sol = re.sub(r'<p>\s*<br\s*/?>\s*</p>', '', formatted_sol, flags=re.IGNORECASE)
                formatted_sol = re.sub(r'<p>\s*</p>', '', formatted_sol, flags=re.IGNORECASE)

            html_blocks.append(f"""
                <div style="background-color: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; color: {text_color} !important; font-size: {sol_font_size}px; line-height: 1.5;">
                    {formatted_sol}
                </div>
            """)

        # 3. Key Points Section
        if key_points:
            kp_items = "".join([f"<li style='margin-bottom: 6px; line-height: 1.45; color: {text_color} !important;'>{html.escape(str(pt))}</li>" for pt in key_points])
            html_blocks.append(f"""
                <div style="background-color: rgba(92, 124, 250, 0.08); border-left: 4px solid #5C7CFA; border-radius: 6px; padding: 12px 16px; margin-bottom: 10px;">
                    <div style="color: #5C7CFA !important; font-size: {sol_font_size}px; font-weight: bold; margin-bottom: 6px;">
                        🔑 Key Points
                    </div>
                    <ul style="color: {text_color} !important; font-size: {sol_font_size}px; margin: 0; padding-left: 18px;">
                        {kp_items}
                    </ul>
                </div>
            """)

        # 4. Additional Information Section
        if additional_info:
            ai_items = "".join([f"<li style='margin-bottom: 5px; line-height: 1.4; color: {subtext_color} !important;'>{html.escape(str(info))}</li>" for info in additional_info])
            html_blocks.append(f"""
                <div style="background-color: rgba(139, 233, 253, 0.08); border-left: 4px solid #8BE9FD; border-radius: 6px; padding: 12px 16px; margin-bottom: 10px;">
                    <div style="color: #8BE9FD !important; font-size: {sol_font_size}px; font-weight: bold; margin-bottom: 6px;">
                        📝 Additional Information
                    </div>
                    <ul style="color: {subtext_color} !important; font-size: {sol_font_size}px; margin: 0; padding-left: 18px;">
                        {ai_items}
                    </ul>
                </div>
            """)

        # 5. Important Points / Chronology Section
        if important_points:
            ip_items = "".join([f"<li style='margin-bottom: 5px; line-height: 1.4; color: {text_color} !important;'>{html.escape(str(ip))}</li>" for ip in important_points])
            html_blocks.append(f"""
                <div style="background-color: rgba(255, 184, 108, 0.08); border-left: 4px solid #FFB86C; border-radius: 6px; padding: 12px 16px; margin-bottom: 10px;">
                    <div style="color: #FFB86C !important; font-size: {sol_font_size}px; font-weight: bold; margin-bottom: 6px;">
                        📌 Important Points
                    </div>
                    <ul style="color: {text_color} !important; font-size: {sol_font_size}px; margin: 0; padding-left: 18px;">
                        {ip_items}
                    </ul>
                </div>
            """)

        full_sol_html = f"""
            <div style="color: {text_color} !important; font-family: {self._font_family}; font-size: {sol_font_size}px; line-height: 1.55;">
                {"".join(html_blocks)}
            </div>
        """

        doc_css = f"""
            p, div {{ margin: 4px 0; padding: 0; line-height: 1.45; }}
            img {{ max-width: 100%; height: auto; border-radius: 6px; margin: 4px 0; }}
            p, div, span, li, td, th, label, font, b, strong {{ color: {text_color} !important; }}
            table {{ border-collapse: collapse; margin: 6px 0; }}
            th, td {{ border: 1px solid #4A5568; padding: 4px 8px; color: {text_color} !important; }}
        """
        self.sol_browser.document().setDefaultStyleSheet(doc_css)
        self.sol_browser.setFont(QFont(self._font_family, sol_font_size))
        self.sol_browser.setHtml(full_sol_html)
        self.sol_browser._adjust_height()

    def _format_exam_html(self, text, color, font_size):
        if not text:
            return ""
        if "<p" in text or "<div" in text or "<br" in text:
            return f"<div style='color: {color} !important; font-size: {font_size}px; font-weight: 600; line-height: 1.45;'>{text}</div>"
        escaped = html.escape(text).replace("\n", "<br>")
        return f"<div style='color: {color} !important; font-size: {font_size}px; font-weight: 600; line-height: 1.45;'>{escaped}</div>"

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "scratchpad"):
            self.scratchpad.setGeometry(self.rect())
        if hasattr(self, "q_browser"):
            self.q_browser._adjust_height()
        if hasattr(self, "sol_browser"):
            self.sol_browser._adjust_height()

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

    def zoom_in(self):
        self._zoom_factor = min(2.5, round(self._zoom_factor + 0.1, 2))
        self._apply_zoom()

    def zoom_out(self):
        self._zoom_factor = max(0.6, round(self._zoom_factor - 0.1, 2))
        self._apply_zoom()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._apply_zoom()

    def _apply_zoom(self):
        MCQReviewWidget._stored_zoom_factor = self._zoom_factor
        if hasattr(self, "btn_font_reset"):
            self.btn_font_reset.setText(f"{int(round(self._zoom_factor * 100))}%")
        self._render_question_html()
        self._update_options_font()
        if self.is_revealed:
            self._render_solution_html()

    def _update_options_font(self):
        opt_font_size = max(11, int(14 * self._zoom_factor))
        badge_size = max(22, int(26 * self._zoom_factor))
        for btn in self._option_buttons:
            if hasattr(btn, "lbl_text"):
                btn.lbl_text.setStyleSheet(f"color: #E2E8F0; font-size: {opt_font_size}px; font-weight: 500; background: transparent; border: none;")
            if hasattr(btn, "lbl_badge"):
                btn.lbl_badge.setFixedSize(badge_size, badge_size)
                btn.lbl_badge.setStyleSheet(f"""
                    background: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: {badge_size // 2}px;
                    font-weight: bold;
                    font-size: {max(10, int(12 * self._zoom_factor))}px;
                """)
            btn.setMinimumHeight(max(36, int(42 * self._zoom_factor)))
