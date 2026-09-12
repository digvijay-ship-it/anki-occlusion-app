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
from perf_utils import build_deck_rollups, trace_perf

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
    QShortcut,
    QCheckBox,
    QComboBox,
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
    QKeySequence,
)

import tempfile

# ── Single-instance lock file ─────────────────────────────────────────────────
LOCK_FILE = os.path.join(tempfile.gettempdir(), "anki_occlusion.lock")


# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

# ── Theme constants — single source of truth is theme_manager.PALETTES["dark"] ──
from theme_manager import get_palette as _get_palette, normalize_theme

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

# ── Depth-based color palettes for deck tree hierarchy ────────────────────────
DEPTH_COLORS = {
    "classic": [
        "#4DABF7",  # 0: Soft Indigo Blue
        "#38D9A9",  # 1: Emerald Teal
        "#FF922B",  # 2: Warm Orange
        "#B197FC",  # 3: Rich Lavender
        "#FF8787",  # 4: Coral Red
        "#3BC9DB",  # 5: Cyan Teal
    ],
    "dojo": [
        "#39FF14",  # 0: Electric Green
        "#FF2DF1",  # 1: Hot Magenta
        "#00D4FF",  # 2: Laser Cyan
        "#FF6600",  # 3: Vivid Orange
        "#FFFF00",  # 4: Neon Yellow
        "#FF1493",  # 5: Deep Pink
    ],
    "tmnt": [
        "#00FFFF",  # 0: Full Cyan
        "#32CD32",  # 1: Lime Green
        "#FF8C00",  # 2: Dark Orange
        "#DA70D6",  # 3: Orchid Purple
        "#FF4444",  # 4: Bright Red
        "#FFD700",  # 5: Gold
    ],
    "manhattan": [
        "#00f0ff",  # 0: Cyber Mutant Cyan
        "#ffa200",  # 1: Pizza Orange
        "#39ff14",  # 2: Sewer Slime Green
        "#ff0055",  # 3: Foot Clan Red
        "#ffcc00",  # 4: Arcade Coin Yellow
        "#a86cff",  # 5: Arcade Purple
    ],
}


def depth_color(depth: int, theme: str = "classic") -> str:
    """Return a hex color for the given nesting depth and theme."""
    palette = DEPTH_COLORS.get(theme, DEPTH_COLORS["classic"])
    return palette[depth % len(palette)]



BASE_FONT_SIZE = 11
HOME_ANIMATIONS_ENV = "ANKI_HOME_ANIMATIONS"
CACHE_AUTO_REFRESH_MS = 30000


