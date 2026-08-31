# Anki Occlusion 🃏

**Offline desktop image occlusion for PDFs, notes, vocabulary, exam papers, and serious revision.**

**Anki Occlusion** is a high-performance Python + PyQt5 desktop flashcard application that combines Anki's Image Occlusion workflow with native Text/Vocabulary flashcards, Testbook/Exam MCQ practice, and a full SM-2 spaced-repetition scheduler.

Draw masks over parts of your PDF notes to hide answers, import entire vocabulary directory trees with automatic sub-decks, solve interactive 4-option MCQs with detailed explanations, and review with **Again / Hard / Good / Easy / Perfect**. Everything is stored locally on your machine with zero cloud dependency and non-destructive spaced repetition sync.

> Desktop entry point: `anki_occlusion_v19.py`

---

## ✨ Key Features

### 🧠 Study Core & Spaced Repetition (SM-2)
- **PDF & Image Occlusion** — Load a PDF or image, draw masks over answers, and turn your own notes into review cards.
- **Smart Grouped Masks (1 Group = 1 Card)** — Link multiple masks into a group (e.g. an 8-cell table). Reviewed and rated together as **1 single card review unit** so daily performance statistics reflect true study effort without exaggeration.
- **SM-2 Engine** — Cards transition through `new → learning → review → relearn` states with configurable intraday learning steps, ease-factor updates, interval fuzzing, and a 365-day interval cap.
- **Non-Destructive Incremental Deck Sync** — Sync updated word lists, new definitions, or typo fixes from local folders with **1-click**. All existing cards keep 100% of their learning history, intervals, repetition counts, and scheduled due dates.
- **Duplicate Card Protection** — Visual similarity checking (dHash) and file byte hashes (SHA-256) prevent adding identical cards or overlapping screenshots.
- **Local-First Storage** — Decks, cards, masks, review history, and scheduling data live safely in local JSON/SQLite storage.

### 📂 Smart Batch Folder Importer & Auto Sub-Decks
- **Recursive Directory Scanning** — Recursively scans folder trees for `.csv`, `.tsv`, `.txt`, and `.json` files.
- **Auto Sub-Deck Hierarchy** — Automatically mirrors your directory structure into nested sub-decks (e.g., `Part_A_One_Word_Substitutions::A1_All_OWS::A`, `...::B`, etc.) or merges into a master deck with auto-tags.
- **Natural Alphanumeric Sorting** — Automatically sorts files in natural human order (`A.csv` ... `Z.csv`, `1.csv`, `2.csv`, `10.csv`).
- **Intelligent Ignore Filter** — Automatically excludes documentation and system files (`Instruction.txt`, `INSTRUCTIONS.md`, `README.md`, `LICENSE`, `requirements.txt`, etc.), preventing empty decks or junk cards.
- **Multi-Tab Import Center** — Import via pasted raw text, single files, JSON chained cards, Testbook MCQ JSON, or recursive directory trees with live table previews and auto-delimiter detection.

### 📖 Text & Vocabulary Review (`TextReviewWidget`)
- **Rich HTML & Mnemonic Styler** — Renders rich formatting, `<br>`, `<b>`, and emojis cleanly with dedicated styled callout pills:
  - 💡 **Mnemonics Callout** — Amber/gold pill box highlighting memory tricks.
  - 📝 **Example Callout** — Emerald/green pill box highlighting contextual example sentences.
- **Exam Strategy Badges** — Dynamic visual badges for 🔥 **80/20 CORE** (high-yield questions), ⚡ **80/20 DETAIL** (supporting concepts), 📌 **Topic Context**, and 🔗 **Sequential Linked Chains**.
- **Integrated Drawing Scratchpad** — Floating drawing canvas for quick handwriting, calculations, and active recall with instant clear (`Ctrl+Del`).

### 🎯 Interactive Exam MCQ Engine (`MCQReviewWidget`)
- **Interactive Option Selection** — Clickable `[ A ]`, `[ B ]`, `[ C ]`, `[ D ]` option buttons with instant keyboard shortcuts (`A`, `B`, `C`, `D` or `1`, `2`, `3`, `4`).
- **Instant Visual Feedback** — Highlights selected choices in Green (Correct) or Red (Incorrect) with correct answer revelations.
- **Comprehensive Solution Cards** — Renders Testbook-grade explanations:
  - 📌 Statement and Key Points
  - 📝 Additional Information
  - 📌 Important Points & Chronological Tables
- **Exam Telemetry** — Shows average exam completion time, question marks, and historical accuracy percentages.

