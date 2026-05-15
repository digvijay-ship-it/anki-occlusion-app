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


class RecoveryDialog(QDialog):
    def __init__(self, summary, parent=None, startup=False):
        super().__init__(parent)
        self.summary = summary or {}
        self.action = "close"
        self.selected_draft = None
        self.setWindowTitle("Recovery Center")
        self.setMinimumWidth(560)
        self.setModal(bool(startup))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Recover unsaved work")
        title.setStyleSheet("font-size:16px;font-weight:bold;")
        layout.addWidget(title)

        events = self.summary.get("review_events", []) or []
        recoverable = [event for event in events if event.get("status") == "recoverable"]
        blocked = [event for event in events if event.get("status") != "recoverable"]
        event_text = f"Review checkpoints ready: {len(recoverable)}"
        if blocked:
            event_text += f"  |  Needs attention: {len(blocked)}"
        self.event_label = QLabel(event_text)
        self.event_label.setWordWrap(True)
        layout.addWidget(self.event_label)

        self.draft_list = QListWidget()
        self.draft_list.setMinimumHeight(180)
        for draft in self.summary.get("drafts", []) or []:
            card = draft.get("card", {}) or {}
            deck = draft.get("deck", {}) or {}
            title_text = card.get("title") or "Untitled draft"
            source = card.get("pdf_path") or card.get("image_path") or "no source"
            boxes = len(card.get("boxes", []) or [])
            updated = draft.get("updated_at", "?")
            deck_name = deck.get("name") or "unknown deck"
            item = QListWidgetItem(
                f"{title_text}  |  {deck_name}  |  boxes:{boxes}  |  {updated}\n{source}"
            )
            item.setData(Qt.UserRole, draft)
            self.draft_list.addItem(item)
        layout.addWidget(self.draft_list)

        row = QHBoxLayout()
        self.btn_recover_reviews = QPushButton("Recover Review Progress")
        self.btn_open_draft = QPushButton("Open Draft")
        self.btn_delete_draft = QPushButton("Delete Draft")
        self.btn_close = QPushButton("Close")
        self.btn_recover_reviews.setEnabled(bool(recoverable))
        self.btn_open_draft.setEnabled(self.draft_list.count() > 0)
        self.btn_delete_draft.setEnabled(self.draft_list.count() > 0)
        row.addWidget(self.btn_recover_reviews)
        row.addWidget(self.btn_open_draft)
        row.addWidget(self.btn_delete_draft)
        row.addStretch()
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self.btn_recover_reviews.clicked.connect(self._recover_reviews)
        self.btn_open_draft.clicked.connect(self._open_draft)
        self.btn_delete_draft.clicked.connect(self._delete_draft)
        self.btn_close.clicked.connect(self.accept)

    def _current_draft(self):
        item = self.draft_list.currentItem()
        if item is None and self.draft_list.count() > 0:
            item = self.draft_list.item(0)
            self.draft_list.setCurrentItem(item)
        return item.data(Qt.UserRole) if item is not None else None

    def _recover_reviews(self):
        self.action = "recover_reviews"
        self.accept()

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