def _home_animations_enabled() -> bool:
    return os.environ.get(HOME_ANIMATIONS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        self._drop_line_y = -1  # screen-y of indicator line, -1 = hidden
        self._drop_line_indent = 0
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def keyPressEvent(self, e):
        from services import shortcut_manager
        if shortcut_manager.event_matches(e, "home.browse_cards"):
            sel_deck = getattr(self, "_selected_deck", None)
            p = self.parent()
            while p is not None:
                if not sel_deck:
                    sel_deck = getattr(p, "_selected_deck", None)
                if hasattr(p, "main") and hasattr(p.main, "_open_card_browser"):
                    if not getattr(p.main, "deck", None) and sel_deck:
                        p.main.load_deck(sel_deck, getattr(p.main, "_data", None) or getattr(p, "_data", None))
                    p.main._open_card_browser()
                    e.accept()
                    return
                if hasattr(p, "deck_view") and getattr(p, "deck_view", None):
                    if not getattr(p.deck_view, "deck", None) and sel_deck:
                        p.deck_view.load_deck(sel_deck, getattr(p, "_data", None) or getattr(p.deck_view, "_data", None))
                    p.deck_view._open_card_browser()
                    e.accept()
                    return
                if hasattr(p, "_open_card_browser"):
                    p._open_card_browser()
                    e.accept()
                    return
                p = p.parent()
            win = self.window()
            if win and hasattr(win, "centralWidget"):
                home = win.centralWidget()
                if home and hasattr(home, "_open_card_browser"):
                    home._open_card_browser()
                    e.accept()
                    return
        if shortcut_manager.event_matches(e, "home.edit_card") or (e.key() == Qt.Key_E and (e.modifiers() & Qt.ControlModifier) and not (e.modifiers() & (Qt.AltModifier | Qt.MetaModifier))):
            sel_deck = getattr(self, "_selected_deck", None)
            p = self.parent()
            while p is not None:
                if not sel_deck:
                    sel_deck = getattr(p, "_selected_deck", None)
                if hasattr(p, "_get_deck_from_item") and not sel_deck and hasattr(self, "currentItem"):
                    cur = self.currentItem()
                    if cur:
                        sel_deck = p._get_deck_from_item(cur)
                target_view = getattr(p, "main", None) or getattr(p, "deck_view", None)
                if target_view:
                    if sel_deck and getattr(target_view, "deck", None) != sel_deck:
                        target_view.load_deck(sel_deck, getattr(target_view, "_data", None) or getattr(p, "_data", None))
                    item = target_view.card_list.currentItem()
                    if not item and target_view.card_list.count() > 0:
                        item = target_view.card_list.item(0)
                        target_view.card_list.setCurrentItem(item)
                    if item:
                        target_view._edit_card(item)
                        e.accept()
                        return
                    elif getattr(target_view, "deck", None):
                        def _find_card(d):
                            if d.get("cards"):
                                return d["cards"][0], d
                            for child in d.get("children", []):
                                r = _find_card(child)
                                if r:
                                    return r
                            return None, None
                        sub_card, sub_d = _find_card(target_view.deck)
                        if sub_card and sub_d:
                            target_view._edit_card_by_dict(sub_card, sub_d)
                            e.accept()
                            return
                        else:
                            target_view._add_card()
                            e.accept()
                            return
                p = p.parent()
        if e.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                       Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape,
                       Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Home, Qt.Key_End,
                       Qt.Key_PageUp, Qt.Key_PageDown):
            super().keyPressEvent(e)
            return
        
        text = e.text()
        if text and text.isprintable() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            e.ignore()
            return
            
        super().keyPressEvent(e)

    def keyboardSearch(self, search):
        pass

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        # Override to prevent horizontal scrolling on item selection/focus
        super().scrollTo(index, hint)
        self.horizontalScrollBar().setValue(0)

    def set_drop_line(self, y: int, indent: int = 0):
        self._drop_line_y = y
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
        y = self._drop_line_y
        p.drawLine(x1, y, x2, y)
        # Draw a small circle on left to make it look like a insertion point
        p.setBrush(QColor("#7C6AF7"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(x1, y - 4, 8, 8)
        p.end()


DECK_TREE_DISPLAY_FONT = "Segoe UI"


class DeckItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, theme="classic"):
        super().__init__(parent)
        self.theme = normalize_theme(theme)

    def paint(self, painter, option, index):
        if self.theme != "dojo":
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        is_selected = option.state & QStyle.State_Selected
        is_hovered = option.state & QStyle.State_MouseOver
        rect = option.rect

        # Background
        if is_selected:
            painter.fillRect(rect, QColor(168, 108, 255, 38))  # rgba(168,108,255, 0.15)
            painter.setPen(QPen(QColor("#A86CFF"), 2))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        elif is_hovered:
            painter.setBrush(QColor(80, 250, 123, 20))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
            painter.setPen(QPen(QColor("#50FA7B"), 4))
            painter.drawLine(
                rect.left() + 2, rect.top() + 4, rect.left() + 2, rect.bottom() - 4
            )

        name = index.data(Qt.UserRole + 2) or "Unknown"
        due_str = index.data(Qt.UserRole + 1)
        due = int(due_str) if due_str else 0

        from dojo_assets import DojoAssets

        icon = DojoAssets.get().get_clan_icon(name, 32)

        # Draw Icon (Centered vertically)
        icon_rect = QRect(
            rect.left() + 8, rect.top() + (rect.height() - 32) // 2, 32, 32
        )
        if not icon.isNull():
            # Clip icon to rounded rect to remove artifacts
            path = QPainterPath()
            path.addRoundedRect(QRectF(icon_rect), 6, 6)
            painter.setClipPath(path)
            painter.drawPixmap(icon_rect, icon)
            painter.setClipping(False)

            # Subtle border around icon
            painter.setPen(QPen(QColor("#45475A"), 1))
            painter.drawRoundedRect(icon_rect, 6, 6)

        # Draw Text — use depth-based color
        depth = index.data(Qt.UserRole + 4) or 0
        is_paused = bool(index.data(Qt.UserRole + 6))
        if is_paused:
            painter.setPen(QColor("#FFB86C" if not is_selected else "#FFFFFF"))
        else:
            painter.setPen(QColor("#A86CFF" if is_selected else depth_color(depth, "dojo")))
        font = QFont(DECK_TREE_DISPLAY_FONT, 9, QFont.Bold)
        painter.setFont(font)
        text_rect = QRect(
            icon_rect.right() + 12,
            rect.top(),
            rect.width() - icon_rect.width() - 60,
            rect.height(),
        )
        bookmarked = index.data(Qt.UserRole + 5)
        display_name = name.upper()
        if bookmarked:
            display_name = "🔖 " + display_name
        if is_paused:
            display_name = "⏸️ " + display_name
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, display_name)

        # Draw Badge
        if is_paused:
            p_badge_w = 52
            p_badge_h = 20
            p_badge_rect = QRect(
                rect.right() - p_badge_w - 12,
                rect.top() + (rect.height() - p_badge_h) // 2,
                p_badge_w,
                p_badge_h,
            )
            painter.setPen(QPen(QColor("#FFB86C"), 1))
            painter.setBrush(QColor(40, 42, 54, 220))
            painter.drawRoundedRect(p_badge_rect, 4, 4)
            badge_font = QFont(DECK_TREE_DISPLAY_FONT, 7, QFont.Bold)
            painter.setFont(badge_font)
            painter.setPen(QColor("#FFB86C"))
            painter.drawText(p_badge_rect, Qt.AlignCenter, "PAUSED")
        elif due > 0:
            badge_w = 24
            badge_h = 20
            badge_rect = QRect(
                rect.right() - badge_w - 12,
                rect.top() + (rect.height() - badge_h) // 2,
                badge_w,
                badge_h,
            )
            painter.setBrush(QColor("#FF5555"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, 4, 4)
            painter.setPen(QColor("#FFFFFF"))
            font = QFont("Segoe UI", 9, QFont.Bold)
            painter.setFont(font)
            painter.drawText(badge_rect, Qt.AlignCenter, str(due))
        else:
            badge_w = 24
            badge_h = 20
            badge_rect = QRect(
                rect.right() - badge_w - 12,
                rect.top() + (rect.height() - badge_h) // 2,
                badge_w,
                badge_h,
            )
            painter.setPen(QColor("#50FA7B"))
            font = QFont("Segoe UI", 12, QFont.Bold)
            painter.setFont(font)
            painter.drawText(badge_rect, Qt.AlignCenter, "✓")

        painter.restore()

    def sizeHint(self, option, index):
        if self.theme != "dojo":
            return super().sizeHint(option, index)
        name = index.data(Qt.UserRole + 2) or "Unknown"
        bookmarked = index.data(Qt.UserRole + 5)
        display_name = name.upper()
        if bookmarked:
            display_name = "🔖 " + display_name
        font = QFont(DECK_TREE_DISPLAY_FONT, 9, QFont.Bold)
        from PyQt5.QtGui import QFontMetrics

        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(display_name)
        return QSize(w + 100, 48)



class DeckSettingsDialog(QDialog):
    """
    Deck Settings Dialog
    Allows configuring per-deck daily review limits, pause state, and review priority order.
    Complies with Generous Typography rules (large readable fonts and inputs).
    """
    def __init__(self, parent=None, deck=None, data=None):
        super().__init__(parent)
        self.deck = deck or {}
        self._data = data
        deck_title = str(self.deck.get("name", "Deck"))
        self.setWindowTitle(f"⚙️ Deck Settings — {deck_title}")
        self.setModal(True)
        self.setMinimumWidth(860)
        self.setMinimumHeight(740)
        self.resize(920, 800)
        self.setStyleSheet("""
            QDialog {
                background-color: #151821;
                color: #F8F8F2;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
            QLabel {
                color: #F8F8F2;
                background: transparent;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #12141A;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #3D4457;
                border-radius: 5px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #50FA7B;
            }
            QFrame#cardFrame {
                background-color: #1E222D;
                border: 1px solid #2D3342;
                border-radius: 10px;
                padding: 22px;
            }
            QFrame#bottomBar {
                background-color: #101218;
                border-top: 1px solid #2D3342;
            }
            QLineEdit {
                background-color: #12141A;
                color: #50FA7B;
                border: 2px solid #3D4457;
                border-radius: 6px;
                font-size: 24px;
                font-weight: bold;
                padding: 8px 14px;
            }
            QLineEdit:focus {
                border-color: #50FA7B;
                background-color: #171A22;
            }
            QComboBox {
                background-color: #12141A;
                color: #F8F8F2;
                border: 2px solid #3D4457;
                border-radius: 6px;
                font-size: 20px;
                font-weight: 600;
                padding: 10px 16px;
            }
            QComboBox:focus {
                border-color: #BD93F9;
            }
            QComboBox QAbstractItemView {
                background-color: #1E222D;
                color: #F8F8F2;
                selection-background-color: #BD93F9;
                selection-color: #151821;
                font-size: 19px;
                padding: 8px;
            }
            QCheckBox {
                color: #F8F8F2;
                font-size: 21px;
                font-weight: 700;
                spacing: 14px;
            }
            QCheckBox::indicator {
                width: 28px;
                height: 28px;
                border-radius: 5px;
                border: 2px solid #3D4457;
                background-color: #12141A;
            }
            QCheckBox::indicator:checked {
                background-color: #FFB86C;
                border-color: #FFB86C;
            }
            QPushButton#btnSave {
                background-color: #50FA7B;
                color: #0D1117;
                font-size: 20px;
                font-weight: 900;
                border: none;
                border-radius: 8px;
                padding: 14px 32px;
                min-width: 220px;
            }
            QPushButton#btnSave:hover {
                background-color: #69FF91;
            }
            QPushButton#btnCancel {
                background-color: transparent;
                color: #AAB1C4;
                font-size: 18px;
                font-weight: 700;
                border: 1px solid #3D4457;
                border-radius: 8px;
                padding: 14px 28px;
                min-width: 140px;
            }
            QPushButton#btnCancel:hover {
                background-color: rgba(255, 255, 255, 0.05);
                color: #FFFFFF;
                border-color: #6272A4;
            }
        """)
        self._setup_ui()

    def _setup_ui(self):
        from PyQt5.QtGui import QIntValidator, QKeySequence
        from PyQt5.QtWidgets import QScrollArea, QShortcut

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll Area for all settings content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(32, 24, 32, 24)
        scroll_layout.setSpacing(20)

        # Header
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("🏯")
        icon_lbl.setStyleSheet("font-size: 36px;")
        header_layout.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)
        deck_name = str(self.deck.get("name", "Deck"))
        lbl_title = QLabel(deck_name.upper())
        lbl_title.setStyleSheet("font-size: 28px; font-weight: 900; color: #50FA7B; letter-spacing: 1px;")
        lbl_sub = QLabel("DECK CONFIGURATION & STUDY LIMITS / डेक सेटिंग्स")
        lbl_sub.setStyleSheet("font-size: 16px; font-weight: bold; color: #8F9BB3; letter-spacing: 1px;")
        title_layout.addWidget(lbl_title)
        title_layout.addWidget(lbl_sub)

        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        scroll_layout.addLayout(header_layout)

        # Card: Daily Review Limit
        card_limit = QFrame()
        card_limit.setObjectName("cardFrame")
        cl_layout = QVBoxLayout(card_limit)
        cl_layout.setSpacing(14)

        # 1. Daily New Cards Limit
        lbl_new_title = QLabel("🌱 Daily New Cards Limit (दैनिक नए कार्ड्स लिमिट):")
        lbl_new_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #50FA7B;")
        cl_layout.addWidget(lbl_new_title)

        row_new = QHBoxLayout()
        row_new.setSpacing(16)
        self.inp_daily_new_limit = QLineEdit()
        self.inp_daily_new_limit.setValidator(QIntValidator(0, 9999, self))
        self.inp_daily_new_limit.setFixedWidth(220)
        self.inp_daily_new_limit.setAlignment(Qt.AlignCenter)
        curr_new = self.deck.get("daily_new_limit", 0) or 0
        self.inp_daily_new_limit.setText(str(curr_new) if curr_new > 0 else "")
        self.inp_daily_new_limit.setPlaceholderText("0 (Unlimited)")
        row_new.addWidget(self.inp_daily_new_limit)

        lbl_new_unit = QLabel("new cards / day (नए कार्ड्स प्रतिदिन)")
        lbl_new_unit.setStyleSheet("font-size: 19px; font-weight: 600; color: #50FA7B;")
        row_new.addWidget(lbl_new_unit)
        row_new.addStretch()
        cl_layout.addLayout(row_new)

        lbl_new_desc = QLabel(
            "प्रतिदिन अधिकतम कितने नए कार्ड्स पढ़ने हैं। 0 या खाली रखने पर Unlimited रहेगा।"
        )
        lbl_new_desc.setStyleSheet("font-size: 18px; color: #CDD6F4; line-height: 1.4;")
        lbl_new_desc.setWordWrap(True)
        cl_layout.addWidget(lbl_new_desc)

        # Divider between new and review
        div_new = QFrame()
        div_new.setFrameShape(QFrame.HLine)
        div_new.setStyleSheet("background-color: #2D3342; max-height: 1px; margin: 6px 0px;")
        cl_layout.addWidget(div_new)

        # 2. Daily Review / Due Limit
        lbl_rev_title = QLabel("📅 Daily Review / Due Target (दैनिक रिवीजन लिमिट):")
        lbl_rev_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #FFB86C;")
        cl_layout.addWidget(lbl_rev_title)

        row_rev = QHBoxLayout()
        row_rev.setSpacing(16)
        self.inp_daily_review_limit = QLineEdit()
        self.inp_daily_review_limit.setValidator(QIntValidator(0, 9999, self))
        self.inp_daily_review_limit.setFixedWidth(220)
        self.inp_daily_review_limit.setAlignment(Qt.AlignCenter)
        curr_rev = self.deck.get("daily_review_limit", 0) or 0
        self.inp_daily_review_limit.setText(str(curr_rev) if curr_rev > 0 else "")
        self.inp_daily_review_limit.setPlaceholderText("0 (Unlimited)")
        row_rev.addWidget(self.inp_daily_review_limit)

        lbl_rev_unit = QLabel("due cards / day (ड्यू कार्ड्स प्रतिदिन)")
        lbl_rev_unit.setStyleSheet("font-size: 19px; font-weight: 600; color: #FFB86C;")
        row_rev.addWidget(lbl_rev_unit)
        row_rev.addStretch()
        cl_layout.addLayout(row_rev)

        lbl_rev_desc = QLabel(
            "प्रतिदिन अधिकतम कितने Due / रिवीजन कार्ड्स हल करने हैं। 0 या खाली रखने पर Unlimited रहेगा।"
        )
        lbl_rev_desc.setStyleSheet("font-size: 18px; color: #CDD6F4; line-height: 1.4;")
        lbl_rev_desc.setWordWrap(True)
        cl_layout.addWidget(lbl_rev_desc)

        # Divider between review and total cap
        div_cap = QFrame()
        div_cap.setFrameShape(QFrame.HLine)
        div_cap.setStyleSheet("background-color: #2D3342; max-height: 1px; margin: 6px 0px;")
        cl_layout.addWidget(div_cap)

        # 3. Overall Total Daily Cap
        lbl_limit_title = QLabel("🎯 Total Daily Cap (कुल दैनिक सीमा - New + Due):")
        lbl_limit_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #8BE9FD;")
        cl_layout.addWidget(lbl_limit_title)

        input_row = QHBoxLayout()
        input_row.setSpacing(16)

        self.inp_daily_limit = QLineEdit()
        self.inp_daily_limit.setValidator(QIntValidator(0, 9999, self))
        self.inp_daily_limit.setFixedWidth(220)
        self.inp_daily_limit.setAlignment(Qt.AlignCenter)
        current_limit = self.deck.get("daily_limit", 0)
        self.inp_daily_limit.setText(str(current_limit) if current_limit > 0 else "")
        self.inp_daily_limit.setPlaceholderText("0 (Unlimited)")
        input_row.addWidget(self.inp_daily_limit)

        lbl_unit = QLabel("total cards / day (कुल कार्ड्स प्रतिदिन)")
        lbl_unit.setStyleSheet("font-size: 19px; font-weight: 600; color: #8BE9FD;")
        input_row.addWidget(lbl_unit)
        input_row.addStretch()
        cl_layout.addLayout(input_row)

        lbl_limit_desc = QLabel(
            "इस डेक से प्रतिदिन अधिकतम कुल कार्ड्स (New + Due)। 0 या खाली रखने पर Unlimited रहेगा।"
        )
        lbl_limit_desc.setStyleSheet("font-size: 18px; color: #CDD6F4; line-height: 1.4;")
        lbl_limit_desc.setWordWrap(True)
        cl_layout.addWidget(lbl_limit_desc)

        # Divider
        div_line = QFrame()
        div_line.setFrameShape(QFrame.HLine)
        div_line.setStyleSheet("background-color: #2D3342; max-height: 1px; margin: 8px 0px;")
        cl_layout.addWidget(div_line)

        # 4. Session Target
        lbl_sess_title = QLabel("⏱️ Session Review Target (प्रति सेशन टारगेट):")
        lbl_sess_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #BD93F9;")
        cl_layout.addWidget(lbl_sess_title)

        sess_row = QHBoxLayout()
        sess_row.setSpacing(16)

        self.inp_session_limit = QLineEdit()
        self.inp_session_limit.setValidator(QIntValidator(1, 9999, self))
        self.inp_session_limit.setFixedWidth(220)
        self.inp_session_limit.setAlignment(Qt.AlignCenter)
        current_sess = self.deck.get("session_limit", 25)
        self.inp_session_limit.setText(str(current_sess) if current_sess > 0 else "25")
        self.inp_session_limit.setPlaceholderText("25")
        sess_row.addWidget(self.inp_session_limit)

        lbl_sess_unit = QLabel("cards / session (कार्ड्स प्रति सेशन)")
        lbl_sess_unit.setStyleSheet("font-size: 19px; font-weight: 600; color: #BD93F9;")
        sess_row.addWidget(lbl_sess_unit)
        sess_row.addStretch()
        cl_layout.addLayout(sess_row)

        self.chk_auto_exit = QCheckBox("Take Break on Target (टारगेट पूरा होने पर ब्रेक लें और बाहर आएं)")
        self.chk_auto_exit.setChecked(bool(self.deck.get("auto_exit_session", True)))
        cl_layout.addWidget(self.chk_auto_exit)

        lbl_auto_exit_desc = QLabel(
            "जैसे ही 25 (या तय किए गए) कार्ड्स पूरे होंगे, ऐप आपको ब्रेक लेने का विकल्प देगा और रिव्यू स्क्रीन से बाहर ले आएगा ताकि आप दूसरा विषय पढ़ सकें।"
        )
        lbl_auto_exit_desc.setStyleSheet("font-size: 18px; color: #CDD6F4; margin-left: 42px; line-height: 1.4;")
        lbl_auto_exit_desc.setWordWrap(True)
        cl_layout.addWidget(lbl_auto_exit_desc)

        scroll_layout.addWidget(card_limit)

        # Card: Pause Status & Review Order
        card_opts = QFrame()
        card_opts.setObjectName("cardFrame")
        co_layout = QVBoxLayout(card_opts)
        co_layout.setSpacing(16)

        self.chk_pause = QCheckBox("Pause Deck (डेक पॉज / फ्रीज करें)")
        from data_manager import is_deck_effective_paused
        all_decks = (self._data.get("decks", []) if getattr(self, "_data", None) else None) or (self.parent()._data.get("decks", []) if hasattr(self.parent(), "_data") else None)
        self.chk_pause.setChecked(is_deck_effective_paused(self.deck, all_decks))
        co_layout.addWidget(self.chk_pause)

        lbl_pause_desc = QLabel(
            "पॉज करने पर नए अनदेखे कार्ड्स आना रुक जाएंगे। जो कार्ड्स पहले से Due हैं, "
            "उन्हें आप 'Start Training' से कभी भी पढ़ सकते हैं।"
        )
        lbl_pause_desc.setStyleSheet("font-size: 18px; color: #FFB86C; margin-left: 42px; line-height: 1.4;")
        lbl_pause_desc.setWordWrap(True)
        co_layout.addWidget(lbl_pause_desc)

        lbl_order = QLabel("🔀 Review Order (प्राथमिकता क्रम):")
        lbl_order.setStyleSheet("font-size: 22px; font-weight: 700; color: #F8F8F2; margin-top: 6px;")
        co_layout.addWidget(lbl_order)

        self.combo_order = QComboBox()
        self.combo_order.addItem("📅 Due Date (Standard / नियत तारीख)", "default")
        self.combo_order.addItem("🌱 Least Mature First (कम याद वाले कार्ड्स पहले)", "least_mature")

        curr_order = self.deck.get("review_order", "default")
        idx = self.combo_order.findData(curr_order)
        if idx >= 0:
            self.combo_order.setCurrentIndex(idx)
        co_layout.addWidget(self.combo_order)

        scroll_layout.addWidget(card_opts)
        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=1)

        # Pinned Bottom Action Bar (always 100% visible at bottom)
        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottomBar")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(32, 14, 32, 14)
        bottom_layout.setSpacing(16)

        lbl_tip = QLabel("💡 Tip: Press Enter or Ctrl+S to save immediately")
        lbl_tip.setStyleSheet("font-size: 16px; color: #8F9BB3; font-weight: 500;")
        bottom_layout.addWidget(lbl_tip)
        bottom_layout.addStretch()

        self.btn_cancel = QPushButton("✕ CANCEL (Esc)")
        self.btn_cancel.setObjectName("btnCancel")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("💾 SAVE SETTINGS (Enter)")
        self.btn_save.setObjectName("btnSave")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_settings)
        bottom_layout.addWidget(self.btn_save)

        main_layout.addWidget(bottom_bar, stretch=0)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_settings)
        QShortcut(QKeySequence("Return"), self, self._save_settings)
        QShortcut(QKeySequence("Enter"), self, self._save_settings)
        QShortcut(QKeySequence("Esc"), self, self.reject)

    def _save_settings(self):
        new_text = self.inp_daily_new_limit.text().strip()
        try:
            new_val = int(new_text) if new_text else 0
        except ValueError:
            new_val = 0
        daily_new_val = max(0, new_val)

        rev_text = self.inp_daily_review_limit.text().strip()
        try:
            rev_val = int(rev_text) if rev_text else 0
        except ValueError:
            rev_val = 0
        daily_review_val = max(0, rev_val)

        text = self.inp_daily_limit.text().strip()
        try:
            val = int(text) if text else 0
        except ValueError:
            val = 0
        limit_val = max(0, val)

        sess_text = self.inp_session_limit.text().strip()
        try:
            sess_val = int(sess_text) if sess_text else 25
        except ValueError:
            sess_val = 25
        session_val = max(1, sess_val)

        is_paused_val = self.chk_pause.isChecked()
        auto_exit_val = self.chk_auto_exit.isChecked()
        order_val = self.combo_order.currentData() or "default"

        all_decks = (self._data.get("decks", []) if getattr(self, "_data", None) else None) or (self.parent()._data.get("decks", []) if hasattr(self.parent(), "_data") else None)
        from data_manager import is_deck_effective_paused, cascade_deck_pause
        orig_paused = is_deck_effective_paused(self.deck, all_decks)

        self.deck["daily_new_limit"] = daily_new_val
        self.deck["daily_review_limit"] = daily_review_val
        self.deck["daily_limit"] = limit_val
        self.deck["session_limit"] = session_val
        self.deck["auto_exit_session"] = auto_exit_val
        self.deck["is_paused"] = is_paused_val
        self.deck["review_order"] = order_val

        from datetime import date
        today_iso = date.today().isoformat()
        if is_paused_val:
            if "pause_backlog_cutoff" not in self.deck:
                self.deck["pause_backlog_cutoff"] = today_iso
            if "pause_last_shift_date" not in self.deck:
                self.deck["pause_last_shift_date"] = today_iso
        else:
            self.deck.pop("pause_backlog_cutoff", None)
            self.deck.pop("pause_last_shift_date", None)

        if is_paused_val != orig_paused:
            cascade_deck_pause(self.deck, is_paused_val, today_iso)

        store.save_force(async_save=True)
        self.accept()


