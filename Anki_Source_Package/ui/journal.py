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
import re
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QFrame,
    QFileDialog,
    QMessageBox,
    QAction,
    QMenu,
    QSizePolicy,
    QCalendarWidget,
    QScrollArea,
)
from PyQt5.QtCore import Qt, QPointF, QRect, QRectF, QSize, QDate, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap, QFont, QPolygonF, QIcon
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtCore import QByteArray

from ui.canvas.retro_effects import CRTOverlay, RetroParticlePanel, OozeDripWidget
# ── Classic Theme ─────────────────────────────────────────────────────────────
# ── Theme constants — single source of truth is theme_manager.PALETTES["dark"] ──
from theme_manager import get_palette as _get_palette

_DARK = _get_palette("dark")
C_BG = _DARK["C_BG"]
C_SURFACE = _DARK["C_SURFACE"]
C_CARD = _DARK["C_CARD"]
C_ACCENT = _DARK["C_ACCENT"]
C_GREEN = _DARK["C_GREEN"]
C_RED = _DARK["C_RED"]
C_TEXT = _DARK["C_TEXT"]
C_SUBTEXT = _DARK["C_SUBTEXT"]
C_BORDER = _DARK["C_BORDER"]

# ── Ninja / Dojo Theme ────────────────────────────────────────────────────────
N_BG = "#07070B"
N_SURFACE = "#0F0F17"
N_CARD = "#14141F"
N_ACCENT = "#72FF4F"  # neon green — primary highlight
N_PURPLE = "#A86CFF"  # secondary — ninja purple
N_RED = "#FF4444"
N_TEXT = "#E0E0FF"
N_SUBTEXT = "#5F627D"
N_BORDER = "#1A1A26"
N_CANVAS = "#07070B"

# ── Theme resolver ────────────────────────────────────────────────────────────


def _is_ninja() -> bool:
    """Return True when the app is running in Ninja/Dojo mode."""
    try:
        from PyQt5.QtWidgets import QApplication
        from theme_manager import is_retro_theme

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        return is_retro_theme(theme) or theme == "dojo"
    except Exception:
        return False


def _t(classic_val, ninja_val):
    """Pick classic or ninja value based on current theme."""
    return ninja_val if _is_ninja() else classic_val


INK_COLORS = ["#CDD6F4", "#FF4444", "#FFD700", "#50FA7B", "#00FFFF", "#F7916A"]
NINJA_INK_COLORS = ["#72FF4F", "#A86CFF", "#E0E0FF", "#FF4444", "#F1FA8C", "#F7916A"]
INK_WIDTH = 2.0
ERASER_WIDTH = 22.0
PAGE_WIDTH = 900  # logical canvas width
PAGE_HEIGHT = 1200  # initial height — grows as you scroll down
JOURNAL_FONT_SCALE = 1.4
JOURNAL_WINDOW_SCALE = 1.25
JOURNAL_BASE_WINDOW_SIZE = (1060, 700)
JOURNAL_WINDOW_SIZE = (
    int(round(JOURNAL_BASE_WINDOW_SIZE[0] * JOURNAL_WINDOW_SCALE)),
    int(round(JOURNAL_BASE_WINDOW_SIZE[1] * JOURNAL_WINDOW_SCALE)),
)
_FONT_SIZE_RE = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(px|pt)")


def _journal_font_size(value):
    return max(1, int(round(float(value) * JOURNAL_FONT_SCALE)))


def _scale_font_css(style: str) -> str:
    return _FONT_SIZE_RE.sub(
        lambda m: f"{m.group(1)}{_journal_font_size(m.group(2))}{m.group(3)}",
        style or "",
    )

MODE_PEN = "pen"
MODE_ERASER = "eraser"
MODE_TEXT = "text"


