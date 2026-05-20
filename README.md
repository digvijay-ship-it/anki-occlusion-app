# Anki Occlusion - Offline Desktop App

Anki Occlusion is an offline-first desktop study app built with Python and
PyQt5. It turns local PDFs and images into image-occlusion flashcards, schedules
reviews with an SM-2 style algorithm, and keeps your study data on your machine.

This root README documents the desktop app in this repository.

## Current App State

- Desktop entry point is `anki_occlusion_v19.py`.
- Local JSON data store with autosave, atomic writes, safety checks, and backups.
- Nested decks, deck/card management, undo/redo for deck changes, and recovery
  flows for interrupted work.
- PDF and image occlusion editor with rectangle, ellipse, text labels, grouping,
  multi-select, move, resize, rotate, pan, zoom, and per-page masks.
- Review mode with Anki-style reveal/rate flow: Again, Hard, Good, Easy, and
  Perfect.
- SM-2 scheduling supports new, learning, review, and relearn states with
  intraday learning steps, interval fuzzing, ease-factor updates, and an
  interval cap.
- Large PDF review mode is optimized for long documents. The app builds the
  review layout from page metadata first, then renders only the current and
  visible pages on demand.
- PDF page cache uses a 48-page RAM limit plus persistent disk cache. Cached
  pages can be injected immediately during review.
- PDF rendering workers create `QImage` in background threads. `QPixmap`
  conversion is kept on the GUI thread for Qt thread safety.
- Review pen is active by default when review starts.
- Review queue drawer can be hidden. When hidden, a large floating study timer
  stays on top of the PDF.
- Left/right arrow page navigation keeps already-rendered pages in the canvas
  instead of reloading them unnecessarily.
- Live PDF sync watches external PDF edits and refreshes changed documents.
- In-app PDF annotation scroll supports pen, highlight, erase, pasted images,
  undo/redo, save, and page navigation.
- Session timer tracks focus time during review and writes daily totals into
  the journal.
- Math Trainer OCR runs asynchronously so prediction work does not freeze the UI.
- Shortcut settings dialog lets core shortcuts be customized.
- Cache panel and diagnostics help inspect and clear cached PDF data.
- Dojo/classic themes, font scaling, music controls, fullscreen mode, and
  single-instance protection are included.

## Install

Use Python 3.8+.

Install core desktop dependencies:

```powershell
python -m pip install PyQt5 pymupdf
```

Optional Math Trainer OCR dependencies:

```powershell
python -m pip install numpy opencv-python pillow tensorflow
```

The app can still be used for normal deck, PDF, image, and review work without
the optional OCR stack.

## Run

From the repository root:

```powershell
python anki_occlusion_v19.py
```

If you are launching from another directory, pass the full path:

```powershell
python "C:\path\to\Anki gs3236208\anki_occlusion_v19.py"
```

## Desktop Workflow

1. Create a deck or subdeck from the home screen.
2. Add a card.
3. Load a PDF or image.
4. Draw masks over the answers.
5. Save the card.
6. Start review.
7. Press `Space` to reveal the answer.
8. Rate the answer with `1` to `5`.

## PDF Review Model

The current PDF review path is designed for large files.

- The app scans page dimensions from PDF metadata instead of rendering pages
  just to build the initial layout.
- The current review page gets priority even when it is beyond the first
  48 cached pages.
- Already-rendered canvas pages are reused when moving back and forth.
- Visible cached pages are injected immediately.
- Missing visible pages are rendered lazily in background workers.
- Cache profile checks the PDF file and zoom level so stale render data can be
  skipped or refreshed.

For a large PDF, the terminal should show a fast skeleton phase with:

```text
[DEBUG][skeleton] ... mode=rect_only
```

Useful review loading diagnostics:

```text
[DEBUG][review_cache_profile]
[DEBUG][review_queue_pages]
[DEBUG][review_load]
[DEBUG][review_viewport]
[DEBUG][review_decision]
[DEBUG][review_lazy]
[DEBUG][review_inject]
[DEBUG][review_visible_cache]
```

These debug statements are intentional during the current PDF/review performance
work so slow loads, cache misses, and page hydration decisions can be observed
from the terminal.

## Review Mode

Main review behavior:

