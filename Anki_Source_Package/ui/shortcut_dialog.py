from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QKeySequenceEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services import shortcut_manager
from theme_manager import get_palette


class ShortcutSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shortcuts")
        self.setMinimumSize(600, 650)
        self._edits = {}
        self._shortcut_rows = []
        self._filter_mode = "current"

        # Determine active context based on parent class
        parent_class = parent.__class__.__name__ if parent else ""
        if "Review" in parent_class or "QuickNote" in parent_class:
            self._active_context = "Review"
        else:
            self._active_context = "Home"

        self._build_ui()

    def _build_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "dark")
        p = get_palette(theme)
        self.setStyleSheet(
            f"""
            QDialog{{background:{p['C_BG']};color:{p['C_TEXT']};}}
            QLabel{{background:transparent;color:{p['C_TEXT']};}}
            QFrame#row{{background:{p['C_CARD']};border:1px solid {p['C_BORDER']};border-radius:8px;}}
            QKeySequenceEdit{{background:{p['C_SURFACE']};color:{p['C_TEXT']};border:1px solid {p['C_BORDER']};border-radius:6px;padding:6px;}}
            QPushButton{{background:{p['C_ACCENT']};color:white;border:none;border-radius:8px;padding:8px 16px;font-weight:bold;}}
            QPushButton#flat{{background:{p['C_CARD']};color:{p['C_TEXT']};border:1px solid {p['C_BORDER']};}}
            QLineEdit{{background:{p['C_SURFACE']};color:{p['C_TEXT']};border:1px solid {p['C_BORDER']};border-radius:8px;padding:8px 12px;font-size:13px;}}
            """
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        # Theme terminology mappings for "name" and "view"
        if theme == "dojo":
            window_title = "Quick Moves"
            header_title = "Ninja Quick Moves"
            hint_text = "Click a technique, perform the move, then master it."
            search_placeholder = "🔍 Seek techniques by description, action, or moves..."
            if self._active_context == "Review":
                current_view_text = "⚔ Training Dojo Only"
            else:
                current_view_text = "🏯 Dojo Selection Only"
            full_view_text = "🌍 All Dojo Moves"
            reset_text = "Reset Kata"
            cancel_text = "✕ Dismiss"
            save_text = "💾 Master Moves"
        elif theme in ("tmnt", "manhattan"):
            window_title = "Combo Keys"
            header_title = "Sewer Combo Keys"
            hint_text = "Select a combo, key in your inputs, then save the sequence."
            search_placeholder = "🔍 Scan combos by description, action, or buttons..."
            if self._active_context == "Review":
                current_view_text = "🐢 Sewer Combat Only"
            else:
                current_view_text = "📺 Sewer Levels Only"
            full_view_text = "🌍 All Sewer Combos"
            reset_text = "Reset Combos"
            cancel_text = "✕ Retreat"
            save_text = "💾 Lock in Combos"
        elif theme == "arcanum":
            window_title = "Glyph Keys"
            header_title = "Arcane Glyph Keys"
            hint_text = "Touch a glyph, invoke the new rune, then bind the spell."
            search_placeholder = "🔍 Search runes by description, action, or spell keys..."
            if self._active_context == "Review":
                current_view_text = "🔮 Arcane Ritual Only"
            else:
                current_view_text = "📖 Grimoire Select Only"
            full_view_text = "🌍 All Magic Glyphs"
            reset_text = "Restore Codex"
            cancel_text = "✕ Dispel"
            save_text = "💾 Bind Glyphs"
        else:
            window_title = "Shortcuts"
            header_title = "Keyboard Shortcuts"
            hint_text = "Click a shortcut field, press the new key combo, then save."
            search_placeholder = "🔍 Search shortcuts by description, action, or keys..."
            screen_name = "Review Screen" if self._active_context == "Review" else "Home Screen"
            current_view_text = f"📺 {screen_name} Only"
            full_view_text = "🌍 Full App Shortcuts"
            reset_text = "Reset Defaults"
            cancel_text = "Cancel"
            save_text = "Save"

        self.setWindowTitle(window_title)

        title = QLabel(header_title)
        title.setStyleSheet(f"color:{p['C_ACCENT']};font-size:18px;font-weight:bold;")
        outer.addWidget(title)

        hint = QLabel(hint_text)
        hint.setStyleSheet(f"color:{p['C_SUBTEXT']};font-size:12px;")
        outer.addWidget(hint)

        # Segmented Filter Buttons (Views)
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        self.btn_current_screen = QPushButton(current_view_text)
        self.btn_current_screen.setObjectName("flat")
        self.btn_current_screen.setCursor(Qt.PointingHandCursor)
        self.btn_current_screen.clicked.connect(self._show_current_screen_only)

        self.btn_full_app = QPushButton(full_view_text)
        self.btn_full_app.setObjectName("flat")
        self.btn_full_app.setCursor(Qt.PointingHandCursor)
        self.btn_full_app.clicked.connect(self._show_full_app)

        filter_layout.addWidget(self.btn_current_screen)
        filter_layout.addWidget(self.btn_full_app)
        filter_layout.addStretch()
        outer.addLayout(filter_layout)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(search_placeholder)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        outer.addWidget(self.search_input)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        # Context header translations based on theme
        def get_themed_context_header(context_name):
            if theme == "dojo":
                return "TRAINING DOJO" if context_name == "Review" else "DOJO SELECTION"
            elif theme in ("tmnt", "manhattan"):
                return "SEWER COMBAT" if context_name == "Review" else "SEWER LEVEL SELECT"
            elif theme == "arcanum":
                return "ARCANE RITUAL" if context_name == "Review" else "ARCANE LIBRARY"
            else:
                return "REVIEW SCREEN" if context_name == "Review" else "HOME SCREEN"

        current_context = None
        row = 0
        for action in shortcut_manager.all_actions():
            header_widget = None
            if action.context != current_context:
                current_context = action.context
                header = QLabel(get_themed_context_header(current_context))
                header.setStyleSheet(
                    f"color:{p['C_ACCENT']};font-size:11px;font-weight:bold;letter-spacing:1px;"
                )
                grid.addWidget(header, row, 0, 1, 2)
                header_widget = header
                row += 1

            row_frame = QFrame()
            row_frame.setObjectName("row")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(10, 8, 10, 8)
            label = QLabel(action.label)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            edit = QKeySequenceEdit(QKeySequence(shortcut_manager.shortcut_text(action.action_id)))
            row_layout.addWidget(label)
            row_layout.addWidget(edit)
            grid.addWidget(row_frame, row, 0, 1, 2)
            self._edits[action.action_id] = edit

            # Keep track of shortcut rows for dynamic filtering
            self._shortcut_rows.append({
                "context": action.context,
                "header": header_widget,
                "frame": row_frame
            })
            row += 1

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        btn_reset = QPushButton(reset_text)
        btn_reset.setObjectName("flat")
        btn_cancel = QPushButton(cancel_text)
        btn_cancel.setObjectName("flat")
        btn_save = QPushButton(save_text)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        buttons.addWidget(btn_reset)
        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        outer.addLayout(buttons)

        # Initialize filter styles and visibility
        self._update_filter_view()

    def _show_current_screen_only(self):
        self._filter_mode = "current"
        self._update_filter_view()

    def _show_full_app(self):
        self._filter_mode = "all"
        self._update_filter_view()

    def _on_search_text_changed(self, text):
        self._update_filter_view()

    def _update_filter_view(self):
        theme = getattr(QApplication.instance(), "_active_theme", "dark")
        p = get_palette(theme)

        active_style = f"background:{p['C_ACCENT']};color:white;border:none;border-radius:8px;padding:8px 16px;font-weight:bold;"
        inactive_style = f"background:{p['C_CARD']};color:{p['C_TEXT']};border:1px solid {p['C_BORDER']};border-radius:8px;padding:8px 16px;font-weight:bold;"

        if self._filter_mode == "current":
            self.btn_current_screen.setStyleSheet(active_style)
            self.btn_full_app.setStyleSheet(inactive_style)
        else:
            self.btn_current_screen.setStyleSheet(inactive_style)
            self.btn_full_app.setStyleSheet(active_style)

        search_query = self.search_input.text().strip().lower()
        context_visibility = {}

        # Update individual row visibilities based on context and search query
        for row_info in self._shortcut_rows:
            matches_context = (self._filter_mode == "all" or row_info["context"] == self._active_context)
            
            matches_search = True
            if search_query:
                label_text = row_info["frame"].findChild(QLabel).text().lower()
                edit_widget = row_info["frame"].findChild(QKeySequenceEdit)
                key_text = edit_widget.keySequence().toString().lower() if edit_widget else ""
                matches_search = (search_query in label_text or search_query in key_text)

            show_row = matches_context and matches_search
            row_info["frame"].setVisible(show_row)
            
            if show_row:
                context_visibility[row_info["context"]] = True

        # Show or hide category headers based on whether any matching row is visible
        for row_info in self._shortcut_rows:
            if row_info["header"] is not None:
                show_header = context_visibility.get(row_info["context"], False)
                row_info["header"].setVisible(show_header)

    def _reset_defaults(self):
        for action in shortcut_manager.all_actions():
            self._edits[action.action_id].setKeySequence(
                QKeySequence(action.default)
            )

    def _save(self):
        seen = {}
        for action_id, edit in self._edits.items():
            seq = edit.keySequence().toString(QKeySequence.PortableText)
            if not seq:
                continue
            action = shortcut_manager.action_by_id(action_id)
            seen_key = (action.context, seq)
            if seen_key in seen:
                first = shortcut_manager.action_by_id(seen[seen_key]).label
                second = shortcut_manager.action_by_id(action_id).label
                QMessageBox.warning(
                    self,
                    "Shortcut conflict",
                    f"{seq} is assigned to both {first} and {second} in {action.context}.",
                )
                return
            seen[seen_key] = action_id

        for action_id, edit in self._edits.items():
            seq = edit.keySequence().toString(QKeySequence.PortableText)
            shortcut_manager.set_shortcut(action_id, seq)
        self.accept()

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
            self.reject()
            e.accept()
            return
        super().keyPressEvent(e)
