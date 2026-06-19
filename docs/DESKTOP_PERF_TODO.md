# DESKTOP_PERF_TODO.md

Performance and architecture cleanup tasks for the **Anki Occlusion desktop app** only.
Scope: the PyQt5 desktop app (`anki_occlusion_v19.pyw`, `ui/`, `services/`, core modules).
**Ignore `web/`, `scratch/`, `installer/`, `dist/`, `build/`, `release/`** entirely.

---

## How to use this file (READ FIRST)

- Do **one task at a time**, in priority order (P0 → P1 → P2 → SEC → CLEANUP).
- Each task is self-contained: it tells you the exact files and line numbers, the
  current behavior, the desired behavior, and the acceptance test.
- **Do not refactor beyond the task's stated scope.** No renaming, no reformatting,
  no "while I'm here" edits. Match the surrounding code style.
- After every task, run the acceptance test command. If it fails, fix your change
  — do not move on.
- Preserve all existing debug `print("[DEBUG]...")` lines unless a task explicitly
  says to remove them.
- Do **not** delete or modify any test file's assertions. If a test reveals a real
  bug in your change, fix the change.
- The entry point is `anki_occlusion_v19.pyw` (the `.py` was deleted; `.pyw` is real).
- `DATA_FILE` resolves to `~/anki_occlusion_data.db` in production (SQLite backend).

### How to run tests (Windows, cmd)
```
python -m unittest discover -s tests
```
Or a focused suite:
```
python -m unittest tests.test_data_manager tests.test_review_screen
```
Set `ANKI_TESTING=1` if a test needs the temp data dir (the code already does this
automatically when run under unittest/pytest).

---

## Priority legend

| Tag | Meaning |
|-----|---------|
| 🔴 P0 | Biggest perf win, lowest risk. Do these first. |
| 🟠 P1 | Real perf win, moderate scope. |
| 🟡 P2 | Smaller win or larger scope. Do after P0/P1. |
| 🔒 SEC | Security — do regardless of perf. |
| 🧹 CLEANUP | Dead code / duplication. Do last. |

---

# 🔴 P0 — Highest impact

## P0-1 — Remove the dead mask-cache machinery

**Problem.** The "hardware mask cache" feature was disabled but its build step still
runs on every paint.

- `ui/canvas/renderer.py:217` has `if False and self._mask_cache_layer ...` — the
  cached-layer blit **never executes**.
- But `ui/canvas/renderer.py:154-159` still calls `self._rebuild_mask_cache()` on
  every dirty cycle.
- `_rebuild_mask_cache` (`ui/canvas/state.py` around line 353) allocates a
  full-viewport `QPixmap` and redraws **all** boxes into it (`state.py:370-382`).
- The result is then thrown away, and `paintEvent` redraws every box again
  directly (`renderer.py:229`).

**Net waste per paint:** one viewport-sized pixmap allocation + a full mask redraw,
all discarded. ~15 call sites invoke `_invalidate_mask_cache` (set_mode, reveal,
select, delete, undo, redo, group…), each retriggering this.

**Task.**
1. In `ui/canvas/renderer.py` `paintEvent`: delete the entire `if False and ...`
   branch (lines ~217-225). Keep only the direct-draw `else` path (lines ~226+).
   The comment at lines 214-216 can stay.
2. In `ui/canvas/state.py`: delete `_rebuild_mask_cache`, `_invalidate_mask_cache`,
   and the `_mask_cache_dirty` / `_mask_cache_layer` attributes from `__init__`
   and every call site that sets/reads them. Search the whole `ui/` tree for
   `_mask_cache_dirty`, `_mask_cache_layer`, `_rebuild_mask_cache`,
   `_invalidate_mask_cache`, `_draw_mask_cache_layer` and remove them.
3. In `cache_manager.py`: the `MASK_REGISTRY` (`_MaskRegistry` class + `MASK_REGISTRY`
   singleton, roughly lines 942-1018) and its usage in `CacheManagerPanel`
   (`mask_bytes_for_pdf`, `invalidate_masks_for_pdf`, the `🧯`/mask row in
   `_make_card`, the `_clear_all` mask loop) exist only to track this dead layer.
   Remove `MASK_REGISTRY`, the `_MaskRegistry` class, and all references in
   `CacheManagerPanel` (the per-PDF "mask layer" row and its total computation
   should simply be dropped from the UI).
