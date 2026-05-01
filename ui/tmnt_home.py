"""
tmnt_home.py — TMNT "Dojo Dashboard" HomeScreen layout
=======================================================
Pixel-faithful to test2.html skeleton.
Data pulled from the same data_manager / sm2_engine layer
that the dojo/classic themes use.

Layout (matches HTML):
  ┌─ TopBar (header) ──────────────────────────────────────────────┐
  │ Logo | Nav btns | Font btns | BGM | Mentor card               │
  ├─ Left Sidebar ─┬─ Main Content ─────────┬─ Right Sidebar ─────┤
  │  Dojo Cave     │  Deck title + stats    │  Banga Lab          │
  │  Search        │  3 stat cards          │  System Status      │
  │  Deck list     │  Mission banner        │  Dojo Resources     │
  │  + NEW DOJO    │  Card list area        │  Fuel Up tip        │
  │  + SUB         │  Edit / Delete bar     │                     │
  ├─ Footer ───────┴────────────────────────┴─────────────────────┤
  │  SM-2 Active | PDF Engine status                              │
  └────────────────────────────────────────────────────────────────┘
"""

import os, math
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea, QSizePolicy,
    QListWidget, QListWidgetItem, QAbstractItemView, QMessageBox,
    QDialog, QStackedWidget, QApplication
)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPixmap, QPainterPath,
    QLinearGradient
)

from sm2_engine import sm2_init, is_due_today, sm2_days_left
from data_manager import find_deck_by_id, next_deck_id, store
from pdf_engine import PDF_SUPPORT

# ── TMNT Palette ─────────────────────────────────────────────────────────────
T_BG       = "#0b0c10"
T_PANEL    = "#1f2833"
T_CARD     = "#262933"
T_GREEN    = "#45a247"
T_NEON     = "#66fcf1"
T_TEXT     = "#c5c6c7"
T_SUBTEXT  = "#6b7280"
T_RED      = "#ff4d4d"
T_PURPLE   = "#b088f9"
T_BORDER   = "#333b4d"
T_MONO     = "'Roboto Mono', 'Courier New', monospace"
T_PIXEL    = "'Press Start 2P', monospace"

MENTOR_QUOTES = [
    ('"FOCUS. TRAIN. MASTER."',   "— DONATELLO"),
    ('"KNOWLEDGE IS THE WEAPON."',"— SPLINTER"),
    ('"COWABUNGA, DUDE!"',        "— MICHELANGELO"),
    ('"NEVER STOP LEARNING."',    "— LEONARDO"),
    ('"SCIENCE NEVER FAILS."',    "— DONATELLO"),
]

# ── Helper: pixel-font label ─────────────────────────────────────────────────
def _px_lbl(text, color=T_NEON, size=10, weight="900"):
    l = QLabel(text)
    l.setStyleSheet(
        f"font-family: {T_PIXEL}; font-size: {size}px; font-weight: {weight}; "
        f"color: {color}; background: transparent; border: none;"
    )
    return l

def _mono_lbl(text, color=T_TEXT, size=11, weight="normal"):
    l = QLabel(text)
    l.setStyleSheet(
        f"font-family: {T_MONO}; font-size: {size}px; font-weight: {weight}; "
        f"color: {color}; background: transparent; border: none;"
    )
    return l

def _sep_line():
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {T_BORDER}; border: none;")
    return f


# ══════════════════════════════════════════════════════════════════════════════
#  STAT CARD  (3 across top of main area)
# ══════════════════════════════════════════════════════════════════════════════
class TMNTStatCard(QFrame):
    def __init__(self, title, subtitle, color, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_stat_card")
        self._color = color
        self._setup(title, subtitle, color)

    def _setup(self, title, subtitle, color):
        self.setStyleSheet(f"""
            QFrame#tmnt_stat_card {{
                background: {T_CARD};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
            }}
            QFrame#tmnt_stat_card:hover {{ border-color: {color}; }}
            QLabel {{ background: transparent; border: none; }}
        """)
        l = QHBoxLayout(self)
        l.setContentsMargins(16, 12, 16, 12)
        l.setSpacing(16)

        # Glow blob (painted) + icon
        self._icon = QLabel("★")
        self._icon.setStyleSheet(f"color: {color}; font-size: 28px; background: transparent; border: none;")
        l.addWidget(self._icon)

        txt = QVBoxLayout()
        txt.setSpacing(2)
        self.val_lbl = QLabel("0")
        self.val_lbl.setStyleSheet(
            f"color: {color}; font-size: 32px; font-weight: 900; "
            f"font-family: {T_PIXEL}; background: transparent; border: none;"
        )
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(
            f"color: {T_TEXT}; font-size: 9px; font-weight: 900; "
            f"font-family: {T_MONO}; letter-spacing: 1px; background: transparent; border: none;"
        )
        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 9px; "
            f"font-family: {T_MONO}; background: transparent; border: none;"
        )
        txt.addWidget(self.val_lbl)
        txt.addWidget(t_lbl)
        txt.addWidget(s_lbl)
        l.addLayout(txt)
        l.addStretch()

    def set_value(self, v):
        self.val_lbl.setText(str(v))


