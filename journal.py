# ═══════════════════════════════════════════════════════════════════════════════
#  DAILY JOURNAL  —  Anki Occlusion  v2
#
#  Features:
#    - Scrollable ink canvas (expand as you write)
#    - Pen + Eraser + Keyboard Text tools
#    - Date picker popup (click date label → calendar)
#    - Proper ‹ › arrow navigation buttons
#    - Multiple ink colors + undo + clear
#    - Export current page as PNG
#    - Persistent storage: ~/anki_journal.json
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import tempfile
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QSplitter, QFrame,
    QFileDialog, QMessageBox, QSizePolicy, QCalendarWidget,
    QScrollArea
)
from PyQt5.QtCore import Qt, QPointF, QRect, QSize, QDate, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QFont, QPolygonF
)

# ── Storage ───────────────────────────────────────────────────────────────────
JOURNAL_FILE = os.path.join(os.path.expanduser("~"), "anki_journal.json")

# ── Theme ─────────────────────────────────────────────────────────────────────
C_BG      = "#1E1E2E"
C_SURFACE = "#2A2A3E"
C_CARD    = "#313145"
C_ACCENT  = "#7C6AF7"
C_GREEN   = "#50FA7B"
C_RED     = "#FF5555"
C_TEXT    = "#CDD6F4"
C_SUBTEXT = "#A6ADC8"
C_BORDER  = "#45475A"

INK_COLORS   = ["#CDD6F4", "#FF4444", "#FFD700", "#50FA7B", "#00FFFF", "#F7916A"]
INK_WIDTH    = 2.0
ERASER_WIDTH = 22.0
PAGE_WIDTH   = 900     # logical canvas width
PAGE_HEIGHT  = 1200    # initial height — grows as you scroll down

MODE_PEN    = "pen"
MODE_ERASER = "eraser"
MODE_TEXT   = "text"


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════════

def _load_journal() -> dict:
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_journal(data: dict):
    dir_ = os.path.dirname(JOURNAL_FILE) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, JOURNAL_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _strokes_to_json(strokes):
    result = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        color = stroke[0]
        pts   = stroke[1:]
        result.append({
            "color": color.name(),
            "pts":   [[p.x(), p.y()] for p in pts],
        })
    return result


def _strokes_from_json(data):
    result = []
    for s in data:
        color = QColor(s.get("color", "#CDD6F4"))
        pts   = [QPointF(p[0], p[1]) for p in s.get("pts", [])]
        if pts:
            result.append([color] + pts)
    return result


def _texts_to_json(texts):
    return [{"x": t["x"], "y": t["y"], "text": t["text"],
             "color": t["color"], "size": t.get("size", 14)} for t in texts]


def _texts_from_json(data):
    return [{"x": d["x"], "y": d["y"], "text": d["text"],
             "color": d.get("color", "#CDD6F4"), "size": d.get("size", 14)}
            for d in data]


# ═══════════════════════════════════════════════════════════════════════════════
#  DATE PICKER POPUP
# ═══════════════════════════════════════════════════════════════════════════════

