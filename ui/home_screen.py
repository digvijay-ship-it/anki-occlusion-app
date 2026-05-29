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


def load_custom_fonts():
    """Safe font loading. Only runs if QApplication instance exists."""
    global NARUTO_FONT_FAMILY
    if not QApplication.instance():
        return


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


class _PreloadThread(QThread):
    """
    Silent background thread — PDF ko disk cache mein silently save karo.
    Koi UI signal nahi, koi canvas update nahi. Sirf disk par PNG save hota hai.
    Deck switch hone par stop() call karo — thread cleanly exit ho jaayega.
    """

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self._path = pdf_path
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        from pdf_engine import PDF_SUPPORT, PAGE_CACHE, pdf_page_to_image

        if not PDF_SUPPORT:
            return
        import fitz

        try:
            doc = fitz.open(self._path)
            if doc.is_encrypted:
                return
            total = len(doc)
            mat = fitz.Matrix(1.5, 1.5)

            for i in range(total):
                if self._stop_flag:
                    doc.close()
                    return

                # Check if page is already in cache
                cached = PAGE_CACHE.get_image(self._path, i)
                if not cached:
                    # If not, render as QImage; QPixmap is GUI-thread only.
                    img = pdf_page_to_image(doc.load_page(i), mat)
                    if not img.isNull():
                        if hasattr(PAGE_CACHE, "put_image"):
                            PAGE_CACHE.put_image(self._path, i, img, render_zoom=1.5)
                        print(f"[DEBUG][pdf_preload] cached p.{i + 1}/{total}")

            doc.close()
        except Exception:
            pass


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

    def __init__(self, parent=None):
        super().__init__(parent)
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
            if self._pygame_ok:
                self._pygame.mixer.music.load(self._tracks[idx])
                self._pygame.mixer.music.set_volume(0.4)
                self._pygame.mixer.music.play(-1)  # -1 = loop
            elif self._player:
                self._playlist.setCurrentIndex(idx)
                self._player.setVolume(40)
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
        
        # Opacity effect for fade animation
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        
        # Animation: Fade In
        from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, QTimer
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
        
        # Start
        self.show()
        self._anim_in.start()
        
        # Schedule Fade Out
        QTimer.singleShot(duration_ms, self._anim_out.start)
        
    def move_to_position(self):
        if not self.parent():
            return
        parent_rect = self.parent().rect()
        x = (parent_rect.width() - self.width()) // 2
        y = parent_rect.height() - self.height() - 40
        self.move(x, y)


