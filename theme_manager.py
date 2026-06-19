import os

from PyQt5.QtGui import QColor
from storage_paths import app_resource_path, app_resource_url

# ── Theme Feature Gates ───────────────────────────────────────────────────────

NINJA_THEME_ENABLED = False
DISABLED_THEMES = {"dojo", "ninja"}


def _raw_mode(mode="classic"):
    if mode == "ninja":
        return "dojo"
    return mode or "classic"


def is_theme_enabled(mode="classic"):
    return _raw_mode(mode) not in DISABLED_THEMES


def is_retro_theme(mode="classic"):
    """True for themes that share the rich 3-column dashboard, retro effects,
    and glowing CTA. Single source of truth — all theme-family checks should
    route through here instead of hand-maintaining tuples."""
    return _raw_mode(mode) in {"tmnt", "manhattan", "arcanum"}


# ── Color Palettes ────────────────────────────────────────────────────────────

PALETTES = {
    # "dark" is the pre-theme fallback used in widgets that initialize before
    # a theme is selected. It matches the original hardcoded C_* constants.
    "dark": {
        "C_BG":      "#1E1E2E",
        "C_SURFACE": "#2A2A3E",
        "C_CARD":    "#313145",
        "C_ACCENT":  "#7C6AF7",
        "C_PURPLE":  "#7C6AF7",
        "C_ORANGE":  "#FFB86C",
        "C_GREEN":   "#50FA7B",
        "C_RED":     "#FF5555",
        "C_TEXT":    "#CDD6F4",
        "C_SUBTEXT": "#A6ADC8",
        "C_BORDER":  "#45475A",
        "C_YELLOW":  "#F1FA8C",
        "header_font": "'Segoe UI', sans-serif",
        "body_font":   "'Segoe UI', sans-serif",
    },
    "dojo": {
        "C_BG": "#07070B",
        "C_SURFACE": "#0F0F17",
        "C_CARD": "#14141F",
        "C_ACCENT": "#72FF4F",  # Neon Green
        "C_PURPLE": "#A86CFF",  # Arcade Purple
        "C_ORANGE": "#FF9A2E",
        "C_GREEN": "#72FF4F",
        "C_RED": "#FF4444",
        "C_TEXT": "#E0E0FF",
        "C_SUBTEXT": "#5F627D",
        "C_BORDER": "#1A1A26",
        "C_YELLOW": "#FFD700",
        "header_font": "'Orbitron', 'Oxanium', 'Segoe UI Black', sans-serif",
        "body_font": "'Inter', 'Segoe UI', sans-serif",
    },
    "classic": {
        "C_BG": "#F0F2F5",
        "C_SURFACE": "#FFFFFF",
        "C_CARD": "#F8F9FA",
        "C_ACCENT": "#4C6EF5",  # Muted Blue
        "C_PURPLE": "#7048E8",
        "C_ORANGE": "#F59F00",
        "C_GREEN": "#37B24D",
        "C_RED": "#F03E3E",
        "C_TEXT": "#212529",
        "C_SUBTEXT": "#868E96",
        "C_BORDER": "#DEE2E6",
        "C_YELLOW": "#FAB005",
        "header_font": "'Segoe UI', sans-serif",
        "body_font": "'Segoe UI', sans-serif",
    },
    "tmnt": {
        "C_BG": "#0F150E",       # Dojo Dark Green-Black background
        "C_SURFACE": "#181D16",  # Dojo Panel background
        "C_CARD": "#353B33",     # Dojo Card background
        "C_ACCENT": "#66FCF1",   # Dojo Neon Cyan
        "C_PURPLE": "#B088F9",   # Dojo Purple
        "C_ORANGE": "#FFB86C",
        "C_GREEN": "#45A247",    # Dojo Accent Green
        "C_RED": "#FF4D4D",      # Dojo Red
        "C_TEXT": "#FFFFFF",     # Pure White for excellent contrast!
        "C_SUBTEXT": "#A0AEC0",  # Bright slate gray for clean readability!
        "C_BORDER": "#2D332B",   # Dojo Border
        "C_YELLOW": "#F4D35E",
        "header_font": "'Orbitron', 'Oxanium', 'Segoe UI Black', sans-serif",
        "body_font": "'Roboto Mono', 'Courier New', monospace",
    },
    "manhattan": {
        "C_BG": "#080c10",
        "C_SURFACE": "#121622",
        "C_CARD": "#192030",
        "C_ACCENT": "#00f0ff",
        "C_PURPLE": "#a86cff",
        "C_ORANGE": "#ffa200",
        "C_GREEN": "#39ff14",
        "C_RED": "#ff0055",
        "C_TEXT": "#f5f1e8",
        "C_SUBTEXT": "#7a8ca3",
        "C_BORDER": "#212a3b",
        "C_YELLOW": "#ffcc00",
        "header_font": "'Orbitron', 'Oxanium', 'Segoe UI Black', sans-serif",
        "body_font": "'Courier New', monospace",
    },
    "arcanum": {
        "C_BG":      "#0E0B1A",
        "C_SURFACE": "#15122A",
        "C_CARD":    "#1F1B38",
        "C_ACCENT":  "#5FEAD0",
        "C_PURPLE":  "#A78BFA",
        "C_ORANGE":  "#F0A35E",
        "C_GREEN":   "#6FE7A8",
        "C_RED":     "#FF5C7A",
        "C_YELLOW":  "#F4D35E",
        "C_TEXT":    "#EDE6D6",
        "C_SUBTEXT": "#8E86B0",
        "C_BORDER":  "#2A2545",
        "header_font": "'Cinzel', 'Palatino Linotype', serif",
        "body_font":   "'Cinzel', 'Palatino Linotype', serif",
    },
}

