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

import os, math, re
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QMessageBox,
    QTreeWidgetItem,
    QDialog,
    QStackedWidget,
    QApplication,
    QGraphicsDropShadowEffect,
    QStyledItemDelegate,
    QStyle,
)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QRect
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPixmap,
    QPainterPath,
    QLinearGradient,
)

from sm2_engine import sm2_init, is_due_today, sm2_days_left
from data_manager import find_deck_by_id, next_deck_id, store
from pdf_engine import PDF_SUPPORT
from ui.deck_tree import DeckTree, _DeckTreeWidget
from ui.deck_view import DeckView

# ── TMNT Palette ─────────────────────────────────────────────────────────────
T_BG = "#0b0c10"
T_PANEL = "#1f2833"
T_CARD = "#262933"
T_GREEN = "#45a247"
T_NEON = "#66fcf1"
T_TEXT = "#c5c6c7"
T_SUBTEXT = "#6b7280"
T_RED = "#ff4d4d"
T_PURPLE = "#b088f9"
T_BORDER = "#333b4d"
T_MONO = "'Roboto Mono', 'Courier New', monospace"
T_PIXEL = "'Press Start 2P', monospace"
TMNT_BASE_SIZE = 11
TMNT_SIDEBAR_W = int(228 * 1.2)
TMNT_RIGHTBAR_W = int(218 * 1.2)
_PX_RE = re.compile(r"(-?\d+(?:\.\d+)?)px")

MENTOR_QUOTES = [
    ('"FOCUS. TRAIN. MASTER."', "— DONATELLO"),
    ('"KNOWLEDGE IS THE WEAPON."', "— SPLINTER"),
    ('"COWABUNGA, DUDE!"', "— MICHELANGELO"),
    ('"NEVER STOP LEARNING."', "— LEONARDO"),
    ('"SCIENCE NEVER FAILS."', "— DONATELLO"),
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


def _tmnt_scale(data=None):
    if data and data.get("_font_size"):
        size = int(data.get("_font_size", TMNT_BASE_SIZE))
    else:
        app = QApplication.instance()
        size = app.font().pointSize() if app else TMNT_BASE_SIZE
        if size <= 0:
            size = TMNT_BASE_SIZE
    return max(0.75, size / TMNT_BASE_SIZE)


def _px(value, scale=1.0):
    return max(1, int(round(value * scale)))


def _scale_ss(style, scale=1.0):
    return _PX_RE.sub(lambda m: f"{_px(float(m.group(1)), scale)}px", style)


def _apply_glow(widget, color, blur=16, offset_y=0, alpha=110):
    effect = QGraphicsDropShadowEffect(widget)
    glow = QColor(color)
    glow.setAlpha(alpha)
    effect.setColor(glow)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset_y)
    widget.setGraphicsEffect(effect)


def _walk_decks(decks):
    for deck in decks:
        yield deck
        yield from _walk_decks(deck.get("children", []))


def _deck_total_cards(deck):
    total = len(deck.get("cards", []))
    for child in deck.get("children", []):
        total += _deck_total_cards(child)
    return total


def _deck_total_reviews(deck):
    total = sum(card.get("reviews", 0) for card in deck.get("cards", []))
    for child in deck.get("children", []):
        total += _deck_total_reviews(child)
    return total


class TMNTDeckItemDelegate(QStyledItemDelegate):
    def __init__(self, scale=1.0, parent=None):
        super().__init__(parent)
        self._scale = scale

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect.adjusted(
            _px(2, self._scale),
            _px(1, self._scale),
            -_px(2, self._scale),
            -_px(1, self._scale),
        )

        if is_selected:
            painter.fillRect(rect, QColor(T_PANEL))
            painter.fillRect(
                QRect(rect.left(), rect.top(), _px(2, self._scale), rect.height()),
                QColor(T_PURPLE),
            )
        elif is_hovered:
            painter.fillRect(rect, QColor(69, 162, 71, 15))

        name = (
            index.data(Qt.UserRole + 2) or index.data(Qt.DisplayRole) or "?"
        ).upper()
        due_str = index.data(Qt.UserRole + 1)
        total_cards = int(index.data(Qt.UserRole + 3) or 0)
        due = int(due_str) if due_str else 0
        is_complete = due == 0 and total_cards > 0

        text_color = QColor(T_PURPLE if is_selected else T_TEXT)
        font = QFont("Press Start 2P")
        font.setPixelSize(_px(10, self._scale))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text_color)

        badge_w = _px(26, self._scale)
        badge_h = _px(20, self._scale)
        right_pad = _px(10, self._scale)
        text_rect = QRect(
            rect.left() + _px(14, self._scale),
            rect.top(),
            max(
                _px(20, self._scale),
                rect.width() - badge_w - right_pad - _px(24, self._scale),
            ),
            rect.height(),
        )
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, name)

        badge_rect = QRect(
            rect.right() - badge_w - right_pad,
            rect.top() + (rect.height() - badge_h) // 2,
            badge_w,
            badge_h,
        )

        if due > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(T_RED))
            painter.drawRoundedRect(
                badge_rect, _px(3, self._scale), _px(3, self._scale)
            )
            badge_font = QFont("Roboto Mono")
            badge_font.setPixelSize(_px(10, self._scale))
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(badge_rect, Qt.AlignCenter, str(due))
        elif is_complete:
            check_font = QFont("Roboto Mono")
            check_font.setPixelSize(_px(13, self._scale))
            check_font.setBold(True)
            painter.setFont(check_font)
            painter.setPen(QColor(T_GREEN))
            painter.drawText(badge_rect, Qt.AlignCenter, "✓")

        painter.restore()

    def sizeHint(self, option, index):
        from PyQt5.QtGui import QFontMetrics

        name = (
            index.data(Qt.UserRole + 2) or index.data(Qt.DisplayRole) or "?"
        ).upper()
        font = QFont("Press Start 2P")
        font.setPixelSize(_px(10, self._scale))
        font.setBold(True)
        fm = QFontMetrics(font)

        text_w = fm.horizontalAdvance(name)
        badge_w = _px(26, self._scale)
        right_pad = _px(10, self._scale)
        left_pad = _px(14, self._scale)
        extra = _px(24, self._scale)

        total_w = left_pad + text_w + extra + badge_w + right_pad
        base_size = super().sizeHint(option, index)
        return QSize(max(base_size.width(), total_w), _px(44, self._scale))


