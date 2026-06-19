import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QFormLayout, QFrame, QApplication, QMessageBox, QWidget, QFileDialog
)
from PyQt5.QtCore import Qt, QSize, QUrl
from PyQt5.QtGui import QFont, QIcon
from theme_manager import get_palette, normalize_theme
from sm2_engine import sm2_init

def get_base_url():
    from storage_paths import get_mission_archive_root, current_data_file
    root = get_mission_archive_root()
    if not root:
        root = os.path.dirname(current_data_file())
    if root:
        return QUrl.fromLocalFile(os.path.abspath(root) + "/")
    return QUrl()

class RichTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.document().setBaseUrl(get_base_url())
        self.document().setDefaultStyleSheet("img { width: 100%; }")

    def insertFromMimeData(self, mimeData):
        if mimeData.hasImage():
            image = mimeData.imageData()
            if image:
                self.insert_qimage(image)
                return
        if mimeData.hasUrls():
            for url in mimeData.urls():
                file_path = url.toLocalFile()
                if file_path and os.path.exists(file_path):
                    ext = os.path.splitext(file_path.lower())[1]
                    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                        self.insert_image_file(file_path)
            return
        super().insertFromMimeData(mimeData)

    def insert_qimage(self, qimage):
        import uuid
        from storage_paths import has_mission_archive, build_archive_asset_path
        filename = f"paste_{uuid.uuid4().hex[:8]}.png"
        
        if has_mission_archive():
            abs_path, rel_path = build_archive_asset_path("images", filename)
        else:
            import tempfile
            temp_dir = tempfile.gettempdir()
            abs_path = os.path.normpath(os.path.join(temp_dir, filename))
            rel_path = abs_path
            
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        if qimage.save(abs_path, "PNG"):
            self.insert_image_html(rel_path)

    def insert_image_file(self, file_path):
        from storage_paths import has_mission_archive, import_asset_into_archive
        try:
            if has_mission_archive():
                rel_path = import_asset_into_archive(file_path, "images")
            else:
                rel_path = file_path
            self.insert_image_html(rel_path)
        except Exception as e:
            print(f"Error importing image: {e}")

    def insert_image_html(self, rel_path):
        url_path = rel_path.replace("\\", "/")
        cursor = self.textCursor()
        cursor.insertHtml(f'<br><img src="{url_path}"/><br>')

class TextCardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None):
        super().__init__(parent)
        self.setWindowTitle("Text Card Editor")
        self.setMinimumSize(950, 700)
        self.resize(1000, 750)
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
        
        # Question Row
        q_widget = QWidget()
        q_lay = QHBoxLayout(q_widget)
        q_lay.setContentsMargins(0, 0, 0, 0)
        self.inp_question = RichTextEdit()
        self.inp_question.setPlaceholderText("Type the question/prompt here... Drag-and-drop or paste images directly!")
        self.inp_question.setMinimumHeight(220)
        q_lay.addWidget(self.inp_question)
        
        q_btn_layout = QVBoxLayout()
        q_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_q_img = QPushButton("🖼️ Image")
        self.btn_q_img.setToolTip("Insert image from file")
        self.btn_q_img.clicked.connect(self._select_q_image)
        q_btn_layout.addWidget(self.btn_q_img)
        q_btn_layout.addStretch()
        q_lay.addLayout(q_btn_layout)
        form_layout.addRow("Question (Front):", q_widget)
        
        # Answer Row
        a_widget = QWidget()
        a_lay = QHBoxLayout(a_widget)
        a_lay.setContentsMargins(0, 0, 0, 0)
        self.inp_answer = RichTextEdit()
        self.inp_answer.setPlaceholderText("Type the correct answer here... Drag-and-drop or paste images directly!")
        self.inp_answer.setMinimumHeight(220)
        a_lay.addWidget(self.inp_answer)
        
        a_btn_layout = QVBoxLayout()
        a_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_a_img = QPushButton("🖼️ Image")
        self.btn_a_img.setToolTip("Insert image from file")
        self.btn_a_img.clicked.connect(self._select_a_image)
        a_btn_layout.addWidget(self.btn_a_img)
        a_btn_layout.addStretch()
        a_lay.addLayout(a_btn_layout)
        form_layout.addRow("Answer (Back):", a_widget)
        
        self.inp_notes = QTextEdit()
        self.inp_notes.setPlaceholderText("Optional hints or study notes...")
        self.inp_notes.setMaximumHeight(100)
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

    def _select_q_image(self):
        self._select_image_for_edit(self.inp_question)
        
    def _select_a_image(self):
        self._select_image_for_edit(self.inp_answer)
        
    def _select_image_for_edit(self, editor):
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        if path:
            editor.insert_image_file(path)

    def _set_editor_content(self, editor, text):
        if not text:
            editor.clear()
        elif "<" in text and ">" in text:
            editor.setHtml(text)
        else:
            editor.setPlainText(text)
        
    def _load_card_data(self):
        if self.card:
            self.inp_title.setText(self.card.get("title", ""))
            self._set_editor_content(self.inp_question, self.card.get("question", ""))
            self._set_editor_content(self.inp_answer, self.card.get("answer", ""))
            self.inp_notes.setText(self.card.get("notes", ""))
            self.inp_tags.setText(", ".join(self.card.get("tags", [])))
            
    def _save(self):
        question_plain = self.inp_question.toPlainText().strip()
        answer_plain = self.inp_answer.toPlainText().strip()
        
        if not question_plain:
            QMessageBox.warning(self, "Missing Question", "Please enter a question.")
            return
        if not answer_plain:
            QMessageBox.warning(self, "Missing Answer", "Please enter an answer.")
            return
            
        # If there are images/formatting, save HTML. Otherwise save plain text.
        html_q = self.inp_question.toHtml()
        html_a = self.inp_answer.toHtml()
        
        question = html_q if ("<img" in html_q or "<table" in html_q or "font-weight" in html_q) else question_plain
        answer = html_a if ("<img" in html_a or "<table" in html_a or "font-weight" in html_a) else answer_plain

        title = self.inp_title.text().strip()
        if not title:
            # Auto-generate title from question snippet (using plain text to avoid HTML tags)
            lines = question_plain.split("\n")
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

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
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
            e.accept()
            return
        super().keyPressEvent(e)