# ── Label Mappings ────────────────────────────────────────────────────────────

LABELS = {
    "dojo": {
        "APP_TITLE": "ANKI OCCLUSION",
        "SUBTITLE": "SM-2 • PDF & IMAGE OCCLUSION • TRAINING DOJO",
        "SIDEBAR_HDR": "Dojos",
        "BTN_NEW_TOP": "＋ DOJO",
        "BTN_NEW_SUB": "＋ SUB",
        "BTN_ADD": "📜 FORGE SCROLL",
        "BTN_ADD_TEXT": "🥋 SCRIBE TILE",
        "BTN_DUE": "⚔ START TRAINING",
        "BTN_ALL": "🏃 RUN DOJO",
        "BTN_EDIT": "✏ Edit Scroll",
        "BTN_SELECTED": "▶ Train Selected",
        "BTN_JOURNAL": "📓 Battle Log",
        "BTN_SHORTCUTS": "⌨ Quick Moves",
        "STAT_SCROLLS": "Scrolls",
        "STAT_DUE": "Due",
        "STAT_REVIEWS": "Battles",
        "VAULT_TITLE": "🧪 BANGA LAB",
        "BTN_CLEAR_VAULT": "🧹 Clear Vault",
        "STATUS_READY": "Scroll Engine Ready",
        "DASH_TITLE": "SELECT DOJO",
        "DASH_SUB": "Cowabunga. Stay sharp, ninja.",
        "DASH_MISS": "REMAINING MISSIONS",
        "DASH_NEW": "NEW TECHNIQUES",
        "DASH_BATTLES": "TRIALS CLEARED",
    },
    "classic": {
        "APP_TITLE": "ANKI OCCLUSION",
        "SUBTITLE": "Review • Recall • Master",
        "SIDEBAR_HDR": "Decks",
        "BTN_NEW_TOP": "＋ Deck",
        "BTN_NEW_SUB": "＋ Sub",
        "BTN_ADD": "＋ Add Card",
        "BTN_ADD_TEXT": "＋ Basic Card",
        "BTN_DUE": "🔴 Review Due",
        "BTN_ALL": "▶ Review All",
        "BTN_EDIT": "✏ Edit",
        "BTN_SELECTED": "▶ Review Selected",
        "BTN_JOURNAL": "📓 Journal",
        "BTN_SHORTCUTS": "⌨ Shortcuts",
        "STAT_SCROLLS": "Cards",
        "STAT_DUE": "Due",
        "STAT_REVIEWS": "Reviews",
        "VAULT_TITLE": "💾 Cache",
        "BTN_CLEAR_VAULT": "🧹 Clear Cache",
        "STATUS_READY": "PDF Engine Ready",
        "DASH_TITLE": "SELECT DECK",
        "DASH_SUB": "Focus on your goals.",
        "DASH_MISS": "DUE CARDS",
        "DASH_NEW": "NEW CARDS",
        "DASH_BATTLES": "TOTAL REVIEWS",
    },
    "manhattan": {
        "APP_TITLE": "MANHATTAN PROJECT",
        "SUBTITLE": "RETRO NES OCCLUSION SYSTEM • STAGE 3",
        "SIDEBAR_HDR": "Sewer Caves",
        "BTN_NEW_TOP": "＋ STAGE",
        "BTN_NEW_SUB": "＋ SUBSTAGE",
        "BTN_ADD": "🍕 ADD PIZZA CARD",
        "BTN_ADD_TEXT": "🍕 ADD PIZZA SLICE",
        "BTN_DUE": "🐢 FIGHT FOOT CLAN",
        "BTN_ALL": "🎮 RUN MANHATTAN",
        "BTN_EDIT": "✏ Modify Scroll",
        "BTN_SELECTED": "▶ Clear Area",
        "BTN_JOURNAL": "📓 Ooze Journal",
        "BTN_SHORTCUTS": "⌨ Combo Keys",
        "STAT_SCROLLS": "Pizzas",
        "STAT_DUE": "Fighters",
        "STAT_REVIEWS": "Combats",
        "VAULT_TITLE": "🧪 BANGA LAB",
        "BTN_CLEAR_VAULT": "🧹 Clear Vault",
        "STATUS_READY": "8-bit NES Engine Loaded",
        "DASH_TITLE": "SELECT SEWER LEVEL",
        "DASH_SUB": "Cowabunga! Stop Shredder's project.",
        "DASH_MISS": "DUE COMBATS",
        "DASH_NEW": "NEW TRAINING",
        "DASH_BATTLES": "STAGES CLEARED",
    },
    "arcanum": {
        "APP_TITLE": "ANKI OCCLUSION",
        "SUBTITLE": "SM-2 • OCCLUSION • ARCANE ACADEMY",
        "SIDEBAR_HDR": "Grimoires",
        "BTN_NEW_TOP": "＋ GRIMOIRE",
        "BTN_NEW_SUB": "＋ CHAPTER",
        "BTN_ADD": "🔮 FORGE SPELL",
        "BTN_ADD_TEXT": "📜 INSCRIBE SCROLL",
        "BTN_DUE": "🔮 BEGIN RITUAL",
        "BTN_ALL": "▶ CAST ALL",
        "BTN_EDIT": "✏ Edit Spell",
        "BTN_SELECTED": "▶ Cast Selected",
        "BTN_JOURNAL": "📓 Chronicle",
        "BTN_SHORTCUTS": "⌨ Glyph Keys",
        "STAT_SCROLLS": "Spells",
        "STAT_DUE": "Due",
        "STAT_REVIEWS": "Castings",
        "VAULT_TITLE": "🔮 ARCANE VAULT",
        "BTN_CLEAR_VAULT": "🧹 Purge Vault",
        "STATUS_READY": "Arcane Engine Ready",
        "DASH_TITLE": "SELECT GRIMOIRE",
        "DASH_SUB": "The vault of memory opens at midnight.",
        "DASH_MISS": "PENDING INCANTATIONS",
        "DASH_NEW": "NEW SPELLS",
        "DASH_BATTLES": "RITUALS COMPLETE",
    },
}


