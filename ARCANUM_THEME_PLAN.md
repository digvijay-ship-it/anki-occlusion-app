# ARCANUM THEME — Implementation Plan

> **What this is:** A complete, self-contained work order for adding a brand-new,
> **100% original** game theme called **ARCANUM** (arcane spellbook academy) to the
> Anki Occlusion desktop app. Every edit is specified with an exact `file:line`
> reference and, where useful, ready-to-paste code.
>
> **Audience:** an implementer (Gemini acting as labor). You should not need to
> re-investigate the codebase — this document is the result of the investigation.
> Read it top-to-bottom. Do the tasks in order. Check the Acceptance Criteria at
> the end before declaring done.
>
> **Created:** 2026-06-20. Branch off `main` before starting.

---

## 1. Goals & Non-Goals

### Goals
1. Ship **ARCANUM** as a 4th selectable theme alongside `classic`, `tmnt`,
   `manhattan`.
2. It joins the **"retro family"** so it renders through the rich 3-column
   dashboard layout (`ui/tmnt_home.py`), gets particle effects, and a glowing CTA.
3. Zero third-party IP. No `cowabunga`, `shredder`, `pizza`, `sewer`, `ninja`,
   `turtle`, `foot clan`, or any other borrowed names. All vocabulary is original.
4. **Old themes are preserved bit-for-bit.** A user switching classic/tmnt/manhattan
   must see the exact same UI as before this change.
5. Introduce one shared helper, `is_retro_theme()`, so the ~25 hand-duplicated
   `("tmnt","manhattan")` checks become a single source of truth. This is what
   makes ARCANUM "just work" everywhere and pays off for any future theme.

### Non-Goals (do NOT do these)
- Do **not** remove, rename, or disable the existing `tmnt` / `manhattan` /
  `dojo` / `ninja` themes. They stay exactly as-is.
- Do **not** touch the `web/` frontend. It has its own unrelated `classicMode`
  boolean and is out of scope.
- Do **not** change `== "dojo"`-only checks. `dojo` is in `DISABLED_THEMES` and
  falls back to `classic`; leave that machinery alone.
- Do **not** alter any spacing/size/color value for existing themes. The
  `is_retro_theme()` refactor must be behavior-preserving for the old themes.

---

## 2. Concept Brief (so the aesthetic decisions make sense)

**Theme:** an arcane spellbook academy at midnight. The app's code already calls
cards "scrolls" — ARCANUM makes that literal and cohesive.

| Element | Value |
|---|---|
| Mood | dark-fantasy mage's study, candlelit, glowing runes |
| Background | midnight indigo |
| Cards | parchment-dark with warm text |
| Accent | glowing arcane teal (a "magic" glow, not cyber neon) |
| Secondary | mystic violet + candle ember orange + gilt gold |
| Motion | warm embers/gold motes drifting **upward** (like sparks), soft glow — the opposite of TMNT's ooze dripping down |

### Locked Palette (`PALETTES["arcanum"]`)
```
C_BG      #0E0B1A   midnight indigo
C_SURFACE #15122A   study panel
C_CARD    #1F1B38   parchment-dark card
C_ACCENT  #5FEAD0   glowing arcane teal
C_PURPLE  #A78BFA   mystic violet
C_ORANGE  #F0A35E   candle ember
C_GREEN   #6FE7A8   success
C_RED     #FF5C7A   alert
C_YELLOW  #F4D35E   gilt / rune gold
C_TEXT    #EDE6D6   warm parchment
C_SUBTEXT #8E86B0   dim violet-gray
C_BORDER  #2A2545   rune-trace border
header_font  'Cinzel', 'Palatino Linotype', serif
body_font    'Cinzel', 'Palatino Linotype', serif
```