class _DatePicker(QDialog):
    date_selected = pyqtSignal(str)

    def __init__(self, current_date_str, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(f"""
            QDialog {{ background:{C_SURFACE}; border:2px solid {C_BORDER};
                       border-radius:10px; }}
            QCalendarWidget QWidget {{ background:{C_SURFACE}; color:{C_TEXT}; }}
            QCalendarWidget QAbstractItemView:enabled {{
                background:{C_CARD}; color:{C_TEXT};
                selection-background-color:{C_ACCENT};
                selection-color:white;
            }}
            QCalendarWidget QToolButton {{
                background:{C_CARD}; color:{C_TEXT};
                border:none; border-radius:4px; padding:4px 10px;
                font-weight:bold; font-size:13px;
            }}
            QCalendarWidget QToolButton:hover {{ background:{C_ACCENT}; color:white; }}
            QCalendarWidget #qt_calendar_navigationbar {{
                background:{C_SURFACE}; padding:4px;
            }}
            QCalendarWidget QAbstractItemView:disabled {{ color:{C_SUBTEXT}; }}
        """)
        L = QVBoxLayout(self)
        L.setContentsMargins(8, 8, 8, 8)
        cal = QCalendarWidget()
        cal.setGridVisible(False)
        cal.setMaximumDate(QDate.currentDate())
        try:
            qd = QDate.fromString(current_date_str, "yyyy-MM-dd")
            if qd.isValid():
                cal.setSelectedDate(qd)
        except Exception:
            pass
        cal.clicked.connect(lambda qd: (self.date_selected.emit(qd.toString("yyyy-MM-dd")), self.accept()))
        L.addWidget(cal)


# ═══════════════════════════════════════════════════════════════════════════════
#  INK CANVAS  (scrollable)
# ═══════════════════════════════════════════════════════════════════════════════

class JournalCanvas(QWidget):
    """Freehand ink + eraser + keyboard-text canvas. Grows downward on scroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page_h       = PAGE_HEIGHT
        self.setFixedWidth(PAGE_WIDTH)
        self.setFixedHeight(self._page_h)
        self.setStyleSheet(f"background:{C_BG};")
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        self._strokes   = []
        self._texts     = []
        self._current   = []
        self._color_idx = 0
        self._drawing   = False
        self._show_lines = True
        self._mode      = MODE_PEN

        # Text state
        self._text_pos    = None
        self._text_buf    = ""
        self._text_size   = 14

        # Eraser cursor — tracked in mouseMoveEvent, not from global cursor()
        self._eraser_pos  = None
        self.setMouseTracking(True)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_content(self, strokes, texts):
        self._strokes = strokes
        self._texts   = texts
        self._current = []
        self._commit_text()
        # Expand canvas if saved content goes beyond current height
        all_y = [p.y() for s in strokes for p in s[1:]]
        all_y += [t["y"] for t in texts]
        if all_y:
            needed = int(max(all_y)) + 200
            if needed > self._page_h:
                self._page_h = needed
                self.setFixedHeight(self._page_h)
        self.update()

    def get_strokes(self):
        return list(self._strokes)

    def get_texts(self):
        return list(self._texts)

    def set_mode(self, mode):
        self._mode = mode
        self._commit_text()
        cursors = {
            MODE_PEN:    Qt.CrossCursor,
            MODE_ERASER: Qt.BlankCursor,
            MODE_TEXT:   Qt.IBeamCursor,
        }
        self.setCursor(cursors.get(mode, Qt.CrossCursor))
        self.update()

    def clear(self):
        self._strokes = []
        self._texts   = []
        self._current = []
        self._commit_text()
        self._page_h  = PAGE_HEIGHT
        self.setFixedHeight(self._page_h)
        self.update()

    def undo(self):
        if self._text_buf:
            self._text_buf = self._text_buf[:-1]
            self.update()
            return
        if self._texts:
            self._texts.pop()
            self.update()
            return
        if self._strokes:
            self._strokes.pop()
            self.update()

    def cycle_color(self):
        self._color_idx = (self._color_idx + 1) % len(INK_COLORS)
        return INK_COLORS[self._color_idx]

    def current_color(self):
        return QColor(INK_COLORS[self._color_idx])

    def toggle_lines(self):
        self._show_lines = not self._show_lines
        self.update()

    def export_pixmap(self):
        px = QPixmap(self.size())
        px.fill(QColor(C_BG))
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint(p)
        p.end()
        return px

    # ── Text commit ───────────────────────────────────────────────────────────

    def _commit_text(self):
        if self._text_buf.strip() and self._text_pos:
            self._texts.append({
                "x":     self._text_pos.x(),
                "y":     self._text_pos.y(),
                "text":  self._text_buf,
                "color": INK_COLORS[self._color_idx],
                "size":  self._text_size,
            })
        self._text_buf = ""
        self._text_pos = None

    # ── Auto-expand ───────────────────────────────────────────────────────────

    def _maybe_expand(self, y: float):
        """Expand page height if drawing near the bottom."""
        if y > self._page_h - 120:
            self._page_h += 400
            self.setFixedHeight(self._page_h)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint(p)

    def _paint(self, p):
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(C_BG))

        if self._show_lines:
            p.setPen(QPen(QColor("#2A2A4A"), 1))
            for y in range(40, h, 32):
                p.drawLine(0, y, w, y)
            p.setPen(QPen(QColor("#3A2A3A"), 1))
            p.drawLine(48, 0, 48, h)

        # Committed strokes
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            color = stroke[0]
            pts   = stroke[1:]
            p.setPen(QPen(color, INK_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(pts) == 1:
                p.drawPoint(pts[0])
            else:
                p.drawPolyline(QPolygonF(pts))

        # Current stroke
        if len(self._current) >= 2:
            color = self._current[0]
            pts   = self._current[1:]
            p.setPen(QPen(color, INK_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPolygonF(pts))

        # Text items
        for t in self._texts:
            font = QFont("Segoe UI", t.get("size", 14))
            p.setFont(font)
            p.setPen(QColor(t.get("color", "#CDD6F4")))
            p.drawText(QPointF(t["x"], t["y"]), t["text"])

        # Active text being typed
        if self._mode == MODE_TEXT and self._text_pos:
            font = QFont("Segoe UI", self._text_size)
            p.setFont(font)
            p.setPen(QColor(INK_COLORS[self._color_idx]))
            display = self._text_buf + "|"
            p.drawText(self._text_pos, display)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(display)
            iy = int(self._text_pos.y()) + 3
            ix = int(self._text_pos.x())
            p.setPen(QPen(QColor(C_ACCENT), 1))
            p.drawLine(ix, iy, ix + tw, iy)

        # Eraser cursor — use tracked position for accuracy
        if self._mode == MODE_ERASER and self._eraser_pos is not None:
            ep = self._eraser_pos
            p.setPen(QPen(QColor(C_SUBTEXT), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            r = int(ERASER_WIDTH)
            p.drawEllipse(int(ep.x()) - r//2, int(ep.y()) - r//2, r, r)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = QPointF(e.pos())

        if self._mode == MODE_TEXT:
            self._commit_text()
            self._text_pos = pos
            self._text_buf = ""
            self.setFocus()
            self.update()

        elif self._mode == MODE_ERASER:
            self._drawing = True
            self._erase_at(pos)

        else:  # pen
            self._drawing = True
            self._current = [self.current_color(), pos]
            self._maybe_expand(pos.y())
        e.accept()

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        if self._mode == MODE_ERASER:
            self._eraser_pos = pos   # always track for cursor display
            self.update()
            if self._drawing:
                self._erase_at(pos)

        elif self._mode == MODE_PEN and self._drawing and self._current:
            self._current.append(pos)
            self._maybe_expand(pos.y())
            pts = self._current[1:]
            if len(pts) >= 2:
                p0, p1 = pts[-2], pts[-1]
                pw = int(INK_WIDTH) + 4
                self.update(QRect(
                    int(min(p0.x(), p1.x())) - pw,
                    int(min(p0.y(), p1.y())) - pw,
                    int(abs(p1.x() - p0.x())) + pw*2,
                    int(abs(p1.y() - p0.y())) + pw*2,
                ))
            else:
                self.update()
        e.accept()

    def leaveEvent(self, e):
        self._eraser_pos = None
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._mode == MODE_PEN and self._drawing:
                if len(self._current) >= 2:
                    self._strokes.append(list(self._current))
                self._current = []
                self.update()
            self._drawing = False
        e.accept()

    # ── Keyboard (text mode) ──────────────────────────────────────────────────

    def keyPressEvent(self, e):
        if self._mode != MODE_TEXT or self._text_pos is None:
            super().keyPressEvent(e)
            return

        key = e.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            # Commit and move cursor down
            self._commit_text()
            new_y = (self._text_pos.y() if self._text_pos else 100) + self._text_size + 8
            self._text_pos = QPointF(self._text_pos.x() if self._text_pos else 60, new_y)
            self._text_buf = ""
            self._maybe_expand(new_y)
            self.update()
        elif key == Qt.Key_Escape:
            self._commit_text()
            self.update()
        elif key == Qt.Key_Backspace:
            self._text_buf = self._text_buf[:-1]
            self.update()
        else:
            txt = e.text()
            if txt and txt.isprintable():
                self._text_buf += txt
                self.update()
        e.accept()

    # ── Eraser ────────────────────────────────────────────────────────────────

    def _erase_at(self, pos):
        r2 = (ERASER_WIDTH / 2) ** 2
        kept = []
        changed = False
        for stroke in self._strokes:
            hit = any(
                (pt.x() - pos.x())**2 + (pt.y() - pos.y())**2 <= r2
                for pt in stroke[1:]
            )
            if hit:
                changed = True
            else:
                kept.append(stroke)
        if changed:
            self._strokes = kept
            self.update()


# ═══════════════════════════════════════════════════════════════════════════════
#  JOURNAL DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class JournalDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📓 Daily Journal")
        self.setMinimumSize(1060, 700)
        self.setStyleSheet(f"""
            QDialog  {{ background:{C_BG}; color:{C_TEXT}; }}
            QWidget  {{ background:{C_BG}; color:{C_TEXT};
                        font-family:'Segoe UI'; font-size:12px; }}
            QFrame   {{ background:{C_SURFACE}; border-radius:8px; }}
            QLabel   {{ background:transparent; color:{C_TEXT}; }}
            QPushButton {{
                background:{C_CARD}; color:{C_TEXT};
                border:1px solid {C_BORDER}; border-radius:6px;
                padding:5px 12px; font-size:12px;
            }}
            QPushButton:hover {{ background:{C_SURFACE}; color:white; }}
            QListWidget {{
                background:{C_SURFACE}; border:1px solid {C_BORDER};
                border-radius:8px; padding:4px;
            }}
            QListWidget::item {{ padding:6px 10px; border-radius:6px; }}
            QListWidget::item:selected {{ background:{C_ACCENT}; color:white; }}
            QListWidget::item:hover    {{ background:{C_CARD}; }}
            QScrollArea {{ border:none; background:{C_BG}; }}
            QScrollBar:vertical {{
                background:{C_SURFACE}; width:10px; border-radius:5px;
            }}
            QScrollBar::handle:vertical {{
                background:{C_BORDER}; border-radius:5px; min-height:30px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{C_ACCENT}; }}
            QScrollBar:horizontal {{
                background:{C_SURFACE}; height:10px; border-radius:5px;
            }}
            QScrollBar::handle:horizontal {{
                background:{C_BORDER}; border-radius:5px;
            }}
        """)

        self._journal      = _load_journal()
        self._current_date = date.today().isoformat()
        self._mode         = MODE_PEN

        self._setup_ui()
        self._refresh_sidebar()
        self._load_date(self._current_date)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top = QFrame()
        top.setFixedHeight(54)
        top.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {C_BORDER};}}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 0, 12, 0)
        tl.setSpacing(6)

        lbl = QLabel("📓")
        lbl.setFont(QFont("Segoe UI", 16))
        lbl.setStyleSheet("background:transparent;")
        tl.addWidget(lbl)
        tl.addSpacing(4)

        # Arrow buttons — large, clear
        self._btn_prev = self._arrow_btn("‹", self._go_prev)
        self._btn_next = self._arrow_btn("›", self._go_next)

        # Clickable date label
        self._btn_date = QPushButton()
        self._btn_date.setFixedHeight(36)
        self._btn_date.setMinimumWidth(240)
        self._btn_date.setStyleSheet(
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 16px;font-size:13px;font-weight:bold;text-align:center;}}"
            f"QPushButton:hover{{background:{C_ACCENT};color:white;border:none;}}")
        self._btn_date.setToolTip("Click to pick a date")
        self._btn_date.clicked.connect(self._open_date_picker)

        self._lbl_focus = QLabel("")
        self._lbl_focus.setStyleSheet(f"color:{C_SUBTEXT};font-size:13px;font-weight:bold;padding-left:12px;padding-right:12px;")
        self._lbl_focus.hide()

        btn_today = QPushButton("Today")
        btn_today.setFixedHeight(36)
        btn_today.clicked.connect(self._go_today)

        tl.addWidget(self._btn_prev)
        tl.addWidget(self._btn_date)
        tl.addWidget(self._lbl_focus)
        tl.addWidget(self._btn_next)
        tl.addSpacing(4)
        tl.addWidget(btn_today)
        tl.addSpacing(10)
        tl.addWidget(self._vsep())

        # Tool mode buttons
        self._btn_pen    = self._mode_btn("✏  Pen",    MODE_PEN)
        self._btn_eraser = self._mode_btn("⬜ Eraser", MODE_ERASER)
        self._btn_text   = self._mode_btn("T  Text",   MODE_TEXT)
        tl.addWidget(self._btn_pen)
        tl.addWidget(self._btn_eraser)
        tl.addWidget(self._btn_text)
        tl.addSpacing(6)
        tl.addWidget(self._vsep())
        tl.addSpacing(4)

        # Color dot + button
        self._dot = QLabel()
        self._dot.setFixedSize(22, 22)
        self._dot.setStyleSheet(
            f"background:{INK_COLORS[0]};border-radius:11px;"
            f"border:2px solid {C_BORDER};")
        btn_color = QPushButton("Color")
        btn_color.setFixedHeight(36)
        btn_color.clicked.connect(self._cycle_color)
        tl.addWidget(self._dot)
        tl.addWidget(btn_color)

        btn_undo = QPushButton("↩ Undo");  btn_undo.setFixedHeight(36)
        btn_undo.clicked.connect(lambda: self._canvas.undo())

        btn_clear = QPushButton("🗑 Clear"); btn_clear.setFixedHeight(36)
        btn_clear.setStyleSheet(
            f"QPushButton{{background:{C_RED};color:white;border:none;"
            f"border-radius:6px;padding:5px 12px;}}"
            f"QPushButton:hover{{background:#CC2222;}}")
        btn_clear.clicked.connect(self._clear)

        btn_lines = QPushButton("📏 Lines"); btn_lines.setFixedHeight(36)
        btn_lines.clicked.connect(lambda: self._canvas.toggle_lines())

        btn_export = QPushButton("💾 PNG"); btn_export.setFixedHeight(36)
        btn_export.clicked.connect(self._export)

        tl.addWidget(btn_undo)
        tl.addWidget(btn_clear)
        tl.addWidget(btn_lines)
        tl.addWidget(btn_export)
        tl.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(36, 36)
        btn_close.clicked.connect(self._on_close)
        tl.addWidget(btn_close)

        root.addWidget(top)

        # Main area
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(188)
        sidebar.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-right:1px solid {C_BORDER};border-radius:0px;}}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 12, 8, 8)
        sl.setSpacing(6)
        hdr = QLabel("📅  Entries")
        hdr.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;font-weight:bold;"
            f"padding-bottom:4px;border-bottom:1px solid {C_BORDER};")
        sl.addWidget(hdr)
        self._sidebar = QListWidget()
        self._sidebar.itemClicked.connect(self._on_sidebar_click)
        sl.addWidget(self._sidebar, stretch=1)
        split.addWidget(sidebar)

        # Scroll area wrapping the canvas
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C_BG};}}")

        self._canvas = JournalCanvas()
        self._scroll.setWidget(self._canvas)
        split.addWidget(self._scroll)
        split.setSizes([188, 872])

        root.addWidget(split, stretch=1)

        # Hint bar
        self._hint_lbl = QLabel("")
        self._hint_lbl.setAlignment(Qt.AlignCenter)
        self._hint_lbl.setFixedHeight(22)
        self._hint_lbl.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;background:{C_SURFACE};"
            f"border-top:1px solid {C_BORDER};padding:2px;")
        root.addWidget(self._hint_lbl)

        self._update_mode_ui()

    def _arrow_btn(self, text, slot):
        b = QPushButton(text)
        b.setFixedSize(36, 36)
        b.setFont(QFont("Segoe UI", 20, QFont.Bold))
        b.setStyleSheet(
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"font-size:20px;font-weight:bold;padding:0;line-height:36px;}}"
            f"QPushButton:hover{{background:{C_ACCENT};color:white;border:none;}}")
        b.clicked.connect(slot)
        return b

    def _mode_btn(self, text, mode):
        b = QPushButton(text)
        b.setFixedHeight(36)
        b.clicked.connect(lambda _, m=mode: self._set_mode(m))
        return b

    def _vsep(self):
        s = QFrame()
        s.setFrameShape(QFrame.VLine)
        s.setFixedSize(1, 32)
        s.setStyleSheet(f"background:{C_BORDER};border:none;border-radius:0px;")
        return s

    # ── Mode ──────────────────────────────────────────────────────────────────

    def _set_mode(self, mode):
        self._mode = mode
        self._canvas.set_mode(mode)
        self._update_mode_ui()

    def _update_mode_ui(self):
        active_ss = (
            f"QPushButton{{background:{C_ACCENT};color:white;border:none;"
            f"border-radius:6px;padding:5px 12px;font-size:12px;}}"
            f"QPushButton:hover{{background:#6A58E0;}}")
        normal_ss = (
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:5px 12px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_SURFACE};color:white;}}")
        hints = {
            MODE_PEN:    "✏ Pen — draw freehand with mouse or stylus",
            MODE_ERASER: "⬜ Eraser — drag over strokes to erase them",
            MODE_TEXT:   "T Text — click canvas to place cursor, then type  •  Enter = new line  •  Esc = done",
        }
        for btn, mode in [(self._btn_pen, MODE_PEN),
                          (self._btn_eraser, MODE_ERASER),
                          (self._btn_text, MODE_TEXT)]:
            btn.setStyleSheet(active_ss if mode == self._mode else normal_ss)
        self._hint_lbl.setText(hints.get(self._mode, ""))

    # ── Date navigation ───────────────────────────────────────────────────────

    def _open_date_picker(self):
        self._save_current()
        popup = _DatePicker(self._current_date, self)
        popup.date_selected.connect(self._load_date)
        btn_pos = self._btn_date.mapToGlobal(self._btn_date.rect().bottomLeft())
        popup.move(btn_pos)
        popup.exec_()

    def _go_prev(self):
        self._save_current()
        d = date.fromisoformat(self._current_date) - timedelta(days=1)
        self._load_date(d.isoformat())

    def _go_next(self):
        self._save_current()
        d = date.fromisoformat(self._current_date) + timedelta(days=1)
        if d <= date.today():
            self._load_date(d.isoformat())

    def _go_today(self):
        self._save_current()
        self._load_date(date.today().isoformat())

    def _on_sidebar_click(self, item):
        ds = item.data(Qt.UserRole)
        if ds:
            self._save_current()
            self._load_date(ds)

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load_date(self, date_str):
        self._current_date = date_str
        try:
            d  = date.fromisoformat(date_str)
            dn = d.strftime("%A")
            df = d.strftime("%d %B %Y")
            tag = "  ✨" if d == date.today() else ""
            self._btn_date.setText(f"{dn},  {df}{tag}")
        except Exception:
            self._btn_date.setText(date_str)

        entry   = self._journal.get(date_str, {})
        # Backward compat — old format was a plain list of strokes
        if isinstance(entry, list):
            entry = {"strokes": entry, "texts": []}

        focus_secs = entry.get("focus_seconds", 0) if isinstance(entry, dict) else 0
        if focus_secs > 0:
            h, rem = divmod(focus_secs, 3600)
            m, s = divmod(rem, 60)
            if h:
                self._lbl_focus.setText(f"⏱ {h}h {m:02d}m")
            elif m:
                self._lbl_focus.setText(f"⏱ {m}m")
            else:
                self._lbl_focus.setText(f"⏱ {s}s")
            self._lbl_focus.show()
        else:
            self._lbl_focus.hide()

        strokes = _strokes_from_json(entry.get("strokes", []))
        texts   = _texts_from_json(entry.get("texts", []))
        self._canvas.set_content(strokes, texts)
        self._scroll.verticalScrollBar().setValue(0)

        for i in range(self._sidebar.count()):
            item = self._sidebar.item(i)
            if item.data(Qt.UserRole) == date_str:
                self._sidebar.setCurrentItem(item)
                break

    def _save_current(self):
        self._canvas._commit_text()
        strokes = self._canvas.get_strokes()
        texts   = self._canvas.get_texts()
        if strokes or texts:
            self._journal[self._current_date] = {
                "strokes": _strokes_to_json(strokes),
                "texts":   _texts_to_json(texts),
            }
        else:
            self._journal.pop(self._current_date, None)
        try:
            _save_journal(self._journal)
        except Exception as e:
            print(f"[Journal] Save error: {e}")
        self._refresh_sidebar()

    def _refresh_sidebar(self):
        sel = self._current_date
        self._sidebar.clear()
        dates     = sorted(self._journal.keys(), reverse=True)
        today_str = date.today().isoformat()
        if today_str not in dates:
            dates = [today_str] + dates
        for d_str in dates:
            try:
                d   = date.fromisoformat(d_str)
                has = d_str in self._journal
                if d == date.today():
                    label = "✨ Today — " + d.strftime("%d %b")
                elif d == date.today() - timedelta(days=1):
                    label = "Yesterday — " + d.strftime("%d %b")
                else:
                    label = d.strftime("%d %b %Y")
                icon = "📝" if has else "📄"
                item = QListWidgetItem(f"  {icon}  {label}")
                item.setData(Qt.UserRole, d_str)
                if not has:
                    item.setForeground(QColor(C_SUBTEXT))
                self._sidebar.addItem(item)
                if d_str == sel:
                    self._sidebar.setCurrentItem(item)
            except Exception:
                pass

    # ── Tools ─────────────────────────────────────────────────────────────────

    def _cycle_color(self):
        c = self._canvas.cycle_color()
        self._dot.setStyleSheet(
            f"background:{c};border-radius:11px;border:2px solid {C_BORDER};")

    def _clear(self):
        if QMessageBox.question(
            self, "Clear Page", "Clear everything on this page?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            self._canvas.clear()

    def _export(self):
        self._canvas._commit_text()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export as PNG",
            f"journal_{self._current_date}.png",
            "PNG Images (*.png)")
        if path:
            px = self._canvas.export_pixmap()
            if px.save(path, "PNG"):
                QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
            else:
                QMessageBox.warning(self, "Error", "Could not save PNG.")

    # ── Close ─────────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        """Global shortcuts — P=Pen, E=Eraser, T=Text, C=Color."""
        key = e.key()
        # Don't intercept if canvas is in text mode and has active text
        if self._canvas._mode == MODE_TEXT and self._canvas._text_pos is not None:
            super().keyPressEvent(e)
            return
        if key == Qt.Key_P:
            self._set_mode(MODE_PEN)
        elif key == Qt.Key_E:
            self._set_mode(MODE_ERASER)
        elif key == Qt.Key_T:
            self._set_mode(MODE_TEXT)
        elif key == Qt.Key_C:
            self._cycle_color()
        else:
            super().keyPressEvent(e)

    def _on_close(self):
        self._save_current()
        self.accept()

    def closeEvent(self, e):
        self._save_current()
        super().closeEvent(e)