def _normalize_mode(mode="classic"):
    raw_mode = _raw_mode(mode)
    if raw_mode in DISABLED_THEMES:
        print(f"[DEBUG][theme] ninja_disabled fallback=classic source={mode}")
        return "classic"
    if raw_mode not in PALETTES:
        return "classic"
    return raw_mode


normalize_theme = _normalize_mode


def get_palette(mode="classic"):
    mode = _normalize_mode(mode)
    return PALETTES.get(mode, PALETTES["classic"])


def get_label(key, mode="classic"):
    mode = _normalize_mode(mode)
    return LABELS.get(mode, LABELS["classic"]).get(key, key)


def build_stylesheet(mode="classic", font_size=14):
    mode = _normalize_mode(mode)
    p = get_palette(mode)

    hf = p["header_font"]
    bf = p["body_font"]
    dojo_wall_hex = app_resource_url("assets", "themes", "dojo", "wall_hex_accent.png")
    dojo_wall_main = app_resource_url("assets", "themes", "dojo", "wall_main.png")
    overlay_name = "panel_overlay_subtle.png"
    if not os.path.exists(app_resource_path("assets", "themes", "dojo", overlay_name)):
        overlay_name = "panel_overlay.png"
    dojo_panel_overlay_subtle = app_resource_url("assets", "themes", "dojo", overlay_name)

    if mode == "tmnt":
        return f"""
QMainWindow, QDialog {{
    background: {p['C_BG']};
    color: {p['C_TEXT']};
}}
QWidget {{
    background: {p['C_BG']};
    color: {p['C_TEXT']};
    font-family: {bf};
    font-size: {font_size}px;
}}
QLabel {{
    background: transparent;
    color: {p['C_TEXT']};
}}
QFrame {{
    border: none;
}}
QMenu {{
    background: {p['C_SURFACE']};
    color: {p['C_TEXT']};
    border: 1px solid {p['C_BORDER']};
    border-radius: 2px;
    font-family: {bf};
    font-size: {font_size}px;
}}
QMenu::item:selected {{
    background: {p['C_CARD']};
    color: {p['C_ACCENT']};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: {p['C_BG']};
    width: 8px;
    margin: 0px;
    border-left: 1px solid {p['C_BORDER']};
}}
QScrollBar::handle:vertical {{
    background: {p['C_CARD']};
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['C_ACCENT']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: {p['C_BG']};
    height: 8px;
    margin: 0px;
    border-top: 1px solid {p['C_BORDER']};
}}
QScrollBar::handle:horizontal {{
    background: {p['C_CARD']};
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p['C_ACCENT']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""

    if mode == "dojo":
        hf = "'Orbitron', " + hf
        bf = "'Orbitron', " + bf
    elif mode == "manhattan":
        hf = "'Press Start 2P', " + hf
        bf = "'Courier New', " + bf
    elif mode == "arcanum":
        hf = "'Cinzel', " + hf
        bf = "'Cinzel', " + bf

    # UI Constants
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

    raised = (
        f"border-bottom: 4px solid rgba(0,0,0,0.6);"
        if mode == "manhattan"
        else (
            f"border-bottom: 3px solid rgba(0,0,0,0.5);"
            if mode == "dojo"
            else (
                f"border-bottom: 2px solid rgba(0,0,0,0.4);"
                if mode == "arcanum"
                else "border-bottom: 2px solid rgba(0,0,0,0.15);"
            )
        )
    )

    return f"""
