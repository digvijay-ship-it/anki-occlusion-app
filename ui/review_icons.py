"""
Review Screen — Programmatic Icon Generator
=============================================
Generates crisp vector icons via QPainter → QPixmap → QIcon.
No external SVG/PNG files needed. DPI-independent.
"""

from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap, QIcon, QFont, QPainterPath
from PyQt5.QtCore import Qt, QRect, QRectF, QPointF


def _make_pixmap(size: int, fg: str, draw_fn) -> QPixmap:
    """Create a transparent QPixmap and draw on it."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    pen = QPen(QColor(fg))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    draw_fn(p, size, QColor(fg))
    p.end()
    return pm


def make_icon(size: int, fg: str, draw_fn) -> QIcon:
    return QIcon(_make_pixmap(size, fg, draw_fn))


# ── Individual icon draw functions ─────────────────────────────────────────────

def _draw_zoom_in(p: QPainter, s: int, fg: QColor):
    """Magnifying glass with +"""
    pen = p.pen()
    pen.setWidthF(s * 0.09)
    p.setPen(pen)
    cx, cy, r = s * 0.40, s * 0.40, s * 0.26
    p.drawEllipse(QPointF(cx, cy), r, r)
    # handle
    hx = cx + r * 0.707
    hy = cy + r * 0.707
    p.drawLine(QPointF(hx, hy), QPointF(s * 0.82, s * 0.82))
    # plus
    pen2 = QPen(fg)
    pen2.setWidthF(s * 0.08)
    pen2.setCapStyle(Qt.RoundCap)
    p.setPen(pen2)
    p.drawLine(QPointF(cx - r * 0.5, cy), QPointF(cx + r * 0.5, cy))
    p.drawLine(QPointF(cx, cy - r * 0.5), QPointF(cx, cy + r * 0.5))


def _draw_zoom_out(p: QPainter, s: int, fg: QColor):
    """Magnifying glass with −"""
    pen = p.pen()
    pen.setWidthF(s * 0.09)
    p.setPen(pen)
    cx, cy, r = s * 0.40, s * 0.40, s * 0.26
    p.drawEllipse(QPointF(cx, cy), r, r)
    hx = cx + r * 0.707
    hy = cy + r * 0.707
    p.drawLine(QPointF(hx, hy), QPointF(s * 0.82, s * 0.82))
    pen2 = QPen(fg)
    pen2.setWidthF(s * 0.08)
    pen2.setCapStyle(Qt.RoundCap)
    p.setPen(pen2)
    p.drawLine(QPointF(cx - r * 0.5, cy), QPointF(cx + r * 0.5, cy))


def _draw_zoom_fit(p: QPainter, s: int, fg: QColor):
    """Expand-to-fit arrows (four corners)"""
    pen = p.pen()
    pen.setWidthF(s * 0.08)
    p.setPen(pen)
    m = s * 0.2  # margin
    e = s * 0.8
    L = s * 0.2  # arm length
    # top-left corner
    p.drawLine(QPointF(m, m + L), QPointF(m, m))
    p.drawLine(QPointF(m, m), QPointF(m + L, m))
    # top-right corner
    p.drawLine(QPointF(e - L, m), QPointF(e, m))
    p.drawLine(QPointF(e, m), QPointF(e, m + L))
    # bottom-left corner
    p.drawLine(QPointF(m, e - L), QPointF(m, e))
    p.drawLine(QPointF(m, e), QPointF(m + L, e))
    # bottom-right corner
    p.drawLine(QPointF(e - L, e), QPointF(e, e))
    p.drawLine(QPointF(e, e), QPointF(e, e - L))


def _draw_crosshair(p: QPainter, s: int, fg: QColor):
    """Crosshair / target (center on active mask)"""
    pen = p.pen()
    pen.setWidthF(s * 0.07)
    p.setPen(pen)
    cx, cy = s * 0.5, s * 0.5
    r_outer = s * 0.32
    r_inner = s * 0.16
    p.drawEllipse(QPointF(cx, cy), r_outer, r_outer)
    p.drawEllipse(QPointF(cx, cy), r_inner, r_inner)
    # crosshair lines (outside outer circle)
    gap = s * 0.04
    arm = s * 0.14
    p.drawLine(QPointF(cx, cy - r_outer - gap), QPointF(cx, cy - r_outer - gap - arm))
    p.drawLine(QPointF(cx, cy + r_outer + gap), QPointF(cx, cy + r_outer + gap + arm))
    p.drawLine(QPointF(cx - r_outer - gap, cy), QPointF(cx - r_outer - gap - arm, cy))
    p.drawLine(QPointF(cx + r_outer + gap, cy), QPointF(cx + r_outer + gap + arm, cy))


def _draw_chevron_left(p: QPainter, s: int, fg: QColor):
    """Bold chevron left (previous page)"""
    pen = p.pen()
    pen.setWidthF(s * 0.12)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(s * 0.62, s * 0.20)
    path.lineTo(s * 0.32, s * 0.50)
    path.lineTo(s * 0.62, s * 0.80)
    p.drawPath(path)


def _draw_chevron_right(p: QPainter, s: int, fg: QColor):
    """Bold chevron right (next page)"""
    pen = p.pen()
    pen.setWidthF(s * 0.12)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(s * 0.38, s * 0.20)
    path.lineTo(s * 0.68, s * 0.50)
    path.lineTo(s * 0.38, s * 0.80)
    p.drawPath(path)


def _draw_contrast(p: QPainter, s: int, fg: QColor):
    """Half-circle contrast icon (invert PDF)"""
    pen = p.pen()
    pen.setWidthF(s * 0.07)
    p.setPen(pen)
    cx, cy, r = s * 0.5, s * 0.5, s * 0.32
    # full circle outline
    p.drawEllipse(QPointF(cx, cy), r, r)
    # fill left half
    p.setBrush(fg)
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.arcTo(QRectF(cx - r, cy - r, r * 2, r * 2), 90, 180)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.drawPath(path)


# ── Convenience builders ───────────────────────────────────────────────────────

def icon_zoom_in(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_zoom_in)


def icon_zoom_out(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_zoom_out)


def icon_zoom_fit(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_zoom_fit)


def icon_crosshair(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_crosshair)


def icon_chevron_left(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_chevron_left)


def icon_chevron_right(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_chevron_right)


def icon_contrast(size: int = 24, fg: str = "#CDD6F4") -> QIcon:
    return make_icon(size, fg, _draw_contrast)