### Locked Vocabulary (`LABELS["arcanum"]`) — original, no IP
| Key | ARCANUM value |
|---|---|
| APP_TITLE | ANKI OCCLUSION |
| SUBTITLE | SM-2 • OCCLUSION • ARCANE ACADEMY |
| SIDEBAR_HDR | Grimoires |
| BTN_NEW_TOP | ＋ GRIMOIRE |
| BTN_NEW_SUB | ＋ CHAPTER |
| BTN_ADD | 🔮 FORGE SPELL |
| BTN_ADD_TEXT | 📜 INSCRIBE SCROLL |
| BTN_DUE | 🔮 BEGIN RITUAL |
| BTN_ALL | ▶ CAST ALL |
| BTN_EDIT | ✏ Edit Spell |
| BTN_SELECTED | ▶ Cast Selected |
| BTN_JOURNAL | 📓 Chronicle |
| BTN_SHORTCUTS | ⌨ Glyph Keys |
| STAT_SCROLLS | Spells |
| STAT_DUE | Due |
| STAT_REVIEWS | Castings |
| VAULT_TITLE | 🔮 ARCANE VAULT |
| BTN_CLEAR_VAULT | 🧹 Purge Vault |
| STATUS_READY | Arcane Engine Ready |
| DASH_TITLE | SELECT GRIMOIRE |
| DASH_SUB | The vault of memory opens at midnight. |
| DASH_MISS | PENDING INCANTATIONS |
| DASH_NEW | NEW SPELLS |
| DASH_BATTLES | RITUALS COMPLETE |

**Mentor quote (replaces the turtle/Donatello line):**
> "KNOWLEDGE IS THE ONLY MAGIC."
> — THE ARCHMAGE

---

## 3. How the Theme System Works (read this before editing)

- **Single source of truth:** `theme_manager.py`. It has:
  - `PALETTES` dict — colors + font-family stacks per theme.
  - `LABELS` dict — UI strings per theme.
  - `build_stylesheet(mode, font_size)` — returns a giant QSS string. Branches
    on mode: a `tmnt` fast-path (line ~229), then a generic branch that handles
    `dojo` and `manhattan` tweaks (lines ~304–775).
  - `normalize_theme(mode)` — maps disabled/unknown themes to `classic`.
  - `DISABLED_THEMES = {"dojo","ninja"}` — these fall back to classic.
- **Active theme propagation:** the current theme is a monkey-patched attribute
  `app._active_theme` on the `QApplication` instance. It's *not* a global. Code
  reads it via `getattr(app, "_active_theme", "classic")`. It's also persisted to
  the JSON settings dict as `self._data["_theme"]`.
- **The "retro family":** `tmnt` and `manhattan` share (a) the rich
  `ui/tmnt_home.py` dashboard layout, (b) particle/CRT effects in
  `ui/canvas/retro_effects.py`, and (c) ~25 hardcoded
  `theme in ("tmnt","manhattan")` checks scattered across the UI. `classic` uses a
  simpler splitter layout. ARCANUM joins the retro family.
- **Fonts:** only two fonts ship (`assets/fonts/PressStart2P-Regular.ttf`,
  `RobotoMono-Regular.ttf`). `Orbitron`/`Oxanium`/`Inter` appear only in CSS stacks
  and silently fall back to system fonts. Loader: `load_custom_fonts()` at
  `anki_occlusion_v19.pyw:276`.

---

## 4. Task List (do in this order)

### TASK 1 — Add `is_retro_theme()` helper + palette + labels
**File:** `theme_manager.py`

**1a.** After line 19 (`def is_theme_enabled(...)`), add a new helper:
```python
def is_retro_theme(mode="classic"):
    """True for themes that share the rich 3-column dashboard, retro effects,
    and glowing CTA. Single source of truth — all theme-family checks should
    route through here instead of hand-maintaining tuples."""
    return _raw_mode(mode) in {"tmnt", "manhattan", "arcanum"}
```
> Why `_raw_mode`: it normalizes `ninja`→`dojo`, so a disabled alias never
> accidentally counts as retro.

**1b.** Add `PALETTES["arcanum"]` immediately **after** the `"manhattan"` entry
(ends at line 106, before the closing `}`). Use the locked palette from §2.

**1c.** Add `LABELS["arcanum"]` immediately **after** the `"manhattan"` labels
entry (ends at line 189). Use the locked vocabulary from §2.

