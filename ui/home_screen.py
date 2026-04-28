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
    sched_init, sm2_init, sched_update, sm2_update, 
    is_due_now, is_due_today, sm2_is_due, sm2_days_left, 
    _fmt_due_interval, sm2_simulate, sm2_badge
)

# SM-2 debug logger — safe import (no crash if file missing)
try:
    from sm2_debug_log import log_session, log_rate, log_due, log_queue
    _DEBUG_LOG = True
except ImportError:
    _DEBUG_LOG = False

# Daily Journal — safe import
try:
    from ui.journal import JournalDialog
    _JOURNAL_AVAILABLE = True
except ImportError:
    _JOURNAL_AVAILABLE = False

# Session Timer — safe import
try:
    from session_timer import SessionTimer
    _TIMER_AVAILABLE = True
except ImportError:
    _TIMER_AVAILABLE = False

from pdf_engine import (
    PDF_SUPPORT, PAGE_CACHE, PdfLoaderThread, PdfSkeletonThread,
    pdf_page_to_pixmap, load_pdf_skeleton, PdfOnDemandThread,
    build_skeleton_placeholders,
    invalidate_pdf_skeleton        # STEP 2 + 3
)

from editor_ui import OcclusionCanvas,_ZoomableScrollArea
from ui.editor_dialog import CardEditorDialog
from ui.review_screen import ReviewScreen

import fitz

from data_manager import (
    load_data, save_data, find_deck_by_id, next_deck_id, new_box_id, deck_history,
    DATA_FILE, store
)

import sys, os, copy, uuid, math, time
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QFrame, QScrollArea, QInputDialog, QMessageBox,
    QSplitter, QStatusBar, QProgressBar, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QAbstractItemView, QMenu, QStyledItemDelegate, QStyle,
    QHeaderView
)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QRectF, QPointF, pyqtSignal, QLockFile, QTimer, QModelIndex, QFileSystemWatcher, QThread, QEvent, QMimeData, QByteArray, QUrl
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QIcon, QBrush, QTransform, QPainterPath, QDrag, QDesktopServices
)

import tempfile

# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

C_BG      = "#1E1E2E"
C_SURFACE = "#2A2A3E"
C_CARD    = "#313145"
C_ACCENT  = "#7C6AF7"
C_GREEN   = "#50FA7B"
C_RED     = "#FF5555"
C_YELLOW  = "#F1FA8C"
C_TEXT    = "#CDD6F4"
C_SUBTEXT = "#A6ADC8"
C_BORDER  = "#45475A"
C_MASK    = "#F7916A"
C_GROUP   = "#BD93F9"


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



from .deck_tree import DeckTree, CacheWidget
from .deck_view import DeckView

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
        self.setStyleSheet(f"QDialog{{background:{C_BG};}}")
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)
        header = QFrame()
        header.setFixedHeight(140)
        header.setStyleSheet(f"QFrame{{background:{C_SURFACE};border-radius:0px;}}")
        hl = QVBoxLayout(header)
        hl.setAlignment(Qt.AlignCenter)
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_px = make_app_icon().pixmap(72, 72)
        icon_lbl.setPixmap(icon_px)
        hl.addWidget(icon_lbl)
        name_lbl = QLabel("Anki Occlusion")
        name_lbl.setFont(QFont("Segoe UI", 18, QFont.Bold))
        name_lbl.setStyleSheet(f"color:{C_ACCENT};background:transparent;")
        name_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(name_lbl)
        ver_lbl = QLabel("Version 1.0  •  Desktop Edition")
        ver_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;background:transparent;")
        ver_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(ver_lbl)
        L.addWidget(header)
        body = QWidget()
        body.setStyleSheet(f"background:{C_BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(32, 24, 32, 24)
        bl.setSpacing(16)
        def _section(title, text):
            t = QLabel(title)
            t.setFont(QFont("Segoe UI", 10, QFont.Bold))
            t.setStyleSheet(f"color:{C_TEXT};")
            d = QLabel(text)
            d.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
            d.setWordWrap(True)
            bl.addWidget(t)
            bl.addWidget(d)
        _section("What it does",
            "Draw rectangular masks over your PDF notes and images, "
            "then study them with a full Anki-style spaced repetition "
            "scheduler — learning steps, review intervals, ease factors.")
        _section("Keyboard shortcuts",
            "F11 — fullscreen        Ctrl+Z / Y — undo / redo\n"
            "Space — reveal answer   1/2/3/4 — rate Again/Hard/Good/Easy\n"
            "V=Select  R=Rect  E=Ellipse  T=Label  Del=delete selected\n"
            "Ctrl+A — select all     Ctrl+Scroll — zoom\n"
            "Alt+Click — multi-select   Hold Alt — temp select tool\n"
            "C — center on mask      Drag ↻ handle — rotate shape\n"
            "Space+drag — pan canvas  H — toggle pan lock")
        _section("Data location", f"{DATA_FILE}")
        bl.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"background:{C_ACCENT};color:white;border:none;border-radius:8px;"
            f"padding:8px 32px;font-weight:bold;font-size:13px;")
        close_btn.clicked.connect(self.accept)
        bl.addWidget(close_btn, alignment=Qt.AlignCenter)
        L.addWidget(body)