# ══════════════════════════════════════════════════════════════════════════════
#  MISSION BANNER
# ══════════════════════════════════════════════════════════════════════════════
class TMNTMissionBanner(QFrame):
    train_clicked = pyqtSignal()
    selected_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_banner")
        self.setStyleSheet(f"""
            QFrame#tmnt_banner {{
                background: {T_CARD};
                border: 1px solid {T_BORDER};
                border-left: 3px solid {T_PURPLE};
                border-radius: 4px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        l = QHBoxLayout(self)
        l.setContentsMargins(20, 16, 20, 16)
        l.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(6)
        title = QLabel("⚔  TRAINING MISSION")
        title.setStyleSheet(
            f"color: {T_PURPLE}; font-size: 11px; font-weight: 900; "
            f"font-family: {T_PIXEL}; letter-spacing: 1px; background: transparent; border: none;"
        )
        desc = QLabel("Continue your training and defeat the due cards!")
        desc.setStyleSheet(f"color: {T_TEXT}; font-size: 12px; font-family: {T_MONO}; background: transparent; border: none;")
        self.quote = QLabel("> Cowabunga! 🐢_")
        self.quote.setStyleSheet(
            f"color: {T_GREEN}; font-size: 11px; font-weight: bold; "
            f"font-family: {T_MONO}; background: transparent; border: none;"
        )
        left.addWidget(title)
        left.addWidget(desc)
        left.addWidget(self.quote)
        left.addStretch()
        l.addLayout(left)
        l.addStretch()

        right = QVBoxLayout()
        right.setSpacing(8)
        right.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self.btn_train = QPushButton("▶  START TRAINING\nREVIEW DUE SCROLLS")
        self.btn_train.setStyleSheet(f"""
            QPushButton {{
                background: {T_GREEN};
                color: {T_BG};
                border: none;
                border-radius: 2px;
                font-weight: 900;
                font-family: {T_PIXEL};
                font-size: 10px;
                min-height: 52px;
                padding: 0px 24px;
                text-align: center;
            }}
            QPushButton:hover {{ background: {T_NEON}; color: {T_BG}; }}
        """)
        self.btn_train.clicked.connect(self.train_clicked)

        self.btn_selected = QPushButton("◎  TRAIN SELECTED SCROLL")
        self.btn_selected.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T_GREEN};
                border: 1px solid {T_GREEN};
                border-radius: 2px;
                font-size: 10px;
                font-weight: 700;
                font-family: {T_MONO};
                letter-spacing: 1px;
                min-height: 36px;
                padding: 0px 16px;
            }}
            QPushButton:hover {{ background: rgba(69,162,71,0.12); }}
        """)
        self.btn_selected.clicked.connect(self.selected_clicked)

        right.addWidget(self.btn_train)
        right.addWidget(self.btn_selected)
        l.addLayout(right)

        # Animated glow on train button
        self._glow_step = 0
        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._tick_glow)
        self._glow_timer.start(50)

    def _tick_glow(self):
        self._glow_step += 1
        t = (math.sin(self._glow_step * math.pi / 20.0) + 1.0) / 2.0
        r = int(69  + (102 - 69)  * t)
        g = int(162 + (252 - 162) * t)
        b = int(71  + (241 - 71)  * t)
        col = f"#{r:02X}{g:02X}{b:02X}"
        self.btn_train.setStyleSheet(f"""
            QPushButton {{
                background: {col};
                color: {T_BG};
                border: none;
                border-radius: 2px;
                font-weight: 900;
                font-family: {T_PIXEL};
                font-size: 10px;
                min-height: 52px;
                padding: 0px 24px;
                text-align: center;
            }}
            QPushButton:hover {{ background: {T_NEON}; color: {T_BG}; }}
        """)


