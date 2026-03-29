# Anki Occlusion 🃏

**Anki Occlusion** is a desktop flashcard app built with Python and PyQt5 that brings Anki's Image Occlusion feature to your own PDFs and images — with a full SM-2 spaced repetition scheduler built in.

Draw rectangles over the parts of your notes you want to hide. Each rectangle becomes a flashcard. Study them with the same Again / Hard / Good / Easy flow as real Anki — no typing required.

---

## ✨ Features

### Core
- **PDF & Image Occlusion** — Load any PDF or image, drag masks over what you want to hide, and each mask becomes its own flashcard question automatically.
- **SM-2 Spaced Repetition** — Full Anki-style scheduler with intraday learning steps (1m → 6m → 10m → 15m) and graduated review intervals (days/weeks). Cards move through `new → learning → review → relearn` states exactly like real Anki.
- **Anki-Style Review Flow** — Cards show with all masks hidden. Press `Space` to reveal, then rate yourself: **Again / Hard / Good / Easy**. Rating buttons only appear after you reveal — just like Anki.
- **Nested Decks** — Create decks and sub-decks to organise your subjects (e.g. `Biology › Chapter 3 › Cell Division`). Right-click for deck options.
- **Grouped Masks** — Link multiple masks together so they are reviewed as a single card (all masks hidden at once).

### PDF Features
- **Live PDF Sync** *(v13)* — When a PDF is loaded in the editor, the app watches the file for changes. Annotate your PDF in **any external app** (Foxit, Adobe Acrobat, Drawboard, Xodo, etc.), save it there, and the editor **auto-reloads within 800ms** — your masks stay in place.
- **Open in PDF Reader** *(v13)* — One-click button opens the current PDF in your system default reader so you can annotate and switch back seamlessly.
- **Multi-page PDFs** — Navigate pages with Prev / Next buttons inside the editor.

### Editor
- **Pinch-to-Zoom** — Ctrl+Scroll (or two-finger trackpad pinch) zooms the canvas. Works in both the editor and review mode.
- **Undo / Redo** — Full undo stack in the editor (Ctrl+Z / Ctrl+Y).
- **Select, Move & Duplicate** — Click to select masks, Ctrl+D to duplicate, Del to delete, Ctrl+A to select all.
- **Dynamic Font Size** — A− / A / A+ buttons in the top bar scale the entire app font. Preference is saved and restored on next launch.

### Other
- **First-Launch Wizard** — A short onboarding tour on first use explains the workflow in 30 seconds.
- **App Icon** — Programmatically generated icon; no external image file needed.
- **Safe Storage** — Atomic file write (write to temp → rename) guarantees your data is never corrupted even on a crash mid-save.
- **Single-Instance Lock** — Only one window can open at a time.

---

## 🚀 Installation

**Requirements:** Python 3.8+

```bash
pip install PyQt5 pymupdf
```

> `pymupdf` is needed for PDF support. If you only use images, you can skip it.

**Run:**

```bash
python anki_occlusion_v13.py
```

On Windows PowerShell with spaces in the path:
```powershell
python "C:\path with spaces\anki_occlusion_v13.py"
```

---

## 📖 How to Use

### 1 — Create a Deck
Click **＋ Deck** in the left sidebar. To nest it, select a parent deck first and click **＋ Sub**.

### 2 — Add a Card
Select a deck → click **＋ Add Card** → load a PDF or image → drag rectangles over the content you want to hide → click **💾 Save Card**.

**Tip for PDFs:** Click **📂 Open in PDF Reader** to annotate your PDF in Foxit / Adobe / Drawboard, save it there, and the editor will auto-reload showing your fresh annotations. Then draw your occlusion masks on top.

### 3 — Review
Click **🔴 Review Due** to study cards that are due today.
- Press `Space` to reveal the answer
- Press `1` Again · `2` Hard · `3` Good · `4` Easy to rate

The scheduler decides when you'll see each card next — minutes for new cards, days or weeks for well-known ones.

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
| `Ctrl` + `Scroll` | Zoom in / out |
| `Ctrl` + `+` / `-` / `0` | Zoom in / out / fit |
| `F11` | Toggle fullscreen |

### Editor Mode

| Shortcut | Action |
|----------|--------|
| `Ctrl` + `Z` | Undo |
| `Ctrl` + `Y` | Redo |
| `Ctrl` + `A` | Select all masks |
| `Ctrl` + `D` | Duplicate selected mask |
| `Del` | Delete selected mask(s) |
| `G` | Toggle group mode |
| `Ctrl` + `Scroll` | Zoom canvas |

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
5. The editor shows **🟡 change detected…** then **🟢 reloaded ✓** within a second
6. Your annotated PDF is now displayed — draw occlusion masks on top

Works with any app that saves to the same file path, including:
- Foxit PDF Reader / Editor
- Adobe Acrobat Reader / Pro
- Drawboard PDF
- Xodo
- PDF-XChange Editor
- Inkscape (export to same file)
- Any app that does in-place saves

---

## 📂 Data Location

All decks, cards, and scheduling data are stored in a single JSON file:

| Platform | Path |
|----------|------|
| Windows | `C:\Users\<YourUser>\anki_occlusion_data.json` |
| macOS | `~/anki_occlusion_data.json` |
| Linux | `~/anki_occlusion_data.json` |

Your font size preference is also saved here under the `_font_size` key.

---

## 📦 Version History

| Version | Highlights |
|---------|-----------|
| v13 | Live PDF Sync, Open in PDF Reader button, debounce reload, clean watcher teardown |
| v12 | Anki-style reveal flow, pinch zoom, center-on-mask button, dynamic font size, onboarding wizard, app icon, About dialog |
| v11 | Anki-style SM-2 scheduler (learning steps, relearn), improved review UX |
| v10 | Mask colors fixed, group/ungroup from deck view, shift+click multi-select |
| v9  | Initial public release |

---

*Consistency beats cramming! 🔥*