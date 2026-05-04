# Anki Occlusion 🃏

**Anki Occlusion** is a desktop flashcard app built with Python and PyQt5 that brings Anki's Image Occlusion feature to your own PDFs and images — with a full SM-2 spaced repetition scheduler built in.

Draw rectangles over the parts of your notes you want to hide. Each rectangle becomes a flashcard. Study them with the same Again / Hard / Good / Easy flow as real Anki — no typing required.

---

## ✨ Features

### Core
- **PDF & Image Occlusion** — Load any PDF or image, drag masks over what you want to hide, and each mask becomes its own flashcard question automatically.
- **SM-2 Spaced Repetition** — Full Anki-style scheduler with intraday learning steps and graduated review intervals. Cards move through `new → learning → review → relearn` states exactly like real Anki.
- **Anki-Style Review Flow** — Cards show with all masks hidden. Press `Space` to reveal, then rate yourself: **Again / Hard / Good / Easy**. Rating buttons only appear after you reveal — just like Anki.
- **Hide One, Guess One** — Toggle between "Hide All, Guess One" and "Hide One, Guess One" modes during review sessions.
- **Nested Decks** — Create decks and sub-decks to organise your subjects (e.g. `Biology › Chapter 3 › Cell Division`). Right-click for deck options.
- **Grouped Masks** — Link multiple masks together so they are reviewed as a single card.
- **Auto-Save** *(v19)* — DirtyStore background thread auto-saves every 60 seconds. Data is never lost even if the app crashes mid-session.

### SM-2 Scheduler *(v19 fixes)*
- **Hard button fixed** — Now correctly shows 5m (midpoint) instead of 1m in the learning phase.
- **Discrete EF penalties** — Again −0.20, Hard −0.15, Good 0.00, Easy +0.15 (Anki-accurate).
- **Interval fuzzing** — Small random offset added to review intervals to prevent card pile-ups.
- **365-day cap** — Intervals never grow beyond one year.

### PDF Features
- **Live PDF Sync** *(v13)* — The editor watches the file for changes. Annotate in any external app (Foxit, Adobe, Drawboard, Xodo), save there, and the editor auto-reloads within 800ms — masks stay in place.
- **Open in PDF Reader** *(v13)* — One-click button opens the current PDF in your system default reader.
- **Progressive Background Loading** *(v16 & v17)* — Large PDFs load in a background thread in chunks. The UI never freezes, and you can start working immediately while the rest loads silently.
- **LRU Page Cache** *(v18)* — Individual pages are cached (max 15 in RAM). Switching between Edit and Review mode is instant with zero disk I/O on cache hits.

### Editor
- **Toolbar** — Vertical toolbar to switch between Select (V), Rectangle (R), Ellipse (E), and Text (T) tools.
- **Ellipse & Text Tools** — Draw oval/circular masks and label them inline.
- **Pan Navigation** *(v19)* — Hold `Space` + drag to pan (Photoshop-style). Press `H` to lock/unlock pan mode. Works with mouse, trackpad, and **XP Pen / drawing tablet stylus**.
- **Pinch-to-Zoom** — Ctrl+Scroll or trackpad pinch zooms the canvas in both editor and review.
- **Undo / Redo** — Full undo stack (Ctrl+Z / Ctrl+Y).
- **Select, Move, Resize & Rotate** — Click to select, drag to move, 8 handles to resize, top circular handle to rotate.
- **Zero-Lag Drawing** — Native hardware painting eliminates mouse lag when drawing or moving masks.
- **Dynamic Font Size** — A− / A / A+ buttons scale the entire app font. Saved and restored on next launch.

### Review
- **Review Queue Panel** *(v19)* — Right-side panel shows the full session queue with live status: current (green), done (dim), pending, and relearn (orange) states.
- **Learning Card Countdown** *(v19)* — When all pending cards are done but learning cards still have time left, the session shows a live countdown ("⏳ 1 card in learning — next due in 0m 45s") instead of ending early. The card appears automatically when due.
- **Session Summary** *(v19)* — After each session a stats dialog shows a colored retention bar (Again / Hard / Good / Easy segments), per-rating counts, retention %, and total reviewed.

### Other
- **First-Launch Wizard** — A short onboarding tour on first use explains the workflow.
- **App Icon** — Programmatically generated; no external image file needed.
- **Crash-Safe Storage** — Atomic write (temp file + rename) guarantees data is never corrupted even on a crash mid-save.
- **Single-Instance Lock** — Only one window can open at a time.

