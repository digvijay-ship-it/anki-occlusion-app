# Anki Occlusion 🃏

**Offline desktop image occlusion for PDFs, notes, and serious revision.**

**Anki Occlusion** is a Python + PyQt5 desktop flashcard app that brings Anki's
Image Occlusion workflow to your own local PDFs and images, with a full SM-2
spaced-repetition scheduler built in.

Draw masks over the parts of your notes you want to hide. Each mask becomes a
flashcard. Study with **Again / Hard / Good / Easy / Perfect**, annotate while
reviewing, and keep everything stored locally on your machine.

> This root README documents the mature **offline desktop app** and the planned
> commercial browser direction.
> Desktop entry point: `anki_occlusion_v19.py`

---

## Commercial Web Direction

The desktop app is the mature current product. The next commercial direction is
a browser-based paid app that can be tested locally now and deployed publicly
later.

The reason for moving the paid product to the browser is practical: piracy
resistance should come from hosted accounts, subscription entitlements, and
server-side sync gates rather than from shipping a fully copyable desktop binary.
Frontend code can still be inspected or copied, so the business value should be
protected by login, billing state, user data sync, and account-level limits.

The existing `web/` folder is a useful prototype, not the final public
architecture. It currently provides a thin FastAPI + React review console over
the desktop JSON data file. The production web app should evolve from that
prototype toward a low-cost SaaS shape.

### What Carries To Web

Carry forward directly:

- SM-2 scheduling and rating logic.
- Decks, subdecks, cards, boxes, and occlusion mask metadata.
- Due queue calculation, review states, and rating history.
- Import/export concepts for moving user study data safely.

Redesign for browser use:

- PDF/image editor and review canvas.
- Browser PDF rendering with PDF.js.
- Mask drawing, moving, resizing, grouping, and reveal behavior.
- Annotation tools, keyboard shortcuts, and local file access.
- Cache strategy using browser storage instead of desktop RAM/QPixmap caches.

Delay or drop for the first web MVP:

- PyQt-specific UI code.
- Desktop installer and PyInstaller packaging.
- Desktop file watcher and system PDF reader integration.
- Music-heavy assets and desktop theme effects.
- TensorFlow OCR and Math Trainer OCR unless there is a paid reason to carry
  the server cost.

### Low-Cost SaaS Stack

Recommended first public stack:

- **Frontend:** Vite + React hosted as static files.
- **Local testing:** Vite dev server plus the existing FastAPI backend.
- **Public launch:** static frontend plus a small FastAPI API server.
- **Database:** SQLite first for the lowest fixed cost; upgrade to Postgres only
  when real usage proves it is needed.
- **Payments:** Stripe subscription.
- **Piracy gate:** login plus active subscription entitlement checks.

The first paid version should avoid a heavy backend. The browser should perform
the expensive work wherever possible, while the server stores only the minimum
data needed to authenticate users, preserve paid value, and sync study metadata.

### Cost Strategy

Use the user's local device for heavy work:

- Render PDFs in the browser with PDF.js.
- Draw and edit masks on the client canvas.
- Cache PDF pages, previews, and working state in IndexedDB/local browser
  storage.
- Batch review activity locally before syncing.

Keep the server responsible for minimal paid-product state:

- Accounts, subscription status, and entitlement checks.
- Deck/card/mask metadata.
- Schedule state, review history, and sync revisions.
- Lightweight telemetry needed to understand cost and performance.

Avoid for the MVP:

- Server-side PDF page rendering for normal review/edit flows.
- Uploading every PDF/image to the server by default.
- Per-click server writes during review.
- Always-on background workers per user.
- Server-side TensorFlow/OCR.

PDFs and large source images should stay local/browser-side for the first public
MVP. Optional cloud PDF storage can become a paid upgrade later if users clearly
need cross-device document sync.

### Cost Monitoring

Before public deployment, add local/dev visibility for:

