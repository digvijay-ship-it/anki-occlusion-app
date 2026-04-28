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



# ═══════════════════════════════════════════════════════════════════════════════
#  REVIEW SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

QUEUE_ROLE       = Qt.UserRole + 10
QUEUE_INDEX_ROLE = Qt.UserRole + 11
CARD_DRAG_MIME   = "application/x-anki-card"

class QueueDelegate(QStyledItemDelegate):
    COLORS = {
        "current": {"bg": QColor(C_GREEN),    "fg": QColor("#1E1E2E")},
        "done":    {"bg": QColor("#2A3A2A"),  "fg": QColor("#6A8A6A")},
        "pending": {"bg": QColor(C_SURFACE),  "fg": QColor(C_TEXT)},
        "relearn": {"bg": QColor("#3A2A1A"),  "fg": QColor("#E08030")},
        "peek":    {"bg": QColor("#B83B3B"),  "fg": QColor("#FFF1F1")},
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
    finished   = pyqtSignal()
    cancelled  = pyqtSignal()

    RATINGS = [
        ("1  🔁 Again", "danger",  1),
        ("2  😓 Hard",  "hard",    3),
        ("3  ✅ Good",  "success", 4),
        ("4  ⚡ Easy",  "warning", 5),
    ]

    @property
    def _items(self): return self.mgr._items
    @_items.setter
    def _items(self, val): self.mgr._items = val
    @property
    def _idx(self): return self.mgr._idx
    @_idx.setter
    def _idx(self, val): self.mgr._idx = val
    @property
    def _done(self): return self.mgr._done
    @_done.setter
    def _done(self, val): self.mgr._done = val
    @property
    def _queued_ids(self): return self.mgr._queued_ids
    @_queued_ids.setter
    def _queued_ids(self, val): self.mgr._queued_ids = val
    @property
    def _deleted_ids(self): return self.mgr._deleted_ids
    @_deleted_ids.setter
    def _deleted_ids(self, val): self.mgr._deleted_ids = val
    @property
    def _review_undo_stack(self): return self.mgr._review_undo_stack
    @_review_undo_stack.setter
    def _review_undo_stack(self, val): self.mgr._review_undo_stack = val
    @property
    def _review_redo_stack(self): return self.mgr._review_redo_stack
    @_review_redo_stack.setter
    def _review_redo_stack(self, val): self.mgr._review_redo_stack = val

    def _rate(self, quality): self.mgr._rate(quality)
    def _review_undo(self): self.mgr._review_undo()
    def _review_redo(self): self.mgr._review_redo()
    def _rebuild_queue(self, peek_idx=None): self.mgr._rebuild_queue(peek_idx)
    def _check_learning_due(self): self.mgr._check_learning_due()
    def _promote_expired_learning(self, insert_pos): self.mgr._promote_expired_learning(insert_pos)

    def __init__(self, cards, data=None, parent=None):
        super().__init__(parent)
        from services.review_manager import ReviewSessionManager
        self.mgr = ReviewSessionManager(self)
        self._data           = data
        self._cache_panel = None
        self._items          = []
        self._pdf_cache      = {}
        self._current_pixmap = None
        from services.pdf_watcher import PdfWatcher
        self._pdf_watcher = PdfWatcher(self)
        self._pdf_watcher.file_changed.connect(self._on_pdf_file_changed)
        self._pdf_watcher.reload_requested.connect(self._on_pdf_reload_requested)
        self._pdf_watcher.get_current_page_cb = lambda: self.canvas.get_current_page(self._canvas_scroll.verticalScrollBar().value())
        self._pdf_watcher.get_hint_cb = lambda: (self._external_pdf_path_hint, self._external_pdf_page_hint)
        self._watched_pdf_path = None
        
        
        
        
        
        self._pending_reload_page = None
        self._external_pdf_path_hint = None
        self._external_pdf_page_hint = None
        self._pending_visible_request = None
        self._pending_skeleton_result = None
        self._background_fill_state = None
        self._ondemand_kind = None
        self._ondemand_thread = None
        self._bg_pending_inserts = {}
        self._bg_accept_mode = False
        self._bg_prefetch_dialog = None
        self._bg_prefetch_total_pages = 0
        self._bg_prefetch_cached_count = 0
        self._bg_prefetch_rendered_count = 0
        self._skeleton_thread = None
        self._ui_idle_timer = QTimer(self)
        self._ui_idle_timer.setSingleShot(True)
        self._ui_idle_timer.setInterval(220)
        self._ui_idle_timer.timeout.connect(self._on_ui_idle_timeout)
        self._peek_idx = None
        self._peek_origin_idx = None
        # ── User zoom tracking — None = no manual zoom set yet ────────────────
        self._user_zoom_scale = None
        # ── O(1) box tracking ─────────────────────────────────────────────────
        # All box_ids/group_ids that entered the queue (ever seen this session)
        self._queued_ids     = set()
        # Tombstone set — deleted boxes, skip in _load_item
        self._deleted_ids    = set()

        seen_item_keys = set()

        # ── SM-2 Debug Logger ─────────────────────────────────────────────────
        if _DEBUG_LOG:
            try: log_session()
            except Exception: pass

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
                            _due_result = is_due_today(box)
                            if _DEBUG_LOG:
                                try: log_due(box, card, _due_result)
                                except Exception: pass
                            if _due_result:
                                self._items.append((card, ("group", gid), box))
                                self._queued_ids.add(gid)          # O(1) track
                else:
                    box_id = box.get("box_id", f"__idx_{i}")
                    item_key = (card_key, box_id)
                    if item_key not in seen_item_keys:
                        seen_item_keys.add(item_key)
                        _due_result = is_due_today(box)
                        if _DEBUG_LOG:
                            try: log_due(box, card, _due_result)
                            except Exception: pass
                        if _due_result:
                            self._items.append((card, i, box))
                            self._queued_ids.add(box_id)           # O(1) track

        self._items.sort(key=lambda x: x[2].get("sm2_due", ""))
        if _DEBUG_LOG:
            try: log_queue(self._items)
            except Exception: pass
        self._idx  = 0
        self._done = 0
        # ── Review undo/redo stacks ───────────────────────────────────────────
        # Each entry saves full state before a rating so Ctrl+Z can reverse it.
        # "Reset" = restore SM-2 fields to pre-rating values, not full history wipe.
        self._review_undo_stack = []   # list of state snapshots
        self._review_redo_stack = []   # cleared on new rating, filled on undo

        # ── Session Timer ─────────────────────────────────────────────────────
        if _TIMER_AVAILABLE:
            self._stimer = SessionTimer(self)
            self._stimer.start()
        else:
            self._stimer = None

        self._setup_ui()
        for w in (self, self.canvas, self._canvas_scroll.viewport(), self._queue_list.viewport()):
            try:
                w.setMouseTracking(True)
                w.installEventFilter(self)
            except Exception:
                pass
        self._load_item()

    def _toggle_cache_panel(self):
        from cache_manager import CacheManagerPanel
        if self._cache_panel is None:
            self._cache_panel = CacheManagerPanel(parent=self)
        if self._cache_panel.isVisible():
            self._cache_panel.hide()
        else:
            self._cache_panel.show()
            self._cache_panel.refresh()
    def closeEvent(self, e):
        self._close_bg_prefetch_dialog()
        self._stop_skeleton_thread()
        if hasattr(self, '_pdf_loader_thread') and self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000)

        # STEP 4 — stop on-demand thread on close
        self._stop_ondemand_thread()

        if hasattr(self, '_stop_watch'):
            self._pdf_watcher.stop_watch()

        # Stop timer and write focus time to today's journal
        if self._stimer:
            self._stimer.stop()
            self._stimer.flush_to_journal()

        super().closeEvent(e)

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.MouseMove, QEvent.HoverMove, QEvent.Wheel):
            self._note_user_activity()
        return super().eventFilter(obj, event)

    def _note_user_activity(self):
        self._ui_idle_timer.start()

    def _on_ui_idle_timeout(self):
        self._flush_pending_background_inserts()
        bg_state = self._background_fill_state
        if not bg_state:
            return
        if self._pending_visible_request:
            return
        if self._ondemand_thread and self._ondemand_thread.isRunning():
            return
        bg_path, bg_already_rendered, bg_total = bg_state
        if getattr(self, "_canvas_pdf_path", None) != bg_path:
            self._background_fill_state = None
            return
        self._start_background_fill(bg_path, bg_already_rendered, bg_total)

    def _close_bg_prefetch_dialog(self):
        """Removed — BackgroundPrefetchDialog no longer used."""
        self._bg_accept_mode = False
        self._bg_prefetch_total_pages = 0
        self._bg_prefetch_cached_count = 0
        self._bg_prefetch_rendered_count = 0

    def _show_bg_prefetch_dialog(self, path: str, total_pages: int):
        """Removed — BackgroundPrefetchDialog no longer used."""
        pass

    def _sync_bg_prefetch_dialog(self, path: str, total_pages: int, done: bool = False):
        """Removed — BackgroundPrefetchDialog no longer used."""
        pass

    def _accept_bg_prefetch(self):
        """Removed — BackgroundPrefetchDialog no longer used."""
        self._bg_accept_mode = True
        self._flush_pending_background_inserts()

    def _on_pdf_reload_requested(self, path, current_page, target_page):
        self._pending_reload_page = target_page
        self._reload_current_canvas()

    def _on_pdf_file_changed(self, path: str):
        if not path:
            return
        self.canvas._show_toast("PDF changed on disk — refreshing…")

    def _toggle_chrome(self):
        """Right-click on canvas — show/hide header and hint bars."""
        visible = self._hdr_widget.isVisible()
        self._hdr_widget.setVisible(not visible)
        self._hint_label.setVisible(not visible)

    def _show_overlay(self, overlay):
        """Show a floating overlay and reposition it."""
        self._reposition_overlays()
        overlay.show()
        overlay.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition_overlays()

    def _reposition_overlays(self):
        """Pin overlays to bottom-center of canvas scroll area."""
        ref = self._canvas_scroll
        w = ref.width()
        h = ref.height()

        # Rating frame — flush to bottom
        self._rating_frame.adjustSize()
        sh = self._rating_frame.sizeHint()
        rw = max(sh.width(), 10)
        rh = max(sh.height(), 48)
        self._rating_frame.setGeometry((w - rw) // 2, h - rh - 2, rw, rh)

        # Reveal bar — just above where rating would be
        self._reveal_bar.adjustSize()
        sh2 = self._reveal_bar.sizeHint()
        bw = max(sh2.width(), 10)
        bh = max(sh2.height(), 44)
        self._reveal_bar.setGeometry((w - bw) // 2, h - bh - 2, bw, bh)

    def _load_item(self):
        # [O(1) FIX] Skip tombstoned (deleted) boxes
        while self._idx < len(self._items):
            _, b, _ = self._items[self._idx]
            bid = b[1] if isinstance(b, tuple) else (b if isinstance(b, str) else "")
            if bid and bid in self._deleted_ids:
                self._idx += 1
            else:
                break

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

        # 🚀 SM-2 SIMULATION UPDATE
        previews = _fmt_due_interval(sm2_obj)
        LABELS = ["Again", "Hard", "Good", "Easy"]
        for (btn, q), (orig_lbl, _, _), color_lbl in zip(self._prev_lbls, self.RATINGS, LABELS):
            val = previews.get(q, "?")
            # orig_lbl e.g. "1  🔁 Again" → parts[0]="1", parts[1]="🔁"
            parts = orig_lbl.split()
            icon = parts[1] if len(parts) > 1 else ""
            btn.setText(f"{parts[0]} {icon}  {val}  {color_lbl}")

        current_path = getattr(self.canvas, "_current_pdf_path", "") or getattr(self, "_canvas_pdf_path", "")
        new_path = card.get("pdf_path", "")
        same_pdf = bool(current_path and new_path and os.path.abspath(current_path) == os.path.abspath(new_path))

        if same_pdf and getattr(self.canvas, "_pages", None):
            self._canvas_pdf_path = new_path
            self.canvas._current_pdf_path = new_path
            if hasattr(self.canvas, "clear_peek_target"):
                self.canvas.clear_peek_target()
            boxes = card.get("boxes", [])
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                gid = box_idx[1]
                display_boxes = [{**b, "revealed": False} for b in boxes]
                self.canvas.set_boxes_with_state(display_boxes)
                self.canvas.set_target_box(-1)
                self.canvas.set_mode("review")
                self.canvas.set_target_group(gid)
            elif box_idx is None:
                self.canvas.set_boxes_with_state([{**b, "revealed": False} for b in boxes])
                self.canvas.set_target_box(-1)
                self.canvas.set_mode("review")
            else:
                display_boxes = [{**b, "revealed": False} for b in boxes]
                self.canvas.set_boxes_with_state(display_boxes)
                self.canvas.set_target_box(box_idx if isinstance(box_idx, int) else -1)
                self.canvas.set_mode("review")
            # FIX: retain user-set zoom on same-PDF card switch too
            def _same_pdf_zoom_center():
                if self._user_zoom_scale is not None:
                    self.canvas._scale = self._user_zoom_scale
                    self.canvas._on_zoom()
                self._center_on_target()
            QTimer.singleShot(0, _same_pdf_zoom_center)
        else:
            self._reload_current_canvas()

        # ── Reset ink on every card change ────────────────────────────────────────────
        # Ink state must not carry over from the previous card.
        # ink_toggle() turns ink OFF and resets cursor to arrow.
        # ink_clear() wipes drawn strokes from the previous card.
        # _update_ink_hint() syncs the icon to reflect OFF state.
        if getattr(self.canvas, "_ink_active", False):
            self.canvas.ink_toggle()   # turns OFF → resets cursor
        self.canvas.ink_clear()        # wipe strokes from previous card
        self._update_ink_hint()        # sync icon to OFF state

        self.canvas.setFocus() # यह पक्का करेगा कि Keyboard Commands सीधे Canvas पकड़ें
        self._rating_frame.hide()   # ← rating frame explicitly hide karo
        QTimer.singleShot(50, lambda: self._show_overlay(self._reveal_bar))
    def keyPressEvent(self, e):
        key  = e.key()
        mods = e.modifiers()
        if getattr(self, "canvas", None) is not None and getattr(self.canvas, "_mode", "") == "edit":
            if mods & Qt.ControlModifier and key == Qt.Key_A:
                if mods & Qt.AltModifier:
                    self.canvas.select_all_on_pdf()
                elif mods & Qt.ShiftModifier:
                    self.canvas.select_all_in_view()
                else:
                    self.canvas.select_visible_only()
                self.canvas.setFocus()
                e.accept()
                return
        if key == Qt.Key_F11:
            win = self.window()
            if win.isFullScreen():
                win.showMaximized()
                self._set_fullscreen_ui(False)
            else:
                win.showFullScreen()
                self._set_fullscreen_ui(True)
        elif key == Qt.Key_Escape:
            self.cancelled.emit()
        elif key == Qt.Key_Space:
            if self._rating_frame.isVisible():
                # Already revealed — hide karo (toggle back)
                self._rating_frame.hide()
                self._show_overlay(self._reveal_bar)
                # Masks wapas hide karo
                for b in self.canvas._boxes:
                    b["revealed"] = False
                self.canvas._redraw()
            else:
                self._reveal_current()
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
            self._user_zoom_scale = self.canvas._scale
        elif mods & Qt.ControlModifier and key == Qt.Key_Minus:
            self.canvas.zoom_out()
            self._user_zoom_scale = self.canvas._scale
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self._zoom_fit()
            self._user_zoom_scale = None   # reset to auto-fit
        elif key == Qt.Key_C:
            if self._peek_idx is not None:
                self._exit_peek()
            else:
                # Ensure canvas has focus so it can calculate target rects
                self._zoom_fit()
                self._center_on_target()
                self._user_zoom_scale = self.canvas._scale  # C = user set zoom
            self._debug_report("C key")
        elif key == Qt.Key_D and not e.isAutoRepeat():
            self._debug_report("D key (manual)")
        elif mods & Qt.ControlModifier and key == Qt.Key_Z:
            self._review_undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_X:
            self._review_redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_E:
            self._open_current_pdf_in_reader()
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
        self._show_overlay(self._rating_frame)

    def _exit_peek(self):
        if self._peek_idx is None:
            return
        self._peek_idx = None
        self._peek_origin_idx = None
        if hasattr(self.canvas, "set_peek_active"):
            self.canvas.set_peek_active(False)
        if hasattr(self.canvas, "clear_peek_target"):
            self.canvas.clear_peek_target()
        self._rebuild_queue()
        self._center_on_target()

    def _jump_to_queue_index(self, idx, from_peek=False):
        if not (0 <= idx < len(self._items)):
            return
        if self._peek_origin_idx is None:
            self._peek_origin_idx = self._idx
        self._peek_idx = idx
        card, box_idx, _ = self._items[idx]
        if hasattr(self.canvas, "set_peek_target_box"):
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                self.canvas.set_peek_target_group(box_idx[1])
            else:
                self.canvas.set_peek_target_box(box_idx if isinstance(box_idx, int) else -1)
        if hasattr(self.canvas, "set_peek_active"):
            self.canvas.set_peek_active(True)
        self._rebuild_queue(peek_idx=idx)
        self._center_on_target()
        self._debug_report(f"queue jump -> {idx}")

    def _on_queue_item_clicked(self, item):
        idx = item.data(QUEUE_INDEX_ROLE)
        if idx is None:
            return
        self._jump_to_queue_index(int(idx))

    def _set_fullscreen_ui(self, fullscreen: bool):
        self._hdr_widget.setVisible(not fullscreen)
        self.lbl_title.setVisible(False)   # always hidden
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
        # Cache location button — toolbar mein b_edit ke baad
        b_cache = QPushButton("💾 Cache")
        b_cache.setStyleSheet(
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 14px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_SURFACE};}}")
        b_cache.clicked.connect(self._toggle_cache_panel)
        hdr.addWidget(b_edit)
        hdr.addWidget(b_cache)

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
        b_exit.clicked.connect(self.cancelled.emit)
        hdr.addWidget(b_exit)
        L.addWidget(hdr_w)
        self._hdr_widget = hdr_w
        self._hdr_widget.hide()          # hidden by default, right-click to toggle

        self.lbl_title = QLabel("")
        self.lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_title.setStyleSheet(
            f"color:{C_ACCENT};background:{C_BG};"
            f"padding:4px 16px;border-bottom:1px solid {C_BORDER};")
        self.lbl_title.setFixedHeight(30)
        self.lbl_title.hide()
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
        self.canvas.right_clicked.connect(self._toggle_chrome)
        self._canvas_scroll.setWidget(self.canvas)
        self._canvas_scroll.set_canvas(self.canvas)
        # Track Ctrl+scroll zoom so we retain it across cards
        self.canvas._zoom_timer.timeout.connect(self._on_canvas_zoom_settled)
        self._canvas_scroll.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._note_user_activity()
        )
        self._canvas_scroll.verticalScrollBar().valueChanged.connect(
            lambda *_: self._note_user_activity()
        )

        # ── Queue panel (right sidebar) ──────────────────────────────────
        queue_panel = QWidget()
        queue_panel.setFixedWidth(200)
        queue_panel.setStyleSheet(f"background:{C_SURFACE};")
        qp_l = QVBoxLayout(queue_panel)
        qp_l.setContentsMargins(6, 8, 6, 8)
        qp_l.setSpacing(4)

        # ── Timer block — sits above the queue list ───────────────────────
        if self._stimer:
            timer_frame = QFrame()
            timer_frame.setStyleSheet(
                f"QFrame{{background:{C_CARD};"
                f"border-radius:8px;"
                f"border:1px solid {C_BORDER};}}")
            tf_l = QVBoxLayout(timer_frame)
            tf_l.setContentsMargins(8, 6, 8, 6)
            tf_l.setSpacing(2)
            tf_top = QLabel("⏱  Today's focus")
            tf_top.setStyleSheet(
                f"color:{C_SUBTEXT};font-size:10px;"
                f"font-weight:bold;background:transparent;border:none;")
            self._stimer.label.setStyleSheet(
                f"background:transparent;color:#CDD6F4;"
                f"font-size:18px;font-weight:bold;"
                f"font-family:'Segoe UI Mono','Courier New',monospace;"
                f"border:none;")
            tf_l.addWidget(tf_top)
            tf_l.addWidget(self._stimer.label)
            qp_l.addWidget(timer_frame)
            qp_l.addSpacing(6)

        qp_hdr = QLabel("📋  Queue")
        qp_hdr.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;font-weight:bold;"
            f"padding-bottom:4px;border-bottom:1px solid {C_BORDER};")
        qp_l.addWidget(qp_hdr)
        self._queue_list = QListWidget()
        self._queue_list.setItemDelegate(QueueDelegate(self._queue_list))
        self._queue_list.setFocusPolicy(Qt.NoFocus)
        self._queue_list.itemClicked.connect(self._on_queue_item_clicked)
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
        self._hint_label.hide()          # hidden by default, right-click to toggle

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

        # ── Floating overlay: Show Answer button ──────────────────────────────
        self._reveal_bar = QFrame(self._canvas_scroll)
        self._reveal_bar.setStyleSheet("QFrame{background:transparent;border:none;}")
        rb_l = QHBoxLayout(self._reveal_bar)
        rb_l.setContentsMargins(0, 0, 0, 20)
        rb_l.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        b_rev = QPushButton("👁  Show Answer  [Space]")
        b_rev.setStyleSheet(
            f"background:rgba(42,42,62,220);color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:8px 40px;font-size:13px;font-weight:bold;")
        b_rev.clicked.connect(self._reveal_current)
        rb_l.addWidget(b_rev)
        self._reveal_bar.hide()

        # ── Floating overlay: Rating buttons ─────────────────────────────────
        self._rating_frame = QFrame(self._canvas_scroll)
        self._rating_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        rfl = QHBoxLayout(self._rating_frame)
        rfl.setContentsMargins(0, 0, 0, 0)
        rfl.setSpacing(8)
        rfl.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        RATING_COLORS = {
            "danger":  ("#FF5555", "#FF8888", "#CC2222"),
            "hard":    ("#E08030", "#FFB060", "#B05010"),
            "success": ("#50FA7B", "#80FFB0", "#20C040"),
            "warning": ("#4DC4FF", "#88DDFF", "#1A88CC"),
        }

        self._rating_btns = []
        self._prev_lbls   = []
        LABELS = ["Again", "Hard", "Good", "Easy"]
        for (orig_lbl, obj, q), color_lbl in zip(self.RATINGS, LABELS):
            bg, fg_hover, hv = RATING_COLORS.get(obj, ("#555","#FFF","#333"))
            # Extract icon+number prefix from orig_lbl e.g. "1  🔁 Again"
            btn = QPushButton(f"{orig_lbl.split()[0]}  {orig_lbl.split()[1]}  ?  {color_lbl}")
            btn.setFixedHeight(40)
            btn.setMinimumWidth(140)
            btn.setStyleSheet(
                f"QPushButton{{background:{bg};color:#1E1E2E;"
                f"border:none;border-radius:8px;"
                f"font-size:13px;font-weight:bold;padding:0 16px;}}"
                f"QPushButton:hover{{background:{fg_hover};color:#111;}}")
            btn.clicked.connect(lambda _, qq=q: self._rate(qq))
            rfl.addWidget(btn)
            self._rating_btns.append(btn)
            self._prev_lbls.append((btn, q))

        self._rating_frame.hide()

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

    def _on_canvas_zoom_settled(self):
        """Ctrl+scroll zoom settle hone ke baad — user zoom yaad rakho."""
        self._user_zoom_scale = self.canvas._scale

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
        # After session complete _idx == len(_items), use last card
        idx = self._idx
        if idx >= len(self._items):
            idx = len(self._items) - 1
        if not (0 <= idx < len(self._items)):
            return
        card, box_idx, sm2_obj = self._items[idx]
        scroll_pos = self._canvas_scroll.verticalScrollBar().value()
        review_scale = self.canvas._scale
        img_y = scroll_pos / max(review_scale, 0.01)

        # ── O(1) snapshot: box_ids before edit ────────────────────────────────
        before_ids = {b.get("box_id", ""): b.get("group_id", "")
                      for b in card.get("boxes", []) if b.get("box_id")}

        dlg = CardEditorDialog(self, card=dict(card), data=self._data,
                       initial_scroll=0, initial_page=None,
                       initial_img_y=img_y)
        self._active_editor = dlg
        dlg.finished.connect(lambda *_: setattr(self, "_active_editor", None))
        result = dlg.exec_()

        if result != QDialog.Accepted:
            self._reload_current_canvas()
            return

        edited = dlg.get_card()

        # [FIX] Preserve SM-2 data on existing boxes — editor returns fresh box
        # dicts that don't have SM-2 fields. If we do card.update(edited) blindly,
        # the new boxes list replaces the old one and all SM-2 state is lost.
        # Solution: merge SM-2 fields from old boxes into edited boxes by box_id.
        old_boxes_by_id = {b.get("box_id", ""): b for b in card.get("boxes", [])}
        SM2_KEYS = ("sched_state", "sched_step", "sm2_interval", "sm2_ease",
                    "sm2_due", "sm2_last_quality", "sm2_repetitions", "reviews")
        for new_box in edited.get("boxes", []):
            bid = new_box.get("box_id", "")
            if bid and bid in old_boxes_by_id:
                old = old_boxes_by_id[bid]
                for k in SM2_KEYS:
                    if k in old:
                        new_box[k] = old[k]   # preserve SM-2 state

        card.update(edited)
        if self._data:
            store.mark_dirty()

        after_ids = {b.get("box_id", ""): b.get("group_id", "")
                     for b in card.get("boxes", []) if b.get("box_id")}

        # ── O(1) detect deleted boxes → tombstone them ─────────────────────────
        for bid in before_ids:
            if bid not in after_ids:
                self._deleted_ids.add(bid)
                gid = before_ids[bid]
                if gid:
                    self._deleted_ids.add(gid)

        # ── O(1) detect new boxes → add only them to queue ────────────────────
        seen_new_groups = set()
        for box in card.get("boxes", []):
            bid = box.get("box_id", "")
            gid = box.get("group_id", "")
            track_id = gid if gid else bid
            if not track_id:
                continue
            if track_id in self._queued_ids:
                continue
            if track_id in self._deleted_ids:
                continue
            sm2_init(box)
            self._queued_ids.add(track_id)
            if gid:
                if gid not in seen_new_groups:
                    seen_new_groups.add(gid)
                    self._items.append((card, ("group", gid), box))
            else:
                i = card.get("boxes", []).index(box)
                self._items.append((card, i, box))

        # If session was done and new items added, resume from first new item
        if self._idx >= len(self._items):
            self._idx = max(0, len(self._items) - 1)

        self._rebuild_queue()
        self._reload_current_canvas()

    def _open_current_pdf_in_reader(self):
        idx = self._idx
        if idx >= len(self._items):
            idx = len(self._items) - 1
        if not (0 <= idx < len(self._items)):
            return

        card, _, _ = self._items[idx]
        path = card.get("pdf_path", "")
        if not path or not os.path.exists(path):
            self.canvas._show_toast("No PDF loaded for this card")
            return

        scroll_pos        = self._canvas_scroll.verticalScrollBar().value()
        current_page_zero = self.canvas.get_current_page(scroll_pos)
        current_page      = current_page_zero + 1
        self._external_pdf_path_hint = path
        self._external_pdf_page_hint = current_page_zero

        try:
            import subprocess

            if sys.platform == "win32":
                # PDF-XChange Editor — page jump via /A page=N
                xchange_paths = [
                    r"C:\Program Files\Tracker Software\PDF Editor\PDFXEdit.exe",
                    r"C:\Program Files (x86)\Tracker Software\PDF Editor\PDFXEdit.exe",
                    r"C:\Program Files\PDF-XChange\PDF-XChange Editor\PDFXEdit.exe",
                    r"C:\Program Files (x86)\PDF-XChange\PDF-XChange Editor\PDFXEdit.exe",
                ]
                for exe in xchange_paths:
                    if os.path.exists(exe):
                        subprocess.Popen([exe, "/A", f"page={current_page}", path])
                        self.canvas._show_toast(f"📄 Opened p.{current_page} in PDF-XChange")
                        return

                # PDF-XChange not found at known paths — try via registry
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PDFXEdit.exe")
                    exe = winreg.QueryValue(key, None)
                    winreg.CloseKey(key)
                    if exe and os.path.exists(exe):
                        subprocess.Popen([exe, "/A", f"page={current_page}", path])
                        self.canvas._show_toast(f"📄 Opened p.{current_page} in PDF-XChange")
                        return
                except Exception:
                    pass

                # Final fallback — open without page number
                os.startfile(path)
                self.canvas._show_toast("📄 Opened PDF (page jump not supported by this reader)")

            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
                self.canvas._show_toast(f"📄 Opened PDF p.{current_page}")
            else:
                subprocess.Popen(["xdg-open", path])
                self.canvas._show_toast(f"📄 Opened PDF p.{current_page}")

        except Exception as ex:
            QMessageBox.warning(self, "Could not open PDF", f"Could not open PDF:\n{ex}")

    def _reload_current_canvas(self, view_idx=None):
        """
        STEP 4 — Skeleton-first lazy loading.

        Flow:
          1. Image card      → unchanged (direct QPixmap load)
          2. PDF, full cache → instant (same as before)
          3. PDF, no/partial cache → NEW lazy path:
               a. load_pdf_skeleton() — grey placeholders, ~5ms
               b. canvas ready instantly with correct layout + page_tops
               c. _start_priority_render() — due-mask pages first
               d. scroll → _on_visible_pages_changed() → on-demand rest
          4. PDF missing     → grey fallback (unchanged)

        Terminal prints every decision point.
        """
        if view_idx is None:
            view_idx = self._idx

        if not (0 <= view_idx < len(self._items)):
            return
        card, box_idx, _ = self._items[view_idx]
        self._bg_pending_inserts.clear()
        self._pending_skeleton_result = None
        self._close_bg_prefetch_dialog()
        self._stop_skeleton_thread()

        import time
        t_start = time.perf_counter()
        fname   = os.path.basename(card.get("pdf_path", card.get("image_path", "?")))

        # ── 1. IMAGE CARD ─────────────────────────────────────────────────────
        if card.get("image_path") and os.path.exists(card["image_path"]):
            px = QPixmap(card["image_path"])
            if px and not px.isNull():
                self._apply_canvas(card, box_idx, px)
            return

        # ── 2. PDF CARD ───────────────────────────────────────────────────────
        if card.get("pdf_path") and PDF_SUPPORT:
            path = card["pdf_path"]
            self._pdf_watcher.watch_pdf(path)

            # ── 2a. PDF missing ───────────────────────────────────────────────
            if not os.path.exists(path):
                self._canvas_pdf_path = ""   # FIX 1: kills stale thread signals
                self.canvas.load_pixmap(QPixmap())
                boxes = card.get("boxes", [])
                if boxes:
                    display_boxes = [{**b, "revealed": False} for b in boxes]
                    self.canvas.set_boxes_with_state(display_boxes)
                    tgt = box_idx if isinstance(box_idx, int) else -1
                    self.canvas.set_target_box(tgt)
                    self.canvas.set_mode("review")
                    self.canvas._show_toast("PDF not found — Edit Card > Relink PDF to fix")
                self._show_overlay(self._reveal_bar)
                self._rating_frame.hide()
                self.setFocus()
                return

            # ── 2b. Full cache hit — instant ──────────────────────────────────
            try:
                _doc        = fitz.open(path)
                total_pages = len(_doc)
                _doc.close()
            except Exception:
                total_pages = 0

            clean_pages = {}
            for i in range(total_pages):
                pg = PAGE_CACHE.get(path, i)
                if pg and not pg.isNull():
                    clean_pages[i] = pg

            if total_pages > 0 and len(clean_pages) == total_pages:
                t_ms = (time.perf_counter() - t_start) * 1000
                self._canvas_pdf_path = path   # FIX 1: stamp
                self._apply_canvas_pages(card, box_idx, [clean_pages[i] for i in range(total_pages)])
                self._wire_scroll_ondemand(path, total_pages)
                return

            # ── 2c. NEW LAZY PATH — skeleton first ────────────────────────────
            self._pending_skeleton_result = {
                "card": card,
                "box_idx": box_idx,
                "clean_pages": clean_pages,
                "path": path,
                "t_start": t_start,
            }
            self._start_review_skeleton_thread(path)
            return

        # ── 3. FALLBACK — no image, no pdf ────────────────────────────────────

    # ── STEP 4 HELPERS ────────────────────────────────────────────────────────

    def _get_priority_pages(self, card, box_idx, total_pages, path=None):
        """
        Return the current mask page, every other due page from the same PDF,
        plus immediate neighbours. These pages render FIRST so the viewport
        stays responsive while the current review session is warming up.

        The goal is simple:
          1. current mask page
          2. other review pages from the same PDF
          3. one page before / after each priority page
        Everything else stays lazy and scroll-driven.
        """
        boxes    = card.get("boxes", [])
        pages    = set()
        card_path = path or card.get("pdf_path", "")

        def _add_pages_from_card(c, box_ref):
            c_boxes = c.get("boxes", [])
            if isinstance(box_ref, tuple) and box_ref[0] == "group":
                gid = box_ref[1]
                for b in c_boxes:
                    if b.get("group_id") == gid:
                        pn = b.get("page_num")
                        if pn is not None:
                            pages.add(pn)
            elif isinstance(box_ref, int) and 0 <= box_ref < len(c_boxes):
                pn = c_boxes[box_ref].get("page_num")
                if pn is not None:
                    pages.add(pn)

        # Preload every due page from the same PDF that is already in this
        # review session. This keeps the current PDF warm without fanning out
        # into a full-document background fill.
        if card_path:
            for c, box_ref, _sm2 in self._items:
                if c.get("pdf_path", "") != card_path:
                    continue
                _add_pages_from_card(c, box_ref)

        # Current box's page — always priority #1
        _add_pages_from_card(card, box_idx)
        # Also add pages adjacent to priority pages (±1) for smooth scroll
        adjacent = set()
        for pn in pages:
            if pn > 0:             adjacent.add(pn - 1)
            if pn < total_pages-1: adjacent.add(pn + 1)
        pages.update(adjacent)

        result = sorted(pages)
        return result

    def _stop_skeleton_thread(self):
        if self._skeleton_thread and self._skeleton_thread.isRunning():
            self._skeleton_thread.stop()
            self._skeleton_thread.quit()
            self._skeleton_thread.wait(500)
        self._skeleton_thread = None

    def _start_review_skeleton_thread(self, path):
        self._stop_skeleton_thread()
        self._skeleton_thread = PdfSkeletonThread(path, zoom=1.5, parent=self)
        self._skeleton_thread.done.connect(lambda skel, p=path: self._on_review_skeleton_ready(p, skel))
        self._skeleton_thread.error.connect(lambda err, p=path: self._on_review_skeleton_error(p, err))
        self._skeleton_thread.start()

    def _on_review_skeleton_error(self, path, err):
        pending = self._pending_skeleton_result
        if not pending or pending.get("path") != path:
            return
        card = pending.get("card")
        box_idx = pending.get("box_idx")
        self._pending_skeleton_result = None
        self._start_review_pdf_thread(card, box_idx)

    def _on_review_skeleton_ready(self, path, skel):
        pending = self._pending_skeleton_result
        if not pending or pending.get("path") != path:
            return
        self._pending_skeleton_result = None
        if not skel or getattr(skel, "error", None):
            self._on_review_skeleton_error(path, getattr(skel, "error", "Could not build PDF skeleton"))
            return
        self._apply_review_skeleton_result(
            pending["card"],
            pending["box_idx"],
            pending["clean_pages"],
            path,
            skel,
            pending["t_start"],
        )

    def _apply_review_skeleton_result(self, card, box_idx, clean_pages, path, skel, t_start):
        pages = list(skel.placeholders) if getattr(skel, "placeholders", None) else \
                build_skeleton_placeholders(getattr(skel, "page_dims", []))
        for i, pg in clean_pages.items():
            if 0 <= i < len(pages):
                pages[i] = pg
        if clean_pages:
            cached_idxs = sorted(clean_pages.keys())
        self._apply_canvas_pages(card, box_idx, pages)
        self.canvas._show_toast(f"⏳ Loading p.1–{skel.total_pages}...")
        t_skel_ms = (time.perf_counter() - t_start) * 1000

        priority_pages = self._get_priority_pages(card, box_idx, skel.total_pages, path)
        self._start_priority_render(path, priority_pages, skel.total_pages)
        self._wire_scroll_ondemand(path, skel.total_pages)

    def _start_priority_render(self, path, priority_pages, total_pages):
        """
        Launch PdfOnDemandThread for priority pages.
        On each page_ready → canvas.inject_page().
        On batch_done → start background fill for remaining pages.

        FIX 1: We stamp self._canvas_pdf_path = path here.
        _on_page_ready checks this stamp before injecting —
        if user switched card mid-render, stamp changes and
        stale signals are silently dropped. No more 'canvas has 0 pages'.
        """
        self._stop_ondemand_thread()
        self._ondemand_kind = "priority"
        self._background_fill_state = None
        self._bg_pending_inserts.clear()

        # ── FIX 1: stamp current PDF path on canvas ───────────────────────────
        # This is the guard key — _on_page_ready compares against this.
        self._canvas_pdf_path = path
        self.canvas._current_pdf_path = path

        already_cached = [p for p in priority_pages
                          if PAGE_CACHE.get(path, p) is not None]
        to_render      = [p for p in priority_pages
                          if PAGE_CACHE.get(path, p) is None]


        # Inject already-cached pages immediately (no thread needed)
        for pn in already_cached:
            pg = PAGE_CACHE.get(path, pn)
            if pg and not pg.isNull():
                self.canvas.inject_page(pn, pg)

        if not to_render:
            self._background_fill_state = None
            self._ondemand_kind = None
            self._start_background_fill(path, priority_pages, total_pages)
            return

        self._ondemand_thread = PdfOnDemandThread(path, to_render, zoom=1.5, parent=self)
        self._ondemand_path   = path
        self._ondemand_total  = total_pages
        self._priority_pages  = set(priority_pages)
        self._ondemand_kind   = "priority"

        self._ondemand_thread.page_ready.connect(self._on_page_ready)
        self._ondemand_thread.batch_done.connect(
            lambda rendered: self._on_priority_batch_done(path, priority_pages, total_pages)
        )
        self._ondemand_thread.error.connect(lambda err: None)
        self._ondemand_thread.start()

    def _on_priority_batch_done(self, path, priority_pages, total_pages):
        self._background_fill_state = None
        self._ondemand_kind = None
        if getattr(self, "_canvas_pdf_path", None) == path:
            self._start_background_fill(path, priority_pages, total_pages)

    # ── LRU window size for background fill ───────────────────────────────────
    # Background fill renders at most this many pages beyond priority set.
    # Keeps RAM bounded even for huge PDFs.
    # On-demand scroll handles anything outside this window.
    _BG_FILL_WINDOW = 15

    # Background fill runs in small batches so it can yield to scroll-driven
    # visible-page loads instead of monopolizing the render thread.
    _BG_FILL_BATCH = 2
    _BG_FILL_DELAY_MS = 250

    def _queue_background_ready(self, path, rendered):
        ready = [pn for pn in rendered if PAGE_CACHE.get(path, pn) is not None]
        if not ready:
            return
        for pn in ready:
            cached = PAGE_CACHE.get(path, pn)
            if cached and not cached.isNull():
                self._bg_pending_inserts[pn] = cached
        self._bg_prefetch_rendered_count += len(ready)
        total = self._bg_prefetch_total_pages or max(self._bg_prefetch_rendered_count, 1)
        self._bg_prefetch_cached_count = min(self._bg_prefetch_cached_count + len(ready), total)
        msg = "BG ready: " + ", ".join(f"p.{pn+1}" for pn in sorted(ready))
        self.canvas._show_toast(msg)
        self._note_user_activity()

    def _flush_pending_background_inserts(self):
        if not self._bg_pending_inserts:
            return
        if not self._bg_accept_mode:
            return
        current_path = getattr(self, "_canvas_pdf_path", None)
        if not current_path:
            self._bg_pending_inserts.clear()
            return
        if self._pending_visible_request:
            self._ui_idle_timer.start()
            return
        if self._ondemand_thread and self._ondemand_thread.isRunning() and getattr(self, "_ondemand_kind", None) == "visible":
            self._ui_idle_timer.start()
            return
        if self._ondemand_thread and self._ondemand_thread.isRunning() and getattr(self, "_ondemand_kind", None) == "background":
            # let the background render continue, but flush only on idle timeout
            return
        ready_items = sorted(self._bg_pending_inserts.items())
        self._bg_pending_inserts.clear()
        for pn, pg in ready_items:
            self.canvas.inject_page(pn, pg)
        if ready_items:
            self.canvas._show_toast("Inserted " + ", ".join(f"p.{pn+1}" for pn, _ in ready_items))

    def _start_background_fill(self, path, already_rendered, total_pages):
        cached_pages = sum(
            1 for page_num in range(total_pages)
            if PAGE_CACHE.get(path, page_num) is not None
        )
        self._bg_accept_mode = False
        self._bg_prefetch_total_pages = total_pages
        self._bg_prefetch_cached_count = cached_pages
        self._bg_prefetch_rendered_count = len(already_rendered)
        self._show_bg_prefetch_dialog(path, total_pages)
        self._sync_bg_prefetch_dialog(path, total_pages, done=False)
        self.canvas._show_toast(f"Ready: {cached_pages}/{total_pages} pages cached")

        # Defer if a visible-page request is in flight. Scroll responsiveness
        # wins over background cache completion.
        if self._ondemand_thread and self._ondemand_thread.isRunning():
            if getattr(self, "_ondemand_kind", None) == "visible":
                self._background_fill_state = (path, list(already_rendered), total_pages)
                return
            if getattr(self, "_ondemand_kind", None) == "background":
                print("[DEBUG][bg_fill] already running ? skipping duplicate start")
                return

        # ?? FIX 1 guard: if card switched, abort ?????????????????????????????
        if getattr(self, "_canvas_pdf_path", None) != path:
            return

        all_pages  = set(range(total_pages))
        skip       = set(already_rendered) | {
            p for p in all_pages if PAGE_CACHE.get(path, p) is not None
        }
        remaining  = sorted(all_pages - skip)

        if not remaining:
            self.canvas._show_toast(f"PDF ready: {total_pages} pages")
            self._background_fill_state = None
            self._ondemand_kind = None
            self._bg_accept_mode = True
            self._sync_bg_prefetch_dialog(path, total_pages, done=True)
            return

        skipped_count = 0
        windowed = remaining
        next_rendered = sorted(set(already_rendered) | set(windowed))

        self._stop_ondemand_thread()
        self._ondemand_kind = "background"
        self._background_fill_state = (path, next_rendered, total_pages)

        # Verify canvas is still intact after stop (regression check for the wipe bug)
        canvas_pages_after_stop = len(self.canvas._pages)
        if canvas_pages_after_stop == 0:
            return

        self._ondemand_thread = PdfOnDemandThread(
            path, windowed, zoom=1.5, parent=self)
        self._ondemand_path   = path
        self._ondemand_total  = total_pages
        self._ondemand_kind   = "background"

        self._ondemand_thread.page_ready.connect(self._on_page_ready)
        self._ondemand_thread.batch_done.connect(
            lambda rendered, p=path, ar=next_rendered, tp=total_pages: self._on_background_fill_batch_done(rendered, p, ar, tp)
        )
        self._ondemand_thread.error.connect(lambda err: None)
        self._ondemand_thread.start()

    def _on_background_fill_batch_done(self, rendered, path, already_rendered, total_pages):
        combined = sorted(set(already_rendered) | set(rendered))
        self._queue_background_ready(path, rendered)
        remaining = [
            pn for pn in range(total_pages)
            if PAGE_CACHE.get(path, pn) is None and pn not in combined
        ]

        if path != getattr(self, "_canvas_pdf_path", None):
            self._background_fill_state = None
            self._ondemand_kind = None
            return

        if remaining:
            self._background_fill_state = (path, combined, total_pages)
            self._ondemand_kind = None
            self._sync_bg_prefetch_dialog(path, total_pages, done=False)
            self._ui_idle_timer.start(self._BG_FILL_DELAY_MS)
            return

        self._background_fill_state = None
        self._ondemand_kind = None
        self._bg_accept_mode = True
        self._sync_bg_prefetch_dialog(path, total_pages, done=True)
        self.canvas._show_toast(f"PDF ready: {total_pages} pages")

    def _wire_scroll_ondemand(self, path, total_pages):
        """
        Connect scroll area's visible_pages_changed signal → on-demand render.
        Safe to call multiple times — disconnects old connection first.
        """
        try:
            self._canvas_scroll.visible_pages_changed.disconnect(
                self._on_visible_pages_changed)
        except Exception:
            pass   # not connected yet — fine

        # Store path+total for use in the slot
        self._ondemand_path  = path
        self._ondemand_total = total_pages

        self._canvas_scroll.visible_pages_changed.connect(
            self._on_visible_pages_changed)

    def _on_visible_pages_changed(self, first, last):
        """
        Called 120ms after scroll stops (debounced).
        Renders any visible pages that are still placeholders.
        """
        self._note_user_activity()
        path        = getattr(self, "_ondemand_path", None)
        total_pages = getattr(self, "_ondemand_total", 0)

        if not path:
            return

        needed = [pn for pn in range(first, last + 1) if PAGE_CACHE.get(path, pn) is None]

        if not needed:
            return


        if self._ondemand_thread and self._ondemand_thread.isRunning():
            if getattr(self, "_ondemand_kind", None) == "background":
                self._stop_ondemand_thread()
                self._ondemand_kind = None
                self._start_visible_page_request(path, needed)
                return

            self._pending_visible_request = (path, list(needed))
            print(f"[DEBUG][on_visible] render thread busy - queued pages {[p+1 for p in needed]}")
            return

        self._start_visible_page_request(path, needed)

    def _start_visible_page_request(self, path, needed):
        self._pending_visible_request = None
        self._ondemand_kind = "visible"
        self._ondemand_thread = PdfOnDemandThread(path, needed, zoom=1.5, parent=self)
        self._ondemand_thread.page_ready.connect(self._on_page_ready)
        self._ondemand_thread.batch_done.connect(self._on_visible_pages_batch_done)
        self._ondemand_thread.start()
        

    def _on_visible_pages_batch_done(self, rendered):
        self._note_user_activity()

        pending = self._pending_visible_request
        self._pending_visible_request = None
        if pending and pending[0] == getattr(self, "_ondemand_path", None):
            path, needed = pending
            fresh_needed = [pn for pn in needed if PAGE_CACHE.get(path, pn) is None]
            if fresh_needed:
                self._start_visible_page_request(path, fresh_needed)
            else:
                self._ondemand_kind = None
        elif getattr(self, "_ondemand_kind", None) == "visible":
            self._ondemand_kind = None

        bg_state = self._background_fill_state
        if bg_state and not (self._ondemand_thread and self._ondemand_thread.isRunning()) and not self._pending_visible_request:
            bg_path, bg_already_rendered, bg_total = bg_state
            if getattr(self, "_canvas_pdf_path", None) == bg_path:
                self._start_background_fill(bg_path, bg_already_rendered, bg_total)

    def _on_page_ready(self, page_num, qpx):
        """
        Slot — called from PdfOnDemandThread.page_ready signal.

        FIX 1: Check _canvas_pdf_path stamp before injecting.
        If user switched to a different card mid-render, the thread's
        path no longer matches the canvas's current PDF — drop the signal.
        This is what caused 'canvas has 0 pages' — canvas was already
        wiped by the new card's load_pages() call.
        """
        current_path = getattr(self, "_canvas_pdf_path", None)
        thread_path  = getattr(self, "_ondemand_path", None)

        if current_path != thread_path:
            return

        canvas_len = len(self.canvas._pages)
        canvas_wh  = f"{self.canvas.width()}x{self.canvas.height()}px"

        # Guard: canvas wiped — should not happen after _stop_ondemand_thread fix
        if canvas_len == 0:
            return

        if getattr(self, "_ondemand_kind", None) == "background":
            self._bg_pending_inserts[page_num] = qpx
            print(f"[DEBUG][page_ready] background page queued p.{page_num+1}")
            return
        self.canvas.inject_page(page_num, qpx)
    def _stop_ondemand_thread(self):
        """
        Safely stop any running PdfOnDemandThread.

        ── BUG FIX (v20-patch) ──────────────────────────────────────────────────
        BEFORE (broken):
            if thread running  → stop it
            else               → canvas.load_pixmap(QPixmap())   ← WIPED _pages!

        The else branch fired every time _stop_ondemand_thread() was called when
        no thread was running yet — e.g. the very first call from
        _start_background_fill() right after skeleton load.
        load_pixmap(null-QPixmap) sets _pages=[] and resizes canvas to 1×1 px,
        so every subsequent inject_page() hit "out of range (canvas has 0 pages)".

        FIX: simply remove the else branch. Callers that need UI resets
        (_show_overlay, _rating_frame.hide) already do so themselves.
        ─────────────────────────────────────────────────────────────────────────
        """
        t = getattr(self, "_ondemand_thread", None)
        if t and t.isRunning():
            t.stop()
            t.quit()
            t.wait(400)
        # Always clear the reference so the next start gets a fresh thread
        self._ondemand_thread = None
        
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

        # FIX: retain user-set zoom for image cards too
        from PyQt5.QtCore import QTimer
        def _apply_zoom_and_center_img():
            if self._user_zoom_scale is not None:
                self.canvas._scale = self._user_zoom_scale
                self.canvas._on_zoom()
            else:
                self._zoom_fit()
            self._center_on_target()
        QTimer.singleShot(0, _apply_zoom_and_center_img)

    def _apply_canvas_pages(self, card, box_idx, pages):
        """File: anki_occlusion_v19.py -> Class: ReviewScreen"""
        path = card.get("pdf_path", "")
        self._canvas_pdf_path = path
        self.canvas._current_pdf_path = path
        if hasattr(self.canvas, "clear_peek_target"):
            self.canvas.clear_peek_target()

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
        self._show_overlay(self._reveal_bar)
        self._rating_frame.hide()

        # 6. Zoom fit + center (deferred so viewport geometry is final)
        from PyQt5.QtCore import QTimer
        if self._pending_reload_page is not None:
            reload_page = self._pending_reload_page
            self._pending_reload_page = None
            QTimer.singleShot(0, lambda pg=reload_page: (self._zoom_fit(), self.canvas.scroll_to_page(pg, self._canvas_scroll)))
        else:
            # FIX: retain user-set zoom across cards
            def _apply_zoom_and_center():
                if self._user_zoom_scale is not None:
                    self.canvas._scale = self._user_zoom_scale
                    self.canvas._on_zoom()
                else:
                    self._zoom_fit()
                self._center_on_target()
            QTimer.singleShot(0, _apply_zoom_and_center)

        # 7. Rebuild queue now that _page_tops is populated with real page positions
        QTimer.singleShot(50, self._rebuild_queue)
        # 8. Force a visible-page pass after the viewport settles so already-cached
        #    pages show immediately when returning to review.
        QTimer.singleShot(120, self._canvas_scroll._emit_visible_pages)
        
    def _start_review_pdf_thread(self, card, box_idx):
        path = card.get("pdf_path", "")
        if hasattr(self, "_pdf_loader_thread") and self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(300)

        self._pdf_loader_thread     = PdfLoaderThread(path, parent=self)
        self._pending_review_card   = card
        self._pending_review_box_idx = box_idx

        # [FIX] Show first chunk instantly as pages arrive
        self._pdf_loader_thread.pages_ready.connect(self._on_review_pages_chunk)
        self._pdf_loader_thread.done.connect(self._on_review_pages_ready)
        self._pdf_loader_thread.start()

        # Show loading toast immediately
        try:
            _doc = fitz.open(path)
            total = len(_doc)
            _doc.close()
        except Exception:
            total = "?"
        self.canvas._show_toast(f"⏳ Loading PDF... 0/{total} pages")
        self._pdf_total_pages = total

    def _on_review_pages_chunk(self, pages, loaded, total):
        """Show first pages as soon as first chunk arrives — don't wait for full load."""
        card    = self._pending_review_card
        box_idx = self._pending_review_box_idx
        if pages:
            self._apply_canvas_pages(card, box_idx, pages)
        self.canvas._show_toast(f"⏳ Loading PDF... {loaded}/{total} pages")

    def _on_review_pages_ready(self, pages, err):
        if not pages or err:
            return
        card    = self._pending_review_card
        box_idx = self._pending_review_box_idx
        self._apply_canvas_pages(card, box_idx, pages)
        self.canvas._show_toast(f"✅ PDF loaded — {len(pages)} pages")







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
        dlg.setFixedSize(340, 345)
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

        if self._stimer:
            L.addWidget(_stat_row("⏱  Time spent", self._stimer.elapsed_str(), C_SUBTEXT))

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



# ═══════════════════════════════════════════════════════════════════════════════