**1d.** In `build_stylesheet()`, ARCANUM must route through the **generic branch**
(the same code path as `manhattan`/`dojo`), NOT the `tmnt` fast-path at line 229.
The fast-path is gated `if mode == "tmnt":` — leave it. ARCANUM naturally falls
through to the generic branch. You only need to add `arcanum` to the per-mode
constant tuples inside the generic branch:

| Line | Current | Change to |
|---|---|---|
| 312 | `btn_radius = "0px" if mode in ("dojo", "manhattan") else "6px"` | treat arcanum as `"4px"`: see snippet below |
| 313 | `btn_border = ... ("2px" if mode == "dojo" else "1px")` | arcanum `"2px"` |
| 314 | `btn_padding = ...` | arcanum `"8px 18px"` |
| 383 | `QPushButton:hover` background | arcanum gets `rgba(240,163,94,0.12)` (ember) |
| 467–468 | mode_tab active colors | arcanum uses `p['C_ACCENT']` / `white` |
| 502 | dash_pane bg image | arcanum: `"none"` |
| 728–729 | tree item hover colors | arcanum: `rgba(95,234,208,0.05)` / `(0.2)` (teal) |
| 752–756, 770–775 | scrollbar handle colors | arcanum: `rgba(95,234,208,0.3)` / hover `0.6` |

Suggested rewrite for lines 312–314 (replace those three lines):
```python
btn_radius = (
    "0px" if mode in ("dojo", "manhattan")
    else "4px" if mode == "arcanum"
    else "6px"
)
btn_border = (
    "3px" if mode == "manhattan"
    else "2px" if mode in ("dojo", "arcanum")
    else "1px"
)
btn_padding = (
    "0px 20px" if mode == "manhattan"
    else "10px 20px" if mode == "dojo"
    else "8px 18px" if mode == "arcanum"
    else "6px 14px"
)
```
And the `raised` block at lines 316–324: arcanum should reuse the soft classic
look (`border-bottom: 2px solid rgba(0,0,0,0.4)`) — add an `elif mode == "arcanum"`
or just let it fall into the else with a tweak.

> **Preserve old themes:** every value above for `dojo`/`manhattan`/`classic` must
> match what's there today. Only add the `arcanum` branches.

**1e.** Font-family prep: at line ~304–309 the generic branch does
`hf = "'Orbitron', " + hf` for dojo and `"'Press Start 2P', " + hf` for manhattan.
Add an arcanum branch:
```python
elif mode == "arcanum":
    hf = "'Cinzel', " + hf        # Cinzel ships in TASK 2
    bf = "'Cinzel', " + bf
```

---

### TASK 2 — Ship the Cinzel font
**Files:** `assets/fonts/Cinzel-Regular.ttf`, `anki_occlusion_v19.pyw`

**2a.** Obtain **Cinzel** by Natanael Gama — **SIL Open Font License** (free to
bundle). Download `Cinzel-Regular.ttf` (and `Cinzel-Bold.ttf` if available) into:
```
assets/fonts/Cinzel-Regular.ttf
assets/fonts/Cinzel-Bold.ttf   (optional)
```
> Source: Google Fonts (`https://fonts.google.com/specimen/Cinzel`) or the
> upstream GitHub. Verify the license file (OFL) is the bundled one. Do NOT use a
> font with a restrictive license.

**2b.** In `load_custom_fonts()` at `anki_occlusion_v19.pyw:281-284`, add Cinzel
to the `font_paths` list:
```python
font_paths = [
    app_resource_path("assets", "fonts", "PressStart2P-Regular.ttf"),
    app_resource_path("assets", "fonts", "RobotoMono-Regular.ttf"),
    app_resource_path("assets", "fonts", "Cinzel-Regular.ttf"),
    app_resource_path("assets", "fonts", "Cinzel-Bold.ttf"),
]
```