---

## 📂 Project Structure

Following the recent refactoring, the application is highly modularised:

### 🏛️ Core Architecture
These are the foundational files that run the application, manage data, and handle the core spaced repetition logic.

```text
Anki Occlusion/
├── 🚀 anki_occlusion_v19.py   Main entry point that launches the application
├── 📦 models.py               Defines core data structures (Decks, Cards, Occlusions)
├── 💾 data_manager.py         Handles loading, saving, and managing the local database
├── 🧠 sm2_engine.py           Implements the SuperMemo-2 (SM-2) spaced repetition algorithm
├── 📄 pdf_engine.py           Parses and renders PDF pages into images for occlusion
├── ⚡ cache_manager.py        Caches rendered PDFs and images for lightning-fast loading
├── ⏱️ session_timer.py        Tracks active focus and study time during review sessions
├── 🎨 theme_manager.py        Manages application themes, colors, and styling modes
├── ⚙️ thread_manager.py       Orchestrates background workers (keeps the UI responsive)
└── 🏗️ AnkiOcclusion.spec      Build specification for compiling the executable
```

### 🖥️ User Interface (`ui/`)
This folder contains the presentation layer and all the interactive Qt widgets you see on the screen.

```text
ui/
├── 🏠 home_screen.py          The main dashboard (integrates navigation & sidebars)
├── 🗂️ deck_tree.py            Sidebar widget displaying your hierarchy of decks
├── 📊 deck_view.py            Central view showing stats and options for the selected deck
├── ✏️ editor_dialog.py        The studio where you create cards and draw occlusion masks
├── 🎓 review_screen.py        The study interface (flipping cards, grading your memory)
├── 📓 journal.py              Displays daily study logs, streaks, and focus times
├── 🧮 math_trainer.py         Standalone module for practicing tables, squares, and cubes
│
└── 🖌️ canvas/                 Specialized module for the image occlusion drawing area
    ├── 🧩 core.py             Base definitions and core structures for the canvas
    ├── 🕹️ interaction.py      Handles mouse/keyboard events (drawing, panning, zooming)
    ├── 🖼️ renderer.py         Paints the background image and draws masks on top
    └── 🧠 state.py            Manages canvas state, selected shapes, and undo/redo history
```

### ⚙️ Background Services (`services/`)
These modules run behind the scenes to orchestrate complex logic away from the UI.

```text
services/
├── 🔄 review_manager.py       Orchestrates review sessions (fetching due cards, processing answers)
├── 📈 journal_manager.py      Handles data storage for the daily journal and focus stats
└── 👁️ pdf_watcher.py          Monitors imported PDF files for external modifications
```

### 🖼️ Assets (`assets/`)
Static resources like images, icons, and theme files.

```text
assets/
└── 🎨 themes/
    └── 🥷 dojo/               Backgrounds and UI elements for the specialized "Ninja" theme
        ├── Cyber_ninja_turtle...
        ├── Fantasy_ninja_UI...
        └── panel_overlay.png
```

### 🧪 Tests (`tests/`)
Automated test suites to ensure the application remains stable as new features are added.

```text
tests/
├── ⏱️ test_session_timer.py   Verifies that focus time is tracked accurately
├── 🧠 test_sm2_engine.py      Ensures the SM-2 algorithm calculates intervals correctly
├── 📄 test_pdf_engine.py      Checks that PDFs are parsed and rendered properly
└── 🏗️ test_packaging.py       Verifies the application builds correctly
```

---

## 🚀 Installation

**Requirements:** Python 3.8+

```bash
pip install PyQt5 pymupdf
```

> `pymupdf` is needed for PDF support. If you only use images, you can skip it.

**Run:**

```bash
python anki_occlusion_v18.pyw
```

On Windows PowerShell with spaces in the path:
```powershell
python "C:\path with spaces\anki_occlusion_v18.pyw"
```

**Run tests:**

```bash
python -m unittest discover -s tests -v
```

---

## 📖 How to Use

### 1 — Create a Deck
Click **＋ Deck** in the left sidebar. To nest it, select a parent deck first and click **＋ Sub**.

### 2 — Add a Card
Select a deck → click **＋ Add Card** → load a PDF or image → drag rectangles over the content you want to hide → click **💾 Save Card**.