# ══════════════════════════════════════════════════════════════════════════════
#  RIGHT SIDEBAR — Banga Lab
# ══════════════════════════════════════════════════════════════════════════════
class TMNTBangaLab(QFrame):
    clear_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banga_lab")
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame#banga_lab {{
                background: {T_BG};
                border-left: 1px solid {T_BORDER};
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_timer.start(4000)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 20, 16, 20)
        root.setSpacing(20)

        # ── Header ──
        hdr = QHBoxLayout()
        icon = QLabel("🧪")
        icon.setStyleSheet("font-size: 16px; border: none;")
        title = QLabel("Banga Lab")
        title.setStyleSheet(
            f"color: {T_GREEN}; font-size: 12px; font-weight: 900; "
            f"font-family: {T_PIXEL}; letter-spacing: 1px;"
        )
        hdr.addWidget(icon)
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        # ── System Status ──
        sys_lbl = QLabel("— SYSTEM STATUS —")
        sys_lbl.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 9px; font-weight: 900; "
            f"font-family: {T_MONO}; letter-spacing: 2px; padding: 4px 0px;"
        )
        sys_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(sys_lbl)

        def _stat_row(lbl_text, val_text, val_color, dot=False):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 4, 0, 4)
            lb = QLabel(lbl_text)
            lb.setStyleSheet(f"color: {T_SUBTEXT}; font-size: 10px; font-family: {T_MONO}; font-weight: bold;")
            vl = QLabel(("● " if dot else "") + val_text)
            vl.setStyleSheet(f"color: {val_color}; font-size: 10px; font-weight: bold; font-family: {T_MONO};")
            hl.addWidget(lb)
            hl.addStretch()
            hl.addWidget(vl)
            return w

        root.addWidget(_stat_row("ALGORITHM", "SM-2",    T_PURPLE))
        root.addWidget(_sep_line())
        root.addWidget(_stat_row("SCHEDULER", "ACTIVE",  T_GREEN, dot=True))
        root.addWidget(_sep_line())
        pdf_val = "PyMuPDF" if PDF_SUPPORT else "MISSING"
        pdf_col = T_PURPLE if PDF_SUPPORT else T_RED
        root.addWidget(_stat_row("PDF ENGINE", pdf_val,  pdf_col))
        root.addWidget(_sep_line())
        root.addWidget(_stat_row("OCCLUSION",  "ACTIVE", T_GREEN, dot=True))

        # ── Dojo Resources ──
        res_lbl = QLabel("— DOJO RESOURCES —")
        res_lbl.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 9px; font-weight: 900; "
            f"font-family: {T_MONO}; letter-spacing: 2px; padding: 4px 0px;"
        )
        res_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(res_lbl)

        def _res_row(name, color):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 2, 0, 2)
            vl.setSpacing(3)
            hl = QHBoxLayout()
            hl.setContentsMargins(0, 0, 0, 0)
            lb = QLabel(name)
            lb.setStyleSheet(f"color: {T_SUBTEXT}; font-size: 10px; font-family: {T_MONO}; font-weight: bold;")
            val = QLabel("0.0 MB")
            val.setStyleSheet(f"color: {T_TEXT}; font-size: 10px; font-family: {T_MONO}; font-weight: bold;")
            hl.addWidget(lb); hl.addStretch(); hl.addWidget(val)
            vl.addLayout(hl)
            bg = QFrame()
            bg.setFixedHeight(4)
            bg.setStyleSheet(f"background: {T_PANEL}; border-radius: 2px; border: none;")
            bl = QHBoxLayout(bg)
            bl.setContentsMargins(0,0,0,0)
            bl.setAlignment(Qt.AlignLeft)
            bar = QFrame()
            bar.setFixedHeight(4)
            bar.setFixedWidth(0)
            bar.setStyleSheet(f"background: {color}; border-radius: 2px; border: none;")
            bl.addWidget(bar)
            vl.addWidget(bg)
            return w, val, bar, bg

        self.w_mem,   self.lbl_mem,   self.bar_mem,   self.bg_mem   = _res_row("MEMORY", T_PURPLE)
        self.w_cache, self.lbl_cache, self.bar_cache, self.bg_cache = _res_row("CACHE",  T_GREEN)
        self.w_media, self.lbl_media, self.bar_media, self.bg_media = _res_row("MEDIA",  T_RED)
        self.w_tot,   self.lbl_tot,   self.bar_tot,   self.bg_tot   = _res_row("TOTAL",  T_PURPLE)

        for row in (self.w_mem, self.w_cache, self.w_media, self.w_tot):
            root.addWidget(row)

        root.addStretch()

        # ── Fuel Up ──
        fuel = QFrame()
        fuel.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: 1px solid {T_GREEN};
                border-radius: 4px;
                opacity: 0.85;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        fl = QHBoxLayout(fuel)
        fl.setContentsMargins(10, 10, 10, 10)
        fl.setSpacing(10)
        pizza = QLabel("🍕")
        pizza.setStyleSheet("font-size: 22px; border: none;")
        fl.addWidget(pizza)
        ftxt = QVBoxLayout()
        ftxt.setSpacing(3)
        fh = QLabel("FUEL UP, NINJA!")
        fh.setStyleSheet(f"color: {T_GREEN}; font-size: 9px; font-weight: 900; font-family: {T_PIXEL};")
        fd = QLabel("Take breaks.\nYour brain is\nnot a robot.")
        fd.setStyleSheet(f"color: {T_SUBTEXT}; font-size: 9px; font-family: {T_MONO};")
        ftxt.addWidget(fh); ftxt.addWidget(fd)
        fl.addLayout(ftxt)
        root.addWidget(fuel)

        # ── Clear Cache btn ──
        clr = QPushButton("🧹  Clear All Caches")
        clr.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: 10px;
                font-family: {T_MONO};
                padding: 6px;
            }}
            QPushButton:hover {{ color: {T_TEXT}; border-color: {T_GREEN}; }}
        """)
        clr.clicked.connect(self._clear_all)
        root.addWidget(clr)

    def refresh(self):
        try:
            from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY
            known = set()
            known.update(COMBINED_CACHE.all_cached_pdfs())
            known.update(PAGE_CACHE.all_cached_pdfs())
            known.update(MASK_REGISTRY.all_registered_pdfs())
            ram_b = disk_b = mask_b = 0
            for p in known:
                disk_b += COMBINED_CACHE.disk_bytes_for_pdf(p)
                ram_b  += PAGE_CACHE.ram_bytes_for_pdf(p)
                mask_b += MASK_REGISTRY.mask_bytes_for_pdf(p)
        except Exception:
            ram_b = disk_b = mask_b = 0

        tot_b  = ram_b + disk_b + mask_b
        to_mb  = lambda b: b / (1024**2)
        MAX_MB = 512.0

        def _w(mb):
            max_w = 188
            return int(min(mb / MAX_MB, 1.0) * max_w)

        self.lbl_mem.setText(f"{to_mb(ram_b):.1f} MB")
        self.lbl_cache.setText(f"{to_mb(disk_b):.1f} MB")
        self.lbl_media.setText(f"{to_mb(mask_b):.1f} MB")
        self.lbl_tot.setText(f"{to_mb(tot_b):.1f} MB")
        self.bar_mem.setFixedWidth(_w(to_mb(ram_b)))
        self.bar_cache.setFixedWidth(_w(to_mb(disk_b)))
        self.bar_media.setFixedWidth(_w(to_mb(mask_b)))
        self.bar_tot.setFixedWidth(_w(to_mb(tot_b)))

    def _clear_all(self):
        try:
            from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY
            COMBINED_CACHE.clear()
            PAGE_CACHE.clear_ram_only()
            MASK_REGISTRY._map.clear()
            for label in list(PIXMAP_REGISTRY._entries.keys()):
                PIXMAP_REGISTRY.unregister(label)
            self.refresh()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  LEFT SIDEBAR — Dojo Cave
# ══════════════════════════════════════════════════════════════════════════════
class TMNTSidebar(QFrame):
    deck_selected = pyqtSignal(object)   # emits deck dict
    new_deck      = pyqtSignal()
    new_sub       = pyqtSignal()

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._selected_deck = None
        self.setFixedWidth(260)
        self.setObjectName("tmnt_sidebar")
        self.setStyleSheet(f"""
            QFrame#tmnt_sidebar {{
                background: {T_BG};
                border-right: 1px solid {T_BORDER};
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ── Header ──
        hdr = QWidget()
        hdr.setStyleSheet(f"background: {T_BG}; border-bottom: 1px solid {T_BORDER};")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(16, 14, 16, 10)
        hl.setSpacing(10)

        title_row = QHBoxLayout()
        torii = QLabel("⛩")
        torii.setStyleSheet(f"color: {T_GREEN}; font-size: 18px;")
        title = QLabel("DOJO CAVE")
        title.setStyleSheet(
            f"color: {T_GREEN}; font-size: 11px; font-weight: 900; "
            f"font-family: {T_PIXEL}; letter-spacing: 2px;"
        )
        title_row.addWidget(torii)
        title_row.addWidget(title)
        title_row.addStretch()
        hl.addLayout(title_row)

        # Search box
        search_frame = QFrame()
        search_frame.setStyleSheet(
            f"QFrame {{ background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 3px; }}"
            f"QLabel {{ border: none; }}"
        )
        search_frame.setFixedHeight(32)
        sl = QHBoxLayout(search_frame)
        sl.setContentsMargins(8, 0, 8, 0)
        sl.setSpacing(6)
        search_icon = QLabel("⌕")
        search_icon.setStyleSheet(f"color: {T_SUBTEXT}; font-size: 14px; border: none;")
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Search scrolls...")
        self.search_in.setStyleSheet(
            f"background: transparent; border: none; color: {T_TEXT}; "
            f"font-family: {T_MONO}; font-size: 11px;"
        )
        self.search_in.textChanged.connect(self._on_search)
        kb_badge = QLabel("CTRL+K")
        kb_badge.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 9px; background: rgba(255,255,255,0.04); "
            f"border: 1px solid {T_BORDER}; border-radius: 2px; padding: 1px 3px;"
        )
        sl.addWidget(search_icon)
        sl.addWidget(self.search_in, stretch=1)
        sl.addWidget(kb_badge)
        hl.addWidget(search_frame)
        L.addWidget(hdr)

        # ── YOUR DOJOS label ──
        dojos_lbl = QLabel("— YOUR DOJOS —")
        dojos_lbl.setAlignment(Qt.AlignCenter)
        dojos_lbl.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 9px; font-weight: 900; "
            f"font-family: {T_MONO}; letter-spacing: 2px; "
            f"padding: 10px 0px 6px 0px; background: {T_BG};"
        )
        L.addWidget(dojos_lbl)

        # ── Deck list (custom paint) ──
        self._deck_list = _TMNTDeckList()
        self._deck_list.deck_selected.connect(self._on_deck_clicked)
        L.addWidget(self._deck_list, stretch=1)

        # ── Footer buttons ──
        foot = QWidget()
        foot.setStyleSheet(f"background: {T_BG}; border-top: 1px solid {T_BORDER};")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)

        def _foot_btn(text):
            b = QPushButton(text)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {T_GREEN};
                    border: 1px solid {T_GREEN};
                    border-radius: 2px;
                    font-size: 9px;
                    font-weight: 900;
                    font-family: {T_PIXEL};
                    padding: 6px 8px;
                }}
                QPushButton:hover {{ background: rgba(69,162,71,0.12); }}
            """)
            return b

        btn_new = _foot_btn("⊕ NEW")
        btn_sub = _foot_btn("⊕ SUB")
        btn_del = QPushButton("⚙")
        btn_del.setFixedSize(30, 30)
        btn_del.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: 15px;
            }}
            QPushButton:hover {{ color: {T_TEXT}; border-color: {T_GREEN}; }}
        """)

        btn_new.clicked.connect(self.new_deck)
        btn_sub.clicked.connect(self.new_sub)
        fl.addWidget(btn_new, stretch=1)
        fl.addWidget(btn_sub, stretch=1)
        fl.addWidget(btn_del)
        L.addWidget(foot)

    def _on_deck_clicked(self, deck):
        self._selected_deck = deck
        self.deck_selected.emit(deck)

    def _on_search(self, text):
        self._deck_list.filter(text.lower())

    def refresh(self):
        decks = self._data.get("decks", [])
        self._deck_list.load(decks)

    def get_selected(self):
        return self._selected_deck

    def set_data(self, data):
        self._data = data
        self.refresh()


