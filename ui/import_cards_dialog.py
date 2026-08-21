# -*- coding: utf-8 -*-
import os
import io
import csv
import uuid
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton,
    QButtonGroup, QComboBox, QCheckBox, QFileDialog, QMessageBox, QFrame,
    QTabWidget, QWidget, QApplication, QSplitter
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor
from theme_manager import get_palette, normalize_theme
from sm2_engine import sm2_init
from data_manager import find_deck_by_id, next_deck_id, deck_history, store


def parse_delimited_text(text: str, delimiter: str = ",", has_header: bool = False, strip_whitespace: bool = True) -> list:
    """
    Parse delimited text into a list of card data dicts:
    [{'question': ..., 'answer': ..., 'notes': ...}, ...]
    Handles standard CSV quoting, escaping, newlines, and various separators.
    """
    if not text or not text.strip():
        return []

    # Map escaped tab representations
    if delimiter in (r"\t", "\\t"):
        delimiter = "\t"

    results = []
    # Use StringIO and csv.reader for standard RFC 4180 parsing
    f = io.StringIO(text)
    try:
        reader = csv.reader(f, delimiter=delimiter, skipinitialspace=strip_whitespace)
        rows = list(reader)
    except Exception:
        # Fallback line-by-line if csv.reader encounters unexpected delimiter issue
        rows = []
        for line in text.splitlines():
            line_str = line.strip() if strip_whitespace else line
            if not line_str:
                continue
            rows.append(line.split(delimiter))

    if has_header and rows:
        # Skip header if present
        rows = rows[1:]

    for row in rows:
        if not row:
            continue
        cleaned = [cell.strip() if strip_whitespace else cell for cell in row]
        # Remove trailing empty cells
        while cleaned and cleaned[-1] == "":
            cleaned.pop()
        if not cleaned:
            continue

        q = cleaned[0] if len(cleaned) > 0 else ""
        a = cleaned[1] if len(cleaned) > 1 else ""
        notes = cleaned[2] if len(cleaned) > 2 else ""

        if not q and not a:
            continue

        results.append({
            "question": q,
            "answer": a,
            "notes": notes
        })

    return results


def build_text_card(question: str, answer: str, notes: str = "", tags: list = None) -> dict:
    """Build a fully-formed SM-2 initialized text card dictionary."""
    lines = [line.strip() for line in question.split("\n") if line.strip()]
    first_line = lines[0] if lines else "Untitled"
    title = first_line[:45] + "..." if len(first_line) > 45 else first_line
    if not title:
        title = "Untitled"

    card = {
        "_id": str(uuid.uuid4()),
        "card_type": "text",
        "title": title,
        "question": question,
        "answer": answer,
        "notes": notes,
        "tags": tags or [],
        "created": datetime.now().isoformat(),
        "reviews": 0,
        "pdf_path": None,
        "image_path": None,
        "boxes": [],
        "is_formula": False
    }
    sm2_init(card)
    return card


