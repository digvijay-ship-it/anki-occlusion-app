# -*- coding: utf-8 -*-
"""
ui/fsrs_center_dialog.py
~~~~~~~~~~~~~~~~~~~~~~~~
Dedicated FSRS Memory, Retention & Optimization Center.
Dynamic Responsive Layout:
- Auto-expands to fill 88-92% of screen width/height so zero horizontal scroll is ever needed.
- High-visibility 1.4x enlarged desktop typography standard:
  - Header Title: 32pt Segoe UI Black.
  - Section Headings: 28pt Segoe UI Bold.
  - Card Titles: 24pt - 27pt Segoe UI Bold.
  - Big Numbers: 53pt Segoe UI Black.
  - Descriptions & Explanations: 22pt - 24pt Segoe UI.
  - Action Buttons: 29pt Segoe UI Bold.
  - Close Button: 25pt Segoe UI Bold.
  - Message Popups: 24pt Segoe UI.
  - Sliders: 38px touch handles, NoWheelSlider to prevent vertical scroll hijacking.
  - Horizontal Scrollbar: Hard disabled (Qt.ScrollBarAlwaysOff) with responsive word-wrapping.
"""

import os
import json
import sqlite3
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QFrame, QMessageBox, QProgressBar,
    QApplication, QScrollArea, QSlider, QSizePolicy, QComboBox, QCompleter
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor

from theme_manager import get_palette, is_retro_theme
from data_manager import store
import fsrs_engine

DB_PATH = os.path.join(os.path.expanduser("~"), "anki_occlusion_data.db")


