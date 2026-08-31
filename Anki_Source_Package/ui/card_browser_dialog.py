import os
import re
import io
import csv
import html
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QApplication, QMessageBox, QWidget, QShortcut, QMenu
)
from PyQt5.QtCore import Qt, QSize, QEvent, QTimer
from PyQt5.QtGui import QFont, QColor, QKeySequence, QPalette
from theme_manager import get_palette
from data_manager import store
from perf_utils import card_has_due_today
from sm2_engine import sm2_days_left
from storage_paths import iter_cards


def _extract_plain_text(text: str) -> str:
    """Cleanly strip HTML tags and unescape HTML entities for plain text / CSV export."""
    if not text:
        return ""
    # Convert HTML line breaks to newline before stripping other tags
    clean = re.sub(r'<\s*br\s*/?>', '\n', str(text), flags=re.IGNORECASE)
    clean = re.sub(r'</\s*p\s*>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'</\s*div\s*>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<[^>]+>', '', clean)
    clean = html.unescape(clean)
    lines = [line.strip() for line in clean.split('\n')]
    compact_lines = []
    prev_blank = False
    for l in lines:
        if not l:
            if not prev_blank:
                compact_lines.append("")
                prev_blank = True
        else:
            compact_lines.append(l)
            prev_blank = False
    return "\n".join(compact_lines).strip()


def format_cards_as_csv(cards, mode="csv", delimiter=","):
    """
    Format list of card dicts into CSV/delimited text compatible with RFC 4180 / Bulk Importer.
    mode: 'csv' (Question, Answer, Notes) or 'words_only' (Question/Title only)
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
    for card in cards:
        card_type = card.get("card_type", "pdf")
        if card_type == "text":
            q = _extract_plain_text(card.get("question") or card.get("title") or "")
            a = _extract_plain_text(card.get("answer") or "")
            notes = _extract_plain_text(card.get("notes") or "")
            if mode == "words_only":
                if q:
                    writer.writerow([q])
            else:
                if notes:
                    writer.writerow([q, a, notes])
                elif a:
                    writer.writerow([q, a])
                else:
                    writer.writerow([q])
        else:
            title = _extract_plain_text(card.get("title") or os.path.basename(card.get("pdf_path") or card.get("image_path") or ""))
            notes = _extract_plain_text(card.get("notes") or "")
            if mode == "words_only":
                if title:
                    writer.writerow([title])
            else:
                if notes:
                    writer.writerow([title, notes])
                else:
                    writer.writerow([title])
    return output.getvalue()


def _clean_text_preview(text, max_len=120):
    if not text:
        return ""
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Replace multiple whitespaces/newlines with single space
    clean = " ".join(clean.split()).strip()
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean


class CardBrowserDialog(QDialog):
    def __init__(self, parent=None, deck=None, data=None, review_screen=None):
        super().__init__(parent)
        self._deck = deck
        self._data = data if data is not None else getattr(store, "_data", {})
        self._review_screen = review_screen
        
        deck_title = self._deck.get("name", "All Decks") if self._deck else "All Decks"
        self.setWindowTitle(f"📋 Card Manager — {deck_title}")
        self.setMinimumSize(1050, 680)
        self.resize(1150, 740)
        self.setWindowState(Qt.WindowMaximized)
        
        self._all_cards_data = [] # List of tuples: (card, parent_deck)
        self._filtered_indices = []
        
        self._setup_ui()
        self._collect_cards()
        self._populate_table()
        
    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        bg_dark = p.get("C_BG", "#0B0E14")
        card_bg = p.get("C_CARD", "#141824")
        border_col = p.get("C_BORDER", "#2B3347")
        text_col = p.get("C_TEXT", "#FFFFFF")
        subtext_col = p.get("C_SUBTEXT", "#A0AEC0")
        accent_col = p.get("C_ACCENT", "#5C7CFA")
        
        self.setStyleSheet(f"""
            QDialog {{
                background: {bg_dark};
                color: {text_col};
            }}
            QWidget {{
                background: transparent;
                color: {text_col};
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }}
            QLabel {{
                color: {text_col};
                font-size: 13px;
            }}
            QLineEdit {{
                background: {card_bg};
                color: {text_col};
                border: 1.5px solid {border_col};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 14px;
                selection-background-color: {accent_col};
            }}
            QLineEdit:focus {{
                border-color: {accent_col};
                background: #181E2E;
            }}
            QTableWidget {{
                background-color: #0E131F;
                alternate-background-color: #171E2E;
                color: #FFFFFF;
                gridline-color: #242D40;
                border: 1.5px solid {border_col};
                border-radius: 8px;
                selection-background-color: #2D3E66;
                selection-color: #FFFFFF;
                font-size: 13px;
                outline: none;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                color: #FFFFFF;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }}
            QTableWidget::item:selected {{
                background-color: #2D3E66;
                color: #FFFFFF;
            }}
            QTableWidget::item:hover {{
                background-color: #1E283D;
                color: #FFFFFF;
            }}
            QHeaderView::section {{
                background-color: #121622;
                color: {subtext_col};
                padding: 8px;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-right: 1px solid {border_col};
                border-bottom: 2px solid {accent_col};
            }}
            QPushButton {{
                background: #1E2333;
                color: {text_col};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: #283046;
                border-color: {accent_col};
            }}
            QPushButton#btn_copy {{
                background: #059669;
                color: #FFFFFF;
                border: none;
                padding: 9px 20px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton#btn_copy:hover {{
                background: #10B981;
            }}
            QPushButton#btn_delete {{
                background: #DC2626;
                color: #FFFFFF;
                border: none;
                padding: 9px 20px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton#btn_delete:hover {{
                background: #EF4444;
            }}
            QPushButton#btn_edit {{
                background: #3B82F6;
                color: #FFFFFF;
                border: none;
                padding: 9px 20px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton#btn_edit:hover {{
                background: #60A5FA;
            }}
            QMenu {{
                background-color: #141824;
                color: #FFFFFF;
                border: 1px solid {border_col};
                padding: 6px;
                border-radius: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }}
            QMenu::item {{
                padding: 7px 24px 7px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: #2563EB;
                color: #FFFFFF;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {border_col};
                margin: 4px 0;
            }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)
        
        # ── Top Bar: Search + Stats + Select All ──────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search questions, answers, titles, tags... (real-time)")
        self.search_input.textChanged.connect(self._on_search_changed)
        
        def _browser_search_key_press(e):
            if e.key() == Qt.Key_Escape:
                if self.search_input.text():
                    self.search_input.clear()
                    e.accept()
                    return
            QLineEdit.keyPressEvent(self.search_input, e)
        self.search_input.keyPressEvent = _browser_search_key_press
        
        top_bar.addWidget(self.search_input, stretch=1)
        
        self.lbl_stats = QLabel("0 cards")
        self.lbl_stats.setStyleSheet(f"color: {subtext_col}; font-weight: 500; font-size: 13px;")
        top_bar.addWidget(self.lbl_stats)
        
        self.btn_select_all = QPushButton("Select All (Ctrl+A)")
        self.btn_select_all.setCursor(Qt.PointingHandCursor)
        self.btn_select_all.clicked.connect(self._select_all_rows)
        top_bar.addWidget(self.btn_select_all)
        
        main_layout.addLayout(top_bar)
        
        # ── Central Card Table ────────────────────────────────────────────────
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "Type", "Front / Question", "Back / Answer", "Deck", "Status / Due"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        
        # Explicitly enforce dark base and alternateBase colors on QTableWidget palette
        pal = self.table.palette()
        pal.setColor(QPalette.Base, QColor("#0E131F"))
        pal.setColor(QPalette.AlternateBase, QColor("#171E2E"))
        pal.setColor(QPalette.Text, QColor("#FFFFFF"))
        pal.setColor(QPalette.Highlight, QColor("#2D3E66"))
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.table.setPalette(pal)
        
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        
        # Header resize modes
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents) # #
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents) # Type
        header.setSectionResizeMode(2, QHeaderView.Stretch)          # Front
        header.setSectionResizeMode(3, QHeaderView.Stretch)          # Back
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents) # Deck
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents) # Status
        
        main_layout.addWidget(self.table, stretch=1)
        
        # ── Bottom Action Bar ─────────────────────────────────────────────────
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)
        
        self.lbl_selection = QLabel("Selected: 0 cards")
        self.lbl_selection.setStyleSheet(f"color: {accent_col}; font-weight: bold; font-size: 13px;")
        bottom_bar.addWidget(self.lbl_selection)
        
        bottom_bar.addStretch()
        
        self.btn_copy = QPushButton("📋 Copy to Clipboard")
        self.btn_copy.setObjectName("btn_copy")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setToolTip("Copy selected cards (or all cards) to clipboard in comma-separated CSV format (Ctrl+C). Right-click for options.")
        self.btn_copy.clicked.connect(lambda: self._copy_cards_to_clipboard(mode="csv", delimiter=","))
        self.btn_copy.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_copy.customContextMenuRequested.connect(self._show_copy_menu)
        bottom_bar.addWidget(self.btn_copy)
        
        self.btn_edit = QPushButton("✏ Edit Card")
        self.btn_edit.setObjectName("btn_edit")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.setToolTip("Edit selected card (Enter)")
        self.btn_edit.clicked.connect(self._edit_selected_card)
        bottom_bar.addWidget(self.btn_edit)
        
        self.btn_delete = QPushButton("🗑 Delete Selected")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setToolTip("Delete selected cards permanently (Del)")
        self.btn_delete.clicked.connect(self._delete_selected_cards)
        bottom_bar.addWidget(self.btn_delete)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(self.btn_close)
        
        main_layout.addLayout(bottom_bar)
        
        # Shortcuts
        self._shortcut_del = QShortcut(QKeySequence("Delete"), self)
        self._shortcut_del.activated.connect(self._delete_selected_cards)
        
        self._shortcut_select_all = QShortcut(QKeySequence("Ctrl+A"), self)
        self._shortcut_select_all.activated.connect(self._select_all_rows)
        
        self._shortcut_copy = QShortcut(QKeySequence("Ctrl+C"), self)
        self._shortcut_copy.activated.connect(lambda: self._copy_cards_to_clipboard(mode="csv", delimiter=","))

    def _collect_cards(self):
        self._all_cards_data = []
        
        def _walk_deck(d):
            if not d:
                return
            for card in d.get("cards", []):
                self._all_cards_data.append((card, d))
            for sub in d.get("children", []):
                _walk_deck(sub)
            for sub in d.get("subdecks", []):
                _walk_deck(sub)
                
        if self._deck is not None:
            _walk_deck(self._deck)
        else:
            decks = self._data.get("decks", [])
            if isinstance(decks, dict):
                decks = list(decks.values())
            for d in decks:
                _walk_deck(d)
                
    def _populate_table(self):
        query = self.search_input.text().strip().lower()
        self.table.setRowCount(0)
        self._filtered_indices = []
        
        row_idx = 0
        for i, (card, deck) in enumerate(self._all_cards_data):
            card_type = card.get("card_type", "pdf")
            title = card.get("title", "") or ""
            question = card.get("question", "") or ""
            answer = card.get("answer", "") or ""
            notes = card.get("notes", "") or ""
            tags = " ".join(card.get("tags", []))
            deck_name = deck.get("name", "Unknown Deck")
            
            # Type label & icon
            if card_type in ("mcq", "testbook_mcq"):
                type_display = "🎯 MCQ"
                front_display = _clean_text_preview(question) or title
                back_display = _clean_text_preview(answer)
            elif card_type == "text":
                type_display = "🏷️ Text"
                front_display = _clean_text_preview(question) or title
                back_display = _clean_text_preview(answer)
            elif card.get("pdf_path"):
                type_display = "📄 PDF"
                front_display = title or os.path.basename(card.get("pdf_path", ""))
                boxes_count = len(card.get("boxes", []))
                back_display = f"{boxes_count} occlusion mask(s)"
            else:
                type_display = "🖼️ Image"
                front_display = title or os.path.basename(card.get("image_path", ""))
                boxes_count = len(card.get("boxes", []))
                back_display = f"{boxes_count} occlusion mask(s)"
                
            # Check filter query
            searchable = f"{title} {question} {answer} {notes} {tags} {deck_name} {type_display}".lower()
            if query and query not in searchable:
                continue
                
            self._filtered_indices.append(i)
            self.table.insertRow(row_idx)
            
            # Status display
            if card_has_due_today(card):
                status_display = "🔴 Due"
            elif card.get("reviews", 0) == 0:
                status_display = "⭐ New"
            else:
                days = sm2_days_left(card)
                status_display = f"✅ {days}d"
                
            # Row Items
            it_num = QTableWidgetItem(str(row_idx + 1))
            it_num.setTextAlignment(Qt.AlignCenter)
            it_num.setForeground(QColor("#94A3B8"))
            
            it_type = QTableWidgetItem(type_display)
            it_type.setTextAlignment(Qt.AlignCenter)
            it_type.setForeground(QColor("#FFFFFF"))
            
            it_front = QTableWidgetItem(front_display)
            it_front.setToolTip(front_display)
            it_front.setForeground(QColor("#FFFFFF"))
            
            it_back = QTableWidgetItem(back_display)
            it_back.setToolTip(back_display)
            it_back.setForeground(QColor("#E2E8F0"))
            
            it_deck = QTableWidgetItem(deck_name)
            it_deck.setTextAlignment(Qt.AlignCenter)
            it_deck.setForeground(QColor("#94A3B8"))
            
            it_status = QTableWidgetItem(status_display)
            it_status.setTextAlignment(Qt.AlignCenter)
            if "Due" in status_display:
                it_status.setForeground(QColor("#EF4444"))
            elif "New" in status_display:
                it_status.setForeground(QColor("#BD93F9"))
            else:
                it_status.setForeground(QColor("#10B981"))
                
            self.table.setItem(row_idx, 0, it_num)
            self.table.setItem(row_idx, 1, it_type)
            self.table.setItem(row_idx, 2, it_front)
            self.table.setItem(row_idx, 3, it_back)
            self.table.setItem(row_idx, 4, it_deck)
            self.table.setItem(row_idx, 5, it_status)
            
            row_idx += 1
            
        self._update_stats_label()
        self._on_selection_changed()

    def _on_search_changed(self):
        self._populate_table()

    def _update_stats_label(self):
        total = len(self._all_cards_data)
        showing = len(self._filtered_indices)
        if showing == total:
            self.lbl_stats.setText(f"Total: {total} cards")
        else:
            self.lbl_stats.setText(f"Showing {showing} of {total} cards")

    def _on_selection_changed(self):
        selected_rows = set(index.row() for index in self.table.selectedIndexes())
        count = len(selected_rows)
        self.lbl_selection.setText(f"Selected: {count} card{'s' if count != 1 else ''}")
        self.btn_delete.setEnabled(count > 0)
        self.btn_edit.setEnabled(count == 1)

    def _select_all_rows(self):
        self.table.selectAll()

    def _on_item_double_clicked(self, item):
        self._edit_selected_card()

    def _edit_selected_card(self):
        selected_rows = list(set(index.row() for index in self.table.selectedIndexes()))
        if len(selected_rows) != 1:
            return
        row = selected_rows[0]
        if not (0 <= row < len(self._filtered_indices)):
            return
        orig_idx = self._filtered_indices[row]
        card, deck = self._all_cards_data[orig_idx]
        
        card_type = card.get("card_type", "pdf")
        if card_type in ("text", "mcq", "testbook_mcq"):
            from ui.text_card_editor_dialog import TextCardEditorDialog
            dlg = TextCardEditorDialog(self, card=dict(card), data=self._data, deck=deck)
            if dlg.exec_() == QDialog.Accepted:
                edited = dlg.get_card()
                card.update(edited)
                store.mark_dirty()
                if self._review_screen is not None:
                    if hasattr(self._review_screen, "_text_card_cache"):
                        card_id = card.get("_id")
                        self._review_screen._text_card_cache.pop((card_id, True), None)
                        self._review_screen._text_card_cache.pop((card_id, False), None)
                    if hasattr(self._review_screen, "_load_item") and getattr(self._review_screen, "_items", None):
                        self._review_screen._load_item()
                self._collect_cards()
                self._populate_table()
        else:
            from ui.editor_dialog import CardEditorDialog
            dlg = CardEditorDialog(self, card=dict(card), data=self._data)
            if dlg.exec_() == QDialog.Accepted:
                edited = dlg.get_card()
                card.update(edited)
                store.mark_dirty()
                if self._review_screen is not None and hasattr(self._review_screen, "_load_item") and getattr(self._review_screen, "_items", None):
                    self._review_screen._load_item()
                self._collect_cards()
                self._populate_table()

    def _delete_selected_cards(self):
        selected_rows = sorted(list(set(index.row() for index in self.table.selectedIndexes())), reverse=True)
        if not selected_rows:
            return
            
        count = len(selected_rows)
        confirm = QMessageBox.question(
            self,
            "Delete Cards Confirmation",
            f"Are you sure you want to permanently delete {count} selected card{'s' if count != 1 else ''}?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if confirm != QMessageBox.Yes:
            return
            
        cards_to_delete = []
        for r in selected_rows:
            if 0 <= r < len(self._filtered_indices):
                orig_idx = self._filtered_indices[r]
                cards_to_delete.append(self._all_cards_data[orig_idx])
                
        deleted_count = 0
        for card, deck in cards_to_delete:
            cards_list = deck.get("cards", [])
            # Remove by object reference or id
            removed = False
            for i, c in enumerate(cards_list):
                if c is card or (card.get("_id") and c.get("_id") == card.get("_id")):
                    cards_list.pop(i)
                    deleted_count += 1
                    removed = True
                    break
                    
            # If opened from review screen, remove from active review items
            if self._review_screen is not None and hasattr(self._review_screen, "_items"):
                rev = self._review_screen
                rev._items = [
                    item for item in rev._items 
                    if not (item[0] is card or (card.get("_id") and item[0].get("_id") == card.get("_id")))
                ]
                if hasattr(rev, "_text_card_cache"):
                    card_id = card.get("_id")
                    rev._text_card_cache.pop((card_id, True), None)
                    rev._text_card_cache.pop((card_id, False), None)
                    
        if deleted_count > 0:
            store.mark_dirty()
            try:
                store.save_force(async_save=True)
            except Exception:
                pass
                
            self._collect_cards()
            self._populate_table()
            
            # If review screen is open, refresh progress
            if self._review_screen is not None:
                rev = self._review_screen
                if hasattr(rev, "prog") and hasattr(rev, "lbl_prog"):
                    rev.prog.setMaximum(len(rev._items))
                    if rev._items:
                        rev._idx = min(rev._idx, len(rev._items) - 1)
                        rev.lbl_prog.setText(f"Card {rev._idx + 1}/{len(rev._items)}")
                        rev._load_item()
                    else:
                        rev._finish_session()

    def _show_toast(self, msg: str):
        if not hasattr(self, "_toast_label") or self._toast_label is None:
            self._toast_label = QLabel(self)
            self._toast_label.setStyleSheet("""
                background-color: rgba(15, 23, 42, 0.95);
                color: #38BDF8;
                border: 1.5px solid #0284C7;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            """)
            self._toast_label.hide()
            
        if not hasattr(self, "_toast_timer") or self._toast_timer is None:
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._hide_toast)
            
        self._toast_label.setText(msg)
        self._toast_label.adjustSize()
        self._toast_label.move((self.width() - self._toast_label.width()) // 2, max(20, self.height() - 90))
        self._toast_label.show()
        self._toast_label.raise_()
        self._toast_timer.start(2500)

    def _hide_toast(self):
        if hasattr(self, "_toast_label") and self._toast_label is not None:
            self._toast_label.hide()

    def _copy_cards_to_clipboard(self, mode="csv", delimiter=","):
        """Copy selected cards (or all visible cards if none selected) to system clipboard."""
        selected_rows = sorted(list(set(index.row() for index in self.table.selectedIndexes())))
        if selected_rows:
            target_indices = [self._filtered_indices[r] for r in selected_rows if 0 <= r < len(self._filtered_indices)]
        else:
            target_indices = list(self._filtered_indices)
            
        if not target_indices:
            self._show_toast("⚠ No cards to copy")
            return
            
        cards_to_export = [self._all_cards_data[idx][0] for idx in target_indices]
        text = format_cards_as_csv(cards_to_export, mode=mode, delimiter=delimiter)
        
        cb = QApplication.clipboard()
        if cb:
            cb.setText(text)
            
        count = len(cards_to_export)
        mode_label = "words only" if mode == "words_only" else ("TSV" if delimiter == "\t" else "comma-separated CSV")
        self._show_toast(f"📋 Copied {count} card{'s' if count != 1 else ''} to clipboard ({mode_label})!")

    def _show_copy_menu(self, pos):
        menu = QMenu(self)
        act_csv = menu.addAction("📋 Copy as Comma-Separated (CSV: Word, Meaning)")
        act_csv.triggered.connect(lambda: self._copy_cards_to_clipboard(mode="csv", delimiter=","))
        
        act_words = menu.addAction("📝 Copy Questions / Words Only")
        act_words.triggered.connect(lambda: self._copy_cards_to_clipboard(mode="words_only"))
        
        act_tsv = menu.addAction("📑 Copy as Tab-Separated (TSV)")
        act_tsv.triggered.connect(lambda: self._copy_cards_to_clipboard(mode="csv", delimiter="\t"))
        
        menu.exec_(self.btn_copy.mapToGlobal(pos))

    def _show_table_context_menu(self, pos):
        menu = QMenu(self)
        act_csv = menu.addAction("📋 Copy Selected (CSV: Word, Meaning)")
        act_csv.triggered.connect(lambda: self._copy_cards_to_clipboard(mode="csv", delimiter=","))
        
        act_words = menu.addAction("📝 Copy Selected (Words Only)")
        act_words.triggered.connect(lambda: self._copy_cards_to_clipboard(mode="words_only"))
        
        act_tsv = menu.addAction("📑 Copy Selected (TSV)")
        act_tsv.triggered.connect(lambda: self._copy_cards_to_clipboard(mode="csv", delimiter="\t"))
        
        menu.addSeparator()
        selected_rows = set(index.row() for index in self.table.selectedIndexes())
        if len(selected_rows) == 1:
            act_edit = menu.addAction("✏ Edit Card")
            act_edit.triggered.connect(self._edit_selected_card)
        if len(selected_rows) > 0:
            act_del = menu.addAction("🗑 Delete Selected")
            act_del.triggered.connect(self._delete_selected_cards)
            
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        
        if key in (Qt.Key_Delete, Qt.Key_Backspace) and not clean_mods:
            self._delete_selected_cards()
            e.accept()
            return
        elif (clean_mods & Qt.ControlModifier) and key == Qt.Key_A:
            self._select_all_rows()
            e.accept()
            return
        elif (clean_mods & Qt.ControlModifier) and key == Qt.Key_C:
            self._copy_cards_to_clipboard(mode="csv", delimiter=",")
            e.accept()
            return
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._edit_selected_card()
            e.accept()
            return
        super().keyPressEvent(e)