QMainWindow, QDialog {{ background: {p['C_BG']}; color: {p['C_TEXT']}; }}
QWidget {{ background: {p['C_BG']}; color: {p['C_TEXT']}; font-family: {bf}; font-size: {font_size}px; }}
QFrame {{ background: {p['C_SURFACE']}; border: none; border-radius: {btn_radius}; }}

/* Top Bar and Panels */
QFrame#top_bar {{
    background: {p['C_SURFACE']};
    border-bottom: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}
QFrame#cache_panel {{
    background-color: {p['C_SURFACE']};
    background-image: {f"url({dojo_wall_hex})" if mode == "dojo" else "none"};
    background-position: right top;
    background-repeat: no-repeat;
    border-left: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}
QWidget#side_panel, QFrame#side_panel {{
    background-color: {p['C_SURFACE']};
    background-image: {f"url({dojo_wall_main})" if mode == "dojo" else "none"};
    background-position: left bottom;
    background-repeat: no-repeat;
    border-right: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}

QLabel {{ background: transparent; color: {p['C_TEXT']}; }}
QLabel#app_logo {{
    color: {p['C_ACCENT']};
    font-family: {hf};
    font-weight: 900;
    font-size: 18px;
    letter-spacing: 2px;
}}
QLabel#title_box {{
    border: 1px solid {p['C_SUBTEXT']};
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 16px;
    font-weight: bold;
    color: {p['C_TEXT']};
}}

