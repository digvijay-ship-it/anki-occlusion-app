# TODO_v2.md

Round-2 fixes after the DESKTOP_PERF_TODO.md / instructionGemini.md work.
These are **NEW findings** — none overlap with what was already shipped.

Style and rules are identical to `DESKTOP_PERF_TODO.md`. Read that file's
"How to use this file" section first if you haven't.

## How to use this file

- Do **one task at a time**, in priority order (🔴 P0 → 🟠 P1 → 🟡 P2 → 🔒 SEC).
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
- Entry point: `anki_occlusion_v19.pyw`. Data backend: `~/anki_occlusion_data.db`.
- Python: `C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe`
- **Baseline before you start:** `Ran 417 tests, OK (0 errors)`.

### Tags
- ✅ **MECH** — mechanical, well-specified. Safe for an agent to implement.
- ⚠️ **SUBTLE** — race / threading / security. Implement extra carefully;
  read the whole surrounding function before editing. These are the ones most
  likely to need a human review of the diff.

## Priority legend

| Tag | Meaning |
|-----|---------|
| 🔴 P0 | Correctness — user-visible or data-integrity. Do these first. |
| 🟠 P1 | Performance — real wins, moderate scope. |
| 🟡 P2 | Leaks / smaller correctness / smaller perf. |
| 🔒 SEC | Security — do regardless of perf. |

---

# 🔴 P0 — Correctness

## P0-1 — Emit `batch_done` on every render error/early-return path  ⚠️ SUBTLE

**Problem.** When a PDF page render fails, `PdfOnDemandThread.run`
(`pdf_engine.py`) emits `error` but **never** emits `batch_done`. The only
place that resets pages from `"loading"` → `"not_loaded"` is
`page_scheduler.py` `_on_worker_batch_done`. So after any render error, every
page left in `"loading"` stays stuck forever, `_not_done_count` never reaches
0, and the `all_done` signal never fires. The user sees a permanently
half-loaded review.

**Locations (every path that returns/exits without emitting `batch_done`):**
- `pdf_engine.py` — `PdfOnDemandThread.run`:
  - the `not PDF_SUPPORT` early return
  - the file-not-found early return
  - the empty-pages early return
  - the fatal `except` block (around line 895–897)
- `pdf_engine.py` — `PdfLoaderThread.run`: same set of early-return paths
  (around lines 1107, 1179, 1218).

**Task.**
1. In each early-return path and each top-level `except` of both
   `PdfOnDemandThread.run` and `PdfLoaderThread.run`, emit
   `self.batch_done.emit([])` (empty list — nothing was rendered) **before**
   returning, so the scheduler can reset its `"loading"` pages.
2. In `page_scheduler.py` `_on_worker_batch_done`: when `rendered_set` is
   empty AND none of the requested pages were rendered, the existing
   reset-to-`"not_loaded"` logic already handles it — verify it does, and log
   one line `[DEBUG][scheduler] batch_done empty — resetting N loading pages`
   so this is diagnosable.
3. Do **not** change the success path, the generation counter, or `stop()`.

**Acceptance.**
```
python -m unittest tests.test_pdf_engine tests.test_page_scheduler
```
Passes. Manual reasoning: with a deliberately corrupt PDF page, no page
remains in `"loading"` state after the worker exits.

---

## P0-2 — Don't `json.dumps` a live, mutable `_data` dict  ⚠️ SUBTLE

**Problem.** `data_manager.py` serializes `self._data` (the live dict that
callers mutate in place via `get()`) directly:

- `_write_snapshot_to_disk` around lines 623 and 645 does
  `json.dumps(self._data, ...)` under `_lock`.
- `_save_to_sqlite` (around line 687) walks `self._data` under `_write_lock`.

`json.dumps` is **not atomic** vs. concurrent dict mutation. The autosave
thread can be mid-`json.dumps` while the GUI thread mutates `self._data`
through a `get()` reference → `RuntimeError: dictionary changed size during
iteration` → save fails or writes truncated JSON. The SQLite path is
similarly exposed (it walks the live dict).

**Task.**
1. In `_write_snapshot_to_disk`: take a `copy.deepcopy(self._data)` snapshot
   **under** `self._lock`, then release the lock and serialize/walk the
   snapshot. Pass the snapshot to the JSON write branch and to
   `_save_to_sqlite`.
2. Keep `_save_to_sqlite`'s signature but have it accept the snapshot (not
   the live dict). Do not change its SQL.
