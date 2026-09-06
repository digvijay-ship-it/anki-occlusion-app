"""
Anki Occlusion — PDF & Image Flashcard App  v19 (Smart Review Items Rebuild)
================================================
v19 New Feature:
  [SMART REVIEW REBUILD] ReviewScreen ab sirf tabhi _items list rebuild karta hai
      jab editor mein koi box ka group_id actually change hua ho.
      Bina kisi change ke review se editor aur wapas = zero overhead.
      Sirf affected card ke items replace hote hain — baaki cards untouched.
      Detection: before/after snapshot of {box_id -> group_id} map.

v18 (Hardware Mask Cache + LRU Page Cache Edition)
================================================
v18 New Features:
  [HARDWARE MASK CACHE] OcclusionCanvas ab masks ko ek GPU-backed QPixmap
      offscreen layer mein cache karta hai. Jab tak koi mask change nahi hota,
      paintEvent mein sirf ek drawPixmap() call hota hai — loop nahi.
      100+ masks = 1 mask jaisi speed. FPS ~3x better on dense cards.
      Cache sirf tab rebuild hota hai jab _mask_cache_dirty = True ho:
        - mouseReleaseEvent (drag/draw finish)
        - delete, undo, redo, label change, group/ungroup
      Mouse drag ke dauran cache rebuild NAHI hoti — isliye dragging bhi smooth.

  [LRU PAGE CACHE] GLOBAL_PDF_CACHE replace ho gaya ek smart LRUPageCache se.
      Pura combined QPixmap store karne ki jagah ab individual pages store hoti hain.
      Max 15 pages RAM mein — baaki on-demand fitz se reload.
      Ek 100-page PDF pehle ~2GB RAM leta tha, ab sirf ~300MB.
      OrderedDict se O(1) get/put/evict — zero performance penalty.

v17 New Feature:
  [PROGRESSIVE LOADING] PDF ab 10-10 pages ke chunks mein load hota hai.
      Pehla chunk (10 pages) aate hi canvas pe dikhta hai — user turant
      kaam shuru kar sakta hai. Baaki pages background mein silently load
      hote rehte hain. Progress bar-style label dikhata hai kitne pages load hue.
  [ULTRA FAST CACHE] PDF ek baar load hone ke baad RAM mein save ho jati hai.
      Edit aur Review mode ke beech switch karne par zero delay (0.001s).
v16 Bug Fixes:
  [NOT-RESPONDING FIX] PDF ab background QThread mein load hota hai.
      CardEditorDialog._load_card() aur _load_pdf() dono ab non-blocking hain.
      _reload_pdf() (Live Sync) bhi thread-based ho gaya.
      closeEvent/reject mein thread safely stop hota hai.
v15 Bug Fixes:
  [FIX-1]  ReviewScreen.__init__ — duplicate item prevention
  [FIX-2]  _rate() — "reviews" double-increment fixed
  [FIX-3]  _start_review() — win.closeEvent double-save fixed
  [FIX-4]  is_due_today() called on un-initialised boxes in ReviewScreen
  [FIX-5]  Group dedup across cards
  [LAG-FIX] Native Hardware Painting & Caching applied to OcclusionCanvas
            to eliminate mouseMoveEvent lag completely.
"""

from sm2_engine import (
    sched_init,
    sm2_init,
    sched_update,
    sm2_update,
    is_due_now,
    is_due_today,
    sm2_is_due,
    sm2_days_left,
    _fmt_due_interval,
    sm2_simulate,
    sm2_badge,
)

from services import recovery_manager
from services import shortcut_manager
from services.review_manager import REVIEW_SAVE_MIN_INTERVAL

from data_manager import (
    load_data,
    save_data,
    find_deck_by_id,
    next_deck_id,
    new_box_id,
    deck_history,
    DATA_FILE,
    store,
)
from storage_paths import (
    app_resource_path,
    archive_label,
    archive_tooltip,
    current_data_file,
    flush_runtime_state,
    get_mission_archive_root,
    migrate_to_mission_archive,
    resolve_asset_path,
    is_running_tests,
)

import sys, os, copy, uuid, math, time
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QScrollArea,
    QInputDialog,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QProgressBar,
    QDialog,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QMenu,
    QStyledItemDelegate,
    QStyle,
    QHeaderView,
    QStackedWidget,
    QSlider,
)
from PyQt5.QtCore import (
    Qt,
    QRect,
    QPoint,
    QSize,
    QRectF,
    QPointF,
    pyqtSignal,
    QLockFile,
    QTimer,
    QModelIndex,
    QFileSystemWatcher,
    QThread,
    QEvent,
    QMimeData,
    QByteArray,
    QUrl,
)
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QFont,
    QCursor,
    QIcon,
    QBrush,
    QTransform,
    QPainterPath,
    QDrag,
    QDesktopServices,
    QFontDatabase,
)

import tempfile

# ── LOAD CUSTOM FONTS ────────────────────────────────────────────────────────
NARUTO_FONT_FAMILY = "Segoe UI"  # Global variable for easy access


_FONTS_LOADED = False


def load_custom_fonts():
    """Safe font loading. Only runs if QApplication instance exists."""
    global _FONTS_LOADED, NARUTO_FONT_FAMILY
    if _FONTS_LOADED or not QApplication.instance():
        return
    _FONTS_LOADED = True


# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

# ── Theme constants — single source of truth is theme_manager.PALETTES["dark"] ──
from theme_manager import (
    get_palette as _get_palette,
    get_palette,
    normalize_theme,
    is_retro_theme,
    NINJA_THEME_ENABLED,
)

_DARK = _get_palette("dark")
C_BG = _DARK["C_BG"]
C_SURFACE = _DARK["C_SURFACE"]
C_CARD = _DARK["C_CARD"]
C_ACCENT = _DARK["C_ACCENT"]
C_GREEN = _DARK["C_GREEN"]
C_RED = _DARK["C_RED"]
C_YELLOW = _DARK["C_YELLOW"]
C_TEXT = _DARK["C_TEXT"]
C_SUBTEXT = _DARK["C_SUBTEXT"]
C_BORDER = _DARK["C_BORDER"]
C_MASK = "#F7916A"
C_GROUP = "#BD93F9"

def _hex_to_rgba(hex_str: str, alpha: float) -> str:
    if not hex_str or not isinstance(hex_str, str):
        return f"rgba(124, 106, 247, {alpha})"
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
    return f"rgba(124, 106, 247, {alpha})"

def _log_success(msg: str):
    banner = f" 👍  SUCCESS: {msg} "
    width = max(len(banner) + 4, 50)
    print("\n" + "╔" + "═"*(width-2) + "╗")
    print("║" + banner.center(width-2) + "║")
    print("╚" + "═"*(width-2) + "╝\n")

BASE_FONT_SIZE = 11


def _build_ss(font_size: int = BASE_FONT_SIZE) -> str:
    return f"""
QMainWindow,QDialog{{background:{C_BG};color:{C_TEXT};}}
QWidget{{background:{C_BG};color:{C_TEXT};font-family:'Segoe UI';font-size:{font_size}px;}}
QFrame{{background:{C_SURFACE};border-radius:8px;}}
QLabel{{background:transparent;color:{C_TEXT};}}
QPushButton{{background:{C_ACCENT};color:white;border:none;border-radius:8px;padding:8px 18px;font-weight:bold;}}
QPushButton:hover{{background:#6A58E0;}}
QPushButton:pressed{{background:#5448C8;}}
QPushButton#danger{{background:{C_RED};color:white;}}
QPushButton#danger:hover{{background:#CC3333;}}
QPushButton#success{{background:{C_GREEN};color:#1E1E2E;}}
QPushButton#success:hover{{background:#3DD668;}}
QPushButton#warning{{background:{C_YELLOW};color:#1E1E2E;}}
QPushButton#warning:hover{{background:#D9E070;}}
QPushButton#hard{{background:#E08030;color:white;}}
QPushButton#hard:hover{{background:#C06020;}}
QPushButton#flat{{background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};}}
QPushButton#flat:hover{{background:{C_SURFACE};}}
QListWidget,QTreeWidget{{background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;padding:4px;}}
QListWidget::item,QTreeWidget::item{{padding:6px;border-radius:6px;}}
QListWidget::item:selected,QTreeWidget::item:selected{{background:{C_ACCENT};color:white;}}
QListWidget::item:hover,QTreeWidget::item:hover{{background:{C_CARD};}}
QTreeView::drop-indicator{{background:{C_ACCENT};height:3px;border:none;border-radius:2px;}}
QScrollArea{{border:none;background:transparent;}}
QScrollBar:vertical{{background:{C_SURFACE};width:8px;border-radius:4px;}}
QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:4px;}}
QLineEdit,QTextEdit{{background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;padding:6px;}}
QProgressBar{{background:{C_CARD};border-radius:6px;height:12px;text-align:center;color:transparent;}}
QProgressBar::chunk{{background:{C_ACCENT};border-radius:6px;}}
QMessageBox{{background:{C_BG};color:{C_TEXT};}}
QStatusBar{{background:{C_SURFACE};color:{C_SUBTEXT};}}
QMenu{{background:{C_SURFACE};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;}}
QMenu::item:selected{{background:{C_ACCENT};}}
"""


SS = _build_ss()


DeckTree = None
CacheWidget = None
DeckView = None
TMNTHomeLayout = None
JournalDialog = None
MathTrainerPage = None
ReviewScreen = None
CardEditorDialog = None
RecoveryDialog = None
ShortcutSettingsDialog = None
_TMNT_HOME_AVAILABLE = None
_JOURNAL_AVAILABLE = None
_MATH_AVAILABLE = None


def _load_classic_home_classes():
    global DeckTree, CacheWidget, DeckView
    if DeckTree is None or CacheWidget is None:
        from .deck_tree import CacheWidget as _CacheWidget
        from .deck_tree import DeckTree as _DeckTree

        DeckTree = _DeckTree
        CacheWidget = _CacheWidget
    if DeckView is None:
        from .deck_view import DeckView as _DeckView

        DeckView = _DeckView
    return DeckTree, CacheWidget, DeckView


def _load_tmnt_home_layout():
    global TMNTHomeLayout, _TMNT_HOME_AVAILABLE
    if _TMNT_HOME_AVAILABLE is False:
        return None
    if TMNTHomeLayout is not None:
        _TMNT_HOME_AVAILABLE = True
        return TMNTHomeLayout
    try:
        from .tmnt_home import TMNTHomeLayout as _TMNTHomeLayout

        TMNTHomeLayout = _TMNTHomeLayout
        _TMNT_HOME_AVAILABLE = True
    except Exception as _tmnt_err:
        import traceback as _tb

        print(f"[TMNT IMPORT ERROR] {type(_tmnt_err).__name__}: {_tmnt_err}")
        _tb.print_exc()
        _TMNT_HOME_AVAILABLE = False
        return None
    return TMNTHomeLayout


def _load_journal_dialog():
    global JournalDialog, _JOURNAL_AVAILABLE
    if _JOURNAL_AVAILABLE is False:
        return None
    if JournalDialog is not None:
        _JOURNAL_AVAILABLE = True
        return JournalDialog
    try:
        from .journal import JournalDialog as _JournalDialog

        JournalDialog = _JournalDialog
        _JOURNAL_AVAILABLE = True
    except ImportError:
        _JOURNAL_AVAILABLE = False
        return None
    return JournalDialog


def _load_math_trainer_page():
    global MathTrainerPage, _MATH_AVAILABLE
    if _MATH_AVAILABLE is False:
        return None
    if MathTrainerPage is not None:
        _MATH_AVAILABLE = True
        return MathTrainerPage
    try:
        from .math_trainer import MathTrainerPage as _MathTrainerPage

        MathTrainerPage = _MathTrainerPage
        _MATH_AVAILABLE = True
    except Exception as _math_err:
        import traceback as _tb

        print(f"[MATH TRAINER IMPORT ERROR] {type(_math_err).__name__}: {_math_err}")
        _tb.print_exc()
        _MATH_AVAILABLE = False
        return None
    return MathTrainerPage


def _load_review_screen():
    global ReviewScreen
    if ReviewScreen is None:
        from .review_screen import ReviewScreen as _ReviewScreen

        ReviewScreen = _ReviewScreen
    return ReviewScreen


def _load_card_editor_dialog():
    global CardEditorDialog
    if CardEditorDialog is None:
        from .editor_dialog import CardEditorDialog as _CardEditorDialog

        CardEditorDialog = _CardEditorDialog
    return CardEditorDialog


def _load_recovery_dialog():
    global RecoveryDialog
    if RecoveryDialog is None:
        from .recovery_dialog import RecoveryDialog as _RecoveryDialog

        RecoveryDialog = _RecoveryDialog
    return RecoveryDialog


def _load_shortcut_settings_dialog():
    global ShortcutSettingsDialog
    if ShortcutSettingsDialog is None:
        from .shortcut_dialog import ShortcutSettingsDialog as _ShortcutSettingsDialog

        ShortcutSettingsDialog = _ShortcutSettingsDialog
    return ShortcutSettingsDialog