# ── Custom deck list widget (paints like HTML items) ─────────────────────────
class _TMNTDeckList(QScrollArea):
    deck_selected = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"background: {T_BG}; border: none;")
        self._container = QWidget()
        self._container.setStyleSheet(f"background: {T_BG};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(2)
        self._layout.addStretch()
        self.setWidget(self._container)
        self._all_decks = []
        self._selected = None
        self._buttons = []

    def load(self, decks):
        self._all_decks = decks
        self._render(decks)

    def filter(self, text):
        if not text:
            self._render(self._all_decks)
            return
        filtered = [d for d in self._all_decks
                    if text in d.get("name","").lower()]
        self._render(filtered)

    def _render(self, decks):
        # Remove all but last stretch
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._buttons = []
        for deck in decks:
            btn = _TMNTDeckItem(deck, deck is self._selected)
            btn.clicked_deck.connect(self._on_item_clicked)
            self._layout.insertWidget(self._layout.count() - 1, btn)
            self._buttons.append(btn)

    def _on_item_clicked(self, deck):
        self._selected = deck
        for btn in self._buttons:
            btn.set_selected(btn._deck is deck)
        self.deck_selected.emit(deck)


def _count_due_in_deck(deck):
    """Recursively count due items in a deck."""
    count = 0
    for card in deck.get("cards", []):
        boxes = card.get("boxes", [])
        if not boxes:
            sm2_init(card)
            if is_due_today(card):
                count += 1
        else:
            seen = set()
            for b in boxes:
                sm2_init(b)
                gid = b.get("group_id", "")
                if gid:
                    if gid not in seen:
                        seen.add(gid)
                        if is_due_today(b):
                            count += 1
                else:
                    if is_due_today(b):
                        count += 1
    for child in deck.get("children", []):
        count += _count_due_in_deck(child)
    return count


class _TMNTDeckItem(QFrame):
    clicked_deck = pyqtSignal(object)

    def __init__(self, deck, selected=False, parent=None):
        super().__init__(parent)
        self._deck = deck
        self._selected = selected
        self.setCursor(Qt.PointingHandCursor)
        self._build()

    def _build(self):
        self.setFixedHeight(44)
        due = _count_due_in_deck(self._deck)
        name = self._deck.get("name", "?").upper()
        is_complete = (due == 0 and any(
            c.get("reviews", 0) > 0
            for c in self._deck.get("cards", [])
        ))

        if self._selected:
            bg   = f"background: {T_PANEL};"
            border = f"border-left: 2px solid {T_PURPLE};"
        else:
            bg   = "background: transparent;"
            border = "border-left: 2px solid transparent;"

        self.setStyleSheet(f"""
            QFrame {{ {bg} {border}
                border-radius: 3px;
            }}
            QFrame:hover {{ background: {T_PANEL}; }}
            QLabel {{ background: transparent; border: none; }}
        """)

        l = QHBoxLayout(self)
        l.setContentsMargins(8, 0, 10, 0)
        l.setSpacing(8)

        arrow = QLabel("▼" if self._selected else "▶")
        arrow.setStyleSheet(
            f"color: {T_PURPLE if self._selected else T_SUBTEXT}; font-size: 9px;"
        )
        l.addWidget(arrow)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"color: {T_PURPLE if self._selected else T_TEXT}; "
            f"font-size: 9px; font-weight: 900; font-family: {T_PIXEL};"
        )
        l.addWidget(name_lbl, stretch=1)

        if is_complete:
            badge = QLabel("✓")
            badge.setStyleSheet(f"color: {T_GREEN}; font-size: 13px;")
        elif due > 0:
            badge = QLabel(str(due))
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(26, 20)
            badge.setStyleSheet(
                f"background: {T_RED}; color: white; font-size: 9px; "
                f"font-weight: bold; border-radius: 3px; font-family: {T_MONO};"
            )
        else:
            badge = QLabel("")
        l.addWidget(badge)

    def set_selected(self, val):
        if self._selected == val:
            return
        self._selected = val
        # Rebuild layout
        for i in reversed(range(self.layout().count())):
            item = self.layout().takeAt(i)
            if item.widget():
                item.widget().deleteLater()
        self._build()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked_deck.emit(self._deck)
        super().mousePressEvent(e)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN CONTENT AREA