3. Keep the empty-overwrite safety check working against the snapshot.
4. Do not introduce a second lock — reuse `_lock` for the snapshot copy.
5. This is a behavior-preserving change: the bytes written must be identical
   for a quiescent tree.

**Acceptance.**
```
python -m unittest tests.test_data_manager tests.test_review_manager
```
Passes. Confirm by inspection that `json.dumps` and the SQLite walk never
touch `self._data` directly — only the deep-copied snapshot.

---

## P0-3 — Join `DataLoaderThread` on close  ✅ MECH

**Problem.** `anki_occlusion_v19.pyw` `MainWindow.__init__` (around line
348–385) starts a `DataLoaderThread` for the background DB load, but
`closeEvent` never waits on it. If the user closes the window during the
initial load, `load_data()` keeps running while widgets are torn down.

**Task.**
1. In `MainWindow.closeEvent`, before the existing teardown, if
   `self._data_thread` is not None and `self._data_thread.isRunning()`:
   call `self._data_thread.stop()` (if it has one) or signal it, then
   `self._data_thread.wait(2000)`.
2. Wrap in `try/except Exception` so a join failure cannot block app exit.
3. Set `self._data_thread = None` after.
4. Do not change the success/error signal wiring or the `is_testing` branch.

**Acceptance.**
```
python -m unittest discover -s tests
```
Passes (OK, 0 errors). Confirm by inspection that `closeEvent` waits on the
data thread.

---

## P0-4 — Reset image-card boxes to `revealed=False`  ✅ MECH

**Problem.** `ui/review_screen.py` `_apply_canvas` (around line 4990–4993),
the `box_idx is None` branch, calls `self.canvas.set_boxes(boxes)` with the
raw boxes. Every sibling branch builds `[{**b, "revealed": False} for b in
boxes]`. So for an image card with no target box, masks revealed on the
**previous** card bleed through.

**Task.**
1. In that one branch, build `display_boxes = [{**b, "revealed": False} for b in boxes]`
   and pass `display_boxes` to `set_boxes`, matching the sibling branches.
2. Do not touch the other branches or `set_boxes_with_state`.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes.

---

## P0-5 — Refresh `_canvas_page_num` after undo/redo  ✅ MECH

**Problem.** `ui/canvas/state.py` `undo()` (around 703–712) and `redo()`
(714–723) restore boxes from a snapshot but never refresh the cached
`_canvas_page_num` field (added by P2-1 of the prior round). If the document
layout changed between push and undo, `get_boxes()` returns stale page
numbers, which mis-routes lazy page loading.

**Task.**
1. At the end of both `undo()` and `redo()`, after the boxes are restored,
   call the existing helper that recomputes `_canvas_page_num` for all boxes
   (the same one P2-1 added for the load/inject path — e.g.
   `_update_all_box_page_nums()`; find it by name).
2. If no such bulk helper exists, loop the boxes and call the per-box helper
   (`_infer_page_num_from_rect` or the `_page_tops` bisect) the same way the
   load path does.
3. Do not change the push/pop logic or the deque bound.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. After an undo, `get_boxes()` page numbers match a fresh computation.

---

## P0-6 — Clamp `easy_iv` to `MAX_INTERVAL`  ✅ MECH

**Problem.** `sm2_engine.py` around line 235–241:
```python
easy_iv_raw = min(MAX_INTERVAL, int(...))
good_iv_raw = min(MAX_INTERVAL, int(...))
easy_iv_raw = max(easy_iv_raw, good_iv_raw + 1)   # line ~241
```
The `max(...)` at line 241 runs **after** the `min(MAX_INTERVAL, ...)` clamp,
so an Easy rating can produce an interval larger than `MAX_INTERVAL`,
defeating the documented 365-day cap.

**Task.**
1. Re-clamp after the `max`: change line ~241 to
   `easy_iv_raw = min(MAX_INTERVAL, max(easy_iv_raw, good_iv_raw + 1))`.
2. Do not change any other branch (Hard/Good/Perfect) or the fuzz step.

**Acceptance.**
```
python -m unittest tests.test_sm2_engine
```
Passes. Add (or extend) a test asserting no rating ever returns an interval
`> MAX_INTERVAL` from the `review` state.

---

## P0-7 — Don't let tablet timestamps suppress edit-mode mouse events  ✅ MECH