- API calls per user per day.
- Payload bytes sent and received.
- Database reads and writes.
- Sync frequency and batch sizes.
- Storage used per account.
- Slow routes and failed sync attempts.

Cost optimizations should be part of the product design:

- Batch sync changes instead of writing on every small action.
- Debounce autosaves from the browser.
- Sync diffs/revisions rather than full decks whenever possible.
- Use IndexedDB as the main working cache.
- Keep PDF rendering and page cache work on the user's device.

### Public API Direction

The current prototype endpoints are temporary:

```text
GET  /api/health
GET  /api/summary
GET  /api/decks
GET  /api/review/items
POST /api/review/rate
```

The paid public API should move toward:

```text
GET  /api/me              Account, plan, and entitlement status
GET  /api/sync/pull       Revision-based metadata sync
POST /api/sync/push       Batched local changes
POST /api/review/rate     Optional server-validated rating writes
POST /api/metrics/client  Lightweight cost/performance telemetry
```

Default rule: avoid per-click server writes when the browser can safely batch
changes and sync them as session-level metadata.

---

## ✨ Features

### 🧠 Study Core
- **PDF & Image Occlusion** — Load a PDF or image, draw masks over answers, and
  turn your own notes into review cards.
- **Duplicate Card Protection** — Visual similarity checking (dHash) and file byte hashes (SHA-256) prevent adding identical cards or overlapping screenshots.
- **Text & Vocabulary Cards** — Edit and review non-image Q&A cards with a dedicated text editor and study interface.
- **Local-First Syncing** — Web-client sync framework with offline queuing, transaction compaction, LWW conflict resolution, and background Google Drive sync.
- **SM-2 Spaced Repetition** — Cards move through `new → learning → review →
  relearn` states with intraday learning steps, ease-factor updates, interval
  fuzzing, and a 365-day interval cap.
- **Anki-Style Review Flow** — Cards stay hidden until you press `Space`, then
  you rate the answer with **Again / Hard / Good / Easy / Perfect**.
- **Nested Decks** — Organise subjects into decks and subdecks, such as
  `History › Ancient India › Stone Age`.
- **Grouped Masks** — Link multiple masks together so several hidden regions
  are reviewed as one card.
- **Local-First Storage** — Decks, cards, masks, review history, and scheduling
  data live in a local JSON data file.

### 📄 PDF Power
- **Fast Large-PDF Startup** — Review mode now builds its initial skeleton from
  PDF page metadata instead of rendering pages first.
- **Priority Review Page Loading** — The current review page is loaded first,
  even if it is far beyond the first cache window.
- **Visible-Page Lazy Rendering** — Missing visible pages render on demand while
  cached pages appear immediately.
- **48-Page RAM Cache + Disk Cache** — Individual rendered pages are cached in
  RAM and persisted on disk for fast repeat openings.
- **Thread-Safe PDF Workers** — Background workers create `QImage`; GUI-thread
  code converts to `QPixmap`, avoiding Qt thread-safety crashes.
- **Live PDF Sync** — Annotate a PDF in another reader, save it, and the app
  refreshes the changed document while keeping masks aligned.
- **Open in PDF Reader** — Jump from the editor or review mode to the current
  PDF in your system reader.

### ✏️ Editor
- **Rectangle, Ellipse & Text Tools** — Hide answers with rectangular masks,
  oval masks, or inline text labels.
- **Move / Resize / Rotate** — Select masks, drag them around, resize with
  handles, and rotate when needed.
- **Undo / Redo** — Safely experiment while building cards.
- **Pan & Zoom** — Use `Space+drag`, `Ctrl+Scroll`, and fit/reset zoom controls.
- **PDF Page Navigation** — Move between PDF pages with left/right arrows while
  editing.
- **Recovery Support** — Interrupted edits can be recovered instead of silently
  disappearing.