**2c.** Cold-start font selection, `anki_occlusion_v19.pyw:452-460`. Current:
```python
if theme == "classic":
    app.setFont(QFont("Segoe UI", self._font_size)); ...
else:
    if theme == "tmnt":
        app.setFont(QFont("Roboto Mono", self._font_size))
    else:
        app.setFont(QFont(NARUTO_FONT_FAMILY, self._font_size))
    ss = build_stylesheet(theme, self._font_size); ...
```
Change the inner branch to add arcanum:
```python
    if theme == "tmnt":
        app.setFont(QFont("Roboto Mono", self._font_size))
    elif theme == "arcanum":
        app.setFont(QFont("Cinzel", self._font_size))
    else:
        app.setFont(QFont(NARUTO_FONT_FAMILY, self._font_size))
```

**2d.** Same edit in `change_font_size()` at `anki_occlusion_v19.pyw:644-647`.
Current:
```python
else:
    if theme == "tmnt":
        app.setFont(QFont("Roboto Mono", self._font_size))
    ss = build_stylesheet(theme, self._font_size)
```
Change to:
```python
else:
    if theme == "tmnt":
        app.setFont(QFont("Roboto Mono", self._font_size))
    elif theme == "arcanum":
        app.setFont(QFont("Cinzel", self._font_size))
    ss = build_stylesheet(theme, self._font_size)
```

---

### TASK 3 — Wire ARCANUM into the theme picker (6 + 2 spots)
The theme cycle is hardcoded in dicts/lists in two files. ARCANUM becomes index
3, cycling `classic → tmnt → manhattan → arcanum → classic`.

**File:** `ui/home_screen.py`

**3a.** Line 1214 — `_next_lbl` (top-bar cycle button label):
```python
_next_lbl = {
    "classic": "🐢 TMNT MODE",
    "tmnt": "🎮 MANHATTAN",
    "manhattan": "🔮 ARCANUM",
    "arcanum": "📚 CLASSIC MODE",
}
```

**3b.** Lines 2244 & 2247 — `_idx_to_theme` and `_cycle` inside `_toggle_theme`:
```python
_idx_to_theme = {0: "classic", 1: "tmnt", 2: "manhattan", 3: "arcanum"}
...
_cycle = {
    "classic": "tmnt", "tmnt": "manhattan",
    "manhattan": "arcanum", "arcanum": "classic",
}
```

**3c.** Line 2256 — `_theme_to_idx` (dropdown sync):
```python
_theme_to_idx = {"classic": 0, "tmnt": 1, "manhattan": 2, "arcanum": 3}
```

**3d.** Lines 1885 & 1889 — classic settings-panel dropdown:
```python
self._btn_theme.addItems(
    ["📚 CLASSIC MODE", "🐢 TMNT MODE", "🎮 MANHATTAN", "🔮 ARCANUM"]
)
...
_theme_to_idx = {"classic": 0, "tmnt": 1, "manhattan": 2, "arcanum": 3}
```

**3e.** Line 2282 — font name inside the retro-layout branch of `_toggle_theme`.
Current:
```python
font_name = "Courier New" if self._current_theme == "manhattan" else "Roboto Mono"
```
Change to:
```python
if self._current_theme == "manhattan":
    font_name = "Courier New"
elif self._current_theme == "arcanum":
    font_name = "Cinzel"
else:  # tmnt
    font_name = "Roboto Mono"
```

**File:** `ui/tmnt_home.py`

**3f.** Lines 3226 & 3251 — TMNT top-bar dropdown:
```python
self._btn_theme.addItems(
    ["📚 CLASSIC THEME", "🐢 TMNT THEME", "🎮 MANHATTAN", "🔮 ARCANUM"]
)
...
_theme_to_idx = {"classic": 0, "tmnt": 1, "manhattan": 2, "arcanum": 3}
```

---

### TASK 4 — Route ARCANUM through the retro dashboard layout
**File:** `ui/home_screen.py`

The retro layout is selected when `self._current_theme in ("tmnt", "manhattan")`.
Replace these tuples with the helper so ARCANUM joins the family.

**4a.** Line 2268 — the layout branch:
```python
if self._current_theme in ("tmnt", "manhattan") and self._ensure_tmnt_layout():
```
→
```python
if is_retro_theme(self._current_theme) and self._ensure_tmnt_layout():
```
(Add `from theme_manager import is_retro_theme` to the imports at top of
`_toggle_theme`, alongside the existing `build_stylesheet, normalize_theme` import
on line 2240.)