class ImportCardsDialog(QDialog):
    def __init__(self, parent=None, data=None, current_deck=None):
        super().__init__(parent)
        self.setWindowTitle("📥 Bulk Card Importer & Vocab Checker")
        self.resize(980, 740)
        self.setMinimumSize(820, 620)
        self._data = data or {"decks": []}
        self._current_deck = current_deck
        self._parsed_rows = []
        self._file_content = ""
        self._imported_count = 0
        self._skipped_duplicates_count = 0
        self._target_deck_id = None
        self._is_new_deck = False

        self._existing_cards_map = {}  # norm_question -> list of (deck_id, deck_name)
        self._build_existing_cards_index()

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._reparse_and_preview)

        self._setup_ui()
        self._populate_decks()
        self._reparse_and_preview()

    def _build_existing_cards_index(self):
        """Index all existing cards by normalized question text for instant O(1) duplicate checks."""
        self._existing_cards_map = {}

        def _walk(decks):
            for d in decks or []:
                if not isinstance(d, dict):
                    continue
                d_id = d.get("_id")
                d_name = d.get("name", "Untitled")
                for card in d.get("cards", []) or []:
                    if not isinstance(card, dict):
                        continue
                    q = (card.get("question") or card.get("title") or "").strip().lower()
                    if q:
                        self._existing_cards_map.setdefault(q, []).append((d_id, d_name))
                _walk(d.get("children", []))

        _walk(self._data.get("decks", []))

    def _setup_ui(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        self._theme_p = p

        self.setStyleSheet(f"""
            QDialog {{
                background: {p['C_BG']};
                color: {p['C_TEXT']};
                font-family: 'Segoe UI', sans-serif;
            }}
            QWidget {{
                background: {p['C_BG']};
                color: {p['C_TEXT']};
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }}
            QLabel {{
                background: transparent;
                color: {p['C_TEXT']};
            }}
            QLabel#header_title {{
                font-size: 17px;
                font-weight: bold;
                color: {p.get('C_PURPLE', p['C_ACCENT'])};
            }}
            QLabel#header_sub {{
                font-size: 12px;
                color: {p['C_SUBTEXT']};
            }}
            QTabWidget::pane {{
                border: 1px solid {p['C_BORDER']};
                background: {p['C_SURFACE']};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                background: {p['C_CARD']};
                color: {p['C_SUBTEXT']};
                padding: 7px 18px;
                margin-right: 4px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                background: {p['C_SURFACE']};
                color: {p['C_TEXT']};
                border-bottom: 2px solid {p['C_ACCENT']};
            }}
            QLineEdit, QPlainTextEdit, QComboBox {{
                background: {p['C_CARD']};
                color: {p['C_TEXT']};
                border: 1px solid {p['C_BORDER']};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {p['C_ACCENT']};
            }}
            QTableWidget {{
                background: {p['C_CARD']};
                color: {p['C_TEXT']};
                border: 1px solid {p['C_BORDER']};
                border-radius: 6px;
                gridline-color: {p['C_BORDER']};
                selection-background-color: {p['C_ACCENT']};
                selection-color: white;
            }}
            QHeaderView::section {{
                background: {p['C_SURFACE']};
                color: {p['C_TEXT']};
                padding: 6px;
                border: 1px solid {p['C_BORDER']};
                font-weight: bold;
            }}
            QRadioButton, QCheckBox {{
                background: transparent;
                color: {p['C_TEXT']};
            }}
            QPushButton {{
                background: {p['C_SURFACE']};
                color: {p['C_TEXT']};
                border: 1px solid {p['C_BORDER']};
                border-radius: 5px;
                padding: 7px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {p['C_CARD']};
                border-color: {p['C_ACCENT']};
            }}
            QPushButton#primary_import {{
                background: {p['C_GREEN']};
                color: {p['C_BG'] if theme in ('dojo', 'manhattan') else '#111827'};
                border: none;
                padding: 8px 22px;
                font-size: 13px;
            }}
            QPushButton#primary_import:hover {{
                background: #6BE88D;
            }}
            QPushButton#primary_import:disabled {{
                background: {p['C_BORDER']};
                color: {p['C_SUBTEXT']};
            }}
            QFrame#card_box {{
                background: {p['C_SURFACE']};
                border: 1px solid {p['C_BORDER']};
                border-radius: 6px;
                padding: 10px;
            }}
        """)

        main_l = QVBoxLayout(self)
        main_l.setContentsMargins(18, 18, 18, 18)
        main_l.setSpacing(12)

        # ── Header ──
        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(2)
        lbl_title = QLabel("📥 Bulk Card Importer & Vocab Checker")
        lbl_title.setObjectName("header_title")
        lbl_sub = QLabel("Import vocabulary and question-answer cards with automatic duplicate detection & skipping.")
        lbl_sub.setObjectName("header_sub")
        hdr_box.addWidget(lbl_title)
        hdr_box.addWidget(lbl_sub)
        main_l.addLayout(hdr_box)

        # ── Splitter between (Input & Config) and (Live Preview) ──
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # ── Upper Container: Input Tabs + Config ──
        upper_widget = QWidget()
        upper_l = QVBoxLayout(upper_widget)
        upper_l.setContentsMargins(0, 0, 0, 0)
        upper_l.setSpacing(10)

        # Tabs: Paste Text vs Browse File
        self.tabs = QTabWidget()
        
        # Tab 1: Paste Text
        tab_paste = QWidget()
        paste_l = QVBoxLayout(tab_paste)
        paste_l.setContentsMargins(8, 8, 8, 8)
        self.txt_paste = QPlainTextEdit()
        self.txt_paste.setPlaceholderText(
            "Paste comma-separated vocabulary or cards here. Example:\n"
            "Abundant, Existing or available in large quantities; plentiful\n"
            "Ephemeral, Lasting for a very short time\n"
            "\"Ubiquitous, or everywhere\", Present, appearing, or found everywhere"
        )
        self.txt_paste.textChanged.connect(self._on_input_changed)
        paste_l.addWidget(self.txt_paste)
        self.tabs.addTab(tab_paste, "📋 Paste Raw Text")

        # Tab 2: Browse File
        tab_file = QWidget()
        file_l = QVBoxLayout(tab_file)
        file_l.setContentsMargins(12, 12, 12, 12)
        file_l.setSpacing(10)

        f_row = QHBoxLayout()
        self.inp_file_path = QLineEdit()
        self.inp_file_path.setPlaceholderText("Select a .txt, .csv, or .tsv file...")
        self.inp_file_path.setReadOnly(True)
        btn_browse = QPushButton("📂 Browse...")
        btn_browse.clicked.connect(self._browse_file)
        f_row.addWidget(self.inp_file_path)
        f_row.addWidget(btn_browse)
        file_l.addLayout(f_row)

        self.lbl_file_info = QLabel("No file selected yet.")
        self.lbl_file_info.setStyleSheet(f"color: {p['C_SUBTEXT']};")
        file_l.addWidget(self.lbl_file_info)
        file_l.addStretch()
        self.tabs.addTab(tab_file, "📁 Choose File (.txt / .csv / .tsv)")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        upper_l.addWidget(self.tabs)

        # Config Panel (Delimiter, Duplicate Policy, Destination Deck)
        cfg_frame = QFrame()
        cfg_frame.setObjectName("card_box")
        cfg_l = QVBoxLayout(cfg_frame)
        cfg_l.setContentsMargins(10, 10, 10, 10)
        cfg_l.setSpacing(8)

        # Row 1: Delimiter + Formatting Options
        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        
        lbl_delim = QLabel("Separator:")
        lbl_delim.setStyleSheet("font-weight: bold;")
        opt_row.addWidget(lbl_delim)

        self.combo_delim = QComboBox()
        self.combo_delim.addItems([
            "Comma ( , )",
            "Tab ( \\t )",
            "Semicolon ( ; )",
            "Pipe ( | )",
            "Custom..."
        ])
        self.combo_delim.currentIndexChanged.connect(self._on_delim_changed)
        opt_row.addWidget(self.combo_delim)

        self.inp_custom_delim = QLineEdit()
        self.inp_custom_delim.setPlaceholderText("Custom char")
        self.inp_custom_delim.setMaximumWidth(80)
        self.inp_custom_delim.hide()
        self.inp_custom_delim.textChanged.connect(self._on_input_changed)
        opt_row.addWidget(self.inp_custom_delim)

        self.chk_header = QCheckBox("Ignore 1st row (Header)")
        self.chk_header.toggled.connect(self._on_input_changed)
        opt_row.addWidget(self.chk_header)

        self.chk_trim = QCheckBox("Trim spaces")
        self.chk_trim.setChecked(True)
        self.chk_trim.toggled.connect(self._on_input_changed)
        opt_row.addWidget(self.chk_trim)

        opt_row.addStretch()
        cfg_l.addLayout(opt_row)

        # Row 2: Duplicate Detection & Policy
        dup_row = QHBoxLayout()
        dup_row.setSpacing(12)

        lbl_dup = QLabel("Duplicate Policy:")
        lbl_dup.setStyleSheet("font-weight: bold;")
        dup_row.addWidget(lbl_dup)

        self.chk_skip_duplicates = QCheckBox("🛡️ Auto-skip duplicate cards / words (Recommended)")
        self.chk_skip_duplicates.setChecked(True)
        self.chk_skip_duplicates.toggled.connect(self._on_input_changed)
        dup_row.addWidget(self.chk_skip_duplicates)

        self.chk_check_all_decks = QCheckBox("Check across all decks")
        self.chk_check_all_decks.setChecked(True)
        self.chk_check_all_decks.setToolTip("If unchecked, only checks for duplicates in the target deck.")
        self.chk_check_all_decks.toggled.connect(self._on_input_changed)
        dup_row.addWidget(self.chk_check_all_decks)

        dup_row.addStretch()
        cfg_l.addLayout(dup_row)

        # Row 3: Target Destination Deck
        dest_row = QHBoxLayout()
        dest_row.setSpacing(12)

        lbl_dest = QLabel("Destination:")
        lbl_dest.setStyleSheet("font-weight: bold;")
        dest_row.addWidget(lbl_dest)

        self.rb_new_deck = QRadioButton("Create New Deck:")
        self.rb_new_deck.setChecked(True)
        self.rb_new_deck.toggled.connect(self._on_dest_mode_changed)
        dest_row.addWidget(self.rb_new_deck)

        self.inp_new_deck_name = QLineEdit("Vocabulary")
        self.inp_new_deck_name.setPlaceholderText("Enter new deck name...")
        dest_row.addWidget(self.inp_new_deck_name, stretch=2)

        self.rb_existing_deck = QRadioButton("Add to Deck:")
        dest_row.addWidget(self.rb_existing_deck)

        self.combo_existing_decks = QComboBox()
        self.combo_existing_decks.setEnabled(False)
        self.combo_existing_decks.currentIndexChanged.connect(self._on_input_changed)
        dest_row.addWidget(self.combo_existing_decks, stretch=2)

        dest_row.addStretch()
        cfg_l.addLayout(dest_row)

        upper_l.addWidget(cfg_frame)
        splitter.addWidget(upper_widget)

        # ── Lower Container: Live Preview Table with Duplicate Status ──
        lower_widget = QWidget()
        lower_l = QVBoxLayout(lower_widget)
        lower_l.setContentsMargins(0, 0, 0, 0)
        lower_l.setSpacing(6)

        preview_hdr = QHBoxLayout()
        self.lbl_preview_count = QLabel("🔍 Live Preview (0 cards parsed)")
        self.lbl_preview_count.setStyleSheet("font-weight: bold;")
        preview_hdr.addWidget(self.lbl_preview_count)
        preview_hdr.addStretch()

        self.lbl_summary_badge = QLabel("")
        self.lbl_summary_badge.setStyleSheet("font-weight: bold;")
        preview_hdr.addWidget(self.lbl_summary_badge)
        lower_l.addLayout(preview_hdr)

        self.table_preview = QTableWidget(0, 4)
        self.table_preview.setHorizontalHeaderLabels(["#", "Front (Word / Question)", "Back (Meaning / Answer)", "Duplicate Status"])
        self.table_preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_preview.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_preview.setAlternatingRowColors(True)
        self.table_preview.setEditTriggers(QTableWidget.NoEditTriggers)
        lower_l.addWidget(self.table_preview)

        splitter.addWidget(lower_widget)
        splitter.setSizes([330, 260])
        main_l.addWidget(splitter, stretch=1)

        # ── Bottom Action Row ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {p['C_SUBTEXT']};")
        btn_row.addWidget(self.lbl_status)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_import = QPushButton("📥 Import Cards")
        self.btn_import.setObjectName("primary_import")
        self.btn_import.clicked.connect(self._do_import)
        btn_row.addWidget(self.btn_import)

        main_l.addLayout(btn_row)

    def _populate_decks(self):
        self.combo_existing_decks.clear()
        deck_items = []

        def _walk(decks, prefix=""):
            for d in decks or []:
                dname = f"{prefix}{d.get('name', 'Untitled')}"
                deck_items.append((dname, d.get("_id")))
                _walk(d.get("children", []), prefix=f"{dname} > ")

        _walk(self._data.get("decks", []))

        current_idx = 0
        for i, (name, did) in enumerate(deck_items):
            self.combo_existing_decks.addItem(name, did)
            if self._current_deck and self._current_deck.get("_id") == did:
                current_idx = i

        if deck_items:
            self.combo_existing_decks.setCurrentIndex(current_idx)
            if self._current_deck:
                self.rb_existing_deck.setChecked(True)
                self._on_dest_mode_changed()
        else:
            self.rb_existing_deck.setEnabled(False)
            self.rb_new_deck.setChecked(True)

    def _get_current_delimiter(self) -> str:
        idx = self.combo_delim.currentIndex()
        if idx == 0:
            return ","
        elif idx == 1:
            return "\t"
        elif idx == 2:
            return ";"
        elif idx == 3:
            return "|"
        else:
            custom = self.inp_custom_delim.text()
            return custom if custom else ","

    def _on_delim_changed(self, idx):
        if idx == 4:
            self.inp_custom_delim.show()
            self.inp_custom_delim.setFocus()
        else:
            self.inp_custom_delim.hide()
        self._on_input_changed()

    def _on_dest_mode_changed(self):
        is_new = self.rb_new_deck.isChecked()
        self.inp_new_deck_name.setEnabled(is_new)
        self.combo_existing_decks.setEnabled(not is_new)
        self._on_input_changed()

    def _on_tab_changed(self, idx):
        self._on_input_changed()

    def _on_input_changed(self):
        self._debounce_timer.start()

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Text or CSV File",
            "",
            "Text / CSV Files (*.txt *.csv *.tsv);;CSV Files (*.csv);;Text Files (*.txt);;All Files (*.*)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="latin-1") as f:
                    content = f.read()
            except Exception as e:
                QMessageBox.critical(self, "Read Error", f"Could not read file:\n{e}")
                return
        except Exception as e:
            QMessageBox.critical(self, "Read Error", f"Could not read file:\n{e}")
            return

        self._file_content = content
        self.inp_file_path.setText(path)
        base_name = os.path.splitext(os.path.basename(path))[0]
        self.lbl_file_info.setText(f"Loaded: {os.path.basename(path)} ({len(content)} characters)")
        if self.inp_new_deck_name.text() in ("", "Vocabulary", "Imported Cards"):
            self.inp_new_deck_name.setText(base_name)

        # Auto-detect tab delimiter if TSV
        if path.lower().endswith(".tsv"):
            self.combo_delim.setCurrentIndex(1)
        elif path.lower().endswith(".csv"):
            self.combo_delim.setCurrentIndex(0)

        self._reparse_and_preview()

    def _check_card_duplicate(self, question: str, target_deck_id=None, check_all=True) -> tuple:
        """
        Check if a card's question already exists.
        Returns (is_duplicate: bool, location_desc: str)
        """
        norm_q = question.strip().lower()
        if not norm_q:
            return False, ""

        matches = self._existing_cards_map.get(norm_q, [])
        if not matches:
            return False, ""

        if check_all:
            # Return first deck location where it appears
            deck_names = [name for (_, name) in matches]
            loc_str = f"in '{deck_names[0]}'" if len(deck_names) == 1 else f"in {len(deck_names)} decks"
            return True, loc_str
        else:
            # Check specifically in target deck
            if target_deck_id is not None:
                for did, name in matches:
                    if did == target_deck_id:
                        return True, f"in this deck ('{name}')"

        return False, ""

    def _reparse_and_preview(self):
        # Choose active text source
        if self.tabs.currentIndex() == 0:
            text = self.txt_paste.toPlainText()
        else:
            text = self._file_content

        delim = self._get_current_delimiter()
        has_header = self.chk_header.isChecked()
        trim = self.chk_trim.isChecked()
        check_all = self.chk_check_all_decks.isChecked()
        target_did = self.combo_existing_decks.currentData() if self.rb_existing_deck.isChecked() else None

        parsed = parse_delimited_text(text, delimiter=delim, has_header=has_header, strip_whitespace=trim)
        
        # Analyze duplicates
        seen_in_batch = set()
        new_count = 0
        dup_count = 0

        for item in parsed:
            q = item["question"]
            norm_q = q.strip().lower()
            
            # Check internal duplicates within the current pasted batch
            if norm_q in seen_in_batch:
                item["is_duplicate"] = True
                item["dup_location"] = "in this batch"
                dup_count += 1
            else:
                is_dup, loc_desc = self._check_card_duplicate(q, target_deck_id=target_did, check_all=check_all)
                item["is_duplicate"] = is_dup
                item["dup_location"] = loc_desc
                if is_dup:
                    dup_count += 1
                else:
                    new_count += 1
                if norm_q:
                    seen_in_batch.add(norm_q)

        self._parsed_rows = parsed
        total_count = len(parsed)

        # Update Summary Badge
        if total_count > 0:
            if dup_count > 0:
                self.lbl_summary_badge.setText(f"✨ {new_count} New   |   ⚠️ {dup_count} Duplicates Detected")
                self.lbl_summary_badge.setStyleSheet("color: #FFB86C; font-weight: bold;")
            else:
                self.lbl_summary_badge.setText(f"✅ All {new_count} cards are unique and new!")
                self.lbl_summary_badge.setStyleSheet(f"color: {self._theme_p.get('C_GREEN', '#50FA7B')}; font-weight: bold;")
        else:
            self.lbl_summary_badge.setText("")

        self.lbl_preview_count.setText(f"🔍 Live Preview ({total_count} total cards)")

        # Populate Table
        self.table_preview.setRowCount(total_count)
        for row_idx, item in enumerate(parsed):
            # Column 0: Index
            it_idx = QTableWidgetItem(str(row_idx + 1))
            it_idx.setTextAlignment(Qt.AlignCenter)
            self.table_preview.setItem(row_idx, 0, it_idx)

            # Column 1: Front (Question / Word)
            it_q = QTableWidgetItem(item["question"])
            self.table_preview.setItem(row_idx, 1, it_q)

            # Column 2: Back (Answer / Meaning)
            it_a = QTableWidgetItem(item["answer"])
            if not item["answer"]:
                it_a.setForeground(QColor(self._theme_p.get("C_ORANGE", "#FFB86C")))
                it_a.setText("[Empty Back]")
            self.table_preview.setItem(row_idx, 2, it_a)

            # Column 3: Duplicate Status
            if item["is_duplicate"]:
                it_status = QTableWidgetItem(f"⚠️ Duplicate ({item['dup_location']})")
                it_status.setForeground(QColor("#FFB86C"))
            else:
                it_status = QTableWidgetItem("✅ New")
                it_status.setForeground(QColor(self._theme_p.get("C_GREEN", "#50FA7B")))
            self.table_preview.setItem(row_idx, 3, it_status)

        # Update button text & enabled state
        skip_dups = self.chk_skip_duplicates.isChecked()
        import_target_count = new_count if skip_dups else total_count

        self.btn_import.setEnabled(import_target_count > 0)
        if skip_dups and dup_count > 0:
            self.btn_import.setText(f"📥 Import {new_count} New Cards (Skip {dup_count} Dups)")
        elif total_count > 0:
            self.btn_import.setText(f"📥 Import {total_count} Card{'s' if total_count != 1 else ''}")
        else:
            self.btn_import.setText("📥 Import Cards")

    def _do_import(self):
        if not self._parsed_rows:
            QMessageBox.warning(self, "No Cards", "No valid cards detected to import.")
            return

        is_new_deck = self.rb_new_deck.isChecked()
        deck_name = self.inp_new_deck_name.text().strip()

        if is_new_deck and not deck_name:
            QMessageBox.warning(self, "Deck Name Required", "Please enter a name for the new deck.")
            self.inp_new_deck_name.setFocus()
            return

        skip_dups = self.chk_skip_duplicates.isChecked()

        # Build cards to import
        new_cards = []
        skipped_count = 0

        for row in self._parsed_rows:
            if skip_dups and row.get("is_duplicate", False):
                skipped_count += 1
                continue

            card = build_text_card(
                question=row["question"],
                answer=row["answer"],
                notes=row.get("notes", "")
            )
            new_cards.append(card)

        if not new_cards:
            QMessageBox.information(
                self,
                "All Cards Skipped",
                "All cards in the import data were detected as duplicates and skipped according to your duplicate policy."
            )
            return

        # Snapshot for undo
        deck_history.push(self._data)

        if is_new_deck:
            new_id = next_deck_id(self._data)
            new_deck = {
                "_id": new_id,
                "name": deck_name,
                "cards": new_cards,
                "children": [],
                "expanded": False
            }
            self._data.setdefault("decks", []).append(new_deck)
            self._target_deck_id = new_id
            self._is_new_deck = True
        else:
            target_id = self.combo_existing_decks.currentData()
            target_deck = find_deck_by_id(target_id, self._data.get("decks", []))
            if not target_deck:
                QMessageBox.critical(self, "Error", "Target deck could not be found.")
                return
            target_deck.setdefault("cards", []).extend(new_cards)
            self._target_deck_id = target_id
            self._is_new_deck = False

        self._imported_count = len(new_cards)
        self._skipped_duplicates_count = skipped_count
        store.mark_dirty()
        store.save_force(async_save=True)

        self.accept()

    def get_result(self) -> dict:
        """Returns details about the completed import operation."""
        return {
            "count": self._imported_count,
            "skipped_duplicates": self._skipped_duplicates_count,
            "target_deck_id": self._target_deck_id,
            "is_new_deck": self._is_new_deck
        }
