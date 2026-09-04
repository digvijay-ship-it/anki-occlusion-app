"""
Concept Hub & Mind-Map Slide-Out Drawer for ReviewScreen.
Allows zero-mutation interactive browsing of story chains,
connected concept tags, and cross-deck mind-map links.
"""

from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QTabWidget, QTextBrowser,
    QScrollArea, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal, QSettings
from PyQt5.QtGui import QColor, QFont
from theme_manager import get_palette
import html
import re


class ConceptHubDrawer(QFrame):
    """
    Slide-out Concept Hub Drawer on ReviewScreen.
    Displays:
    1. Topic Chain Steps (Step 1..N) with live progress.
    2. Connected Concepts & Cross-Deck Mind-Map Cards.
    3. Instant Accordion / Card Quick-Peek View.
    4. One-Click Practice Mode on current concept cluster.
    """
    practice_requested = pyqtSignal(list)

    SETTINGS_WIDTH_KEY = "review/concept_hub_width"
    DEFAULT_WIDTH = 460
    MIN_WIDTH = 320
    RESIZE_MARGIN = 8

    def __init__(self, review_screen, parent=None):
        super().__init__(parent or review_screen)
        self.rs = review_screen
        self.setObjectName("concept_hub_drawer")
        self._current_card = None
        self._current_tag = None
        self._selected_card = None
        self._all_chain_cards = []
        self._related_cards = []
        
        self._resizing = False
        self._drag_start_x = 0
        self._drag_start_w = self.DEFAULT_WIDTH

        settings = QSettings("AnkiOcclusion", "App")
        saved_w = settings.value(self.SETTINGS_WIDTH_KEY, self.DEFAULT_WIDTH, type=int)
        self._drawer_width = max(self.MIN_WIDTH, saved_w if isinstance(saved_w, int) and saved_w > 0 else self.DEFAULT_WIDTH)

        self.setMouseTracking(True)
        self.setFixedWidth(self._drawer_width)
        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        theme = getattr(self.rs, "theme", "classic")
        p = get_palette(theme)
        self.p = p

        bg = p.get("C_SURFACE", "#1A1A24")
        border = p.get("C_BORDER", "#2E2E3E")
        text = p.get("C_TEXT", "#FFFFFF")
        subtext = p.get("C_SUBTEXT", "#A0AEC0")
        accent = p.get("C_ACCENT", "#5C7CFA")
        card_bg = p.get("C_CARD", "#222230")

        self.setStyleSheet(f"""
            QFrame#concept_hub_drawer {{
                background-color: {bg};
                border-left: 2px solid {accent};
                border-top: 1px solid {border};
                border-bottom: 1px solid {border};
                border-radius: 0px;
            }}
            QLabel {{
                color: {text};
                font-family: 'Segoe UI', sans-serif;
            }}
            QLineEdit {{
                background: {card_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 17px;
            }}
            QLineEdit:focus {{
                border: 1px solid {accent};
            }}
            QListWidget {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 6px;
                color: {text};
                font-size: 15px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-bottom: 1px solid {border};
                border-radius: 4px;
                font-size: 15px;
            }}
            QListWidget::item:hover {{
                background: rgba(92, 124, 250, 0.18);
            }}
            QListWidget::item:selected {{
                background: rgba(92, 124, 250, 0.35);
                color: #FFFFFF;
                border: 1px solid {accent};
            }}
            QTabWidget::pane {{
                border: 1px solid {border};
                background: {bg};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                background: {card_bg};
                color: {subtext};
                padding: 8px 18px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 16px;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                background: {accent};
                color: #FFFFFF;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        lbl_title = QLabel("🧠 Mind-Map Concept Hub")
        lbl_title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_title.setStyleSheet(f"color: {accent};")
        hdr.addWidget(lbl_title)
        hdr.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setToolTip("Close Concept Hub (Esc / Alt+M)")
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {subtext};
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: rgba(255, 107, 107, 0.2);
                color: #FF6B6B;
            }}
        """)
        btn_close.clicked.connect(self.close_drawer)
        hdr.addWidget(btn_close)
        layout.addLayout(hdr)

        # Active Concept Anchor Badge
        self.lbl_anchor = QLabel("Topic: —")
        self.lbl_anchor.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_anchor.setStyleSheet(f"background: rgba(92, 124, 250, 0.12); color: {accent}; padding: 6px 12px; border-radius: 6px;")
        self.lbl_anchor.setWordWrap(True)
        layout.addWidget(self.lbl_anchor)

        # Search Filter
        self.inp_filter = QLineEdit()
        self.inp_filter.setFont(QFont("Segoe UI", 13))
        self.inp_filter.setPlaceholderText("🔍 Filter cards, steps, or keywords...")
        self.inp_filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.inp_filter)

        # Tabs
        self.tabs = QTabWidget()
        
        # Tab 1: Story Chain
        tab_chain = QWidget()
        l_chain = QVBoxLayout(tab_chain)
        l_chain.setContentsMargins(4, 4, 4, 4)
        self.list_chain = QListWidget()
        self.list_chain.setWordWrap(True)
        self.list_chain.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list_chain.itemClicked.connect(self._on_chain_card_selected)
        self.list_chain.itemDoubleClicked.connect(self._on_item_double_clicked)
        l_chain.addWidget(self.list_chain)
        self.tabs.addTab(tab_chain, "🔗 Topic Chain")

        # Tab 2: Related Mind-Map
        tab_related = QWidget()
        l_related = QVBoxLayout(tab_related)
        l_related.setContentsMargins(4, 4, 4, 4)
        self.list_related = QListWidget()
        self.list_related.setWordWrap(True)
        self.list_related.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list_related.itemClicked.connect(self._on_related_card_selected)
        self.list_related.itemDoubleClicked.connect(self._on_item_double_clicked)
        l_related.addWidget(self.list_related)
        self.tabs.addTab(tab_related, "🌐 Connected Web")

        # Vertical Splitter: Topic List on Top (Scrollable), Expanded Quick-Peek on Bottom
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle:vertical {{
                background: {border};
                height: 5px;
                margin: 2px 0px;
                border-radius: 2px;
            }}
            QSplitter::handle:vertical:hover {{
                background: {accent};
            }}
        """)
        self.splitter.addWidget(self.tabs)

        # Quick-Peek Container
        peek_container = QWidget()
        peek_l = QVBoxLayout(peek_container)
        peek_l.setContentsMargins(0, 2, 0, 0)
        peek_l.setSpacing(6)

        lbl_peek = QLabel("📋 Card Quick-Peek (Zero-Mutation):")
        lbl_peek.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_peek.setStyleSheet(f"color: {accent};")
        peek_l.addWidget(lbl_peek)

        self.txt_peek = QTextBrowser()
        self.txt_peek.setStyleSheet(f"""
            QTextBrowser {{
                background: {card_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 12px;
                font-size: 16px;
            }}
        """)
        self.txt_peek.setHtml("<i style='color:#718096; font-size: 15px;'>Click any card above to instantly preview its Q&A, deep notes, and exam traps...</i>")
        peek_l.addWidget(self.txt_peek)

        self.splitter.addWidget(peek_container)
        self.splitter.setSizes([260, 460])
        layout.addWidget(self.splitter, stretch=1)

        # Bottom Action Row
        btn_row = QHBoxLayout()
        self.btn_practice_concept = QPushButton("🎯 Practice This Chain (Isolated)")
        self.btn_practice_concept.setStyleSheet(f"""
            QPushButton {{
                background: {accent};
                color: #FFFFFF;
                font-weight: bold;
                font-size: 14px;
                border-radius: 6px;
                padding: 10px 18px;
            }}
            QPushButton:hover {{
                background: #4C6EF5;
            }}
        """)
        self.btn_practice_concept.clicked.connect(self._on_practice_concept_clicked)
        btn_row.addWidget(self.btn_practice_concept)

        layout.addLayout(btn_row)

    def update_geometry(self):
        parent_w = self.rs.width() if hasattr(self.rs, "width") else 800
        parent_h = self.rs.height() if hasattr(self.rs, "height") else 600
        max_w = max(self.MIN_WIDTH, int(parent_w * 0.85))
        dw = max(self.MIN_WIDTH, min(max_w, getattr(self, "_drawer_width", self.DEFAULT_WIDTH)))
        self._drawer_width = dw
        self.setFixedWidth(dw)
        self.setGeometry(parent_w - dw, 0, dw, parent_h)
        if self.isVisible():
            self.raise_()

    def open_drawer(self, card=None, tag_filter=None):
        """Populate and show the drawer."""
        self._current_card = card or (self.rs._items[self.rs._idx][0] if getattr(self.rs, "_items", None) and 0 <= self.rs._idx < len(self.rs._items) else None)
        self._current_tag = tag_filter
        self._refresh_content()

        self.update_geometry()

        self.show()
        self.raise_()
        self.inp_filter.setFocus()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.pos().x() <= self.RESIZE_MARGIN:
            self._resizing = True
            self._drag_start_x = event.globalPos().x()
            self._drag_start_w = self.width()
            self.setCursor(Qt.SizeHorCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = self._drag_start_x - event.globalPos().x()
            parent_w = self.rs.width() if hasattr(self.rs, "width") else 1200
            max_w = max(self.MIN_WIDTH, int(parent_w * 0.85))
            new_w = max(self.MIN_WIDTH, min(max_w, self._drag_start_w + delta))
            self._drawer_width = new_w
            self.update_geometry()
            event.accept()
            return

        if event.pos().x() <= self.RESIZE_MARGIN:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self.setCursor(Qt.ArrowCursor)
            QSettings("AnkiOcclusion", "App").setValue(self.SETTINGS_WIDTH_KEY, self.width())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._resizing:
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def close_drawer(self):
        self.hide()
        if hasattr(self.rs, "canvas"):
            self.rs.canvas.setFocus()

    def toggle_drawer(self):
        if self.isVisible():
            self.close_drawer()
        else:
            self.open_drawer()

    def _refresh_content(self):
        if not self._current_card:
            return

        c = self._current_card
        anchor = c.get("context_anchor") or c.get("title") or "General Knowledge"
        self.lbl_anchor.setText(f"📌 {anchor}")

        # 1. Collect all cards in the current session/deck that form the chain
        session_cards = [item[0] for item in getattr(self.rs, "_items", []) if isinstance(item, (list, tuple)) and item]
        
        # Filter to cards belonging to the active sub-topic context_anchor if present
        curr_anchor = self._current_card.get("context_anchor") if self._current_card else None
        if curr_anchor:
            anchor_cards = [c for c in session_cards if c.get("context_anchor") == curr_anchor]
            if anchor_cards:
                session_cards = anchor_cards

        # Sort session cards by chain_order
        def _c_sort(x):
            try:
                return int(x.get("chain_order", 0) or 0)
            except Exception:
                return 0
        
        self._all_chain_cards = sorted(session_cards, key=_c_sort)
        
        # 2. Collect related cross-deck cards sharing tags or related concepts
        self._recalculate_related_cards()
        self._apply_filter(self.inp_filter.text())

    def _detect_card_domain(self, card):
        if not card:
            return "general"
        domain = card.get("domain")
        if domain:
            return domain
        tags_str = " ".join(str(t).lower() for t in card.get("tags", []))
        anchor_str = (card.get("context_anchor") or "").lower()
        full_blob = f"{tags_str} {anchor_str}".lower()
        if any(k in full_blob for k in ["temple", "nagara", "dravida", "vesara", "architecture", "वास्तुकला"]):
            return "architecture"
        if any(k in full_blob for k in ["music", "instrument", "bansuri", "santoor", "sitar", "tabla", "shehnai", "संगीत", "वाद्य"]):
            return "music"
        if any(k in full_blob for k in ["dance", "kathak", "bharatanatyam", "kuchipudi", "gharana", "घराना", "नृत्य"]):
            return "dance"
        if any(k in full_blob for k in ["inscription", "literature", "prashasti", "कालिदास", "अभिलेख", "साहित्य"]):
            return "literature"
        if any(k in full_blob for k in ["tax", "coin", "dinara", "administration", "कर", "सिक्के", "प्रशासन"]):
            return "economy"
        if any(k in full_blob for k in ["ruler", "king", "dynasty", "battle", "शासक", "राजा", "विजय"]):
            return "rulers"
        if any(k in full_blob for k in ["emergency", "amendment", "article", "constitution", "आपातकाल", "संविधान"]):
            return "polity"
        if any(k in full_blob for k in ["plateau", "river", "mountain", "ghat", "पठार", "नदी", "पर्वत"]):
            return "geography"
        return "general"

    def _recalculate_related_cards(self):
        if not self._current_card:
            self._related_cards = []
            return

        c = self._current_card
        target_domain = self._detect_card_domain(c)
        data = getattr(self.rs, "_data", None) or {}
        all_db_cards = []
        def _walk_decks(decks):
            for d in decks or []:
                all_db_cards.extend(d.get("cards", []))
                _walk_decks(d.get("children", []))
        _walk_decks(data.get("decks", []))

        GENERIC_TAGS = {"ancient_history", "gupta_era", "polity", "geography", "static_gk", "constitution_of_india", "general_knowledge", "physical_geography", "indian_geography", "general_polity", "mock_core"}
        current_tags = set(str(t).strip().lower() for t in c.get("tags", []) if t) - GENERIC_TAGS
        current_related = set(str(r).strip().lower() for r in c.get("related_concepts", []) if r)

        exact_concept_terms = set()
        for r in current_related:
            clean_r = r.lower()
            exact_concept_terms.add(clean_r)
            paren_match = re.search(r'\((.*?)\)', clean_r)
            if paren_match:
                sub_term = paren_match.group(1).strip()
                if len(sub_term) >= 4:
                    exact_concept_terms.add(sub_term)
            main_term = re.sub(r'\(.*?\)', '', clean_r).strip()
            if len(main_term) >= 4:
                exact_concept_terms.add(main_term)

        c_id = c.get("_id")
        c_q = (c.get("question") or c.get("title") or "").strip().lower()

        scored_candidates = []
        for db_c in all_db_cards:
            if db_c is c:
                continue
            if c_id is not None and db_c.get("_id") == c_id:
                continue
            db_q = (db_c.get("question") or db_c.get("title") or "").strip().lower()
            if c_q and db_q == c_q:
                continue

            c_domain = self._detect_card_domain(db_c)
            if target_domain != "general" and c_domain != "general" and target_domain != c_domain:
                continue

            db_tags = set(str(t).strip().lower() for t in db_c.get("tags", []) if t) - GENERIC_TAGS
            db_related = set(str(r).strip().lower() for r in db_c.get("related_concepts", []) if r)
            db_corpus = f"{db_q} {db_c.get('context_anchor', '')} {' '.join(db_c.get('tags', []))} {' '.join(db_c.get('related_concepts', []))}".lower()

            score = 0
            # 1. Match specific tags
            shared_tags = current_tags.intersection(db_tags)
            score += len(shared_tags) * 25

            # 2. Shared related concepts
            shared_rel = current_related.intersection(db_related)
            score += len(shared_rel) * 35

            # 3. Cross match: Does candidate mention our exact multi-char terms?
            for term in exact_concept_terms:
                if term in db_corpus:
                    score += 20

            # 4. Fallback on explicit current tag if active
            if self._current_tag and self._current_tag.lower() in db_corpus:
                score += 15

            if score > 0:
                scored_candidates.append((score, db_c))

        # Sort by relevance score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        self._related_cards = [item[1] for item in scored_candidates]

    def _get_concept_web_for_query(self, query):
        q = query.strip().lower()
        if not q:
            return self._related_cards

        data = getattr(self.rs, "_data", None) or {}
        all_db_cards = []
        def _walk_decks(decks):
            for d in decks or []:
                all_db_cards.extend(d.get("cards", []))
                _walk_decks(d.get("children", []))
        _walk_decks(data.get("decks", []))

        GENERIC_TAGS = {"ancient_history", "gupta_era", "polity", "geography", "static_gk", "constitution_of_india", "general_knowledge", "physical_geography", "indian_geography", "general_polity", "mock_core"}

        # 1. Find cards matching the query
        focal_cards = []
        for c in all_db_cards:
            q_text = (c.get("question") or c.get("title") or "").lower()
            tags_str = " ".join(str(t) for t in c.get("tags", [])).lower()
            rel_str = " ".join(str(r) for r in c.get("related_concepts", [])).lower()
            if q in q_text or q in tags_str or q in rel_str:
                focal_cards.append(c)

        if not focal_cards and self._current_card:
            focal_cards = [self._current_card]

        target_domain = self._detect_card_domain(focal_cards[0]) if focal_cards else "general"

        # 2. Gather concept cluster tags and exact terms from focal cards
        target_tags = set()
        target_related = set()
        exact_concept_terms = set()
        focal_ids = set(c.get("_id") for c in focal_cards if c.get("_id") is not None)
        focal_questions = set((c.get("question") or "").strip().lower() for c in focal_cards)

        for fc in focal_cards:
            target_tags.update(set(str(t).strip().lower() for t in fc.get("tags", [])) - GENERIC_TAGS)
            target_related.update(set(str(r).strip().lower() for r in fc.get("related_concepts", [])))

        for r in target_related:
            clean_r = r.lower()
            exact_concept_terms.add(clean_r)
            paren_match = re.search(r'\((.*?)\)', clean_r)
            if paren_match:
                sub_term = paren_match.group(1).strip()
                if len(sub_term) >= 4:
                    exact_concept_terms.add(sub_term)
            main_term = re.sub(r'\(.*?\)', '', clean_r).strip()
            if len(main_term) >= 4:
                exact_concept_terms.add(main_term)

        # 3. Score all candidates against this concept cluster with domain protection
        scored_candidates = []
        for db_c in all_db_cards:
            c_id = db_c.get("_id")
            q_text = (db_c.get("question") or db_c.get("title") or "").strip().lower()
            is_focal = (c_id in focal_ids) if c_id is not None else (q_text in focal_questions)

            c_domain = self._detect_card_domain(db_c)
            if target_domain != "general" and c_domain != "general" and target_domain != c_domain:
                continue

            db_tags = set(str(t).strip().lower() for t in db_c.get("tags", []) if t) - GENERIC_TAGS
            db_related = set(str(r).strip().lower() for r in db_c.get("related_concepts", []) if r)
            db_corpus = f"{q_text} {db_c.get('context_anchor', '')} {' '.join(db_c.get('tags', []))} {' '.join(db_c.get('related_concepts', []))}".lower()

            score = 0
            shared_tags = target_tags.intersection(db_tags)
            score += len(shared_tags) * 25

            shared_rel = target_related.intersection(db_related)
            score += len(shared_rel) * 35

            for term in exact_concept_terms:
                if term in db_corpus:
                    score += 20

            if is_focal:
                score -= 10

            if score > 0:
                scored_candidates.append((score, db_c))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_candidates]

    def _apply_filter(self, query=""):
        q = query.strip().lower()
        self.list_chain.clear()
        self.list_related.clear()

        # Populate chain list
        curr_id = self._current_card.get("_id") if self._current_card else None
        for i, card in enumerate(self._all_chain_cards):
            order = card.get("chain_order", i + 1)
            q_text = card.get("question") or card.get("title") or "Untitled Card"
            anchor = card.get("context_anchor") or ""
            search_blob = f"{q_text} {anchor} {' '.join(card.get('tags', []))} {' '.join(card.get('related_concepts', []))}".lower()
            
            if q and (q not in search_blob):
                continue

            status_icon = "▶ " if card.get("_id") == curr_id else "🔗 "
            item_text = f"{status_icon}Step {order}: {q_text}"
            
            it = QListWidgetItem(item_text)
            it.setData(Qt.UserRole, card)
            if card.get("_id") == curr_id:
                it.setForeground(QColor("#70A5FD"))
                it.setFont(QFont("Segoe UI", 12, QFont.Bold))
            else:
                it.setFont(QFont("Segoe UI", 12))
            self.list_chain.addItem(it)

        # Populate related list: If query exists, search full concept web; otherwise use active card's web
        if q:
            display_related = self._get_concept_web_for_query(q)
        else:
            display_related = self._related_cards

        for card in display_related:
            q_text = card.get("question") or card.get("title") or "Untitled Card"
            it = QListWidgetItem(f"🌐 {q_text}")
            it.setData(Qt.UserRole, card)
            it.setFont(QFont("Segoe UI", 12))
            self.list_related.addItem(it)

        if not self.list_related.count():
            empty_item = QListWidgetItem("No cross-linked cards found for this search yet.")
            empty_item.setFont(QFont("Segoe UI", 11, QFont.StyleItalic))
            self.list_related.addItem(empty_item)

    def _on_chain_card_selected(self, item):
        card = item.data(Qt.UserRole)
        if card:
            self._selected_card = card
            self._current_card = card
            anchor = card.get("context_anchor") or card.get("title") or "General Knowledge"
            self.lbl_anchor.setText(f"📌 {anchor}")
            self._render_peek(card)
            self._recalculate_related_cards()
            self._apply_filter(self.inp_filter.text())

    def _on_related_card_selected(self, item):
        card = item.data(Qt.UserRole)
        if card:
            self._selected_card = card
            anchor = card.get("context_anchor") or card.get("title") or "General Knowledge"
            self.lbl_anchor.setText(f"📌 {anchor}")
            self._render_peek(card)

    def _on_item_double_clicked(self, item):
        card = item.data(Qt.UserRole)
        if card:
            self._selected_card = card
            self._render_peek(card)
            self._on_practice_concept_clicked()

    def _render_peek(self, card):
        q = html.escape(card.get("question", "") or card.get("title", ""))
        a = html.escape(card.get("answer", ""))
        notes = html.escape(card.get("notes", ""))
        trap = html.escape(card.get("trap_note", ""))
        step = card.get("chain_order", "")
        anchor = html.escape(card.get("context_anchor", "") or "")

        html_content = f"""
        <div style="font-family: 'Segoe UI', sans-serif; line-height: 1.5; color: #F8F8F2;">
            <div style="font-size: 14px; color: #70A5FD; font-weight: bold; margin-bottom: 8px; letter-spacing: 0.5px;">
                🔗 STEP {step} &nbsp;|&nbsp; 📌 {anchor}
            </div>
            <div style="font-size: 19px; font-weight: bold; color: #FFFFFF; margin-bottom: 12px; line-height: 1.45;">
                {q}
            </div>
            <hr style="border: none; border-top: 1px solid #2E2E3E; margin: 10px 0;">
            <div style="font-size: 14px; color: #50FA7B; font-weight: bold; letter-spacing: 1px; margin-bottom: 6px;">
                ANSWER:
            </div>
            <div style="font-size: 17px; color: #E2E8F0; line-height: 1.55; margin-bottom: 12px;">
                {a}
            </div>
        """
        if trap:
            html_content += f"""
            <div style="background: rgba(255, 107, 107, 0.14); border-left: 4px solid #FF6B6B; border-radius: 6px; padding: 10px 14px; margin: 10px 0; font-size: 16px; color: #FFA066; line-height: 1.45;">
                ⚠️ <b>EXAM TRAP:</b> {trap}
            </div>
            """
        if notes and notes != trap:
            html_content += f"""
            <div style="background: rgba(92, 124, 250, 0.10); border-left: 4px solid #5C7CFA; border-radius: 6px; padding: 10px 14px; margin: 10px 0; font-size: 16px; color: #CBD5E1; line-height: 1.45;">
                📝 <b>DEEP NOTES:</b> {notes}
            </div>
            """
        html_content += "</div>"
        self.txt_peek.setHtml(html_content)

    def _on_practice_concept_clicked(self):
        """Launches isolated practice on current chain or filtered cards starting at selected card."""
        sel_card = getattr(self, "_selected_card", None) or self._current_card

        # 1. Determine target chain cards
        target_cards = []
        active_list = self.list_chain if self.tabs.currentIndex() == 0 else self.list_related
        for i in range(active_list.count()):
            it = active_list.item(i)
            c = it.data(Qt.UserRole)
            if isinstance(c, dict):
                target_cards.append(c)

        # Fallback to matching anchor if active list is empty
        if not target_cards and sel_card:
            sel_anchor = (sel_card.get("context_anchor") or "").strip().lower()
            if sel_anchor:
                target_cards = [
                    c for c in self._all_chain_cards
                    if (c.get("context_anchor") or "").strip().lower() == sel_anchor
                ]

        if not target_cards and sel_card:
            target_cards = [sel_card]

        if not target_cards:
            return

        self.close_drawer()

        # Delegate directly to ReviewScreen's isolated practice handler
        if hasattr(self.rs, "start_isolated_chain_practice"):
            self.rs.start_isolated_chain_practice(target_cards, start_card=sel_card)
        else:
            # Fallback: locate home screen traversing up the widget hierarchy
            p = self.rs
            while p and not hasattr(p, "show_review_sequential"):
                p = p.parent()
            if p and hasattr(p, "show_review_sequential"):
                p.show_review_sequential([target_cards], getattr(self.rs, "_data", {}), is_practice=True)