# ══════════════════════════════════════════════════════════════════════════════
class TMNTMainContent(QWidget):
    """Centre panel: deck title, stat cards, mission banner, card list, action bar."""
    request_review_due      = pyqtSignal()
    request_review_all      = pyqtSignal()
    request_review_selected = pyqtSignal()
    request_add_card        = pyqtSignal()
    request_edit_card       = pyqtSignal(int)    # index
    request_delete_card     = pyqtSignal(int)    # index

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck = None
        self._data = {}
        self.setStyleSheet(f"background: #151821;")
        self._build_ui()

    def _build_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(20, 20, 20, 12)
        L.setSpacing(14)

        # ── Deck title row ──
        title_row = QHBoxLayout()
        title_row.setSpacing(16)

        self.deck_icon = QLabel("🏯")
        self.deck_icon.setFixedSize(40, 40)
        self.deck_icon.setAlignment(Qt.AlignCenter)
        self.deck_icon.setStyleSheet(
            f"font-size: 24px; background: {T_PANEL}; "
            f"border: 1px solid {T_BORDER}; border-radius: 4px;"
        )

        title_txt = QVBoxLayout()
        title_txt.setSpacing(2)
        self.lbl_title = QLabel("SELECT A DOJO")
        self.lbl_title.setStyleSheet(
            f"color: {T_GREEN}; font-size: 18px; font-weight: 900; "
            f"font-family: {T_PIXEL}; letter-spacing: 1px; background: transparent;"
        )
        self.lbl_sub = QLabel("SCROLLS: 0  ❖  DUE: 0")
        self.lbl_sub.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 10px; font-weight: bold; "
            f"font-family: {T_MONO}; letter-spacing: 1px; background: transparent;"
        )
        title_txt.addWidget(self.lbl_title)
        title_txt.addWidget(self.lbl_sub)

        title_row.addWidget(self.deck_icon)
        title_row.addLayout(title_txt)
        title_row.addStretch()

        self.btn_forge = QPushButton("🐢  FORGE SCROLL")
        self.btn_forge.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T_GREEN};
                border: 1px solid {T_GREEN};
                border-radius: 2px;
                font-size: 10px;
                font-weight: 900;
                font-family: {T_PIXEL};
                padding: 8px 16px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: rgba(69,162,71,0.12); }}
        """)
        self.btn_forge.clicked.connect(self.request_add_card)
        title_row.addWidget(self.btn_forge)
        L.addLayout(title_row)

        # ── 3 Stat Cards ──
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.stat_missions = TMNTStatCard("REMAINING MISSIONS", "Cards due for review", T_RED)
        self.stat_scrolls  = TMNTStatCard("NEW TECHNIQUES",     "Total active scrolls", T_PURPLE)
        self.stat_battles  = TMNTStatCard("BATTLES WON",        "Reviews completed",    T_GREEN)
        stats_row.addWidget(self.stat_missions)
        stats_row.addWidget(self.stat_scrolls)
        stats_row.addWidget(self.stat_battles)
        L.addLayout(stats_row)

        # ── Mission Banner ──
        self.banner = TMNTMissionBanner()
        self.banner.train_clicked.connect(self.request_review_due)
        self.banner.selected_clicked.connect(self.request_review_selected)
        L.addWidget(self.banner)

        # ── Card list area ──
        list_frame = QFrame()
        list_frame.setObjectName("card_list_frame")
        list_frame.setStyleSheet(f"""
            QFrame#card_list_frame {{
                background: {T_BG};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
            }}
        """)
        lf_l = QVBoxLayout(list_frame)
        lf_l.setContentsMargins(0, 0, 0, 0)

        self.card_list = QListWidget()
        self.card_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                color: {T_TEXT};
                font-family: {T_MONO};
                font-size: 11px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-radius: 3px;
                border-bottom: 1px solid {T_BORDER};
            }}
            QListWidget::item:selected {{
                background: rgba(176,136,249,0.15);
                color: {T_PURPLE};
                border-left: 2px solid {T_PURPLE};
            }}
            QListWidget::item:hover:!selected {{
                background: rgba(69,162,71,0.06);
            }}
            QScrollBar:vertical {{
                background: {T_BG};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {T_PANEL};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {T_GREEN};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self.card_list.itemDoubleClicked.connect(
            lambda item: self.request_edit_card.emit(self.card_list.row(item))
        )

        # Empty state label
        self._empty_lbl = QLabel()
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color: {T_SUBTEXT}; font-family: {T_PIXEL}; font-size: 10px; "
            f"background: transparent; border: none;"
        )
        self._empty_lbl.setText("★\n\n— SELECT A SCROLL TO BEGIN —")
        self._empty_lbl.hide()

        lf_l.addWidget(self.card_list)
        lf_l.addWidget(self._empty_lbl)
        L.addWidget(list_frame, stretch=1)

        # ── Bottom action bar ──
        bot = QHBoxLayout()
        bot.setSpacing(10)

        self.btn_edit = QPushButton("✏  Edit")
        self.btn_edit.setStyleSheet(f"""
            QPushButton {{
                background: {T_PANEL};
                color: {T_TEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: 11px;
                font-family: {T_MONO};
                padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {T_CARD}; color: white; }}
        """)
        self.btn_edit.clicked.connect(
            lambda: self.request_edit_card.emit(self.card_list.currentRow())
        )

        self.btn_delete = QPushButton("🗑  DELETE")
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {T_RED};
                border: 1px solid {T_RED};
                border-radius: 2px;
                font-size: 11px;
                font-weight: bold;
                font-family: {T_MONO};
                padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {T_RED}; color: white; }}
        """)
        self.btn_delete.clicked.connect(
            lambda: self.request_delete_card.emit(self.card_list.currentRow())
        )

        bot.addWidget(self.btn_edit)
        bot.addWidget(self.btn_delete)
        bot.addStretch()
        L.addLayout(bot)

    def load_deck(self, deck, data):
        self._deck = deck
        self._data = data
        self._refresh()

    def _refresh(self):
        if not self._deck:
            return

        def _all_cards(d):
            res = list(d.get("cards", []))
            for ch in d.get("children", []):
                res.extend(_all_cards(ch))
            return res

        all_cards = _all_cards(self._deck)
        due_c     = 0
        total_rev = 0

        for c in all_cards:
            sm2_init(c)
            boxes = c.get("boxes", [])
            if not boxes:
                if is_due_today(c): due_c += 1
            else:
                seen = set()
                for b in boxes:
                    sm2_init(b)
                    gid = b.get("group_id", "")
                    if gid:
                        if gid not in seen:
                            seen.add(gid)
                            if is_due_today(b): due_c += 1
                    else:
                        if is_due_today(b): due_c += 1
            total_rev += c.get("reviews", 0)

        self.lbl_title.setText(self._deck.get("name", "?").upper())
        self.lbl_sub.setText(f"SCROLLS: {len(all_cards)}  ❖  DUE: {due_c}")
        self.stat_missions.set_value(due_c)
        self.stat_scrolls.set_value(len(all_cards))
        self.stat_battles.set_value(total_rev)

        self.card_list.clear()
        direct = self._deck.get("cards", [])

        for c in direct:
            boxes   = c.get("boxes", [])
            is_due  = self._card_due(c)
            badge   = "🔴 DUE" if is_due else f"✅ {sm2_days_left(c)}d"
            n_masks = len(set(
                b.get("group_id","") or b.get("box_id","")
                for b in boxes
            ))
            title = c.get("title", "Untitled")
            rep   = c.get("sm2_repetitions", 0)
            text  = f"  {title}  |  masks: {n_masks}  |  rep: {rep}  |  {badge}"
            item  = QListWidgetItem(text)
            if is_due:
                item.setForeground(QColor(T_RED))
            self.card_list.addItem(item)

        if not direct:
            self.card_list.hide()
            self._empty_lbl.show()
        else:
            self.card_list.show()
            self._empty_lbl.hide()

    def _card_due(self, card):
        boxes = card.get("boxes", [])
        if not boxes:
            sm2_init(card)
            return is_due_today(card)
        seen = set()
        for b in boxes:
            sm2_init(b)
            gid = b.get("group_id","")
            if gid:
                if gid not in seen:
                    seen.add(gid)
                    if is_due_today(b): return True
            else:
                if is_due_today(b): return True
        return False

    def clear(self):
        self._deck = None
        self.lbl_title.setText("SELECT A DOJO")
        self.lbl_sub.setText("SCROLLS: 0  ❖  DUE: 0")
        self.stat_missions.set_value(0)
        self.stat_scrolls.set_value(0)
        self.stat_battles.set_value(0)
        self.card_list.clear()
        self.card_list.hide()
        self._empty_lbl.show()


