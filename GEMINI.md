# Anki Occlusion Desktop App: Agent Instructions & Master Architecture

## 📌 Core Identity & Repository Scope
You are the AI Developer and Pair Programmer for the **Anki Occlusion Desktop App** (`anki_occlusion_v19.pyw`, `ui/`, `services/`, and core modules).
- **Primary Technology**: Python 3.12, PyQt5, SQLite (`~/anki_occlusion_data.db`).
- **Core Architecture**: Local-first spaced repetition with hybrid FSRS v4.5 ML engine + legacy SM-2 compatibility layer, high-performance image/PDF canvas occlusion rendering, and zero-flicker database operations.

---

## 🖥️ Mandatory Desktop UI Typography & Font Size Architecture (Strict Anti-Squint Standard)

### 1. 🚫 Absolute Ban on Small Fonts (< 18pt / 24px in Dialogs & Modals)
- **NEVER use font sizes below `18pt` (or `24px`)** for readable text, descriptions, buttons, or inputs in modal dialogs or new UI screens.
- **DPI Scaling & Anti-Blur**: Under Windows 125% Display Scaling (120 DPI), CSS `14px` resolves to a tiny ~10.5pt, causing Hindi matras and labels to appear jagged, pixelated, and unreadable.
- **Native QFont Priority**: NEVER rely solely on CSS stylesheets (`font-size: 14px`) for font sizing because theme cascades override or shrink it. ALWAYS set font sizes explicitly in Python via `widget.setFont(QFont("Segoe UI", size))`.

### 2. 🏷️ Standard 7-Tier Desktop Typography Hierarchy
Every modal dialog, settings screen, or custom tool MUST strictly conform to this visual hierarchy:
1. **Window / Modal Header (H1)**: `QFont("Segoe UI", 24..28, QFont.Black)`
2. **Section Headings (H2)**: `QFont("Segoe UI", 20..22, QFont.Bold)`
3. **Card Titles & Slider Headers (H3)**: `QFont("Segoe UI", 19..20, QFont.Bold)`
4. **Big Stat Metrics (Numbers)**: `QFont("Segoe UI", 38..46, QFont.Black)`
5. **Body Text, Hindi Tips, Descriptions**: `QFont("Segoe UI", 17..19, QFont.Normal/DemiBold)` with `setWordWrap(True)`
6. **Interactive Action Buttons**: `QFont("Segoe UI", 19..21, QFont.Bold)` with generous padding (e.g. `16px 32px` to `18px 36px`)
7. **Status Badges / Chips**: `QFont("Segoe UI", 15..16, QFont.Bold)`

### 3. 🎚️ NoWheelSlider Protocol (Zero Slider Hijacking)
- Any `QSlider` embedded inside a `QScrollArea` **MUST subclass `QSlider`** and call `event.ignore()` in `wheelEvent`:
  ```python
  class NoWheelSlider(QSlider):
      def wheelEvent(self, event):
          event.ignore()
  ```
- Mouse wheel scrolling MUST ONLY scroll the viewport vertically. It must NEVER accidentally move or alter slider values when a user scrolls past them.

### 4. ↔️ Zero Horizontal Scrollbar & Responsive Width Protocol
- **Absolute Ban on Horizontal Scrollbars**: Dialogs must NEVER require horizontal scrolling (`scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)`).
- **Mandatory Word Wrap**: All `QLabel` widgets displaying explanations, subtitles, or Hindi text MUST call `setWordWrap(True)`.
- **No Multi-Column Cramming**: Never place 3 or more text-heavy cards side-by-side horizontally. Use clean vertical stacks or 2 balanced responsive columns so layouts never overflow on standard monitor resolutions.

---

## ⚡ Memory Algorithm Standards (FSRS v4.5 & SM-2)
- **FSRS ML Priority**: All review interval calculations must prioritize FSRS v4.5 memory stability ($S$) and retrievability ($R$).
- **Subject-Wise Retention**: Support distinct target retention rates per subject (e.g. Math 85% for workload relief, GK 90% for exam recall, English 90% balanced).
- **Safe Persistence**: All user tweaks, custom weights, and subject retention mappings must persist in `store.get()` and write back non-destructively to SQLite.

---

## 🧪 Testing & Verification Protocol
- Run unit test suites before and after modifying UI or scheduler logic:
  ```powershell
  python -m unittest tests/test_review_manager.py tests/test_fsrs_engine.py
  ```
- Always verify that dialogs instantiate cleanly without geometry clipping:
  ```powershell
  python -c "from ui.fsrs_center_dialog import FSRSCenterDialog; from data_manager import store; store.load(); dlg = FSRSCenterDialog()"
  ```

---

## 🧹 Automatic Process Memory Flush Protocol (RAM Leak Prevention)
- **Automatic Flush on Close & Home Screen**:
  1. Whenever any `ReviewScreen`, `EditorDialog`, `FSRSCenterDialog`, or modal `QDialog` closes, `perf_utils.flush_process_memory()` is triggered automatically.
  2. Whenever the user is on or returns to the **Home Screen** (via `showEvent`, exiting review, or 30-second idle sweeps), all RAM page caches and buffer caches are purged automatically via `_clear_home_ram_caches()`.
- **Unlimited RAM During Active Review (`DEFAULT_RAM_PAGE_LIMIT = None`)**:
  - During an active review session, all pages of the document can stay cached in RAM for buttery-smooth 0ms navigation with zero LRU eviction stutter.
  - The second the user exits review or returns to the Home Screen, RAM is reclaimed back to the lean baseline (~90MB–130MB).
- **Components Flushed**:
  1. `fitz.TOOLS.store_shrink(100)`: Releases all PyMuPDF decompression and rendering buffer caches.
  2. `QPixmapCache.clear()`: Purges unreferenced UI/GPU pixmaps.
  3. `PAGE_CACHE.clear_ram_only()`: Clears in-RAM PDF page pixmaps.
  4. `gc.collect()`: Forces Python garbage collection to eliminate cyclic references.
- **Working-Set Goal**: Maintain app RAM between 90MB and 140MB on the Home Screen.