QPushButton {{
    background: {p['C_SURFACE']};
    color: {p['C_ACCENT']};
    border: {btn_border} solid {p['C_ACCENT']};
    border-radius: {btn_radius};
    padding: {btn_padding};
    font-family: {hf};
    font-weight: {'normal' if mode == 'manhattan' else 'bold'};
    text-transform: {'uppercase' if mode in ('dojo', 'manhattan') else 'none'};
    letter-spacing: {'2px' if mode in ('dojo', 'manhattan') else '0px'};
}}
QPushButton:hover {{
    background: { 'rgba(240, 163, 94, 0.12)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.15)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.1)') };
}}

/* Dominant CTA - START TRAINING */
QPushButton#cta_primary {{
    background: {p['C_ACCENT']};
    color: {p['C_BG']};
    border: none;
    border-radius: {btn_radius};
    padding: 12px 24px;
    font-family: {hf};
    font-weight: {'normal' if mode == 'manhattan' else '900'};
    font-size: 16px;
    text-transform: uppercase;
    letter-spacing: 2px;
    {raised}
}}
QPushButton#cta_primary:hover {{
    background: white;
    color: {p['C_BG']};
}}

QPushButton#top_bar_btn {{
    background: transparent;
    color: {p['C_SUBTEXT']};
    border: 1px solid {p['C_BORDER']};
    border-radius: 6px;
    padding: 4px 14px;
    font-size: 12px;
    text-transform: none;
    letter-spacing: 0px;
    font-family: {bf};
}}
QPushButton#top_bar_btn:hover {{
    background: {p['C_CARD']};
    color: {p['C_TEXT']};
}}

QPushButton#flat {{
    background: transparent;
    color: {p['C_SUBTEXT']};
    border: 1px solid {p['C_BORDER']};
    text-transform: none;
    letter-spacing: 0px;
    font-family: {bf};
}}

QPushButton#danger {{
    background: transparent;
    color: {p['C_RED']};
    border: {btn_border} solid {p['C_RED']};
}}
QPushButton#danger:hover {{
    background: rgba(255, 68, 68, 0.1);
}}

QPushButton#success {{
    background: {p['C_GREEN']};
    color: {p['C_BG']};
    border: {btn_border} solid {p['C_GREEN']};
}}
QPushButton#success:hover {{
    background: white;
    color: {p['C_BG']};
}}

/* Segmented Toggle Styling */
QFrame#mode_container {{
    background: {p['C_CARD']};
    border: 1px solid {p['C_BORDER']};
    border-radius: 4px;
    padding: 2px;
}}
QPushButton#mode_tab {{
    background: transparent;
    color: {p['C_SUBTEXT']};
    border: none;
    border-radius: 2px;
    padding: 6px 20px;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QPushButton#mode_tab[active="true"] {{
    background: {p['C_ACCENT'] if mode=='dojo' else p['C_ACCENT']};
    color: {p['C_BG'] if mode == "dojo" else "white"};
    font-weight: bold;
}}

QListWidget, QTreeWidget {{
    background: {p['C_BG']};
    border: none;
    padding: 5px;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 8px;
    border-radius: 4px;
    margin-bottom: 2px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {'#A86CFF' if mode == 'dojo' else p['C_ACCENT']};
    color: white;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background: rgba(255, 255, 255, 0.05);
}}