# ══════════════════════════════════════════════════════════════════════════════
#  STAT CARD  (3 across top of main area)
# ══════════════════════════════════════════════════════════════════════════════
class TMNTStatCard(QFrame):
    def __init__(self, title, subtitle, color, data=None, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_stat_card1")
        self._color = color
        self._scale = _tmnt_scale(data)
        self._setup(title, subtitle, color)
        _apply_glow(self, color, blur=_px(18, self._scale), alpha=55)

    def _setup(self, title, subtitle, color):
        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_stat_card1 {{
                background: {T_CARD};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
            }}
            QFrame#tmnt_stat_card1:hover {{ background: #2b2f3b; border-color: {T_BORDER}; }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
        l = QHBoxLayout(self)
        l.setContentsMargins(
            _px(18, self._scale),
            _px(12, self._scale),
            _px(18, self._scale),
            _px(12, self._scale),
        )
        l.setSpacing(_px(18, self._scale))

        # Glow blob (painted) + icon
        self._icon = QLabel("★")
        self._icon.setStyleSheet(
            _scale_ss(
                f"color: {color}; font-size: 28px; background: transparent; border: none;",
                self._scale,
            )
        )
        l.addWidget(self._icon)

        txt = QVBoxLayout()
        txt.setSpacing(_px(2, self._scale))
        self.val_lbl = QLabel("0")
        self.val_lbl.setStyleSheet(
            _scale_ss(
                f"color: {color}; font-size: 32px; font-weight: 900; "
                f"font-family: {T_PIXEL}; background: transparent; border: none;",
                self._scale,
            )
        )
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_TEXT}; font-size: 10px; font-weight: 900; "
                f"font-family: {T_MONO}; letter-spacing: 1px; background: transparent; border: none;",
                self._scale,
            )
        )
        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 10px; "
                f"font-family: {T_MONO}; background: transparent; border: none;",
                self._scale,
            )
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

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_banner1")
        self._scale = _tmnt_scale(data)
        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_banner1 {{
                background: {T_CARD};
                border: 1px solid {T_BORDER};
                border-left: 3px solid {T_PURPLE};
                border-radius: 4px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
        l = QHBoxLayout(self)
        l.setContentsMargins(
            _px(20, self._scale),
            _px(16, self._scale),
            _px(20, self._scale),
            _px(16, self._scale),
        )
        l.setSpacing(_px(16, self._scale))

        left = QVBoxLayout()
        left.setSpacing(_px(6, self._scale))
        title = QLabel("⚔  TRAINING MISSION")
        title.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE}; font-size: 12px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 1px; background: transparent; border: none;",
                self._scale,
            )
        )
        desc = QLabel("Continue your training and defeat the due cards!")
        desc.setStyleSheet(
            _scale_ss(
                f"color: {T_TEXT}; font-size: 14px; font-family: {T_MONO}; background: transparent; border: none;",
                self._scale,
            )
        )
        self.quote = QLabel("> Cowabunga! 🐢_")
        self.quote.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: 12px; font-weight: bold; "
                f"font-family: {T_MONO}; background: transparent; border: none;",
                self._scale,
            )
        )
        left.addWidget(title)
        left.addWidget(desc)
        left.addWidget(self.quote)
        left.addStretch()
        l.addLayout(left)
        l.addStretch()

        right = QVBoxLayout()
        right.setSpacing(_px(8, self._scale))
        right.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self.btn_train = QPushButton("▶  START TRAINING\nREVIEW DUE SCROLLS")
        self.btn_train.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: #4aa84f;
                color: {T_BG};
                border: 1px solid #60c467;
                border-radius: 2px;
                font-weight: 900;
                font-family: {T_PIXEL};
                font-size: 14px;
                min-height: 52px;
                padding: 0px 24px;
                text-align: center;
            }}
            QPushButton:hover {{ background: #56b75c; color: {T_BG}; }}
        """,
                self._scale,
            )
        )
        self.btn_train.clicked.connect(self.train_clicked)
        _apply_glow(self.btn_train, "#5bc561", blur=_px(24, self._scale), alpha=120)

        self.btn_selected = QPushButton("◎  TRAIN SELECTED SCROLL")
        self.btn_selected.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: #aab1c4;
                border: 1px solid #555c6e;
                border-radius: 2px;
                font-size: 12px;
                font-weight: 700;
                font-family: {T_MONO};
                letter-spacing: 1px;
                min-height: 36px;
                padding: 0px 16px;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.04); color: {T_TEXT}; border-color: #70788f; }}
        """,
                self._scale,
            )
        )
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
        r = int(74 + (92 - 74) * t)
        g = int(168 + (190 - 168) * t)
        b = int(79 + (99 - 79) * t)
        col = f"#{r:02X}{g:02X}{b:02X}"
        self.btn_train.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: {col};
                color: {T_BG};
                border: none;
                border-radius: 2px;
                font-weight: 900;
                font-family: {T_PIXEL};
                font-size: 14px;
                min-height: 52px;
                padding: 0px 24px;
                text-align: center;
            }}
            QPushButton:hover {{ background: #56b75c; color: {T_BG}; }}
        """,
                self._scale,
            )
        )


# ══════════════════════════════════════════════════════════════════════════════
#  RIGHT SIDEBAR — Banga Lab
# ══════════════════════════════════════════════════════════════════════════════
class TMNTBangaLab(QFrame):
    clear_clicked = pyqtSignal()

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_banga_lab1")
        self._scale = _tmnt_scale(data)
        self.setFixedWidth(_px(TMNT_RIGHTBAR_W, self._scale))
        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_banga_lab1 {{
                background: {T_BG};
                border-left: 1px solid {T_BORDER};
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_timer.start(4000)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            _scale_ss(
                f"""
            QScrollArea {{
                background: {T_BG};
                border: none;
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
        """,
                self._scale,
            )
        )
        root.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {T_BG};")
        scroll.setWidget(content)

        body = QVBoxLayout(content)
        body.setContentsMargins(
            _px(16, self._scale),
            _px(20, self._scale),
            _px(16, self._scale),
            _px(20, self._scale),
        )
        body.setSpacing(_px(20, self._scale))

        # ── Header ──
        hdr = QHBoxLayout()
        icon = QLabel("🧪")
        icon.setStyleSheet(_scale_ss("font-size: 16px; border: none;", self._scale))
        title = QLabel("Banga Lab")
        title.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: 11px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 1px;",
                self._scale,
            )
        )
        hdr.addWidget(icon)
        hdr.addWidget(title)
        hdr.addStretch()
        body.addLayout(hdr)

        # ── System Status ──
        sys_lbl = QLabel("— SYSTEM STATUS —")
        sys_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 10px; font-weight: 900; "
                f"font-family: {T_MONO}; letter-spacing: 2px; padding: 4px 0px;",
                self._scale,
            )
        )
        sys_lbl.setAlignment(Qt.AlignCenter)
        body.addWidget(sys_lbl)

        def _stat_row(lbl_text, val_text, val_color, dot=False):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, _px(4, self._scale), 0, _px(4, self._scale))
            lb = QLabel(lbl_text)
            lb.setStyleSheet(
                _scale_ss(
                    f"color: {T_SUBTEXT}; font-size: 10px; font-family: {T_MONO}; font-weight: bold;",
                    self._scale,
                )
            )
            vl = QLabel(("● " if dot else "") + val_text)
            vl.setStyleSheet(
                _scale_ss(
                    f"color: {val_color}; font-size: 10px; font-weight: bold; font-family: {T_MONO};",
                    self._scale,
                )
            )
            hl.addWidget(lb)
            hl.addStretch()
            hl.addWidget(vl)
            return w

        body.addWidget(_stat_row("ALGORITHM", "SM-2", T_PURPLE))
        body.addWidget(_sep_line())
        body.addWidget(_stat_row("SCHEDULER", "ACTIVE", T_GREEN, dot=True))
        body.addWidget(_sep_line())
        pdf_val = "PyMuPDF" if PDF_SUPPORT else "MISSING"
        pdf_col = T_PURPLE if PDF_SUPPORT else T_RED
        body.addWidget(_stat_row("PDF ENGINE", pdf_val, pdf_col))
        body.addWidget(_sep_line())
        body.addWidget(_stat_row("OCCLUSION", "ACTIVE", T_GREEN, dot=True))

        # ── Dojo Resources ──
        res_lbl = QLabel("— DOJO RESOURCES —")
        res_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 10px; font-weight: 900; "
                f"font-family: {T_MONO}; letter-spacing: 2px; padding: 4px 0px;",
                self._scale,
            )
        )
        res_lbl.setAlignment(Qt.AlignCenter)
        body.addWidget(res_lbl)

        def _res_row(name, color):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, _px(2, self._scale), 0, _px(2, self._scale))
            vl.setSpacing(_px(3, self._scale))
            hl = QHBoxLayout()
            hl.setContentsMargins(0, 0, 0, 0)
            lb = QLabel(name)
            lb.setStyleSheet(
                _scale_ss(
                    f"color: {T_SUBTEXT}; font-size: 10px; font-family: {T_MONO}; font-weight: bold;",
                    self._scale,
                )
            )
            val = QLabel("0.0 MB")
            val.setStyleSheet(
                _scale_ss(
                    f"color: {T_TEXT}; font-size: 10px; font-family: {T_MONO}; font-weight: bold;",
                    self._scale,
                )
            )
            hl.addWidget(lb)
            hl.addStretch()
            hl.addWidget(val)
            vl.addLayout(hl)
            bg = QFrame()
            bg.setFixedHeight(_px(4, self._scale))
            bg.setStyleSheet(
                _scale_ss(
                    f"background: {T_PANEL}; border-radius: 2px; border: none;",
                    self._scale,
                )
            )
            bl = QHBoxLayout(bg)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setAlignment(Qt.AlignLeft)
            bar = QFrame()
            bar.setFixedHeight(_px(4, self._scale))
            bar.setFixedWidth(0)
            bar.setStyleSheet(
                _scale_ss(
                    f"background: {color}; border-radius: 2px; border: none;",
                    self._scale,
                )
            )
            bl.addWidget(bar)
            vl.addWidget(bg)
            return w, val, bar, bg

        self.w_mem, self.lbl_mem, self.bar_mem, self.bg_mem = _res_row(
            "MEMORY", T_PURPLE
        )
        self.w_cache, self.lbl_cache, self.bar_cache, self.bg_cache = _res_row(
            "CACHE", T_GREEN
        )
        self.w_media, self.lbl_media, self.bar_media, self.bg_media = _res_row(
            "MEDIA", T_RED
        )
        self.w_tot, self.lbl_tot, self.bar_tot, self.bg_tot = _res_row(
            "TOTAL", T_PURPLE
        )

        for row in (self.w_mem, self.w_cache, self.w_media, self.w_tot):
            body.addWidget(row)

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
        fl.setContentsMargins(
            _px(10, self._scale),
            _px(10, self._scale),
            _px(10, self._scale),
            _px(10, self._scale),
        )
        fl.setSpacing(_px(10, self._scale))
        pizza = QLabel("🍕")
        pizza.setStyleSheet(_scale_ss("font-size: 22px; border: none;", self._scale))
        fl.addWidget(pizza)
        ftxt = QVBoxLayout()
        ftxt.setSpacing(_px(3, self._scale))
        fh = QLabel("FUEL UP, NINJA!")
        fh.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: 10px; font-weight: 900; font-family: {T_PIXEL};",
                self._scale,
            )
        )
        fd = QLabel("Take breaks.\nYour brain is\nnot a robot.")
        fd.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 9px; font-family: {T_MONO};",
                self._scale,
            )
        )
        ftxt.addWidget(fh)
        ftxt.addWidget(fd)
        fl.addLayout(ftxt)
        body.addWidget(fuel)

        # ── Clear Cache btn ──
        clr = QPushButton("🧹  Clear All Caches")
        clr.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: 9px;
                font-family: {T_MONO};
                padding: 6px;
            }}
            QPushButton:hover {{ color: {T_TEXT}; border-color: {T_GREEN}; }}
        """,
                self._scale,
            )
        )
        clr.clicked.connect(self._clear_all)
        body.addWidget(clr)
        body.addStretch()

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
                ram_b += PAGE_CACHE.ram_bytes_for_pdf(p)
                mask_b += MASK_REGISTRY.mask_bytes_for_pdf(p)
        except Exception:
            ram_b = disk_b = mask_b = 0

        tot_b = ram_b + disk_b + mask_b
        to_mb = lambda b: b / (1024**2)
        MAX_MB = 512.0

        def _w(mb):
            max_w = _px(188, self._scale)
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
            from cache_manager import (
                PAGE_CACHE,
                COMBINED_CACHE,
                MASK_REGISTRY,
                PIXMAP_REGISTRY,
            )

            COMBINED_CACHE.clear()
            PAGE_CACHE.clear_ram_only()
            MASK_REGISTRY._map.clear()
            for label in list(PIXMAP_REGISTRY._entries.keys()):
                PIXMAP_REGISTRY.unregister(label)
            self.refresh()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  TMNT DECK ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class TMNTDeckEngine(DeckTree):
    def __init__(self, data, scale=1.0, parent=None):
        self._tmnt_scale = scale
        super().__init__(data, theme="tmnt", parent=parent)
        if hasattr(self, "_blink_timer"):
            self._blink_timer.stop()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(_px(6, self._tmnt_scale))

        self.tree = _DeckTreeWidget()
        self._delegate = TMNTDeckItemDelegate(self._tmnt_scale, self.tree)
        self.tree.setItemDelegate(self._delegate)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.viewport().setAcceptDrops(True)
        self.tree.dropEvent = self._on_tree_drop
        self.tree.dragEnterEvent = self._on_drag_enter
        self.tree.dragMoveEvent = self._on_drag_move
        self.tree.dragLeaveEvent = self._on_drag_leave
        self.tree.setIndentation(_px(16, self._tmnt_scale))
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setStyleSheet(
            _scale_ss(
                f"""
            QTreeWidget {{
                background: {T_BG};
                border: none;
                color: {T_TEXT};
                outline: none;
                padding: 0px 4px 4px 4px;
                font-family: {T_MONO};
                font-size: 10px;
            }}
            QTreeWidget::item {{
                padding: 8px 8px;
                border-radius: 3px;
                margin: 1px 0px;
            }}
            QTreeWidget::item:selected {{
                background: rgba(176,136,249,0.15);
                color: {T_PURPLE};
                border-left: 2px solid {T_PURPLE};
            }}
            QTreeWidget::item:hover:!selected {{
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
            QScrollBar:horizontal {{
                background: {T_BG};
                height: 8px;
            }}
            QScrollBar::handle:horizontal {{
                background: {T_PANEL};
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {T_GREEN};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        """,
                self._tmnt_scale,
            )
        )
        L.addWidget(self.tree, stretch=1)

        self._drop_hint = QLabel("↕ Reorder — hold Ctrl to nest inside")
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setVisible(False)
        self._drop_hint.setStyleSheet(
            _scale_ss(
                "background:#534AB7;color:white;font-size:11px;padding:4px 8px;border-radius:4px;",
                self._tmnt_scale,
            )
        )
        L.addWidget(self._drop_hint)

    def set_theme(self, theme):
        self._theme = "tmnt"

    def _make_item(self, deck):
        due = _count_due_in_deck(deck)
        item = QTreeWidgetItem([deck["name"].upper()])
        item.setData(0, Qt.UserRole, deck.get("_id"))
        item.setData(0, Qt.UserRole + 1, str(due))
        item.setData(0, Qt.UserRole + 2, deck["name"])
        item.setData(0, Qt.UserRole + 3, _deck_total_cards(deck))
        for child in deck.get("children", []):
            item.addChild(self._make_item(child))
        return item

    def _blink_tick(self):
        return

    def refresh(self):
        sel_id = self._get_selected_id()
        expanded_ids = set()

        def _collect(item):
            if item.isExpanded():
                expanded_ids.add(item.data(0, Qt.UserRole))
            for i in range(item.childCount()):
                _collect(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _collect(self.tree.topLevelItem(i))

        self.tree.clear()
        for deck in self._data.get("decks", []):
            self.tree.addTopLevelItem(self._make_item(deck))

        def _restore(item):
            if item.data(0, Qt.UserRole) in expanded_ids:
                item.setExpanded(True)
            for i in range(item.childCount()):
                _restore(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _restore(self.tree.topLevelItem(i))

        if sel_id is not None:
            self._select_by_id(sel_id)


# ══════════════════════════════════════════════════════════════════════════════
#  LEFT SIDEBAR — Dojo Cave
# ══════════════════════════════════════════════════════════════════════════════
class TMNTSidebar(QFrame):
    deck_selected = pyqtSignal(object)  # emits deck dict
    new_deck = pyqtSignal()
    new_sub = pyqtSignal()

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._scale = _tmnt_scale(data)
        self._selected_deck = None
        self.setFixedWidth(_px(TMNT_SIDEBAR_W, self._scale))
        self.setObjectName("tmnt_sidebar1")
        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_sidebar1 {{
                background: {T_BG};
                border-right: 1px solid {T_BORDER};
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
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
        hl.setContentsMargins(
            _px(16, self._scale),
            _px(16, self._scale),
            _px(16, self._scale),
            _px(16, self._scale),
        )
        hl.setSpacing(_px(12, self._scale))

        title_row = QHBoxLayout()
        torii = QLabel("⛩")
        torii.setStyleSheet(
            _scale_ss(f"color: {T_GREEN}; font-size: 18px;", self._scale)
        )
        title = QLabel("DOJO CAVE")
        title.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: 14px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 2px;",
                self._scale,
            )
        )
        title_row.addWidget(torii)
        title_row.addWidget(title)
        title_row.addStretch()
        hl.addLayout(title_row)

        # Search box
        search_frame = QFrame()
        search_frame.setStyleSheet(
            _scale_ss(
                f"QFrame {{ background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 3px; }}"
                f"QLabel {{ border: none; }}",
                self._scale,
            )
        )
        search_frame.setFixedHeight(_px(32, self._scale))
        sl = QHBoxLayout(search_frame)
        sl.setContentsMargins(_px(8, self._scale), 0, _px(8, self._scale), 0)
        sl.setSpacing(_px(6, self._scale))
        search_icon = QLabel("⌕")
        search_icon.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 12px; border: none;", self._scale
            )
        )
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Search scrolls...")
        self.search_in.setStyleSheet(
            _scale_ss(
                f"background: transparent; border: none; color: {T_TEXT}; "
                f"font-family: {T_MONO}; font-size: 14px;",
                self._scale,
            )
        )
        self.search_in.textChanged.connect(self._on_search)
        kb_badge = QLabel("CTRL+K")
        kb_badge.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 9px; background: rgba(255,255,255,0.04); "
                f"border: 1px solid {T_BORDER}; border-radius: 2px; padding: 1px 3px;",
                self._scale,
            )
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
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 12px; font-weight: 900; "
                f"font-family: {T_MONO}; letter-spacing: 2px; "
                f"padding: 12px 0px 12px 0px; background: {T_BG};",
                self._scale,
            )
        )
        L.addWidget(dojos_lbl)

        # ── Real deck tree engine ──
        self._engine = TMNTDeckEngine(self._data, scale=self._scale, parent=self)
        self._engine.deck_selected.connect(self._on_deck_clicked)
        L.addWidget(self._engine, stretch=1)

        # ── Footer buttons ──
        foot = QWidget()
        foot.setStyleSheet(f"background: {T_BG}; border-top: 1px solid {T_BORDER};")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(
            _px(16, self._scale),
            _px(16, self._scale),
            _px(16, self._scale),
            _px(16, self._scale),
        )
        fl.setSpacing(_px(8, self._scale))

        def _foot_btn(text):
            b = QPushButton(text)
            b.setStyleSheet(
                _scale_ss(
                    f"""
                QPushButton {{
                    background: transparent;
                    color: {T_GREEN};
                    border: 1px solid {T_GREEN};
                    border-radius: 2px;
                    font-size: 12px;
                    font-weight: 900;
                    font-family: {T_PIXEL};
                    padding: 6px 8px;
                }}
                QPushButton:hover {{ background: rgba(69,162,71,0.12); }}
            """,
                    self._scale,
                )
            )
            return b

        btn_new = _foot_btn("⊕ NEW DOJO")
        btn_sub = _foot_btn("⊕ SUB Dojo")
        from PyQt5.QtGui import QIcon
        from PyQt5.QtCore import QSize

        btn_open = QPushButton()
        btn_open.setIcon(QIcon("assets/themes/dojo/sewer_icon.png"))
        btn_h = _px(34, self._scale)  # same height as NEW DOJO / SUB
        btn_w = _px(34, self._scale)  # square — logo is circular anyway
        btn_Icon_height = _px(74, self._scale)  # square — logo is circular anyway

        btn_open.setIconSize(
            QSize(btn_Icon_height, btn_Icon_height)
        )  # icon fills the whole button
        btn_open.setFixedSize(btn_w, btn_h)

        btn_open.setToolTip("Focus selected dojo")
        btn_open.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                border: none;          /* ← kill the border box */
                padding: 0px;
            }}
            QPushButton:hover {{
                background: transparent;
            }}
        """,
                self._scale,
            )
        )

        btn_new.clicked.connect(self._new_top)
        btn_sub.clicked.connect(self._new_child)
        btn_open.clicked.connect(self._focus_selected)
        fl.addWidget(btn_new, stretch=1)
        fl.addWidget(btn_sub, stretch=1)
        fl.addWidget(btn_open)
        L.addWidget(foot)

    def _on_deck_clicked(self, deck):
        self._selected_deck = deck
        self.deck_selected.emit(deck)

    def _on_search(self, text):
        self._engine._on_search(text)

    def _new_top(self):
        self._engine._new_deck(None)
        self._sync_from_engine()

    def _new_child(self):
        self._engine._new_subdeck()
        self._sync_from_engine()

    def _focus_selected(self):
        item = self._engine.tree.currentItem()
        if item:
            self._engine.tree.scrollToItem(item)

    def _sync_from_engine(self):
        self._selected_deck = self._engine.get_selected_deck()
        self.refresh()
        if self._selected_deck:
            self.deck_selected.emit(self._selected_deck)

    def refresh(self):
        decks = self._data.get("decks", [])
        selected_id = self._selected_deck.get("_id") if self._selected_deck else None
        if selected_id:
            self._selected_deck = find_deck_by_id(selected_id, decks)
        self._engine._data = self._data
        self._engine.refresh()
        if selected_id:
            self._engine._select_by_id(selected_id)

    def get_selected(self):
        return self._engine.get_selected_deck()

    def set_data(self, data):
        self._data = data
        self._engine._data = data
        self.refresh()


# ── Custom deck list widget (paints like HTML items) ─────────────────────────
class _TMNTDeckList(QScrollArea):
    deck_selected = pyqtSignal(object)

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._scale = _tmnt_scale(data)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"background: {T_BG}; border: none;")
        self._container = QWidget()
        self._container.setStyleSheet(f"background: {T_BG};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(
            _px(8, self._scale),
            _px(4, self._scale),
            _px(8, self._scale),
            _px(4, self._scale),
        )
        self._layout.setSpacing(_px(2, self._scale))
        self._layout.addStretch()
        self.setWidget(self._container)
        self._all_decks = []
        self._selected_id = None
        self._expanded_ids = set()
        self._buttons = []
        self._filter_text = ""

    def load(self, decks, selected_id=None):
        self._all_decks = decks
        if selected_id is not None:
            self._selected_id = selected_id
        self._render()

    def filter(self, text):
        self._filter_text = text.strip().lower()
        self._render()

    def ensure_selected_visible(self):
        for btn in self._buttons:
            if btn._deck.get("_id") == self._selected_id:
                self.ensureWidgetVisible(btn, 0, 64)
                break

    def _render(self):
        # Remove all but last stretch
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._buttons = []
        visible = 0
        for deck in self._all_decks:
            visible += self._add_deck(deck, depth=0)

        if visible == 0:
            empty = QLabel("No scrolls match search.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                _scale_ss(
                    f"color: {T_SUBTEXT}; font-size: 10px; "
                    f"font-family: {T_MONO}; padding: 24px 8px;",
                    self._scale,
                )
            )
            self._layout.insertWidget(self._layout.count() - 1, empty)

    def _add_deck(self, deck, depth):
        children = deck.get("children", [])
        name = deck.get("name", "").lower()
        name_match = (not self._filter_text) or (self._filter_text in name)
        deck_id = deck.get("_id")
        child_visible = any(self._should_show(child) for child in children)

        if not name_match and child_visible == 0:
            return 0

        selected = deck.get("_id") == self._selected_id
        expanded = bool(children) and (
            bool(self._filter_text)
            or deck_id in self._expanded_ids
            or self._has_selected_descendant(deck)
        )

        btn = _TMNTDeckItem(
            deck,
            data={"_font_size": int(self._scale * TMNT_BASE_SIZE)},
            depth=depth,
            selected=selected,
            expanded=expanded,
            has_children=bool(children),
        )
        btn.clicked_deck.connect(self._on_item_clicked)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        self._buttons.append(btn)

        rendered = 1
        if expanded or self._filter_text:
            for child in children:
                rendered += self._add_deck(child, depth + 1)
        return rendered

    def _should_show(self, deck):
        if not self._filter_text:
            return True
        if self._filter_text in deck.get("name", "").lower():
            return True
        return any(self._should_show(child) for child in deck.get("children", []))

    def _contains_selected(self, deck):
        if deck.get("_id") == self._selected_id:
            return True
        return any(self._contains_selected(child) for child in deck.get("children", []))

    def _has_selected_descendant(self, deck):
        for child in deck.get("children", []):
            if self._contains_selected(child):
                return True
        return False

    def _toggle_expanded(self, deck):
        deck_id = deck.get("_id")
        if deck_id in self._expanded_ids:
            self._expanded_ids.remove(deck_id)
        else:
            self._expanded_ids.add(deck_id)

    def _on_item_clicked(self, deck):
        self._selected_id = deck.get("_id")
        if deck.get("children"):
            self._toggle_expanded(deck)
        self._render()
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

    def __init__(
        self,
        deck,
        data=None,
        depth=0,
        selected=False,
        expanded=False,
        has_children=False,
        parent=None,
    ):
        super().__init__(parent)
        self._deck = deck
        self._scale = _tmnt_scale(data if isinstance(data, dict) else None)
        self._depth = depth
        self._selected = selected
        self._expanded = expanded
        self._has_children = has_children
        self.setCursor(Qt.PointingHandCursor)
        self._build()

    def _build(self):
        self.setFixedHeight(_px(44, self._scale))
        due = _count_due_in_deck(self._deck)
        name = self._deck.get("name", "?").upper()
        total_cards = _deck_total_cards(self._deck)
        is_complete = due == 0 and total_cards > 0
        indent = self._depth * _px(16, self._scale)

        if self._selected:
            bg = f"background: {T_PANEL};"
            border = f"border-left: 2px solid {T_PURPLE};"
        else:
            bg = "background: transparent;"
            border = "border-left: 2px solid transparent;"

        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame {{ {bg} {border}
                border-radius: 3px;
            }}
            QFrame:hover {{ background: {T_PANEL}; }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )

        l = QHBoxLayout(self)
        l.setContentsMargins(_px(8, self._scale) + indent, 0, _px(10, self._scale), 0)
        l.setSpacing(_px(8, self._scale))

        arrow_text = (
            "▼"
            if self._has_children and self._expanded
            else ("▶" if self._has_children else "•")
        )
        arrow = QLabel(arrow_text)
        arrow.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE if self._selected else T_SUBTEXT}; font-size: 9px;",
                self._scale,
            )
        )
        l.addWidget(arrow)

        icon = QLabel("🧠" if self._depth == 0 else "📜")
        icon.setStyleSheet(_scale_ss("font-size: 10px;", self._scale))
        l.addWidget(icon)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE if self._selected else T_TEXT}; "
                f"font-size: 9px; font-weight: 900; font-family: {T_PIXEL};",
                self._scale,
            )
        )
        l.addWidget(name_lbl, stretch=1)

        if is_complete:
            badge = QLabel("✓")
            badge.setStyleSheet(
                _scale_ss(f"color: {T_GREEN}; font-size: 13px;", self._scale)
            )
        elif due > 0:
            badge = QLabel(str(due))
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(_px(26, self._scale), _px(20, self._scale))
            badge.setStyleSheet(
                _scale_ss(
                    f"background: {T_RED}; color: white; font-size: 9px; "
                    f"font-weight: bold; border-radius: 3px; font-family: {T_MONO};",
                    self._scale,
                )
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
class TMNTMainContent(DeckView):
    """Centre panel: deck title, stat cards, mission banner, card list, action bar."""

    def __init__(self, data=None, parent=None):
        self._data = data if isinstance(data, dict) else {}
        self._scale = _tmnt_scale(data)
        self._theme = "tmnt"
        super().__init__(parent)
        self.setStyleSheet(f"background: #151821;")

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(
            _px(20, self._scale),
            _px(20, self._scale),
            _px(20, self._scale),
            _px(12, self._scale),
        )
        L.setSpacing(_px(14, self._scale))

        # ── Deck title row ──
        title_row = QHBoxLayout()
        title_row.setSpacing(_px(16, self._scale))

        self.lbl_deck_icon = QLabel("🏯")
        self.lbl_deck_icon.setFixedSize(_px(40, self._scale), _px(40, self._scale))
        self.lbl_deck_icon.setAlignment(Qt.AlignCenter)
        self.lbl_deck_icon.setStyleSheet(
            _scale_ss(
                f"font-size: 24px; background: {T_PANEL}; "
                f"border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )

        title_txt = QVBoxLayout()
        title_txt.setSpacing(_px(2, self._scale))
        self.lbl_deck = QLabel("SELECT A DOJO")
        self.lbl_deck.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: 24px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 1px; background: transparent;",
                self._scale,
            )
        )
        self.lbl_deck_sub = QLabel("SCROLLS: 0  ❖  DUE: 0")
        self.lbl_deck_sub.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 12px; font-weight: bold; "
                f"font-family: {T_MONO}; letter-spacing: 1px; background: transparent;",
                self._scale,
            )
        )
        self.lbl_stats = QLabel() # hidden, needed by DeckView
        self.lbl_stats.hide()
        
        title_txt.addWidget(self.lbl_deck)
        title_txt.addWidget(self.lbl_deck_sub)

        title_row.addWidget(self.lbl_deck_icon)
        title_row.addLayout(title_txt)
        title_row.addStretch()

        self.btn_add = QPushButton("🐢  FORGE SCROLL")
        self.btn_add.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: rgba(69,162,71,0.04);
                color: #58b85d;
                border: 1px solid #58b85d;
                border-radius: 2px;
                font-size: 12px;
                font-weight: 900;
                font-family: {T_PIXEL};
                padding: 8px 16px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: rgba(69,162,71,0.10); color: #78c97c; border-color: #78c97c; }}
        """,
                self._scale,
            )
        )
        self.btn_add.clicked.connect(self._add_card)
        _apply_glow(self.btn_add, "#58b85d", blur=_px(22, self._scale), alpha=95)
        title_row.addWidget(self.btn_add)
        L.addLayout(title_row)

        # ── 3 Stat Cards ──
        stats_row = QHBoxLayout()
        stats_row.setSpacing(_px(12, self._scale))
        self.stat_missions = TMNTStatCard(
            "REMAINING MISSIONS", "Cards due for review", T_RED, data=self._data
        )
        self.stat_scrolls = TMNTStatCard(
            "NEW TECHNIQUES", "Total active scrolls", T_PURPLE, data=self._data
        )
        self.stat_battles = TMNTStatCard(
            "BATTLES WON", "Reviews completed", T_GREEN, data=self._data
        )
        stats_row.addWidget(self.stat_missions)
        stats_row.addWidget(self.stat_scrolls)
        stats_row.addWidget(self.stat_battles)
        L.addLayout(stats_row)

        # ── Mission Banner ──
        self.banner = TMNTMissionBanner(data=self._data)
        self.btn_due = self.banner.btn_train
        self.btn_all = self.banner.btn_selected
        self.btn_due.clicked.connect(self._review_due)
        self.btn_all.clicked.connect(self._review_selected)
        L.addWidget(self.banner)

        # ── Card list area ──
        section_lbl = QLabel("SCROLL INVENTORY")
        section_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 10px; font-weight: 900; "
                f"font-family: {T_MONO}; letter-spacing: 2px; padding: 2px 0px 0px 2px;",
                self._scale,
            )
        )
        L.addWidget(section_lbl)

        list_frame = QFrame()
        list_frame.setObjectName("tmnt_card_list_frame1")
        list_frame.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_card_list_frame1 {{
                background: {T_BG};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
            }}
        """,
                self._scale,
            )
        )
        lf_l = QVBoxLayout(list_frame)
        lf_l.setContentsMargins(0, 0, 0, 0)

        self.card_list = QListWidget()
        self.card_list.setStyleSheet(
            _scale_ss(
                f"""
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
        """,
                self._scale,
            )
        )
        self.card_list.itemDoubleClicked.connect(
            lambda item: self._edit_card(item)
        )
        self.card_list.itemSelectionChanged.connect(self._sync_action_state)
        self.card_list.keyPressEvent = self._card_list_key_press
        self.card_list.setDragEnabled(True)
        self.card_list.setDragDropMode(QAbstractItemView.DragOnly)
        self.card_list.startDrag = self._start_card_drag

        # Empty state label
        self._empty_lbl = QLabel()
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_PIXEL}; font-size: 14px; "
                f"background: transparent; border: none;",
                self._scale,
            )
        )
        self._empty_lbl.setText("★\n\n— SELECT A DOJO TO BEGIN —")

        lf_l.addWidget(self.card_list)
        lf_l.addWidget(self._empty_lbl)
        L.addWidget(list_frame, stretch=1)

        # ── Bottom action bar ──
        bot = QHBoxLayout()
        bot.setSpacing(_px(10, self._scale))

        self.btn_edit = QPushButton("✏  Edit")
        self.btn_edit.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: {T_PANEL};
                color: {T_TEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: 14px;
                font-family: {T_MONO};
                padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {T_CARD}; color: white; }}
        """,
                self._scale,
            )
        )
        self.btn_edit.clicked.connect(
            lambda: self._edit_card(self.card_list.currentItem())
        )

        self.btn_delete_tmnt = QPushButton("🗑  DELETE")
        self.btn_delete_tmnt.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: {T_RED};
                border: 1px solid {T_RED};
                border-radius: 2px;
                font-size: 14px;
                font-weight: bold;
                font-family: {T_MONO};
                padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {T_RED}; color: white; }}
        """,
                self._scale,
            )
        )
        self.btn_delete_tmnt.clicked.connect(self._delete_card)
        _apply_glow(self.btn_delete_tmnt, T_RED, blur=_px(18, self._scale), alpha=100)

        bot.addWidget(self.btn_edit)
        bot.addWidget(self.btn_delete_tmnt)
        bot.addStretch()
        L.addLayout(bot)
        self._sync_action_state()

    def set_theme(self, theme):
        # Override DeckView's set_theme so it doesn't mess with our TMNT layout
        pass

    def _refresh(self):
        # Call the classic logic to populate the list and update the stats
        super()._refresh()
        
        direct_cards = self.deck.get("cards", []) if self.deck else []
        if not direct_cards:
            self.card_list.hide()
            self._empty_lbl.show()
            if self.deck:
                self._empty_lbl.setText("★\n\n— FORGE FIRST SCROLL TO BEGIN —")
            else:
                self.lbl_deck.setText("SELECT A DOJO")
                self._empty_lbl.setText("★\n\n— SELECT A DOJO TO BEGIN —")
        else:
            self.card_list.show()
            self._empty_lbl.hide()
            
        self._sync_action_state()

    def _sync_action_state(self):
        has_deck = self.deck is not None
        has_card = self.card_list.currentRow() >= 0 and self.card_list.count() > 0
        self.btn_add.setEnabled(has_deck)
        self.btn_edit.setEnabled(has_card)
        self.btn_delete_tmnt.setEnabled(has_card)
        self.btn_all.setEnabled(has_card)

    def clear(self):
        self._deck_id = None
        self.deck = None
        self.lbl_deck.setText("SELECT A DOJO")
        self.lbl_deck_sub.setText("SCROLLS: 0  ❖  DUE: 0")
        self.stat_missions.set_value(0)
        self.stat_scrolls.set_value(0)
        self.stat_battles.set_value(0)
        self.card_list.clear()
        self.card_list.hide()
        self._empty_lbl.setText("★\n\n— SELECT A DOJO TO BEGIN —")
        self._empty_lbl.show()
        self.btn_due.setEnabled(False)
        self._sync_action_state()

# ══════════════════════════════════════════════════════════════════════════════
class TMNTBgmWidget(QFrame):
    clicked = pyqtSignal()

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._scale = _tmnt_scale(data)
        self._playing = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(_px(26, self._scale))
        self.setStyleSheet(
            _scale_ss(
                f"QFrame {{ background: {T_PANEL}; border: 1px solid {T_BORDER}; border-radius: 2px; }}",
                self._scale,
            )
        )

        l = QHBoxLayout(self)
        l.setContentsMargins(
            _px(12, self._scale),
            _px(3, self._scale),
            _px(12, self._scale),
            _px(3, self._scale),
        )
        l.setSpacing(_px(8, self._scale))

        self.note_lbl = QLabel("♫")
        self.note_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE}; font-size: 12px; font-weight: bold;", self._scale
            )
        )
        self.text_lbl = QLabel("BGM")
        self.text_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_TEXT}; font-size: 12px; font-weight: bold; font-family: {T_MONO};",
                self._scale,
            )
        )
        self.badge_lbl = QLabel("OFF")
        self.badge_lbl.setAlignment(Qt.AlignCenter)
        self.badge_lbl.setFixedWidth(_px(30, self._scale))
        self.badge_lbl.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; color: {T_SUBTEXT}; border-radius: 3px; "
                f"font-size: 10px; font-weight: 900; font-family: {T_MONO}; padding: 1px 4px;",
                self._scale,
            )
        )
        l.addWidget(self.note_lbl)
        l.addWidget(self.text_lbl)
        l.addWidget(self.badge_lbl)
        self.set_playing(False)

    def set_playing(self, playing):
        self._playing = bool(playing)
        if self._playing:
            self.note_lbl.setStyleSheet(
                _scale_ss(
                    f"color: {T_NEON}; font-size: 12px; font-weight: bold;", self._scale
                )
            )
            self.badge_lbl.setText("ON")
            self.badge_lbl.setStyleSheet(
                _scale_ss(
                    f"background: {T_PURPLE}; color: white; border-radius: 3px; "
                    f"font-size: 10px; font-weight: 900; font-family: {T_MONO}; padding: 1px 4px;",
                    self._scale,
                )
            )
        else:
            self.note_lbl.setStyleSheet(
                _scale_ss(
                    f"color: {T_PURPLE}; font-size: 12px; font-weight: bold;",
                    self._scale,
                )
            )
            self.badge_lbl.setText("OFF")
            self.badge_lbl.setStyleSheet(
                _scale_ss(
                    f"background: {T_BG}; color: {T_SUBTEXT}; border-radius: 3px; "
                    f"font-size: 10px; font-weight: 900; font-family: {T_MONO}; padding: 1px 4px;",
                    self._scale,
                )
            )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ══════════════════════════════════════════════════════════════════════════════
#  TOP BAR
# ══════════════════════════════════════════════════════════════════════════════
class TMNTTopBar(QFrame):
    btn_math_clicked = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_theme_clicked = pyqtSignal()
    btn_help_clicked = pyqtSignal()
    btn_about_clicked = pyqtSignal()
    font_change = pyqtSignal(int)  # -1 / 0 / +1
    bgm_toggle = pyqtSignal()

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._scale = _tmnt_scale(data)
        self.setObjectName("tmnt_topbar1")
        self.setFixedHeight(_px(52, self._scale))
        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_topbar1 {{
                background: {T_BG};
                border-bottom: 1px solid {T_BORDER};
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
        self._build_ui()
        self._quote_idx = 0
        self._quote_timer = QTimer(self)
        self._quote_timer.timeout.connect(self._rotate_quote)
        self._quote_timer.start(8000)

    def _build_ui(self):
        L = QHBoxLayout(self)
        L.setContentsMargins(_px(16, self._scale), 0, _px(16, self._scale), 0)
        L.setSpacing(_px(14, self._scale))

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_l = QHBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(_px(12, self._scale))

        logo_box = QFrame()
        logo_box.setStyleSheet(
            _scale_ss(
                f"QFrame {{ border: 2px solid {T_GREEN}; border-radius: 4px; "
                f"background: transparent; padding: 2px 6px; }}"
                f"QLabel {{ border: none; }}",
                self._scale,
            )
        )
        logo_box.setFixedSize(_px(46, self._scale), _px(38, self._scale))
        ll = QHBoxLayout(logo_box)
        ll.setContentsMargins(0, 0, 0, 0)
        logo_icon = QLabel("🐢")
        logo_icon.setStyleSheet(
            _scale_ss("font-size: 22px; border: none;", self._scale)
        )
        logo_icon.setAlignment(Qt.AlignCenter)
        # ll.addWidget(logo_icon)
        # left_l.addWidget(logo_box, 0, Qt.AlignVCenter)

        app_name = QLabel("ANKI OCCLUSION")
        app_name.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-size: 18px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 2px;",
                self._scale,
            )
        )
        left_l.addWidget(app_name, 0, Qt.AlignVCenter)
        left_l.addStretch()
        L.addWidget(left, 1)

        # ── Nav buttons ──
        def _nav(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                _scale_ss(
                    f"""
                QPushButton {{
                background: transparent;
                color: {T_SUBTEXT};
                border: none;
                border-bottom: 2px solid transparent;
                font-family: {T_MONO};
                font-size: 12px;
                font-weight: bold;
                padding: 6px 8px;
                letter-spacing: 1px;
                text-transform: uppercase;
            }}
                QPushButton:hover {{
                    color: {T_GREEN};
                    border-bottom: 2px solid {T_GREEN};
                }}
            """,
                    self._scale,
                )
            )
            return b

        btn_math = _nav("📘 MATH", "Math Trainer")
        btn_journal = _nav("📜 JOURNAL", "Daily Journal")
        btn_theme = _nav("🖥 CLASSIC MODE", "Switch Theme")
        btn_help = _nav("❓ HELP", "Help")
        btn_about = _nav("ⓘ ABOUT", "About")

        btn_math.clicked.connect(self.btn_math_clicked)
        btn_journal.clicked.connect(self.btn_journal_clicked)
        btn_theme.clicked.connect(self.btn_theme_clicked)
        btn_help.clicked.connect(self.btn_help_clicked)
        btn_about.clicked.connect(self.btn_about_clicked)

        center = QWidget()
        center.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        center_l = QHBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(_px(10, self._scale))
        center_l.addStretch()
        for b in (btn_math, btn_journal, btn_theme, btn_help, btn_about):
            center_l.addWidget(b, 0, Qt.AlignCenter)
        center_l.addStretch()
        L.addWidget(center, 1)

        # ── Font buttons ──
        def _font_btn(text, delta):
            b = QPushButton(text)
            b.setFixedSize(_px(28, self._scale), _px(26, self._scale))
            b.setStyleSheet(
                _scale_ss(
                    f"""
                QPushButton {{
                    background: {T_PANEL};
                    color: {T_SUBTEXT};
                    border: 1px solid {T_BORDER};
                    border-radius: 2px;
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {T_CARD}; color: {T_TEXT}; border-color: {T_GREEN}; }}
            """,
                    self._scale,
                )
            )
            b.clicked.connect(lambda _, d=delta: self.font_change.emit(d))
            return b

        right = QWidget()
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_l = QHBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(_px(10, self._scale))
        right_l.addStretch()

        font_box = QWidget()
        font_l = QHBoxLayout(font_box)
        font_l.setContentsMargins(0, 0, 0, 0)
        font_l.setSpacing(_px(2, self._scale))
        font_l.addWidget(_font_btn("A−", -1))
        font_l.addWidget(_font_btn("A", 0))
        font_l.addWidget(_font_btn("A+", +1))
        right_l.addWidget(font_box, 0, Qt.AlignVCenter)

        self.bgm_widget = TMNTBgmWidget(
            data={"_font_size": int(round(TMNT_BASE_SIZE * self._scale))}
        )
        self.bgm_widget.clicked.connect(self.bgm_toggle)
        right_l.addWidget(self.bgm_widget, 0, Qt.AlignVCenter)

        # ── Mentor / Quote card ──
        mentor = QFrame()
        mentor.setFixedSize(_px(236, self._scale), _px(40, self._scale))
        mentor.setStyleSheet(
            _scale_ss(
                f"""
            QFrame {{
                background: rgba(176,136,249,0.08);
                border: 1px solid {T_PURPLE};
                border-radius: 4px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
        ml = QHBoxLayout(mentor)
        ml.setContentsMargins(
            _px(8, self._scale),
            _px(4, self._scale),
            _px(8, self._scale),
            _px(4, self._scale),
        )
        ml.setSpacing(_px(8, self._scale))

        av = QLabel("🐢")
        av.setFixedSize(_px(30, self._scale), _px(30, self._scale))
        av.setAlignment(Qt.AlignCenter)
        av.setStyleSheet(
            _scale_ss(
                f"font-size: 20px; background: rgba(176,136,249,0.15); "
                f"border: 1px solid {T_PURPLE}; border-radius: 15px;",
                self._scale,
            )
        )
        ml.addWidget(av)

        self.quote_lbl = QLabel(MENTOR_QUOTES[0][0])
        self.quote_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE}; font-size: 7px; font-weight: 900; "
                f"font-family: {T_PIXEL}; line-height: 1.4;",
                self._scale,
            )
        )
        self.name_lbl = QLabel(MENTOR_QUOTES[0][1])
        self.name_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 14px; font-family: {T_MONO};",
                self._scale,
            )
        )
        q_col = QVBoxLayout()
        q_col.setSpacing(0)
        q_col.addWidget(self.quote_lbl)
        q_col.addWidget(self.name_lbl)
        ml.addLayout(q_col)
        right_l.addWidget(mentor, 0, Qt.AlignVCenter)
        L.addWidget(right, 1)

    def _rotate_quote(self):
        self._quote_idx = (self._quote_idx + 1) % len(MENTOR_QUOTES)
        q, n = MENTOR_QUOTES[self._quote_idx]
        self.quote_lbl.setText(q)
        self.name_lbl.setText(n)

    def set_bgm_state(self, playing):
        self.bgm_widget.set_playing(playing)