**Problem.** `ui/canvas/interaction.py`:
- `tabletEvent` (around 42–49) records `_last_tablet_event_time` /
  `_last_tablet_move_time` even when `_handle_review_tablet_ink` returns
  `False`.
- `_is_recent_stylus_mouse_event` (around 118–138) then suppresses
  synthesized mouse events for 0.35s — including in **edit** mode, where
  synthesized mouse events are the primary input for most tablets.

Result: stylus users see dropped clicks/drags in the editor right after pen
contact.

**Task.**
1. In `_is_recent_stylus_mouse_event`, early-return `False` if
   `self._mode != "review"`. Edit mode must never suppress mouse events.
2. Equivalently, in `tabletEvent`, only record the timestamps when
   `self._mode == "review"`. Pick one of the two; do not do both.
3. Do not change review-mode behavior.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. Confirm by inspection that edit-mode tablet→mouse synthesis is no
longer suppressed.

---

## P0-8 — Guard malformed `rect` so one bad row doesn't roll back the save  ✅ MECH

**Problem.** `data_manager.py` around line 336–337:
```python
rect = box.get("rect", [0,0,0,0])
... rect[0], rect[1], rect[2], rect[3] ...
```
A legacy/manually-edited `rect` that isn't length-4 raises `ValueError`
**inside the SQLite transaction** → rollback → **all** changes in that save
are lost.

**Task.**
1. Coerce `rect` to a length-4 list before unpacking, e.g.:
   ```python
   rect = list(box.get("rect") or [0, 0, 0, 0])
   if len(rect) < 4:
       rect = rect + [0] * (4 - len(rect))
   rect = rect[:4]
   ```
2. Do not change the schema, the column write, or any other field.

**Acceptance.**
```
python -m unittest tests.test_data_manager
```
Passes. Add a test: a box with `rect: [10, 20]` (too short) does not raise
and does not abort the save.

---

# 🟠 P1 — Performance

## P1-1 — Scan the review queue once per second, not twice  ✅ MECH

**Problem.** `ui/review_screen.py` `_sync_floating_timer` (around 1128–1138)
runs on a 1 Hz timer and calls both `_sync_floating_queue_count()` and
`_sync_queue_timer_count()`. Each independently calls
`_active_queue_count()` = `sum(1 for _,_,sm2 in self._items if
is_due_today(sm2))` — a full queue walk with date-string parsing. That's
**2× O(N) per second** for the entire review session.

**Task.**
1. At the top of `_sync_floating_timer`, compute
   `count = self._active_queue_count()` once.
2. Pass it as `total=count` to both `_sync_floating_queue_count(total=...)`
   and `_sync_queue_timer_count(total=...)`. Both helpers already accept a
   `total` kwarg (see how `_update_queue_label` at ~560–565 already does
   this).
3. Do not change the timer interval or the label-update logic.

**Acceptance.**
```
python -m unittest tests.test_review_screen
```
Passes. Confirm by inspection that `_active_queue_count()` is called exactly
once per `_sync_floating_timer` tick.

---

## P1-2 — Make background-fill diff O(rendered) instead of O(total_pages)  ✅ MECH

**Problem.** `ui/review_screen.py`:
- `_on_background_fill_batch_done` (~4403–4414) and `_start_background_fill`
  (~4266, 4301–4318) call `PAGE_CACHE.cached_page_indices(path, total_pages)`
  and then iterate `range(total_pages)` to diff against
  `combined | canvas_real | pending_bg`.
- With `_BG_FILL_BATCH = 2`, completing a 500-page PDF does ~250 batches ×
  500 probes = ~125k set probes.

**Task.**
1. Add an instance attribute `self._bg_remaining` — a `set` of page numbers
   still pending background fill. Initialize it when a background fill
   starts: `_bg_remaining = set(candidates)`.
2. In `_on_background_fill_batch_done`, do
   `self._bg_remaining.difference_update(rendered_set)` — O(rendered), not
   O(total).
3. If `self._bg_remaining` is empty (or below `_BG_FILL_BATCH`), stop
   scheduling further batches.
4. Drop the `range(total_pages)` rescan. Keep the per-batch size and the
   priority ordering of which pages fill first.
5. Reset/clear `_bg_remaining` whenever the PDF or review session changes
   (find the existing reset points).

**Acceptance.**
```
python -m unittest tests.test_review_screen
```
Passes. Background fill still completes the whole PDF; the per-batch cost no
longer depends on `total_pages`.

