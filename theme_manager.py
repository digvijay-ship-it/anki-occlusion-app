from PyQt5.QtGui import QColor

# ── Color Palettes ────────────────────────────────────────────────────────────

PALETTES = {
    "dojo": {
        "C_BG":      "#07070B",
        "C_SURFACE": "#0F0F17",
        "C_CARD":    "#14141F",
        "C_ACCENT":  "#72FF4F", # Neon Green
        "C_PURPLE":  "#A86CFF", # Arcade Purple
        "C_ORANGE":  "#FF9A2E",
        "C_GREEN":   "#72FF4F",
        "C_RED":     "#FF4444",
        "C_TEXT":    "#E0E0FF",
        "C_SUBTEXT": "#5F627D",
        "C_BORDER":  "#1A1A26",
        "C_YELLOW":  "#FFD700",
        "header_font": "'Orbitron', 'Oxanium', 'Segoe UI Black', sans-serif",
        "body_font":   "'Inter', 'Segoe UI', sans-serif",
    },
    "classic": {
        "C_BG":      "#F0F2F5",
        "C_SURFACE": "#FFFFFF",
        "C_CARD":    "#F8F9FA",
        "C_ACCENT":  "#4C6EF5", # Muted Blue
        "C_PURPLE":  "#7048E8",
        "C_ORANGE":  "#F59F00",
        "C_GREEN":   "#37B24D",
        "C_RED":     "#F03E3E",
        "C_TEXT":    "#212529",
        "C_SUBTEXT": "#868E96",
        "C_BORDER":  "#DEE2E6",
        "C_YELLOW":  "#FAB005",
        "header_font": "'Segoe UI', sans-serif",
        "body_font":   "'Segoe UI', sans-serif",
    }
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
    }
}

def get_palette(mode="dojo"):
    return PALETTES.get(mode, PALETTES["dojo"])

def get_label(key, mode="dojo"):
    return LABELS.get(mode, LABELS["dojo"]).get(key, key)

def build_stylesheet(mode="dojo", font_size=14):
    p = get_palette(mode)
    hf = p["header_font"]
    bf = p["body_font"]
    
    # UI Constants
    btn_radius = "0px" if mode == "dojo" else "6px"
    btn_border = "2px" if mode == "dojo" else "1px"
    btn_padding = "10px 20px" if mode == "dojo" else "6px 14px"
    
    raised = f"border-bottom: 3px solid rgba(0,0,0,0.5);" if mode == "dojo" else "border-bottom: 2px solid rgba(0,0,0,0.15);"

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
    background-image: {f"url(assets/themes/dojo/wall_hex_accent.png)" if mode == "dojo" else "none"};
    background-position: right top;
    background-repeat: no-repeat;
    border-left: 1px solid {p['C_BORDER']};
    border-radius: 0px;
}}
QWidget#side_panel, QFrame#side_panel {{
    background-color: {p['C_SURFACE']};
    background-image: {f"url(assets/themes/dojo/wall_main.png)" if mode == "dojo" else "none"};
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
    font-weight: bold;
    text-transform: {'uppercase' if mode=='dojo' else 'none'};
    letter-spacing: {'2px' if mode=='dojo' else '0px'};
}}
QPushButton:hover {{
    background: rgba(114, 255, 79, 0.1);
}}

/* Dominant CTA - START TRAINING */
QPushButton#cta_primary {{
    background: {p['C_ACCENT']};
    color: {p['C_BG']};
    border: none;
    border-radius: {btn_radius};
    padding: 12px 24px;
    font-family: {hf};
    font-weight: 900;
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
    background-image: {f"url(assets/themes/dojo/panel_overlay_subtle.png)" if mode == "dojo" else "none"};
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
    background-image: {f"url(assets/themes/dojo/wall_main.png)" if mode == "dojo" else "none"};
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

/* Tree items — ninja style */
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
    background: rgba(168, 108, 255, 0.15);
    border-left: 2px solid #A86CFF;
    color: {p['C_TEXT']};
}}
QTreeWidget::item:hover:!selected {{
    background: rgba(114, 255, 79, 0.05);
    border-left: 2px solid rgba(114, 255, 79, 0.2);
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
"""
