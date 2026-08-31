# -*- coding: utf-8 -*-
import os
import io
import csv
import json
import uuid
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton,
    QButtonGroup, QComboBox, QCheckBox, QFileDialog, QMessageBox, QFrame,
    QTabWidget, QWidget, QApplication, QSplitter
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QPalette
from theme_manager import get_palette, normalize_theme
from sm2_engine import sm2_init
from data_manager import find_deck_by_id, next_deck_id, deck_history, store, get_or_create_deck_by_path


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


def build_text_card(
    question: str,
    answer: str,
    notes: str = "",
    tags: list = None,
    context_anchor: str = "",
    chain_order: int = 0,
    parent_chain_id: str = None,
    trap_note: str = "",
    priority_tier: int = 1
) -> dict:
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
        "trap_note": trap_note or notes,
        "context_anchor": context_anchor or "",
        "chain_order": int(chain_order or 0),
        "parent_chain_id": parent_chain_id,
        "priority_tier": int(priority_tier or 1),
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


def build_mcq_card(
    question: str,
    options: list,
    correct_option: any = None,
    solution_data: dict = None,
    percent_answered_correctly: str = "",
    exam_meta: dict = None,
    notes: str = "",
    trap_note: str = "",
    context_anchor: str = "",
    chain_order: int = 0,
    parent_chain_id: str = None,
    priority_tier: int = 1,
    tags: list = None,
    question_html: str = ""
) -> dict:
    """Build a fully-formed SM-2 initialized interactive MCQ card dictionary."""
    import re
    clean_q = re.sub(r'<[^>]+>', ' ', question).strip()
    lines = [line.strip() for line in clean_q.split("\n") if line.strip()]
    first_line = lines[0] if lines else "Untitled MCQ"
    title = first_line[:45] + "..." if len(first_line) > 45 else first_line
    if not title:
        title = "Untitled MCQ"

    # Find answer text for fallback
    ans_text = ""
    if isinstance(correct_option, dict):
        lbl = correct_option.get("label", "")
        txt = correct_option.get("text", "")
        ans_text = f"Option {lbl}: {txt}" if txt else f"Option {lbl}"
    elif isinstance(correct_option, str):
        ans_text = correct_option
    elif options:
        for opt in options:
            if isinstance(opt, dict) and opt.get("is_correct"):
                ans_text = f"Option {opt.get('label', '')}: {opt.get('text', '')}"
                break

    card = {
        "_id": str(uuid.uuid4()),
        "card_type": "mcq",
        "title": title,
        "question": question,
        "question_html": question_html or question,
        "answer": ans_text,
        "options": options or [],
        "correct_option": correct_option,
        "solution_data": solution_data or {},
        "percent_answered_correctly": percent_answered_correctly or "",
        "exam_meta": exam_meta or {},
        "notes": notes,
        "trap_note": trap_note or notes,
        "context_anchor": context_anchor or "",
        "chain_order": int(chain_order or 0),
        "parent_chain_id": parent_chain_id,
        "priority_tier": int(priority_tier or 1),
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


def parse_testbook_or_mcq_json(text: str) -> tuple:
    """
    Parse Testbook / Mock Exam export JSON or list of MCQ question objects.
    Returns (list of normalized card dicts, suggested_deck_name: str).
    """
    import re
    if not text or not text.strip():
        return [], ""

    try:
        raw = json.loads(text)
    except Exception as e:
        raise ValueError(f"Invalid JSON syntax: {e}")

    suggested_deck = ""
    global_section = ""
    global_platform = "Testbook"

    if isinstance(raw, dict):
        global_section = raw.get("section", "")
        raw_platform = raw.get("platform", "Testbook") or "Testbook"
        clean_platform = raw_platform.lower().replace(".com", "").replace(".in", "").capitalize()
        global_platform = clean_platform
        if global_section:
            suggested_deck = f"{global_platform}::{global_section}"
        elif global_platform:
            suggested_deck = f"{global_platform} Exam"

        if "questions" in raw and isinstance(raw["questions"], list):
            items = raw["questions"]
        elif "question" in raw:
            items = [raw]
        else:
            items = raw.get("cards", [raw])
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError("JSON must contain an object or list of questions")

    results = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue

        q = str(it.get("question", "")).strip()
        q_html = str(it.get("question_html", "")).strip() or q
        if not q and not q_html:
            continue

        # Extract options
        raw_options = it.get("options", [])
        clean_options = []
        for o_idx, opt in enumerate(raw_options):
            if isinstance(opt, dict):
                clean_options.append({
                    "label": opt.get("label") or chr(65 + o_idx),
                    "text": str(opt.get("text") or "").strip(),
                    "is_correct": bool(opt.get("is_correct", False)),
                    "is_user_selected": bool(opt.get("is_user_selected", False))
                })
            elif isinstance(opt, str):
                lbl = chr(65 + o_idx)
                opt_str = opt.strip()
                match = re.match(r'^([A-Da-d1-4])[\.\)\:\-]\s*(.*)$', opt_str)
                if match:
                    lbl = match.group(1).upper()
                    opt_str = match.group(2)
                clean_options.append({
                    "label": lbl,
                    "text": opt_str,
                    "is_correct": False,
                    "is_user_selected": False
                })

        # Correct option
        c_opt = it.get("correct_option")
        c_label = ""
        c_text = ""
        if isinstance(c_opt, dict):
            c_label = str(c_opt.get("label", "")).strip()
            c_text = str(c_opt.get("text", "")).strip()
        elif isinstance(c_opt, str):
            c_label = c_opt.strip()

        # Match correct flag in clean_options if not set
        if c_label:
            for opt in clean_options:
                if opt["label"].upper() == c_label.upper():
                    opt["is_correct"] = True
                    if not c_text:
                        c_text = opt["text"]

        # Solution data
        raw_sol = it.get("solution")
        sol_data = {}
        if isinstance(raw_sol, dict):
            sol_data = {
                "statement": str(raw_sol.get("statement") or "").strip(),
                "key_points": raw_sol.get("key_points") if isinstance(raw_sol.get("key_points"), list) else [],
                "additional_info": raw_sol.get("additional_info") if isinstance(raw_sol.get("additional_info"), list) else [],
                "important_points": raw_sol.get("important_points") if isinstance(raw_sol.get("important_points"), list) else [],
                "html": str(raw_sol.get("html") or it.get("detailed_solution") or it.get("explanation") or "").strip(),
                "text": str(raw_sol.get("text") or raw_sol.get("markdown") or it.get("detailed_solution") or it.get("explanation") or "").strip()
            }
        elif isinstance(raw_sol, str):
            sol_data = {
                "statement": f"The correct answer is Option {c_label}: {c_text}." if c_label else "",
                "key_points": [line.strip().lstrip("•*- ") for line in raw_sol.split("\n") if line.strip()],
                "additional_info": [],
                "important_points": [],
                "html": raw_sol,
                "text": raw_sol
            }
        elif it.get("detailed_solution") or it.get("explanation"):
            d_sol = str(it.get("detailed_solution") or it.get("explanation") or "").strip()
            sol_data = {
                "statement": f"The correct answer is Option {c_label}: {c_text}." if c_label else "",
                "key_points": [],
                "additional_info": [],
                "important_points": [],
                "html": d_sol,
                "text": d_sol
            }

        # Notes / Deep concept extracted from key points if notes empty
        notes = str(it.get("notes", "")).strip()
        if not notes and sol_data.get("key_points"):
            notes = "\n".join([f"• {kp}" for kp in sol_data["key_points"][:4]])

        # Trap note
        trap_note = str(it.get("trap_note", "")).strip()
        if not trap_note and sol_data.get("important_points"):
            trap_note = "\n".join([f"• {ip}" for ip in sol_data["important_points"][:3]])

        # Context Anchor / Section
        section = it.get("section") or global_section or ""
        context_anchor = it.get("context_anchor") or section or "General Awareness"

        # Chain order & Q No
        try:
            q_no = int(it.get("question_no") or (idx + 1))
        except (ValueError, TypeError):
            q_no = idx + 1

        acc_stat = str(it.get("percent_answered_correctly") or "").strip()

        exam_meta = {
            "section": section,
            "platform": it.get("platform") or global_platform,
            "marks": it.get("marks", ""),
            "avg_time_raw": it.get("avg_time_raw", ""),
            "my_time_raw": it.get("my_time_raw", ""),
            "question_no": str(q_no),
            "url": it.get("url", "")
        }

        ans_str = f"Option {c_label}: {c_text}" if c_label else (it.get("answer") or "")
        deck_name = str(it.get("deck_name") or "").strip()

        results.append({
            "is_mcq": True,
            "question": q,
            "question_html": q_html,
            "options": clean_options,
            "correct_option": {"label": c_label, "text": c_text} if c_label else c_opt,
            "solution_data": sol_data,
            "percent_answered_correctly": acc_stat,
            "exam_meta": exam_meta,
            "answer": ans_str,
            "notes": notes,
            "trap_note": trap_note,
            "context_anchor": context_anchor,
            "chain_order": q_no,
            "parent_chain_id": it.get("parent_chain_id"),
            "priority_tier": int(it.get("priority_tier", 1) or 1),
            "deck_name": deck_name
        })

    return results, suggested_deck



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
                        self._existing_cards_map.setdefault(q, []).append((d_id, d_name, card))
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
                background-color: {p['C_CARD']};
                alternate-background-color: {p.get('C_SURFACE', '#1E2333')};
                color: {p['C_TEXT']};
                border: 1px solid {p['C_BORDER']};
                border-radius: 6px;
                gridline-color: {p['C_BORDER']};
                selection-background-color: {p['C_ACCENT']};
                selection-color: white;
                font-size: 12px;
                outline: none;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                color: {p['C_TEXT']};
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }}
            QTableWidget::item:selected {{
                background-color: {p['C_ACCENT']};
                color: white;
            }}
            QTableWidget::item:hover {{
                background-color: {p.get('C_SURFACE', '#1E2333')};
                color: {p['C_TEXT']};
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
        hdr_row = QHBoxLayout()
        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(2)
        lbl_title = QLabel("📥 Bulk Card Importer & Vocab Checker")
        lbl_title.setObjectName("header_title")
        lbl_sub = QLabel("Import vocabulary and question-answer cards with automatic duplicate detection & skipping.")
        lbl_sub.setObjectName("header_sub")
        hdr_box.addWidget(lbl_title)
        hdr_box.addWidget(lbl_sub)
        hdr_row.addLayout(hdr_box, stretch=1)

        btn_hdr_prompt = QPushButton("🤖 Copy AI Prompt (80/20 Rule)")
        btn_hdr_prompt.setCursor(Qt.PointingHandCursor)
        btn_hdr_prompt.setToolTip("Copy the 80/20 master prompt to clipboard to give to Gemini / ChatGPT along with your PDF")
        btn_hdr_prompt.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7950F2, stop:1 #4C6EF5);
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #845EF7, stop:1 #5C7CFA);
            }}
        """)
        btn_hdr_prompt.clicked.connect(self._copy_master_prompt)
        hdr_row.addWidget(btn_hdr_prompt, alignment=Qt.AlignVCenter)
        main_l.addLayout(hdr_row)

        # ── Splitter between (Input & Config) and (Live Preview) ──
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # ── Upper Container: Input Tabs + Config ──
        upper_widget = QWidget()
        upper_l = QVBoxLayout(upper_widget)
        upper_l.setContentsMargins(0, 0, 0, 0)
          # Tabs: Paste Text vs Browse File vs Paste JSON
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
        self.inp_file_path.setPlaceholderText("Select a .txt, .csv, .tsv, or .json file...")
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
        self.tabs.addTab(tab_file, "📁 Choose File (.txt / .csv / .tsv / .json)")

        # Tab 3: Paste JSON
        tab_json = QWidget()
        json_l = QVBoxLayout(tab_json)
        json_l.setContentsMargins(8, 8, 8, 8)
        json_l.setSpacing(6)

        json_hdr = QHBoxLayout()
        lbl_json_hint = QLabel("Paste structured flashcards JSON below or copy the prompt:")
        lbl_json_hint.setStyleSheet(f"color: {p['C_SUBTEXT']}; font-size: 11px;")
        
        btn_copy_prompt = QPushButton("📋 Copy AI Master Prompt (80/20 Rule)")
        btn_copy_prompt.setObjectName("flat")
        btn_copy_prompt.setStyleSheet(f"""
            QPushButton {{
                background: rgba(92, 124, 250, 0.15);
                color: {p['C_ACCENT']};
                border: 1px solid {p['C_ACCENT']};
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {p['C_ACCENT']};
                color: #FFFFFF;
            }}
        """)
        btn_copy_prompt.setCursor(Qt.PointingHandCursor)
        btn_copy_prompt.setToolTip("Copy the 80/20 master prompt to clipboard to give to Gemini / ChatGPT along with your PDF")
        btn_copy_prompt.clicked.connect(self._copy_master_prompt)
        
        json_hdr.addWidget(lbl_json_hint)
        json_hdr.addStretch()
        json_hdr.addWidget(btn_copy_prompt)
        json_l.addLayout(json_hdr)

        self.txt_json = QPlainTextEdit()
        self.txt_json.setPlaceholderText(
            "Paste JSON list of cards here. Example:\n"
            "[\n"
            "  {\n"
            '    "deck_name": "Biology::Genetics",\n'
            '    "context_anchor": "Mendelian Inheritance",\n'
            '    "question": "What is the phenotypic ratio of a monohybrid cross?",\n'
            '    "answer": "3:1 ratio (dominant : recessive)",\n'
            '    "trap_note": "Do not confuse with genotypic ratio 1:2:1",\n'
            '    "chain_order": 1\n'
            "  }\n"
            "]"
        )
        self.txt_json.textChanged.connect(self._on_input_changed)
        json_l.addWidget(self.txt_json)
        self.tabs.addTab(tab_json, "📦 Paste JSON / Chained Cards")

        # Tab 4: Paste Exam / Testbook MCQ JSON
        tab_mcq = QWidget()
        mcq_l = QVBoxLayout(tab_mcq)
        mcq_l.setContentsMargins(8, 8, 8, 8)
        mcq_l.setSpacing(6)

        mcq_hdr = QHBoxLayout()
        lbl_mcq_hint = QLabel("Paste Testbook / Mock Exam export JSON with 4 choices & solutions:")
        lbl_mcq_hint.setStyleSheet(f"color: {p['C_SUBTEXT']}; font-size: 11px;")

        btn_sample_mcq = QPushButton("📄 Load Sample Testbook JSON")
        btn_sample_mcq.setObjectName("flat")
        btn_sample_mcq.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 184, 108, 0.15);
                color: #FFB86C;
                border: 1px solid #FFB86C;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: #FFB86C;
                color: #111827;
            }}
        """)
        btn_sample_mcq.setCursor(Qt.PointingHandCursor)
        btn_sample_mcq.setToolTip("Paste a 2-question Testbook sample JSON to test the exam UI immediately")
        btn_sample_mcq.clicked.connect(self._load_sample_mcq_json)

        btn_copy_exam_prompt = QPushButton("📋 Copy AI Exam Prompt")
        btn_copy_exam_prompt.setObjectName("flat")
        btn_copy_exam_prompt.setStyleSheet(f"""
            QPushButton {{
                background: rgba(92, 124, 250, 0.15);
                color: {p['C_ACCENT']};
                border: 1px solid {p['C_ACCENT']};
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {p['C_ACCENT']};
                color: #FFFFFF;
            }}
        """)
        btn_copy_exam_prompt.setCursor(Qt.PointingHandCursor)
        btn_copy_exam_prompt.setToolTip("Copy prompt to ask AI to create Testbook-style 4-choice MCQs with Key Points")
        btn_copy_exam_prompt.clicked.connect(self._copy_exam_prompt)

        mcq_hdr.addWidget(lbl_mcq_hint)
        mcq_hdr.addStretch()
        mcq_hdr.addWidget(btn_sample_mcq)
        mcq_hdr.addWidget(btn_copy_exam_prompt)
        mcq_l.addLayout(mcq_hdr)

        self.txt_mcq_json = QPlainTextEdit()
        self.txt_mcq_json.setPlaceholderText(
            "Paste Testbook or Exam Paper export JSON here. Example:\n"
            "{\n"
            '  "platform": "testbook.com",\n'
            '  "section": "General Awareness",\n'
            '  "questions": [\n'
            "    {\n"
            '      "question": "Which of the following classical dances originated in Tamil Nadu?",\n'
            '      "options": [\n'
            '        {"label": "A", "text": "Kathak", "is_correct": false},\n'
            '        {"label": "B", "text": "Bharatanatyam", "is_correct": true},\n'
            '        {"label": "C", "text": "Mohiniyattam", "is_correct": false},\n'
            '        {"label": "D", "text": "Manipuri", "is_correct": false}\n'
            "      ],\n"
            '      "correct_option": {"label": "B", "text": "Bharatanatyam"},\n'
            '      "percent_answered_correctly": "82%",\n'
            '      "solution": {\n'
            '        "statement": "The correct answer is Bharatanatyam.",\n'
            '        "key_points": ["Bharatanatyam is rooted in Natyashastra and Tamil Nadu temple traditions."]\n'
            "      }\n"
            "    }\n"
            "  ]\n"
            "}"
        )
        self.txt_mcq_json.textChanged.connect(self._on_input_changed)
        mcq_l.addWidget(self.txt_mcq_json)
        self.tabs.addTab(tab_mcq, "🎯 Paste Exam / Testbook MCQ JSON")

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
        dup_row.setSpacing(10)

        lbl_dup = QLabel("Duplicate Policy:")
        lbl_dup.setStyleSheet("font-weight: bold;")
        dup_row.addWidget(lbl_dup)

        self.combo_dup_policy = QComboBox()
        self.combo_dup_policy.addItems([
            "🛡️ Auto-skip duplicate cards / words (Recommended)",
            "🔄 Update existing cards (Update Back/Tricks, Keep SM-2 stats)",
            "➕ Add as new duplicates (Create duplicate cards)"
        ])
        self.combo_dup_policy.setToolTip(
            "Choose action when Front (Question/Word) already exists in database:\n"
            "• Skip: Ignores duplicates (Recommended)\n"
            "• Update: Overwrites Answer/Tricks and keeps review history\n"
            "• Add: Imports as new duplicate card"
        )
        self.combo_dup_policy.currentIndexChanged.connect(self._on_dup_policy_changed)
        dup_row.addWidget(self.combo_dup_policy)

        # Backward compatibility proxy
        self.chk_skip_duplicates = QCheckBox()
        self.chk_skip_duplicates.setChecked(True)
        self.chk_skip_duplicates.hide()
        self.chk_skip_duplicates.toggled.connect(self._on_chk_skip_toggled)

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

        self.table_preview = QTableWidget(0, 6)
        self.table_preview.setHorizontalHeaderLabels([
            "#",
            "Context / Deck",
            "Front (Word / Question)",
            "Back (Meaning / Answer)",
            "Chain / Trap",
            "Duplicate Status"
        ])
        self.table_preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table_preview.setColumnWidth(1, 140)
        self.table_preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_preview.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_preview.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table_preview.setColumnWidth(4, 110)
        self.table_preview.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_preview.setAlternatingRowColors(True)
        self.table_preview.setEditTriggers(QTableWidget.NoEditTriggers)

        # Enforce dark theme colors on QTableWidget palette so alternate rows don't default to white
        pal = self.table_preview.palette()
        pal.setColor(QPalette.Base, QColor(p.get('C_CARD', '#141824')))
        pal.setColor(QPalette.AlternateBase, QColor(p.get('C_SURFACE', '#1E2333')))
        pal.setColor(QPalette.Text, QColor(p.get('C_TEXT', '#FFFFFF')))
        pal.setColor(QPalette.Highlight, QColor(p.get('C_ACCENT', '#5C7CFA')))
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.table_preview.setPalette(pal)

        lower_l.addWidget(self.table_preview)

        splitter.addWidget(lower_widget)
        splitter.setSizes([260, 360])
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

    def _copy_master_prompt(self):
        prompt_text = """# TASK: Generate 100% Complete, 3-Layer Deep Concept, Tier-Ranked (80/20) Flashcards (JSON) from Attached Document

### ROLE & CORE OBJECTIVE:
You are an expert SSC/Competitive Exam Curriculum Architect and Anki Flashcard Engineer. Your objective is to convert 100% of the factual, conceptual, legal, and analytical content from the attached document into rich, 3-layer, sequential, tier-ranked flashcards.
The student must NEVER need to search Google or open a textbook to clarify doubts—every card must contain the full background story, mechanism, and reasoning inside the `notes` field.

---

### CRITICAL PROCESSING & CARD ARCHITECTURE RULES:

1. **3-Layer Card Structure (Rapid Active Recall + Deep Concept):**
   - **Layer 1 (`question`):** 1 sharp, focused question testing a single concept.
   - **Layer 2 (`answer`):** 1-2 lines of direct, punchy core answer with bold key terms for instant 5-second active recall.
   - **Layer 3 (`notes` - Deep Theory & Background Explanation):** 
     - 3 to 5 rich, structured bullet points explaining the **complete background story, the "Why & How" mechanism, historical evolution, related articles, and common doubts**.
     - Must be 100% self-contained so no external Googling is ever needed.
   - **Layer 4 (`trap_note`):** 1 punchy line warning against specific exam traps, confusing option pairs, or exceptions.

2. **Zero-Drop Coverage (100% Completeness):**
   - Extract every article, amendment number, year, committee, landmark case, numerical timeline, majority type, exception, and handwritten annotation. No detail must be skipped.

3. **80/20 Tier-Ranked Prioritization (`priority_tier`):**
   - **`"priority_tier": 1` (Core 20% Data / 80% Value):** Core definitions, essential articles, mandatory timelines/majorities, fundamental mechanisms, and high-frequency exam concepts.
   - **`"priority_tier": 2` (Elimination 80% Data / 20% Value):** Nuanced details, secondary committees, background facts, specific case citations, and minor historical points used for MCQ option elimination.

4. **Roman Numerals to Common Decimal Numbers (Mandatory Rule):**
   - Whenever writing Constitutional Parts, Schedules, or Roman numerals, ALWAYS write the Roman numeral followed by its common decimal/Arabic number (0-9) in parentheses.
   - *Examples:*
     - Write `Part XVIII (18)` or `भाग XVIII (18)` (NOT just `Part XVIII`).
     - Write `Part XV (15)` or `भाग XV (15)` (NOT just `Part XV`).
     - Write `Part XX (20)` or `भाग XX (20)` (NOT just `Part XX`).
     - Write `8वीं अनुसूची (Schedule VIII - 8)`.

5. **Self-Contained Acronyms & Full Forms (Zero-Search Rule):**
   - Whenever an abbreviation, commission, or short form is used, ALWAYS include its full expansion (in English and Hindi) in parentheses on first mention.
   - *Examples:*
     - Write `ECI (Election Commission of India / भारतीय चुनाव आयोग)`.
     - Write `UPSC (Union Public Service Commission / संघ लोक सेवा आयोग)`.
     - Write `CAA (Constitutional Amendment Act / संविधान संशोधन अधिनियम)`.
     - Write `EWS (Economically Weaker Sections / आर्थिक रूप से कमजोर वर्ग)`.
     - Write `NCBC (National Commission for Backward Classes / राष्ट्रीय पिछड़ा वर्ग आयोग)`.

6. **Sequential Linked Story Chaining:**
   - Group multi-step concepts, chronologies, or complex mechanisms under the same `context_anchor` badge.
   - Order them logically from foundation to advanced traps using sequential integers (`chain_order: 1, 2, 3...`).

7. **Language & Tone:**
   - Bilingual (Hinglish/Hindi with standard English technical/legal terms in brackets) for maximum active recall and memory retention.

---

### REQUIRED JSON SCHEMA:
Output ONLY a strictly valid JSON array of objects matching this exact structure:

[
  {
    "deck_name": "Subject::Chapter_Name",
    "context_anchor": "Concept Anchor (e.g., National Emergency Article 352)",
    "question": "Single sharp question targeting one concept with full forms and decimal numbers.",
    "answer": "• Crisp 1-2 line direct answer with bold key terms.",
    "notes": "• Background / Mechanism: Detailed explanation of why and how this provision operates.\n• Historical / Legal Context: Relevant constitutional history, previous position, or related amendment.\n• Connected Provisions: Related articles/clauses that clarify potential doubts completely.",
    "trap_note": "TRAP: Direct exam pitfall, confusing pair, or exception.",
    "chain_order": 1,
    "priority_tier": 1
  }
]

### INSTRUCTIONS:
- Replace "Subject::Chapter_Name" with the subject and topic of the attached PDF (e.g., Polity::Emergency_and_Amendments).
- Ensure the `notes` field is rich, detailed, and completely explains the context so the user never has to search Google.
- Return ONLY the raw JSON array. Do not wrap in conversational chit-chat."""
        cb = QApplication.clipboard()
        if cb:
            cb.setText(prompt_text)
            QMessageBox.information(
                self,
                "📋 Prompt Copied!",
                "✅ AI Master Prompt (80/20 Rule) copied to clipboard!\n\n"
                "Next Steps:\n"
                "1. Open Gemini / ChatGPT / Claude.\n"
                "2. Attach your lecture/revision PDF.\n"
                "3. Paste this prompt and generate cards.\n"
                "4. Copy the resulting JSON and paste it right here!"
            )

    def _copy_exam_prompt(self):
        prompt_text = """# TASK: Generate Complete, Authentic Testbook/Exam-Style 4-Option MCQ Flashcards (JSON)

### ROLE & CORE OBJECTIVE:
You are an expert SSC/Competitive Exam Architect. Convert the provided document or test questions into authentic 4-option MCQs with comprehensive Testbook-style solution explanations (Key Points, Additional Information, and Important Points).

---

### REQUIRED JSON SCHEMA:
Output ONLY a strictly valid JSON object matching this exact structure:

{
  "platform": "testbook.com",
  "section": "General Awareness",
  "total_questions": 5,
  "questions": [
    {
      "question_no": "1",
      "section": "General Awareness",
      "question": "Arrange the following classical dances in chronological order of earliest historical references (oldest to newest):\\n\\n1. Bharatanatyam\\n\\n2. Mohiniyattam\\n\\n3. Kathak\\n\\n4. Manipuri",
      "options": [
        {"label": "A", "text": "1 - 3 - 2 - 4", "is_correct": false},
        {"label": "B", "text": "1 - 2 - 4 - 3", "is_correct": false},
        {"label": "C", "text": "1 - 3 - 4 - 2", "is_correct": true},
        {"label": "D", "text": "1 - 4 - 3 - 2", "is_correct": false}
      ],
      "correct_option": {
        "label": "C",
        "text": "1 - 3 - 4 - 2"
      },
      "percent_answered_correctly": "22%",
      "solution": {
        "statement": "The correct answer is 1 - 3 - 4 - 2.",
        "key_points": [
          "Bharatanatyam is considered one of the oldest classical dance forms of India, with references dating back to the Natyashastra (200 BCE - 200 CE).",
          "Kathak traces its roots to ancient storytelling traditions, flourishing during the Bhakti movement (15th-17th century).",
          "Manipuri developed in Manipur under Vaishnavite traditions in the 18th century.",
          "Mohiniyattam gained prominence in Kerala during the late 18th century."
        ],
        "additional_info": [
          "Bharatanatyam: Performed in Tamil Nadu temples to Carnatic music.",
          "Kathak: North Indian dance accompanied by Hindustani music, tabla and pakhawaj.",
          "Manipuri: Features graceful Radha-Krishna Raas Leela with cylindrical Potloi skirts.",
          "Mohiniyattam: Known as the dance of the enchantress in Kerala."
        ],
        "important_points": [
          "Chronological Order: Bharatanatyam (Oldest) -> Kathak -> Manipuri -> Mohiniyattam.",
          "Natyashastra serves as foundational treatise for classical dances."
        ]
      }
    }
  ]
}

### INSTRUCTIONS:
- Return ONLY valid raw JSON. Do not wrap in conversational chit-chat."""
        cb = QApplication.clipboard()
        if cb:
            cb.setText(prompt_text)
            QMessageBox.information(
                self,
                "📋 Exam Prompt Copied!",
                "✅ AI Testbook / Exam MCQ Prompt copied to clipboard!\n\n"
                "Next Steps:\n"
                "1. Open Gemini / ChatGPT / Claude.\n"
                "2. Attach your study material or mock test questions.\n"
                "3. Paste this prompt and generate JSON.\n"
                "4. Paste the output right into the '🎯 Paste Exam / Testbook MCQ JSON' tab!"
            )

    def _load_sample_mcq_json(self):
        sample = {
            "platform": "testbook.com",
            "section": "General Awareness",
            "total_questions": 2,
            "questions": [
                {
                    "question_no": "1",
                    "section": "General Awareness",
                    "question": "Arrange the following classical dances in chronological order of earliest historical references (oldest to newest):\n\n1. Bharatanatyam\n\n2. Mohiniyattam\n\n3. Kathak\n\n4. Manipuri",
                    "options": [
                        {"label": "A", "text": "1 - 3 - 2 - 4", "is_correct": False},
                        {"label": "B", "text": "1 - 2 - 4 - 3", "is_correct": False},
                        {"label": "C", "text": "1 - 3 - 4 - 2", "is_correct": True},
                        {"label": "D", "text": "1 - 4 - 3 - 2", "is_correct": False}
                    ],
                    "correct_option": {"label": "C", "text": "1 - 3 - 4 - 2"},
                    "percent_answered_correctly": "22%",
                    "solution": {
                        "statement": "The correct answer is 1 - 3 - 4 - 2.",
                        "key_points": [
                            "Bharatanatyam is considered one of the oldest classical dance forms of India, with references dating back to the Natyashastra (200 BCE - 200 CE).",
                            "Kathak traces its roots to ancient storytelling traditions, flourishing during the Bhakti movement (15th-17th century).",
                            "Manipuri developed in Manipur under Vaishnavite traditions in the 18th century.",
                            "Mohiniyattam gained prominence in Kerala during the late 18th century."
                        ],
                        "additional_info": [
                            "Bharatanatyam: Performed in Tamil Nadu temples to Carnatic music.",
                            "Kathak: North Indian dance accompanied by Hindustani music, tabla and pakhawaj.",
                            "Manipuri: Features graceful Radha-Krishna Raas Leela with cylindrical Potloi skirts.",
                            "Mohiniyattam: Known as the dance of the enchantress in Kerala."
                        ],
                        "important_points": [
                            "Chronological Order: Bharatanatyam (Oldest) -> Kathak -> Manipuri -> Mohiniyattam.",
                            "Natyashastra serves as foundational treatise for classical dances."
                        ]
                    }
                },
                {
                    "question_no": "2",
                    "section": "General Awareness",
                    "question": "Which of the following pairs is correctly matched with the shape of its roof?",
                    "options": [
                        {"label": "A", "text": "Latina — rectangular, wagon-shaped", "is_correct": False},
                        {"label": "B", "text": "Phamsana — slabs rising to a point, straight incline", "is_correct": True},
                        {"label": "C", "text": "Valabhi — tall, curving inward sharply", "is_correct": False},
                        {"label": "D", "text": "Latina — low and broad with stepped roofing", "is_correct": False}
                    ],
                    "correct_option": {"label": "B", "text": "Phamsana — slabs rising to a point, straight incline"},
                    "percent_answered_correctly": "9%",
                    "solution": {
                        "statement": "The correct answer is Phamsana — slabs rising to a point, straight incline.",
                        "key_points": [
                            "Phamsana roofs are characterized by horizontal slabs rising in a straight slope to a central apex (pyramidal).",
                            "Latina (Rekha-Prasada) is a tall curvilinear tower curving gently inward.",
                            "Valabhi features a rectangular wagon-vaulted roof resembling ancient Buddhist chaitya halls."
                        ],
                        "additional_info": [
                            "Nagara Style: Dominant North Indian temple architecture style.",
                            "Latina Shikhara: Most common superstructure over the sanctum sanctorum (Garbhagriha).",
                            "Phamsana: Broad and lower, widely used over assembly halls (Mandapas)."
                        ],
                        "important_points": [
                            "Latina = Curvilinear spire",
                            "Phamsana = Stepped straight incline pyramid",
                            "Valabhi = Wagon-vaulted / Barrel roof"
                        ]
                    }
                }
            ]
        }
        self.txt_mcq_json.setPlainText(json.dumps(sample, indent=2, ensure_ascii=False))

    def _on_input_changed(self):
        self._debounce_timer.start()

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cards File",
            "",
            "All Supported (*.txt *.csv *.tsv *.json);;JSON Files (*.json);;CSV / TSV Files (*.csv *.tsv);;Text Files (*.txt);;All Files (*.*)"
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

        # Auto-detect format
        if path.lower().endswith(".json"):
            self._is_json_file = True
        elif path.lower().endswith(".tsv"):
            self._is_json_file = False
            self.combo_delim.setCurrentIndex(1)
        elif path.lower().endswith(".csv"):
            self._is_json_file = False
            self.combo_delim.setCurrentIndex(0)
        else:
            self._is_json_file = False

        self._reparse_and_preview()

    def _on_dup_policy_changed(self):
        idx = self.combo_dup_policy.currentIndex()
        self.chk_skip_duplicates.blockSignals(True)
        self.chk_skip_duplicates.setChecked(idx == 0)
        self.chk_skip_duplicates.blockSignals(False)
        self._on_input_changed()

    def _on_chk_skip_toggled(self, checked: bool):
        self.combo_dup_policy.blockSignals(True)
        self.combo_dup_policy.setCurrentIndex(0 if checked else 2)
        self.combo_dup_policy.blockSignals(False)
        self._on_input_changed()

    def _get_dup_policy(self) -> str:
        """Returns 'skip', 'update', or 'add'."""
        if hasattr(self, "combo_dup_policy"):
            idx = self.combo_dup_policy.currentIndex()
            if idx == 1:
                return "update"
            elif idx == 2:
                return "add"
            else:
                return "skip"
        return "skip" if getattr(self, "chk_skip_duplicates", None) and self.chk_skip_duplicates.isChecked() else "add"

    def _check_card_duplicate(self, question: str, target_deck_id=None, check_all=True) -> tuple:
        """
        Check if a card's question already exists.
        Returns (is_duplicate: bool, location_desc: str, matching_card_ref: dict or None)
        """
        norm_q = question.strip().lower()
        if not norm_q:
            return False, "", None

        matches = self._existing_cards_map.get(norm_q, [])
        if not matches:
            return False, "", None

        if check_all:
            # Return first deck location where it appears
            deck_names = [name for (_, name, _) in matches]
            loc_str = f"in '{deck_names[0]}'" if len(deck_names) == 1 else f"in {len(deck_names)} decks"
            first_card = matches[0][2]
            return True, loc_str, first_card
        else:
            # Check specifically in target deck
            if target_deck_id is not None:
                for did, name, card_obj in matches:
                    if did == target_deck_id:
                        return True, f"in this deck ('{name}')", card_obj

        return False, "", None

    def _reparse_and_preview(self):
        # Choose active text source
        curr_tab = self.tabs.currentIndex()
        if curr_tab == 3:
            text = self.txt_mcq_json.toPlainText()
            is_json = True
            force_mcq = True
        elif curr_tab == 2:
            text = self.txt_json.toPlainText()
            is_json = True
            force_mcq = False
        elif curr_tab == 0:
            text = self.txt_paste.toPlainText()
            s_text = text.strip()
            is_json = s_text.startswith("[") or (s_text.startswith("{") and ("question" in s_text or "questions" in s_text))
            force_mcq = False
        else:
            text = self._file_content
            s_text = text.strip()
            is_json = getattr(self, "_is_json_file", False) or s_text.startswith("[") or (s_text.startswith("{") and ("question" in s_text or "questions" in s_text))
            force_mcq = False

        parsed = []
        if is_json and text.strip():
            try:
                s_lower = text.strip().lower()
                is_mcq_format = force_mcq or ("options" in s_lower and ("correct_option" in s_lower or "is_correct" in s_lower)) or '"questions"' in s_lower or "'questions'" in s_lower
                
                if is_mcq_format:
                    parsed, suggested_deck = parse_testbook_or_mcq_json(text)
                    if suggested_deck and self.rb_new_deck.isChecked() and self.inp_new_deck_name.text().strip() in ("", "Vocabulary", "Imported Cards"):
                        self.inp_new_deck_name.setText(suggested_deck)
                else:
                    raw = json.loads(text)
                    items = raw if isinstance(raw, list) else raw.get("cards", [raw])
                    
                    # Auto-chaining
                    chain_id_map = {}
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        c_anchor = str(it.get("context_anchor", "")).strip()
                        c_order = it.get("chain_order", 0)
                        c_parent = it.get("parent_chain_id")
                        d_name = str(it.get("deck_name", "")).strip()
                        if not c_parent and c_anchor and c_order:
                            grp = (d_name, c_anchor)
                            if grp not in chain_id_map:
                                chain_id_map[grp] = str(uuid.uuid4())
                            it["parent_chain_id"] = chain_id_map[grp]

                        q = str(it.get("question", "")).strip()
                        a = str(it.get("answer", "")).strip()
                        if not q and not a:
                            continue
                        
                        trap = str(it.get("trap_note", "")).strip()
                        notes = str(it.get("notes", "")).strip()
                        if trap and not notes:
                            notes = trap
                        elif notes and not trap:
                            trap = notes

                        try:
                            chain_order = int(it.get("chain_order", 0) or 0)
                        except (ValueError, TypeError):
                            chain_order = 0

                        try:
                            priority_tier = int(it.get("priority_tier", 1) or 1)
                        except (ValueError, TypeError):
                            priority_tier = 1

                        parsed.append({
                            "is_mcq": False,
                            "question": q,
                            "answer": a,
                            "notes": notes,
                            "trap_note": trap,
                            "context_anchor": c_anchor,
                            "chain_order": chain_order,
                            "parent_chain_id": it.get("parent_chain_id"),
                            "priority_tier": priority_tier,
                            "deck_name": it.get("deck_name", "").strip()
                        })
            except Exception as e:
                self.lbl_summary_badge.setText(f"⚠️ JSON Parse error: {e}")
                self.lbl_summary_badge.setStyleSheet("color: #FF5555; font-weight: bold;")
                self.table_preview.setRowCount(0)
                self.btn_import.setEnabled(False)
                return
        else:
            delim = self._get_current_delimiter()
            has_header = self.chk_header.isChecked()
            trim = self.chk_trim.isChecked()
            raw_parsed = parse_delimited_text(text, delimiter=delim, has_header=has_header, strip_whitespace=trim)
            for item in raw_parsed:
                parsed.append({
                    "is_mcq": False,
                    "question": item.get("question", ""),
                    "answer": item.get("answer", ""),
                    "notes": item.get("notes", ""),
                    "trap_note": "",
                    "context_anchor": "",
                    "chain_order": 0,
                    "parent_chain_id": None,
                    "priority_tier": 1,
                    "deck_name": ""
                })

        check_all = self.chk_check_all_decks.isChecked()
        target_did = self.combo_existing_decks.currentData() if self.rb_existing_deck.isChecked() else None
        dup_policy = self._get_dup_policy()

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
                item["existing_card_ref"] = None
                dup_count += 1
            else:
                is_dup, loc_desc, card_ref = self._check_card_duplicate(q, target_deck_id=target_did, check_all=check_all)
                item["is_duplicate"] = is_dup
                item["dup_location"] = loc_desc
                item["existing_card_ref"] = card_ref
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
            if dup_policy == "update":
                if dup_count > 0:
                    self.lbl_summary_badge.setText(f"✨ {new_count} New Cards   |   🔄 {dup_count} Cards Will Be Updated")
                    self.lbl_summary_badge.setStyleSheet("color: #70A5FD; font-weight: bold;")
                else:
                    self.lbl_summary_badge.setText(f"✅ All {new_count} cards are unique and new!")
                    self.lbl_summary_badge.setStyleSheet(f"color: {self._theme_p.get('C_GREEN', '#50FA7B')}; font-weight: bold;")
            elif dup_policy == "skip":
                if dup_count > 0:
                    self.lbl_summary_badge.setText(f"✨ {new_count} New Cards   |   ⚠️ {dup_count} Duplicates Skipped")
                    self.lbl_summary_badge.setStyleSheet("color: #FFB86C; font-weight: bold;")
                else:
                    self.lbl_summary_badge.setText(f"✅ All {new_count} cards are unique and new!")
                    self.lbl_summary_badge.setStyleSheet(f"color: {self._theme_p.get('C_GREEN', '#50FA7B')}; font-weight: bold;")
            else:  # add
                self.lbl_summary_badge.setText(f"➕ Importing All {total_count} Cards ({dup_count} Duplicates Allowed)")
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
            it_idx.setForeground(QColor(self._theme_p.get("C_SUBTEXT", "#A0AEC0")))
            self.table_preview.setItem(row_idx, 0, it_idx)

            # Column 1: Context / Deck
            c_text = item.get("context_anchor") or item.get("deck_name") or "—"
            it_ctx = QTableWidgetItem(c_text)
            if item.get("context_anchor"):
                it_ctx.setForeground(QColor(self._theme_p.get("C_ACCENT", "#5C7CFA")))
            else:
                it_ctx.setForeground(QColor(self._theme_p.get("C_SUBTEXT", "#A0AEC0")))
            self.table_preview.setItem(row_idx, 1, it_ctx)

            # Column 2: Front (Question / Word)
            it_q = QTableWidgetItem(item["question"])
            it_q.setForeground(QColor(self._theme_p.get("C_TEXT", "#FFFFFF")))
            self.table_preview.setItem(row_idx, 2, it_q)

            # Column 3: Back (Answer / Meaning / Correct Option)
            it_a = QTableWidgetItem(item["answer"])
            if not item["answer"]:
                it_a.setForeground(QColor(self._theme_p.get("C_ORANGE", "#FFB86C")))
                it_a.setText("[Empty Back]")
            elif item.get("is_mcq"):
                it_a.setForeground(QColor(self._theme_p.get("C_GREEN", "#50FA7B")))
            else:
                it_a.setForeground(QColor(self._theme_p.get("C_TEXT", "#FFFFFF")))
            self.table_preview.setItem(row_idx, 3, it_a)

            # Column 4: Chain / Trap / MCQ Stats
            if item.get("is_mcq"):
                opts_len = len(item.get("options", []))
                kp_len = len(item.get("solution_data", {}).get("key_points", []))
                acc = item.get("percent_answered_correctly", "")
                chain_str = f"🎯 {opts_len} Opts"
                if kp_len:
                    chain_str += f" | 🔑 {kp_len} Pts"
                if acc:
                    chain_str += f" | 📊 {acc}"
                it_chain = QTableWidgetItem(chain_str)
                it_chain.setForeground(QColor("#8BE9FD"))
            else:
                chain_str = ""
                p_tier = item.get("priority_tier", 1)
                tier_prefix = "🔥 T1 " if p_tier == 1 else "⚡ T2 "
                chain_str += tier_prefix
                if item.get("chain_order"):
                    chain_str += f"🔗 #{item['chain_order']} "
                if item.get("trap_note"):
                    chain_str += "⚠️ Trap"
                if not chain_str.strip():
                    chain_str = "—"
                it_chain = QTableWidgetItem(chain_str.strip())
                it_chain.setForeground(QColor("#FFD700" if "🔗" in chain_str else ("#FFB86C" if p_tier == 1 else "#8BE9FD")))
            self.table_preview.setItem(row_idx, 4, it_chain)

            # Column 5: Duplicate Status
            if item["is_duplicate"]:
                if dup_policy == "update":
                    it_status = QTableWidgetItem(f"🔄 Update ({item['dup_location']})")
                    it_status.setForeground(QColor("#70A5FD"))
                elif dup_policy == "skip":
                    it_status = QTableWidgetItem(f"⚠️ Dup ({item['dup_location']}) - Skip")
                    it_status.setForeground(QColor("#FFB86C"))
                else:
                    it_status = QTableWidgetItem(f"➕ Dup ({item['dup_location']}) - Add")
                    it_status.setForeground(QColor("#F1FA8C"))
            else:
                it_status = QTableWidgetItem("✅ New")
                it_status.setForeground(QColor(self._theme_p.get("C_GREEN", "#50FA7B")))
            self.table_preview.setItem(row_idx, 5, it_status)

        # Update button text & enabled state
        if dup_policy == "update":
            self.btn_import.setEnabled(total_count > 0)
            if dup_count > 0:
                self.btn_import.setText(f"📥 Import ({new_count} New, {dup_count} Updated)")
            elif total_count > 0:
                self.btn_import.setText(f"📥 Import {total_count} Card{'s' if total_count != 1 else ''}")
            else:
                self.btn_import.setText("📥 Import Cards")
        elif dup_policy == "skip":
            self.btn_import.setEnabled(new_count > 0)
            if dup_count > 0:
                self.btn_import.setText(f"📥 Import {new_count} New Cards (Skip {dup_count} Dups)")
            elif total_count > 0:
                self.btn_import.setText(f"📥 Import {total_count} Card{'s' if total_count != 1 else ''}")
            else:
                self.btn_import.setText("📥 Import Cards")
        else:  # add
            self.btn_import.setEnabled(total_count > 0)
            if total_count > 0:
                self.btn_import.setText(f"📥 Import All {total_count} Card{'s' if total_count != 1 else ''}")
            else:
                self.btn_import.setText("📥 Import Cards")

    def _do_import(self):
        if not self._parsed_rows:
            QMessageBox.warning(self, "No Cards", "No valid cards detected to import.")
            return

        is_new_deck = self.rb_new_deck.isChecked()
        default_deck_name = self.inp_new_deck_name.text().strip()

        if is_new_deck and not default_deck_name:
            QMessageBox.warning(self, "Deck Name Required", "Please enter a name for the new deck.")
            self.inp_new_deck_name.setFocus()
            return

        dup_policy = self._get_dup_policy()

        # Snapshot for undo
        deck_history.push(self._data)

        new_cards = []
        updated_cards = []
        skipped_count = 0
        target_deck_ids = set()

        # Fallback default target deck if row has no specific deck_name
        default_target_deck = None
        if is_new_deck:
            new_id = next_deck_id(self._data)
            default_target_deck = {
                "_id": new_id,
                "name": default_deck_name,
                "cards": [],
                "children": [],
                "expanded": False
            }
            self._data.setdefault("decks", []).append(default_target_deck)
            self._target_deck_id = new_id
            self._is_new_deck = True
            target_deck_ids.add(new_id)
        else:
            target_id = self.combo_existing_decks.currentData()
            default_target_deck = find_deck_by_id(target_id, self._data.get("decks", []))
            if not default_target_deck:
                QMessageBox.critical(self, "Error", "Target deck could not be found.")
                return
            self._target_deck_id = target_id
            self._is_new_deck = False
            target_deck_ids.add(target_id)

        for row in self._parsed_rows:
            is_dup = row.get("is_duplicate", False)
            existing_ref = row.get("existing_card_ref")

            if is_dup:
                if dup_policy == "skip":
                    skipped_count += 1
                    continue
                elif dup_policy == "update":
                    if existing_ref is not None:
                        # Update existing database card while keeping SM-2 learning progress intact!
                        existing_ref["answer"] = row["answer"]
                        if row.get("is_mcq"):
                            existing_ref["card_type"] = "mcq"
                            existing_ref["options"] = row.get("options", [])
                            existing_ref["correct_option"] = row.get("correct_option")
                            existing_ref["solution_data"] = row.get("solution_data", {})
                            existing_ref["percent_answered_correctly"] = row.get("percent_answered_correctly", "")
                            existing_ref["exam_meta"] = row.get("exam_meta", {})
                            existing_ref["question_html"] = row.get("question_html", "")
                        if row.get("notes"):
                            existing_ref["notes"] = row["notes"]
                        if row.get("trap_note"):
                            existing_ref["trap_note"] = row["trap_note"]
                        if row.get("context_anchor"):
                            existing_ref["context_anchor"] = row["context_anchor"]
                        if row.get("chain_order"):
                            existing_ref["chain_order"] = row["chain_order"]
                        if row.get("parent_chain_id"):
                            existing_ref["parent_chain_id"] = row["parent_chain_id"]
                        if row.get("priority_tier"):
                            existing_ref["priority_tier"] = row["priority_tier"]
                        updated_cards.append(existing_ref)
                        continue
                    else:
                        # Duplicate within this batch: update previously added card in new_cards
                        for nc in reversed(new_cards):
                            if nc["question"].strip().lower() == row["question"].strip().lower():
                                nc["answer"] = row["answer"]
                                if row.get("is_mcq"):
                                    nc["card_type"] = "mcq"
                                    nc["options"] = row.get("options", [])
                                    nc["correct_option"] = row.get("correct_option")
                                    nc["solution_data"] = row.get("solution_data", {})
                                    nc["percent_answered_correctly"] = row.get("percent_answered_correctly", "")
                                    nc["exam_meta"] = row.get("exam_meta", {})
                                    nc["question_html"] = row.get("question_html", "")
                                if row.get("notes"):
                                    nc["notes"] = row["notes"]
                                if row.get("trap_note"):
                                    nc["trap_note"] = row["trap_note"]
                                if row.get("priority_tier"):
                                    nc["priority_tier"] = row["priority_tier"]
                                break
                        skipped_count += 1
                        continue

            # Build card
            if row.get("is_mcq"):
                card = build_mcq_card(
                    question=row["question"],
                    options=row.get("options", []),
                    correct_option=row.get("correct_option"),
                    solution_data=row.get("solution_data", {}),
                    percent_answered_correctly=row.get("percent_answered_correctly", ""),
                    exam_meta=row.get("exam_meta", {}),
                    notes=row.get("notes", ""),
                    trap_note=row.get("trap_note", ""),
                    context_anchor=row.get("context_anchor", ""),
                    chain_order=row.get("chain_order", 0),
                    parent_chain_id=row.get("parent_chain_id"),
                    priority_tier=row.get("priority_tier", 1),
                    tags=row.get("tags", []),
                    question_html=row.get("question_html", "")
                )
            else:
                card = build_text_card(
                    question=row["question"],
                    answer=row["answer"],
                    notes=row.get("notes", ""),
                    tags=[],
                    context_anchor=row.get("context_anchor", ""),
                    chain_order=row.get("chain_order", 0),
                    parent_chain_id=row.get("parent_chain_id"),
                    trap_note=row.get("trap_note", ""),
                    priority_tier=row.get("priority_tier", 1)
                )

            # Route to target deck
            d_name = row.get("deck_name", "").strip()
            if d_name:
                deck_dest = get_or_create_deck_by_path(self._data, d_name, context_deck=default_target_deck)
            else:
                deck_dest = default_target_deck

            deck_dest.setdefault("cards", []).append(card)
            target_deck_ids.add(deck_dest.get("_id"))
            new_cards.append(card)

        # If default_target_deck was newly created but never used because cards had explicit deck_names, clean it up
        if is_new_deck and default_target_deck and not default_target_deck.get("cards") and not default_target_deck.get("children"):
            if default_target_deck in self._data.get("decks", []):
                self._data["decks"].remove(default_target_deck)

        if not new_cards and not updated_cards:
            QMessageBox.information(
                self,
                "All Cards Skipped",
                "All cards in the import data were detected as duplicates and skipped according to your duplicate policy."
            )
            return

        self._imported_count = len(new_cards)
        self._updated_count = len(updated_cards)
        self._skipped_duplicates_count = skipped_count

        from perf_utils import invalidate_deck_stats
        invalidate_deck_stats()
        store.mark_dirty()
        store.save_force(async_save=True)

        self.accept()

    def get_result(self) -> dict:
        """Returns details about the completed import operation."""
        return {
            "count": self._imported_count,
            "updated_count": getattr(self, "_updated_count", 0),
            "skipped_duplicates": self._skipped_duplicates_count,
            "target_deck_id": self._target_deck_id,
            "is_new_deck": self._is_new_deck
        }