---

## P1-3 — Cache canvas colors once per paint, not per box  ✅ MECH

**Problem.** `ui/canvas/renderer.py`:
- `_draw_box_impl` (~309) calls `self._get_canvas_colors()` inside the
  per-box loop.
- `_draw_handles` (~376) calls it again.
`_get_canvas_colors` imports `cache_manager.get_pdf_invert_setting` and
queries the store **per visible box per frame**. (P1-2 of the prior round
added a memo keyed on the invert flag, but the call site is still inside the
loop.)

**Task.**
1. In `paintEvent`, compute `cc = self._get_canvas_colors()` **once** at the
   top (after the existing setup, before the boxes loop).
2. Pass `cc` down into `_draw_box` / `_draw_box_impl` / `_draw_handles` as a
   parameter. Update their signatures to accept it (keep defaults so other
   callers still work, or update all callers — pick whichever is smaller).
3. Do not change what `_get_canvas_colors` returns or its cache.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. With profiling off, `_get_canvas_colors` runs once per paint, not
once per box.

---

## P1-4 — Hoist per-paint QColor/QPen allocations  ✅ MECH

**Problem.** `ui/canvas/renderer.py`:
- ~164: `QColor("#1E1E2E")` for the background fill, allocated every paint.
- ~194: `sep_pen = QPen(QColor("#45475A"), 2)` for separators, allocated
  every paint even when the page loop is skipped.

**Task.**
1. Add two module-level constants near the other theme constants at the top
   of `renderer.py`:
   ```python
   _C_BG_CANVAS = QColor("#1E1E2E")
   _SEP_PEN = QPen(QColor("#45475A"), 2)
   ```
2. Replace the two allocations with the constants.
3. Do not change any color value.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes.

---

## P1-5 — Hoist text-card regex compiles to module level  ✅ MECH

**Problem.** `ui/review_screen.py` `_render_text_card_to_pixmap`
(~3501–3625) does `import re` and compiles three patterns
(`<img...src=...>`, `<img...>`, `font-size...`) inside `process_html_images`
on **every cache miss**. Also has local Qt imports at the top of the
function.

**Task.**
1. Move the three `re.compile(...)` calls to module level (named, e.g.
   `_RE_IMG_SRC`, `_RE_IMG`, `_RE_FONT_SIZE`).
2. Use the compiled patterns inside `process_html_images`.
3. Move the Qt imports (`QTextDocument`, `QPainter`, `QPixmap`, `QColor`,
   `QUrl`) to the top of `review_screen.py` with the other Qt imports — but
   only if they're not already imported there. If they are already imported
   at the top, just delete the local imports.
