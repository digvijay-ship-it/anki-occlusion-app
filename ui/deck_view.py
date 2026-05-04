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


class DojoStatsCard(QFrame):
    def __init__(self, title, subtitle, color_hex, parent=None):
        super().__init__(parent)
        self._color_hex = color_hex
        self.setObjectName("dojo_stats_card")
        self.setFixedHeight(100)
        self.setStyleSheet(f"""
            QFrame#dojo_stats_card {{
                background: #181825;
                border-radius: 8px;
                border: 1px solid #1E1E2E;
            }}
        """)
        l = QHBoxLayout(self)
        l.setContentsMargins(20, 16, 20, 16)
        l.setSpacing(16)

        self.icon_lbl = QLabel("★")
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        l.addWidget(self.icon_lbl)

        text_l = QVBoxLayout()
        text_l.setSpacing(0)
        text_l.setAlignment(Qt.AlignVCenter)

        self.val_lbl = QLabel("0")
        self.title_lbl = QLabel(title)
        self.sub_lbl = QLabel(subtitle)

        text_l.addWidget(self.val_lbl)
        text_l.addWidget(self.title_lbl)
        text_l.addWidget(self.sub_lbl)
        l.addLayout(text_l)
        l.addStretch()
        self.update_font_scale(1.0)
        
    def update_font_scale(self, scale: float):
        self.setFixedHeight(int(100 * scale))
        self.icon_lbl.setStyleSheet(f"color: {self._color_hex}; font-size: {int(32 * scale)}px;")
        self.val_lbl.setStyleSheet(f"color: {self._color_hex}; font-size: {int(38 * scale)}px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: -2px;")
        self.title_lbl.setStyleSheet(f"color: #A6ADC8; font-size: {max(8, int(10 * scale))}px; font-weight: 800; font-family: 'Orbitron'; letter-spacing: 1px;")
        self.sub_lbl.setStyleSheet(f"color: #5F627D; font-size: {max(9, int(11 * scale))}px;")

    def set_value(self, val):
        self.val_lbl.setText(str(val))

class DojoMissionBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self.setObjectName("dojo_mission_banner")
        self.setMinimumHeight(140)
        self.setStyleSheet(f"""
            QFrame#dojo_mission_banner {{
                background: #181825;
                border-radius: 8px;
                border: 1px solid #1E1E2E;
            }}
        """)
        l = QHBoxLayout(self)
        l.setContentsMargins(24, 20, 24, 20)
        
        left_l = QVBoxLayout()
        left_l.setSpacing(6)
        
        self.title_lbl = QLabel("⚔ TRAINING MISSION")
        self.desc_lbl = QLabel("Continue your training and defeat the due cards!")
        self.quote_lbl = QLabel("> Cowabunga! 🐢_")
        
        left_l.addWidget(self.title_lbl)
        left_l.addWidget(self.desc_lbl)
        left_l.addWidget(self.quote_lbl)
        left_l.addStretch()
        l.addLayout(left_l)
        l.addStretch()
        
        right_l = QVBoxLayout()
        right_l.setSpacing(8)
        right_l.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        
        self.btn_train = QPushButton("▶ START TRAINING\nREVIEW DUE SCROLLS")
        self.btn_all = QPushButton("  TRAIN SELECTED SCROLL")
        from dojo_assets import DojoAssets
        self.btn_all.setIcon(QIcon(DojoAssets.get().get_ui_icon(2, 32)))
        
        right_l.addWidget(self.btn_train)
        right_l.addWidget(self.btn_all)
        l.addLayout(right_l)

        from PyQt5.QtCore import QTimer
        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._animate_glow)
        self._glow_step = 0
        
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self.btn_train.setGraphicsEffect(self._shadow)
        
        self.update_font_scale(1.0)
        self._glow_timer.start(50)

    def update_font_scale(self, scale: float):
        self._scale = scale
        self.setMinimumHeight(int(140 * scale))
        self.title_lbl.setStyleSheet(f"color: #BD93F9; font-size: {max(9, int(12 * scale))}px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: 2px;")
        self.desc_lbl.setStyleSheet(f"color: #CDD6F4; font-size: {max(11, int(14 * scale))}px;")
        self.quote_lbl.setStyleSheet(f"color: #50FA7B; font-size: {max(9, int(12 * scale))}px; font-weight: bold; font-family: monospace;")
        
        from PyQt5.QtCore import QSize
        self.btn_all.setIconSize(QSize(int(20 * scale), int(20 * scale)))
        self.btn_all.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #50FA7B;
                border: 1px solid #50FA7B;
                border-radius: 6px;
                font-size: {max(9, int(11 * scale))}px;
                font-weight: 900;
                font-family: 'Orbitron';
                letter-spacing: 1px;
                min-height: {int(38 * scale)}px;
                padding: 0px {int(20 * scale)}px;
                text-align: center;
            }}
            QPushButton:hover {{
                background: rgba(80, 250, 123, 0.1);
            }}
        """)
        self._animate_glow()

    def _animate_glow(self):
        import math
        self._glow_step += 1
        progress = (math.sin(self._glow_step * math.pi / 20.0) + 1.0) / 2.0
        
        r = int(32 + (114 - 32) * progress)
        g = int(106 + (255 - 106) * progress)
        b = int(50 + (79 - 50) * progress)
        
        color = f"#{r:02X}{g:02X}{b:02X}"
        scale = getattr(self, '_scale', 1.0)
        self.btn_train.setStyleSheet(f"""
            QPushButton {{
                background: {color};
                color: #0F0F17;
                border-radius: 6px;
                font-weight: 900;
                font-family: 'Orbitron';
                font-size: {max(11, int(14 * scale))}px;
                min-height: {int(52 * scale)}px;
                padding: 0px {int(32 * scale)}px;
                text-align: center;
                border: 1px solid {color};
            }}
            QPushButton:hover {{
                background: #8BFF6B;
                border: 1px solid #8BFF6B;
            }}
        """)
        
        from PyQt5.QtGui import QColor
        blur_radius = 5 + 35 * progress
        shadow_alpha = int(80 + 175 * progress)
        self._shadow.setBlurRadius(blur_radius)
        self._shadow.setColor(QColor(r, g, b, shadow_alpha))


#  DECK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class DeckView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.deck          = None
        self._deck_id      = None
        self._data         = {}
        self._thumb_cache  = {}
        self._undo_stack   = []
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(12, 12, 12, 12)
        L.setSpacing(10)

        self.hdr_w = QFrame()
        self.hdr_w.setObjectName("deck_header")
        hdr = QHBoxLayout(self.hdr_w)
        hdr.setContentsMargins(16, 16, 16, 16)
        hdr.setAlignment(Qt.AlignVCenter)

        self.lbl_deck_icon = QLabel()
        self.lbl_deck_icon.hide()
        hdr.addWidget(self.lbl_deck_icon)
        
        title_l = QVBoxLayout()
        title_l.setSpacing(4)
        title_l.setAlignment(Qt.AlignVCenter)
        self.lbl_deck = QLabel("← Select a deck")
        self.lbl_deck.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self.lbl_deck_sub = QLabel("")
        self.lbl_deck_sub.setStyleSheet("color: #5F627D; font-size: 11px; font-weight: bold; font-family: 'Orbitron'; letter-spacing: 1px;")
        self.lbl_deck_sub.hide()
        title_l.addWidget(self.lbl_deck)
        title_l.addWidget(self.lbl_deck_sub)
        hdr.addLayout(title_l)
        
        hdr.addStretch()
        self.btn_add = QPushButton("＋ Add Card")
        self.btn_add.clicked.connect(self._add_card)
        self.btn_due = QPushButton("🔴 Review Due")
        self.btn_due.setObjectName("danger")
        self.btn_due.clicked.connect(self._review_due)
        self.btn_all = QPushButton("▶ Review")
        self.btn_all.setObjectName("success")
        self.btn_all.clicked.connect(self._review_all)
        hdr.addWidget(self.btn_add)
        hdr.addWidget(self.btn_due)
        hdr.addWidget(self.btn_all)
        L.addWidget(self.hdr_w)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(f"color:{C_SUBTEXT};")
        L.addWidget(self.lbl_stats)

        # --- Container for Stats & Banner ---
        self.dojo_container = QFrame()
        self.dojo_container.setObjectName("dojo_container")
        self.dojo_container.setStyleSheet("""
            QFrame#dojo_container {
                background: #0F0F17;
                border-radius: 12px;
                border: 1px solid #1E1E2E;
            }
        """)
        self.dojo_container.hide()
        dc_layout = QVBoxLayout(self.dojo_container)
        dc_layout.setContentsMargins(16, 16, 16, 16)
        dc_layout.setSpacing(16)

        self.dojo_stats_w = QWidget()
        sl = QHBoxLayout(self.dojo_stats_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(16)
        self.stat_missions = DojoStatsCard("REMAINING MISSIONS", "CARDS DUE FOR REVIEW", "#FF5555")
        self.stat_scrolls = DojoStatsCard("NEW TECHNIQUES", "TOTAL ACTIVE SCROLLS", "#BD93F9")
        self.stat_battles = DojoStatsCard("BATTLES WON", "REVIEWS COMPLETED", "#50FA7B")
        sl.addWidget(self.stat_missions)
        sl.addWidget(self.stat_scrolls)
        sl.addWidget(self.stat_battles)
        dc_layout.addWidget(self.dojo_stats_w)

        self.dojo_banner = DojoMissionBanner()
        self.dojo_banner.btn_train.clicked.connect(self._review_due)
        self.dojo_banner.btn_all.clicked.connect(self._review_all)
        dc_layout.addWidget(self.dojo_banner)

        L.addWidget(self.dojo_container)

        self.card_list = QListWidget()
        self.card_list.setIconSize(QSize(64, 48))
        self.card_list.itemDoubleClicked.connect(self._edit_card)
        self.card_list.keyPressEvent = self._card_list_key_press
        self.card_list.setDragEnabled(True)
        self.card_list.setDragDropMode(QAbstractItemView.DragOnly)
        self.card_list.startDrag = self._start_card_drag
        L.addWidget(self.card_list, stretch=1)


        bot = QHBoxLayout()
        be  = QPushButton("✏ Edit")
        be.setObjectName("flat")
        be.clicked.connect(lambda: self._edit_card(self.card_list.currentItem()))
        bd  = QPushButton("🗑 Delete")
        bd.setObjectName("danger")
        bd.clicked.connect(self._delete_card)
        bot.addWidget(be)
        bot.addWidget(bd)
        bot.addStretch()
        L.addLayout(bot)

    def update_font_size(self, size: int):
        self._font_size_val = size
        scale = size / 11.0 # 11 is BASE_FONT_SIZE
        if hasattr(self, 'stat_missions'):
            self.stat_missions.update_font_scale(scale)
            self.stat_scrolls.update_font_scale(scale)
            self.stat_battles.update_font_scale(scale)
            self.dojo_banner.update_font_scale(scale)
            
        if self._theme == "dojo":
            self.lbl_deck.setStyleSheet(f"color: #72FF4F; font-size: {int(24 * scale)}px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: 2px;")
            self.btn_add.setStyleSheet(f"QPushButton{{background:transparent;border:2px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:8px 16px;font-family:'Segoe UI';font-weight:bold;font-size:{max(10, int(12 * scale))}px;letter-spacing:1px;text-align:left;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}")
            from dojo_assets import DojoAssets
            self.lbl_deck_icon.setPixmap(DojoAssets.get().get_ui_icon(0, int(48 * scale)).scaled(int(48 * scale), int(48 * scale), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._refresh()

    def set_theme(self, theme):
        from dojo_assets import DojoAssets
        self._theme = theme
        if theme == "dojo":
            self.lbl_deck_sub.show()
            self.lbl_deck_icon.show()
            self.dojo_container.show()
            self.dojo_stats_w.show()
            self.dojo_banner.show()
            self.lbl_stats.hide()
            
            self.btn_due.hide()
            self.btn_all.hide()
            
            self.lbl_deck.setStyleSheet("color: #72FF4F; font-size: 24px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: 2px;")
            if not self.deck:
                self.lbl_deck.setText("CHOOSE YOUR DOJO NINJA! 🤺")
            
            deck_icon_px = DojoAssets.get().get_ui_icon(0, 48)
            self.lbl_deck_icon.setPixmap(deck_icon_px.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))

            self.btn_add.setText(" FORGE SCROLL")
            self.btn_add.setIcon(QIcon(DojoAssets.get().get_ui_icon(0, 32)))
            self.btn_add.setIconSize(QSize(24, 24))
            self.btn_add.setStyleSheet(f"QPushButton{{background:transparent;border:2px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:8px 16px;font-family:'Segoe UI';font-weight:bold;font-size:12px;letter-spacing:1px;text-align:left;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}")
            
        else:
            self.lbl_deck_sub.hide()
            self.lbl_deck_icon.hide()
            self.dojo_container.hide()
            self.dojo_stats_w.hide()
            self.dojo_banner.hide()
            self.lbl_stats.show()
            
            self.btn_due.show()
            self.btn_all.show()
            
            self.lbl_deck.setStyleSheet("")
            self.lbl_deck.setFont(QFont("Segoe UI", 15, QFont.Bold))
            if not self.deck:
                self.lbl_deck.setText("← Select a deck")

            self.btn_add.setText("＋ Add Card")
            self.btn_add.setIcon(QIcon())
            self.btn_add.setStyleSheet("")
            
            self.btn_all.setText("▶ Review")
            self.btn_all.setIcon(QIcon())
            self.btn_all.setStyleSheet("")
            self.btn_all.setObjectName("success")
            
            self.btn_due.setText("🔴 Review Due")
            self.btn_due.setIcon(QIcon())
            self.btn_due.setStyleSheet("")
            self.btn_due.setObjectName("danger")
            
        self._refresh()

    def _card_list_key_press(self, e):
        key = e.key()
        mods = e.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.undo()
            return
        if key == Qt.Key_E:
            self._edit_card(self.card_list.currentItem())
        else:
            QListWidget.keyPressEvent(self.card_list, e)

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.undo()
            e.accept()
            return
        super().keyPressEvent(e)

    def _push_undo(self):
        if not self._data:
            return
        self._undo_stack.append((copy.deepcopy(self._data), self._deck_id))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            return
        data_snapshot, deck_id = self._undo_stack.pop()
        self._data = data_snapshot
        self._deck_id = deck_id
        fresh = find_deck_by_id(deck_id, self._data.get("decks", [])) if deck_id else None
        self.deck = fresh
        if fresh:
            self.lbl_deck.setText(fresh.get("name", "?"))
            self._refresh()
        else:
            self.card_list.clear()
            if getattr(self, '_theme', 'classic') == 'dojo':
                self.lbl_deck.setText("CHOOSE YOUR DOJO NINJA! 🤺")
            else:
                self.lbl_deck.setText("← Select a deck")
        store.mark_dirty()

    def _start_card_drag(self, _actions):
        row = self.card_list.currentRow()
        if row < 0 or not self.deck:
            return
        mime = QMimeData()
        # Encode: src_deck_id|card_index
        payload = f"{self.deck.get('_id')}|{row}".encode()
        mime.setData(CARD_DRAG_MIME, QByteArray(payload))
        drag = QDrag(self.card_list)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def load_deck(self, deck, data):
        self._data = data
        new_id     = deck.get("_id")
        # [FIX] Same deck clicked again — don't clear card list or reset selection
        if new_id == self._deck_id:
            return
        # [PERF FIX] Thumb cache sirf tab clear karo jab deck badla ho
        self._thumb_cache.clear()
        self._undo_stack.clear()
        self._deck_id = new_id
        self.deck     = deck
        self.lbl_deck.setText(deck.get("name", "?"))
        self._refresh()

    def _refresh(self):
        if self._deck_id is not None:
            fresh = find_deck_by_id(self._deck_id, self._data.get("decks", []))
            if fresh:
                self.deck = fresh
        if not self.deck:
            return
        self.card_list.clear()

        scale = getattr(self, '_font_size_val', 11) / 11.0

        def _get_all_cards(d):
            res = list(d.get("cards", []))
            for child in d.get("children", []):
                res.extend(_get_all_cards(child))
            return res

        all_cards  = _get_all_cards(self.deck)
        due_c  = 0
        untouched_c = 0
        mastered_c = 0

        for c in all_cards:
            # [PERF FIX] sm2_init sirf tab call karo jab fields missing hon
            # (setdefault calls skip karna = O(1) per card instead of O(fields))
            if "sched_state" not in c:
                sm2_init(c)
            boxes = c.get("boxes", [])
            
            card_due = False
            card_untouched = True
            card_mastered = False
            
            if not boxes:
                card_due = is_due_today(c)
                if c.get("reviews", 0) > 0: card_untouched = False
                if sm2_days_left(c) > 30: card_mastered = True
            else:
                seen_gids = set()
                all_mastered = True
                has_boxes = False
                for b in boxes:
                    gid = b.get("group_id", "")
                    if gid:
                        if gid not in seen_gids:
                            seen_gids.add(gid)
                            has_boxes = True
                            if is_due_today(b): card_due = True
                            if b.get("reviews", 0) > 0: card_untouched = False
                            if sm2_days_left(b) <= 30: all_mastered = False
                    else:
                        has_boxes = True
                        if is_due_today(b): card_due = True
                        if b.get("reviews", 0) > 0: card_untouched = False
                        if sm2_days_left(b) <= 30: all_mastered = False
                if has_boxes and all_mastered:
                    card_mastered = True

            due_c += card_due
            untouched_c += card_untouched
            mastered_c += card_mastered

        direct_cards = self.deck.get("cards", [])
        for c in direct_cards:
            badge = "🔴 Due" if self._card_has_due_today(c) else f"✅ {sm2_days_left(c)}d"

            # ── Pages count ───────────────────────────────────────────────────
            pdf_path = c.get("pdf_path", "")
            if pdf_path and os.path.exists(pdf_path) and PDF_SUPPORT:
                try:
                    import fitz as _fitz
                    _doc = _fitz.open(pdf_path)
                    n_pages = len(_doc)
                    _doc.close()
                except Exception:
                    n_pages = 0
                pages_str = f"📄{n_pages}p  "
            else:
                pages_str = ""

            # ── Mask count: grouped + individual ─────────────────────────────
            seen_grp  = set()
            n_grouped = 0
            n_indiv   = 0
            boxes = c.get("boxes", [])
            for b in boxes:
                gid = b.get("group_id", "")
                if gid:
                    if gid not in seen_grp:
                        seen_grp.add(gid)
                        n_grouped += 1
                else:
                    n_indiv += 1
            mask_parts = []
            if n_grouped: mask_parts.append(f"{n_grouped}grp")
            if n_indiv:   mask_parts.append(f"{n_indiv}ind")
            mask_str = "🎭" + ("+".join(mask_parts) if mask_parts else "0")

            item  = QListWidgetItem(
                f"  {c.get('title','Untitled')}  "
                f"| {pages_str}{mask_str}  "
                f"| Rep:{c.get('sm2_repetitions',0)}  "
                f"| EF:{c.get('sm2_ease',2.5):.2f}  | {badge}")

            img_path = c.get("image_path", "")
            if img_path and os.path.exists(img_path):
                if img_path not in self._thumb_cache:
                    px = QPixmap(img_path).scaled(
                        64, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._thumb_cache[img_path] = QIcon(px)
                item.setIcon(self._thumb_cache[img_path])

            self.card_list.addItem(item)

        total_rev = sum(c.get("reviews", 0) for c in all_cards)
        self.lbl_stats.setText(
            f"Cards:{len(all_cards)}  🔴Due:{due_c}  Reviews:{total_rev}")
        
        self.lbl_deck_sub.setText(f"SCROLLS: {len(all_cards)} ❖ DUE: {due_c}")
        self.stat_missions.set_value(due_c)
        self.stat_scrolls.set_value(untouched_c)
        self.stat_battles.set_value(total_rev)

        if not direct_cards and getattr(self, '_theme', 'classic') == 'dojo':
            # Empty state for Dojo mode
            item = QListWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(QFont('Orbitron', int(14 * scale), QFont.Bold))
            item.setForeground(QBrush(QColor("#45475A")))
            item.setText("\n\n★\n- SELECT A SCROLL TO BEGIN -\n")
            self.card_list.addItem(item)

    def _add_card(self):
        if not self.deck:
            return
        self._push_undo()
        dlg = CardEditorDialog(self, data=self._data, deck=self.deck)
        if dlg.exec_() != QDialog.Accepted:
            self._undo_stack.pop() if self._undo_stack else None
            return
        card         = dlg.get_card()
        subdeck_name = card.pop("_auto_subdeck", None)

        if subdeck_name:
            target_deck = None
            for child in self.deck.get("children", []):
                if child.get("name", "").strip().lower() == subdeck_name.strip().lower():
                    target_deck = child
                    break
            if target_deck is None:
                target_deck = {
                    "_id":      next_deck_id(self._data),
                    "name":     subdeck_name,
                    "cards":    [],
                    "children": [],
                    "created":  datetime.now().isoformat(),
                }
                self.deck.setdefault("children", []).append(target_deck)
            target_deck.setdefault("cards", []).append(card)
        else:
            self.deck.setdefault("cards", []).append(card)

        home = self._find_home()
        if home:
            home.refresh()
        else:
            self._refresh()
        store.mark_dirty()  # 🔒 DirtyStore

    def _find_home(self):
        from ui.home_screen import HomeScreen
        w = self.parent()
        while w is not None:
            if isinstance(w, HomeScreen):
                return w
            w = w.parent()
        return None

    def _edit_card(self, item):
        if not item or not self.deck:
            return
        idx   = self.card_list.row(item)
        cards = self.deck.get("cards", [])
        if not 0 <= idx < len(cards):
            return
        self._push_undo()
        dlg = CardEditorDialog(self, card=dict(cards[idx]), data=self._data, deck=self.deck)
        if dlg.exec_() == QDialog.Accepted:
            c = dlg.get_card()
            c.pop("_auto_subdeck", None)
            # [FIX] Preserve SM-2 data — editor returns fresh box dicts without
            # SM-2 fields. Merge SM-2 state from old boxes into new ones by box_id.
            old_boxes_by_id = {b.get("box_id", ""): b for b in cards[idx].get("boxes", [])}
            SM2_KEYS = ("sched_state", "sched_step", "sm2_interval", "sm2_ease",
                        "sm2_due", "sm2_last_quality", "sm2_repetitions", "reviews")
            for new_box in c.get("boxes", []):
                bid = new_box.get("box_id", "")
                if bid and bid in old_boxes_by_id:
                    old = old_boxes_by_id[bid]
                    for k in SM2_KEYS:
                        if k in old:
                            new_box[k] = old[k]
            cards[idx] = c
            self._refresh()
            store.mark_dirty()
        else:
            self._undo_stack.pop() if self._undo_stack else None

    def _delete_card(self):
        if not self.deck:
            return
        idx   = self.card_list.currentRow()
        cards = self.deck.get("cards", [])
        if not 0 <= idx < len(cards):
            return
        if QMessageBox.question(self, "Delete", "Delete this card?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._push_undo()
            cards.pop(idx)
            self._refresh()
            store.mark_dirty()  # 🔒 DirtyStore

    def _card_has_due_today(self, card):
        boxes = card.get("boxes", [])
        if not boxes:
            sm2_init(card)
            return is_due_today(card)
        seen_gids = set()
        for b in boxes:
            sm2_init(b)
            gid = b.get("group_id", "")
            if gid:
                if gid not in seen_gids:
                    seen_gids.add(gid)
                    if is_due_today(b):
                        return True
            else:
                if is_due_today(b):
                    return True
        return False

    def _collect_due_by_pdf(self, deck):
        """Recursively collect due cards from deck+children, grouped by pdf_path.
        Returns a list of card-lists, one per unique PDF, in DFS order."""
        from collections import OrderedDict
        groups = OrderedDict()
        def _walk(d):
            for card in d.get("cards", []):
                if self._card_has_due_today(card):
                    key = card.get("pdf_path") or card.get("image_path") or "__no_path__"
                    groups.setdefault(key, []).append(card)
            for child in d.get("children", []):
                _walk(child)
        _walk(deck)
        return list(groups.values())

    def _review_due(self):
        if not self.deck:
            return
        if self.deck.get("children"):
            # Parent deck: group due cards by PDF and review sequentially
            groups = self._collect_due_by_pdf(self.deck)
            if not groups:
                QMessageBox.information(self, "✅ All clear!",
                    "No cards due today.\nCome back tomorrow! 🌙")
                return
            home = self._find_home()
            if home:
                home.show_review_sequential(groups, self._data)
        else:
            due = [c for c in self.deck.get("cards", []) if self._card_has_due_today(c)]
            if not due:
                QMessageBox.information(self, "✅ All clear!",
                    "No cards due today.\nCome back tomorrow! 🌙")
                return
            self._start_review(due)

    def _review_all(self):
        if not self.deck:
            return
        cards = self.deck.get("cards", [])
        if not cards:
            QMessageBox.information(self, "Empty", "Add some cards first!")
            return
        self._start_review(cards)

    def _start_review(self, cards):
        home = self._find_home()
        if home:
            home.show_review(cards, self._data)


# ═══════════════════════════════════════════════════════════════════════════════