- `Space` reveals the answer.
- Rating buttons update the card schedule and advance the queue.
- Queue drawer shows due/new/learning/review state.
- Hiding the queue drawer shows the floating timer.
- Default review tool is the pen.
- Timer overlay is kept above the PDF during scroll and arrow-key navigation.
- PDF pages can be changed with left/right arrows.
- Current PDF can be opened in the system reader from review mode.
- Annotation scroll can be opened from review mode at the current page position.

Review shortcuts:

| Shortcut | Action |
| --- | --- |
| `Space` | Reveal answer |
| `1` | Rate Again |
| `2` | Rate Hard |
| `3` | Rate Good |
| `4` | Rate Easy |
| `5` | Rate Perfect |
| `Left` | Previous PDF page |
| `Right` | Next PDF page |
| `C` | Center current mask |
| `E` | Edit current card |
| `T` | Open annotation scroll |
| `Ctrl+E` | Open current PDF |
| `Ctrl+L` | Open PDF folder |
| `L` | Copy current PDF path |
| `Ctrl+Z` | Undo rating |
| `Ctrl+Y` | Redo rating |
| `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Fit/reset zoom |
| `` ` `` | Toggle review pen |
| `X` | Cycle review pen color |
| `+` / `-` | Adjust review pen size |
| `Del` | Clear review pen marks |
| `F11` | Toggle fullscreen |
| `Esc` | Leave review |

## Editor Mode

Editor behavior:

- Load image files or PDFs.
- Draw masks on one page or across multiple PDF pages.
- Group and ungroup masks.
- Use undo/redo while editing.
- Open the source PDF in the system reader.
- Open the in-app annotation scroll.
- Save/recover interrupted card edits.
- Keep PDF masks adapted to page/image space.

Editor shortcuts:

| Shortcut | Action |
| --- | --- |
| `V` | Select tool |
| `R` | Rectangle mask |
| `E` | Ellipse mask |
| `T` | Text/label tool |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+A` | Select visible masks |
| `Ctrl+Shift+A` | Select all masks |
| `G` | Group selected masks |
| `Shift+G` | Ungroup selected masks |
| `Del` | Delete selected masks |
| `Ctrl+Scroll` | Zoom canvas |
| `Space+drag` | Pan canvas |
| `H` | Toggle pan lock |
| `Left` | Previous PDF page |
| `Right` | Next PDF page |

## Annotation Scroll

The annotation scroll is an in-app PDF annotation tool used for quick notes on
top of the PDF.

| Shortcut | Action |
| --- | --- |
| `Ctrl+S` | Save PDF annotations |
| `Ctrl+V` | Paste clipboard image |
| `Delete` | Delete selected pasted image |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Left` | Previous page |
| `Right` | Next page |
| `1` or `P` | Pen |
| `2` | Highlight |
| `3` or `E` | Erase |
| `S` | Image tool |
| `+` / `-` | Adjust pen width |
| `0` | Reset pen style |
| `C` | Reset fit |

## Home Screen

Home behavior:

- Browse decks and subdecks.
- Search and manage cards.
- Start due reviews.
- View due/new/learning/review counts.
- Open journal and Math Trainer.
- Open shortcut settings and cache tools.
- Switch theme/font settings.

Home shortcuts:

| Shortcut | Action |
| --- | --- |
| `Ctrl+S` | Save now |
| `Ctrl+Z` | Undo deck/card change |
| `Ctrl+Y` | Redo deck/card change |
| `Ctrl++` | Increase app font size |
| `Ctrl+-` | Decrease app font size |
| `Ctrl+0` | Reset app font size |
| `M` | Toggle music |
| `N` | Next music track |
| `F11` | Toggle fullscreen |

## Data And Cache

Main data file:

| Platform | Path |
| --- | --- |
| Windows | `C:\Users\<YourUser>\anki_occlusion_data.json` |
| macOS | `~/anki_occlusion_data.json` |
| Linux | `~/anki_occlusion_data.json` |

Persistence behavior:

- Saves are atomic through temp-file replacement.
- DirtyStore coalesces repeated changes and autosaves in the background.
- Save guards prevent accidental empty-data overwrites.
- Backups are created around risky writes.
- Recovery events can be replayed after interrupted review actions.

PDF cache behavior:

- RAM cache defaults to 48 rendered pages.
- Disk cache persists rendered pages between sessions.
- Pending worker images are tracked without forcing GUI pixmap creation.
- Cache inspection can count RAM, pending, and disk pages without loading them.
- Cache metadata tracks render zoom and PDF identity.

## Project Structure