### 🎓 Review Mode
- **Default Review Pen** — Review opens with the pen active, so you can mark and
  think directly on the page.
- **Floating Study Timer** — When the queue drawer is hidden, a large floating
  timer stays above the PDF.
- **Stable Timer During Page Jumps** — Arrow-key page navigation raises the
  floating timer again after the canvas updates.
- **Canvas-Real Page Reuse** — Moving back and forth through nearby pages reuses
  already-rendered page content instead of reloading static areas.
- **Review Queue Drawer** — See current, pending, done, and learning/relearn
  cards during the session.
- **Annotation Scroll from Review** — Open the in-app PDF annotation scroll from
  the current review position.
- **Session Timer** — Focus time is tracked during review and written into the
  daily journal.

### 🧮 Math Trainer & OCR
- **Math Practice Module** — Practice tables, squares, cubes, and quick mental
  calculation.
- **Async OCR** — OCR prediction runs in a Qt worker thread so the interface
  does not freeze while TensorFlow or the local OCR worker is busy.

### 🛡️ Safety & Comfort
- **DirtyStore Autosave** — Data changes are coalesced and saved in the
  background.
- **Atomic Writes** — Saves use temp-file replacement to reduce corruption risk.
- **Backup Guards** — Risky writes create backups and safety checks prevent
  accidental empty-data overwrites.
- **Single-Instance Protection** — Prevents two app windows from writing to the
  same data file at the same time.
- **Themes, Font Scaling & Music** — Dojo/classic theme support, app-wide font
  scaling, music controls, fullscreen mode, and shortcut customization.

---

## 🚀 Installation

**Requirements:** Python 3.8+

Core desktop dependencies:

```powershell
python -m pip install PyQt5 pymupdf
```

Optional Math Trainer OCR dependencies:

```powershell
python -m pip install numpy opencv-python pillow tensorflow
```

> `pymupdf` is required for PDF support. OCR dependencies are optional unless
> you use Math Trainer prediction.

---

## ▶️ Run

From the repository root:

```powershell
python anki_occlusion_v19.py
```

If the path contains spaces:

```powershell
python "C:\path\to\Anki gs3236208\anki_occlusion_v19.py"
```

---

## 📖 How to Use

### 1 — Create a Deck
Click **+ Deck** from the home screen. Create subdecks when you want a subject
hierarchy like `SSC › History › Ancient History`.

### 2 — Add a Card
Select a deck, click **+ Add Card**, load a PDF or image, then draw masks over
the answers you want to hide.

### 3 — Review
Start review from the deck/home screen.

- Press `Space` to reveal the answer.
- Press `1` to `5` to rate your recall.
- Use left/right arrows to move between PDF pages.
- Use the default pen to mark, reason, or eliminate options while studying.

---

## ⚡ Large PDF Review Flow

The current desktop app is tuned for big PDFs, including documents where the
active review page may be far past the first 48 pages.

```text
Open review
   ↓
Build skeleton from PDF metadata
   ↓
Inject cached visible pages immediately
   ↓
Render current/visible missing pages lazily
   ↓
Reuse already-real canvas pages during navigation
```

What changed recently:

- Skeleton creation uses `mode=rect_only`, so page sizes are measured without
  rendering the first page.
- The current review page is prioritised over simple first-page loading.
- Cache counters inspect RAM, pending worker images, and disk cache without
  forcing extra pixmap loads.
- Review navigation skips pages that are already real in the canvas.
- Worker threads avoid creating `QPixmap` directly.

Useful terminal diagnostics while this performance work is being observed:

```text
[DEBUG][skeleton] ... mode=rect_only
[DEBUG][review_cache_profile]
[DEBUG][review_queue_pages]
[DEBUG][review_load]
[DEBUG][review_viewport]
[DEBUG][review_decision]
[DEBUG][review_lazy]
[DEBUG][review_inject]
[DEBUG][review_visible_cache]
```

---

## ⌨️ Keyboard Shortcuts

