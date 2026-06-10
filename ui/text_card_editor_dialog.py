import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QFormLayout, QFrame, QApplication, QMessageBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QIcon
from theme_manager import get_palette, normalize_theme
from sm2_engine import sm2_init

class TextCardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None):
        super().__init__(parent)
        self.setWindowTitle("Text Card Editor")
        self.setMinimumSize(600, 450)
        self.card = card or {}
        self._data = data
        self._deck = deck
        self._setup_ui()
        self._load_card_data()
        
    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        self.setStyleSheet(f"""
            QDialog {{ background: {p['C_BG']}; }}
            QWidget {{ background: {p['C_BG']}; color: {p['C_TEXT']}; font-family: 'Segoe UI'; font-size: 12px; }}
            QLabel {{ background: transparent; color: {p['C_TEXT']}; font-weight: bold; }}
            QLineEdit, QTextEdit {{
                background: {p['C_CARD']}; color: {p['C_TEXT']};
                border: 1px solid {p['C_BORDER']}; border-radius: 4px; padding: 6px; }}
            QPushButton {{
                background: {p['C_SURFACE']}; color: {p['C_TEXT']};
                border: 1px solid {p['C_BORDER']}; border-radius: 4px;
                padding: 6px 14px; font-weight: bold; }}
            QPushButton:hover {{ background: {p['C_CARD']}; }}
            QPushButton#save {{
                background: {p['C_GREEN']}; color: {p['C_BG'] if theme == 'dojo' else 'white'};
                border: 1px solid {p['C_BORDER']};
            }}
            QPushButton#save:hover {{
                background: white; color: {p['C_BG']};
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)
        
        # Form Container
        form_frame = QFrame()
        form_layout = QFormLayout(form_frame)
        form_layout.setSpacing(10)
        
        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("Optional title (auto-generated if empty)...")
        form_layout.addRow("Title:", self.inp_title)
        
        self.inp_question = QTextEdit()
        self.inp_question.setPlaceholderText("Type the question/prompt here...")
        self.inp_question.setMinimumHeight(100)
        form_layout.addRow("Question (Front):", self.inp_question)
        
        self.inp_answer = QTextEdit()
        self.inp_answer.setPlaceholderText("Type the correct answer here...")
        self.inp_answer.setMinimumHeight(100)
        form_layout.addRow("Answer (Back):", self.inp_answer)
        
        self.inp_notes = QTextEdit()
        self.inp_notes.setPlaceholderText("Optional hints or study notes...")
        self.inp_notes.setMaximumHeight(60)
        form_layout.addRow("Notes/Hints:", self.inp_notes)
        
        self.inp_tags = QLineEdit()
        self.inp_tags.setPlaceholderText("e.g. history, science, exam1...")
        form_layout.addRow("Tags:", self.inp_tags)
        
        main_layout.addWidget(form_frame, stretch=1)
        
        # Buttons Row
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("💾 Save Card")
        self.btn_save.setObjectName("save")
        self.btn_save.clicked.connect(self._save)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        main_layout.addLayout(btn_layout)
        
    def _load_card_data(self):
        if self.card:
            self.inp_title.setText(self.card.get("title", ""))
            self.inp_question.setText(self.card.get("question", ""))
            self.inp_answer.setText(self.card.get("answer", ""))
            self.inp_notes.setText(self.card.get("notes", ""))
            self.inp_tags.setText(", ".join(self.card.get("tags", [])))
            
    def _save(self):
        question = self.inp_question.toPlainText().strip()
        answer = self.inp_answer.toPlainText().strip()
        
        if not question:
            QMessageBox.warning(self, "Missing Question", "Please enter a question.")
            return
        if not answer:
            QMessageBox.warning(self, "Missing Answer", "Please enter an answer.")
            return
            
        title = self.inp_title.text().strip()
        if not title:
            # Auto-generate title from question snippet
            lines = question.split("\n")
            title = lines[0][:40] + "..." if len(lines[0]) > 40 else lines[0]
            
        tags = [t.strip() for t in self.inp_tags.text().split(",") if t.strip()]
        notes = self.inp_notes.toPlainText().strip()
        
        self.card.update({
            "card_type": "text",
            "title": title,
            "question": question,
            "answer": answer,
            "notes": notes,
            "tags": tags,
            "created": self.card.get("created", datetime.now().isoformat()),
            "reviews": self.card.get("reviews", 0),
            "pdf_path": None,
            "image_path": None,
            "boxes": [] # Text cards have no occlusion boxes
        })
        
        sm2_init(self.card)
        self.accept()
        
    def get_card(self):
        return self.card
        
    def clear_recovery_draft(self):
        pass
