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
    QPainter, QPen, QColor, QPixmap, QFont, QPolygonF, QIcon
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtCore import QByteArray

# ── Classic Theme ─────────────────────────────────────────────────────────────
C_BG      = "#1E1E2E"
C_SURFACE = "#2A2A3E"
C_CARD    = "#313145"
C_ACCENT  = "#7C6AF7"
C_GREEN   = "#50FA7B"
C_RED     = "#FF5555"
C_TEXT    = "#CDD6F4"
C_SUBTEXT = "#A6ADC8"
C_BORDER  = "#45475A"

# ── Ninja / Dojo Theme ────────────────────────────────────────────────────────
N_BG      = "#07070B"
N_SURFACE = "#0F0F17"
N_CARD    = "#14141F"
N_ACCENT  = "#72FF4F"      # neon green — primary highlight
N_PURPLE  = "#A86CFF"      # secondary — ninja purple
N_RED     = "#FF4444"
N_TEXT    = "#E0E0FF"
N_SUBTEXT = "#5F627D"
N_BORDER  = "#1A1A26"
N_CANVAS  = "#07070B"

# ── Theme resolver ────────────────────────────────────────────────────────────

def _is_ninja() -> bool:
    """Return True when the app is running in Ninja/Dojo mode."""
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        return getattr(app, "_active_theme", "classic") == "dojo"
    except Exception:
        return False


def _t(classic_val, ninja_val):
    """Pick classic or ninja value based on current theme."""
    return ninja_val if _is_ninja() else classic_val

INK_COLORS      = ["#CDD6F4", "#FF4444", "#FFD700", "#50FA7B", "#00FFFF", "#F7916A"]
NINJA_INK_COLORS = ["#72FF4F", "#A86CFF", "#E0E0FF", "#FF4444", "#F1FA8C", "#F7916A"]
INK_WIDTH    = 2.0
ERASER_WIDTH = 22.0
PAGE_WIDTH   = 900     # logical canvas width
PAGE_HEIGHT  = 1200    # initial height — grows as you scroll down

MODE_PEN    = "pen"
MODE_ERASER = "eraser"
MODE_TEXT   = "text"