# ══════════════════════════════════════════════════════════════════════════════
#  TOP BAR
# ══════════════════════════════════════════════════════════════════════════════
class TMNTTopBar(QFrame):
    btn_math_clicked    = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_theme_clicked   = pyqtSignal()
    btn_help_clicked    = pyqtSignal()
    btn_about_clicked   = pyqtSignal()
    font_change         = pyqtSignal(int)   # -1 / 0 / +1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_topbar")
        self.setFixedHeight(52)
        self.setStyleSheet(f"""
            QFrame#tmnt_topbar {{
                background: {T_BG};
                border-bottom: 1px solid {T_BORDER};
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        self._build_ui()
        self._quote_idx = 0
        self._quote_timer = QTimer(self)
        self._quote_timer.timeout.connect(self._rotate_quote)
        self._quote_timer.start(8000)

    def _build_ui(self):
        L = QHBoxLayout(self)
        L.setContentsMargins(16, 0, 16, 0)
        L.setSpacing(0)

        # ── Logo ──
        logo_box = QFrame()
        logo_box.setStyleSheet(
            f"QFrame {{ border: 2px solid {T_GREEN}; border-radius: 4px; "
            f"background: transparent; padding: 2px 6px; }}"
            f"QLabel {{ border: none; }}"
        )
        logo_box.setFixedSize(46, 38)
        ll = QHBoxLayout(logo_box)
        ll.setContentsMargins(0, 0, 0, 0)
        logo_icon = QLabel("🐢")
        logo_icon.setStyleSheet("font-size: 22px; border: none;")
        logo_icon.setAlignment(Qt.AlignCenter)
        ll.addWidget(logo_icon)
        L.addWidget(logo_box)

        L.addSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title_col.setAlignment(Qt.AlignVCenter)
        app_name = QLabel("ANKI OCCLUSION")
        app_name.setStyleSheet(
            f"color: {T_NEON}; font-size: 14px; font-weight: 900; "
            f"font-family: {T_PIXEL}; letter-spacing: 2px;"
        )
        title_col.addWidget(app_name)
        L.addLayout(title_col)

        L.addStretch()

        # ── Nav buttons ──
        def _nav(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {T_SUBTEXT};
                    border: none;
                    border-bottom: 2px solid transparent;
                    font-family: {T_MONO};
                    font-size: 11px;
                    font-weight: bold;
                    padding: 8px 14px;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                }}
                QPushButton:hover {{
                    color: {T_GREEN};
                    border-bottom: 2px solid {T_GREEN};
                }}
            """)
            return b

        btn_math    = _nav("🧮 MATH",    "Math Trainer")
        btn_journal = _nav("📓 JOURNAL", "Daily Journal")
        btn_theme   = _nav("📚 CLASSIC", "Switch Theme")
        btn_help    = _nav("❓ HELP",    "Help")
        btn_about   = _nav("ℹ ABOUT",   "About")

        btn_math.clicked.connect(self.btn_math_clicked)
        btn_journal.clicked.connect(self.btn_journal_clicked)
        btn_theme.clicked.connect(self.btn_theme_clicked)
        btn_help.clicked.connect(self.btn_help_clicked)
        btn_about.clicked.connect(self.btn_about_clicked)

        for b in (btn_math, btn_journal, btn_theme, btn_help, btn_about):
            L.addWidget(b)

        L.addSpacing(12)

        # ── Font buttons ──
        def _font_btn(text, delta):
            b = QPushButton(text)
            b.setFixedSize(28, 26)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {T_PANEL};
                    color: {T_SUBTEXT};
                    border: 1px solid {T_BORDER};
                    border-radius: 2px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {T_CARD}; color: {T_TEXT}; border-color: {T_GREEN}; }}
            """)
            b.clicked.connect(lambda: self.font_change.emit(delta))
            return b

        L.addWidget(_font_btn("A−", -1))
        L.addSpacing(2)
        L.addWidget(_font_btn("A",   0))
        L.addSpacing(2)
        L.addWidget(_font_btn("A+", +1))
        L.addSpacing(14)

        # ── Mentor / Quote card ──
        mentor = QFrame()
        mentor.setFixedSize(220, 40)
        mentor.setStyleSheet(f"""
            QFrame {{
                background: rgba(176,136,249,0.08);
                border: 1px solid {T_PURPLE};
                border-radius: 4px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        ml = QHBoxLayout(mentor)
        ml.setContentsMargins(8, 4, 8, 4)
        ml.setSpacing(8)

        av = QLabel("🐢")
        av.setFixedSize(30, 30)
        av.setAlignment(Qt.AlignCenter)
        av.setStyleSheet(
            f"font-size: 20px; background: rgba(176,136,249,0.15); "
            f"border: 1px solid {T_PURPLE}; border-radius: 15px;"
        )
        ml.addWidget(av)

        self.quote_lbl = QLabel(MENTOR_QUOTES[0][0])
        self.quote_lbl.setStyleSheet(
            f"color: {T_PURPLE}; font-size: 7px; font-weight: 900; "
            f"font-family: {T_PIXEL}; line-height: 1.4;"
        )
        self.name_lbl = QLabel(MENTOR_QUOTES[0][1])
        self.name_lbl.setStyleSheet(
            f"color: {T_SUBTEXT}; font-size: 8px; font-family: {T_MONO};"
        )
        q_col = QVBoxLayout()
        q_col.setSpacing(2)
        q_col.addWidget(self.quote_lbl)
        q_col.addWidget(self.name_lbl)
        ml.addLayout(q_col)
        L.addWidget(mentor)

    def _rotate_quote(self):
        self._quote_idx = (self._quote_idx + 1) % len(MENTOR_QUOTES)
        q, n = MENTOR_QUOTES[self._quote_idx]
        self.quote_lbl.setText(q)
        self.name_lbl.setText(n)


# ══════════════════════════════════════════════════════════════════════════════
#  FOOTER
# ══════════════════════════════════════════════════════════════════════════════
class TMNTFooter(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setStyleSheet(f"""
            QFrame {{ background: {T_BG}; border-top: 1px solid {T_BORDER}; border-radius: 0px; }}
            QLabel {{ background: transparent; border: none; }}
        """)
        L = QHBoxLayout(self)
        L.setContentsMargins(12, 0, 12, 0)
        L.setSpacing(12)

        def _status(icon, text, color):
            lbl = QLabel(f"{icon}  {text}")
            lbl.setStyleSheet(
                f"color: {color}; font-size: 9px; font-family: {T_MONO}; font-weight: bold;"
            )
            return lbl

        L.addWidget(_status("✅", "SM-2 Active", T_GREEN))
        sep = QLabel("|")
        sep.setStyleSheet(f"color: {T_BORDER}; font-size: 10px;")
        L.addWidget(sep)
        pdf_text = "PyMuPDF loaded — PDF support active" if PDF_SUPPORT else "⚠ pip install pymupdf for PDF support"
        pdf_col  = T_GREEN if PDF_SUPPORT else T_RED
        L.addWidget(_status("✅" if PDF_SUPPORT else "⚠", pdf_text, pdf_col))
        L.addStretch()


# ══════════════════════════════════════════════════════════════════════════════
#  TMNT HOME LAYOUT  (top-level widget, drop-in for HomeScreen)
# ══════════════════════════════════════════════════════════════════════════════
class TMNTHomeLayout(QWidget):
    """
    Full TMNT Dojo Dashboard layout.
    HomeScreen instantiates this and swaps it in when theme == 'tmnt'.
    Signals mirror the HomeScreen interface HomeScreen depends on.
    """
    # Forwarded to HomeScreen so it can wire buttons
    btn_math_clicked    = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_theme_clicked   = pyqtSignal()
    btn_help_clicked    = pyqtSignal()
    btn_about_clicked   = pyqtSignal()
    font_change         = pyqtSignal(int)
    deck_selected       = pyqtSignal(object)

    def __init__(self, data: dict, deck_view_ref, parent=None):
        """
        data          — the global app data dict
        deck_view_ref — the existing DeckView (we call its methods for
                        card add/edit/delete/review so we don't duplicate logic)
        """
        super().__init__(parent)
        self._data     = data
        self._dv       = deck_view_ref   # DeckView — used for card ops
        self._selected_deck = None
        self._setup_ui()
        self._wire_signals()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # Top bar
        self.topbar = TMNTTopBar()
        L.addWidget(self.topbar)

        # Body (sidebar + main + right)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar  = TMNTSidebar(self._data)
        self.main     = TMNTMainContent()
        self.banga    = TMNTBangaLab()

        body.addWidget(self.sidebar)
        body.addWidget(self.main, stretch=1)
        body.addWidget(self.banga)

        body_w = QWidget()
        body_w.setLayout(body)
        body_w.setStyleSheet(f"background: #151821;")
        L.addWidget(body_w, stretch=1)

        # Footer
        self.footer = TMNTFooter()
        L.addWidget(self.footer)

    def _wire_signals(self):
        # Topbar → HomeScreen
        self.topbar.btn_math_clicked.connect(self.btn_math_clicked)
        self.topbar.btn_journal_clicked.connect(self.btn_journal_clicked)
        self.topbar.btn_theme_clicked.connect(self.btn_theme_clicked)
        self.topbar.btn_help_clicked.connect(self.btn_help_clicked)
        self.topbar.btn_about_clicked.connect(self.btn_about_clicked)
        self.topbar.font_change.connect(self.font_change)

        # Sidebar deck selection
        self.sidebar.deck_selected.connect(self._on_deck_selected)
        self.sidebar.new_deck.connect(self._new_deck)
        self.sidebar.new_sub.connect(self._new_sub)

        # Main content card operations → delegate to DeckView
        self.main.request_add_card.connect(self._add_card)
        self.main.request_review_due.connect(self._review_due)
        self.main.request_review_all.connect(self._review_all)
        self.main.request_review_selected.connect(self._review_selected)
        self.main.request_edit_card.connect(self._edit_card)
        self.main.request_delete_card.connect(self._delete_card)

    # ── Deck ops ─────────────────────────────────────────────────────────────
    def _on_deck_selected(self, deck):
        self._selected_deck = deck
        # Sync the hidden DeckView so card ops work
        self._dv.load_deck(deck, self._data)
        self.main.load_deck(deck, self._data)
        self.deck_selected.emit(deck)

    def _new_deck(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Dojo", "Dojo name:")
        if ok and name.strip():
            deck = {
                "_id":      next_deck_id(self._data),
                "name":     name.strip(),
                "cards":    [],
                "children": [],
                "created":  datetime.now().isoformat(),
            }
            self._data.setdefault("decks", []).append(deck)
            store.mark_dirty()
            self.refresh()

    def _new_sub(self):
        if not self._selected_deck:
            QMessageBox.warning(self, "No Dojo", "Select a dojo first.")
            return
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Sub-Dojo", "Sub-dojo name:")
        if ok and name.strip():
            child = {
                "_id":      next_deck_id(self._data),
                "name":     name.strip(),
                "cards":    [],
                "children": [],
                "created":  datetime.now().isoformat(),
            }
            self._selected_deck.setdefault("children", []).append(child)
            store.mark_dirty()
            self.refresh()

    # ── Card ops (delegate to DeckView) ──────────────────────────────────────
    def _add_card(self):
        self._dv._add_card()
        self._reload_main()

    def _edit_card(self, idx):
        if idx < 0:
            return
        item = self._dv.card_list.item(idx)
        if item:
            self._dv._edit_card(item)
            self._reload_main()

    def _delete_card(self, idx):
        if idx < 0:
            return
        self._dv.card_list.setCurrentRow(idx)
        self._dv._delete_card()
        self._reload_main()

    def _review_due(self):
        self._dv._review_due()

    def _review_all(self):
        self._dv._review_all()

    def _review_selected(self):
        idx = self.main.card_list.currentRow()
        if idx < 0 or not self._selected_deck:
            return
        cards = self._selected_deck.get("cards", [])
        if 0 <= idx < len(cards):
            home = self._find_home()
            if home:
                home.show_review([cards[idx]], self._data)

    def _reload_main(self):
        """Reload main content from fresh deck data."""
        if self._selected_deck:
            fresh = find_deck_by_id(
                self._selected_deck.get("_id"), self._data.get("decks", []))
            if fresh:
                self._selected_deck = fresh
                self.main.load_deck(fresh, self._data)

    def _find_home(self):
        from ui.home_screen import HomeScreen
        w = self.parent()
        while w:
            if isinstance(w, HomeScreen):
                return w
            w = w.parent()
        return None

    # ── Public interface (called by HomeScreen) ───────────────────────────────
    def refresh(self):
        self.sidebar.set_data(self._data)
        if self._selected_deck:
            fresh = find_deck_by_id(
                self._selected_deck.get("_id"), self._data.get("decks", []))
            if fresh:
                self._selected_deck = fresh
                self.main.load_deck(fresh, self._data)
        self.banga.refresh()

    def get_selected_deck(self):
        return self._selected_deck