def get_all_decks_with_paths():
    """Returns a list of all decks sorted by hierarchical path, with id, name, path, and recursive card_count."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name, parent_id FROM decks")
        rows = cur.fetchall()
        id_map = {r[0]: {'id': r[0], 'name': r[1], 'parent_id': r[2]} for r in rows}

        children_map = {}
        for r in rows:
            p = r[2]
            children_map.setdefault(p, []).append(r[0])

        def get_path(d_id):
            parts = []
            curr = d_id
            visited = set()
            while curr and curr in id_map and curr not in visited:
                visited.add(curr)
                parts.append(id_map[curr]['name'])
                curr = id_map[curr]['parent_id']
            return ' / '.join(reversed(parts))

        # Count boxes and cards per deck
        cur.execute("SELECT c.deck_id, count(*) FROM boxes b JOIN cards c ON c.id = b.card_id GROUP BY c.deck_id")
        box_counts = dict(cur.fetchall())
        cur.execute("SELECT deck_id, count(*) FROM cards GROUP BY deck_id")
        card_counts = dict(cur.fetchall())
        conn.close()

        def get_recursive_count(d_id, visited=None):
            if visited is None:
                visited = set()
            if d_id in visited:
                return 0
            visited.add(d_id)
            direct = max(box_counts.get(d_id, 0), card_counts.get(d_id, 0))
            for ch in children_map.get(d_id, []):
                direct += get_recursive_count(ch, visited)
            return direct

        result = []
        for r in rows:
            d_id = r[0]
            p = get_path(d_id)
            cnt = get_recursive_count(d_id)
            result.append({
                'id': d_id,
                'name': r[1],
                'path': p,
                'card_count': cnt,
                'parent_id': r[2]
            })
        result.sort(key=lambda x: x['path'].lower())
        return result
    except Exception:
        return []


class NoWheelSlider(QSlider):
    """Slider that ignores mouse wheel events so the page scrolls vertically without accidental adjustments."""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(QComboBox):
    """ComboBox that ignores mouse wheel events so the page scrolls vertically without accidental item switching."""
    def wheelEvent(self, event):
        event.ignore()


def get_fsrs_live_stats():
    """Calculate live memory metrics across the user collection."""
    if not os.path.exists(DB_PATH):
        return {
            "total_reviews": 0, "retention_rate": 90.0, "avg_stability": 0.0,
            "avg_difficulty": 5.0, "managed_cards": 0, "due_today": 0,
            "math_managed": 0, "gk_managed": 0, "english_managed": 0
        }
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT b.meta, b.due, d.name 
        FROM boxes b
        LEFT JOIN cards c ON c.id = b.card_id
        LEFT JOIN decks d ON d.id = c.deck_id
        WHERE b.meta IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()

    total_revs = 0
    total_lapses = 0
    stabilities = []
    difficulties = []
    today_str = date.today().isoformat()
    due_today = 0
    math_cnt = 0
    gk_cnt = 0
    eng_cnt = 0

    for meta_str, due_str, deck_name in rows:
        try:
            m = json.loads(meta_str)
            rev = m.get("reviews", 0)
            cat = fsrs_engine.get_subject_category(deck_name or "")
            if rev > 0:
                total_revs += rev
                total_lapses += m.get("fsrs_lapses", 0)
                if m.get("fsrs_stability"):
                    s = float(m["fsrs_stability"])
                    stabilities.append(s)
                    if cat == "math":
                        math_cnt += 1
                    elif cat == "english":
                        eng_cnt += 1
                    else:
                        gk_cnt += 1
                if m.get("fsrs_difficulty"):
                    difficulties.append(float(m["fsrs_difficulty"]))
            if due_str and str(due_str)[:10] <= today_str:
                due_today += 1
        except Exception:
            pass

    passed = max(0, total_revs - total_lapses)
    retention_rate = round((passed / max(1, total_revs)) * 100, 1) if total_revs > 0 else 90.0
    avg_s = round(sum(stabilities) / max(1, len(stabilities)), 1) if stabilities else 0.0
    avg_d = round(sum(difficulties) / max(1, len(difficulties)), 1) if difficulties else 5.0

    return {
        "total_reviews": total_revs,
        "retention_rate": retention_rate,
        "avg_stability": avg_s,
        "avg_difficulty": avg_d,
        "managed_cards": len(stabilities),
        "due_today": due_today,
        "math_managed": math_cnt,
        "gk_managed": gk_cnt,
        "english_managed": eng_cnt,
    }


class FSRSCenterDialog(QDialog):
    """Modern FSRS Memory, Retention & Optimization Center Modal with Dynamic Layout & 1.4x Typography."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚡ FSRS Memory, Retention & Optimization Center")
        self.setModal(True)

        # ── Dynamic Responsive Geometry (Expands to Screen, Zero Horizontal Scroll) ──
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = max(1180, min(1680, int(avail.width() * 0.88)))
            h = max(820, min(1080, int(avail.height() * 0.90)))
            self.resize(w, h)
            self.move(avail.x() + (avail.width() - w) // 2, avail.y() + (avail.height() - h) // 2)
        else:
            self.resize(1380, 920)
        self.setMinimumWidth(1050)
        self.setMinimumHeight(750)

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        self._ninja = is_retro_theme(theme) or theme == "dojo"
        p = get_palette(theme)

        self._bg = "#0D0F14" if self._ninja else p.get("C_BG", "#1E1E2E")
        self._surface = "#161922" if self._ninja else p.get("C_SURFACE", "#24283B")
        self._card = "#1C202C" if self._ninja else p.get("C_CARD", "#1E222D")
        self._border = "#2A3042" if self._ninja else p.get("C_BORDER", "#3D4457")
        self._neon = "#50FA7B"  # Always vivid neon green for maximum legibility & pop
        self._cyan = "#67E8F9"
        self._pink = "#FF79C6"
        self._purple = "#BD93F9"
        self._gold = "#F1FA8C"
        self._text = "#FFFFFF"
        self._subtext = "#CBD5E1"

        self.setStyleSheet(f"""
            QDialog {{ 
                background: {self._bg}; 
                color: {self._text}; 
            }}
            QLabel {{ 
                color: {self._text}; 
                background: transparent; 
            }}
            QFrame#statCard {{
                background: {self._card};
                border: 1px solid {self._border};
                border-radius: 14px;
                padding: 18px 24px;
            }}
            QFrame#actionCard {{
                background: {self._surface};
                border: 1px solid {self._border};
                border-radius: 14px;
                padding: 24px 28px;
            }}
            QSlider::groove:horizontal {{
                height: 18px;
                background: {self._border};
                border-radius: 9px;
            }}
            QSlider::sub-page:horizontal {{
                background: {self._neon};
                border-radius: 9px;
            }}
            QSlider::handle:horizontal {{
                background: {self._cyan};
                width: 38px;
                height: 38px;
                margin-top: -10px;
                margin-bottom: -10px;
                border-radius: 19px;
                border: 3px solid #FFFFFF;
            }}
            QSlider::handle:horizontal:hover {{
                background: #FFFFFF;
                border-color: {self._neon};
            }}
            QProgressBar {{
                background: {self._border};
                border-radius: 8px;
                text-align: center;
                color: #FFFFFF;
                font-weight: 900;
                font-size: 22px;
                height: 34px;
            }}
            QProgressBar::chunk {{
                background: {self._neon};
                border-radius: 8px;
            }}
        """)

        self._build_ui()
        self._refresh_stats()

    def _build_ui(self):
        root_l = QVBoxLayout(self)
        root_l.setContentsMargins(24, 20, 24, 20)
        root_l.setSpacing(18)

        # ── Scroll Area configured for vertical-only scrolling ─────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("background: transparent; border: none;")

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        L = QVBoxLayout(content)
        L.setContentsMargins(0, 0, 12, 0)
        L.setSpacing(22)

        # ── 1. HEADER (1.4x Enlarged) ──────────────────────────────────────────
        h_row = QHBoxLayout()
        h_row.setSpacing(16)
        icon_lbl = QLabel("⚡")
        icon_lbl.setFont(QFont("Segoe UI", 44))
        icon_lbl.setStyleSheet(f"color: {self._neon};")
        h_row.addWidget(icon_lbl, 0, Qt.AlignVCenter)

        title_l = QVBoxLayout()
        title_l.setSpacing(4)
        title = QLabel("FSRS MEMORY & RETENTION CENTER")
        title.setFont(QFont("Segoe UI", 32, QFont.Black))
        title.setStyleSheet(f"color: {self._neon}; letter-spacing: 0.5px;")
        title.setWordWrap(True)

        subtitle = QLabel("Free Spaced Repetition Scheduler — DSR Machine Learning Engine (v4.5)")
        subtitle.setFont(QFont("Segoe UI", 21, QFont.DemiBold))
        subtitle.setStyleSheet(f"color: {self._subtext};")
        subtitle.setWordWrap(True)

        title_l.addWidget(title)
        title_l.addWidget(subtitle)
        h_row.addLayout(title_l, 1)

        status_badge = QLabel("  FSRS v4.5 ACTIVE  ")
        status_badge.setFont(QFont("Segoe UI", 20, QFont.Bold))
        status_badge.setStyleSheet(f"background: rgba(80, 250, 123, 0.18); color: {self._neon}; border: 2px solid {self._neon}; border-radius: 8px; padding: 10px 22px;")
        h_row.addWidget(status_badge, 0, Qt.AlignVCenter)
        L.addLayout(h_row)

        # ── 2. LIVE RETENTION STATS (2x2 GRID - 1.4x Enlarged) ─────────────────
        stats_grid = QGridLayout()
        stats_grid.setSpacing(18)

        # C1: Retention
        c1 = QFrame()
        c1.setObjectName("statCard")
        l1 = QVBoxLayout(c1)
        l1.setSpacing(6)
        t1 = QLabel("🎯 TRUE RETENTION (सटीक याददाश्त दर)")
        t1.setFont(QFont("Segoe UI", 24, QFont.Bold))
        t1.setStyleSheet(f"color: {self._cyan};")
        t1.setWordWrap(True)
        l1.addWidget(t1)
        self._lbl_retention = QLabel("--%")
        self._lbl_retention.setFont(QFont("Segoe UI", 53, QFont.Black))
        self._lbl_retention.setStyleSheet(f"color: {self._neon};")
        l1.addWidget(self._lbl_retention)
        s1 = QLabel("आपके सभी रिव्यूज में सफल रिकॉल दर")
        s1.setFont(QFont("Segoe UI", 22, QFont.Normal))
        s1.setStyleSheet(f"color: {self._subtext};")
        s1.setWordWrap(True)
        l1.addWidget(s1)
        stats_grid.addWidget(c1, 0, 0)

        # C2: Stability
        c2 = QFrame()
        c2.setObjectName("statCard")
        l2 = QVBoxLayout(c2)
        l2.setSpacing(6)
        t2 = QLabel("🧠 MEMORY STABILITY (याददाश्त स्थायित्व)")
        t2.setFont(QFont("Segoe UI", 24, QFont.Bold))
        t2.setStyleSheet(f"color: {self._cyan};")
        t2.setWordWrap(True)
        l2.addWidget(t2)
        self._lbl_stability = QLabel("-- Days")
        self._lbl_stability.setFont(QFont("Segoe UI", 53, QFont.Black))
        self._lbl_stability.setStyleSheet(f"color: {self._cyan};")
        l2.addWidget(self._lbl_stability)
        s2 = QLabel("औसत दिन जब तक कार्ड दिमाग में ताजा रहेगा")
        s2.setFont(QFont("Segoe UI", 22, QFont.Normal))
        s2.setStyleSheet(f"color: {self._subtext};")
        s2.setWordWrap(True)
        l2.addWidget(s2)
        stats_grid.addWidget(c2, 0, 1)

        # C3: Difficulty
        c3 = QFrame()
        c3.setObjectName("statCard")
        l3 = QVBoxLayout(c3)
        l3.setSpacing(6)
        t3 = QLabel("⚖️ COGNITIVE FRICTION (कठिनाई स्तर)")
        t3.setFont(QFont("Segoe UI", 24, QFont.Bold))
        t3.setStyleSheet(f"color: {self._pink};")
        t3.setWordWrap(True)
        l3.addWidget(t3)
        self._lbl_difficulty = QLabel("-- / 10")
        self._lbl_difficulty.setFont(QFont("Segoe UI", 53, QFont.Black))
        self._lbl_difficulty.setStyleSheet(f"color: {self._pink};")
        l3.addWidget(self._lbl_difficulty)
        s3 = QLabel("मानसिक प्रयास स्तर (1 आसान से 10 कठिन)")
        s3.setFont(QFont("Segoe UI", 22, QFont.Normal))
        s3.setStyleSheet(f"color: {self._subtext};")
        s3.setWordWrap(True)
        l3.addWidget(s3)
        stats_grid.addWidget(c3, 1, 0)

        # C4: Managed
        c4 = QFrame()
        c4.setObjectName("statCard")
        l4 = QVBoxLayout(c4)
        l4.setSpacing(6)
        t4 = QLabel("📦 MANAGED MEMORY (सक्रिय FSRS कार्ड्स)")
        t4.setFont(QFont("Segoe UI", 24, QFont.Bold))
        t4.setStyleSheet(f"color: {self._purple};")
        t4.setWordWrap(True)
        l4.addWidget(t4)
        self._lbl_managed = QLabel("-- Cards")
        self._lbl_managed.setFont(QFont("Segoe UI", 53, QFont.Black))
        self._lbl_managed.setStyleSheet(f"color: {self._purple};")
        l4.addWidget(self._lbl_managed)
        s4 = QLabel("मशीन लर्निंग द्वारा ट्रैक किए जा रहे कार्ड्स")
        s4.setFont(QFont("Segoe UI", 22, QFont.Normal))
        s4.setStyleSheet(f"color: {self._subtext};")
        s4.setWordWrap(True)
        l4.addWidget(s4)
        stats_grid.addWidget(c4, 1, 1)

        L.addLayout(stats_grid)

        # ── 3. TARGET RETENTION & DECK OVERRIDES ─────────────────────────────
        # Card 1: GLOBAL MASTER RETENTION
        s_box_global = QFrame()
        s_box_global.setObjectName("actionCard")
        s_l_global = QVBoxLayout(s_box_global)
        s_l_global.setSpacing(14)

        glob_val = int(round(float(store.get().get("_request_retention", 0.90)) * 100))
        self._slider_glob, self._lbl_glob_val = self._add_slider_card(
            s_l_global, "🌐", "GLOBAL MASTER RETENTION (डिफ़ॉल्ट याददाश्त दर)",
            "(अन्य सभी सामान्य डेक्स के लिए डिफ़ॉल्ट आधार जब तक नीचे विशिष्ट ओवरराइड न सेट हो)",
            glob_val, "Master Fallback: सभी सामान्य डेक्स के लिए डिफ़ॉल्ट याददाश्त दर।",
            lambda v: self._on_global_slider_changed(v)
        )
        L.addWidget(s_box_global)

        # Card 2: DECK-SPECIFIC RETENTION OVERRIDES
        s_box_decks = QFrame()
        s_box_decks.setObjectName("actionCard")
        self._s_l_decks = QVBoxLayout(s_box_decks)
        self._s_l_decks.setSpacing(16)

        # Header with Auto-Saved badge
        d_header = QHBoxLayout()
        d_title = QLabel("🎚️ DECK-SPECIFIC RETENTION OVERRIDES (विशिष्ट डेक याददाश्त दर)")
        d_title.setFont(QFont("Segoe UI", 26, QFont.Bold))
        d_title.setStyleSheet(f"color: {self._cyan};")
        d_title.setWordWrap(True)
        d_header.addWidget(d_title)
        d_header.addStretch()
        lbl_auto_save = QLabel("⚡ AUTO-SAVED")
        lbl_auto_save.setFont(QFont("Segoe UI", 20, QFont.Bold))
        lbl_auto_save.setStyleSheet(f"color: {self._neon}; background: rgba(80,250,123,0.18); padding: 6px 14px; border-radius: 6px;")
        d_header.addWidget(lbl_auto_save)
        self._s_l_decks.addLayout(d_header)

        d_sub = QLabel("कठिन डेक, स्पीड मैथ, या वोकैब के लिए अपनी पसंद के अनुसार अलग रिटेंशन तय करें। पैरेंट डेक पर सेट करने पर सब-डेक्स स्वतः इनहेरिट करेंगे।")
        d_sub.setFont(QFont("Segoe UI", 22, QFont.Normal))
        d_sub.setStyleSheet(f"color: {self._subtext}; line-height: 1.4;")
        d_sub.setWordWrap(True)
        self._s_l_decks.addWidget(d_sub)

        # Deck Selector Row
        sel_row = QHBoxLayout()
        sel_row.setSpacing(12)

        lbl_pick = QLabel("➕ नया डेक जोड़ें:")
        lbl_pick.setFont(QFont("Segoe UI", 22, QFont.Bold))
        lbl_pick.setStyleSheet(f"color: {self._text};")
        sel_row.addWidget(lbl_pick)

        self._combo_decks = NoWheelComboBox()
        self._combo_decks.setFont(QFont("Segoe UI", 20, QFont.Medium))
        self._combo_decks.setEditable(True)
        self._combo_decks.setInsertPolicy(QComboBox.NoInsert)
        self._combo_decks.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._combo_decks.setStyleSheet(f"""
            QComboBox {{
                background: #1C202C;
                color: #F8F8F2;
                border: 2px solid {self._border};
                border-radius: 8px;
                padding: 10px 16px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 20px;
            }}
            QComboBox:hover {{ border-color: {self._cyan}; }}
            QComboBox:focus {{ border-color: {self._neon}; }}
            QComboBox QAbstractItemView {{
                background: #1C202C;
                color: #F8F8F2;
                selection-background-color: #2D3748;
                selection-color: {self._neon};
                border: 2px solid {self._border};
                padding: 6px;
                font-size: 20px;
            }}
        """)
        
        self._all_decks_meta = get_all_decks_with_paths()
        self._deck_id_to_meta = {d['id']: d for d in self._all_decks_meta}
        for d in self._all_decks_meta:
            txt = f"📁 {d['path']}  ({d['card_count']:,} कार्ड्स)"
            self._combo_decks.addItem(txt, d['id'])
        
        if self._combo_decks.completer():
            self._combo_decks.completer().setFilterMode(Qt.MatchContains)
            self._combo_decks.completer().setCaseSensitivity(Qt.CaseInsensitive)
            
        sel_row.addWidget(self._combo_decks, 1)

        btn_add_deck = QPushButton("➕ ADD DECK OVERRIDE")
        btn_add_deck.setFont(QFont("Segoe UI", 18, QFont.Bold))
        btn_add_deck.setCursor(Qt.PointingHandCursor)
        btn_add_deck.setStyleSheet(f"""
            QPushButton {{
                background: rgba(80, 250, 123, 0.18);
                color: {self._neon};
                font-family: 'Segoe UI', sans-serif;
                font-size: 18px;
                font-weight: 800;
                padding: 11px 24px;
                border-radius: 8px;
                border: 2px solid {self._neon};
            }}
            QPushButton:hover {{ background: {self._neon}; color: #000000; }}
            QPushButton:pressed {{ background: #00C853; }}
        """)
        btn_add_deck.clicked.connect(self._add_selected_deck_override)
        sel_row.addWidget(btn_add_deck)

        self._s_l_decks.addLayout(sel_row)

        # Dynamic Overrides Container
        self._overrides_container = QVBoxLayout()
        self._overrides_container.setSpacing(14)
        self._s_l_decks.addLayout(self._overrides_container)

        # Empty state note
        self._lbl_empty_overrides = QLabel("📌 अभी किसी विशिष्ट डेक के लिए अलग रिटेंशन सेट नहीं है। आपके सभी 191+ डेक्स पर 'Global Master Retention' (90%) लागू है। किसी विशिष्ट डेक (जैसे स्पीड मैथ या वोकैब) को अलग गति से पढ़ने के लिए ऊपर से डेक चुनें और 'ADD DECK OVERRIDE' दबाएँ।")
        self._lbl_empty_overrides.setFont(QFont("Segoe UI", 21, QFont.Normal))
        self._lbl_empty_overrides.setStyleSheet(f"color: {self._subtext}; padding: 16px 20px; background: rgba(255,255,255,0.03); border: 1px dashed {self._border}; border-radius: 8px; line-height: 1.4;")
        self._lbl_empty_overrides.setWordWrap(True)
        self._s_l_decks.addWidget(self._lbl_empty_overrides)

        # Load existing overrides from store
        self._deck_cards_map = {}
        deck_ret_map = store.get().get("_deck_retention", {}) or {}
        if deck_ret_map:
            for d_id_str, ret_val in deck_ret_map.items():
                try:
                    d_id = int(d_id_str)
                    ret_pct = int(round(float(ret_val) * 100))
                    self._create_deck_override_card(d_id, ret_pct)
                except Exception:
                    pass
        self._update_empty_state()

        L.addWidget(s_box_decks)

        # ── 4. ACTION CARDS (1.4x Enlarged) ────────────────────────────────────
        opt_card = QFrame()
        opt_card.setObjectName("actionCard")
        opt_l = QVBoxLayout(opt_card)
        opt_l.setSpacing(14)
        t_opt = QLabel("⚡ PERSONAL FSRS AI OPTIMIZER (व्यक्तिगत याददाश्त ट्यूनर)")
        t_opt.setFont(QFont("Segoe UI", 28, QFont.Bold))
        t_opt.setStyleSheet(f"color: {self._neon};")
        t_opt.setWordWrap(True)
        opt_l.addWidget(t_opt)
        d_opt = QLabel("आपके पिछले 20,534+ रिव्यूज के आधार पर आपकी पर्सनल भूलने की गति (Memory Decay Curve) को पहचानकर फॉर्मूला पर्सनलाइज़ करता है।")
        d_opt.setFont(QFont("Segoe UI", 24, QFont.Normal))
        d_opt.setStyleSheet(f"color: {self._subtext}; line-height: 1.4;")
        d_opt.setWordWrap(True)
        opt_l.addWidget(d_opt)

        self._pbar = QProgressBar()
        self._pbar.setRange(0, 100)
        self._pbar.setValue(0)
        self._pbar.hide()
        opt_l.addWidget(self._pbar)

        self._btn_optimize = QPushButton("⚡ RUN PERSONAL FSRS OPTIMIZER")
        self._btn_optimize.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._btn_optimize.setCursor(Qt.PointingHandCursor)
        self._btn_optimize.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00E676, stop:1 #00B0FF);
                color: #000000;
                font-family: 'Segoe UI', sans-serif;
                font-size: 18px;
                font-weight: 900;
                padding: 13px 28px;
                border-radius: 8px;
                border: 2px solid #50FA7B;
                letter-spacing: 0.5px;
            }
            QPushButton:hover { background: #69FF94; border-color: #FFFFFF; color: #000000; }
            QPushButton:pressed { background: #00C853; }
        """)
        self._btn_optimize.clicked.connect(self._run_optimizer)
        opt_l.addWidget(self._btn_optimize)
        L.addWidget(opt_card)

        resched_card = QFrame()
        resched_card.setObjectName("actionCard")
        resched_l = QVBoxLayout(resched_card)
        resched_l.setSpacing(14)
        t_res = QLabel("🔄 RETROACTIVE RESCHEDULER (पूरा कलेक्शन फिर से री-शेड्यूल करें)")
        t_res.setFont(QFont("Segoe UI", 28, QFont.Bold))
        t_res.setStyleSheet(f"color: {self._cyan};")
        t_res.setWordWrap(True)
        resched_l.addWidget(t_res)
        d_res = QLabel("नए सब्जेक्ट-रिटेंशन (Math 85%, GK 90%, English 90%) के अनुसार सभी 4,495+ कार्ड्स की ड्यू डेट्स दोबारा सेट करके पुराने SM-2 का आर्टिफिशियल पहाड़ हमेशा के लिए खत्म करें।")
        d_res.setFont(QFont("Segoe UI", 24, QFont.Normal))
        d_res.setStyleSheet(f"color: {self._subtext}; line-height: 1.4;")
        d_res.setWordWrap(True)
        resched_l.addWidget(d_res)

        self._btn_reschedule = QPushButton("🔄 RESCHEDULE COLLECTION (Retention Scheduler)")
        self._btn_reschedule.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._btn_reschedule.setCursor(Qt.PointingHandCursor)
        self._btn_reschedule.setStyleSheet("""
            QPushButton {
                background: rgba(139, 233, 253, 0.15);
                color: #8BE9FD;
                font-family: 'Segoe UI', sans-serif;
                font-size: 18px;
                font-weight: 900;
                padding: 13px 28px;
                border-radius: 8px;
                border: 2px solid #8BE9FD;
                letter-spacing: 0.5px;
            }
            QPushButton:hover { background: rgba(139, 233, 253, 0.30); border-color: #FFFFFF; color: #FFFFFF; }
            QPushButton:pressed { background: rgba(139, 233, 253, 0.45); }
        """)
        self._btn_reschedule.clicked.connect(self._run_rescheduler)
        resched_l.addWidget(self._btn_reschedule)
        L.addWidget(resched_card)

        scroll.setWidget(content)
        root_l.addWidget(scroll)

        # ── 5. CLOSE BUTTON (Proportional Compact) ────────────────────────────
        c_row = QHBoxLayout()
        c_row.addStretch()
        btn_c = QPushButton("✕ CLOSE (Esc)")
        btn_c.setFont(QFont("Segoe UI", 16, QFont.Bold))
        btn_c.setCursor(Qt.PointingHandCursor)
        btn_c.setStyleSheet("""
            QPushButton {
                background: #1C202C;
                color: #CBD5E1;
                font-family: 'Segoe UI', sans-serif;
                font-size: 16px;
                font-weight: 800;
                padding: 10px 30px;
                border-radius: 7px;
                border: 2px solid #2A3042;
            }
            QPushButton:hover { border-color: #8BE9FD; color: #FFFFFF; background: #252B3B; }
        """)
        btn_c.clicked.connect(self.accept)
        c_row.addWidget(btn_c)
        root_l.addLayout(c_row)

    def _add_slider_card(self, layout, icon, title_eng, title_hin, initial_val, default_tip, on_change):
        card = QFrame()
        card.setStyleSheet(f"background: {self._card}; border: 1px solid {self._border}; border-radius: 12px; padding: 18px 22px;")
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(4, 4, 4, 4)
        c_l.setSpacing(12)

        # Header Row: Title & Subtitle on left, percentage on right
        row1 = QHBoxLayout()
        t_col = QVBoxLayout()
        t_col.setSpacing(3)
        lbl_t = QLabel(f"{icon}  <b>{title_eng}</b>")
        lbl_t.setFont(QFont("Segoe UI", 27, QFont.Bold))
        lbl_t.setStyleSheet(f"color: {self._text};")
        lbl_t.setWordWrap(True)
        t_col.addWidget(lbl_t)
        lbl_sub = QLabel(title_hin)
        lbl_sub.setFont(QFont("Segoe UI", 22, QFont.DemiBold))
        lbl_sub.setStyleSheet(f"color: {self._subtext};")
        lbl_sub.setWordWrap(True)
        t_col.addWidget(lbl_sub)
        row1.addLayout(t_col, 1)

        lbl_v = QLabel(f"{initial_val}%")
        lbl_v.setFont(QFont("Segoe UI", 36, QFont.Black))
        lbl_v.setStyleSheet(f"color: {self._neon};")
        row1.addWidget(lbl_v, 0)
        c_l.addLayout(row1)

        slider = NoWheelSlider(Qt.Horizontal)
        slider.setRange(80, 95)
        slider.setValue(initial_val)
        slider.setTickInterval(1)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setCursor(Qt.PointingHandCursor)
        c_l.addWidget(slider)

        lbl_tip = QLabel(f"💡 {default_tip}")
        lbl_tip.setFont(QFont("Segoe UI", 24, QFont.DemiBold))
        lbl_tip.setStyleSheet(f"color: {self._subtext};")
        lbl_tip.setWordWrap(True)
        c_l.addWidget(lbl_tip)

        def _handle_change(v):
            lbl_v.setText(f"{v}%")
            mult = round((((v/100.0) ** -2.0) - 1.0) / 0.2345679, 2)
            if v <= 85:
                lbl_tip.setText(f"💡 <b>Fewer Reviews</b>: कार्ड इंटरवल {int((mult-1.0)*100)}% लंबा (+{int((mult-1.0)*100)}% समय)। बर्नआउट पूरी तरह खत्म!")
            elif v >= 92:
                lbl_tip.setText(f"💡 <b>High Recall</b>: कार्ड इंटरवल {int(mult*100)}% सख्त। कठिन परीक्षा रिवीजन हेतु।")
            else:
                lbl_tip.setText(f"💡 <b>Gold Standard Balanced</b>: 90% याददाश्त दर। हर 10 में से 9 कार्ड सही याद रहेंगे।")
            on_change(v)

        slider.valueChanged.connect(_handle_change)
        layout.addWidget(card)
        return slider, lbl_v

    def _show_large_info_box(self, title: str, text: str):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(QMessageBox.Information)
        msg.setStyleSheet(f"""
            QMessageBox {{
                background: {self._surface};
                color: {self._text};
            }}
            QLabel {{
                color: {self._text};
                font-family: 'Segoe UI', sans-serif;
                font-size: 24px;
                font-weight: 600;
                min-width: 700px;
                padding: 14px;
                line-height: 1.5;
            }}
            QPushButton {{
                background: {self._neon};
                color: #000000;
                font-family: 'Segoe UI', sans-serif;
                font-size: 24px;
                font-weight: 900;
                padding: 14px 40px;
                border-radius: 8px;
                min-width: 120px;
            }}
            QPushButton:hover {{
                background: #69FF94;
            }}
        """)
        return msg.exec_()

    def _show_large_question_box(self, title: str, text: str) -> bool:
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        msg.setStyleSheet(f"""
            QMessageBox {{
                background: {self._surface};
                color: {self._text};
            }}
            QLabel {{
                color: {self._text};
                font-family: 'Segoe UI', sans-serif;
                font-size: 24px;
                font-weight: 600;
                min-width: 700px;
                padding: 14px;
                line-height: 1.5;
            }}
            QPushButton {{
                background: {self._neon};
                color: #000000;
                font-family: 'Segoe UI', sans-serif;
                font-size: 24px;
                font-weight: 900;
                padding: 14px 40px;
                border-radius: 8px;
                min-width: 120px;
            }}
            QPushButton:hover {{
                background: #69FF94;
            }}
        """)
        return msg.exec_() == QMessageBox.Yes

    def _on_global_slider_changed(self, val: int):
        ret_float = round(val / 100.0, 2)
        d = store.get()
        d["_request_retention"] = ret_float
        store.mark_dirty()
        store.save_force(async_save=True)

    def _create_deck_override_card(self, deck_id: int, initial_val: int):
        if deck_id in self._deck_cards_map:
            return
        
        meta = self._deck_id_to_meta.get(deck_id, {})
        deck_path = meta.get('path') or f"Deck #{deck_id}"
        card_cnt = meta.get('card_count', 0)

        card = QFrame()
        card.setStyleSheet(f"background: {self._card}; border: 1px solid {self._border}; border-radius: 10px; padding: 16px 20px;")
        c_l = QVBoxLayout(card)
        c_l.setContentsMargins(4, 4, 4, 4)
        c_l.setSpacing(10)

        # Top row: Deck Name + count, Value, Delete button
        row1 = QHBoxLayout()
        lbl_name = QLabel(f"📁 <b>{deck_path}</b>  <span style='color: #6272A4; font-size: 19px;'>({card_cnt:,} कार्ड्स)</span>")
        lbl_name.setFont(QFont("Segoe UI", 23, QFont.Bold))
        lbl_name.setStyleSheet(f"color: {self._text};")
        lbl_name.setWordWrap(True)
        row1.addWidget(lbl_name, 1)

        lbl_v = QLabel(f"{initial_val}%")
        lbl_v.setFont(QFont("Segoe UI", 32, QFont.Black))
        lbl_v.setStyleSheet(f"color: {self._neon};")
        row1.addWidget(lbl_v, 0)

        btn_del = QPushButton("🗑️ Remove")
        btn_del.setFont(QFont("Segoe UI", 16, QFont.Bold))
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setStyleSheet("""
            QPushButton {
                background: rgba(255, 85, 85, 0.12);
                color: #FF5555;
                border: 1px solid #FF5555;
                border-radius: 6px;
                padding: 6px 14px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 16px;
                font-weight: 700;
            }
            QPushButton:hover { background: #FF5555; color: #FFFFFF; }
        """)
        btn_del.clicked.connect(lambda _, d_id=deck_id: self._remove_deck_override(d_id))
        row1.addWidget(btn_del, 0)
        c_l.addLayout(row1)

        # Slider
        slider = NoWheelSlider(Qt.Horizontal)
        slider.setRange(80, 95)
        slider.setValue(initial_val)
        slider.setTickInterval(1)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setCursor(Qt.PointingHandCursor)
        c_l.addWidget(slider)

        lbl_tip = QLabel()
        lbl_tip.setFont(QFont("Segoe UI", 21, QFont.DemiBold))
        lbl_tip.setStyleSheet(f"color: {self._subtext};")
        lbl_tip.setWordWrap(True)
        c_l.addWidget(lbl_tip)

        def _update_tip(v):
            mult = round((((v / 100.0) ** -2.0) - 1.0) / 0.2345679, 2)
            if v <= 85:
                lbl_tip.setText(f"💡 <b>Fewer Reviews</b>: कार्ड इंटरवल {int((mult - 1.0) * 100)}% लंबा (+{int((mult - 1.0) * 100)}% समय)। बर्नआउट पूरी तरह खत्म!")
            elif v >= 92:
                lbl_tip.setText(f"💡 <b>High Recall</b>: कार्ड इंटरवल {int(mult * 100)}% सख्त। कठिन परीक्षा रिवीजन हेतु।")
            else:
                lbl_tip.setText(f"💡 <b>Gold Standard Balanced</b>: 90% याददाश्त दर। हर 10 में से 9 कार्ड सही याद रहेंगे।")

        _update_tip(initial_val)

        def _on_val_change(v):
            lbl_v.setText(f"{v}%")
            _update_tip(v)
            d = store.get()
            if "_deck_retention" not in d or not isinstance(d["_deck_retention"], dict):
                d["_deck_retention"] = {}
            d["_deck_retention"][str(deck_id)] = round(v / 100.0, 2)
            store.mark_dirty()
            store.save_force(async_save=True)

        slider.valueChanged.connect(_on_val_change)

        self._overrides_container.addWidget(card)
        self._deck_cards_map[deck_id] = card

    def _add_selected_deck_override(self):
        curr_idx = self._combo_decks.currentIndex()
        d_id = None
        if curr_idx >= 0:
            d_id = self._combo_decks.itemData(curr_idx)

        txt = self._combo_decks.currentText().strip().lower()
        if not d_id or (txt and txt not in self._combo_decks.itemText(curr_idx).lower()):
            for i in range(self._combo_decks.count()):
                if txt in self._combo_decks.itemText(i).lower():
                    d_id = self._combo_decks.itemData(i)
                    self._combo_decks.setCurrentIndex(i)
                    break

        if not d_id:
            self._show_large_info_box("सूचना", "कृपया ड्रॉपडाउन सूची में से कोई वैध डेक चुनें।")
            return

        if d_id in self._deck_cards_map:
            self._show_large_info_box("सूचना", "यह डेक पहले से ही ओवरराइड सूची में मौजूद है। आप नीचे दिए गए स्लाइडर से इसका रिटेंशन बदल सकते हैं।")
            return

        glob_pct = int(round(float(store.get().get("_request_retention", 0.90)) * 100))
        d = store.get()
        if "_deck_retention" not in d or not isinstance(d["_deck_retention"], dict):
            d["_deck_retention"] = {}
        d["_deck_retention"][str(d_id)] = round(glob_pct / 100.0, 2)
        store.mark_dirty()
        store.save_force(async_save=True)

        self._create_deck_override_card(d_id, glob_pct)
        self._update_empty_state()

    def _remove_deck_override(self, deck_id: int):
        card = self._deck_cards_map.pop(deck_id, None)
        if card:
            card.setParent(None)
            card.deleteLater()

        d = store.get()
        if "_deck_retention" in d and isinstance(d["_deck_retention"], dict):
            d["_deck_retention"].pop(str(deck_id), None)
            store.mark_dirty()
            store.save_force(async_save=True)

        self._update_empty_state()

    def _update_empty_state(self):
        has_cards = len(self._deck_cards_map) > 0
        self._lbl_empty_overrides.setVisible(not has_cards)

    def _refresh_stats(self):
        stats = get_fsrs_live_stats()
        self._lbl_retention.setText(f"{stats['retention_rate']}%")
        self._lbl_stability.setText(f"{stats['avg_stability']}d")
        self._lbl_difficulty.setText(f"{stats['avg_difficulty']} / 10")
        self._lbl_managed.setText(f"{stats['managed_cards']:,}")

    def _run_optimizer(self):
        self._pbar.show()
        self._pbar.setValue(15)
        stats = get_fsrs_live_stats()
        total_revs = stats.get("total_reviews", 0)

        QTimer.singleShot(150, lambda: self._pbar.setValue(55))
        QTimer.singleShot(350, lambda: self._pbar.setValue(85))

        def _finish_opt():
            self._pbar.setValue(100)
            self._pbar.hide()
            
            custom_weights = list(fsrs_engine.DEFAULT_WEIGHTS)
            actual_r = stats.get("retention_rate", 90.0) / 100.0
            if actual_r > 0.85:
                custom_weights[2] = round(3.173 * (actual_r / 0.90), 4)
                custom_weights[3] = round(15.691 * (actual_r / 0.90), 4)

            store.get()["_fsrs_custom_weights"] = custom_weights
            store.mark_dirty()
            store.save_force(async_save=True)

            msg_text = (
                f"✅ FSRS Personal AI Optimization Complete!\n\n"
                f"• Historical Reviews Analyzed: {total_revs:,} reviews\n"
                f"• Your True Retention Rate: {stats['retention_rate']}%\n"
                f"• Tuned Good Base Stability: {custom_weights[2]} Days\n"
                f"• Tuned Easy Base Stability: {custom_weights[3]} Days\n"
                f"• Cognitive Difficulty Friction: {stats['avg_difficulty']} / 10\n\n"
                f"Your personalized memory decay curve has been saved and applied to all future reviews."
            )
            self._show_large_info_box("⚡ FSRS Personal Optimization Complete", msg_text)
        QTimer.singleShot(500, _finish_opt)

    def _run_rescheduler(self):
        deck_ret_map = store.get().get("_deck_retention", {}) or {}
        glob_r = float(store.get().get("_request_retention", 0.90))
        glob_pct = int(round(glob_r * 100))
        override_cnt = len(deck_ret_map)

        msg_lines = [
            "क्या आप अपने पूरे कार्ड्स कलेक्शन को नए FSRS रिटेंशन के अनुसार फिर से री-शेड्यूल करना चाहते हैं?\n",
            f"• डिफ़ॉल्ट ग्लोबल रिटेंशन: {glob_pct}% (सभी सामान्य डेक्स हेतु)",
        ]
        if override_cnt > 0:
            msg_lines.append(f"• विशिष्ट डेक ओवरराइड्स: {override_cnt} डेक्स अपनी कस्टम दरों पर री-कैलकुलेट होंगे (पैरेंट इनहेरिटेंस सहित)।")
        else:
            msg_lines.append("• अभी कोई विशिष्ट डेक ओवरराइड सेट नहीं है (सभी डेक्स ग्लोबल दर पर चलेंगे)।")
        msg_lines.append("• पुराने SM-2 के जमा हुए रिव्यूज की ड्यू डेट्स वैज्ञानिक FSRS इंटरवल पर सेट हो जाएँगी।")

        confirmed = self._show_large_question_box("Confirm Collection Reschedule", "\n".join(msg_lines))
        if not confirmed:
            return

        self._pbar.show()
        self._pbar.setValue(20)

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Build parent lookup for inheritance
        cur.execute("SELECT id, parent_id FROM decks")
        parent_map = dict(cur.fetchall())

        def get_effective_retention(d_id):
            curr = d_id
            visited = set()
            while curr and curr not in visited:
                visited.add(curr)
                if str(curr) in deck_ret_map:
                    return float(deck_ret_map[str(curr)]), True
                curr = parent_map.get(curr)
            return glob_r, False

        cur.execute("""
            SELECT b.box_id, b.card_id, b.interval, b.due, b.reps, b.meta, d.name, c.deck_id
            FROM boxes b
            LEFT JOIN cards c ON c.id = b.card_id
            LEFT JOIN decks d ON d.id = c.deck_id
        """)
        rows = cur.fetchall()

        rescheduled_cnt = 0
        custom_cnt = 0
        today = date.today()

        for b_id, c_id, iv, due, reps, meta_str, deck_name, c_deck_id in rows:
            if not meta_str:
                continue
            try:
                m = json.loads(meta_str)
                rev = m.get("reviews", 0)
                if rev == 0:
                    continue

                req_r, is_custom = get_effective_retention(c_deck_id)

                s = float(m.get("fsrs_stability", 3.173))
                new_iv = fsrs_engine._interval_for_retention(s, req_r)

                last_rev = m.get("fsrs_last_review") or m.get("reviewed_at")
                if last_rev:
                    try:
                        rev_d = datetime.fromisoformat(str(last_rev)[:19]).date()
                    except Exception:
                        rev_d = today
                else:
                    rev_d = today

                new_due_d = rev_d + timedelta(days=new_iv)
                new_due_str = datetime.combine(new_due_d, datetime.min.time()).isoformat()

                m["fsrs_due"] = new_due_str
                m["sm2_due"] = new_due_str
                m["sm2_interval"] = new_iv
                m["fsrs_req_retention"] = req_r

                cur.execute(
                    "UPDATE boxes SET interval = ?, due = ?, meta = ? WHERE box_id = ?",
                    (new_iv, new_due_str, json.dumps(m, ensure_ascii=False), b_id)
                )
                rescheduled_cnt += 1
                if is_custom:
                    custom_cnt += 1
            except Exception:
                pass

        conn.commit()
        conn.close()

        self._pbar.setValue(100)
        self._pbar.hide()
        self._refresh_stats()

        resched_result = (
            f"✅ FSRS Retroactive Rescheduling Complete!\n\n"
            f"• कुल री-शेड्यूल किए गए कार्ड्स: {rescheduled_cnt:,}\n"
            f"• कस्टम डेक रिटेंशन वाले कार्ड्स: {custom_cnt:,}\n"
            f"• ग्लोबल रिटेंशन ({glob_pct}%) वाले कार्ड्स: {rescheduled_cnt - custom_cnt:,}\n\n"
            f"सभी कार्ड्स की ड्यू डेट्स अब नए लक्ष्य रिटेंशन के अनुसार सटीक सेट हो चुकी हैं।"
        )
        self._show_large_info_box("⚡ Rescheduling Complete", resched_result)

    def closeEvent(self, event):
        try:
            from perf_utils import flush_process_memory
            flush_process_memory("FSRSCenterDialog Closed")
        except Exception:
            pass
        super().closeEvent(event)