QStatusBar {{
    background: {p['C_SURFACE']};
    color: {p['C_ACCENT']};
    border-top: 1px solid {p['C_BORDER']};
    font-family: {hf};
    font-weight: bold;
    padding-left: 10px;
}}

/* Dashboard Specific */
QFrame#dash_pane {{
    background-color: transparent;
    background-image: {f"url({dojo_panel_overlay_subtle})" if mode == "dojo" else "none"};
    background-position: center;
    background-repeat: no-repeat;
    border: none;
}}
QFrame#stat_tile {{
    background: {p['C_CARD']};
    border: 1px solid {p['C_BORDER']};
    border-radius: 12px;
    padding: 15px;
}}
QLabel#stat_value {{
    color: {p['C_ACCENT']};
    font-size: 32px;
    font-weight: 900;
    font-family: {hf};
}}
QLabel#stat_label {{
    color: {p['C_SUBTEXT']};
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#dash_sub_lbl {{
    color: {p['C_SUBTEXT']};
    font-size: 13px;
    font-family: {hf};
    letter-spacing: 1px;
}}
QPushButton#dash_glow_btn {{
    background: {p['C_ACCENT']};
    color: {p['C_BG']};
    border: none;
    border-radius: 40px;
    padding: 20px 60px;
    font-size: 24px;
    font-weight: 900;
    font-family: {hf};
    letter-spacing: 3px;
    text-transform: uppercase;
    {f"border: 4px solid {p['C_ACCENT']};" if mode=='dojo' else ""}
}}

/* ═══ DOJO UI — Top Bar ═══════════════════════════════════════════════ */
QFrame#top_bar {{
    background: {p['C_SURFACE']};
    border-bottom: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}

/* Logo box */
QFrame#logo_box {{
    border: 2px solid {p['C_ACCENT']};
    border-radius: 5px;
    background: transparent;
}}
QLabel#logo_icon_lbl {{
    color: {p['C_ACCENT']};
    font-size: 14px;
    font-weight: 900;
    font-family: {hf};
    background: transparent;
    border: none;
}}
QLabel#app_logo {{
    color: {p['C_ACCENT']};
    font-family: {hf};
    font-weight: 900;
    font-size: 10px;
    letter-spacing: 2px;
    background: transparent;
    border: none;
}}
QLabel#logo_sub {{
    color: {p['C_SUBTEXT']};
    font-size: 7px;
    letter-spacing: 0.5px;
    background: transparent;
    border: none;
}}

/* Nav tabs */
QPushButton#nav_tab {{
    background: transparent;
    color: {p['C_SUBTEXT']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 4px 14px;
    font-family: {hf};
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QPushButton#nav_tab:hover {{
    color: {p['C_TEXT']};
}}
QPushButton#nav_tab[active="true"] {{
    color: {p['C_ACCENT']};
    border-bottom: 2px solid {p['C_ACCENT']};
}}

/* Mentor card */
QFrame#mentor_card_top {{
    background: rgba(168, 108, 255, 0.1);
    border: 1px solid #A86CFF;
    border-radius: 6px;
}}
QLabel#mentor_avatar {{
    color: #A86CFF;
    font-size: 18px;
    background: transparent;
    border: none;
}}
QLabel#mentor_quote {{
    color: #A86CFF;
    font-family: {hf};
    font-size: 6px;
    font-weight: 700;
    line-height: 1.5;
    background: transparent;
    border: none;
}}

/* ═══ DOJO UI — Sidebar ═══════════════════════════════════════════════ */
QWidget#side_panel, QFrame#side_panel {{
    background-color: {p['C_SURFACE']};
    background-image: {f"url({dojo_wall_main})" if mode == "dojo" else "none"};
    background-position: left bottom;
    background-repeat: no-repeat;
    border-right: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}
QFrame#sidebar_hdr_frame {{
    background: transparent;
    border-bottom: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}
