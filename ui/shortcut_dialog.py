from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
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
        self.setMinimumSize(560, 520)
        self._edits = {}
        self._build_ui()

    def _build_ui(self):
        p = get_palette("dark")
        self.setStyleSheet(
            f"""
            QDialog{{background:{p['C_BG']};color:{p['C_TEXT']};}}
            QLabel{{background:transparent;color:{p['C_TEXT']};}}
            QFrame#row{{background:{p['C_CARD']};border:1px solid {p['C_BORDER']};border-radius:8px;}}
            QKeySequenceEdit{{background:{p['C_SURFACE']};color:{p['C_TEXT']};border:1px solid {p['C_BORDER']};border-radius:6px;padding:6px;}}
            QPushButton{{background:{p['C_ACCENT']};color:white;border:none;border-radius:8px;padding:8px 16px;font-weight:bold;}}
            QPushButton#flat{{background:{p['C_CARD']};color:{p['C_TEXT']};border:1px solid {p['C_BORDER']};}}
            """
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        title = QLabel("Keyboard Shortcuts")
        title.setStyleSheet(f"color:{p['C_ACCENT']};font-size:18px;font-weight:bold;")
        outer.addWidget(title)

        hint = QLabel("Click a shortcut field, press the new key combo, then save.")
        hint.setStyleSheet(f"color:{p['C_SUBTEXT']};font-size:12px;")
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        current_context = None
        row = 0
        for action in shortcut_manager.all_actions():
            if action.context != current_context:
                current_context = action.context
                header = QLabel(current_context.upper())
                header.setStyleSheet(
                    f"color:{p['C_ACCENT']};font-size:11px;font-weight:bold;letter-spacing:1px;"
                )
                grid.addWidget(header, row, 0, 1, 2)
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
            row += 1

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        btn_reset = QPushButton("Reset Defaults")
        btn_reset.setObjectName("flat")
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("flat")
        btn_save = QPushButton("Save")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        buttons.addWidget(btn_reset)
        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        outer.addLayout(buttons)

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
