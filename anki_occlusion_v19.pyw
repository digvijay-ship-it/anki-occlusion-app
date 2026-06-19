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
import time
APP_START_TIME = time.perf_counter()

import sys
import os
import re
import traceback
from datetime import datetime

# Ensure script directory is in sys.path for robust local imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

_LOG_FILE_HANDLE = None

def _scrub_traceback(tb_text: str) -> str:
    # Redact bearer tokens
    tb_text = re.sub(r'ya29\.[A-Za-z0-9_-]+', '[REDACTED BEARER TOKEN]', tb_text)
    # Redact client_secret value, e.g. client_secret='xyz' or client_secret: "xyz"
    tb_text = re.sub(
        r'(client_secret[\'"]?\s*[:=]\s*[\'"])[^\'"]+([\'"])',
        r'\1[REDACTED SECRET]\2',
        tb_text,
        flags=re.IGNORECASE
    )
    # Redact Authorization header values, e.g. Authorization: Bearer xyz
    tb_text = re.sub(
        r'(authorization[\'"]?\s*[:=]\s*[\'"]Bearer\s+)[^\'"]+([\'"])',
        r'\1[REDACTED BEARER TOKEN]\2',
        tb_text,
        flags=re.IGNORECASE
    )
    # Redact client secret from JSON/dict output, e.g. "client_secret": "xyz"
    tb_text = re.sub(
        r'("client_secret"\s*:\s*")[^"]+(")',
        r'\1[REDACTED SECRET]\2',
        tb_text,
        flags=re.IGNORECASE
    )
    return tb_text

