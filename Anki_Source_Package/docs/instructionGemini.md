# instructionGemini.md

Follow-up fixes after the DESKTOP_PERF_TODO.md review.
These are **minor polish items** — small, isolated, low-risk. Do them one at a time.

## Rules (same as before)

- Do **one task at a time**, in order (F-1 → F-4).
- Do not refactor beyond the task's stated scope. Match surrounding code style.
- After each task, run the acceptance test command.
- Preserve all other `print("[DEBUG]...")` lines unless a task says otherwise.
- Use Python 3.12 for all test runs:
  ```
  C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
  ```
- **Baseline before you start:** `Ran 417 tests, OK (0 errors)`. After each task,
  result must still be `OK` with 0 errors. If errors go up, something broke.

---

## F-1 — Remove a dead mask-cache line in review_screen.py

**Problem.** The mask-cache machinery was fully removed (P0-1), but one stale
assignment survived:

`ui/review_screen.py:876`:
```python
self.canvas._mask_cache_layer = None
```

The canvas no longer has a `_mask_cache_layer` attribute. The line runs inside a
`try/except`, so it does not crash — it just silently sets a non-existent
attribute. It is dead cleanup-targeting code.

**Task.**
1. Open `ui/review_screen.py`, find the `closeEvent` teardown block around line
   872-880 that clears `self.canvas._pages`, `self.canvas._px`, etc.
2. Delete **only** the line `self.canvas._mask_cache_layer = None`.
3. Leave the surrounding lines (`_pages = []`, `_px = None`, `_spx_cache.clear()`)
   exactly as they are.

**Acceptance.**
```
findstr /n "_mask_cache_layer" ui\review_screen.py
```
Must return **no matches**.
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `OK` with 0 errors (417 tests or more).

---

## F-2 — Give the startup DB-load error a usable screen

**Problem.** P2-2 added a background `DataLoaderThread`. On **success**, the
home screen loads correctly. On **failure**, `_on_data_load_error`
(`anki_occlusion_v19.pyw:436-441`) only shows the error in the status bar:

```python
def _on_data_load_error(self, err_msg):
    print(f"[main] Failed to load data: {err_msg}")
    sb = self.statusBar()
    if sb:
        sb.showMessage(f"❌ Database load failed: {err_msg}")
    self._data_thread = None
```

The central widget is still the "Loading database…" `QLabel`, so on a corrupt or
missing DB the user sees a frozen-looking window with a tiny status-bar message
at the bottom — confusing and easy to miss on a maximized window.

**Task.**
1. In `_on_data_load_error`, replace the central widget with an error screen
   instead of leaving the loading label. Build a simple `QWidget` containing:
   - A large centered title like `"❌ Failed to load database"`
   - The error message below it (wrap it; use the `err_msg` arg)
   - Two buttons: **Retry** and **Quit**
2. **Retry** should: clear `store`'s in-memory data, recreate and start a new
   `DataLoaderThread` (same signal wiring as `MainWindow.__init__`), and swap the
   central widget back to a fresh loading label while it runs.
3. **Quit** should call `QApplication.quit()` (do NOT use `sys.exit` from a slot).
4. Style the error screen to match the existing dark theme — reuse colors from
   `theme_manager.get_palette("dark")` (e.g. `C_BG`, `C_CARD`, `C_TEXT`,
   `C_RED`, `C_ACCENT`). Do not hardcode hex colors that duplicate the palette.
5. Keep `self._data_thread = None` at the end.
6. Do not change the success path (`_on_data_loaded`) or the testing branch
   (`is_testing` in `__init__`).

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `OK` with 0 errors.
Manual: temporarily rename/move `~/anki_occlusion_data.db`, launch the app, and
confirm the error screen appears with Retry and Quit buttons. Rename it back
before finishing.

---

## F-3 — Add the missing "sync disabled" log line in gdrive_service.py

**Problem.** SEC-1 moved the client secret to the `ANKI_GDRIVE_CLIENT_SECRET`
environment variable, but the user-facing log line I asked for was not added.
When the env var is unset, `is_linked()` silently returns False and Drive sync
just won't connect — the user has no hint why.

**Task.**
1. In `services/gdrive_service.py`, in the config-loading code (around lines
   100-108 where `client_secret` is read from `os.environ.get(
   "ANKI_GDRIVE_CLIENT_SECRET", "")`), add a log line **only when the secret is
   empty**:
   ```python
   print("[gdrive] ANKI_GDRIVE_CLIENT_SECRET not set — sync disabled")
   ```
2. The line must fire **once per process**, not on every config read. Use a
   module-level flag (e.g. `_SYNC_DISABLED_LOGGED = False`) guarded by a lock or
   simple check so rapid re-reads don't spam the log.
3. Do not change `is_linked()` logic or any other behavior — this is purely a
   diagnostic print.
4. Do not print the secret value, ever — only the "not set" message.

**Acceptance.**
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `OK` with 0 errors.
Confirm by inspection: with `ANKI_GDRIVE_CLIENT_SECRET` unset, importing and
configuring `gdrive_service` prints the line exactly once.

---

## F-4 — Update the stale docstring in editor_ui.py

**Problem.** P0-1 removed `_rebuild_mask_cache`, but the historical docstring in
`editor_ui.py` (around lines 32, 39-40) still describes it:

```text
ROOT CAUSE: _rebuild_mask_cache() created QPixmap(sw, sh) for the ENTIRE
...
  • _rebuild_mask_cache() now checks: if sh > 32 767, skip the cache and
    set _mask_cache_layer = None (direct-draw signal).
```

Cosmetic only — a reader will be confused because the method no longer exists.

**Task.**
1. Open `editor_ui.py`, find the module-level comment block around lines 28-45
   that discusses the mask cache and `> 32 767` pixel handling.
2. Rewrite it to reflect the **current** reality: the mask-cache layer was
   removed entirely; masks are drawn directly in `paintEvent` per box, clipped to
   the viewport; no offscreen `QPixmap` is allocated for masks.
3. Keep it short (5-10 lines). Keep the same comment style (`#` lines or the
   existing block style) as the surrounding file.
4. Do not change any code, only the comment/docstring text.

**Acceptance.**
```
findstr /n "_rebuild_mask_cache\|_mask_cache_layer" editor_ui.py
```
Must return **no matches** (the historical references are gone).
```
C:\Users\Digvijay\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests
```
Must print `OK` with 0 errors.

---

## Definition of Done

- [ ] F-1: dead line removed; no `_mask_cache_layer` in review_screen.py.
- [ ] F-2: DB-load failure shows a Retry/Quit error screen.
- [ ] F-3: missing-secret log line added, fires once.
- [ ] F-4: editor_ui.py docstring no longer references removed mask cache.
- [ ] `python -m unittest discover -s tests` is green end-to-end (`OK`, 0 errors).
- [ ] No task refactored beyond its stated scope.

When all are done, hand the diff back for a quick re-review.
