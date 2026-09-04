import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QFormLayout, QFrame, QApplication, QMessageBox, QWidget, QFileDialog, QMenu, QCheckBox, QShortcut, QScrollArea
)
from PyQt5.QtCore import Qt, QSize, QUrl, QEvent
from PyQt5.QtGui import QFont, QIcon, QKeySequence, QTextDocument
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
    def __init__(self, parent=None, font_size=25):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.document().setBaseUrl(get_base_url())
        self.document().setDefaultStyleSheet(f"body, p, div, span, td, li {{ font-size: {font_size}px; }} img {{ width: 100%; }}")

    def copy(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            if self._try_copy_image(cursor):
                return
            plain_text = cursor.selectedText().replace('\u2029', '\n')
            if plain_text:
                clipboard = QApplication.clipboard()
                clipboard.setText(plain_text)
                return
        super().copy()

    def cut(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            if self._try_copy_image(cursor):
                cursor.removeSelectedText()
                return
            plain_text = cursor.selectedText().replace('\u2029', '\n')
            if plain_text:
                clipboard = QApplication.clipboard()
                clipboard.setText(plain_text)
                cursor.removeSelectedText()
                return
        super().cut()

    def keyPressEvent(self, e):
        from PyQt5.QtGui import QKeySequence
        if (e.modifiers() & Qt.ControlModifier) and e.key() == Qt.Key_S:
            p = self.parent()
            while p is not None and not hasattr(p, "_save"):
                p = p.parent()
            if p and hasattr(p, "_save"):
                p._save()
                e.accept()
                return
        elif e.matches(QKeySequence.Copy) or (e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_C):
            self.copy()
            e.accept()
            return
        elif e.matches(QKeySequence.Cut) or (e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_X):
            self.cut()
            e.accept()
            return
        elif e.matches(QKeySequence.Paste) or (e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_V):
            self.paste()
            e.accept()
            return
        super().keyPressEvent(e)

    def _try_copy_image(self, cursor):
        char_format = cursor.charFormat()
        if not char_format.isImageFormat() and cursor.hasSelection():
            start_pos = cursor.selectionStart()
            temp_cursor = self.textCursor()
            temp_cursor.setPosition(start_pos)
            char_format = temp_cursor.charFormat()
            
        if char_format.isImageFormat():
            image_format = char_format.toImageFormat()
            image_name = image_format.name()
            
            from storage_paths import resolve_asset_path
            from PyQt5.QtGui import QPixmap
            abs_path = resolve_asset_path(image_name)
            if abs_path and os.path.exists(abs_path):
                pixmap = QPixmap(abs_path)
                if not pixmap.isNull():
                    clipboard = QApplication.clipboard()
                    clipboard.setImage(pixmap.toImage())
                    return True
        return False

    def contextMenuEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        char_format = cursor.charFormat()
        
        if char_format.isImageFormat():
            pos = cursor.position()
            doc = self.document()
            is_img = False
            select_start = pos
            
            char_at = doc.characterAt(pos)
            char_prev = doc.documentLayout().anchorAt(pos) if hasattr(doc, "documentLayout") else ""
            char_prev_char = doc.characterAt(pos - 1) if pos > 0 else ""
            
            if char_at == '\ufffc':
                is_img = True
                select_start = pos
            elif char_prev_char == '\ufffc':
                is_img = True
                select_start = pos - 1
                
            if is_img:
                img_cursor = self.cursorForPosition(event.pos())
                img_cursor.setPosition(select_start)
                img_cursor.setPosition(select_start + 1, img_cursor.KeepAnchor)
                self.setTextCursor(img_cursor)
                cursor = img_cursor
                
            menu = self.createStandardContextMenu()
            image_format = char_format.toImageFormat()
            image_name = image_format.name()
            
            menu.addSeparator()
            crop_action = menu.addAction("✂ Crop Image")
            edit_sketch_action = menu.addAction("🎨 Edit Sketch")
            
            action = menu.exec_(event.globalPos())
            if action == crop_action:
                self._crop_inline_image(image_name, char_format, cursor)
            elif action == edit_sketch_action:
                self._edit_inline_sketch(image_name, char_format, cursor)
        else:
            menu = self.createStandardContextMenu()
            menu.exec_(event.globalPos())

    def _crop_inline_image(self, image_name, char_format, cursor):
        from storage_paths import resolve_asset_path
        from PyQt5.QtGui import QPixmap
        abs_path = resolve_asset_path(image_name)
        if not abs_path or not os.path.exists(abs_path):
            QMessageBox.warning(self, "Error", "Could not locate image path.")
            return
            
        pixmap = QPixmap(abs_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
            
        from ui.crop_dialog import CropImageDialog
        dialog = CropImageDialog(pixmap, self.window())
        if dialog.exec_() == QDialog.Accepted:
            cropped_pixmap = dialog.get_cropped_pixmap()
            if not cropped_pixmap.isNull():
                if cropped_pixmap.save(abs_path, "PNG"):
                    self.document().addResource(
                        self.document().ImageResource,
                        QUrl(image_name),
                        cropped_pixmap
                    )
                    html = self.toHtml()
                    self.setHtml(html)
                    
                    parent_win = self.window()
                    if hasattr(parent_win, "_write_recovery_checkpoint"):
                        parent_win._write_recovery_checkpoint("image_cropped")
                else:
                    QMessageBox.warning(self, "Error", "Could not save cropped image.")

    def _edit_inline_sketch(self, image_name, char_format, cursor):
        from storage_paths import resolve_asset_path
        from PyQt5.QtGui import QPixmap
        abs_path = resolve_asset_path(image_name)
        if not abs_path or not os.path.exists(abs_path):
            QMessageBox.warning(self, "Error", "Could not locate image path.")
            return
            
        pixmap = QPixmap(abs_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
            
        from ui.quick_note_dialog import EditSketchDialog
        dialog = EditSketchDialog(pixmap, self.window())
        if dialog.exec_() == QDialog.Accepted:
            edited_pixmap = dialog.get_edited_pixmap()
            if not edited_pixmap.isNull():
                if edited_pixmap.save(abs_path, "PNG"):
                    self.document().addResource(
                        self.document().ImageResource,
                        QUrl(image_name),
                        edited_pixmap
                    )
                    html = self.toHtml()
                    self.setHtml(html)
                    
                    parent_win = self.window()
                    if hasattr(parent_win, "_write_recovery_checkpoint"):
                        parent_win._write_recovery_checkpoint("image_edited")
                else:
                    QMessageBox.warning(self, "Error", "Could not save edited sketch.")

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
        import os
        from storage_paths import has_mission_archive, build_archive_asset_path, archive_image_dir
        from PyQt5.QtGui import QPixmap
        filename = f"paste_{uuid.uuid4().hex[:8]}.png"
        
        if has_mission_archive():
            abs_path, rel_path = build_archive_asset_path("images", filename)
        else:
            image_dir = archive_image_dir()
            if image_dir:
                abs_path = os.path.join(image_dir, filename)
                rel_path = f"images/{filename}"
            else:
                import tempfile
                temp_dir = tempfile.gettempdir()
                abs_path = os.path.normpath(os.path.join(temp_dir, filename))
                rel_path = abs_path
            
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        if qimage.save(abs_path, "PNG"):
            pix = QPixmap.fromImage(qimage)
            self.document().addResource(QTextDocument.ImageResource, QUrl(rel_path), pix)
            self.document().addResource(QTextDocument.ImageResource, QUrl.fromLocalFile(abs_path), pix)
            self.insert_image_html(rel_path)

    def insert_image_file(self, file_path):
        from storage_paths import has_mission_archive, import_asset_into_archive, resolve_asset_path
        from PyQt5.QtGui import QPixmap
        try:
            if has_mission_archive():
                rel_path = import_asset_into_archive(file_path, "images")
            else:
                rel_path = file_path
            abs_path = resolve_asset_path(rel_path) or file_path
            if os.path.exists(abs_path):
                pix = QPixmap(abs_path)
                if not pix.isNull():
                    self.document().addResource(QTextDocument.ImageResource, QUrl(rel_path), pix)
                    self.document().addResource(QTextDocument.ImageResource, QUrl.fromLocalFile(abs_path), pix)
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
        self._apply_screen_geometry()
        self.card = card or {}
        self._data = data
        self._deck = deck
        self._setup_ui()
        self._load_card_data()

    def _apply_screen_geometry(self):
        screen = None
        if self.parent() and hasattr(self.parent(), "window") and self.parent().window():
            p_win = self.parent().window()
            if hasattr(p_win, "screen"):
                screen = p_win.screen()
        if screen is None:
            screen = QApplication.primaryScreen()

        if screen:
            geo = screen.availableGeometry()
            # Occupy 80% screen width and 80% screen height (leaving only 20% margin)
            target_w = max(1100, int(geo.width() * 0.80))
            target_h = max(750, int(geo.height() * 0.80))
            self.setMinimumSize(int(geo.width() * 0.50), int(geo.height() * 0.50))
            self.resize(target_w, target_h)
            target_x = geo.x() + (geo.width() - target_w) // 2
            target_y = geo.y() + (geo.height() - target_h) // 2
            self.move(target_x, target_y)
        else:
            self.setMinimumSize(950, 700)
            self.resize(1300, 850)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_geometry_initialized", False):
            self._geometry_initialized = True
            self._apply_screen_geometry()

    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        self.setStyleSheet(f"""
            QDialog {{
                background: #0B0E14;
                color: #FFFFFF;
            }}
            QScrollArea {{
                background: #0B0E14;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background: #0B0E14;
            }}
            QLabel {{
                background: transparent;
                color: #E2E8F0;
                font-weight: bold;
                font-size: 23px;
            }}
            QLineEdit {{
                background: #141824;
                color: #FFFFFF;
                border: 1.5px solid #2B3347;
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 25px;
                selection-background-color: #5C7CFA;
            }}
            QLineEdit:focus {{
                border-color: #5C7CFA;
                background: #181E2E;
            }}
            QTextEdit {{
                background: #141824;
                color: #FFFFFF;
                border: 1.5px solid #2B3347;
                border-radius: 6px;
                padding: 12px 14px;
                font-size: 25px;
                line-height: 1.5;
                selection-background-color: #5C7CFA;
            }}
            QTextEdit:focus {{
                border-color: #5C7CFA;
                background: #181E2E;
            }}
            QPushButton {{
                background: #1E2333;
                color: #FFFFFF;
                border: 1px solid #374158;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 23px;
            }}
            QPushButton:hover {{
                background: #283046;
                border-color: #5C7CFA;
            }}
            QPushButton#save {{
                background: #10B981;
                color: #07090E;
                border: none;
                padding: 11px 28px;
                font-size: 24px;
                font-weight: bold;
            }}
            QPushButton#save:hover {{
                background: #34D399;
            }}
            QCheckBox {{
                background: transparent;
                color: #A0AEC0;
                font-size: 23px;
            }}
            QCheckBox::indicator {{
                width: 22px;
                height: 22px;
            }}
            QScrollBar:vertical {{
                background: #0B0E14;
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #2B3347;
                min-height: 24px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #5C7CFA;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 22, 28, 22)
        main_layout.setSpacing(16)

        # Form Scroll Area
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        # Form Container
        form_frame = QFrame()
        form_layout = QFormLayout(form_frame)
        form_layout.setSpacing(16)
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        
        self.inp_title = QLineEdit()
        self.inp_title.setFont(QFont("Segoe UI", 24))
        self.inp_title.setPlaceholderText("Optional card title (auto-generated if empty)...")
        form_layout.addRow("Title:", self.inp_title)
        
        # Question Row (Front)
        q_widget = QWidget()
        q_lay = QHBoxLayout(q_widget)
        q_lay.setContentsMargins(0, 0, 0, 0)
        q_lay.setSpacing(10)
        self.inp_question = RichTextEdit(font_size=26)
        self.inp_question.setFont(QFont("Segoe UI", 26, QFont.DemiBold))
        self.inp_question.setPlaceholderText("Type the question or front word here (e.g. 'Nascent (Adj.)')...")
        self.inp_question.setMinimumHeight(220)
        q_lay.addWidget(self.inp_question)
        
        q_btn_layout = QVBoxLayout()
        q_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_q_img = QPushButton("🖼️ Image")
        self.btn_q_img.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.btn_q_img.setToolTip("Insert image from file")
        self.btn_q_img.clicked.connect(self._select_q_image)
        q_btn_layout.addWidget(self.btn_q_img)
        q_btn_layout.addStretch()
        q_lay.addLayout(q_btn_layout)
        form_layout.addRow("Front (Word / Question):", q_widget)
        
        # Answer Row (Back)
        a_widget = QWidget()
        a_lay = QHBoxLayout(a_widget)
        a_lay.setContentsMargins(0, 0, 0, 0)
        a_lay.setSpacing(10)
        self.inp_answer = RichTextEdit(font_size=25)
        self.inp_answer.setFont(QFont("Segoe UI", 25))
        self.inp_answer.setPlaceholderText("Type the answer, meaning or definition here...")
        self.inp_answer.setMinimumHeight(220)
        a_lay.addWidget(self.inp_answer)
        
        a_btn_layout = QVBoxLayout()
        a_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_a_img = QPushButton("🖼️ Image")
        self.btn_a_img.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.btn_a_img.setToolTip("Insert image from file")
        self.btn_a_img.clicked.connect(self._select_a_image)
        a_btn_layout.addWidget(self.btn_a_img)
        a_btn_layout.addStretch()
        a_lay.addLayout(a_btn_layout)
        form_layout.addRow("Back (Meaning / Answer):", a_widget)
        
        self.inp_trap = QTextEdit()
        self.inp_trap.setFont(QFont("Segoe UI", 23))
        self.inp_trap.setPlaceholderText("Optional exam trap, confusing pair, or pitfall note...")
        self.inp_trap.setMinimumHeight(100)
        self.inp_trap.setMaximumHeight(140)
        form_layout.addRow("⚠️ Trap / Pitfall Note:", self.inp_trap)

        self.inp_notes = QTextEdit()
        self.inp_notes.setFont(QFont("Segoe UI", 23))
        self.inp_notes.setPlaceholderText("Optional hints, mnemonics or study notes...")
        self.inp_notes.setMinimumHeight(100)
        self.inp_notes.setMaximumHeight(140)
        form_layout.addRow("Notes / Hints:", self.inp_notes)
        
        self.inp_tags = QLineEdit()
        self.inp_tags.setFont(QFont("Segoe UI", 23))
        self.inp_tags.setPlaceholderText("e.g. vocab, idioms, biology...")
        form_layout.addRow("Tags:", self.inp_tags)
        
        self.chk_formula = QCheckBox("Mark as Formula")
        self.chk_formula.setFont(QFont("Segoe UI", 23))
        self.chk_formula.setToolTip("Formula cards are excluded from normal reviews and can be viewed/practiced anytime.")
        form_layout.addRow("", self.chk_formula)
        
        scroll.setWidget(form_frame)
        main_layout.addWidget(scroll, stretch=1)
        
        # Buttons Row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(14)
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFont(QFont("Segoe UI", 23, QFont.Bold))
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("💾 Save Card")
        self.btn_save.setObjectName("save")
        self.btn_save.setFont(QFont("Segoe UI", 24, QFont.Bold))
        self.btn_save.setToolTip("Save card changes (Ctrl+S)")
        self.btn_save.setShortcut(QKeySequence("Ctrl+S"))
        self.btn_save.clicked.connect(self._save)
        
        # Dialog-wide shortcut to guarantee Ctrl+S works in any child widget
        self._shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self._shortcut_save.setContext(Qt.WindowShortcut)
        self._shortcut_save.activated.connect(self._save)
        
        # Install eventFilter on dialog and all input fields so Ctrl+S always intercepts
        for w in (self, self.inp_title, self.inp_question, self.inp_answer, self.inp_trap, self.inp_notes, self.inp_tags, self.chk_formula, self.btn_save, self.btn_cancel):
            w.installEventFilter(self)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        main_layout.addLayout(btn_layout)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            mods = event.modifiers()
            clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
            if (clean_mods & Qt.ControlModifier) and not (clean_mods & Qt.AltModifier) and key == Qt.Key_S:
                self._save()
                return True
        return super().eventFilter(obj, event)

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
        font = QFont("Segoe UI", 26 if editor == self.inp_question else 25)
        editor.setFont(font)
        
    def _load_card_data(self):
        if self.card:
            self.inp_title.setText(self.card.get("title", ""))
            self._set_editor_content(self.inp_question, self.card.get("question", ""))
            self._set_editor_content(self.inp_answer, self.card.get("answer", ""))
            self.inp_trap.setText(self.card.get("trap_note", "") or "")
            self.inp_notes.setText(self.card.get("notes", "") or "")
            self.inp_tags.setText(", ".join(self.card.get("tags", [])))
            self.chk_formula.setChecked(self.card.get("is_formula", False))
            
    def _get_field_content(self, editor):
        plain = editor.toPlainText().strip()
        if not plain:
            return ""
        html = editor.toHtml()
        
        import re
        has_img = "<img" in html.lower()
        has_table = "<table" in html.lower()
        has_tags = bool(re.search(r'<(b|i|u|s|em|strong|table|img|ul|ol|li|h[1-6]|font)\b', html, re.IGNORECASE))
        has_custom_style = bool(re.search(r'<span style="[^"]*(color|background|text-decoration)[^"]*"', html, re.IGNORECASE))
        
        if not (has_img or has_table or has_tags or has_custom_style):
            return plain
            
        # Extract body content to avoid full document overhead
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if body_match:
            inner = body_match.group(1).strip()
            inner = re.sub(r'<p style="[^"]*margin-top:0px;[^"]*">', '<p>', inner)
            return inner
        return html

    def _save(self):
        question_plain = self.inp_question.toPlainText().strip()
        answer_plain = self.inp_answer.toPlainText().strip()
        
        if not question_plain:
            QMessageBox.warning(self, "Missing Question", "Please enter a question.")
            return
        if not answer_plain:
            QMessageBox.warning(self, "Missing Answer", "Please enter an answer.")
            return
            
        question = self._get_field_content(self.inp_question)
        answer = self._get_field_content(self.inp_answer)

        title = self.inp_title.text().strip()
        if not title:
            # Auto-generate title from question snippet (using plain text to avoid HTML tags)
            lines = question_plain.split("\n")
            title = lines[0][:40] + "..." if len(lines[0]) > 40 else lines[0]
            
        tags = [t.strip() for t in self.inp_tags.text().split(",") if t.strip()]
        trap_note = self.inp_trap.toPlainText().strip()
        notes = self.inp_notes.toPlainText().strip()
        
        self.card.update({
            "card_type": "text",
            "title": title,
            "question": question,
            "answer": answer,
            "trap_note": trap_note,
            "notes": notes,
            "tags": tags,
            "created": self.card.get("created", datetime.now().isoformat()),
            "reviews": self.card.get("reviews", 0),
            "pdf_path": None,
            "image_path": None,
            "boxes": [], # Text cards have no occlusion boxes
            "is_formula": self.chk_formula.isChecked()
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
        if (clean_mods & Qt.ControlModifier) and key == Qt.Key_S:
            self._save()
            e.accept()
            return
        if is_ctrl_question:
            from ui.shortcut_dialog import ShortcutSettingsDialog
            dlg = ShortcutSettingsDialog(self)
            dlg.exec_()
            e.accept()
            return
        super().keyPressEvent(e)