def setup_logging():
    try:
        app_data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AnkiOcclusion")
        if not os.path.exists(app_data_dir):
            os.makedirs(app_data_dir, exist_ok=True)
            
        log_file_path = os.path.join(app_data_dir, "anki_occlusion.log")
        prev_log_path = os.path.join(app_data_dir, "anki_occlusion_prev.log")
        
        # Rotate previous log
        rotated = False
        if os.path.exists(log_file_path):
            try:
                if os.path.exists(prev_log_path):
                    os.remove(prev_log_path)
                os.rename(log_file_path, prev_log_path)
                rotated = True
            except Exception:
                pass
            
        mode = "w" if rotated or not os.path.exists(log_file_path) else "a"
        global _LOG_FILE_HANDLE
        log_file = open(log_file_path, mode, encoding="utf-8", buffering=1)
        _LOG_FILE_HANDLE = log_file
        log_file.write(f"\n--- App Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        
        class TeeStream:
            def __init__(self, original, file_s):
                self.original = original
                self.file_s = file_s
            def write(self, data):
                if self.original is not None:
                    try: self.original.write(data)
                    except Exception: pass
                try:
                    self.file_s.write(data)
                    self.file_s.flush()
                except Exception: pass
            def flush(self):
                if self.original is not None:
                    try: self.original.flush()
                    except Exception: pass
                try: self.file_s.flush()
                except Exception: pass

        sys.stdout = TeeStream(sys.stdout, log_file)
        sys.stderr = TeeStream(sys.stderr, log_file)

        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return

            # Try to scrub f_locals from stack frames
            tb = exc_traceback
            while tb:
                try:
                    frame = tb.tb_frame
                    for key in list(frame.f_locals.keys()):
                        if any(k in key.lower() for k in ("secret", "token", "auth", "password", "key")):
                            try:
                                frame.f_locals[key] = "[REDACTED]"
                            except Exception:
                                pass
                except Exception:
                    pass
                tb = tb.tb_next

            err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            err_msg = _scrub_traceback(err_msg)
            sys.stderr.write("CRITICAL UNHANDLED EXCEPTION:\n" + err_msg + "\n")
            
        sys.excepthook = handle_exception
        print("Logging initialized. Log file: " + log_file_path)
    except Exception as e:
        sys.__stderr__.write("Failed to initialize logging: " + str(e) + "\n")

setup_logging()

from debug_output import install_debug_output_filter

install_debug_output_filter()

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
from storage_paths import app_base_dir, app_resource_path, initialize_mission_archive

import importlib.util
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

NARUTO_FONT_FAMILY = "Segoe UI"


def load_custom_fonts():
    if not QApplication.instance():
        return
    global NARUTO_FONT_FAMILY
    print("[DEBUG][theme] ninja_font_skipped")
    font_paths = [
        app_resource_path("assets", "fonts", "PressStart2P-Regular.ttf"),
        app_resource_path("assets", "fonts", "RobotoMono-Regular.ttf"),
        app_resource_path("assets", "fonts", "Cinzel-Regular.ttf"),
        app_resource_path("assets", "fonts", "Cinzel-Bold.ttf"),
    ]
    print(
        f"[DEBUG][packaging] font_probe frozen={getattr(sys, 'frozen', False)} "
        f"base={app_base_dir()} count={len(font_paths)}"
    )
    for font_path in font_paths:
        if not os.path.exists(font_path):
            continue
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id == -1:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families and font_path.endswith("PressStart2P-Regular.ttf"):
            pass  # reserved for future custom family override


# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

# ── Theme constants — single source of truth is theme_manager.PALETTES["dark"] ──
from theme_manager import get_palette as _get_palette

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


from ui.home_screen import HomeScreen, make_app_icon, OnboardingDialog


def __getattr__(name):
    if name == "ReviewScreen":
        from ui.review_screen import ReviewScreen as _ReviewScreen

        globals()[name] = _ReviewScreen
        return _ReviewScreen
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _pdf_backend_status():
    return (
        "PDF backend: PyMuPDF"
        if importlib.util.find_spec("fitz") is not None
        else "⚠ pip install pymupdf  for PDF support"
    )

#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════


class DataLoaderThread(QThread):
    loaded = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            data = load_data()
            self.loaded.emit(data)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        initialize_mission_archive()
        self.setWindowTitle("Anki Occlusion")
        self.setMinimumSize(1100, 720)
        self.setWindowIcon(make_app_icon())
        self._recovery_prompt_shown = False

        import sys
        is_testing = "unittest" in sys.modules

        if is_testing:
            self._data = load_data()
            self._on_data_loaded(self._data)
        else:
            loading_label = QLabel("Loading database...")
            loading_label.setAlignment(Qt.AlignCenter)
            loading_label.setStyleSheet("font-size: 24px; color: #888; background: #1E1E2E;")
            self.setCentralWidget(loading_label)
            self.showMaximized()

            sb = QStatusBar()
            sb.showMessage("Loading database...")
            self.setStatusBar(sb)

            self._data_thread = DataLoaderThread()
            self._data_thread.loaded.connect(self._on_data_loaded)
            self._data_thread.error.connect(self._on_data_load_error)
            self._data_thread.start()

    def _on_data_loaded(self, data):
        self._data = data
        store.start_autosave()

        self._font_size = int(self._data.get("_font_size", BASE_FONT_SIZE))

        # Apply saved theme/font before building HomeScreen so TMNT widgets
        # construct with the correct cold-start sizing context.
        from theme_manager import normalize_theme

        saved_theme = self._data.get("_theme", "classic")
        theme = normalize_theme(saved_theme)
        app = QApplication.instance()
        if app:
            app._active_theme = theme
            from theme_manager import build_stylesheet

            if theme == "classic":
                app.setFont(QFont("Segoe UI", self._font_size))
                app.setStyleSheet(_build_ss(self._font_size))
                self.setStyleSheet("")
            else:
                if theme == "tmnt":
                    app.setFont(QFont("Roboto Mono", self._font_size))
                elif theme == "arcanum":
                    app.setFont(QFont("Cinzel", self._font_size))
                else:
                    app.setFont(QFont(NARUTO_FONT_FAMILY, self._font_size))
                ss = build_stylesheet(theme, self._font_size)
                app.setStyleSheet(ss)
                self.setStyleSheet(ss)

        home = HomeScreen(self._data, parent=self)
        self.setCentralWidget(home)

        sb = self.statusBar()
        if sb:
            sb.showMessage(f"✅ SM-2 Active  |  {_pdf_backend_status()}")

        if theme == "tmnt" and hasattr(home, "_tmnt_layout") and home._tmnt_layout:
            if hasattr(home._tmnt_layout, "main"):
                home._tmnt_layout.main._font_size_val = self._font_size
            QTimer.singleShot(200, home._tmnt_layout.refresh)

        if not self._data.get("_onboarding_done"):
            QTimer.singleShot(200, self._run_onboarding)
        else:
            QTimer.singleShot(350, self._show_recovery_prompt)

        self._data_thread = None

    def _on_data_load_error(self, err_msg):
        print(f"[main] Failed to load data: {err_msg}")
        sb = self.statusBar()
        if sb:
            sb.showMessage(f"❌ Database load failed: {err_msg}")

        # Replace central widget with an error screen
        error_widget = QWidget()
        import theme_manager
        
        palette = theme_manager.get_palette("dark")
        c_bg = palette["C_BG"]
        c_card = palette["C_CARD"]
        c_text = palette["C_TEXT"]
        c_red = palette["C_RED"]
        c_accent = palette["C_ACCENT"]
        c_subtext = palette["C_SUBTEXT"]
        c_border = palette["C_BORDER"]

        error_widget.setStyleSheet(f"background-color: {c_bg}; color: {c_text};")
        
        layout = QVBoxLayout(error_widget)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)
        
        # Center card/container to hold the elements
        container = QWidget()
        container.setStyleSheet(f"""
            QWidget {{
                background-color: {c_card};
                border: 1px solid {c_border};
                border-radius: 8px;
            }}
        """)
        container.setFixedWidth(500)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(30, 30, 30, 30)
        container_layout.setSpacing(15)
        
        # Title Label
        title_label = QLabel("❌ Failed to load database")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"""
            color: {c_red};
            font-size: 20px;
            font-weight: bold;
            border: none;
            background: transparent;
        """)
        container_layout.addWidget(title_label)
        
        # Error message label
        msg_label = QLabel(err_msg)
        msg_label.setAlignment(Qt.AlignCenter)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"""
            color: {c_subtext};
            font-size: 14px;
            border: none;
            background: transparent;
        """)
        container_layout.addWidget(msg_label)
        
        # Spacer
        container_layout.addSpacing(10)
        
        # Button layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        # Retry button
        btn_retry = QPushButton("Retry")
        btn_retry.setCursor(Qt.PointingHandCursor)
        btn_retry.setStyleSheet(f"""
            QPushButton {{
                background-color: {c_accent};
                color: #FFFFFF;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #9284F9;
            }}
        """)
        
        # Quit button
        btn_quit = QPushButton("Quit")
        btn_quit.setCursor(Qt.PointingHandCursor)
        btn_quit.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_text};
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 4px;
                border: 1px solid {c_border};
            }}
            QPushButton:hover {{
                background-color: {c_border};
            }}
        """)
        
        btn_layout.addWidget(btn_retry)
        btn_layout.addWidget(btn_quit)
        container_layout.addLayout(btn_layout)
        
        layout.addWidget(container)
        
        self.setCentralWidget(error_widget)

        def on_retry():
            # 1. Clear store's in-memory data
            with store._lock:
                store._data = {"decks": []}
                store._card_index = {}
                store._dirty = False
            
            # 2. Swap central widget back to a fresh loading label
            loading_label = QLabel("Loading database...")
            loading_label.setAlignment(Qt.AlignCenter)
            loading_label.setStyleSheet("font-size: 24px; color: #888; background: #1E1E2E;")
            self.setCentralWidget(loading_label)
            
            sb = self.statusBar()
            if sb:
                sb.showMessage("Loading database...")
            
            # 3. Recreate and start a new DataLoaderThread
            self._data_thread = DataLoaderThread()
            self._data_thread.loaded.connect(self._on_data_loaded)
            self._data_thread.error.connect(self._on_data_load_error)
            self._data_thread.start()

        btn_retry.clicked.connect(on_retry)
        btn_quit.clicked.connect(QApplication.quit)

        self._data_thread = None

    def change_font_size(self, direction: int):
        if direction == 0:
            self._font_size = BASE_FONT_SIZE
        else:
            self._font_size = max(8, min(20, self._font_size + direction))
        self._data["_font_size"] = self._font_size

        from theme_manager import build_stylesheet

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        print(
            f"[DEBUG] change_font_size called! Active theme: {theme}, Font size: {self._font_size}"
        )

        if theme == "classic":
            ss = _build_ss(self._font_size)
            app.setStyleSheet(ss)
            self.setStyleSheet("")
            print(f"[DEBUG] Classic stylesheet applied.")
        else:
            if theme == "tmnt":
                app.setFont(QFont("Roboto Mono", self._font_size))
            elif theme == "arcanum":
                app.setFont(QFont("Cinzel", self._font_size))
            ss = build_stylesheet(theme, self._font_size)
            app.setStyleSheet(ss)
            self.setStyleSheet(ss)
            print(f"[DEBUG] {theme} stylesheet applied (length: {len(ss)} chars).")

        home = self.centralWidget()
        if home is not None and hasattr(home, "rebuild_tmnt_layout"):
            home.rebuild_tmnt_layout(force=(theme == "tmnt"))
            if theme == "tmnt" and hasattr(home, "_tmnt_layout") and home._tmnt_layout:
                if hasattr(home._tmnt_layout, "main"):
                    home._tmnt_layout.main._font_size_val = self._font_size
                    if getattr(home._tmnt_layout.main, "deck", None):
                        home._tmnt_layout.main._refresh()
            if hasattr(home, "deck_view") and hasattr(
                home.deck_view, "update_font_size"
            ):
                home.deck_view.update_font_size(self._font_size)

        store.save_force()

    def _run_onboarding(self):
        dlg = OnboardingDialog(self)
        dlg.exec_()
        self._data["_onboarding_done"] = True
        store.mark_dirty()  # 🔒 DirtyStore
        QTimer.singleShot(100, self._show_recovery_prompt)

    def _show_recovery_prompt(self):
        if self._recovery_prompt_shown:
            return
        self._recovery_prompt_shown = True
        home = self.centralWidget()
        if home is not None and hasattr(home, "show_recovery_center"):
            home.show_recovery_center(startup=True)

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        
        # Ctrl+? toggle to open shortcuts dialog
        is_ctrl_question = (
            (clean_mods & Qt.ControlModifier) and
            not (clean_mods & Qt.AltModifier) and
            not (clean_mods & Qt.MetaModifier) and
            (key == Qt.Key_Question or (key == Qt.Key_Slash and (clean_mods & Qt.ShiftModifier)))
        )
        if is_ctrl_question:
            home = self.centralWidget()
            if home is not None and hasattr(home, "_show_shortcuts"):
                home._show_shortcuts()
                e.accept()
                return

        from services import shortcut_manager
        home = self.centralWidget()
        
        # 3. Active Review Screen - check dynamically
        if home is not None and getattr(home, "_active_review", None) is not None and shortcut_manager.event_matches(e, "review.cancel"):
            home._active_review.cancelled.emit()
            e.accept()
            return

        if key == Qt.Key_Escape:
            if home is not None:
                # 1. Classic Settings Panel
                if getattr(home, "_classic_settings_panel", None) is not None and home._classic_settings_panel.isVisible():
                    home._classic_settings_panel.hide()
                    e.accept()
                    return
                # 2. TMNT Settings/More Panels
                if getattr(home, "_tmnt_layout", None) is not None and home._tmnt_layout.isVisible():
                    tmnt = home._tmnt_layout
                    panels_closed = False
                    if getattr(tmnt, "_settings_panel", None) is not None and tmnt._settings_panel.isVisible():
                        tmnt._hide_panel(tmnt._settings_panel)
                        panels_closed = True
                    if getattr(tmnt, "_more_panel", None) is not None and tmnt._more_panel.isVisible():
                        tmnt._hide_panel(tmnt._more_panel)
                        panels_closed = True
                    if panels_closed:
                        e.accept()
                        return
                # 4. Math Trainer Page
                if getattr(home, "_math_trainer", None) is not None:
                    home._math_trainer.go_back()
                    e.accept()
                    return
        if key == Qt.Key_F11:
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
        elif mods & Qt.ControlModifier and key in (Qt.Key_Equal, Qt.Key_Plus):
            self.change_font_size(+1)
        elif mods & Qt.ControlModifier and key == Qt.Key_Minus:
            self.change_font_size(-1)
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self.change_font_size(0)
        elif mods & Qt.ControlModifier and key == Qt.Key_C:
            # Ctrl+C → RAM cache clear (disk untouched)
            home = self.centralWidget()
            if home is not None and hasattr(home, "_clear_home_ram_caches"):
                home._clear_home_ram_caches()
            else:
                from cache_manager import PAGE_CACHE
                try:
                    import fitz
                    from pdf_engine import _SKELETON_CACHE, _SKELETON_PLACEHOLDER_CACHE
                    _SKELETON_CACHE.clear()
                    _SKELETON_PLACEHOLDER_CACHE.clear()
                    fitz.TOOLS.store_shrink(100)  # Purge PyMuPDF internal caches
                except Exception as ex:
                    pass
                before = len(PAGE_CACHE._cache)
                PAGE_CACHE.clear_ram_only()
                print(
                    f"[MainWindow][Ctrl+C] 🧹 RAM cache cleared — "
                    f"{before} pages evicted, disk untouched"
                )
                sb = self.statusBar()
                if sb:
                    sb.showMessage(f"🧹 RAM cache cleared — {before} pages freed", 3000)
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        if hasattr(self, "_data_thread") and self._data_thread is not None:
            try:
                if self._data_thread.isRunning():
                    if hasattr(self._data_thread, "stop"):
                        self._data_thread.stop()
                    else:
                        self._data_thread.quit()
                    self._data_thread.wait(2000)
            except Exception as ex:
                print(f"[main] Error joining data thread: {ex}")
            finally:
                self._data_thread = None

        home = self.centralWidget()
        if home is not None:
            active_editor = getattr(home, "_active_editor", None)
            if active_editor is not None:
                active_editor.close()
        store.stop_autosave()  # 🔒 Final force-save + background thread stop
        try:
            from services import recovery_manager
            recovery_manager.flush()
        except Exception as ex:
            print(f"[main] Failed to flush recovery events: {ex}")
        try:
            from services.ocr_engine import shutdown as ocr_shutdown
            ocr_shutdown()
        except Exception:
            pass

        global _LOG_FILE_HANDLE
        if _LOG_FILE_HANDLE is not None:
            try:
                _LOG_FILE_HANDLE.close()
                _LOG_FILE_HANDLE = None
            except Exception:
                pass
        super().closeEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    os.environ["ANKI_ALLOW_DEBUG_LOGS"] = "0"
    os.environ["ANKI_PERF_DEBUG"] = "0"
    os.environ["ANKI_CANVAS_PAINT_PROFILE"] = "0"
    os.environ["ANKI_REVIEW_PROFILE"] = "0"
    os.environ["ANKI_REVIEW_SCROLL_PROFILE"] = "0"
    os.environ["ANKI_REVIEW_VERBOSE"] = "0"
    os.environ["ANKI_ANNOTATION_VERBOSE"] = "0"
    os.environ["ANKI_EDITOR_VERBOSE"] = "0"
    os.environ["ANKI_EDITOR_SCROLL_PROFILE"] = "0"
    os.environ["QT_LOGGING_RULES"] = "qt.multimedia*=false;qt.audio*=false"

    lock = QLockFile(LOCK_FILE)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        app_tmp = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            "Already Running",
            "Anki Occlusion is already open!\nCheck your taskbar.",
        )
        sys.exit(1)

    # Suppress DirectShow codec warnings on Windows — Qt multimedia backend
    # tries to enumerate DirectShow filters on startup; harmless but spammy.
    import os as _os

    _os.environ.setdefault("QT_MULTIMEDIA_PREFERRED_PLUGINS", "windowsmediafoundation")

    app = QApplication(sys.argv)
    load_custom_fonts()
    app.setStyleSheet(SS)
    app.setApplicationName("Anki Occlusion")
    app.setApplicationVersion("1.0")
    _icon = make_app_icon()
    app.setWindowIcon(_icon)
    win = MainWindow()
    win.show()
    print(f"[PROFILE][app_startup] App loaded and ready in {(time.perf_counter() - APP_START_TIME) * 1000:.1f}ms")
    ret = app.exec_()
    lock.unlock()
    sys.exit(ret)