### 🔍 Universal Persistent Zoom & Font Scaling
- **Universal Storage** — Any zoom adjustments made during Text Review, MCQ Review, or PDF/Image Occlusion (via `Ctrl + Wheel`, `Ctrl++`, `Ctrl+-`, trackpad pinch, or toolbar buttons) are immediately saved to permanent application settings.
- **Cross-Deck Consistency** — Zoom level remains active across all decks and subjects.
- **Cross-Restart Persistence** — Closing and relaunching the app preserves your exact preferred zoom factor and font size.
- **Live Shortcut Delegation** — `Ctrl++`, `Ctrl+-`, and `Ctrl+0` dynamically scale the active text, MCQ, or canvas viewport.

### 📍 Hint & Note Panel Coordinate Memory
- **Per-Question Scroll Memory** — Pressing `N` to open the hint/notes drawer, scrolling down to read, and pressing `N` to close it preserves the exact vertical scroll coordinate in RAM.
- **Instant Resume** — Reopening `N` on the same card resumes reading from the exact location where you left off.
- **Automatic Question Transition Reset** — Transitioning to the next or previous card automatically clears the RAM cache and resets the scroll position to the top (coordinate 0) for the new question.

### 📄 PDF Power & Rendering Engine
- **Fast Large-PDF Startup** — Builds initial page skeletons from PDF metadata (`mode=rect_only`) without blocking GUI threads.
- **Priority Review Page Loading** — Loads the current review page first, even if it is deep in a 1,000+ page book.
- **48-Page RAM Cache + Disk Cache** — Caches rendered pages in RAM and persists them on disk for instant repeat openings.
- **Thread-Safe PDF Workers** — Background workers render `QImage`, safely converted to `QPixmap` on the GUI thread.
- **Live PDF Sync** — Annotate a PDF in an external reader (like Acrobat or PDF-XChange), save it, and the app live-refreshes masks and pages.

### ✏️ Card Editor
- **Drawing Tools** — Hide answers with Rectangles, Ellipses, or inline Text labels.
- **Transform Controls** — Select, move, resize with corner handles, and rotate masks at any angle.
- **Background & Inline Cropping** — Crop card background images or right-click any inline image to crop whitespace directly inside the editor.
- **Undo / Redo** — Dedicated history stack for error-free card creation.
- **Crash Recovery Drafts** — Automatic debounced drafts protect unsaved masks from unexpected power cuts or app quits.

### 📊 Performance, Daily Journal & Mission Reports
- **Daily Performance Report Card** — Full-screen mission report with collapsible deck hierarchy tree, retention rate, rating breakdown, and study rank.
- **Session Focus Timer** — Tracks focused study duration while review mode is active and logs daily focus time to the journal.
- **Card Manager & Browser (`Ctrl+B`)** — Search, inspect, bulk-delete, and export cards to CSV or plain word lists.

### 🎨 Themes & Comfort
- **Four Distinct Themes**:
  - 🏯 **Dojo Theme** — High-contrast martial study aesthetics.
  - 🔮 **Arcanum Magic Theme** — Cinzel typography, interactive procedural sigils, and animated rune particle effects.
  - 🌃 **TMNT / Manhattan Theme** — Cyberpunk neon palette.
  - 🌌 **Classic Theme** — Clean modern dark theme.
- **Persistent Fullscreen State (`F11`)** — Remembers and automatically restores fullscreen mode on launch.
- **Shortcut Help Dialog (`Ctrl+?`)** — Interactive modal cheat sheet for all navigation, rating, and editing shortcuts.

---

## 🚀 Installation & Setup

### Requirements
- **Python:** 3.8 to 3.12
- **Operating System:** Windows, macOS, or Linux

### Core Dependencies
```powershell
python -m pip install PyQt5 pymupdf
```

### Optional Dependencies (OCR & Advanced Tools)
```powershell
python -m pip install numpy opencv-python pillow tensorflow
```

---

## ▶️ Running the Application

From the repository root directory:

```powershell
python anki_occlusion_v19.py
```

If your directory path contains spaces:
```powershell
python "C:\path\to\Anki gs3236208\anki_occlusion_v19.py"
```

---

## ⌨️ Keyboard Shortcuts Reference

### 🎓 Review Mode (Text, MCQ & Image Occlusion)

