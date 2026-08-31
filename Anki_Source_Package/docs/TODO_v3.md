# TODO_v3.md

Unify the three drawing pens so they all feel like the review-mode pen
(currently the smoothest). Same rules as `docs/DESKTOP_PERF_TODO.md`,
`docs/TODO_v2.md`, `docs/TODO_v2_followup.md`. Read those files' "How to use"
sections first if you haven't.

## How to use this file

- Do **one task at a time**, in order (T1 → T2). T2 depends on T1.
- Each task is self-contained: exact files + line numbers, current behavior,
  desired behavior, acceptance test.
- **Do not refactor beyond the task's stated scope.** No renaming, no
  reformatting, no "while I'm here" edits. Match surrounding code style.
- After every task, run its acceptance test. If it fails, fix your change —
  do not move on.
- Preserve all existing `print("[DEBUG]...")` lines unless a task says to
  remove them.
- Line numbers are anchored to the code at the time of this report. If a line
  has drifted, find the target by the surrounding code / symbol names.
- Python: `C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe`
- **Baseline before you start:** `Ran 426 tests, OK (0 errors)`.

## Background — why these tasks exist

The app has three independent "pen" implementations that have drifted apart:

| Pen | File | Input | Smoothing |
|-----|------|-------|-----------|
| Review (smoothest) | `ui/canvas/renderer.py` `_smooth_points_to_path` | Real `tabletEvent` (pen pressure) | Midpoint quad-Bézier, **both** endpoints `lineTo`-anchored |
| Annotation | `ui/pdf_annotation_dialog.py` `_draw_points` | `mouseMoveEvent` only | Midpoint quad-Bézier, **start** `moveTo`-anchored (different lead-in) |
| Math scratchpad | `ui/math_trainer.py` `MathScratchpad` | `mouseMoveEvent` only | **None** — raw `drawLine(p0, p1)` |

Goal: extract ONE shared smoothing helper, make all three use it, so the
output is visually identical and can never drift again. **Review's math is
the reference** — do not change what review produces.

---

## T1 — Extract `smooth_points_to_path` into `ui/canvas/geometry.py` and adopt it everywhere  ✅ MECH

**Problem.** The midpoint-quad-Bézier smoothing exists in two places and is
written slightly differently; the math scratchpad has none. Three divergent
"pens".

**Reference implementation (review — keep its output byte-identical):**
`ui/canvas/renderer.py:404-431` `_smooth_points_to_path(self, pts, sc)`.

**Task.**

### 1. Add the shared helper

