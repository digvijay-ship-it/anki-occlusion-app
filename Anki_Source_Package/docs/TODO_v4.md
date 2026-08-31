# TODO_v4.md

Scroll-feel fixes. The canvas scroll currently feels laggy/jittery because of
four compounding problems. This file addresses three of them with cheap,
targeted changes. Same rules as `docs/DESKTOP_PERF_TODO.md`, `docs/TODO_v2.md`,
`docs/TODO_v3.md`. Read those files' "How to use" sections first.

## How to use this file

- Do **one task at a time**, in order (S1 → S3).
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

Tracing the scroll path revealed four causes of the laggy/jittery feel:

| # | Cause | Where |
|---|-------|-------|
| 1 | Huge fixed-size canvas widget + no viewport-update-mode tuning | `review_screen.py:2179`, `editor_dialog.py:446` |
| 2 | Per-scroll-event Python work that loops pages and rebuilds sets, on every pixel of scroll | `editor_ui.py:331`, `review_screen.py:4571` |
| 3 | `_apply_smooth` wipes the ENTIRE scaled-pixmap cache mid-scroll, forcing a full re-raster | `ui/canvas/state.py:338` |
| 4 | Touchpad scroll stepping coarse (not per-pixel) | `editor_ui.py:286` |

S1 fixes #4 + part of #1. S2 fixes #2. S3 fixes #3. (The deeper "virtualise
the canvas widget height" part of #1 is a real refactor and is deliberately
out of scope here.)

---

## S1 — Smooth pixel scrolling + viewport-update mode on the canvas scroll area  ✅ MECH

**Problem.** `_ZoomableScrollArea` (`editor_ui.py:286-318`) does not configure
per-pixel scrolling or a viewport-update mode. On Windows touchpads the
default scroll stepping can be coarse (the "jumpy" feel), and the default
`MinimalViewportUpdate` mode can cause extra repaint bookkeeping on a very
tall canvas widget.

**Task.**

1. In `_ZoomableScrollArea.__init__` (after line 309, `self.viewport().installEventFilter(self)`),
   add (match the surrounding init style — no blank-line churn beyond what's
   natural):
   ```python
   # Per-pixel scrolling for smooth touchpad feel
   self.setVerticalScrollMode(QScrollArea.ScrollPerPixel)
   self.setHorizontalScrollMode(QScrollArea.ScrollPerPixel)
   # Coarse-grained viewport updates: fewer repaint scheduling passes on a
   # tall canvas widget than the MinimalViewportUpdate default.
   self.setViewportUpdateMode(QAbstractArea.BoundingRectViewportUpdate)
   ```
2. `QAbstractArea` is not a real Qt class. The correct import for the
   viewport-update enum is `QAbstractScrollArea` (which `QScrollArea`
   inherits from). Use the qualified form:
   `QAbstractScrollArea.BoundingRectViewportUpdate` — and ensure
   `QAbstractScrollArea` is imported at the top of `editor_ui.py` (add it to
   the existing `from PyQt5.QtWidgets import (...)` block if missing; it is
   the parent of `QScrollArea` so the import is safe).
   So the three lines become:
   ```python
   self.setVerticalScrollMode(QScrollArea.ScrollPerPixel)
   self.setHorizontalScrollMode(QScrollArea.ScrollPerPixel)
   self.setViewportUpdateMode(QAbstractScrollArea.BoundingRectViewportUpdate)
   ```
3. Do **not** change anything else in the class (pan logic, event filter,
   signal wiring). Only these three lines + the import.

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `Ran 426+ tests, OK` with 0 errors. Manual: touchpad two-finger
scroll on a PDF in review mode should glide per-pixel, not jump in coarse
steps.

---

## S2 — Stop doing eager visible-pages work on every pixel of scroll  ✅ MECH

**Problem.** `_ZoomableScrollArea._on_scroll` (`editor_ui.py:331-360`) is
connected to `verticalScrollBar().valueChanged` and therefore runs on **every
pixel of scroll**. It does Python work on each call (page lookup, geometry
reads, timer restart) and, worse, every 100ms it also calls
`_emit_visible_pages` (line 359-360) *during active motion*. That emit fans
out into `_on_visible_pages_changed` (`review_screen.py:4571`) which builds
set copies, runs debug-state tracking, and calls both
`_inject_cached_visible_pages` and `_review_pages_needing_render` — all
synchronous, all rebuilding sets, all on the GUI thread mid-scroll.