### 🎓 Review Mode

| Shortcut | Action |
|----------|--------|
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

### ✏️ Editor Mode

| Shortcut | Action |
|----------|--------|
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

### 📝 Annotation Scroll

| Shortcut | Action |
|----------|--------|
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

### 🏠 Home Screen

| Shortcut | Action |
|----------|--------|
| `Ctrl+S` | Save now |
| `Ctrl+Z` | Undo deck/card change |
| `Ctrl+Y` | Redo deck/card change |
| `Ctrl++` | Increase app font size |
| `Ctrl+-` | Decrease app font size |
| `Ctrl+0` | Reset app font size |
| `M` | Toggle music |
| `N` | Next music track |
| `F11` | Toggle fullscreen |

---

## 📂 Project Structure

The desktop app is split into core logic, services, UI modules, assets, and
tests.

### 🏛️ Core Architecture

```text
Anki Occlusion/
├── 🚀 anki_occlusion_v19.py   Main desktop entry point
├── 📦 models.py               Shared deck/card data helpers
├── 💾 data_manager.py         JSON storage, autosave, backups, undo history
├── 🧠 sm2_engine.py           SM-2 scheduling and rating previews
├── 📄 pdf_engine.py           PDF skeleton scan, rendering, worker threads
├── ⚡ cache_manager.py        RAM/disk page cache and cache diagnostics
├── ⏱️ session_timer.py        Review focus timer and journal integration
├── 🧭 page_scheduler.py       Lazy page scheduling helpers
├── 🎨 theme_manager.py        Theme, font, and style management
├── ⚙️ thread_manager.py       Thread lifecycle helper
├── 🛠️ storage_paths.py        User data/cache/recovery path helpers
└── 🏗️ AnkiOcclusion.spec      PyInstaller desktop packaging spec
```

### 🖥️ User Interface (`ui/`)

```text
ui/
├── 🏠 home_screen.py          Main dashboard
├── 🗂️ deck_tree.py            Deck hierarchy sidebar
├── 📊 deck_view.py            Deck detail/actions view
├── ✏️ editor_dialog.py        Card editor and PDF/image occlusion editor
├── 🎓 review_screen.py        Review mode
├── 📓 journal.py              Journal and focus view
├── 🧮 math_trainer.py         Math practice module
├── 📝 pdf_annotation_dialog.py In-app PDF annotation scroll
├── ⌨️ shortcut_dialog.py      Shortcut settings dialog
├── 🧯 recovery_dialog.py      Recovery UI
├── 📄 pdf_viewer_controller.py PDF viewport/navigation helper
│
└── 🖌️ canvas/
    ├── 🧩 core.py             Canvas core widget
    ├── 🕹️ interaction.py      Mouse/keyboard drawing interactions
    ├── 🖼️ renderer.py         Background pages, masks, and pen rendering
    └── 🧠 state.py            Canvas state, selection, undo/redo, cache
```

### ⚙️ Background Services (`services/`)

```text
services/
├── 🔄 review_manager.py       Review queue/session state
├── ⌨️ shortcut_manager.py     Shortcut registry and persistence
├── 👁️ ocr_engine.py           Async OCR bridge
├── 🧠 tf_worker.py            TensorFlow OCR worker
├── 🧪 local_ocr_server.py     Local OCR server helper
├── 👀 pdf_watcher.py          External PDF change watcher
├── 📝 pdf_annotation_service.py PDF annotation read/write service
├── 🧯 recovery_manager.py     Recovery event and draft handling
└── 📓 journal_manager.py      Journal persistence helpers
```

### 🖼️ Assets

```text
assets/
├── fonts/                     App fonts
├── icons_sliced/              Icon assets
├── model/                     Math Trainer OCR model/server assets
├── music/                     UI sound/music assets
└── themes/dojo/               Dojo theme images and overlays
```

### 🧪 Tests