**Tip for PDFs:** Click **📂 Open in PDF Reader** to annotate in Foxit / Adobe / Drawboard, save there, and the editor auto-reloads within a second. Then draw your masks on top.

### 3 — Review
Click **🔴 Review Due** to study cards that are due today.
- Press `Space` to reveal the answer
- Press `1` Again · `2` Hard · `3` Good · `4` Easy to rate

The queue panel on the right shows all cards in the session with live status. The scheduler decides when you'll see each card next — minutes for new cards, days or weeks for well-known ones.

---

## ⌨️ Keyboard Shortcuts

### Review Mode

| Shortcut | Action |
|----------|--------|
| `Space` | Reveal answer |
| `1` | Again |
| `2` | Hard |
| `3` | Good |
| `4` | Easy |
| `C` | Center view on active mask |
| `E` | Edit current card |
| `Ctrl` + `Scroll` | Zoom in / out |
| `Ctrl` + `+` / `-` / `0` | Zoom in / out / fit |
| `Space` + drag | Pan canvas |
| `H` | Toggle pan mode lock |
| `F11` | Toggle fullscreen |

### Editor Mode

| Shortcut | Action |
|----------|--------|
| `V` | Select tool |
| `R` | Rectangle tool |
| `E` | Ellipse tool |
| `T` | Text / Label tool |
| `Ctrl` + `Z` | Undo |
| `Ctrl` + `Y` | Redo |
| `Ctrl` + `A` | Select visible masks |
| `Ctrl` + `Shift` + `A` | Select all masks |
| `G` | Group selected masks |
| `Shift` + `G` | Ungroup selected masks |
| `Del` | Delete selected mask(s) |
| `Ctrl` + `Scroll` | Zoom canvas |
| `Space` + drag | Pan canvas |
| `H` | Toggle pan mode lock |

### Home Screen

| Shortcut | Action |
|----------|--------|
| `Ctrl` + `+` | Increase font size |
| `Ctrl` + `-` | Decrease font size |
| `Ctrl` + `0` | Reset font size |
| `F11` | Toggle fullscreen |

---

## 🔴 Live PDF Sync — Workflow

1. Open the Card Editor and load a PDF
2. Click **📂 Open in PDF Reader** — your PDF opens in Foxit / Adobe / Drawboard / Xodo
3. Draw highlights, underlines, circles, text — whatever you like
4. **Save** in your PDF reader (`Ctrl+S`)
5. The editor shows **🟡 change detected…** then reloads within a second
6. Your annotated PDF is now displayed — draw occlusion masks on top

Works with any app that saves to the same file path, including Foxit, Adobe Acrobat, Drawboard, Xodo, PDF-XChange Editor, and Inkscape.

---

## 📂 Data Location

All decks, cards, and scheduling data are stored in a single JSON file:

| Platform | Path |
|----------|------|
| Windows | `C:\Users\<YourUser>\anki_occlusion_data.json` |
| macOS | `~/anki_occlusion_data.json` |
| Linux | `~/anki_occlusion_data.json` |

Auto-saves every 60 seconds when data has changed. A final save is always performed on app close.

---

## 📦 Version History

| Version | Highlights |
|---------|-----------|
| v19 | SM-2 Hard/EF/fuzzing fixes; DirtyStore autosave; session bugs fixed (Again card, X-button save loss); queue panel; learning countdown; session summary; Space+drag & H pan (tablet/stylus support); async PDF in review; performance fixes |
| v18 | Hardware mask cache (GPU-backed offscreen layer, ~3× FPS); LRU page cache (RAM from ~2GB → ~300MB for large PDFs) |
| v17 | Progressive chunk loading (start working instantly), ultra-fast RAM caching |
| v16 | PDF background loading in QThread (fixes "Not Responding" freezes) |
| v15 | Native hardware painting (zero-lag drawing), SM-2 queue/duplicate bug fixes |
| v14 | Hide One Guess One mode, Ellipse & Text tools, object move/resize/rotate |
| v13 | Live PDF Sync, Open in PDF Reader, debounce reload, clean watcher teardown |
| v12 | Anki-style reveal flow, pinch zoom, center-on-mask, dynamic font size, onboarding wizard, app icon, About dialog |
| v11 | Anki-style SM-2 scheduler (learning steps, relearn), improved review UX |
| v10 | Mask colors fixed, group/ungroup from deck view, shift+click multi-select |
| v9  | Initial public release |

---

*Consistency beats cramming! 🔥*
