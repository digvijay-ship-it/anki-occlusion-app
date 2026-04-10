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

from pdf_engine import (
    PDF_SUPPORT, PAGE_CACHE, PdfLoaderThread, pdf_page_to_pixmap
)

from editor_ui import CardEditorDialog,OcclusionCanvas,_ZoomableScrollArea

import fitz

from data_manager import (
    load_data, save_data, find_deck_by_id, next_deck_id, new_box_id,
    DATA_FILE, store
)

import sys, os, copy, uuid, math
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
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QRectF, QPointF, pyqtSignal, QLockFile, QTimer, QModelIndex, QFileSystemWatcher, QThread, QEvent
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QCursor, QIcon, QBrush, QTransform, QPainterPath
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


# ═══════════════════════════════════════════════════════════════════════════════
#  REVIEW SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

QUEUE_ROLE = Qt.UserRole + 10

class QueueDelegate(QStyledItemDelegate):
    COLORS = {
        "current": {"bg": QColor(C_GREEN),    "fg": QColor("#1E1E2E")},
        "done":    {"bg": QColor("#2A3A2A"),  "fg": QColor("#6A8A6A")},
        "pending": {"bg": QColor(C_SURFACE),  "fg": QColor(C_TEXT)},
        "relearn": {"bg": QColor("#3A2A1A"),  "fg": QColor("#E08030")},
    }

    def paint(self, painter, option, index):
        state = index.data(QUEUE_ROLE) or "pending"
        cols  = self.COLORS[state]
        painter.save()
        r = option.rect.adjusted(2, 2, -2, -2)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cols["bg"]))
        painter.drawRoundedRect(r, 5, 5)
        if state == "current":
            painter.setBrush(QBrush(QColor("#1E1E2E")))
            painter.drawRect(r.left(), r.top() + 4, 4, r.height() - 8)
        painter.setPen(cols["fg"])
        font = painter.font()
        font.setBold(state == "current")
        painter.setFont(font)
        painter.drawText(r.adjusted(10, 0, -4, 0), Qt.AlignVCenter, index.data())
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 34)