4. Do not change the regex behavior or the rendering output.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_text_cards
```
Passes. No `re.compile` inside `_render_text_card_to_pixmap` or
`process_html_images`.

---

## P1-6 — Stop calling `fitz.TOOLS.store_shrink(100)` on every render  ✅ MECH

**Problem.** `pdf_engine.py` calls `fitz.TOOLS.store_shrink(100)` after
nearly every render: around lines 516, 632, 904, 939, 985, 1033, 1218.
This is a **global** operation across all open MuPDF documents, it's racy
when called from concurrent QThreadPool workers, and it penalizes other live
documents.

**Task.**
1. Remove every `fitz.TOOLS.store_shrink(100)` call from the render paths
   listed above.
2. Add **one** call site instead: a low-frequency idle shrink. Simplest
   correct option — call it once at the end of `PdfOnDemandThread.run` /
   `PdfLoaderThread.run` (after the batch completes), not per-page. If an
   idle timer already exists in the app, prefer wiring it there.
3. If unsure, the minimal change is: remove all per-page calls, keep one at
   the end of each `run()`. Document the choice in a one-line comment.

**Acceptance.**
```
python -m unittest tests.test_pdf_engine tests.test_review_screen
```
Passes. `grep -n "store_shrink" pdf_engine.py` shows at most one call per
worker `run()`.

---

## P1-7 — Hoist `get_pdf_invert_setting` import out of the render loop  ✅ MECH

**Problem.** `pdf_engine.py` around line 675 (inside `pdf_page_to_image`,
in the hot render loop):
```python
from cache_manager import get_pdf_invert_setting
```
An import lookup on every page render.

**Task.**
1. Move `from cache_manager import get_pdf_invert_setting` to the top of
   `pdf_engine.py` with the other imports (guard with the existing
   `try/except ImportError` if `cache_manager` is optional — match how
   `pdf_engine` already handles optional deps).
2. Delete the in-loop import.
3. Do not change when/how `get_pdf_invert_setting()` is *called* — only the
   import location.

**Acceptance.**
```
python -m unittest tests.test_pdf_engine
```
Passes. No `from cache_manager import` inside `pdf_page_to_image`.

---

## P1-8 — Call `_init_sqlite` once at load, not on every save  ✅ MECH

**Problem.** `data_manager.py` `_save_to_sqlite` (around line 222) calls
`_init_sqlite()` on every save. That's 4 `CREATE TABLE IF NOT EXISTS` + a
`PRAGMA` on every autosave.

**Task.**
1. Move the `_init_sqlite()` call out of `_save_to_sqlite` and into `load()`
   (call it once, right after the DB path is resolved and before the first
   read).
2. Ensure `_init_sqlite` is idempotent (it already uses `IF NOT EXISTS`, so
   it is) and safe to call before any write.
3. Do not change the schema or the PRAGMAs.

**Acceptance.**
```
python -m unittest tests.test_data_manager
```
Passes. `_init_sqlite` is not called from `_save_to_sqlite`.

---

## P1-9 — Precompute card hashes at import; stop disk reads in `find_duplicate_card`  ⚠️ SUBTLE

**Problem.** `data_manager.py` `find_duplicate_card` (around 1131–1178)
computes SHA-256 and dHash by reading full files from disk **inside the
search loop** — O(n) file reads per duplicate check. It also mutates
`card["file_hash"]` **outside** `store._lock` (the lock is released at
~1129 after copying the index), so the autosave thread can serialize the
same card mid-mutation.

**Task.**
1. When a card is created/imported (find the import/add path), compute
   `file_hash` (SHA-256) and `dhash` once and store them on the card dict.
   Re-use the existing helpers; do not change their algorithms.
2. In `find_duplicate_card`, read `file_hash`/`dhash` from the card dict
   when present; only fall back to on-demand computation when missing (and
   in that case, write the result back under `store._lock` via
   `store.mark_dirty`, not by direct mutation outside the lock).
3. Snapshot the hash values under `store._lock`, then iterate and compare
   outside the lock — no card mutation outside the lock.
4. Do not change the duplicate-detection semantics (dHash threshold, SHA
   equality).

**Acceptance.**
```
python -m unittest tests.test_data_manager tests.test_review_manager
```
Passes. A duplicate check over N already-imported cards does **zero** file
reads.

---

# 🟡 P2 — Leaks & smaller fixes

## P2-1 — Bound and sweep `_pending_worker_cleanups`  ✅ MECH

**Problem.** `ui/review_screen.py` appends stopped QThread objects to
`self._pending_worker_cleanups` and removes them via a `finished` lambda.
If `finished` never fires (thread crashed, or already-finished before
`connect`), the QThread — which may hold rendered page pixmaps — stays
referenced for the whole session. Call sites: `_stop_skeleton_thread`
(~3935), `_stop_ondemand_thread` (~4930), `_reload_pdf_contrast` (~3005,
3015), `_start_review_pdf_thread` (~5113).

**Task.**
1. In every stop path: connect the `finished` cleanup lambda **before**
   calling `thread.stop()` / `quit()` (connecting after is the bug when the
   thread is already done).
2. Add a small sweep: before appending, drop any entries where
   `t.isFinished()` is True. Also cap the list (e.g. drop oldest finished
   entries if it exceeds ~16).
3. On `closeEvent`, clear the list (after joining — see P0-3's pattern).

**Acceptance.**
```
python -m unittest tests.test_review_screen
```
Passes. List does not grow unbounded over a long session.

---

## P2-2 — Clear `_ondemand_request_pages_by_thread` on stop  ✅ MECH

**Problem.** `ui/review_screen.py` `_ondemand_request_pages_by_thread` has
entries inserted at ~4096, ~4360, ~4681 keyed by `id(thread)`. But
`_stop_ondemand_thread` (~4936) only pops the entry for the *current*
`self._ondemand_thread`. During scroll churn, old threads' entries leak
forever.

**Task.**
1. In `_stop_ondemand_thread`, clear the **whole** dict
   (`self._ondemand_request_pages_by_thread.clear()`) instead of popping
   only the current thread's key — or pop entries from the `finished`
   cleanup lambda for each thread.
2. Do not change how entries are inserted.

**Acceptance.**
```
python -m unittest tests.test_review_screen
```
Passes. Dict size stays bounded across many stop/start cycles.

---

## P2-3 — Null PdfWatcher callbacks on close to break the cycle  ✅ MECH

**Problem.** `ui/review_screen.py` `__init__` (~647–653) assigns:
```python
self._pdf_watcher.get_current_page_cb = lambda: self.canvas.get_current_page(...)
self._pdf_watcher.get_hint_cb = lambda: (self._external_pdf_path_hint, ...)
```
These lambdas capture `self`, forming a reference cycle
(watcher ↔ lambda ↔ ReviewScreen) that keeps the whole screen + canvas +
caches reachable until GC. `closeEvent` calls `_pdf_watcher.stop_watch()`
(~909) but never nulls the callbacks.

**Task.**
1. In `closeEvent`, after `stop_watch()`, set both callbacks to `None`:
   ```python
   self._pdf_watcher.get_current_page_cb = None
   self._pdf_watcher.get_hint_cb = None
   ```
2. Guard with `if self._pdf_watcher is not None`.
3. Do not change how the callbacks are assigned or used.

**Acceptance.**
```
python -m unittest tests.test_review_screen
```
Passes. After close, no lambda holds a reference to the ReviewScreen.

---

## P2-4 — Lock the module-level skeleton caches  ⚠️ SUBTLE

**Problem.** `pdf_engine.py` ~60–64 defines `_SKELETON_CACHE`,
`_SKELETON_DIMS_CACHE`, `_SKELETON_PLACEHOLDER_CACHE` as module-level
`OrderedDict`s. They're mutated from `PdfSkeletonThread.run` (writes at
~541) and read from the GUI thread, with **no lock**. Concurrent
`move_to_end` / `popitem` can `KeyError` or corrupt iteration.

**Task.**
1. Add a module-level `_SKELETON_CACHE_LOCK = threading.Lock()`.
2. Wrap every read and write of the three caches in
   `with _SKELETON_CACHE_LOCK:`. Find all sites by searching for the three
   names.
3. Keep the LRU eviction (`move_to_end` / `popitem`) inside the lock.
4. Do not change cache sizes, keys, or eviction policy.

**Acceptance.**
```
python -m unittest tests.test_pdf_engine tests.test_review_screen
```
Passes. Stress-test reasoning: concurrent skeleton requests for different
PDFs do not raise `KeyError`.

---

## P2-5 — Close the `mkstemp` fd on exception  ✅ MECH

**Problem.** `services/recovery_manager.py` `_atomic_write_json` (~60–66):
if `json.dump` raises between `tempfile.mkstemp` (returns a raw fd) and
`os.fdopen`, the raw fd leaks. The `except` only `unlink`s the path.

**Task.**
1. Restructure so the fd is wrapped by `os.fdopen` **immediately** after
   `mkstemp`, inside a `with` block (so it closes on any exception), OR
   explicitly `os.close(fd)` in the `except` before `unlink`.
2. Do not change the atomic-rename behavior or the retry loop.

**Acceptance.**
```
python -m unittest tests.test_recovery_manager
```
Passes.

---

## P2-6 — Cap the inject queue while scrolling  ⚠️ SUBTLE

**Problem.** `page_scheduler.py` `_process_inject_queue` (~288–290): if
`_is_scrolling` is True, the function returns **without popping** the queue.
`_is_scrolling` is only reset by `_scroll_stop_timer` (150ms). Continuous
scrolling → every `_on_worker_page_ready` enqueues, nothing dequeues →
unbounded queue growth + a mass delayed inject when scrolling stops.

**Task.**
1. Even while scrolling, drain the **highest-priority** entry (or keep the
   queue capped — e.g. if `len(inject_queue) > 64`, drop the
   lowest-priority pending entry before appending).
2. Preserve the existing priority ordering (`min()` by page distance or
   whatever the current key is).
3. Do not change the scroll-stop timer interval.

**Acceptance.**
```
python -m unittest tests.test_page_scheduler
```
Passes. During continuous scrolling, `inject_queue` stays bounded.

---

## P2-7 — Replace `_ink_path_cache` `id()` keying with a stable counter  ✅ MECH

**Problem.** `ui/canvas/renderer.py` `_ink_path_cache` (~437–454) is keyed
on `id(stroke)`. When a stroke list object is GC'd, its `id` can be reused
by a new object → a stale `QPainterPath` is drawn for the wrong stroke.
The cache is also never cleared on `set_boxes`, `load_pixmap`, `load_pages`,
`undo`, `redo`.

**Task.**
1. Give each stroke a stable monotonically-increasing id at creation time
   (e.g. a `_stroke_seq` counter incremented when a stroke is appended —
   find the stroke-append path). Store it on the stroke dict as e.g.
   `stroke["_path_key"]`.
2. Key `_ink_path_cache` on that stable key instead of `id(stroke)`.
3. Clear `_ink_path_cache` in: `set_boxes`, `set_boxes_with_state`,
   `load_pixmap`, `load_pages`, `undo`, `redo`. (It's already cleared in
   `ink_clear`, `clear_review_ink_for_card_switch`, `ink_undo_stroke`.)
4. Do not change the smoothing algorithm or the cache size.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. No `id(` used as a cache key in renderer.py.

---

## P2-8 — Cap `_replace_file_with_retry` retries  ✅ MECH

**Problem.** `services/recovery_manager.py` `_replace_file_with_retry`
(~79–87) does 8 retries with linear backoff (up to ~400ms). With the 1.5s
debounce flush from P1-1 of the prior round, multiple flushes can stack
many sleeping threads.

**Task.**
1. Reduce max attempts from 8 to 3.
2. After the final failure, log **one** line
   `[recovery] replace failed after 3 attempts: <path>` and raise (let the
   caller decide — do not silently swallow).
3. Keep the linear backoff shape; just fewer steps.

**Acceptance.**
```
python -m unittest tests.test_recovery_manager tests.test_review_manager
```
Passes.

---

# 🔒 SEC — Security

## SEC-1 — Add OAuth `state` CSRF token verification  ⚠️ SUBTLE

**Problem.** `services/gdrive_service.py`:
- The OAuth receiver `OAuthReceiverHandler.do_GET` (~23–52) accepts any
  `code` param and stores it as `server.auth_code` with **no `state`
  verification**.
- The auth URL is built without a `state` parameter (find the URL-build
  site, ~around the `start_oauth_flow` / `get_auth_url` helper).

A malicious local process can POST a crafted URL to `localhost:8080` and
inject an attacker-controlled auth code, hijacking the user's Drive sync.

**Task.**
1. When building the auth URL, generate a random `state`
   (`secrets.token_urlsafe(16)`) and store it on the `HTTPServer` instance
   (e.g. `server.expected_state = state`). Include `&state=<state>` in the
   auth URL.
2. In `do_GET`, read `state = params.get("state", [None])[0]`. Only accept
   the `code` if `state == self.server.expected_state`. If it doesn't match,
   respond 400 and do **not** store the code.
3. Do not change the token-exchange flow, the redirect port, or the token
   file path.

**Acceptance.**
```
python -m unittest tests.test_gdrive_service
```
Passes. Add/extend a test: a request with a wrong/missing `state` is
rejected and `server.auth_code` stays `None`.

---

## SEC-2 — Restrict token file permissions  ✅ MECH

**Problem.** `services/gdrive_service.py` `_save_tokens` (~87–93) writes
the token file with default umask; the refresh token is readable by other
users on shared systems.

**Task.**
1. After writing the token file, `os.chmod(path, 0o600)`.
2. On Windows, `os.chmod(0o600)` is best-effort — that's fine, keep it.
3. Do not change the file path or JSON format.

**Acceptance.**
```
python -m unittest tests.test_gdrive_service
```
Passes.

---

## SEC-3 — Scrub auth headers from logged tracebacks  ⚠️ SUBTLE

**Problem.** `anki_occlusion_v19.pyw` `setup_logging` (~63–119) writes full
tracebacks (including locals) to `%APPDATA%/AnkiOcclusion/anki_occlusion.log`.
A failed GDrive call can include the access token in locals (e.g. a
`headers=` dict or a `requests` response object).

**Task.**
1. Before writing a traceback to the log, walk the stack frames and redact
   any local whose name suggests a secret: `token`, `access_token`,
   `refresh_token`, `Authorization`, `headers`, `client_secret`,
   `password`. Replace the value with `"<redacted>"`.
2. Implement as a small helper `_scrub_traceback(tb_text) -> str` and apply
   it in the exception hook. Keep the rest of the traceback (file/line/func)
   intact.
3. Do not change the log file path or the stdout TeeStream.

**Acceptance.**
```
python -m unittest discover -s tests
```
Passes. Inspect: a synthetic exception whose locals include
`access_token = "abc"` is logged with `"<redacted>"` in place of `"abc"`.

---

## SEC-4 — Escape single quotes in Drive query strings  ✅ MECH

**Problem.** `services/gdrive_service.py`:
- `_get_or_create_backups_folder` (~342–343) and `_find_file_in_folder`
  (~366–367) embed `folder_name` / `filename` directly into the Drive `q=`
  query via f-string. A filename containing `'` breaks the query → silent
  sync failure (data correctness, not just injection).

**Task.**
1. Add a helper `_escape_drive_query(value: str) -> str` that returns
   `value.replace("\\", "\\\\").replace("'", "\\'")`.
2. Use it on every user-derived string interpolated into a Drive `q=`
   query (folder name, filename).
3. Do not change the query structure or the field names (`name=`, `mimeType=`,
   `'root' in parents`, etc.).

**Acceptance.**
```
python -m unittest tests.test_gdrive_service
```
Passes. Add a test: a filename `o'brien.db` produces a valid query and is
found.

---

## SEC-5 — Close the log file handle on exit (unblocks rotation)  ✅ MECH

**Problem.** `anki_occlusion_v19.pyw` `setup_logging` (~84) opens the log
file, wraps it in `TeeStream`, but never closes it. On Windows the file
stays locked until process exit, which blocks the rotation `os.rename` at
~78 (the `except: pass` at ~80 swallows the failure).

**Task.**
1. Store the log file handle on a place `closeEvent` can reach (e.g. a
   module-level global or `MainWindow._log_file_handle`).
2. In `MainWindow.closeEvent`, before `super().closeEvent`, close the handle
   (`try/except` around it).
3. Keep the TeeStream and the rotation attempt as-is; closing the handle
   just makes the next launch's rotation succeed.
4. Do not change the log path.

**Acceptance.**
```
python -m unittest discover -s tests
```
Passes.

---

## SEC-6 — `server.shutdown()` the OAuth receiver on cancel  ⚠️ SUBTLE

**Problem.** `ui/home_screen.py` `start_oauth_flow` (~2760–2787): if the
user cancels the progress `QMessageBox`, the `HTTPServer` receiver thread is
parked on `handle_request()` for 120s and port 8080 stays bound.

**Task.**
1. On cancel, call `server.shutdown()` **from a separate thread** (calling
   `shutdown()` from the same thread that wants to `join` deadlocks) — or
   set a short `server.timeout` and loop `handle_request` so cancel can
   break out. Pick the simpler of the two for this codebase.
2. Then `server.server_close()` to release the socket.
3. Do not change the success path or the port.

**Acceptance.**
```
python -m unittest tests.test_home_screen
```
Passes. After cancel, port 8080 is released within ~1s.

---

# Definition of Done (for the whole file)

- [ ] All 🔴 P0 tasks done and their acceptance tests pass.
- [ ] All 🟠 P1 tasks done and their acceptance tests pass.
- [ ] All 🟡 P2 tasks done and their acceptance tests pass.
- [ ] All 🔒 SEC tasks done and their acceptance tests pass.
- [ ] `python -m unittest discover -s tests` is green end-to-end
      (`Ran 417+ tests, OK`, 0 errors). Baseline is 417.
- [ ] No task introduced a new `print("[DEBUG]...")` in a hot path.
- [ ] No task refactored beyond its stated scope.
- [ ] Every ⚠️ SUBTLE task's diff was reviewed by a human (race / security
      / threading).

When all are done, hand the diff back for review. Reviewer will re-check
each `file:line` anchor against this report.

---

## Token-budget note (for the operator)

The ✅ MECH tasks are self-contained and safe for an automated implementer.
The ⚠️ SUBTLE tasks (P0-1, P0-2, P1-9, P2-4, P2-6, SEC-1, SEC-3, SEC-6)
involve threading, races, or security — implement them last and review
their diffs manually. Recommended order: all ✅ MECH first (P0-3 → P0-8 →
P1-1 → P1-8 → P2-1 → P2-3 → P2-5 → P2-7 → P2-8 → SEC-2 → SEC-4 → SEC-5),
then the ⚠️ SUBTLE batch.
