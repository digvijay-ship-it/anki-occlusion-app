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

CARD_DRAG_MIME = "application/x-anki-card"

#  DECK TREE
# ═══════════════════════════════════════════════════════════════════════════════

class _DeckTreeWidget(QTreeWidget):
    """QTreeWidget with a custom bright drop-indicator line drawn in paintEvent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_line_y  = -1   # screen-y of indicator line, -1 = hidden
        self._drop_line_indent = 0

    def set_drop_line(self, y: int, indent: int = 0):
        self._drop_line_y      = y
        self._drop_line_indent = indent
        self.viewport().update()

    def clear_drop_line(self):
        self._drop_line_y = -1
        self.viewport().update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drop_line_y < 0:
            return
        p = QPainter(self.viewport())
        pen = QPen(QColor("#7C6AF7"), 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        x1 = self._drop_line_indent
        x2 = self.viewport().width() - 8
        y  = self._drop_line_y
        p.drawLine(x1, y, x2, y)
        # Draw a small circle on left to make it look like a insertion point
        p.setBrush(QColor("#7C6AF7"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(x1, y - 4, 8, 8)
        p.end()


class DeckTree(QWidget):
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._last_drop_pos  = None
        self._last_drop_item = None
        self._last_drop_ctrl = False
        self._blink_state    = False
        self._ensure_ids()
        self._setup_ui()
        # Blink timer — toggles due badge color every 800ms
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink_tick)
        self._blink_timer.start(800)
        self.refresh()

    def _blink_tick(self):
        """Toggle blink state and repaint all due items."""
        self._blink_state = not self._blink_state
        def _walk(item):
            due_str = item.data(0, Qt.UserRole + 1)
            if due_str and int(due_str) > 0:
                name  = item.data(0, Qt.UserRole + 2)
                due   = int(due_str)
                badge = f"🔴{due}" if self._blink_state else f"⭕{due}"
                item.setText(0, f"  📂  {name}  {badge}")
            for i in range(item.childCount()):
                _walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            _walk(self.tree.topLevelItem(i))

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
        self.tree = _DeckTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
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
        self.tree.dropEvent    = self._on_tree_drop
        self.tree.dragEnterEvent = self._on_drag_enter
        self.tree.dragMoveEvent  = self._on_drag_move
        self.tree.dragLeaveEvent = self._on_drag_leave
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
        # Drop hint — shows during drag to guide user
        self._drop_hint = QLabel("↕ Reorder — hold Ctrl to nest inside")
        self._drop_hint.setStyleSheet(
            "background:#534AB7;color:white;font-size:11px;"
            "padding:4px 8px;border-radius:4px;")
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setVisible(False)
        L.addWidget(self._drop_hint)
        hint = QLabel("Double-click to open  •  Right-click for menu")
        hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;")
        hint.setAlignment(Qt.AlignCenter)
        L.addWidget(hint)

    def refresh(self):
        sel_id = self._get_selected_id()
        self.tree.clear()
        for deck in self._data.get("decks", []):
            self.tree.addTopLevelItem(self._make_item(deck))
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

        def _total_due(d):
            """Recursively count due cards in this deck and all children."""
            total = sum(1 for c in d.get("cards", []) if _card_due(c))
            for child in d.get("children", []):
                total += _total_due(child)
            return total

        due   = _total_due(deck)
        badge = f"🔴{due}" if due else "✅"
        item  = QTreeWidgetItem([f"  📂  {deck['name']}  {badge}"])
        item.setData(0, Qt.UserRole,     deck.get("_id"))
        item.setData(0, Qt.UserRole + 1, str(due))           # for blink timer
        item.setData(0, Qt.UserRole + 2, deck['name'])       # for blink timer
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
        # ── Duplicate name check ──────────────────────────────────────────────
        siblings = (self._data.get("decks", []) if parent_id is None
                    else (find_deck_by_id(parent_id, self._data.get("decks", [])) or {}).get("children", []))
        dup = next((d for d in siblings if d["name"].strip().lower() == name.strip().lower()), None)
        if dup:
            action = self._duplicate_dialog(name.strip())
            if action == "show":
                self._select_by_id(dup["_id"])
                return
            elif action == "retry":
                self._new_deck(parent_id)
                return
            else:
                return
        # ─────────────────────────────────────────────────────────────────────
        new_deck = {
            "_id":      next_deck_id(self._data),
            "name":     name.strip(),
            "cards":    [],
            "children": [],
            "created":  datetime.now().isoformat()
        }
        print(f"[DeckTree][new_deck] ➕ creating '{name.strip()}' parent={parent_id}")
        deck_history.push(self._data)   # ← undo snapshot
        if parent_id is None:
            self._data.setdefault("decks", []).append(new_deck)
        else:
            parent = find_deck_by_id(parent_id, self._data.get("decks", []))
            if parent is None:
                QMessageBox.warning(self, "Error", "Parent deck not found!")
                return
            parent.setdefault("children", []).append(new_deck)
        store.mark_dirty()
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
            # ── Duplicate name check ──────────────────────────────────────────
            parent = self._find_parent(deck_id, self._data.get("decks", []))
            siblings = parent.get("children", []) if parent else self._data.get("decks", [])
            dup = next((d for d in siblings if d["name"].strip().lower() == name.strip().lower()
                        and d.get("_id") != deck_id), None)
            if dup:
                action = self._duplicate_dialog(name.strip())
                if action == "show":
                    self._select_by_id(dup["_id"])
                    return
                elif action == "retry":
                    self._rename_by_id(deck_id)
                    return
                else:
                    return
            # ─────────────────────────────────────────────────────────────────
            print(f"[DeckTree][rename] ✏ '{deck.get('name')}' → '{name.strip()}'")
            deck_history.push(self._data)   # ← undo snapshot
            deck["name"] = name.strip()
            store.mark_dirty()
            self.refresh()

    def _duplicate_dialog(self, name):
        """
        Show a 3-button dialog when a duplicate deck name is entered.
        Returns: 'show' | 'retry' | 'cancel'
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Duplicate Name")
        dlg.setMinimumWidth(340)
        L = QVBoxLayout(dlg)
        L.setSpacing(12)
        L.setContentsMargins(16, 16, 16, 16)

        msg = QLabel(f"A deck named <b>'{name}'</b> already exists at this level.")
        msg.setWordWrap(True)
        L.addWidget(msg)

        btn_row = QHBoxLayout()
        b_show   = QPushButton("📍 Show Existing")
        b_retry  = QPushButton("✏ Try Again")
        b_cancel = QPushButton("Cancel")
        b_cancel.setObjectName("flat")
        btn_row.addWidget(b_show)
        btn_row.addWidget(b_retry)
        btn_row.addStretch()
        btn_row.addWidget(b_cancel)
        L.addLayout(btn_row)

        result = ["cancel"]
        b_show.clicked.connect(lambda: (result.__setitem__(0, "show"), dlg.accept()))
        b_retry.clicked.connect(lambda: (result.__setitem__(0, "retry"), dlg.accept()))
        b_cancel.clicked.connect(dlg.reject)

        dlg.exec_()
        return result[0]

    def _find_parent(self, deck_id, lst, parent=None):
        """Return the parent deck dict of the given deck_id, or None if top-level."""
        for d in lst:
            if d.get("_id") == deck_id:
                return parent
            found = self._find_parent(deck_id, d.get("children", []), d)
            if found is not None:
                return found
        return None

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
        print(f"[DeckTree][delete] 🗑 deleting '{deck['name']}' id={deck_id}")
        deck_history.push(self._data)   # ← undo snapshot
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

    def _on_drag_enter(self, event):
        if (event.mimeData().hasFormat(CARD_DRAG_MIME) or
                event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist")):
            event.accept()
        else:
            event.ignore()

    def _on_drag_move(self, event):
        if (event.mimeData().hasFormat(CARD_DRAG_MIME) or
                event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist")):
            self._last_drop_pos  = self.tree.dropIndicatorPosition()
            self._last_drop_item = self.tree.itemAt(event.pos())
            ctrl = bool(event.keyboardModifiers() & Qt.ControlModifier)
            self._last_drop_ctrl = ctrl
            item = self._last_drop_item

            # ── Draw custom drop line ─────────────────────────────────────────
            if item and not ctrl:
                rect  = self.tree.visualItemRect(item)
                pos   = self._last_drop_pos
                line_y = rect.top() if pos == QAbstractItemView.AboveItem else rect.bottom()
                self.tree.set_drop_line(line_y, rect.left())
            else:
                self.tree.clear_drop_line()

            # ── Hint label ────────────────────────────────────────────────────
            if item:
                name  = item.data(0, Qt.UserRole)
                deck  = find_deck_by_id(name, self._data.get("decks", []))
                dname = deck["name"] if deck else "?"
                if ctrl:
                    self._drop_hint.setText(f"📂 Drop INTO '{dname}' as child")
                    self._drop_hint.setStyleSheet(
                        "background:#1D9E75;color:white;font-size:11px;"
                        "padding:4px 8px;border-radius:4px;")
                else:
                    self._drop_hint.setText("↕ Reorder — hold Ctrl to nest inside")
                    self._drop_hint.setStyleSheet(
                        "background:#534AB7;color:white;font-size:11px;"
                        "padding:4px 8px;border-radius:4px;")
            self._drop_hint.setVisible(True)
            event.accept()
        else:
            event.ignore()

    def _on_drag_leave(self, event=None):
        self._drop_hint.setVisible(False)
        self.tree.clear_drop_line()

    def _on_tree_drop(self, event):
        # ── Card dropped from DeckView onto a deck ────────────────────────────
        if event.mimeData().hasFormat(CARD_DRAG_MIME):
            target_item = self.tree.itemAt(event.pos())
            if target_item is None:
                event.ignore(); return
            target_id   = self._get_id_from_item(target_item)
            target_deck = find_deck_by_id(target_id, self._data["decks"])
            if target_deck is None:
                event.ignore(); return

            raw         = bytes(event.mimeData().data(CARD_DRAG_MIME)).decode()
            src_id_str, row_str = raw.split("|")
            src_deck    = find_deck_by_id(int(src_id_str), self._data["decks"])
            if src_deck is None or src_deck is target_deck:
                event.ignore(); return

            cards = src_deck.get("cards", [])
            row   = int(row_str)
            if not (0 <= row < len(cards)):
                event.ignore(); return
            
            print(f"[DeckTree][drop] 🃏 card row={row} moved to '{target_deck.get('name')}'")
            deck_history.push(self._data)   # ← undo snapshot
            card = cards.pop(row)
            target_deck.setdefault("cards", []).append(card)
            store.mark_dirty()
            self.refresh()
            self._select_by_id(target_id)
            event.accept()
            return

        # ── Deck reorder (InternalMove) ───────────────────────────────────────
        self._drop_hint.setVisible(False)
        self.tree.clear_drop_line()
        target_item = getattr(self, '_last_drop_item', self.tree.itemAt(event.pos()))
        drop_pos    = getattr(self, '_last_drop_pos', self.tree.dropIndicatorPosition())
        ctrl        = getattr(self, '_last_drop_ctrl', False)
        dragged_id  = self._get_selected_id()
        if dragged_id is None:
            event.ignore(); return
        print(f"[DeckTree][drop] 🗂 reordering id={dragged_id}, ctrl={ctrl}")
        deck_history.push(self._data)   # ← undo snapshot
        deck = self._detach_deck(dragged_id, self._data["decks"])
        if deck is None:
            event.ignore(); return

        if target_item is None:
            self._data["decks"].append(deck)
        else:
            tid   = self._get_id_from_item(target_item)
            tdeck = find_deck_by_id(tid, self._data["decks"])
            if tdeck is None:
                self._data["decks"].append(deck)
            elif ctrl:
                # Ctrl held → nest as child
                tdeck.setdefault("children", []).append(deck)
            else:
                # No Ctrl → always reorder as sibling
                plist = self._find_parent_list(tid, self._data["decks"])
                if plist is None:
                    self._data["decks"].append(deck)
                else:
                    idx = next((i for i, d in enumerate(plist) if d["_id"] == tid), None)
                    if idx is None:
                        self._data["decks"].append(deck)
                    else:
                        insert_at = idx if drop_pos == QAbstractItemView.AboveItem else idx + 1
                        plist.insert(insert_at, deck)

        store.mark_dirty()
        event.accept()
        # [FIX] Defer refresh so Qt finishes its internal InternalMove first,
        # otherwise the visual tree and data tree conflict and changes only
        # appear after restart.
        QTimer.singleShot(0, lambda: (self.refresh(), self._select_by_id(dragged_id)))

    def _detach_deck(self, deck_id, lst):
        """Remove and return a deck from wherever it lives in the tree."""
        for i, d in enumerate(lst):
            if d["_id"] == deck_id:
                return lst.pop(i)
            found = self._detach_deck(deck_id, d.get("children", []))
            if found:
                return found
        return None

    def _find_parent_list(self, deck_id, lst):
        """Return the list that directly contains deck_id."""
        for d in lst:
            if d["_id"] == deck_id:
                return lst
            found = self._find_parent_list(deck_id, d.get("children", []))
            if found:
                return found
        return None

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
        # self.setStyleSheet(f"""
        #     QFrame#cacheFrame {{
        #         background:{C_SURFACE};
        #         border-left:1px solid {C_BORDER};
        #         border-radius:0px;
        #     }}
        #     QLabel {{ background:transparent; }}
        # """)
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
        from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY
        COMBINED_CACHE.invalidate(pdf_path)
        PAGE_CACHE.invalidate_pdf(pdf_path)
        MASK_REGISTRY.invalidate_masks_for_pdf(pdf_path)
        # [FIX] Remove PDF from MASK_REGISTRY map entirely so box disappears
        MASK_REGISTRY._map.pop(pdf_path, None)
        # [FIX] Also unregister from PIXMAP_REGISTRY
        for label in [l for l, (_, _, p) in PIXMAP_REGISTRY._entries.items() if p == pdf_path]:
            PIXMAP_REGISTRY.unregister(label)
        self.refresh()

    def _clear_all(self):
        from cache_manager import PAGE_CACHE, COMBINED_CACHE, MASK_REGISTRY, PIXMAP_REGISTRY
        COMBINED_CACHE.clear()
        PAGE_CACHE.clear_ram_only()
        MASK_REGISTRY._map.clear()
        # [FIX] Also clear PIXMAP_REGISTRY so all boxes disappear
        for label in list(PIXMAP_REGISTRY._entries.keys()):
            PIXMAP_REGISTRY.unregister(label)
        self.refresh()

# ═══════════════════════════════════════════════════════════════════════════════