#  HOME SCREEN
# ══════════════════════════════════════════════════════════════
def make_app_icon() -> QIcon:
    SIZE = 256
    px = QPixmap(SIZE, SIZE)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(C_SURFACE)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, SIZE, SIZE, 48, 48)
    card_rect = QRect(36, 44, 184, 148)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.setPen(QPen(QColor(C_BORDER), 3))
    p.drawRoundedRect(card_rect, 10, 10)
    p.setPen(QPen(QColor("#E0E0E0"), 1))
    for y in range(card_rect.top() + 24, card_rect.bottom() - 10, 18):
        p.drawLine(card_rect.left() + 12, y, card_rect.right() - 12, y)
    p.setBrush(QBrush(QColor(C_MASK)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(52, 62, 80, 36, 5, 5)
    p.drawRoundedRect(148, 104, 60, 30, 5, 5)
    p.setBrush(QBrush(QColor(C_GREEN)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(168, 168, 60, 60)
    p.setPen(QPen(QColor("#1E1E2E"), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(182, 199, 192, 211)
    p.drawLine(192, 211, 214, 185)
    p.end()
    return QIcon(px)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Anki Occlusion")
        self.setFixedSize(480, 560)
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        self.setStyleSheet(f"QDialog{{background:{p.get('C_BG', C_BG)};}}")
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)
        header = QFrame()
        header.setFixedHeight(140)
        header.setStyleSheet(
            f"QFrame{{background:{p.get('C_SURFACE', C_SURFACE)};border-radius:0px;}}"
        )
        hl = QVBoxLayout(header)
        hl.setAlignment(Qt.AlignCenter)
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_px = make_app_icon().pixmap(72, 72)
        icon_lbl.setPixmap(icon_px)
        hl.addWidget(icon_lbl)
        hf = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        bf = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        name_lbl = QLabel("Anki Occlusion")
        name_lbl.setFont(QFont(hf, 18, QFont.Bold))
        name_lbl.setStyleSheet(
            f"color:{p.get('C_ACCENT', C_ACCENT)};background:transparent;"
        )
        name_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(name_lbl)
        ver_lbl = QLabel("Version 1.0  •  Desktop Edition")
        ver_lbl.setStyleSheet(
            f"color:{p.get('C_SUBTEXT', C_SUBTEXT)};font-size:11px;background:transparent;font-family:{bf};"
        )
        ver_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(ver_lbl)
        L.addWidget(header)
        body = QWidget()
        body.setStyleSheet(f"background:{p.get('C_BG', C_BG)};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(32, 24, 32, 24)
        bl.setSpacing(16)

        def _section(title, text):
            t = QLabel(title)
            t.setFont(QFont(hf, 10, QFont.Bold))
            t.setStyleSheet(f"color:{p.get('C_TEXT', C_TEXT)};")
            d = QLabel(text)
            d.setStyleSheet(
                f"color:{p.get('C_SUBTEXT', C_SUBTEXT)};font-size:12px;font-family:{bf};"
            )
            d.setWordWrap(True)
            bl.addWidget(t)
            bl.addWidget(d)

        _section(
            "What it does",
            "Draw rectangular masks over your PDF notes and images, "
            "then study them with a full Anki-style spaced repetition "
            "scheduler — learning steps, review intervals, ease factors.",
        )
        _section(
            "Keyboard shortcuts",
            "F11 — fullscreen        Ctrl+Z / Y — undo / redo\n"
            "Space — reveal answer   1/2/3/4/5 — rate Again/Hard/Good/Easy/Perfect\n"
            "V=Select  R=Rect  E=Ellipse  T=Label  Del=delete selected\n"
            "Ctrl+A — select all     Ctrl+Scroll — zoom\n"
            "Alt+Click — multi-select   Hold Alt — temp select tool\n"
            "C — center on mask      Drag ↻ handle — rotate shape\n"
            "Space+drag — pan canvas  H — toggle pan lock\n"
            "L — copy current PDF file   Ctrl+L — open current PDF folder",
        )
        _section("Data location", f"{current_data_file()}")
        bl.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"background:{p.get('C_ACCENT', C_ACCENT)};color:{p.get('C_BG', 'white')};border:none;border-radius:8px;"
            f"padding:8px 32px;font-weight:bold;font-size:13px;font-family:{hf};"
        )
        close_btn.clicked.connect(self.accept)
        bl.addWidget(close_btn, alignment=Qt.AlignCenter)
        L.addWidget(body)


class OnboardingDialog(QDialog):
    STEPS = [
        {
            "icon": "🃏",
            "title": "Welcome to Anki Occlusion",
            "body": "The fastest way to turn your PDF notes and images into Anki-style flashcards — without typing a single word.\n\nThis quick tour takes about 30 seconds.",
        },
        {
            "icon": "📂",
            "title": "Step 1 — Create a Deck",
            "body": "Click  ＋ Deck  in the left sidebar to create your first deck.\n\nYou can nest decks inside each other — for example:\n  Biology  ›  Chapter 3  ›  Cell Division\n\nDrag and drop to reorganise them any time.",
        },
        {
            "icon": "🖼",
            "title": "Step 2 — Add a Card",
            "body": "Select a deck, then click  ＋ Add Card.\n\nLoad a PDF or image, then use the toolbar:\n  ▶ Select — move, resize, rotate shapes\n  ▭ Rectangle — draw rectangular masks\n  ⬭ Ellipse — draw oval masks\n  T Text — click a mask to edit its label\n\nEach mask becomes one flashcard question automatically.",
        },
        {
            "icon": "🧠",
            "title": "Step 3 — Review",
            "body": "Click  🔴 Review Due  to start your session.\n\nTwo review modes (toggle in review header):\n  🟧 Hide All, Guess One — all masks hidden one by one\n  👁 Hide One, Guess One — only the target mask hidden\n\nPress Space to reveal, then rate yourself:\n  1 = Again   2 = Hard   3 = Good   4 = Easy   5 = Perfect\n\nThe scheduler decides when you'll see each card next.",
        },
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setFixedSize(540, 440)
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        self._p = get_palette(theme)
        self.setStyleSheet(f"QDialog{{background:{self._p.get('C_BG', C_BG)};}}")
        self._step = 0
        self._setup_ui()
        self._show_step(0)

    def _setup_ui(self):
        p = self._p
        hf = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        bf = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)
        dot_bar = QWidget()
        dot_bar.setFixedHeight(32)
        dot_bar.setStyleSheet(f"background:{p.get('C_SURFACE', C_SURFACE)};")
        dl = QHBoxLayout(dot_bar)
        dl.setAlignment(Qt.AlignCenter)
        dl.setSpacing(8)
        self._dots = []
        for _ in self.STEPS:
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color:{p.get('C_BORDER', C_BORDER)};font-size:10px;background:transparent;"
            )
            dl.addWidget(dot)
            self._dots.append(dot)
        L.addWidget(dot_bar)
        content = QWidget()
        content.setStyleSheet(f"background:{p.get('C_BG', C_BG)};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(48, 32, 48, 24)
        cl.setSpacing(16)
        self._icon_lbl = QLabel()
        self._icon_lbl.setFont(QFont(hf, 48))
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setStyleSheet("background:transparent;")
        self._title_lbl = QLabel()
        self._title_lbl.setFont(QFont(hf, 16, QFont.Bold))
        self._title_lbl.setStyleSheet(
            f"color:{p.get('C_TEXT', C_TEXT)};background:transparent;"
        )
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setWordWrap(True)
        self._body_lbl = QLabel()
        self._body_lbl.setStyleSheet(
            f"color:{p.get('C_SUBTEXT', C_SUBTEXT)};font-size:12px;background:transparent;font-family:{bf};"
        )
        self._body_lbl.setWordWrap(True)
        self._body_lbl.setAlignment(Qt.AlignCenter)
        cl.addStretch()
        cl.addWidget(self._icon_lbl)
        cl.addWidget(self._title_lbl)
        cl.addWidget(self._body_lbl)
        cl.addStretch()
        L.addWidget(content, stretch=1)
        btn_bar = QFrame()
        btn_bar.setFixedHeight(64)
        btn_bar.setStyleSheet(
            f"QFrame{{background:{p.get('C_SURFACE', C_SURFACE)};"
            f"border-top:1px solid {p.get('C_BORDER', C_BORDER)};border-radius:0px;}}"
        )
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(24, 0, 24, 0)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setStyleSheet(
            f"background:transparent;color:{p.get('C_SUBTEXT', C_SUBTEXT)};border:none;font-size:12px;padding:6px 16px;font-family:{hf};"
        )
        self._skip_btn.clicked.connect(self.accept)
        self._back_btn = QPushButton("← Back")
        self._back_btn.setStyleSheet(
            f"background:{p.get('C_CARD', C_CARD)};color:{p.get('C_TEXT', C_TEXT)};border:1px solid {p.get('C_BORDER', C_BORDER)};"
            f"border-radius:8px;padding:8px 20px;font-size:12px;font-family:{hf};"
        )
        self._back_btn.clicked.connect(self._prev)
        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(
            f"background:{p.get('C_ACCENT', C_ACCENT)};color:{p.get('C_BG', 'white')};border:none;"
            f"border-radius:8px;padding:8px 24px;font-weight:bold;font-size:13px;font-family:{hf};"
        )
        self._next_btn.clicked.connect(self._next)
        bl.addWidget(self._skip_btn)
        bl.addStretch()
        bl.addWidget(self._back_btn)
        bl.addWidget(self._next_btn)
        L.addWidget(btn_bar)

    def _show_step(self, idx):
        step = self.STEPS[idx]
        self._icon_lbl.setText(step["icon"])
        self._title_lbl.setText(step["title"])
        self._body_lbl.setText(step["body"])
        for i, dot in enumerate(self._dots):
            dot.setStyleSheet(
                f"color:{C_ACCENT if i == idx else C_BORDER};"
                f"font-size:10px;background:transparent;"
            )
        is_last = idx == len(self.STEPS) - 1
        is_first = idx == 0
        self._back_btn.setVisible(not is_first)
        self._skip_btn.setVisible(not is_last)
        self._next_btn.setText("🚀  Get Started!" if is_last else "Next →")
        self._next_btn.setStyleSheet(
            f"background:{C_GREEN if is_last else C_ACCENT};"
            f"color:{'#1E1E2E' if is_last else 'white'};"
            f"border:none;border-radius:8px;padding:8px 24px;"
            f"font-weight:bold;font-size:13px;"
        )

    def _next(self):
        if self._step < len(self.STEPS) - 1:
            self._step += 1
            self._show_step(self._step)
        else:
            self.accept()

    def _prev(self):
        if self._step > 0:
            self._step -= 1
            self._show_step(self._step)

class MentorWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mentor_widget")
        self.setFixedHeight(50)
        l = QHBoxLayout(self)
        l.setContentsMargins(10, 2, 12, 2)
        l.setSpacing(12)

        # ── CIRCULAR AVATAR (Fixed Clipping) ──────────────────────────────────
        self.av_lbl = QLabel()
        self.av_lbl.setFixedSize(38, 38)
        self.av_lbl.setObjectName("mentor_avatar")

        av_path = app_resource_path(
            "assets", "themes", "dojo", "Cyber_ninja_turtle_202604270705.jpeg_clean.png"
        )
        if NINJA_THEME_ENABLED and os.path.exists(av_path):
            original_px = QPixmap(av_path)
            # Create circular mask
            size = 38
            rounded_px = QPixmap(size, size)
            rounded_px.fill(Qt.transparent)

            painter = QPainter(rounded_px)
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, size, size)
            painter.setClipPath(path)

            painter.drawPixmap(
                0,
                0,
                size,
                size,
                original_px.scaled(
                    size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                ),
            )
            painter.end()

            self.av_lbl.setPixmap(rounded_px)
        else:
            self.av_lbl.setStyleSheet(
                "background: #A86CFF; border-radius: 19px; border: 2px solid #A86CFF;"
            )

        txt_l = QVBoxLayout()
        txt_l.setSpacing(0)
        txt_l.setAlignment(Qt.AlignCenter)

        self.q_lbl = QLabel('"FOCUS. TRAIN. MASTER."')
        self.q_lbl.setObjectName("mentor_quote")
        # +1.5px (was 10px -> 11.5px)
        self.q_lbl.setStyleSheet(
            "font-family: 'Orbitron'; font-size: 11.5px; font-weight: 900; color: #A86CFF;"
        )

        self.n_lbl = QLabel("— DONATELLO")
        self.n_lbl.setObjectName("mentor_name")
        # +1px (was 7px -> 8px)
        self.n_lbl.setStyleSheet(
            "font-family: 'Orbitron'; font-size: 8px; font-weight: 700; color: #A86CFF; opacity: 0.8;"
        )

        txt_l.addWidget(self.q_lbl)
        txt_l.addWidget(self.n_lbl)

        # Swapped layout: Image LEFT, Text RIGHT
        l.addWidget(self.av_lbl)
        l.addLayout(txt_l)

    def set_style(self, theme):
        theme = normalize_theme(theme)
        if theme == "dojo":
            self.show()
            self.setStyleSheet("""
                QFrame#mentor_widget {
                    background: rgba(168, 108, 255, 0.1);
                    border: 1px solid #A86CFF;
                    border-radius: 6px;
                }
            """)
        else:
            self.hide()


"""
MUSIC WIDGET PATCH  — drop this into home_screen.py
=====================================================
1. Add MusicWidget class (below MentorWidget, before HomeScreen)
2. In HomeScreen._setup_ui(), add 3 lines after mentor widget
3. In HomeScreen.keyPressEvent(), add M / N key handlers

REQUIREMENTS:
    pip install pygame
    Put .mp3/.ogg files in:  assets/music/   (any filenames)
    Falls back gracefully if pygame missing or folder empty.
"""

# ── PASTE THIS IMPORT at top of home_screen.py (near other imports) ──────────
# (already have os, sys, etc — just add this)
import random

# ── PASTE THIS CLASS after MentorWidget, before HomeScreen ───────────────────


class MusicWidget(QFrame):
    """
    Compact BGM player for the top navbar.
    - M key  → toggle mute/unmute
    - N key  → next track
    - Click the widget → same as M
    Tracks: assets/music/*.mp3  (or .ogg)
    """

    MUSIC_DIR = app_resource_path("assets", "music")
    BGM_EXTENSIONS = {".mp3", ".ogg"}

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self._data = data
        self.setObjectName("music_widget")
        self.setFixedSize(110, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("BGM  [M] toggle  [N] next track")

        self._playing = False  # whether music is ON
        self._paused = False
        self._tracks = []
        self._idx = 0
        self._pygame_ok = False
        self._audio_initialized = False
        self._pygame = None
        self._player = None
        self._playlist = None

        self._scan_tracks()

        # ── Layout ──────────────────────────────────────────────────────
        hl = QHBoxLayout(self)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        self._note_lbl = QLabel("♪")
        self._note_lbl.setObjectName("music_note")
        self._note_lbl.setStyleSheet(
            "font-size:16px; color:#BD93F9; background:transparent;"
        )
        self._note_lbl.setFixedWidth(16)

        self._state_lbl = QLabel("BGM")
        self._state_lbl.setObjectName("music_state")
        self._state_lbl.setStyleSheet(
            "font-size:9px; font-weight:700; letter-spacing:1.5px;"
            "color:#7C6AF7; background:transparent;"
        )

        self._badge = QLabel("OFF")
        self._badge.setObjectName("music_badge")
        self._badge.setFixedWidth(28)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(
            "font-size:8px; font-weight:700; border-radius:3px; padding:1px 3px;"
            f"background:{C_CARD}; color:{C_SUBTEXT};"
        )

        hl.addWidget(self._note_lbl)
        hl.addWidget(self._state_lbl)
        hl.addWidget(self._badge)

        self._refresh_style(dojo=False)

    # ── Audio init ─────────────────────────────────────────────────────
    def _ensure_audio(self):
        if self._audio_initialized:
            return
        self._audio_initialized = True
        self._init_audio()
        self._sync_playlist()

    def _init_audio(self):
        try:
            import pygame

            pygame.mixer.init()
            self._pygame = pygame
            self._pygame_ok = True
        except Exception as e:
            self._pygame_ok = False
            print(
                f"[MusicWidget] pygame not available: {e}, falling back to QMediaPlayer"
            )
            try:
                from PyQt5.QtMultimedia import QMediaPlayer, QMediaPlaylist

                self._player = QMediaPlayer()
                self._playlist = QMediaPlaylist()
                self._player.setPlaylist(self._playlist)
            except Exception as e2:
                print(f"[MusicWidget] QMediaPlayer not available: {e2}")

    def _scan_tracks(self):
        if not os.path.isdir(self.MUSIC_DIR):
            return
        self._tracks = [
            os.path.join(self.MUSIC_DIR, name)
            for name in os.listdir(self.MUSIC_DIR)
            if os.path.isfile(os.path.join(self.MUSIC_DIR, name))
            and os.path.splitext(name)[1].lower() in self.BGM_EXTENSIONS
        ]
        random.shuffle(self._tracks)
        self._sync_playlist()

    def _sync_playlist(self):
        if self._playlist:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtMultimedia import QMediaContent, QMediaPlaylist

            self._playlist.clear()
            for track in self._tracks:
                self._playlist.addMedia(QMediaContent(QUrl.fromLocalFile(track)))
            self._playlist.setPlaybackMode(QMediaPlaylist.Loop)

    # ── Public API ──────────────────────────────────────────────────────
    def toggle(self):
        """M key handler."""
        if not self._tracks:
            return
        self._ensure_audio()
        if not self._pygame_ok and not self._player:
            return

        if self._playing:
            if self._pygame_ok:
                self._pygame.mixer.music.pause()
            elif self._player:
                self._player.pause()
            self._playing = False
            self._paused = True
        else:
            if self._paused:
                if self._pygame_ok:
                    self._pygame.mixer.music.unpause()
                elif self._player:
                    self._player.play()
                self._paused = False
            else:
                self._load_and_play(self._idx)
            self._playing = True
        self._update_badge()

    def next_track(self):
        """N key handler."""
        if not self._tracks:
            return
        self._ensure_audio()
        if not self._pygame_ok and not self._player:
            return

        self._idx = (self._idx + 1) % len(self._tracks)
        self._load_and_play(self._idx)
        self._playing = True
        self._paused = False
        self._update_badge()

    def _load_and_play(self, idx):
        try:
            vol = self._data.get("_volume", 40) if self._data else 40
            if self._pygame_ok:
                self._pygame.mixer.music.load(self._tracks[idx])
                self._pygame.mixer.music.set_volume(vol / 100.0)
                self._pygame.mixer.music.play(-1)  # -1 = loop
            elif self._player:
                self._playlist.setCurrentIndex(idx)
                self._player.setVolume(vol)
                self._player.play()
        except Exception as e:
            print(f"[MusicWidget] play error: {e}")

    # ── Visual ──────────────────────────────────────────────────────────
    def _update_badge(self):
        if self._playing:
            self._badge.setText("ON")
            self._badge.setStyleSheet(
                "font-size:8px; font-weight:700; border-radius:3px; padding:1px 3px;"
                f"background:{C_ACCENT}; color:white;"
            )
            self._note_lbl.setStyleSheet(
                "font-size:16px; color:#50FA7B; background:transparent;"
            )
        else:
            self._badge.setText("OFF")
            self._badge.setStyleSheet(
                "font-size:8px; font-weight:700; border-radius:3px; padding:1px 3px;"
                f"background:{C_CARD}; color:{C_SUBTEXT};"
            )
            self._note_lbl.setStyleSheet(
                "font-size:16px; color:#BD93F9; background:transparent;"
            )

    def _refresh_style(self, dojo: bool):
        if dojo:
            self.setStyleSheet("""
                QFrame#music_widget {
                    background: rgba(124, 106, 247, 0.08);
                    border: 1.5px solid #7C6AF7;
                    border-radius: 6px;
                }
                QFrame#music_widget:hover {
                    background: rgba(124, 106, 247, 0.18);
                    border: 1.5px solid #BD93F9;
                }
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#music_widget {{
                    background: {C_CARD};
                    border: 1px solid {C_BORDER};
                    border-radius: 6px;
                }}
                QFrame#music_widget:hover {{
                    background: {C_SURFACE};
                    border: 1px solid {C_ACCENT};
                }}
            """)

    def set_theme(self, theme: str):
        theme = normalize_theme(theme)
        self._refresh_style(dojo=(theme == "dojo"))

    def _set_volume_internal(self, value):
        if self._pygame_ok:
            try:
                self._pygame.mixer.music.set_volume(value / 100.0)
            except Exception:
                pass
        elif self._player:
            try:
                self._player.setVolume(value)
            except Exception:
                pass
        if self._data:
            self._data["_volume"] = value
            from data_manager import store
            store.mark_dirty()

    def set_volume(self, value):
        self._set_volume_internal(value)

    # click = toggle
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle()
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  PATCHES INSIDE HomeScreen
# ═══════════════════════════════════════════════════════════════════════════════

# ── PATCH 1: In _setup_ui(), AFTER the mentor block (line ~632), add: ─────────
#
#   self.music_widget = MusicWidget()
#   tl.addSpacing(4)
#   tl.addWidget(self.music_widget)
#
# Full context (replace lines 630-636):
#
#   self.mentor = MentorWidget()
#   self.mentor.setFixedWidth(220)
#   tl.addWidget(self.mentor)
#
#   self.music_widget = MusicWidget()          # ← ADD
#   tl.addSpacing(4)                            # ← ADD
#   tl.addWidget(self.music_widget)             # ← ADD
#
#   self._top_bar = self.top_frame
#   self._apply_topbar_style()
#   L.addWidget(self.top_frame)


# ── PATCH 2: In _toggle_theme(), after deck_view.set_theme(), add: ───────────
#
#   self.music_widget.set_theme(self._current_theme)


# ── PATCH 3: In keyPressEvent(), BEFORE super().keyPressEvent(e), add: ───────
#
#   elif key == Qt.Key_M:
#       self.music_widget.toggle()
#       e.accept()
#       return
#   elif key == Qt.Key_N:
#       self.music_widget.next_track()
#       e.accept()
#       return


# ── PATCH 4 (optional): In _apply_topbar_style(), dojo branch QPushButton#nav_btn
#   block, no changes needed — MusicWidget has its own set_theme().


# ═══════════════════════════════════════════════════════════════════════════════
#  FOLDER STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════
#
#  anki_occlusion/
#  └── assets/
#      └── music/
#          ├── lofi_beat_1.mp3
#          ├── ninja_ambient.ogg
#          └── ... (any .mp3 / .ogg / .wav)
#
#  pip install pygame
#
# ═══════════════════════════════════════════════════════════════════════════════


class ToastNotification(QLabel):
    def __init__(self, parent, text, duration_ms=2500):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        
        # Style matching the parent theme colors
        p = getattr(parent, "_p", {})
        bg = p.get("C_SURFACE", "#161B25")
        border = p.get("C_BORDER", "#2C3545")
        green = p.get("C_GREEN", "#50FA7B")
        text_color = p.get("C_TEXT", "#E1E6ED")
        
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {text_color};
                border: 1px solid {border};
                border-left: 3px solid {green};
                border-radius: 4px;
                padding: 10px 18px;
                font-size: 10pt;
                font-weight: bold;
            }}
        """)
        
        # Position at bottom-center of parent
        self.adjustSize()
        self.resize(max(self.width() + 10, 300), self.height() + 10)
        self.move_to_position()
        
        self.show()
        from PyQt5.QtCore import QTimer, QPropertyAnimation, QEasingCurve
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        from ui.canvas.retro_effects import _home_animations_enabled

        if _home_animations_enabled():
            # Opacity effect for fade animation
            self._effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._effect)

            # Animation: Fade In
            self._anim_in = QPropertyAnimation(self._effect, b"opacity")
            self._anim_in.setDuration(300)
            self._anim_in.setStartValue(0.0)
            self._anim_in.setEndValue(1.0)
            self._anim_in.setEasingCurve(QEasingCurve.OutCubic)

            # Animation: Fade Out
            self._anim_out = QPropertyAnimation(self._effect, b"opacity")
            self._anim_out.setDuration(400)
            self._anim_out.setStartValue(1.0)
            self._anim_out.setEndValue(0.0)
            self._anim_out.setEasingCurve(QEasingCurve.InCubic)
            self._anim_out.finished.connect(self.deleteLater)
            self._anim_in.start()
            QTimer.singleShot(duration_ms, self._anim_out.start)
        else:
            QTimer.singleShot(duration_ms, self.deleteLater)
        
    def move_to_position(self):
        if not self.parent():
            return
        parent_rect = self.parent().rect()
        x = (parent_rect.width() - self.width()) // 2
        y = parent_rect.height() - self.height() - 40
        self.move(x, y)


class RecoveryScanThread(QThread):
    finished_scan = pyqtSignal(dict)

    def __init__(self, data, startup=False, parent=None):
        super().__init__(parent)
        self.data = data
        self.startup = startup

    def run(self):
        try:
            summary = recovery_manager.scan_recovery(self.data, startup=self.startup)
            self.finished_scan.emit(summary)
        except Exception as e:
            print(f"[recovery] Background scan failed: {e}")
            self.finished_scan.emit({"drafts": [], "review_events": []})


class HomeScreen(QWidget):
    thread_safe_run_signal = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.thread_safe_run_signal.connect(self._run_closure)
        load_custom_fonts()  # ── SAFE FONT LOAD ──
        self._data = data
        self._preload_thread = None  # background PDF preload thread
        self._active_editor = None
        self._lazy_classic_settings_panel = None
        self._classic_archive_value = None
        self._classic_archive_box = None
        self._classic_archive_btn = None
        self._btn_shortcuts = None
        self.deck_tree = None
        self.deck_view = None
        self._cache_widget = None
        self._splitter_widget = None
        self._tmnt_layout = None
        self._backup_in_progress = False
        self._restore_in_progress = False
        self._prune_in_progress = False
        self._setup_ui()
        self._check_resume_button_state()

    @property
    def _classic_settings_panel(self):
        if getattr(self, "_lazy_classic_settings_panel", None) is None:
            self._lazy_classic_settings_panel = self._build_classic_settings_panel()
        return self._lazy_classic_settings_panel

    @_classic_settings_panel.setter
    def _classic_settings_panel(self, val):
        self._lazy_classic_settings_panel = val

    def __getattr__(self, name):
        if name in ("_cb_keep_fullscreen", "_cb_invert_pdf", "_classic_volume_slider", "_btn_pen_perf"):
            _ = self._classic_settings_panel
            if name in self.__dict__:
                return self.__dict__[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ── TOP BAR (Container) ───────────────────────────────────────────────
        self.top_frame = QFrame()
        self.top_frame.setFixedHeight(60)  # Larger height
        self.top_frame.setObjectName("topbar")

        tl = QHBoxLayout(self.top_frame)
        tl.setContentsMargins(14, 0, 14, 0)
        tl.setSpacing(12)

        # Logo Section
        logo_layout = QHBoxLayout()
        logo_layout.setSpacing(12)

        self.l_box = QLabel("猿")
        self.l_box.setObjectName("logo_box")
        self.l_box.setFixedSize(42, 42)  # Significantly larger
        self.l_box.setAlignment(Qt.AlignCenter)

        self.l_text = QLabel("ANKI OCCLUSION")
        self.l_text.setObjectName("logo_text")

        logo_layout.addWidget(self.l_box)
        logo_layout.addWidget(self.l_text)
        tl.addLayout(logo_layout)

        tl.addStretch()

        def _topbtn(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("nav_btn")
            return b

        btn_math = _topbtn("🧮 MATH TRAINER", "Practice Tables, Squares & Cubes")
        btn_journal = _topbtn("📓 JOURNAL", "Open Daily Journal")
        btn_report = _topbtn("📊 REPORT", "Open Daily Mission Report Card")
        self._btn_resume = _topbtn("⚡ RESUME LAST MISSION", "Resume last review session (R)")
        self._btn_save = _topbtn("💾 SAVE", "Save now  Ctrl+S")
        self._btn_settings = _topbtn("⚙ SETTINGS", "Visual scale and Mission Archive")
        self._btn_shortcuts = _topbtn("⌨ SHORTCUTS", "Set or modify keyboard shortcuts")
        btn_help = _topbtn("❓ HELP", "Show quick-start guide")
        btn_about = _topbtn("ℹ ABOUT", "About Anki Occlusion")

        btn_math.clicked.connect(self._show_math_trainer)
        btn_journal.clicked.connect(self._show_journal)
        btn_report.clicked.connect(self._show_mission_report)
        self._btn_resume.clicked.connect(self.resume_last_review)
        self._btn_save.clicked.connect(self._on_classic_save_clicked)
        self._btn_settings.clicked.connect(self._toggle_classic_settings_panel)
        self._btn_shortcuts.clicked.connect(self._show_shortcuts)
        btn_help.clicked.connect(self._show_help)
        btn_about.clicked.connect(self._show_about)

        # Theme Toggle Button
        saved_theme = self._data.get("_theme", "classic")
        self._current_theme = normalize_theme(saved_theme)
        from theme_manager import get_palette
        self._p = get_palette(self._current_theme)
        _next_lbl = {
            "classic": "🐢 TMNT MODE",
            "tmnt": "🎮 MANHATTAN",
            "manhattan": "🔮 ARCANUM",
            "arcanum": "📚 CLASSIC MODE",
        }
        btn_text = _next_lbl.get(self._current_theme, "🐢 TMNT MODE")
        self._btn_theme = _topbtn(btn_text, "Switch Theme")
        self._btn_theme.clicked.connect(self._toggle_theme)

        # Font Buttons
        def _fontbtn(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(30)
            b.setObjectName("font_btn")
            return b

        btn_fa = _fontbtn("A−", "Decrease font size")
        btn_fr = _fontbtn("A", "Reset font size")
        btn_fi = _fontbtn("A+", "Increase font size")

        btn_fa.clicked.connect(lambda: self._emit_font(-1))
        btn_fr.clicked.connect(lambda: self._emit_font(0))
        btn_fi.clicked.connect(lambda: self._emit_font(+1))

        tl.addWidget(btn_math)
        tl.addWidget(btn_journal)
        tl.addWidget(btn_report)
        tl.addWidget(self._btn_resume)
        tl.addWidget(self._btn_save)
        tl.addWidget(self._btn_settings)
        tl.addWidget(self._btn_shortcuts)
        tl.addWidget(btn_help)
        tl.addWidget(btn_about)
        tl.addSpacing(6)
        tl.addWidget(btn_fa)
        tl.addWidget(btn_fr)
        tl.addWidget(btn_fi)

        self.music_widget = MusicWidget(data=self._data)
        tl.addSpacing(4)
        tl.addWidget(self.music_widget)

        # Mentor Section (Aligned with Cache Bar width ~220px)
        self.mentor = MentorWidget()
        self.mentor.setFixedWidth(220)
        tl.addWidget(self.mentor)

        self._top_bar = self.top_frame
        self._apply_topbar_style()  # Initial style
        self._lazy_classic_settings_panel = None
        L.addWidget(self.top_frame)

        # ── BODY STACK: active theme is built immediately; inactive theme is lazy.
        self._body_stack = QStackedWidget()

        L.addWidget(self._body_stack, stretch=1)

        # Activate correct body for saved theme
        if is_retro_theme(self._current_theme) and self._ensure_tmnt_layout():
            self.top_frame.hide()
            self._body_stack.setCurrentWidget(self._tmnt_layout)
            QTimer.singleShot(
                100,
                lambda: (
                    self.window().statusBar().hide()
                    if self.window() and hasattr(self.window(), "statusBar")
                    else None
                ),
            )
        else:
            self._ensure_classic_layout()
            self.top_frame.show()
            self._body_stack.setCurrentWidget(self._splitter_widget)
        self._install_home_ram_shortcut()
        self._install_resume_review_shortcut()

    def _ensure_classic_layout(self):
        if self._splitter_widget is not None:
            return self._splitter_widget

        DeckTreeCls, CacheWidgetCls, DeckViewCls = _load_classic_home_classes()
        self._splitter_widget = QWidget()
        _sw_l = QVBoxLayout(self._splitter_widget)
        _sw_l.setContentsMargins(0, 0, 0, 0)
        _sw_l.setSpacing(0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(5)
        self.deck_tree = DeckTreeCls(self._data, theme=self._current_theme)
        self.deck_tree.setMinimumWidth(200)
        self.deck_tree.setMaximumWidth(16777215)
        self.deck_tree.deck_selected.connect(self._on_deck_selected)
        split.addWidget(self.deck_tree)
        self.deck_view = DeckViewCls()
        self.deck_view.set_theme(self._current_theme)
        split.addWidget(self.deck_view)
        self._cache_widget = CacheWidgetCls()
        split.addWidget(self._cache_widget)
        split.setSizes([340, 760, 220])
        _sw_l.addWidget(split, stretch=1)
        self._body_stack.addWidget(self._splitter_widget)
        return self._splitter_widget

    def _ensure_tmnt_layout(self):
        if self._tmnt_layout is not None:
            return self._tmnt_layout
        if _load_tmnt_home_layout() is None:
            return None
        self._tmnt_layout = self._create_tmnt_layout()
        self._body_stack.addWidget(self._tmnt_layout)
        return self._tmnt_layout

    def _install_home_ram_shortcut(self):
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtWidgets import QShortcut

        self._clear_home_ram_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        self._clear_home_ram_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._clear_home_ram_shortcut.activated.connect(self._clear_home_ram_caches)

    def _install_resume_review_shortcut(self):
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtWidgets import QShortcut
        sc_text = shortcut_manager.shortcut_text("home.resume_review")
        if sc_text:
            self._resume_review_shortcut = QShortcut(QKeySequence(sc_text), self)
            self._resume_review_shortcut.setContext(Qt.WindowShortcut)
            self._resume_review_shortcut.activated.connect(self._on_resume_review_shortcut_activated)

    def _on_resume_review_shortcut_activated(self):
        import sys
        sys.stderr.write("[ANNO-LOG] R key pressed on Home Screen!\n")
        if not self.isVisible():
            sys.stderr.write("[ANNO-LOG] Resume shortcut ignored: Home Screen is not visible\n")
            return
        fw = self.focusWidget()
        sys.stderr.write(f"[ANNO-LOG] Active review check: {getattr(self, '_active_review', None) is None}, Focus widget: {fw.__class__.__name__ if fw else 'None'} ({fw})\n")
        if getattr(self, "_active_review", None) is None:
            from PyQt5.QtWidgets import QLineEdit, QTextEdit
            if not (fw and isinstance(fw, (QLineEdit, QTextEdit))):
                sys.stderr.write("[ANNO-LOG] Resume shortcut criteria matched. Calling resume_last_review()\n")
                self.resume_last_review()
            else:
                sys.stderr.write("[ANNO-LOG] Resume shortcut ignored: focus is in line/text edit\n")
        else:
            sys.stderr.write("[ANNO-LOG] Resume shortcut ignored: an active review session already exists\n")



    def _clear_home_ram_caches(self):
        try:
            _ = self.parent()
        except RuntimeError:
            return

        active_editor = getattr(self, "_active_editor", None)
        if active_editor is not None:
            try:
                if not active_editor.isVisible():
                    self._active_editor = None
                    active_editor = None
            except Exception:
                self._active_editor = None
                active_editor = None

        if (
            getattr(self, "_active_review", None) is not None
            or active_editor is not None
        ):
            return

        t0 = time.perf_counter()
        from cache_manager import PAGE_CACHE, PIXMAP_REGISTRY
        import gc

        before = len(getattr(PAGE_CACHE, "_cache", {}) or {})
        pixmap_entries = list(getattr(PIXMAP_REGISTRY, "_entries", {}).items())
        hidden_count = len(pixmap_entries)
        thumb_count = 0
        canvas_count = 0

        # Purge PyMuPDF internal caches and skeleton caches
        try:
            import fitz
            from pdf_engine import _SKELETON_CACHE, _SKELETON_PLACEHOLDER_CACHE, _SKELETON_DIMS_CACHE
            from perf_utils import _pdf_page_count_cache
            _SKELETON_CACHE.clear()
            _SKELETON_PLACEHOLDER_CACHE.clear()
            _SKELETON_DIMS_CACHE.clear()
            _pdf_page_count_cache.clear()
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass

        PAGE_CACHE.clear_ram_only()
        try:
            from PyQt5.QtGui import QPixmapCache
            import pdf_engine

            QPixmapCache.clear()
            pdf_engine._CURRENT_ACTIVE_PDF = None
        except Exception:
            pass

        for label, (wref, attr, _path) in pixmap_entries:
            obj = wref()
            if obj is not None:
                try:
                    setattr(obj, attr, None)
                except RuntimeError:
                    pass
            PIXMAP_REGISTRY.unregister(label)

        deck_view = getattr(self, "deck_view", None)
        if deck_view is not None and hasattr(deck_view, "_thumb_cache"):
            thumb_count += len(deck_view._thumb_cache)
            deck_view._thumb_cache.clear()

        tmnt_main = getattr(getattr(self, "_tmnt_layout", None), "main", None)
        if tmnt_main is not None and hasattr(tmnt_main, "_thumb_cache"):
            thumb_count += len(tmnt_main._thumb_cache)
            tmnt_main._thumb_cache.clear()

        gc.collect()

        cache_widget = getattr(self, "_cache_widget", None)
        if cache_widget is not None and hasattr(cache_widget, "refresh"):
            cache_widget.refresh()
        tmnt_banga = getattr(getattr(self, "_tmnt_layout", None), "banga", None)
        if tmnt_banga is not None and hasattr(tmnt_banga, "refresh"):
            tmnt_banga.refresh()

        elapsed = (time.perf_counter() - t0) * 1000.0
        print(
            f"[PROFILE][home_clear_caches] 🧹 RAM cache cleared in {elapsed:.1f}ms — "
            f"{before} pages evicted, mask layers invalidated, disk untouched"
        )

        win = self.window()
        if win is not None and hasattr(win, "statusBar") and win.statusBar():
            win.statusBar().showMessage(f"🧹 RAM cache cleared — {before} pages freed in {elapsed:.1f}ms", 3000)

    def show_review(self, cards, data, _on_batch_done=None, state_to_restore=None, is_practice=False, initial_idx: int = 0, order_mode: str = "default"):
        """Replace the DeckView panel with ReviewScreen inline."""
        _save_done = [False]

        rev = _load_review_screen()(cards, data=data, parent=self, state_to_restore=state_to_restore, is_practice=is_practice, initial_idx=initial_idx, order_mode=order_mode)
        self._active_review = rev

        def _schedule_review_save():
            if store.is_dirty():
                store.save_force(async_save=True, force_gdrive=True)

        def _on_finished():
            if not _save_done[0]:
                _save_done[0] = True
                _schedule_review_save()

            # Save the session state for sequential review undo if active
            if getattr(self, "_current_sequential_group", None) is not None:
                state = {
                    "items": list(rev._items),
                    "idx": rev._idx,
                    "done": rev._done,
                    "undo_stack": list(rev._review_undo_stack),
                    "redo_stack": list(rev._review_redo_stack),
                    "queued_ids": set(rev._queued_ids),
                    "deleted_ids": set(rev._deleted_ids),
                    "order_mode": getattr(rev, "_order_mode", "default"),
                    "batch": self._current_sequential_group,
                }
                self._past_sequential_sessions.append(state)

            self.hide_review()
            if _on_batch_done:
                _on_batch_done()

        def _on_cancelled():
            if not _save_done[0]:
                _save_done[0] = True
                _schedule_review_save()
            self._current_sequential_group = None
            self._sequential_groups = []
            self._past_sequential_sessions = []
            self.hide_review()

        rev.finished.connect(_on_finished)
        rev.cancelled.connect(_on_cancelled)
        rev.undo_requested_when_empty.connect(self._handle_sequential_undo)

        if is_retro_theme(self._current_theme) and self._ensure_tmnt_layout():
            # TMNT: push review into body stack slot 2
            self._pre_review_tmnt = True
            self.top_frame.hide()
            self._body_stack.addWidget(rev)
            self._body_stack.setCurrentWidget(rev)
        else:
            self._pre_review_tmnt = False
            self._ensure_classic_layout()
            split = self._get_splitter()
            if split is None:
                return
            self._pre_review_sizes = split.sizes()
            self.deck_tree.hide()
            self._top_bar.hide()
            self.window().statusBar().hide()
            split.replaceWidget(1, rev)
            split.setSizes([0, split.width(), 0])

        rev.show()
        QTimer.singleShot(0, rev.canvas.setFocus)

    def show_review_sequential(self, groups, data, is_practice=False, order_mode: str = "default"):
        """Review card groups one PDF at a time.
        After each group finishes: clear RAM + masks + pixmap, then load next group."""
        self._sequential_groups = list(groups)
        self._past_sequential_sessions = []
        self._current_sequential_group = None
        self._sequential_data = data
        self._sequential_is_practice = bool(is_practice)
        self._sequential_order_mode = str(order_mode or "default")

        def _clear_ram():
            from cache_manager import PAGE_CACHE, PIXMAP_REGISTRY

            PAGE_CACHE.clear_ram_only()
            for label in list(PIXMAP_REGISTRY._entries.keys()):
                PIXMAP_REGISTRY.unregister(label)

        def _on_done():
            _clear_ram()
            if self._sequential_groups:
                QTimer.singleShot(0, _launch_next)
            else:
                self._current_sequential_group = None
                self._past_sequential_sessions = []

        def _launch_next():
            if not self._sequential_groups:
                return
            batch = self._sequential_groups.pop(0)
            self._current_sequential_group = batch
            self.show_review(batch, data, _on_batch_done=_on_done, is_practice=self._sequential_is_practice, order_mode=self._sequential_order_mode)

        self._sequential_on_done = _on_done
        _launch_next()

    def _handle_sequential_undo(self):
        if not getattr(self, "_past_sequential_sessions", None):
            return

        current_rev = getattr(self, "_active_review", None)
        if current_rev:
            current_rev._undo_handled = True

        prev_state = self._past_sequential_sessions.pop()

        # Put the current group back to the remaining groups list
        if getattr(self, "_current_sequential_group", None) is not None:
            self._sequential_groups.insert(0, self._current_sequential_group)

        # Hide current review screen (deletes current widget, restores home view)
        self.hide_review()

        # Restore the previous session
        batch = prev_state["batch"]
        self._current_sequential_group = batch

        self.show_review(
            batch,
            self._sequential_data,
            _on_batch_done=self._sequential_on_done,
            state_to_restore=prev_state,
            is_practice=prev_state.get("is_practice", getattr(self, "_sequential_is_practice", False)),
        )

    def hide_review(self):
        """Restore layout after review ends."""
        rev = getattr(self, "_active_review", None)
        self._active_review = None

        if rev:
            # 1. Disconnect signals to break python closure reference cycles
            try:
                rev.finished.disconnect()
            except Exception:
                pass
            try:
                rev.cancelled.disconnect()
            except Exception:
                pass

            # 2. Call close() to trigger closeEvent and release threads/monitors
            try:
                rev.close()
            except Exception:
                pass

            # 3. Explicitly clear high-memory attributes on the canvas and review screen
            if hasattr(rev, "canvas") and rev.canvas is not None:
                try:
                    rev.canvas._pages = []
                    rev.canvas._px = None
                    if hasattr(rev.canvas, "_spx_cache"):
                        rev.canvas._spx_cache.clear()
                except Exception:
                    pass
            try:
                rev._current_pixmap = None
                if hasattr(rev, "_pdf_cache"):
                    rev._pdf_cache.clear()
            except Exception:
                pass

        if getattr(self, "_pre_review_tmnt", False) and self._tmnt_layout:
            if rev:
                self._body_stack.removeWidget(rev)
                rev.setParent(None)
                rev.deleteLater()
            self._body_stack.setCurrentWidget(self._tmnt_layout)
            self.top_frame.hide()
            self._tmnt_layout.refresh()
        else:
            split = self._get_splitter()
            if rev and split:
                split.replaceWidget(1, self.deck_view)
                rev.setParent(None)
                rev.deleteLater()
            if self.deck_view:
                self.deck_view.show()
            if self.deck_tree:
                self.deck_tree.show()
            if getattr(self, "_cache_widget", None):
                self._cache_widget.show()
            self._top_bar.show()
            self.window().statusBar().show()
            sizes = getattr(self, "_pre_review_sizes", [340, 760, 220])
            if split:
                split.setSizes(sizes)
        self.refresh()
        self._check_resume_button_state()
        QTimer.singleShot(100, self._clear_home_ram_caches)

    def _get_splitter(self):
        """Return the main QSplitter child."""
        if self._splitter_widget is None:
            return None
        for child in self._splitter_widget.children():
            if isinstance(child, QSplitter):
                return child
        return None

    def save_last_review_session(self, cards, current_idx=0):
        if not cards or current_idx >= len(cards):
            self.clear_last_review_session()
            return
        try:
            import json
            session_data = {
                "card_identifiers": [
                    {
                        "card_id": card.get("_id") or card.get("id"),
                        "card_type": card.get("card_type", "image"),
                        "question": card.get("question"),
                        "pdf_path": card.get("pdf_path"),
                        "image_path": card.get("image_path"),
                        "title": card.get("title"),
                        "visual_hash": card.get("visual_hash")
                    } for card in cards
                ],
                "idx": current_idx
            }
            from storage_paths import current_data_file
            app_dir = os.path.dirname(current_data_file())
            session_file = os.path.join(app_dir, "last_review_session.json")
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2)
            if hasattr(self, "_btn_resume") and self._btn_resume:
                self._btn_resume.setEnabled(True)
                from theme_manager import get_palette
                p = get_palette(self._current_theme)
                self._btn_resume.setStyleSheet(f"QPushButton {{ color: {p.get('C_ORANGE', '#FFB86C')}; font-weight: bold; }}")
            if hasattr(self, "_tmnt_layout") and self._tmnt_layout:
                self._tmnt_layout.set_resume_enabled(True)
        except Exception as e:
            print("[DEBUG] Failed to save last review session:", e)

    def load_last_review_session(self):
        try:
            import json
            from storage_paths import current_data_file
            app_dir = os.path.dirname(current_data_file())
            session_file = os.path.join(app_dir, "last_review_session.json")
            if not os.path.exists(session_file):
                return None
            with open(session_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def clear_last_review_session(self):
        try:
            from storage_paths import current_data_file
            app_dir = os.path.dirname(current_data_file())
            session_file = os.path.join(app_dir, "last_review_session.json")
            if os.path.exists(session_file):
                os.remove(session_file)
        except Exception:
            pass
        if hasattr(self, "_btn_resume") and self._btn_resume:
            self._btn_resume.setEnabled(False)
            self._btn_resume.setStyleSheet("")
        if hasattr(self, "_tmnt_layout") and self._tmnt_layout:
            self._tmnt_layout.set_resume_enabled(False)

    def resume_last_review(self):
        session = self.load_last_review_session()
        if not session:
            QMessageBox.information(self, "No session", "No previous review session found.")
            return
        
        identifiers = session.get("card_identifiers", [])
        idx = session.get("idx", 0)
        if not identifiers:
            return
            
        resolved_cards = []
        all_db_cards = []
        def _walk(d):
            all_db_cards.extend(d.get("cards", []))
            for child in d.get("children", []):
                _walk(child)
                
        for deck in self._data.get("decks", []):
            _walk(deck)
            
        for idf in identifiers:
            card_id = idf.get("card_id")
            card_type = idf.get("card_type")
            question = idf.get("question")
            pdf_path = idf.get("pdf_path")
            image_path = idf.get("image_path")
            title = idf.get("title")
            visual_hash = idf.get("visual_hash")
            
            matched_card = None
            for card in all_db_cards:
                c_id = card.get("_id") or card.get("id")
                if card_id and c_id and c_id == card_id:
                    matched_card = card
                    break
                if (card_type == "text" or card.get("card_type") == "text"):
                    if question and card.get("question") == question:
                        matched_card = card
                        break
                    if title and card.get("title") == title:
                        matched_card = card
                        break
                if visual_hash and card.get("visual_hash") == visual_hash:
                    matched_card = card
                    break
                if pdf_path and card.get("pdf_path") == pdf_path and card.get("title") == title:
                    matched_card = card
                    break
                if image_path and card.get("image_path") == image_path and card.get("title") == title:
                    matched_card = card
                    break
            
            if matched_card:
                resolved_cards.append(matched_card)
                
        if not resolved_cards:
            QMessageBox.information(self, "Resume Failed", "Could not find the cards of the last session in the database.")
            return
            
        self.show_review(resolved_cards, self._data, initial_idx=idx)
        
        if hasattr(self, "_active_review") and self._active_review:
            if self._active_review._items:
                target_idx = max(0, min(idx, len(self._active_review._items) - 1))
                if self._active_review._idx != target_idx:
                    self._active_review._idx = target_idx
                    self._active_review._load_item()
            else:
                self._active_review._idx = 0
                self._active_review._finish()

    def _check_resume_button_state(self):
        session = self.load_last_review_session()
        has_session = bool(session and session.get("card_identifiers"))
        if has_session:
            self._btn_resume.setEnabled(True)
            from theme_manager import get_palette
            p = get_palette(self._current_theme)
            self._btn_resume.setStyleSheet(f"QPushButton {{ color: {p.get('C_ORANGE', '#FFB86C')}; font-weight: bold; }}")
        else:
            self._btn_resume.setEnabled(False)
            self._btn_resume.setStyleSheet("")
        if hasattr(self, "_tmnt_layout") and self._tmnt_layout:
            self._tmnt_layout.set_resume_enabled(has_session)

    def _on_deck_selected(self, deck):
        t0 = time.perf_counter()
        self.deck_view.load_deck(deck, self._data)
        print(f"[PROFILE][home_deck_selected] Loaded deck '{deck.get('name', 'Unknown')}' in {(time.perf_counter() - t0) * 1000:.1f}ms")
        # [FIX] Removed _preload_deck_pdf here — PDF should only load
        # when the user explicitly opens/reviews a card, not on deck click.
    def _show_journal(self):
        if self.__dict__.get("_journal_widget") is not None:
            return
        t0 = time.perf_counter()
        page_cls = _load_journal_dialog()
        if page_cls is None:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Journal",
                "journal.py not found!\nPlace journal.py next to anki_occlusion_v19.py",
            )
            return

        jw = page_cls(parent=self)
        jw.closed.connect(self._hide_journal)
        self._journal_widget = jw

        if is_retro_theme(self.__dict__.get("_current_theme")) and self.__dict__.get("_tmnt_layout"):
            self._pre_journal_tmnt = True
            self.top_frame.hide()
            self._body_stack.addWidget(jw)
            self._body_stack.setCurrentWidget(jw)
        else:
            self._pre_journal_tmnt = False
            self._ensure_classic_layout()
            split = self._get_splitter()
            if split is None:
                return
            self._pre_journal_sizes = split.sizes()
            split.replaceWidget(1, jw)
            jw.show()
            split.setSizes([split.sizes()[0], split.width(), 0])
        print(f"[PROFILE][home_show_journal] Daily Journal initialized and displayed in {(time.perf_counter() - t0) * 1000:.1f}ms")

    def _hide_journal(self):
        jw = self.__dict__.get("_journal_widget")
        self._journal_widget = None
        if not jw:
            return
        if self.__dict__.get("_pre_journal_tmnt") and self.__dict__.get("_tmnt_layout"):
            self._body_stack.removeWidget(jw)
            jw.setParent(None)
            jw.deleteLater()
            self._body_stack.setCurrentWidget(self._tmnt_layout)
            self.top_frame.hide()
            self._tmnt_layout.refresh()
        else:
            split = self._get_splitter()
            if split:
                split.replaceWidget(1, self.deck_view)
                jw.setParent(None)
                jw.deleteLater()
                if self.deck_view:
                    self.deck_view.show()
                if self.deck_tree:
                    self.deck_tree.show()
                if getattr(self, "_cache_widget", None):
                    self._cache_widget.show()
                sizes = self.__dict__.get("_pre_journal_sizes", [340, 760, 220])
                split.setSizes(sizes)
        self.refresh()
        self._clear_home_ram_caches()

    def _show_math_trainer(self):
        if getattr(self, "_math_trainer", None) is not None:
            return
        t0 = time.perf_counter()
        page_cls = _load_math_trainer_page()
        if page_cls is None:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Math Trainer",
                "math_trainer.py not found!\n\nPlace math_trainer.py inside the ui/ folder.",
            )
            return
        mt = page_cls(parent=self)
        mt.closed.connect(self._hide_math_trainer)
        self._math_trainer = mt

        # Warm up the OCR background worker when entering Math Trainer
        try:
            from services.ocr_engine import warm_up as ocr_warm_up, SIGNALS, is_ready as ocr_is_ready
            try:
                SIGNALS.ready.disconnect(self._on_ocr_ready_popup)
            except Exception:
                pass
            if ocr_is_ready():
                QTimer.singleShot(100, self._on_ocr_ready_popup)
            else:
                SIGNALS.ready.connect(self._on_ocr_ready_popup)
            import threading
            threading.Thread(target=ocr_warm_up, daemon=True).start()
        except Exception as e:
            print(f"[MathTrainer] Failed to warm up OCR worker: {e}")
        if is_retro_theme(self._current_theme) and self._tmnt_layout:
            self._pre_math_tmnt = True
            self.top_frame.hide()
            self._body_stack.addWidget(mt)
            self._body_stack.setCurrentWidget(mt)
        else:
            self._pre_math_tmnt = False
            self._ensure_classic_layout()
            split = self._get_splitter()
            if split is None:
                return
            self._pre_math_sizes = split.sizes()
            split.replaceWidget(1, mt)
            mt.show()
            split.setSizes([split.sizes()[0], split.width(), 0])
        print(f"[PROFILE][home_show_math_trainer] Math Trainer initialized and displayed in {(time.perf_counter() - t0) * 1000:.1f}ms")

    def _hide_math_trainer(self):
        try:
            from services.ocr_engine import SIGNALS
            SIGNALS.ready.disconnect(self._on_ocr_ready_popup)
        except Exception:
            pass

        mt = getattr(self, "_math_trainer", None)
        self._math_trainer = None
        if not mt:
            return
        if getattr(self, "_pre_math_tmnt", False) and self._tmnt_layout:
            self._body_stack.removeWidget(mt)
            mt.setParent(None)
            mt.deleteLater()
            self._body_stack.setCurrentWidget(self._tmnt_layout)
            self.top_frame.hide()
            self._tmnt_layout.refresh()
        else:
            split = self._get_splitter()
            if split:
                split.replaceWidget(1, self.deck_view)
                mt.setParent(None)
                mt.deleteLater()
                if self.deck_view:
                    self.deck_view.show()
                if self.deck_tree:
                    self.deck_tree.show()
                if getattr(self, "_cache_widget", None):
                    self._cache_widget.show()
                sizes = getattr(self, "_pre_math_sizes", [340, 760, 220])
                split.setSizes(sizes)
        self.refresh()
        self._clear_home_ram_caches()

        # Shutdown the OCR background worker when exiting Math Trainer to free RAM
        try:
            from services.ocr_engine import shutdown as ocr_shutdown
            ocr_shutdown()
        except Exception as e:
            print(f"[MathTrainer] Failed to shutdown OCR worker: {e}")

    def _on_ocr_ready_popup(self):
        try:
            from services.ocr_engine import SIGNALS
            SIGNALS.ready.disconnect(self._on_ocr_ready_popup)
        except Exception:
            pass
        ToastNotification(self, "⚡ OCR engine loaded completely and is ready!")

    def _show_about(self):
        AboutDialog(self).exec_()

    def _show_help(self):
        OnboardingDialog(self).exec_()

    def _show_mission_report(self, date_str=None):
        if self.__dict__.get("_report_widget") is not None:
            return
        t0 = time.perf_counter()
        from .mission_report_dialog import MissionReportDialog
        rw = MissionReportDialog(initial_date=date_str, parent=self)
        rw.closed.connect(self._hide_mission_report)
        self._report_widget = rw

        if is_retro_theme(self.__dict__.get("_current_theme")) and self.__dict__.get("_tmnt_layout"):
            self._pre_report_tmnt = True
            self._pre_report_widget = self._body_stack.currentWidget()
            self.top_frame.hide()
            self._body_stack.addWidget(rw)
            self._body_stack.setCurrentWidget(rw)
        else:
            self._pre_report_tmnt = False
            self._ensure_classic_layout()
            split = self._get_splitter()
            if split is None:
                return
            self._pre_report_sizes = split.sizes()
            self._pre_report_widget = split.widget(1)
            split.replaceWidget(1, rw)
            rw.show()
            split.setSizes([split.sizes()[0], split.width(), 0])
        print(f"[PROFILE][home_show_mission_report] Mission Report initialized and displayed in {(time.perf_counter() - t0) * 1000:.1f}ms")

    def _hide_mission_report(self):
        rw = self.__dict__.get("_report_widget")
        self._report_widget = None
        if not rw:
            return
        if self.__dict__.get("_pre_report_tmnt") and self.__dict__.get("_tmnt_layout"):
            self._body_stack.removeWidget(rw)
            rw.setParent(None)
            rw.deleteLater()
            target_widget = self.__dict__.get("_pre_report_widget")
            if target_widget and self._body_stack.indexOf(target_widget) != -1:
                self._body_stack.setCurrentWidget(target_widget)
            else:
                self._body_stack.setCurrentWidget(self._tmnt_layout)
            if self._body_stack.currentWidget() == self._tmnt_layout:
                self.top_frame.hide()
                self._tmnt_layout.refresh()
        else:
            split = self._get_splitter()
            if split:
                target_widget = self.__dict__.get("_pre_report_widget") or self.deck_view
                split.replaceWidget(1, target_widget)
                rw.setParent(None)
                rw.deleteLater()
                if target_widget:
                    target_widget.show()
                if self.deck_tree:
                    self.deck_tree.show()
                if getattr(self, "_cache_widget", None):
                    self._cache_widget.show()
                sizes = self.__dict__.get("_pre_report_sizes", [340, 760, 220])
                split.setSizes(sizes)
        self.refresh()
        self._clear_home_ram_caches()

    def _create_tmnt_layout(self):
        layout_cls = _load_tmnt_home_layout()
        if layout_cls is None:
            return None
        layout = layout_cls(self._data, parent=self)
        layout.btn_save_clicked.connect(self._save_current_data_now)
        layout.btn_math_clicked.connect(self._show_math_trainer)
        layout.btn_journal_clicked.connect(self._show_journal)
        if hasattr(layout, "btn_report_clicked"):
            layout.btn_report_clicked.connect(self._show_mission_report)
        layout.btn_resume_clicked.connect(self.resume_last_review)
        layout.btn_theme_clicked.connect(self._toggle_theme)
        layout.btn_help_clicked.connect(self._show_help)
        layout.btn_about_clicked.connect(self._show_about)
        layout.btn_shortcuts_clicked.connect(self._show_shortcuts)
        layout.font_change.connect(self._emit_font)
        layout.bgm_toggle.connect(self._toggle_tmnt_bgm)
        layout.bgm_volume_changed.connect(self.music_widget.set_volume)
        layout.set_bgm_state(self.music_widget._playing)
        return layout

    def _save_current_data_now(self):
        t0 = time.perf_counter()
        try:
            store.mark_dirty()
            store.save_force(async_save=True)
            flush_runtime_state(save_store=False)
        except Exception as ex:
            QMessageBox.warning(
                self, "Save Failed", f"Could not save current data:\n{ex}"
            )
            return
        print(f"[PROFILE][home_save] Data save triggered in {(time.perf_counter() - t0) * 1000:.1f}ms")

        win = self.window()
        if hasattr(win, "statusBar") and callable(win.statusBar):
            sb = win.statusBar()
            if sb is not None:
                sb.showMessage(f"Saved data to {current_data_file()}", 4000)

    def _on_classic_save_clicked(self):
        self._save_current_data_now()

    def _show_shortcuts(self):
        dlg = _load_shortcut_settings_dialog()(self)
        dlg.exec_()

    def _build_classic_settings_panel(self):
        from PyQt5.QtWidgets import QApplication
        from theme_manager import get_palette
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        p_green = p.get("C_GREEN", "#50FA7B")
        p_accent = p.get("C_ACCENT", "#7C6AF7")
        p_red = p.get("C_RED", "#FF5555")
        p_card = p.get("C_CARD", "#313145")
        p_border = p.get("C_BORDER", "#45475A")
        p_text = p.get("C_TEXT", "#CDD6F4")

        panel = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        panel.setObjectName("classic_settings_panel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setStyleSheet(f"""
            QFrame#classic_settings_panel {{
                background: {C_SURFACE};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QPushButton, QComboBox {{
                background: {C_CARD};
                color: {C_SUBTEXT};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                padding: 5px 10px;
                font-family: 'Segoe UI';
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover, QComboBox:hover {{
                background: {C_BG};
                color: {C_TEXT};
                border-color: {C_ACCENT};
            }}
            QComboBox QAbstractItemView {{
                background-color: {C_CARD};
                color: {C_SUBTEXT};
                border: 1px solid {C_BORDER};
                selection-background-color: {C_BG};
                selection-color: {C_TEXT};
            }}
            """)
        # Outer layout of the popup frame
        outer_l = QVBoxLayout(panel)
        outer_l.setContentsMargins(0, 0, 0, 0)
        
        # Scroll Area
        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(330)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {C_SURFACE};
                width: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {C_CARD};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C_ACCENT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        
        container = QWidget(scroll)
        container.setObjectName("settings_container")
        container.setStyleSheet("background: transparent; border: none;")
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        theme_title = QLabel("THEME")
        theme_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(theme_title)

        theme_box = QFrame()
        theme_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        theme_layout = QHBoxLayout(theme_box)
        theme_layout.setContentsMargins(10, 8, 10, 8)
        theme_layout.setSpacing(8)
        theme_label = QLabel("Active Mode")
        theme_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        theme_layout.addWidget(theme_label, 1)

        saved_theme = self._data.get("_theme", "classic")
        self._current_theme = normalize_theme(saved_theme)
        
        from PyQt5.QtWidgets import QComboBox
        self._btn_theme = QComboBox()
        self._btn_theme.addItems(["📚 CLASSIC MODE", "🐢 TMNT MODE", "🎮 MANHATTAN", "🔮 ARCANUM"])
        self._btn_theme.setCursor(Qt.PointingHandCursor)
        self._btn_theme.setObjectName("font_btn")
        
        _theme_to_idx = {"classic": 0, "tmnt": 1, "manhattan": 2, "arcanum": 3}
        self._btn_theme.setCurrentIndex(_theme_to_idx.get(self._current_theme, 0))
        self._btn_theme.currentIndexChanged.connect(self._toggle_theme)
        theme_layout.addWidget(self._btn_theme, 0, Qt.AlignRight)
        layout.addWidget(theme_box)

        audio_title = QLabel("VOLUME CONTROL")
        audio_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(audio_title)

        audio_box = QFrame()
        audio_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        audio_layout = QHBoxLayout(audio_box)
        audio_layout.setContentsMargins(10, 8, 10, 8)
        audio_layout.setSpacing(8)
        
        vol_label = QLabel("Sound Output Volume")
        vol_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        audio_layout.addWidget(vol_label, 1)

        self._classic_volume_slider = QSlider(Qt.Horizontal)
        self._classic_volume_slider.setRange(0, 100)
        self._classic_volume_slider.setValue(self._data.get("_volume", 40))
        self._classic_volume_slider.setFixedWidth(80)
        self._classic_volume_slider.setCursor(Qt.PointingHandCursor)
        self._classic_volume_slider.setStyleSheet(f"""
            QSlider {{
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background: rgba(124, 106, 247, 0.2);
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {C_ACCENT};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #BD93F9;
                width: 10px;
                height: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }}
        """)
        self._classic_volume_slider.valueChanged.connect(self._on_classic_volume_changed)

        btn_dec = QPushButton("−")
        btn_dec.setFixedWidth(24)
        btn_dec.setFixedHeight(24)
        btn_dec.setCursor(Qt.PointingHandCursor)
        btn_dec.clicked.connect(self._dec_classic_volume)

        btn_inc = QPushButton("＋")
        btn_inc.setFixedWidth(24)
        btn_inc.setFixedHeight(24)
        btn_inc.setCursor(Qt.PointingHandCursor)
        btn_inc.clicked.connect(self._inc_classic_volume)

        audio_layout.addWidget(btn_dec)
        audio_layout.addWidget(self._classic_volume_slider)
        audio_layout.addWidget(btn_inc)
        layout.addWidget(audio_box)

        scroll_title = QLabel("SCROLL SPEED")
        scroll_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(scroll_title)

        scroll_box = QFrame()
        scroll_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        scroll_layout = QHBoxLayout(scroll_box)
        scroll_layout.setContentsMargins(10, 8, 10, 8)
        scroll_layout.setSpacing(8)
        
        scroll_label = QLabel("Mouse Sensitivity")
        scroll_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        scroll_layout.addWidget(scroll_label)

        current_scroll = int(self._data.get("_scroll_speed", 35))
        self._classic_scroll_val_lbl = QLabel(f"{current_scroll}%")
        self._classic_scroll_val_lbl.setStyleSheet(f"color:{C_ACCENT};font-size:12px;font-weight:bold;")
        scroll_layout.addWidget(self._classic_scroll_val_lbl)
        scroll_layout.addStretch()

        self._classic_scroll_slider = QSlider(Qt.Horizontal)
        self._classic_scroll_slider.setRange(10, 100)
        self._classic_scroll_slider.setSingleStep(5)
        self._classic_scroll_slider.setValue(current_scroll)
        self._classic_scroll_slider.setFixedWidth(80)
        self._classic_scroll_slider.setCursor(Qt.PointingHandCursor)
        self._classic_scroll_slider.setStyleSheet(f"""
            QSlider {{
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background: rgba(124, 106, 247, 0.2);
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {C_ACCENT};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #BD93F9;
                width: 10px;
                height: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }}
        """)
        self._classic_scroll_slider.valueChanged.connect(self._on_classic_scroll_speed_changed)

        btn_scroll_dec = QPushButton("−")
        btn_scroll_dec.setFixedWidth(24)
        btn_scroll_dec.setFixedHeight(24)
        btn_scroll_dec.setCursor(Qt.PointingHandCursor)
        btn_scroll_dec.clicked.connect(self._dec_classic_scroll_speed)

        btn_scroll_inc = QPushButton("＋")
        btn_scroll_inc.setFixedWidth(24)
        btn_scroll_inc.setFixedHeight(24)
        btn_scroll_inc.setCursor(Qt.PointingHandCursor)
        btn_scroll_inc.clicked.connect(self._inc_classic_scroll_speed)

        scroll_layout.addWidget(btn_scroll_dec)
        scroll_layout.addWidget(self._classic_scroll_slider)
        scroll_layout.addWidget(btn_scroll_inc)
        layout.addWidget(scroll_box)

        scale_title = QLabel("VISUAL SCALE")
        scale_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(scale_title)

        scale_box = QFrame()
        scale_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        scale_layout = QHBoxLayout(scale_box)
        scale_layout.setContentsMargins(10, 8, 10, 8)
        scale_layout.setSpacing(8)
        scale_label = QLabel("Size")
        scale_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        scale_layout.addWidget(scale_label)
        scale_layout.addStretch()
        scale_layout.addWidget(self._classic_font_button("A−", -1))
        scale_layout.addWidget(self._classic_font_button("A", 0))
        scale_layout.addWidget(self._classic_font_button("A+", +1))
        layout.addWidget(scale_box)

        contrast_title = QLabel("PDF CONTRAST")
        contrast_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(contrast_title)

        contrast_box = QFrame()
        contrast_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        contrast_layout = QHBoxLayout(contrast_box)
        contrast_layout.setContentsMargins(10, 8, 10, 8)
        contrast_layout.setSpacing(8)
        contrast_label = QLabel("Dark Colors / Inverted PDF")
        contrast_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        contrast_layout.addWidget(contrast_label, 1)

        from PyQt5.QtWidgets import QCheckBox
        self._cb_invert_pdf = QCheckBox()
        self._cb_invert_pdf.setCursor(Qt.PointingHandCursor)
        self._cb_invert_pdf.setChecked(store.get().get("_invert_pdf", False))
        self._cb_invert_pdf.stateChanged.connect(self._on_classic_contrast_changed)
        contrast_layout.addWidget(self._cb_invert_pdf, 0, Qt.AlignRight)
        layout.addWidget(contrast_box)

        window_title = QLabel("WINDOW MODE")
        window_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(window_title)

        window_box = QFrame()
        window_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        window_layout = QHBoxLayout(window_box)
        window_layout.setContentsMargins(10, 8, 10, 8)
        window_layout.setSpacing(8)
        window_label = QLabel("Keep open in Fullscreen")
        window_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        window_layout.addWidget(window_label, 1)

        self._cb_keep_fullscreen = QCheckBox()
        self._cb_keep_fullscreen.setCursor(Qt.PointingHandCursor)
        self._cb_keep_fullscreen.setChecked(self._data.get("_keep_fullscreen", False))
        self._cb_keep_fullscreen.stateChanged.connect(self._on_classic_fullscreen_changed)
        window_layout.addWidget(self._cb_keep_fullscreen, 0, Qt.AlignRight)
        layout.addWidget(window_box)

        # Pen Performance Selector (Beta)
        pen_perf_title = QLabel("PEN PERFORMANCE (BETA)")
        pen_perf_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(pen_perf_title)

        pen_perf_box = QFrame()
        pen_perf_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        pen_perf_layout = QHBoxLayout(pen_perf_box)
        pen_perf_layout.setContentsMargins(10, 8, 10, 8)
        pen_perf_layout.setSpacing(8)
        
        pen_perf_label = QLabel("Pen Mode")
        pen_perf_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        pen_perf_layout.addWidget(pen_perf_label, 1)

        from PyQt5.QtCore import QSettings
        settings = QSettings("AnkiOcclusion", "App")
        saved_impl = settings.value("review/pen_implementation", "filtered")

        from PyQt5.QtWidgets import QComboBox
        self._btn_pen_perf = QComboBox()
        self._btn_pen_perf.addItems([
            "Classic Smooth",
            "Incremental Bezier",
            "Raw Polyline",
            "Distance-Filtered"
        ])
        self._btn_pen_perf.setCursor(Qt.PointingHandCursor)
        self._btn_pen_perf.setObjectName("font_btn")
        
        _impl_to_idx = {"classic": 0, "incremental": 1, "polyline": 2, "filtered": 3}
        self._btn_pen_perf.setCurrentIndex(_impl_to_idx.get(saved_impl, 3))
        self._btn_pen_perf.currentIndexChanged.connect(self._on_classic_pen_perf_changed)
        pen_perf_layout.addWidget(self._btn_pen_perf, 0, Qt.AlignRight)
        layout.addWidget(pen_perf_box)

        archive_title = QLabel("MISSION ARCHIVE")
        archive_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(archive_title)

        archive_box = QFrame()
        archive_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        archive_layout = QHBoxLayout(archive_box)
        archive_layout.setContentsMargins(10, 8, 10, 8)
        archive_layout.setSpacing(8)
        archive_icon = QLabel("Folder")
        archive_icon.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        archive_layout.addWidget(archive_icon)
        self._classic_archive_value = QLabel()
        self._classic_archive_value.setStyleSheet(
            f"color:{C_TEXT};font-size:12px;font-weight:bold;"
        )
        archive_layout.addWidget(self._classic_archive_value, 1)
        self._classic_archive_btn = QPushButton("SET")
        self._classic_archive_btn.setCursor(Qt.PointingHandCursor)
        self._classic_archive_btn.setObjectName("font_btn")
        self._classic_archive_btn.setToolTip("Choose Mission Archive folder")
        self._classic_archive_btn.clicked.connect(self._choose_classic_mission_archive)
        archive_layout.addWidget(self._classic_archive_btn, 0, Qt.AlignRight)
        self._classic_archive_box = archive_box
        layout.addWidget(archive_box)

        recovery_title = QLabel("RECOVERY")
        recovery_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(recovery_title)

        recovery_box = QFrame()
        recovery_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        recovery_layout = QHBoxLayout(recovery_box)
        recovery_layout.setContentsMargins(10, 8, 10, 8)
        recovery_layout.setSpacing(8)
        recovery_label = QLabel("Drafts and review checkpoints")
        recovery_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        recovery_layout.addWidget(recovery_label, 1)
        self._classic_recovery_btn = QPushButton("OPEN")
        self._classic_recovery_btn.setCursor(Qt.PointingHandCursor)
        self._classic_recovery_btn.setObjectName("font_btn")
        self._classic_recovery_btn.clicked.connect(
            lambda: self.show_recovery_center(startup=False)
        )
        recovery_layout.addWidget(self._classic_recovery_btn, 0, Qt.AlignRight)
        layout.addWidget(recovery_box)

        # Google Drive Backup Section
        gdrive_title = QLabel("GOOGLE DRIVE SYNC")
        gdrive_title.setStyleSheet(
            f"color:{C_ACCENT};font-weight:bold;font-size:11px;letter-spacing:1px;"
        )
        layout.addWidget(gdrive_title)

        gdrive_box = QFrame()
        gdrive_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        gdrive_layout = QHBoxLayout(gdrive_box)
        gdrive_layout.setContentsMargins(10, 8, 10, 8)
        gdrive_layout.setSpacing(8)
        
        self._gdrive_status_lbl = QLabel("Checking status...")
        self._gdrive_status_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        gdrive_layout.addWidget(self._gdrive_status_lbl, 1)
        
        self._gdrive_sync_btn = QPushButton("SYNC")
        self._gdrive_sync_btn.setCursor(Qt.PointingHandCursor)
        self._gdrive_sync_btn.setObjectName("font_btn")
        self._gdrive_sync_btn.clicked.connect(self._manual_gdrive_sync)
        gdrive_layout.addWidget(self._gdrive_sync_btn, 0, Qt.AlignRight)

        self._gdrive_link_btn = QPushButton("LINK")
        self._gdrive_link_btn.setCursor(Qt.PointingHandCursor)
        self._gdrive_link_btn.setObjectName("font_btn")
        self._gdrive_link_btn.clicked.connect(self._toggle_gdrive_link)
        gdrive_layout.addWidget(self._gdrive_link_btn, 0, Qt.AlignRight)
        
        layout.addWidget(gdrive_box)

        # Cloud Asset Utilities
        assets_lbl = QLabel("CLOUD ASSET UTILITIES")
        assets_lbl.setStyleSheet(
            f"color:{C_SUBTEXT};font-weight:bold;font-size:10px;margin-top:10px;"
        )
        layout.addWidget(assets_lbl)

        assets_box = QFrame()
        assets_box.setStyleSheet(
            f"background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
        )
        assets_layout = QHBoxLayout(assets_box)
        assets_layout.setContentsMargins(10, 8, 10, 8)
        assets_layout.setSpacing(8)

        self._assets_backup_btn = QPushButton("BACKUP ASSETS")
        self._assets_backup_btn.setCursor(Qt.PointingHandCursor)
        self._assets_backup_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {p_card};
                color: {p_green};
                border: 1px solid {p_border};
                border-radius: 6px;
                padding: 5px 10px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {_hex_to_rgba(p_green, 0.12)};
                color: {p_text};
                border-color: {p_green};
            }}
            """
        )
        self._assets_backup_btn.clicked.connect(self._backup_assets_to_cloud)
        assets_layout.addWidget(self._assets_backup_btn, 0)

        self._assets_restore_btn = QPushButton("RESTORE ASSETS")
        self._assets_restore_btn.setCursor(Qt.PointingHandCursor)
        self._assets_restore_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {p_card};
                color: {p_accent};
                border: 1px solid {p_border};
                border-radius: 6px;
                padding: 5px 10px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {_hex_to_rgba(p_accent, 0.12)};
                color: {p_text};
                border-color: {p_accent};
            }}
            """
        )
        self._assets_restore_btn.clicked.connect(self._sync_assets_from_cloud)
        assets_layout.addWidget(self._assets_restore_btn, 0)

        self._assets_prune_btn = QPushButton("PRUNE CLOUD")
        self._assets_prune_btn.setCursor(Qt.PointingHandCursor)
        self._assets_prune_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {p_card};
                color: {p_red};
                border: 1px solid {p_border};
                border-radius: 6px;
                padding: 5px 10px;
                font-family: 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {_hex_to_rgba(p_red, 0.12)};
                color: {p_text};
                border-color: {p_red};
            }}
            """
        )
        self._assets_prune_btn.clicked.connect(self._prune_cloud_assets)
        assets_layout.addWidget(self._assets_prune_btn, 0)

        layout.addWidget(assets_box)

        scroll.setWidget(container)
        outer_l.addWidget(scroll)
        
        # Save references to prevent garbage collection and allow dynamic resizing
        panel._scroll = scroll
        panel._container = container
        
        self._refresh_classic_archive_display()
        self._refresh_gdrive_display()
        panel.adjustSize()
        return panel

    def _classic_font_button(self, text, direction):
        button = QPushButton(text)
        button.setObjectName("font_btn")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedWidth(34)
        button.clicked.connect(lambda _, d=direction: self._on_classic_font_clicked(d))
        return button

    def _on_classic_font_clicked(self, direction):
        self._emit_font(direction)

    def _on_classic_contrast_changed(self, state):
        invert = (state == Qt.Checked)
        store.get()["_invert_pdf"] = invert
        store.mark_dirty()

    def _on_classic_fullscreen_changed(self, state):
        keep = (state == Qt.Checked)
        self._data["_keep_fullscreen"] = keep
        store.mark_dirty()
        win = self.window()
        if win:
            if keep:
                win.showFullScreen()
            else:
                win.showMaximized()

    def _on_classic_pen_perf_changed(self, idx):
        _idx_to_impl = {0: "classic", 1: "incremental", 2: "polyline", 3: "filtered"}
        impl = _idx_to_impl.get(idx, "classic")
        from PyQt5.QtCore import QSettings
        QSettings("AnkiOcclusion", "App").setValue("review/pen_implementation", impl)

    def _refresh_classic_archive_display(self):
        if self._classic_archive_value is None:
            return
        label = archive_label()
        tooltip = archive_tooltip()
        self._classic_archive_value.setText(label)
        self._classic_archive_value.setToolTip(tooltip)
        if self._classic_archive_box is not None:
            self._classic_archive_box.setToolTip(tooltip)
        if self._classic_archive_btn is not None:
            self._classic_archive_btn.setToolTip(tooltip)

    def _toggle_classic_settings_panel(self):
        panel = self._classic_settings_panel
        if panel is None or self._btn_settings is None:
            return
        if panel.isVisible():
            panel.hide()
            return
        if hasattr(self, "_cb_invert_pdf") and self._cb_invert_pdf:
            self._cb_invert_pdf.blockSignals(True)
            self._cb_invert_pdf.setChecked(store.get().get("_invert_pdf", False))
            self._cb_invert_pdf.blockSignals(False)
        if hasattr(self, "_cb_keep_fullscreen") and self._cb_keep_fullscreen:
            self._cb_keep_fullscreen.blockSignals(True)
            self._cb_keep_fullscreen.setChecked(self._data.get("_keep_fullscreen", False))
            self._cb_keep_fullscreen.blockSignals(False)
        if hasattr(self, "_classic_volume_slider") and self._classic_volume_slider:
            self._classic_volume_slider.blockSignals(True)
            self._classic_volume_slider.setValue(self._data.get("_volume", 40))
            self._classic_volume_slider.blockSignals(False)
        if hasattr(self, "_classic_scroll_slider") and self._classic_scroll_slider:
            self._classic_scroll_slider.blockSignals(True)
            s_val = int(self._data.get("_scroll_speed", 35))
            self._classic_scroll_slider.setValue(s_val)
            if hasattr(self, "_classic_scroll_val_lbl") and self._classic_scroll_val_lbl:
                self._classic_scroll_val_lbl.setText(f"{s_val}%")
            self._classic_scroll_slider.blockSignals(False)
        if hasattr(self, "_btn_pen_perf") and self._btn_pen_perf:
            self._btn_pen_perf.blockSignals(True)
            from PyQt5.QtCore import QSettings
            saved_impl = QSettings("AnkiOcclusion", "App").value("review/pen_implementation", "filtered")
            _impl_to_idx = {"classic": 0, "incremental": 1, "polyline": 2, "filtered": 3}
            self._btn_pen_perf.setCurrentIndex(_impl_to_idx.get(saved_impl, 3))
            self._btn_pen_perf.blockSignals(False)
        self._refresh_classic_archive_display()
        self._refresh_gdrive_display()
        # Reset constraints first to get true size hint
        panel.setMinimumHeight(0)
        panel.setMaximumHeight(16777215)
        panel.adjustSize()
        
        pos = self._btn_settings.mapToGlobal(QPoint(0, self._btn_settings.height() + 6))
        
        # Constrain height to fit available screen space
        screen = QApplication.primaryScreen()
        if screen:
            screen_geom = screen.availableGeometry()
            max_allowed_h = screen_geom.bottom() - pos.y() - 12
            if panel.height() > max_allowed_h:
                panel.setFixedHeight(max_allowed_h)
                
        panel.move(pos)
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def _on_classic_volume_changed(self, value):
        self.music_widget.set_volume(value)

    def _dec_classic_volume(self):
        val = max(0, self._data.get("_volume", 40) - 10)
        self._classic_volume_slider.setValue(val)

    def _inc_classic_volume(self):
        val = min(100, self._data.get("_volume", 40) + 10)
        self._classic_volume_slider.setValue(val)

    def _on_classic_scroll_speed_changed(self, value):
        self._data["_scroll_speed"] = value
        if hasattr(self, "_classic_scroll_val_lbl") and self._classic_scroll_val_lbl:
            self._classic_scroll_val_lbl.setText(f"{value}%")
        from data_manager import store
        store.mark_dirty()

    def _dec_classic_scroll_speed(self):
        val = max(10, self._data.get("_scroll_speed", 35) - 5)
        self._classic_scroll_slider.setValue(val)

    def _inc_classic_scroll_speed(self):
        val = min(100, self._data.get("_scroll_speed", 35) + 5)
        self._classic_scroll_slider.setValue(val)

    def _choose_classic_mission_archive(self):
        if self._classic_settings_panel is not None:
            self._classic_settings_panel.hide()
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
        self._refresh_classic_archive_display()
        self.refresh()
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

    def rebuild_tmnt_layout(self, force=False):
        if self._tmnt_layout is None and force:
            self._ensure_tmnt_layout()
        if self._tmnt_layout is None:
            return
        current = self._body_stack.currentWidget()
        was_visible = current is self._tmnt_layout
        if not force and not was_visible:
            return

        selected = self._tmnt_layout.get_selected_deck()
        selected_id = selected.get("_id") if selected else None
        old = self._tmnt_layout
        old_index = self._body_stack.indexOf(old)
        self._tmnt_layout = self._create_tmnt_layout()
        if hasattr(self._tmnt_layout, "main"):
            self._tmnt_layout.main._font_size_val = int(
                self._data.get("_font_size", BASE_FONT_SIZE)
            )
        self._body_stack.insertWidget(
            old_index if old_index >= 0 else 1, self._tmnt_layout
        )
        if was_visible:
            self._body_stack.setCurrentWidget(self._tmnt_layout)
        self._body_stack.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        if selected_id:
            self._tmnt_layout.select_deck_by_id(selected_id)
        else:
            self._tmnt_layout.refresh()

    def _toggle_tmnt_bgm(self):
        self.music_widget.toggle()
        if self._tmnt_layout:
            self._tmnt_layout.set_bgm_state(self.music_widget._playing)

    def _toggle_theme(self, index=None):
        t0 = time.perf_counter()
        from theme_manager import build_stylesheet, normalize_theme, is_retro_theme
        from PyQt5.QtGui import QFont

        if isinstance(index, int) and not isinstance(index, bool):
            _idx_to_theme = {0: "classic", 1: "tmnt", 2: "manhattan", 3: "arcanum"}
            self._current_theme = normalize_theme(_idx_to_theme.get(index, "classic"))
        else:
            _cycle = {
                "classic": "tmnt",
                "tmnt": "manhattan",
                "manhattan": "arcanum",
                "arcanum": "classic",
            }
            self._current_theme = normalize_theme(
                _cycle.get(self._current_theme, "classic")
            )
        
        self._data["_theme"] = self._current_theme
        store.mark_dirty()
        from theme_manager import get_palette
        self._p = get_palette(self._current_theme)

        # Synchronize classic dropdown state if it exists
        _theme_to_idx = {"classic": 0, "tmnt": 1, "manhattan": 2, "arcanum": 3}
        idx = _theme_to_idx.get(self._current_theme, 0)
        from PyQt5.QtWidgets import QComboBox
        if hasattr(self, "_btn_theme") and isinstance(self._btn_theme, QComboBox):
            self._btn_theme.blockSignals(True)
            self._btn_theme.setCurrentIndex(idx)
            self._btn_theme.blockSignals(False)

        app = QApplication.instance()
        win = self.window()
        current_size = self._data.get("_font_size", BASE_FONT_SIZE)

        if is_retro_theme(self._current_theme) and self._ensure_tmnt_layout():
            # ── Swap to TMNT/Manhattan full layout ────────────────────────────
            if (
                self._classic_settings_panel is not None
                and self._classic_settings_panel.isVisible()
            ):
                self._classic_settings_panel.hide()
            self.top_frame.hide()
            win_sb = self.window().statusBar() if self.window() else None
            if win_sb:
                win_sb.hide()

            if app:
                app._active_theme = self._current_theme
                if self._current_theme == "manhattan":
                    font_name = "Courier New"
                elif self._current_theme == "arcanum":
                    font_name = "Cinzel"
                else:
                    font_name = "Roboto Mono"
                app.setFont(QFont(font_name, current_size))
                ss = build_stylesheet(self._current_theme, current_size)
                app.setStyleSheet(ss)
                if win:
                    win.setStyleSheet(ss)

            # Rebuild the layout to apply updated styles and dynamic palette values instantly!
            self.rebuild_tmnt_layout(force=True)
            self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            self._body_stack.setCurrentWidget(self._tmnt_layout)
        else:
            # ── Swap back to splitter (classic; Ninja/Dojo is disabled) ─────
            self._ensure_classic_layout()
            self.top_frame.show()
            win_sb = self.window().statusBar() if self.window() else None
            if win_sb:
                win_sb.show()
            self._body_stack.setCurrentWidget(self._splitter_widget)
            if self.deck_tree is not None:
                self.deck_tree.set_theme(self._current_theme)
            if self.deck_view is not None:
                self.deck_view.set_theme(self._current_theme)
            self.music_widget.set_theme(self._current_theme)
            if self._cache_widget is not None:
                self._cache_widget.set_theme(self._current_theme)
            self._apply_topbar_style()
            self._refresh_classic_archive_display()
            if app:
                app._active_theme = self._current_theme
                app.setFont(QFont("Segoe UI", current_size))
                app.setStyleSheet(_build_ss(current_size))
                if win:
                    win.setStyleSheet("")
        print(f"[PROFILE][home_theme_toggle] Switched theme to '{self._current_theme}' in {(time.perf_counter() - t0) * 1000:.1f}ms")

    def _emit_font(self, direction: int):
        win = self.window()
        if hasattr(win, "change_font_size"):
            win.change_font_size(direction)

    def _open_card_browser(self):
        if getattr(self, "_active_review", None) is not None:
            return
        # If TMNT layout is active
        if getattr(self, "_tmnt_layout", None) and self._tmnt_layout.isVisible():
            if hasattr(self._tmnt_layout, "main") and self._tmnt_layout.main:
                if getattr(self._tmnt_layout.main, "deck", None):
                    self._tmnt_layout.main._open_card_browser()
                    return
                if hasattr(self._tmnt_layout, "sidebar") and getattr(self._tmnt_layout.sidebar, "_selected_deck", None):
                    self._tmnt_layout.main.load_deck(self._tmnt_layout.sidebar._selected_deck)
                    self._tmnt_layout.main._open_card_browser()
                    return
                self._tmnt_layout.main._open_card_browser()
                return
        # Classic layout
        dv = getattr(self, "deck_view", None) or getattr(self, "_deck_view", None)
        if dv:
            if getattr(dv, "deck", None):
                dv._open_card_browser()
                return
            dt = getattr(self, "deck_tree", None) or getattr(self, "_deck_tree", None)
            if dt and getattr(dt, "_selected_deck", None):
                dv.load_deck(dt._selected_deck)
                dv._open_card_browser()
                return
            dv._open_card_browser()

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        if shortcut_manager.event_matches(e, "home.browse_cards"):
            if getattr(self, "_active_review", None) is None:
                self._open_card_browser()
                e.accept()
                return
        if shortcut_manager.event_matches(e, "home.search_decks") or (ctrl and not shift and key in (Qt.Key_F, Qt.Key_K)):
            if getattr(self, "_active_review", None) is None:
                if getattr(self, "_tmnt_layout", None) and hasattr(self._tmnt_layout, "sidebar") and hasattr(self._tmnt_layout.sidebar, "_focus_search"):
                    self._tmnt_layout.sidebar._focus_search()
                    e.accept()
                    return
                dt = getattr(self, "deck_tree", None) or getattr(self, "_deck_tree", None)
                if dt and hasattr(dt, "_focus_search"):
                    dt._focus_search()
                    e.accept()
                    return

        if shortcut_manager.event_matches(e, "home.resume_review"):
            if getattr(self, "_active_review", None) is None:
                fw = self.focusWidget()
                from PyQt5.QtWidgets import QLineEdit, QTextEdit
                if not (fw and isinstance(fw, (QLineEdit, QTextEdit))):
                    self.resume_last_review()
                    e.accept()
                    return

        if shortcut_manager.event_matches(e, "home.mission_report") or (ctrl and not shift and key == Qt.Key_R):
            if getattr(self, "_report_widget", None) is not None:
                self._hide_mission_report()
            else:
                self._show_mission_report()
            e.accept()
            return

        if shortcut_manager.event_matches(e, "home.save"):
            store.mark_dirty()
            store.save_force(async_save=True)
            if hasattr(self, "canvas"):
                self.canvas._show_toast("💾 Manual Save")
            print("[HomeScreen][key] Ctrl+S — manual save triggered")
            e.accept()
            return

        is_home_redo = shortcut_manager.event_matches(e, "home.redo") or (
            ctrl and shift and key == Qt.Key_Z
        )
        if shortcut_manager.event_matches(e, "home.undo") or is_home_redo:
            if getattr(self, "_active_review", None) is None:
                if is_home_redo:
                    # Ctrl+Shift+Z → deck redo
                    ok = deck_history.redo(store)
                    if ok and self.deck_tree is not None:
                        self.deck_tree.refresh()
                        (
                            self.canvas._show_toast("↪ Deck redo")
                            if hasattr(self, "canvas")
                            else None
                        )
                    print(f"[HomeScreen][key] Ctrl+Shift+Z — deck redo, ok={ok}")
                else:
                    # Ctrl+Z → try deck undo first, else mask undo
                    ok = deck_history.undo(store)
                    if ok:
                        # deck_tree ka sahi attribute name use karo
                        dt = getattr(self, "deck_tree", None) or getattr(
                            self, "_deck_tree", None
                        )
                        if dt:
                            dt._data = store.get()  # ← data bhi sync karo
                            dt.refresh()
                            print("[HomeScreen][key] Ctrl+Z — deck_tree refreshed ✅")
                        else:
                            print("[HomeScreen][key] ⚠ deck_tree attribute nahi mila")
                        print("[HomeScreen][key] Ctrl+Z — deck undo done")
                    else:
                        if self.deck_view is not None:
                            self.deck_view.undo()
                        print("[HomeScreen][key] Ctrl+Z — fell through to mask undo")
                e.accept()
                return
        elif shortcut_manager.event_matches(e, "home.music_toggle"):
            self.music_widget.toggle()
            if self._tmnt_layout:
                self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "home.music_next"):
            self.music_widget.next_track()
            if self._tmnt_layout:
                self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "home.edit_card"):
            if getattr(self, "_active_review", None) is None:
                dv = getattr(self, "deck_view", None) or getattr(self, "_deck_view", None)
                if dv and dv.isVisible():
                    item = dv.card_list.currentItem()
                    if item:
                        dv._edit_card(item)
                        e.accept()
                        return
        elif shortcut_manager.event_matches(e, "home.add_card") or (key == Qt.Key_A and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))):
            fw = self.focusWidget()
            from PyQt5.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit
            if not (fw and isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit))):
                if getattr(self, "_active_review", None) is None:
                    from ui.review.annotation_handler import open_annotation_for_deck
                    dv = getattr(self, "deck_view", None) or getattr(self, "_deck_view", None)
                    target = None
                    if dv and dv.isVisible():
                        item = dv.card_list.currentItem()
                        if item:
                            target = item.data(Qt.UserRole)
                        if not target:
                            target = getattr(dv, "deck", None)
                    if not target:
                        dt = getattr(self, "deck_tree", None) or getattr(self, "_deck_tree", None)
                        if dt:
                            target = getattr(dt, "_selected_deck", None)
                    if target:
                        ok = open_annotation_for_deck(target, self)
                        if ok:
                            e.accept()
                            return

        super().keyPressEvent(e)  # ← yeh already hai, sirf usse pehle add karo

    def closeEvent(self, e):
        active_editor = getattr(self, "_active_editor", None)
        if active_editor is not None:
            active_editor.close()
            self._active_editor = None
        super().closeEvent(e)

    def _apply_topbar_style(self):
        """Apply top bar styling based on current theme."""
        self.mentor.set_style(self._current_theme)
        if self._current_theme == "dojo":
            # Ninja Mode Style
            self.top_frame.setStyleSheet(f"""
                QFrame#topbar {{
                    background: #0F0F17;
                    border-bottom: 1px solid #1A1A26;
                }}
                QLabel#logo_box {{
                    border: 2.5px solid #72FF4F;
                    border-radius: 8px;
                    color: #72FF4F;
                    font-family: '{NARUTO_FONT_FAMILY}';
                    font-weight: bold;
                    font-size: 26px;
                }}
                QLabel#logo_text {{
                    font-family: '{NARUTO_FONT_FAMILY}';
                    font-weight: 900;
                    font-size: 20px;
                    color: #72FF4F;
                    letter-spacing: 3px;
                }}
                QPushButton#nav_btn {{
                    background: transparent;
                    color: #5F627D;
                    border: none;
                    border-bottom: 2px solid transparent;
                    font-family: 'Orbitron';
                    font-size: 14px;
                    font-weight: 900;
                    padding: 8px 18px;
                    letter-spacing: 1px;
                }}
                QPushButton#nav_btn:hover {{
                    color: #72FF4F;
                    border-bottom: 3px solid #72FF4F;
                    background: rgba(114, 255, 79, 0.08);
                }}
                QPushButton#font_btn {{
                    background: #14141F;
                    color: #5F627D;
                    border: 1px solid #1A1A26;
                    border-radius: 4px;
                    font-family: 'Segoe UI';
                    font-size: 11px;
                    font-weight: bold;
                    padding: 0px;
                    letter-spacing: 0px;
                    text-transform: none;
                }}
                QPushButton#font_btn:hover {{
                    background: #1E1E2E;
                    color: #E0E0FF;
                    border: 1px solid #72FF4F;
                }}
            """)
        else:
            # Classic Mode Style
            self.top_frame.setStyleSheet(f"""
                QFrame#topbar {{
                    background: {C_SURFACE};
                    border-bottom: 1px solid {C_BORDER};
                }}
                QLabel#logo_box {{
                    border: 2px solid {C_ACCENT};
                    border-radius: 6px;
                    color: {C_ACCENT};
                    font-family: 'Segoe UI';
                    font-weight: bold;
                    font-size: 20px;
                }}
                QLabel#logo_text {{
                    font-family: 'Segoe UI';
                    font-weight: bold;
                    font-size: 18px;
                    color: {C_TEXT};
                }}
                QLabel#logo_sub {{
                    font-family: 'Segoe UI';
                    font-size: 12px;
                    color: {C_SUBTEXT};
                }}
                QPushButton#nav_btn {{
                    background: transparent;
                    color: {C_SUBTEXT};
                    border: 1px solid {C_BORDER};
                    border-radius: 6px;
                    font-family: 'Segoe UI';
                    font-size: 13px;
                    font-weight: bold;
                    padding: 6px 16px;
                }}
                QPushButton#nav_btn:hover {{
                    background: {C_CARD};
                    color: {C_TEXT};
                    border: 1px solid {C_ACCENT};
                }}
                QPushButton#font_btn {{
                    background: transparent;
                    color: {C_SUBTEXT};
                    border: 1px solid {C_BORDER};
                    border-radius: 6px;
                    font-family: 'Segoe UI';
                    font-size: 12px;
                    font-weight: bold;
                    padding: 0px;
                    letter-spacing: 0px;
                    text-transform: none;
                }}
                QPushButton#font_btn:hover {{
                    background: {C_CARD};
                    color: {C_TEXT};
                }}
            """)

    def show_recovery_center(self, startup=False):
        if self._classic_settings_panel is not None:
            self._classic_settings_panel.hide()
        if self._tmnt_layout is not None and hasattr(self._tmnt_layout, "topbar"):
            topbar = self._tmnt_layout.topbar
            if topbar is not None:
                if hasattr(topbar, "_settings_panel") and topbar._settings_panel is not None:
                    topbar._settings_panel.hide()
                if hasattr(topbar, "_more_panel") and topbar._more_panel is not None:
                    topbar._more_panel.hide()

        if startup and not is_running_tests():
            # Run startup scan asynchronously to prevent UI freeze
            self._recovery_thread = RecoveryScanThread(store.get(), startup=True, parent=self)
            self._recovery_thread.finished_scan.connect(self._on_startup_scan_completed)
            self._recovery_thread.start()
            return True
        else:
            t0 = time.perf_counter()
            summary = recovery_manager.scan_recovery(store.get(), startup=startup)
            print(f"[PROFILE][home_recovery_scan] Scanned recovery directory in {(time.perf_counter() - t0) * 1000:.1f}ms (startup={startup})")
            return self._process_recovery_summary(summary, startup=startup)

    def _on_startup_scan_completed(self, summary):
        self._recovery_thread = None
        self._process_recovery_summary(summary, startup=True)

    def _process_recovery_summary(self, summary, startup):
        has_drafts = bool(summary.get("drafts"))
        has_events = bool(summary.get("review_events"))
        if startup and has_events:
            print(
                "[DEBUG][recovery] startup_auto_review_recover_start "
                f"events={len(summary.get('review_events', []))}"
            )
            result = recovery_manager.apply_pending_review_events(store.get())
            if result.get("applied", 0) > 0:
                store.mark_dirty()
                store.save_force(async_save=True)
            print(
                "[DEBUG][recovery] startup_auto_review_recover "
                f"applied={result.get('applied', 0)} "
                f"already={result.get('already_applied', 0)} "
                f"blocked={len(result.get('blocked', []))}"
            )
            summary = recovery_manager.scan_recovery(store.get(), startup=startup)
            has_drafts = bool(summary.get("drafts"))
            has_events = bool(summary.get("review_events"))

        if startup:
            # Silent startup: only show dialog if there are actual un-saved editor drafts waiting to be recovered
            if not has_drafts:
                return True

        if not has_drafts and not has_events:
            if not startup:
                QMessageBox.information(
                    self, "Recovery", "No recoverable drafts or review checkpoints."
                )
            return False

        try:
            while True:
                dlg = _load_recovery_dialog()(summary, self, startup=startup)
                dlg.exec_()
                action = getattr(dlg, "action", "close")
                if action == "recover_reviews":
                    result = recovery_manager.apply_pending_review_events(store.get())
                    if result.get("applied", 0) > 0:
                        store.mark_dirty()
                        store.save_force(async_save=True)
                        self.refresh()
                    QMessageBox.information(
                        self,
                        "Recovery",
                        "Review recovery complete.\n"
                        f"Applied: {result.get('applied', 0)}\n"
                        f"Already safe: {result.get('already_applied', 0)}\n"
                        f"Needs attention: {len(result.get('blocked', []))}",
                    )
                elif action == "open_draft":
                    draft = getattr(dlg, "selected_draft", None)
                    if draft:
                        self._open_recovery_draft(draft)
                        return True
                elif action == "delete_draft":
                    draft = getattr(dlg, "selected_draft", None)
                    if draft:
                        recovery_manager.delete_editor_draft(draft.get("draft_id"))
                elif action == "delete_all_drafts":
                    deleted = 0
                    for draft in getattr(dlg, "selected_drafts", []) or []:
                        if recovery_manager.delete_editor_draft(draft.get("draft_id")):
                            deleted += 1
                    QMessageBox.information(
                        self,
                        "Recovery",
                        f"Deleted {deleted} recovery draft(s). Your saved decks were not changed.",
                    )
                else:
                    return True

                summary = recovery_manager.scan_recovery(store.get(), startup=startup)
                if not summary.get("drafts") and not summary.get("review_events"):
                    return True
        finally:
            if not startup:
                self._clear_home_ram_caches()

    def _find_or_create_recovered_drafts_deck(self):
        for deck in self._data.get("decks", []) or []:
            if deck.get("name") == "Recovered Drafts":
                return deck
        deck = {
            "_id": next_deck_id(self._data),
            "name": "Recovered Drafts",
            "cards": [],
            "children": [],
            "created": datetime.now().isoformat(),
        }
        self._data.setdefault("decks", []).append(deck)
        return deck

    def _deck_for_recovery_draft(self, draft):
        deck_info = (draft or {}).get("deck", {}) or {}
        deck = find_deck_by_id(deck_info.get("id"), self._data.get("decks", []))
        return deck or self._find_or_create_recovered_drafts_deck()

    def _target_deck_for_recovered_card(self, parent_deck, card):
        subdeck_name = (card or {}).pop("_auto_subdeck", None)
        if not subdeck_name:
            return parent_deck
        if parent_deck.get("name", "").strip().lower() == subdeck_name.strip().lower():
            return parent_deck
        for child in parent_deck.get("children", []) or []:
            if child.get("name", "").strip().lower() == subdeck_name.strip().lower():
                return child
        child = {
            "_id": next_deck_id(self._data),
            "name": subdeck_name,
            "cards": [],
            "children": [],
            "created": datetime.now().isoformat(),
        }
        parent_deck.setdefault("children", []).append(child)
        return child

    def _open_recovery_draft(self, draft):
        card = recovery_manager.draft_to_card(draft)
        parent_deck = self._deck_for_recovery_draft(draft)
        mode = draft.get("mode", "add")
        original_card = None
        original_deck = None
        original_idx = None
        if mode == "edit":
            original_card, original_deck, original_idx, status = (
                recovery_manager.find_card_by_locator(
                    self._data, draft.get("initial_card_locator", {})
                )
            )
            if status == "ok":
                parent_deck = original_deck

        dlg = _load_card_editor_dialog()(
            self,
            card=card,
            data=self._data,
            deck=parent_deck,
            recovery_draft=draft,
        )
        self._active_editor = dlg
        try:
            if dlg.exec_() != QDialog.Accepted:
                return
            recovered_card = dlg.get_card()
            if original_card is not None and original_deck is not None:
                original_deck.setdefault("cards", [])[original_idx] = recovered_card
            else:
                target_deck = self._target_deck_for_recovered_card(
                    parent_deck, recovered_card
                )
                if recovered_card not in target_deck.setdefault("cards", []):
                    target_deck.setdefault("cards", []).append(recovered_card)
            store.mark_dirty()
            store.save_force(async_save=True)
            dlg.clear_recovery_draft()
            recovery_manager.delete_editor_draft(draft.get("draft_id"))
            self.refresh()
            QMessageBox.information(self, "Recovery", "Recovered draft saved.")
        finally:
            self._active_editor = None

    def refresh(self):
        if self._current_theme == "tmnt" and self._ensure_tmnt_layout():
            self._tmnt_layout.refresh()
        else:
            self._ensure_classic_layout()
            self.deck_tree.refresh()
            sel = self.deck_tree.get_selected_deck()
            if sel:
                self.deck_view.load_deck(sel, self._data)

    def _refresh_gdrive_display(self):
        from services.gdrive_service import gdrive_store
        
        # Refresh classic UI if it exists
        if hasattr(self, "_gdrive_status_lbl") and self._gdrive_status_lbl is not None:
            if gdrive_store.is_linked():
                email = gdrive_store.get_email()
                self._gdrive_status_lbl.setText(f"Linked: {email}")
                self._gdrive_status_lbl.setToolTip(f"Linked to Google Account: {email}")
                self._gdrive_link_btn.setText("UNLINK")
                self._gdrive_sync_btn.setEnabled(True)
            else:
                self._gdrive_status_lbl.setText("Not linked to Google Drive")
                self._gdrive_status_lbl.setToolTip("Google Drive Sync is not connected.")
                self._gdrive_link_btn.setText("LINK")
                self._gdrive_sync_btn.setEnabled(False)

        backup_running = getattr(self, "_backup_in_progress", False)
        restore_running = getattr(self, "_restore_in_progress", False)
        prune_running = getattr(self, "_prune_in_progress", False)

        if hasattr(self, "_assets_backup_btn") and self._assets_backup_btn is not None:
            self._assets_backup_btn.setEnabled(gdrive_store.is_linked() and not backup_running)
        if hasattr(self, "_assets_restore_btn") and self._assets_restore_btn is not None:
            self._assets_restore_btn.setEnabled(gdrive_store.is_linked() and not restore_running)
        if hasattr(self, "_assets_prune_btn") and self._assets_prune_btn is not None:
            self._assets_prune_btn.setEnabled(gdrive_store.is_linked() and not prune_running)

        # Refresh TMNT UI if active
        if hasattr(self, "_tmnt_layout") and self._tmnt_layout is not None:
            if hasattr(self._tmnt_layout, "topbar") and self._tmnt_layout.topbar is not None:
                self._tmnt_layout.topbar._refresh_gdrive_display()

    def _toggle_gdrive_link(self):
        from services.gdrive_service import gdrive_store
        if gdrive_store.is_linked():
            gdrive_store.unlink()
            self._refresh_gdrive_display()
            QMessageBox.information(self, "Unlinked", "Google Drive account has been unlinked.")
            return

        if not gdrive_store.is_configured():
            dialog = GDriveCredentialsDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                client_id = dialog.client_id_input.text().strip()
                client_secret = dialog.client_secret_input.text().strip()
                if client_id and client_secret:
                    gdrive_store.save_config(client_id, client_secret)
                else:
                    QMessageBox.warning(self, "Error", "Both Client ID and Client Secret are required.")
                    return
            else:
                return

        try:
            auth_url, server = gdrive_store.start_oauth_flow()
            from PyQt5.QtGui import QDesktopServices
            from PyQt5.QtCore import QUrl, QTimer
            QDesktopServices.openUrl(QUrl(auth_url))
            
            progress = QMessageBox(self)
            progress.setWindowTitle("Linking Google Drive")
            progress.setText("Please complete authorization in your web browser...")
            progress.setStandardButtons(QMessageBox.Cancel)
            
            timer = QTimer(self)
            def _check_auth():
                if server.auth_code:
                    timer.stop()
                    progress.accept()
                    try:
                        gdrive_store.exchange_code_for_tokens(server.auth_code)
                        self._refresh_gdrive_display()
                        QMessageBox.information(self, "Linked", "Google Drive has been linked successfully!")
                    except Exception as ex:
                        QMessageBox.warning(self, "Error", f"Failed to link account: {ex}")
                elif not progress.isVisible():
                    timer.stop()
            timer.timeout.connect(_check_auth)
            timer.start(500)
            
            progress.exec_()
            timer.stop()
            if not server.auth_code:
                server.running = False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not initiate OAuth login: {e}")

    def _manual_gdrive_sync(self):
        from services.gdrive_service import gdrive_store
        db_path = store._get_db_path()
        
        self._gdrive_status_lbl.setText("Syncing in background...")
        self._gdrive_sync_btn.setEnabled(False)
        
        def _bg():
            success = False
            try:
                success = gdrive_store.upload_file_to_drive(db_path)
                from data_manager import DATA_FILE
                if DATA_FILE.endswith(".json") and os.path.exists(DATA_FILE):
                    gdrive_store.upload_file_to_drive(DATA_FILE)
            except Exception as e:
                print(f"[GDrive Manual Sync] Error: {e}")
            
            def _done():
                self._refresh_gdrive_display()
                if success:
                    _log_success("Database manual sync completed successfully!")
                    ToastNotification(self, "👍 Database synced to Google Drive successfully!")
                else:
                    QMessageBox.warning(self, "Sync Failed", "Could not sync database. Check your internet connection.")
            self.thread_safe_run_signal.emit(_done)
            
        import threading
        threading.Thread(target=_bg, daemon=True, name="GDrive-ManualSync").start()

    def _run_closure(self, func):
        try:
            func()
        except Exception as e:
            print(f"[HomeScreen] Error in thread callback: {e}")

    def _get_active_assets(self):
        from storage_paths import iter_cards, to_archive_relative
        data = self._data
        referenced_pdfs = set()
        referenced_images = set()
        for card in iter_cards(data):
            pdf = card.get("pdf_path")
            if pdf:
                referenced_pdfs.add(to_archive_relative(pdf))
            img = card.get("image_path")
            if img:
                referenced_images.add(to_archive_relative(img))
        return referenced_pdfs, referenced_images

    def _set_assets_button_state(self, action_type, is_running):
        if action_type == "backup":
            self._backup_in_progress = is_running
            btn = getattr(self, "_assets_backup_btn", None)
            text_normal, text_running = "BACKUP ASSETS", "⏳ BACKING UP..."
        elif action_type == "restore":
            self._restore_in_progress = is_running
            btn = getattr(self, "_assets_restore_btn", None)
            text_normal, text_running = "RESTORE ASSETS", "⏳ RESTORING..."
        else:
            self._prune_in_progress = is_running
            btn = getattr(self, "_assets_prune_btn", None)
            text_normal, text_running = "PRUNE CLOUD", "⏳ PRUNING..."

        if btn is not None:
            btn.setEnabled(not is_running)
            btn.setText(text_running if is_running else text_normal)

        if self._tmnt_layout is not None and hasattr(self._tmnt_layout, "topbar") and self._tmnt_layout.topbar is not None:
            tb = self._tmnt_layout.topbar
            if action_type == "backup":
                tmnt_btn = getattr(tb, "_assets_backup_btn", None)
            elif action_type == "restore":
                tmnt_btn = getattr(tb, "_assets_restore_btn", None)
            else:
                tmnt_btn = getattr(tb, "_assets_prune_btn", None)

            if tmnt_btn is not None:
                tmnt_btn.setEnabled(not is_running)
                tmnt_btn.setText(text_running if is_running else text_normal)

    def _backup_assets_to_cloud(self):
        from services.gdrive_service import gdrive_store
        from storage_paths import get_mission_archive_root
        
        local_archive_root = get_mission_archive_root()
        if not local_archive_root:
            QMessageBox.warning(
                self, 
                "Mission Archive Required", 
                "You must configure a Mission Archive folder in settings before backing up assets to the cloud."
            )
            return
            
        self._gdrive_status_lbl.setText("Backing up assets...")
        self._set_assets_button_state("backup", True)
        print("\n[GDriveService] ⚡ Starting cloud backup of all active assets...")
        ToastNotification(self, "⚡ Starting assets backup to Google Drive in background...", duration_ms=2000)
            
        def _bg():
            success = False
            try:
                db_path = store._get_db_path()
                db_ok = gdrive_store.upload_file_to_drive(db_path)
                from data_manager import DATA_FILE
                if DATA_FILE.endswith(".json") and os.path.exists(DATA_FILE):
                    gdrive_store.upload_file_to_drive(DATA_FILE)
                
                ref_pdfs, ref_images = self._get_active_assets()
                success = gdrive_store.backup_referenced_assets(local_archive_root, ref_pdfs, ref_images)
            except Exception as e:
                print(f"[GDrive Backup Assets] Error: {e}")
                
            def _done():
                self._set_assets_button_state("backup", False)
                self._refresh_gdrive_display()
                    
                if success:
                    _log_success("Assets backup completed successfully!")
                    ToastNotification(self, "👍 All active assets backed up to Google Drive successfully!")
                else:
                    QMessageBox.warning(
                        self, 
                        "Backup Complete with Issues", 
                        "Some assets failed to upload. Check console or log for details."
                    )
            self.thread_safe_run_signal.emit(_done)
            
        import threading
        threading.Thread(target=_bg, daemon=True, name="GDrive-BackupAssets").start()

    def _sync_assets_from_cloud(self):
        from services.gdrive_service import gdrive_store
        from storage_paths import get_mission_archive_root
        import shutil
        
        local_archive_root = get_mission_archive_root()
        if not local_archive_root:
            QMessageBox.warning(
                self, 
                "Mission Archive Required", 
                "You must configure a Mission Archive folder in settings before syncing assets from the cloud."
            )
            return
            
        self._gdrive_status_lbl.setText("Restoring assets...")
        self._set_assets_button_state("restore", True)
        print("\n[GDriveService] ⚡ Starting cloud restore/sync of assets...")
        ToastNotification(self, "⚡ Starting assets restore from Google Drive in background...", duration_ms=2000)
            
        def _bg():
            success = False
            try:
                db_path = store._get_db_path()
                
                # Create a local safety backup of current db first
                if os.path.exists(db_path):
                    backup_local = db_path + ".restore_backup"
                    shutil.copy2(db_path, backup_local)
                
                # Fetch database from cloud
                token = gdrive_store.get_access_token()
                if token:
                    folder_id = gdrive_store._get_or_create_backups_folder({"Authorization": f"Bearer {token}"})
                    file_id = gdrive_store._find_file_in_folder({"Authorization": f"Bearer {token}"}, os.path.basename(db_path), folder_id)
                    if file_id:
                        dl_db_ok = gdrive_store.download_file_from_drive(file_id, db_path)
                        if dl_db_ok:
                            # Reload store so we parse the updated database
                            store.load()
                            ref_pdfs, ref_images = self._get_active_assets()
                            
                            # Differential sync for referenced assets
                            success = gdrive_store.sync_referenced_assets(local_archive_root, ref_pdfs, ref_images)
            except Exception as e:
                print(f"[GDrive Sync Assets] Error: {e}")
                
            def _done():
                self._set_assets_button_state("restore", False)
                self._refresh_gdrive_display()
                    
                # Reload UI data
                self._data = store.get()
                self.refresh()
                if hasattr(self, "_tmnt_layout") and self._tmnt_layout is not None:
                    self._tmnt_layout.sidebar.set_data(self._data)
                    self._tmnt_layout.main._data = self._data
                    
                if success:
                    _log_success("Assets sync/restore completed successfully!")
                    ToastNotification(self, "👍 Database and active assets synced from Google Drive successfully!")
                else:
                    QMessageBox.warning(
                        self, 
                        "Sync Complete with Issues", 
                        "Database synced, but some asset downloads failed. Check console for details."
                    )
            self.thread_safe_run_signal.emit(_done)
            
        import threading
        threading.Thread(target=_bg, daemon=True, name="GDrive-SyncAssets").start()

    def _prune_cloud_assets(self):
        from services.gdrive_service import gdrive_store
        
        if (
            QMessageBox.question(
                self,
                "Prune Cloud Storage",
                "Are you sure you want to prune cloud storage?\n\n"
                "This will scan your Google Drive and delete any PDFs or images that are NOT "
                "referenced by any cards in your active database. This cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            != QMessageBox.Yes
        ):
            return
            
        self._gdrive_status_lbl.setText("Pruning cloud...")
        self._set_assets_button_state("prune", True)
        print("\n[GDriveService] ⚡ Starting cloud pruning scan...")
        ToastNotification(self, "⚡ Starting cloud pruning scan in background...", duration_ms=2000)
            
        def _bg():
            success = False
            try:
                ref_pdfs, ref_images = self._get_active_assets()
                success = gdrive_store.prune_unreferenced_assets(ref_pdfs, ref_images)
            except Exception as e:
                print(f"[GDrive Prune Cloud] Error: {e}")
                
            def _done():
                self._set_assets_button_state("prune", False)
                self._refresh_gdrive_display()
                    
                if success:
                    _log_success("Prune cloud assets completed successfully!")
                    ToastNotification(self, "👍 Unreferenced assets deleted from Google Drive successfully!")
                else:
                    QMessageBox.warning(
                        self, 
                        "Pruning Failed", 
                        "Pruning process encountered errors. Check console for details."
                    )
            self.thread_safe_run_signal.emit(_done)
            
        import threading
        threading.Thread(target=_bg, daemon=True, name="GDrive-PruneAssets").start()


from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit

class GDriveCredentialsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Google Drive Sync")
        self.setFixedWidth(480)
        
        from PyQt5.QtWidgets import QApplication
        from theme_manager import get_palette
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        
        # Style sheet to apply premium dark/light mode depending on the active theme
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {p.get('C_BG', '#0B0C10')};
            }}
            QLabel {{
                color: {p.get('C_TEXT', '#FFFFFF')};
                font-family: {p.get('body_font', 'Segoe UI')};
                font-size: 12px;
            }}
            QLineEdit {{
                background-color: {p.get('C_CARD', '#1F2833')};
                color: {p.get('C_TEXT', '#FFFFFF')};
                border: 1px solid {p.get('C_BORDER', '#45A29E')};
                border-radius: 4px;
                padding: 8px;
                font-family: {p.get('body_font', 'Segoe UI')};
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid {p.get('C_ACCENT', '#66FCF1')};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        
        desc = QLabel(
            "To link Google Drive, please configure your Google OAuth credentials.\n"
            "This ensures your study database is synced directly to your own Google account."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {p.get('C_SUBTEXT', '#BAC2DE')}; font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc)
        
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)
        
        client_id_label = QLabel("Client ID:")
        client_id_label.setStyleSheet("font-weight: bold;")
        self.client_id_input = QLineEdit()
        self.client_id_input.setPlaceholderText("Paste Google OAuth Client ID here...")
        form.addRow(client_id_label, self.client_id_input)
        
        client_secret_label = QLabel("Client Secret:")
        client_secret_label.setStyleSheet("font-weight: bold;")
        self.client_secret_input = QLineEdit()
        self.client_secret_input.setPlaceholderText("Paste Client Secret here...")
        self.client_secret_input.setEchoMode(QLineEdit.Password)
        form.addRow(client_secret_label, self.client_secret_input)
        
        layout.addLayout(form)
        
        # Prepopulate with current config if exists
        from services.gdrive_service import gdrive_store
        cfg = gdrive_store.get_config()
        if cfg:
            self.client_id_input.setText(cfg.get("client_id", ""))
            self.client_secret_input.setText(cfg.get("client_secret", ""))
            
        help_label = QLabel()
        help_label.setWordWrap(True)
        help_label.setOpenExternalLinks(True)
        accent_color = p.get('C_ACCENT', '#66FCF1')
        subtext_color = p.get('C_SUBTEXT', '#8892B0')
        help_label.setText(
            f'<span style="color: {subtext_color};">Need help? </span>'
            f'<a href="https://developers.google.com/drive/api/quickstart/python" '
            f'style="color: {accent_color}; text-decoration: underline; font-weight: bold;">'
            f'Instructions: How to get Client ID & Secret</a>'
        )
        help_label.setStyleSheet("font-size: 12px; margin-top: 4px;")
        layout.addWidget(help_label)
        
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {p.get('C_SUBTEXT', '#8892B0')};
                border: 1px solid {p.get('C_BORDER', '#45A29E')};
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.05);
                color: {p.get('C_TEXT', '#FFFFFF')};
            }}
        """)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        
        save = QPushButton("Save Config")
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.get('C_ACCENT', '#66FCF1')};
                color: {p.get('C_BG', '#0B0C10')};
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #FFFFFF;
                color: {p.get('C_BG', '#0B0C10')};
            }}
        """)
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        
        layout.addLayout(buttons)


# ═══════════════════════════════════════════════════════════════════════════════