class ReviewScreen(QWidget):
    finished = pyqtSignal()

    RATINGS = [
        ("1  🔁 Again", "danger",  1),
        ("2  😓 Hard",  "hard",    3),
        ("3  ✅ Good",  "success", 4),
        ("4  ⚡ Easy",  "warning", 5),
    ]

    def __init__(self, cards, data=None, parent=None):
        super().__init__(parent)
        self._data           = data
        self._items          = []
        self._pdf_cache      = {}
        self._current_pixmap = None

        seen_item_keys = set()

        for card in cards:
            boxes = card.get("boxes", [])
            card_key = id(card)

            if len(boxes) == 0:
                item_key = (card_key, None)
                if item_key not in seen_item_keys:
                    seen_item_keys.add(item_key)
                    sm2_init(card)
                    self._items.append((card, None, card))
                continue

            seen_groups = set()

            for i, box in enumerate(boxes):
                sm2_init(box)
                gid = box.get("group_id", "")

                if gid:
                    if gid not in seen_groups:
                        seen_groups.add(gid)
                        item_key = (card_key, ("group", gid))
                        if item_key not in seen_item_keys:
                            seen_item_keys.add(item_key)
                            if is_due_today(box):
                                self._items.append((card, ("group", gid), box))
                else:
                    box_id = box.get("box_id", f"__idx_{i}")
                    item_key = (card_key, box_id)
                    if item_key not in seen_item_keys:
                        seen_item_keys.add(item_key)
                        if is_due_today(box):
                            self._items.append((card, i, box))

        self._items.sort(key=lambda x: x[2].get("sm2_due", ""))
        self._idx  = 0
        self._done = 0
        self._setup_ui()
        self._load_item()

    def closeEvent(self, e):
        if hasattr(self, '_pdf_loader_thread') and self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000) 
        
        if hasattr(self, '_stop_watch'):
            self._stop_watch()
            
        super().closeEvent(e)

    def _load_item(self):
        if self._idx >= len(self._items):
            self._finish()
            return

        card, box_idx, sm2_obj = self._items[self._idx]
        self._rebuild_queue()           # sync queue panel on every card load

        # UI updates...
        self.prog.setMaximum(len(self._items))
        self.prog.setValue(self._idx)
        self.lbl_prog.setText(f"Card {self._idx + 1}/{len(self._items)}")
        self.lbl_sm2.setText(sm2_badge(sm2_obj))
        self.lbl_title.setText(card.get("title", "Untitled"))

        # 🚀 SM-2 SIMULATION UPDATE (Fix for the '?' bug)
        # Ye part calculate karega ki Again/Good/Easy dabane par next date kya hogi
        previews = _fmt_due_interval(sm2_obj)
        for lbl, q in self._prev_lbls:
            val = previews.get(q, "?")
            lbl.setText(f"→ {val}")

        self._reload_current_canvas()
        self.canvas.setFocus() # यह पक्का करेगा कि Keyboard Commands सीधे Canvas पकड़ें

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        if key == Qt.Key_F11:
            win = self.window()
            if win.isFullScreen():
                win.showMaximized()
                self._set_fullscreen_ui(False)
            else:
                win.showFullScreen()
                self._set_fullscreen_ui(True)
        elif key == Qt.Key_Escape:
            self.window().close()
        elif key == Qt.Key_Space:
            self._reveal_current()
            self._debug_report("Space (reveal)")
        elif key == Qt.Key_1 and self._rating_frame.isVisible():
            self._rate(1)
        elif key == Qt.Key_2 and self._rating_frame.isVisible():
            self._rate(3)
        elif key == Qt.Key_3 and self._rating_frame.isVisible():
            self._rate(4)
        elif key == Qt.Key_4 and self._rating_frame.isVisible():
            self._rate(5)
        elif mods & Qt.ControlModifier and key in (Qt.Key_Equal, Qt.Key_Plus):
            self.canvas.zoom_in()
        elif mods & Qt.ControlModifier and key == Qt.Key_Minus:
            self.canvas.zoom_out()
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self._zoom_fit()
        elif key == Qt.Key_C:
            # Ensure canvas has focus so it can calculate target rects
            self._zoom_fit()
            self._center_on_target()
            self._debug_report("C key")
        elif key == Qt.Key_D and not e.isAutoRepeat():
            self._debug_report("D key (manual)")
        elif key == Qt.Key_E:
            self._edit_current_card()
        # ── INK LAYER SHORTCUTS ──────────────────────────────────────────────
        elif (key == Qt.Key_Alt or key == Qt.Key_QuoteLeft) and not e.isAutoRepeat():
            self.canvas.ink_toggle()
            active = self.canvas._ink_active
            color  = self.canvas._ink_colors[self.canvas._ink_color_idx]
            self.canvas._show_toast(f"✏ Pen {'ON' if active else 'OFF'}  {color if active else ''}")
            self._update_ink_hint()
        elif key == Qt.Key_X and not e.isAutoRepeat():
            if self.canvas._ink_active:
                self.canvas.ink_cycle_color()
        elif key == Qt.Key_Delete and not e.isAutoRepeat():
            self.canvas.ink_clear()
        else:
            super().keyPressEvent(e)

    def _reveal_current(self):
        if not (0 <= self._idx < len(self._items)):
            return
        _, box_idx, _ = self._items[self._idx]
        if box_idx is None:
            self.canvas.reveal_all()
        elif isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for b in self.canvas._boxes:
                if b.get("group_id", "") == gid:
                    b["revealed"] = True
            self.canvas._redraw()
        else:
            if 0 <= box_idx < len(self.canvas._boxes):
                self.canvas._boxes[box_idx]["revealed"] = True
                self.canvas._redraw()
        self._reveal_bar.hide()
        self._rating_frame.show()

    def _set_fullscreen_ui(self, fullscreen: bool):
        self._hdr_widget.setVisible(not fullscreen)
        self.lbl_title.setVisible(not fullscreen)
        self._hint_label.setVisible(not fullscreen)

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        hdr_w = QFrame()
        hdr_w.setFixedHeight(46)
        hdr_w.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-bottom:1px solid {C_BORDER};border-radius:0;}}")
        hdr = QHBoxLayout(hdr_w)
        hdr.setContentsMargins(14, 0, 14, 0); hdr.setSpacing(10)

        self.lbl_prog = QLabel("Card 1/1")
        self.lbl_prog.setFont(QFont("Segoe UI", 12, QFont.Bold))
        hdr.addWidget(self.lbl_prog)

        self.prog = QProgressBar()
        self.prog.setFixedHeight(8)
        self.prog.setTextVisible(False)
        self.prog.setStyleSheet(
            f"QProgressBar{{background:{C_CARD};border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{C_ACCENT};border-radius:4px;}}")
        hdr.addWidget(self.prog, stretch=1)

        self.lbl_sm2 = QLabel("")
        self.lbl_sm2.setStyleSheet(
            f"background:{C_CARD};color:{C_SUBTEXT};"
            f"border-radius:6px;padding:3px 10px;font-size:11px;")
        hdr.addWidget(self.lbl_sm2)

        def _zb(txt, tip):
            b = QPushButton(txt); b.setToolTip(tip)
            b.setFixedSize(28, 28)
            b.setStyleSheet(
                f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
                f"border:1px solid {C_BORDER};border-radius:5px;font-size:13px;}}"
                f"QPushButton:hover{{background:{C_SURFACE};}}")
            return b
        b_zin  = _zb("+", "Zoom In  Ctrl++")
        b_zout = _zb("−", "Zoom Out  Ctrl+−")
        b_zfit = _zb("⊡", "Zoom Fit  Ctrl+0")
        b_center = _zb("⊕", "Center on active mask")
        b_zin.clicked.connect(lambda: self.canvas.zoom_in())
        b_zout.clicked.connect(lambda: self.canvas.zoom_out())
        b_zfit.clicked.connect(self._zoom_fit)
        b_center.clicked.connect(self._center_on_target)
        hdr.addWidget(b_zin); hdr.addWidget(b_zout)
        hdr.addWidget(b_zfit); hdr.addWidget(b_center)

        b_edit = QPushButton("✏ Edit Card")
        b_edit.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:white;border:none;"
            f"border-radius:6px;padding:4px 14px;font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:#6A58E0;}}")
        b_edit.clicked.connect(self._edit_current_card)
        hdr.addWidget(b_edit)

        self._btn_mode = QPushButton("🟧 Hide All, Guess One")
        self._btn_mode.setCheckable(True)
        self._btn_mode.setChecked(False)
        self._btn_mode.setStyleSheet(
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 14px;font-size:12px;}}"
            f"QPushButton:checked{{background:#6A3FBF;color:white;"
            f"border:1px solid {C_ACCENT};}}"
            f"QPushButton:hover{{background:{C_SURFACE};}}")
        self._btn_mode.clicked.connect(self._toggle_review_mode)
        hdr.addWidget(self._btn_mode)

        b_exit = QPushButton("✕ Exit")
        b_exit.setStyleSheet(
            f"background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};"
            f"border-radius:6px;padding:4px 14px;font-size:12px;")
        b_exit.clicked.connect(self.finished.emit)
        hdr.addWidget(b_exit)
        L.addWidget(hdr_w)
        self._hdr_widget = hdr_w

        self.lbl_title = QLabel("")
        self.lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_title.setStyleSheet(
            f"color:{C_ACCENT};background:{C_BG};"
            f"padding:4px 16px;border-bottom:1px solid {C_BORDER};")
        self.lbl_title.setFixedHeight(30)
        L.addWidget(self.lbl_title)

        self._canvas_scroll = _ZoomableScrollArea()
        # setWidgetResizable(False) — canvas apni natural size maintain kare,
        # scroll area use stretch na kare (otherwise PDF too wide dikhta hai)
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._canvas_scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C_BG};}}"
            f"QScrollBar:vertical{{background:{C_SURFACE};width:8px;border-radius:4px;}}"
            f"QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:4px;}}"
            f"QScrollBar:horizontal{{background:{C_SURFACE};height:8px;border-radius:4px;}}"
            f"QScrollBar::handle:horizontal{{background:{C_BORDER};border-radius:4px;}}")
        self.canvas = OcclusionCanvas()
        self.canvas.set_mode("review")
        self._canvas_scroll.setWidget(self.canvas)
        self._canvas_scroll.set_canvas(self.canvas)

        # ── Queue panel (right sidebar) ──────────────────────────────────
        queue_panel = QWidget()
        queue_panel.setFixedWidth(200)
        queue_panel.setStyleSheet(f"background:{C_SURFACE};")
        qp_l = QVBoxLayout(queue_panel)
        qp_l.setContentsMargins(6, 8, 6, 8)
        qp_l.setSpacing(4)
        qp_hdr = QLabel("📋  Queue")
        qp_hdr.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;font-weight:bold;"
            f"padding-bottom:4px;border-bottom:1px solid {C_BORDER};")
        qp_l.addWidget(qp_hdr)
        self._queue_list = QListWidget()
        self._queue_list.setItemDelegate(QueueDelegate(self._queue_list))
        self._queue_list.setFocusPolicy(Qt.NoFocus)
        self._queue_list.setStyleSheet(
            f"QListWidget{{background:{C_SURFACE};border:none;padding:0;}}"
            f"QListWidget::item{{padding:0;}}")
        qp_l.addWidget(self._queue_list, stretch=1)

        mid_split = QSplitter(Qt.Horizontal)
        mid_split.addWidget(self._canvas_scroll)
        mid_split.addWidget(queue_panel)
        mid_split.setSizes([900, 200])
        mid_split.setHandleWidth(1)
        L.addWidget(mid_split, stretch=1)

        bottom_w = QWidget()
        bottom_w.setStyleSheet(f"background:{C_SURFACE};")
        bl = QVBoxLayout(bottom_w)
        bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(0)

        hint = QLabel(
            "Space = reveal  •  1/2/3/4 = rate  •  C = fit+center  •  D = debug  •  Ctrl+Scroll = zoom  •  H = pan  •  Alt = pen  •  X = color  •  Del = clear ink  •  F11")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFixedHeight(22)
        hint.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;"
            f"border-top:1px solid {C_BORDER};padding:2px;")
        bl.addWidget(hint)
        self._hint_label = hint

        self._reveal_bar = QFrame()
        self._reveal_bar.setStyleSheet(f"QFrame{{background:{C_BG};}}")
        rb_l = QHBoxLayout(self._reveal_bar)
        rb_l.setContentsMargins(0, 10, 0, 10)
        b_rev = QPushButton("👁  Show Answer  [Space]")
        b_rev.setStyleSheet(
            f"background:{C_SURFACE};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:10px 60px;font-size:14px;font-weight:bold;")
        b_rev.clicked.connect(self._reveal_current)
        rb_l.addStretch(); rb_l.addWidget(b_rev); rb_l.addStretch()
        bl.addWidget(self._reveal_bar)

        self._rating_frame = QFrame()
        self._rating_frame.setStyleSheet(
            f"QFrame{{background:{C_BG};border-top:1px solid {C_BORDER};}}")
        rfl = QVBoxLayout(self._rating_frame)
        rfl.setContentsMargins(12, 8, 12, 12); rfl.setSpacing(4)

        lq = QLabel("🧠 How well did you remember?")
        lq.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lq.setAlignment(Qt.AlignCenter)
        lq.setStyleSheet(f"color:{C_SUBTEXT};")
        rfl.addWidget(lq)

        br = QHBoxLayout(); br.setSpacing(8)
        RATING_STYLES = {
            "danger":  "background:#5C2A2A;color:#FFB3B3;border:1px solid #7A3535;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "hard":    "background:#5C3D1A;color:#FFCC88;border:1px solid #7A5225;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "success": "background:#1E4A2A;color:#88DDAA;border:1px solid #2A6B3C;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
            "warning": "background:#4A4A1A;color:#E8E888;border:1px solid #66661F;"
                       "border-radius:8px;padding:10px 0;font-size:13px;font-weight:bold;",
        }
        self._rating_btns = []
        for lbl, obj, q in self.RATINGS:
            btn = QPushButton(lbl)
            btn.setStyleSheet(RATING_STYLES.get(obj, ""))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda _, qq=q: self._rate(qq))
            br.addWidget(btn)
            self._rating_btns.append(btn)
        rfl.addLayout(br)

        prev_row = QHBoxLayout(); prev_row.setSpacing(6)
        self._prev_lbls = []
        for _, _, q in self.RATINGS:
            pl = QLabel("→?")
            pl.setAlignment(Qt.AlignCenter)
            pl.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
            prev_row.addWidget(pl)
            self._prev_lbls.append((pl, q))
        rfl.addLayout(prev_row)

        self._rating_frame.hide()
        bl.addWidget(self._rating_frame)

        # ── Waiting state bar (shown when learning cards are pending) ──
        self._wait_bar = QFrame()
        self._wait_bar.setStyleSheet(f"QFrame{{background:{C_BG};}}")
        wb_l = QVBoxLayout(self._wait_bar)
        wb_l.setContentsMargins(0, 16, 0, 16)
        wb_l.setSpacing(6)
        self._wait_lbl_count = QLabel("")
        self._wait_lbl_count.setAlignment(Qt.AlignCenter)
        self._wait_lbl_count.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:bold;background:transparent;")
        self._wait_lbl_countdown = QLabel("")
        self._wait_lbl_countdown.setAlignment(Qt.AlignCenter)
        self._wait_lbl_countdown.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:12px;background:transparent;")
        wb_l.addWidget(self._wait_lbl_count)
        wb_l.addWidget(self._wait_lbl_countdown)
        self._wait_bar.hide()
        bl.addWidget(self._wait_bar)

        L.addWidget(bottom_w)

        self._mid_row_widget = self._reveal_bar

    def _update_ink_hint(self):
        """Flash a small ink-status label near the hint bar."""
        pass   # toast in canvas handles display; placeholder for future status bar

    def _toggle_review_mode(self):
        if self._btn_mode.isChecked():
            self._btn_mode.setText("👁 Hide One, Guess One")
            self.canvas.set_review_style("hide_one")
        else:
            self._btn_mode.setText("🟧 Hide All, Guess One")
            self.canvas.set_review_style("hide_all")

    def _zoom_fit(self):
        vp = self._canvas_scroll.viewport()
        if self.canvas._pages:
            # PDF: fit by width only — user scrolls vertically through pages
            w = self.canvas._total_w
            if w < 1:
                return
            self.canvas._scale = vp.width() / w
        else:
            w, h = self.canvas._canvas_wh()
            if w < 1 or h < 1:
                return
            scale_w = vp.width()  / w
            scale_h = vp.height() / h
            self.canvas._scale = min(scale_w, scale_h)
        self.canvas._on_zoom()
        
    def _center_on_target(self):
        # Force a layout update so viewport dimensions are accurate
        QApplication.processEvents()
        
        vp = self._canvas_scroll.viewport()
        view_w = vp.width()
        view_h = vp.height()
        
        # Canvas se scroll position lo — canvas size se calculate hoti hai,
        # scrollbar.maximum() pe depend nahi karta (jo late update hota hai)
        pos = self.canvas.get_target_scroll_pos(view_w, view_h)
        
        # If target is not set yet (e.g. first load), try to find it from current item
        if pos is None and 0 <= self._idx < len(self._items):
            pos = self.canvas.get_target_scroll_pos(view_w, view_h)

        if pos is None:
            return

        hval, vval = pos
        self._canvas_scroll.horizontalScrollBar().setValue(hval)
        self._canvas_scroll.verticalScrollBar().setValue(vval)

    def _debug_report(self, trigger: str = "manual"):
        """
        Press D in review screen to print a full diagnostic report to terminal.
        Also called automatically on C and Space.

        Covers:
          - Which widget has keyboard focus
          - Canvas scale, size, logical size
          - Viewport size
          - Scroll position (current H/V values and maximums)
          - Target mask rect (scaled) and computed scroll-to position
          - Current card index, box_idx, sm2 state
          - Reveal bar / rating frame visibility
          - PDF path + page count in cache
        """
        import time
        sep = "─" * 60
        vp      = self._canvas_scroll.viewport()
        view_w  = vp.width()
        view_h  = vp.height()
        hsb     = self._canvas_scroll.horizontalScrollBar()
        vsb     = self._canvas_scroll.verticalScrollBar()
        cw, ch  = self.canvas._canvas_wh()
        focused = QApplication.focusWidget()

        lines = [
            "",
            sep,
            f"  🔍 DEBUG REPORT  —  trigger: [{trigger}]  @ {time.strftime('%H:%M:%S')}",
            sep,
            f"  Focus widget    : {type(focused).__name__} (id={id(focused)})",
            f"  Canvas mode     : {self.canvas._mode}",
            f"  Canvas scale    : {self.canvas._scale:.4f}",
            f"  Canvas logical  : {cw} × {ch} px (image-space)",
            f"  Canvas widget   : {self.canvas.width()} × {self.canvas.height()} px (screen)",
            f"  Viewport        : {view_w} × {view_h} px",
            f"  Scroll H        : {hsb.value()} / {hsb.maximum()}",
            f"  Scroll V        : {vsb.value()} / {vsb.maximum()}",
        ]

        # Target mask
        tr = self.canvas.get_target_scaled_rect()
        if tr:
            lines.append(f"  Target rect     : x={tr.x():.1f} y={tr.y():.1f} "
                         f"w={tr.width():.1f} h={tr.height():.1f}  (screen-space)")
            pos = self.canvas.get_target_scroll_pos(view_w, view_h)
            if pos:
                lines.append(f"  Computed scroll : H={pos[0]}  V={pos[1]}")
        else:
            lines.append(f"  Target rect     : None (target_idx={self.canvas._target_idx}, "
                         f"group='{self.canvas._target_group_id}')")

        # Current item
        if 0 <= self._idx < len(self._items):
            card, box_idx, sm2_obj = self._items[self._idx]
            lines += [
                f"  Card idx        : {self._idx} / {len(self._items) - 1}",
                f"  Card title      : {card.get('title','?')}",
                f"  Box idx         : {box_idx}",
                f"  SM2 state       : {sm2_obj.get('sched_state','?')}  due={sm2_obj.get('sm2_due','?')}",
                f"  Total boxes     : {len(card.get('boxes', []))}",
            ]
            pdf_path = card.get("pdf_path", "")
            if pdf_path:
                cached_pages = 0
                for i in range(10000):
                    if PAGE_CACHE.get(pdf_path, i) is None:
                        break
                    cached_pages += 1
                lines.append(f"  PDF path        : {os.path.basename(pdf_path)}")
                lines.append(f"  Cached pages    : {cached_pages}")
            lines.append(f"  Canvas pages    : {len(self.canvas._pages)}")

        # UI state
        lines += [
            f"  Reveal bar      : {'visible' if self._reveal_bar.isVisible() else 'hidden'}",
            f"  Rating frame    : {'visible' if self._rating_frame.isVisible() else 'hidden'}",
            sep,
            "",
        ]

        print("\n".join(lines))
        # Also show as canvas toast so it's visible without terminal
        self.canvas._show_toast(f"📋 Debug report printed to terminal  [{trigger}]")

    def _edit_current_card(self):
        if not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, sm2_obj = self._items[self._idx]
        scroll_pos = self._canvas_scroll.verticalScrollBar().value()

        # --- SNAPSHOT: editor kholne se pehle har box ka group_id save karo ---
        before_snapshot = {
            b.get("box_id", f"__i_{i}"): b.get("group_id", "")
            for i, b in enumerate(card.get("boxes", []))
        }

        dlg = CardEditorDialog(None, card=dict(card), data=self._data, initial_scroll=scroll_pos)
        result = dlg.exec_()

        if result == QDialog.Accepted:
            edited = dlg.get_card()
            card.update(edited)
            if self._data:
                store.mark_dirty()  # 🔒 DirtyStore

            # --- COMPARE: kya koi box ka group_id badla? ---
            after_snapshot = {
                b.get("box_id", f"__i_{i}"): b.get("group_id", "")
                for i, b in enumerate(card.get("boxes", []))
            }

            # Rebuild if group structure changed OR box count changed (new mask added)
            before_box_ids = set(before_snapshot.keys())
            after_box_ids  = {
                b.get("box_id", f"__i_{i}")
                for i, b in enumerate(card.get("boxes", []))
            }
            if before_snapshot != after_snapshot or before_box_ids != after_box_ids:
                self._rebuild_items_for_card(card)

        self._reload_current_canvas()

    def _rebuild_items_for_card(self, changed_card):
        """
        Sirf ek specific card ke items ko _items list mein rebuild karo.
        Baaki saare cards ke items bilkul untouched rahenge.

        Trigger: sirf tab jab editor mein kisi box ka group_id change hua ho.
        """
        card_key = id(changed_card)

        # Step 1: Is card ke purane saare entries _items se hata do
        self._items = [
            (c, b, s) for (c, b, s) in self._items
            if id(c) != card_key
        ]

        # Step 2: Is card ke liye fresh items banao (same logic as __init__)
        boxes = changed_card.get("boxes", [])
        new_items = []
        seen_groups = set()

        if len(boxes) == 0:
            new_items.append((changed_card, None, changed_card))
        else:
            for i, box in enumerate(boxes):
                gid = box.get("group_id", "")
                if gid:
                    if gid not in seen_groups:
                        seen_groups.add(gid)
                        if is_due_today(box):
                            new_items.append((changed_card, ("group", gid), box))
                else:
                    if is_due_today(box):
                        new_items.append((changed_card, i, box))

        # Step 3: Current index ke position par naye items insert karo
        # (taaki review sequence buri tarah na toote)
        self._items[self._idx:self._idx] = new_items

        # Step 4: Queue panel refresh karo
        self._rebuild_queue()

    def _reload_current_canvas(self):
        """File: anki_occlusion_v19.py -> Class: ReviewScreen"""
        if not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, _ = self._items[self._idx]

        px = None
        # 1. Image logic (Unchanged)
        if card.get("image_path") and os.path.exists(card["image_path"]):
            px = QPixmap(card["image_path"])

        # 2. PDF Logic — cache hit = instant, cache miss = background thread
        elif card.get("pdf_path") and PDF_SUPPORT:
            path = card["pdf_path"]

            if os.path.exists(path):
                # Collect only already-cached pages — never block UI thread
                clean_pages = []
                i = 0
                while True:
                    pg = PAGE_CACHE.get(path, i)
                    if pg is None:
                        break
                    if not pg.isNull():
                        clean_pages.append(pg)
                    i += 1

                # Check if we have ALL pages (fitz metadata only — fast)
                try:
                    _doc = fitz.open(path)
                    total_pages = len(_doc)
                    _doc.close()
                except Exception:
                    total_pages = 0

                if clean_pages and len(clean_pages) == total_pages:
                    # Full cache hit — instant, no blocking
                    self._apply_canvas_pages(card, box_idx, clean_pages)
                    return
                else:
                    # Partial or no cache — show what we have, thread fills the rest
                    if clean_pages:
                        self._apply_canvas_pages(card, box_idx, clean_pages)
                    self._start_review_pdf_thread(card, box_idx)
                    return
            else:
                # PDF file missing (folder renamed etc.) — show masks on grey
                # background so user can still see which mask to review
                self.canvas.load_pixmap(QPixmap())
                boxes = card.get("boxes", [])
                if boxes:
                    display_boxes = [{**b, "revealed": False} for b in boxes]
                    self.canvas.set_boxes_with_state(display_boxes)
                    tgt = box_idx if isinstance(box_idx, int) and box_idx is not None else -1
                    self.canvas.set_target_box(tgt)
                    self.canvas.set_mode("review")
                    self.canvas._show_toast(
                        "PDF not found — Edit Card > Relink PDF to fix")
                self._reveal_bar.show()
                self._rating_frame.hide()
                self.setFocus()
                return

        # 3. Apply Canvas for Images or Empty states
        if px and not px.isNull():
            self._apply_canvas(card, box_idx, px)
            # Image specific zoom logic remains here...
        else:
            self.canvas.load_pixmap(QPixmap())

        self._reveal_bar.show()
        self._rating_frame.hide()
        self.setFocus()
        
    def _apply_canvas(self, card, box_idx, px):
        """Pixmap + boxes canvas pe set karo — sync aur async dono paths use karte hain."""
        self._current_pixmap = px
        _pdf_path = card.get("pdf_path", "")
        # [PIXMAP REGISTRY] ReviewWindow ka current pixmap + canvas track karo
        from cache_manager import PIXMAP_REGISTRY
        PIXMAP_REGISTRY.register(
            f"review_current_{id(self)}", self, "_current_pixmap", _pdf_path)
        self.canvas._current_pdf_path = _pdf_path
        boxes = card.get("boxes", [])
        self.canvas.load_pixmap(px)
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            display_boxes = [
                {**{k: b[k] for k in ("rect","label","shape","angle","group_id","box_id") if k in b},
                 "rect": b["rect"], "label": b.get("label",""),
                 "revealed": False}
                for b in boxes
            ]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(-1)
            self.canvas.set_mode("review")
            self.canvas.set_target_group(gid)
        elif box_idx is None:
            self.canvas.set_boxes(boxes)
            self.canvas.set_target_box(-1)
            self.canvas.set_mode("review")
        else:
            display_boxes = [
                {"rect": b["rect"], "label": b.get("label",""),
                 "shape": b.get("shape","rect"), "angle": b.get("angle",0.0),
                 "group_id": b.get("group_id",""), "revealed": False}
                for i, b in enumerate(boxes)
            ]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(box_idx)
            self.canvas.set_mode("review")

    def _apply_canvas_pages(self, card, box_idx, pages):
        """File: anki_occlusion_v19.py -> Class: ReviewScreen"""
        path = card.get("pdf_path", "")
        self.canvas._current_pdf_path = path

        # 1. Load ALL pages
        self.canvas.load_pages(pages)

        # 2. Re-register with Registry for deep cards
        from cache_manager import MASK_REGISTRY
        MASK_REGISTRY.register(path, self.canvas)

        # 3. set_mode FIRST so it doesn't wipe revealed state set below
        self.canvas.set_mode("review")

        # 4. Setup boxes state (must come AFTER set_mode)
        boxes = card.get("boxes", [])
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            display_boxes = [{**b, "revealed": False} for b in boxes]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_group(gid)
        else:
            display_boxes = [{**b, "revealed": False} for i, b in enumerate(boxes)]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(box_idx if box_idx is not None else -1)

        # 5. Always reset UI state — Show Answer bar visible, rating hidden
        self._reveal_bar.show()
        self._rating_frame.hide()

        # 6. Zoom fit + center (deferred so viewport geometry is final)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: (self._zoom_fit(), self._center_on_target()))
        
    def _start_review_pdf_thread(self, card, box_idx):
        """File: anki_occlusion_v19.py -> Class: ReviewScreen -> Function: _start_review_pdf_thread"""
        path = card.get("pdf_path", "")
        if hasattr(self, "_pdf_loader_thread") and self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(300)
            
        self._pdf_loader_thread = PdfLoaderThread(path, parent=self)
        self._pending_review_card = card
        self._pending_review_box_idx = box_idx
        
        # ⚡ V20 Fix: Connect to the new handler that expects a list of pages
        self._pdf_loader_thread.done.connect(self._on_review_pages_ready)
        self._pdf_loader_thread.start()

    def _on_review_pages_ready(self, pages, err):
        """File: anki_occlusion_v19.py -> Class: ReviewScreen"""
        if not pages or err:
            return
            
        card = self._pending_review_card
        box_idx = self._pending_review_box_idx
        
        # ⚡ FIX: 'card' argument pass karna must hai
        self._apply_canvas_pages(card, box_idx, pages)

    def _rate(self, quality):
        card, box_idx, sm2_obj = self._items[self._idx]

        sched_update(sm2_obj, quality)

        if box_idx is None:
            card["reviews"] = sm2_obj.get("reviews", 0)

        if self._data:
            store.mark_dirty()

        state = sm2_obj.get("sched_state", "review")

        if state in ("learning", "relearn"):
            # Pull item out and re-insert by due time
            item = self._items.pop(self._idx)
            due_str = sm2_obj.get("sm2_due", "")
            insert_at = len(self._items)
            for j in range(self._idx, len(self._items)):
                other_due = self._items[j][2].get("sm2_due", "")
                if other_due >= due_str:
                    insert_at = j
                    break
            self._items.insert(insert_at, item)
        else:
            self._done += 1
            self._idx  += 1

        # ── NEW: after every rating, bubble any expired learning cards to front ──
        self._promote_expired_learning(self._idx)

        self._load_item()

    def _promote_expired_learning(self, insert_pos):
        from datetime import datetime as _dt
        now_str = _dt.now().isoformat(timespec="seconds")

        to_promote = [
            j for j in range(insert_pos, len(self._items))
            if self._items[j][2].get("sched_state") in ("learning", "relearn")
            and self._items[j][2].get("sm2_due", "") <= now_str
        ]

        for offset, j in enumerate(to_promote):
            real_j = j - offset
            item = self._items.pop(real_j)
            self._items.insert(insert_pos + offset, item)

    def _rebuild_queue(self):
        """Rebuild the right-side queue list — reflects current order + states."""
        self._queue_list.clear()
        for i, (card, box_idx, sm2_obj) in enumerate(self._items):
            title = card.get("title", "Untitled")
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                label = f"{title}  [grp]"
            elif box_idx is None:
                label = title
            else:
                label = f"{title}  #{box_idx + 1}"
            item = QListWidgetItem(label)
            if i < self._idx:
                state = "done"
            elif i == self._idx:
                state = "current"
            else:
                sched = sm2_obj.get("sched_state", "new")
                state = "relearn" if sched in ("learning", "relearn") else "pending"
            item.setData(QUEUE_ROLE, state)
            self._queue_list.addItem(item)
        # Scroll to current card
        if 0 <= self._idx < self._queue_list.count():
            self._queue_list.scrollToItem(
                self._queue_list.item(self._idx),
                QListWidget.PositionAtCenter
            )


    def _finish(self):
        # [BUG 1 FIX] Check if any learning/relearn items are still pending
        # (e.g. m1 got Again → due in 1min, but m2/m3 finished early)
        # If yes, wait and re-check instead of ending the session.
        pending_learning = [
            (i, sm2_obj) for i, (_, _, sm2_obj) in enumerate(self._items)
            if sm2_obj.get("sched_state") in ("learning", "relearn")
        ]
        if pending_learning:
            # Find the earliest due learning item
            earliest_idx, earliest_obj = min(
                pending_learning,
                key=lambda x: x[1].get("sm2_due", "")
            )
            due_str = earliest_obj.get("sm2_due", "")
            try:
                from datetime import datetime as _dt
                due_dt  = _dt.fromisoformat(due_str)
                wait_ms = max(0, int((_dt.now() - due_dt).total_seconds() * -1000))
            except Exception:
                wait_ms = 0
            if wait_ms > 0:
                # Show waiting state — re-check when earliest card becomes due
                self._show_waiting_state(wait_ms, len(pending_learning))
                return
            else:
                # Due time already passed — jump to that item directly
                self._idx = earliest_idx
                self._load_item()
                return

        self.prog.setValue(len(self._items))
        self._show_session_summary()

    def _show_session_summary(self):
        """Session khatam — stats dialog dikhao."""
        again = hard = good = easy = 0
        for _, _, sm2_obj in self._items:
            q = sm2_obj.get("sm2_last_quality", -1)
            if   q == 1: again += 1
            elif q == 3: hard  += 1
            elif q == 4: good  += 1
            elif q == 5: easy  += 1

        total = again + hard + good + easy
        retention = round((good + easy) / total * 100) if total else 0

        dlg = QDialog(self)
        dlg.setWindowTitle("Session Complete")
        dlg.setFixedSize(340, 320)
        dlg.setStyleSheet(f"QDialog{{background:{C_BG};}}")
        L = QVBoxLayout(dlg)
        L.setContentsMargins(24, 24, 24, 24)
        L.setSpacing(12)

        title = QLabel("🎉  Session Complete")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color:{C_ACCENT};background:transparent;")
        L.addWidget(title)

        # Retention bar
        bar_w = QWidget()
        bar_l = QHBoxLayout(bar_w)
        bar_l.setContentsMargins(0,0,0,0); bar_l.setSpacing(0)
        colors = [(again, C_RED), (hard, "#E08030"), (good, C_GREEN), (easy, C_YELLOW)]
        for count, color in colors:
            if count and total:
                seg = QFrame()
                seg.setFixedHeight(10)
                seg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                seg.setStyleSheet(f"background:{color};border-radius:0px;")
                bar_l.addWidget(seg, stretch=count)
        L.addWidget(bar_w)

        # Stats grid
        def _stat_row(label, value, color):
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(0,0,0,0)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;background:transparent;")
            val = QLabel(str(value))
            val.setStyleSheet(f"color:{color};font-size:13px;font-weight:bold;background:transparent;")
            val.setAlignment(Qt.AlignRight)
            rl.addWidget(lbl); rl.addWidget(val)
            return row

        L.addWidget(_stat_row("🔁  Again",  again, C_RED))
        L.addWidget(_stat_row("😓  Hard",   hard,  "#E08030"))
        L.addWidget(_stat_row("✅  Good",   good,  C_GREEN))
        L.addWidget(_stat_row("⚡  Easy",   easy,  C_YELLOW))

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{C_BORDER};")
        sep.setFixedHeight(1)
        L.addWidget(sep)

        L.addWidget(_stat_row("Retention", f"{retention}%",
            C_GREEN if retention >= 80 else C_YELLOW if retention >= 60 else C_RED))
        L.addWidget(_stat_row("Total reviewed", self._done, C_TEXT))

        btn = QPushButton("Close  ✓")
        btn.setStyleSheet(
            f"background:{C_ACCENT};color:white;border:none;border-radius:8px;"
            f"padding:8px 24px;font-size:13px;font-weight:bold;")
        btn.clicked.connect(dlg.accept)
        L.addWidget(btn, alignment=Qt.AlignCenter)

        dlg.exec_()
        self.finished.emit()

    def _show_waiting_state(self, wait_ms: int, pending_count: int):
        """Learning cards pending hain — countdown show karo, session end mat karo."""
        secs = max(1, wait_ms // 1000)
        self._reveal_bar.hide()
        self._rating_frame.hide()
        # _wait_bar is a proper QFrame already in the layout (created in _setup_ui)
        mins, s = divmod(secs, 60)
        self._wait_lbl_countdown.setText(
            f"next card in  {mins}m {s:02d}s")
        self._wait_lbl_count.setText(
            f"⏳  {pending_count} card(s) still in learning")
        self._wait_bar.show()
        QTimer.singleShot(1000, self._check_learning_due)

    def _check_learning_due(self):
        """Every 1s check karein kya koi learning card due ho gaya."""
        self._wait_bar.hide()
        pending = [
            (i, sm2_obj) for i, (_, _, sm2_obj) in enumerate(self._items)
            if sm2_obj.get("sched_state") in ("learning", "relearn")
        ]
        if not pending:
            self.finished.emit()
            return
        from datetime import datetime as _dt
        now_str = _dt.now().isoformat(timespec="seconds")
        due_now = [
            (i, obj) for i, obj in pending
            if obj.get("sm2_due", "") <= now_str
        ]
        if due_now:
            earliest_idx = min(due_now, key=lambda x: x[1].get("sm2_due", ""))[0]
            self._idx = earliest_idx
            self._wait_bar.hide()
            self._reveal_bar.show()
            self._load_item()
        else:
            self._finish()   # re-evaluate wait time


# ═══════════════════════════════════════════════════════════════════════════════
#  DECK TREE
# ═══════════════════════════════════════════════════════════════════════════════

class DeckTree(QWidget):
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._ensure_ids()
        self._setup_ui()
        self.refresh()

    def _ensure_ids(self):
        counter = [0]
        def _walk(lst):
            for d in lst:
                if "_id" not in d:
                    counter[0] += 1
                    d["_id"] = counter[0]
                _walk(d.get("children", []))
        _walk(self._data.get("decks", []))

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)
        hdr = QLabel("📚  Decks")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Bold))
        L.addWidget(hdr)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_click)
        L.addWidget(self.tree, stretch=1)
        btn_row = QHBoxLayout()
        b_new = QPushButton("＋ Deck")
        b_new.clicked.connect(lambda: self._new_deck(None))
        b_sub = QPushButton("＋ Sub")
        b_sub.clicked.connect(self._new_subdeck)
        b_del = QPushButton("🗑")
        b_del.setObjectName("danger")
        b_del.setFixedWidth(36)
        b_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(b_new)
        btn_row.addWidget(b_sub)
        btn_row.addStretch()
        btn_row.addWidget(b_del)
        L.addLayout(btn_row)
        hint = QLabel("Double-click to open  •  Right-click for menu")
        hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        hint.setAlignment(Qt.AlignCenter)
        L.addWidget(hint)

    def refresh(self):
        sel_id = self._get_selected_id()
        self.tree.clear()
        for deck in self._data.get("decks", []):
            self.tree.addTopLevelItem(self._make_item(deck))
        self.tree.expandAll()
        if sel_id is not None:
            self._select_by_id(sel_id)

    def _make_item(self, deck):
        def _card_due(c):
            boxes = c.get("boxes", [])
            if not boxes:
                return is_due_today(c)
            seen = set()
            for b in boxes:
                gid = b.get("group_id", "")
                if gid:
                    if gid not in seen:
                        seen.add(gid)
                        if is_due_today(b): return True
                else:
                    if is_due_today(b): return True
            return False

        due   = sum(1 for c in deck.get("cards", []) if _card_due(c))
        badge = f"🔴{due}" if due else "✅"
        item  = QTreeWidgetItem([f"  📂  {deck['name']}  {badge}"])
        item.setData(0, Qt.UserRole, deck.get("_id"))
        for child in deck.get("children", []):
            item.addChild(self._make_item(child))
        return item

    def _get_id_from_item(self, item):
        return item.data(0, Qt.UserRole) if item else None

    def _get_deck_from_item(self, item):
        did = self._get_id_from_item(item)
        return find_deck_by_id(did, self._data.get("decks", [])) if did is not None else None

    def _get_selected_id(self):
        return self._get_id_from_item(self.tree.currentItem())

    def _select_by_id(self, deck_id):
        def _walk(item):
            if item.data(0, Qt.UserRole) == deck_id:
                self.tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if _walk(item.child(i)):
                    return True
            return False
        for i in range(self.tree.topLevelItemCount()):
            if _walk(self.tree.topLevelItem(i)):
                break

    def _on_double_click(self, item, _col):
        deck = self._get_deck_from_item(item)
        if deck:
            self.deck_selected.emit(deck)

    def _on_click(self, item, _col):
        deck = self._get_deck_from_item(item)
        if deck:
            self.deck_selected.emit(deck)

    def _ctx_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            did = self._get_id_from_item(item)
            menu.addAction("▶ Open",      lambda: self._on_double_click(item, 0))
            menu.addAction("＋ Sub-deck", lambda: self._new_deck(did))
            menu.addAction("✏ Rename",   lambda: self._rename_by_id(did))
            menu.addSeparator()
            menu.addAction("🗑 Delete",   lambda: self._delete_by_id(did))
        else:
            menu.addAction("＋ New Top-level Deck", lambda: self._new_deck(None))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _new_deck(self, parent_id):
        name, ok = QInputDialog.getText(self, "New Deck", "Deck name:")
        if not ok or not name.strip():
            return
        new_deck = {
            "_id":      next_deck_id(self._data),
            "name":     name.strip(),
            "cards":    [],
            "children": [],
            "created":  datetime.now().isoformat()
        }
        if parent_id is None:
            self._data.setdefault("decks", []).append(new_deck)
        else:
            parent = find_deck_by_id(parent_id, self._data.get("decks", []))
            if parent is None:
                QMessageBox.warning(self, "Error", "Parent deck not found!")
                return
            parent.setdefault("children", []).append(new_deck)
        store.mark_dirty()  # 🔒 DirtyStore
        self.refresh()
        self._select_by_id(new_deck["_id"])

    def _new_subdeck(self):
        did = self._get_selected_id()
        if did is None:
            QMessageBox.information(self, "Select first",
                "Click a parent deck first, then press ＋ Sub.")
            return
        self._new_deck(did)

    def _rename_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        name, ok = QInputDialog.getText(self, "Rename Deck", "New name:", text=deck.get("name", ""))
        if ok and name.strip():
            deck["name"] = name.strip()
            store.mark_dirty()  # 🔒 DirtyStore
            self.refresh()

    def _delete_selected(self):
        did = self._get_selected_id()
        if did is not None:
            self._delete_by_id(did)

    def _delete_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        if QMessageBox.question(self, "Delete",
            f"Delete '{deck['name']}' and ALL its cards / sub-decks?",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._remove_from_tree(deck_id, self._data.get("decks", []))
        store.mark_dirty()  # 🔒 DirtyStore
        self.refresh()

    def _remove_from_tree(self, deck_id, lst):
        for i, d in enumerate(lst):
            if d.get("_id") == deck_id:
                lst.pop(i)
                return True
            if self._remove_from_tree(deck_id, d.get("children", [])):
                return True
        return False

    def get_selected_deck(self):
        return self._get_deck_from_item(self.tree.currentItem())


# ═══════════════════════════════════════════════════════════════════════════════
#  CACHE WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_bytes(n: int) -> str:
    if n < 1024:     return f"{n} B"
    if n < 1024**2:  return f"{n/1024:.1f} KB"
    if n < 1024**3:  return f"{n/1024**2:.1f} MB"
    return f"{n/1024**3:.2f} GB"

class CacheWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cacheFrame")
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame#cacheFrame {{
                background:{C_SURFACE};
                border-left:1px solid {C_BORDER};
                border-radius:0px;
            }}
            QLabel {{ background:transparent; }}
        """)
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_timer.start(4000)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(38)
        hdr.setStyleSheet(
            f"QFrame{{background:{C_CARD};"
            f"border-bottom:1px solid {C_BORDER};border-radius:0px;}}")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 10, 0)
        title = QLabel("💾 Cache")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:11px;font-weight:bold;")
        self._lbl_total = QLabel("")
        self._lbl_total.setStyleSheet(
            f"color:{C_GREEN};font-size:10px;")
        self._lbl_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(title)
        hl.addStretch()
        hl.addWidget(self._lbl_total)
        root.addWidget(hdr)

        # Scrollable list of cached PDFs
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:transparent;}}"
            f"QScrollBar:vertical{{background:{C_SURFACE};width:5px;border-radius:2px;}}"
            f"QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:2px;}}")

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(6, 6, 6, 6)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_container)
        root.addWidget(scroll, stretch=1)

        # Clear All button at bottom
        btn_all = QPushButton("🧹 Clear All Caches")
        btn_all.setStyleSheet(
            f"background:#444460;color:{C_TEXT};border:none;"
            f"border-top:1px solid {C_BORDER};"
            f"border-radius:0px;padding:8px;font-size:11px;")
        btn_all.clicked.connect(self._clear_all)
        root.addWidget(btn_all)

    def refresh(self):
        from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY

        # Collect all known PDFs
        known = set()
        known.update(COMBINED_CACHE.all_cached_pdfs())
        known.update(PAGE_CACHE.all_cached_pdfs())
        known.update(MASK_REGISTRY.all_registered_pdfs())

        # Clear old entries (keep trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_bytes = 0
        for pdf_path in sorted(known):
            disk_b = COMBINED_CACHE.disk_bytes_for_pdf(pdf_path)
            ram_b  = PAGE_CACHE.ram_bytes_for_pdf(pdf_path)
            mask_b = MASK_REGISTRY.mask_bytes_for_pdf(pdf_path)
            total  = disk_b + ram_b + mask_b
            total_bytes += total
            card = self._make_card(pdf_path, disk_b, ram_b, mask_b, total)
            self._list_layout.insertWidget(
                self._list_layout.count() - 1, card)

        if not known:
            empty = QLabel("No cached PDFs yet.")
            empty.setStyleSheet(f"color:{C_SUBTEXT};font-size:10px;")
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)

        count = len(known)
        self._lbl_total.setText(
            f"{_fmt_bytes(total_bytes)}  {count} PDF{'s' if count!=1 else ''}")

    def _make_card(self, pdf_path, disk_b, ram_b, mask_b, total_b):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{C_CARD};"
            f"border:1px solid {C_BORDER};border-radius:6px;}}"
            f"QLabel{{background:transparent;}}")
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(3)

        # File name
        name = os.path.basename(pdf_path)
        if len(name) > 22: name = name[:19] + "..."
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:10px;font-weight:bold;")
        name_lbl.setToolTip(pdf_path)
        vl.addWidget(name_lbl)

        def _row(icon, val):
            w = QWidget(); w.setStyleSheet("background:transparent;")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(4)
            il = QLabel(icon); il.setFixedWidth(16)
            il.setStyleSheet("font-size:10px;")
            vl2 = QLabel(val)
            vl2.setStyleSheet(f"color:{C_GREEN};font-size:10px;")
            vl2.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            hl.addWidget(il)
            hl.addStretch()
            hl.addWidget(vl2)
            return w

        vl.addWidget(_row("💿", _fmt_bytes(disk_b)))
        vl.addWidget(_row("🧠", _fmt_bytes(ram_b)))
        vl.addWidget(_row("🎭", _fmt_bytes(mask_b)))

        # Total + remove button
        hl_bot = QHBoxLayout()
        tl = QLabel(_fmt_bytes(total_b))
        tl.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:10px;font-weight:bold;")
        btn = QPushButton("🗑")
        btn.setFixedSize(24, 24)
        btn.setToolTip("Remove this PDF cache")
        btn.setStyleSheet(
            f"background:{C_RED};color:white;border:none;"
            f"border-radius:4px;font-size:11px;padding:0px;")
        btn.clicked.connect(lambda _, p=pdf_path: self._remove_pdf(p))
        hl_bot.addWidget(tl)
        hl_bot.addStretch()
        hl_bot.addWidget(btn)
        vl.addLayout(hl_bot)
        return card

    def _remove_pdf(self, pdf_path):
        from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY
        COMBINED_CACHE.invalidate(pdf_path)
        PAGE_CACHE.invalidate_pdf(pdf_path)
        MASK_REGISTRY.invalidate_masks_for_pdf(pdf_path)
        self.refresh()

    def _clear_all(self):
        from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY
        COMBINED_CACHE.clear()
        PAGE_CACHE.clear()
        for p in list(MASK_REGISTRY.all_registered_pdfs()):
            MASK_REGISTRY.invalidate_masks_for_pdf(p)
        self.refresh()

# ═══════════════════════════════════════════════════════════════════════════════
#  DECK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class DeckView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.deck          = None
        self._deck_id      = None
        self._data         = {}
        self._thumb_cache  = {}
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(12, 12, 12, 12)
        L.setSpacing(10)

        hdr = QHBoxLayout()
        self.lbl_deck = QLabel("← Select a deck")
        self.lbl_deck.setFont(QFont("Segoe UI", 15, QFont.Bold))
        hdr.addWidget(self.lbl_deck)
        hdr.addStretch()
        self.btn_add = QPushButton("＋ Add Card")
        self.btn_add.clicked.connect(self._add_card)
        self.btn_due = QPushButton("🔴 Review Due")
        self.btn_due.setObjectName("danger")
        self.btn_due.clicked.connect(self._review_due)
        self.btn_all = QPushButton("▶ Review All")
        self.btn_all.setObjectName("success")
        self.btn_all.clicked.connect(self._review_all)
        hdr.addWidget(self.btn_add)
        hdr.addWidget(self.btn_due)
        hdr.addWidget(self.btn_all)
        L.addLayout(hdr)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(f"color:{C_SUBTEXT};")
        L.addWidget(self.lbl_stats)

        self.card_list = QListWidget()
        self.card_list.setIconSize(QSize(64, 48))
        self.card_list.itemDoubleClicked.connect(self._edit_card)
        self.card_list.keyPressEvent = self._card_list_key_press
        L.addWidget(self.card_list, stretch=1)


        bot = QHBoxLayout()
        be  = QPushButton("✏ Edit")
        be.setObjectName("flat")
        be.clicked.connect(lambda: self._edit_card(self.card_list.currentItem()))
        bd  = QPushButton("🗑 Delete")
        bd.setObjectName("danger")
        bd.clicked.connect(self._delete_card)
        brs = QPushButton("▶ Review Selected")
        brs.clicked.connect(self._review_selected)
        bot.addWidget(be)
        bot.addWidget(bd)
        bot.addStretch()
        bot.addWidget(brs)
        L.addLayout(bot)

    def _card_list_key_press(self, e):
        key = e.key()
        if key == Qt.Key_E:
            self._edit_card(self.card_list.currentItem())
        elif key == Qt.Key_R:
            self._review_selected()
        else:
            QListWidget.keyPressEvent(self.card_list, e)

    def load_deck(self, deck, data):
        self._data = data
        new_id     = deck.get("_id")
        # [PERF FIX] Thumb cache sirf tab clear karo jab deck badla ho
        if new_id != self._deck_id:
            self._thumb_cache.clear()
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
        cards  = self.deck.get("cards", [])
        due_c  = 0

        for c in cards:
            # [PERF FIX] sm2_init sirf tab call karo jab fields missing hon
            # (setdefault calls skip karna = O(1) per card instead of O(fields))
            if "sched_state" not in c:
                sm2_init(c)
            boxes = c.get("boxes", [])
            if not boxes:
                card_due = is_due_today(c)
            else:
                seen_gids = set()
                card_due = False
                for b in boxes:
                    gid = b.get("group_id", "")
                    if gid:
                        if gid not in seen_gids:
                            seen_gids.add(gid)
                            if is_due_today(b):
                                card_due = True
                    else:
                        if is_due_today(b):
                            card_due = True
            due_c += card_due

            badge = "🔴 Due" if card_due else f"✅ {sm2_days_left(c)}d"

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

        total_rev = sum(c.get("reviews", 0) for c in cards)
        self.lbl_stats.setText(
            f"Cards:{len(cards)}  🔴Due:{due_c}  Reviews:{total_rev}")

    def _add_card(self):
        if not self.deck:
            return
        dlg = CardEditorDialog(self, data=self._data, deck=self.deck)
        if dlg.exec_() != QDialog.Accepted:
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
        dlg = CardEditorDialog(self, card=dict(cards[idx]), data=self._data, deck=self.deck)
        if dlg.exec_() == QDialog.Accepted:
            c = dlg.get_card()
            c.pop("_auto_subdeck", None)
            cards[idx] = c
            self._refresh()
            store.mark_dirty()  # 🔒 DirtyStore

    def _delete_card(self):
        if not self.deck:
            return
        idx   = self.card_list.currentRow()
        cards = self.deck.get("cards", [])
        if not 0 <= idx < len(cards):
            return
        if QMessageBox.question(self, "Delete", "Delete this card?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cards.pop(idx)
            self._refresh()
            store.mark_dirty()  # 🔒 DirtyStore

    def _review_due(self):
        if not self.deck:
            return

        def _card_has_due_today(card):
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

        due = [c for c in self.deck.get("cards", []) if _card_has_due_today(c)]
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

    def _review_selected(self):
        if not self.deck:
            return
        idxs  = [self.card_list.row(i) for i in self.card_list.selectedItems()]
        cards = self.deck.get("cards", [])
        sub   = [cards[i] for i in idxs if i < len(cards)]
        if not sub:
            QMessageBox.information(self, "None", "Select cards first.")
            return
        self._start_review(sub)

    def _start_review(self, cards):
        _save_done = [False]

        win = QMainWindow(self)
        win.setWindowTitle("Review Mode 🧠")
        win.setMinimumSize(960, 730)
        rev = ReviewScreen(cards, data=self._data, parent=win)

        def _on_finished():
            if not _save_done[0]:
                _save_done[0] = True
                store.mark_dirty()  # 🔒 DirtyStore
            self._refresh()
            win.close()

        original_close = win.closeEvent
        def _safe_close(e):
            # [BUG 2 FIX] X button se close karne par bhi save karo
            # Warna reviewed cards ki sm2_due changes lost ho jaati hain
            if not _save_done[0]:
                _save_done[0] = True
                store.mark_dirty()  # 🔒 Force dirty — next autosave ya app-close pe save hoga
            original_close(e)
        win.closeEvent = _safe_close

        rev.finished.connect(_on_finished)
        win.setCentralWidget(rev)
        win.setStyleSheet(SS)
        win.showMaximized()


# ═══════════════════════════════════════════════════════════════════════════════
#  HOME SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

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
        sub = QLabel("SM-2 Spaced Repetition  •  PDF & Image Occlusion")
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

        btn_help  = _topbtn("❓ Help",  "Show quick-start guide")
        btn_about = _topbtn("ℹ About", "About Anki Occlusion")
        btn_help.clicked.connect(self._show_help)
        btn_about.clicked.connect(self._show_about)

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
        tl.addWidget(btn_help)
        tl.addWidget(btn_about)
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

    def _on_deck_selected(self, deck):
        self.deck_view.load_deck(deck, self._data)
        self._preload_deck_pdf(deck)

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

    def _show_about(self):
        AboutDialog(self).exec_()

    def _show_help(self):
        OnboardingDialog(self).exec_()

    def _emit_font(self, direction: int):
        win = self.window()
        if isinstance(win, MainWindow):
            win.change_font_size(direction)

    def refresh(self):
        self.deck_tree.refresh()
        sel = self.deck_tree.get_selected_deck()
        if sel:
            self.deck_view.load_deck(sel, self._data)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._data = load_data()
        store.start_autosave()          # 🔒 DirtyStore — auto-save every 60s if dirty
        self.setWindowTitle("Anki Occlusion")
        self.setMinimumSize(1100, 720)
        self.setWindowIcon(make_app_icon())
        self._font_size = int(self._data.get("_font_size", BASE_FONT_SIZE))
        self.showMaximized()
        home = HomeScreen(self._data, parent=self)
        self.setCentralWidget(home)

        sb = QStatusBar()
        sb.showMessage("✅ SM-2 Active  |  " + (
            "PyMuPDF loaded — PDF support active"
            if PDF_SUPPORT else "⚠ pip install pymupdf  for PDF support"))
        self.setStatusBar(sb)
        if self._font_size != BASE_FONT_SIZE:
            self._apply_font_size(self._font_size)
        if not self._data.get("_onboarding_done"):
            QTimer.singleShot(200, self._run_onboarding)

    def change_font_size(self, direction: int):
        if direction == 0:
            self._font_size = BASE_FONT_SIZE
        else:
            self._font_size = max(8, min(20, self._font_size + direction))
        self._apply_font_size(self._font_size)
        self._data["_font_size"] = self._font_size
        store.mark_dirty()  # 🔒 DirtyStore

    def _apply_font_size(self, size: int):
        QApplication.instance().setStyleSheet(_build_ss(size))

    def _run_onboarding(self):
        dlg = OnboardingDialog(self)
        dlg.exec_()
        self._data["_onboarding_done"] = True
        store.mark_dirty()  # 🔒 DirtyStore

    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
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
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        store.stop_autosave()           # 🔒 Final force-save + background thread stop
        super().closeEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    lock = QLockFile(LOCK_FILE)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        app_tmp = QApplication(sys.argv)
        QMessageBox.warning(None, "Already Running",
            "Anki Occlusion is already open!\nCheck your taskbar.")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyleSheet(SS)
    app.setApplicationName("Anki Occlusion")
    app.setApplicationVersion("1.0")
    _icon = make_app_icon()
    app.setWindowIcon(_icon)
    win = MainWindow()
    win.show()
    ret = app.exec_()
    lock.unlock()
    sys.exit(ret)