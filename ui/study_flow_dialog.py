# -*- coding: utf-8 -*-
"""
ui/study_flow_dialog.py
~~~~~~~~~~~~~~~~~~~~~~~
Daily Study Flow & Session Tile Planner Dialog.

Enables:
1. Target Chunking: Choose a subject deck, set daily target (e.g. 100 cards), pick chunk size (e.g. 25),
   and auto-generate session tiles.
2. Interleaved Playlist: Reorder / interleave subject chunks (Math -> GK -> English -> Math...)
   to maximize retention and prevent cognitive burnout.
3. Continuous Flow Launch: Emits flow_started to run through the entire daily playlist seamlessly.
4. Routine Presets: Save/load daily study routines (e.g. 'Daily Exam Sprint').

Responsive & Anti-Squint Design Standards:
- Dynamically fits within any screen resolution (1024x768 up to 4K) with hard-bounded viewport clamping.
- Strict NoWheelSlider protocol.
- Zero horizontal scrollbars.
- Generous readable desktop typography (17pt - 24pt).
- Memory flush on dialog close.
"""

import os

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QMessageBox, QScrollArea, QSlider, QSizePolicy,
    QComboBox, QSpinBox, QInputDialog, QApplication, QRadioButton, QMenu, QGridLayout
)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QFont

