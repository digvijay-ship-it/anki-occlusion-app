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
   └─────────────────┴────────────────────────┴─────────────────────┘
"""

import importlib.util
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
    QFileDialog,
    QSlider,
    QShortcut,
)
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QSettings,
    QSize,
    QAbstractAnimation,
    pyqtSignal,
    QRect,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
    QEvent,
)
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPixmap,
    QPainterPath,
    QLinearGradient,
    QCursor,
    QKeySequence,
)

from sm2_engine import sm2_init, is_due_today, sm2_days_left
from data_manager import deck_history, find_deck_by_id, next_deck_id, store
from perf_utils import build_deck_rollups
from services import shortcut_manager
from storage_paths import (
    app_resource_path,
    app_resource_url,
    archive_label,
    archive_tooltip,
    current_data_file,
    get_mission_archive_root,
    migrate_to_mission_archive,
)
from ui.deck_tree import DeckTree, _DeckTreeWidget, depth_color
from ui.deck_view import DeckView
from ui.canvas.retro_effects import CRTOverlay, RetroParticlePanel, ParticleBurstOverlay, OozeDripWidget


_PDF_SUPPORT_AVAILABLE = None


def _pdf_support_available():
    global _PDF_SUPPORT_AVAILABLE
    if _PDF_SUPPORT_AVAILABLE is None:
        _PDF_SUPPORT_AVAILABLE = importlib.util.find_spec("fitz") is not None
    return _PDF_SUPPORT_AVAILABLE

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
T_HEADER = "'Orbitron', 'Oxanium', 'Segoe UI Black', sans-serif"
T_PIXEL = T_HEADER

def _hex_to_rgba(hex_str: str, alpha: float) -> str:
    if not hex_str or not isinstance(hex_str, str):
        return f"rgba(102, 252, 241, {alpha})"
    hex_str = hex_str.strip().lstrip('#')
    if len(hex_str) == 6:
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    elif len(hex_str) == 3:
        r = int(hex_str[0] * 2, 16)
        g = int(hex_str[1] * 2, 16)
        b = int(hex_str[2] * 2, 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    return f"rgba(102, 252, 241, {alpha})"

def sync_theme_colors():
    global T_BG, T_PANEL, T_CARD, T_GREEN, T_NEON, T_TEXT, T_SUBTEXT, T_RED, T_PURPLE, T_BORDER, T_MONO, T_HEADER, T_PIXEL
    try:
        from PyQt5.QtWidgets import QApplication
        from theme_manager import get_palette
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "tmnt")
        if theme not in ("tmnt", "manhattan"):
            theme = "tmnt"
        p = get_palette(theme)
        
        T_BG = p.get("C_BG", "#0A0B11")
        T_PANEL = p.get("C_SURFACE", "#141A24")
        T_CARD = p.get("C_CARD", "#1F2836")
        T_GREEN = p.get("C_GREEN", "#39FF14")
        T_NEON = p.get("C_ACCENT", "#39FF14")
        T_TEXT = p.get("C_TEXT", "#FFFFFF")
        T_SUBTEXT = p.get("C_SUBTEXT", "#A0AEC0")
        T_RED = p.get("C_RED", "#FF5A66")
        T_PURPLE = p.get("C_PURPLE", "#B084FF")
        T_BORDER = p.get("C_BORDER", "#3E4E68")
        T_MONO = p.get("body_font", "'Roboto Mono', 'Courier New', monospace")
        T_HEADER = p.get("header_font", "'Orbitron', 'Oxanium', 'Segoe UI Black', sans-serif")
        T_PIXEL = T_HEADER
    except Exception as e:
        print(f"[DEBUG][tmnt_home] sync_theme_colors error: {e}")
TMNT_BASE_SIZE = 11
TMNT_SIDEBAR_W = int(228 * 1.2)
TMNT_RIGHTBAR_W = int(218 * 1.2)
_PX_RE = re.compile(r"(-?\d+(?:\.\d+)?)px")
HOME_ANIMATIONS_ENV = "ANKI_HOME_ANIMATIONS"

MENTOR_QUOTES = [
    ('"FOCUS. TRAIN. MASTER."', "— DONATELLO"),
    ('"KNOWLEDGE IS THE WEAPON."', "— SPLINTER"),
    ('"COWABUNGA, DUDE!"', "— MICHELANGELO"),
    ('"NEVER STOP LEARNING."', "— LEONARDO"),
    ('"SCIENCE NEVER FAILS."', "— DONATELLO"),
]


def _home_animations_enabled():
    raw = os.environ.get(HOME_ANIMATIONS_ENV, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    from data_manager import store
    try:
        user_override = store.get().get("_home_animations")
        if user_override is not None:
            return bool(user_override)
    except Exception:
        pass
    return False


# ── Helper: header-font label ────────────────────────────────────────────────
def _px_lbl(text, color=None, size=10, weight="900"):
    global T_NEON, T_PIXEL
    if color is None:
        color = T_NEON
    l = QLabel(text)
    l.setStyleSheet(
        f"font-family: {T_PIXEL}; font-size: {size}px; font-weight: {weight}; "
        f"color: {color}; background: transparent; border: none;"
    )
    return l


def _mono_lbl(text, color=None, size=11, weight="normal"):
    global T_TEXT, T_MONO
    if color is None:
        color = T_TEXT
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

    def _row_rect(self, option):
        rect = option.rect.adjusted(
            _px(2, self._scale),
            _px(1, self._scale),
            -_px(2, self._scale),
            -_px(1, self._scale),
        )
        tree = self.parent()
        viewport = tree.viewport() if tree is not None and hasattr(tree, "viewport") else None
        if viewport is not None:
            viewport_right = viewport.width() - _px(6, self._scale)
            if viewport_right > rect.right():
                rect.setRight(viewport_right)
        return rect

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered = bool(option.state & QStyle.State_MouseOver)
        rect = self._row_rect(option)

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
        bookmarked = index.data(Qt.UserRole + 5)
        is_paused = bool(index.data(Qt.UserRole + 6))
        if bookmarked:
            name = "🔖 " + name
        if is_paused:
            name = "⏸️ " + name
        due_str = index.data(Qt.UserRole + 1)
        total_cards = int(index.data(Qt.UserRole + 3) or 0)
        due = int(due_str) if due_str else 0
        is_complete = due == 0 and total_cards > 0

        depth = index.data(Qt.UserRole + 4) or 0
        if is_paused:
            text_color = QColor("#FFB86C" if not is_selected else "#FFFFFF")
        else:
            text_color = QColor(T_PURPLE if is_selected else depth_color(depth, "tmnt"))
        font = QFont("Press Start 2P")
        font.setPixelSize(_px(10, self._scale))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text_color)

        badge_w = _px(54 if (is_paused and due > 0) else (48 if is_paused else 26), self._scale)
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

        if is_paused:
            painter.setPen(QPen(QColor("#FFB86C"), 1))
            painter.setBrush(QColor(40, 42, 54, 220))
            painter.drawRoundedRect(
                badge_rect, _px(3, self._scale), _px(3, self._scale)
            )
            badge_font = QFont("Roboto Mono")
            badge_font.setPixelSize(_px(9 if due > 0 else 8, self._scale))
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setPen(QColor("#FFB86C"))
            badge_txt = f"⏸ {due}" if due > 0 else "PAUSED"
            painter.drawText(badge_rect, Qt.AlignCenter, badge_txt)
        elif due > 0:
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
        bookmarked = index.data(Qt.UserRole + 5)
        if bookmarked:
            name = "🔖 " + name
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
        self.setFixedHeight(_px(100, self._scale))

    def _setup(self, title, subtitle, color):
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        if theme_name not in ("tmnt", "manhattan"):
            theme_name = "tmnt"

        self.setStyleSheet(
            _scale_ss(
                f"""
            QFrame#tmnt_stat_card1 {{
                background: {T_CARD};
                border: 1px solid {T_BORDER};
                border-left: 3px solid {color};
                border-radius: 4px;
            }}
            QFrame#tmnt_stat_card1:hover {{ background: #2b2f3b; border-color: {color}; }}
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
        
        val_size = 32
        self.val_lbl = QLabel("0")
        self.val_lbl.setStyleSheet(
            _scale_ss(
                f"color: {color}; font-size: {val_size}px; font-weight: 900; "
                f"font-family: {T_PIXEL}; background: transparent; border: none;",
                self._scale,
            )
        )
        val_font = QFont("Orbitron")
        val_font.setPixelSize(_px(val_size, self._scale))
        val_font.setBold(True)
        self.val_lbl.setFont(val_font)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_TEXT}; font-size: 10px; font-weight: 900; "
                f"font-family: {T_MONO}; letter-spacing: 1px; background: transparent; border: none;",
                self._scale,
            )
        )
        t_font = QFont(T_MONO)
        t_font.setPixelSize(_px(10, self._scale))
        t_font.setBold(True)
        t_lbl.setFont(t_font)
        t_lbl.setWordWrap(True)

        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-size: 10px; "
                f"font-family: {T_MONO}; background: transparent; border: none;",
                self._scale,
            )
        )
        s_font = QFont(T_MONO)
        s_font.setPixelSize(_px(10, self._scale))
        s_lbl.setFont(s_font)
        s_lbl.setWordWrap(True)

        txt.addWidget(self.val_lbl)
        txt.addWidget(t_lbl)
        txt.addWidget(s_lbl)
        l.addLayout(txt)
        l.addStretch()

    def set_value(self, v):
        self.val_lbl.setText(str(v))


# ══════════════════════════════════════════════════════════════════════════════
#  HTMLButton (Custom clickable QLabel for rich HTML layouts)
# ══════════════════════════════════════════════════════════════════════════════
class HTMLButton(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.RichText)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
#  MISSION BANNER
# ══════════════════════════════════════════════════════════════════════════════
class TMNTMissionBanner(QFrame):
    train_clicked = pyqtSignal()
    selected_clicked = pyqtSignal()
    resume_clicked = pyqtSignal()
    practice_clicked = pyqtSignal()
    review_new_clicked = pyqtSignal()
    GLOW_INTERVAL_MS = 50

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self.setObjectName("tmnt_banner1")
        self._scale = _tmnt_scale(data)
        # Determine theme name
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        if theme_name not in ("tmnt", "manhattan"):
            theme_name = "tmnt"

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
        
        title_text = "⚔  STAGE COMBAT" if theme_name == "manhattan" else "⚔  TRAINING MISSION"
        title_size = 12
        title = QLabel(title_text)
        title.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE}; font-size: {title_size}px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 1px; background: transparent; border: none;",
                self._scale,
            )
        )
        title_font = QFont("Orbitron")
        title_font.setPixelSize(_px(title_size, self._scale))
        title_font.setBold(True)
        title.setFont(title_font)
        title.setWordWrap(True)

        desc_text = "Stop Shredder's project and clear the levels!" if theme_name == "manhattan" else "Continue your training and defeat the due cards!"
        desc = QLabel(desc_text)
        desc.setStyleSheet(
            _scale_ss(
                f"color: {T_TEXT}; font-size: 14px; font-family: {T_MONO}; background: transparent; border: none;",
                self._scale,
            )
        )
        desc_font = QFont(T_MONO)
        desc_font.setPixelSize(_px(14, self._scale))
        desc.setFont(desc_font)
        desc.setWordWrap(True)

        quote_text = "> Pizza time! 🍕_" if theme_name == "manhattan" else "> Cowabunga! 🐢_"
        self.quote = QLabel(quote_text)
        self.quote.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: 12px; font-weight: bold; "
                f"font-family: {T_MONO}; background: transparent; border: none;",
                self._scale,
            )
        )
        quote_font = QFont(T_MONO)
        quote_font.setPixelSize(_px(12, self._scale))
        quote_font.setBold(True)
        self.quote.setFont(quote_font)

        left.addWidget(title)
        left.addWidget(desc)
        left.addWidget(self.quote)
        left.addStretch()
        l.addLayout(left)
        l.addStretch()

        right = QVBoxLayout()
        right.setSpacing(_px(20, self._scale))

        if theme_name == "manhattan":
            btn_train_text = "▶  FIGHT FOOT CLAN\nREVIEW DUE COMBATS"
            btn_selected_text = "🌱  REVIEW LEAST MATURE"
        else:
            btn_train_text = "▶  START TRAINING\nREVIEW DUE SCROLLS"
            btn_selected_text = "🌱  REVIEW LEAST MATURE"
        btn_train_size = 14
        btn_train_family = "Orbitron"
        btn_selected_size = 12
        btn_selected_family = T_MONO
        btn_selected_bold = True

        top_size = _px(16.5, self._scale)
        sub_size = _px(10, self._scale)
        if theme_name == "manhattan":
            btn_train_html = f"""
            <div style="line-height: 1.1;">
                <span style="font-family: {btn_train_family}; font-size: {top_size}px; font-weight: 900; color: #07070B;">▶  FIGHT FOOT CLAN</span><br/>
                <span style="font-family: {btn_train_family}; font-size: {sub_size}px; font-weight: 700; color: rgba(7, 7, 11, 0.6);">REVIEW DUE COMBATS</span>
            </div>
            """
        else:
            btn_train_html = f"""
            <div style="line-height: 1.1;">
                <span style="font-family: {btn_train_family}; font-size: {top_size}px; font-weight: 900; color: #07070B;">▶  START TRAINING</span><br/>
                <span style="font-family: {btn_train_family}; font-size: {sub_size}px; font-weight: 700; color: rgba(7, 7, 11, 0.6);">REVIEW DUE SCROLLS</span>
            </div>
            """

        base_w = _px(240, self._scale)
        base_h = _px(76, self._scale)

        self.btn_train_container = QWidget()
        self.btn_train_container.setObjectName("btnTrainContainer")
        self.btn_train_container.setStyleSheet("background:transparent; border:none;")
        self.btn_train_container.setFixedSize(base_w, base_h)

        self.btn_train = HTMLButton(btn_train_html, self.btn_train_container)
        self.btn_train.setObjectName("btnTrain")
        self.btn_train.setStyleSheet(
            _scale_ss(
                f"""
            QLabel#btnTrain {{
                background: #72FF4F;
                border: 2px solid #72FF4F;
                border-radius: 4px;
                min-width: 240px;
            }}
            QLabel#btnTrain:hover {{
                background: white;
                border-color: white;
            }}
        """,
                self._scale,
            )
        )
        self.btn_train.setFixedSize(base_w, base_h)
        self.btn_train.move(0, 0)
        self.btn_train.clicked.connect(self.train_clicked)
        _apply_glow(self.btn_train, "#72FF4F", blur=_px(16, self._scale), alpha=100)

        self.btn_selected = QPushButton(btn_selected_text)
        self.btn_selected.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: #8BE9FD;
                border: 1px solid #8BE9FD;
                border-radius: 2px;
                font-size: {btn_selected_size}px;
                font-weight: 700;
                font-family: {btn_selected_family};
                letter-spacing: 1px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{ background: rgba(139, 233, 253, 0.1); color: #A4F0FF; border-color: #A4F0FF; }}
            QPushButton:disabled {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
            }}
        """,
                self._scale,
            )
        )
        self.btn_selected.clicked.connect(self.selected_clicked)
        self.btn_selected.setToolTip("Review cards starting with least mature / lowest retention score first")
        
        btn_sel_font = QFont(btn_selected_family)
        btn_sel_font.setPixelSize(_px(btn_selected_size, self._scale))
        btn_sel_font.setBold(btn_selected_bold)
        self.btn_selected.setFont(btn_sel_font)

        self.btn_review_new = QPushButton("✨  REVIEW NEW (0)")
        self.btn_review_new.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: #BD93F9;
                border: 1px solid #BD93F9;
                border-radius: 2px;
                font-size: {btn_selected_size}px;
                font-weight: 700;
                font-family: {btn_selected_family};
                letter-spacing: 1px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{ background: rgba(189, 147, 249, 0.12); color: #D6ACFF; border-color: #D6ACFF; }}
            QPushButton:disabled {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
            }}
        """,
                self._scale,
            )
        )
        self.btn_review_new.setFont(btn_sel_font)
        self.btn_review_new.clicked.connect(self.review_new_clicked)
        self.btn_review_new.setToolTip("Review only brand-new cards (skipping due / previously reviewed cards)")
        self.btn_review_new.setEnabled(False)

        self.btn_resume = QPushButton("⚡  RESUME LAST MISSION")
        self.btn_resume.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: #ff9f43;
                color: #07070b;
                border: 2px solid #ff9f43;
                border-radius: 4px;
                font-size: {btn_selected_size}px;
                font-weight: 900;
                font-family: {btn_selected_family};
                letter-spacing: 1px;
                padding: 10px 16px;
            }}
            QPushButton:hover {{
                background: white;
                color: #07070b;
                border-color: white;
            }}
            QPushButton:disabled {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 2px solid {T_BORDER};
            }}
        """,
                self._scale,
            )
        )
        self.btn_resume.clicked.connect(self.resume_clicked)
        self.btn_resume.setVisible(True)
        self.btn_resume.setEnabled(False)
        _apply_glow(self.btn_resume, "#ff9f43", blur=_px(16, self._scale), alpha=120)

        self.btn_practice = QPushButton("🎯  PRACTICE ALL")
        self.btn_practice.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: #72FF4F;
                border: 1px solid #72FF4F;
                border-radius: 2px;
                font-size: {btn_selected_size}px;
                font-weight: 700;
                font-family: {btn_selected_family};
                letter-spacing: 1px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{ background: rgba(114,255,79,0.1); color: #8BFF6B; border-color: #8BFF6B; }}
            QPushButton:disabled {{
                background: transparent;
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
            }}
        """,
                self._scale,
            )
        )
        self.btn_practice.setFont(btn_sel_font)
        self.btn_practice.clicked.connect(self.practice_clicked)

        right.addWidget(self.btn_train_container)
        right.addWidget(self.btn_resume)
        right.addWidget(self.btn_selected)
        right.addWidget(self.btn_review_new)
        right.addWidget(self.btn_practice)
        l.addLayout(right)

        # Animated glow on train button
        self._glow_step = 0
        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._tick_glow)
        self._glow_timer.setInterval(self.GLOW_INTERVAL_MS)

        try:
            from ui.canvas.retro_effects import register_retro_widget
            register_retro_widget(self)
        except Exception:
            pass

        self.setMinimumHeight(_px(110, self._scale))
        self.btn_train.setMinimumHeight(_px(76, self._scale))
        self.btn_selected.setMinimumHeight(_px(36, self._scale))
        self.btn_review_new.setMinimumHeight(_px(36, self._scale))

    def set_new_cards_count(self, count: int):
        self.btn_review_new.setText(f"✨  REVIEW NEW ({count})")
        self.btn_review_new.setEnabled(count > 0)

    def set_animation_enabled(self, enabled):
        if enabled:
            if not self._glow_timer.isActive():
                self._glow_timer.start()
        else:
            if self._glow_timer.isActive():
                self._glow_timer.stop()

    def sync_timer(self):
        try:
            from ui.canvas.retro_effects import animations_suspended, _home_animations_enabled
            self.set_animation_enabled(not animations_suspended() and _home_animations_enabled())
        except Exception:
            self.set_animation_enabled(False)

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        if self._glow_timer.isActive():
            self._glow_timer.stop()
        super().hideEvent(event)

    def _tick_glow(self):
        try:
            from ui.canvas.retro_effects import animations_suspended, _home_animations_enabled
            if animations_suspended() or not _home_animations_enabled():
                return
        except Exception:
            pass

        self._glow_step += 1
        t = (math.sin(self._glow_step * math.pi / 15.0) + 1.0) / 2.0
        eff = self.btn_train.graphicsEffect()
        if eff and isinstance(eff, QGraphicsDropShadowEffect):
            glow_color = QColor("#72FF4F")
            glow_color.setAlpha(int(80 + 90 * t))
            eff.setColor(glow_color)

        # Heartbeat pulse animation on resume button
        eff2 = self.btn_resume.graphicsEffect()
        if eff2 and isinstance(eff2, QGraphicsDropShadowEffect):
            if self.btn_resume.isEnabled():
                t2 = (math.sin(self._glow_step * math.pi / 6.0) + 1.0) / 2.0
                glow_c = QColor("#ff9f43")
                glow_c.setAlpha(int(110 + 80 * t2))
                eff2.setColor(glow_c)
            else:
                eff2.setColor(QColor(0, 0, 0, 0))

    def set_resume_enabled(self, enabled):
        self.btn_resume.setEnabled(enabled)