class HomeScreen(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        load_custom_fonts()  # ── SAFE FONT LOAD ──
        self._data = data
        self._preload_thread = None  # background PDF preload thread
        self._active_editor = None
        self._classic_settings_panel = None
        self._classic_archive_value = None
        self._classic_archive_box = None
        self._classic_archive_btn = None
        self._btn_shortcuts = None
        self.deck_tree = None
        self.deck_view = None
        self._cache_widget = None
        self._splitter_widget = None
        self._tmnt_layout = None
        self._setup_ui()

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

        btn_math = _topbtn("🧮 MATH", "Practice Tables, Squares & Cubes")
        btn_journal = _topbtn("📓 JOURNAL", "Open Daily Journal")
        self._btn_save = _topbtn("💾 SAVE", "Save now  Ctrl+S")
        self._btn_settings = _topbtn("⚙ SETTINGS", "Visual scale and Mission Archive")
        self._btn_shortcuts = _topbtn("⌨ SHORTCUTS", "Set or modify keyboard shortcuts")
        btn_help = _topbtn("❓ HELP", "Show quick-start guide")
        btn_about = _topbtn("ℹ ABOUT", "About Anki Occlusion")

        btn_math.clicked.connect(self._show_math_trainer)
        btn_journal.clicked.connect(self._show_journal)
        self._btn_save.clicked.connect(self._on_classic_save_clicked)
        self._btn_settings.clicked.connect(self._toggle_classic_settings_panel)
        self._btn_shortcuts.clicked.connect(self._show_shortcuts)
        btn_help.clicked.connect(self._show_help)
        btn_about.clicked.connect(self._show_about)

        # Theme Toggle Button
        saved_theme = self._data.get("_theme", "classic")
        self._current_theme = normalize_theme(saved_theme)
        _next_lbl = {"classic": "🐢 TMNT MODE", "tmnt": "📚 CLASSIC MODE"}
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
        tl.addWidget(self._btn_save)
        tl.addWidget(self._btn_settings)
        tl.addWidget(self._btn_shortcuts)
        tl.addWidget(self._btn_theme)
        tl.addWidget(btn_help)
        tl.addWidget(btn_about)
        tl.addSpacing(6)
        tl.addWidget(btn_fa)
        tl.addWidget(btn_fr)
        tl.addWidget(btn_fi)

        self.music_widget = MusicWidget()
        tl.addSpacing(4)
        tl.addWidget(self.music_widget)

        # Mentor Section (Aligned with Cache Bar width ~220px)
        self.mentor = MentorWidget()
        self.mentor.setFixedWidth(220)
        tl.addWidget(self.mentor)

        self._top_bar = self.top_frame
        self._apply_topbar_style()  # Initial style
        self._classic_settings_panel = self._build_classic_settings_panel()
        L.addWidget(self.top_frame)

        # ── BODY STACK: active theme is built immediately; inactive theme is lazy.
        self._body_stack = QStackedWidget()

        L.addWidget(self._body_stack, stretch=1)

        # Activate correct body for saved theme
        if self._current_theme == "tmnt" and self._ensure_tmnt_layout():
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

    def _ensure_classic_layout(self):
        if self._splitter_widget is not None:
            return self._splitter_widget

        DeckTreeCls, CacheWidgetCls, DeckViewCls = _load_classic_home_classes()
        self._splitter_widget = QWidget()
        _sw_l = QVBoxLayout(self._splitter_widget)
        _sw_l.setContentsMargins(0, 0, 0, 0)
        _sw_l.setSpacing(0)
        split = QSplitter(Qt.Horizontal)
        self.deck_tree = DeckTreeCls(self._data, theme=self._current_theme)
        self.deck_tree.setMinimumWidth(260)
        self.deck_tree.setMaximumWidth(420)
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

    def _clear_home_ram_caches(self):
        if (
            getattr(self, "_active_review", None) is not None
            or getattr(self, "_active_editor", None) is not None
        ):
            return

        from cache_manager import PAGE_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY
        import gc

        before = len(getattr(PAGE_CACHE, "_cache", {}) or {})
        mask_pdfs = list(MASK_REGISTRY.all_registered_pdfs())
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

        for pdf_path in mask_pdfs:
            canvases = list(getattr(MASK_REGISTRY, "_map", {}).get(pdf_path, []) or [])
            for canvas in canvases:
                try:
                    canvas_count += 1
                    canvas._mask_cache_layer = None
                    canvas._mask_cache_dirty = True
                    if hasattr(canvas, "_spx_cache"):
                        canvas._spx_cache.clear()
                    if not canvas.isVisible():
                        canvas._pages = []
                        canvas._px = None
                        canvas._page_tops = []
                        canvas._total_w = 0
                        canvas._total_h = 0
                except RuntimeError:
                    pass
            MASK_REGISTRY.invalidate_masks_for_pdf(pdf_path)

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
        gc.collect()

        # Debug: Check if any ReviewScreen or OcclusionCanvas is leaked
        try:
            screens = [o for o in gc.get_objects() if type(o).__name__ == "ReviewScreen"]
            canvases = [o for o in gc.get_objects() if type(o).__name__ == "OcclusionCanvas"]
            print(f"[DEBUG][GC] Active ReviewScreen count: {len(screens)}")
            print(f"[DEBUG][GC] Active OcclusionCanvas count: {len(canvases)}")
        except Exception:
            pass

        cache_widget = getattr(self, "_cache_widget", None)
        if cache_widget is not None and hasattr(cache_widget, "refresh"):
            cache_widget.refresh()
        tmnt_banga = getattr(getattr(self, "_tmnt_layout", None), "banga", None)
        if tmnt_banga is not None and hasattr(tmnt_banga, "refresh"):
            tmnt_banga.refresh()

        print(
            f"[HomeScreen][Auto-Clean] 🧹 RAM cache cleared — "
            f"{before} pages evicted, mask layers invalidated, disk untouched"
        )

        win = self.window()
        if win is not None and hasattr(win, "statusBar") and win.statusBar():
            win.statusBar().showMessage(f"🧹 RAM cache cleared — {before} pages freed", 3000)

    def show_review(self, cards, data, _on_batch_done=None):
        """Replace the DeckView panel with ReviewScreen inline."""
        _save_done = [False]

        rev = _load_review_screen()(cards, data=data, parent=self)
        self._active_review = rev

        def _schedule_review_save():
            if store.is_dirty():
                store.save_soon(
                    min_interval=REVIEW_SAVE_MIN_INTERVAL,
                    delay_from_now=True,
                )

        def _on_finished():
            if not _save_done[0]:
                _save_done[0] = True
                _schedule_review_save()
            self.hide_review()
            if _on_batch_done:
                _on_batch_done()

        def _on_cancelled():
            if not _save_done[0]:
                _save_done[0] = True
                _schedule_review_save()
            self.hide_review()

        rev.finished.connect(_on_finished)
        rev.cancelled.connect(_on_cancelled)

        if self._current_theme == "tmnt" and self._ensure_tmnt_layout():
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

    def show_review_sequential(self, groups, data):
        """Review card groups one PDF at a time.
        After each group finishes: clear RAM + masks + pixmap, then load next group."""
        groups = list(groups)

        def _clear_ram():
            from cache_manager import PAGE_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY

            PAGE_CACHE.clear_ram_only()
            MASK_REGISTRY._map.clear()
            for label in list(PIXMAP_REGISTRY._entries.keys()):
                PIXMAP_REGISTRY.unregister(label)

        def _on_done():
            _clear_ram()
            if groups:
                QTimer.singleShot(0, _launch_next)

        def _launch_next():
            if not groups:
                return
            batch = groups.pop(0)
            self.show_review(batch, data, _on_batch_done=_on_done)

        _launch_next()

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
                    from cache_manager import MASK_REGISTRY
                    MASK_REGISTRY.unregister(rev.canvas)
                except Exception:
                    pass
                try:
                    rev.canvas._pages = []
                    rev.canvas._px = None
                    rev.canvas._mask_cache_layer = None
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
            self.deck_tree.show()
            self._top_bar.show()
            self.window().statusBar().show()
            sizes = getattr(self, "_pre_review_sizes", [340, 760, 220])
            if split:
                split.setSizes(sizes)
        self.refresh()
        QTimer.singleShot(100, self._clear_home_ram_caches)

    def _get_splitter(self):
        """Return the main QSplitter child."""
        if self._splitter_widget is None:
            return None
        for child in self._splitter_widget.children():
            if isinstance(child, QSplitter):
                return child
        return None

    def _on_deck_selected(self, deck):
        self.deck_view.load_deck(deck, self._data)
        # [FIX] Removed _preload_deck_pdf here — PDF should only load
        # when the user explicitly opens/reviews a card, not on deck click.

    def _preload_deck_pdf(self, deck):
        """
        Background mein deck ke pehle PDF card ko preload karo.
        Agar koi aur preload chal raha tha toh usse cancel karo pehle.
        Sirf ek PDF at a time preload hoti hai.
        """
        # Cancel any running preload
        if hasattr(self, "_preload_thread") and self._preload_thread is not None:
            if self._preload_thread.isRunning():
                self._preload_thread.stop()
                self._preload_thread.quit()
                self._preload_thread.wait(300)
            self._preload_thread = None

        from pdf_engine import PDF_SUPPORT, PAGE_CACHE

        if not PDF_SUPPORT:
            return

        # Find first card in this deck (or any child deck) with a pdf_path
        pdf_path = self._find_first_pdf(deck)
        if not pdf_path or not os.path.exists(pdf_path):
            return

        # Already cached? No need to preload
        # In v20, we check if page 0 exists in the PAGE_CACHE instead
        if PAGE_CACHE.get(pdf_path, 0) is not None:
            return

        # Start silent background thread — no signals connected to UI
        self._preload_thread = _PreloadThread(pdf_path, parent=self)
        self._preload_thread.start()

    def _find_first_pdf(self, deck):
        """DFS: deck aur uske children mein pehla pdf_path dhundho."""
        for card in deck.get("cards", []):
            p = resolve_asset_path(card.get("pdf_path", ""))
            if p and os.path.exists(p):
                return p
        for child in deck.get("children", []):
            p = self._find_first_pdf(child)
            if p:
                return p
        return None

    def _show_journal(self):
        dialog_cls = _load_journal_dialog()
        if dialog_cls is not None:
            dialog_cls(self).exec_()
        else:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Journal",
                "journal.py not found!\nPlace journal.py next to anki_occlusion_v19.py",
            )

    def _show_math_trainer(self):
        if getattr(self, "_math_trainer", None) is not None:
            return
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
            ocr_warm_up()
        except Exception as e:
            print(f"[MathTrainer] Failed to warm up OCR worker: {e}")
        if self._current_theme == "tmnt" and self._tmnt_layout:
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
                sizes = getattr(self, "_pre_math_sizes", [340, 760, 220])
                split.setSizes(sizes)
        self.refresh()

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

    def _create_tmnt_layout(self):
        layout_cls = _load_tmnt_home_layout()
        if layout_cls is None:
            return None
        layout = layout_cls(self._data, parent=self)
        layout.btn_save_clicked.connect(self._save_current_data_now)
        layout.btn_math_clicked.connect(self._show_math_trainer)
        layout.btn_journal_clicked.connect(self._show_journal)
        layout.btn_theme_clicked.connect(self._toggle_theme)
        layout.btn_help_clicked.connect(self._show_help)
        layout.btn_about_clicked.connect(self._show_about)
        layout.btn_shortcuts_clicked.connect(self._show_shortcuts)
        layout.font_change.connect(self._emit_font)
        layout.bgm_toggle.connect(self._toggle_tmnt_bgm)
        layout.set_bgm_state(self.music_widget._playing)
        return layout

    def _save_current_data_now(self):
        try:
            store.mark_dirty()
            store.save_force(async_save=True)
            flush_runtime_state()
        except Exception as ex:
            QMessageBox.warning(
                self, "Save Failed", f"Could not save current data:\n{ex}"
            )
            return

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
            QPushButton {{
                background: {C_CARD};
                color: {C_SUBTEXT};
                border: 1px solid {C_BORDER};
                border-radius: 6px;
                padding: 5px 10px;
                font-family: 'Segoe UI';
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {C_BG};
                color: {C_TEXT};
                border-color: {C_ACCENT};
            }}
            """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

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

        self._refresh_classic_archive_display()
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
        self._refresh_classic_archive_display()
        panel.adjustSize()
        pos = self._btn_settings.mapToGlobal(QPoint(0, self._btn_settings.height() + 6))
        panel.move(pos)
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def _choose_classic_mission_archive(self):
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
        if self._classic_settings_panel is not None:
            self._classic_settings_panel.hide()
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

    def _toggle_theme(self):
        from theme_manager import build_stylesheet, normalize_theme
        from PyQt5.QtGui import QFont

        _cycle = {"classic": "tmnt", "tmnt": "classic"}
        _btn_next = {"classic": "🐢 TMNT MODE", "tmnt": "📚 CLASSIC MODE"}

        self._current_theme = normalize_theme(
            _cycle.get(self._current_theme, "classic")
        )
        self._btn_theme.setText(_btn_next.get(self._current_theme, "🐢 TMNT MODE"))
        self._data["_theme"] = self._current_theme
        store.mark_dirty()

        app = QApplication.instance()
        win = self.window()
        current_size = self._data.get("_font_size", BASE_FONT_SIZE)

        if self._current_theme == "tmnt" and self._ensure_tmnt_layout():
            # ── Swap to TMNT full layout ──────────────────────────────────────
            if (
                self._classic_settings_panel is not None
                and self._classic_settings_panel.isVisible()
            ):
                self._classic_settings_panel.hide()
            self.top_frame.hide()
            win_sb = self.window().statusBar() if self.window() else None
            if win_sb:
                win_sb.hide()
            self._tmnt_layout.refresh()
            self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            self._body_stack.setCurrentWidget(self._tmnt_layout)
            if app:
                app._active_theme = "tmnt"
                app.setFont(QFont("Roboto Mono", current_size))
                ss = build_stylesheet("tmnt", current_size)
                app.setStyleSheet(ss)
                if win:
                    win.setStyleSheet(ss)
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

    def _emit_font(self, direction: int):
        win = self.window()
        if hasattr(win, "change_font_size"):
            win.change_font_size(direction)

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)

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
                }}
                QPushButton#font_btn:hover {{
                    background: {C_CARD};
                    color: {C_TEXT};
                }}
            """)

    def show_recovery_center(self, startup=False):
        summary = recovery_manager.scan_recovery(store.get(), startup=startup)
        has_drafts = bool(summary.get("drafts"))
        has_events = bool(summary.get("review_events"))
        if startup and has_events and not has_drafts:
            events = summary.get("review_events", []) or []
            if events and all(event.get("status") == "recoverable" for event in events):
                print(
                    "[DEBUG][recovery] startup_auto_review_recover_start "
                    f"events={len(events)}"
                )
                result = recovery_manager.apply_pending_review_events(store.get())
                if result.get("applied", 0) > 0:
                    store.mark_dirty()
                    store.save_force()
                print(
                    "[DEBUG][recovery] startup_auto_review_recover "
                    f"applied={result.get('applied', 0)} "
                    f"already={result.get('already_applied', 0)} "
                    f"blocked={len(result.get('blocked', []))}"
                )
                summary = recovery_manager.scan_recovery(store.get(), startup=startup)
                has_drafts = bool(summary.get("drafts"))
                has_events = bool(summary.get("review_events"))
                if not has_drafts and not has_events:
                    return True
        if not has_drafts and not has_events:
            if not startup:
                QMessageBox.information(
                    self, "Recovery", "No recoverable drafts or review checkpoints."
                )
            return False

        while True:
            dlg = _load_recovery_dialog()(summary, self, startup=startup)
            dlg.exec_()
            action = getattr(dlg, "action", "close")
            if action == "recover_reviews":
                result = recovery_manager.apply_pending_review_events(store.get())
                if result.get("applied", 0) > 0:
                    store.mark_dirty()
                    store.save_force()
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


# ═══════════════════════════════════════════════════════════════════════════════