In `ui/canvas/geometry.py`, add a new module-level function (place it after
the existing `_point_in_rotated_ellipse` helper, match the file's style):

```python
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
```

This is review's exact math, generalised to accept an optional `offset`
(which the annotation canvas needs) and a default `scale=1.0` (math
scratchpad renders in widget space, no scaling). **Verify:** with
`offset=None`, the output must equal review's current `_smooth_points_to_path`
for identical `pts` + `sc`.

### 2. Adopt in `ui/canvas/renderer.py`

Replace the body of `_smooth_points_to_path` (lines ~404-431) to delegate to
the shared helper. Keep the method (callers still use `self._smooth_points_to_path`),
keep its signature `(self, pts, sc)`, and keep any docstring/comment style:

```python
def _smooth_points_to_path(self, pts, sc) -> QPainterPath:
    from .geometry import smooth_points_to_path
    return smooth_points_to_path(pts, scale=sc)
```

**Do not** change `_draw_ink_layer` or the `_ink_path_cache` logic — only the
helper body changes. Review's rendered output must be identical.

### 3. Adopt in `ui/pdf_annotation_dialog.py` `_draw_points` (lines ~391-437)

Rewrite the path-construction portion of `_draw_points` to use the shared
helper with the page-top offset. The pen/color/width/opacity/cap/join
setup at the bottom of the method stays exactly as-is.

Current (lines ~407-421) — delete this block:
```python
path = QPainterPath()
path.moveTo(pts[0].x() * self._scale, top + pts[0].y() * self._scale)
for idx in range(1, len(pts) - 1):
    mid = QPointF(
        (pts[idx].x() + pts[idx + 1].x()) / 2.0,
        (pts[idx].y() + pts[idx + 1].y()) / 2.0,
    )
    path.quadTo(
        pts[idx].x() * self._scale,
        top + pts[idx].y() * self._scale,
        mid.x() * self._scale,
        mid.y() * self._scale,
    )
last = pts[-1]
path.lineTo(last.x() * self._scale, top + last.y() * self._scale)
```

Replace with:
```python
from ui.canvas.geometry import smooth_points_to_path
path = smooth_points_to_path(
    pts,
    scale=self._scale,
    offset=QPointF(0.0, top),
)
```

`QPointF` is already imported in this file (verify at the top; if not, add
`QPointF` to the `PyQt5.QtCore` import — it is used elsewhere in the file).
Keep everything below (`pen_color`, `painter.save()`, pen setup, `drawPath`,
`painter.restore()`) unchanged.

**Result:** annotation strokes now start with the same `lineTo(first_mid)`
lead-in as review. Visually, the very start of each stroke settles cleanly
instead of hooking.

### 4. Adopt in `ui/math_trainer.py` `MathScratchpad`

This is the biggest perceptual win. Currently the scratchpad has **no**
smoothing — `_draw_segment_to_backing_store` (lines ~112-127) does a raw
`p.drawLine(p0, p1)` per segment into the backing-store `QImage`.

**Important constraint:** the OCR path (`_trigger_ocr`, lines ~183-195) must
NOT change. It builds a PIL image with `draw.line(..., joint="curve")` for the
digit-recognition model. Leave `_trigger_ocr` exactly as-is — smoothing is a
visual-only change.

Change only the visual render:

In `_draw_segment_to_backing_store`, replace the per-segment `drawLine` with a
full-stroke smoothed path. The cleanest approach that preserves the
incremental backing-store model:

- Add a new method `_redraw_stroke_to_backing_store(self, stroke)` that draws
  the ENTIRE current stroke as one smoothed path (using
  `smooth_points_to_path`) into the backing store, replacing the per-segment
  approach.
- In `mouseMoveEvent` (lines ~154-170), when a new point arrives, instead of
  calling `_draw_segment_to_backing_store(p0, p1)`, clear the backing store's
  "live stroke" region and call `_redraw_stroke_to_backing_store(self._current)`.

Concretely (sketch — adapt to the surrounding code):

```python
def _redraw_stroke_to_backing_store(self, stroke):
    if self._backing_store is None or self._backing_store.isNull():
        self._init_backing_store()
    if len(stroke) < 2:
        return
    # Erase the previous version of this live stroke and re-render smoothed.
    # (Simplest correct approach: keep a second QImage of the "committed"
    # strokes and composite live stroke on top each move. If that's too big a
    # change for this task's scope, fall back to redrawing into the existing
    # backing store — the smoothing will still look better than drawLine even
    # without perfect erase semantics.)
    from ui.canvas.geometry import smooth_points_to_path
    p = QPainter(self._backing_store)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(self._pen_color, self._pen_width, Qt.SolidLine,
                  Qt.RoundCap, Qt.RoundJoin))
    path = smooth_points_to_path(stroke, scale=1.0)
    p.drawPath(path)
    p.end()
```

**If** the erase-and-redraw approach risks ghosting (drawing the smoothed
path on top of the previous unsmoothed segments without erasing), the
acceptable simpler fallback is: keep the per-segment backing-store approach
for the live stroke, BUT change the final committed render (on
`mouseReleaseEvent`, lines ~172-181) to redraw the completed stroke through
`smooth_points_to_path`. Pick whichever is smaller and doesn't ghost; the
key acceptance criterion is that a completed stroke shows a smooth Bézier,
not raw line facets.

Do **not** change `_pen_width` (4.5), `_pen_color`, the idle timer, the OCR
trigger, or `get_pil_image()`.

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `Ran 426+ tests, OK` with 0 errors.
By inspection:
- `ui/canvas/geometry.py` defines `smooth_points_to_path`.
- `ui/canvas/renderer.py` `_smooth_points_to_path` delegates to it.
- `ui/pdf_annotation_dialog.py` `_draw_points` calls it with the page-top offset.
- `ui/math_trainer.py` completed strokes render through it.
- `_trigger_ocr` in math_trainer is unchanged (still PIL `draw.line`).
- A quick manual draw in each of the three surfaces shows smooth curves with
  no visible facets on fast strokes.

---

## T2 — Give the annotation canvas real `tabletEvent` handling  ⚠️ SUBTLE

**Problem.** The annotation canvas (`ui/pdf_annotation_dialog.py`) has no
`tabletEvent` override. On a stylus/pen tablet it receives Qt-synthesised
mouse events, which are coarser and slightly laggier than real tablet
events — and carry no pressure. Review mode reads real `TabletEvent`s
(`ui/canvas/interaction.py:64-110`) and that fidelity is a big part of why
review feels smoothest.

**Task.** Port review's tablet-event forwarding pattern into the annotation
canvas so stylus users get high-fidelity pen input there too. This is a
focused port — do not rewrite the annotation canvas.

### 1. Add a `tabletEvent` override to the annotation canvas widget

Find the canvas widget class in `ui/pdf_annotation_dialog.py` (the one that
defines `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`/`_draw_points`,
around lines 439-625). Add a `tabletEvent` method that:

- Accepts the tablet event when a pen/stylus is in use.
- Translates it into the same internal state the mouse handlers use
  (`self._live_points`, `self._drawing_page`, `self._tool`, etc.).
- Calls `e.accept()` on TabletPress / TabletMove / TabletRelease so Qt does
  **not** synthesise a duplicate mouse event afterwards.
- For non-pen tablets or unsupported cases, calls `e.ignore()` so the
  existing mouse path still works (mouse users must be unaffected).

Reference: review's pattern in `ui/canvas/interaction.py:64-71` + the
`_handle_review_tablet_ink` body. You do NOT need pressure-modulated width —
just accept the high-fidelity position events and feed them into the
existing `_live_points` append logic.

Sketch:
```python
def tabletEvent(self, e):
    from PyQt5.QtCore import QEvent
    et = e.type()
    if et == QEvent.TabletPress:
        # mirror mousePressEvent's left-button branch using e.posF()/position()
        ...
        e.accept()
    elif et == QEvent.TabletMove:
        # mirror mouseMoveEvent's left-button branch
        ...
        e.accept()
    elif et == QEvent.TabletRelease:
        # mirror mouseReleaseEvent's left-button branch
        ...
        e.accept()
    else:
        e.ignore()
```

Use the same `_tablet_pos` helper pattern review uses
(`ui/canvas/interaction.py:73-83`): try `posF()`, then `position()`, then
`pos()`. Add a small private `_tablet_pos(self, e)` method copied from
interaction.py.

### 2. Do not break mouse users

The existing `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent` must
continue to work unchanged for mouse input. Because `tabletEvent` accepts
pen events, Qt will not synthesise mouse events for pen input — so the
mouse handlers will only fire for actual mice. Verify this with a manual
test if possible.

### 3. Do not port pressure-based width

Review reads `e.pressure()` but does not (currently) modulate width by it.
Match that: read position only, ignore pressure for rendering. (Future task
can add pressure-width to both.)

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `Ran 426+ tests, OK` with 0 errors.
By inspection:
- Annotation canvas has a `tabletEvent` override that accepts
  TabletPress/Move/Release and feeds `posF()` into the existing
  `_live_points` path.
- A `_tablet_pos` helper exists (mirroring interaction.py).
- Mouse-only input still draws correctly (no regression).

---

## Definition of Done

- [ ] T1: shared `smooth_points_to_path` in `ui/canvas/geometry.py`; adopted
      by review (delegates), annotation (with offset), and math scratchpad
      (visual render only, OCR path untouched).
- [ ] T2: annotation canvas has real `tabletEvent` handling; mouse path
      unchanged.
- [ ] `python -m unittest discover -s tests` is green end-to-end
      (`Ran 426+ tests, OK`, 0 errors). Baseline is 426.
- [ ] Review-mode pen output is byte-identical to before (T1 only refactored
      the helper, not the math).
- [ ] No task refactored beyond its stated scope.
- [ ] T2 (⚠️ SUBTLE) diff reviewed by a human before commit.

When both are done, hand the diff back for review.
