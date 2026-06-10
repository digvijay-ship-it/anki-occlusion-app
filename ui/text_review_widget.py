import os
import difflib
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextBrowser, QFrame, QApplication, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor
from theme_manager import get_palette

class TextReviewWidget(QWidget):
    answer_submitted = pyqtSignal() # Emitted when user presses Enter in the input field to show the answer

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card = None
        self.is_revealed = False
        self._setup_ui()
        
    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        # Dynamic fonts based on theme
        is_dojo = theme in ("dojo", "tmnt", "manhattan")
        self._font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        self._header_font_family = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setAlignment(Qt.AlignCenter)
        
        # Card container (Glassmorphic / elegant rounded frame)
        self.card_frame = QFrame()
        self.card_frame.setObjectName("card_frame")
        self.card_frame.setFixedWidth(650)
        self.card_frame.setMinimumHeight(350)
        
        # Frame styles
        border_px = "2px" if is_dojo else "1px"
        self.card_frame.setStyleSheet(f"""
            QFrame#card_frame {{
                background: {p['C_SURFACE']};
                border: {border_px} solid {p['C_BORDER']};
                border-radius: 12px;
            }}
            QLabel {{
                background: transparent;
                color: {p['C_TEXT']};
                font-family: {self._font_family};
            }}
            QLineEdit {{
                background: {p['C_CARD']};
                color: {p['C_TEXT']};
                border: 2px solid {p['C_BORDER']};
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 14px;
                font-family: {self._font_family};
            }}
            QLineEdit:focus {{
                border: 2px solid {p['C_ACCENT']};
            }}
            QTextBrowser {{
                background: transparent;
                border: none;
                color: {p['C_TEXT']};
                font-family: {self._font_family};
            }}
        """)
        
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(20)
        
        # Question Section
        self.lbl_question_title = QLabel("QUESTION" if is_dojo else "Question")
        self.lbl_question_title.setStyleSheet(f"""
            color: {p['C_ACCENT']};
            font-size: {'10px' if is_dojo else '12px'};
            font-family: {self._header_font_family};
            font-weight: bold;
            letter-spacing: 2px;
        """)
        card_layout.addWidget(self.lbl_question_title)
        
        # Scrollable Question text
        self.q_browser = QTextBrowser()
        self.q_browser.setOpenExternalLinks(True)
        self.q_browser.setFont(QFont(self._font_family, 16))
        card_layout.addWidget(self.q_browser, stretch=1)
        
        # Separator 1
        self.sep1 = QFrame()
        self.sep1.setFrameShape(QFrame.HLine)
        self.sep1.setStyleSheet(f"background: {p['C_BORDER']}; height: 1px;")
        card_layout.addWidget(self.sep1)
        
        # Input Section
        self.lbl_input_title = QLabel("YOUR ANSWER" if is_dojo else "Your Answer")
        self.lbl_input_title.setStyleSheet(f"""
            color: {p['C_SUBTEXT']};
            font-size: {'9px' if is_dojo else '11px'};
            font-family: {self._header_font_family};
            font-weight: bold;
            letter-spacing: 1.5px;
        """)
        card_layout.addWidget(self.lbl_input_title)
        
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Type your answer here and press Enter to reveal...")
        self.txt_input.returnPressed.connect(self._on_enter_pressed)
        card_layout.addWidget(self.txt_input)
        
        # Reveal / Comparison Section (initially hidden)
        self.answer_container = QWidget()
        ans_layout = QVBoxLayout(self.answer_container)
        ans_layout.setContentsMargins(0, 0, 0, 0)
        ans_layout.setSpacing(10)
        
        # Separator 2
        self.sep2 = QFrame()
        self.sep2.setFrameShape(QFrame.HLine)
        self.sep2.setStyleSheet(f"background: {p['C_BORDER']}; height: 1px;")
        ans_layout.addWidget(self.sep2)
        
        self.lbl_diff_title = QLabel("COMPARISON" if is_dojo else "Comparison")
        self.lbl_diff_title.setStyleSheet(f"""
            color: {p['C_PURPLE'] if is_dojo else p['C_ACCENT']};
            font-size: {'9px' if is_dojo else '11px'};
            font-family: {self._header_font_family};
            font-weight: bold;
            letter-spacing: 1.5px;
        """)
        ans_layout.addWidget(self.lbl_diff_title)
        
        self.diff_browser = QTextBrowser()
        self.diff_browser.setFont(QFont(self._font_family, 13))
        self.diff_browser.setFixedHeight(120)
        ans_layout.addWidget(self.diff_browser)
        
        # Notes Section (if any)
        self.notes_container = QWidget()
        notes_layout = QVBoxLayout(self.notes_container)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(4)
        
        self.lbl_notes_title = QLabel("NOTES" if is_dojo else "Notes / Hints")
        self.lbl_notes_title.setStyleSheet(f"""
            color: {p['C_SUBTEXT']};
            font-size: {'8px' if is_dojo else '10px'};
            font-family: {self._header_font_family};
            font-weight: bold;
            letter-spacing: 1px;
        """)
        notes_layout.addWidget(self.lbl_notes_title)
        
        self.notes_browser = QTextBrowser()
        self.notes_browser.setFont(QFont(self._font_family, 12))
        self.notes_browser.setFixedHeight(60)
        notes_layout.addWidget(self.notes_browser)
        ans_layout.addWidget(self.notes_container)
        
        card_layout.addWidget(self.answer_container)
        self.answer_container.hide()
        
        main_layout.addWidget(self.card_frame)
        
    def load_card(self, card):
        self.card = card
        self.is_revealed = False
        self.txt_input.clear()
        self.txt_input.setReadOnly(False)
        self.txt_input.setEnabled(True)
        self.txt_input.setFocus()
        
        # Load Question
        question_html = f"<div style='font-size: 16px; color: #CDD6F4;'>{self._escape_and_format(card.get('question', ''))}</div>"
        # Adjust text color for classic theme
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        if theme == "classic":
            question_html = f"<div style='font-size: 16px; color: {p['C_TEXT']};'>{self._escape_and_format(card.get('question', ''))}</div>"
            
        self.q_browser.setHtml(question_html)
        
        # Clear/Hide answer container
        self.answer_container.hide()
        self.diff_browser.clear()
        self.notes_browser.clear()
        
    def reveal_answer(self):
        if self.is_revealed:
            return
        self.is_revealed = True
        self.txt_input.setReadOnly(True) # Prevent editing once revealed
        
        typed = self.txt_input.text().strip()
        correct = self.card.get("answer", "").strip()
        
        # Generate visual diff HTML
        diff_html = self._generate_diff_html(typed, correct)
        self.diff_browser.setHtml(diff_html)
        
        # Load Notes if exists
        notes = self.card.get("notes", "").strip()
        if notes:
            theme = getattr(QApplication.instance(), "_active_theme", "classic")
            p = get_palette(theme)
            notes_color = "#A6ADC8" if theme != "classic" else p['C_TEXT']
            self.notes_browser.setHtml(f"<div style='color: {notes_color}; font-size: 13px;'>{self._escape_and_format(notes)}</div>")
            self.notes_container.show()
        else:
            self.notes_container.hide()
            
        self.answer_container.show()
        
    def _on_enter_pressed(self):
        if not self.is_revealed:
            self.answer_submitted.emit()
            
    def _escape_and_format(self, text):
        import html
        escaped = html.escape(text)
        return escaped.replace("\n", "<br>")
        
    def _generate_diff_html(self, typed: str, correct: str) -> str:
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        # Color schemes based on dark/light themes
        c_green = "#50FA7B" if theme != "classic" else "#2F9E44"
        c_red = "#FF5555" if theme != "classic" else "#E03131"
        c_orange = "#FFB86C" if theme != "classic" else "#E8590C"
        c_cyan = "#8BE9FD" if theme != "classic" else "#15AABF"
        c_text = p['C_TEXT']
        
        if typed == correct:
            return f"<div style='font-family: sans-serif; font-size: 14px; color: {c_text};'>" \
                   f"<p><b>Your Input:</b> <code style='font-size: 15px; color: {c_green};'>{self._escape_and_format(typed)}</code></p>" \
                   f"<p style='color: {c_green}; font-weight: bold;'>✓ Perfect Match!</p></div>"
                   
        matcher = difflib.SequenceMatcher(None, typed, correct)
        typed_html = []
        correct_html = []
        
        for opcode, a_start, a_end, b_start, b_end in matcher.get_opcodes():
            if opcode == 'equal':
                match_str = self._escape_and_format(typed[a_start:a_end])
                typed_html.append(f"<span style='color: {c_green};'>{match_str}</span>")
                correct_html.append(f"<span style='color: {c_green};'>{match_str}</span>")
            elif opcode == 'replace':
                replaced_str = self._escape_and_format(typed[a_start:a_end])
                correct_str = self._escape_and_format(correct[b_start:b_end])
                typed_html.append(f"<span style='color: {c_red}; text-decoration: line-through;'>{replaced_str}</span>")
                correct_html.append(f"<span style='color: {c_orange}; font-weight: bold;'>{correct_str}</span>")
            elif opcode == 'delete':
                deleted_str = self._escape_and_format(typed[a_start:a_end])
                typed_html.append(f"<span style='color: {c_red}; text-decoration: line-through;'>{deleted_str}</span>")
            elif opcode == 'insert':
                inserted_str = self._escape_and_format(correct[b_start:b_end])
                correct_html.append(f"<span style='color: {c_cyan}; text-decoration: underline;'>{inserted_str}</span>")
                
        typed_res = "".join(typed_html)
        correct_res = "".join(correct_html)
        
        html = f"""
        <div style='font-family: sans-serif; font-size: 14px; color: {c_text};'>
            <p style='margin-bottom: 6px;'><b>Your Input:</b> <code style='font-size: 14px;'>{typed_res if typed_res else "<span style='color: " + c_red + ";'>(empty)</span>"}</code></p>
            <p style='margin-top: 0px;'><b>Correct:</b> <code style='font-size: 14px;'>{correct_res}</code></p>
        </div>
        """
        return html