**4b.** Lines 1267, 1460, 1638, 1711 — any other `in ("tmnt","manhattan")` checks
in home_screen.py that gate layout/visibility. Change each to `is_retro_theme(...)`.
> Audit each one individually before changing — some may be font/palette
> distinctions that should stay as `("tmnt","manhattan")` (e.g. a check that
> selects manhattan-specific styling). When in doubt, include arcanum only if the
> branch is about *layout*, not *manhattan-specific visuals*.

**File:** `ui/tmnt_home.py`

**4c.** Line 2832 — the brand-name guard:
```python
if theme_name not in ("tmnt", "manhattan"):
    theme_name = "tmnt"
```
→
```python
from theme_manager import is_retro_theme  # at top of file if not already
...
if not is_retro_theme(theme_name):
    theme_name = "tmnt"
```

---

### TASK 5 — New ember/rune particle effect + retro-effect gating
**File:** `ui/canvas/retro_effects.py`

There are **4** `_is_theme_active()` methods (lines 67, 176, 290, 408), each
returning `theme in ("tmnt", "manhattan")`.

**5a.** Change all four to use the helper:
```python
def _is_theme_active(self):
    try:
        from PyQt5.QtWidgets import QApplication
        from theme_manager import is_retro_theme
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        return is_retro_theme(theme)
    except Exception:
        return True
```

**5b.** Add a sibling helper for the ember variant:
```python
def _is_ember_theme(self):
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        return getattr(app, "_active_theme", "classic") == "arcanum"
    except Exception:
        return False
```

**5c.** Add an `EmberMote` particle class near the existing `OozeParticle`
(line 150). Warm orange `#F0A35E` + gilt gold `#F4D35E` motes that drift
**upward** (negative y velocity) and fade — the opposite direction of ooze:
```python
class EmberMote:
    """Warm spark drifting upward (candlelight). Used by ARCANUM."""
    def __init__(self, x, y, size, speed, color):
        self.x = x
        self.y = y
        self.size = size
        self.speed = speed      # negative = upward
        self.color = color
        self.life = random.uniform(0.6, 1.0)
```

**5d.** In the particle-panel that creates particles (the
`RetroParticlePanel`/`init_particles` area, ~lines 208–227), branch on
`self._is_ember_theme()`: if ember, create `EmberMote` instances with upward
velocity and ember/gold colors; otherwise keep the existing ooze/pizza behavior
unchanged. **Do not** alter the tmnt/manhattan particle paths.

**5e.** CRT scanlines: the `CRTOverlay` class (~line 60) currently activates for
all retro themes after 5a. **ARCANUM must NOT show CRT scanlines** — it's
candlelit, not cyber. Gate scanlines out for arcanum:
```python
def _is_theme_active(self):  # CRTOverlay only
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        return theme in ("tmnt", "manhattan")  # explicitly NOT arcanum
    except Exception:
        return True
```
(i.e. for the CRT overlay specifically, keep the original tuple and do NOT add
arcanum.)

---

### TASK 6 — Centralize the ~25 retro-family tuples
**Goal:** replace `theme in ("tmnt","manhattan")` and
`theme in ("dojo","tmnt","manhattan")` with `is_retro_theme(theme)`, where the
intent is "is this a retro-family theme." Behavior for old themes must be
identical. Import `is_retro_theme` at the top of each file.

> **Critical rule:** ONLY replace checks whose meaning is "retro family / shared
> dashboard styling." Leave `== "dojo"`-only checks and any check that does
> manhattan-vs-tmnt *visual* distinction alone. After each edit, the set
> `{tmnt, manhattan}` of true-values must be unchanged for existing themes.

Files & lines to audit and (where appropriate) convert:
- `ui/review_screen.py` — 291, 633, 1995, 2756 (and 2897 `== "dojo"` → leave)
- `ui/review/summary_dialog.py` — 38, 66 (115/117 are manhattan-vs-tmnt visual
  branches → add an `elif theme_mode == "arcanum"` for arcanum-appropriate
  styling; font weight 122; padding 346–347)