QLabel#sidebar_hdr {{
    color: {p['C_ACCENT']};
    font-family: {hf};
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 2px;
    background: transparent;
    border: none;
}}
QFrame#sidebar_search {{
    background: {p['C_CARD']};
    border: 1px solid {p['C_BORDER']};
    border-radius: 4px;
    margin: 5px;
}}
QLabel#search_icon {{
    color: {p['C_SUBTEXT']};
    font-size: 11px;
    background: transparent;
    border: none;
}}
QLineEdit#search_input {{
    background: transparent;
    border: none;
    color: {p['C_TEXT']};
    font-size: 11px;
    font-family: {bf};
}}
QLabel#decks_sublabel {{
    color: {p['C_SUBTEXT']};
    font-family: {hf};
    font-size: 8px;
    letter-spacing: 1px;
    padding: 2px 0px;
    background: transparent;
    border: none;
}}
QFrame#sidebar_footer {{
    background: transparent;
    border-top: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}
QPushButton#sidebar_foot_btn {{
    background: {p['C_CARD']};
    color: {p['C_ACCENT']};
    border: 1px solid {p['C_ACCENT']};
    border-radius: 2px;
    padding: 4px 2px;
    font-family: {hf};
    font-size: 6px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#sidebar_foot_btn:hover {{
    background: rgba(114, 255, 79, 0.1);
}}
QPushButton#sidebar_foot_icon {{
    background: {p['C_CARD']};
    color: {p['C_SUBTEXT']};
    border: 1px solid {p['C_BORDER']};
    border-radius: 2px;
    font-size: 12px;
    padding: 0px;
}}

/* Tree items — retro style */
QTreeWidget {{
    background: transparent;
    border: none;
    padding: 2px 4px;
}}
QTreeWidget::item {{
    padding: 5px 6px;
    border-radius: 4px;
    border-left: 2px solid transparent;
    margin-bottom: 1px;
    font-family: {hf};
    font-size: 7px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {p['C_SUBTEXT']};
}}
QTreeWidget::item:selected {{
    background: { 'rgba(168, 108, 255, 0.15)' if mode == 'dojo' else ('rgba(95, 234, 208, 0.15)' if mode == 'arcanum' else 'rgba(0, 240, 255, 0.15)') };
    border-left: 2px solid {p['C_PURPLE']};
    color: {p['C_TEXT']};
}}
QTreeWidget::item:hover:!selected {{
    background: { 'rgba(95, 234, 208, 0.05)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.05)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.05)') };
    border-left: 2px solid { 'rgba(95, 234, 208, 0.2)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.2)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.2)') };
    color: #9090C0;
}}

/* Status bar — dojo quote style */
QStatusBar {{
    background: {p['C_SURFACE']};
    color: {p['C_ACCENT']};
    border-top: 1px solid {p['C_BORDER']};
    font-family: {'monospace'};
    font-size: 8px;
    letter-spacing: 1px;
    padding-left: 10px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {p['C_BG']};
    width: 8px;
    margin: 0px;
    border-left: 1px solid {p['C_BORDER']};
}}
QScrollBar::handle:vertical {{
    background: {p['C_BORDER'] if mode == 'classic' else ('rgba(95, 234, 208, 0.3)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.4)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.3)'))};
    border-radius: {'0px' if mode == 'manhattan' else '4px'};
}}
QScrollBar::handle:vertical:hover {{
    background: {p['C_SUBTEXT'] if mode == 'classic' else ('rgba(95, 234, 208, 0.6)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.8)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.6)'))};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: {p['C_BG']};
    height: 8px;
    margin: 0px;
    border-top: 1px solid {p['C_BORDER']};
}}
QScrollBar::handle:horizontal {{
    background: {p['C_BORDER'] if mode == 'classic' else ('rgba(95, 234, 208, 0.3)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.4)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.3)'))};
    border-radius: {'0px' if mode == 'manhattan' else '4px'};
}}
QScrollBar::handle:horizontal:hover {{
    background: {p['C_SUBTEXT'] if mode == 'classic' else ('rgba(95, 234, 208, 0.6)' if mode == 'arcanum' else ('rgba(0, 240, 255, 0.8)' if mode == 'manhattan' else 'rgba(114, 255, 79, 0.6)'))};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""