# ══════════════════════════════════════════════════════════════════════════════
#  FOOTER
# ══════════════════════════════════════════════════════════════════════════════
class TMNTFooter(QFrame):
    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._scale = _tmnt_scale(data)
        self.setFixedHeight(_px(22, self._scale))
        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame {{ background: {T_BG}; border-top: 1px solid {T_BORDER}; border-radius: 0px; }}
            QLabel {{ background: transparent; border: none; }}
        """,
                self._scale,
            )
        )
        L = QHBoxLayout(self)
        L.setContentsMargins(_px(12, self._scale), 0, _px(12, self._scale), 0)
        L.setSpacing(_px(12, self._scale))

        def _status(icon, text, color):
            lbl = QLabel(f"{icon}  {text}")
            lbl.setStyleSheet(
                _scale_ss(
                    f"color: {color}; font-size: 8px; font-family: {T_MONO}; font-weight: bold;",
                    self._scale,
                )
            )
            return lbl

        L.addWidget(_status("✅", "SM-2 Active", T_GREEN))
        sep = QLabel("|")
        sep.setStyleSheet(_scale_ss(f"color: {T_BORDER}; font-size: 8px;", self._scale))
        L.addWidget(sep)
        pdf_text = (
            "PyMuPDF loaded — PDF support active"
            if PDF_SUPPORT
            else "⚠ pip install pymupdf for PDF support"
        )
        pdf_col = T_GREEN if PDF_SUPPORT else T_RED
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
    btn_math_clicked = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_theme_clicked = pyqtSignal()
    btn_help_clicked = pyqtSignal()
    btn_about_clicked = pyqtSignal()
    font_change = pyqtSignal(int)
    bgm_toggle = pyqtSignal()
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        """
        data          — the global app data dict
        """
        super().__init__(parent)
        self._data = data
        self._scale = _tmnt_scale(data)
        self._selected_deck = None
        self._setup_ui()
        self._wire_signals()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # Top bar
        self.topbar = TMNTTopBar(data=self._data)
        L.addWidget(self.topbar)

        # Body (sidebar + main + right)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = TMNTSidebar(self._data)
        self.main = TMNTMainContent(data=self._data)
        self.banga = TMNTBangaLab(data=self._data)

        body.addWidget(self.sidebar)
        body.addWidget(self.main, stretch=1)
        body.addWidget(self.banga)

        body_w = QWidget()
        body_w.setLayout(body)
        body_w.setStyleSheet(f"background: #151821;")
        L.addWidget(body_w, stretch=1)

        # Footer
        self.footer = TMNTFooter(data=self._data)
        L.addWidget(self.footer)

    def _wire_signals(self):
        # Topbar → HomeScreen
        self.topbar.btn_math_clicked.connect(self.btn_math_clicked)
        self.topbar.btn_journal_clicked.connect(self.btn_journal_clicked)
        self.topbar.btn_theme_clicked.connect(self.btn_theme_clicked)
        self.topbar.btn_help_clicked.connect(self.btn_help_clicked)
        self.topbar.btn_about_clicked.connect(self.btn_about_clicked)
        self.topbar.font_change.connect(self.font_change)
        self.topbar.bgm_toggle.connect(self.bgm_toggle)

        # Sidebar deck selection
        self.sidebar.deck_selected.connect(self._on_deck_selected)
        self.sidebar.new_deck.connect(self._new_deck)
        self.sidebar.new_sub.connect(self._new_sub)



    # ── Deck ops ─────────────────────────────────────────────────────────────
    def _on_deck_selected(self, deck):
        self._selected_deck = deck
        self.main.load_deck(deck, self._data)
        self.deck_selected.emit(deck)

    def _new_deck(self):
        from PyQt5.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "New Dojo", "Dojo name:")
        if ok and name.strip():
            deck = {
                "_id": next_deck_id(self._data),
                "name": name.strip(),
                "cards": [],
                "children": [],
                "created": datetime.now().isoformat(),
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
                "_id": next_deck_id(self._data),
                "name": name.strip(),
                "cards": [],
                "children": [],
                "created": datetime.now().isoformat(),
            }
            self._selected_deck.setdefault("children", []).append(child)
            store.mark_dirty()
            self.refresh()

    def _reload_main(self):
        """Reload main content from fresh deck data."""
        if self._selected_deck:
            fresh = find_deck_by_id(
                self._selected_deck.get("_id"), self._data.get("decks", [])
            )
            if fresh:
                self._selected_deck = fresh
                self.main.load_deck(fresh, self._data)
        self.sidebar.refresh()
        self.banga.refresh()

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
                self._selected_deck.get("_id"), self._data.get("decks", [])
            )
            if fresh:
                self._selected_deck = fresh
                self.main.load_deck(fresh, self._data)
            else:
                self._selected_deck = None
                self.main.clear()
        else:
            self.main.clear()
        self.banga.refresh()

    def get_selected_deck(self):
        return self._selected_deck

    def set_bgm_state(self, playing):
        self.topbar.set_bgm_state(playing)

    def select_deck_by_id(self, deck_id):
        if not deck_id:
            return
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self.sidebar._selected_deck = deck
        self.sidebar.refresh()
        self._on_deck_selected(deck)
ng):
        self.topbar.set_bgm_state(playing)

    def select_deck_by_id(self, deck_id):
        if not deck_id:
            return
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self.sidebar._selected_deck = deck
        self.sidebar.refresh()
        self._on_deck_selected(deck)
esh:
                self._selected_deck = fresh
                self.main.load_deck(fresh, self._data)
            else:
                self._selected_deck = None
                self.main.clear()
        else:
            self.main.clear()
        self.banga.refresh()

    def get_selected_deck(self):
        return self._selected_deck

    def set_bgm_state(self, playing):
        self.topbar.set_bgm_state(playing)

    def select_deck_by_id(self, deck_id):
        if not deck_id:
            return
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self.sidebar._selected_deck = deck
        self.sidebar.refresh()
        self._on_deck_selected(deck)