# ══════════════════════════════════════════════════════════════════════════════
#  RIGHT SIDEBAR — Banga Lab
# ══════════════════════════════════════════════════════════════════════════════
class TMNTBangaLab(QFrame):
    clear_clicked = pyqtSignal()
    resources_refreshed = pyqtSignal(str)
    AUTO_REFRESH_MS = 4000

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
        self._auto_timer.setInterval(self.AUTO_REFRESH_MS)
        self.particles = RetroParticlePanel(self, is_ooze=False)
        self._build_ui()
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "particles"):
            self.particles.setGeometry(self.rect())

    def set_auto_refresh_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled:
            drawer = self.parent()
            if drawer is not None:
                drawer_open = getattr(drawer, "_drawer_open", None)
                drawer_locked = getattr(drawer, "_drawer_locked", None)
                if drawer_open is not None and drawer_locked is not None:
                    if not (drawer_open or drawer_locked):
                        enabled = False
        if enabled:
            if not self._auto_timer.isActive():
                self._auto_timer.start()
            return
        if self._auto_timer.isActive():
            self._auto_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        drawer = self.parent()
        drawer_open = getattr(drawer, "_drawer_open", None)
        drawer_locked = getattr(drawer, "_drawer_locked", None)
        if drawer_open is not None and drawer_locked is not None:
            self.set_auto_refresh_enabled(drawer_open or drawer_locked)
        else:
            self.set_auto_refresh_enabled(True)

    def hideEvent(self, event):
        self.set_auto_refresh_enabled(False)
        super().hideEvent(event)

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
                background: {T_GREEN};
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
        pdf_ok = _pdf_support_available()
        pdf_val = "PyMuPDF" if pdf_ok else "MISSING"
        pdf_col = T_PURPLE if pdf_ok else T_RED
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
        clr_font = QFont(T_MONO)
        clr_font.setPixelSize(_px(9, self._scale))
        clr_font.setBold(True)
        clr.setFont(clr_font)
        clr.clicked.connect(self._clear_all)
        body.addWidget(clr)
        body.addStretch()

    def refresh(self):
        try:
            from cache_manager import PAGE_CACHE, COMBINED_CACHE

            known = set()
            known.update(COMBINED_CACHE.all_cached_pdfs())
            known.update(PAGE_CACHE.all_cached_pdfs())
            ram_b = disk_b = mask_b = 0
            for p in known:
                disk_b += COMBINED_CACHE.disk_bytes_for_pdf(p)
                ram_b += PAGE_CACHE.ram_bytes_for_pdf(p)
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
        self.resources_refreshed.emit(self.lbl_tot.text())

    def _clear_all(self):
        try:
            from cache_manager import (
                PAGE_CACHE,
                COMBINED_CACHE,
                PIXMAP_REGISTRY,
            )

            COMBINED_CACHE.clear()
            PAGE_CACHE.clear_ram_only()
            for label in list(PIXMAP_REGISTRY._entries.keys()):
                PIXMAP_REGISTRY.unregister(label)
            self.refresh()
        except Exception:
            pass


