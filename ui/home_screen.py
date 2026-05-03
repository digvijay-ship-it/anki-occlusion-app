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
    QHeaderView, QStackedWidget
)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QRectF, QPointF, pyqtSignal, QLockFile, QTimer, QModelIndex, QFileSystemWatcher, QThread, QEvent, QMimeData, QByteArray, QUrl
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QIcon, QBrush, QTransform, QPainterPath, QDrag, QDesktopServices,
    QFontDatabase
)

import tempfile

# ── LOAD CUSTOM FONTS ────────────────────────────────────────────────────────
NARUTO_FONT_FAMILY = "Segoe UI" # Global variable for easy access

def load_custom_fonts():
    """Safe font loading. Only runs if QApplication instance exists."""
    global NARUTO_FONT_FAMILY
    if not QApplication.instance():
        return
    
    font_path = os.path.join(os.path.dirname(__file__), "..", "ninja-naruto-font", "njnaruto.ttf")
    if os.path.exists(font_path):
        fid = QFontDatabase.addApplicationFont(font_path)
        if fid != -1:
            NARUTO_FONT_FAMILY = QFontDatabase.applicationFontFamilies(fid)[0]

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

# TMNT Home Layout — safe import
try:
    from .tmnt_home import TMNTHomeLayout
    _TMNT_HOME_AVAILABLE = True
    print("[TMNT] Import OK")
except Exception as _tmnt_err:
    import traceback as _tb
    print(f"[TMNT IMPORT ERROR] {type(_tmnt_err).__name__}: {_tmnt_err}")
    _tb.print_exc()
    _TMNT_HOME_AVAILABLE = False

# Math Trainer — safe import
try:
    from .math_trainer import MathTrainerPage
    _MATH_AVAILABLE = True
except ImportError:
    _MATH_AVAILABLE = False

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
        
        av_path = "assets/themes/dojo/Cyber_ninja_turtle_202604270705.jpeg_clean.png"
        if os.path.exists(av_path):
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
            
            painter.drawPixmap(0, 0, size, size, original_px.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            painter.end()
            
            self.av_lbl.setPixmap(rounded_px)
        else:
            self.av_lbl.setStyleSheet("background: #A86CFF; border-radius: 19px; border: 2px solid #A86CFF;")

        txt_l = QVBoxLayout()
        txt_l.setSpacing(0)
        txt_l.setAlignment(Qt.AlignCenter)
        
        self.q_lbl = QLabel('"FOCUS. TRAIN. MASTER."')
        self.q_lbl.setObjectName("mentor_quote")
        # +1.5px (was 10px -> 11.5px)
        self.q_lbl.setStyleSheet("font-family: 'Orbitron'; font-size: 11.5px; font-weight: 900; color: #A86CFF;")
        
        self.n_lbl = QLabel("— DONATELLO")
        self.n_lbl.setObjectName("mentor_name")
        # +1px (was 7px -> 8px)
        self.n_lbl.setStyleSheet("font-family: 'Orbitron'; font-size: 8px; font-weight: 700; color: #A86CFF; opacity: 0.8;")
        
        txt_l.addWidget(self.q_lbl)
        txt_l.addWidget(self.n_lbl)
        
        # Swapped layout: Image LEFT, Text RIGHT
        l.addWidget(self.av_lbl)
        l.addLayout(txt_l)

    def set_style(self, theme):
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
# (already have os, sys, etc — just add these two)
import glob
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
    MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "music")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("music_widget")
        self.setFixedSize(110, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("BGM  [M] toggle  [N] next track")

        self._playing   = False   # whether music is ON
        self._paused    = False
        self._tracks    = []
        self._idx       = 0
        self._pygame_ok = False
        self._player    = None
        self._playlist  = None

        self._init_audio()
        self._scan_tracks()

        # ── Layout ──────────────────────────────────────────────────────
        hl = QHBoxLayout(self)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        self._note_lbl = QLabel("♪")
        self._note_lbl.setObjectName("music_note")
        self._note_lbl.setStyleSheet(
            "font-size:16px; color:#BD93F9; background:transparent;")
        self._note_lbl.setFixedWidth(16)

        self._state_lbl = QLabel("BGM")
        self._state_lbl.setObjectName("music_state")
        self._state_lbl.setStyleSheet(
            "font-size:9px; font-weight:700; letter-spacing:1.5px;"
            "color:#7C6AF7; background:transparent;")

        self._badge = QLabel("OFF")
        self._badge.setObjectName("music_badge")
        self._badge.setFixedWidth(28)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(
            "font-size:8px; font-weight:700; border-radius:3px; padding:1px 3px;"
            f"background:{C_CARD}; color:{C_SUBTEXT};")

        hl.addWidget(self._note_lbl)
        hl.addWidget(self._state_lbl)
        hl.addWidget(self._badge)

        self._refresh_style(dojo=False)

    # ── Audio init ─────────────────────────────────────────────────────
    def _init_audio(self):
        try:
            import pygame
            pygame.mixer.init()
            self._pygame = pygame
            self._pygame_ok = True
        except Exception as e:
            self._pygame_ok = False
            print(f"[MusicWidget] pygame not available: {e}, falling back to QMediaPlayer")
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
        self._tracks = (
            glob.glob(os.path.join(self.MUSIC_DIR, "*.mp3")) +
            glob.glob(os.path.join(self.MUSIC_DIR, "*.ogg")) +
            glob.glob(os.path.join(self.MUSIC_DIR, "*.wav"))
        )
        random.shuffle(self._tracks)
        
        if self._playlist:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtMultimedia import QMediaContent, QMediaPlaylist
            for track in self._tracks:
                self._playlist.addMedia(QMediaContent(QUrl.fromLocalFile(track)))
            self._playlist.setPlaybackMode(QMediaPlaylist.Loop)

    # ── Public API ──────────────────────────────────────────────────────
    def toggle(self):
        """M key handler."""
        if not self._tracks:
            return
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
                self._pygame.mixer.music.play(-1)   # -1 = loop
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
                f"background:{C_ACCENT}; color:white;")
            self._note_lbl.setStyleSheet(
                "font-size:16px; color:#50FA7B; background:transparent;")
        else:
            self._badge.setText("OFF")
            self._badge.setStyleSheet(
                "font-size:8px; font-weight:700; border-radius:3px; padding:1px 3px;"
                f"background:{C_CARD}; color:{C_SUBTEXT};")
            self._note_lbl.setStyleSheet(
                "font-size:16px; color:#BD93F9; background:transparent;")

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