- `ui/journal.py` — 81
- `ui/math_trainer.py` — 420
- `ui/pdf_annotation_dialog.py` — 813, 945
- `ui/editor_dialog.py` — 173
- `ui/deck_view.py` — 604 (leave 676/700/823/996 which are `== "dojo"`)
- `cache_manager.py` — 124 (currently `in ("tmnt","dojo")` — leave as-is; arcanum
  does not need the dojo cache path)

**Special case — `summary_dialog.py` lines 115–117:** this is a per-theme visual
branch (manhattan vs tmnt). Add arcanum handling so the review summary renders
correctly:
```python
if theme_mode == "manhattan":
    ...   # existing
elif theme_mode == "arcanum":
    ...   # arcanum-equivalent: ember/violet accents, Cinzel font weight
elif theme_mode == "tmnt":
    ...   # existing
```

---

### TASK 7 — Archmage mentor card (replaces dead turtle/pizza widgets)
**Context:** `dojo_assets.py` exposes `get_turtle_widget()` and
`get_pizza_widget()` (lines 126, 162), but the codebase audit found **zero
callers** — they're dead code. Do not delete them (non-goal: preserve old themes),
but add a new arcanum mentor.

**7a.** Create `arcane_assets.py` (new file) with an `ArcaneAssets` singleton and
a `get_archmage_widget()` that returns a `QFrame` styled in arcanum colors,
containing a **procedurally-drawn sigil** (a small rune/eye drawn with `QPainter`
into a `QPixmap` — no external image needed, keeps it 100% original) and the
mentor quote:
> "KNOWLEDGE IS THE ONLY MAGIC." — THE ARCHMAGE

Style: `background: rgba(31,27,56,0.6); border: 1px solid #5FEAD0; border-radius: 8px;`
quote color `#A78BFA`, font Cinzel.

**7b.** In `ui/tmnt_home.py`, find where the mentor slot is populated (search for
`mentor_card` / `MentorCard` / where a mentor widget is added to the top bar or
sidebar). When `is_retro_theme(theme) and theme == "arcanum"`, render the
archmage card instead of the existing tmnt/manhattan mentor. If the existing
mentor is hardcoded for tmnt/manhattan visuals, branch on `theme == "arcanum"`.

> If you cannot locate a mentor slot in tmnt_home.py after searching, place the
archmage card in the right-sidebar "fuel up" area (the slot currently filled by
`get_pizza_widget` conceptually) for arcanum. Document where you placed it in your
PR description.

---

### TASK 8 — Tests
**File:** `tests/test_theme_manager.py`

Add (after `test_manhattan_theme_passes_cleanly`, line 22):
```python
def test_arcanum_theme_passes_cleanly(self):
    self.assertEqual(normalize_theme("arcanum"), "arcanum")
    stylesheet = build_stylesheet("arcanum", 12)
    self.assertIn("#0E0B1A", stylesheet)        # midnight indigo bg
    self.assertIn("Cinzel", stylesheet)          # arcanum display font

def test_is_retro_theme_helper(self):
    from theme_manager import is_retro_theme
    self.assertTrue(is_retro_theme("arcanum"))
    self.assertTrue(is_retro_theme("tmnt"))
    self.assertTrue(is_retro_theme("manhattan"))
    self.assertFalse(is_retro_theme("classic"))
    self.assertFalse(is_retro_theme("dojo"))     # disabled → not retro

def test_arcanum_contains_no_third_party_ip(self):
    from theme_manager import LABELS
    blob = build_stylesheet("arcanum", 12) + " " + str(LABELS["arcanum"]).lower()
    for forbidden in ("cowabunga", "shredder", "pizza", "sewer",
                      "ninja", "turtle", "foot clan", "donatello", "splinter"):
        self.assertNotIn(forbidden, blob, f"ARCANUM must not contain '{forbidden}'")
```

