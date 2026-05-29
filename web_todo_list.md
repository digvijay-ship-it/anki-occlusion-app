# Web Todo List & Comparison: Anki Occlusion

This file documents the complete workflow of the mature desktop app, compares it to the web app, and lists the required features to make the web implementation complete.

---

## 🔍 Part 1: How the Local App Works (Flow & Functionality)

```text
               [ HOME SCREEN ]
               /      |      \
     Create Deck   Select Deck  Settings (Themes, Scale)
         |            |
     + Add Card    [ STUDY MODE (ReviewScreen) ]
         |            |
  Load PDF/Image   Reveal Mask (Space)
         |            |
   Draw Masks      Rate (1-5 Again to Perfect)
         |            |
  Group/Edit Masks   Draw/Annotate on Canvas
         |            |
     Save Card     Review Summary
```

### 1. Database & Lifecycle
- **JSON Storage (`data_manager.py`)**: All decks, cards, scheduling states, and box coordinates are written to a local file (`anki_occlusion_data.json`).
- **Autosave (`DirtyStore`)**: Periodically checks if the data has been modified (is dirty) and writes it atomically to disk in a separate background save.
- **Recovery Manager**: Captures critical states so that review progress is not lost if the app crashes.

### 2. Spaced Repetition (`sm2_engine.py`)
- Standard SM-2 algorithm: handles states `new -> learning -> review -> relearn`.
- Calculates due dates, intervals (e.g. 1d, 4d, 7d), ease factors (EF), and repetitions.
- Updates card due status when rating quality buttons (1: Again, 2: Hard, 3: Good, 4: Easy, 5: Perfect) are pressed.

### 3. PDF Loading & Page Cache (`pdf_engine.py`, `cache_manager.py`)
- **Fast Startup**: Scans PDF page dimensions using `mode=rect_only` (doesn't render the pages first).
- **Background Loading**: Pages are loaded progressively in chunks via background worker threads to keep the UI responsive.
- **LRU Page Cache**: Keeps up to 15 pages in RAM, evicting older ones to keep memory usage under 300MB.
- **Dynamic File Sync**: Watches local PDFs. If a user annotates a PDF in an external reader and saves it, the app automatically updates the canvas view.

### 4. Interactive Editor (`ui/editor_dialog.py`)
- **Mask Drawing**: Draw Rectangle, Ellipse, or Inline Text.
- **Transformations**: Move, resize, delete, and rotate masks.
- **Grouping**: Link multiple masks together (`G` shortcut) so they reveal simultaneously.
- **Editor History**: Full `Ctrl+Z` / `Ctrl+Y` undo and redo.

### 5. Review Screen (`ui/review_screen.py`)
- **Pen Annotation**: Review screen opens with a drawing pen active by default. You can scribble notes on the PDF page during study.
- **Study Timers**: Floating timer keeps track of active time.
- **Shortcuts**: Space to reveal, 1-5 to rate, arrow keys to change pages, `C` to center on mask, `E` to edit.

---

## ⚖️ Part 2: Local vs. Web Comparison

| Feature | Local Desktop App | Web App (Prototype Status) | Gap to Close |
|---|---|---|---|
| **Data Flow** | Writes directly to local JSON. | Makes API calls to backend JSON. | **Disconnected Offline Storage:** The web prototype has an unused IndexedDB store (`localFirstStore.js`). The UI must load and write directly to IndexedDB first, then sync with the backend. |
| **Card Creation** | Support PDFs and Images. | Supports **Images only** via FileReader. | **No PDF Creator:** The web app cannot load a PDF file, navigate pages, and draw masks on a PDF to create a card. |
| **Editor Canvas** | Select, move, resize, rotate, group, and undo masks. | Rectangle drawing only. No select, move, resize, or grouping. | **Primitive Canvas:** Missing mouse vector coordinates to select/drag/resize/group masks. |
| **Review Features** | Default review pen, shortcuts, floating timer, center-on-mask. | Has SVG pen. Basic keyboard shortcuts. | **Missing Polish:** Center-on-mask centering, floating timer, and shortcut parity. |
| **PDF Rendering** | Threaded PyMuPDF + LRU Cache. | PDF.js canvas rendering. | **Memory Leak Risk:** If a user reviews a large PDF, keeping all page canvases in the DOM will crash the tab. Only visible pages should render/stay active. |

---

## 📋 Part 3: TODO Checklist for Complete Web App

### 🛠️ Stage 1: Integrate Local-First Storage (IndexedDB)
- [ ] **Wire up LocalFirstStore:** Modify `App.jsx` to load decks, cards, and review states from IndexedDB instead of hitting `/api/summary` and `/api/decks` on every load.
- [ ] **Offline Mode Toggle:** Add a status indicator showing if the app is working offline (saving to browser IndexedDB) or online.
- [ ] **Batch Sync Execution:** Wire the "Sync" button to call `flushQueuedChanges()` which pushes queued metadata changes to FastAPI and pulls incoming updates.

### 📄 Stage 2: Enable PDF Support in Card Creator
- [ ] **Add PDF Upload Input:** Update "+ Add Card" dialog to accept both images and PDF files.
- [ ] **PDF.js Creator Canvas:** When a PDF is selected, render pages using PDF.js inside the creation viewport.
- [ ] **Page Navigator:** Add next/prev page buttons in the creator so users can flip through the PDF to find the page they want to occlude.
- [ ] **Save PDF Cards:** Store the uploaded PDF file as a binary blob in the IndexedDB `files` store, and save the metadata referencing `pdf_path` and `page_num`.

### ✏️ Stage 3: Build Advanced Canvas Editor
- [ ] **Select and Move Masks:** Enable clicking an existing mask to highlight it, showing active drag handles. Support dragging to move.
- [ ] **Resize Masks:** Add corner handles to drawn masks to allow resizing.
- [ ] **Ellipse and Text Masks:** Support switching tools between Rectangles, Ellipses, and Text labels.
- [ ] **Group and Ungroup Actions:** Add a "Group Selected" button (and `G` keyboard shortcut) that sets a shared `group_id` on selected masks.
- [ ] **Editor Undo/Redo:** Implement a simple undo/redo stack for mask additions, translations, and deletions.

### 🎓 Stage 4: Polish Review Surface & Experience
- [ ] **Center on Mask (`C`):** Calculate the bounding rect of the active mask and scroll the review container to center the mask on-screen automatically when a card loads or when `C` is pressed.
- [ ] **Group Reveal Logic:** When rating a card that contains grouped masks, reveal all masks sharing the same `group_id` when the answer is shown.
- [ ] **Visible-Page Lazy Loading:** Clean up old page canvases in the PDF page stack that are out of the viewport window to conserve browser memory.
- [ ] **Floating Study Timer:** Add a subtle, beautiful floating session timer when reviewing.
- [ ] **Shortcut Parity:** Map `E` to edit, left/right arrows to flip pages, `` ` `` (backtick) to toggle pen.