class HomeScreen(QWidget):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        load_custom_fonts() # ── SAFE FONT LOAD ──
        self._data = data
        self._preload_thread = None   # background PDF preload thread
        self._active_editor = None
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
        self.l_box.setFixedSize(42, 42) # Significantly larger
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

        btn_math    = _topbtn("🧮 MATH",    "Practice Tables, Squares & Cubes")
        btn_journal = _topbtn("📓 JOURNAL", "Open Daily Journal")
        btn_help    = _topbtn("❓ HELP",    "Show quick-start guide")
        btn_about   = _topbtn("ℹ ABOUT",   "About Anki Occlusion")
        
        btn_math.clicked.connect(self._show_math_trainer)
        btn_journal.clicked.connect(self._show_journal)
        btn_help.clicked.connect(self._show_help)
        btn_about.clicked.connect(self._show_about)

        # Theme Toggle Button
        self._current_theme = self._data.get("_theme", "classic")
        _next_lbl = {"classic": "🥷 NINJA MODE", "dojo": "🐢 TMNT MODE", "tmnt": "📚 CLASSIC MODE"}
        btn_text = _next_lbl.get(self._current_theme, "🥷 NINJA MODE")
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
        btn_fr = _fontbtn("A",  "Reset font size")
        btn_fi = _fontbtn("A+", "Increase font size")
        
        btn_fa.clicked.connect(lambda: self._emit_font(-1))
        btn_fr.clicked.connect(lambda: self._emit_font(0))
        btn_fi.clicked.connect(lambda: self._emit_font(+1))

        tl.addWidget(btn_math)
        tl.addWidget(btn_journal)
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
        L.addWidget(self.top_frame)

        # ── BODY STACK: index 0 = splitter (classic/dojo), index 1 = TMNT ──
        self._body_stack = QStackedWidget()

        # Splitter widget (classic + dojo)
        self._splitter_widget = QWidget()
        _sw_l = QVBoxLayout(self._splitter_widget)
        _sw_l.setContentsMargins(0, 0, 0, 0)
        _sw_l.setSpacing(0)
        split = QSplitter(Qt.Horizontal)
        self.deck_tree = DeckTree(self._data, theme=self._current_theme)
        self.deck_tree.setMinimumWidth(260)
        self.deck_tree.setMaximumWidth(420)
        self.deck_tree.deck_selected.connect(self._on_deck_selected)
        split.addWidget(self.deck_tree)
        self.deck_view = DeckView()
        self.deck_view.set_theme(self._current_theme)
        split.addWidget(self.deck_view)
        self._cache_widget = CacheWidget()
        split.addWidget(self._cache_widget)
        split.setSizes([340, 760, 220])
        _sw_l.addWidget(split, stretch=1)
        self._body_stack.addWidget(self._splitter_widget)   # index 0

        # TMNT layout
        self._tmnt_layout = None
        if _TMNT_HOME_AVAILABLE:
            self._tmnt_layout = self._create_tmnt_layout()
            self._body_stack.addWidget(self._tmnt_layout)   # index 1

        L.addWidget(self._body_stack, stretch=1)

        # Activate correct body for saved theme
        if self._current_theme == "tmnt" and self._tmnt_layout:
            self.top_frame.hide()
            self._body_stack.setCurrentIndex(1)
            QTimer.singleShot(100, lambda: (
                self.window().statusBar().hide()
                if self.window() and self.window().statusBar() else None
            ))

    def show_review(self, cards, data, _on_batch_done=None):
        """Replace the DeckView panel with ReviewScreen inline."""
        _save_done = [False]

        rev = ReviewScreen(cards, data=data, parent=self)
        self._active_review = rev

        def _on_finished():
            if not _save_done[0]:
                _save_done[0] = True
                store.mark_dirty()
                store.save_force()
            self.hide_review()
            if _on_batch_done:
                _on_batch_done()

        def _on_cancelled():
            if not _save_done[0]:
                _save_done[0] = True
                store.mark_dirty()
                store.save_force()
            self.hide_review()

        rev.finished.connect(_on_finished)
        rev.cancelled.connect(_on_cancelled)

        if self._current_theme == "tmnt" and self._tmnt_layout:
            # TMNT: push review into body stack slot 2
            self._pre_review_tmnt = True
            self.top_frame.hide()
            self._body_stack.addWidget(rev)
            self._body_stack.setCurrentWidget(rev)
        else:
            self._pre_review_tmnt = False
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

        if getattr(self, "_pre_review_tmnt", False) and self._tmnt_layout:
            if rev:
                self._body_stack.removeWidget(rev)
                rev.setParent(None)
                rev.deleteLater()
            self._body_stack.setCurrentIndex(1)
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

    def _get_splitter(self):
        """Return the main QSplitter child."""
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

    def _show_math_trainer(self):
        if getattr(self, "_math_trainer", None) is not None:
            return
        if not _MATH_AVAILABLE:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Math Trainer",
                "math_trainer.py not found!\n\nPlace math_trainer.py inside the ui/ folder.")
            return
        mt = MathTrainerPage(parent=self)
        mt.closed.connect(self._hide_math_trainer)
        self._math_trainer = mt
        if self._current_theme == "tmnt" and self._tmnt_layout:
            self._pre_math_tmnt = True
            self.top_frame.hide()
            self._body_stack.addWidget(mt)
            self._body_stack.setCurrentWidget(mt)
        else:
            self._pre_math_tmnt = False
            split = self._get_splitter()
            if split is None:
                return
            self._pre_math_sizes = split.sizes()
            split.replaceWidget(1, mt)
            mt.show()
            split.setSizes([split.sizes()[0], split.width(), 0])

    def _hide_math_trainer(self):
        mt = getattr(self, "_math_trainer", None)
        self._math_trainer = None
        if not mt:
            return
        if getattr(self, "_pre_math_tmnt", False) and self._tmnt_layout:
            self._body_stack.removeWidget(mt)
            mt.setParent(None)
            mt.deleteLater()
            self._body_stack.setCurrentIndex(1)
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

    def _show_about(self):
        AboutDialog(self).exec_()

    def _show_help(self):
        OnboardingDialog(self).exec_()

    def _create_tmnt_layout(self):
        layout = TMNTHomeLayout(self._data, self.deck_view, parent=self)
        layout.btn_math_clicked.connect(self._show_math_trainer)
        layout.btn_journal_clicked.connect(self._show_journal)
        layout.btn_theme_clicked.connect(self._toggle_theme)
        layout.btn_help_clicked.connect(self._show_help)
        layout.btn_about_clicked.connect(self._show_about)
        layout.font_change.connect(self._emit_font)
        layout.bgm_toggle.connect(self._toggle_tmnt_bgm)
        layout.set_bgm_state(self.music_widget._playing)
        return layout

    def rebuild_tmnt_layout(self):
        if not _TMNT_HOME_AVAILABLE or self._tmnt_layout is None:
            return
        current = self._body_stack.currentWidget()
        if current is not self._tmnt_layout:
            return
        selected = self._tmnt_layout.get_selected_deck()
        selected_id = selected.get("_id") if selected else None
        old = self._tmnt_layout
        self._tmnt_layout = self._create_tmnt_layout()
        self._body_stack.insertWidget(1, self._tmnt_layout)
        self._body_stack.setCurrentWidget(self._tmnt_layout)
        self._body_stack.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        if selected_id:
            self._tmnt_layout.select_deck_by_id(selected_id)

    def _toggle_tmnt_bgm(self):
        self.music_widget.toggle()
        if self._tmnt_layout:
            self._tmnt_layout.set_bgm_state(self.music_widget._playing)

    def _toggle_theme(self):
        from theme_manager import build_stylesheet
        from PyQt5.QtGui import QFont

        _cycle    = {"classic": "dojo", "dojo": "tmnt", "tmnt": "classic"}
        _btn_next = {"classic": "🥷 NINJA MODE", "dojo": "🐢 TMNT MODE", "tmnt": "📚 CLASSIC MODE"}

        self._current_theme = _cycle.get(self._current_theme, "dojo")
        self._btn_theme.setText(_btn_next.get(self._current_theme, "🥷 NINJA MODE"))
        self._data["_theme"] = self._current_theme
        store.mark_dirty()

        app = QApplication.instance()
        win = self.window()
        current_size = self._data.get("_font_size", BASE_FONT_SIZE)

        if self._current_theme == "tmnt" and self._tmnt_layout:
            # ── Swap to TMNT full layout ──────────────────────────────────────
            self.top_frame.hide()
            win_sb = self.window().statusBar() if self.window() else None
            if win_sb: win_sb.hide()
            self._tmnt_layout.refresh()
            self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            self._body_stack.setCurrentIndex(1)
            if app:
                app._active_theme = "tmnt"
                app.setFont(QFont("Roboto Mono", current_size))
                ss = build_stylesheet("tmnt", current_size)
                app.setStyleSheet(ss)
                if win: win.setStyleSheet(ss)
        else:
            # ── Swap back to splitter (classic / dojo) ───────────────────────
            self.top_frame.show()
            win_sb = self.window().statusBar() if self.window() else None
            if win_sb: win_sb.show()
            self._body_stack.setCurrentIndex(0)
            self.deck_tree.set_theme(self._current_theme)
            self.deck_view.set_theme(self._current_theme)
            self.music_widget.set_theme(self._current_theme)
            self._cache_widget.set_theme(self._current_theme)
            self._apply_topbar_style()
            if app:
                app._active_theme = self._current_theme
                if self._current_theme == "classic":
                    app.setFont(QFont("Segoe UI", current_size))
                    app.setStyleSheet(_build_ss(current_size))
                    if win: win.setStyleSheet("")
                else:
                    app.setFont(QFont(NARUTO_FONT_FAMILY, current_size))
                    ss = build_stylesheet("dojo", current_size)
                    app.setStyleSheet(ss)
                    if win: win.setStyleSheet(ss)

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
        elif key == Qt.Key_M:
            self.music_widget.toggle()
            if self._tmnt_layout:
                self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            e.accept()
            return
        elif key == Qt.Key_N:
            self.music_widget.next_track()
            if self._tmnt_layout:
                self._tmnt_layout.set_bgm_state(self.music_widget._playing)
            e.accept()
            return

        super().keyPressEvent(e)   # ← yeh already hai, sirf usse pehle add karo

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

    def refresh(self):
        if self._current_theme == "tmnt" and self._tmnt_layout:
            self._tmnt_layout.refresh()
        else:
            self.deck_tree.refresh()
            sel = self.deck_tree.get_selected_deck()
            if sel:
                self.deck_view.load_deck(sel, self._data)


# ═══════════════════════════════════════════════════════════════════════════════