from services.journal_manager import (
    _load_journal,
    _save_journal,
    _strokes_to_json,
    _strokes_from_json,
    _texts_to_json,
    _texts_from_json,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  DATE PICKER POPUP
# ═══════════════════════════════════════════════════════════════════════════════


class _DatePicker(QDialog):
    date_selected = pyqtSignal(str)

    def __init__(self, current_date_str, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(_scale_font_css(f"""
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
        """))
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
        cal.clicked.connect(
            lambda qd: (
                self.date_selected.emit(qd.toString("yyyy-MM-dd")),
                self.accept(),
            )
        )
        L.addWidget(cal)


# ═══════════════════════════════════════════════════════════════════════════════
#  INK CANVAS  (scrollable)
# ═══════════════════════════════════════════════════════════════════════════════


class JournalCanvas(QWidget):
    """Freehand ink + eraser + keyboard-text canvas. Grows downward on scroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        self._p = _get_palette(theme)

        self._page_h = PAGE_HEIGHT
        self.setMinimumWidth(PAGE_WIDTH)
        self.setFixedHeight(self._page_h)
        bg = self._p.get("C_BG", N_CANVAS if _is_ninja() else C_BG)
        self.setStyleSheet(f"background:{bg};")
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        self._strokes = []
        self._texts = []
        self._current = []
        self._color_idx = 0
        self._drawing = False
        self._show_lines = True
        self._mode = MODE_PEN

        # Text state
        self._text_pos = None
        self._text_buf = ""
        self._text_size = 14

        # Eraser cursor — tracked in mouseMoveEvent, not from global cursor()
        self._eraser_pos = None
        self.setMouseTracking(True)
        self._stroke_bboxes = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def set_content(self, strokes, texts):
        self._strokes = strokes
        self._texts = texts
        self._current = []
        self._commit_text()
        self._stroke_bboxes = {}
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
            MODE_PEN: Qt.CrossCursor,
            MODE_ERASER: Qt.BlankCursor,
            MODE_TEXT: Qt.IBeamCursor,
        }
        self.setCursor(cursors.get(mode, Qt.CrossCursor))
        self.update()

    def clear(self):
        self._strokes = []
        self._texts = []
        self._current = []
        self._commit_text()
        self._stroke_bboxes = {}
        self._page_h = PAGE_HEIGHT
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
            popped = self._strokes.pop()
            self._stroke_bboxes.pop(id(popped), None)
            self.update()

    def _get_stroke_bbox(self, stroke):
        stroke_id = id(stroke)
        if stroke_id not in self._stroke_bboxes:
            pts = stroke[1:]
            if not pts:
                self._stroke_bboxes[stroke_id] = QRectF()
            else:
                xs = [p.x() for p in pts]
                ys = [p.y() for p in pts]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                self._stroke_bboxes[stroke_id] = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        return self._stroke_bboxes[stroke_id]

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
        px.fill(QColor(self._p.get("C_BG", N_CANVAS if _is_ninja() else C_BG)))
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint(p)
        p.end()
        return px

    # ── Text commit ───────────────────────────────────────────────────────────

    def _commit_text(self):
        if self._text_buf.strip() and self._text_pos:
            colors = self._colors()
            self._texts.append(
                {
                    "x": self._text_pos.x(),
                    "y": self._text_pos.y(),
                    "text": self._text_buf,
                    "color": colors[self._color_idx % len(colors)],
                    "size": self._text_size,
                }
            )
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
        self._paint(p, e.rect())

    def _paint(self, p, rect=None):
        w, h = self.width(), self.height()
        ninja = _is_ninja()
        bg = self._p.get("C_BG", N_CANVAS if ninja else C_BG)
        
        if rect is not None and not rect.isEmpty():
            p.fillRect(rect, QColor(bg))
        else:
            p.fillRect(0, 0, w, h, QColor(bg))

        if self._show_lines:
            if ninja:
                # Ninja: subtle teal grid lines
                p.setPen(QPen(QColor("#0D1220"), 1))
                y_start = 40
                if rect is not None and not rect.isEmpty():
                    y_start = max(40, ((rect.top() - 40) // 32) * 32 + 40)
                    y_end = min(h, rect.bottom() + 32)
                else:
                    y_end = h
                for y in range(y_start, y_end, 32):
                    p.drawLine(0, y, w, y)
                if rect is None or rect.left() <= 60 <= rect.right():
                    p.setPen(QPen(QColor("#0F1A10"), 1))
                    p.drawLine(60, 0, 60, h)
            else:
                p.setPen(QPen(QColor("#2A2A4A"), 1))
                y_start = 40
                if rect is not None and not rect.isEmpty():
                    y_start = max(40, ((rect.top() - 40) // 32) * 32 + 40)
                    y_end = min(h, rect.bottom() + 32)
                else:
                    y_end = h
                for y in range(y_start, y_end, 32):
                    p.drawLine(0, y, w, y)
                if rect is None or rect.left() <= 48 <= rect.right():
                    p.setPen(QPen(QColor("#3A2A3A"), 1))
                    p.drawLine(48, 0, 48, h)

        # Committed strokes
        has_dirty = (rect is not None and not rect.isEmpty())
        dirty_rect = QRectF(rect) if has_dirty else None

        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            
            if dirty_rect is not None:
                bbox = self._get_stroke_bbox(stroke)
                if not bbox.adjusted(-6, -6, 6, 6).intersects(dirty_rect):
                    continue

            color = stroke[0]
            pts = stroke[1:]
            p.setPen(QPen(color, INK_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if len(pts) == 1:
                p.drawPoint(pts[0])
            else:
                p.drawPolyline(QPolygonF(pts))

        # Current stroke
        if len(self._current) >= 2:
            color = self._current[0]
            pts = self._current[1:]
            should_draw = True
            if dirty_rect is not None:
                xs = [pt.x() for pt in pts]
                ys = [pt.y() for pt in pts]
                c_bbox = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                if not c_bbox.adjusted(-6, -6, 6, 6).intersects(dirty_rect):
                    should_draw = False
            if should_draw:
                p.setPen(QPen(color, INK_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(QPolygonF(pts))

        # Text items
        for t in self._texts:
            if dirty_rect is not None:
                text_rect = QRectF(t["x"], t["y"] - t.get("size", 14), 400, t.get("size", 14) * 1.5)
                if not text_rect.intersects(dirty_rect):
                    continue
            font = QFont("Segoe UI", _journal_font_size(t.get("size", 14)))
            p.setFont(font)
            p.setPen(QColor(t.get("color", "#CDD6F4")))
            p.drawText(QPointF(t["x"], t["y"]), t["text"])

        # Active text being typed
        if self._mode == MODE_TEXT and self._text_pos:
            display = self._text_buf + "|"
            should_draw = True
            if dirty_rect is not None:
                text_rect = QRectF(self._text_pos.x(), self._text_pos.y() - self._text_size, 400, self._text_size * 1.5)
                if not text_rect.intersects(dirty_rect):
                    should_draw = False
            if should_draw:
                font = QFont("Segoe UI", _journal_font_size(self._text_size))
                p.setFont(font)
                p.setPen(QColor(INK_COLORS[self._color_idx]))
                p.drawText(self._text_pos, display)
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(display)
                iy = int(self._text_pos.y()) + 3
                ix = int(self._text_pos.x())
                accent = self._p.get("C_ACCENT", N_ACCENT if ninja else C_ACCENT)
                p.setPen(QPen(QColor(accent), 1))
                p.drawLine(ix, iy, ix + tw, iy)

        # Eraser cursor — use tracked position for accuracy
        if self._mode == MODE_ERASER and self._eraser_pos is not None:
            ep = self._eraser_pos
            should_draw = True
            if dirty_rect is not None:
                r = int(ERASER_WIDTH)
                cursor_rect = QRectF(ep.x() - r, ep.y() - r, r * 2, r * 2)
                if not cursor_rect.intersects(dirty_rect):
                    should_draw = False
            if should_draw:
                cursor_col = self._p.get("C_ACCENT", N_ACCENT if ninja else C_SUBTEXT)
                p.setPen(QPen(QColor(cursor_col), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                r = int(ERASER_WIDTH)
                p.drawEllipse(int(ep.x()) - r // 2, int(ep.y()) - r // 2, r, r)

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
            old_pos = self._eraser_pos
            self._eraser_pos = pos  # always track for cursor display

            r = int(ERASER_WIDTH) + 4
            dirty_rect = QRect()
            if old_pos is not None:
                dirty_rect = dirty_rect.united(QRect(int(old_pos.x()) - r // 2, int(old_pos.y()) - r // 2, r, r))
            dirty_rect = dirty_rect.united(QRect(int(pos.x()) - r // 2, int(pos.y()) - r // 2, r, r))
            self.update(dirty_rect)

            if self._drawing:
                self._erase_at(pos)

        elif self._mode == MODE_PEN and self._drawing and self._current:
            self._current.append(pos)
            self._maybe_expand(pos.y())
            pts = self._current[1:]
            if len(pts) >= 2:
                p0, p1 = pts[-2], pts[-1]
                pw = int(INK_WIDTH) + 4
                self.update(
                    QRect(
                        int(min(p0.x(), p1.x())) - pw,
                        int(min(p0.y(), p1.y())) - pw,
                        int(abs(p1.x() - p0.x())) + pw * 2,
                        int(abs(p1.y() - p0.y())) + pw * 2,
                    )
                )
            else:
                self.update()
        e.accept()

    def leaveEvent(self, e):
        old_pos = self._eraser_pos
        self._eraser_pos = None
        if old_pos is not None:
            r = int(ERASER_WIDTH) + 4
            self.update(QRect(int(old_pos.x()) - r // 2, int(old_pos.y()) - r // 2, r, r))
        else:
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
            new_y = (
                (self._text_pos.y() if self._text_pos else 100) + self._text_size + 8
            )
            self._text_pos = QPointF(
                self._text_pos.x() if self._text_pos else 60, new_y
            )
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
        r = ERASER_WIDTH / 2
        r2 = r ** 2
        kept = []
        changed = False
        erased_bboxes = []
        eraser_rect = QRectF(pos.x() - r, pos.y() - r, ERASER_WIDTH, ERASER_WIDTH)

        for stroke in self._strokes:
            bbox = self._get_stroke_bbox(stroke)
            if not bbox.intersects(eraser_rect):
                kept.append(stroke)
                continue

            hit = any(
                (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= r2
                for pt in stroke[1:]
            )
            if hit:
                changed = True
                erased_bboxes.append(bbox)
                self._stroke_bboxes.pop(id(stroke), None)
            else:
                kept.append(stroke)

        if changed:
            self._strokes = kept
            for bbox in erased_bboxes:
                dirty = bbox.toRect().adjusted(-6, -6, 6, 6)
                self.update(dirty)


# ═══════════════════════════════════════════════════════════════════════════════
#  SVG ICON SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════


def _make_icon(svg_body: str, size: int = 14) -> "QIcon":
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 16 16" width="{size}" height="{size}">'
        f"{svg_body}</svg>"
    )
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
        "</g>"
    ),
    "smoke": (
        '<g fill="none" stroke="#A86CFF" stroke-width="1.2" stroke-linecap="round">'
        '<path d="M5,14 Q4,10 6,8 Q4,6 6,4"/>'
        '<path d="M8,14 Q7,9 9,7 Q7,5 9,3"/>'
        '<path d="M11,14 Q10,10 12,8 Q10,6 12,4"/>'
        "</g>"
    ),
    "scroll": (
        '<g fill="#A86CFF">'
        '<rect x="3" y="4" width="10" height="8" rx="1"/>'
        '<rect x="2" y="3" width="2" height="10" rx="1"/>'
        '<rect x="12" y="3" width="2" height="10" rx="1"/>'
        '<line x1="5" y1="7" x2="11" y2="7" stroke="#07070B" stroke-width="1"/>'
        '<line x1="5" y1="9" x2="11" y2="9" stroke="#07070B" stroke-width="1"/>'
        "</g>"
    ),
    "shuriken": (
        '<g fill="#72FF4F">'
        '<polygon points="8,1 9,7 15,8 9,9 8,15 7,9 1,8 7,7"/>'
        "</g>"
    ),
    "rewind": (
        '<g fill="none" stroke="#A86CFF" stroke-width="1.4" stroke-linecap="round">'
        '<path d="M10,4 Q5,4 5,8 Q5,12 10,12"/>'
        '<polyline points="7,2 5,4 7,6"/>'
        "</g>"
    ),
    "skull": (
        '<g fill="#FF4444">'
        '<ellipse cx="8" cy="7" rx="4.5" ry="4"/>'
        '<rect x="5.5" y="10" width="5" height="2.5" rx="0.5"/>'
        '<rect x="5.5" y="12" width="1.5" height="1.5"/>'
        '<rect x="9" y="12" width="1.5" height="1.5"/>'
        '<circle cx="6.3" cy="6.5" r="1.2" fill="#07070B"/>'
        '<circle cx="9.7" cy="6.5" r="1.2" fill="#07070B"/>'
        "</g>"
    ),
    "grid": (
        '<g stroke="#A86CFF" stroke-width="1" fill="none">'
        '<rect x="2" y="2" width="12" height="12" rx="1"/>'
        '<line x1="2" y1="6.7" x2="14" y2="6.7"/>'
        '<line x1="2" y1="11.3" x2="14" y2="11.3"/>'
        '<line x1="6.7" y1="2" x2="6.7" y2="14"/>'
        '<line x1="11.3" y1="2" x2="11.3" y2="14"/>'
        "</g>"
    ),
    "export": (
        '<g fill="none" stroke="#72FF4F" stroke-width="1.3" stroke-linecap="round">'
        '<line x1="8" y1="2" x2="8" y2="11"/>'
        '<polyline points="5,8 8,11 11,8"/>'
        '<polyline points="3,13 3,14.5 13,14.5 13,13"/>'
        "</g>"
    ),
    "now": (
        '<g fill="none" stroke="#72FF4F" stroke-width="1.2">'
        '<circle cx="8" cy="8" r="5.5"/>'
        '<line x1="8" y1="4" x2="8" y2="8.5" stroke-linecap="round"/>'
        '<line x1="8" y1="8.5" x2="11" y2="10" stroke-linecap="round"/>'
        "</g>"
    ),
    "close": (
        '<g stroke="#5F627D" stroke-width="1.5" stroke-linecap="round">'
        '<line x1="4" y1="4" x2="12" y2="12"/>'
        '<line x1="12" y1="4" x2="4" y2="12"/>'
        "</g>"
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  JOURNAL DIALOG
# ═══════════════════════════════════════════════════════════════════════════════


class JournalDialog(QDialog):
    closed = pyqtSignal()

    # ── Stylesheet builders ───────────────────────────────────────────────────

    def _classic_ss(self, p) -> str:
        C_BG = p.get("C_BG", "#1E1E2E")
        C_SURFACE = p.get("C_SURFACE", "#2A2A3E")
        C_CARD = p.get("C_CARD", "#313145")
        C_ACCENT = p.get("C_ACCENT", "#7C6AF7")
        C_TEXT = p.get("C_TEXT", "#CDD6F4")
        C_SUBTEXT = p.get("C_SUBTEXT", "#A6ADC8")
        C_BORDER = p.get("C_BORDER", "#45475A")
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
            QFrame#stats_panel {{
                background:{C_SURFACE}; border-left:1px solid {C_BORDER}; border-radius:0px;
            }}
            QLabel#stats_header {{
                color:{C_ACCENT}; font-weight:bold; font-size:16px; padding-bottom:2px;
            }}
            QLabel#stats_num {{
                color:{C_TEXT}; font-size:22px; font-weight:bold;
            }}
            QLabel#stats_label {{
                color:{C_SUBTEXT}; font-size:12px; font-weight:bold; text-transform:uppercase; letter-spacing:0.5px;
            }}
            QPushButton#btn_toggle_stats {{
                background:{C_CARD}; color:{C_TEXT};
                border:1px solid {C_BORDER}; border-radius:6px;
                padding:5px 12px; font-size:12px;
            }}
            QPushButton#btn_toggle_stats:hover {{
                background:{C_SURFACE}; color:white;
            }}
            QPushButton#btn_toggle_stats:checked {{
                background:{C_ACCENT}; color:white; border:none;
            }}
            QPushButton#btn_toggle_stats:checked:hover {{
                background:#6A58E0;
            }}
        """

    def _ninja_ss(self, p) -> str:
        """Ninja/Dojo/TMNT stylesheet — matches test.html visual language."""
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        is_cyan = theme in ("manhattan", "tmnt")
        hover_g = "0, 240, 255" if is_cyan else "114, 255, 79"

        N_BG = p.get("C_BG", "#07070B")
        N_SURFACE = p.get("C_SURFACE", "#0F0F17")
        N_CARD = p.get("C_CARD", "#14141F")
        N_ACCENT = p.get("C_ACCENT", "#72FF4F")
        N_PURPLE = p.get("C_PURPLE", "#A86CFF")
        N_RED = p.get("C_RED", "#FF4444")
        N_TEXT = p.get("C_TEXT", "#E0E0FF")
        N_SUBTEXT = p.get("C_SUBTEXT", "#5F627D")
        N_BORDER = p.get("C_BORDER", "#1A1A26")
        hf = p.get("header_font", "{hf}").split(",")[0].strip("'")
        bf = p.get("body_font", "'Share Tech Mono'").split(",")[0].strip("'")

        is_ps = (hf == "Press Start 2P")
        btn_padding = "2px 8px" if is_ps else "4px 10px"
        btn_fsize = "8px" if is_ps else "11px"
        btn_fweight = "normal" if is_ps else "700"
        btn_letter_spacing = "0px" if is_ps else "1px"

        stats_hdr_size = "13px" if is_ps else "16px"
        stats_lbl_size = "11px" if is_ps else "13px"

        return f"""
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap');
            QDialog  {{ background:{N_BG}; color:{N_TEXT}; }}
            QWidget  {{ background:{N_BG}; color:{N_TEXT};
                        font-family:{bf}, 'Segoe UI'; font-size:12px; }}
            QFrame   {{ background:{N_SURFACE}; border-radius:4px; }}
            QLabel   {{ background:transparent; color:{N_TEXT}; }}
            QPushButton {{
                background:{N_CARD}; color:{N_ACCENT};
                border:1px solid {N_ACCENT}; border-radius:2px;
                padding:{btn_padding}; font-size:{btn_fsize};
                font-family:{hf}, 'Segoe UI'; font-weight:{btn_fweight};
                letter-spacing:{btn_letter_spacing};
            }}
            QPushButton:hover {{
                background:rgba({hover_g},0.1); color:{N_TEXT};
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
                font-family:{bf}, 'Consolas';
                font-size:10px;
            }}
            QListWidget::item {{ padding:5px 6px; border-radius:3px;
                border-left:2px solid transparent; }}
            QListWidget::item:selected {{
                background:rgba(168,108,255,0.15);
                border-left:2px solid {N_PURPLE};
                color:{N_TEXT};
            }}
            QListWidget::item:hover:!selected {{
                background:rgba({hover_g},0.05);
                border-left:2px solid rgba({hover_g},0.2);
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
            QFrame#stats_panel {{
                background:{N_SURFACE}; border-left:1px solid {N_BORDER}; border-radius:0px;
            }}
            QLabel#stats_header {{
                color:{N_ACCENT}; font-family:{hf}, 'Segoe UI'; font-size:{stats_hdr_size}; font-weight:900; letter-spacing:1.5px; padding-bottom:2px;
            }}
            QLabel#stats_num {{
                color:{N_TEXT}; font-family:{bf}, 'Consolas'; font-size:20px; font-weight:bold;
            }}
            QLabel#stats_label {{
                color:{N_SUBTEXT}; font-family:{hf}, 'Segoe UI'; font-size:{stats_lbl_size}; font-weight:700; text-transform:uppercase; letter-spacing:1px;
            }}
            QPushButton#btn_toggle_stats {{
                background:{N_CARD}; color:{N_ACCENT};
                border:1px solid {N_ACCENT}; border-radius:2px;
                padding:4px 10px; font-size:11px;
                font-family:{hf}, 'Segoe UI'; font-weight:700; letter-spacing:1px;
            }}
            QPushButton#btn_toggle_stats:hover {{
                background:rgba({hover_g},0.1);
            }}
            QPushButton#btn_toggle_stats:checked {{
                background:{N_ACCENT}; color:{N_BG}; border:none; font-weight:900;
            }}
            QPushButton#btn_toggle_stats:checked:hover {{
                background:white; color:{N_BG};
            }}
        """

    def __init__(self, parent=None):
        import time
        t0 = time.perf_counter()
        super().__init__(parent)
        self._ninja = _is_ninja()
        title = "⛩ SHINOBI LOGBOOK" if self._ninja else "📓 Daily Journal"
        self.setWindowTitle(title)
        self.setMinimumSize(*JOURNAL_WINDOW_SIZE)
        self.resize(*JOURNAL_WINDOW_SIZE)
        self._apply_theme_ss()
        self._stats_visible = True

        try:
            self._journal = _load_journal()
            self._journal_load_error = None
        except Exception as e:
            self._journal = {}
            self._journal_load_error = e
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "Journal Load Error",
                f"Failed to load daily journal data:\n{e}\n\nSaving has been disabled to prevent data loss. Please restore a backup.",
            )

        self._current_date = date.today().isoformat()
        self._mode = MODE_PEN

        self._setup_ui()
        self._scale_journal_ui()
        self._refresh_sidebar()
        self._load_date(self._current_date)
        print(f"[PROFILE][journal_init] Daily Journal loaded in {(time.perf_counter() - t0) * 1000:.1f}ms")

        # Retro Visual Overlays
        self.crt = None
        self.particles = None
        self.drips = None
        if self._ninja:
            self.particles = RetroParticlePanel(self, is_ooze=True)
            self.particles.lower()
            self.drips = OozeDripWidget(self)
            self.crt = CRTOverlay(self)
            self.crt.trigger_boot_flicker()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "particles", None) is not None:
            self.particles.setGeometry(self.rect())
        if getattr(self, "drips", None) is not None:
            self.drips.setGeometry(0, 0, self.width(), 30)
            self.drips.raise_()
        if getattr(self, "crt", None) is not None:
            self.crt.setGeometry(self.rect())
            self.crt.raise_()

    def _apply_theme_ss(self):
        """Apply correct stylesheet for current theme."""
        self._ninja = _is_ninja()
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        self._p = _get_palette(theme)
        self.setStyleSheet(
            self._ninja_ss(self._p) if self._ninja else self._classic_ss(self._p)
        )

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        if self._ninja:
            self._setup_ui_ninja()
        else:
            self._setup_ui_classic()

    def _scale_journal_ui(self):
        widgets = [self] + self.findChildren(QWidget)
        for widget in widgets:
            style = widget.styleSheet()
            if style and not widget.property("_journal_font_scaled"):
                widget.setStyleSheet(_scale_font_css(style))
                widget.setProperty("_journal_font_scaled", True)

        fixed_height_widgets = [
            widget
            for widget in widgets
            if widget.minimumHeight() == widget.maximumHeight()
            and 0 < widget.minimumHeight() < 400
        ]
        for widget in fixed_height_widgets:
            if widget.property("_journal_height_scaled"):
                continue
            widget.setFixedHeight(_journal_font_size(widget.minimumHeight()))
            widget.setProperty("_journal_height_scaled", True)

        fixed_width_widgets = [
            widget
            for widget in widgets
            if widget.minimumWidth() == widget.maximumWidth()
            and 1 < widget.minimumWidth() < 400
        ]
        for widget in fixed_width_widgets:
            if widget.property("_journal_width_scaled"):
                continue
            widget.setFixedWidth(_journal_font_size(widget.minimumWidth()))
            widget.setProperty("_journal_width_scaled", True)
        self._journal_ui_scaled = True

    # ── Classic layout ────────────────────────────────────────────────────────

    def _setup_ui_classic(self):
        p = self._p
        C_BG = p.get("C_BG", "#1E1E2E")
        C_SURFACE = p.get("C_SURFACE", "#2A2A3E")
        C_CARD = p.get("C_CARD", "#313145")
        C_ACCENT = p.get("C_ACCENT", "#7C6AF7")
        C_TEXT = p.get("C_TEXT", "#CDD6F4")
        C_SUBTEXT = p.get("C_SUBTEXT", "#A6ADC8")
        C_BORDER = p.get("C_BORDER", "#45475A")
        hf = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        bf = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top = QFrame()
        top.setFixedHeight(54)
        top.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {C_BORDER};}}"
        )
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
        self._btn_date.setMinimumWidth(_journal_font_size(240))
        self._btn_date.setStyleSheet(
            f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 16px;font-size:13px;font-weight:bold;text-align:center;}}"
            f"QPushButton:hover{{background:{C_ACCENT};color:white;border:none;}}"
        )
        self._btn_date.setToolTip("Click to pick a date")
        self._btn_date.clicked.connect(self._open_date_picker)

        self._lbl_focus = QLabel("")
        self._lbl_focus.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:13px;font-weight:bold;padding-left:12px;padding-right:12px;"
        )
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
        self._btn_pen = self._mode_btn("✏  Pen", MODE_PEN)
        self._btn_eraser = self._mode_btn("⬜ Eraser", MODE_ERASER)
        self._btn_text = self._mode_btn("T  Text", MODE_TEXT)
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
            f"border:2px solid {C_BORDER};"
        )
        btn_color = QPushButton("Color")
        btn_color.setFixedHeight(36)
        btn_color.clicked.connect(self._cycle_color)
        tl.addWidget(self._dot)
        tl.addWidget(btn_color)

        btn_undo = QPushButton("↩ Undo")
        btn_undo.setFixedHeight(36)
        btn_undo.clicked.connect(lambda: self._canvas.undo())

        btn_clear = QPushButton("🗑 Clear")
        btn_clear.setFixedHeight(36)
        btn_clear.setStyleSheet(
            f"QPushButton{{background:{C_RED};color:white;border:none;"
            f"border-radius:6px;padding:5px 12px;}}"
            f"QPushButton:hover{{background:#CC2222;}}"
        )
        btn_clear.clicked.connect(self._clear)

        btn_lines = QPushButton("📏 Lines")
        btn_lines.setFixedHeight(36)
        btn_lines.clicked.connect(lambda: self._canvas.toggle_lines())

        btn_export = QPushButton("💾 PNG")
        btn_export.setFixedHeight(36)
        btn_export.clicked.connect(self._export)

        self._btn_toggle_stats = QPushButton("📊 Stats")
        self._btn_toggle_stats.setObjectName("btn_toggle_stats")
        self._btn_toggle_stats.setFixedHeight(36)
        self._btn_toggle_stats.setCheckable(True)
        self._btn_toggle_stats.setChecked(self._stats_visible)
        self._btn_toggle_stats.clicked.connect(self._toggle_stats)

        tl.addWidget(btn_undo)
        tl.addWidget(btn_clear)
        tl.addWidget(btn_lines)
        tl.addWidget(btn_export)
        tl.addWidget(self._btn_toggle_stats)
        tl.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(36, 36)
        btn_close.clicked.connect(self._on_close)
        tl.addWidget(btn_close)

        root.addWidget(top)

        # Main area
        split = QSplitter(Qt.Horizontal)
        self._splitter = split
        split.setHandleWidth(1)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(188)
        sidebar.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};"
            f"border-right:1px solid {C_BORDER};border-radius:0px;}}"
        )
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 12, 8, 8)
        sl.setSpacing(6)
        hdr = QLabel("📅  Entries")
        hdr.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;font-weight:bold;"
            f"padding-bottom:4px;border-bottom:1px solid {C_BORDER};"
        )
        sl.addWidget(hdr)
        self._sidebar = QListWidget()
        self._sidebar.itemClicked.connect(self._on_sidebar_click)
        sl.addWidget(self._sidebar, stretch=1)
        split.addWidget(sidebar)

        # Scroll area wrapping the canvas
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._scroll.setStyleSheet(f"QScrollArea{{border:none;background:{C_BG};}}")

        self._canvas = JournalCanvas()
        self._scroll.setWidget(self._canvas)
        split.addWidget(self._scroll)

        # Stats Panel
        self._stats_panel = self._build_stats_panel()
        self._stats_panel.setVisible(self._stats_visible)
        split.addWidget(self._stats_panel)
        split.setSizes([188, 800, 337])

        root.addWidget(split, stretch=1)

        # Hint bar
        self._hint_lbl = QLabel("")
        self._hint_lbl.setAlignment(Qt.AlignCenter)
        self._hint_lbl.setFixedHeight(22)
        self._hint_lbl.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:11px;background:{C_SURFACE};"
            f"border-top:1px solid {C_BORDER};padding:2px;"
        )
        root.addWidget(self._hint_lbl)

        self._update_mode_ui()

    # ── Ninja layout ──────────────────────────────────────────────────────────

    def _setup_ui_ninja(self):
        """Build the Dojo/Ninja themed journal UI matching test.html aesthetic."""
        p = self._p
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        is_cyan = theme in ("manhattan", "tmnt")
        hover_g = "0, 240, 255" if is_cyan else "114, 255, 79"
        N_BG = p.get("C_BG", "#07070B")
        N_SURFACE = p.get("C_SURFACE", "#0F0F17")
        N_CARD = p.get("C_CARD", "#14141F")
        N_ACCENT = p.get("C_ACCENT", "#72FF4F")
        N_PURPLE = p.get("C_PURPLE", "#A86CFF")
        N_RED = p.get("C_RED", "#FF4444")
        N_TEXT = p.get("C_TEXT", "#E0E0FF")
        N_SUBTEXT = p.get("C_SUBTEXT", "#5F627D")
        N_BORDER = p.get("C_BORDER", "#1A1A26")
        hf = p.get("header_font", "'Orbitron'").split(",")[0].strip("'")
        bf = p.get("body_font", "'Share Tech Mono'").split(",")[0].strip("'")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Topbar ────────────────────────────────────────────────────────────
        top = QFrame()
        self._ninja_topbar = top
        top.setObjectName("ninja_journal_topbar")
        top.setFixedHeight(104 if self._ninja else 84)
        top.setStyleSheet(
            f"QFrame{{background:{N_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {N_BORDER};}}"
        )
        top_l = QVBoxLayout(top)
        top_l.setContentsMargins(10, 32 if self._ninja else 6, 10, 6)
        top_l.setSpacing(4)
        tl = QHBoxLayout()
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        tool_l = QHBoxLayout()
        tool_l.setContentsMargins(0, 0, 0, 0)
        tool_l.setSpacing(6)
        top_l.addLayout(tl)
        top_l.addLayout(tool_l)

        # Logo section
        logo_box = QLabel("猿")
        logo_box.setFixedSize(32, 32)
        logo_box.setAlignment(Qt.AlignCenter)
        logo_box.setStyleSheet(
            f"color:{N_ACCENT};border:2px solid {N_ACCENT};"
            f"border-radius:5px;font-size:13px;font-weight:900;"
            f"font-family:{hf}, 'Segoe UI';background:{N_BG};"
        )
        tl.addWidget(logo_box)

        logo_txt = QWidget()
        logo_txt.setStyleSheet("background:transparent;")
        logo_txt.setMaximumWidth(_journal_font_size(240))
        lt = QVBoxLayout(logo_txt)
        lt.setContentsMargins(0, 0, 0, 0)
        lt.setSpacing(1)
        lbl_title = QLabel("SCROLL — DAILY JOURNAL")
        lbl_title.setStyleSheet(
            f"color:{N_ACCENT};font-family:{hf}, 'Segoe UI';"
            f"font-size:10px;font-weight:900;letter-spacing:2px;"
        )
        lbl_sub = QLabel("MISSION LOG • SM-2")
        lbl_sub.setStyleSheet(
            f"color:{N_SUBTEXT};font-size:7px;letter-spacing:0.5px;"
            f"font-family:{bf}, 'Consolas';"
        )
        lt.addWidget(lbl_title)
        lt.addWidget(lbl_sub)
        tl.addWidget(logo_txt)
        tl.addSpacing(4)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedSize(1, 28)
        sep.setStyleSheet(f"background:{N_BORDER};border:none;")
        tl.addWidget(sep)
        tl.addSpacing(4)

        # Date navigation
        self._btn_prev = self._arrow_btn("‹", self._go_prev)
        self._btn_date = QPushButton()
        self._btn_date.setFixedHeight(30)
        self._btn_date.setMinimumWidth(_journal_font_size(230))
        self._btn_date.setMaximumWidth(_journal_font_size(290))
        self._btn_date.setStyleSheet(
            f"QPushButton{{background:{N_CARD};color:{N_TEXT};"
            f"border:1px solid {N_BORDER};border-radius:2px;"
            f"padding:3px 8px;font-size:10px;font-weight:700;"
            f"font-family:{hf}, 'Segoe UI';letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(114,255,79,0.08);"
            f"border-color:{N_ACCENT};color:{N_ACCENT};}}"
        )
        self._btn_date.setToolTip("Click to pick a date")
        self._btn_date.clicked.connect(self._open_date_picker)
        self._btn_next = self._arrow_btn("›", self._go_next)

        self._lbl_focus = QLabel("")
        self._lbl_focus.setStyleSheet(
            f"color:{N_PURPLE};font-size:10px;font-weight:700;"
            f"font-family:{bf}, 'Consolas';padding:0 10px;"
        )
        self._lbl_focus.hide()

        btn_today = QPushButton("NOW")
        btn_today.setIcon(_make_icon(_ICONS["now"]))
        btn_today.setFixedHeight(30)
        btn_today.clicked.connect(self._go_today)

        tl.addWidget(self._btn_prev)
        tl.addWidget(self._btn_date)
        tl.addWidget(self._lbl_focus)
        tl.addWidget(self._btn_next)
        tl.addSpacing(2)
        tl.addWidget(btn_today)
        tl.addSpacing(4)
        tl.addStretch()

        # Tool mode buttons
        self._btn_pen = self._mode_btn(
            "INK JUTSU", MODE_PEN, _make_icon(_ICONS["kunai"])
        )
        self._btn_eraser = self._mode_btn(
            "VANISH", MODE_ERASER, _make_icon(_ICONS["smoke"])
        )
        self._btn_text = self._mode_btn(
            "CIPHER", MODE_TEXT, _make_icon(_ICONS["scroll"])
        )
        tool_l.addWidget(self._btn_pen)
        tool_l.addWidget(self._btn_eraser)
        tool_l.addWidget(self._btn_text)
        tool_l.addSpacing(4)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setFixedSize(1, 28)
        sep3.setStyleSheet(f"background:{N_BORDER};border:none;")
        tool_l.addWidget(sep3)
        tool_l.addSpacing(4)

        # Color dot + tools
        self._dot = QLabel()
        self._dot.setFixedSize(18, 18)
        self._dot.setStyleSheet(
            f"background:{NINJA_INK_COLORS[0]};border-radius:9px;"
            f"border:1.5px solid {N_BORDER};"
        )
        btn_color = QPushButton("PIGMENT")
        btn_color.setIcon(_make_icon(_ICONS["shuriken"]))
        btn_color.setFixedHeight(30)
        btn_color.clicked.connect(self._cycle_color)

        btn_clear = QPushButton("PURGE")
        btn_clear.setIcon(_make_icon(_ICONS["skull"]))
        btn_clear.setFixedHeight(30)
        btn_clear.setObjectName("ninja_danger")
        btn_clear.clicked.connect(self._clear)

        self._overflow_menu = QMenu(self)
        self._overflow_menu.setObjectName("ninja_journal_overflow")
        self._overflow_menu.setStyleSheet(
            f"QMenu{{background:{N_CARD};color:{N_TEXT};"
            f"border:1px solid {N_ACCENT};border-radius:3px;"
            f"font-family:{hf}, 'Segoe UI';font-size:10px;}}"
            f"QMenu::item{{padding:7px 24px 7px 12px;}}"
            f"QMenu::item:selected{{background:rgba(114,255,79,0.12);"
            f"color:{N_ACCENT};}}"
        )

        def _overflow_action(text, icon_name, slot):
            action = QAction(_make_icon(_ICONS[icon_name]), text, self)
            action.triggered.connect(slot)
            self._overflow_menu.addAction(action)
            return action

        self._act_undo = _overflow_action(
            "REWIND", "rewind", lambda: self._canvas.undo()
        )
        self._act_lines = _overflow_action(
            "GRID", "grid", lambda: self._canvas.toggle_lines()
        )
        self._act_export = _overflow_action("EXPORT SCROLL", "export", self._export)

        self._btn_more_tools = QPushButton("MORE")
        self._btn_more_tools.setIcon(_make_icon(_ICONS["scroll"]))
        self._btn_more_tools.setFixedHeight(30)
        self._btn_more_tools.setMenu(self._overflow_menu)
        self._btn_more_tools.setToolTip("More journal actions")

        self._btn_toggle_stats = QPushButton("📊 REPORT")
        self._btn_toggle_stats.setObjectName("btn_toggle_stats")
        self._btn_toggle_stats.setFixedHeight(30)
        self._btn_toggle_stats.setCheckable(True)
        self._btn_toggle_stats.setChecked(self._stats_visible)
        self._btn_toggle_stats.clicked.connect(self._toggle_stats)

        tool_l.addWidget(self._dot)
        tool_l.addWidget(btn_color)
        tool_l.addWidget(btn_clear)
        tool_l.addWidget(self._btn_more_tools)
        tool_l.addWidget(self._btn_toggle_stats)
        tool_l.addStretch()

        btn_close = QPushButton()
        btn_close.setIcon(_make_icon(_ICONS["close"]))
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet(
            f"QPushButton{{background:{N_CARD};color:{N_SUBTEXT};"
            f"border:1px solid {N_BORDER};border-radius:2px;}}"
            f"QPushButton:hover{{border-color:{N_ACCENT};}}"
        )
        btn_close.clicked.connect(self._on_close)
        tl.addWidget(btn_close)

        root.addWidget(top)

        # ── Main layout ───────────────────────────────────────────────────────
        split = QSplitter(Qt.Horizontal)
        self._splitter = split
        split.setHandleWidth(1)
        split.setStyleSheet(f"QSplitter::handle{{background:{N_BORDER};}}")

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(195)
        sidebar.setStyleSheet(
            f"QFrame{{background:{N_SURFACE};"
            f"border-right:1px solid {N_BORDER};border-radius:0px;}}"
        )
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        sbh = QLabel("⛩ CHRONICLE")
        sbh.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        sbh.setFixedHeight(32)
        sbh.setStyleSheet(
            f"color:{N_ACCENT};font-family:{hf}, 'Segoe UI';"
            f"font-size:8px;font-weight:700;letter-spacing:2px;"
            f"border-bottom:1px solid {N_BORDER};padding-left:11px;"
        )
        sl.addWidget(sbh)

        # Quote label at the top of sidebar
        daily_quote = self._get_daily_ninja_quote()
        q_lbl = QLabel(f"「{daily_quote}」")
        q_lbl.setWordWrap(True)
        q_lbl.setAlignment(Qt.AlignCenter)
        q_lbl.setStyleSheet(
            f"color:{N_SUBTEXT};font-family:{bf}, 'Consolas';"
            f"font-size:7px;padding:6px 8px;letter-spacing:0.5px;"
            f"border-bottom:1px solid {N_BORDER};"
        )
        sl.addWidget(q_lbl)

        # Entries list
        dlbl = QLabel("— ENTRIES —")
        dlbl.setFixedHeight(22)
        dlbl.setStyleSheet(
            f"color:{N_SUBTEXT};font-family:{hf}, 'Segoe UI';"
            f"font-size:7.5px;letter-spacing:1px;padding-left:11px;"
        )
        sl.addWidget(dlbl)

        self._sidebar = QListWidget()
        self._sidebar.setStyleSheet(
            f"QListWidget{{background:transparent;border:none;padding:2px 4px;}}"
            f"QListWidget::item{{padding:5px 6px;border-radius:3px;"
            f"border-left:2px solid transparent;color:{N_SUBTEXT};"
            f"font-family:{hf}, 'Segoe UI';font-size:7.5px;font-weight:700;letter-spacing:1px;}}"
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
        sbfoot.setStyleSheet(f"background:{N_SURFACE};border-top:1px solid {N_BORDER};")
        sfl = QHBoxLayout(sbfoot)
        sfl.setContentsMargins(6, 4, 6, 4)
        sfl.setSpacing(4)
        btn_new = QPushButton("NEW SCROLL")
        btn_new.setIcon(_make_icon(_ICONS["kunai"]))
        btn_new.setStyleSheet(
            f"QPushButton{{background:{N_CARD};color:{N_ACCENT};"
            f"border:1px solid {N_ACCENT};border-radius:2px;"
            f"padding:4px 4px;font-family:{hf}, 'Segoe UI';"
            f"font-size:6.5px;font-weight:700;letter-spacing:0.5px;}}"
            f"QPushButton:hover{{background:rgba(114,255,79,0.1);}}"
        )
        btn_new.clicked.connect(self._go_today)
        sfl.addWidget(btn_new, stretch=1)
        sl.addWidget(sbfoot)

        split.addWidget(sidebar)

        # Canvas scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._scroll.setStyleSheet(f"QScrollArea{{border:none;background:{N_BG};}}")
        self._canvas = JournalCanvas()
        self._canvas.setStyleSheet(f"background:{N_CANVAS};")
        self._scroll.setWidget(self._canvas)
        split.addWidget(self._scroll)

        # Stats Panel
        self._stats_panel = self._build_stats_panel()
        self._stats_panel.setVisible(self._stats_visible)
        split.addWidget(self._stats_panel)
        split.setSizes([195, 800, 330])

        root.addWidget(split, stretch=1)

        # ── Status bar (ninja quote strip) ────────────────────────────────────
        sbar = QFrame()
        sbar.setFixedHeight(26)
        sbar.setStyleSheet(
            f"QFrame{{background:{N_SURFACE};border-top:1px solid {N_BORDER};"
            f"border-radius:0px;}}"
        )
        sb_layout = QHBoxLayout(sbar)
        sb_layout.setContentsMargins(10, 0, 10, 0)
        sb_layout.setSpacing(6)

        dot = QLabel("●")
        dot.setFixedWidth(12)
        dot.setStyleSheet(
            f"color:{N_ACCENT};font-size:8px;" f"qproperty-alignment:AlignCenter;"
        )
        self._hint_lbl = QLabel("")
        self._hint_lbl.setAlignment(Qt.AlignCenter)
        self._hint_lbl.setStyleSheet(
            f"color:{N_ACCENT};font-size:8px;letter-spacing:1px;"
            f"font-family:{bf}, 'Consolas';"
        )

        mode_hint = QLabel("I=INK  V=VANISH  C=CIPHER  P=PIGMENT")
        mode_hint.setStyleSheet(
            f"color:{N_SUBTEXT};font-size:7px;font-family:{bf}, 'Consolas';"
            f"letter-spacing:0.5px;"
        )

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
            p = getattr(self, "_p", {})
            bg = p.get("C_CARD", "#14141F")
            subtext = p.get("C_SUBTEXT", "#5F627D")
            border = p.get("C_BORDER", "#1A1A26")
            accent = p.get("C_ACCENT", "#72FF4F")
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
            is_cyan = theme in ("manhattan", "tmnt")
            hover_g = "0, 240, 255" if is_cyan else "114, 255, 79"

            b.setFixedSize(30, 30)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{subtext};"
                f"border:1px solid {border};border-radius:2px;"
                f"font-size:16px;font-weight:700;padding:0;}}"
                f"QPushButton:hover{{color:{accent};border-color:{accent};"
                f"background:rgba({hover_g},0.08);}}"
            )
        else:
            b.setFixedSize(36, 36)
            b.setFont(QFont("Segoe UI", 20, QFont.Bold))
            b.setStyleSheet(
                f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"font-size:20px;font-weight:bold;padding:0;line-height:36px;}}"
                f"QPushButton:hover{{background:{C_ACCENT};color:white;border:none;}}"
            )
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
        p = getattr(self, "_p", {})
        if self._ninja:
            N_BG = p.get("C_BG", "#07070B")
            N_CARD = p.get("C_CARD", "#14141F")
            N_ACCENT = p.get("C_ACCENT", "#72FF4F")
            N_TEXT = p.get("C_TEXT", "#E0E0FF")
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
            is_cyan = theme in ("manhattan", "tmnt")
            hover_g = "0, 240, 255" if is_cyan else "114, 255, 79"

            hf = p.get("header_font", "'Orbitron'").split(",")[0].strip("'")
            active_ss = (
                f"QPushButton{{background:{N_ACCENT};color:{N_BG};"
                f"border:none;border-radius:2px;padding:4px 10px;"
                f"font-size:11px;font-family:{hf}, 'Segoe UI';"
                f"font-weight:900;letter-spacing:1px;}}"
                f"QPushButton:hover{{background:white;color:{N_BG};}}"
            )
            normal_ss = (
                f"QPushButton{{background:{N_CARD};color:{N_ACCENT};"
                f"border:1px solid {N_ACCENT};border-radius:2px;"
                f"padding:4px 10px;font-size:11px;"
                f"font-family:{hf}, 'Segoe UI';font-weight:700;letter-spacing:1px;}}"
                f"QPushButton:hover{{background:rgba({hover_g},0.1);}}"
            )
            hints = {
                MODE_PEN: "🗡 INK JUTSU — INSCRIBE THE SCROLL",
                MODE_ERASER: "◌ VANISH — STRIKE FROM THE RECORD",
                MODE_TEXT: "巻 CIPHER — ENCODE YOUR THOUGHTS",
            }
        else:
            active_ss = (
                f"QPushButton{{background:{C_ACCENT};color:white;border:none;"
                f"border-radius:6px;padding:5px 12px;font-size:12px;}}"
                f"QPushButton:hover{{background:#6A58E0;}}"
            )
            normal_ss = (
                f"QPushButton{{background:{C_CARD};color:{C_TEXT};"
                f"border:1px solid {C_BORDER};border-radius:6px;"
                f"padding:5px 12px;font-size:12px;}}"
                f"QPushButton:hover{{background:{C_SURFACE};color:white;}}"
            )
            hints = {
                MODE_PEN: "✏ Pen — draw freehand with mouse or stylus",
                MODE_ERASER: "⬜ Eraser — drag over strokes to erase them",
                MODE_TEXT: "T Text — click canvas to place cursor, then type  •  Enter = new line  •  Esc = done",
            }
        for btn, mode in [
            (self._btn_pen, MODE_PEN),
            (self._btn_eraser, MODE_ERASER),
            (self._btn_text, MODE_TEXT),
        ]:
            style = active_ss if mode == self._mode else normal_ss
            if getattr(self, "_journal_ui_scaled", False):
                style = _scale_font_css(style)
            btn.setStyleSheet(style)
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
            d = date.fromisoformat(date_str)
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

        entry = self._journal.get(date_str, {})
        # Backward compat — old format was a plain list of strokes
        if isinstance(entry, list):
            entry = {"strokes": entry, "texts": []}

        focus_secs = entry.get("focus_seconds", 0) if isinstance(entry, dict) else 0

        # Override with live timer state if viewing today
        if date_str == date.today().isoformat():
            import session_timer
            
            # Try to query the active running timer in memory first for real-time progress
            active_seconds = None
            try:
                from PyQt5.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    seen = set()
                    for widget in app.allWidgets():
                        st = getattr(widget, "_stimer", None)
                        if st is not None and id(st) not in seen:
                            seen.add(id(st))
                            if hasattr(st, "elapsed_seconds"):
                                active_seconds = st.elapsed_seconds
                                break
            except Exception:
                pass

            if active_seconds is not None:
                focus_secs = max(focus_secs, active_seconds)
            
            state_file = getattr(session_timer, "_STATE_FILE", os.path.join(os.path.expanduser("~"), "anki_timer_state.json"))
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
        texts = _texts_from_json(entry.get("texts", []))
        self._canvas.set_content(strokes, texts)
        self._scroll.verticalScrollBar().setValue(0)

        # Update activity stats for this date
        self._update_stats(date_str, focus_secs)

        for i in range(self._sidebar.count()):
            item = self._sidebar.item(i)
            if item.data(Qt.UserRole) == date_str:
                self._sidebar.setCurrentItem(item)
                break

    def _save_current(self):
        if getattr(self, "_journal_load_error", None) is not None:
            print("[Journal] Save aborted because loading failed previously.")
            return

        self._canvas._commit_text()
        strokes = self._canvas.get_strokes()
        texts = self._canvas.get_texts()

        # Load the latest journal from disk to merge changes
        try:
            fresh_journal = _load_journal()
        except Exception as e:
            print(f"[Journal] Failed to load fresh journal, using in-memory: {e}")
            fresh_journal = self._journal

        # Retrieve/merge current date's entry
        fresh_entry = fresh_journal.get(self._current_date, {})
        if isinstance(fresh_entry, list):
            fresh_entry = {"strokes": fresh_entry, "texts": []}
        if not isinstance(fresh_entry, dict):
            fresh_entry = {"strokes": [], "texts": []}

        # Keep focus_seconds from disk if it exists or is larger
        current_entry = self._journal.get(self._current_date, {})
        if isinstance(current_entry, list):
            current_entry = {"strokes": current_entry, "texts": []}
        current_focus = current_entry.get("focus_seconds", 0) if isinstance(current_entry, dict) else 0
        fresh_focus = fresh_entry.get("focus_seconds", 0) if isinstance(fresh_entry, dict) else 0
        merged_focus = max(current_focus, fresh_focus)

        if strokes or texts:
            fresh_entry["strokes"] = _strokes_to_json(strokes)
            
            # Merge canvas texts with any background-updated focus label
            canvas_texts = _texts_to_json(texts)
            
            # Find the focus text in fresh_entry (if session_timer wrote it in the background)
            fresh_texts = fresh_entry.get("texts", [])
            if not isinstance(fresh_texts, list):
                fresh_texts = []
            
            import session_timer
            focus_tag = getattr(session_timer, "_JOURNAL_TAG", "\u23f1 Focus today:")
            fresh_focus_obj = next(
                (t for t in fresh_texts if isinstance(t, dict) and str(t.get("text", "")).startswith(focus_tag)),
                None
            )
            
            # Also check if there is a focus text in canvas_texts
            canvas_focus_idx = next(
                (i for i, t in enumerate(canvas_texts) if isinstance(t, dict) and str(t.get("text", "")).startswith(focus_tag)),
                None
            )
            
            if merged_focus > 0:
                label = f"{focus_tag} {session_timer._fmt_human(merged_focus)}"
                updated_focus_obj = {
                    "x": getattr(session_timer, "_TEXT_X", 60),
                    "y": getattr(session_timer, "_TEXT_Y", 80),
                    "text": label,
                    "color": getattr(session_timer, "_TEXT_COLOR", "#7C6AF7"),
                    "size": getattr(session_timer, "_TEXT_SIZE", 15),
                }
                # If there was a focus text in fresh_entry, preserve its styling/coordinates
                if fresh_focus_obj:
                    updated_focus_obj["x"] = fresh_focus_obj.get("x", updated_focus_obj["x"])
                    updated_focus_obj["y"] = fresh_focus_obj.get("y", updated_focus_obj["y"])
                    updated_focus_obj["color"] = fresh_focus_obj.get("color", updated_focus_obj["color"])
                    updated_focus_obj["size"] = fresh_focus_obj.get("size", updated_focus_obj["size"])
                elif canvas_focus_idx is not None:
                    c_obj = canvas_texts[canvas_focus_idx]
                    updated_focus_obj["x"] = c_obj.get("x", updated_focus_obj["x"])
                    updated_focus_obj["y"] = c_obj.get("y", updated_focus_obj["y"])
                    updated_focus_obj["color"] = c_obj.get("color", updated_focus_obj["color"])
                    updated_focus_obj["size"] = c_obj.get("size", updated_focus_obj["size"])

                if canvas_focus_idx is not None:
                    canvas_texts[canvas_focus_idx] = updated_focus_obj
                else:
                    canvas_texts.insert(0, updated_focus_obj)
            else:
                if canvas_focus_idx is not None:
                    canvas_texts.pop(canvas_focus_idx)
            
            fresh_entry["texts"] = canvas_texts
            if merged_focus > 0:
                fresh_entry["focus_seconds"] = merged_focus
            else:
                fresh_entry.pop("focus_seconds", None)
            
            fresh_journal[self._current_date] = fresh_entry
        else:
            if merged_focus > 0:
                fresh_entry["strokes"] = []
                
                # Ensure the focus text is retained in texts even with empty canvas
                fresh_texts = fresh_entry.get("texts", [])
                if not isinstance(fresh_texts, list):
                    fresh_texts = []
                
                import session_timer
                focus_tag = getattr(session_timer, "_JOURNAL_TAG", "\u23f1 Focus today:")
                fresh_focus_obj = next(
                    (t for t in fresh_texts if isinstance(t, dict) and str(t.get("text", "")).startswith(focus_tag)),
                    None
                )
                if not fresh_focus_obj:
                    label = f"{focus_tag} {session_timer._fmt_human(merged_focus)}"
                    fresh_focus_obj = {
                        "x": getattr(session_timer, "_TEXT_X", 60),
                        "y": getattr(session_timer, "_TEXT_Y", 80),
                        "text": label,
                        "color": getattr(session_timer, "_TEXT_COLOR", "#7C6AF7"),
                        "size": getattr(session_timer, "_TEXT_SIZE", 15),
                    }
                fresh_entry["texts"] = [fresh_focus_obj]
                fresh_entry["focus_seconds"] = merged_focus
                fresh_journal[self._current_date] = fresh_entry
            else:
                fresh_journal.pop(self._current_date, None)

        self._journal = fresh_journal

        try:
            _save_journal(self._journal)
        except Exception as e:
            print(f"[Journal] Save error: {e}")
        self._refresh_sidebar()

    def _refresh_sidebar(self):
        sel = self._current_date
        self._sidebar.clear()
        dates = sorted(self._journal.keys(), reverse=True)
        today_str = date.today().isoformat()
        if today_str not in dates:
            dates = [today_str] + dates
        for d_str in dates:
            try:
                d = date.fromisoformat(d_str)
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

    # ── Daily Activity Stats ──────────────────────────────────────────────────

    def _get_activity_stats(self, date_str):
        from services.activity_stats import get_daily_activity_stats
        return get_daily_activity_stats(date_str)

    def _build_stats_panel(self):
        from PyQt5.QtWidgets import QScrollArea, QProgressBar
        
        panel = QFrame()
        panel.setObjectName("stats_panel")
        panel.setMinimumWidth(_journal_font_size(260))
        
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(10)
        
        # Header
        self._stats_title = QLabel("⛩ MISSION REPORT" if self._ninja else "📊 Daily Stats")
        self._stats_title.setObjectName("stats_header")
        self._stats_title.setFont(QFont(self._p["header_font"], 12, QFont.Bold))
        self._stats_title.setAlignment(Qt.AlignCenter)
        pl.addWidget(self._stats_title)
        
        # Divider line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{self._p['C_BORDER']}; border:none;")
        sep.setFixedHeight(1)
        pl.addWidget(sep)
        
        # Scroll Area for stats details
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        
        scroll_content = QWidget()
        self._stats_scroll_content = scroll_content
        scroll_content.setStyleSheet("background:transparent;")
        scl = QVBoxLayout(scroll_content)
        scl.setContentsMargins(0, 0, 0, 0)
        scl.setSpacing(14)
        
        # 1. No Activity Label
        self._lbl_no_activity = QLabel("No study activity recorded\nfor this day.")
        self._lbl_no_activity.setAlignment(Qt.AlignCenter)
        self._lbl_no_activity.setStyleSheet(f"color:{self._p['C_SUBTEXT']}; font-size:12px; padding: 40px 10px;")
        scl.addWidget(self._lbl_no_activity)
        
        # 2. Main Stats Widget (container for stats when there IS activity)
        self._stats_container = QWidget()
        self._stats_container.setStyleSheet("background:transparent;")
        scl_container = QVBoxLayout(self._stats_container)
        scl_container.setContentsMargins(0, 0, 0, 0)
        scl_container.setSpacing(14)
        
        # Metrics Cards (Grid or vertical stack of small cards)
        # Card 1: Time spent
        card_time = QFrame()
        card_time.setObjectName("stats_card")
        card_time.setStyleSheet(f"QFrame#stats_card {{ background:{self._p['C_CARD']}; border:1px solid {self._p['C_BORDER']}; border-radius:6px; }}")
        ctl = QVBoxLayout(card_time)
        ctl.setContentsMargins(8, 8, 8, 8)
        ctl.setSpacing(2)
        lbl_time_hdr = QLabel("FOCUS TIME" if self._ninja else "Focus Time")
        lbl_time_hdr.setObjectName("stats_label")
        self._lbl_focus_val = QLabel("0s")
        self._lbl_focus_val.setObjectName("stats_num")
        self._lbl_focus_val.setAlignment(Qt.AlignCenter)
        ctl.addWidget(lbl_time_hdr, 0, Qt.AlignCenter)
        ctl.addWidget(self._lbl_focus_val)
        scl_container.addWidget(card_time)
        
        # Card 2: Cards Studied
        card_cards = QFrame()
        card_cards.setObjectName("stats_card")
        card_cards.setStyleSheet(f"QFrame#stats_card {{ background:{self._p['C_CARD']}; border:1px solid {self._p['C_BORDER']}; border-radius:6px; }}")
        ccl = QVBoxLayout(card_cards)
        ccl.setContentsMargins(8, 8, 8, 8)
        ccl.setSpacing(2)
        lbl_cards_hdr = QLabel("CARDS REVIEWED" if self._ninja else "Cards Reviewed")
        lbl_cards_hdr.setObjectName("stats_label")
        self._lbl_cards_val = QLabel("0")
        self._lbl_cards_val.setObjectName("stats_num")
        self._lbl_cards_val.setAlignment(Qt.AlignCenter)
        ccl.addWidget(lbl_cards_hdr, 0, Qt.AlignCenter)
        ccl.addWidget(self._lbl_cards_val)
        scl_container.addWidget(card_cards)
        
        # Card 3: Success Rate
        card_succ = QFrame()
        card_succ.setObjectName("stats_card")
        card_succ.setStyleSheet(f"QFrame#stats_card {{ background:{self._p['C_CARD']}; border:1px solid {self._p['C_BORDER']}; border-radius:6px; }}")
        csl = QVBoxLayout(card_succ)
        csl.setContentsMargins(8, 8, 8, 8)
        csl.setSpacing(2)
        lbl_succ_hdr = QLabel("RETENTION" if self._ninja else "Retention")
        lbl_succ_hdr.setObjectName("stats_label")
        self._lbl_succ_val = QLabel("0%")
        self._lbl_succ_val.setObjectName("stats_num")
        self._lbl_succ_val.setAlignment(Qt.AlignCenter)
        csl.addWidget(lbl_succ_hdr, 0, Qt.AlignCenter)
        csl.addWidget(self._lbl_succ_val)
        scl_container.addWidget(card_succ)
        
        # Rating Breakdown bars
        breakdown_box = QFrame()
        breakdown_box.setObjectName("stats_card")
        breakdown_box.setStyleSheet(f"QFrame#stats_card {{ background:{self._p['C_CARD']}; border:1px solid {self._p['C_BORDER']}; border-radius:6px; }}")
        bvl = QVBoxLayout(breakdown_box)
        bvl.setContentsMargins(10, 10, 10, 10)
        bvl.setSpacing(6)
        
        lbl_b_hdr = QLabel("BREAKDOWN" if self._ninja else "Rating Breakdown")
        lbl_b_hdr.setObjectName("stats_label")
        bvl.addWidget(lbl_b_hdr)
        
        hf = self._p.get("header_font", "").split(",")[0].strip("'")
        is_ps = (hf == "Press Start 2P")
        deck_font_size = 11 if is_ps else 14

        self._bars = {}
        for rating_name, rating_color in [
            ("again", self._p["C_RED"]),
            ("hard", self._p["C_ORANGE"]),
            ("good", self._p["C_GREEN"]),
            ("easy", self._p["C_YELLOW"]),
            ("perfect", self._p["C_PURPLE"]),
        ]:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 2, 0, 2)
            row_l.setSpacing(6)
            
            lbl_name = QLabel(rating_name.upper() if self._ninja else rating_name.capitalize())
            lbl_name.setStyleSheet(f"color:{self._p['C_TEXT']}; font-size:{deck_font_size}px;")
            
            lbl_val = QLabel("0")
            lbl_val.setStyleSheet(f"color:{rating_color}; font-size:{deck_font_size}px; font-weight:bold;")
            lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            row_l.addWidget(lbl_name, 1)
            row_l.addWidget(lbl_val)
            
            bar = QProgressBar()
            bar.setFixedHeight(5)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"""
                QProgressBar {{ background:{self._p['C_BORDER']}; border:none; border-radius:2px; }}
                QProgressBar::chunk {{ background:{rating_color}; border-radius:2px; }}
            """)
            
            bvl.addWidget(row)
            bvl.addWidget(bar)
            self._bars[rating_name] = (bar, lbl_val)
            
        scl_container.addWidget(breakdown_box)
        
        # Decks Covered box
        decks_box = QFrame()
        decks_box.setObjectName("stats_card")
        decks_box.setStyleSheet(f"QFrame#stats_card {{ background:{self._p['C_CARD']}; border:1px solid {self._p['C_BORDER']}; border-radius:6px; }}")
        dvl = QVBoxLayout(decks_box)
        dvl.setContentsMargins(10, 10, 10, 10)
        dvl.setSpacing(6)
        
        self._lbl_decks_hdr = QLabel("DECKS COVERED" if self._ninja else "Decks Covered")
        self._lbl_decks_hdr.setObjectName("stats_label")
        dvl.addWidget(self._lbl_decks_hdr)
        
        # List of decks
        self._decks_list_layout = QVBoxLayout()
        self._decks_list_layout.setContentsMargins(0, 0, 0, 0)
        self._decks_list_layout.setSpacing(4)
        dvl.addLayout(self._decks_list_layout)
        
        scl_container.addWidget(decks_box)

        # Button to open full dedicated Mission Report Card
        self._btn_open_report_card = QPushButton("📋 Full Report Card" if self._ninja else "📋 Full Report Card")
        self._btn_open_report_card.setCursor(Qt.PointingHandCursor)
        self._btn_open_report_card.setFixedHeight(30)
        c_acc = self._p.get("C_ACCENT", "#72FF4F")
        c_card_bg = self._p.get("C_CARD", "#14141F")
        self._btn_open_report_card.setStyleSheet(f"""
            QPushButton {{
                background: {c_card_bg};
                color: {c_acc};
                border: 1px solid {c_acc};
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: rgba(114, 255, 79, 0.12);
            }}
        """)
        self._btn_open_report_card.clicked.connect(self._open_full_report)
        scl_container.addWidget(self._btn_open_report_card)
        
        # Add to scroll area layout
        scl.addWidget(self._stats_container)
        scroll.setWidget(scroll_content)
        pl.addWidget(scroll, stretch=1)
        
        return panel

    def _update_stats(self, date_str, focus_secs):
        stats = self._get_activity_stats(date_str)
        
        has_activity = (stats["total"] > 0) or (focus_secs > 0)
        
        if not has_activity:
            self._lbl_no_activity.show()
            self._stats_container.hide()
            return
            
        self._lbl_no_activity.hide()
        self._stats_container.show()
        
        # 1. Update Focus Time
        h, rem = divmod(focus_secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            time_str = f"{h}h {m}m"
        elif m:
            time_str = f"{m}m"
        else:
            time_str = f"{s}s"
        self._lbl_focus_val.setText(time_str)
        
        # 2. Update Total Reviews
        self._lbl_cards_val.setText(str(stats["total"]))
        
        # 3. Update Success Rate (Retention)
        correct = stats["good"] + stats["easy"] + stats["perfect"]
        total_rated = stats["again"] + stats["hard"] + stats["good"] + stats["easy"] + stats["perfect"]
        retention = round(correct / total_rated * 100) if total_rated > 0 else 0
        self._lbl_succ_val.setText(f"{retention}%")
        
        # Color accuracy label based on percentage
        green = self._p.get("C_GREEN", "#50FA7B")
        yellow = self._p.get("C_YELLOW", "#F1FA8C")
        red = self._p.get("C_RED", "#FF5555")
        ret_color = green if retention >= 80 else yellow if retention >= 60 else red
        self._lbl_succ_val.setStyleSheet(f"color: {ret_color};")
        
        # 4. Update breakdown progress bars
        total_rated = stats["again"] + stats["hard"] + stats["good"] + stats["easy"] + stats["perfect"]
        for rating_name in ["again", "hard", "good", "easy", "perfect"]:
            count = stats[rating_name]
            bar, lbl_val = self._bars[rating_name]
            bar.setRange(0, total_rated if total_rated > 0 else 1)
            bar.setValue(count)
            pct = round(count / total_rated * 100) if total_rated > 0 else 0
            lbl_val.setText(f"{count} ({pct}%)")
            
        # 5. Clear and rebuild decks covered list (Hierarchical Tree)
        tree_nodes = stats.get("tree", [])
        total_deck_reviews = sum(node["total_reviews"] for node in tree_nodes)
        num_topics = len(tree_nodes)
        if num_topics > 0:
            if self._ninja:
                hdr_text = f"DECKS COVERED ({num_topics} TOPICS, {total_deck_reviews} REVIEWS)"
            else:
                hdr_text = f"Decks Covered ({num_topics} topics, {total_deck_reviews} reviews)"
        else:
            hdr_text = "DECKS COVERED" if self._ninja else "Decks Covered"
        self._lbl_decks_hdr.setText(hdr_text)

        while self._decks_list_layout.count():
            item = self._decks_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        hf = self._p.get("header_font", "").split(",")[0].strip("'")
        is_ps = (hf == "Press Start 2P")
        deck_font_size = 10 if is_ps else 12

        if not tree_nodes:
            lbl_none = QLabel("No decks studied.")
            lbl_none.setStyleSheet(f"color:{self._p['C_SUBTEXT']}; font-size:{deck_font_size}px; font-style:italic;")
            self._decks_list_layout.addWidget(lbl_none)
        else:
            def _create_node_widget(node_data, depth=0):
                container = QWidget()
                container.setStyleSheet("background:transparent;")
                clayout = QVBoxLayout(container)
                clayout.setContentsMargins(0, 0, 0, 0)
                clayout.setSpacing(2)

                row = QWidget()
                row.setStyleSheet("background:transparent;")
                row_l = QHBoxLayout(row)
                row_l.setContentsMargins(depth * 12, 1, 0, 1)
                row_l.setSpacing(4)

                has_children = bool(node_data.get("children"))

                if has_children:
                    btn_toggle = QPushButton("▶")
                    btn_toggle.setFixedSize(16, 16)
                    btn_toggle.setCursor(Qt.PointingHandCursor)
                    btn_toggle.setStyleSheet(f"QPushButton {{ background:transparent; color:{self._p['C_ACCENT']}; border:none; font-size:9px; font-weight:bold; }}")
                    row_l.addWidget(btn_toggle)
                else:
                    lbl_bullet = QLabel("•")
                    lbl_bullet.setFixedWidth(16)
                    lbl_bullet.setStyleSheet(f"color:{self._p['C_SUBTEXT']}; font-size:11px;")
                    row_l.addWidget(lbl_bullet)

                display_name = node_data["name"]
                lbl_deck = QLabel(display_name)
                lbl_deck.setToolTip(node_data.get("full_path", display_name))
                name_weight = "bold" if has_children else "normal"
                name_color = self._p['C_TEXT'] if has_children else self._p.get('C_TEXT', '#DDD')
                lbl_deck.setStyleSheet(f"color:{name_color}; font-size:{deck_font_size}px; font-weight:{name_weight};")

                revs = node_data["total_reviews"]
                lbl_count = QLabel(f"{revs} rev(s)")
                badge_color = self._p['C_ACCENT'] if has_children else self._p.get('C_PURPLE', '#BD93F9')
                lbl_count.setStyleSheet(f"color:{badge_color}; font-size:{deck_font_size}px; font-weight:bold;")
                lbl_count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                row_l.addWidget(lbl_deck, 1)
                row_l.addWidget(lbl_count)
                clayout.addWidget(row)

                if has_children:
                    child_box = QWidget()
                    child_box.setStyleSheet("background:transparent;")
                    child_l = QVBoxLayout(child_box)
                    child_l.setContentsMargins(0, 0, 0, 0)
                    child_l.setSpacing(2)
                    for child in node_data["children"]:
                        child_l.addWidget(_create_node_widget(child, depth + 1))
                    child_box.hide()
                    clayout.addWidget(child_box)

                    def _toggle_child(checked=False, cbox=child_box, btn=btn_toggle):
                        if cbox.isVisible():
                            cbox.hide()
                            btn.setText("▶")
                        else:
                            cbox.show()
                            btn.setText("▼")

                    btn_toggle.clicked.connect(_toggle_child)

                return container

            for top_node in tree_nodes:
                self._decks_list_layout.addWidget(_create_node_widget(top_node, depth=0))

        # Force layout update to compute the new minimum size hint
        if hasattr(self, "_stats_scroll_content") and self._stats_scroll_content.layout():
            self._stats_scroll_content.layout().invalidate()
            self._stats_scroll_content.layout().activate()
            content_w = self._stats_scroll_content.layout().minimumSize().width()
        else:
            content_w = 0
            
        # Calculate new required width based on scroll content + margins + scrollbar buffer
        req_w = content_w + _journal_font_size(12 * 2 + 20)
        base_w = _journal_font_size(260)
        final_w = max(base_w, req_w)
        
        # Only constrain minimum width and resize splitter if dialog is fully visible and fonts are resolved
        if self.isVisible():
            self._stats_panel.setMinimumWidth(final_w)
            
            # Update splitter sizes to accommodate the new minimum width
            if hasattr(self, "_splitter") and self._stats_visible:
                sizes = self._splitter.sizes()
                if len(sizes) == 3 and sum(sizes) > 0:
                    if sizes[2] < final_w:
                        diff = final_w - sizes[2]
                        sizes[1] = max(100, sizes[1] - diff)
                        sizes[2] = final_w
                        self._splitter.setSizes(sizes)
        else:
            self._stats_panel.setMinimumWidth(base_w)

    def _open_full_report(self):
        home = None
        w = self
        while w:
            if hasattr(w, "_show_mission_report"):
                home = w
                break
            w = w.parent()

        target_date = getattr(self, "_current_date", None)
        if home is not None:
            self._on_close()
            home._show_mission_report(date_str=target_date)
        else:
            from ui.mission_report_dialog import MissionReportDialog
            rw = MissionReportDialog(initial_date=target_date)
            rw.setWindowFlags(Qt.Window)
            rw.showMaximized()

    # ── Tools ─────────────────────────────────────────────────────────────────

    def _cycle_color(self):
        c = self._canvas.cycle_color()
        if self._ninja:
            self._dot.setStyleSheet(
                f"background:{c};border-radius:9px;border:1.5px solid {N_BORDER};"
            )
        else:
            self._dot.setStyleSheet(
                f"background:{c};border-radius:11px;border:2px solid {C_BORDER};"
            )

    def _clear(self):
        if (
            QMessageBox.question(
                self,
                "Clear Page",
                "Clear everything on this page?",
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        ):
            self._canvas.clear()

    def _export(self):
        self._canvas._commit_text()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export as PNG",
            f"journal_{self._current_date}.png",
            "PNG Images (*.png)",
        )
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
        mods = e.modifiers()
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        is_ctrl_question = (
            (clean_mods & Qt.ControlModifier) and
            not (clean_mods & Qt.AltModifier) and
            not (clean_mods & Qt.MetaModifier) and
            (key == Qt.Key_Question or (key == Qt.Key_Slash and (clean_mods & Qt.ShiftModifier)))
        )
        if is_ctrl_question:
            from ui.shortcut_dialog import ShortcutSettingsDialog
            dlg = ShortcutSettingsDialog(self)
            dlg.exec_()
            e.accept()
            return

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
        self.closed.emit()
        self.accept()

    def reject(self):
        self._save_current()
        self.closed.emit()
        super().reject()

    def closeEvent(self, e):
        self._save_current()
        super().closeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        # Reload current date now that window is shown and fonts are resolved,
        # forcing correct QSplitter sizing.
        self._load_date(self._current_date)

    def _toggle_stats(self):
        self._stats_visible = self._btn_toggle_stats.isChecked()
        self._stats_panel.setVisible(self._stats_visible)
        if self._stats_visible and hasattr(self, "_splitter"):
            # Force layout update to compute the new minimum size hint
            if hasattr(self, "_stats_scroll_content") and self._stats_scroll_content.layout():
                self._stats_scroll_content.layout().invalidate()
                self._stats_scroll_content.layout().activate()
                content_w = self._stats_scroll_content.layout().minimumSize().width()
            else:
                content_w = 0
            
            req_w = content_w + _journal_font_size(12 * 2 + 20)
            base_w = _journal_font_size(260)
            final_w = max(base_w, req_w)
            
            self._stats_panel.setMinimumWidth(final_w)
            
            sizes = self._splitter.sizes()
            if len(sizes) == 3 and sum(sizes) > 0:
                if sizes[2] < final_w:
                    diff = final_w - sizes[2]
                    sizes[1] = max(100, sizes[1] - diff)
                    sizes[2] = final_w
                    self._splitter.setSizes(sizes)