4. Do **not** touch `_spx_cache`, the page loop, or the ink path.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
grep -r "_mask_cache_layer\|_rebuild_mask_cache\|_invalidate_mask_cache\|MASK_REGISTRY" --include=*.py ui/ cache_manager.py
```
First command passes; second command returns **no matches** in app code (test
files may still reference removed names — update those tests only if they fail).
Mask drawing must look identical to the user.

---

## P0-2 — Stop serializing the whole tree to JSON when the backend is SQLite

**Problem.** `DATA_FILE` is now `~/anki_occlusion_data.db` (SQLite is the primary
backend, `data_manager.py:42`). But the save path still does:

```python
# data_manager.py:586  (save_if_dirty)  and  :604  (save_force)
snapshot_text = json.dumps(self._data, ensure_ascii=False, indent=2)
snapshot_summary = DirtyStore._data_summary(self._data)
```

Then `_write_snapshot_to_disk` (`data_manager.py:628`) only writes that string if
`DATA_FILE.endswith(".json")` (the guard at `data_manager.py:646`), which is
**never** true in production. So every autosave serializes the entire deck tree to
a JSON string that is immediately discarded, plus walks the whole tree a second
time for `_data_summary`.

**Task.**
1. In `save_if_dirty` (`data_manager.py:578`) and `save_force`
   (`data_manager.py:601`): compute `snapshot_text` and `snapshot_summary` **only
   when** `DATA_FILE.endswith(".json")`. Otherwise pass `None` for both into
   `_write_snapshot_to_disk`.
2. In `_write_snapshot_to_disk` (`data_manager.py:628`): accept `snapshot_text`
   and `snapshot_summary` as possibly-`None`. The existing JSON-write guard at
   line 646 already checks `DATA_FILE.endswith(".json")` — make sure it also
   guards against `snapshot_text is None` (defensive: `if snapshot_text is not
   None and DATA_FILE.endswith(".json")`).
3. Do not change `_save_to_sqlite` — it is the real writer and stays as-is.
4. Keep the empty-overwrite safety check logic intact for JSON mode.

**Acceptance.**
```
python -m unittest tests.test_data_manager
```
Passes. With the `.db` backend, a profiler/`timeit` around `save_if_dirty` should
show no `json.dumps` of the full tree.

---

# 🟠 P1 — High value

## P1-1 — Batch recovery events instead of fsync-per-rating

**Problem.** Every card rating writes a recovery JSON event atomically, which
calls `os.fsync` (`services/recovery_manager.py:60`). This runs on the GUI thread
via `services/review_manager.py:132`. Rapid reviewing = one disk sync per
keypress.

**Task.**
1. In `services/recovery_manager.py`, add an in-memory pending queue and a flush
   timer:
   - A module-level `_PENDING_EVENTS = []` (list) and a lock.
   - `record_review_event(event)` (`recovery_manager.py:477`) appends a **deep
     copy** of the event to `_PENDING_EVENTS` instead of writing immediately, then
     schedules/refreshes a flush via a `threading.Timer(1.5, flush_pending_events)`.
     Re-scheduling replaces an existing pending timer (debounce) so the timer
     fires 1.5s after the **last** rating.
   - `flush_pending_events()`: under the lock, move the pending list to a local
     var, clear `_PENDING_EVENTS`, cancel the pending timer; then write each
     event via the existing `_atomic_write_json` path (outside the lock).
   - Make `flush_pending_events` idempotent and safe to call when empty.
2. Add a module-level `flush()` that callers can invoke synchronously.
3. Wire `flush()` into:
   - `ui/review_screen.py` `closeEvent` (already does teardown — add the call).
   - `anki_occlusion_v19.pyw` `MainWindow.closeEvent` (near `store.stop_autosave()`).
4. `discard_review_event` (`recovery_manager.py:488`) must also remove the event
   from the in-memory queue if it hasn't been flushed yet.
5. Do not change the on-disk format, file naming, or retention pruning.

**Acceptance.**
```
python -m unittest tests.test_recovery_manager tests.test_review_manager
```
Passes. Crash safety is preserved: events are either on disk or flushed on close.
Confirm: rapid ratings (simulate 10 ratings within 1s) produce ≤1 write batch, not 10.

---

## P1-2 — Cache canvas colors; gate per-paint allocations behind the profile flag

**Problem.** In `ui/canvas/renderer.py`:
- `_get_canvas_colors()` (lines ~281-308) builds a new ~10-key dict **every box,
  every paint** (called from `_draw_box_impl` ~line 322). N masks ⇒ N dict
  allocations per frame.
- `paintEvent` (lines 134-148) rebuilds the `phases` dict and calls
  `time.perf_counter()` multiple times even when profiling is off.
- `_draw_box_impl` constructs fresh `QColor`/`QPen`/`QBrush` per box per paint
  (lines ~344-360).

**Task.**
1. Replace `_get_canvas_colors()` with a cached lookup keyed on
   `get_pdf_invert_setting()`. Implement a small module-level cache:
   `_CANVAS_COLORS_CACHE = {}` keyed by a boolean invert flag; recompute the dict
   only when the flag changes. Return the cached dict.
2. Build shared `QPen`/`QBrush`/`QColor` objects **once** per color-set and store
   them in the cached dict (or a parallel cache). `_draw_box_impl` reads them
   instead of constructing new ones.
3. In `paintEvent`: build the `phases` dict and call `time.perf_counter()` only
   when `self._paint_profile_enabled` is True (it is already read once at init
   in `core.py`). When profiling is off, skip the dict and the timer calls; the
   drawing logic itself must be unchanged.
4. Keep the existing log line format for when profiling IS on.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. With profiling off (`ANKI_PERF_DEBUG` unset), no dict/timer allocations
per box per paint.

---

## P1-3 — Bound `_spx_cache` with an LRU

**Problem.** `ui/canvas/core.py:156` defines `_spx_cache` as a plain `dict`. Each
zoom level × page index stores a full-page scaled `QPixmap`; entries are never
evicted except on full `.clear()`. Scrolling/zooming a long PDF grows pixmap RAM
monotonically.

**Task.**
1. Replace the plain `dict` with `collections.OrderedDict`. Add a module constant
   `SPX_CACHE_MAX = 24` near the top of `core.py`.
2. On every write to `_spx_cache` (search for `_spx_cache[` assignments in
   `renderer.py` and `state.py`), call `move_to_end(key)` and evict with
   `popitem(last=False)` while `len(self._spx_cache) > SPX_CACHE_MAX`.
3. Reads stay as-is (returns the cached value). Optionally `move_to_end` on hit
   for true LRU, but FIFO-ish eviction is acceptable if simpler.
4. `_apply_smooth` in `state.py` (around line 418) currently clears the whole
   cache on zoom-settle — that can stay, but note it's now redundant with the
   bound; leave it as-is to keep behavior identical.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. Pixmap RAM stays bounded regardless of how many zoom levels are visited.

---

## P1-4 — Remove blocking `.wait()` from GUI-thread reload/close/contrast paths

**Problem.** Several GUI-thread code paths call `thread.stop(); thread.wait(N)`,
freezing the UI for up to 300-1000ms when a worker doesn't quit promptly.

**Locations.**
- `ui/review_screen.py`: lines 898, 2996, 3002, 3897, 4881, 5065
- `ui/editor_dialog.py`: lines 1165, 1320, 1325
- `page_scheduler.py`: line 202 (`wait(800)`)

**Task.**
1. For each reload / contrast-toggle / close path listed above, replace the
   synchronous `thread.stop(); thread.wait(N)` with:
   - `thread.stop()` (signals the worker to exit after its current page).
   - A deferred cleanup: pass the thread object to a helper that connects to its
     `finished` signal (or uses `QTimer.singleShot`) to null the reference and
     do any post-stop bookkeeping. Do **not** block the GUI thread.
2. Keep a synchronous `wait()` **only** in true app shutdown: the top-level
   `MainWindow.closeEvent` in `anki_occlusion_v19.pyw` and the final
   `ReviewScreen.closeEvent` / `CardEditorDialog` teardown where the window is
   actually being destroyed.
3. Stale-result guards (generation counters, path checks) must remain intact —
   they are what make deferred stop safe.
4. If a worker's `stop()` + deferred cleanup is genuinely unsafe for a specific
   call site, document why in a comment and leave that one as synchronous.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui tests.test_page_scheduler
```
Passes. Manually (or via a test): toggling PDF contrast, reloading, and closing
the review/editor no longer freeze the UI for up to 1s.

---

# 🟡 P2 — Moderate value

## P2-1 — Store `page_num` on each box at load/inject time

**Problem.** `ui/canvas/state.py` `get_boxes()` (lines ~448-491) computes
`page_num` by looping `_page_tops` for **every box** (lines ~480-486). It is
emitted on every drag-end / delete / group / select. On a 100-page PDF with many
masks this is O(boxes × pages) per interaction.

**Task.**
1. When boxes are loaded or injected into the canvas (find the set/load path in
   `state.py`), compute each box's `page_num` once using the existing
   `_infer_page_num_from_rect` helper (or `_page_tops` bisect) and store it on
   the box dict (e.g. `box["_canvas_page_num"]`). Keep any existing `page_num`
   field untouched — use a new key to avoid clashing with persisted data.
2. In `get_boxes()`, read `_canvas_page_num` from the box instead of recomputing.
   Fall back to the old computation only if the key is missing (defensive).
3. Update `_canvas_page_num` whenever a box is moved/resized (in the
   move/resize handlers in `interaction.py` and `state.py`) — or invalidate it so
   the next `get_boxes` recomputes for that box only.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. `get_boxes()` is O(boxes) in the common case.

---

## P2-2 — Move startup data load off the GUI thread

**Problem.** `anki_occlusion_v19.pyw:348` calls `load_data()` synchronously in
`MainWindow.__init__`. This reads/parses the whole SQLite DB and recursively runs
`sched_init` on every deck/card/box (`data_manager.py:86-105`) before the window
appears. No splash, no deferred load. For large decks this is the dominant
cold-start cost.

**Task.**
1. Show the `MainWindow` shell (with the home screen in a "Loading…" state)
   immediately. Disable deck/card/study actions until load completes.
2. Move the `load_data()` + post-load setup into a `QThread` (or
   `threading.Thread` that emits a Qt signal). Use a worker `QObject` with a
   `done` signal carrying nothing — the main thread reads `store.get()` after.
3. On the `done` signal (GUI thread): populate the home screen, enable actions,
   start autosave (`store.start_autosave()`), run the existing
   `QTimer.singleShot` onboarding/recovery hooks.
4. Keep `store.load()` itself thread-safe — it already uses locks; just make
   sure no Qt widget code runs inside the worker.
5. If the load is fast (small DB), the user sees no flicker; if slow, they see a
   responsive shell instead of a frozen blank window.

**Acceptance.**
```
python -m unittest tests.test_home_screen tests.test_data_manager
```
Passes. Window appears immediately on cold start; home populates when load done.

---

## P2-3 — Fix `_check_completion` O(n²) during bulk load

**Problem.** `page_scheduler.py:325` `_check_completion` runs `any(...)` over all
pages on every `page_ready` signal. During a full-PDF load this is O(n²).

**Task.**
1. Maintain a `_remaining` counter (number of pages still pending/`loading`)
   decremented on each successful render/inject and incremented when new pages
   are requested.
2. `_check_completion` becomes `self._remaining <= 0` — O(1).
3. Be careful with the priority/visible/background batching: the counter must
   reflect pages that have been **requested** but not yet **injected**, including
   those queued in `inject_queue`.

**Acceptance.**
```
python -m unittest tests.test_page_scheduler
```
Passes. Bulk-load completion check is O(1) per page.

---

## P2-4 — Index cards by `_id` for O(1) lookup

**Problem.** `data_manager.py` `find_card_and_deck_by_id` (line 1137) and
`find_duplicate_card` (line 1071) do recursive full-deck walks per lookup. Called
on every rating/undo. O(depth × cards) each.

**Task.**
1. In `DirtyStore`, maintain a `_card_index: dict` mapping `card_id → (card_dict,
   parent_deck_dict)`. Rebuild it whenever `set()` or `load()` is called (full
   rebuild is fine — it happens at most once per revision).
2. Add a public `get_card_by_id(card_id) -> (card, deck) | (None, None)` that
   reads the index.
3. Update `find_card_and_deck_by_id` to delegate to the index (keep the function
   signature and behavior identical for callers).
4. `find_duplicate_card` can keep walking for the dHash/SHA-256 comparison (those
   need every card), but skip the title/identity walk by using the index where
   possible.
5. Invalidate/rebuild the index only on `set`/`load`/`mark_dirty`-with-structural-
   change — simplest correct approach is rebuild on every `set`/`load`. Do not
   rebuild on every `mark_dirty`.

**Acceptance.**
```
python -m unittest tests.test_data_manager tests.test_review_manager
```
Passes. Per-rating card lookup is O(1) instead of O(tree).

---

## P2-5 — Cache rendered text-card pixmaps

**Problem.** `ui/review_screen.py` `_render_text_card_to_pixmap` (line ~3475)
builds a `QTextDocument`, runs regex image processing, scales pixmaps, and paints
— synchronously, on the GUI thread. It is re-invoked on every reveal toggle
(callers at lines ~1505 and ~1634). No per-(card, revealed) cache.

**Task.**
1. Add a small instance-level pixmap cache on `ReviewScreen`, keyed by
   `(card_id, revealed: bool)`. Max size ~8 entries (LRU `OrderedDict`).
2. `_render_text_card_to_pixmap` checks the cache first; on hit, returns the
   cached `QPixmap`. On miss, renders as today, stores, returns.
3. Invalidate the entry for a card when that card is edited (find the edit-save
   path) or when the review session resets.
4. Do not cache across different cards indefinitely — bound it.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_text_cards
```
Passes. Toggling reveal on the same card twice does not re-run the
`QTextDocument` build the second time.

---

## P2-6 — Replace `processEvents()` in `_center_on_target`

**Problem.** `ui/review_screen.py:3105` calls `QApplication.processEvents()`
inside the centering routine to flush layout. Pumping the event loop from within
a slot risks reentrancy.

**Task.**
1. Replace the `processEvents()` + immediate-center with a deferred
   `QTimer.singleShot(0, self._do_center_on_target)` pattern (the file already
   uses `singleShot(0, ...)` elsewhere — match that style).
2. Move the actual centering logic into `_do_center_on_target` so the layout is
   settled by the time it runs.
3. Preserve the existing behavior: after centering, the target mask is in view.

**Acceptance.**
```
python -m unittest tests.test_review_screen
```
Passes. No `processEvents()` call remains in `_center_on_target`.

---

# 🔒 SEC — Security (do regardless of perf)

## SEC-1 — Revoke and remove the leaked Google OAuth client secret

**Problem.** `services/gdrive_service.py:106` hardcodes a Google OAuth client
secret:
```python
"client_secret": "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"
```
A client secret in source is a credential leak. Also `services/gdrive_service.py:12`
bakes in a developer-machine path:
```python
sys.path.append(r"C:\Users\Digvijay\Desktop\Anki gs3236208")
```

**Task.**
1. **Human action first (not code):** the repo owner must revoke
   `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` in Google Cloud Console and create a new
   credential. Flag this in the PR description — Gemini cannot do the revocation.
2. Remove the hardcoded secret from the fallback config. Load the client secret
   from an environment variable (e.g. `ANKI_GDRIVE_CLIENT_SECRET`) or from a
   user-writable config file outside the repo. The client_id can stay if it is
   the public OAuth client id (those are not secret), but the secret must not be
   in source.
3. Remove the `sys.path.append(r"C:\Users\...")` line at `gdrive_service.py:12`.
   If the module needs its own directory on the path, compute it relative to
   `__file__` (e.g. `os.path.dirname(os.path.abspath(__file__))`).
4. Do not break existing linked accounts — the token storage path must stay the
   same.

**Acceptance.**
```
python -m unittest tests.test_gdrive_service
grep -r "GOCSPX" --include=*.py .
```
Tests pass (mock the secret in tests); grep returns **no matches**.

---

# 🧹 CLEANUP — Do last, after all perf tasks

## CLEANUP-1 — Delete dead modules

**Problem.** These modules have **zero production imports** (verified by search):
- `services/tf_worker.py`
- `services/local_ocr_server.py`
- `thread_manager.py`

**Task.**
1. Delete the three files above.
2. Search the whole repo (excluding `dist/`, `build/`, `release/`,
   `installer/`, `__pycache__`) for any remaining imports of them and remove.
3. If `AnkiOcclusion.spec` (PyInstaller) or `build_installer.ps1` references them,
   remove those references too.
4. Do not delete `convert_to_onnx.py`, `train_model.py`, `verify_models.py`,
   `render_pdf_to_images.py` — those are build/tooling scripts, confirm with the
   owner first.

**Acceptance.**
```
grep -r "tf_worker\|local_ocr_server\|thread_manager" --include=*.py . | findstr /v "__pycache__ \\dist\\ \\build\\ \\release\\ \\installer\\"
python -m unittest discover -s tests
```
First command returns no app-code matches; full suite passes.

---

## CLEANUP-2 — Deduplicate the OCR preprocessing pipeline

**Problem.** The contour → pad → resize → 28×28 → predict pipeline is copy-pasted
in (after CLEANUP-1) `services/ocr_engine.py` and possibly `assets/model/app.py`.
The vestigial test-hook at `services/ocr_engine.py:84-91`
(`_worker_process.stdin.write.side_effect` + `raise BrokenPipeError`) also leaks
test mocking into production.

**Task.**
1. Extract the shared preprocessing into a single function in `ocr_engine.py`
   (e.g. `preprocess_digit_image(image_bytes_or_array) -> np.ndarray`).
2. Use it from `ocr_number` and any other in-repo caller.
3. Remove the dead `_worker_process`, `_worker_ready`, `_worker_started`,
   `_reset_worker_state` symbols and the test-hook branch at `ocr_engine.py:84-91`.
4. `warm_up` is called on every `ocr_number` (`ocr_engine.py:93`) redundantly —
   call it once at first use only (keep the lock-guarded lazy load).

**Acceptance.**
```
python -m unittest tests.test_ocr_engine tests.test_editor_ocr
```
Passes.

---

## CLEANUP-3 — Deduplicate canvas geometry helpers and theme constants

**Problem.** All four canvas files re-declare identical module-level theme
constants and the `_point_in_rotated_box` / `_point_in_rotated_ellipse` helpers:
- `ui/canvas/core.py:43-60`
- `ui/canvas/renderer.py:48-65`
- `ui/canvas/state.py:44-61`
- `ui/canvas/interaction.py:41-58`

The geometry helpers are only actually *used* in `interaction.py`.

**Task.**
1. Move the shared geometry helpers into one place (e.g. a new
   `ui/canvas/geometry.py` or into `interaction.py` and import from there).
2. Import them where used; delete the duplicates from the other three files.
3. Consolidate the duplicated theme-color constants into a single import from
   `theme_manager` (or one shared `ui/canvas/colors.py`). Do not change any color
   values.
4. This is a pure move/refactor — no behavior change.

**Acceptance.**
```
python -m unittest tests.test_review_screen tests.test_editor_ui
```
Passes. No duplicated helper definitions remain across the four canvas files.

---

## CLEANUP-4 — Reduce journal backup write amplification

**Problem.** `services/journal_manager.py` `_save_journal` (line ~41) creates a
dated backup (`shutil.copy2`) on **every save**, then prunes to 30.
`session_timer.py` fires the save every 30s (`session_timer.py:223`). That's up to
~120 backup-creates + prunes per hour of runtime.

**Task.**
1. Back up the journal **at most once per calendar day**. Track the last backup
   date (e.g. in a module-level var or a small sidecar file); skip the `copy2` if
   a backup for today already exists.
2. Keep the 30-backup rotation and the atomic write.
3. The `flush_to_journal` on close can still force a backup if none exists for
   today.

**Acceptance.**
```
python -m unittest tests.test_journal
```
Passes. Simulating 10 saves within the same day produces ≤1 new backup file.

---

# Definition of Done (for the whole file)

- [ ] All 🔴 P0 tasks done and their acceptance tests pass.
- [ ] All 🟠 P1 tasks done and their acceptance tests pass.
- [ ] 🔒 SEC-1 done; secret revoked out-of-band; no `GOCSPX` in repo.
- [ ] `python -m unittest discover -s tests` is green end-to-end.
- [ ] No task introduced a new `print("[DEBUG]...")` in a hot path.
- [ ] No task refactored beyond its stated scope.

When all of the above are true, hand the diff back for review. Reviewer will
re-check each `file:line` anchor against the original report.