```text
anki_occlusion_v19.py        Desktop app entry point
AnkiOcclusion.spec           PyInstaller desktop packaging spec
build_installer.ps1          Windows installer build script

data_manager.py              JSON storage, autosave, backups, undo history
sm2_engine.py                SM-2 scheduling and rating previews
pdf_engine.py                PDF skeleton scan, rendering, worker threads
cache_manager.py             RAM/disk page cache and cache diagnostics
session_timer.py             Review focus timer and journal integration
storage_paths.py             User data/cache/recovery path helpers
page_scheduler.py            Lazy page scheduling helpers
perf_utils.py                Performance helper utilities
theme_manager.py             Theme/font/style management
thread_manager.py            Thread lifecycle helper
models.py                    Shared card/deck data helpers

services/
  review_manager.py          Review queue/session state
  shortcut_manager.py        Shortcut registry and persistence
  ocr_engine.py              Async OCR bridge
  tf_worker.py               TensorFlow OCR worker
  local_ocr_server.py        Local OCR server helper
  pdf_watcher.py             External PDF change watcher
  pdf_annotation_service.py  PDF annotation read/write service
  recovery_manager.py        Recovery event and draft handling
  journal_manager.py         Journal persistence helpers

ui/
  home_screen.py             Main dashboard
  deck_tree.py               Deck tree/sidebar
  deck_view.py               Deck detail view
  editor_dialog.py           Card editor and occlusion editor
  review_screen.py           Review mode
  journal.py                 Journal/focus view
  math_trainer.py            Math practice module
  pdf_annotation_dialog.py   In-app PDF annotation scroll
  shortcut_dialog.py         Shortcut settings dialog
  recovery_dialog.py         Recovery UI
  pdf_viewer_controller.py   PDF viewport/navigation helper
  canvas/                    Canvas state, rendering, and interaction modules

assets/                      Fonts, icons, music, themes, OCR model assets
installer/                   Windows installer helper scripts
tests/                       Unit tests for storage, scheduling, PDF, cache,
                             review flow, UI helpers, OCR, recovery, and timer
```

## Test

Run the full test suite:

```powershell
python -m unittest discover -s tests
```

Useful focused checks:

```powershell
python -m unittest tests.test_pdf_engine tests.test_cache_manager tests.test_review_screen
python -m unittest tests.test_review_manager tests.test_sm2_engine tests.test_session_timer
python -m unittest tests.test_ocr_engine tests.test_pdf_annotation_service tests.test_recovery_manager
```

## Package

Build the desktop app with PyInstaller:

```powershell
pyinstaller --noconfirm AnkiOcclusion.spec
```

Build the Windows installer helper flow:

```powershell
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

The packaging tests assert that the spec points at `anki_occlusion_v19.py`,
collects desktop assets, and includes required Qt multimedia support.

## Troubleshooting

Slow PDF startup:

- Check the terminal for `[DEBUG][skeleton] ... mode=rect_only`.
- Check `[DEBUG][review_cache_profile]` for cache count, PDF page count, and
  zoom profile.
- If `reset_cache=True`, the app is refreshing stale render data.
- If `need=` in `[DEBUG][review_decision]` lists pages, those visible pages are
  not yet cached and are being rendered lazily.

Timer hidden or flickering:

- The floating timer only appears when the review queue drawer is hidden.
- It is raised after scroll and arrow-key page navigation so it stays above the
  PDF viewport.

OCR not working:

- Normal review does not need OCR dependencies.
- Math Trainer OCR needs the optional OCR dependency stack and model assets.

PDF annotations not appearing:

- Save the PDF in the external reader.
- Return to the app and let the PDF watcher refresh the changed document.
- If needed, reopen the card or current PDF from review mode.

## Current Desktop Highlights

- Large PDFs open into review mode much faster because skeleton layout no longer
  renders pages.
- Review mode prioritizes the current page even if it is far beyond the first
  cache window.
- Moving between nearby pages reuses canvas-real pages instead of re-rendering
  static content.
- Floating timer is larger and stays visible above the PDF when the queue drawer
  is hidden.
- PDF workers use thread-safe image objects and avoid background-thread pixmap
  creation.
- OCR prediction work is off the GUI thread.
- Tests cover the PDF loader, cache counters, review lazy-loading decisions,
  floating timer behavior, default review pen, async OCR, SM-2 scheduling, and
  recovery flows.