class DeckTree(QWidget):
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, theme="classic", parent=None):
        super().__init__(parent)
        self._data = data
        self._theme = normalize_theme(theme)
        self._last_drop_pos = None
        self._last_drop_item = None
        self._last_drop_ctrl = False
        self._blink_state = False
        self._ensure_ids()
        self._setup_ui()
        self._blink_enabled = _home_animations_enabled()
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(800)
        self._blink_timer.timeout.connect(self._blink_tick)
        self._sync_blink_timer()
        self.refresh()

    def set_blink_enabled(self, enabled: bool):
        self._blink_enabled = bool(enabled)
        self._sync_blink_timer()

    def _sync_blink_timer(self):
        if self._blink_enabled and self.isVisible():
            if not self._blink_timer.isActive():
                self._blink_timer.start()
        else:
            self._blink_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_blink_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._blink_timer.stop()

    def _blink_tick(self):
        """Toggle blink state and repaint all due items."""
        self._blink_state = not self._blink_state

        def _walk(item):
            due_str = item.data(0, Qt.UserRole + 1)
            if due_str and int(due_str) > 0:
                name = item.data(0, Qt.UserRole + 2)
                due = int(due_str)
                badge = f"🔴{due}" if self._blink_state else f"⭕{due}"
                if getattr(self, "_theme", "classic") == "classic":
                    bookmarked = item.data(0, Qt.UserRole + 5)
                    bookmark_str = " 🔖" if bookmarked else ""
                    item.setText(0, f"  📂  {name}{bookmark_str}  {badge}")
                    # Preserve depth-based text color
                    d = item.data(0, Qt.UserRole + 4) or 0
                    item.setForeground(0, QBrush(QColor(depth_color(d, "classic"))))
                else:
                    item.setText(0, "")
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

    def _on_search(self, text):
        query = text.strip().lower()

        if query:
            # Snapshot tree expansion state when search begins
            if not hasattr(self, "_pre_search_expansion_state") or self._pre_search_expansion_state is None:
                self._pre_search_expansion_state = {}
                def _save_state(item):
                    did = item.data(0, Qt.UserRole)
                    if did is not None:
                        self._pre_search_expansion_state[did] = item.isExpanded()
                    for i in range(item.childCount()):
                        _save_state(item.child(i))
                for i in range(self.tree.topLevelItemCount()):
                    _save_state(self.tree.topLevelItem(i))

            def _filter_item(item, parent_matched=False):
                name = item.data(0, Qt.UserRole + 2) or ""
                self_matched = bool(query in name.lower())
                is_matched_context = self_matched or parent_matched

                any_child_matched = False
                for i in range(item.childCount()):
                    child_matched = _filter_item(item.child(i), parent_matched=is_matched_context)
                    if child_matched:
                        any_child_matched = True

                visible = bool(self_matched or parent_matched or any_child_matched)
                item.setHidden(not visible)

                # Expansion rules:
                # 1. If a descendant matched, expand so the user can see the matched item.
                # 2. If this item or its parent matched, do NOT force expand; keep collapsed (or pre-search state).
                if any_child_matched:
                    item.setExpanded(True)
                else:
                    was_expanded = self._pre_search_expansion_state.get(item.data(0, Qt.UserRole), False)
                    item.setExpanded(was_expanded)

                return self_matched or any_child_matched

            for i in range(self.tree.topLevelItemCount()):
                _filter_item(self.tree.topLevelItem(i), parent_matched=False)

        else:
            # Search cleared: unhide all and restore exact pre-search expansion states
            saved_state = getattr(self, "_pre_search_expansion_state", None)

            def _restore_all(item):
                item.setHidden(False)
                did = item.data(0, Qt.UserRole)
                if saved_state is not None and did in saved_state:
                    item.setExpanded(saved_state[did])
                for i in range(item.childCount()):
                    _restore_all(item.child(i))

            for i in range(self.tree.topLevelItemCount()):
                _restore_all(self.tree.topLevelItem(i))

            self._pre_search_expansion_state = None

    def set_theme(self, theme):
        theme = normalize_theme(theme)
        self._theme = theme
        self._delegate.theme = theme
        if theme == "dojo":
            self._classic_hdr.hide()
            self._classic_btns_w.hide()
            self._dojo_hdr_w.show()
            self._dojo_btns_w.show()
            self.layout().setContentsMargins(0, 0, 0, 0)
        else:
            self._dojo_hdr_w.hide()
            self._dojo_btns_w.hide()
            self._classic_hdr.show()
            self._classic_btns_w.show()
            self.layout().setContentsMargins(0, 0, 0, 0)
        self.refresh()

    def _focus_search(self):
        if hasattr(self, "search_in") and self.search_in:
            self.search_in.setFocus(Qt.ShortcutFocusReason)
            self.search_in.selectAll()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)

        # --- Classic Header ---
        self._classic_hdr_w = QWidget()
        chl = QHBoxLayout(self._classic_hdr_w)
        chl.setContentsMargins(0, 0, 0, 0)
        self._classic_hdr = QLabel("📚  Decks")
        self._classic_hdr.setFont(QFont("Segoe UI", 13, QFont.Bold))
        chl.addWidget(self._classic_hdr)
        chl.addStretch()
        self.btn_classic_lock = QPushButton()
        self.btn_classic_lock.setFixedSize(28, 28)
        self.btn_classic_lock.setCursor(Qt.PointingHandCursor)
        self.btn_classic_lock.clicked.connect(self._toggle_structure_lock)
        chl.addWidget(self.btn_classic_lock)
        L.addWidget(self._classic_hdr_w)

        # --- Dojo Header ---
        self._dojo_hdr_w = QWidget()
        dhl = QVBoxLayout(self._dojo_hdr_w)
        dhl.setContentsMargins(12, 16, 12, 0)
        dhl.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        logo = QLabel("⛩")
        logo.setStyleSheet(f"color:{C_GREEN};font-size:18px;")
        top_row.addWidget(logo)
        title = QLabel("DOJO CAVA")
        title.setFont(QFont(DECK_TREE_DISPLAY_FONT, 14, QFont.Bold))
        title.setStyleSheet(f"color:{C_GREEN};letter-spacing:2px;")
        top_row.addWidget(title)
        top_row.addStretch()
        dhl.addLayout(top_row)
        dhl.addSpacing(4)

        search_box = QFrame()
        search_box.setStyleSheet(
            f"background:transparent;border:1px solid {C_BORDER};border-radius:4px;"
        )
        search_box.setFixedHeight(32)
        sh_l = QHBoxLayout(search_box)
        sh_l.setContentsMargins(8, 0, 8, 0)
        search_icon = QLabel("⌕")
        search_icon.setStyleSheet(f"color:{C_SUBTEXT};border:none;")
        sh_l.addWidget(search_icon)
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Search scrolls...")
        self.search_in.setClearButtonEnabled(True)
        self.search_in.setStyleSheet(
            f"background:transparent;border:none;color:{C_TEXT};"
        )
        self.search_in.textChanged.connect(self._on_search)
        
        def _search_key_press(e):
            if e.key() == Qt.Key_Escape:
                if self.search_in.text():
                    self.search_in.clear()
                else:
                    self.search_in.clearFocus()
                    if hasattr(self, "tree") and self.tree:
                        self.tree.setFocus()
                e.accept()
                return
            QLineEdit.keyPressEvent(self.search_in, e)
        self.search_in.keyPressEvent = _search_key_press
        
        sh_l.addWidget(self.search_in)
        shortcut_badge = QLabel("CTRL+F")
        shortcut_badge.setStyleSheet(
            f"color:{C_SUBTEXT};background:rgba(255,255,255,0.05);border-radius:3px;padding:2px 4px;font-size:9px;border:none;"
        )
        sh_l.addWidget(shortcut_badge)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_row.addWidget(search_box, stretch=1)

        self.btn_lock_structure = QPushButton()
        self.btn_lock_structure.setFixedSize(32, 32)
        self.btn_lock_structure.setCursor(Qt.PointingHandCursor)
        self.btn_lock_structure.clicked.connect(self._toggle_structure_lock)
        search_row.addWidget(self.btn_lock_structure)

        dhl.addLayout(search_row)
        dhl.addSpacing(6)
        
        # Shortcut to focus search
        self._shortcut_focus_f = QShortcut(QKeySequence("Ctrl+F"), self)
        self._shortcut_focus_f.setContext(Qt.WindowShortcut)
        self._shortcut_focus_f.activated.connect(self._focus_search)
        
        self._shortcut_focus_k = QShortcut(QKeySequence("Ctrl+K"), self)
        self._shortcut_focus_k.setContext(Qt.WindowShortcut)
        self._shortcut_focus_k.activated.connect(self._focus_search)

        hdr_dojo = QLabel("— YOUR DOJOS —")
        hdr_dojo.setFont(QFont("Orbitron", 9, QFont.Bold))
        hdr_dojo.setStyleSheet(
            f"color:{C_SUBTEXT};letter-spacing:2px;background:transparent;"
        )
        dhl.addWidget(hdr_dojo)
        L.addWidget(self._dojo_hdr_w)

        self.tree = _DeckTreeWidget()
        self._delegate = DeckItemDelegate(self.tree, getattr(self, "_theme", "classic"))
        self.tree.setItemDelegate(self._delegate)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
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
        L.addWidget(self.tree, stretch=1)

        # --- Classic Buttons ---
        self._classic_btns_w = QWidget()
        cbl = QHBoxLayout(self._classic_btns_w)
        cbl.setContentsMargins(0, 0, 0, 0)
        cb_new = QPushButton("＋ Deck")
        cb_new.clicked.connect(lambda: self._new_deck(None))
        cb_sub = QPushButton("＋ Sub")
        cb_sub.clicked.connect(self._new_subdeck)
        cb_import = QPushButton("📥 Import")
        cb_import.setToolTip("Import cards from comma-separated text or CSV file")
        cb_import.clicked.connect(lambda: self._import_cards(self._get_selected_id()))
        cb_del = QPushButton("🗑")
        cb_del.setObjectName("danger")
        cb_del.setFixedWidth(36)
        cb_del.clicked.connect(self._delete_selected)
        cbl.addWidget(cb_new)
        cbl.addWidget(cb_sub)
        cbl.addWidget(cb_import)
        cbl.addStretch()
        cbl.addWidget(cb_del)
        L.addWidget(self._classic_btns_w)

        # --- Dojo Buttons ---
        self._dojo_btns_w = QWidget()
        dbl = QHBoxLayout(self._dojo_btns_w)
        dbl.setContentsMargins(12, 0, 12, 12)
        db_new = QPushButton("⊕ NEW DOJO")
        db_new.setFont(QFont(DECK_TREE_DISPLAY_FONT, 9, QFont.Bold))
        db_new.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:6px 12px;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}"
        )
        db_new.clicked.connect(lambda: self._new_deck(None))
        db_sub = QPushButton("⊕ SUB")
        db_sub.setFont(QFont(DECK_TREE_DISPLAY_FONT, 9, QFont.Bold))
        db_sub.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:6px 12px;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}"
        )
        db_sub.clicked.connect(self._new_subdeck)
        db_del = QPushButton("⚙")
        db_del.setFixedSize(32, 32)
        db_del.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {C_BORDER};color:{C_SUBTEXT};border-radius:4px;font-size:16px;}} QPushButton:hover{{background:rgba(255,255,255,0.05);}}"
        )
        dbl.addWidget(db_new)
        dbl.addWidget(db_sub)
        dbl.addStretch()
        dbl.addWidget(db_del)
        L.addWidget(self._dojo_btns_w)

        # Drop hint
        self._drop_hint = QLabel("↕ Reorder — hold Ctrl to nest inside")
        self._drop_hint.setStyleSheet(
            "background:#534AB7;color:white;font-size:11px;padding:4px 8px;border-radius:4px;"
        )
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setVisible(False)
        L.addWidget(self._drop_hint)

        self.set_theme(getattr(self, "_theme", "classic"))
        self._structure_locked = self._is_structure_locked_saved()
        self.set_structure_locked(self._structure_locked)

    def _is_structure_locked_saved(self) -> bool:
        from PyQt5.QtCore import QSettings
        return bool(QSettings("AnkiOcclusion", "App").value("deck_structure_locked", False, type=bool))

    def _save_structure_locked(self, locked: bool):
        from PyQt5.QtCore import QSettings
        QSettings("AnkiOcclusion", "App").setValue("deck_structure_locked", bool(locked))

    def _update_lock_button_ui(self):
        is_locked = getattr(self, "_structure_locked", False)
        lock_icon = "🔒" if is_locked else "🔓"
        lock_tip = (
            "🔒 Deck Structure Locked (डेक लॉक है)\nDrag & drop moving and reordering is disabled.\nClick to unlock."
            if is_locked
            else "🔓 Deck Structure Unlocked (डेक अनलॉक है)\nDrag & drop moving and reordering is enabled.\nClick to lock."
        )
        lock_style = (
            f"QPushButton {{ background: rgba(255, 184, 108, 0.2); color: #FFB86C; border: 1.5px solid #FFB86C; border-radius: 4px; font-size: 16px; }}"
            f"QPushButton:hover {{ background: rgba(255, 184, 108, 0.35); }}"
            if is_locked
            else f"QPushButton {{ background: transparent; border: 1px solid {C_BORDER}; border-radius: 4px; font-size: 16px; color: {C_SUBTEXT}; }}"
            f"QPushButton:hover {{ background: rgba(255, 255, 255, 0.08); border-color: {C_TEXT}; }}"
        )
        if hasattr(self, "btn_lock_structure") and self.btn_lock_structure:
            self.btn_lock_structure.setText(lock_icon)
            self.btn_lock_structure.setToolTip(lock_tip)
            self.btn_lock_structure.setStyleSheet(lock_style)
        if hasattr(self, "btn_classic_lock") and self.btn_classic_lock:
            self.btn_classic_lock.setText(lock_icon)
            self.btn_classic_lock.setToolTip(lock_tip)
            self.btn_classic_lock.setStyleSheet(lock_style)

    def _toggle_structure_lock(self):
        new_state = not getattr(self, "_structure_locked", False)
        self._save_structure_locked(new_state)
        self.set_structure_locked(new_state)

        home = self._find_home()
        if home:
            if hasattr(home, "_tmnt_layout") and home._tmnt_layout:
                if hasattr(home._tmnt_layout, "set_structure_locked"):
                    home._tmnt_layout.set_structure_locked(new_state)
                elif hasattr(home._tmnt_layout, "sidebar") and hasattr(home._tmnt_layout.sidebar, "set_structure_locked"):
                    home._tmnt_layout.sidebar.set_structure_locked(new_state)
                elif hasattr(home._tmnt_layout, "main") and hasattr(home._tmnt_layout.main, "set_structure_locked"):
                    home._tmnt_layout.main.set_structure_locked(new_state)
            if hasattr(home, "deck_view") and home.deck_view and hasattr(home.deck_view, "set_structure_locked"):
                home.deck_view.set_structure_locked(new_state)

    def set_structure_locked(self, locked: bool):
        self._structure_locked = bool(locked)
        self._update_lock_button_ui()
        if hasattr(self, "tree") and self.tree:
            if self._structure_locked:
                self.tree.setDragEnabled(False)
                self.tree.setAcceptDrops(False)
                self.tree.viewport().setAcceptDrops(False)
                self.tree.setDragDropMode(QAbstractItemView.NoDragDrop)
            else:
                self.tree.setDragEnabled(True)
                self.tree.setAcceptDrops(True)
                self.tree.viewport().setAcceptDrops(True)
                self.tree.setDragDropMode(QAbstractItemView.InternalMove)

    def refresh(self):
        try:
            store.check_and_apply_paused_decks_timeline_shift()
        except Exception:
            pass
        sel_id = self._get_selected_id()
        rollups = build_deck_rollups(self._data.get("decks", []))
        self._due_counts = rollups["due_cards"]
        self.tree.clear()
        for deck in self._data.get("decks", []):
            self.tree.addTopLevelItem(self._make_item(deck))
        self.set_structure_locked(getattr(self, "_structure_locked", False))
        if sel_id is not None:
            self._select_by_id(sel_id)

    def _make_item(self, deck, depth=0, parent_is_paused=False):
        if "is_paused" in deck and deck["is_paused"] is not None:
            is_paused = bool(deck["is_paused"])
        else:
            is_paused = parent_is_paused
        due = getattr(self, "_due_counts", {}).get(deck.get("_id"), 0)
        badge = (f"⏸️ PAUSED ({due})" if due else "⏸️ PAUSED") if is_paused else (f"🔴{due}" if due else "✅")
        theme = getattr(self, "_theme", "classic")
        bookmarked = deck.get("bookmarked", False)
        bookmark_str = " 🔖" if bookmarked else ""
        pause_str = " ⏸️" if is_paused else ""
        text = (
            f"  📂{pause_str}  {deck['name']}{bookmark_str}  [{badge}]"
            if theme == "classic"
            else ""
        )
        item = QTreeWidgetItem([text])
        item.setToolTip(0, f"{deck.get('name', '')} (⏸️ PAUSED - {due} Due Backlog)" if is_paused else deck.get("name", ""))
        item.setData(0, Qt.UserRole, deck.get("_id"))
        item.setData(0, Qt.UserRole + 1, str(due))
        item.setData(0, Qt.UserRole + 2, deck["name"])
        item.setData(0, Qt.UserRole + 4, depth)
        item.setData(0, Qt.UserRole + 5, bookmarked)
        item.setData(0, Qt.UserRole + 6, is_paused)
        # Apply depth-based text color for classic theme
        if theme == "classic":
            if is_paused:
                item.setForeground(0, QBrush(QColor("#FFB86C")))
            else:
                item.setForeground(0, QBrush(QColor(depth_color(depth, "classic"))))
        for child in deck.get("children", []):
            item.addChild(self._make_item(child, depth + 1, parent_is_paused=is_paused))
        return item

    def _get_id_from_item(self, item):
        return item.data(0, Qt.UserRole) if item else None

    def _get_deck_from_item(self, item):
        did = self._get_id_from_item(item)
        return (
            find_deck_by_id(did, self._data.get("decks", []))
            if did is not None
            else None
        )

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

    @trace_perf
    def _on_click(self, item, _col):
        deck = self._get_deck_from_item(item)
        if deck:
            self.deck_selected.emit(deck)

    def _ctx_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            did = self._get_id_from_item(item)
            deck = self._get_deck_from_item(item)
            menu.addAction("▶ Open", lambda: self._on_double_click(item, 0))
            menu.addAction("⚙️ Deck Settings / डेक सेटिंग्स...", lambda: self._open_deck_settings(did))
            menu.addAction("🎯 Practice Mode (All Cards)", lambda: self._practice_deck_by_id(did))
            menu.addAction("✨ Review only the new card, not the due one", lambda: self._review_new_cards_by_id(did))
            menu.addAction("🌱 Review: Least Mature First", lambda checked=False, d_id=did: self._review_least_mature_by_id(d_id))
            menu.addAction("🎯 Practice: Least Mature First", lambda checked=False, d_id=did: self._practice_least_mature_by_id(d_id))

            order_menu = menu.addMenu("🔀 Review Order / प्राथमिकता क्रम")
            current_order = (deck.get("review_order") or "default") if deck else "default"
            act_due = order_menu.addAction("📅 Due Date (Standard / नियत तारीख)")
            act_due.setCheckable(True)
            act_due.setChecked(current_order == "default")
            act_due.triggered.connect(lambda checked=False, d_id=did: self._set_deck_order_mode(d_id, "default"))
            act_mature = order_menu.addAction("🌱 Least Mature First (इमैच्योर कार्ड्स पहले)")
            act_mature.setCheckable(True)
            act_mature.setChecked(current_order == "least_mature")
            act_mature.triggered.connect(lambda checked=False, d_id=did: self._set_deck_order_mode(d_id, "least_mature"))

            menu.addAction("＋ Sub-deck", lambda: self._new_deck(did))
            source_p = (deck.get("source_folder_path") if deck and deck.get("source_folder_path") and os.path.isdir(deck.get("source_folder_path")) else None) or (deck.get("source_file_path") or deck.get("source_folder_path") if deck else None)
            if source_p and os.path.exists(source_p):
                src_name = os.path.basename(source_p)
                action_text = f"🔄 Sync Folder ('{src_name}')" if os.path.isdir(source_p) else f"🔄 Sync Deck ('{src_name}')"
                menu.addAction(action_text, lambda: self._sync_deck_from_source(did))
                menu.addAction("📄 Change Linked File (JSON / CSV)...", lambda: self._link_source_file(did))
                menu.addAction("📁 Change Linked Folder...", lambda: self._link_source_folder(did))
                menu.addAction("❌ Unlink Source (Clear Link)", lambda: self._unlink_source(did))
            else:
                menu.addAction("📄 Link to Source File (JSON / CSV)...", lambda: self._link_source_file(did))
                menu.addAction("📁 Link to Source Folder...", lambda: self._link_source_folder(did))
            menu.addAction("✏ Rename", lambda: self._rename_by_id(did))
            if deck:
                from data_manager import is_deck_effective_paused
                is_paused = is_deck_effective_paused(deck, self._data.get("decks", []))
                pause_text = "▶️ Unpause Deck (Resume Schedule)" if is_paused else "⏸️ Pause Deck (Freeze Incoming Cards)"
                menu.addAction(pause_text, lambda: self._toggle_pause_deck_by_id(did))
                bookmarked = deck.get("bookmarked", False)
                action_text = "🔖 Remove Bookmark" if bookmarked else "🔖 Bookmark (Unmasked)"
                menu.addAction(action_text, lambda: self._toggle_bookmark_by_id(did))
            menu.addSeparator()
            menu.addAction("🗑 Delete", lambda: self._delete_by_id(did))
        else:
            menu.addAction("＋ New Top-level Deck", lambda: self._new_deck(None))
            menu.addAction("📥 Import Text / CSV Deck...", lambda: self._import_cards(None))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _open_deck_settings(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        dlg = DeckSettingsDialog(self, deck=deck, data=self._data)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()
            home = self._find_home()
            if home:
                if hasattr(home, "_clear_home_ram_caches"):
                    home._clear_home_ram_caches()
                active_dv = None
                if hasattr(home, "_tmnt_layout") and home._tmnt_layout and hasattr(home._tmnt_layout, "main"):
                    active_dv = home._tmnt_layout.main
                elif hasattr(home, "deck_view") and home.deck_view:
                    active_dv = home.deck_view
                if active_dv and getattr(active_dv, "_deck_id", None) == deck_id:
                    active_dv.deck = deck
                    active_dv._refresh()

    def _practice_deck_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self._select_by_id(deck_id)
        self.deck_selected.emit(deck)
        home = self._find_home()
        if home:
            active_dv = None
            if hasattr(home, "_tmnt_layout") and home._tmnt_layout and hasattr(home._tmnt_layout, "main"):
                active_dv = home._tmnt_layout.main
            elif hasattr(home, "deck_view") and home.deck_view:
                active_dv = home.deck_view
            if active_dv:
                active_dv.deck = deck
                active_dv._deck_id = deck_id
                active_dv._practice_deck()

    def _review_new_cards_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self._select_by_id(deck_id)
        self.deck_selected.emit(deck)
        home = self._find_home()
        if home:
            active_dv = None
            if hasattr(home, "_tmnt_layout") and home._tmnt_layout and hasattr(home._tmnt_layout, "main"):
                active_dv = home._tmnt_layout.main
            elif hasattr(home, "deck_view") and home.deck_view:
                active_dv = home.deck_view
            if active_dv:
                active_dv.deck = deck
                active_dv._deck_id = deck_id
                if hasattr(active_dv, "_review_new_cards"):
                    active_dv._review_new_cards()
                elif hasattr(active_dv, "_practice_new_cards"):
                    active_dv._practice_new_cards()

    _practice_new_cards_by_id = _review_new_cards_by_id

    def _review_least_mature_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self._select_by_id(deck_id)
        self.deck_selected.emit(deck)
        home = self._find_home()
        if home:
            active_dv = None
            if hasattr(home, "_tmnt_layout") and home._tmnt_layout and hasattr(home._tmnt_layout, "main"):
                active_dv = home._tmnt_layout.main
            elif hasattr(home, "deck_view") and home.deck_view:
                active_dv = home.deck_view
            if active_dv:
                active_dv.deck = deck
                active_dv._deck_id = deck_id
                if hasattr(active_dv, "_review_due_least_mature"):
                    active_dv._review_due_least_mature()
                else:
                    active_dv._start_review(order_mode="least_mature")

    def _practice_least_mature_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        self._select_by_id(deck_id)
        self.deck_selected.emit(deck)
        home = self._find_home()
        if home:
            active_dv = None
            if hasattr(home, "_tmnt_layout") and home._tmnt_layout and hasattr(home._tmnt_layout, "main"):
                active_dv = home._tmnt_layout.main
            elif hasattr(home, "deck_view") and home.deck_view:
                active_dv = home.deck_view
            if active_dv:
                active_dv.deck = deck
                active_dv._deck_id = deck_id
                if hasattr(active_dv, "_practice_deck_least_mature"):
                    active_dv._practice_deck_least_mature()
                else:
                    active_dv._practice_deck(order_mode="least_mature")

    def _set_deck_order_mode(self, deck_id, mode):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        deck_history.push(self._data)
        deck["review_order"] = mode
        store.mark_dirty()
        store.save_soon(min_interval=3.0)
        home = self._find_home()
        if home:
            active_dv = getattr(home, "deck_view", None)
            if active_dv is None and hasattr(home, "_tmnt_layout") and hasattr(home._tmnt_layout, "main"):
                active_dv = home._tmnt_layout.main
            if active_dv and getattr(active_dv, "_deck_id", None) == deck_id:
                active_dv.deck = deck
                if hasattr(active_dv, "_update_order_mode_ui"):
                    active_dv._update_order_mode_ui()

    def _import_cards(self, deck_id=None):
        deck = find_deck_by_id(deck_id, self._data.get("decks", [])) if deck_id is not None else None
        from ui.import_cards_dialog import ImportCardsDialog
        dlg = ImportCardsDialog(self, data=self._data, current_deck=deck)
        res = dlg.exec_()
        if res == QDialog.Accepted:
            result = dlg.get_result()
            home = self._find_home()
            if home and hasattr(home, "_clear_home_ram_caches"):
                home._clear_home_ram_caches()
            if home:
                home.refresh()
                target_id = result.get("target_deck_id")
                if target_id is not None:
                    self._select_by_id(target_id)
            else:
                self.refresh()
        dlg.deleteLater()

    def _link_source_file(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            f"Select Flashcard File to Link with '{deck.get('name')}'",
            "",
            "Flashcard Files (*.json *.csv *.tsv);;JSON (*.json);;CSV (*.csv);;TSV (*.tsv);;All Files (*.*)"
        )
        if not fpath:
            return
        norm_p = os.path.normpath(fpath).replace("\\", "/")
        deck["source_file_path"] = norm_p
        deck["source_folder_path"] = norm_p
        store.mark_dirty()
        store.save_force(async_save=True)
        reply = QMessageBox.question(
            self,
            "File Linked",
            f"Successfully linked '{deck.get('name')}' to:\n{norm_p}\n\nDo you want to sync this deck now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._sync_deck_from_source(deck_id)

    def _link_source_folder(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        folder = QFileDialog.getExistingDirectory(
            self,
            f"Select Source Folder to Link with '{deck.get('name')}'",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if not folder:
            return
        norm_p = os.path.normpath(folder).replace("\\", "/")
        deck["source_folder_path"] = norm_p
        deck["source_file_path"] = norm_p
        store.mark_dirty()
        store.save_force(async_save=True)
        reply = QMessageBox.question(
            self,
            "Folder Linked",
            f"Successfully linked '{deck.get('name')}' to folder:\n{norm_p}\n\nDo you want to sync this deck now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._sync_deck_from_source(deck_id)

    def _unlink_source(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        from PyQt5.QtWidgets import QMessageBox
        old_path = deck.get("source_file_path") or deck.get("source_folder_path") or ""
        reply = QMessageBox.question(
            self,
            "Unlink Source",
            f"Are you sure you want to unlink the source from '{deck.get('name')}'?\n\nLinked path:\n{old_path}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            deck["source_file_path"] = ""
            deck["source_folder_path"] = ""
            store.mark_dirty()
            store.save_force(async_save=True)
            QMessageBox.information(
                self,
                "Source Unlinked",
                f"Deck '{deck.get('name')}' is no longer linked to any file or folder."
            )

    def _sync_deck_from_source(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return

        source_p = (deck.get("source_folder_path") if deck.get("source_folder_path") and os.path.isdir(deck.get("source_folder_path")) else None) or deck.get("source_file_path") or deck.get("source_folder_path")
        if not source_p or not os.path.exists(source_p):
            self._link_source_file(deck_id)
            return

        from data_manager import sync_deck_from_source_folder
        from PyQt5.QtWidgets import QMessageBox

        res = sync_deck_from_source_folder(self._data, deck=deck, custom_folder_path=source_p)
        if res.get("status") == "error":
            QMessageBox.warning(self, "Sync Failed", res.get("message", "Unknown error during sync."))
            return

        new_c = res.get("new_count", 0)
        upd_c = res.get("updated_count", 0)
        unch_c = res.get("unchanged_count", 0)
        total_s = res.get("total_cards_scanned", 0)

        home = self._find_home()
        if home and hasattr(home, "_clear_home_ram_caches"):
            home._clear_home_ram_caches()
        if home:
            home.refresh()
        else:
            self.refresh()

        from perf_utils import invalidate_deck_stats
        invalidate_deck_stats()

        msg = (
            f"<b>✅ Sync Complete for '{deck.get('name')}'</b><br><br>"
            f"• <b>{new_c}</b> new card(s) added<br>"
            f"• <b>{upd_c}</b> card(s) updated (all SM-2 learning progress preserved)<br>"
            f"• <b>{unch_c}</b> card(s) unchanged<br>"
            f"• Total scanned: {total_s} card(s)<br><br>"
            f"<i>Source: {source_p}</i>"
        )
        box = QMessageBox(QMessageBox.Information, "Deck Synchronized", msg, parent=self)
        box.setTextFormat(Qt.RichText)
        box.exec_()

    def _find_home(self):
        w = self.parent()
        while w is not None:
            if type(w).__name__ == "HomeScreen" or hasattr(w, "show_review"):
                return w
            w = w.parent()
        app = QApplication.instance()
        if app:
            for top in app.topLevelWidgets():
                if hasattr(top, "centralWidget"):
                    cw = top.centralWidget()
                    if type(cw).__name__ == "HomeScreen" or hasattr(cw, "show_review"):
                        return cw
        return None

    def _toggle_bookmark_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        deck_history.push(self._data)  # undo snapshot
        deck["bookmarked"] = not deck.get("bookmarked", False)
        store.mark_dirty()
        store.save_soon(min_interval=3.0)
        home = self._find_home()
        if home:
            home.refresh()
        else:
            self.refresh()

    def _toggle_pause_deck_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        from datetime import date
        from data_manager import cascade_deck_pause, is_deck_effective_paused
        deck_history.push(self._data)  # undo snapshot
        currently_paused = is_deck_effective_paused(deck, self._data.get("decks", []))
        is_paused = not currently_paused
        deck["is_paused"] = is_paused
        today_iso = date.today().isoformat()
        if is_paused:
            deck["pause_backlog_cutoff"] = today_iso
            deck["pause_last_shift_date"] = today_iso
        else:
            deck.pop("pause_backlog_cutoff", None)
            deck.pop("pause_last_shift_date", None)

        cascade_deck_pause(deck, is_paused, today_iso)

        store.mark_dirty()
        store.save_soon(min_interval=3.0)
        from perf_utils import invalidate_deck_stats
        invalidate_deck_stats()
        home = self._find_home()
        if home:
            if hasattr(home, "_clear_home_ram_caches"):
                home._clear_home_ram_caches()
            home.refresh()
            active_dv = getattr(home, "deck_view", None)
            if active_dv is None and hasattr(home, "_tmnt_layout") and hasattr(home._tmnt_layout, "main"):
                active_dv = home._tmnt_layout.main
            if active_dv and getattr(active_dv, "_deck_id", None) == deck_id:
                active_dv.load_deck(deck, self._data)
        else:
            self.refresh()

    def _new_deck(self, parent_id):
        name, ok = QInputDialog.getText(self, "New Deck", "Deck name:")
        if not ok or not name.strip():
            return
        # ── Duplicate name check ──────────────────────────────────────────────
        siblings = (
            self._data.get("decks", [])
            if parent_id is None
            else (find_deck_by_id(parent_id, self._data.get("decks", [])) or {}).get(
                "children", []
            )
        )
        dup = next(
            (d for d in siblings if d["name"].strip().lower() == name.strip().lower()),
            None,
        )
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
            "_id": next_deck_id(self._data),
            "name": name.strip(),
            "cards": [],
            "children": [],
            "created": datetime.now().isoformat(),
        }
        print(f"[DeckTree][new_deck] ➕ creating '{name.strip()}' parent={parent_id}")
        deck_history.push(self._data)  # ← undo snapshot
        if parent_id is None:
            self._data.setdefault("decks", []).append(new_deck)
        else:
            parent = find_deck_by_id(parent_id, self._data.get("decks", []))
            if parent is None:
                QMessageBox.warning(self, "Error", "Parent deck not found!")
                return
            parent.setdefault("children", []).append(new_deck)
        store.mark_dirty()
        from perf_utils import invalidate_deck_stats

        invalidate_deck_stats()
        store.save_soon(min_interval=3.0)
        self.refresh()
        self._select_by_id(new_deck["_id"])

    def _new_subdeck(self):
        did = self._get_selected_id()
        if did is None:
            QMessageBox.information(
                self, "Select first", "Click a parent deck first, then press ＋ Sub."
            )
            return
        self._new_deck(did)

    def _rename_by_id(self, deck_id):
        deck = find_deck_by_id(deck_id, self._data.get("decks", []))
        if not deck:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Deck", "New name:", text=deck.get("name", "")
        )
        if ok and name.strip():
            # ── Duplicate name check ──────────────────────────────────────────
            parent = self._find_parent(deck_id, self._data.get("decks", []))
            siblings = (
                parent.get("children", []) if parent else self._data.get("decks", [])
            )
            dup = next(
                (
                    d
                    for d in siblings
                    if d["name"].strip().lower() == name.strip().lower()
                    and d.get("_id") != deck_id
                ),
                None,
            )
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
            deck_history.push(self._data)  # ← undo snapshot
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
        b_show = QPushButton("📍 Show Existing")
        b_retry = QPushButton("✏ Try Again")
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
        if (
            QMessageBox.question(
                self,
                "Delete",
                f"Delete '{deck['name']}' and ALL its cards / sub-decks?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            != QMessageBox.Yes
        ):
            return
        print(f"[DeckTree][delete] 🗑 deleting '{deck['name']}' id={deck_id}")
        deck_history.push(self._data)  # ← undo snapshot
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
        if getattr(self, "_structure_locked", False):
            event.ignore()
            return
        if event.mimeData().hasFormat(CARD_DRAG_MIME) or event.mimeData().hasFormat(
            "application/x-qabstractitemmodeldatalist"
        ):
            event.accept()
        else:
            event.ignore()

    def _on_drag_move(self, event):
        if getattr(self, "_structure_locked", False):
            event.ignore()
            return
        if event.mimeData().hasFormat(CARD_DRAG_MIME) or event.mimeData().hasFormat(
            "application/x-qabstractitemmodeldatalist"
        ):
            self._last_drop_pos = self.tree.dropIndicatorPosition()
            self._last_drop_item = self.tree.itemAt(event.pos())
            ctrl = bool(event.keyboardModifiers() & Qt.ControlModifier)
            self._last_drop_ctrl = ctrl
            item = self._last_drop_item

            # ── Draw custom drop line ─────────────────────────────────────────
            if item and not ctrl:
                rect = self.tree.visualItemRect(item)
                pos = self._last_drop_pos
                line_y = (
                    rect.top() if pos == QAbstractItemView.AboveItem else rect.bottom()
                )
                self.tree.set_drop_line(line_y, rect.left())
            else:
                self.tree.clear_drop_line()

            # ── Hint label ────────────────────────────────────────────────────
            if item:
                name = item.data(0, Qt.UserRole)
                deck = find_deck_by_id(name, self._data.get("decks", []))
                dname = deck["name"] if deck else "?"
                if ctrl:
                    self._drop_hint.setText(f"📂 Drop INTO '{dname}' as child")
                    self._drop_hint.setStyleSheet(
                        "background:#1D9E75;color:white;font-size:11px;"
                        "padding:4px 8px;border-radius:4px;"
                    )
                else:
                    self._drop_hint.setText("↕ Reorder — hold Ctrl to nest inside")
                    self._drop_hint.setStyleSheet(
                        "background:#534AB7;color:white;font-size:11px;"
                        "padding:4px 8px;border-radius:4px;"
                    )
            self._drop_hint.setVisible(True)
            event.accept()
        else:
            event.ignore()

    def _on_drag_leave(self, event=None):
        self._drop_hint.setVisible(False)
        self.tree.clear_drop_line()

    def _on_tree_drop(self, event):
        if getattr(self, "_structure_locked", False):
            event.ignore()
            return
        # ── Card dropped from DeckView onto a deck ────────────────────────────
        if event.mimeData().hasFormat(CARD_DRAG_MIME):
            target_item = self.tree.itemAt(event.pos())
            if target_item is None:
                event.ignore()
                return
            target_id = self._get_id_from_item(target_item)
            target_deck = find_deck_by_id(target_id, self._data["decks"])
            if target_deck is None:
                event.ignore()
                return

            raw = bytes(event.mimeData().data(CARD_DRAG_MIME)).decode()
            src_id_str, row_str = raw.split("|")
            src_deck = find_deck_by_id(int(src_id_str), self._data["decks"])
            if src_deck is None or src_deck is target_deck:
                event.ignore()
                return

            cards = src_deck.get("cards", [])
            row = int(row_str)
            if not (0 <= row < len(cards)):
                event.ignore()
                return

            print(
                f"[DeckTree][drop] 🃏 card row={row} moved to '{target_deck.get('name')}'"
            )
            deck_history.push(self._data)  # ← undo snapshot
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
        target_item = getattr(self, "_last_drop_item", self.tree.itemAt(event.pos()))
        drop_pos = getattr(self, "_last_drop_pos", self.tree.dropIndicatorPosition())
        ctrl = getattr(self, "_last_drop_ctrl", False)
        dragged_id = self._get_selected_id()
        if dragged_id is None:
            event.ignore()
            return
        print(f"[DeckTree][drop] 🗂 reordering id={dragged_id}, ctrl={ctrl}")
        deck_history.push(self._data)  # ← undo snapshot
        deck = self._detach_deck(dragged_id, self._data["decks"])
        if deck is None:
            event.ignore()
            return

        if target_item is None:
            self._data["decks"].append(deck)
        else:
            tid = self._get_id_from_item(target_item)
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
                    idx = next(
                        (i for i, d in enumerate(plist) if d["_id"] == tid), None
                    )
                    if idx is None:
                        self._data["decks"].append(deck)
                    else:
                        insert_at = (
                            idx if drop_pos == QAbstractItemView.AboveItem else idx + 1
                        )
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
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.1f} KB"
    if n < 1024**3:
        return f"{n/1024**2:.1f} MB"
    return f"{n/1024**3:.2f} GB"


class ClassicCacheWidget(QFrame):
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
        self._auto_timer.setInterval(CACHE_AUTO_REFRESH_MS)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_refresh_enabled = False
        self._build_ui()
        self.refresh()

    def set_auto_refresh_enabled(self, enabled: bool):
        self._auto_refresh_enabled = bool(enabled)
        if self._auto_refresh_enabled and self.isVisible():
            if not self._auto_timer.isActive():
                self._auto_timer.start()
        else:
            self._auto_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_refresh_enabled:
            self._auto_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._auto_timer.stop()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(38)
        hdr.setStyleSheet(
            f"QFrame{{background:{C_CARD};"
            f"border-bottom:1px solid {C_BORDER};border-radius:0px;}}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 10, 0)
        title = QLabel("💾 Cache")
        title.setStyleSheet(f"color:{C_TEXT};font-size:11px;font-weight:bold;")
        self._lbl_total = QLabel("")
        self._lbl_total.setStyleSheet(f"color:{C_GREEN};font-size:10px;")
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
            f"QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:2px;}}"
        )

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
            f"border-radius:0px;padding:8px;font-size:11px;"
        )
        btn_all.clicked.connect(self._clear_all)
        root.addWidget(btn_all)

    def refresh(self):
        from cache_manager import PAGE_CACHE, COMBINED_CACHE

        # Collect all known PDFs
        known = set()
        known.update(COMBINED_CACHE.all_cached_pdfs())
        known.update(PAGE_CACHE.all_cached_pdfs())

        # Clear old entries (keep trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_bytes = 0
        for pdf_path in sorted(known):
            disk_b = COMBINED_CACHE.disk_bytes_for_pdf(pdf_path)
            ram_b = PAGE_CACHE.ram_bytes_for_pdf(pdf_path)
            total = disk_b + ram_b
            total_bytes += total
            card = self._make_card(pdf_path, disk_b, ram_b, total)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

        if not known:
            empty = QLabel("No cached PDFs yet.")
            empty.setStyleSheet(f"color:{C_SUBTEXT};font-size:10px;")
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)

        count = len(known)
        self._lbl_total.setText(
            f"{_fmt_bytes(total_bytes)}  {count} PDF{'s' if count!=1 else ''}"
        )

    def _make_card(self, pdf_path, disk_b, ram_b, total_b):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{C_CARD};"
            f"border:1px solid {C_BORDER};border-radius:6px;}}"
            f"QLabel{{background:transparent;}}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(3)

        # File name
        name = os.path.basename(pdf_path)
        if len(name) > 22:
            name = name[:19] + "..."
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color:{C_TEXT};font-size:10px;font-weight:bold;")
        name_lbl.setToolTip(pdf_path)
        vl.addWidget(name_lbl)

        def _row(icon, val):
            w = QWidget()
            w.setStyleSheet("background:transparent;")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            il = QLabel(icon)
            il.setFixedWidth(16)
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

        # Total + remove button
        hl_bot = QHBoxLayout()
        tl = QLabel(_fmt_bytes(total_b))
        tl.setStyleSheet(f"color:{C_SUBTEXT};font-size:10px;font-weight:bold;")
        btn = QPushButton("🗑")
        btn.setFixedSize(24, 24)
        btn.setToolTip("Remove this PDF cache")
        btn.setStyleSheet(
            f"background:{C_RED};color:white;border:none;"
            f"border-radius:4px;font-size:11px;padding:0px;"
        )
        btn.clicked.connect(lambda _, p=pdf_path: self._remove_pdf(p))
        hl_bot.addWidget(tl)
        hl_bot.addStretch()
        hl_bot.addWidget(btn)
        vl.addLayout(hl_bot)
        return card

    def _remove_pdf(self, pdf_path):
        from cache_manager import (
            PAGE_CACHE,
            COMBINED_CACHE,
            PIXMAP_REGISTRY,
        )

        COMBINED_CACHE.invalidate(pdf_path)
        PAGE_CACHE.invalidate_pdf(pdf_path)
        for label in [
            l for l, (_, _, p) in PIXMAP_REGISTRY._entries.items() if p == pdf_path
        ]:
            PIXMAP_REGISTRY.unregister(label)
        self.refresh()

    def _clear_all(self):
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


class DojoCacheWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cacheFrame")
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame#cacheFrame {{
                background: #0F0F17;
                border-left: 1px solid #1E1E2E;
                border-radius: 0px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(CACHE_AUTO_REFRESH_MS)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_refresh_enabled = False
        self._build_ui()
        self.refresh()

    def set_auto_refresh_enabled(self, enabled: bool):
        self._auto_refresh_enabled = bool(enabled)
        if self._auto_refresh_enabled and self.isVisible():
            if not self._auto_timer.isActive():
                self._auto_timer.start()
        else:
            self._auto_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_refresh_enabled:
            self._auto_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._auto_timer.stop()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 24, 16, 24)
        root.setSpacing(24)

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(8)
        icon_lbl = QLabel("🧪")
        icon_lbl.setStyleSheet("font-size: 16px;")

        title = QLabel("BANGA LAB")
        title.setStyleSheet(
            "color: #72FF4F; font-size: 13px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: 1px;"
        )
        hdr.addWidget(icon_lbl)
        hdr.addWidget(title)
        hdr.addStretch()
        root.addLayout(hdr)

        # System Status
        status_v = QVBoxLayout()
        status_v.setSpacing(8)
        status_hdr = QLabel("— SYSTEM STATUS —")
        status_hdr.setStyleSheet(
            "color: #5F627D; font-size: 11px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: 2px;"
        )
        status_v.addWidget(status_hdr)

        def _stat_row(label, val, val_color):
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                "color: #5F627D; font-size: 11px; font-family: 'Orbitron'; font-weight: bold;"
            )
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet(
                f"color: {val_color}; font-size: 11px; font-weight: bold;"
            )
            l.addWidget(lbl)
            l.addStretch()
            l.addWidget(v_lbl)
            return w

        status_v.addWidget(_stat_row("ALGORITHM", "SM-2", "#A86CFF"))
        status_v.addWidget(_stat_row("SCHEDULER", "● ACTIVE", "#72FF4F"))
        status_v.addWidget(_stat_row("PDF ENGINE", "PyMuPDF", "#A86CFF"))
        status_v.addWidget(_stat_row("OCCLUSION", "● ACTIVE", "#72FF4F"))
        root.addLayout(status_v)

        # Dojo Resources
        res_v = QVBoxLayout()
        res_v.setSpacing(12)
        res_hdr = QLabel("— DOJO RESOURCES —")
        res_hdr.setStyleSheet(
            "color: #5F627D; font-size: 11px; font-weight: 900; font-family: 'Orbitron'; letter-spacing: 2px;"
        )
        res_v.addWidget(res_hdr)

        def _prog_row(name, color):
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(4)
            hl = QHBoxLayout()
            hl.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(name)
            lbl.setStyleSheet(
                "color: #5F627D; font-size: 11px; font-family: 'Orbitron'; font-weight: bold;"
            )
            val_lbl = QLabel("0 MB")
            val_lbl.setStyleSheet(
                "color: #CDD6F4; font-size: 11px; font-family: monospace; font-weight: bold;"
            )
            hl.addWidget(lbl)
            hl.addStretch()
            hl.addWidget(val_lbl)
            vl.addLayout(hl)

            bg_bar = QFrame()
            bg_bar.setFixedHeight(6)
            bg_bar.setStyleSheet("background: #1E1E2E; border-radius: 3px;")
            bg_l = QHBoxLayout(bg_bar)
            bg_l.setContentsMargins(0, 0, 0, 0)
            bg_l.setAlignment(Qt.AlignLeft)

            fill_bar = QFrame()
            fill_bar.setFixedHeight(6)
            fill_bar.setStyleSheet(f"background: {color}; border-radius: 3px;")
            fill_bar.setFixedWidth(0)
            bg_l.addWidget(fill_bar)

            vl.addWidget(bg_bar)
            return w, val_lbl, fill_bar, bg_bar

        self.w_mem, self.lbl_mem, self.bar_mem, self.bg_mem = _prog_row(
            "MEMORY", "#A86CFF"
        )
        self.w_cache, self.lbl_cache, self.bar_cache, self.bg_cache = _prog_row(
            "CACHE", "#72FF4F"
        )
        self.w_media, self.lbl_media, self.bar_media, self.bg_media = _prog_row(
            "MEDIA", "#FF5555"
        )
        self.w_tot, self.lbl_tot, self.bar_tot, self.bg_tot = _prog_row(
            "TOTAL", "#A86CFF"
        )

        res_v.addWidget(self.w_mem)
        res_v.addWidget(self.w_cache)
        res_v.addWidget(self.w_media)
        res_v.addWidget(self.w_tot)
        root.addLayout(res_v)

        root.addStretch()

        # Fuel Up
        fuel_box = QFrame()
        fuel_box.setStyleSheet("""
            QFrame {
                background: transparent;
                border: 1px solid #72FF4F;
                border-radius: 8px;
            }
        """)
        fl = QHBoxLayout(fuel_box)
        fl.setContentsMargins(12, 12, 12, 12)
        fl.setSpacing(12)

        pizza = QLabel("🍕")
        pizza.setStyleSheet("font-size: 24px; border: none;")
        fl.addWidget(pizza)

        ftl = QVBoxLayout()
        ftl.setSpacing(4)
        ft = QLabel("FUEL UP, NINJA!")
        ft.setStyleSheet(
            "color: #72FF4F; font-size: 11px; font-weight: 900; font-family: 'Orbitron'; border: none;"
        )
        fd = QLabel("Take breaks.\nYour brain is\nnot a robot.")
        fd.setStyleSheet(
            "color: #5F627D; font-size: 10px; border: none; font-family: monospace;"
        )
        ftl.addWidget(ft)
        ftl.addWidget(fd)
        fl.addLayout(ftl)

        root.addWidget(fuel_box)

    def refresh(self):
        from cache_manager import PAGE_CACHE, COMBINED_CACHE

        known = set()
        known.update(COMBINED_CACHE.all_cached_pdfs())
        known.update(PAGE_CACHE.all_cached_pdfs())

        ram_b = 0
        disk_b = 0
        mask_b = 0
        for pdf_path in known:
            disk_b += COMBINED_CACHE.disk_bytes_for_pdf(pdf_path)
            ram_b += PAGE_CACHE.ram_bytes_for_pdf(pdf_path)

        tot_b = ram_b + disk_b + mask_b

        ram_mb = ram_b / (1024**2)
        disk_mb = disk_b / (1024**2)
        mask_mb = mask_b / (1024**2)
        tot_mb = tot_b / (1024**2)

        self.lbl_mem.setText(f"{ram_mb:.1f} MB")
        self.lbl_cache.setText(f"{disk_mb:.1f} MB")
        self.lbl_media.setText(f"{mask_mb:.1f} MB")
        self.lbl_tot.setText(f"{tot_mb:.1f} MB")

        MAX_MB = 512.0

        def _w(mb, bg):
            max_w = bg.width() if bg.width() > 0 else 188
            return int(min(mb / MAX_MB, 1.0) * max_w)

        self.bar_mem.setFixedWidth(_w(ram_mb, self.bg_mem))
        self.bar_cache.setFixedWidth(_w(disk_mb, self.bg_cache))
        self.bar_media.setFixedWidth(_w(mask_mb, self.bg_media))
        self.bar_tot.setFixedWidth(_w(tot_mb, self.bg_tot))


from PyQt5.QtWidgets import QStackedWidget


class CacheWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        self.classic_widget = ClassicCacheWidget()
        self.dojo_widget = DojoCacheWidget()
        self._theme = "classic"

        self.stack.addWidget(self.classic_widget)
        self.stack.addWidget(self.dojo_widget)
        l.addWidget(self.stack)
        self._sync_auto_refresh()

    def _sync_auto_refresh(self):
        active = self.isVisible()
        classic_active = active and self._theme != "dojo"
        dojo_active = active and self._theme == "dojo"
        self.classic_widget.set_auto_refresh_enabled(classic_active)
        self.dojo_widget.set_auto_refresh_enabled(dojo_active)

    def set_theme(self, theme):
        theme = normalize_theme(theme)
        self._theme = theme
        if theme == "dojo":
            self.stack.setCurrentWidget(self.dojo_widget)
            self.dojo_widget.refresh()
        else:
            self.stack.setCurrentWidget(self.classic_widget)
            self.classic_widget.refresh()
        self._sync_auto_refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_auto_refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.classic_widget.set_auto_refresh_enabled(False)
        self.dojo_widget.set_auto_refresh_enabled(False)


# ═══════════════════════════════════════════════════════════════════════════════