class OnboardingDialog(QDialog):
    STEPS = [
        {"icon": "🃏", "title": "Welcome to Anki Occlusion",
         "body": "The fastest way to turn your PDF notes and images into Anki-style flashcards — without typing a single word.\n\nThis quick tour takes about 30 seconds."},
        {"icon": "📂", "title": "Step 1 — Create a Deck",
         "body": "Click  ＋ Deck  in the left sidebar to create your first deck.\n\nYou can nest decks inside each other — for example:\n  Biology  ›  Chapter 3  ›  Cell Division\n\nDrag and drop to reorganise them any time."},
        {"icon": "🖼", "title": "Step 2 — Add a Card",
         "body": "Select a deck, then click  ＋ Add Card.\n\nLoad a PDF or image, then use the toolbar:\n  ▶ Select — move, resize, rotate shapes\n  ▭ Rectangle — draw rectangular masks\n  ⬭ Ellipse — draw oval masks\n  T Text — click a mask to edit its label\n\nEach mask becomes one flashcard question automatically."},
        {"icon": "🧠", "title": "Step 3 — Review",
         "body": "Click  🔴 Review Due  to start your session.\n\nTwo review modes (toggle in review header):\n  🟧 Hide All, Guess One — all masks hidden one by one\n  👁 Hide One, Guess One — only the target mask hidden\n\nPress Space to reveal, then rate yourself:\n  1 = Again   2 = Hard   3 = Good   4 = Easy\n\nThe scheduler decides when you'll see each card next."},
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome")
        self.setFixedSize(540, 440)
        self.setStyleSheet(f"QDialog{{background:{C_BG};}}")
        self._step = 0
        self._setup_ui()
        self._show_step(0)

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)
        dot_bar = QWidget()
        dot_bar.setFixedHeight(32)
        dot_bar.setStyleSheet(f"background:{C_SURFACE};")
        dl = QHBoxLayout(dot_bar)
        dl.setAlignment(Qt.AlignCenter)
        dl.setSpacing(8)
        self._dots = []
        for _ in self.STEPS:
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{C_BORDER};font-size:10px;background:transparent;")
            dl.addWidget(dot)
            self._dots.append(dot)
        L.addWidget(dot_bar)
        content = QWidget()
        content.setStyleSheet(f"background:{C_BG};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(48, 32, 48, 24)
        cl.setSpacing(16)
        self._icon_lbl = QLabel()
        self._icon_lbl.setFont(QFont("Segoe UI", 48))
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setStyleSheet("background:transparent;")
        self._title_lbl = QLabel()
        self._title_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color:{C_TEXT};background:transparent;")
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setWordWrap(True)
        self._body_lbl = QLabel()
        self._body_lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;background:transparent;")
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
            f"QFrame{{background:{C_SURFACE};"
            f"border-top:1px solid {C_BORDER};border-radius:0px;}}")
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(24, 0, 24, 0)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setStyleSheet(
            f"background:transparent;color:{C_SUBTEXT};border:none;font-size:12px;padding:6px 16px;")
        self._skip_btn.clicked.connect(self.accept)
        self._back_btn = QPushButton("← Back")
        self._back_btn.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:8px;padding:8px 20px;font-size:12px;")
        self._back_btn.clicked.connect(self._prev)
        self._next_btn = QPushButton("Next →")
        self._next_btn.setStyleSheet(
            f"background:{C_ACCENT};color:white;border:none;"
            f"border-radius:8px;padding:8px 24px;font-weight:bold;font-size:13px;")
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
                f"font-size:10px;background:transparent;")
        is_last  = (idx == len(self.STEPS) - 1)
        is_first = (idx == 0)
        self._back_btn.setVisible(not is_first)
        self._skip_btn.setVisible(not is_last)
        self._next_btn.setText("🚀  Get Started!" if is_last else "Next →")
        self._next_btn.setStyleSheet(
            f"background:{C_GREEN if is_last else C_ACCENT};"
            f"color:{'#1E1E2E' if is_last else 'white'};"
            f"border:none;border-radius:8px;padding:8px 24px;"
            f"font-weight:bold;font-size:13px;")

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
        self._path      = pdf_path
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        if not PDF_SUPPORT:
            return
        from pdf_engine import PAGE_CACHE, pdf_page_to_pixmap
        try:
            doc = fitz.open(self._path)
            if doc.is_encrypted:
                return
            total = len(doc)
            mat   = fitz.Matrix(1.5, 1.5)
            
            for i in range(total):
                if self._stop_flag:
                    doc.close()
                    return
                
                # Check if page is already in cache
                cached = PAGE_CACHE.get(self._path, i)
                if not cached:
                    # If not, render and put in PAGE_CACHE
                    qpx = pdf_page_to_pixmap(doc.load_page(i), mat)
                    if not qpx.isNull():
                        PAGE_CACHE.put(self._path, i, qpx)
            
            doc.close()
        except Exception:
            pass