```text
tests/
├── test_pdf_engine.py         PDF skeleton/render worker behavior
├── test_cache_manager.py      RAM/pending/disk cache behavior
├── test_review_screen.py      Review UI helpers, timer, default pen
├── test_zoom.py               Review/editor zoom and PDF navigation helpers
├── test_sm2_engine.py         Scheduling logic
├── test_data_manager.py       Storage and safety checks
├── test_ocr_engine.py         Async OCR bridge
├── test_recovery_manager.py   Recovery event handling
└── ...                        Additional UI/service/package tests
```

---

## 🧪 Run Tests

Full suite:

```powershell
python -m unittest discover -s tests
```

Focused checks:

```powershell
python -m unittest tests.test_pdf_engine tests.test_cache_manager tests.test_review_screen
python -m unittest tests.test_review_manager tests.test_sm2_engine tests.test_session_timer
python -m unittest tests.test_ocr_engine tests.test_pdf_annotation_service tests.test_recovery_manager
```

---

## 📦 Build Desktop App

Build with PyInstaller:

```powershell
pyinstaller --noconfirm AnkiOcclusion.spec
```

Build the Windows installer helper flow:

```powershell
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

---

## 📍 Data Location

Main data file:

| Platform | Path |
|----------|------|
| Windows | `C:\Users\<YourUser>\anki_occlusion_data.json` |
| macOS | `~/anki_occlusion_data.json` |
| Linux | `~/anki_occlusion_data.json` |

Persistence behavior:

- Autosave runs when data is dirty.
- Saves are atomic.
- Backups protect risky writes.
- Empty-data overwrite guards are active.
- Recovery events can be replayed after interrupted review work.

---

## 🧭 Troubleshooting

### Slow PDF Review Load
- Look for `[DEBUG][skeleton] ... mode=rect_only`.
- Check `[DEBUG][review_cache_profile]` for page count, cached count, zoom, and
  cache reset state.
- If `[DEBUG][review_decision]` shows pages in `need=`, those visible pages are
  not cached yet and are being lazily rendered.

### Floating Timer Missing
- The floating timer appears when the review queue drawer is hidden.
- It is raised again after scroll/page navigation so it stays above the PDF.

### OCR Not Working
- Normal PDF/image review does not need OCR.
- Math Trainer OCR needs the optional OCR dependencies and model assets.

### External PDF Notes Not Showing
- Save the PDF in the external reader.
- Return to the app and let the file watcher refresh it.
- Reopen the card/PDF if the external reader delays writing changes to disk.

---

## 📦 Version History

| Version | Highlights |
|---------|------------|
| Current | Visual similarity (dHash) & byte check (SHA-256) duplicate card protection, Text/Q&A Card creator & review flow, local-first web sync engine with transactional compaction, thread-safe merge-on-save daily journal, viewport-scoped mask cache & scroll paint fixes, O(1) deck stats cache, fast deepcopy undo/redo snapshots, on-demand OCR lifecycle (54MB boot memory) with animated theme-aware loading toast |
| v19 | SM-2 Hard/EF/fuzzing fixes, DirtyStore autosave, review queue panel, learning countdown, session summary, tablet-friendly pan |
| v18 | Hardware mask cache and LRU page cache |
| v17 | Progressive chunk loading and RAM cache improvements |
| v16 | PDF loading moved to background threads |
| v15 | Native hardware painting and review queue bug fixes |
| v14 | Hide One Guess One, ellipse/text tools, move/resize/rotate |
| v13 | Live PDF Sync and Open in PDF Reader |
| v12 | Anki-style reveal flow, pinch zoom, center-on-mask, dynamic font size, onboarding |
| v11 | SM-2 learning/relearn scheduler |
| v10 | Mask colors, group/ungroup, multi-select |
| v9 | Initial public release |

---

**Consistency beats cramming. Build the deck once, let the scheduler carry the revision.** 🔥