from services.journal_manager import _load_journal, _save_journal, _strokes_to_json, _strokes_from_json, _texts_to_json, _texts_from_json

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
        bg = N_CANVAS if _is_ninja() else C_BG
        self.setStyleSheet(f"background:{bg};")
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

    def _colors(self):
        return NINJA_INK_COLORS if _is_ninja() else INK_COLORS

    def cycle_color(self):
        colors = self._colors()
        self._color_idx = (self._color_idx + 1) % len(colors)
        return colors[self._color_idx]

    def current_color(self):
        colors = self._colors()
        return QColor(colors[self._color_idx % len(colors)])

    def toggle_lines(self):
        self._show_lines = not self._show_lines
        self.update()

    def export_pixmap(self):
        px = QPixmap(self.size())
        px.fill(QColor(N_CANVAS if _is_ninja() else C_BG))
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint(p)
        p.end()
        return px

    # ── Text commit ───────────────────────────────────────────────────────────

    def _commit_text(self):
        if self._text_buf.strip() and self._text_pos:
            colors = self._colors()
            self._texts.append({
                "x":     self._text_pos.x(),
                "y":     self._text_pos.y(),
                "text":  self._text_buf,
                "color": colors[self._color_idx % len(colors)],
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
        ninja = _is_ninja()
        bg = N_CANVAS if ninja else C_BG
        p.fillRect(0, 0, w, h, QColor(bg))

        if self._show_lines:
            if ninja:
                # Ninja: subtle teal grid lines
                p.setPen(QPen(QColor("#0D1220"), 1))
                for y in range(40, h, 32):
                    p.drawLine(0, y, w, y)
                p.setPen(QPen(QColor("#0F1A10"), 1))
                p.drawLine(60, 0, 60, h)
            else:
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
            accent = N_ACCENT if ninja else C_ACCENT
            p.setPen(QPen(QColor(accent), 1))
            p.drawLine(ix, iy, ix + tw, iy)

        # Eraser cursor — use tracked position for accuracy
        if self._mode == MODE_ERASER and self._eraser_pos is not None:
            ep = self._eraser_pos
            cursor_col = N_ACCENT if ninja else C_SUBTEXT
            p.setPen(QPen(QColor(cursor_col), 1, Qt.DashLine))
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
#  SVG ICON SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

def _make_icon(svg_body: str, size: int = 14) -> "QIcon":
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 16 16" width="{size}" height="{size}">'
           f'{svg_body}</svg>')
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    p = QPainter(px)
    renderer.render(p)
    p.end()
    return QIcon(px)


_ICONS = {
    "kunai": (
        '<g fill="#72FF4F">'
        '<polygon points="8,0 9.2,6 8,5.2 6.8,6"/>'
        '<rect x="7.3" y="5" width="1.4" height="5"/>'
        '<ellipse cx="8" cy="10.5" rx="1.8" ry="1"/>'
        '<rect x="7.5" y="11.5" width="1" height="2.5"/>'
        '<line x1="6" y1="13" x2="10" y2="13" stroke="#72FF4F" stroke-width="0.8"/>'
        '</g>'
    ),
    "smoke": (
        '<g fill="none" stroke="#A86CFF" stroke-width="1.2" stroke-linecap="round">'
        '<path d="M5,14 Q4,10 6,8 Q4,6 6,4"/>'
        '<path d="M8,14 Q7,9 9,7 Q7,5 9,3"/>'
        '<path d="M11,14 Q10,10 12,8 Q10,6 12,4"/>'
        '</g>'
    ),
    "scroll": (
        '<g fill="#A86CFF">'
        '<rect x="3" y="4" width="10" height="8" rx="1"/>'
        '<rect x="2" y="3" width="2" height="10" rx="1"/>'
        '<rect x="12" y="3" width="2" height="10" rx="1"/>'
        '<line x1="5" y1="7" x2="11" y2="7" stroke="#07070B" stroke-width="1"/>'
        '<line x1="5" y1="9" x2="11" y2="9" stroke="#07070B" stroke-width="1"/>'
        '</g>'
    ),
    "shuriken": (
        '<g fill="#72FF4F">'
        '<polygon points="8,1 9,7 15,8 9,9 8,15 7,9 1,8 7,7"/>'
        '</g>'
    ),
    "rewind": (
        '<g fill="none" stroke="#A86CFF" stroke-width="1.4" stroke-linecap="round">'
        '<path d="M10,4 Q5,4 5,8 Q5,12 10,12"/>'
        '<polyline points="7,2 5,4 7,6"/>'
        '</g>'
    ),
    "skull": (
        '<g fill="#FF4444">'
        '<ellipse cx="8" cy="7" rx="4.5" ry="4"/>'
        '<rect x="5.5" y="10" width="5" height="2.5" rx="0.5"/>'
        '<rect x="5.5" y="12" width="1.5" height="1.5"/>'
        '<rect x="9" y="12" width="1.5" height="1.5"/>'
        '<circle cx="6.3" cy="6.5" r="1.2" fill="#07070B"/>'
        '<circle cx="9.7" cy="6.5" r="1.2" fill="#07070B"/>'
        '</g>'
    ),
    "grid": (
        '<g stroke="#A86CFF" stroke-width="1" fill="none">'
        '<rect x="2" y="2" width="12" height="12" rx="1"/>'
        '<line x1="2" y1="6.7" x2="14" y2="6.7"/>'
        '<line x1="2" y1="11.3" x2="14" y2="11.3"/>'
        '<line x1="6.7" y1="2" x2="6.7" y2="14"/>'
        '<line x1="11.3" y1="2" x2="11.3" y2="14"/>'
        '</g>'
    ),
    "export": (
        '<g fill="none" stroke="#72FF4F" stroke-width="1.3" stroke-linecap="round">'
        '<line x1="8" y1="2" x2="8" y2="11"/>'
        '<polyline points="5,8 8,11 11,8"/>'
        '<polyline points="3,13 3,14.5 13,14.5 13,13"/>'
        '</g>'
    ),
    "now": (
        '<g fill="none" stroke="#72FF4F" stroke-width="1.2">'
        '<circle cx="8" cy="8" r="5.5"/>'
        '<line x1="8" y1="4" x2="8" y2="8.5" stroke-linecap="round"/>'
        '<line x1="8" y1="8.5" x2="11" y2="10" stroke-linecap="round"/>'
        '</g>'
    ),
    "close": (
        '<g stroke="#5F627D" stroke-width="1.5" stroke-linecap="round">'
        '<line x1="4" y1="4" x2="12" y2="12"/>'
        '<line x1="12" y1="4" x2="4" y2="12"/>'
        '</g>'
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  JOURNAL DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class JournalDialog(QDialog):

    # ── Stylesheet builders ───────────────────────────────────────────────────

    @staticmethod
    def _classic_ss() -> str:
        return f"""
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
                background:{C_SURFACE}; width:8px; border-radius:4px;
            }}
            QScrollBar::handle:vertical {{
                background:{C_BORDER}; border-radius:4px; min-height:30px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{C_ACCENT}; }}
            QScrollBar:horizontal {{
                background:{C_SURFACE}; height:8px; border-radius:4px;
            }}
            QScrollBar::handle:horizontal {{
                background:{C_BORDER}; border-radius:4px;
            }}
        """

    @staticmethod
    def _ninja_ss() -> str:
        """Ninja/Dojo stylesheet — matches test.html visual language."""
        return f"""
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap');
            QDialog  {{ background:{N_BG}; color:{N_TEXT}; }}
            QWidget  {{ background:{N_BG}; color:{N_TEXT};
                        font-family:'Rajdhani', 'Segoe UI'; font-size:12px; }}
            QFrame   {{ background:{N_SURFACE}; border-radius:4px; }}
            QLabel   {{ background:transparent; color:{N_TEXT}; }}
            QPushButton {{
                background:{N_CARD}; color:{N_ACCENT};
                border:1px solid {N_ACCENT}; border-radius:2px;
                padding:4px 10px; font-size:11px;
                font-family:'Orbitron','Segoe UI'; font-weight:700;
                letter-spacing:1px;
            }}
            QPushButton:hover {{
                background:rgba(114,255,79,0.1); color:{N_TEXT};
            }}
            QPushButton#ninja_primary {{
                background:{N_ACCENT}; color:{N_BG};
                border:none; font-weight:900;
            }}
            QPushButton#ninja_primary:hover {{
                background:white; color:{N_BG};
            }}
            QPushButton#ninja_danger {{
                background:{N_RED}; color:white;
                border:none;
            }}
            QPushButton#ninja_danger:hover {{
                background:#CC2222;
            }}
            QPushButton#ninja_active {{
                background:{N_ACCENT}; color:{N_BG};
                border:none; font-weight:900;
            }}
            QListWidget {{
                background:{N_SURFACE}; border:1px solid {N_BORDER};
                border-radius:4px; padding:2px;
                font-family:'Share Tech Mono','Consolas';
                font-size:10px;
                scrollbar-width:thin;
            }}
            QListWidget::item {{ padding:5px 6px; border-radius:3px;
                border-left:2px solid transparent; }}
            QListWidget::item:selected {{
                background:rgba(168,108,255,0.15);
                border-left:2px solid {N_PURPLE};
                color:{N_TEXT};
            }}
            QListWidget::item:hover:!selected {{
                background:rgba(114,255,79,0.05);
                border-left:2px solid rgba(114,255,79,0.2);
            }}
            QScrollArea {{ border:none; background:{N_BG}; }}
            QScrollBar:vertical {{
                background:{N_SURFACE}; width:6px; border-radius:3px;
            }}
            QScrollBar::handle:vertical {{
                background:{N_BORDER}; border-radius:3px; min-height:20px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{N_ACCENT}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{
                background:{N_SURFACE}; height:6px; border-radius:3px;
            }}
            QScrollBar::handle:horizontal {{
                background:{N_BORDER}; border-radius:3px;
            }}
        """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ninja = _is_ninja()
        title = "⛩ SHINOBI LOGBOOK" if self._ninja else "📓 Daily Journal"
        self.setWindowTitle(title)
        self.setMinimumSize(1060, 700)
        self._apply_theme_ss()

        self._journal      = _load_journal()
        self._current_date = date.today().isoformat()
        self._mode         = MODE_PEN

        self._setup_ui()
        self._refresh_sidebar()
        self._load_date(self._current_date)

    def _apply_theme_ss(self):
        """Apply correct stylesheet for current theme."""
        self._ninja = _is_ninja()
        self.setStyleSheet(self._ninja_ss() if self._ninja else self._classic_ss())

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        if self._ninja:
            self._setup_ui_ninja()
        else:
            self._setup_ui_classic()

    # ── Classic layout ────────────────────────────────────────────────────────

    def _setup_ui_classic(self):
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

    # ── Ninja layout ──────────────────────────────────────────────────────────

    def _setup_ui_ninja(self):
        """Build the Dojo/Ninja themed journal UI matching test.html aesthetic."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Topbar ────────────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(52)
        top.setStyleSheet(
            f"QFrame{{background:{N_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {N_BORDER};}}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 0, 14, 0)
        tl.setSpacing(10)

        # Logo section
        logo_box = QLabel("猿")
        logo_box.setFixedSize(32, 32)
        logo_box.setAlignment(Qt.AlignCenter)
        logo_box.setStyleSheet(
            f"color:{N_ACCENT};border:2px solid {N_ACCENT};"
            f"border-radius:5px;font-size:13px;font-weight:900;"
            f"font-family:'Orbitron','Segoe UI';background:{N_BG};")
        tl.addWidget(logo_box)

        logo_txt = QWidget()
        logo_txt.setStyleSheet("background:transparent;")
        lt = QVBoxLayout(logo_txt)
        lt.setContentsMargins(0, 0, 0, 0)
        lt.setSpacing(1)
        lbl_title = QLabel("SCROLL — DAILY JOURNAL")
        lbl_title.setStyleSheet(
            f"color:{N_ACCENT};font-family:'Orbitron','Segoe UI';"
            f"font-size:10px;font-weight:900;letter-spacing:2px;")
        lbl_sub = QLabel("MISSION LOG • SM-2")
        lbl_sub.setStyleSheet(
            f"color:{N_SUBTEXT};font-size:7px;letter-spacing:0.5px;"
            f"font-family:'Share Tech Mono','Consolas';")
        lt.addWidget(lbl_title)
        lt.addWidget(lbl_sub)
        tl.addWidget(logo_txt)
        tl.addSpacing(8)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setFixedSize(1, 28)
        sep.setStyleSheet(f"background:{N_BORDER};border:none;")
        tl.addWidget(sep)
        tl.addSpacing(8)

        # Date navigation
        self._btn_prev = self._arrow_btn("‹", self._go_prev)
        self._btn_date = QPushButton()
        self._btn_date.setFixedHeight(30)
        self._btn_date.setMinimumWidth(220)
        self._btn_date.setStyleSheet(
            f"QPushButton{{background:{N_CARD};color:{N_TEXT};"
            f"border:1px solid {N_BORDER};border-radius:2px;"
            f"padding:3px 14px;font-size:10px;font-weight:700;"
            f"font-family:'Orbitron','Segoe UI';letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(114,255,79,0.08);"
            f"border-color:{N_ACCENT};color:{N_ACCENT};}}")
        self._btn_date.setToolTip("Click to pick a date")
        self._btn_date.clicked.connect(self._open_date_picker)
        self._btn_next = self._arrow_btn("›", self._go_next)

        self._lbl_focus = QLabel("")
        self._lbl_focus.setStyleSheet(
            f"color:{N_PURPLE};font-size:10px;font-weight:700;"
            f"font-family:'Share Tech Mono','Consolas';padding:0 10px;")
        self._lbl_focus.hide()

        btn_today = QPushButton("NOW")
        btn_today.setIcon(_make_icon(_ICONS["now"]))
        btn_today.setFixedHeight(30)
        btn_today.clicked.connect(self._go_today)

        tl.addWidget(self._btn_prev)
        tl.addWidget(self._btn_date)
        tl.addWidget(self._lbl_focus)
        tl.addWidget(self._btn_next)
        tl.addSpacing(6)
        tl.addWidget(btn_today)
        tl.addSpacing(10)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine)
        sep2.setFixedSize(1, 28)
        sep2.setStyleSheet(f"background:{N_BORDER};border:none;")
        tl.addWidget(sep2)
        tl.addSpacing(6)

        # Tool mode buttons
        self._btn_pen    = self._mode_btn("INK JUTSU", MODE_PEN,    _make_icon(_ICONS["kunai"]))
        self._btn_eraser = self._mode_btn("VANISH",    MODE_ERASER, _make_icon(_ICONS["smoke"]))
        self._btn_text   = self._mode_btn("CIPHER",    MODE_TEXT,   _make_icon(_ICONS["scroll"]))
        tl.addWidget(self._btn_pen)
        tl.addWidget(self._btn_eraser)
        tl.addWidget(self._btn_text)
        tl.addSpacing(8)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.VLine)
        sep3.setFixedSize(1, 28)
        sep3.setStyleSheet(f"background:{N_BORDER};border:none;")
        tl.addWidget(sep3)
        tl.addSpacing(6)

        # Color dot + tools
        self._dot = QLabel()
        self._dot.setFixedSize(18, 18)
        self._dot.setStyleSheet(
            f"background:{NINJA_INK_COLORS[0]};border-radius:9px;"
            f"border:1.5px solid {N_BORDER};")
        btn_color = QPushButton("PIGMENT")
        btn_color.setIcon(_make_icon(_ICONS["shuriken"]))
        btn_color.setFixedHeight(30)
        btn_color.clicked.connect(self._cycle_color)

        btn_undo = QPushButton("REWIND")
        btn_undo.setIcon(_make_icon(_ICONS["rewind"]))
        btn_undo.setFixedHeight(30)
        btn_undo.clicked.connect(lambda: self._canvas.undo())

        btn_clear = QPushButton("PURGE")
        btn_clear.setIcon(_make_icon(_ICONS["skull"]))
        btn_clear.setFixedHeight(30)
        btn_clear.setObjectName("ninja_danger")
        btn_clear.clicked.connect(self._clear)

        btn_lines = QPushButton("GRID")
        btn_lines.setIcon(_make_icon(_ICONS["grid"]))
        btn_lines.setFixedHeight(30)
        btn_lines.clicked.connect(lambda: self._canvas.toggle_lines())

        btn_export = QPushButton("EXPORT SCROLL")
        btn_export.setIcon(_make_icon(_ICONS["export"]))
        btn_export.setFixedHeight(30)
        btn_export.clicked.connect(self._export)

        tl.addWidget(self._dot)
        tl.addWidget(btn_color)
        tl.addWidget(btn_undo)
        tl.addWidget(btn_clear)
        tl.addWidget(btn_lines)
        tl.addWidget(btn_export)
        tl.addStretch()

        btn_close = QPushButton()
        btn_close.setIcon(_make_icon(_ICONS["close"]))
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet(
            f"QPushButton{{background:{N_CARD};color:{N_SUBTEXT};"
            f"border:1px solid {N_BORDER};border-radius:2px;}}"
            f"QPushButton:hover{{border-color:{N_ACCENT};}}")
        btn_close.clicked.connect(self._on_close)
        tl.addWidget(btn_close)

        root.addWidget(top)

        # ── Main layout ───────────────────────────────────────────────────────
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        split.setStyleSheet(f"QSplitter::handle{{background:{N_BORDER};}}")

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(195)
        sidebar.setStyleSheet(
            f"QFrame{{background:{N_SURFACE};"
            f"border-right:1px solid {N_BORDER};border-radius:0px;}}")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        sbh = QLabel("⛩ CHRONICLE")
        sbh.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        sbh.setFixedHeight(32)
        sbh.setStyleSheet(
            f"color:{N_ACCENT};font-family:'Orbitron','Segoe UI';"
            f"font-size:8px;font-weight:700;letter-spacing:2px;"
            f"border-bottom:1px solid {N_BORDER};padding-left:11px;")
        sl.addWidget(sbh)

        # Quote label at the top of sidebar
        daily_quote = self._get_daily_ninja_quote()
        q_lbl = QLabel(f'「{daily_quote}」')
        q_lbl.setWordWrap(True)
        q_lbl.setAlignment(Qt.AlignCenter)
        q_lbl.setStyleSheet(
            f"color:{N_SUBTEXT};font-family:'Share Tech Mono','Consolas';"
            f"font-size:7px;padding:6px 8px;letter-spacing:0.5px;"
            f"border-bottom:1px solid {N_BORDER};")
        sl.addWidget(q_lbl)

        # Entries list
        dlbl = QLabel("— ENTRIES —")
        dlbl.setFixedHeight(22)
        dlbl.setStyleSheet(
            f"color:{N_SUBTEXT};font-family:'Orbitron','Segoe UI';"
            f"font-size:7.5px;letter-spacing:1px;padding-left:11px;")
        sl.addWidget(dlbl)

        self._sidebar = QListWidget()
        self._sidebar.setStyleSheet(
            f"QListWidget{{background:transparent;border:none;padding:2px 4px;}}"
            f"QListWidget::item{{padding:5px 6px;border-radius:3px;"
            f"border-left:2px solid transparent;color:{N_SUBTEXT};"
            f"font-family:'Orbitron','Segoe UI';font-size:7.5px;font-weight:700;letter-spacing:1px;}}"
            f"QListWidget::item:selected{{background:rgba(168,108,255,0.15);"
            f"border-left:2px solid {N_PURPLE};color:{N_TEXT};}}"
            f"QListWidget::item:hover:!selected{{background:rgba(114,255,79,0.05);"
            f"border-left:2px solid rgba(114,255,79,0.2);}}"
        )
        self._sidebar.itemClicked.connect(self._on_sidebar_click)
        sl.addWidget(self._sidebar, stretch=1)

        # Sidebar footer
        sbfoot = QWidget()
        sbfoot.setFixedHeight(38)
        sbfoot.setStyleSheet(
            f"background:{N_SURFACE};border-top:1px solid {N_BORDER};")
        sfl = QHBoxLayout(sbfoot)
        sfl.setContentsMargins(6, 4, 6, 4)
        sfl.setSpacing(4)
        btn_new = QPushButton("NEW SCROLL")
        btn_new.setIcon(_make_icon(_ICONS["kunai"]))
        btn_new.setStyleSheet(
            f"QPushButton{{background:{N_CARD};color:{N_ACCENT};"
            f"border:1px solid {N_ACCENT};border-radius:2px;"
            f"padding:4px 4px;font-family:'Orbitron','Segoe UI';"
            f"font-size:6.5px;font-weight:700;letter-spacing:0.5px;}}"
            f"QPushButton:hover{{background:rgba(114,255,79,0.1);}}")
        btn_new.clicked.connect(self._go_today)
        sfl.addWidget(btn_new, stretch=1)
        sl.addWidget(sbfoot)

        split.addWidget(sidebar)

        # Canvas scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{N_BG};}}")
        self._canvas = JournalCanvas()
        self._canvas.setStyleSheet(f"background:{N_CANVAS};")
        self._scroll.setWidget(self._canvas)
        split.addWidget(self._scroll)
        split.setSizes([195, 865])

        root.addWidget(split, stretch=1)

        # ── Status bar (ninja quote strip) ────────────────────────────────────
        sbar = QFrame()
        sbar.setFixedHeight(26)
        sbar.setStyleSheet(
            f"QFrame{{background:{N_SURFACE};border-top:1px solid {N_BORDER};"
            f"border-radius:0px;}}")
        sb_layout = QHBoxLayout(sbar)
        sb_layout.setContentsMargins(10, 0, 10, 0)
        sb_layout.setSpacing(6)

        dot = QLabel("●")
        dot.setFixedWidth(12)
        dot.setStyleSheet(
            f"color:{N_ACCENT};font-size:8px;"
            f"qproperty-alignment:AlignCenter;")
        self._hint_lbl = QLabel("")
        self._hint_lbl.setAlignment(Qt.AlignCenter)
        self._hint_lbl.setStyleSheet(
            f"color:{N_ACCENT};font-size:8px;letter-spacing:1px;"
            f"font-family:'Share Tech Mono','Consolas';")

        mode_hint = QLabel("I=INK  V=VANISH  C=CIPHER  P=PIGMENT")
        mode_hint.setStyleSheet(
            f"color:{N_SUBTEXT};font-size:7px;font-family:'Share Tech Mono','Consolas';"
            f"letter-spacing:0.5px;")

        sb_layout.addWidget(dot)
        sb_layout.addWidget(self._hint_lbl, stretch=1)
        sb_layout.addWidget(mode_hint)
        root.addWidget(sbar)

        self._update_mode_ui()

    @staticmethod
    def _get_daily_ninja_quote() -> str:
        """Return a rotating daily ninja quote."""
        quotes = [
            "THE PAIN OF DISCIPLINE IS LESS THAN THE PAIN OF REGRET.",
            "A NINJA WHO QUITS LEARNS NOTHING. WRITE AGAIN.",
            "SMALL PROGRESS DAILY BEATS PERFECT PROGRESS NEVER.",
            "YOUR FUTURE SELF IS WATCHING. RECORD YOUR JOURNEY.",
            "SWORDS ARE SHARPENED BY FRICTION. SO IS YOUR MIND.",
            "TRAIN WHEN MOTIVATED. REFLECT WHEN NOT.",
            "COWABUNGA! ONE MORE ENTRY WON'T HURT.",
            "THE DOJO IS OPEN. YOUR EXCUSES ARE NOT WELCOME.",
            "MEMORY IS A SCROLL. FILL IT DAILY.",
            "WRITE TODAY. REMEMBER FOREVER.",
            "A NINJA NEVER SKIPS JOURNAL DAY.",
            "CONSISTENCY IS THE ULTIMATE JUTSU.",
            "MASTER YOUR THOUGHTS. WRITE THEM DOWN.",
            "ONE ENTRY AT A TIME. ONE DAY AT A TIME.",
            "THE SCROLL DOES NOT FILL ITSELF.",
        ]
        from datetime import date as _date
        import datetime as _dt
        d = _date.today()
        day_of_year = d.timetuple().tm_yday
        return quotes[day_of_year % len(quotes)]

    def _arrow_btn(self, text, slot):
        b = QPushButton(text)
        if self._ninja:
            b.setFixedSize(30, 30)
            b.setStyleSheet(
                f"QPushButton{{background:{N_CARD};color:{N_SUBTEXT};"
                f"border:1px solid {N_BORDER};border-radius:2px;"
                f"font-size:16px;font-weight:700;padding:0;}}"
                f"QPushButton:hover{{color:{N_ACCENT};border-color:{N_ACCENT};"
                f"background:rgba(114,255,79,0.08);}}")
        else:
            b.setFixedSize(36, 36)
            b.setFont(QFont("Segoe UI", 20, QFont.Bold))
            b.setStyleSheet(
                f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"font-size:20px;font-weight:bold;padding:0;line-height:36px;}}"
                f"QPushButton:hover{{background:{C_ACCENT};color:white;border:none;}}")
        b.clicked.connect(slot)
        return b

    def _mode_btn(self, text, mode, icon=None):
        b = QPushButton(text)
        if icon:
            b.setIcon(icon)
        if self._ninja:
            b.setFixedHeight(30)
        else:
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
        if self._ninja:
            active_ss = (
                f"QPushButton{{background:{N_ACCENT};color:{N_BG};"
                f"border:none;border-radius:2px;padding:4px 10px;"
                f"font-size:11px;font-family:'Orbitron','Segoe UI';"
                f"font-weight:900;letter-spacing:1px;}}"
                f"QPushButton:hover{{background:white;color:{N_BG};}}")
            normal_ss = (
                f"QPushButton{{background:{N_CARD};color:{N_ACCENT};"
                f"border:1px solid {N_ACCENT};border-radius:2px;"
                f"padding:4px 10px;font-size:11px;"
                f"font-family:'Orbitron','Segoe UI';font-weight:700;letter-spacing:1px;}}"
                f"QPushButton:hover{{background:rgba(114,255,79,0.1);}}")
            hints = {
                MODE_PEN:    "🗡 INK JUTSU — INSCRIBE THE SCROLL",
                MODE_ERASER: "◌ VANISH — STRIKE FROM THE RECORD",
                MODE_TEXT:   "巻 CIPHER — ENCODE YOUR THOUGHTS",
            }
        else:
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
            if self._ninja:
                dn = d.strftime("%A").upper()
                df = d.strftime("%d %B %Y").upper()
                tag = "  ✦" if d == date.today() else ""
                self._btn_date.setText(f"{dn} — {df}{tag}")
            else:
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
        
        # Override with live timer state if viewing today
        if date_str == date.today().isoformat():
            state_file = os.path.join(os.path.expanduser("~"), "anki_timer_state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        timer_data = json.load(f)
                    if timer_data.get("date") == date_str:
                        focus_secs = max(focus_secs, int(timer_data.get("seconds", 0)))
                except Exception:
                    pass

        # Show 0s for today so the UI element is always discoverable
        if focus_secs > 0 or date_str == date.today().isoformat():
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
        
        entry = self._journal.get(self._current_date, {})
        if isinstance(entry, list):
            entry = {"strokes": entry, "texts": []}
            
        if strokes or texts:
            entry["strokes"] = _strokes_to_json(strokes)
            entry["texts"]   = _texts_to_json(texts)
            self._journal[self._current_date] = entry
        else:
            entry.pop("strokes", None)
            entry.pop("texts", None)
            if not entry:
                self._journal.pop(self._current_date, None)
            else:
                self._journal[self._current_date] = entry

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
                if self._ninja:
                    if d == date.today():
                        label = "✦ TODAY — " + d.strftime("%d %b").upper()
                    elif d == date.today() - timedelta(days=1):
                        label = "YESTERDAY — " + d.strftime("%d %b").upper()
                    else:
                        label = d.strftime("%d %b %Y").upper()
                    icon = "▪" if has else "▫"
                    item = QListWidgetItem(f"  {icon}  {label}")
                else:
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
                    item.setForeground(QColor(N_SUBTEXT if self._ninja else C_SUBTEXT))
                self._sidebar.addItem(item)
                if d_str == sel:
                    self._sidebar.setCurrentItem(item)
            except Exception:
                pass

    # ── Tools ─────────────────────────────────────────────────────────────────

    def _cycle_color(self):
        c = self._canvas.cycle_color()
        if self._ninja:
            self._dot.setStyleSheet(
                f"background:{c};border-radius:9px;border:1.5px solid {N_BORDER};")
        else:
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

    def reject(self):
        self._save_current()
        super().reject()

    def closeEvent(self, e):
        self._save_current()
        super().closeEvent(e)