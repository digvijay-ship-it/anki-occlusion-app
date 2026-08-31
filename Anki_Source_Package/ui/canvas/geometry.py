import math

def _point_in_rotated_box(px, py, cx, cy, w, h, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    return abs(lx) <= w / 2 and abs(ly) <= h / 2


def _point_in_rotated_ellipse(px, py, cx, cy, rx, ry, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    if rx < 1 or ry < 1:
        return False
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1


def smooth_points_to_path(pts, scale=1.0, offset=None):
    """Build a smoothed QPainterPath through `pts` using midpoint quad-Béziers.

    This is the single source of truth for pen-stroke smoothing across the
    app (review, annotation, math scratchpad). `pts` is an iterable of
    QPointF-like objects (anything with `.x()` / `.y()`). `scale` multiplies
    both axes. `offset`, if given, is a QPointF added to every point after
    scaling (used by the annotation canvas which offsets strokes by the
    page's top y). Returns a QPainterPath.
    """
    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import QPainterPath

    path = QPainterPath()
    pts = list(pts)
    if not pts:
        return path

    def _transform(pt):
        x = pt.x() * scale
        y = pt.y() * scale
        if offset is not None:
            x += offset.x()
            y += offset.y()
        return QPointF(x, y)

    spts = [_transform(pt) for pt in pts]

    path.moveTo(spts[0])
    if len(spts) == 1:
        return path
    if len(spts) == 2:
        path.lineTo(spts[1])
        return path

    p0 = spts[0]
    p1 = spts[1]
    first_mid = QPointF((p0.x() + p1.x()) / 2.0, (p0.y() + p1.y()) / 2.0)
    path.lineTo(first_mid)

    for i in range(1, len(spts) - 1):
        curr = spts[i]
        nxt = spts[i + 1]
        mid = QPointF((curr.x() + nxt.x()) / 2.0, (curr.y() + nxt.y()) / 2.0)
        path.quadTo(curr, mid)

    path.lineTo(spts[-1])
    return path
