from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


def _format_saved_time(value):
    if not value:
        return "saved time unknown"
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(str(value))
        return parsed.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return str(value)


def _short_source_name(path):
    if not path:
        return "no source file"
    try:
        import os

        return os.path.basename(str(path)) or str(path)
    except Exception:
        return str(path)


def _draft_label(draft, index):
    card = draft.get("card", {}) or {}
    deck = draft.get("deck", {}) or {}
    title_text = card.get("title") or "Untitled draft"
    source = _short_source_name(card.get("pdf_path") or card.get("image_path"))
    boxes = len(card.get("boxes", []) or [])
    deck_name = deck.get("name") or "No deck selected yet"
    saved = _format_saved_time(draft.get("updated_at"))
    prefix = "Recommended - newest draft" if index == 0 else "Older draft"
    mask_label = "mask" if boxes == 1 else "masks"
    return (
        f"{prefix}\n"
        f"{title_text} from {source}\n"
        f"{boxes} {mask_label} | {deck_name} | {saved}"
    )


class RecoveryDialog(QDialog):
    def __init__(self, summary, parent=None, startup=False):
        super().__init__(parent)
        self.summary = summary or {}
        self.action = "close"
        self.selected_draft = None
        self.selected_drafts = []
        self.setWindowTitle("Recovery Center")
        self.setMinimumWidth(560)
        self.setModal(bool(startup))
        self.setStyleSheet(
            """
            QDialog {
                background: #0B0F16;
                color: #F4F7FB;
            }
            QLabel {
                color: #F4F7FB;
            }
            QListWidget {
                background: #070A10;
                color: #F4F7FB;
                border: 1px solid #2C3B52;
                border-radius: 8px;
                padding: 6px;
                outline: none;
            }
            QListWidget::item {
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 8px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background: #12345A;
                border: 1px solid #5AD7FF;
                color: #FFFFFF;
            }
            QPushButton {
                background: #111827;
                color: #F4F7FB;
                border: 2px solid #3A4A63;
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #16243A;
                border: 2px solid #5AD7FF;
                color: #FFFFFF;
            }
            QPushButton:focus {
                background: #16243A;
                border: 2px solid #6EE7B7;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background: #0F766E;
                border: 2px solid #99F6E4;
                color: #FFFFFF;
            }
            QPushButton:disabled {
                background: #10131A;
                color: #707A8D;
                border: 2px solid #252C3A;
            }
            QPushButton#primaryRecoveryButton {
                background: #0F766E;
                border: 2px solid #5EEAD4;
                color: #FFFFFF;
            }
            QPushButton#primaryRecoveryButton:hover,
            QPushButton#primaryRecoveryButton:focus {
                background: #0D9488;
                border: 2px solid #CCFBF1;
            }
            QPushButton#dangerRecoveryButton {
                border: 2px solid #F97373;
            }
            QPushButton#dangerRecoveryButton:hover,
            QPushButton#dangerRecoveryButton:focus {
                background: #4A1717;
                border: 2px solid #FCA5A5;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        drafts = self.summary.get("drafts", []) or []
        events = self.summary.get("review_events", []) or []
        recoverable = [event for event in events if event.get("status") == "recoverable"]
        blocked = [event for event in events if event.get("status") != "recoverable"]
        review_only = bool(events) and not bool(drafts)

        title_text = (
            "We found unsaved review progress"
            if review_only
            else "We found unsaved work"
        )
        title = QLabel(title_text)
        title.setStyleSheet("font-size:16px;font-weight:bold;")
        layout.addWidget(title)

        help_copy = (
            "No card drafts are waiting. Choose Recover Review Progress to apply "
            "the saved review updates."
            if review_only
            else (
                "The newest draft is selected for you. Choose Restore to inspect it. "
                "Delete only removes the selected recovery draft."
            )
        )
        help_text = QLabel(help_copy)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        event_text = f"Review progress ready to restore: {len(recoverable)}"
        if blocked:
            event_text += f"  |  Needs attention: {len(blocked)}"
        self.event_label = QLabel(event_text)
        self.event_label.setWordWrap(True)
        layout.addWidget(self.event_label)

        self.draft_list = QListWidget()
        self.draft_list.setMinimumHeight(180)
        if review_only:
            review_item = QListWidgetItem(
                "Review progress checkpoint\n"
                f"{len(recoverable)} review update(s) can be restored from recovery.\n"
                "There is no editor draft to inspect."
            )
            review_item.setFlags(Qt.NoItemFlags)
            self.draft_list.addItem(review_item)
        for index, draft in enumerate(drafts):
            item = QListWidgetItem(_draft_label(draft, index))
            item.setData(Qt.UserRole, draft)
            self.draft_list.addItem(item)
        if drafts:
            self.draft_list.setCurrentRow(0)
        layout.addWidget(self.draft_list)

        quick_row = QHBoxLayout()
        self.btn_restore_latest = QPushButton("Restore Latest Draft")
        self.btn_delete_all = QPushButton("Delete All Drafts")
        self.btn_restore_latest.setObjectName("primaryRecoveryButton")
        self.btn_delete_all.setObjectName("dangerRecoveryButton")
        self.btn_restore_latest.setEnabled(bool(drafts))
        self.btn_delete_all.setEnabled(bool(drafts))
        self.btn_restore_latest.setDefault(bool(drafts))
        quick_row.addWidget(self.btn_restore_latest)
        quick_row.addWidget(self.btn_delete_all)
        layout.addLayout(quick_row)

        row = QHBoxLayout()
        review_button_text = (
            "Recover Review Progress"
            if recoverable
            else "No Review Progress To Restore"
        )
        self.btn_recover_reviews = QPushButton(review_button_text)
        self.btn_open_draft = QPushButton("Restore Selected Draft")
        self.btn_delete_draft = QPushButton("Delete Selected Draft")
        self.btn_close = QPushButton("Close (Keep Progress)" if review_only else "Close (Keep Drafts)")
        if recoverable:
            self.btn_recover_reviews.setObjectName("primaryRecoveryButton")
        self.btn_open_draft.setObjectName("primaryRecoveryButton")
        self.btn_delete_draft.setObjectName("dangerRecoveryButton")
        self.btn_recover_reviews.setEnabled(bool(recoverable))
        self.btn_recover_reviews.setDefault(bool(recoverable) and not bool(drafts))
        self.btn_open_draft.setEnabled(bool(drafts))
        self.btn_delete_draft.setEnabled(bool(drafts))
        row.addWidget(self.btn_recover_reviews)
        row.addWidget(self.btn_open_draft)
        row.addWidget(self.btn_delete_draft)
        row.addStretch()
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self.btn_restore_latest.clicked.connect(self._open_latest_draft)
        self.btn_delete_all.clicked.connect(self._delete_all_drafts)
        self.btn_recover_reviews.clicked.connect(self._recover_reviews)
        self.btn_open_draft.clicked.connect(self._open_draft)
        self.btn_delete_draft.clicked.connect(self._delete_draft)
        self.btn_close.clicked.connect(self.accept)
        self.draft_list.itemDoubleClicked.connect(lambda *_: self._open_draft())

    def _current_draft(self):
        item = self.draft_list.currentItem()
        if item is None and self.draft_list.count() > 0:
            item = self.draft_list.item(0)
            self.draft_list.setCurrentItem(item)
        return item.data(Qt.UserRole) if item is not None else None

    def _recover_reviews(self):
        self.action = "recover_reviews"
        self.accept()

    def _open_latest_draft(self):
        if self.draft_list.count() <= 0:
            return
        self.draft_list.setCurrentRow(0)
        self._open_draft()

    def _open_draft(self):
        self.selected_draft = self._current_draft()
        if self.selected_draft is None:
            return
        self.action = "open_draft"
        self.accept()

    def _delete_draft(self):
        self.selected_draft = self._current_draft()
        if self.selected_draft is None:
            return
        self.action = "delete_draft"
        self.accept()

    def _delete_all_drafts(self):
        self.selected_drafts = []
        for index in range(self.draft_list.count()):
            item = self.draft_list.item(index)
            if item is not None:
                self.selected_drafts.append(item.data(Qt.UserRole))
        if not self.selected_drafts:
            return
        self.action = "delete_all_drafts"
        self.accept()