The debounce timer (`_scroll_debounce`, 150ms, line 312-315) already exists
and is the correct place to do this work — it fires once after motion
settles. The eager 100ms emit is redundant with it and is the source of the
per-scroll overhead.

**Task.**

1. In `_on_scroll` (`editor_ui.py:331-360`): **remove the eager emit** at
   lines 358-360:
   ```python
   last_emit = self._last_visible_emit_ts
   if last_emit is None or (now - last_emit) * 1000.0 >= 100.0:
       self._emit_visible_pages()
   ```
   Replace it with a single comment explaining that visible-page work is
   deferred to the debounce timer:
   ```python
   # Visible-page detection is deferred to _scroll_debounce (150ms after
   # motion stops) — see _emit_visible_pages. Doing it eagerly here runs
   # set-rebuilds + cache probes on the GUI thread every pixel of scroll.
   ```
2. Keep `self._scroll_debounce.start()` (line 356) — that is what schedules
   the deferred emit. Every new scroll event restarts it, so it fires 150ms
   after the **last** scroll event, exactly once.
3. Keep all the bookkeeping that `_on_scroll` does (direction tracking,
   `_last_scroll_value`, `_last_scroll_ts`, `page` computation for any
   caller that needs it). Only the eager emit goes away.
4. Do **not** change `_emit_visible_pages` itself, the debounce interval,
   or the signal wiring. The signal still fires — just once-after-settle
   instead of repeatedly mid-scroll.
5. Sanity: confirm `_last_visible_emit_ts` is still updated inside
   `_emit_visible_pages` (it is — line 412) so any caller that reads it
   still gets a sane value.

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `Ran 426+ tests, OK` with 0 errors. Manual: during a continuous
touchpad scroll, the visible-pages prefetch/render should trigger once after
the scroll settles, not repeatedly mid-swipe. Lazy page rendering of pages
that scroll into view still works (the debounce fires within 150ms of stop).

**Note on a subtle risk:** if any caller relies on visible-page updates being
**real-time** during scroll (e.g., a floating UI element that must track the
current page as you swipe), the 150ms deferral will make it lag. The current
callers (`_on_visible_pages_changed` → lazy render + prefetch) are
post-settle by design, so this is safe. Do not add a real-time path back.

---

## S3 — Stop `_apply_smooth` from wiping the whole scaled-pixmap cache  ⚠️ SUBTLE

**Problem.** After a Ctrl+wheel zoom settles, `_finalize_zoom`
(`ui/canvas/state.py:334-336`) starts `_smooth_timer` (300ms), which fires
`_apply_smooth` (lines 338-341):
```python
def _apply_smooth(self):
    """Clear fast-scaled cache and repaint with SmoothTransformation."""
    self._spx_cache.clear()   # wipes ALL cached scaled pixmaps
    self.update()              # forces immediate repaint
```
This wipes the **entire** `_spx_cache` and forces a repaint that re-rasterizes
every visible page with `SmoothTransformation` (expensive bilinear filter).
If the user zooms and then scrolls within 300ms, this lands mid-scroll and
causes a visible stutter.

**Why the wipe is unnecessary.** The scaled-pixmap cache is keyed on the
page index, and each entry stores `(scale, pixmap)` — but NOT the transform
type used to produce it. So a `FastTransformation` pixmap cached during zoom
would be wrongly reused after we want smooth quality. The wipe "fixes" that
by nuking everything.

The correct fix is to **include the transform type in the cache key** so
stale fast-zoom entries naturally miss and get replaced lazily as each page
repaints — no bulk wipe, no mid-scroll re-raster storm.

**Task.**