class TMNTBangaDrawer(QFrame):
    """Overlay drawer for the TMNT cache/resource panel."""

    AUTO_HIDE_MS = 900
    EDGE_W = 22
    EDGE_BUTTON_W = 22
    EDGE_BUTTON_H = 42
    LOCK_SETTINGS_KEY = "home/tmnt_cache_drawer_locked"

    def __init__(self, data=None, parent=None, reserve_widget=None):
        super().__init__(parent)
        self.setObjectName("tmnt_banga_drawer")
        self._data = data
        self._host = parent
        self._reserve_widget = reserve_widget
        self._scale = _tmnt_scale(data)
        self._drawer_open = False
        self._drawer_locked = self._load_locked()
        self._open_width = _px(TMNT_RIGHTBAR_W, self._scale)
        self._edge_w = _px(self.EDGE_W, self._scale)
        self._edge_button_w = _px(self.EDGE_BUTTON_W, self._scale)
        self._edge_button_h = _px(self.EDGE_BUTTON_H, self._scale)
        self.setFixedWidth(self._open_width)
        self.setStyleSheet("QFrame#tmnt_banga_drawer{background:transparent;border:none;}")

        self._slide_anim = QPropertyAnimation(self, b"geometry", self)
        self._slide_anim.setDuration(240)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.lab = TMNTBangaLab(data=data, parent=self)
        lay.addWidget(self.lab)

        self._edge_button = QPushButton("‹", parent)
        self._edge_button.setObjectName("tmnt_banga_edge")
        self._edge_button.setFocusPolicy(Qt.NoFocus)
        self._edge_button.setToolTip("Show cache panel")
        self._edge_button.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton#tmnt_banga_edge {{
                background: rgba(11, 12, 16, 235);
                color: {T_NEON};
                border: 1px solid {T_GREEN};
                border-radius: 8px 0px 0px 8px;
                font-size: 18px;
                font-weight: 900;
                font-family: {T_MONO};
                padding: 0px;
            }}
            QPushButton#tmnt_banga_edge:hover {{
                background: {T_PANEL};
                color: {T_GREEN};
                border-color: {T_NEON};
            }}
        """,
                self._scale,
            )
        )
        self._edge_button.clicked.connect(self.open_drawer)
        self._edge_glow = QGraphicsDropShadowEffect(self._edge_button)
        self._edge_glow.setColor(QColor(T_GREEN))
        self._edge_glow.setOffset(0, 0)
        self._edge_glow.setBlurRadius(_px(14, self._scale))
        self._edge_button.setGraphicsEffect(self._edge_glow)
        self._edge_pulse = QPropertyAnimation(self._edge_glow, b"blurRadius", self)
        self._edge_pulse.setDuration(1200)
        self._edge_pulse.setStartValue(float(_px(8, self._scale)))
        self._edge_pulse.setEndValue(float(_px(24, self._scale)))
        self._edge_pulse.setEasingCurve(QEasingCurve.InOutSine)
        self._edge_pulse.setLoopCount(-1)

        self._lock_button = QPushButton("🔓", self)
        self._lock_button.setObjectName("tmnt_banga_lock")
        self._lock_button.setFocusPolicy(Qt.NoFocus)
        self._lock_button.setToolTip("Lock cache panel open")
        self._lock_button.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton#tmnt_banga_lock {{
                background: rgba(11, 12, 16, 225);
                color: {T_GREEN};
                border: 1px solid {T_BORDER};
                border-radius: 3px;
                font-size: 12px;
                font-weight: 900;
                padding: 2px;
            }}
            QPushButton#tmnt_banga_lock:hover {{
                color: {T_NEON};
                border-color: {T_GREEN};
            }}
        """,
                self._scale,
            )
        )
        self._lock_button.clicked.connect(self._toggle_lock)

        self._memory_chip = QLabel("TOTAL 0.0 MB", parent)
        self._memory_chip.setObjectName("tmnt_banga_memory_chip")
        self._memory_chip.setAlignment(Qt.AlignCenter)
        self._memory_chip.setToolTip("Total cache memory")
        self._memory_chip.setStyleSheet(
            _scale_ss(
                f"""
            QLabel#tmnt_banga_memory_chip {{
                background: rgba(11, 12, 16, 225);
                color: {T_TEXT};
                border: 1px solid {T_GREEN};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 10px;
                font-weight: 900;
                font-family: {T_MONO};
            }}
        """,
                self._scale,
            )
        )
        chip_font = QFont(T_MONO)
        chip_font.setPixelSize(_px(10, self._scale))
        chip_font.setBold(True)
        self._memory_chip.setFont(chip_font)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self.AUTO_HIDE_MS)
        self._hide_timer.timeout.connect(self._hide_if_cursor_outside)

        for widget in (
            self,
            self.lab,
            self._edge_button,
            self._lock_button,
            self._memory_chip,
        ):
            widget.installEventFilter(self)
            widget.setMouseTracking(True)
        if parent is not None:
            parent.installEventFilter(self)
            parent.setMouseTracking(True)

        self.lab.resources_refreshed.connect(self._set_total_memory_text)
        self._set_total_memory_text(self.lab.lbl_tot.text())
        if self._drawer_locked:
            self._drawer_open = True
            self.show()
            self._edge_button.setText("›")
        else:
            self.hide()
        self._sync_lab_auto_refresh()
        self._sync_reserved_space()
        self._sync_floating_triggers()
        self._sync_lock_button()
        self._sync_edge_pulse()
        QTimer.singleShot(0, self.reposition)

    @classmethod
    def _load_locked(cls):
        raw = QSettings("AnkiOcclusion", "App").value(cls.LOCK_SETTINGS_KEY, False)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def _save_locked(cls, locked):
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue(cls.LOCK_SETTINGS_KEY, bool(locked))
        settings.sync()

    def refresh(self):
        self.lab._data = self._data
        self.lab.refresh()
        self._set_total_memory_text(self.lab.lbl_tot.text())

    def _sync_lab_auto_refresh(self):
        self.lab.set_auto_refresh_enabled(self._drawer_open or self._drawer_locked)

    def _set_total_memory_text(self, total_text):
        self._memory_chip.setText(f"TOTAL {total_text}")
        self._memory_chip.adjustSize()
        self.reposition()

    def eventFilter(self, obj, event):
        et = event.type()
        if obj is self._host and et == QEvent.Resize:
            self.reposition()
        elif obj in (self._edge_button, self._memory_chip) and et in (
            QEvent.Enter,
            QEvent.HoverMove,
            QEvent.MouseMove,
        ):
            self.open_drawer()
        elif obj in (self, self.lab, self._lock_button) and et in (
            QEvent.Enter,
            QEvent.MouseMove,
        ):
            self._hide_timer.stop()
        elif obj in (self, self.lab, self._lock_button) and et == QEvent.Leave:
            if not self._drawer_locked:
                self._hide_timer.start()
        return super().eventFilter(obj, event)

    def open_drawer(self):
        self._drawer_open = True
        self._hide_timer.stop()
        self._sync_floating_triggers()
        self._sync_lock_button()
        self._sync_edge_pulse()
        self._sync_lab_auto_refresh()
        self.refresh()

        host = self._host
        h = max(1, host.height()) if host else 400
        w = max(1, host.width()) if host else 600

        self.show()
        self.raise_()

        if _home_animations_enabled():
            self._slide_anim.stop()
            self._slide_anim.setStartValue(QRect(w, 0, self._open_width, h))
            self._slide_anim.setEndValue(QRect(w - self._open_width, 0, self._open_width, h))
            self._slide_anim.start()
        else:
            self.setGeometry(max(0, w - self._open_width), 0, self._open_width, h)
            self.reposition()

        self._edge_button.setText("›")
        self._edge_button.setToolTip("Move away to hide cache panel")

    def close_drawer(self):
        if self._drawer_locked:
            self.open_drawer()
            return
        if not self._drawer_open:
            return
        self._drawer_open = False
        self._sync_floating_triggers()
        self._sync_lock_button()
        self._sync_edge_pulse()
        self._sync_lab_auto_refresh()

        host = self._host
        h = max(1, host.height()) if host else 400
        w = max(1, host.width()) if host else 600

        if _home_animations_enabled():
            self._slide_anim.stop()
            self._slide_anim.setStartValue(QRect(self.x(), 0, self._open_width, h))
            self._slide_anim.setEndValue(QRect(w, 0, self._open_width, h))
            try:
                self._slide_anim.finished.disconnect()
            except Exception:
                pass
            self._slide_anim.finished.connect(self.hide)
            self._slide_anim.start()
        else:
            self.hide()
            self.reposition()

        self._edge_button.setText("‹")
        self._edge_button.setToolTip("Show cache panel")

    def _toggle_lock(self):
        self._drawer_locked = not self._drawer_locked
        self._save_locked(self._drawer_locked)
        self._sync_reserved_space()
        self._sync_lock_button()
        if self._drawer_locked:
            self.open_drawer()
        elif not self._contains_cursor():
            self._hide_timer.start()
        self._sync_edge_pulse()

    def _sync_lock_button(self):
        self._lock_button.setText("🔒" if self._drawer_locked else "🔓")
        self._lock_button.setToolTip(
            "Unlock cache panel" if self._drawer_locked else "Lock cache panel open"
        )
        self._lock_button.setVisible(self._drawer_open)

    def _sync_floating_triggers(self):
        show_floating = not self._drawer_open
        self._edge_button.setVisible(show_floating)
        self._memory_chip.setVisible(show_floating)

    def _sync_reserved_space(self):
        reserve = self._reserve_widget
        if reserve is None:
            return
        width = self._open_width if self._drawer_locked else 0
        reserve.setFixedWidth(width)
        reserve.setVisible(width > 0)

    def _sync_edge_pulse(self):
        should_pulse = (
            _home_animations_enabled()
            and not self._drawer_open
            and not self._drawer_locked
        )
        if should_pulse:
            if self._edge_pulse.state() != QAbstractAnimation.Running:
                self._edge_pulse.start()
            return
        if self._edge_pulse.state() == QAbstractAnimation.Running:
            self._edge_pulse.stop()
        self._edge_glow.setBlurRadius(_px(14, self._scale))

    def _hide_if_cursor_outside(self):
        if self._drawer_locked:
            return
        if self._contains_cursor():
            self._hide_timer.start()
            return
        self.close_drawer()

    def _contains_cursor(self):
        pos = QCursor.pos()
        for widget in (self, self._edge_button, self._lock_button, self._memory_chip):
            if widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(pos)):
                return True
        return False

    def reposition(self):
        host = self._host
        if host is None:
            return
        h = max(1, host.height())
        w = max(1, host.width())

        if not (hasattr(self, "_slide_anim") and self._slide_anim.state() == QAbstractAnimation.Running):
            if self._drawer_open:
                self.setGeometry(max(0, w - self._open_width), 0, self._open_width, h)
            else:
                self.setGeometry(w, 0, self._open_width, h)

        edge_y = max(_px(16, self._scale), (h - self._edge_button_h) // 2)
        self._edge_button.setGeometry(
            max(0, w - self._edge_button_w),
            edge_y,
            self._edge_button_w,
            self._edge_button_h,
        )
        lock_size = _px(30, self._scale)
        self._lock_button.setGeometry(
            max(0, self._open_width - lock_size - _px(10, self._scale)),
            _px(10, self._scale),
            lock_size,
            lock_size,
        )
        self._memory_chip.adjustSize()
        chip_w = self._memory_chip.width()
        chip_h = self._memory_chip.height()
        chip_x = max(0, w - chip_w - self._edge_button_w - _px(8, self._scale))
        chip_y = max(0, h - chip_h - _px(12, self._scale))
        self._memory_chip.move(chip_x, chip_y)
        self._lock_button.raise_()
        self._edge_button.raise_()
        self._memory_chip.raise_()


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
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, self.tree.header().Stretch)
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
            QTreeWidget::branch {{
                background: transparent;
            }}
            QTreeWidget::branch:closed:has-children,
            QTreeWidget::branch:closed:has-children:has-siblings,
            QTreeWidget::branch:closed:has-children:adjoins-item {{
                image: url({app_resource_url("assets", "themes", "dojo", "tmnt_tree_closed.svg")});
            }}
            QTreeWidget::branch:open:has-children:has-siblings,
            QTreeWidget::branch:open:has-children {{
                image: url({app_resource_url("assets", "themes", "dojo", "tmnt_tree_open.svg")});
            }}
            QScrollBar:vertical {{
                background: {T_BG};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {T_GREEN};
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
                background: {T_GREEN};
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
        self._structure_locked = self._is_structure_locked_saved()
        self.set_structure_locked(self._structure_locked)

    def set_theme(self, theme):
        self._theme = "tmnt"

    def keyPressEvent(self, event):
        key = event.key()
        if shortcut_manager.event_matches(event, "home.browse_cards"):
            sel_deck = getattr(self, "_selected_deck", None)
            p = self.parent()
            while p is not None:
                if not sel_deck:
                    sel_deck = getattr(p, "_selected_deck", None)
                if hasattr(p, "main") and hasattr(p.main, "_open_card_browser"):
                    if not getattr(p.main, "deck", None) and sel_deck:
                        p.main.load_deck(sel_deck, getattr(p.main, "_data", None) or getattr(self, "_data", None))
                    p.main._open_card_browser()
                    event.accept()
                    return
                if hasattr(p, "_open_card_browser"):
                    p._open_card_browser()
                    event.accept()
                    return
                p = p.parent()
            win = self.window()
            if win and hasattr(win, "centralWidget"):
                home = win.centralWidget()
                if home and hasattr(home, "_open_card_browser"):
                    home._open_card_browser()
                    event.accept()
                    return
        if shortcut_manager.event_matches(event, "home.edit_card") or (key == Qt.Key_E and (event.modifiers() & Qt.ControlModifier) and not (event.modifiers() & (Qt.AltModifier | Qt.MetaModifier))):
            sel_deck = getattr(self, "_selected_deck", None)
            if not sel_deck and hasattr(self, "currentItem"):
                cur_item = self.currentItem()
                if cur_item and hasattr(self, "_get_deck_from_item"):
                    sel_deck = self._get_deck_from_item(cur_item)
            p = self.parent()
            main = None
            while p is not None:
                if not sel_deck:
                    sel_deck = getattr(p, "_selected_deck", None)
                if hasattr(p, "main") and getattr(p, "main", None):
                    main = p.main
                    break
                p = p.parent()
            if main:
                if sel_deck and getattr(main, "deck", None) != sel_deck:
                    main.load_deck(sel_deck, getattr(main, "_data", None) or getattr(self, "_data", None))
                item = main.card_list.currentItem()
                if not item and main.card_list.count() > 0:
                    item = main.card_list.item(0)
                    main.card_list.setCurrentItem(item)
                if item:
                    main._edit_card(item)
                    event.accept()
                    return
                elif getattr(main, "deck", None):
                    def _find_card(d):
                        if d.get("cards"):
                            return d["cards"][0], d
                        for child in d.get("children", []):
                            r = _find_card(child)
                            if r:
                                return r
                        return None, None
                    sub_card, sub_d = _find_card(main.deck)
                    if sub_card and sub_d:
                        main._edit_card_by_dict(sub_card, sub_d)
                        event.accept()
                        return
                    else:
                        main._add_card()
                        event.accept()
                        return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected()
            event.accept()
            return
        if key == Qt.Key_F2:
            deck_id = self._get_selected_id()
            if deck_id is not None:
                self._rename_by_id(deck_id)
                event.accept()
                return
        super().keyPressEvent(event)

    def _make_item(self, deck, depth=0, parent_is_paused=False):
        if "is_paused" in deck and deck["is_paused"] is not None:
            is_paused = bool(deck["is_paused"])
        else:
            is_paused = parent_is_paused
        due = getattr(self, "_due_counts", {}).get(deck.get("_id"), 0)
        item = QTreeWidgetItem([deck["name"].upper()])
        item.setToolTip(0, f"{deck.get('name', '')} (⏸️ PAUSED - {due} Due Backlog)" if is_paused else deck.get("name", ""))
        item.setData(0, Qt.UserRole, deck.get("_id"))
        item.setData(0, Qt.UserRole + 1, str(due))
        item.setData(0, Qt.UserRole + 2, deck["name"])
        item.setData(
            0,
            Qt.UserRole + 3,
            getattr(self, "_total_cards", {}).get(deck.get("_id"), 0),
        )
        item.setData(0, Qt.UserRole + 4, depth)
        item.setData(0, Qt.UserRole + 5, deck.get("bookmarked", False))
        item.setData(0, Qt.UserRole + 6, is_paused)
        for child in deck.get("children", []):
            item.addChild(self._make_item(child, depth + 1, parent_is_paused=is_paused))
        return item

    def _blink_tick(self):
        return

    def refresh(self):
        sel_id = self._get_selected_id()
        query = ""
        sidebar = self.parent()
        search = getattr(sidebar, "search_in", None)
        if search is not None:
            query = search.text()
        expanded_ids = set()

        def _collect(item):
            if item.isExpanded():
                expanded_ids.add(item.data(0, Qt.UserRole))
            for i in range(item.childCount()):
                _collect(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            _collect(self.tree.topLevelItem(i))

        rollups = build_deck_rollups(self._data.get("decks", []))
        self._due_counts = rollups["due_units"]
        self._total_cards = rollups["total_cards"]
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
            selected = self.tree.currentItem()
            if selected:
                self.tree.scrollToItem(selected)

        if query:
            self._on_search(query)


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
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
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
        self.particles = RetroParticlePanel(self, is_ooze=True)
        self._build_ui()
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "particles"):
            self.particles.setGeometry(self.rect())

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

        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        if theme_name not in ("tmnt", "manhattan"):
            theme_name = "tmnt"

        sidebar_hdr = "SEWER CAVES" if theme_name == "manhattan" else "DOJO CAVE"
        title = QLabel(sidebar_hdr)
        title_size = 14
        title.setStyleSheet(
            _scale_ss(
                f"color: {T_GREEN}; font-size: {title_size}px; font-weight: 900; "
                f"font-family: {T_PIXEL}; letter-spacing: 2px;",
                self._scale,
            )
        )
        title_font = QFont("Orbitron")
        title_font.setPixelSize(_px(title_size, self._scale))
        title_font.setBold(True)
        title.setFont(title_font)

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
        search_placeholder = "Search area..." if theme_name == "manhattan" else "Search scrolls..."
        self.search_in.setPlaceholderText(search_placeholder)
        self.search_in.setClearButtonEnabled(True)
        search_font_size = 14
        self.search_in.setStyleSheet(
            _scale_ss(
                f"background: transparent; border: none; color: {T_TEXT}; "
                f"font-family: {T_MONO}; font-size: {search_font_size}px;",
                self._scale,
            )
        )
        self.search_in.textChanged.connect(self._on_search)
        
        def _search_key_press(e):
            if e.key() == Qt.Key_Escape:
                if self.search_in.text():
                    self.search_in.clear()
                else:
                    self.search_in.clearFocus()
                    if hasattr(self, "_engine") and hasattr(self._engine, "tree"):
                        self._engine.tree.setFocus()
                e.accept()
                return
            QLineEdit.keyPressEvent(self.search_in, e)
        self.search_in.keyPressEvent = _search_key_press
        
        kb_badge = QLabel("CTRL+F")
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

        search_row = QHBoxLayout()
        search_row.setSpacing(_px(6, self._scale))
        search_row.addWidget(search_frame, stretch=1)

        self.btn_lock_structure = QPushButton()
        self.btn_lock_structure.setFixedSize(_px(32, self._scale), _px(32, self._scale))
        self.btn_lock_structure.setCursor(Qt.PointingHandCursor)
        self.btn_lock_structure.clicked.connect(self._toggle_deck_structure_lock)
        search_row.addWidget(self.btn_lock_structure)

        hl.addLayout(search_row)
        L.addWidget(hdr)

        # Global shortcuts for search focus
        self._shortcut_focus_f = QShortcut(QKeySequence("Ctrl+F"), self)
        self._shortcut_focus_f.setContext(Qt.WindowShortcut)
        self._shortcut_focus_f.activated.connect(self._focus_search)

        self._shortcut_focus_k = QShortcut(QKeySequence("Ctrl+K"), self)
        self._shortcut_focus_k.setContext(Qt.WindowShortcut)
        self._shortcut_focus_k.activated.connect(self._focus_search)

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

        # Determine theme name
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        if theme_name not in ("tmnt", "manhattan"):
            theme_name = "tmnt"

        def _foot_btn(text):
            b = QPushButton(text)
            f_size = 12
            b.setStyleSheet(
                _scale_ss(
                    f"""
                QPushButton {{
                    background: transparent;
                    color: {T_GREEN};
                    border: 1px solid {T_GREEN};
                    border-radius: 2px;
                    font-size: {f_size}px;
                    font-weight: 900;
                    font-family: {T_PIXEL};
                    padding: 6px 8px;
                }}
                QPushButton:hover {{ background: rgba(69,162,71,0.12); }}
            """,
                    self._scale,
                )
            )
            btn_font = QFont("Orbitron")
            btn_font.setPixelSize(_px(f_size, self._scale))
            btn_font.setBold(True)
            b.setFont(btn_font)
            return b

        new_label = "+ STAGE" if theme_name == "manhattan" else "+ NEW DOJO"
        sub_label = "+ SUBSTAGE" if theme_name == "manhattan" else "+ SUB Dojo"
        btn_new = _foot_btn(new_label)
        btn_sub = _foot_btn(sub_label)
        from PyQt5.QtGui import QIcon
        from PyQt5.QtCore import QSize

        btn_open = QPushButton()
        btn_open.setIcon(
            QIcon(app_resource_path("assets", "themes", "dojo", "sewer_icon.png"))
        )
        btn_h = _px(34, self._scale)  # same height as NEW DOJO / SUB
        btn_w = _px(34, self._scale)  # square — logo is circular anyway
        btn_Icon_height = _px(74, self._scale)  # square — logo is circular anyway

        btn_open.setIconSize(
            QSize(btn_Icon_height, btn_Icon_height)
        )  # icon fills the whole button
        btn_open.setFixedSize(btn_w, btn_h)

        btn_open.setToolTip("Delete selected dojo")
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
        btn_open.clicked.connect(self._delete_selected)
        fl.addWidget(btn_new, stretch=1)
        fl.addWidget(btn_sub, stretch=1)
        fl.addWidget(btn_open)
        L.addWidget(foot)
        self._deck_structure_locked = self._is_deck_structure_locked_saved()
        self.set_structure_locked(self._deck_structure_locked)

    def _is_deck_structure_locked_saved(self) -> bool:
        from PyQt5.QtCore import QSettings
        return bool(QSettings("AnkiOcclusion", "App").value("deck_structure_locked", False, type=bool))

    def _save_deck_structure_locked(self, locked: bool):
        from PyQt5.QtCore import QSettings
        QSettings("AnkiOcclusion", "App").setValue("deck_structure_locked", bool(locked))

    def _sync_deck_structure_lock_button(self):
        if not hasattr(self, "btn_lock_structure") or not self.btn_lock_structure:
            return
        is_locked = getattr(self, "_deck_structure_locked", False)
        lock_icon = "🔒" if is_locked else "🔓"
        lock_tip = (
            "🔒 Deck Structure Locked (डेक लॉक है)\nDrag & drop moving and reordering is disabled.\nClick to unlock."
            if is_locked
            else "🔓 Deck Structure Unlocked (डेक अनलॉक है)\nDrag & drop moving and reordering is enabled.\nClick to lock and prevent accidental shifts."
        )
        lock_style = (
            _scale_ss(
                f"""
                QPushButton {{
                    background: rgba(255, 184, 108, 0.2);
                    color: #FFB86C;
                    border: 1.5px solid #FFB86C;
                    border-radius: 3px;
                    font-size: 15px;
                }}
                QPushButton:hover {{
                    background: rgba(255, 184, 108, 0.35);
                }}
                """,
                self._scale,
            )
            if is_locked
            else _scale_ss(
                f"""
                QPushButton {{
                    background: {T_BG};
                    color: {T_SUBTEXT};
                    border: 1px solid {T_BORDER};
                    border-radius: 3px;
                    font-size: 15px;
                }}
                QPushButton:hover {{
                    background: rgba(255, 255, 255, 0.08);
                    border-color: {T_TEXT};
                }}
                """,
                self._scale,
            )
        )
        self.btn_lock_structure.setText(lock_icon)
        self.btn_lock_structure.setToolTip(lock_tip)
        self.btn_lock_structure.setStyleSheet(lock_style)

    def _toggle_deck_structure_lock(self):
        new_state = not getattr(self, "_deck_structure_locked", False)
        self._save_deck_structure_locked(new_state)
        self.set_structure_locked(new_state)

    def set_structure_locked(self, locked: bool):
        self._deck_structure_locked = bool(locked)
        self._sync_deck_structure_lock_button()
        if hasattr(self, "_engine") and self._engine and hasattr(self._engine, "set_structure_locked"):
            self._engine.set_structure_locked(locked)
        p = self.parent()
        while p:
            if hasattr(p, "main") and p.main and hasattr(p.main, "set_structure_locked"):
                p.main.set_structure_locked(locked)
            if hasattr(p, "deck_view") and p.deck_view and hasattr(p.deck_view, "set_structure_locked"):
                p.deck_view.set_structure_locked(locked)
            p = p.parent()

    @property
    def tree(self):
        return getattr(self._engine, "tree", None) if hasattr(self, "_engine") else None

    def keyPressEvent(self, event):
        if shortcut_manager.event_matches(event, "home.browse_cards"):
            p = self.parent()
            while p is not None:
                if hasattr(p, "main") and hasattr(p.main, "_open_card_browser"):
                    if not getattr(p.main, "deck", None) and hasattr(self, "_selected_deck") and self._selected_deck:
                        p.main.load_deck(self._selected_deck, getattr(p.main, "_data", None) or getattr(self, "_data", None))
                    p.main._open_card_browser()
                    event.accept()
                    return
                if hasattr(p, "_open_card_browser"):
                    p._open_card_browser()
                    event.accept()
                    return
                p = p.parent()
        if event.key() in (Qt.Key_F, Qt.Key_K) and event.modifiers() & Qt.ControlModifier:
            self._focus_search()
            event.accept()
            return
        super().keyPressEvent(event)

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

    def _focus_search(self):
        self.search_in.setFocus(Qt.ShortcutFocusReason)
        self.search_in.selectAll()

    def _delete_selected(self):
        selected_id = self._engine._get_selected_id()
        self._engine._delete_selected()
        self._sync_from_engine()

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
        self._sync_deck_structure_lock_button()
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
        self._rollups = {"due_units": {}, "total_cards": {}}

    def load(self, decks, selected_id=None):
        self._all_decks = decks
        self._rollups = build_deck_rollups(decks)
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
            due_count=self._rollups["due_units"].get(deck_id, 0),
            total_cards=self._rollups["total_cards"].get(deck_id, 0),
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
        due_count=0,
        total_cards=0,
        parent=None,
    ):
        super().__init__(parent)
        self._deck = deck
        self._scale = _tmnt_scale(data if isinstance(data, dict) else None)
        self._depth = depth
        self._selected = selected
        self._expanded = expanded
        self._has_children = has_children
        self._due_count = due_count
        self._total_cards = total_cards
        self.setCursor(Qt.PointingHandCursor)
        self._build()

    def _build(self):
        self.setFixedHeight(_px(44, self._scale))
        due = self._due_count
        name = self._deck.get("name", "?").upper()
        total_cards = self._total_cards
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
        self.setToolTip(self._deck.get("name", ""))
        name_lbl.setToolTip(self._deck.get("name", ""))
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
        self._font_size_val = int(self._data.get("_font_size", TMNT_BASE_SIZE))
        self._scale = _tmnt_scale(data)
        self._theme = "tmnt"
        super().__init__(parent)
        self.setStyleSheet(f"background: #151821;")

    def _setup_ui(self):
        # Create a top-level layout on self to hold the QScrollArea
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(_scale_ss(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {T_BG};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {T_GREEN};
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {T_GREEN};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """, self._scale))

        # Create a container widget for the actual content
        content_widget = QWidget()
        content_widget.setObjectName("tmnt_main_content_widget")
        content_widget.setStyleSheet(f"QWidget#tmnt_main_content_widget {{ background: {T_BG}; }}")
        scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_active)

        L = QVBoxLayout(content_widget)
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
        self.lbl_deck.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
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
        self.lbl_stats = QLabel()  # hidden, needed by DeckView
        self.lbl_stats.hide()

        title_txt.addWidget(self.lbl_deck)
        title_txt.addWidget(self.lbl_deck_sub)

        title_row.addWidget(self.lbl_deck_icon)
        title_row.addLayout(title_txt)
        title_row.addStretch()

        # ── Buttons row ──
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(_px(12, self._scale))

        self.btn_bookmark = QPushButton()
        self.btn_bookmark.setObjectName("bookmark_btn")
        self.btn_bookmark.setCursor(Qt.PointingHandCursor)
        self.btn_bookmark.clicked.connect(self._toggle_bookmark)
        self.btn_bookmark.hide()
        buttons_row.addWidget(self.btn_bookmark)

        buttons_row.addStretch()

        # Dynamic labels & colors for retro layout (Dojo vs Manhattan)
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        if theme_name not in ("tmnt", "manhattan"):
            theme_name = "tmnt"

        if theme_name == "manhattan":
            btn_add_label = "🍕  ADD PIZZA CARD"
            btn_add_text_label = "🍕  ADD PIZZA SLICE"
            hover_green_bg = "rgba(57,255,20,0.10)"
            hover_purple_bg = "rgba(168,108,255,0.10)"
            btn_font_size = 12
        else:
            btn_add_label = "🐢  FORGE SCROLL"
            btn_add_text_label = "🥋  SCRIBE TILE"
            hover_green_bg = "rgba(69,162,71,0.10)"
            hover_purple_bg = "rgba(176,136,249,0.10)"
            btn_font_size = 12

        self.btn_add = QPushButton(btn_add_label)
        self.btn_add.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: rgba(69,162,71,0.04);
                color: {T_GREEN};
                border: 1px solid {T_GREEN};
                border-radius: 2px;
                font-size: {btn_font_size}px;
                font-weight: 900;
                font-family: {T_PIXEL};
                padding: 8px 16px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {hover_green_bg}; color: {T_GREEN}; border-color: {T_GREEN}; }}
        """,
                self._scale,
            )
        )
        self.btn_add.clicked.connect(self._add_card)
        buttons_row.addWidget(self.btn_add)

        self.btn_add_text = QPushButton(btn_add_text_label)
        self.btn_add_text.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: rgba(168,108,255,0.04);
                color: {T_PURPLE};
                border: 1px solid {T_PURPLE};
                border-radius: 2px;
                font-size: {btn_font_size}px;
                font-weight: 900;
                font-family: {T_PIXEL};
                padding: 8px 16px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {hover_purple_bg}; color: {T_PURPLE}; border-color: {T_PURPLE}; }}
        """,
                self._scale,
            )
        )
        self.btn_add_text.clicked.connect(self._add_text_card)
        buttons_row.addWidget(self.btn_add_text)

        self.btn_import = QPushButton("📥  IMPORT")
        self.btn_import.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: rgba(114,255,79,0.04);
                color: {T_GREEN};
                border: 1px solid {T_GREEN};
                border-radius: 2px;
                font-size: {btn_font_size}px;
                font-weight: 900;
                font-family: {T_PIXEL};
                padding: 8px 16px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {hover_green_bg}; color: {T_GREEN}; border-color: {T_GREEN}; }}
        """,
                self._scale,
            )
        )
        self.btn_import.clicked.connect(self._import_cards)
        buttons_row.addWidget(self.btn_import)

        # Set explicitly in Python to prevent sizeHint layout calculation errors and clipping
        btn_font = QFont("Orbitron")
        btn_font.setPixelSize(_px(btn_font_size, self._scale))
        btn_font.setBold(True)
        self.btn_add.setFont(btn_font)
        self.btn_add_text.setFont(btn_font)
        self.btn_import.setFont(btn_font)

        L.addLayout(title_row)
        L.addLayout(buttons_row)

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
        self.btn_practice = self.banner.btn_practice
        self.btn_review_new = self.banner.btn_review_new
        self.btn_due.clicked.connect(self._review_due)
        self.btn_all.clicked.connect(self._review_due_least_mature)
        self.btn_review_new.clicked.connect(self._review_new_cards)
        self.banner.practice_clicked.connect(self._practice_deck)
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
                background: {T_GREEN};
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
        self.card_list.itemDoubleClicked.connect(lambda item: self._edit_card(item))
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

        # Determine theme name
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        if theme_name not in ("tmnt", "manhattan"):
            theme_name = "tmnt"

        if theme_name == "manhattan":
            edit_text = "✏  EDIT"
            btn_font_size = 14
            btn_font_family = T_MONO
            btn_font_bold = False
            delete_text = "🗑  DELETE"
            del_font_size = 14
            del_font_family = T_MONO
            del_font_bold = True
        else:
            edit_text = "✏  Edit"
            btn_font_size = 14
            btn_font_family = T_MONO
            btn_font_bold = False
            delete_text = "🗑  DELETE"
            del_font_size = 14
            del_font_family = T_MONO
            del_font_bold = True

        self.btn_edit = QPushButton(edit_text)
        self.btn_edit.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: {T_PANEL};
                color: {T_TEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: {btn_font_size}px;
                font-family: {btn_font_family};
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
        edit_font = QFont(btn_font_family)
        edit_font.setPixelSize(_px(btn_font_size, self._scale))
        edit_font.setBold(btn_font_bold)
        self.btn_edit.setFont(edit_font)

        self.btn_delete_tmnt = QPushButton(delete_text)
        self.btn_delete_tmnt.setStyleSheet(
            _scale_ss(
                f"""
            QPushButton {{
                background: transparent;
                color: {T_RED};
                border: 1px solid {T_RED};
                border-radius: 2px;
                font-size: {del_font_size}px;
                font-weight: bold;
                font-family: {del_font_family};
                padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {T_RED}; color: white; }}
        """,
                self._scale,
            )
        )
        self.btn_delete_tmnt.clicked.connect(self._delete_card)
        
        del_font = QFont(del_font_family)
        del_font.setPixelSize(_px(del_font_size, self._scale))
        del_font.setBold(del_font_bold)
        self.btn_delete_tmnt.setFont(del_font)

        bot.addWidget(self.btn_edit)
        bot.addWidget(self.btn_delete_tmnt)
        bot.addStretch()
        L.addLayout(bot)

        # programmatically enforce minimum height on list frame to prevent it from collapsing to 0
        list_frame.setMinimumHeight(_px(200, self._scale))

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        self._sync_action_state()

    def _on_scroll_active(self):
        try:
            from ui.canvas.retro_effects import suspend_animations
            if not getattr(self, "_is_scrolling", False):
                self._is_scrolling = True
                suspend_animations(self)
            if not hasattr(self, "_scroll_resume_timer"):
                self._scroll_resume_timer = QTimer(self)
                self._scroll_resume_timer.setSingleShot(True)
                self._scroll_resume_timer.setInterval(250)
                self._scroll_resume_timer.timeout.connect(self._on_scroll_finished)
            self._scroll_resume_timer.start()
        except Exception:
            pass

    def _on_scroll_finished(self):
        self._is_scrolling = False
        try:
            from ui.canvas.retro_effects import resume_animations
            resume_animations(self)
        except Exception:
            pass

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
        has_due = bool(has_deck and self._collect_due_by_pdf(self.deck))
        has_reviewed_due = bool(has_deck and self._collect_due_by_pdf(self.deck, exclude_new=True))
        all_deck_cards = self._collect_all_by_pdf(self.deck) if has_deck else []
        has_any_cards = bool(has_deck and len(all_deck_cards) > 0)
        self.btn_add.setEnabled(has_deck)
        self.btn_add_text.setEnabled(has_deck)
        self.btn_due.setEnabled(has_due)
        self.btn_edit.setEnabled(has_card)
        self.btn_delete_tmnt.setEnabled(has_card)
        self.btn_all.setEnabled(has_reviewed_due)
        if hasattr(self, "btn_practice") and self.btn_practice:
            self.btn_practice.setEnabled(has_any_cards)
        new_groups = self._collect_new_by_pdf(self.deck) if has_deck else []
        new_count = sum(len(g) for g in new_groups)
        if hasattr(self, "banner") and hasattr(self.banner, "set_new_cards_count"):
            self.banner.set_new_cards_count(new_count)

    def _review_selected(self):
        row = self.card_list.currentRow()
        if row < 0 or not self.deck:
            return
        cards = self.deck.get("cards", [])
        if 0 <= row < len(cards):
            self._start_review([cards[row]])

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
        if hasattr(self, "banner") and hasattr(self.banner, "set_new_cards_count"):
            self.banner.set_new_cards_count(0)
        self._sync_action_state()


# ══════════════════════════════════════════════════════════════════════════════
class TMNTBgmWidget(QFrame):
    clicked = pyqtSignal()

    def __init__(self, data=None, parent=None, scale=None):
        super().__init__(parent)
        self._data = data if isinstance(data, dict) else {}
        self._scale = scale if scale is not None else _tmnt_scale(data)
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
    BRAND_BASE_FONT_PX = 18
    BRAND_TITLE_SCALE = 1.5

    btn_save_clicked = pyqtSignal()
    btn_math_clicked = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_report_clicked = pyqtSignal()
    btn_theme_clicked = pyqtSignal(object)
    btn_help_clicked = pyqtSignal()
    btn_about_clicked = pyqtSignal()
    btn_shortcuts_clicked = pyqtSignal()
    recovery_clicked = pyqtSignal()
    font_change = pyqtSignal(int)  # -1 / 0 / +1
    bgm_toggle = pyqtSignal()
    volume_changed = pyqtSignal(int)

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._scale = _tmnt_scale(data)
        self._data = data if isinstance(data, dict) else {}
        self.setObjectName("tmnt_topbar1")
        self.setFixedHeight(_px(58, self._scale))
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
        self._brand_glitch_idx = 0
        self._brand_flicker_idx = 0
        self._more_btn = None
        self._settings_btn = None
        self._more_panel = None
        self._settings_panel = None
        self._pending_panel = None
        self._panel_hide_timer = QTimer(self)
        self._panel_hide_timer.setSingleShot(True)
        self._panel_hide_timer.timeout.connect(self._hide_unhovered_panel)
        self._build_ui()
        self._brand_glitch_timer = QTimer(self)
        self._brand_glitch_timer.timeout.connect(self._advance_brand_glitch)
        self._brand_glitch_timer.setInterval(240)
        self._brand_flicker_timer = QTimer(self)
        self._brand_flicker_timer.timeout.connect(self._advance_brand_flicker)
        self._brand_flicker_timer.setInterval(420)
        self._set_brand_animations_enabled(True)
        self._quote_idx = 0
        self._quote_timer = QTimer(self)
        self._quote_timer.timeout.connect(self._rotate_quote)
        self._quote_timer.setInterval(8000)
        self._set_quote_rotation_enabled(True)

        try:
            from ui.canvas.retro_effects import register_retro_widget
            register_retro_widget(self)
        except Exception:
            pass

    def sync_timer(self):
        self._set_brand_animations_enabled(True)
        self._set_quote_rotation_enabled(True)

    def _set_brand_animations_enabled(self, enabled):
        enabled = bool(enabled) and _home_animations_enabled() and self.isVisible()
        for timer in (
            getattr(self, "_brand_glitch_timer", None),
            getattr(self, "_brand_flicker_timer", None),
        ):
            if timer is None:
                continue
            if enabled:
                if not timer.isActive():
                    timer.start()
            elif timer.isActive():
                timer.stop()

    def _set_quote_rotation_enabled(self, enabled):
        enabled = bool(enabled) and _home_animations_enabled() and self.isVisible()
        timer = getattr(self, "_quote_timer", None)
        if timer is None:
            return
        if enabled:
            if not timer.isActive():
                timer.start()
        elif timer.isActive():
            timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._set_brand_animations_enabled(True)
        self._set_quote_rotation_enabled(True)

    def hideEvent(self, event):
        self._set_brand_animations_enabled(False)
        self._set_quote_rotation_enabled(False)
        super().hideEvent(event)

    def _build_ui(self):
        L = QHBoxLayout(self)
        L.setContentsMargins(
            _px(16, self._scale),
            _px(6, self._scale),
            _px(16, self._scale),
            _px(6, self._scale),
        )
        L.setSpacing(_px(14, self._scale))

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_l = QHBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(0)

        self.brand_name = QLabel("ANKI OCCLUSION")
        self.brand_name.setObjectName("tmnt_brand_name")
        self.brand_name.setStyleSheet(self._brand_name_ss())

        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        from theme_manager import is_retro_theme
        if not is_retro_theme(theme_name):
            theme_name = "tmnt"

        # Set explicitly in Python to prevent sizeHint layout calculation errors and clipping
        brand_font = QFont("Orbitron")
        brand_font.setPixelSize(self._brand_font_px())
        brand_font.setBold(True)
        self.brand_name.setFont(brand_font)

        self.ghost_r = QLabel("ANKI OCCLUSION", self.brand_name)
        self.ghost_r.setStyleSheet(
            self._brand_name_ss().replace(T_NEON, "rgba(255, 77, 77, 180)")
        )
        self.ghost_r.setFont(brand_font)
        self.ghost_r.move(_px(-3, self._scale), _px(-1, self._scale))
        self.ghost_r.hide()

        self.ghost_c = QLabel("ANKI OCCLUSION", self.brand_name)
        self.ghost_c.setStyleSheet(
            self._brand_name_ss().replace(T_NEON, "rgba(102, 252, 241, 180)")
        )
        self.ghost_c.setFont(brand_font)
        self.ghost_c.move(_px(3, self._scale), _px(1, self._scale))
        self.ghost_c.hide()

        self._brand_name_glow = QGraphicsDropShadowEffect(self.brand_name)
        self._brand_name_glow.setColor(QColor(102, 252, 241, 150))
        self._brand_name_glow.setBlurRadius(_px(7, self._scale))
        self._brand_name_glow.setOffset(0, 0)
        self.brand_name.setGraphicsEffect(self._brand_name_glow)

        left_l.addWidget(self.brand_name, 0, Qt.AlignVCenter)
        left_l.addStretch()
        L.addWidget(left, 1)

        btn_math = self._make_nav_button("🧮 MATH TRAINER", "Math Trainer")
        btn_journal = self._make_nav_button("📓", "Daily Journal")
        btn_journal.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: transparent;
                    color: {T_SUBTEXT};
                    border: none;
                    border-bottom: 2px solid transparent;
                    font-family: {T_MONO};
                    font-size: 24px;
                    font-weight: bold;
                    padding: 6px 8px;
                }}
                QPushButton:hover {{
                    color: {T_GREEN};
                    border-bottom: 2px solid {T_GREEN};
                }}
            """,
                self._scale,
            )
        )
        btn_report = self._make_nav_button("📊", "Mission Report Card")
        btn_report.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: transparent;
                    color: {T_SUBTEXT};
                    border: none;
                    border-bottom: 2px solid transparent;
                    font-family: {T_MONO};
                    font-size: 24px;
                    font-weight: bold;
                    padding: 6px 8px;
                }}
                QPushButton:hover {{
                    color: {T_GREEN};
                    border-bottom: 2px solid {T_GREEN};
                }}
            """,
                self._scale,
            )
        )
        self._more_btn = self._make_nav_button("MORE ▾", "More")
        self._more_btn.installEventFilter(self)
        self._more_panel = self._build_more_panel()

        btn_math.clicked.connect(self.btn_math_clicked)
        btn_journal.clicked.connect(self.btn_journal_clicked)
        btn_report.clicked.connect(self.btn_report_clicked)
        self._more_btn.clicked.connect(
            lambda: self._toggle_panel(self._more_panel, self._more_btn, "left")
        )

        center = QWidget()
        center.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        center_l = QHBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(_px(10, self._scale))
        center_l.addStretch()
        for b in (btn_math, btn_journal, btn_report, self._more_btn):
            center_l.addWidget(b, 0, Qt.AlignCenter)
        center_l.addStretch()
        L.addWidget(center, 1)

        right = QWidget()
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_l = QHBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(_px(10, self._scale))
        right_l.addStretch()

        self._save_btn = self._make_square_action(
            "💾",
            T_PURPLE,
            hover_color=T_PURPLE,
            hover_fill="rgba(176,136,249,0.20)",
        )
        self._save_btn.setToolTip("Save now")
        self._save_btn.clicked.connect(self._emit_save)
        right_l.addWidget(self._save_btn, 0, Qt.AlignVCenter)

        self._settings_btn = self._make_square_action(
            "⚙",
            T_SUBTEXT,
            hover_color=T_NEON,
        )
        self._settings_btn.installEventFilter(self)
        self._settings_panel = self._build_settings_panel()
        self._settings_btn.clicked.connect(
            lambda: self._toggle_panel(
                self._settings_panel, self._settings_btn, "right"
            )
        )
        right_l.addWidget(self._settings_btn, 0, Qt.AlignVCenter)

        self.bgm_widget = TMNTBgmWidget(
            data=self._data,
            scale=self._scale,
            parent=self,
        )
        self.bgm_widget.setStyleSheet(
            _scale_ss(
                f"""
                QFrame {{
                    background: {T_PANEL};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                }}
                QLabel {{ background: transparent; border: none; }}
                QFrame:hover {{
                    background: #2a313c;
                    border-color: {T_GREEN};
                }}
            """,
                self._scale,
            )
        )
        self.bgm_widget.clicked.connect(self.bgm_toggle)
        right_l.addWidget(self.bgm_widget, 0, Qt.AlignVCenter)

        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")

        if theme_name == "arcanum":
            from arcane_assets import ArcaneAssets
            mentor = ArcaneAssets.get_instance().get_archmage_widget(scale=self._scale)
            mentor.setFixedSize(_px(244, self._scale), _px(42, self._scale))
            self.quote_lbl = mentor.quote_lbl
            self.name_lbl = mentor.name_lbl
        else:
            mentor = QFrame()
            mentor.setFixedSize(_px(244, self._scale), _px(42, self._scale))
            mentor.setStyleSheet(
                _scale_ss(
                    f"""
                QFrame {{
                    background: {T_PANEL};
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

            av = QLabel("◎")
            av.setFixedSize(_px(28, self._scale), _px(28, self._scale))
            av.setAlignment(Qt.AlignCenter)
            av.setStyleSheet(
                _scale_ss(
                    f"font-size: 16px; color: {T_PURPLE}; background: rgba(176,136,249,0.10); "
                    f"border: 1px solid #5b616d; border-radius: 14px;",
                    self._scale,
                )
            )
            ml.addWidget(av)

            self.quote_lbl = QLabel(MENTOR_QUOTES[0][0])
            self.quote_lbl.setStyleSheet(
                _scale_ss(
                    f"color: {T_PURPLE}; font-size: 8px; font-weight: 900; "
                    f"font-family: {T_MONO};",
                    self._scale,
                )
            )
            self.name_lbl = QLabel(MENTOR_QUOTES[0][1])
            self.name_lbl.setStyleSheet(
                _scale_ss(
                    f"color: {T_SUBTEXT}; font-size: 9px; font-family: {T_MONO};",
                    self._scale,
                )
            )
            q_col = QVBoxLayout()
            q_col.setContentsMargins(0, 0, 0, 0)
            q_col.setSpacing(_px(1, self._scale))
            q_col.addWidget(self.quote_lbl)
            q_col.addWidget(self.name_lbl)
            ml.addLayout(q_col)
        right_l.addWidget(mentor, 0, Qt.AlignVCenter)
        L.addWidget(right, 1)

    def _make_nav_button(self, text, tip, color=None):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.setStyleSheet(
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
        return button

    def _make_theme_nav_button(self, text, tip):
        button = QPushButton(text)
        button.setObjectName("tmnt_mode_btn")
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton#tmnt_mode_btn {{
                    background: transparent;
                    color: #60A5FA;
                    border: none;
                    border-bottom: 2px solid transparent;
                    font-family: {T_MONO};
                    font-size: 12px;
                    font-weight: bold;
                    padding: 6px 8px;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                }}
                QPushButton#tmnt_mode_btn:hover {{
                    color: {T_TEXT};
                    border-bottom: 2px solid {T_NEON};
                }}
            """,
                self._scale,
            )
        )
        return button

    def _make_square_action(
        self, text, border_color, hover_color=None, hover_fill="transparent"
    ):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(_px(30, self._scale), _px(30, self._scale))
        hover_color = hover_color or border_color
        border = T_PURPLE if border_color == T_PURPLE else T_BORDER
        bg = hover_fill if hover_fill != "transparent" else "#2a313c"
        button.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_PANEL};
                    color: {border_color};
                    border: 1px solid {border};
                    border-radius: 4px;
                    font-family: 'Segoe UI Emoji', 'Segoe UI Symbol', {T_MONO};
                    font-size: 13px;
                    font-weight: bold;
                    padding: 0px;
                    letter-spacing: 0px;
                    text-transform: none;
                }}
                QPushButton:hover {{
                    background: {bg};
                    color: {hover_color};
                    border-color: {hover_color};
                }}
            """,
                self._scale,
            )
        )
        return button

    def _build_more_panel(self):
        panel = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        panel.installEventFilter(self)
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setObjectName("tmnt_more_panel")
        panel.setStyleSheet(
            _scale_ss(
                f"""
                QFrame#tmnt_more_panel {{
                    background: {T_PANEL};
                    border: 1px solid {T_GREEN};
                    border-radius: 4px;
                }}
            """,
                self._scale,
            )
        )
        _apply_glow(panel, T_GREEN, blur=_px(20, self._scale), alpha=110)
        panel._fade = QPropertyAnimation(panel, b"windowOpacity", self)
        panel._fade.setDuration(130)
        panel._fade.setEasingCurve(QEasingCurve.OutCubic)
        panel_l = QVBoxLayout(panel)
        panel_l.setContentsMargins(0, _px(6, self._scale), 0, _px(6, self._scale))
        panel_l.setSpacing(0)
        panel_l.addWidget(
            self._menu_button("⌨  SHORTCUTS", T_GREEN, self._emit_shortcuts, divider=True)
        )
        panel_l.addWidget(
            self._menu_button("❓  HELP", T_RED, self._emit_help, divider=True)
        )
        panel_l.addWidget(self._menu_button("ⓘ  ABOUT", T_SUBTEXT, self._emit_about))
        panel.adjustSize()
        return panel

    def _build_settings_panel(self):
        panel = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        panel.installEventFilter(self)
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setObjectName("tmnt_settings_panel")
        panel.setStyleSheet(
            _scale_ss(
                f"""
                QFrame#tmnt_settings_panel {{
                    background: {T_PANEL};
                    border: 1px solid {T_NEON};
                    border-radius: 4px;
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """,
                self._scale,
            )
        )
        _apply_glow(panel, T_NEON, blur=_px(24, self._scale), alpha=90)
        panel._fade = QPropertyAnimation(panel, b"windowOpacity", self)
        panel._fade.setDuration(130)
        panel._fade.setEasingCurve(QEasingCurve.OutCubic)
        
        # Outer layout of the popup frame
        outer_l = QVBoxLayout(panel)
        outer_l.setContentsMargins(0, 0, 0, 0)
        
        # Scroll Area
        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(_px(330, self._scale))
        scroll.setStyleSheet(
            _scale_ss(
                f"""
                QScrollArea {{
                    background: transparent;
                    border: none;
                }}
                QScrollBar:vertical {{
                    background: {T_BG};
                    width: 6px;
                    margin: 0px;
                }}
                QScrollBar::handle:vertical {{
                    background: {T_GREEN};
                    border-radius: 3px;
                    min-height: 20px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background: {T_GREEN};
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
                """,
                self._scale,
            )
        )
        
        container = QWidget(scroll)
        container.setObjectName("settings_container")
        container.setStyleSheet("background: transparent; border: none;")
        
        panel_l = QVBoxLayout(container)
        panel_l.setContentsMargins(
            _px(12, self._scale),
            _px(12, self._scale),
            _px(12, self._scale),
            _px(12, self._scale),
        )
        panel_l.setSpacing(_px(10, self._scale))

        theme_lbl = QLabel("THEME")
        theme_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(theme_lbl)

        theme_box = QFrame()
        theme_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        theme_l = QHBoxLayout(theme_box)
        theme_l.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        theme_l.setSpacing(_px(6, self._scale))
        theme_mode_lbl = QLabel("ACTIVE MODE")
        theme_mode_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        theme_l.addWidget(theme_mode_lbl)
        theme_l.addStretch()

        from PyQt5.QtWidgets import QComboBox
        from theme_manager import normalize_theme
        self._btn_theme = QComboBox()
        self._btn_theme.addItems(["📚 CLASSIC THEME", "🐢 TMNT THEME", "🎮 MANHATTAN", "🔮 ARCANUM"])
        self._btn_theme.setCursor(Qt.PointingHandCursor)
        self._btn_theme.setStyleSheet(
            _scale_ss(
                f"""
                QComboBox {{
                    background: {T_BG};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    padding: 2px 6px;
                    color: {T_PURPLE};
                    font-family: {T_MONO};
                    font-size: 9px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: {T_PANEL};
                    color: {T_PURPLE};
                    border: 1px solid {T_BORDER};
                    selection-background-color: {T_BG};
                    selection-color: {T_NEON};
                }}
                """,
                self._scale,
            )
        )
        _theme_to_idx = {"classic": 0, "tmnt": 1, "manhattan": 2, "arcanum": 3}
        saved_theme = self._data.get("_theme", "classic")
        self._btn_theme.setCurrentIndex(_theme_to_idx.get(normalize_theme(saved_theme), 0))
        self._btn_theme.currentIndexChanged.connect(self.btn_theme_clicked.emit)
        theme_l.addWidget(self._btn_theme)
        panel_l.addWidget(theme_box)

        scale_lbl = QLabel("VISUAL SCALE")
        scale_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(scale_lbl)

        scale_box = QFrame()
        scale_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        scale_l = QHBoxLayout(scale_box)
        scale_l.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        scale_l.setSpacing(_px(6, self._scale))
        size_lbl = QLabel("SIZE")
        size_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        scale_l.addWidget(size_lbl)
        scale_l.addStretch()
        scale_l.addWidget(self._font_button("A−", -1))
        scale_l.addWidget(self._font_button("A", 0, active=True))
        scale_l.addWidget(self._font_button("A+", +1))
        panel_l.addWidget(scale_box)

        volume_lbl = QLabel("VOLUME")
        volume_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(volume_lbl)

        volume_box = QFrame()
        volume_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        volume_layout = QHBoxLayout(volume_box)
        volume_layout.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        volume_layout.setSpacing(_px(6, self._scale))
        volume_txt_lbl = QLabel("SOUND OUTPUT")
        volume_txt_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        volume_layout.addWidget(volume_txt_lbl)
        volume_layout.addStretch()

        self._volume_slider = QSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._data.get("_volume", 40))
        self._volume_slider.setFixedWidth(_px(80, self._scale))
        self._volume_slider.setFixedHeight(_px(16, self._scale))
        self._volume_slider.setCursor(Qt.PointingHandCursor)
        self._volume_slider.setStyleSheet(_scale_ss(
            """
            QSlider {
                background: transparent;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 3px;
                background: rgba(114, 255, 79, 0.2);
                border-radius: 1.5px;
            }
            QSlider::sub-page:horizontal {
                background: #72FF4F;
                border-radius: 1.5px;
            }
            QSlider::handle:horizontal {
                background: #72FF4F;
                width: 8px;
                height: 8px;
                margin-top: -2.5px;
                margin-bottom: -2.5px;
                border-radius: 4px;
            }
            """,
            self._scale
        ))
        self._volume_slider.valueChanged.connect(self._on_volume_slider_changed)

        btn_dec = QPushButton("−")
        btn_dec.setCursor(Qt.PointingHandCursor)
        btn_dec.setFixedSize(_px(20, self._scale), _px(20, self._scale))
        btn_dec.setStyleSheet(_scale_ss(
            f"""
            QPushButton {{
                background: {T_BG};
                color: {T_NEON};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
                font-family: {T_MONO};
                font-size: 10px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(102,252,241,0.12);
                border-color: {T_NEON};
                color: #FFFFFF;
            }}
            """,
            self._scale
        ))
        btn_dec.clicked.connect(self._dec_volume)

        btn_inc = QPushButton("＋")
        btn_inc.setCursor(Qt.PointingHandCursor)
        btn_inc.setFixedSize(_px(20, self._scale), _px(20, self._scale))
        btn_inc.setStyleSheet(_scale_ss(
            f"""
            QPushButton {{
                background: {T_BG};
                color: {T_NEON};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
                font-family: {T_MONO};
                font-size: 10px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(102,252,241,0.12);
                border-color: {T_NEON};
                color: #FFFFFF;
            }}
            """,
            self._scale
        ))
        btn_inc.clicked.connect(self._inc_volume)

        volume_layout.addWidget(btn_dec)
        volume_layout.addWidget(self._volume_slider)
        volume_layout.addWidget(btn_inc)
        panel_l.addWidget(volume_box)

        scroll_lbl = QLabel("SCROLL SPEED")
        scroll_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(scroll_lbl)

        scroll_box = QFrame()
        scroll_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        scroll_layout = QHBoxLayout(scroll_box)
        scroll_layout.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        scroll_layout.setSpacing(_px(6, self._scale))
        scroll_txt_lbl = QLabel("SENSITIVITY")
        scroll_txt_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        scroll_layout.addWidget(scroll_txt_lbl)
        
        current_scroll = int(self._data.get("_scroll_speed", 35))
        self._scroll_val_lbl = QLabel(f"{current_scroll}%")
        self._scroll_val_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold;",
                self._scale,
            )
        )
        scroll_layout.addWidget(self._scroll_val_lbl)
        scroll_layout.addStretch()

        self._scroll_slider = QSlider(Qt.Horizontal)
        self._scroll_slider.setRange(10, 100)
        self._scroll_slider.setSingleStep(5)
        self._scroll_slider.setValue(current_scroll)
        self._scroll_slider.setFixedWidth(_px(80, self._scale))
        self._scroll_slider.setFixedHeight(_px(16, self._scale))
        self._scroll_slider.setCursor(Qt.PointingHandCursor)
        self._scroll_slider.setStyleSheet(_scale_ss(
            f"""
            QSlider {{
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 3px;
                background: rgba(102, 252, 241, 0.2);
                border-radius: 1.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {T_NEON};
                border-radius: 1.5px;
            }}
            QSlider::handle:horizontal {{
                background: {T_NEON};
                width: 8px;
                height: 8px;
                margin-top: -2.5px;
                margin-bottom: -2.5px;
                border-radius: 4px;
            }}
            """,
            self._scale
        ))
        self._scroll_slider.valueChanged.connect(self._on_tmnt_scroll_slider_changed)

        btn_scroll_dec = QPushButton("−")
        btn_scroll_dec.setCursor(Qt.PointingHandCursor)
        btn_scroll_dec.setFixedSize(_px(20, self._scale), _px(20, self._scale))
        btn_scroll_dec.setStyleSheet(_scale_ss(
            f"""
            QPushButton {{
                background: {T_BG};
                color: {T_NEON};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
                font-family: {T_MONO};
                font-size: 10px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(102,252,241,0.12);
                border-color: {T_NEON};
                color: #FFFFFF;
            }}
            """,
            self._scale
        ))
        btn_scroll_dec.clicked.connect(self._dec_scroll_speed)

        btn_scroll_inc = QPushButton("＋")
        btn_scroll_inc.setCursor(Qt.PointingHandCursor)
        btn_scroll_inc.setFixedSize(_px(20, self._scale), _px(20, self._scale))
        btn_scroll_inc.setStyleSheet(_scale_ss(
            f"""
            QPushButton {{
                background: {T_BG};
                color: {T_NEON};
                border: 1px solid {T_BORDER};
                border-radius: 4px;
                font-family: {T_MONO};
                font-size: 10px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(102,252,241,0.12);
                border-color: {T_NEON};
                color: #FFFFFF;
            }}
            """,
            self._scale
        ))
        btn_scroll_inc.clicked.connect(self._inc_scroll_speed)

        scroll_layout.addWidget(btn_scroll_dec)
        scroll_layout.addWidget(self._scroll_slider)
        scroll_layout.addWidget(btn_scroll_inc)
        panel_l.addWidget(scroll_box)

        contrast_lbl = QLabel("PDF CONTRAST")
        contrast_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(contrast_lbl)

        contrast_box = QFrame()
        contrast_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        contrast_l = QHBoxLayout(contrast_box)
        contrast_l.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        contrast_l.setSpacing(_px(6, self._scale))
        contrast_mode_lbl = QLabel("DARK COLORS / INVERTED")
        contrast_mode_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        contrast_l.addWidget(contrast_mode_lbl)
        contrast_l.addStretch()

        from PyQt5.QtWidgets import QCheckBox
        self._cb_invert_pdf = QCheckBox()
        self._cb_invert_pdf.setCursor(Qt.PointingHandCursor)
        self._cb_invert_pdf.setStyleSheet(
            _scale_ss(
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 1px solid {T_BORDER}; background: {T_BG}; }}"
                f"QCheckBox::indicator:checked {{ border: 1px solid {T_NEON}; background: {T_NEON}; }}"
                , self._scale
            )
        )
        self._cb_invert_pdf.setChecked(store.get().get("_invert_pdf", False))
        self._cb_invert_pdf.stateChanged.connect(self._on_tmnt_contrast_changed)
        contrast_l.addWidget(self._cb_invert_pdf)
        panel_l.addWidget(contrast_box)

        window_lbl = QLabel("WINDOW MODE")
        window_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(window_lbl)

        window_box = QFrame()
        window_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        window_layout = QHBoxLayout(window_box)
        window_layout.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        window_layout.setSpacing(_px(6, self._scale))
        window_mode_lbl = QLabel("KEEP OPEN IN FULLSCREEN")
        window_mode_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        window_layout.addWidget(window_mode_lbl)
        window_layout.addStretch()

        self._cb_keep_fullscreen = QCheckBox()
        self._cb_keep_fullscreen.setCursor(Qt.PointingHandCursor)
        self._cb_keep_fullscreen.setStyleSheet(
            _scale_ss(
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 1px solid {T_BORDER}; background: {T_BG}; }}"
                f"QCheckBox::indicator:checked {{ border: 1px solid {T_NEON}; background: {T_NEON}; }}"
                , self._scale
            )
        )
        self._cb_keep_fullscreen.setChecked(self._data.get("_keep_fullscreen", False))
        self._cb_keep_fullscreen.stateChanged.connect(self._on_tmnt_fullscreen_changed)
        window_layout.addWidget(self._cb_keep_fullscreen)
        panel_l.addWidget(window_box)

        fx_lbl = QLabel("VISUAL FX / ANIMATIONS")
        fx_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(fx_lbl)

        fx_box = QFrame()
        fx_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        fx_l = QHBoxLayout(fx_box)
        fx_l.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        fx_l.setSpacing(_px(6, self._scale))
        fx_mode_lbl = QLabel("ENABLE CRT & DUST PARTICLES")
        fx_mode_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        fx_l.addWidget(fx_mode_lbl)
        fx_l.addStretch()

        self._cb_home_animations = QCheckBox()
        self._cb_home_animations.setCursor(Qt.PointingHandCursor)
        self._cb_home_animations.setStyleSheet(
            _scale_ss(
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 1px solid {T_BORDER}; background: {T_BG}; }}"
                f"QCheckBox::indicator:checked {{ border: 1px solid {T_NEON}; background: {T_NEON}; }}"
                , self._scale
            )
        )
        self._cb_home_animations.setChecked(_home_animations_enabled())
        self._cb_home_animations.stateChanged.connect(self._on_tmnt_animations_changed)
        fx_l.addWidget(self._cb_home_animations)
        panel_l.addWidget(fx_box)

        # Numpad Quick Revision Setting
        numpad_lbl = QLabel("KEYBOARD & SHORTCUTS")
        numpad_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(numpad_lbl)

        numpad_box = QFrame()
        numpad_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        numpad_l = QHBoxLayout(numpad_box)
        numpad_l.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        numpad_l.setSpacing(_px(6, self._scale))

        numpad_text_lbl = QLabel("NUMPAD QUICK REVISION (1-9 DAYS)")
        numpad_text_lbl.setToolTip("Use Numpad keys 1–9 during review to reschedule cards for 1–9 days without altering SM-2 Ease Factor.")
        numpad_text_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        numpad_l.addWidget(numpad_text_lbl)
        numpad_l.addStretch()

        self._cb_numpad_revision = QCheckBox()
        self._cb_numpad_revision.setCursor(Qt.PointingHandCursor)
        self._cb_numpad_revision.setStyleSheet(
            _scale_ss(
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 1px solid {T_BORDER}; background: {T_BG}; }}"
                f"QCheckBox::indicator:checked {{ border: 1px solid {T_NEON}; background: {T_NEON}; }}"
                , self._scale
            )
        )
        self._cb_numpad_revision.setChecked(store.get().get("_numpad_custom_revision", False))
        self._cb_numpad_revision.stateChanged.connect(self._on_tmnt_numpad_revision_changed)
        numpad_l.addWidget(self._cb_numpad_revision)
        panel_l.addWidget(numpad_box)

        archive_lbl = QLabel("MISSION ARCHIVE")
        archive_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(archive_lbl)

        archive_box = QFrame()
        archive_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        archive_l = QHBoxLayout(archive_box)
        archive_l.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        archive_l.setSpacing(_px(6, self._scale))
        archive_icon = QLabel("⌂")
        archive_icon.setStyleSheet(
            _scale_ss(f"color: {T_SUBTEXT}; font-size: 10px;", self._scale)
        )
        self._archive_val = QLabel()
        self._archive_val.setStyleSheet(
            _scale_ss(
                f"color: {T_PURPLE}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        self._archive_btn = QPushButton("SET")
        self._archive_btn.setCursor(Qt.PointingHandCursor)
        self._archive_btn.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {T_NEON};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    background: rgba(102,252,241,0.12);
                    border-color: {T_NEON};
                    color: #FFFFFF;
                }}
            """,
                self._scale,
            )
        )
        self._archive_btn.clicked.connect(self._choose_mission_archive)
        archive_l.addWidget(archive_icon)
        archive_l.addWidget(self._archive_val, 1)
        archive_l.addWidget(self._archive_btn, 0, Qt.AlignRight)
        self._archive_box = archive_box
        panel_l.addWidget(archive_box)
        self._refresh_archive_display()

        # Google Drive Backup Section
        gdrive_lbl = QLabel("GOOGLE DRIVE SYNC")
        gdrive_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px;",
                self._scale,
            )
        )
        panel_l.addWidget(gdrive_lbl)

        gdrive_box = QFrame()
        gdrive_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        gdrive_layout = QHBoxLayout(gdrive_box)
        gdrive_layout.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        gdrive_layout.setSpacing(_px(6, self._scale))
        
        self._gdrive_status_lbl = QLabel("Checking status...")
        self._gdrive_status_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_SUBTEXT}; font-family: {T_MONO}; font-size: 9px;",
                self._scale,
            )
        )
        gdrive_layout.addWidget(self._gdrive_status_lbl, 1)

        self._gdrive_sync_btn = QPushButton("SYNC")
        self._gdrive_sync_btn.setCursor(Qt.PointingHandCursor)
        self._gdrive_sync_btn.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {T_NEON};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    background: rgba(102,252,241,0.12);
                    border-color: {T_NEON};
                    color: #FFFFFF;
                }}
            """,
                self._scale,
            )
        )
        self._gdrive_sync_btn.clicked.connect(self._manual_gdrive_sync)
        gdrive_layout.addWidget(self._gdrive_sync_btn, 0, Qt.AlignRight)

        self._gdrive_link_btn = QPushButton("LINK")
        self._gdrive_link_btn.setCursor(Qt.PointingHandCursor)
        self._gdrive_link_btn.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {T_NEON};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    background: rgba(102,252,241,0.12);
                    border-color: {T_NEON};
                    color: #FFFFFF;
                }}
            """,
                self._scale,
            )
        )
        self._gdrive_link_btn.clicked.connect(self._toggle_gdrive_link)
        gdrive_layout.addWidget(self._gdrive_link_btn, 0, Qt.AlignRight)
        
        panel_l.addWidget(gdrive_box)

        # Cloud Asset Utilities Section
        assets_lbl = QLabel("CLOUD ASSET UTILITIES")
        assets_lbl.setStyleSheet(
            _scale_ss(
                f"color: {T_NEON}; font-family: {T_MONO}; font-size: 9px; font-weight: bold; letter-spacing: 2px; margin-top: 10px;",
                self._scale,
            )
        )
        panel_l.addWidget(assets_lbl)

        assets_box = QFrame()
        assets_box.setStyleSheet(
            _scale_ss(
                f"background: {T_BG}; border: 1px solid {T_BORDER}; border-radius: 4px;",
                self._scale,
            )
        )
        assets_layout = QHBoxLayout(assets_box)
        assets_layout.setContentsMargins(
            _px(8, self._scale),
            _px(6, self._scale),
            _px(8, self._scale),
            _px(6, self._scale),
        )
        assets_layout.setSpacing(_px(6, self._scale))

        self._assets_backup_btn = QPushButton("BACKUP ASSETS")
        self._assets_backup_btn.setCursor(Qt.PointingHandCursor)
        self._assets_backup_btn.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {T_GREEN};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    background: {_hex_to_rgba(T_GREEN, 0.12)};
                    border-color: {T_GREEN};
                    color: #FFFFFF;
                }}
            """,
                self._scale,
            )
        )
        self._assets_backup_btn.clicked.connect(self._backup_assets_to_cloud)
        assets_layout.addWidget(self._assets_backup_btn, 0)

        self._assets_restore_btn = QPushButton("RESTORE ASSETS")
        self._assets_restore_btn.setCursor(Qt.PointingHandCursor)
        self._assets_restore_btn.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {T_NEON};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    background: {_hex_to_rgba(T_NEON, 0.12)};
                    border-color: {T_NEON};
                    color: #FFFFFF;
                }}
            """,
                self._scale,
            )
        )
        self._assets_restore_btn.clicked.connect(self._sync_assets_from_cloud)
        assets_layout.addWidget(self._assets_restore_btn, 0)

        self._assets_prune_btn = QPushButton("PRUNE CLOUD")
        self._assets_prune_btn.setCursor(Qt.PointingHandCursor)
        self._assets_prune_btn.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {T_RED};
                    border: 1px solid {T_BORDER};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px 8px;
                }}
                QPushButton:hover {{
                    background: {_hex_to_rgba(T_RED, 0.12)};
                    border-color: {T_RED};
                    color: #FFFFFF;
                }}
            """,
                self._scale,
            )
        )
        self._assets_prune_btn.clicked.connect(self._prune_cloud_assets)
        assets_layout.addWidget(self._assets_prune_btn, 0)

        panel_l.addWidget(assets_box)

        panel_l.addWidget(
            self._menu_button(
                "RECOVERY CENTER", T_PURPLE, self.recovery_clicked.emit
            )
        )

        scroll.setWidget(container)
        outer_l.addWidget(scroll)
        
        # Save references to prevent garbage collection and allow dynamic resizing
        panel._scroll = scroll
        panel._container = container

        panel.adjustSize()
        return panel

    def _menu_button(self, text, accent_color, slot, divider=False):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        line = (
            f"border-bottom: 1px solid {T_BORDER};"
            if divider
            else "border-bottom: none;"
        )
        button.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: transparent;
                    color: {accent_color};
                    border: none;
                    {line}
                    font-family: 'Segoe UI Emoji', 'Segoe UI Symbol', {T_MONO};
                    font-size: 11px;
                    font-weight: bold;
                    text-align: left;
                    padding: 8px 14px;
                }}
                QPushButton:hover {{
                    background: {T_CARD};
                    color: {T_NEON};
                }}
            """,
                self._scale,
            )
        )
        button.clicked.connect(slot)
        return button

    def _font_button(self, text, delta, active=False):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(_px(28, self._scale), _px(24, self._scale))
        border = T_GREEN if active else T_BORDER
        text_color = T_TEXT if active else T_SUBTEXT
        button.setStyleSheet(
            _scale_ss(
                f"""
                QPushButton {{
                    background: {T_CARD};
                    color: {text_color};
                    border: 1px solid {border};
                    border-radius: 4px;
                    font-family: {T_MONO};
                    font-size: 10px;
                    font-weight: bold;
                    padding: 0px;
                    letter-spacing: 0px;
                    text-transform: none;
                }}
                QPushButton:hover {{
                    background: rgba(69,162,71,0.25);
                    color: #FFFFFF;
                    border-color: {T_GREEN};
                }}
            """,
                self._scale,
            )
        )
        button.clicked.connect(lambda _, d=delta: self._emit_font(d))
        return button

    def _refresh_archive_display(self):
        if not hasattr(self, "_archive_val") or self._archive_val is None:
            return
        label = archive_label()
        tooltip = archive_tooltip()
        if get_mission_archive_root():
            label = f"{label}"
        self._archive_val.setText(label)
        self._archive_val.setToolTip(tooltip)
        if hasattr(self, "_archive_box") and self._archive_box is not None:
            self._archive_box.setToolTip(tooltip)
        if hasattr(self, "_archive_btn") and self._archive_btn is not None:
            self._archive_btn.setToolTip(tooltip)

    def _choose_mission_archive(self):
        self._hide_panel(self._settings_panel)
        start_dir = (
            get_mission_archive_root()
            or os.path.dirname(current_data_file())
            or os.path.expanduser("~")
        )
        new_root = QFileDialog.getExistingDirectory(
            self, "Select Mission Archive Folder", start_dir
        )
        if not new_root:
            return
        try:
            summary = migrate_to_mission_archive(new_root, data=store.get())
        except Exception as ex:
            QMessageBox.warning(
                self, "Mission Archive", f"Could not switch Mission Archive:\n{ex}"
            )
            return
        self._refresh_archive_display()
        win = self.window()
        if hasattr(win, "statusBar") and callable(win.statusBar):
            sb = win.statusBar()
            if sb is not None:
                sb.showMessage(f"Mission Archive set to {new_root}", 5000)
        QMessageBox.information(
            self,
            "Mission Archive",
            "Mission Archive updated.\n\n"
            f"Folder: {new_root}\n"
            f"Cards rewritten: {summary['cards_rewritten']}\n"
            f"PDFs copied: {summary['pdfs_copied']}\n"
            f"Images copied: {summary['images_copied']}\n"
            f"Cache entries copied: {summary['cache_entries_copied']}",
        )

    def _brand_font_px(self):
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        scale_factor = 1.0
        return int(round(self.BRAND_BASE_FONT_PX * self.BRAND_TITLE_SCALE * scale_factor))

    def _brand_name_ss(self):
        return _scale_ss(
            f"""
            QLabel#tmnt_brand_name {{
                color: {T_NEON};
                background: transparent;
                border: none;
                font-family: {T_PIXEL};
                font-size: {self._brand_font_px()}px;
                font-weight: 900;
                letter-spacing: 2px;
            }}
        """,
            self._scale,
        )

    def eventFilter(self, obj, event):
        if obj in (self._more_btn, self._more_panel):
            self._handle_panel_hover("more", event)
        elif obj in (self._settings_btn, self._settings_panel):
            self._handle_panel_hover("settings", event)
        return super().eventFilter(obj, event)

    def _handle_panel_hover(self, panel_name, event):
        if event.type() == QEvent.Enter:
            self._panel_hide_timer.stop()
            panel = self._more_panel if panel_name == "more" else self._settings_panel
            anchor = self._more_btn if panel_name == "more" else self._settings_btn
            if panel and anchor and not panel.isVisible():
                self._show_panel(
                    panel, anchor, "left" if panel_name == "more" else "right"
                )
        elif event.type() == QEvent.Leave:
            self._pending_panel = panel_name
            self._panel_hide_timer.start(1500)

    def _toggle_panel(self, panel, anchor, align):
        if panel.isVisible():
            self._hide_panel(panel)
        else:
            self._show_panel(panel, anchor, align)

    def _show_panel(self, panel, anchor, align):
        if (
            panel is self._more_panel
            and self._settings_panel
            and self._settings_panel.isVisible()
        ):
            self._hide_panel(self._settings_panel)
        if (
            panel is self._settings_panel
            and self._more_panel
            and self._more_panel.isVisible()
        ):
            self._hide_panel(self._more_panel)
        if panel is self._settings_panel:
            if hasattr(self, "_cb_invert_pdf") and self._cb_invert_pdf:
                self._cb_invert_pdf.blockSignals(True)
                self._cb_invert_pdf.setChecked(store.get().get("_invert_pdf", False))
                self._cb_invert_pdf.blockSignals(False)
            if hasattr(self, "_cb_keep_fullscreen") and self._cb_keep_fullscreen:
                self._cb_keep_fullscreen.blockSignals(True)
                self._cb_keep_fullscreen.setChecked(self._data.get("_keep_fullscreen", False))
                self._cb_keep_fullscreen.blockSignals(False)
            if hasattr(self, "_volume_slider") and self._volume_slider:
                self._volume_slider.blockSignals(True)
                self._volume_slider.setValue(self._data.get("_volume", 40))
                self._volume_slider.blockSignals(False)
            if hasattr(self, "_scroll_slider") and self._scroll_slider:
                self._scroll_slider.blockSignals(True)
                s_val = int(self._data.get("_scroll_speed", 35))
                self._scroll_slider.setValue(s_val)
                if hasattr(self, "_scroll_val_lbl") and self._scroll_val_lbl:
                    self._scroll_val_lbl.setText(f"{s_val}%")
                self._scroll_slider.blockSignals(False)
            if hasattr(self, "_cb_numpad_revision") and self._cb_numpad_revision:
                self._cb_numpad_revision.blockSignals(True)
                self._cb_numpad_revision.setChecked(store.get().get("_numpad_custom_revision", False))
                self._cb_numpad_revision.blockSignals(False)
            self._refresh_gdrive_display()
        
        # Reset constraints first to get true size hint
        panel.setMinimumHeight(0)
        panel.setMaximumHeight(16777215)
        panel.adjustSize()
        
        x = 0 if align == "left" else anchor.width() - panel.width()
        y = anchor.height() + _px(6, self._scale)
        panel_pos = anchor.mapToGlobal(QPoint(x, y))
        
        # Constrain height to fit available screen space
        screen = QApplication.primaryScreen()
        if screen:
            screen_geom = screen.availableGeometry()
            max_allowed_h = screen_geom.bottom() - panel_pos.y() - _px(12, self._scale)
            if panel.height() > max_allowed_h:
                panel.setFixedHeight(max_allowed_h)
                
        panel.move(panel_pos)
        panel.setWindowOpacity(0.0)
        panel.show()
        panel.raise_()
        panel._fade.stop()
        panel._fade.setStartValue(0.0)
        panel._fade.setEndValue(1.0)
        panel._fade.start()

    def _hide_panel(self, panel):
        if panel:
            panel.hide()

    def _hide_unhovered_panel(self):
        widget = QApplication.widgetAt(QCursor.pos())
        while widget is not None:
            if self._pending_panel == "more" and widget in (
                self._more_btn,
                self._more_panel,
            ):
                return
            if self._pending_panel == "settings" and widget in (
                self._settings_btn,
                self._settings_panel,
            ):
                return
            widget = widget.parentWidget()
        if self._pending_panel == "more":
            self._hide_panel(self._more_panel)
        elif self._pending_panel == "settings":
            self._hide_panel(self._settings_panel)

    def _emit_help(self):
        self._hide_panel(self._more_panel)
        self.btn_help_clicked.emit()

    def _emit_shortcuts(self):
        self._hide_panel(self._more_panel)
        self.btn_shortcuts_clicked.emit()

    def _emit_save(self):
        self.btn_save_clicked.emit()

    def _emit_about(self):
        self._hide_panel(self._more_panel)
        self.btn_about_clicked.emit()

    def _emit_font(self, delta):
        self._hide_panel(self._settings_panel)
        self.font_change.emit(delta)

    def _on_tmnt_contrast_changed(self, state):
        invert = (state == Qt.Checked)
        store.get()["_invert_pdf"] = invert
        store.mark_dirty()

    def _on_tmnt_fullscreen_changed(self, state):
        keep = (state == Qt.Checked)
        self._data["_keep_fullscreen"] = keep
        store.mark_dirty()
        win = self.window()
        if win:
            if keep:
                win.showFullScreen()
            else:
                win.showMaximized()

    def _on_tmnt_animations_changed(self, state):
        enabled = (state == Qt.Checked)
        store.get()["_home_animations"] = enabled
        store.mark_dirty()
        try:
            from ui.canvas.retro_effects import sync_all_retro_widgets
            sync_all_retro_widgets()
        except Exception as e:
            print(f"[DEBUG][tmnt_home] sync_all_retro_widgets error: {e}")

    def _on_tmnt_numpad_revision_changed(self, state):
        enabled = (state == Qt.Checked)
        store.get()["_numpad_custom_revision"] = enabled
        store.mark_dirty()
        store.save_soon(delay_from_now=True)

    def _reset_brand_glitch(self):
        self.brand_name.setText("ANKI OCCLUSION")
        self.brand_name.setStyleSheet(self._brand_name_ss())
        
        # Re-apply explicit font to prevent layout recalculation clipping
        app = QApplication.instance()
        theme_name = getattr(app, "_active_theme", "tmnt")
        brand_font = QFont("Orbitron")
        brand_font.setPixelSize(self._brand_font_px())
        brand_font.setBold(True)
        self.brand_name.setFont(brand_font)

        if hasattr(self, "ghost_r"):
            self.ghost_r.hide()
            self.ghost_c.hide()

    def _advance_brand_glitch(self):
        strengths = [7, 5, 8, 4, 6, 7]
        import random

        if random.random() < 0.15:
            self.ghost_r.show()
            self.ghost_c.show()
            self.brand_name.setStyleSheet(
                self._brand_name_ss().replace(T_NEON, "white")
            )
            
            # Re-apply explicit font to prevent layout recalculation clipping
            app = QApplication.instance()
            theme_name = getattr(app, "_active_theme", "tmnt")
            brand_font = QFont("Orbitron")
            brand_font.setPixelSize(self._brand_font_px())
            brand_font.setBold(True)
            self.brand_name.setFont(brand_font)

            self._brand_name_glow.setBlurRadius(0)

            chars = list("ANKI OCCLUSION")
            idx = random.randint(0, len(chars) - 1)
            if chars[idx] != " ":
                chars[idx] = random.choice("!@#$%^&*()_+{}|:<>?~")
            scrambled = "".join(chars)
            self.brand_name.setText(scrambled)
            self.ghost_r.setText(scrambled)
            self.ghost_c.setText(scrambled)

            QTimer.singleShot(150, self._reset_brand_glitch)
        else:
            self._brand_name_glow.setBlurRadius(
                _px(strengths[self._brand_glitch_idx % len(strengths)], self._scale)
            )

        self._brand_glitch_idx += 1

    def _advance_brand_flicker(self):
        alphas = [160, 118, 170, 108, 150, 132, 176, 140]
        alpha = alphas[self._brand_flicker_idx % len(alphas)]
        self._brand_name_glow.setColor(QColor(102, 252, 241, alpha))
        self._brand_flicker_idx += 1

    def _rotate_quote(self):
        app = QApplication.instance()
        if getattr(app, "_active_theme", "classic") == "arcanum":
            return
        self._quote_idx = (self._quote_idx + 1) % len(MENTOR_QUOTES)
        q, n = MENTOR_QUOTES[self._quote_idx]
        self.quote_lbl.setText(q)
        self.name_lbl.setText(n)

    def set_bgm_state(self, playing):
        self.bgm_widget.set_playing(playing)

    def _on_volume_slider_changed(self, value):
        self._data["_volume"] = value
        from data_manager import store
        store.mark_dirty()
        self.volume_changed.emit(value)

    def _dec_volume(self):
        val = max(0, self._data.get("_volume", 40) - 10)
        self._volume_slider.setValue(val)

    def _inc_volume(self):
        val = min(100, self._data.get("_volume", 40) + 10)
        self._volume_slider.setValue(val)

    def _on_tmnt_scroll_slider_changed(self, value):
        self._data["_scroll_speed"] = value
        if hasattr(self, "_scroll_val_lbl") and self._scroll_val_lbl:
            self._scroll_val_lbl.setText(f"{value}%")
        from data_manager import store
        store.mark_dirty()

    def _dec_scroll_speed(self):
        val = max(10, self._data.get("_scroll_speed", 35) - 5)
        self._scroll_slider.setValue(val)

    def _inc_scroll_speed(self):
        val = min(100, self._data.get("_scroll_speed", 35) + 5)
        self._scroll_slider.setValue(val)

    def _find_home(self):
        from ui.home_screen import HomeScreen
        w = self.parent()
        while w:
            if isinstance(w, HomeScreen):
                return w
            w = w.parent()
        return None

    def _refresh_gdrive_display(self):
        from services.gdrive_service import gdrive_store
        if not hasattr(self, "_gdrive_status_lbl") or self._gdrive_status_lbl is None:
            return
            
        if gdrive_store.is_linked():
            email = gdrive_store.get_email()
            self._gdrive_status_lbl.setText(f"LINKED: {email.upper()}")
            self._gdrive_status_lbl.setToolTip(f"Linked to Google Account: {email}")
            self._gdrive_link_btn.setText("UNLINK")
            self._gdrive_sync_btn.setEnabled(True)
        else:
            self._gdrive_status_lbl.setText("NOT LINKED")
            self._gdrive_status_lbl.setToolTip("Google Drive Sync is not connected.")
            self._gdrive_link_btn.setText("LINK")
            self._gdrive_sync_btn.setEnabled(False)

        home = self._find_home()
        backup_running = getattr(home, "_backup_in_progress", False) if home else False
        restore_running = getattr(home, "_restore_in_progress", False) if home else False
        prune_running = getattr(home, "_prune_in_progress", False) if home else False

        if hasattr(self, "_assets_backup_btn") and self._assets_backup_btn is not None:
            self._assets_backup_btn.setEnabled(gdrive_store.is_linked() and not backup_running)
        if hasattr(self, "_assets_restore_btn") and self._assets_restore_btn is not None:
            self._assets_restore_btn.setEnabled(gdrive_store.is_linked() and not restore_running)
        if hasattr(self, "_assets_prune_btn") and self._assets_prune_btn is not None:
            self._assets_prune_btn.setEnabled(gdrive_store.is_linked() and not prune_running)

    def _toggle_gdrive_link(self):
        home = self._find_home()
        if home and hasattr(home, "_toggle_gdrive_link"):
            home._toggle_gdrive_link()
            self._refresh_gdrive_display()

    def _manual_gdrive_sync(self):
        home = self._find_home()
        if home and hasattr(home, "_manual_gdrive_sync"):
            home._manual_gdrive_sync()
            self._refresh_gdrive_display()

    def _backup_assets_to_cloud(self):
        home = self._find_home()
        if home and hasattr(home, "_backup_assets_to_cloud"):
            home._backup_assets_to_cloud()
            self._refresh_gdrive_display()

    def _sync_assets_from_cloud(self):
        home = self._find_home()
        if home and hasattr(home, "_sync_assets_from_cloud"):
            home._sync_assets_from_cloud()
            self._refresh_gdrive_display()

    def _prune_cloud_assets(self):
        home = self._find_home()
        if home and hasattr(home, "_prune_cloud_assets"):
            home._prune_cloud_assets()
            self._refresh_gdrive_display()






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
    btn_save_clicked = pyqtSignal()
    btn_math_clicked = pyqtSignal()
    btn_journal_clicked = pyqtSignal()
    btn_report_clicked = pyqtSignal()
    btn_resume_clicked = pyqtSignal()
    btn_theme_clicked = pyqtSignal(object)
    btn_help_clicked = pyqtSignal()
    btn_about_clicked = pyqtSignal()
    btn_shortcuts_clicked = pyqtSignal()
    font_change = pyqtSignal(int)
    bgm_toggle = pyqtSignal()
    bgm_volume_changed = pyqtSignal(int)
    deck_selected = pyqtSignal(object)
    SIDEBAR_STRETCH = 30
    MAIN_STRETCH = 70

    def __init__(self, data: dict, parent=None):
        """
        data          — the global app data dict
        """
        sync_theme_colors()
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
        self._body_layout = body
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body_w = QWidget()
        body_w.setLayout(body)
        body_w.setStyleSheet(f"background: {T_BG};")
        body_w.setMouseTracking(True)

        self.sidebar = TMNTSidebar(self._data)
        self.main = TMNTMainContent(data=self._data)

        body.addWidget(self.sidebar, stretch=self.SIDEBAR_STRETCH)
        body.addWidget(self.main, stretch=self.MAIN_STRETCH)

        from PyQt5.QtCore import QSettings
        init_locked = bool(QSettings("AnkiOcclusion", "App").value("deck_structure_locked", False, type=bool))
        self.sidebar.set_structure_locked(init_locked)
        self.main.set_structure_locked(init_locked)

        # Sidebar hover-expand state
        self._sidebar_expanded = False
        self._body_w = body_w  # store reference for coordinate mapping

        from PyQt5.QtCore import QVariantAnimation
        self._sidebar_anim = QVariantAnimation(self)
        self._sidebar_anim.setDuration(250)
        self._sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._sidebar_anim.valueChanged.connect(self._on_sidebar_anim)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)

        # Timer created but NOT started — will start in showEvent
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(150)
        self._hover_timer.timeout.connect(self._check_sidebar_hover)

        # Collapse delay timer — 1 second debounce before collapsing
        self._collapse_delay = QTimer(self)
        self._collapse_delay.setSingleShot(True)
        self._collapse_delay.setInterval(1000)
        self._collapse_delay.timeout.connect(self._do_collapse_sidebar)

        self._banga_reserve = QWidget()
        self._banga_reserve.setFixedWidth(0)
        self._banga_reserve.hide()
        body.addWidget(self._banga_reserve)

        self.banga = TMNTBangaDrawer(
            data=self._data,
            parent=body_w,
            reserve_widget=self._banga_reserve,
        )
        L.addWidget(body_w, stretch=1)

        self.crt = CRTOverlay(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "crt"):
            self.crt.setGeometry(self.rect())
            self.crt.raise_()

        # If sidebar is floating (expanded), update its height to match body
        if getattr(self, "_sidebar_floating", False) and hasattr(self, "sidebar"):
            body = getattr(self, "_body_w", None)
            if body:
                g = self.sidebar.geometry()
                self.sidebar.setGeometry(g.x(), g.y(), g.width(), body.height())

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "crt"):
            self.crt.trigger_boot_flicker()
        # Start hover timer only after the widget is shown and laid out
        if hasattr(self, "_hover_timer") and not self._hover_timer.isActive():
            QTimer.singleShot(500, self._hover_timer.start)

    def _check_sidebar_hover(self):
        if not hasattr(self, "sidebar") or not self.sidebar.isVisible():
            return
        body = getattr(self, "_body_w", None)
        if not body:
            return

        # Map global cursor to body widget coordinates
        pos = body.mapFromGlobal(QCursor.pos())
        body_rect = body.rect()
        if not body_rect.contains(pos):
            self._request_collapse()
            return

        # Dynamic hover zone: use the maximum of the sidebar's current actual width
        # and 30% of body width (so it can always be triggered when collapsed).
        hover_zone_w = max(self.sidebar.width(), int(body.width() * 0.30))
        in_sidebar_zone = pos.x() <= hover_zone_w

        if in_sidebar_zone:
            # Mouse is back in sidebar zone — cancel any pending collapse
            if hasattr(self, '_collapse_delay') and self._collapse_delay.isActive():
                self._collapse_delay.stop()
            self._expand_sidebar()
        else:
            self._request_collapse()

    def _request_collapse(self):
        """Start the 1-second collapse delay if not already pending."""
        if not self._sidebar_expanded:
            return
        if not self._collapse_delay.isActive():
            self._collapse_delay.start()

    def _do_collapse_sidebar(self):
        """Actually perform the collapse after the delay."""
        self._collapse_sidebar()

    def _on_sidebar_anim(self, val):
        """During expand/collapse, update the sidebar geometry (floating mode)
        or width (returning to layout)."""
        if not hasattr(self, "sidebar"):
            return
        body = getattr(self, "_body_w", None)
        if not body:
            return
        w = int(val)
        if getattr(self, "_sidebar_floating", False):
            # Sidebar is floating — set geometry absolutely within body_w
            self.sidebar.setGeometry(0, 0, w, body.height())
        else:
            # Sidebar is back in layout — use setFixedWidth
            self.sidebar.setFixedWidth(w)

    def _on_sidebar_anim_finished(self):
        """After collapse animation, re-insert sidebar into the layout."""
        if not getattr(self, "_sidebar_expanded", False) and getattr(self, "_sidebar_floating", False):
            self._sidebar_floating = False
            body = getattr(self, "_body_w", None)
            if body and hasattr(self, "sidebar"):
                layout = body.layout()
                # Re-insert sidebar at position 0 with original stretch
                layout.insertWidget(0, self.sidebar, stretch=self.SIDEBAR_STRETCH)
                # Release any fixed width so stretch takes over
                self.sidebar.setMinimumWidth(0)
                self.sidebar.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
        try:
            from ui.canvas.retro_effects import resume_animations
            resume_animations(self)
        except Exception:
            pass

    def _expand_sidebar(self):
        if self._sidebar_expanded:
            return
        self._sidebar_expanded = True
        body = getattr(self, "_body_w", None)
        if not body or not hasattr(self, "_sidebar_anim"):
            return

        try:
            from ui.canvas.retro_effects import suspend_animations
            suspend_animations(self)
        except Exception:
            pass

        # Save current geometry before removing from layout
        saved_geom = self.sidebar.geometry()

        # Remove sidebar from layout (it stays as a child of body_w)
        body.layout().removeWidget(self.sidebar)
        self._sidebar_floating = True

        # Position absolutely at saved location, raise above main content
        self.sidebar.setGeometry(saved_geom)
        self.sidebar.raise_()
        self.sidebar.show()

        # Animate width from current to 60% of body
        start_w = saved_geom.width()
        end_w = int(body.width() * 0.60)
        self._sidebar_anim.stop()
        self._sidebar_anim.setStartValue(start_w)
        self._sidebar_anim.setEndValue(end_w)
        self._sidebar_anim.start()

    def _collapse_sidebar(self):
        if not self._sidebar_expanded:
            return
        self._sidebar_expanded = False
        body = getattr(self, "_body_w", None)
        if not body or not hasattr(self, "_sidebar_anim"):
            return

        try:
            from ui.canvas.retro_effects import suspend_animations
            suspend_animations(self)
        except Exception:
            pass

        # Animate width back to 30% of body (matches SIDEBAR_STRETCH)
        start_w = self.sidebar.width()
        end_w = int(body.width() * 0.30)
        self._sidebar_anim.stop()
        self._sidebar_anim.setStartValue(start_w)
        self._sidebar_anim.setEndValue(end_w)
        self._sidebar_anim.start()



    def _wire_signals(self):
        # Topbar → HomeScreen
        self.topbar.btn_save_clicked.connect(self.btn_save_clicked)
        self.topbar.btn_math_clicked.connect(self.btn_math_clicked)
        self.topbar.btn_journal_clicked.connect(self.btn_journal_clicked)
        self.topbar.btn_report_clicked.connect(self.btn_report_clicked)
        self.main.banner.resume_clicked.connect(self.btn_resume_clicked)
        self.topbar.btn_theme_clicked.connect(self.btn_theme_clicked)
        self.topbar.btn_help_clicked.connect(self.btn_help_clicked)
        self.topbar.btn_about_clicked.connect(self.btn_about_clicked)
        self.topbar.btn_shortcuts_clicked.connect(self.btn_shortcuts_clicked)
        self.topbar.recovery_clicked.connect(self._show_recovery_center)
        self.topbar.font_change.connect(self.font_change)
        self.topbar.bgm_toggle.connect(self.bgm_toggle)
        self.topbar.volume_changed.connect(self.bgm_volume_changed)

        # Sidebar deck selection
        self.sidebar.deck_selected.connect(self._on_deck_selected)
        self.sidebar.new_deck.connect(self._new_deck)
        self.sidebar.new_sub.connect(self._new_sub)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            panels_closed = False
            if getattr(self, "_settings_panel", None) is not None and self._settings_panel.isVisible():
                self._hide_panel(self._settings_panel)
                panels_closed = True
            if getattr(self, "_more_panel", None) is not None and self._more_panel.isVisible():
                self._hide_panel(self._more_panel)
                panels_closed = True
            if panels_closed:
                event.accept()
                return
        if (event.key() in (Qt.Key_F, Qt.Key_K)) and event.modifiers() & Qt.ControlModifier:
            if hasattr(self, "sidebar") and hasattr(self.sidebar, "_focus_search"):
                self.sidebar._focus_search()
                event.accept()
                return
        if shortcut_manager.event_matches(event, "home.save"):
            store.mark_dirty()
            store.save_force(async_save=True)
            print("[TMNTHome][key] Ctrl+S — manual save triggered")
            # If we want a toast, we could potentially call it on self.main.canvas if it was open,
            # but usually TMNT uses a separate toast mechanism or we just print to console.
            event.accept()
            return
        if shortcut_manager.event_matches(event, "home.undo"):
            self._apply_deck_history(redo=False)
            event.accept()
            return
        legacy_redo = (
            event.key() == Qt.Key_Z
            and event.modifiers() & Qt.ControlModifier
            and event.modifiers() & Qt.ShiftModifier
        )
        if shortcut_manager.event_matches(event, "home.redo") or legacy_redo:
            self._apply_deck_history(redo=True)
            event.accept()
            return
        if shortcut_manager.event_matches(event, "home.edit_card") or (event.key() == Qt.Key_E and (event.modifiers() & Qt.ControlModifier) and not (event.modifiers() & (Qt.AltModifier | Qt.MetaModifier))):
            if self.main and self.main.isVisible():
                if not getattr(self.main, "deck", None) and hasattr(self, "sidebar") and getattr(self.sidebar, "_selected_deck", None):
                    self.main.load_deck(self.sidebar._selected_deck, getattr(self.main, "_data", None) or getattr(self, "_data", None))
                item = self.main.card_list.currentItem()
                if not item and self.main.card_list.count() > 0:
                    item = self.main.card_list.item(0)
                    self.main.card_list.setCurrentItem(item)
                if item:
                    self.main._edit_card(item)
                    event.accept()
                    return
                elif getattr(self.main, "deck", None):
                    def _find_card(d):
                        if d.get("cards"):
                            return d["cards"][0], d
                        for child in d.get("children", []):
                            r = _find_card(child)
                            if r:
                                return r
                        return None, None
                    sub_card, sub_d = _find_card(self.main.deck)
                    if sub_card and sub_d:
                        self.main._edit_card_by_dict(sub_card, sub_d)
                        event.accept()
                        return
                    else:
                        self.main._add_card()
                        event.accept()
                        return
        if shortcut_manager.event_matches(event, "home.add_card"):
            if self.main and self.main.isVisible() and self.main.btn_add.isEnabled():
                self.main._add_card()
                event.accept()
                return
        if shortcut_manager.event_matches(event, "home.browse_cards"):
            if self.main:
                if not getattr(self.main, "deck", None) and hasattr(self, "sidebar") and getattr(self.sidebar, "_selected_deck", None):
                    self.main.load_deck(self.sidebar._selected_deck, getattr(self.main, "_data", None) or getattr(self, "_data", None))
                self.main._open_card_browser()
                event.accept()
                return
        super().keyPressEvent(event)

    def _apply_deck_history(self, redo=False):
        ok = deck_history.redo(store) if redo else deck_history.undo(store)
        if not ok:
            print(
                f"[TMNTHome][key] {'redo' if redo else 'undo'} skipped — stack empty"
            )
            return False
        self._data = store.get()
        home = self._find_home()
        if home is not None:
            home._data = self._data
        self.sidebar.set_data(self._data)
        self.main._data = self._data
        self.banga._data = self._data
        self.refresh()
        print(f"[TMNTHome][key] {'redo' if redo else 'undo'} applied")
        return True

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
            from perf_utils import invalidate_deck_stats

            invalidate_deck_stats()
            store.mark_dirty()
            store.save_soon(min_interval=3.0)
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
            store.save_soon(min_interval=3.0)
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

    def _show_recovery_center(self):
        home = self._find_home()
        if home is not None and hasattr(home, "show_recovery_center"):
            home.show_recovery_center(startup=False)

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

    def set_resume_enabled(self, enabled):
        if hasattr(self, "main") and hasattr(self.main, "banner") and self.main.banner:
            self.main.banner.set_resume_enabled(enabled)

    def set_structure_locked(self, locked: bool):
        if hasattr(self, "sidebar") and self.sidebar and hasattr(self.sidebar, "set_structure_locked"):
            self.sidebar.set_structure_locked(locked)
        if hasattr(self, "main") and self.main and hasattr(self.main, "set_structure_locked"):
            self.main.set_structure_locked(locked)