class HomeScreen(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._preload_thread = None   # background PDF preload thread
        self._active_editor = None
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)
        top = QFrame()
        top.setFixedHeight(56)
        top.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {C_BORDER};}}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 0, 20, 0)
        ttl = QLabel("🃏  Anki Occlusion")
        ttl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        ttl.setStyleSheet(f"color:{C_ACCENT};")
        sub = QLabel("Recall More. Forget Less⭐")
        sub.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        tl.addWidget(ttl)
        tl.addSpacing(16)
        tl.addWidget(sub)
        tl.addStretch()

        def _topbtn(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C_SUBTEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"padding:4px 14px;font-size:12px;}}"
                f"QPushButton:hover{{background:{C_CARD};color:{C_TEXT};}}")
            return b

        btn_help    = _topbtn("❓ Help",    "Show quick-start guide")
        btn_about   = _topbtn("ℹ About",   "About Anki Occlusion")
        btn_journal = _topbtn("📓 Journal", "Open Daily Journal")
        btn_help.clicked.connect(self._show_help)
        btn_about.clicked.connect(self._show_about)
        btn_journal.clicked.connect(self._show_journal)
        # ── Theme Toggle ──────────────────────────────────────────────────────
        self._current_theme = "classic"  # start state

        self._btn_theme = QPushButton("🥷 Ninja Mode")
        self._btn_theme.setToolTip("Switch between Classic and Ninja Turtle theme")
        self._btn_theme.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_SUBTEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 14px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_CARD};color:{C_TEXT};}}"
        )
        self._btn_theme.clicked.connect(self._toggle_theme)

        def _fontbtn(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(30)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C_SUBTEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"padding:2px 4px;font-size:12px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{C_CARD};color:{C_TEXT};}}")
            return b

        btn_fa = _fontbtn("A−", "Decrease font size  (Ctrl+−)")
        btn_fr = _fontbtn("A",  "Reset font size  (Ctrl+0)")
        btn_fi = _fontbtn("A+", "Increase font size  (Ctrl++)")
        btn_fr.setFixedWidth(24)
        btn_fa.clicked.connect(lambda: self._emit_font(-1))
        btn_fr.clicked.connect(lambda: self._emit_font(0))
        btn_fi.clicked.connect(lambda: self._emit_font(+1))

        tl.addSpacing(8)
        tl.addWidget(btn_fa)
        tl.addWidget(btn_fr)
        tl.addWidget(btn_fi)
        tl.addSpacing(4)
        tl.addWidget(self._btn_theme)
        tl.addWidget(btn_journal)
        tl.addWidget(btn_help)
        tl.addWidget(btn_about)
        self._top_bar = top
        L.addWidget(top)

        split = QSplitter(Qt.Horizontal)
        self.deck_tree = DeckTree(self._data)
        self.deck_tree.setMinimumWidth(260)
        self.deck_tree.setMaximumWidth(420)
        self.deck_tree.deck_selected.connect(self._on_deck_selected)
        split.addWidget(self.deck_tree)
        self.deck_view = DeckView()
        split.addWidget(self.deck_view)
        self._cache_widget = CacheWidget()        # ← ADD
        split.addWidget(self._cache_widget)       # ← ADD
        split.setSizes([340, 760, 220])           # ← CHANGE (was [340, 860])
        L.addWidget(split, stretch=1)

    def show_review(self, cards, data, _on_batch_done=None):
        """Replace the DeckView panel with ReviewScreen inline."""
        _save_done = [False]
        split = self._get_splitter()
        if split is None:
            return

        # Hide deck_tree during review, store splitter sizes to restore later
        self._pre_review_sizes = split.sizes()
        self.deck_tree.hide()
        self._top_bar.hide()
        self.window().statusBar().hide()

        rev = ReviewScreen(cards, data=data, parent=self)
        self._active_review = rev

        def _on_finished():
            if not _save_done[0]:
                _save_done[0] = True
                # [FIX] Force-save on review exit so SM-2 state from the last
                # card rated is never lost if the app is closed immediately after.
                # _rate() already called save_force() per rating, but this is a
                # safety net for edge cases (e.g. user exits mid-session without
                # rating the current card — partial session state still saved).
                store.mark_dirty()
                store.save_force()
            self.hide_review()
            if _on_batch_done:
                _on_batch_done()

        rev.finished.connect(_on_finished)

        def _on_cancelled():
            if not _save_done[0]:
                _save_done[0] = True
                store.mark_dirty()
                store.save_force()
            self.hide_review()  # stop the sequential chain — no _on_batch_done

        rev.cancelled.connect(_on_cancelled)

        # Replace index 1 (deck_view) with the ReviewScreen
        split.replaceWidget(1, rev)
        rev.show()
        # Give most space to review, hide cache panel
        split.setSizes([0, split.width(), 0])
        # Give keyboard focus to canvas immediately so Space works without clicking
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
        """Restore DeckView after review ends."""
        split = self._get_splitter()
        if split is None:
            return
        rev = getattr(self, "_active_review", None)
        if rev:
            split.replaceWidget(1, self.deck_view)
            rev.setParent(None)
            rev.deleteLater()
            self._active_review = None
        self.deck_tree.show()
        self._top_bar.show()
        self.window().statusBar().show()
        # Restore original sizes
        sizes = getattr(self, "_pre_review_sizes", [340, 760, 220])
        split.setSizes(sizes)
        self.refresh()

    def _get_splitter(self):
        """Return the main QSplitter child."""
        for child in self.children():
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
            p = card.get("pdf_path", "")
            if p and os.path.exists(p):
                return p
        for child in deck.get("children", []):
            p = self._find_first_pdf(child)
            if p:
                return p
        return None

    def _show_journal(self):
        if _JOURNAL_AVAILABLE:
            JournalDialog(self).exec_()
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Journal",
                "journal.py not found!\nPlace journal.py next to anki_occlusion_v19.py")

    def _show_about(self):
        AboutDialog(self).exec_()

    def _show_help(self):
        OnboardingDialog(self).exec_()
    def _toggle_theme(self):
        from theme_manager import build_stylesheet

        if self._current_theme == "classic":
            self._current_theme = "dojo"
            self._btn_theme.setText("📚 Classic Mode")
        else:
            self._current_theme = "classic"
            self._btn_theme.setText("🥷 Ninja Mode")

        app = QApplication.instance()
        if app:
            app._active_theme = self._current_theme
            if self._current_theme == "classic":
                app.setStyleSheet(SS)
            else:
                app.setStyleSheet(build_stylesheet(self._current_theme))
    def _emit_font(self, direction: int):
        win = self.window()
        if hasattr(win, "change_font_size"):
            win.change_font_size(direction)

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        ctrl  = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)

        if ctrl and key == Qt.Key_Z:
            if getattr(self, "_active_review", None) is None:
                if shift:
                    # Ctrl+Shift+Z → deck redo
                    ok = deck_history.redo(store)
                    if ok:
                        self.deck_tree.refresh()
                        self.canvas._show_toast("↪ Deck redo") if hasattr(self, 'canvas') else None
                    print(f"[HomeScreen][key] Ctrl+Shift+Z — deck redo, ok={ok}")
                else:
                    # Ctrl+Z → try deck undo first, else mask undo
                    ok = deck_history.undo(store)
                    if ok:
                        # deck_tree ka sahi attribute name use karo
                        dt = getattr(self, 'deck_tree', None) or getattr(self, '_deck_tree', None)
                        if dt:
                            dt._data = store.get()   # ← data bhi sync karo
                            dt.refresh()
                            print("[HomeScreen][key] Ctrl+Z — deck_tree refreshed ✅")
                        else:
                            print("[HomeScreen][key] ⚠ deck_tree attribute nahi mila")
                        print("[HomeScreen][key] Ctrl+Z — deck undo done")
                    else:
                        self.deck_view.undo()
                        print("[HomeScreen][key] Ctrl+Z — fell through to mask undo")
                e.accept()
                return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        active_editor = getattr(self, "_active_editor", None)
        if active_editor is not None:
            active_editor.close()
            self._active_editor = None
        super().closeEvent(e)

    def refresh(self):
        self.deck_tree.refresh()
        sel = self.deck_tree.get_selected_deck()
        if sel:
            self.deck_view.load_deck(sel, self._data)


# ═══════════════════════════════════════════════════════════════════════════════