1. **Change the cache value tuple** from `(scale, pixmap)` to
   `(scale, transform_type, pixmap)` at **every** site that writes the cache.
   There are three write sites:
   - `ui/canvas/renderer.py` paintEvent single-image path, line ~184:
     `self._spx_cache["_px"] = (self._scale, cached_spx)` →
     `self._spx_cache["_px"] = (self._scale, transform_type, cached_spx)`
   - `ui/canvas/state.py` `_get_scaled_page`, line ~188:
     `self._spx_cache[idx] = (self._scale, cached_spx)` →
     `self._spx_cache[idx] = (self._scale, transform_type, cached_spx)`
   - `ui/canvas/state.py` `inject_page`, line ~235-238:
     `self._spx_cache[page_num] = (self._scale, qpx.scaled(...))` →
     store the transform_type alongside. Compute `transform_type` the same
     way the other two sites do (`Qt.FastTransformation if self._fast_zoom
     else Qt.SmoothTransformation`).

2. **Change every read site** to unpack three values and compare transform
   type. Read sites:
   - `renderer.py` line ~170: `cached_scale, cached_spx = self._spx_cache.get("_px", (None, None))`
     → `cached_scale, cached_tt, cached_spx = self._spx_cache.get("_px", (None, None, None))`
     and the hit-test at line ~173 becomes:
     `if cached_scale != self._scale or cached_tt != transform_type or cached_spx is None:`
     (compute `transform_type` once before this block, the same way line 177
     currently does — hoist it up).
   - `state.py` `_get_scaled_page` line ~175: same unpack to three values,
     hit-test at lines 178-183 adds `and cached_tt == transform_type`.
   - `state.py` `inject_page` line ~227: `cached_scale, _cached_spx =
     self._spx_cache.get(page_num, (None, None))` → unpack three, ignore the
     transform_type there (this site only checks whether a cache entry exists
     at the right scale before deciding to re-scale on inject — keep its
     existing logic, just unpack three values).

3. **Make `_apply_smooth` a no-op for the cache** — it no longer needs to
   wipe anything, because stale FastTransformation entries will now
   naturally miss on the next paint (their `cached_tt` won't match the
   current `Qt.SmoothTransformation`). Change it to:
   ```python
   def _apply_smooth(self):
       """Fast-zoom settled: repaint so cached pages re-evaluate quality.

       No cache wipe needed — entries are now keyed by transform type, so
       stale FastTransformation pixmaps miss lazily on the next paint and
       get replaced with SmoothTransformation versions one page at a time.
       """
       self.update()
   ```
   Keep the `self.update()` (it triggers the repaint that lazily upgrades
   visible pages to smooth quality). Remove only the `self._spx_cache.clear()`.

4. **Do not** change `_finalize_zoom`, the timer interval, `_fast_zoom`
   assignment, or any other cache interaction (the PDF-path reset in
   `load_pages`, the LRU eviction `popitem` loops, etc.). Only the three
   write sites, the three read sites, and `_apply_smooth`.

**Why this is ⚠️ SUBTLE:** the cache tuple shape changes everywhere it's read
or written. A missed site will unpack two values from a three-tuple (or vice
versa) and raise `ValueError: too many values to unpack`. Search the whole
`ui/canvas/` tree (and `review_screen.py`) for `_spx_cache.get` and
`_spx_cache[` to find every read/write. If a test constructs cache entries
directly, update it too.

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `Ran 426+ tests, OK` with 0 errors.
By inspection:
- `grep -n "_spx_cache" ui/canvas/*.py ui/review_screen.py` shows every
  read/write site unpacks/packs three values.
- `_apply_smooth` no longer calls `self._spx_cache.clear()`.
Manual: Ctrl+wheel zoom then immediate scroll no longer produces a mid-scroll
stutter; visible pages upgrade to smooth quality smoothly as they repaint.

---

## Definition of Done

- [ ] S1: per-pixel scroll mode + BoundingRectViewportUpdate on
      `_ZoomableScrollArea`.
- [ ] S2: eager visible-pages emit removed from `_on_scroll`; deferred to
      the existing 150ms debounce.
- [ ] S3: scaled-pixmap cache keyed by `(scale, transform_type, pixmap)`;
      `_apply_smooth` no longer wipes the cache.
- [ ] `python -m unittest discover -s tests` is green end-to-end
      (`Ran 426+ tests, OK`, 0 errors). Baseline is 426.
- [ ] No task refactored beyond its stated scope.
- [ ] S3 (⚠️ SUBTLE) diff reviewed by a human before commit — the cache
      tuple shape change is the riskiest part.

When all three are done, hand the diff back for review.
