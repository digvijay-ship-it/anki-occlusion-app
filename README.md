# Anki Occlusion 🃏

**Anki Occlusion** is a desktop application built with Python and PyQt5 that brings Anki's popular "Image Occlusion" feature directly to PDFs and Images. It features a full SM-2 spaced repetition scheduler so you can study your visual notes effectively without typing a single word.

## ✨ Features

- **PDF & Image Occlusion**: Load a PDF or image, drag rectangular masks over the parts you want to hide, and each rectangle automatically becomes a flashcard question.
- **SM-2 Spaced Repetition**: A fully functional Anki-style scheduler with Learning steps (1m, 6m, 10m, 15m) and Review intervals (days).
- **Anki-Style Review Flow**: Press `Space` to reveal the answer, then rate your memory (Again, Hard, Good, Easy) just like native Anki.
- **Deck Organization**: Create nested decks and sub-decks to perfectly organize your subjects.
- **Advanced Canvas**: Pinch-to-zoom (or `Ctrl+Scroll`), auto-scaling, and active-mask centering for highly detailed images and documents.
- **Grouped Masks**: Option to link multiple masks together so they are reviewed on the exact same card.
- **Safe Storage**: Uses atomic file writing to guarantee your flashcard data is never corrupted, even during a system crash.

## 🚀 Installation & Setup

1. Make sure you have **Python 3** installed.
2. Install the required dependencies using pip:
   ```bash
   pip install PyQt5 pymupdf
   ```
   *(Note: `pymupdf` is required for PDF support. If you only want to use images, you can skip it.)*

3. Run the application:
   ```bash
   python anki_occlusion_v12.py
   ```
   *(If using Windows PowerShell and your folder has spaces, wrap the path in quotes: `python "anki_occlusion_v12.py"`)*

## ⌨️ Keyboard Shortcuts

### Review Mode
| Shortcut | Action |
| :--- | :--- |
| `Space` | Reveal Answer |
| `1` / `2` / `3` / `4` | Rate: Again / Hard / Good / Easy |
| `C` | Center view on the active mask |

### Editor Mode
| Shortcut | Action |
| :--- | :--- |
| `Ctrl` + `A` | Select all masks |
| `Del` | Delete selected mask(s) |
| `G` | Toggle grouping masks |

### Global
| Shortcut | Action |
| :--- | :--- |
| `F11` | Toggle Fullscreen |
| `Ctrl` + `Scroll` | Zoom canvas In/Out (or pinch on trackpad) |
| `Ctrl` + `+` / `-` / `0` | Scale Home UI font size / Zoom Canvas |

## 📂 Data Location

Your decks, cards, and scheduling data are safely stored as a single JSON file in your home directory:
- **Windows**: `C:\Users\<YourUser>\anki_occlusion_data.json`
- **Mac/Linux**: `~/anki_occlusion_data.json`

---
*Consistency beats cramming! 🔥*