| Shortcut | Action |
|---|---|
| `Space` | Reveal answer / Submit MCQ |
| `1` | Rate Again (1 min) / Select Option A |
| `2` | Rate Hard (5 min) / Select Option B |
| `3` | Rate Good (10 min) / Select Option C |
| `4` | Rate Easy (4 days) / Select Option D |
| `5` | Rate Perfect (7 days) |
| `A`, `B`, `C`, `D` | Select MCQ options directly |
| `N` | Toggle Hint / Mask Note drawer (with scroll memory) |
| `Ctrl+N` | Quick edit active mask note |
| `Ctrl++` / `Ctrl+-` | Universally Zoom In / Zoom Out |
| `Ctrl+0` | Reset Zoom to 100% / Auto-Fit |
| `Left` / `Right` | Previous / Next PDF page |
| `C` | Center view on active mask |
| `S` | Skip card for current session |
| `Alt+S` | Super Skip card for today |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo review rating |
| `T` | Open In-App PDF Annotation Scroll |
| `Ctrl+E` | Open current PDF in system reader |
| `Ctrl+L` | Open containing folder in file explorer |
| `Ctrl+Shift+E` | Edit current card in Editor |
| `` ` `` | Toggle Review Pen |
| `X` | Cycle Pen Color |
| `+` / `-` | Adjust Pen Width |
| `Del` | Clear review pen marks |
| `Alt+T` | Toggle floating study timer |
| `F11` | Toggle Fullscreen |
| `Ctrl+?` | Open Keyboard Shortcut Cheat Sheet |
| `Esc` | Return to Deck View / Home Screen |

### ✏️ Editor Mode

| Shortcut | Action |
|---|---|
| `V` | Select / Transform tool |
| `R` | Rectangle Mask tool |
| `E` | Ellipse Mask tool |
| `T` | Text Label tool |
| `G` | Group selected masks into 1 card |
| `Shift+G` | Ungroup selected masks |
| `Ctrl+A` | Select all visible masks |
| `Ctrl+Shift+A` | Select all masks on page |
| `Del` | Delete selected masks |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo mask edits |
| `Ctrl+Scroll` | Zoom canvas |
| `Space + Drag` | Pan canvas |
| `Left` / `Right` | Previous / Next PDF page |

### 🏠 Home Screen & Deck Management

| Shortcut | Action |
|---|---|
| `Ctrl+S` | Save data now |
| `Ctrl+B` | Open Card Manager / Browser |
| `A` | Add new card to selected deck |
| `E` | Edit selected card |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo deck structure changes |
| `M` | Toggle background music |
| `N` | Next background music track |
| `Ctrl++` / `Ctrl+-` | Scale UI font size |
| `F11` | Toggle Fullscreen |

---

## 📂 Project Architecture

```text
Anki Occlusion/
├── 🚀 anki_occlusion_v19.py       Main desktop application entry point
├── 📦 models.py                   Dataclass models (Card, Box, Deck, MCQ metadata)
├── 💾 data_manager.py             Database engine, folder tree scanner, non-destructive sync, autosave
├── 🧠 sm2_engine.py               SM-2 Spaced Repetition calculation & scheduling
├── 📄 pdf_engine.py               Fast metadata skeleton builder, multi-threaded PDF rendering
├── ⚡ cache_manager.py            RAM/Disk page caching and memory-mapped cache
├── ⏱️ session_timer.py            Focus timer engine and journal daily focus logger
├── 🎨 theme_manager.py            Theme palette definitions, font loaders, and CSS stylers
├── 🛠️ storage_paths.py            User directories, QSettings storage, archive paths
│
├── 🖥️ ui/                         User Interface Components
│   ├── 🏠 home_screen.py          Dashboard, statistics, and deck overview
│   ├── 🗂️ deck_tree.py            Collapsible deck hierarchy sidebar with right-click sync
│   ├── 📊 deck_view.py            Deck review launcher and study overview
│   ├── 🎓 review_screen.py        Unified Review interface with queue drawer and hint memory
│   ├── 📖 text_review_widget.py   Rich text & vocabulary reviewer with mnemonic callout styling
│   ├── 🎯 mcq_review_widget.py    Interactive Testbook MCQ exam paper reviewer
│   ├── 📂 import_cards_dialog.py  Multi-tab card importer (text, files, JSON, MCQs, batch folder)
│   ├── 📋 card_browser_dialog.py  Card manager, CSV exporter, and bulk editor
│   ├── ✏️ editor_dialog.py        PDF & image occlusion mask editor
│   ├── ✂️ crop_dialog.py          Image cropping and whitespace trimmer
│   ├── 📝 quick_note_dialog.py    Ink canvas and quick note drawer
│   ├── 📊 mission_report_dialog.py Full-screen daily study mission report card
│   ├── 📓 journal.py              Daily study journal and focus calendar
│   └── ⌨️ shortcut_dialog.py      Shortcut cheat sheet & customization modal
│
├── ⚙️ services/                   Background Services
│   ├── 🔄 review_manager.py       Review queue scheduler, rating dispatcher, undo/redo stack
│   ├── 📊 activity_stats.py       True review aggregation engine (1 group = 1 review unit)
│   ├── ⌨️ shortcut_manager.py     Global shortcut dispatcher and JSON persistence
│   ├── 👁️ ocr_engine.py           Async OCR thread bridge
│   ├── 🧯 recovery_manager.py     Crash recovery, draft persistence, and event replay
│   └── 📓 journal_manager.py      Atomic journal read/write and backup manager
│
└── 🧪 tests/                      Automated Unit Test Suites
    ├── test_folder_import_and_sync.py  Batch folder import and non-destructive SM-2 sync
    ├── test_hint_scroll_coordinate.py  Per-question hint scroll coordinate memory
    ├── test_activity_stats.py          Single-unit review counting for grouped cards
    ├── test_text_cards.py              Text flashcard rendering, HTML styling, and persistent zoom
    ├── test_mcq_cards.py               Testbook MCQ parser, option selection, and persistent zoom
    ├── test_import_cards.py            Duplicate skipping, delimiter parsing, and import modes
    ├── test_review_manager.py          Queue manipulation, SM-2 updates, and undo/redo
    └── test_sm2_engine.py              SM-2 intervals, ease factors, and due dates