**File:** `tests/test_tmnt_deck_tree.py` — verify the existing
`test_tmnt_headers_use_math_dojo_header_font` still passes (it asserts on tmnt
only; arcanum doesn't touch it). No edit needed, but run it.

---

### TASK 9 — Verify (acceptance gate, do all of these)
1. `python -m pytest tests/test_theme_manager.py tests/test_tmnt_deck_tree.py -q`
   → all green, including the 3 new arcanum tests.
2. Launch the app: `python anki_occlusion_v19.pyw`.
3. Cycle the theme dropdown through **classic → tmnt → manhattan → arcanum → classic**.
   Each must apply instantly with no exceptions in the console.
4. With **arcanum** active, open and visually confirm:
   - Home dashboard (3-column layout, stat tiles, glowing CTA "BEGIN RITUAL")
   - Deck tree sidebar (Grimoires, ember/gold hover)
   - Review screen (a casting session)
   - Journal (Chronicle)
   - PDF annotation editor
   - Review summary dialog (archmage colors)
   - Math Trainer
5. Confirm **ember motes drift upward** on the arcanum home screen (and that
   there are **no CRT scanlines**).
6. **Regression check:** switch back to tmnt and manhattan and classic. Each must
   look byte-identical to before this change (same colors, same fonts, same
   particle direction for tmnt/manhattan, classic unchanged).
7. Grep the repo: confirm no accidental introduction of IP strings into arcanum:
   `grep -riE "cowabunga|shredder|foot clan|donatello" theme_manager.py arcane_assets.py`
   → must return nothing.

---

## 5. File-by-File Edit Summary (quick index)

| File | Task(s) | Nature |
|---|---|---|
| `theme_manager.py` | 1a–1e | palette, labels, helper, stylesheet branch |
| `assets/fonts/Cinzel-Regular.ttf` (+Bold) | 2a | new asset (OFL) |
| `anki_occlusion_v19.pyw` | 2b–2d | font loader + cold-start/font-size |
| `ui/home_screen.py` | 3a–3e, 4a, 4b | picker dicts, layout routing |
| `ui/tmnt_home.py` | 3f, 4c | picker dicts, brand guard |
| `ui/canvas/retro_effects.py` | 5a–5e | ember particle, retro/scanline gating |
| `ui/review_screen.py` | 6 | tuple → helper |
| `ui/review/summary_dialog.py` | 6 | tuple → helper + arcanum branch |
| `ui/journal.py` | 6 | tuple → helper |
| `ui/math_trainer.py` | 6 | tuple → helper |
| `ui/pdf_annotation_dialog.py` | 6 | tuple → helper |
| `ui/editor_dialog.py` | 6 | tuple → helper |
| `ui/deck_view.py` | 6 | tuple → helper (leave `==dojo`) |
| `arcane_assets.py` | 7a | NEW: archmage mentor card |
| `ui/tmnt_home.py` | 7b | wire archmage into mentor slot |
| `tests/test_theme_manager.py` | 8 | 3 new tests |

---

## 6. Risks & Guardrails

- **Highest risk = the `is_retro_theme()` refactor (Task 6).** A careless swap
  could change behavior for tmnt/manhattan. Mitigation: only swap checks whose
  meaning is "retro family." The acceptance criterion #6 (byte-identical old
  themes) is non-negotiable.
- **`tmnt_home.py` is heavily tmnt/manhattan-coupled** (~20 theme branches). If
  arcanum renders oddly in the dashboard, the likely cause is a visual branch that
  does manhattan-vs-tmnt distinction. Add an `elif theme == "arcanum"` there with
  arcanum-appropriate colors from the palette.
- **Font fallback:** if Cinzel fails to load (missing file), the CSS stack falls
  back to `'Palatino Linotype', serif`. The app must not crash. Test by temporarily
  renaming the ttf and confirming graceful fallback.
- **Do not** reuse any image from `assets/themes/dojo/` for arcanum — those
  (`Cyber_ninja_turtle`, `Fantasy_ninja_*`, `Retro_arcade_pizza`) are IP-adjacent.
  The archmage sigil is procedurally drawn for this reason.
- **`web/` is out of scope.** Do not generalize `classicMode` in
  `web/frontend/src/App.jsx` as part of this work.

---

## 7. Done Definition

All of: Tasks 1–8 implemented · Task 9 acceptance items all pass · no IP strings
in arcanum assets/labels · old themes visually unchanged · PR description notes
where the archmage card was placed.