from theme_manager import get_palette, is_retro_theme
from data_manager import store
from services.study_flow_service import StudyFlowService, FlowTile, DailyStudyPlan
from perf_utils import card_has_due_today, count_due_units_in_card, count_new_units_in_card, flush_process_memory

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
DOWN_ARROW_PATH = os.path.join(ICONS_DIR, "down_arrow.svg").replace("\\", "/")
if not os.path.exists(DOWN_ARROW_PATH):
    os.makedirs(ICONS_DIR, exist_ok=True)
    with open(DOWN_ARROW_PATH, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#39FF14" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>')


class NoWheelSlider(QSlider):
    """Slider that ignores mouse wheel scrolling to prevent accidental value alterations inside scroll areas."""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(QComboBox):
    """ComboBox that ignores mouse wheel scrolling to prevent accidental item switching inside scroll areas."""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    """SpinBox that ignores mouse wheel scrolling to prevent accidental value alterations inside scroll areas."""
    def wheelEvent(self, event):
        event.ignore()


SUBJECT_THEMES = [
    {
        "name": "purple",
        "primary": "#A855F7",       # Vibrant Royal Purple
        "border": "#A855F7",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(168, 85, 247, 0.22), stop:0.45 rgba(168, 85, 247, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(168, 85, 247, 0.25)",
        "badge_text": "#F3E8FF",
        "text": "#E9D5FF",
        "icon": "🟣",
    },
    {
        "name": "amber",
        "primary": "#F59E0B",       # Vivid Amber / Gold
        "border": "#F59E0B",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(245, 158, 11, 0.22), stop:0.45 rgba(245, 158, 11, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(245, 158, 11, 0.25)",
        "badge_text": "#FEF3C7",
        "text": "#FDE68A",
        "icon": "🟡",
    },
    {
        "name": "cyan",
        "primary": "#00D2FF",       # Electric Cyan / Aqua
        "border": "#00D2FF",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 210, 255, 0.22), stop:0.45 rgba(0, 210, 255, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(0, 210, 255, 0.25)",
        "badge_text": "#E0F7FF",
        "text": "#7CE8FF",
        "icon": "🔵",
    },
    {
        "name": "emerald",
        "primary": "#10B981",       # Emerald Green
        "border": "#10B981",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(16, 185, 129, 0.22), stop:0.45 rgba(16, 185, 129, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(16, 185, 129, 0.25)",
        "badge_text": "#D1FAE5",
        "text": "#A7F3D0",
        "icon": "🟢",
    },
    {
        "name": "rose",
        "primary": "#F43F5E",       # Coral / Rose
        "border": "#F43F5E",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(244, 63, 94, 0.22), stop:0.45 rgba(244, 63, 94, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(244, 63, 94, 0.25)",
        "badge_text": "#FFE4E6",
        "text": "#FECDD3",
        "icon": "🔴",
    },
    {
        "name": "sky",
        "primary": "#38BDF8",       # Sky Blue
        "border": "#38BDF8",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(56, 189, 248, 0.22), stop:0.45 rgba(56, 189, 248, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(56, 189, 248, 0.25)",
        "badge_text": "#E0F2FE",
        "text": "#BAE6FD",
        "icon": "🔷",
    },
    {
        "name": "fuchsia",
        "primary": "#D946EF",       # Fuchsia / Magenta
        "border": "#D946EF",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(217, 70, 239, 0.22), stop:0.45 rgba(217, 70, 239, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(217, 70, 239, 0.25)",
        "badge_text": "#FDF4FF",
        "text": "#F5D0FE",
        "icon": "🌸",
    },
    {
        "name": "teal",
        "primary": "#14B8A6",       # Teal
        "border": "#14B8A6",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(20, 184, 166, 0.22), stop:0.45 rgba(20, 184, 166, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(20, 184, 166, 0.25)",
        "badge_text": "#CCFBF1",
        "text": "#99F6E4",
        "icon": "🩵",
    },
    {
        "name": "orange",
        "primary": "#FB923C",       # Orange
        "border": "#FB923C",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(251, 146, 60, 0.22), stop:0.45 rgba(251, 146, 60, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(251, 146, 60, 0.25)",
        "badge_text": "#FFEDD5",
        "text": "#FED7AA",
        "icon": "🟠",
    },
    {
        "name": "lime",
        "primary": "#84CC16",       # Lime
        "border": "#84CC16",
        "bg_gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(132, 204, 22, 0.22), stop:0.45 rgba(132, 204, 22, 0.07), stop:1 rgba(20, 26, 38, 0.95))",
        "badge_bg": "rgba(132, 204, 22, 0.25)",
        "badge_text": "#F7FEE7",
        "text": "#D9F99D",
        "icon": "🟢",
    },
]


def get_root_decks_from_store():
    """Retrieve only top-level parent decks with recursive card, due, and new units."""
    data = store.get()
    decks = data.get("decks", [])
    results = []

    for d in decks or []:
        if not isinstance(d, dict):
            continue
        name = d.get("name", "Unnamed Deck")
        did = d.get("_id") or d.get("id")

        cards = StudyFlowService.collect_all_deck_cards(d, recursive=True)
        due_u = sum(count_due_units_in_card(c) for c in cards)
        new_u = sum(count_new_units_in_card(c) for c in cards)

        results.append({
            "deck": d,
            "id": did,
            "name": name,
            "path": name,
            "card_count": len(cards),
            "due_count": due_u,
            "new_count": new_u,
            "has_children": bool(d.get("children", []) or d.get("subdecks", [])),
        })

    results.sort(key=lambda x: x["name"].lower())
    return results


def get_subdecks_for_deck(root_deck_dict):
    """Retrieve all subdecks/chapters belonging to a root parent deck, walking its tree."""
    d = root_deck_dict.get("deck") if isinstance(root_deck_dict, dict) else None
    if not d or not isinstance(d, dict):
        return []

    results = []

    def _walk(children, level=1, parent_path=""):
        for c in children or []:
            if not isinstance(c, dict):
                continue
            name = c.get("name", "Unnamed Subdeck")
            curr_path = f"{parent_path} / {name}" if parent_path else name
            did = c.get("_id") or c.get("id")

            cards = StudyFlowService.collect_all_deck_cards(c, recursive=True)
            due_u = sum(count_due_units_in_card(sc) for sc in cards)
            new_u = sum(count_new_units_in_card(sc) for sc in cards)

            results.append({
                "deck": c,
                "id": did,
                "name": name,
                "path": curr_path,
                "level": level,
                "card_count": len(cards),
                "due_count": due_u,
                "new_count": new_u,
            })
            sub_children = c.get("children", []) or c.get("subdecks", [])
            _walk(sub_children, level + 1, curr_path)

    children = d.get("children", []) or d.get("subdecks", [])
    _walk(children)
    return results


def get_all_decks_from_store():
    """Retrieve all decks flattened into hierarchical paths with due units and new units."""
    data = store.get()
    decks = data.get("decks", [])
    results = []

    def _walk(d_list, parent_path=""):
        for d in d_list or []:
            if not isinstance(d, dict):
                continue
            name = d.get("name", "Unnamed Deck")
            curr_path = f"{parent_path} / {name}" if parent_path else name
            did = d.get("_id") or d.get("id")

            cards = StudyFlowService.collect_all_deck_cards(d, recursive=True)
            due_u = sum(count_due_units_in_card(c) for c in cards)
            new_u = sum(count_new_units_in_card(c) for c in cards)

            results.append({
                "id": did,
                "name": name,
                "path": curr_path,
                "card_count": len(cards),
                "due_count": due_u,
                "new_count": new_u,
            })
            children = d.get("children", []) or d.get("subdecks", [])
            _walk(children, curr_path)

    _walk(decks)
    results.sort(key=lambda x: x["path"].lower())
    return results


class StudyFlowDialog(QDialog):
    """
    Main modal for planning, interleaving, and launching daily study flows.
    """

    flow_started = pyqtSignal(object)  # Emits DailyStudyPlan

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 Daily Study Flow Planner")
        self.setModal(True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowState(Qt.WindowMaximized)

        self.plan = StudyFlowService.get_or_create_today_plan()
        self.selected_parts = 4
        self._active_card_mode = "mixed"
        self._interleave_active = True
        self._subject_color_map = {}
        self._init_subject_themes()

        self._init_ui()
        self._setup_window_geometry()
        self._refresh_playlist_ui()

    def _init_subject_themes(self):
        """Map existing root decks and plan tiles to unique theme colors deterministically."""
        if not hasattr(self, "_subject_color_map"):
            self._subject_color_map = {}
        roots = get_root_decks_from_store()
        for idx, r in enumerate(roots):
            rname = (r.get("name") or "").strip()
            if rname and rname not in self._subject_color_map:
                self._subject_color_map[rname] = SUBJECT_THEMES[len(self._subject_color_map) % len(SUBJECT_THEMES)]
        if hasattr(self, "plan") and self.plan and self.plan.tiles:
            for t in self.plan.tiles:
                raw_path = t.deck_path or t.deck_name or "General"
                root = raw_path.split("/")[0].strip()
                if root and root not in self._subject_color_map:
                    self._subject_color_map[root] = SUBJECT_THEMES[len(self._subject_color_map) % len(SUBJECT_THEMES)]

    def _get_theme_for_deck(self, deck_path: str, deck_name: str) -> dict:
        """Deterministically returns a distinct visual color theme for each root subject."""
        raw_path = deck_path or deck_name or "General"
        root = raw_path.split("/")[0].strip()
        if not root:
            root = "General"
        if not hasattr(self, "_subject_color_map"):
            self._subject_color_map = {}
        if root not in self._subject_color_map:
            self._subject_color_map[root] = SUBJECT_THEMES[len(self._subject_color_map) % len(SUBJECT_THEMES)]
        return self._subject_color_map[root]

    def _setup_window_geometry(self):
        """Fullscreen dialog strictly clamped to the current monitor with zero multi-monitor overflow."""
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowMinimizeButtonHint
        )
        screen = None
        if self.parent() and hasattr(self.parent(), "screen"):
            screen = self.parent().screen()
        if not screen:
            screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.setMaximumSize(geo.width(), geo.height())
            self.setGeometry(geo)
        self.showFullScreen()

    def showEvent(self, event):
        super().showEvent(event)
        screen = None
        if self.parent() and hasattr(self.parent(), "screen"):
            screen = self.parent().screen()
        if not screen:
            screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.setMaximumSize(geo.width(), geo.height())
            self.setGeometry(geo)
        self.showFullScreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        flush_process_memory()
        super().closeEvent(event)

    def _init_ui(self):
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_bg = palette.get("C_BG", "#0A0B11")
        c_surface = palette.get("C_SURFACE", "#141A24")
        c_card = palette.get("C_CARD", "#1A2232")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_btn_text = "#000000" if is_retro_theme() else "#FFFFFF"
        c_text = palette.get("C_TEXT", "#FFFFFF")
        c_subtext = palette.get("C_SUBTEXT", "#A0AEC0")
        c_border = palette.get("C_BORDER", "#4E6182")

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c_bg};
                color: {c_text};
            }}
            QFrame#panelFrame {{
                background-color: {c_surface};
                border: 1px solid {c_border};
                border-radius: 12px;
            }}
            QFrame#tileCard {{
                background-color: {c_card};
                border: 1px solid {c_border};
                border-radius: 8px;
            }}
            QFrame#statsCard {{
                background-color: rgba(57, 255, 20, 0.08);
                border: 1px solid {c_neon};
                border-radius: 10px;
            }}
            QComboBox {{
                background-color: {c_card};
                color: {c_text};
                border: 2px solid {c_border};
                border-radius: 8px;
                padding: 8px 14px;
                padding-right: 48px;
                min-height: 44px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 17px;
                font-weight: 600;
            }}
            QComboBox:hover {{
                border-color: {c_neon};
            }}
            QComboBox:focus {{
                border-color: {c_neon};
            }}
            QComboBox:disabled {{
                background-color: #141A24;
                color: #55657E;
                border-color: #2D3A4F;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 44px;
                border-left: 2px solid {c_border};
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background-color: #242F42;
            }}
            QComboBox::drop-down:hover {{
                background-color: #33425B;
            }}
            QComboBox::down-arrow {{
                image: url("{DOWN_ARROW_PATH}");
                width: 18px;
                height: 18px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c_surface};
                color: {c_text};
                selection-background-color: {c_neon};
                selection-color: {c_btn_text};
                border: 2px solid {c_border};
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 16px;
            }}
            QScrollBar:vertical {{
                background: {c_bg};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {c_border};
                min-height: 20px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {c_neon};
            }}
        """)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 18, 24, 18)
        root_layout.setSpacing(14)

        # ── 1. Top Header ────────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        lbl_title = QLabel("🎯 STUDY FLOW PLANNER")
        lbl_title.setFont(QFont("Segoe UI", 26, QFont.Black))
        lbl_title.setStyleSheet(f"color: {c_neon};")
        header_layout.addWidget(lbl_title)

        header_layout.addStretch()

        btn_close = QPushButton("✕ CLOSE")
        btn_close.setFont(QFont("Segoe UI", 16, QFont.Bold))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_subtext};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 8px 18px;
            }}
            QPushButton:hover {{
                color: #FFFFFF;
                border-color: #FFFFFF;
            }}
        """)
        btn_close.clicked.connect(self.close)
        header_layout.addWidget(btn_close)
        root_layout.addLayout(header_layout)

        # Subtitle / Hint
        lbl_hint = QLabel(
            "विषयों को छोटे-छोटे सत्रों (Session Chunks) में बांटें और उन्हें अपनी मनपसंद प्लेलिस्ट में व्यवस्थित करें। "
            "एक क्लिक में ऑटो-फ्लो शुरू करें — बिना बार-बार होम स्क्रीन पर आए!"
        )
        lbl_hint.setFont(QFont("Segoe UI", 17, QFont.Normal))
        lbl_hint.setStyleSheet(f"color: {c_subtext};")
        lbl_hint.setWordWrap(True)
        lbl_hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        root_layout.addWidget(lbl_hint)

        # ── 2. Master Two-Column Workspace ──────────────────────────────────
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(20)

        # ── Left Column: Target & Chunk Generator (Balanced 520px width with Inner Scroll Area) ────
        left_panel = QFrame()
        left_panel.setObjectName("panelFrame")
        left_panel.setFixedWidth(520)
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(18, 16, 12, 16)
        left_panel_layout.setSpacing(10)

        lbl_gen_title = QLabel("➕ 1. ADD SESSIONS (सत्र जोड़ें)")
        lbl_gen_title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        lbl_gen_title.setStyleSheet("color: #FFFFFF;")
        left_panel_layout.addWidget(lbl_gen_title)

        # Scroll area for form inputs inside left panel
        self._scroll_left = QScrollArea()
        self._scroll_left.setWidgetResizable(True)
        self._scroll_left.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_left.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_left.setStyleSheet("background: transparent; border: none;")

        left_content = QWidget()
        left_content.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left_content)
        left_layout.setContentsMargins(0, 2, 8, 2)
        left_layout.setSpacing(8)

        # Root Deck Selector
        lbl_root = QLabel("📌 Main Subject / Parent Deck:")
        lbl_root.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_root.setStyleSheet(f"color: {c_subtext};")
        left_layout.addWidget(lbl_root)

        self._combo_root_decks = NoWheelComboBox()
        self._combo_root_decks.setFont(QFont("Segoe UI", 18, QFont.DemiBold))
        self._combo_root_decks.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if self._combo_root_decks.view():
            self._combo_root_decks.view().setMinimumWidth(500)
            self._combo_root_decks.view().setFont(QFont("Segoe UI", 16, QFont.Normal))
        left_layout.addWidget(self._combo_root_decks)

        # Subdeck / Chapter Selector
        lbl_sub = QLabel("📂 Chapter / Subdeck (Optional):")
        lbl_sub.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_sub.setStyleSheet(f"color: {c_subtext};")
        left_layout.addWidget(lbl_sub)

        self._combo_subdecks = NoWheelComboBox()
        self._combo_subdecks.setFont(QFont("Segoe UI", 18, QFont.DemiBold))
        self._combo_subdecks.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if self._combo_subdecks.view():
            self._combo_subdecks.view().setMinimumWidth(500)
            self._combo_subdecks.view().setFont(QFont("Segoe UI", 16, QFont.Normal))
        left_layout.addWidget(self._combo_subdecks)

        # Mode Selector
        lbl_mode = QLabel("🎯 Study Mode:")
        lbl_mode.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_mode.setStyleSheet(f"color: {c_subtext};")
        left_layout.addWidget(lbl_mode)

        self._combo_mode = NoWheelComboBox()
        self._combo_mode.setFont(QFont("Segoe UI", 18, QFont.DemiBold))
        self._combo_mode.addItem("📖 Due Cards First (Spaced Repetition)", "due")
        self._combo_mode.addItem("✨ New Cards Only (Learn First Time)", "new")
        self._combo_mode.addItem("🎯 Practice All Cards (No Reschedule)", "all")
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        left_layout.addWidget(self._combo_mode)

        # ── Mode-Aware Target Controls ─────────────────────────────────────
        self._target_container = QWidget()
        target_vbox = QVBoxLayout(self._target_container)
        target_vbox.setContentsMargins(0, 0, 0, 0)
        target_vbox.setSpacing(10)

        # A) Single Mode Target Frame (for 'due' or 'new')
        self._single_target_frame = QWidget()
        single_layout = QVBoxLayout(self._single_target_frame)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(8)

        single_header = QHBoxLayout()
        self._lbl_single_title = QLabel("Target Due:")
        self._lbl_single_title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._lbl_single_title.setStyleSheet(f"color: {c_subtext};")
        single_header.addWidget(self._lbl_single_title)

        self._lbl_single_avail = QLabel("(Avail: 0)")
        self._lbl_single_avail.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._lbl_single_avail.setStyleSheet("color: #FFB300;")
        single_header.addWidget(self._lbl_single_avail)

        single_header.addStretch()

        self._btn_single_max = QPushButton("All")
        self._btn_single_max.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self._btn_single_max.setCursor(Qt.PointingHandCursor)
        self._btn_single_max.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_neon};
                border: 1px solid {c_neon};
                border-radius: 6px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: rgba(57, 255, 20, 0.15);
            }}
        """)
        self._btn_single_max.clicked.connect(self._on_single_max_clicked)
        single_header.addWidget(self._btn_single_max)

        self._spin_single_target = NoWheelSpinBox()
        self._spin_single_target.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._spin_single_target.setRange(0, 2000)
        self._spin_single_target.setValue(50)
        self._spin_single_target.setSingleStep(5)
        self._spin_single_target.setFixedWidth(110)
        self._spin_single_target.setStyleSheet(f"""
            QSpinBox {{
                background-color: {c_card};
                color: {c_neon};
                border: 2px solid {c_border};
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 18px;
            }}
            QSpinBox:focus {{
                border-color: {c_neon};
            }}
        """)
        self._spin_single_target.valueChanged.connect(self._on_single_spin_changed)
        single_header.addWidget(self._spin_single_target)
        single_layout.addLayout(single_header)

        self._slider_single_target = NoWheelSlider(Qt.Horizontal)
        self._slider_single_target.setRange(0, 1000)
        self._slider_single_target.setValue(50)
        self._slider_single_target.setSingleStep(5)
        self._slider_single_target.valueChanged.connect(self._on_single_slider_changed)
        self._slider_single_target.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 8px;
                background: {c_border};
                border-radius: 4px;
            }}
            QSlider::sub-page:horizontal {{
                background: {c_neon};
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 2px solid {c_neon};
                width: 24px;
                margin-top: -8px;
                margin-bottom: -8px;
                border-radius: 12px;
            }}
        """)
        single_layout.addWidget(self._slider_single_target)
        target_vbox.addWidget(self._single_target_frame)

        # B) Dual Target Frame (for 'all' mode: Due + New targets)
        self._dual_target_frame = QWidget()
        dual_layout = QVBoxLayout(self._dual_target_frame)
        dual_layout.setContentsMargins(0, 0, 0, 0)
        dual_layout.setSpacing(8)

        # Dual Row 1: Due Target
        dual_due_header = QHBoxLayout()
        dual_due_header.setSpacing(10)
        lbl_due = QLabel("⏳ Due:")
        lbl_due.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_due.setStyleSheet(f"color: {c_subtext};")
        dual_due_header.addWidget(lbl_due)

        self._lbl_dual_due_avail = QLabel("(Avail: 0)")
        self._lbl_dual_due_avail.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._lbl_dual_due_avail.setStyleSheet("color: #FFB300;")
        dual_due_header.addWidget(self._lbl_dual_due_avail)

        dual_due_header.addStretch()

        self._btn_dual_due_max = QPushButton("All Due")
        self._btn_dual_due_max.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self._btn_dual_due_max.setCursor(Qt.PointingHandCursor)
        self._btn_dual_due_max.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_neon};
                border: 1px solid {c_neon};
                border-radius: 6px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: rgba(57, 255, 20, 0.15);
            }}
        """)
        self._btn_dual_due_max.clicked.connect(self._on_dual_due_max_clicked)
        dual_due_header.addWidget(self._btn_dual_due_max)

        self._spin_dual_due = NoWheelSpinBox()
        self._spin_dual_due.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._spin_dual_due.setRange(0, 2000)
        self._spin_dual_due.setValue(25)
        self._spin_dual_due.setSingleStep(5)
        self._spin_dual_due.setFixedWidth(105)
        self._spin_dual_due.setStyleSheet(f"""
            QSpinBox {{
                background-color: {c_card};
                color: {c_neon};
                border: 2px solid {c_border};
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 18px;
            }}
            QSpinBox:focus {{
                border-color: {c_neon};
            }}
        """)
        self._spin_dual_due.valueChanged.connect(self._on_dual_due_spin_changed)
        dual_due_header.addWidget(self._spin_dual_due)
        dual_layout.addLayout(dual_due_header)

        self._slider_dual_due = NoWheelSlider(Qt.Horizontal)
        self._slider_dual_due.setRange(0, 1000)
        self._slider_dual_due.setValue(25)
        self._slider_dual_due.setSingleStep(5)
        self._slider_dual_due.valueChanged.connect(self._on_dual_due_slider_changed)
        self._slider_dual_due.setStyleSheet(self._slider_single_target.styleSheet())
        dual_layout.addWidget(self._slider_dual_due)

        # Dual Row 2: New Target
        dual_new_header = QHBoxLayout()
        dual_new_header.setSpacing(10)
        lbl_new = QLabel("✨ New:")
        lbl_new.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_new.setStyleSheet(f"color: {c_subtext};")
        dual_new_header.addWidget(lbl_new)

        self._lbl_dual_new_avail = QLabel("(Avail: 0)")
        self._lbl_dual_new_avail.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._lbl_dual_new_avail.setStyleSheet("color: #FFB300;")
        dual_new_header.addWidget(self._lbl_dual_new_avail)

        dual_new_header.addStretch()

        self._btn_dual_new_max = QPushButton("All New")
        self._btn_dual_new_max.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self._btn_dual_new_max.setCursor(Qt.PointingHandCursor)
        self._btn_dual_new_max.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_neon};
                border: 1px solid {c_neon};
                border-radius: 6px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: rgba(57, 255, 20, 0.15);
            }}
        """)
        self._btn_dual_new_max.clicked.connect(self._on_dual_new_max_clicked)
        dual_new_header.addWidget(self._btn_dual_new_max)

        self._spin_dual_new = NoWheelSpinBox()
        self._spin_dual_new.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._spin_dual_new.setRange(0, 2000)
        self._spin_dual_new.setValue(25)
        self._spin_dual_new.setSingleStep(5)
        self._spin_dual_new.setFixedWidth(105)
        self._spin_dual_new.setStyleSheet(self._spin_dual_due.styleSheet())
        self._spin_dual_new.valueChanged.connect(self._on_dual_new_spin_changed)
        dual_new_header.addWidget(self._spin_dual_new)
        dual_layout.addLayout(dual_new_header)

        self._slider_dual_new = NoWheelSlider(Qt.Horizontal)
        self._slider_dual_new.setRange(0, 1000)
        self._slider_dual_new.setValue(25)
        self._slider_dual_new.setSingleStep(5)
        self._slider_dual_new.valueChanged.connect(self._on_dual_new_slider_changed)
        self._slider_dual_new.setStyleSheet(self._slider_single_target.styleSheet())
        dual_layout.addWidget(self._slider_dual_new)

        # Dual Row 3: Live Summary Pill
        self._lbl_dual_total = QLabel("🎯 Total Target: 50 Cards (25 Due + 25 New)")
        self._lbl_dual_total.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._lbl_dual_total.setWordWrap(False)
        self._lbl_dual_total.setFixedHeight(46)
        self._lbl_dual_total.setAlignment(Qt.AlignCenter)
        self._lbl_dual_total.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(57, 255, 20, 0.09);
                color: {c_neon};
                border: 1.5px solid {c_neon};
                border-radius: 8px;
                padding: 6px 14px;
            }}
        """)
        dual_layout.addWidget(self._lbl_dual_total)

        target_vbox.addWidget(self._dual_target_frame)
        self._dual_target_frame.hide()

        left_layout.addWidget(self._target_container)

        # Divide into Sessions (Parts) Header
        parts_header_layout = QHBoxLayout()
        lbl_parts_title = QLabel("Sessions (सत्र संख्या):")
        lbl_parts_title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        lbl_parts_title.setStyleSheet(f"color: {c_subtext};")
        parts_header_layout.addWidget(lbl_parts_title)

        parts_header_layout.addStretch()

        self._spin_parts = NoWheelSpinBox()
        self._spin_parts.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._spin_parts.setRange(1, 20)
        self._spin_parts.setValue(self.selected_parts)
        self._spin_parts.setFixedWidth(75)
        self._spin_parts.setStyleSheet(f"""
            QSpinBox {{
                background-color: {c_card};
                color: #FFFFFF;
                border: 2px solid {c_border};
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 18px;
            }}
            QSpinBox:focus {{
                border-color: {c_neon};
            }}
        """)
        self._spin_parts.valueChanged.connect(self._on_parts_spin_changed)
        parts_header_layout.addWidget(self._spin_parts)
        left_layout.addLayout(parts_header_layout)

        # Quick Preset Buttons for Division (Crisp bold numbers)
        parts_btn_layout = QHBoxLayout()
        parts_btn_layout.setSpacing(8)
        self._part_buttons = []
        for n in [2, 3, 4, 5, 6]:
            btn = QPushButton(f"{n}")
            btn.setFont(QFont("Segoe UI", 18, QFont.Bold))
            btn.setFixedHeight(42)
            btn.setMinimumWidth(56)
            btn.setCheckable(True)
            btn.setChecked(n == self.selected_parts)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._part_button_style(n == self.selected_parts))
            btn.clicked.connect(lambda checked, num=n: self._set_parts(num))
            parts_btn_layout.addWidget(btn)
            self._part_buttons.append((n, btn))
        left_layout.addLayout(parts_btn_layout)

        # Chunk Preview Label
        self._lbl_chunk_preview = QLabel()
        self._lbl_chunk_preview.setFont(QFont("Segoe UI", 17, QFont.DemiBold))
        self._lbl_chunk_preview.setStyleSheet("color: #FFB300;")
        self._lbl_chunk_preview.setWordWrap(True)
        self._lbl_chunk_preview.setMinimumHeight(38)
        left_layout.addWidget(self._lbl_chunk_preview)
        self._update_chunk_preview()

        # Populate root decks & subdecks now that all left controls are initialized
        self._populate_root_decks()
        self._combo_root_decks.currentIndexChanged.connect(self._on_root_deck_changed)
        self._combo_subdecks.currentIndexChanged.connect(self._on_subdeck_changed)

        left_layout.addStretch()
        self._scroll_left.setWidget(left_content)
        left_panel_layout.addWidget(self._scroll_left, 1)

        # Add Button pinned at bottom of left panel!
        self._btn_add_tiles = QPushButton("+ ADD TO PLAYLIST")
        self._btn_add_tiles.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self._btn_add_tiles.setCursor(Qt.PointingHandCursor)
        self._btn_add_tiles.setMinimumHeight(54)
        self._btn_add_tiles.setStyleSheet(f"""
            QPushButton {{
                background-color: {c_neon};
                color: {'#000000' if is_retro_theme() else '#FFFFFF'};
                font-weight: 800;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
            }}
            QPushButton:hover {{
                background-color: {'#55FF33' if is_retro_theme() else '#9585FA'};
            }}
        """)
        self._btn_add_tiles.clicked.connect(self._on_add_tiles_clicked)
        left_panel_layout.addWidget(self._btn_add_tiles)

        body_layout.addWidget(left_panel)


        # ── Right Column: Playlist & Interleaving ────────────────────────────
        right_panel = QFrame()
        right_panel.setObjectName("panelFrame")
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(22, 18, 22, 18)
        right_layout.setSpacing(14)

        # Playlist Header & Stats
        top_pl_layout = QHBoxLayout()
        lbl_pl_title = QLabel("📋 2. TODAY'S PLAYLIST")
        lbl_pl_title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        lbl_pl_title.setStyleSheet("color: #FFFFFF;")
        top_pl_layout.addWidget(lbl_pl_title)

        top_pl_layout.addStretch()

        self._btn_clear_plan = QPushButton("🔄 Clear All")
        self._btn_clear_plan.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._btn_clear_plan.setCursor(Qt.PointingHandCursor)
        self._btn_clear_plan.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_subtext};
                border: 1px solid {c_border};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                color: #FF5A66;
                border-color: #FF5A66;
            }}
        """)
        self._btn_clear_plan.clicked.connect(self._on_clear_plan_clicked)
        top_pl_layout.addWidget(self._btn_clear_plan)
        right_layout.addLayout(top_pl_layout)

        # Live Summary Card
        self._stats_frame = QFrame()
        self._stats_frame.setObjectName("statsCard")
        stats_layout = QHBoxLayout(self._stats_frame)
        stats_layout.setContentsMargins(18, 12, 18, 12)

        self._lbl_stat_cards = QLabel("0 Cards")
        self._lbl_stat_cards.setFont(QFont("Segoe UI", 28, QFont.Black))
        self._lbl_stat_cards.setStyleSheet(f"color: {c_neon};")
        stats_layout.addWidget(self._lbl_stat_cards)

        stats_layout.addSpacing(24)

        self._lbl_stat_tiles = QLabel("0 Tiles")
        self._lbl_stat_tiles.setFont(QFont("Segoe UI", 28, QFont.Black))
        self._lbl_stat_tiles.setStyleSheet(f"color: {c_text};")
        stats_layout.addWidget(self._lbl_stat_tiles)

        stats_layout.addSpacing(24)

        self._lbl_stat_time = QLabel("~0 Mins")
        self._lbl_stat_time.setFont(QFont("Segoe UI", 28, QFont.Black))
        self._lbl_stat_time.setStyleSheet("color: #FFB300;")
        stats_layout.addWidget(self._lbl_stat_time)

        stats_layout.addStretch()
        right_layout.addWidget(self._stats_frame)

        # Subject Progress Dashboard Strip (Option A: Parent Deck Totals & Progress)
        self._subject_progress_frame = QFrame()
        self._subject_progress_frame.setObjectName("subjectProgressFrame")
        self._subject_progress_frame.setStyleSheet(f"""
            QFrame#subjectProgressFrame {{
                background-color: rgba(15, 23, 42, 0.7);
                border: 1.5px solid {c_border};
                border-radius: 8px;
            }}
        """)
        self._subject_progress_layout = QGridLayout(self._subject_progress_frame)
        self._subject_progress_layout.setContentsMargins(12, 8, 12, 8)
        self._subject_progress_layout.setHorizontalSpacing(10)
        self._subject_progress_layout.setVerticalSpacing(8)
        right_layout.addWidget(self._subject_progress_frame)

        # Flow Sorter Toolbar (Mixed Flow, Due First, New First, Interleave)
        flow_toolbar_frame = QFrame()
        flow_toolbar_frame.setObjectName("flowToolbar")
        flow_toolbar_frame.setStyleSheet(f"""
            QFrame#flowToolbar {{
                background-color: {c_card};
                border: 1.5px solid {c_border};
                border-radius: 8px;
            }}
        """)
        flow_layout = QHBoxLayout(flow_toolbar_frame)
        flow_layout.setContentsMargins(12, 6, 12, 6)
        flow_layout.setSpacing(12)

        lbl_flow_title = QLabel("⚡ Card Flow:")
        lbl_flow_title.setFont(QFont("Segoe UI", 17, QFont.Bold))
        lbl_flow_title.setStyleSheet(f"color: {c_subtext};")
        flow_layout.addWidget(lbl_flow_title)

        self._btn_flow_mixed = QPushButton("🔀 Mixed")
        self._btn_flow_mixed.setToolTip("🔀 Mixed: हर सत्र में Due और New कार्ड्स मिलाकर पढ़ें")
        self._btn_flow_due = QPushButton("⏳ Due First")
        self._btn_flow_due.setToolTip("⏳ Due First: पुराने रिव्यु कार्ड्स पहले आएंगे, नए कार्ड्स बाद में")
        self._btn_flow_new = QPushButton("✨ New First")
        self._btn_flow_new.setToolTip("✨ New First: नए कार्ड्स पहले आएंगे, पुराने कार्ड्स बाद में")

        self._card_mode_buttons = [
            ("mixed", self._btn_flow_mixed),
            ("due_first", self._btn_flow_due),
            ("new_first", self._btn_flow_new),
        ]

        for mode_key, btn in self._card_mode_buttons:
            btn.setFont(QFont("Segoe UI", 16, QFont.Bold))
            btn.setFixedHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda _, m=mode_key: self._on_card_mode_clicked(m))
            flow_layout.addWidget(btn)

        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.VLine)
        sep_line.setFrameShadow(QFrame.Sunken)
        sep_line.setStyleSheet(f"background-color: {c_border}; width: 1.5px; margin: 4px 6px;")
        flow_layout.addWidget(sep_line)

        self._btn_interleave_toggle = QPushButton("🎲 Interleave: ON")
        self._btn_interleave_toggle.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._btn_interleave_toggle.setFixedHeight(44)
        self._btn_interleave_toggle.setCursor(Qt.PointingHandCursor)
        self._btn_interleave_toggle.setFocusPolicy(Qt.NoFocus)
        self._btn_interleave_toggle.setToolTip("🎲 Interleave: विषयों को बारी-बारी से चक्रानुक्रम में बदलें (Math ➔ BlackBook ➔ GK...)")
        self._btn_interleave_toggle.clicked.connect(self._on_interleave_toggled)
        flow_layout.addWidget(self._btn_interleave_toggle)

        flow_layout.addStretch()
        right_layout.addWidget(flow_toolbar_frame)

        # Scroll Area for Tiles inside Playlist
        self._scroll_playlist = QScrollArea()
        self._scroll_playlist.setWidgetResizable(True)
        self._scroll_playlist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_playlist.setStyleSheet("background: transparent; border: none;")

        self._playlist_container = QWidget()
        self._playlist_vbox = QVBoxLayout(self._playlist_container)
        self._playlist_vbox.setContentsMargins(0, 4, 8, 4)
        self._playlist_vbox.setSpacing(10)
        self._scroll_playlist.setWidget(self._playlist_container)

        right_layout.addWidget(self._scroll_playlist, 1)

        body_layout.addWidget(right_panel, 1)

        root_layout.addLayout(body_layout, 1)

        # ── 3. Bottom Action Bar ─────────────────────────────────────────────
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        self._btn_save_routine = QPushButton("💾 Save Routine")
        self._btn_save_routine.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._btn_save_routine.setCursor(Qt.PointingHandCursor)
        self._btn_save_routine.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_text};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 12px 22px;
            }}
            QPushButton:hover {{
                border-color: {c_neon};
                color: {c_neon};
            }}
        """)
        self._btn_save_routine.clicked.connect(self._on_save_routine_clicked)
        bottom_bar.addWidget(self._btn_save_routine)

        self._btn_load_routine = QPushButton("📂 Load Routine")
        self._btn_load_routine.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._btn_load_routine.setCursor(Qt.PointingHandCursor)
        self._btn_load_routine.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c_text};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 12px 22px;
            }}
            QPushButton:hover {{
                border-color: {c_neon};
                color: {c_neon};
            }}
        """)
        self._btn_load_routine.clicked.connect(self._on_load_routine_clicked)
        bottom_bar.addWidget(self._btn_load_routine)

        bottom_bar.addStretch()

        self._btn_start_flow = QPushButton("🚀 START STUDY FLOW")
        self._btn_start_flow.setFont(QFont("Segoe UI", 21, QFont.Bold))
        self._btn_start_flow.setCursor(Qt.PointingHandCursor)
        self._btn_start_flow.setMinimumHeight(56)
        self._btn_start_flow.setStyleSheet(f"""
            QPushButton {{
                background-color: {c_neon};
                color: {c_btn_text};
                border: none;
                border-radius: 8px;
                padding: 12px 36px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: {'#55FF33' if is_retro_theme() else '#9585FA'};
            }}
            QPushButton:disabled {{
                background-color: {c_border};
                color: {c_subtext};
            }}
        """)
        self._btn_start_flow.clicked.connect(self._on_start_flow_clicked)
        bottom_bar.addWidget(self._btn_start_flow)

        root_layout.addLayout(bottom_bar)

    def _part_button_style(self, is_active):
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_card = palette.get("C_CARD", "#1A2232")
        c_border = palette.get("C_BORDER", "#4E6182")
        c_btn_text = "#000000" if is_retro_theme() else "#FFFFFF"
        if is_active:
            return f"""
                QPushButton {{
                    background-color: {c_neon};
                    color: {c_btn_text};
                    border: 1px solid {c_neon};
                    border-radius: 6px;
                    padding: 8px 14px;
                    font-weight: bold;
                }}
            """
        return f"""
            QPushButton {{
                background-color: {c_card};
                color: #FFFFFF;
                border: 1px solid {c_border};
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {c_neon};
            }}
        """

    def _flow_button_style(self, is_active):
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_card = palette.get("C_CARD", "#1A2232")
        c_border = palette.get("C_BORDER", "#4E6182")
        c_text = palette.get("C_TEXT", "#FFFFFF")
        c_btn_text = "#000000" if is_retro_theme() else "#FFFFFF"
        if is_active:
            return f"""
                QPushButton {{
                    background-color: {c_neon};
                    color: {c_btn_text};
                    border: 2px solid {c_neon};
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                }}
            """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {c_text};
                border: 1.5px solid {c_border};
                border-radius: 8px;
                padding: 6px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {c_neon};
                color: {c_neon};
                background-color: rgba(57, 255, 20, 0.08);
            }}
            QPushButton:disabled {{
                color: #55657E;
                border-color: #2D3748;
            }}
        """

    def _interleave_button_style(self, is_on):
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_border = palette.get("C_BORDER", "#4E6182")
        c_subtext = palette.get("C_SUBTEXT", "#A0AEC0")
        if is_on:
            return f"""
                QPushButton {{
                    background-color: rgba(57, 255, 20, 0.16);
                    color: {c_neon};
                    border: 2px solid {c_neon};
                    border-radius: 8px;
                    padding: 6px 18px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: rgba(57, 255, 20, 0.28);
                }}
                QPushButton:disabled {{
                    color: #55657E;
                    border-color: #2D3748;
                    background-color: transparent;
                }}
            """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {c_subtext};
                border: 1.5px solid {c_border};
                border-radius: 8px;
                padding: 6px 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {c_neon};
                color: #FFFFFF;
            }}
            QPushButton:disabled {{
                color: #55657E;
                border-color: #2D3748;
            }}
        """

    def _update_flow_buttons_ui(self):
        has_tiles = bool(self.plan and self.plan.tiles)
        for mode_key, btn in getattr(self, "_card_mode_buttons", []):
            btn.setEnabled(has_tiles)
            is_active = (mode_key == getattr(self, "_active_card_mode", "mixed"))
            btn.setStyleSheet(self._flow_button_style(is_active))

        if hasattr(self, "_btn_interleave_toggle"):
            self._btn_interleave_toggle.setEnabled(has_tiles)
            is_on = getattr(self, "_interleave_active", True)
            self._btn_interleave_toggle.setText("🎲 Interleave: ON" if is_on else "📚 Interleave: OFF")
            self._btn_interleave_toggle.setStyleSheet(self._interleave_button_style(is_on))

    def _on_card_mode_clicked(self, mode):
        if not self.plan or not self.plan.tiles:
            return
        self._active_card_mode = mode
        self.plan = StudyFlowService.reformat_plan_flow(
            self.plan,
            mode=self._active_card_mode,
            interleave=self._interleave_active
        )
        self._update_flow_buttons_ui()
        self._refresh_playlist_ui()

    def _on_interleave_toggled(self):
        if not self.plan or not self.plan.tiles:
            return
        self._interleave_active = not self._interleave_active
        self.plan = StudyFlowService.reformat_plan_flow(
            self.plan,
            mode=self._active_card_mode,
            interleave=self._interleave_active
        )
        self._update_flow_buttons_ui()
        self._refresh_playlist_ui()

    def _on_flow_mode_clicked(self, mode):
        """Backward compatibility for unit tests."""
        if mode == "interleave":
            self._interleave_active = True
            self.plan = StudyFlowService.reformat_plan_flow(
                self.plan,
                mode=self._active_card_mode,
                interleave=True
            )
        else:
            self._active_card_mode = mode
            self.plan = StudyFlowService.reformat_plan_flow(
                self.plan,
                mode=self._active_card_mode,
                interleave=self._interleave_active
            )
        self._update_flow_buttons_ui()
        self._refresh_playlist_ui()

    @property
    def _btn_flow_interleave(self):
        return self._btn_interleave_toggle

    def _set_parts(self, num):
        self.selected_parts = max(1, int(num))
        self._spin_parts.blockSignals(True)
        self._spin_parts.setValue(self.selected_parts)
        self._spin_parts.blockSignals(False)
        for n, btn in self._part_buttons:
            btn.setChecked(n == self.selected_parts)
            btn.setStyleSheet(self._part_button_style(n == self.selected_parts))
        self._update_chunk_preview()

    def _on_parts_spin_changed(self, value):
        self.selected_parts = max(1, int(value))
        for n, btn in self._part_buttons:
            btn.setChecked(n == self.selected_parts)
            btn.setStyleSheet(self._part_button_style(n == self.selected_parts))
        self._update_chunk_preview()

    @property
    def _spin_target(self):
        """Backwards compatibility for unit tests."""
        return self._spin_single_target

    def _on_single_max_clicked(self):
        d = self._get_selected_deck_data()
        if not d:
            return
        mode = self._combo_mode.currentData() or "due"
        max_c = d.get("due_count", 0) if mode == "due" else d.get("new_count", 0)
        self._spin_single_target.setValue(max_c)

    def _on_dual_due_max_clicked(self):
        d = self._get_selected_deck_data()
        if not d:
            return
        self._spin_dual_due.setValue(d.get("due_count", 0))

    def _on_dual_new_max_clicked(self):
        d = self._get_selected_deck_data()
        if not d:
            return
        self._spin_dual_new.setValue(d.get("new_count", 0))

    def _on_single_spin_changed(self, value):
        val = max(0, int(value))
        if self._slider_single_target.value() != val and val <= self._slider_single_target.maximum():
            self._slider_single_target.blockSignals(True)
            self._slider_single_target.setValue(val)
            self._slider_single_target.blockSignals(False)
        self._update_chunk_preview()

    def _on_single_slider_changed(self, value):
        val = max(0, int(value))
        if self._spin_single_target.value() != val:
            self._spin_single_target.blockSignals(True)
            self._spin_single_target.setValue(val)
            self._spin_single_target.blockSignals(False)
        self._update_chunk_preview()

    def _on_dual_due_spin_changed(self, value):
        val = max(0, int(value))
        if self._slider_dual_due.value() != val and val <= self._slider_dual_due.maximum():
            self._slider_dual_due.blockSignals(True)
            self._slider_dual_due.setValue(val)
            self._slider_dual_due.blockSignals(False)
        self._update_chunk_preview()

    def _on_dual_due_slider_changed(self, value):
        val = max(0, int(value))
        if self._spin_dual_due.value() != val:
            self._spin_dual_due.blockSignals(True)
            self._spin_dual_due.setValue(val)
            self._spin_dual_due.blockSignals(False)
        self._update_chunk_preview()

    def _on_dual_new_spin_changed(self, value):
        val = max(0, int(value))
        if self._slider_dual_new.value() != val and val <= self._slider_dual_new.maximum():
            self._slider_dual_new.blockSignals(True)
            self._slider_dual_new.setValue(val)
            self._slider_dual_new.blockSignals(False)
        self._update_chunk_preview()

    def _on_dual_new_slider_changed(self, value):
        val = max(0, int(value))
        if self._spin_dual_new.value() != val:
            self._spin_dual_new.blockSignals(True)
            self._spin_dual_new.setValue(val)
            self._spin_dual_new.blockSignals(False)
        self._update_chunk_preview()

    def _populate_root_decks(self):
        """Populate only root parent decks in the primary dropdown with mode-aware counts."""
        mode = self._combo_mode.currentData() if hasattr(self, "_combo_mode") and self._combo_mode.currentData() else "due"
        selected_id = None
        if self._combo_root_decks.currentIndex() >= 0:
            cur = self._combo_root_decks.currentData()
            if cur and isinstance(cur, dict):
                selected_id = cur.get("id")

        roots = get_root_decks_from_store()
        self._combo_root_decks.blockSignals(True)
        self._combo_root_decks.clear()
        target_idx = 0
        for idx, r in enumerate(roots):
            theme = self._get_theme_for_deck(r['name'], r['name'])
            icon = theme.get("icon", "📌")
            if mode == "due":
                display = f"{icon}  {r['name']} (Due: {r['due_count']})"
            elif mode == "new":
                display = f"{icon}  {r['name']} (New: {r['new_count']})"
            else:  # "all"
                display = f"{icon}  {r['name']} (Due: {r['due_count']}, New: {r['new_count']})"
            self._combo_root_decks.addItem(display, r)
            if selected_id is not None and r.get("id") == selected_id:
                target_idx = idx

        if roots:
            self._combo_root_decks.setCurrentIndex(target_idx)
        self._combo_root_decks.blockSignals(False)

        if roots:
            self._populate_subdecks_for_current_root()

    def _populate_subdecks_for_current_root(self):
        """Populate subdecks/chapters for currently selected root deck with mode-aware counts."""
        mode = self._combo_mode.currentData() if hasattr(self, "_combo_mode") and self._combo_mode.currentData() else "due"
        selected_sub_id = None
        if self._combo_subdecks.currentIndex() >= 0:
            cur_s = self._combo_subdecks.currentData()
            if cur_s and isinstance(cur_s, dict):
                selected_sub_id = cur_s.get("id")

        root_data = self._combo_root_decks.currentData()
        self._combo_subdecks.blockSignals(True)
        self._combo_subdecks.clear()

        if not root_data or not isinstance(root_data, dict):
            self._combo_subdecks.addItem("🌟 Entire Subject (All Chapters)")
            self._combo_subdecks.setEnabled(False)
            self._combo_subdecks.blockSignals(False)
            return

        due_u = root_data.get("due_count", 0)
        new_u = root_data.get("new_count", 0)
        root_theme = self._get_theme_for_deck(root_data["name"], root_data["name"])
        icon = root_theme.get("icon", "🌟")
        if mode == "due":
            item0_text = f"{icon}  All Chapters Combined (Due: {due_u})"
        elif mode == "new":
            item0_text = f"{icon}  All Chapters Combined (New: {new_u})"
        else:
            item0_text = f"{icon}  All Chapters Combined (Due: {due_u}, New: {new_u})"

        item0_data = {
            "id": root_data["id"],
            "name": root_data["name"],
            "path": root_data["name"],
            "card_count": root_data["card_count"],
            "due_count": due_u,
            "new_count": new_u,
            "is_all": True,
        }
        self._combo_subdecks.addItem(item0_text, item0_data)

        subdecks = get_subdecks_for_deck(root_data)
        target_sub_idx = 0
        if subdecks:
            self._combo_subdecks.setEnabled(True)
            for idx, s in enumerate(subdecks):
                indent = "    " * (s["level"] - 1)
                if mode == "due":
                    badge = f"Due: {s['due_count']}"
                elif mode == "new":
                    badge = f"New: {s['new_count']}"
                else:
                    badge = f"Due: {s['due_count']}, New: {s['new_count']}"
                item_text = f"{indent}└─ {s['name']} ({badge})"
                item_data = {
                    "id": s["id"],
                    "name": s["name"],
                    "path": f"{root_data['name']} / {s['path']}",
                    "card_count": s["card_count"],
                    "due_count": s["due_count"],
                    "new_count": s["new_count"],
                    "is_all": False,
                }
                self._combo_subdecks.addItem(item_text, item_data)
                if selected_sub_id is not None and s.get("id") == selected_sub_id:
                    target_sub_idx = idx + 1
        else:
            if mode == "due":
                status_txt = f"Due: {due_u}"
            elif mode == "new":
                status_txt = f"New: {new_u}"
            else:
                status_txt = f"Due: {due_u}, New: {new_u}"
            self._combo_subdecks.setItemText(0, f"🌟 Entire Subject (No Sub-chapters — {status_txt})")
            self._combo_subdecks.setEnabled(False)

        self._combo_subdecks.setCurrentIndex(target_sub_idx)
        self._combo_subdecks.blockSignals(False)
        self._sync_target_for_selection()

    def _on_root_deck_changed(self):
        self._populate_subdecks_for_current_root()

    def _on_subdeck_changed(self):
        self._sync_target_for_selection()

    def _on_mode_changed(self):
        mode = self._combo_mode.currentData() or "due"
        if mode == "all":
            self._single_target_frame.hide()
            self._dual_target_frame.show()
        else:
            self._dual_target_frame.hide()
            self._single_target_frame.show()
            if mode == "due":
                self._lbl_single_title.setText("Target Due Cards:")
                self._btn_single_max.setText("All Due")
            else:
                self._lbl_single_title.setText("Target New Cards:")
                self._btn_single_max.setText("All New")

        self._populate_root_decks()
        self._sync_target_for_selection()

    def _sync_target_for_selection(self):
        d = self._get_selected_deck_data()
        if not d:
            return
        due = d.get("due_count", 0)
        new_c = d.get("new_count", 0)
        mode = self._combo_mode.currentData() or "due"

        # Update single target controls
        if mode == "due":
            self._lbl_single_avail.setText(f"(Avail: {due})")
            self._spin_single_target.setRange(0, max(2000, due))
            self._slider_single_target.setRange(0, max(1, due))
            self._spin_single_target.setValue(min(50, due) if due > 0 else 0)
        elif mode == "new":
            self._lbl_single_avail.setText(f"(Avail: {new_c})")
            self._spin_single_target.setRange(0, max(2000, new_c))
            self._slider_single_target.setRange(0, max(1, new_c))
            self._spin_single_target.setValue(min(50, new_c) if new_c > 0 else 0)

        # Update dual target controls
        self._lbl_dual_due_avail.setText(f"(Avail: {due})")
        self._lbl_dual_new_avail.setText(f"(Avail: {new_c})")
        self._spin_dual_due.setRange(0, max(2000, due))
        self._slider_dual_due.setRange(0, max(1, due))
        self._spin_dual_new.setRange(0, max(2000, new_c))
        self._slider_dual_new.setRange(0, max(1, new_c))
        self._spin_dual_due.setValue(min(50, due) if due > 0 else 0)
        self._spin_dual_new.setValue(min(50, new_c) if new_c > 0 else 0)

        self._update_chunk_preview()

    def _get_selected_deck_data(self):
        """Retrieve metadata for currently chosen subdeck (or root deck if all chapters)."""
        if self._combo_subdecks.isEnabled() and self._combo_subdecks.currentIndex() > 0:
            data = self._combo_subdecks.currentData()
            if data and isinstance(data, dict):
                return data

        if self._combo_subdecks.count() > 0:
            data0 = self._combo_subdecks.itemData(0)
            if data0 and isinstance(data0, dict):
                return data0

        root_data = self._combo_root_decks.currentData()
        if root_data and isinstance(root_data, dict):
            return {
                "id": root_data["id"],
                "name": root_data["name"],
                "path": root_data["name"],
                "card_count": root_data["card_count"],
                "due_count": root_data["due_count"],
                "new_count": root_data["new_count"],
                "is_all": True,
            }
        return None

    def _update_chunk_preview(self):
        mode = self._combo_mode.currentData() or "due"
        parts = max(1, self.selected_parts)

        if mode == "all":
            due_t = self._spin_dual_due.value()
            new_t = self._spin_dual_new.value()
            total_t = due_t + new_t
            self._lbl_dual_total.setText(f"🎯 Total Target: {total_t} Cards ({due_t} Due + {new_t} New)")
            if total_t == 0:
                self._lbl_chunk_preview.setText("ℹ️ कोई कार्ड नहीं चुना गया (0 Cards)")
                return

            base_d = due_t // parts
            base_n = new_t // parts
            self._lbl_chunk_preview.setText(
                f"ℹ️ {parts} session(s): ~{base_d} Due + ~{base_n} New per session (Total: {total_t} Cards)"
            )
        else:
            target = self._spin_single_target.value()
            if target == 0:
                self._lbl_chunk_preview.setText("ℹ️ कोई कार्ड नहीं चुना गया (0 Cards)")
                return
            num_parts = min(target, parts)
            base = target // num_parts
            rem = target % num_parts
            type_str = "Due" if mode == "due" else "New"

            if num_parts == 1:
                self._lbl_chunk_preview.setText(f"ℹ️ 1 session of {target} {type_str} cards")
            elif rem == 0:
                self._lbl_chunk_preview.setText(
                    f"ℹ️ {num_parts} equal sessions of {base} {type_str} cards each (Total: {target})"
                )
            else:
                self._lbl_chunk_preview.setText(
                    f"ℹ️ {num_parts} sessions: {num_parts - 1}x{base} + 1x{base + rem} {type_str} cards (Total: {target})"
                )

    def _on_add_tiles_clicked(self):
        deck_info = self._get_selected_deck_data()
        if not deck_info:
            QMessageBox.warning(self, "No Deck", "कृपया एक मुख्य विषय / डेक चुनें!")
            return

        parts = max(1, self.selected_parts)
        mode = self._combo_mode.currentData() or "due"

        if mode == "all":
            due_val = self._spin_dual_due.value()
            new_val = self._spin_dual_new.value()
            tot = due_val + new_val
            if tot <= 0:
                QMessageBox.warning(self, "Zero Cards", "कृपया कम से कम 1 कार्ड का लक्ष्य रखें!")
                return
            new_tiles = StudyFlowService.generate_tiles(
                deck_id=deck_info["id"],
                deck_name=deck_info["name"],
                deck_path=deck_info.get("path", deck_info["name"]),
                total_target=tot,
                parts=parts,
                mode="all",
                target_due=due_val,
                target_new=new_val,
                mix_style="mixed",
            )
        else:
            val = self._spin_single_target.value()
            if val <= 0:
                QMessageBox.warning(self, "Zero Cards", "कृपया कम से कम 1 कार्ड का लक्ष्य रखें!")
                return
            t_due = val if mode == "due" else 0
            t_new = val if mode == "new" else 0
            new_tiles = StudyFlowService.generate_tiles(
                deck_id=deck_info["id"],
                deck_name=deck_info["name"],
                deck_path=deck_info.get("path", deck_info["name"]),
                total_target=val,
                parts=parts,
                mode=mode,
                target_due=t_due,
                target_new=t_new,
            )

        self.plan = StudyFlowService.add_tiles_to_today_plan(new_tiles)
        if self._interleave_active or self._active_card_mode != "mixed":
            self.plan = StudyFlowService.reformat_plan_flow(
                self.plan,
                mode=self._active_card_mode,
                interleave=self._interleave_active
            )
        self._refresh_playlist_ui()


    def _refresh_playlist_ui(self, scroll_to_tile_id=None):
        # Save current vertical scroll position before modifying widgets
        prev_scroll = self._scroll_playlist.verticalScrollBar().value()

        # Clear existing tile widgets in vbox
        while self._playlist_vbox.count():
            item = self._playlist_vbox.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        tiles = self.plan.tiles
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_text = palette.get("C_TEXT", "#FFFFFF")
        c_subtext = palette.get("C_SUBTEXT", "#A0AEC0")
        c_border = palette.get("C_BORDER", "#3E4E68")

        # Update stats
        total_cards = self.plan.total_target_cards
        est_mins = int(total_cards * 0.45)
        self._lbl_stat_cards.setText(f"{total_cards} Cards")
        self._lbl_stat_tiles.setText(f"{len(tiles)} Tiles")
        self._lbl_stat_time.setText(f"~{est_mins}m Est")

        self._btn_start_flow.setEnabled(len(tiles) > 0)
        if self.plan.current_tile_idx > 0 and self.plan.current_tile_idx < len(tiles):
            self._btn_start_flow.setText(f"▶️ RESUME FLOW (Tile {self.plan.current_tile_idx + 1}/{len(tiles)})")
        else:
            self._btn_start_flow.setText("🚀 START STUDY FLOW")

        self._update_flow_buttons_ui()

        if not tiles:
            if hasattr(self, "_subject_progress_frame"):
                self._subject_progress_frame.hide()
            lbl_empty = QLabel(
                "कोई टाइल अभी नहीं है!\nबाईं तरफ से विषय व कार्ड लक्ष्य चुनकर 'ADD TO PLAYLIST' दबाएं।"
            )
            lbl_empty.setFont(QFont("Segoe UI", 16, QFont.Normal))
            lbl_empty.setStyleSheet(f"color: {c_subtext}; padding: 30px;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self._playlist_vbox.addWidget(lbl_empty)
            self._playlist_vbox.addStretch()
            return

        card_map = {}
        for idx, tile in enumerate(tiles):
            theme = self._get_theme_for_deck(tile.deck_path, tile.deck_name)
            raw_path = tile.deck_path or tile.deck_name or "General"
            root_name = raw_path.split("/")[0].strip() or tile.deck_name

            card = QFrame()
            card.setObjectName("tileCard")
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card.setMinimumHeight(76)
            card.setStyleSheet(f"""
                QFrame#tileCard {{
                    background: {theme['bg_gradient']};
                    border: 1.5px solid {theme['border']};
                    border-left: 8px solid {theme['primary']};
                    border-radius: 10px;
                }}
            """)
            card_map[tile.id] = card
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(12)

            # Left number badge
            lbl_num = QLabel(f"#{idx + 1}")
            lbl_num.setFont(QFont("Segoe UI", 20, QFont.Black))
            lbl_num.setFixedWidth(52)
            if tile.status == "completed":
                lbl_num.setStyleSheet("color: #45A247;")
            elif idx == self.plan.current_tile_idx:
                lbl_num.setStyleSheet(f"color: {c_neon};")
            else:
                lbl_num.setStyleSheet(f"color: {theme['primary']};")
            card_layout.addWidget(lbl_num)

            # Info column
            info_layout = QVBoxLayout()
            info_layout.setSpacing(4)

            # Title row: Pill + Deck Name
            title_row = QHBoxLayout()
            title_row.setSpacing(8)

            lbl_pill = QLabel(f" {root_name.upper()} ")
            lbl_pill.setFont(QFont("Segoe UI", 12, QFont.Bold))
            lbl_pill.setStyleSheet(f"""
                QLabel {{
                    background-color: {theme['badge_bg']};
                    color: {theme['badge_text']};
                    border: 1px solid {theme['primary']};
                    border-radius: 4px;
                    padding: 2px 7px;
                    font-weight: 800;
                }}
            """)
            title_row.addWidget(lbl_pill)

            lbl_name = QLabel(f"{tile.deck_name} — {tile.target_cards} Cards")
            lbl_name.setFont(QFont("Segoe UI", 18, QFont.Bold))
            lbl_name.setStyleSheet(f"color: {theme['text']};")
            title_row.addWidget(lbl_name)
            title_row.addStretch()
            info_layout.addLayout(title_row)

            if tile.mode == "all" and tile.target_due > 0 and tile.target_new > 0:
                mode_str = f"🔀 Mixed ({tile.target_due} Due + {tile.target_new} New)"
            elif tile.mode == "due" or tile.target_due > 0:
                mode_str = f"📖 Due Reviews ({tile.target_cards} Cards)"
            elif tile.mode == "new" or tile.target_new > 0:
                mode_str = f"✨ New Cards ({tile.target_cards} Cards)"
            else:
                mode_str = f"🎯 Practice ({tile.target_cards} Cards)"

            sub_layout = QHBoxLayout()
            sub_layout.setSpacing(8)

            lbl_sub = QLabel(f"{theme['icon']} {tile.deck_path} •")
            lbl_sub.setFont(QFont("Segoe UI", 15, QFont.Normal))
            lbl_sub.setStyleSheet(f"color: {c_subtext};")
            sub_layout.addWidget(lbl_sub)

            # Interactive Mode Switcher Pill Button (allows on-the-fly mode changing for tiles)
            btn_mode_pill = QPushButton(f"{mode_str} ▾")
            btn_mode_pill.setFont(QFont("Segoe UI", 14, QFont.Bold))
            btn_mode_pill.setCursor(Qt.PointingHandCursor)
            btn_mode_pill.setFocusPolicy(Qt.NoFocus)
            btn_mode_pill.setToolTip("Click to change study mode for this tile or all tiles of this deck")
            btn_mode_pill.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.06);
                    color: {theme['text']};
                    border: 1px solid {theme['border']};
                    border-radius: 6px;
                    padding: 2px 10px;
                }}
                QPushButton:hover {{
                    background: {theme['badge_bg']};
                    border-color: {theme['primary']};
                    color: #FFFFFF;
                }}
            """)
            if tile.status != "completed":
                btn_mode_pill.clicked.connect(lambda _, b=btn_mode_pill, t=tile, r=root_name: self._show_tile_mode_menu(b, t, r))
            else:
                btn_mode_pill.setEnabled(False)
            sub_layout.addWidget(btn_mode_pill)
            sub_layout.addStretch()
            info_layout.addLayout(sub_layout)
            card_layout.addLayout(info_layout, 1)

            # Status Chip
            lbl_status = QLabel()
            lbl_status.setFont(QFont("Segoe UI", 15, QFont.Bold))
            if tile.status == "completed":
                lbl_status.setText(f"✅ DONE ({tile.completed_cards}/{tile.target_cards})")
                lbl_status.setStyleSheet("color: #45A247; border: 1px solid #45A247; border-radius: 6px; padding: 5px 10px; background-color: rgba(69, 162, 71, 0.12);")
            elif idx == self.plan.current_tile_idx:
                lbl_status.setText("▶️ CURRENT")
                lbl_status.setStyleSheet(f"color: {c_neon}; border: 1.5px solid {c_neon}; border-radius: 6px; padding: 5px 10px; background-color: rgba(57, 255, 20, 0.15);")
            else:
                lbl_status.setText("⏳ PENDING")
                lbl_status.setStyleSheet(f"color: {c_subtext}; border: 1px solid {c_border}; border-radius: 6px; padding: 5px 10px; background-color: rgba(255, 255, 255, 0.04);")
            card_layout.addWidget(lbl_status)

            # Controls: Move Up, Move Down, Delete (NoFocus to prevent scrollbar hijacking)
            ctrl_layout = QHBoxLayout()
            ctrl_layout.setSpacing(6)

            btn_up = QPushButton("▲")
            btn_up.setFont(QFont("Segoe UI", 16, QFont.Bold))
            btn_up.setFixedSize(38, 38)
            btn_up.setEnabled(idx > 0)
            btn_up.setCursor(Qt.PointingHandCursor)
            btn_up.setFocusPolicy(Qt.NoFocus)
            btn_up.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {c_text};
                    border: 1px solid {c_border};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: {theme['badge_bg']};
                    border-color: {theme['primary']};
                    color: #FFFFFF;
                }}
                QPushButton:disabled {{
                    background: transparent;
                    color: #3E4E68;
                    border-color: #242F42;
                }}
            """)
            btn_up.clicked.connect(lambda _, i=idx: self._move_tile(i, i - 1))
            ctrl_layout.addWidget(btn_up)

            btn_down = QPushButton("▼")
            btn_down.setFont(QFont("Segoe UI", 16, QFont.Bold))
            btn_down.setFixedSize(38, 38)
            btn_down.setEnabled(idx < len(tiles) - 1)
            btn_down.setCursor(Qt.PointingHandCursor)
            btn_down.setFocusPolicy(Qt.NoFocus)
            btn_down.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {c_text};
                    border: 1px solid {c_border};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: {theme['badge_bg']};
                    border-color: {theme['primary']};
                    color: #FFFFFF;
                }}
                QPushButton:disabled {{
                    background: transparent;
                    color: #3E4E68;
                    border-color: #242F42;
                }}
            """)
            btn_down.clicked.connect(lambda _, i=idx: self._move_tile(i, i + 1))
            ctrl_layout.addWidget(btn_down)

            btn_del = QPushButton("✕")
            btn_del.setFont(QFont("Segoe UI", 16, QFont.Bold))
            btn_del.setFixedSize(38, 38)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setFocusPolicy(Qt.NoFocus)
            btn_del.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: #FF5A66;
                    border: 1px solid {c_border};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: rgba(255, 90, 102, 0.2);
                    border-color: #FF5A66;
                    color: #FFFFFF;
                }}
            """)
            btn_del.clicked.connect(lambda _, t_id=tile.id: self._delete_tile(t_id))
            ctrl_layout.addWidget(btn_del)

            card_layout.addLayout(ctrl_layout)
            self._playlist_vbox.addWidget(card)

        self._playlist_vbox.addStretch()

        # Update Option A: Subject Progress Dashboard Strip
        self._update_subject_progress_ui(tiles, card_map)

        # Anchor viewport to moved tile or preserve scroll position
        def _restore_scroll():
            if scroll_to_tile_id and scroll_to_tile_id in card_map:
                self._scroll_playlist.ensureWidgetVisible(card_map[scroll_to_tile_id], 0, 40)
            else:
                self._scroll_playlist.verticalScrollBar().setValue(prev_scroll)

        _restore_scroll()
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, _restore_scroll)

    def _update_subject_progress_ui(self, tiles, card_map):
        """Option A: Render dynamic Subject Progress chips showing done/target cards and sessions."""
        if not hasattr(self, "_subject_progress_frame") or not hasattr(self, "_subject_progress_layout"):
            return

        # Clear existing chips in layout
        while self._subject_progress_layout.count():
            item = self._subject_progress_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        if not tiles:
            self._subject_progress_frame.hide()
            return

        self._subject_progress_frame.show()

        MAX_COLS = 2
        lbl_title = QLabel("📊 Subject Progress:")
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl_title.setStyleSheet("color: #A0AEC0;")
        self._subject_progress_layout.addWidget(lbl_title, 0, 0, 1, MAX_COLS)

        # Aggregate totals & progress per root parent subject
        subject_order = []
        subject_stats = {}
        for t in tiles:
            raw_path = t.deck_path or t.deck_name or "General"
            root_name = raw_path.split("/")[0].strip() or t.deck_name
            if root_name not in subject_order:
                subject_order.append(root_name)
                subject_stats[root_name] = {
                    "total_cards": 0,
                    "completed_cards": 0,
                    "total_sessions": 0,
                    "completed_sessions": 0,
                    "first_tile_id": t.id,
                }
            s = subject_stats[root_name]
            s["total_cards"] += t.target_cards
            s["completed_cards"] += t.completed_cards
            s["total_sessions"] += 1
            if t.status == "completed":
                s["completed_sessions"] += 1

        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_border = palette.get("C_BORDER", "#4E6182")

        for idx, root_name in enumerate(subject_order):
            s = subject_stats[root_name]
            tot_c = s["total_cards"]
            done_c = s["completed_cards"]
            tot_sess = s["total_sessions"]
            done_sess = s["completed_sessions"]
            pct = int((done_c / tot_c) * 100) if tot_c > 0 else 0
            theme = self._get_theme_for_deck(root_name, root_name)

            if done_c >= tot_c and tot_c > 0:
                icon_prefix = "✅"
            else:
                icon_prefix = "●"

            chip_text = f"{icon_prefix} {root_name}: {done_c}/{tot_c} ({pct}%) • {done_sess}/{tot_sess} Done"
            chip = QPushButton(chip_text)
            chip.setFont(QFont("Segoe UI", 14, QFont.Bold))
            chip.setCursor(Qt.PointingHandCursor)
            chip.setFocusPolicy(Qt.NoFocus)
            chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            chip.setToolTip(f"Click to jump to {root_name} in today's playlist")
            chip.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                    border: 1px solid {c_border};
                    border-left: 5px solid {theme['primary']};
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: bold;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {theme['badge_bg']};
                    border-color: {theme['primary']};
                }}
            """)
            first_id = s["first_tile_id"]
            chip.clicked.connect(lambda _, t_id=first_id: self._scroll_to_tile(t_id, card_map))

            row = 1 + (idx // MAX_COLS)
            col = idx % MAX_COLS
            self._subject_progress_layout.addWidget(chip, row, col)

    def _scroll_to_tile(self, tile_id, card_map):
        if tile_id in card_map:
            self._scroll_playlist.ensureWidgetVisible(card_map[tile_id], 0, 40)

    def _show_tile_mode_menu(self, btn, tile: FlowTile, root_name: str):
        menu = QMenu(self)
        menu.setFont(QFont("Segoe UI", 16, QFont.DemiBold))
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_card = palette.get("C_CARD", "#1A2232")
        c_border = palette.get("C_BORDER", "#4E6182")

        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {c_card};
                color: #FFFFFF;
                border: 1.5px solid {c_border};
                border-radius: 8px;
                padding: 6px;
                font-size: 16px;
            }}
            QMenu::item {{
                padding: 10px 24px;
                border-radius: 6px;
                font-weight: 600;
            }}
            QMenu::item:selected {{
                background-color: rgba(57, 255, 20, 0.18);
                color: {c_neon};
            }}
            QMenu::separator {{
                height: 1px;
                background: {c_border};
                margin: 6px 12px;
            }}
        """)

        act_due = menu.addAction(f"📖 Set This Tile as Due Reviews ({tile.target_cards} Cards)")
        act_new = menu.addAction(f"✨ Set This Tile as New Cards ({tile.target_cards} Cards)")
        act_all = menu.addAction(f"🎯 Set This Tile as Practice All Cards ({tile.target_cards} Cards)")
        menu.addSeparator()
        act_root_due = menu.addAction(f"🔄 Change ALL '{root_name}' Tiles to Due Reviews")
        act_root_new = menu.addAction(f"🔄 Change ALL '{root_name}' Tiles to New Cards")
        act_root_all = menu.addAction(f"🔄 Change ALL '{root_name}' Tiles to Practice All Cards")

        action = menu.exec_(btn.mapToGlobal(QPoint(0, btn.height() + 4)))
        if not action:
            return

        def _apply_mode_to_tile(t: FlowTile, new_m: str):
            t.mode = new_m
            if new_m == "due":
                t.target_due = t.target_cards
                t.target_new = 0
            elif new_m == "new":
                t.target_due = 0
                t.target_new = t.target_cards
            else:  # "all"
                t.target_due = 0
                t.target_new = 0

        target_mode = None
        apply_all_root = False
        if action == act_due:
            target_mode = "due"
        elif action == act_new:
            target_mode = "new"
        elif action == act_all:
            target_mode = "all"
        elif action == act_root_due:
            target_mode = "due"
            apply_all_root = True
        elif action == act_root_new:
            target_mode = "new"
            apply_all_root = True
        elif action == act_root_all:
            target_mode = "all"
            apply_all_root = True

        if target_mode:
            if apply_all_root:
                for t in self.plan.tiles:
                    r = (t.deck_path or t.deck_name or "General").split("/")[0].strip()
                    if r == root_name and t.status != "completed":
                        _apply_mode_to_tile(t, target_mode)
            else:
                _apply_mode_to_tile(tile, target_mode)

            StudyFlowService.save_today_plan(self.plan)
            self.plan = StudyFlowService.reformat_plan_flow(
                self.plan,
                mode=self._active_card_mode,
                interleave=self._interleave_active,
            )
            self._refresh_playlist_ui()

    def _move_tile(self, from_idx, to_idx):
        moved_id = None
        if 0 <= from_idx < len(self.plan.tiles):
            moved_id = self.plan.tiles[from_idx].id
        self.plan = StudyFlowService.reorder_tiles(from_idx, to_idx)
        self._refresh_playlist_ui(scroll_to_tile_id=moved_id)

    def _delete_tile(self, tile_id):
        self.plan = StudyFlowService.remove_tile(tile_id)
        self._refresh_playlist_ui()

    def _on_clear_plan_clicked(self):
        reply = QMessageBox.question(
            self,
            "Clear Playlist",
            "क्या आप आज की पूरी प्लेलिस्ट खाली करना चाहते हैं?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.plan = StudyFlowService.clear_today_plan()
            self._refresh_playlist_ui()

    def _on_save_routine_clicked(self):
        if not self.plan.tiles:
            QMessageBox.information(self, "Empty Plan", "सेव करने के लिए पहले प्लेलिस्ट में टाइल्स जोड़ें!")
            return
        name, ok = QInputDialog.getText(
            self,
            "Save Routine Preset",
            "रूटीन का नाम दर्ज करें (जैसे 'Daily Morning Drill'):",
            text="My Study Routine"
        )
        if ok and name.strip():
            StudyFlowService.save_routine_preset(name.strip(), self.plan.tiles)
            QMessageBox.information(self, "Saved", f"रूटीन '{name.strip()}' सफलतापूर्वक सेव हो गया! 🌟")

    def _on_load_routine_clicked(self):
        routines = StudyFlowService.load_routine_presets()
        if not routines:
            QMessageBox.information(self, "No Routines", "कोई सेव किया हुआ रूटीन उपलब्ध नहीं है!")
            return

        names = list(routines.keys())
        name, ok = QInputDialog.getItem(
            self,
            "Load Routine Preset",
            "उपलब्ध रूटीन चुनें:",
            names,
            0,
            False
        )
        if ok and name:
            new_plan = StudyFlowService.apply_routine_preset(name)
            if new_plan:
                self.plan = new_plan
                self._refresh_playlist_ui()
                QMessageBox.information(self, "Loaded", f"रूटीन '{name}' प्लेलिस्ट में लोड हो गया! 🚀")

    def _on_start_flow_clicked(self):
        if not self.plan.tiles:
            return
        self.flow_started.emit(self.plan)
        self.accept()