```

---

## 🧪 Running Automated Tests

Run the complete test suite:

```powershell
python -m unittest discover -s tests -v
```

Run targeted feature test suites:

```powershell
# Folder import, non-destructive sync, and hint scroll memory
python -m unittest tests/test_folder_import_and_sync.py tests/test_hint_scroll_coordinate.py -v

# Text cards, MCQ exam cards, and persistent zoom
python -m unittest tests/test_text_cards.py tests/test_mcq_cards.py -v

# Review stats, journal, and mission reports
python -m unittest tests/test_activity_stats.py tests/test_journal.py tests/test_mission_report_dialog.py -v
```

---

## 📍 Local Data & Backup Paths

| Platform | Primary Data Location |
|---|---|
| Windows | `C:\Users\<YourUser>\anki_occlusion_data.json` (or `.db`) |
| macOS | `~/anki_occlusion_data.json` |
| Linux | `~/anki_occlusion_data.json` |

- **Automatic Backups**: Created automatically before any file write in `~/backups/`.
- **Atomic File Writing**: Temporary file replacement prevents file corruption if power cuts occur during saves.
- **Crash Recovery**: Interrupted review sessions or mask drafts can be restored via Recovery Manager.

---

## 📦 Version History

| Version | Key Highlights |
|---|---|
| **Current** | **Universal Persistent Zoom** across all text/MCQ/image cards and app restarts; **Single-Unit Grouped Reviews** (1 group = 1 review) in Daily Reports; **Hint Panel Coordinate Memory** (`N` key) with auto-reset on question transition; **Recursive Batch Folder Importer** with natural sorting and auto sub-decks; **Non-Destructive Incremental SM-2 Sync**; **Rich HTML & Mnemonic / Example Visual Styler**; **Testbook Interactive MCQ Engine**; Persistent fullscreen preference; Crop canvas whitespace trimming; Arcanum Magic theme. |
| **v21** | Optimized incremental Google Drive backup, restore, and prune operations with O(1) folder caching, folder contents batching, local-first cache pre-filtering, thread-safe Qt GUI signal-slot updates. |
| **v20** | Visual similarity (dHash) & byte check (SHA-256) duplicate card protection; Text/Q&A Card creator & review flow; local-first web sync engine with transactional compaction; thread-safe merge-on-save daily journal; viewport-scoped mask cache & scroll paint fixes; O(1) deck stats cache; fast deepcopy undo/redo snapshots; on-demand OCR lifecycle. |
| **v19** | SM-2 Hard/EF/fuzzing fixes, DirtyStore autosave, review queue panel, learning countdown, session summary, tablet-friendly pan. |
| **v18** | Hardware mask cache and LRU page cache. |
| **v17** | Progressive chunk loading and RAM cache improvements. |
| **v16** | PDF loading moved to background worker threads. |
| **v15** | Native hardware painting and review queue bug fixes. |
| **v14** | Hide One Guess One, ellipse/text tools, move/resize/rotate. |
| **v13** | Live PDF Sync and Open in PDF Reader. |
| **v12** | Anki-style reveal flow, pinch zoom, center-on-mask, dynamic font size, onboarding. |
| **v11** | SM-2 learning/relearn scheduler. |
| **v10** | Mask colors, group/ungroup, multi-select. |
| **v9** | Initial public release. |

---

**Consistency beats cramming. Build the deck once, let the scheduler carry the revision.** 🔥
