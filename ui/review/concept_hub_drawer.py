"""
Concept Hub & Mind-Map Slide-Out Drawer for ReviewScreen.
Allows zero-mutation interactive browsing of story chains,
connected concept tags, and cross-deck mind-map links.
"""

from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QTabWidget, QTextBrowser,
    QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from theme_manager import get_palette
import html


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

    def __init__(self, review_screen, parent=None):
        super().__init__(parent or review_screen)
        self.rs = review_screen
        self.setObjectName("concept_hub_drawer")
        self._current_card = None
        self._current_tag = None
        self._all_chain_cards = []
        self._related_cards = []
        
        self.setFixedWidth(420)
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
                padding: 6px 10px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {accent};
            }}
            QListWidget {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 6px;
                color: {text};
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid {border};
                border-radius: 4px;
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
                padding: 6px 14px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 11px;
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
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
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
        self.lbl_anchor.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_anchor.setStyleSheet(f"background: rgba(92, 124, 250, 0.12); color: {accent}; padding: 4px 8px; border-radius: 4px;")
        self.lbl_anchor.setWordWrap(True)
        layout.addWidget(self.lbl_anchor)

        # Search Filter
        self.inp_filter = QLineEdit()
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
        self.list_chain.itemClicked.connect(self._on_chain_card_selected)
        l_chain.addWidget(self.list_chain)
        self.tabs.addTab(tab_chain, "🔗 Topic Chain")

        # Tab 2: Related Mind-Map
        tab_related = QWidget()
        l_related = QVBoxLayout(tab_related)
        l_related.setContentsMargins(4, 4, 4, 4)
        self.list_related = QListWidget()
        self.list_related.itemClicked.connect(self._on_related_card_selected)
        l_related.addWidget(self.list_related)
        self.tabs.addTab(tab_related, "🌐 Connected Web")

        layout.addWidget(self.tabs, stretch=1)

        # Accordion Quick-Peek Card View
        lbl_peek = QLabel("📋 Card Quick-Peek (Zero-Mutation):")
        lbl_peek.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_peek.setStyleSheet(f"color: {subtext};")
        layout.addWidget(lbl_peek)

        self.txt_peek = QTextBrowser()
        self.txt_peek.setFixedHeight(180)
        self.txt_peek.setStyleSheet(f"""
            QTextBrowser {{
                background: {card_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
            }}
        """)
        self.txt_peek.setHtml("<i style='color:#718096;'>Click any card above to instantly preview its Q&A, deep notes, and exam traps...</i>")
        layout.addWidget(self.txt_peek)

        # Bottom Action Row
        btn_row = QHBoxLayout()
        self.btn_practice_concept = QPushButton("🎯 Practice This Chain (Isolated)")
        self.btn_practice_concept.setStyleSheet(f"""
            QPushButton {{
                background: {accent};
                color: #FFFFFF;
                font-weight: bold;
                font-size: 11px;
                border-radius: 6px;
                padding: 7px 14px;
            }}
            QPushButton:hover {{
                background: #4C6EF5;
            }}
        """)
        self.btn_practice_concept.clicked.connect(self._on_practice_concept_clicked)
        btn_row.addWidget(self.btn_practice_concept)

        layout.addLayout(btn_row)

    def open_drawer(self, card=None, tag_filter=None):
        """Populate and show the drawer."""
        self._current_card = card or (self.rs._items[self.rs._idx][0] if getattr(self.rs, "_items", None) and 0 <= self.rs._idx < len(self.rs._items) else None)
        self._current_tag = tag_filter
        self._refresh_content()

        parent_w = self.rs.width() if hasattr(self.rs, "width") else 800
        parent_h = self.rs.height() if hasattr(self.rs, "height") else 600
        dw = min(420, max(280, parent_w - 80))
        self.setGeometry(parent_w - dw, 0, dw, parent_h)

        self.show()
        self.raise_()
        self.inp_filter.setFocus()

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
        
        # Sort session cards by chain_order
        def _c_sort(x):
            try:
                return int(x.get("chain_order", 0) or 0)
            except Exception:
                return 0
        
        self._all_chain_cards = sorted(session_cards, key=_c_sort)
        
        # 2. Collect related cross-deck cards sharing tags or related concepts
        data = getattr(self.rs, "_data", None) or {}
        all_db_cards = []
        def _walk_decks(decks):
            for d in decks or []:
                all_db_cards.extend(d.get("cards", []))
                _walk_decks(d.get("children", []))
        _walk_decks(data.get("decks", []))

        current_tags = set(str(t).strip().lower() for t in c.get("tags", []) if t)
        current_related = set(str(r).strip().lower() for r in c.get("related_concepts", []) if r)
        
        related_found = []
        for db_c in all_db_cards:
            if db_c.get("_id") == c.get("_id"):
                continue
            db_tags = set(str(t).strip().lower() for t in db_c.get("tags", []) if t)
            db_related = set(str(r).strip().lower() for r in db_c.get("related_concepts", []) if r)
            
            # Match on shared tags or related concepts
            if (current_tags and current_tags.intersection(db_tags)) or (current_related and current_related.intersection(db_related)):
                related_found.append(db_c)
            elif self._current_tag and (self._current_tag.lower() in [t.lower() for t in db_c.get("tags", [])] or self._current_tag.lower() in db_c.get("question", "").lower()):
                related_found.append(db_c)

        self._related_cards = related_found
        self._apply_filter(self.inp_filter.text())

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
            
            if q and (q not in q_text.lower() and q not in anchor.lower()):
                continue

            status_icon = "▶ " if card.get("_id") == curr_id else "🔗 "
            item_text = f"{status_icon}Step {order}: {q_text[:50]}..." if len(q_text) > 50 else f"{status_icon}Step {order}: {q_text}"
            
            it = QListWidgetItem(item_text)
            it.setData(Qt.UserRole, card)
            if card.get("_id") == curr_id:
                it.setForeground(QColor("#70A5FD"))
                it.setFont(QFont("Segoe UI", 10, QFont.Bold))
            self.list_chain.addItem(it)

        # Populate related list
        for card in self._related_cards:
            q_text = card.get("question") or card.get("title") or "Untitled Card"
            anchor = card.get("context_anchor") or ""
            if q and (q not in q_text.lower() and q not in anchor.lower()):
                continue
            it = QListWidgetItem(f"🌐 {q_text[:55]}...")
            it.setData(Qt.UserRole, card)
            self.list_related.addItem(it)

        if not self.list_related.count():
            self.list_related.addItem(QListWidgetItem("No cross-linked cards found for this tag yet."))

    def _on_chain_card_selected(self, item):
        card = item.data(Qt.UserRole)
        if card:
            self._render_peek(card)

    def _on_related_card_selected(self, item):
        card = item.data(Qt.UserRole)
        if card:
            self._render_peek(card)

    def _render_peek(self, card):
        q = html.escape(card.get("question", "") or card.get("title", ""))
        a = html.escape(card.get("answer", ""))
        notes = html.escape(card.get("notes", ""))
        trap = html.escape(card.get("trap_note", ""))
        step = card.get("chain_order", "")
        anchor = html.escape(card.get("context_anchor", "") or "")

        html_content = f"""
        <div style="font-family: 'Segoe UI', sans-serif; line-height: 1.4;">
            <div style="font-size: 10px; color: #70A5FD; font-weight: bold; margin-bottom: 4px;">
                🔗 Step {step} | 📌 {anchor}
            </div>
            <div style="font-size: 13px; font-weight: bold; color: #FFFFFF; margin-bottom: 8px;">
                {q}
            </div>
            <hr style="border: none; border-top: 1px solid #2E2E3E; margin: 6px 0;">
            <div style="font-size: 10px; color: #50FA7B; font-weight: bold;">ANSWER:</div>
            <div style="font-size: 12px; color: #F8F8F2; margin-bottom: 6px;">
                {a}
            </div>
        """
        if trap:
            html_content += f"""
            <div style="background: rgba(255, 107, 107, 0.12); border-left: 2px solid #FF6B6B; padding: 4px 6px; margin: 4px 0; font-size: 11px; color: #FFA066;">
                ⚠️ <b>EXAM TRAP:</b> {trap}
            </div>
            """
        if notes and notes != trap:
            html_content += f"""
            <div style="background: rgba(92, 124, 250, 0.08); border-left: 2px solid #5C7CFA; padding: 4px 6px; margin: 4px 0; font-size: 11px; color: #A0AEC0;">
                📝 <b>DEEP NOTES:</b> {notes}
            </div>
            """
        html_content += "</div>"
        self.txt_peek.setHtml(html_content)

    def _on_practice_concept_clicked(self):
        """Launches practice on current chain or filtered cards."""
        cards = self._all_chain_cards if self._all_chain_cards else [self._current_card]
        if cards:
            self.close_drawer()
            home = getattr(self.rs, "_home", None) or (self.rs.parent() if hasattr(self.rs, "parent") else None)
            if hasattr(home, "show_review_sequential"):
                home.show_review_sequential([cards], getattr(self.rs, "_data", {}), is_practice=True)
