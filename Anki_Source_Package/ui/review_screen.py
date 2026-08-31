"""
Anki Occlusion — PDF & Image Flashcard App  v19 (Smart Review Items Rebuild)
================================================
v19 New Feature:
  [SMART REVIEW REBUILD] ReviewScreen ab sirf tabhi _items list rebuild karta hai
      jab editor mein koi box ka group_id actually change hua ho.
      Bina kisi change ke review se editor aur wapas = zero overhead.
      Sirf affected card ke items replace hote hain — baaki cards untouched.
      Detection: before/after snapshot of {box_id -> group_id} map.

v18 (Hardware Mask Cache + LRU Page Cache Edition)
================================================
v18 New Features:
  [HARDWARE MASK CACHE] OcclusionCanvas ab masks ko ek GPU-backed QPixmap
      offscreen layer mein cache karta hai. Jab tak koi mask change nahi hota,
      paintEvent mein sirf ek drawPixmap() call hota hai — loop nahi.
      100+ masks = 1 mask jaisi speed. FPS ~3x better on dense cards.
      Cache sirf tab rebuild hota hai jab _mask_cache_dirty = True ho:
        - mouseReleaseEvent (drag/draw finish)
        - delete, undo, redo, label change, group/ungroup
      Mouse drag ke dauran cache rebuild NAHI hoti — isliye dragging bhi smooth.

  [LRU PAGE CACHE] GLOBAL_PDF_CACHE replace ho gaya ek smart LRUPageCache se.
      Pura combined QPixmap store karne ki jagah ab individual pages store hoti hain.
      Max 15 pages RAM mein — baaki on-demand fitz se reload.
      Ek 100-page PDF pehle ~2GB RAM leta tha, ab sirf ~300MB.
      OrderedDict se O(1) get/put/evict — zero performance penalty.

v17 New Feature:
  [PROGRESSIVE LOADING] PDF ab 10-10 pages ke chunks mein load hota hai.
      Pehla chunk (10 pages) aate hi canvas pe dikhta hai — user turant
      kaam shuru kar sakta hai. Baaki pages background mein silently load
      hote rehte hain. Progress bar-style label dikhata hai kitne pages load hue.
  [ULTRA FAST CACHE] PDF ek baar load hone ke baad RAM mein save ho jati hai.
      Edit aur Review mode ke beech switch karne par zero delay (0.001s).
v16 Bug Fixes:
  [NOT-RESPONDING FIX] PDF ab background QThread mein load hota hai.
      CardEditorDialog._load_card() aur _load_pdf() dono ab non-blocking hain.
      _reload_pdf() (Live Sync) bhi thread-based ho gaya.
      closeEvent/reject mein thread safely stop hota hai.
v15 Bug Fixes:
  [FIX-1]  ReviewScreen.__init__ — duplicate item prevention
  [FIX-2]  _rate() — "reviews" double-increment fixed
  [FIX-3]  _start_review() — win.closeEvent double-save fixed
  [FIX-4]  is_due_today() called on un-initialised boxes in ReviewScreen
  [FIX-5]  Group dedup across cards
  [LAG-FIX] Native Hardware Painting & Caching applied to OcclusionCanvas
            to eliminate mouseMoveEvent lag completely.
"""

from sm2_engine import (
    sched_init,
    sm2_init,
    sched_update,
    sm2_update,
    is_due_now,
    is_due_today,
    sm2_is_due,
    sm2_days_left,
    _fmt_due_interval,
    sm2_simulate,
    sm2_badge,
)

# Daily Journal — safe import
try:
    from ui.journal import JournalDialog

    _JOURNAL_AVAILABLE = True
except ImportError:
    _JOURNAL_AVAILABLE = False

# Session Timer — safe import
try:
    from session_timer import SessionTimer

    _TIMER_AVAILABLE = True
except ImportError:
    _TIMER_AVAILABLE = False

from pdf_engine import (
    PDF_SUPPORT,
    PAGE_CACHE,
    PdfLoaderThread,
    PdfSkeletonThread,
    pdf_page_to_pixmap,
    load_pdf_skeleton,
    PdfOnDemandThread,
    build_skeleton_placeholders,
    invalidate_pdf_skeleton,  # STEP 2 + 3
    choose_pdf_render_zoom,
    ensure_pdf_cache_profile,
    adapt_pdf_boxes_to_render_zoom,
    PDF_LEGACY_BOX_ZOOM,
    get_cached_pdf_page_set,
)

from editor_ui import OcclusionCanvas, _ZoomableScrollArea
from ui.editor_dialog import CardEditorDialog
from ui.text_card_editor_dialog import TextCardEditorDialog
from ui.text_review_widget import TextReviewWidget
from ui.mcq_review_widget import MCQReviewWidget
from ui.pdf_annotation_dialog import PdfAnnotationDialog
from ui.canvas.retro_effects import CRTOverlay, ParticleBurstOverlay
from PyQt5.QtMultimedia import QSoundEffect
from PyQt5.QtCore import QUrl
from ui.pdf_viewer_controller import PdfViewerController
from services import shortcut_manager

import fitz

from data_manager import (
    load_data,
    save_data,
    find_deck_by_id,
    next_deck_id,
    new_box_id,
    deck_history,
    DATA_FILE,
    store,
)
from perf_utils import get_pdf_page_count, perf_log
from storage_paths import resolve_asset_path

import sys, os, copy, uuid, math, time, re
from datetime import datetime, date, timedelta


from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QStackedWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QScrollArea,
    QInputDialog,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QProgressBar,
    QDialog,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QMenu,
    QStyledItemDelegate,
    QStyle,
    QHeaderView,
    QShortcut,
    QColorDialog,
    QTextBrowser,
    QSlider,
)
from PyQt5.QtCore import (
    Qt,
    QRect,
    QPoint,
    QSize,
    QRectF,
    QPointF,
    pyqtSignal,
    QTimer,
    QModelIndex,
    QFileSystemWatcher,
    QThread,
    QEvent,
    QMimeData,
    QByteArray,
    QUrl,
    QSettings,
)
from PyQt5.QtGui import QGuiApplication as _QGA
from PyQt5.QtGui import (
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QFont,
    QCursor,
    QIcon,
    QBrush,
    QTransform,
    QPainterPath,
    QDrag,
    QDesktopServices,
    QKeySequence,
    QTextDocument,
    QImage,
)

_RE_IMG_SRC = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
_RE_IMG = re.compile(r'<img\s+[^>]+>', re.IGNORECASE)
_RE_FONT_SIZE = re.compile(r'font-size\s*:\s*[^;\'"]+;?', re.IGNORECASE)


class ResizeHandle(QWidget):
    def __init__(self, parent_panel, on_resize):
        super().__init__(parent_panel)
        self.parent_panel = parent_panel
        self.on_resize = on_resize
        self.setCursor(Qt.SizeHorCursor)
        self.setFixedWidth(6)
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_width = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_start_x = event.globalX()
            self.drag_start_width = self.parent_panel.width()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            delta_x = event.globalX() - self.drag_start_x
            new_width = self.drag_start_width - delta_x
            new_width = max(200, min(1600, new_width))
            self.on_resize(new_width)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            event.accept()





MATH_UNICODE_MAP = {
    r"\times": "×",
    r"\cdot": "·",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\infty": "∞",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\le": "≤",
    r"\ge": "≥",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\pi": "π",
    r"\sigma": "σ",
    r"\omega": "ω",
    r"\Delta": "Δ",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\int": "∫",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\deg": "°",
    r"\dots": "...",
    r"\cdots": "...",
}


def parse_markdown_tables(text):
    if not text:
        return ""
    lines = text.split("\n")
    in_table = False
    table_lines = []
    output = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if not in_table:
                in_table = True
                table_lines = [line]
            else:
                table_lines.append(line)
        else:
            if in_table:
                html_table = render_html_table(table_lines)
                output.append(html_table)
                in_table = False
                table_lines = []
            output.append(line)
            
    if in_table:
        html_table = render_html_table(table_lines)
        output.append(html_table)
        
    final_output = []
    for line in output:
        stripped_line = line.strip()
        if (stripped_line.startswith("<table") or 
            stripped_line.startswith("</table") or 
            stripped_line.startswith("<tr") or 
            stripped_line.startswith("</tr") or 
            stripped_line.startswith("<td") or 
            stripped_line.startswith("</td") or 
            stripped_line.startswith("<th") or 
            stripped_line.startswith("</th")):
            final_output.append(line)
        else:
            final_output.append(line + "<br>")
            
    return "".join(final_output)


def render_html_table(table_lines):
    if len(table_lines) < 2:
        return "\n".join(table_lines)
        
    sep_line = table_lines[1].strip()
    sep_content = sep_line.strip("|").replace(" ", "").replace("-", "").replace(":", "").replace("|", "")
    if sep_content != "":
        return "\n".join(table_lines)
        
    headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
    
    alignments = []
    for col in table_lines[1].strip("|").split("|"):
        col = col.strip()
        if col.startswith(":") and col.endswith(":"):
            alignments.append("center")
        elif col.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")
            
    html = ['<table width="100%">']
    
    # Header row
    html.append("  <tr>")
    for i, h in enumerate(headers):
        align = alignments[i] if i < len(alignments) else "left"
        html.append(f"    <th align='{align}'>{h}</th>")
    html.append("  </tr>")
    
    # Data rows
    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.strip("|").split("|")]
        while len(cells) < len(headers):
            cells.append("")
        html.append("  <tr>")
        for i, cell in enumerate(cells[:len(headers)]):
            align = alignments[i] if i < len(alignments) else "left"
            html.append(f"    <td align='{align}'>{cell}</td>")
        html.append("  </tr>")
        
    html.append("</table>")
    return "\n".join(html)


def parse_latex_math(text, text_color):
    import re
    
    def replace_display_math(match):
        formula = match.group(1).strip()
        translated = translate_formula(formula, text_color, is_display=True)
        return f'<div align="center" style="margin: 12px 0;">{translated}</div>'
        
    text = re.sub(r'\$\$(.*?)\$\$', replace_display_math, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.*?)\\\]', replace_display_math, text, flags=re.DOTALL)
    
    def replace_inline_math(match):
        formula = match.group(1).strip()
        return translate_formula(formula, text_color, is_display=False)
        
    text = re.sub(r'\$([^\$\n]+?)\$', replace_inline_math, text)
    text = re.sub(r'\\\((.*?)\\\)', replace_inline_math, text)
    
    return text


def translate_formula(formula, text_color, is_display=False):
    import html
    import urllib.parse
    import re
    
    formula_clean = formula.strip()
    
    # 1. Try simple translation
    translated = formula_clean
    for k, v in MATH_UNICODE_MAP.items():
        translated = translated.replace(k, v)
        
    translated = re.sub(r'\^\{([0-9a-zA-Z+-=]*)\}', r'<sup>\1</sup>', translated)
    translated = re.sub(r'\^([0-9a-zA-Z])', r'<sup>\1</sup>', translated)
    translated = re.sub(r'\_\{([0-9a-zA-Z+-=]*)\}', r'<sub>\1</sub>', translated)
    translated = re.sub(r'\_([0-9a-zA-Z])', r'<sub>\1</sub>', translated)
    
    # 2. Check if complex LaTeX is still present
    if "\\" in translated or "{" in translated or "}" in translated:
        encoded = urllib.parse.quote(formula_clean)
        color_hex = text_color.lstrip('#')
        dpi = "140" if is_display else "120"
        url = f"https://latex.codecogs.com/png.image?\\dpi{{{dpi}}}\\bg_transparent\\color[HTML]{{{color_hex}}}{encoded}"
        display_style = "display: block; margin: 8px auto;" if is_display else "vertical-align: middle; margin: 2px 0;"
        return f'<img src="{url}" alt="{html.escape(formula_clean)}" title="{html.escape(formula_clean)}" style="{display_style}" />'
        
    font_style = "font-size: 1.15em;" if is_display else ""
    return f'<span style="white-space: nowrap; font-family: \'Cambria Math\', \'Times New Roman\', serif; font-style: italic; {font_style}">{translated}</span>'

# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

# ── Theme constants — single source of truth is theme_manager.PALETTES["dark"] ──
from theme_manager import get_palette as _get_palette

_DARK = _get_palette("dark")
C_BG = _DARK["C_BG"]
C_SURFACE = _DARK["C_SURFACE"]
C_CARD = _DARK["C_CARD"]
C_ACCENT = _DARK["C_ACCENT"]
C_GREEN = _DARK["C_GREEN"]
C_RED = _DARK["C_RED"]
C_YELLOW = _DARK["C_YELLOW"]
C_TEXT = _DARK["C_TEXT"]
C_SUBTEXT = _DARK["C_SUBTEXT"]
C_BORDER = _DARK["C_BORDER"]
C_MASK = "#F7916A"
C_GROUP = "#BD93F9"


BASE_FONT_SIZE = 11


def _build_ss(font_size: int = BASE_FONT_SIZE) -> str:
    return f"""
QMainWindow,QDialog{{background:{C_BG};color:{C_TEXT};}}
QWidget{{background:{C_BG};color:{C_TEXT};font-family:'Segoe UI';font-size:{font_size}px;}}
QFrame{{background:{C_SURFACE};border-radius:8px;}}
QLabel{{background:transparent;color:{C_TEXT};}}
QPushButton{{background:{C_ACCENT};color:white;border:none;border-radius:8px;padding:8px 18px;font-weight:bold;}}
QPushButton:hover{{background:#6A58E0;}}
QPushButton:pressed{{background:#5448C8;}}
QPushButton#danger{{background:{C_RED};color:white;}}
QPushButton#danger:hover{{background:#CC3333;}}
QPushButton#success{{background:{C_GREEN};color:#1E1E2E;}}
QPushButton#success:hover{{background:#3DD668;}}
QPushButton#warning{{background:{C_YELLOW};color:#1E1E2E;}}
QPushButton#warning:hover{{background:#D9E070;}}
QPushButton#hard{{background:#E08030;color:white;}}
QPushButton#hard:hover{{background:#C06020;}}
QPushButton#flat{{background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};}}
QPushButton#flat:hover{{background:{C_SURFACE};}}
QListWidget,QTreeWidget{{background:{C_SURFACE};border:1px solid {C_BORDER};border-radius:8px;padding:4px;}}
QListWidget::item,QTreeWidget::item{{padding:6px;border-radius:6px;}}
QListWidget::item:selected,QTreeWidget::item:selected{{background:{C_ACCENT};color:white;}}
QListWidget::item:hover,QTreeWidget::item:hover{{background:{C_CARD};}}
QTreeView::drop-indicator{{background:{C_ACCENT};height:3px;border:none;border-radius:2px;}}
QScrollArea{{border:none;background:transparent;}}
QScrollBar:vertical{{background:{C_SURFACE};width:8px;border-radius:4px;}}
QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:4px;}}
QLineEdit,QTextEdit{{background:{C_CARD};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;padding:6px;}}
QProgressBar{{background:{C_CARD};border-radius:6px;height:12px;text-align:center;color:transparent;}}
QProgressBar::chunk{{background:{C_ACCENT};border-radius:6px;}}
QMessageBox{{background:{C_BG};color:{C_TEXT};}}
QStatusBar{{background:{C_SURFACE};color:{C_SUBTEXT};}}
QMenu{{background:{C_SURFACE};color:{C_TEXT};border:1px solid {C_BORDER};border-radius:6px;}}
QMenu::item:selected{{background:{C_ACCENT};}}
"""


SS = _build_ss()


# ═══════════════════════════════════════════════════════════════════════════════
#  NINJA DOJO THEME PALETTE  (matches test.html / dojo theme)
# ═══════════════════════════════════════════════════════════════════════════════

DOJO = {
    "bg": "#07070B",
    "surface": "#0F0F17",
    "card": "#14141F",
    "accent": "#72FF4F",  # neon green
    "accent2": "#A86CFF",  # purple
    "green": "#72FF4F",
    "red": "#FF4444",
    "yellow": "#FFD700",
    "text": "#E0E0FF",
    "subtext": "#5F627D",
    "border": "#1A1A26",
    "font": "'Orbitron', 'Share Tech Mono', monospace",
    "font_body": "'Rajdhani', 'Segoe UI', sans-serif",
}


def _is_dojo() -> bool:
    """Return True if the Ninja Dojo theme is currently active."""
    app = QApplication.instance()
    theme = getattr(app, "_active_theme", "classic")
    from theme_manager import is_retro_theme
    return is_retro_theme(theme) or theme == "dojo"


def _tc(classic_val: str, dojo_val: str) -> str:
    """Theme-conditional: return dojo_val if dojo active, else classic_val."""
    return dojo_val if _is_dojo() else classic_val


# ═══════════════════════════════════════════════════════════════════════════════
#  REVIEW SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

QUEUE_ROLE = Qt.UserRole + 10
QUEUE_INDEX_ROLE = Qt.UserRole + 11
CARD_DRAG_MIME = "application/x-anki-card"


class DraggableFrame(QFrame):
    def __init__(self, parent=None, on_drag=None, on_release=None):
        super().__init__(parent)
        self._on_drag = on_drag
        self._on_release = on_release
        self._drag_start_pos = None
        self.setCursor(Qt.OpenHandCursor)

    def enterEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        super().enterEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_start_pos is not None:
            new_pos = event.globalPos() - self._drag_start_pos
            parent = self.parentWidget()
            if parent:
                x = max(0, min(new_pos.x(), parent.width() - self.width()))
                y = max(0, min(new_pos.y(), parent.height() - self.height()))
                self.move(x, y)
                if self._on_drag:
                    self._on_drag(x, y)
            else:
                self.move(new_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = None
            self.setCursor(Qt.OpenHandCursor)
            if self._on_release:
                self._on_release(self.x(), self.y())
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class FloatingActionButton(QFrame):
    @staticmethod
    def to_rgba(color_str, alpha=1.0):
        if not color_str:
            return "transparent"
        color_str = str(color_str).strip()
        if color_str.startswith("#"):
            hex_body = color_str[1:]
            if len(hex_body) == 3:
                try:
                    r = int(hex_body[0] * 2, 16)
                    g = int(hex_body[1] * 2, 16)
                    b = int(hex_body[2] * 2, 16)
                    return f"rgba({r}, {g}, {b}, {alpha})"
                except ValueError:
                    return color_str
            elif len(hex_body) == 6:
                try:
                    r = int(hex_body[0:2], 16)
                    g = int(hex_body[2:4], 16)
                    b = int(hex_body[4:6], 16)
                    return f"rgba({r}, {g}, {b}, {alpha})"
                except ValueError:
                    return color_str
            elif len(hex_body) == 8:
                try:
                    r = int(hex_body[0:2], 16)
                    g = int(hex_body[2:4], 16)
                    b = int(hex_body[4:6], 16)
                    return f"rgba({r}, {g}, {b}, {alpha})"
                except ValueError:
                    return color_str
        return color_str

    def __init__(self, parent=None, text="Button", emoji="", on_click=None, border_color_hex=None):
        super().__init__(parent)
        self._on_click = on_click
        self._drag_start_pos = None
        self._press_pos = None
        self.text_str = text
        self.emoji_str = emoji
        self._border_color_hex = border_color_hex
        self._is_dim = False
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        self._bg_color = p.get("C_SURFACE", "#24283B")
        self.accent = border_color_hex or p.get("C_ACCENT", "#7C6AF7")
        self._text_color = p.get("C_TEXT", "#CDD6F4")
        self._subtext_color = p.get("C_SUBTEXT", "#A6ADC8")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(4)
        
        self.label = QLabel(f"{emoji} {text}" if emoji else text)
        self.label.setStyleSheet(
            f"color: {self._text_color}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
        )
        layout.addWidget(self.label)
        
        self.setCursor(Qt.PointingHandCursor)
        self.adjustSize()
        self.setFixedSize(self.sizeHint().width() + 10, 36)
        
        # Setup opacity effect for smooth fade proximity/drawing animations
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(1.0)
        self._current_opacity = 1.0

        self._update_style()

    def set_dim(self, dim: bool):
        self._is_dim = bool(dim)
        self._update_style()

    def _update_style(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        bg = getattr(self, "_bg_color", p.get("C_SURFACE", "#24283B"))
        accent = getattr(self, "accent", p.get("C_ACCENT", "#7C6AF7"))
        text_color = getattr(self, "_text_color", p.get("C_TEXT", "#CDD6F4"))
        subtext_color = getattr(self, "_subtext_color", p.get("C_SUBTEXT", "#A6ADC8"))

        if self._is_dim:
            dim_bg = self.to_rgba(bg, 0.4)
            dim_border = self.to_rgba(accent, 0.35)
            hover_bg = self.to_rgba(accent, 0.25)
            self.setStyleSheet(
                f"QFrame {{ "
                f"  background: {dim_bg}; "
                f"  border: 2px solid {dim_border}; "
                f"  border-radius: 18px; "
                f"  padding: 4px 10px; "
                f"}} "
                f"QFrame:hover {{ "
                f"  background: {hover_bg}; "
                f"  border-color: {dim_border}; "
                f"}}"
            )
            if hasattr(self, "label"):
                self.label.setStyleSheet(
                    f"color: {subtext_color}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
                )
        else:
            border_w = "4px" if self.text_str == "Ooze Hint" else "2px"
            self.setStyleSheet(
                f"QFrame {{ "
                f"  background: {bg}; "
                f"  border: {border_w} solid {accent}; "
                f"  border-radius: 18px; "
                f"  padding: 4px 10px; "
                f"}} "
                f"QFrame:hover {{ "
                f"  background: {accent}; "
                f"  border-color: white; "
                f"}}"
            )
            if hasattr(self, "label"):
                self.label.setStyleSheet(
                    f"color: {text_color}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
                )

    def fade_to(self, opacity, duration=150):
        if not hasattr(self, "_opacity_anim"):
            from PyQt5.QtCore import QPropertyAnimation
            self._opacity_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._opacity_anim.stop()
        self._opacity_anim.setDuration(duration)
        self._opacity_anim.setStartValue(self._opacity_effect.opacity())
        self._opacity_anim.setEndValue(opacity)
        self._opacity_anim.start()

    def slide_to(self, pos, duration=250):
        if not hasattr(self, "_slide_anim"):
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            self._slide_anim = QPropertyAnimation(self, b"pos")
            self._slide_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._slide_anim.stop()
        self._slide_anim.setDuration(duration)
        self._slide_anim.setStartValue(self.pos())
        self._slide_anim.setEndValue(pos)
        self._slide_anim.start()

    def enterEvent(self, event):
        if not self._is_dim:
            theme = getattr(QApplication.instance(), "_active_theme", "classic")
            from theme_manager import get_palette
            p = get_palette(theme)
            bg = p.get("C_BG", "#1E1E2E")
            if hasattr(self, "label"):
                self.label.setStyleSheet(
                    f"color: {bg if theme != 'classic' else 'white'}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
                )
        else:
            subtext_color = getattr(self, "_subtext_color", "#A6ADC8")
            if hasattr(self, "label"):
                self.label.setStyleSheet(
                    f"color: {subtext_color}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
                )
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_dim:
            theme = getattr(QApplication.instance(), "_active_theme", "classic")
            from theme_manager import get_palette
            p = get_palette(theme)
            text_color = p.get("C_TEXT", "#CDD6F4")
            if hasattr(self, "label"):
                self.label.setStyleSheet(
                    f"color: {text_color}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
                )
        else:
            subtext_color = getattr(self, "_subtext_color", "#A6ADC8")
            if hasattr(self, "label"):
                self.label.setStyleSheet(
                    f"color: {subtext_color}; font-weight: bold; font-size: 11px; background: transparent; border: none;"
                )
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
            self._press_pos = event.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_start_pos is not None:
            new_pos = event.globalPos() - self._drag_start_pos
            parent = self.parentWidget()
            if parent:
                x = max(0, min(new_pos.x(), parent.width() - self.width()))
                y = max(0, min(new_pos.y(), parent.height() - self.height()))
                self.move(x, y)
            else:
                self.move(new_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = None
            if self._press_pos is not None:
                diff = event.pos() - self._press_pos
                if diff.manhattanLength() < 5:
                    if self._on_click:
                        self._on_click()
            self._press_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

from ui.quick_note_dialog import QuickNoteDialog


from ui.review.queue_delegate import QueueDelegate


class SelectableTextBrowser(QTextBrowser):
    def keyPressEvent(self, event):
        from PyQt5.QtGui import QKeySequence
        if event.matches(QKeySequence.Copy):
            self.copy()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy(self):
        from PyQt5.QtGui import QCursor
        from PyQt5.QtCore import QPointF
        
        # If no active text selection, detect image under mouse pointer
        cursor = self.textCursor()
        if not cursor.hasSelection():
            pos = self.mapFromGlobal(QCursor.pos())
            layout_pos = QPointF(
                pos.x() + self.horizontalScrollBar().value(),
                pos.y() + self.verticalScrollBar().value()
            )
            img_src = self.document().documentLayout().imageAt(layout_pos)
            if not img_src:
                # Fallback to text cursor position under mouse
                c = self.cursorForPosition(pos)
                char_format = c.charFormat()
                if not char_format.isImageFormat():
                    temp = self.cursorForPosition(pos)
                    temp.movePosition(temp.Left)
                    char_format = temp.charFormat()
                if char_format.isImageFormat():
                    img_src = char_format.toImageFormat().name()
                    
            if img_src:
                import urllib.parse
                img_src = urllib.parse.unquote(img_src)
                if img_src.startswith("file:///"):
                    img_src_path = img_src[8:]
                    if len(img_src_path) > 2 and img_src_path[0] == '/' and img_src_path[2] == ':':
                        img_src_path = img_src_path[1:]
                elif img_src.startswith("file://"):
                    img_src_path = img_src[7:]
                else:
                    img_src_path = img_src
                    
                from storage_paths import resolve_asset_path
                import os
                abs_path = resolve_asset_path(img_src_path)
                if abs_path and os.path.exists(abs_path):
                    from PyQt5.QtGui import QPixmap
                    from PyQt5.QtWidgets import QApplication
                    pixmap = QPixmap(abs_path)
                    if not pixmap.isNull():
                        from PyQt5.QtCore import QMimeData, QByteArray, QBuffer, QIODevice
                        mime_data = QMimeData()
                        
                        data = QByteArray()
                        buffer = QBuffer(data)
                        buffer.open(QIODevice.WriteOnly)
                        pixmap.toImage().save(buffer, "PNG")
                        png_bytes = bytes(data)
                        
                        mime_data.setData("image/png", QByteArray(png_bytes))
                        mime_data.setImageData(pixmap.toImage())
                        
                        clipboard = QApplication.clipboard()
                        clipboard.setMimeData(mime_data)
                        print(f"[ANNO-LOG] Copy shortcut: Copied hovered image: {abs_path}")
                        return

        if self._try_copy_image(cursor):
            return
        super().copy()

    def _try_copy_image(self, cursor):
        char_format = cursor.charFormat()
        if not char_format.isImageFormat():
            temp = self.textCursor()
            temp.movePosition(temp.Left)
            char_format = temp.charFormat()

        # 2. Try character format after cursor (if not at end of document)
        if not char_format.isImageFormat() and cursor.position() < self.document().characterCount():
            temp = self.textCursor()
            temp.setPosition(cursor.position() + 1)
            char_format = temp.charFormat()
            
        # 3. If there is a selection, check within the selection range
        if not char_format.isImageFormat() and cursor.hasSelection():
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            temp = self.textCursor()
            for pos in range(start_pos + 1, end_pos + 1):
                temp.setPosition(pos)
                fmt = temp.charFormat()
                if fmt.isImageFormat():
                    char_format = fmt
                    break
            
        if char_format.isImageFormat():
            image_format = char_format.toImageFormat()
            image_name = image_format.name()
            
            from storage_paths import resolve_asset_path
            import os
            abs_path = resolve_asset_path(image_name)
            if abs_path and os.path.exists(abs_path):
                from PyQt5.QtGui import QPixmap
                from PyQt5.QtWidgets import QApplication
                pixmap = QPixmap(abs_path)
                if not pixmap.isNull():
                    from PyQt5.QtCore import QMimeData, QByteArray, QBuffer, QIODevice
                    mime_data = QMimeData()
                    
                    data = QByteArray()
                    buffer = QBuffer(data)
                    buffer.open(QIODevice.WriteOnly)
                    pixmap.toImage().save(buffer, "PNG")
                    png_bytes = bytes(data)
                    
                    mime_data.setData("image/png", QByteArray(png_bytes))
                    mime_data.setImageData(pixmap.toImage())
                    
                    clipboard = QApplication.clipboard()
                    clipboard.setMimeData(mime_data)
                    return True
        return False


class ReviewScreen(QWidget):
    finished = pyqtSignal()
    cancelled = pyqtSignal()
    undo_requested_when_empty = pyqtSignal()
    QUEUE_AUTO_HIDE_MS = 2000
    PRIORITY_PAGE_LIMIT = 16
    FLOATING_TIMER_MASK_FONT_PX = 36
    FLOATING_TIMER_SESSION_FONT_PX = 36
    FLOATING_TIMER_TODAY_FONT_PX = 30

    RATINGS = [
        ("1  🔁 Again", "danger", 1),
        ("2  😓 Hard", "hard", 3),
        ("3  ✅ Good", "success", 4),
        ("4  ⚡ Easy", "warning", 5),
        ("5  ⭐ Perfect", "perfect", 6),
    ]
    RATING_SHORTCUTS = {
        Qt.Key_1: 1,
        Qt.Key_2: 3,
        Qt.Key_3: 4,
        Qt.Key_4: 5,
        Qt.Key_5: 6,
    }
    RATING_SHORTCUT_ACTIONS = (
        ("review.rate_again", 1),
        ("review.rate_hard", 3),
        ("review.rate_good", 4),
        ("review.rate_easy", 5),
        ("review.rate_perfect", 6),
    )
    RATING_LABELS = ["Again", "Hard", "Good", "Easy", "Perfect"]
    REVEAL_BUTTON_SCALE = 1.3
    RATING_BUTTON_SCALE = 1.3
    QUEUE_EDGE_HANDLE_HOT_ZONE_PX = 10
    QUEUE_EDGE_HANDLE_GRACE_PX = 4
    REVIEW_VERBOSE_ENV = "ANKI_REVIEW_VERBOSE"
    REVIEW_SCROLL_PROFILE_ENV = "ANKI_REVIEW_SCROLL_PROFILE"
    FLOATING_TIMER_REPOSITION_MIN_MS = 80

    @staticmethod
    def _scaled_px(value, scale):
        return max(1, int(round(float(value) * float(scale))))

    @classmethod
    def _review_control_metrics(cls, dojo=False):
        return {
            "reveal_padding_y": cls._scaled_px(8, cls.REVEAL_BUTTON_SCALE),
            "reveal_padding_x": cls._scaled_px(40, cls.REVEAL_BUTTON_SCALE),
            "reveal_font": cls._scaled_px(9 if dojo else 13, cls.REVEAL_BUTTON_SCALE),
            "reveal_min_height": cls._scaled_px(40 if dojo else 38, cls.REVEAL_BUTTON_SCALE),
            "rating_height": cls._scaled_px(44 if dojo else 40, cls.RATING_BUTTON_SCALE),
            "rating_min_width": cls._scaled_px(140, cls.RATING_BUTTON_SCALE),
            "rating_font": cls._scaled_px(14 if dojo else 13, cls.RATING_BUTTON_SCALE),
            "rating_padding_x": cls._scaled_px(16, cls.RATING_BUTTON_SCALE),
            "rating_spacing": cls._scaled_px(8, cls.RATING_BUTTON_SCALE),
        }

    def _review_verbose_debug_enabled(self) -> bool:
        try:
            if not isinstance(self, type):
                return getattr(self, "_verbose_debug_enabled", False)
        except RuntimeError:
            pass
        raw = os.environ.get(self.REVIEW_VERBOSE_ENV, "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _review_scroll_profile_enabled(self) -> bool:
        try:
            if not isinstance(self, type):
                return getattr(self, "_scroll_profile_enabled", False)
        except RuntimeError:
            pass
        raw = os.environ.get(self.REVIEW_SCROLL_PROFILE_ENV, "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @property
    def _items(self):
        return self.mgr._items

    @_items.setter
    def _items(self, val):
        self.mgr._items = val

    @property
    def _idx(self):
        return self.mgr._idx

    @_idx.setter
    def _idx(self, val):
        self.mgr._idx = val

    @property
    def _done(self):
        return self.mgr._done

    @_done.setter
    def _done(self, val):
        self.mgr._done = val

    @property
    def _queued_ids(self):
        return self.mgr._queued_ids

    @_queued_ids.setter
    def _queued_ids(self, val):
        self.mgr._queued_ids = val

    @property
    def _deleted_ids(self):
        return self.mgr._deleted_ids

    @_deleted_ids.setter
    def _deleted_ids(self, val):
        self.mgr._deleted_ids = val

    @property
    def _review_undo_stack(self):
        return self.mgr._review_undo_stack

    @_review_undo_stack.setter
    def _review_undo_stack(self, val):
        self.mgr._review_undo_stack = val

    @property
    def _review_redo_stack(self):
        return self.mgr._review_redo_stack

    @_review_redo_stack.setter
    def _review_redo_stack(self, val):
        self.mgr._review_redo_stack = val

    @property
    def is_practice(self):
        return getattr(self.mgr, "is_practice", False) if hasattr(self, "mgr") and self.mgr is not None else False

    @is_practice.setter
    def is_practice(self, val):
        if hasattr(self, "mgr") and self.mgr is not None:
            self.mgr.is_practice = bool(val)

    def _rate(self, quality):
        # 1. Play low-latency 8-bit sound effects
        try:
            from data_manager import store
            vol = store.get().get("_volume", 40) / 100.0
            if quality in (4, 5, 6): # Good, Easy, Perfect
                if hasattr(self, "_snd_coin"):
                    self._snd_coin.setVolume(vol)
                    self._snd_coin.play()
            elif quality == 1: # Again
                if hasattr(self, "_snd_hit"):
                    self._snd_hit.setVolume(vol)
                    self._snd_hit.play()
        except Exception:
            pass

        # 2. Spawn retro particle burst
        if getattr(self, "burst", None) is not None:
            tone = "green" if quality in (4, 5, 6) else ("red" if quality in (1, 3) else "cyan")
            self.burst.spawn_burst(self.rect().center().x(), self.rect().center().y(), tone, count=30)

        self.mgr._rate(quality)

    def _review_undo(self):
        canvas = getattr(self, "canvas", None)
        if canvas is not None and getattr(canvas, "_ink_active", False) is True:
            if hasattr(canvas, "ink_undo_stroke") and getattr(canvas, "has_ink_undo")() is True:
                canvas.ink_undo_stroke()
                return
        self.mgr._review_undo()

    def _review_redo(self):
        canvas = getattr(self, "canvas", None)
        if canvas is not None and getattr(canvas, "_ink_active", False) is True:
            if hasattr(canvas, "ink_redo_stroke") and getattr(canvas, "has_ink_redo")() is True:
                canvas.ink_redo_stroke()
                return
        self.mgr._review_redo()

    def _skip_session(self):
        self.mgr.skip_session()

    def _super_skip(self):
        self.mgr.super_skip()

    def _close_bg_prefetch_dialog(self):
        self._bg_accept_mode = False
        self._bg_prefetch_total_pages = 0
        self._bg_prefetch_cached_count = 0
        self._bg_prefetch_rendered_count = 0

    def _show_bg_prefetch_dialog(self, path: str, total_pages: int):
        pass

    def _sync_bg_prefetch_dialog(self, path: str, total_pages: int, done: bool = False):
        pass

    def _accept_bg_prefetch(self):
        self._bg_accept_mode = True
        self._flush_pending_background_inserts()

    def _rebuild_queue(self, peek_idx=None):
        self.mgr._rebuild_queue(peek_idx)

    def _sync_queue_state(self, peek_idx=None):
        self.mgr._sync_queue_state(peek_idx)

    def _check_learning_due(self):
        self.mgr._check_learning_due()

    def _promote_expired_learning(self, insert_pos):
        self.mgr._promote_expired_learning(insert_pos)

    def _trigger_center_fit(self):
        if self.__dict__.get("_peek_idx") is not None:
            self._exit_peek()
            return

        center_on_target = self.__dict__.get("_center_on_target")
        if center_on_target is None:
            if "canvas" not in self.__dict__ or "_canvas_scroll" not in self.__dict__:
                return
            center_on_target = self._center_on_target

        center_on_target()

    def _update_queue_label(self, total):
        dojo = _is_dojo()
        base = "▸  QUEUE" if dojo else "📋  Queue"
        self._queue_label.setText(f"{base} ({total})")
        self._sync_floating_queue_count(total)
        self._sync_queue_timer_count(total)

    def _active_queue_count(self):
        try:
            return sum(1 for _, _, sm2 in self._items if is_due_today(sm2))
        except Exception:
            queue = self.__dict__.get("_queue_list")
            return int(queue.count()) if queue is not None else 0

    def _sync_floating_queue_count(self, total=None):
        queue_label = self.__dict__.get("_floating_timer_queue")
        if queue_label is None:
            return
        count = self._active_queue_count() if total is None else int(total)
        queue_label.setText(f"QUEUE ({max(0, count)})")

    def _sync_queue_timer_count(self, total=None):
        queue_label = self.__dict__.get("_queue_timer_count")
        if queue_label is None:
            return
        count = self._active_queue_count() if total is None else int(total)
        queue_label.setText(f"TO REVIEW: {max(0, count)}")

    def _init_review_profile(self, cards):
        from ui.review.profiler import init_review_profile
        init_review_profile(self, cards)

    def _review_profile_active(self):
        from ui.review.profiler import review_profile_active
        return review_profile_active(self)

    def _review_profile_rss_mb(self):
        from ui.review.profiler import review_profile_rss_mb
        return review_profile_rss_mb(self)

    def _review_profile_log(self, event, **fields):
        from ui.review.profiler import review_profile_log
        review_profile_log(self, event, **fields)

    def _review_profile_count(self, name, amount=1):
        from ui.review.profiler import review_profile_count
        return review_profile_count(self, name, amount)

    def __init__(self, cards, data=None, parent=None, state_to_restore=None, is_practice=False):
        super().__init__(parent)
        self._init_review_profile(cards)
        from services.review_manager import ReviewSessionManager

        self.mgr = ReviewSessionManager(self)
        self.mgr.is_practice = bool(is_practice)
        self._data = data
        
        # Load low-latency retro sounds
        import os
        try:
            self._snd_coin = QSoundEffect(self)
            self._snd_hit = QSoundEffect(self)
            self._snd_power = QSoundEffect(self)
            
            for fname, snd_obj in [("pickupCoin.wav", self._snd_coin), ("hitHurt.wav", self._snd_hit), ("powerUp.wav", self._snd_power)]:
                for root in [os.getcwd(), os.path.dirname(os.path.dirname(__file__))]:
                    path = os.path.abspath(os.path.join(root, "assets", "music", fname))
                    if os.path.exists(path):
                        snd_obj.setSource(QUrl.fromLocalFile(path))
                        break
            
            # Play a short powerUp entry sound if in retro theme
            theme = getattr(QApplication.instance(), "_active_theme", "classic")
            from theme_manager import is_retro_theme
            if is_retro_theme(theme) and os.environ.get("ANKI_HOME_ANIMATIONS", "").strip().lower() not in {"0", "false", "no", "off"}:
                from data_manager import store
                vol = store.get().get("_volume", 40) / 100.0
                self._snd_power.setVolume(vol)
                QTimer.singleShot(150, self._snd_power.play)
        except Exception as ex:
            print(f"[DEBUG][review_screen] sound load error: {ex}")

        self._cache_panel = None
        self._items = []
        self._hint_view_mode = "mask"
        self._pdf_cache = {}
        from collections import OrderedDict
        self._text_card_cache = OrderedDict()
        self._current_pixmap = None
        from services.pdf_watcher import PdfWatcher

        self._pdf_watcher = PdfWatcher(self)
        self._pdf_watcher.file_changed.connect(self._on_pdf_file_changed)
        self._pdf_watcher.reload_requested.connect(self._on_pdf_reload_requested)
        self._pdf_watcher.get_current_page_cb = lambda: self.canvas.get_current_page(
            self._canvas_scroll.verticalScrollBar().value()
        )
        self._pdf_watcher.get_hint_cb = lambda: (
            self._external_pdf_path_hint,
            self._external_pdf_page_hint,
        )
        self._watched_pdf_path = None
        self._review_ui_page_zero = 0
        self._review_nav_seq = 0
        self._pdf_render_zoom = 2.0

        self._pending_reload_page = None
        self._external_pdf_path_hint = None
        self._external_pdf_page_hint = None
        self._pending_visible_request = None
        self._pending_skeleton_result = None
        self._review_defer_visible_until_centered = False
        self._background_fill_state = None
        self._bg_remaining = None
        self._ondemand_kind = None
        self._ondemand_thread = None
        self._bg_pending_inserts = {}
        self._bg_accept_mode = False
        self._review_canvas_real_pages = set()
        self._review_render_inflight_pages = set()
        self._ondemand_request_pages_by_thread = {}
        self._review_priority_pages_cache = {}
        self._review_adapted_boxes_cache = {}
        self._bg_prefetch_dialog = None
        self._bg_prefetch_total_pages = 0
        self._bg_prefetch_cached_count = 0
        self._bg_prefetch_rendered_count = 0
        self._queue_locked = self._load_queue_locked()
        self._queue_drawer_open = True if self._queue_locked else False
        self._review_overlays_ready = False
        self._queue_edge_handle_visible = False
        self._review_data_dirty = False
        self._floating_timer_reposition_pending = False
        settings = QSettings("AnkiOcclusion", "App")
        try:
            self._hint_font_size = int(settings.value("review/hint_font_size", 13))
        except (TypeError, ValueError):
            self._hint_font_size = 13
        self._hint_font_size = max(8, min(40, self._hint_font_size))
        try:
            self._user_hint_width = int(settings.value("review/hint_panel_width", 360))
        except (TypeError, ValueError):
            self._user_hint_width = 360
        self._user_hint_width = max(200, min(1600, self._user_hint_width))
        self._hint_scroll_positions = {}
        try:
            self._timer_x_pct = float(settings.value("review/timer_x_pct", 1.0))
        except (TypeError, ValueError):
            self._timer_x_pct = 1.0
        try:
            self._timer_y_pct = float(settings.value("review/timer_y_pct", 0.0))
        except (TypeError, ValueError):
            self._timer_y_pct = 0.0
        self._floating_timer_last_reposition_ts = 0.0
        self._review_scroll_profile_last_event_ts = None
        self._review_scroll_profile_last_log_ts = 0.0
        self._review_last_decision_stats = {}
        self._queue_auto_hide_timer = QTimer(self)
        self._queue_auto_hide_timer.setSingleShot(True)
        self._queue_auto_hide_timer.setInterval(self.QUEUE_AUTO_HIDE_MS)
        self._queue_auto_hide_timer.timeout.connect(
            self._hide_queue_drawer_after_delay
        )
        self._floating_timer_sync_timer = None
        self._skeleton_thread = None
        self._ui_idle_timer = QTimer(self)
        self._ui_idle_timer.setSingleShot(True)
        self._ui_idle_timer.setInterval(220)
        self._ui_idle_timer.timeout.connect(self._on_ui_idle_timeout)
        self._peek_idx = None
        self._peek_origin_idx = None
        # ── User zoom tracking — None = no manual zoom set yet ────────────────
        self._user_zoom_scale = None
        self._review_ink_width = self._load_review_ink_width()
        self._review_ink_colors, self._review_ink_color_idx = self._load_review_ink_color()
        self._review_pen_implementation = settings.value("review/pen_implementation", "classic")

        raw_summary = settings.value("review/show_summary_popup", True)
        if isinstance(raw_summary, str):
            self._show_summary_popup = raw_summary.lower() in ("true", "1", "yes", "on")
        else:
            self._show_summary_popup = bool(raw_summary)

        # Cache environment variables to avoid expensive os.environ.get calls during hot scroll/paint paths
        self._scroll_profile_enabled = (
            os.environ.get(self.REVIEW_SCROLL_PROFILE_ENV, "").strip().lower()
            in ("1", "true", "yes", "on")
        )
        self._verbose_debug_enabled = (
            os.environ.get(self.REVIEW_VERBOSE_ENV, "").strip().lower()
            in ("1", "true", "yes", "on")
        )
        # ── O(1) box tracking ─────────────────────────────────────────────────
        if state_to_restore:
            self._items = state_to_restore["items"]
            self._idx = state_to_restore["idx"]
            self._done = state_to_restore["done"]
            self._review_undo_stack = state_to_restore["undo_stack"]
            self._review_redo_stack = state_to_restore["redo_stack"]
            self._queued_ids = state_to_restore["queued_ids"]
            self._deleted_ids = state_to_restore["deleted_ids"]
        else:
            self._items = []
            self._queued_ids = set()
            self._deleted_ids = set()

            seen_item_keys = set()

            # ── SM-2 Debug Logger removed ─────────────────────────────────────────

            queue_t0 = time.perf_counter()
            total_boxes_seen = 0
            for card in cards:
                boxes = card.get("boxes", [])
                total_boxes_seen += len(boxes)
                card_key = id(card)

                if len(boxes) == 0:
                    item_key = (card_key, None)
                    if item_key not in seen_item_keys:
                        seen_item_keys.add(item_key)
                        sm2_init(card)
                        self._items.append((card, None, card))
                    continue

                seen_groups = set()

                for i, box in enumerate(boxes):
                    sm2_init(box)
                    gid = box.get("group_id", "")

                    if gid:
                        if gid not in seen_groups:
                            seen_groups.add(gid)
                            item_key = (card_key, ("group", gid))
                            if item_key not in seen_item_keys:
                                seen_item_keys.add(item_key)
                                _due_result = is_due_today(box)
                                if _due_result:
                                    self._items.append((card, ("group", gid), box))
                                    self._queued_ids.add(gid)  # O(1) track
                    else:
                        box_id = box.get("box_id", f"__idx_{i}")
                        item_key = (card_key, box_id)
                        if item_key not in seen_item_keys:
                            seen_item_keys.add(item_key)
                            _due_result = is_due_today(box)
                            if _due_result:
                                self._items.append((card, i, box))
                                self._queued_ids.add(box_id)  # O(1) track

            # ── Sequential Chain Ordering ──────────────────────────────────────────
            chain_earliest_due = {}
            for card, box_idx, sm2_obj in self._items:
                chain_id = card.get("parent_chain_id")
                if chain_id:
                    due = sm2_obj.get("sm2_due", "") or ""
                    if chain_id not in chain_earliest_due or (due and due < chain_earliest_due[chain_id]):
                        chain_earliest_due[chain_id] = due

            def _review_sort_key(item):
                card, box_idx, sm2_obj = item
                chain_id = card.get("parent_chain_id")
                if chain_id:
                    c_due = chain_earliest_due.get(chain_id, "")
                    try:
                        c_order = int(card.get("chain_order", 0) or 0)
                    except (ValueError, TypeError):
                        c_order = 0
                    return (c_due, str(chain_id), c_order, sm2_obj.get("sm2_due", "") or "")
                else:
                    return (sm2_obj.get("sm2_due", "") or "", "", 0, "")

            self._items.sort(key=_review_sort_key)
            self._review_profile_log(
                "queue_built",
                elapsed=f"{(time.perf_counter() - queue_t0) * 1000:.1f}ms",
                source_cards=len(cards or []),
                boxes=total_boxes_seen,
                due_items=len(self._items),
                queued_ids=len(self._queued_ids),
            )
            self._idx = 0
            self._done = 0
            self._review_undo_stack = []  # list of state snapshots
            self._review_redo_stack = []  # cleared on new rating, filled on undo

        # ── Session Timer ─────────────────────────────────────────────────────
        if _TIMER_AVAILABLE:
            self._stimer = SessionTimer(self)
            self._stimer.start()
        else:
            self._stimer = None

        ui_t0 = time.perf_counter()
        self._setup_ui()
        self._review_profile_log(
            "ui_built", elapsed=f"{(time.perf_counter() - ui_t0) * 1000:.1f}ms"
        )
        for w in (
            self,
            self.canvas,
            self._canvas_scroll.viewport(),
            self._queue_panel,
            self._queue_list.viewport(),
            self._queue_edge_button,
            self._queue_lock_button,
            self._queue_hide_button,
        ):
            try:
                w.setMouseTracking(True)
                w.installEventFilter(self)
            except Exception:
                pass
        if state_to_restore:
            self._review_undo()
        else:
            self._load_item()
        self._review_profile_log("init_complete", items=len(self._items))

    def _toggle_cache_panel(self):
        from cache_manager import CacheManagerPanel

        if self._cache_panel is None:
            self._cache_panel = CacheManagerPanel(parent=self)
        if self._cache_panel.isVisible():
            self._cache_panel.hide()
        else:
            self._cache_panel.show()
            self._cache_panel.refresh()

    def _get_current_hint_key(self):
        if not hasattr(self, "_items") or not (0 <= self._idx < len(self._items)):
            return None
        card, box_idx, active_box = self._items[self._idx]
        cid = str(card.get("_id") or card.get("id") or id(card))
        b_key = str(box_idx)
        return (cid, b_key, getattr(self, "_hint_view_mode", "mask"))

    def _on_hint_scrolled(self, value):
        if getattr(self, "_restoring_hint_scroll", False):
            return
        if hasattr(self, "_hint_panel") and not self._hint_panel.isVisible():
            return
        if hasattr(self, "_items") and 0 <= self._idx < len(self._items):
            self._hint_scroll_positions[self._idx] = value

    def _set_hint_panel_visible(self, visible: bool):
        if visible:
            self._reposition_hint_panel()
            self._hint_panel.show()
            self._hint_panel.raise_()
            if getattr(self, "_floating_hint_button", None):
                self._floating_hint_button.raise_()
            if getattr(self, "_reveal_bar", None) is not None:
                self._reveal_bar.raise_()
            if getattr(self, "_rating_frame", None) is not None:
                self._rating_frame.raise_()
            self._btn_note.setChecked(True)
            curr_key = self._get_current_hint_key()
            if getattr(self, "_last_rendered_hint_key", None) != curr_key or self._hint_browser.document().isEmpty():
                self._update_mask_note_ui(keep_visible=True)
            else:
                self._update_hint_scroll_indicators()
        else:
            if hasattr(self, "_hint_browser") and self._hint_browser is not None:
                if hasattr(self, "_items") and 0 <= self._idx < len(self._items):
                    self._hint_scroll_positions[self._idx] = self._hint_browser.verticalScrollBar().value()
            self._hint_panel.hide()
            self._btn_note.setChecked(False)

    def _log_shortcut_trigger(self, action_id: str, handler_name: str, key_event=None):
        key_name = ""
        if key_event is not None:
            try:
                key_name = QKeySequence(int(key_event.modifiers()) | int(key_event.key())).toString()
            except Exception:
                pass
        if not key_name:
            key_name = shortcut_manager.shortcut_text(action_id)
        msg = f"[SHORTCUT] Key '{key_name}' -> Triggered '{action_id}' -> Calling {handler_name}()"
        print(msg, flush=True)
        try:
            import os
            app_data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AnkiOcclusion")
            log_file_path = os.path.join(app_data_dir, "anki_occlusion.log")
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"{msg}\n")
        except Exception:
            pass

    def _toggle_hint_panel(self):
        self._log_shortcut_trigger("review.toggle_note", "_toggle_hint_panel")
        if self._hint_panel.isVisible() and getattr(self, "_hint_view_mode", "mask") == "mask":
            self._set_hint_panel_visible(False)
        else:
            self._hint_view_mode = "mask"
            self._update_hint_tab_styles()
            self._set_hint_panel_visible(True)
            self._update_mask_note_ui(keep_visible=True)
        self.setFocus()

    def _toggle_pdf_notes(self):
        self._log_shortcut_trigger("review.toggle_pdf_notes", "_toggle_pdf_notes")
        if self._hint_panel.isVisible() and getattr(self, "_hint_view_mode", "mask") == "pdf":
            self._set_hint_panel_visible(False)
        else:
            self._hint_view_mode = "pdf"
            self._update_hint_tab_styles()
            self._set_hint_panel_visible(True)
            self._update_mask_note_ui(keep_visible=True)
        self.setFocus()

    def _update_mask_note_ui(self, keep_visible=False):
        if not keep_visible:
            self._btn_note.setChecked(False)
            self._hint_browser.clear()
            self._hint_panel.hide()
            if getattr(self, "_floating_hint_button", None):
                self._floating_hint_button.hide()

        if not (0 <= self._idx < len(self._items)):
            self._btn_note.setEnabled(False)
            self._btn_save_ink.setEnabled(False)
            if getattr(self, "_floating_hint_button", None):
                self._floating_hint_button.hide()
            return

        self._btn_save_ink.setEnabled(True)

        card, box_idx, active_box = self._items[self._idx]

        note_content = ""
        if card.get("card_type") == "text":
            note_content = card.get("notes", "") or card.get("note", "")
        elif active_box is not None and active_box is not card:
            if hasattr(active_box, "get"):
                note_content = active_box.get("note", "") or active_box.get("notes", "")
            else:
                note_content = getattr(active_box, "note", "") or getattr(active_box, "notes", "")

        if not note_content:
            note_content = card.get("notes", "") or card.get("note", "")

        note_content = (note_content or "").strip()
        self._current_note_content = note_content

        self._btn_note.setEnabled(True)
        if getattr(self, "_floating_hint_button", None):
            self._floating_hint_button.show()
            self._floating_hint_button.set_dim(not bool(note_content))

        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        text_color = p.get("C_TEXT", "#CDD6F4")
        subtext_color = p.get("C_SUBTEXT", "#A6ADC8")
        accent_color = p.get("C_ACCENT", "#7C6AF7")
        font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        border_color = p.get("C_BORDER", "#313244")

        css = f"""
        body {{
            color: {text_color};
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            font-size: {self._hint_font_size}px;
            line-height: 1.25;
            margin: 2px;
            padding: 0;
        }}
        p {{
            margin: 1px 0;
            padding: 0;
        }}
        a {{
            color: {accent_color};
            text-decoration: none;
        }}
        img {{
            max-width: 100%;
            border-radius: 4px;
            margin: 2px 0;
            vertical-align: top;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 4px 0;
            border: 1px solid {border_color};
        }}
        th, td {{
            padding: 3px 6px;
            border: 1px solid {border_color};
        }}
        th {{
            background-color: rgba(255, 255, 255, 0.08);
            font-weight: bold;
        }}
        """

        def format_field(text):
            if not text:
                return ""
            
            is_html = ("<p>" in text or "<div>" in text or "<span>" in text or "<br" in text or "<table" in text or "<img" in text or "<html>" in text)
            
            processed = text
            if not is_html:
                import html
                processed = html.escape(text)
                processed = parse_markdown_tables(processed)
            
            processed = parse_latex_math(processed, text_color)
            return processed

        # Fetch PDF metadata if available
        pdf_path = card.get("pdf_path")
        pdf_meta = None
        if pdf_path:
            from data_manager import store
            metadata_dict = store._data.setdefault("pdf_metadata", {})
            pdf_meta = metadata_dict.get(pdf_path)
            if not pdf_meta:
                base_name = os.path.basename(pdf_path)
                for k, v in metadata_dict.items():
                    if os.path.basename(k) == base_name:
                        pdf_meta = v
                        break

        # Combine active note and PDF note content for image scanning
        all_notes_for_img_scan = note_content or ""
        if pdf_meta and pdf_meta.get("notes"):
            all_notes_for_img_scan += " " + pdf_meta.get("notes", "")

        # Check current view mode
        view_mode = getattr(self, "_hint_view_mode", "mask")
        
        if view_mode == "mask":
            if note_content:
                n_html = format_field(note_content)
            else:
                themed_text = "Jutsu" if theme == "dojo" else ("Spell" if theme == "arcanum" else "Mask")
                n_html = f"<i style='color:{subtext_color};'>No {themed_text.lower()} hint or note yet.</i><br><br><span style='font-size:11px;color:{subtext_color};'>Press <b>Ctrl+N</b> to add a hint/note or sketch a diagram.</span>"
        else:
            pdf_html = ""
            if pdf_meta:
                lecture = pdf_meta.get("lecture_num", "").strip()
                notes = pdf_meta.get("notes", "").strip()
                if lecture or notes:
                    pdf_html = f"""
                    <div>
                        <div style="color: {accent_color}; font-weight: bold; font-size: 11px; letter-spacing: 0.5px; margin-bottom: 6px;">📄 PDF REFERENCE NOTES</div>
                    """
                    if lecture:
                        pdf_html += f'<div style="font-weight: bold; margin-bottom: 6px; font-size: 12px;">Lecture: {lecture}</div>'
                    if notes:
                        pdf_html += f'<div style="color: {subtext_color}; font-size: 12px; line-height: 1.4;">{format_field(notes)}</div>'
                    pdf_html += "</div>"
            
            if pdf_html:
                n_html = pdf_html
            else:
                n_html = f"<i style='color:{subtext_color};'>No PDF reference notes saved for this document.</i><br><br><span style='font-size:11px;color:{subtext_color};'>Click the <b>📄 PDF Notes</b> button in the top toolbar to add lecture notes or formulas.</span>"

        # Define log helper
        def log_debug(message):
            try:
                import os
                app_data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AnkiOcclusion")
                log_file_path = os.path.join(app_data_dir, "anki_occlusion.log")
                with open(log_file_path, "a", encoding="utf-8") as f:
                    f.write(f"[DEBUG][hint_panel] {message}\n")
            except Exception:
                pass

        log_debug(f"=== _update_mask_note_ui (idx={self._idx}) ===")
        log_debug(f"note_content len: {len(note_content) if note_content else 0}")

        user_w = getattr(self, "_user_hint_width", 360)
        panel_is_visible = hasattr(self, "_hint_panel") and self._hint_panel is not None and self._hint_panel.isVisible()
        if panel_is_visible and hasattr(self, "_hint_browser") and self._hint_browser is not None and self._hint_browser.isVisible():
            try:
                vw = int(self._hint_browser.viewport().width())
                panel_w = max(200, vw - 24) if vw > 100 else max(200, user_w - 30)
            except Exception:
                panel_w = max(200, user_w - 30)
        else:
            panel_w = max(200, user_w - 30)

        from editor_ui import get_base_url
        self._hint_browser.document().setBaseUrl(get_base_url())

        def process_html_images(html_content):
            if not html_content:
                return ""
            import re
            import os
            from storage_paths import resolve_asset_path
            
            # Clean up empty paragraphs and consecutive breaks to remove dead vertical space
            content = re.sub(r'<p[^>]*>(\s*|<br\s*/?>|&nbsp;)*</p>', '', html_content, flags=re.IGNORECASE)
            content = re.sub(r'(<br\s*/?>\s*){2,}', '<br>', content, flags=re.IGNORECASE)
            
            def replace_src(match):
                tag = match.group(0)
                # Strip hardcoded height so aspect ratio is 100% natural and never distorted
                tag = re.sub(r'\bheight\s*=\s*["\']([^"\']*)["\']', '', tag, flags=re.IGNORECASE)
                
                src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
                if src_match:
                    src = src_match.group(1)
                    if not src.lower().startswith(('http://', 'https://', 'data:', 'file:')):
                        abs_path = resolve_asset_path(src)
                        abs_path = os.path.normpath(abs_path)
                        abs_path_url = QUrl.fromLocalFile(abs_path).toString()
                        tag = re.sub(
                            r'src\s*=\s*["\'][^"\']+["\']',
                            f'src="{abs_path_url}"',
                            tag,
                            flags=re.IGNORECASE
                        )
                        # Check natural image width to fit within panel without horizontal scrolling
                        if os.path.exists(abs_path):
                            pix = QPixmap(abs_path)
                            if not pix.isNull():
                                natural_w = pix.width()
                                target_w = min(natural_w, panel_w)
                                tag = re.sub(r'\bwidth\s*=\s*["\']([^"\']*)["\']', '', tag, flags=re.IGNORECASE)
                                tag_clean = tag.strip().rstrip('>').rstrip('/')
                                tag = tag_clean + f' width="{target_w}">'
                return tag
                
            return re.sub(r'<img[^>]+>', replace_src, content, flags=re.IGNORECASE)

        html_body = f"<html><head><style>{css}</style></head><body>{process_html_images(n_html)}</body></html>"
        self._hint_browser.setHtml(html_body)
        self._last_rendered_hint_key = self._get_current_hint_key()
        
        # Trigger scroll indicator update after layout recalculates
        QTimer.singleShot(100, self._update_hint_scroll_indicators)
        
        # Restore saved scroll position for current question safely
        saved_pos = self._hint_scroll_positions.get(self._idx, 0)
        self._restoring_hint_scroll = True
        def _restore_scroll():
            if hasattr(self, "_hint_browser") and self._hint_browser is not None:
                self._hint_browser.verticalScrollBar().setValue(saved_pos)
                self._update_hint_scroll_indicators()
                self._restoring_hint_scroll = False
        QTimer.singleShot(0, _restore_scroll)
        QTimer.singleShot(50, _restore_scroll)
        
        self._reposition_floating_buttons()

    def _reposition_floating_buttons(self):
        self._update_floating_buttons_layout()

    def _update_floating_buttons_layout(self):
        if "_floating_hint_button" not in self.__dict__ or self._floating_hint_button is None:
            return
            
        # 1. Determine target visibility
        # The hint button is always visible as long as we have items
        hint_visible = (0 <= self._idx < len(self._items))
        
        # Save buttons are visible if pen/eraser is active AND slide hover state is active
        save_visible = False
        if hasattr(self, "canvas") and self.canvas is not None:
            pen_active = getattr(self.canvas, "_ink_active", False)
            save_visible = pen_active and getattr(self, "_save_buttons_slide_visible", False)
            
        # 2. Get the list of buttons in their target order
        target_buttons = []
        if hint_visible:
            target_buttons.append(self._floating_hint_button)
        if save_visible:
            if "_floating_save_clear_button" in self.__dict__ and self._floating_save_clear_button is not None:
                target_buttons.append(self._floating_save_clear_button)
            if "_floating_save_keep_button" in self.__dict__ and self._floating_save_keep_button is not None:
                target_buttons.append(self._floating_save_keep_button)
                
        # 3. Position / animate visible buttons
        x = 15
        for btn in target_buttons:
            # If the button was hidden, make it visible first, placing it at start position (e.g. x=-150)
            if not btn.isVisible():
                btn.show()
                btn.move(-150, 15)
            # Slide to its target position
            btn.slide_to(QPoint(x, 15))
            x += btn.width() + 10
            
        # 4. Slide out and hide buttons that should be hidden
        all_btns = []
        if "_floating_hint_button" in self.__dict__ and self._floating_hint_button is not None:
            all_btns.append(self._floating_hint_button)
        if "_floating_save_clear_button" in self.__dict__ and self._floating_save_clear_button is not None:
            all_btns.append(self._floating_save_clear_button)
        if "_floating_save_keep_button" in self.__dict__ and self._floating_save_keep_button is not None:
            all_btns.append(self._floating_save_keep_button)

        for btn in all_btns:
            if btn and btn not in target_buttons:
                if btn.isVisible():
                    # Slide to left and hide when animation finishes
                    btn.slide_to(QPoint(-150, 15))
                    QTimer.singleShot(250, btn.hide)

    def _check_floating_button_proximity(self):
        if "_floating_hint_button" not in self.__dict__ or self._floating_hint_button is None:
            return
            
        # Get mouse position relative to self._canvas_stage
        pos_global = QCursor.pos()
        pos_local = self._canvas_stage.mapFromGlobal(pos_global)
        
        # Check if mouse is in the canvas stage rect
        in_stage = self._canvas_stage.rect().contains(pos_local)
        
        # 1. Determine if hovering over any of the three buttons
        hovering_hint = (self._floating_hint_button.isVisible() and 
                         self._floating_hint_button.geometry().contains(pos_local))
        hovering_save_clear = (self._floating_save_clear_button.isVisible() and 
                               self._floating_save_clear_button.geometry().contains(pos_local))
        hovering_save_keep = (self._floating_save_keep_button.isVisible() and 
                              self._floating_save_keep_button.geometry().contains(pos_local))
                              
        hovering_any_button = hovering_hint or hovering_save_clear or hovering_save_keep
        
        # 2. Update the slide_visible state for the save buttons
        pen_active = False
        if hasattr(self, "canvas") and self.canvas is not None:
            pen_active = getattr(self.canvas, "_ink_active", False)
            
        if pen_active:
            if hovering_any_button:
                # User is hovering over the buttons: show them
                if not getattr(self, "_save_buttons_slide_visible", False):
                    self._save_buttons_slide_visible = True
                    self._update_floating_buttons_layout()
                self._mouse_left_buttons_time = None
            else:
                # Mouse is NOT hovering over any button
                if getattr(self, "_save_buttons_slide_visible", False):
                    if getattr(self, "_mouse_left_buttons_time", None) is None:
                        self._mouse_left_buttons_time = time.time()
                    elif time.time() - self._mouse_left_buttons_time >= 1.5:
                        self._save_buttons_slide_visible = False
                        self._mouse_left_buttons_time = None
                        self._update_floating_buttons_layout()
        else:
            # Pen not active: always hide save buttons
            if getattr(self, "_save_buttons_slide_visible", False):
                self._save_buttons_slide_visible = False
                self._update_floating_buttons_layout()
            self._mouse_left_buttons_time = None

        # 3. Handle proximity opacity-fading
        # Determine if mouse is in the top-left area where buttons are
        # The area is x < 420 and y < 80
        in_proximity_zone = in_stage and pos_local.x() < 420 and pos_local.y() < 80
        
        # Decide target opacity
        # If in proximity zone and NOT hovering directly over a button, fade them to 0.15
        # Otherwise, keep them fully visible (1.0)
        target_opacity = 1.0
        if in_proximity_zone and not hovering_any_button:
            target_opacity = 0.15
            
        all_btns = []
        if "_floating_hint_button" in self.__dict__ and self._floating_hint_button is not None:
            all_btns.append(self._floating_hint_button)
        if "_floating_save_clear_button" in self.__dict__ and self._floating_save_clear_button is not None:
            all_btns.append(self._floating_save_clear_button)
        if "_floating_save_keep_button" in self.__dict__ and self._floating_save_keep_button is not None:
            all_btns.append(self._floating_save_keep_button)

        for btn in all_btns:
            if btn and btn.isVisible():
                if not hasattr(btn, "_current_opacity") or btn._current_opacity != target_opacity:
                    btn._current_opacity = target_opacity
                    btn.fade_to(target_opacity)

    def _show_review_toast(self, msg: str):
        if not hasattr(self, "_review_toast_label") or self._review_toast_label is None:
            self._review_toast_label = QLabel(self)
            self._review_toast_label.setStyleSheet(
                "QLabel{background:rgba(30,30,46,220);color:#F38BA8;"
                "border:1px solid #F38BA8;border-radius:6px;"
                "padding:6px 14px;font-size:12px;font-weight:bold;}"
            )
            self._review_toast_timer = QTimer(self)
            self._review_toast_timer.setSingleShot(True)
            self._review_toast_timer.timeout.connect(lambda: self._review_toast_label.hide())
        
        self._review_toast_label.setText(msg)
        self._review_toast_label.adjustSize()
        x = (self.width() - self._review_toast_label.width()) // 2
        y = 50
        self._review_toast_label.move(x, y)
        self._review_toast_label.show()
        self._review_toast_label.raise_()
        self._review_toast_timer.start(2000)

    def _save_review_ink_to_note(self, clear_ink=True):
        if not getattr(self, "canvas", None) or not self.canvas._ink_strokes:
            self._show_review_toast("⚠️ No drawings to save!")
            return
            
        was_active = getattr(self, "_was_ink_active_before_ctrl", False) or getattr(self.canvas, "_ink_active", False)
        from PyQt5.QtCore import QSize
        from PyQt5.QtWidgets import QDialog, QApplication
        from ui.crop_dialog import CropInkDialog, get_auto_crop_rect, render_cropped_strokes
        
        # Calculate canvas size dynamically based on scale to prevent clipping scratchpad drawings
        sc = getattr(self.canvas, "_scale", 1.0) or 1.0
        canvas_size = QSize(int(self.canvas.width() / sc), int(self.canvas.height() / sc))
        
        card_img_size = None
        if self.canvas._px is not None:
            card_img_size = self.canvas._px.size()
        elif getattr(self.canvas, "_pages", None):
            card_img_size = QSize(self.canvas._total_w, self.canvas._total_h)
            
        if not clear_ink:
            # INSTANT COPY (no prompting dialog)
            crop_rect = get_auto_crop_rect(self.canvas._ink_strokes, canvas_size, card_img_size)
            px = render_cropped_strokes(self.canvas._ink_strokes, crop_rect, self.canvas._ink_width)
        else:
            dialog = CropInkDialog(
                self.canvas._ink_strokes,
                canvas_size,
                self.canvas._ink_width,
                parent=self,
                card_img_size=card_img_size
            )
            if dialog.exec_() != QDialog.Accepted:
                if was_active:
                    if getattr(self, "canvas", None):
                        self.canvas.ink_set_active(True)
                        self._update_ink_hint()
                        self._update_pen_button_states()
                    self._was_ink_active_before_ctrl = False
                return # Cancelled
            px = dialog.get_cropped_pixmap()
            
        # 1. Copy to clipboard
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(px)
        
        # 2. Save to local media folder and append to card/box note (only if clear_ink is True)
        import os
        import uuid
        import storage_paths
        
        image_dir = storage_paths.archive_image_dir()
        saved_to_note = False
        if clear_ink and image_dir:
            try:
                os.makedirs(image_dir, exist_ok=True)
                filename = f"sketch_{uuid.uuid4().hex[:8]}.png"
                file_path = os.path.join(image_dir, filename)
                px.save(file_path, "PNG")
                relative_path = f"images/{filename}"
                
                if 0 <= self._idx < len(self._items):
                    card, box_idx, active_box = self._items[self._idx]
                    
                    current_note = ""
                    if card.get("card_type") == "text":
                        current_note = card.get("notes", "") or card.get("note", "")
                    elif active_box is not None and active_box is not card:
                        if hasattr(active_box, "get"):
                            current_note = active_box.get("note", "") or active_box.get("notes", "")
                        else:
                            current_note = getattr(active_box, "note", "") or getattr(active_box, "notes", "")
                    if not current_note:
                        current_note = card.get("notes", "") or card.get("note", "")
                        
                    current_note = (current_note or "").strip()
                    
                    import base64
                    import json
                    stroke_data_list = []
                    for stroke in self.canvas._ink_strokes:
                        color_hex = stroke[0].name() if hasattr(stroke[0], "name") else str(stroke[0])
                        pts = [{"x": pt.x(), "y": pt.y()} for pt in stroke[1:]]
                        stroke_data_list.append({
                            "color": color_hex,
                            "points": pts,
                            "implementation": getattr(stroke, "_implementation", "classic"),
                            "path_key": getattr(stroke, "_path_key", None)
                        })
                    serialized_strokes = json.dumps(stroke_data_list)
                    b64_strokes = base64.b64encode(serialized_strokes.encode('utf-8')).decode('utf-8')
                    img_tag = f'<img src="{relative_path}" width="{px.width()}" height="{px.height()}" data-strokes="{b64_strokes}">'
                    restored_info = getattr(self, "_restored_image_info", None)
                    replaced = False
                    if restored_info:
                        restored_idx, restored_box_idx, restored_filename = restored_info
                        if restored_idx == self._idx and restored_box_idx == box_idx:
                            import re
                            pattern = re.compile(rf'<img[^>]+?{re.escape(restored_filename)}[^>]*?>')
                            if pattern.search(current_note):
                                new_note = pattern.sub(img_tag, current_note)
                                replaced = True
                                
                    if not replaced:
                        if current_note:
                            if "<img" in current_note or "<html>" in current_note or "<p>" in current_note or "<div" in current_note or "<br" in current_note:
                                new_note = f"{current_note}<br><br>{img_tag}"
                            else:
                                new_note = f"{current_note}\n\n{img_tag}"
                        else:
                            new_note = img_tag
                            
                    self._restored_image_info = None
                        
                    if card.get("card_type") == "text":
                        card["notes"] = new_note
                        card["note"] = new_note
                    elif active_box is not None and active_box is not card:
                        if hasattr(active_box, "__setitem__"):
                            active_box["note"] = new_note
                        elif hasattr(active_box, "note"):
                            active_box.note = new_note
                    else:
                        card["notes"] = new_note
                        card["note"] = new_note
                        
                    if getattr(self, "canvas", None) is not None:
                        if isinstance(box_idx, int) and 0 <= box_idx < len(self.canvas._boxes):
                            self.canvas._boxes[box_idx]["note"] = new_note
                        elif isinstance(box_idx, tuple) and box_idx[0] == "group":
                            gid = box_idx[1]
                            for b in self.canvas._boxes:
                                if b.get("group_id") == gid:
                                    b["note"] = new_note
                                    
                    from data_manager import store
                    store.save_force(async_save=True, force_gdrive=False)
                    
                    self._update_mask_note_ui(keep_visible=True)
                    self._set_hint_panel_visible(True)
                    saved_to_note = True
            except Exception:
                pass
                
        if clear_ink:
            self.canvas.ink_clear()
            if saved_to_note:
                self._show_review_toast("🎨 Saved drawing to hint box & copied to clipboard!")
            else:
                self._show_review_toast("📋 Copied drawing to clipboard!")
        else:
            self._show_review_toast("📋 Copied drawing to clipboard (canvas kept)!")

        # Restore or keep ink state active
        if was_active:
            if getattr(self, "canvas", None):
                self.canvas.ink_set_active(True)
                self._update_ink_hint()
                self._update_pen_button_states()
            self._was_ink_active_before_ctrl = False

    def _open_quick_note_editor_for_box_idx(self, box_idx_to_edit):
        if not (0 <= self._idx < len(self._items)):
            return
            
        card, current_box_idx, active_box = self._items[self._idx]
        
        if not (0 <= box_idx_to_edit < len(card.get("boxes", []))):
            self._open_quick_note_editor()
            return
            
        target_box = card.get("boxes")[box_idx_to_edit]
        
        current_note = ""
        if hasattr(target_box, "get"):
            current_note = target_box.get("note", "")
        else:
            current_note = getattr(target_box, "note", "")
            
        current_note = current_note or ""
        
        dialog = QuickNoteDialog(current_note, parent=self)
        dialog.setWindowTitle(f"Edit Mask Note / Hint - Mask #{box_idx_to_edit + 1}")
        accepted = (dialog.exec_() == QDialog.Accepted)
        
        if getattr(self, "_was_ink_active_before_ctrl", False):
            if getattr(self, "canvas", None):
                self.canvas.ink_set_active(True)
                self._update_ink_hint()
                self._update_pen_button_states()
            self._was_ink_active_before_ctrl = False
            
        if accepted:
            if "<img" in dialog.note_edit.toHtml():
                new_note = dialog.note_edit.toHtml()
            else:
                new_note = dialog.note_edit.toPlainText().strip()
                
            gid = target_box.get("group_id") if hasattr(target_box, "get") else getattr(target_box, "group_id", None)
            
            # Update the card database representation
            if gid:
                for b in card.get("boxes", []):
                    b_gid = b.get("group_id") if hasattr(b, "get") else getattr(b, "group_id", None)
                    if b_gid == gid:
                        if hasattr(b, "__setitem__"):
                            b["note"] = new_note
                        elif hasattr(b, "note"):
                            b.note = new_note
            else:
                if hasattr(target_box, "__setitem__"):
                    target_box["note"] = new_note
                elif hasattr(target_box, "note"):
                    target_box.note = new_note
                    
            # Update canvas in-memory boxes in real-time
            if getattr(self, "canvas", None) is not None:
                if gid:
                    for b in self.canvas._boxes:
                        if b.get("group_id") == gid:
                            b["note"] = new_note
                elif 0 <= box_idx_to_edit < len(self.canvas._boxes):
                    self.canvas._boxes[box_idx_to_edit]["note"] = new_note
                    
            from data_manager import store
            store.save_force(async_save=True, force_gdrive=False)
            
            # If the edited box matches the active box under review, update UI
            is_active_match = False
            if isinstance(current_box_idx, int) and current_box_idx == box_idx_to_edit:
                is_active_match = True
            elif isinstance(current_box_idx, tuple) and current_box_idx[0] == "group" and gid and current_box_idx[1] == gid:
                is_active_match = True
                
            if is_active_match:
                self._update_mask_note_ui(keep_visible=True)
                if not self._reveal_bar.isVisible():
                    self._set_hint_panel_visible(True)
            else:
                self._show_review_toast(f"💾 Saved note for Mask #{box_idx_to_edit + 1}!")
                
        dialog.deleteLater()

    def _on_canvas_right_clicked_box(self, box_idx, global_pos):
        if not (0 <= self._idx < len(self._items)):
            return
            
        card, current_box_idx, _ = self._items[self._idx]
        if not (0 <= box_idx < len(card.get("boxes", []))):
            return
            
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        bg = p.get("C_SURFACE", "#24283B")
        text = p.get("C_TEXT", "#CDD6F4")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        
        menu.setStyleSheet(
            f"QMenu {{ background-color: {bg}; color: {text}; border: 1px solid {border}; border-radius: 4px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px 6px 20px; border-radius: 2px; }}"
            f"QMenu::item:selected {{ background-color: {accent}; color: {bg}; }}"
        )
        
        target_box = card.get("boxes")[box_idx]
        gid = target_box.get("group_id") if hasattr(target_box, "get") else getattr(target_box, "group_id", None)
        
        is_active = False
        if isinstance(current_box_idx, int) and current_box_idx == box_idx:
            is_active = True
        elif isinstance(current_box_idx, tuple) and current_box_idx[0] == "group" and gid and current_box_idx[1] == gid:
            is_active = True
            
        if is_active:
            label_text = "💡 Edit Hint for Active Mask (Current)"
        elif gid:
            label_text = f"✏️ Edit Hint for Group '{gid}' (Mask #{box_idx + 1})"
        else:
            label_text = f"✏️ Edit Hint for Mask #{box_idx + 1}"
            
        action_edit = menu.addAction(label_text)
        action_cancel = menu.addAction("✕ Cancel")
        
        action = menu.exec_(global_pos)
        if action == action_edit:
            self._open_quick_note_editor_for_box_idx(box_idx)

    def _update_hint_tab_styles(self):
        if not hasattr(self, "_btn_hint_tab_mask") or not hasattr(self, "_btn_hint_tab_pdf"):
            return
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        accent = p.get("C_ACCENT", "#7C6AF7")
        subtext = p.get("C_SUBTEXT", "#A6ADC8")
        bg = p.get("C_BG", "#1E1E2E")
        surface = p.get("C_SURFACE", "#24283B")
        border = p.get("C_BORDER", "#45475A")
        font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        
        from PyQt5.QtGui import QColor
        color_obj = QColor(accent)
        accent_raw = f"{color_obj.red()},{color_obj.green()},{color_obj.blue()}"
        
        active_style = (
            f"QPushButton {{ background: {accent}; color: {bg if theme != 'classic' else 'white'}; border: none; border-radius: 12px; "
            f"font-family: '{font_family}'; font-weight: bold; font-size: 11px; padding: 4px 12px; }}"
        )
        inactive_style = (
            f"QPushButton {{ background: {surface}; color: {subtext}; border: 1px solid {border}; border-radius: 12px; "
            f"font-family: '{font_family}'; font-weight: bold; font-size: 11px; padding: 4px 12px; }}"
            f"QPushButton:hover {{ background: rgba({accent_raw}, 0.15); color: {accent}; border-color: {accent}; }}"
        )
        
        if getattr(self, "_hint_view_mode", "mask") == "mask":
            self._btn_hint_tab_mask.setStyleSheet(active_style)
            self._btn_hint_tab_pdf.setStyleSheet(inactive_style)
        else:
            self._btn_hint_tab_mask.setStyleSheet(inactive_style)
            self._btn_hint_tab_pdf.setStyleSheet(active_style)

    def _set_hint_view_mode(self, mode):
        self._hint_view_mode = mode
        self._update_hint_tab_styles()
        self._update_mask_note_ui(keep_visible=True)

    def _open_pdf_notes_editor(self):
        if not (0 <= self._idx < len(self._items)):
            return
            
        card, _, _ = self._items[self._idx]
        pdf_path = card.get("pdf_path")
        if not pdf_path:
            self._show_review_toast("⚠️ No PDF associated with this card!")
            return
            
        from data_manager import store
        metadata_dict = store._data.setdefault("pdf_metadata", {})
        pdf_meta = metadata_dict.get(pdf_path, {})
        
        lecture = pdf_meta.get("lecture_num", "")
        notes = pdf_meta.get("notes", "")
        
        dialog = PdfMetadataDialog(lecture, notes, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            new_lecture = dialog.inp_lecture.text().strip()
            if "<img" in dialog.inp_notes.toHtml():
                new_notes = dialog.inp_notes.toHtml()
            else:
                new_notes = dialog.inp_notes.toPlainText().strip()
                
            metadata_dict[pdf_path] = {
                "lecture_num": new_lecture,
                "notes": new_notes,
                "updated": datetime.now().isoformat()
            }
            
            store.save_force(async_save=True, force_gdrive=False)
            self._show_review_toast("💾 Saved PDF reference notes!")
            
            # Refresh UI to show the updated notes immediately
            self._update_mask_note_ui(keep_visible=True)
            
        dialog.deleteLater()

    def _open_quick_note_editor(self):
        if not (0 <= self._idx < len(self._items)):
            return
            
        card, box_idx, active_box = self._items[self._idx]
        
        current_note = ""
        if card.get("card_type") == "text":
            current_note = card.get("notes", "") or card.get("note", "")
        elif active_box is not None and active_box is not card:
            if hasattr(active_box, "get"):
                current_note = active_box.get("note", "") or active_box.get("notes", "")
            else:
                current_note = getattr(active_box, "note", "") or getattr(active_box, "notes", "")
        if not current_note:
            current_note = card.get("notes", "") or card.get("note", "")
            
        current_note = current_note or ""
        
        dialog = QuickNoteDialog(current_note, parent=self)
        accepted = (dialog.exec_() == QDialog.Accepted)
        
        # Restore ink state if it was temporarily disabled by holding Ctrl
        if getattr(self, "_was_ink_active_before_ctrl", False):
            if getattr(self, "canvas", None):
                self.canvas.ink_set_active(True)
                self._update_ink_hint()
                self._update_pen_button_states()
            self._was_ink_active_before_ctrl = False
            
        if accepted:
            if "<img" in dialog.note_edit.toHtml():
                new_note = dialog.note_edit.toHtml()
            else:
                new_note = dialog.note_edit.toPlainText().strip()
                
            if card.get("card_type") == "text":
                card["notes"] = new_note
                card["note"] = new_note
            elif active_box is not None and active_box is not card:
                if hasattr(active_box, "__setitem__"):
                    active_box["note"] = new_note
                elif hasattr(active_box, "note"):
                    active_box.note = new_note
            else:
                card["notes"] = new_note
                card["note"] = new_note
                
            if getattr(self, "canvas", None) is not None:
                if isinstance(box_idx, int) and 0 <= box_idx < len(self.canvas._boxes):
                    self.canvas._boxes[box_idx]["note"] = new_note
                elif isinstance(box_idx, tuple) and box_idx[0] == "group":
                    gid = box_idx[1]
                    for b in self.canvas._boxes:
                        if b.get("group_id") == gid:
                            b["note"] = new_note
                            
            from data_manager import store
            store.save_force(async_save=True, force_gdrive=False)
            
            self._update_mask_note_ui(keep_visible=True)
            self._set_hint_panel_visible(True)
        dialog.deleteLater()

    def _show_hint_context_menu(self, pos):
        # Create the standard context menu
        menu = self._hint_browser.createStandardContextMenu(pos)
        if not menu:
            from PyQt5.QtWidgets import QMenu
            menu = QMenu(self)
            
        # Map viewport position to document layout coordinate space (adding scroll offset)
        from PyQt5.QtCore import QPointF
        viewport = self._hint_browser.viewport()
        viewport_pos = viewport.mapFrom(self._hint_browser, pos)

        layout_pos = QPointF(
            viewport_pos.x() + self._hint_browser.horizontalScrollBar().value(),
            viewport_pos.y() + self._hint_browser.verticalScrollBar().value()
        )
        
        # Get image source using document layout
        img_src = self._hint_browser.document().documentLayout().imageAt(layout_pos)
        
        # Fallback to character format
        if not img_src:
            cursor = self._hint_browser.cursorForPosition(viewport_pos)
            char_format = cursor.charFormat()
            if not char_format.isImageFormat():
                left_cursor = self._hint_browser.cursorForPosition(viewport_pos)
                left_cursor.movePosition(left_cursor.Left)
                char_format = left_cursor.charFormat()
            if not char_format.isImageFormat():
                right_cursor = self._hint_browser.cursorForPosition(viewport_pos)
                right_cursor.movePosition(right_cursor.Right)
                char_format = right_cursor.charFormat()
            if char_format.isImageFormat():
                img_src = char_format.toImageFormat().name()
            
        if img_src:
            import urllib.parse
            img_src = urllib.parse.unquote(img_src)
            if img_src.startswith("file:///"):
                img_src_path = img_src[8:]
                if len(img_src_path) > 2 and img_src_path[0] == '/' and img_src_path[2] == ':':
                    img_src_path = img_src_path[1:]
            elif img_src.startswith("file://"):
                img_src_path = img_src[7:]
            else:
                img_src_path = img_src
                
            from storage_paths import resolve_asset_path
            import os
            abs_path = resolve_asset_path(img_src_path)
            if abs_path and os.path.exists(abs_path):
                from PyQt5.QtGui import QKeySequence
                copy_action = None
                for action in menu.actions():
                    text = action.text().replace("&", "")
                    if text == "Copy" or (action.shortcut() and action.shortcut().matches(QKeySequence.Copy)):
                        copy_action = action
                        break
                if copy_action:
                    custom_copy = menu.addAction("Copy")
                    custom_copy.setShortcut(QKeySequence.Copy)
                    
                    def do_copy(checked=False):
                        from PyQt5.QtGui import QPixmap
                        from PyQt5.QtWidgets import QApplication
                        pixmap = QPixmap(abs_path)
                        if not pixmap.isNull():
                            from PyQt5.QtCore import QMimeData, QByteArray, QBuffer, QIODevice
                            mime_data = QMimeData()
                            
                            data = QByteArray()
                            buffer = QBuffer(data)
                            buffer.open(QIODevice.WriteOnly)
                            pixmap.toImage().save(buffer, "PNG")
                            png_bytes = bytes(data)
                            
                            mime_data.setData("image/png", QByteArray(png_bytes))
                            mime_data.setImageData(pixmap.toImage())
                            
                            clipboard = QApplication.clipboard()
                            clipboard.setMimeData(mime_data)
                    custom_copy.triggered.connect(do_copy)
                    menu.insertAction(copy_action, custom_copy)
                    menu.removeAction(copy_action)

            b64_strokes = self._get_strokes_for_image_src(img_src)
            if b64_strokes:
                # Create our custom action
                restore_action = menu.addAction("✏️ Restore drawing to canvas")
                
                # Prepend it to the menu so it's at the very top
                actions = menu.actions()
                if actions:
                    menu.insertAction(actions[0], restore_action)
                    menu.insertSeparator(actions[0])
                
                # Extract filename
                filename = img_src.split('/')[-1].split('\\')[-1]
                # Connect the action
                restore_action.triggered.connect(lambda checked=False, bs=b64_strokes, fn=filename: self._restore_ink_from_b64(bs, fn))
                
        self._context_menu_active = True
        try:
            menu.exec_(self._hint_browser.mapToGlobal(pos))
        finally:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(100, lambda: setattr(self, "_context_menu_active", False))

    def _get_strokes_for_image_src(self, src):
        if not getattr(self, "_current_note_content", None) or not src:
            return None
        # Extract filename (e.g., "sketch_abc.png") from the URL/path
        filename = src.split('/')[-1].split('\\')[-1]
        if not filename:
            return None
        import re
        img_tags = re.findall(r'<img[^>]+>', self._current_note_content)
        for tag in img_tags:
            if filename in tag:
                match = re.search(r'data-strokes=["\']([^"\']+)["\']', tag)
                if match:
                    return match.group(1)
        return None

    def _restore_ink_from_b64(self, b64_strokes, filename):
        if not getattr(self, "canvas", None):
            return
            
        import base64
        import json
        from PyQt5.QtGui import QColor
        from PyQt5.QtCore import QPointF
        from ui.canvas.interaction import StrokeList
        
        try:
            serialized = base64.b64decode(b64_strokes).decode('utf-8')
            stroke_data_list = json.loads(serialized)
            
            strokes = []
            for stroke_data in stroke_data_list:
                color = QColor(stroke_data["color"])
                seq = [color]
                for pt in stroke_data["points"]:
                    seq.append(QPointF(pt["x"], pt["y"]))
                stroke = StrokeList(seq)
                stroke._implementation = stroke_data.get("implementation", "classic")
                stroke._path_key = stroke_data.get("path_key")
                strokes.append(stroke)
                
            if hasattr(self.canvas, "_push_ink_undo"):
                self.canvas._push_ink_undo()
            self.canvas._ink_strokes = strokes
            
            # Store restoration info (idx, box_idx, filename) so we can replace it when saving edits
            card, box_idx, active_box = self._items[self._idx]
            self._restored_image_info = (self._idx, box_idx, filename)
            if hasattr(self.canvas, "_ink_path_cache"):
                self.canvas._ink_path_cache = {}
            self.canvas.update()
            
            # Refresh the hint box to ensure the image is displayed correctly
            self._update_mask_note_ui(keep_visible=True)
            
            self._show_review_toast(f"✏️ Restored {len(strokes)} drawing strokes to canvas!")
        except Exception as e:
            self._show_review_toast("⚠️ Failed to restore drawing!")
            print("Error restoring ink:", e)

    def _copy_image_to_clipboard(self, img_src):
        import os
        import storage_paths
        from PyQt5.QtGui import QPixmap, QApplication
        
        image_dir = storage_paths.archive_image_dir()
        if image_dir and img_src.startswith("images/"):
            filename = img_src[len("images/"):]
            abs_path = os.path.join(image_dir, filename)
            if os.path.exists(abs_path):
                pixmap = QPixmap(abs_path)
                QApplication.clipboard().setPixmap(pixmap)

    def closeEvent(self, e):
        try:
            from services import recovery_manager
            recovery_manager.flush()
        except Exception as ex:
            print(f"[review_screen] Failed to flush recovery events: {ex}")

        # Disconnect all signals originating from this ReviewScreen
        try:
            self.disconnect()
        except Exception:
            pass

        # Disconnect child scroll area signals to prevent late-fired visible pages events during destruction
        if hasattr(self, "_canvas_scroll") and self._canvas_scroll is not None:
            try:
                self._canvas_scroll.visible_pages_changed.disconnect(
                    self._on_visible_pages_changed
                )
            except Exception:
                pass

        # Clear canvas page/pixmap cache to free QPixmap memory immediately
        if getattr(self, "canvas", None) is not None:
            try:
                self.canvas._pages = []
                self.canvas._px = None
                if hasattr(self.canvas, "_spx_cache"):
                    self.canvas._spx_cache.clear()
            except Exception:
                pass

        self._current_pixmap = None
        if hasattr(self, "_pdf_cache"):
            self._pdf_cache.clear()
        if hasattr(self, "_text_card_cache"):
            self._text_card_cache.clear()

        # Unregister from pixmap registry
        try:
            from cache_manager import PIXMAP_REGISTRY
            PIXMAP_REGISTRY.unregister(f"review_current_{id(self)}")
        except Exception:
            pass

        self._close_bg_prefetch_dialog()
        self._stop_skeleton_thread(shutdown=True)
        if (
            hasattr(self, "_pdf_loader_thread")
            and self._pdf_loader_thread
            and self._pdf_loader_thread.isRunning()
        ):
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(1000)

        # STEP 4 — stop on-demand thread on close
        self._stop_ondemand_thread(shutdown=True)

        if hasattr(self, "_pending_worker_cleanups") and self._pending_worker_cleanups:
            for t in list(self._pending_worker_cleanups):
                try:
                    if t.isRunning():
                        t.wait(2000)
                except Exception:
                    pass
            self._pending_worker_cleanups.clear()

        if hasattr(self, "_pdf_watcher") and self._pdf_watcher is not None:
            self._pdf_watcher.stop_watch()
            self._pdf_watcher.get_current_page_cb = None
            self._pdf_watcher.get_hint_cb = None

        # Stop timer and write focus time to today's journal
        if self._stimer:
            self._stimer.stop()
            self._stimer.flush_to_journal()

        # Timers cleanup
        for attr in ("_queue_auto_hide_timer", "_ui_idle_timer", "_prog_timer", "_floating_timer_sync_timer"):
            if hasattr(self, attr):
                t = getattr(self, attr)
                if t is not None:
                    try:
                        t.stop()
                        t.disconnect()
                    except Exception:
                        pass
                    setattr(self, attr, None)

        # Threads signals cleanup
        for attr in ("_pdf_loader_thread", "_ondemand_thread", "_skeleton_thread"):
            if hasattr(self, attr):
                t = getattr(self, attr)
                if t is not None:
                    try:
                        t.disconnect()
                    except Exception:
                        pass
                    setattr(self, attr, None)

        # Break reference cycles in managers and controllers
        if hasattr(self, "mgr") and self.mgr is not None:
            try:
                self.mgr.rs = None
            except Exception:
                pass
            self.mgr = None

        if self._stimer is not None:
            try:
                self._stimer._activity_parent = None
                if hasattr(self._stimer, "_activity_filter") and self._stimer._activity_filter is not None:
                    self._stimer._activity_filter._timer = None
            except Exception:
                pass
            self._stimer = None

        if hasattr(self, "_pdf_viewer") and self._pdf_viewer is not None:
            try:
                self._pdf_viewer.canvas = None
                self._pdf_viewer.scroll_area = None
                self._pdf_viewer.page_input = None
                self._pdf_viewer.page_total_label = None
                self._pdf_viewer.prev_button = None
                self._pdf_viewer.next_button = None
                self._pdf_viewer.total_pages_getter = None
                self._pdf_viewer.debug_hook = None
            except Exception:
                pass
            self._pdf_viewer = None

        super().closeEvent(e)

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (
            QEvent.MouseMove,
            QEvent.HoverMove,
            QEvent.Wheel,
            QEvent.KeyPress,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
        ):
            self._note_user_activity()
            
        # Tap outside the floating hint panel to hide it
        if et == QEvent.MouseButtonPress:
            if getattr(self, "_context_menu_active", False):
                return super().eventFilter(obj, event)
            if hasattr(self, "_hint_panel") and self._hint_panel.isVisible():
                from PyQt5.QtCore import QRect
                global_top_left = self._hint_panel.mapToGlobal(self._hint_panel.rect().topLeft())
                global_rect = QRect(global_top_left, self._hint_panel.size())
                if global_rect.contains(event.globalPos()):
                    # Click was inside the hint panel (including child widgets/images), ignore it
                    return super().eventFilter(obj, event)
                if obj in (self.canvas, self._canvas_scroll.viewport(), self):
                    self._set_hint_panel_visible(False)
                    
        if et in (QEvent.MouseMove, QEvent.HoverMove):
            self._maybe_show_queue_edge_handle(event, source=obj)
            self._update_queue_auto_hide_from_event(event)
        elif et in (QEvent.Enter, QEvent.Leave):
            self._update_queue_auto_hide_from_event(event)
        return super().eventFilter(obj, event)

    def _note_user_activity(self):
        if self._ui_idle_timer is not None:
            self._ui_idle_timer.start()
        if self._stimer:
            self._stimer.note_activity()

    def _on_ui_idle_timeout(self):
        self._flush_pending_background_inserts()
        bg_state = self._background_fill_state
        if not bg_state:
            return
        if self._pending_visible_request:
            return
        if self._ondemand_thread and self._ondemand_thread.isRunning():
            return
        bg_path, bg_already_rendered, bg_total = bg_state
        if getattr(self, "_canvas_pdf_path", None) != bg_path:
            self._background_fill_state = None
            self._bg_remaining = None
            return
        self._start_background_fill(bg_path, bg_already_rendered, bg_total)

    def _on_pdf_reload_requested(self, path, current_page, target_page):
        key = os.path.abspath(path) if path else ""
        suppress_until = float(
            getattr(self, "_suppress_pdf_reload_until", {}).get(key, 0.0) or 0.0
        )
        if suppress_until and time.monotonic() <= suppress_until:
            return
        self._pending_reload_page = target_page
        self._reload_current_canvas()

    def _on_pdf_file_changed(self, path: str):
        if not path:
            return
        self.canvas._show_toast("PDF changed on disk — refreshing…")

    def _toggle_chrome(self):
        """Right-click on canvas — show/hide header and hint bars."""
        visible = self._hdr_widget.isVisible()
        self._hdr_widget.setVisible(not visible)
        self._hint_label.setVisible(not visible)

    def _show_overlay(self, overlay):
        """Show a floating overlay and reposition it."""
        self._reposition_overlays()
        overlay.show()
        overlay.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition_overlays()
        self._reposition_queue_edge_handle()
        self._reposition_queue_overlay()
        self._reposition_floating_timer()
        self._reposition_hint_panel()
        if getattr(self, "_floating_hint_button", None) is not None:
            self._floating_hint_button.raise_()
        
        # Synchronize retro overlays
        if getattr(self, "crt", None) is not None:
            self.crt.setGeometry(self.rect())
            self.crt.raise_()
        if getattr(self, "burst", None) is not None:
            self.burst.setGeometry(self.rect())
            self.burst.raise_()
            if self.crt is not None:
                self.crt.raise_()

    def _reposition_overlays(self):
        """Pin overlays to bottom-center of canvas stage area."""
        ref = self._canvas_stage
        w = ref.width()
        h = ref.height()

        # Rating frame — flush to bottom
        self._rating_frame.adjustSize()
        sh = self._rating_frame.sizeHint()
        rw = max(sh.width(), 10)
        rh = max(sh.height(), 48)
        self._rating_frame.setGeometry((w - rw) // 2, h - rh - 2, rw, rh)

        # Reveal bar — just above where rating would be
        self._reveal_bar.adjustSize()
        sh2 = self._reveal_bar.sizeHint()
        bw = max(sh2.width(), 10)
        bh = max(sh2.height(), 44)
        self._reveal_bar.setGeometry((w - bw) // 2, h - bh - 2, bw, bh)

    def _load_queue_locked(self) -> bool:
        raw = QSettings("AnkiOcclusion", "App").value("review/queue_locked", True)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in {"0", "false", "no", "off"}

    def _save_queue_locked(self):
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/queue_locked", bool(self._queue_locked))
        settings.sync()

    def _set_queue_locked(self, locked: bool):
        self._queue_locked = bool(locked)
        self._queue_drawer_open = True if self._queue_locked else False
        self._save_queue_locked()
        self._apply_queue_drawer_state()

    def _toggle_queue_lock(self):
        self._set_queue_locked(not bool(self.__dict__.get("_queue_locked", True)))

    def _open_queue_drawer(self):
        self._queue_drawer_open = True
        self._cancel_queue_auto_hide()
        self._apply_queue_drawer_state()

    def _toggle_queue_drawer(self):
        if self.__dict__.get("_queue_locked", True):
            return
        self._queue_drawer_open = not bool(
            self.__dict__.get("_queue_drawer_open", True)
        )
        self._cancel_queue_auto_hide()
        self._apply_queue_drawer_state()

    def _hide_queue_drawer(self):
        if self.__dict__.get("_queue_locked", True):
            return
        self._queue_drawer_open = False
        self._cancel_queue_auto_hide()
        self._apply_queue_drawer_state()

    def _apply_queue_drawer_state(self, recenter: bool = True):
        from ui.review.queue_panel import apply_queue_drawer_state
        apply_queue_drawer_state(self, recenter)

    def _set_queue_panel_docked(self, docked: bool):
        from ui.review.queue_panel import set_queue_panel_docked
        set_queue_panel_docked(self, docked)

    def _reposition_queue_overlay(self):
        from ui.review.queue_panel import reposition_queue_overlay
        reposition_queue_overlay(self)

    def _sync_floating_timer(self):
        if not self.__dict__.get("_stimer"):
            return
        session_label = self.__dict__.get("_floating_timer_session")
        today_label = self.__dict__.get("_floating_timer_today")
        mask_label = self.__dict__.get("_floating_timer_mask")
        if session_label is not None:
            session_label.setText(self._stimer.label_session.text())
        if today_label is not None:
            today_label.setText(self._stimer.label_today.text())
        if mask_label is not None:
            mask_label.setText(self._stimer.label_mask.text())
        count = self._active_queue_count()
        self._sync_floating_queue_count(total=count)
        self._sync_queue_timer_count(total=count)
        self._reposition_floating_timer()

    def _set_floating_timer_sync_enabled(self, enabled: bool):
        timer = self.__dict__.get("_floating_timer_sync_timer")
        if timer is None:
            return
        enabled = bool(enabled)
        if enabled:
            if not timer.isActive():
                timer.start()
            return
        if timer.isActive():
            timer.stop()

    def _keep_floating_timer_on_top(self):
        frame = self.__dict__.get("_floating_timer_frame")
        if frame is None or frame.isHidden():
            return
        now = time.perf_counter()
        last = float(self.__dict__.get("_floating_timer_last_reposition_ts", 0.0) or 0.0)
        min_interval = float(self.FLOATING_TIMER_REPOSITION_MIN_MS) / 1000.0
        if now - last >= min_interval:
            self._flush_floating_timer_reposition()
            return
        if self.__dict__.get("_floating_timer_reposition_pending", False):
            return
        self._floating_timer_reposition_pending = True
        delay_ms = max(0, int(round((min_interval - (now - last)) * 1000)))
        QTimer.singleShot(delay_ms, self._flush_floating_timer_reposition)

    def _flush_floating_timer_reposition(self):
        self._floating_timer_reposition_pending = False
        frame = self.__dict__.get("_floating_timer_frame")
        if frame is None or frame.isHidden():
            return
        self._reposition_floating_timer()
        self._floating_timer_last_reposition_ts = time.perf_counter()

    def _reposition_floating_timer(self):
        frame = self.__dict__.get("_floating_timer_frame")
        canvas_stage = self.__dict__.get("_canvas_stage")
        if frame is None or canvas_stage is None:
            return
        frame.adjustSize()
        x_pct = self.__dict__.get("_timer_x_pct", 1.0)
        y_pct = self.__dict__.get("_timer_y_pct", 0.0)

        frame_w = frame.width()
        frame_h = frame.height()
        stage_w = canvas_stage.width()
        stage_h = canvas_stage.height()

        x = int(x_pct * (stage_w - frame_w))
        y = int(y_pct * (stage_h - frame_h))

        margin = 10
        x = max(margin, min(x, stage_w - frame_w - margin))
        y = max(margin, min(y, stage_h - frame_h - margin))

        frame.move(x, y)
        frame.raise_()

    def _save_floating_timer_position(self, x, y):
        frame = self.__dict__.get("_floating_timer_frame")
        canvas_stage = self.__dict__.get("_canvas_stage")
        if frame is None or canvas_stage is None:
            return
        max_x = canvas_stage.width() - frame.width()
        max_y = canvas_stage.height() - frame.height()

        x_pct = x / max_x if max_x > 0 else 0.0
        y_pct = y / max_y if max_y > 0 else 0.0

        x_pct = max(0.0, min(x_pct, 1.0))
        y_pct = max(0.0, min(y_pct, 1.0))

        self._timer_x_pct = x_pct
        self._timer_y_pct = y_pct

        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/timer_x_pct", float(x_pct))
        settings.setValue("review/timer_y_pct", float(y_pct))

    def _finish_initial_overlay_placement(self):
        self._review_overlays_ready = True
        self._apply_queue_drawer_state(recenter=False)
        self._reposition_queue_edge_handle()
        self._keep_floating_timer_on_top()

    def _update_floating_timer_visibility(self):
        frame = self.__dict__.get("_floating_timer_frame")
        if frame is None:
            return
        if not self.__dict__.get("_review_overlays_ready", True):
            self._floating_timer_visible = False
            frame.hide()
            self._set_floating_timer_sync_enabled(False)
            return
        if self.__dict__.get("_user_timer_hidden", False):
            self._floating_timer_visible = False
            frame.hide()
            self._set_floating_timer_sync_enabled(False)
            return
        locked = bool(self.__dict__.get("_queue_locked", True))
        open_now = locked or bool(self.__dict__.get("_queue_drawer_open", True))
        show_float = bool(self.__dict__.get("_stimer")) and not open_now
        if show_float:
            self._sync_floating_timer()
            self._floating_timer_visible = True
            frame.show()
            frame.raise_()
            self._set_floating_timer_sync_enabled(True)
        else:
            self._floating_timer_visible = False
            frame.hide()
            self._set_floating_timer_sync_enabled(False)

    def _toggle_floating_timer_visibility(self):
        frame = self.__dict__.get("_floating_timer_frame")
        if frame is None:
            return
        self._user_timer_hidden = not self.__dict__.get("_user_timer_hidden", False)
        if self._user_timer_hidden:
            frame.hide()
            self._set_floating_timer_sync_enabled(False)
            self.canvas._show_toast("⏱ Timer Hidden (Press Alt+T to show)")
        else:
            self._update_floating_timer_visibility()
            if self.__dict__.get("_floating_timer_visible", False):
                self.canvas._show_toast("⏱ Timer Visible")

    def _reposition_queue_edge_handle(self):
        from ui.review.queue_panel import reposition_queue_edge_handle
        reposition_queue_edge_handle(self)

    def _event_pos_in_self(self, event, source=None):
        from ui.review.queue_panel import event_pos_in_self
        return event_pos_in_self(self, event, source)

    def _queue_edge_handle_hot(self, pos) -> bool:
        from ui.review.queue_panel import queue_edge_handle_hot
        return queue_edge_handle_hot(self, pos)

    def _hide_queue_edge_handle(self, reason: str = "left_edge"):
        from ui.review.queue_panel import hide_queue_edge_handle
        hide_queue_edge_handle(self, reason)

    def _maybe_show_queue_edge_handle(self, event, source=None):
        from ui.review.queue_panel import maybe_show_queue_edge_handle
        maybe_show_queue_edge_handle(self, event, source)

    def _event_global_pos(self, event):
        from ui.review.queue_panel import event_global_pos
        return event_global_pos(self, event)

    def _queue_contains_global_pos(self, global_pos) -> bool:
        from ui.review.queue_panel import queue_contains_global_pos
        return queue_contains_global_pos(self, global_pos)

    def _cancel_queue_auto_hide(self):
        from ui.review.queue_panel import cancel_queue_auto_hide
        cancel_queue_auto_hide(self)

    def _schedule_queue_auto_hide(self):
        from ui.review.queue_panel import schedule_queue_auto_hide
        schedule_queue_auto_hide(self)

    def _update_queue_auto_hide_from_event(self, event):
        from ui.review.queue_panel import update_queue_auto_hide_from_event
        update_queue_auto_hide_from_event(self, event)

    def _hide_queue_drawer_after_delay(self):
        from ui.review.queue_panel import hide_queue_drawer_after_delay
        hide_queue_drawer_after_delay(self)

    def _load_item(self):
        load_t0 = time.perf_counter()
        if self._idx < 0 or self._idx >= len(self._items):
            self._finish()
            return
        # [O(1) FIX] Skip tombstoned (deleted) boxes
        while 0 <= self._idx < len(self._items):
            _, b, _ = self._items[self._idx]
            bid = b[1] if isinstance(b, tuple) else (b if isinstance(b, str) else "")
            if bid and bid in self._deleted_ids:
                self._idx += 1
            else:
                break

        if self._idx < 0 or self._idx >= len(self._items):
            self._finish()
            return

        card, box_idx, sm2_obj = self._items[self._idx]
        if hasattr(self.parent(), "save_last_review_session") and self._items:
            self.parent().save_last_review_session([item[0] for item in self._items], self._idx)
        self._hint_scroll_positions.clear()
        self._last_rendered_hint_key = None
        self._hint_view_mode = "mask"
        self._update_hint_tab_styles()
        has_pdf = bool(card.get("pdf_path"))
        if hasattr(self, "_btn_pdf_note"):
            self._btn_pdf_note.setEnabled(has_pdf)
        item_title = card.get("title", "Untitled")
        if self._stimer:
            self._stimer.set_current_pdf(card.get("pdf_path", ""))
            deck = self._find_card_deck(card)
            deck_name = deck.get("name", "") if isinstance(deck, dict) else ""
            if hasattr(self._stimer, "set_current_deck"):
                self._stimer.set_current_deck(deck_name)
            card_id = str(card.get("_id") or card.get("id") or id(card))
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                mask_key = f"{card_id}_grp_{box_idx[1]}"
            elif isinstance(box_idx, int):
                box = card.get("boxes", [])[box_idx] if (0 <= box_idx < len(card.get("boxes", []))) else sm2_obj
                box_id = box.get("box_id") if isinstance(box, dict) else f"box_{box_idx}"
                mask_key = f"{card_id}_{box_id}"
            else:
                mask_key = f"{card_id}_card"
            self._stimer.set_current_mask(mask_key)
        if hasattr(self.canvas, "clear_review_ink_for_card_switch"):
            self.canvas.clear_review_ink_for_card_switch()
        self._last_saved_ink_strokes_key = None
        self._sync_queue_state()  # state-only fast path for normal card advances

        # UI updates...
        self.prog.setMaximum(len(self._items))
        self.prog.setValue(self._idx)
        self.lbl_prog.setText(f"Card {self._idx + 1}/{len(self._items)}")
        self.lbl_sm2.setText(sm2_badge(sm2_obj))
        self.lbl_title.setText(card.get("title", "Untitled"))
        # ── update filename label in header ────────────────────────────────
        _fn = os.path.basename(card.get("pdf_path", "") or card.get("image_path", "") or "")
        if hasattr(self, "lbl_filename"):
            self.lbl_filename.setText(_fn if _fn else "")

        # 🚀 SM-2 SIMULATION UPDATE
        previews = _fmt_due_interval(sm2_obj)
        for (btn, q), (orig_lbl, _, _), color_lbl in zip(
            self._prev_lbls, self.RATINGS, self.RATING_LABELS
        ):
            val = previews.get(q, "?")
            # orig_lbl e.g. "1  🔁 Again" → parts[0]="1", parts[1]="🔁"
            parts = orig_lbl.split()
            icon = parts[1] if len(parts) > 1 else ""
            btn.setText(f"{parts[0]} {icon}  {val}  {color_lbl}")

        is_mcq = card.get("card_type") in ("mcq", "testbook_mcq") or (isinstance(card.get("options"), list) and len(card.get("options", [])) > 0)
        if is_mcq:
            self._stacked_widget.setCurrentIndex(2)
            self._mcq_review_widget.load_card(card)
            
            # Disable page nav/contrast/jump/annotate but keep pen buttons enabled
            self._btn_prev_page.setEnabled(False)
            self._btn_next_page.setEnabled(False)
            self._page_jump.setEnabled(False)
            self._btn_invert_pdf.setEnabled(False)
            if hasattr(self, "_btn_annot") and self._btn_annot is not None:
                self._btn_annot.setEnabled(False)
            self._btn_toggle_pen.setEnabled(True)
            self._btn_pen_color.setEnabled(True)
            self._btn_pen_clear.setEnabled(True)
            
            self._rating_frame.hide()
            QTimer.singleShot(50, lambda: self._show_overlay(self._reveal_bar))
            self._maybe_auto_reveal()
            self._mcq_review_widget.setFocus()
            
            self._update_mask_note_ui()
            self._update_pen_button_states()
            
            self._review_profile_log(
                "item_loaded",
                idx=f"{self._idx + 1}/{len(self._items)}",
                same_pdf=False,
                title=item_title,
                box_ref=box_idx,
                elapsed=f"{(time.perf_counter() - load_t0) * 1000:.1f}ms",
            )
            return

        if card.get("card_type") == "text":
            self._stacked_widget.setCurrentIndex(0)
            px = self._render_text_card_to_pixmap(card, is_revealed=False)
            self.canvas.load_pixmap(px)
            self.canvas.set_boxes_with_state([])
            self.canvas.set_target_box(-1)
            self.canvas.set_mode("review")
            
            # Disable page nav/contrast/jump/annotate but keep pen buttons enabled
            self._btn_prev_page.setEnabled(False)
            self._btn_next_page.setEnabled(False)
            self._page_jump.setEnabled(False)
            self._btn_invert_pdf.setEnabled(False)
            if hasattr(self, "_btn_annot") and self._btn_annot is not None:
                self._btn_annot.setEnabled(False)
            self._btn_toggle_pen.setEnabled(True)
            self._btn_pen_color.setEnabled(True)
            self._btn_pen_clear.setEnabled(True)
            
            self._rating_frame.hide()
            QTimer.singleShot(50, lambda: self._show_overlay(self._reveal_bar))
            self._maybe_auto_reveal()
            
            # Apply user-customized zoom if previously adjusted, otherwise fit
            if self._user_zoom_scale is not None:
                self.canvas._scale = self._user_zoom_scale
                self.canvas._on_zoom()
            else:
                QTimer.singleShot(0, self._zoom_fit)
            self.canvas.setFocus()
            
            self._update_mask_note_ui()
            self._update_pen_button_states()
            
            self._review_profile_log(
                "item_loaded",
                idx=f"{self._idx + 1}/{len(self._items)}",
                same_pdf=False,
                title=item_title,
                box_ref=box_idx,
                elapsed=f"{(time.perf_counter() - load_t0) * 1000:.1f}ms",
            )
            return
        else:
            self._stacked_widget.setCurrentIndex(0)
            self._btn_prev_page.setEnabled(True)
            self._btn_next_page.setEnabled(True)
            self._page_jump.setEnabled(True)
            self._btn_invert_pdf.setEnabled(True)
            if hasattr(self, "_btn_annot") and self._btn_annot is not None:
                self._btn_annot.setEnabled(True)
            self._btn_toggle_pen.setEnabled(True)
            self._btn_pen_color.setEnabled(True)
            self._btn_pen_clear.setEnabled(True)

        current_path = getattr(self.canvas, "_current_pdf_path", "") or getattr(
            self, "_canvas_pdf_path", ""
        )
        new_path = resolve_asset_path(card.get("pdf_path", ""))
        same_pdf = bool(
            current_path
            and new_path
            and os.path.abspath(current_path) == os.path.abspath(new_path)
        )

        if same_pdf and getattr(self.canvas, "_pages", None):
            self._canvas_pdf_path = new_path
            self.canvas._current_pdf_path = new_path
            if hasattr(self.canvas, "clear_peek_target"):
                self.canvas.clear_peek_target()
            boxes = card.get("boxes", [])
            if new_path and boxes:
                source_box_zoom = card.get("_pdf_box_render_zoom")
                if source_box_zoom is None:
                    source_box_zoom = PDF_LEGACY_BOX_ZOOM
                boxes = self._adapt_review_boxes(card, new_path)
                self._pdf_quality_debug(
                    "same_pdf_box_remap",
                    source_zoom=source_box_zoom,
                    target_zoom=self._pdf_render_zoom,
                    boxes=len(boxes),
                    review_idx=self._idx,
                )
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                gid = box_idx[1]
                display_boxes = [{**b, "revealed": False} for b in boxes]
                self.canvas.set_boxes_with_state(display_boxes)
                self.canvas.set_target_box(-1)
                self.canvas.set_mode("review")
                self.canvas.set_target_group(gid)
            elif box_idx is None:
                self.canvas.set_boxes_with_state(
                    [{**b, "revealed": False} for b in boxes]
                )
                self.canvas.set_target_box(-1)
                self.canvas.set_mode("review")
            else:
                display_boxes = [{**b, "revealed": False} for b in boxes]
                self.canvas.set_boxes_with_state(display_boxes)
                self.canvas.set_target_box(box_idx if isinstance(box_idx, int) else -1)
                self.canvas.set_mode("review")

            # FIX: retain user-set zoom on same-PDF card switch too
            def _same_pdf_zoom_center():
                if self._user_zoom_scale is not None:
                    self.canvas._scale = self._user_zoom_scale
                    self.canvas._on_zoom()
                self._center_on_target()
                self._update_review_page_nav_ui()

            QTimer.singleShot(0, _same_pdf_zoom_center)
            self._maybe_auto_reveal()
        else:
            self._reload_current_canvas()

        self._review_profile_log(
            "item_loaded",
            idx=f"{self._idx + 1}/{len(self._items)}",
            same_pdf=same_pdf,
            title=item_title,
            box_ref=box_idx,
            elapsed=f"{(time.perf_counter() - load_t0) * 1000:.1f}ms",
        )
        if same_pdf:
            self._update_mask_note_ui()
        self._update_pen_button_states()

        self.canvas.setFocus()  # यह पक्का करेगा कि Keyboard Commands सीधे Canvas पकड़ें
        self._rating_frame.hide()  # ← rating frame explicitly hide karo
        QTimer.singleShot(50, lambda: self._show_overlay(self._reveal_bar))
        self._maybe_auto_reveal()

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()

        # Ctrl+? toggle to open shortcuts dialog
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        is_ctrl_question = (
            (clean_mods & Qt.ControlModifier) and
            not (clean_mods & Qt.AltModifier) and
            not (clean_mods & Qt.MetaModifier) and
            (key == Qt.Key_Question or (key == Qt.Key_Slash and (clean_mods & Qt.ShiftModifier)))
        )
        if is_ctrl_question:
            from ui.shortcut_dialog import ShortcutSettingsDialog
            dlg = ShortcutSettingsDialog(self)
            dlg.exec_()
            e.accept()
            return

        if (
            getattr(self, "canvas", None) is not None
            and getattr(self.canvas, "_mode", "") == "edit"
        ):
            if mods & Qt.ControlModifier and key == Qt.Key_A:
                if mods & Qt.AltModifier:
                    self.canvas.select_all_on_pdf()
                elif mods & Qt.ShiftModifier:
                    self.canvas.select_all_in_view()
                else:
                    self.canvas.select_visible_only()
        if hasattr(self, "_stacked_widget") and self._stacked_widget.currentIndex() == 2:
            if not self._rating_frame.isVisible() and hasattr(self, "_mcq_review_widget"):
                key_map = {
                    Qt.Key_A: "A", Qt.Key_B: "B", Qt.Key_C: "C", Qt.Key_D: "D",
                    Qt.Key_1: "A", Qt.Key_2: "B", Qt.Key_3: "C", Qt.Key_4: "D"
                }
                if key in key_map:
                    self._mcq_review_widget.select_option(key_map[key])
                    e.accept()
                    return

        if shortcut_manager.event_matches(e, "review.fullscreen"):
            win = self.window()
            if win.isFullScreen():
                win.showMaximized()
                self._set_fullscreen_ui(False)
            else:
                win.showFullScreen()
                self._set_fullscreen_ui(True)
        elif shortcut_manager.event_matches(e, "review.cancel"):
            self.cancelled.emit()
        elif shortcut_manager.event_matches(e, "review.reveal"):
            if self._rating_frame.isVisible():
                # Already revealed — hide karo (toggle back)
                self._rating_frame.hide()
                self._show_overlay(self._reveal_bar)
                card = self._items[self._idx][0] if 0 <= self._idx < len(self._items) else None
                if card and card.get("card_type") == "text":
                    px = self._render_text_card_to_pixmap(card, is_revealed=False)
                    self.canvas._px = px
                    self.canvas._spx_cache.clear()
                    if self._user_zoom_scale is not None:
                        self.canvas._scale = self._user_zoom_scale
                        self.canvas._on_zoom()
                    else:
                        self._zoom_fit()
                    self.canvas.update()
                else:
                    for b in self.canvas._boxes:
                        b["revealed"] = False
                    self.canvas._redraw()
            else:
                self._reveal_current()
        elif self._rating_frame.isVisible() and self._rating_quality_for_event(e) is not None:
            self._rate(self._rating_quality_for_event(e))
        elif shortcut_manager.event_matches(e, "review.zoom_in"):
            self.canvas.zoom_in()
            self._user_zoom_scale = self.canvas._scale
        elif shortcut_manager.event_matches(e, "review.zoom_out"):
            self.canvas.zoom_out()
            self._user_zoom_scale = self.canvas._scale
        elif shortcut_manager.event_matches(e, "review.zoom_reset"):
            self._zoom_fit()
            self._user_zoom_scale = None  # reset to auto-fit
        elif shortcut_manager.event_matches(e, "review.resize_fit"):
            self._zoom_fit()
            self._center_on_target()
            self._user_zoom_scale = self.canvas._scale
        elif shortcut_manager.event_matches(e, "review.center"):
            is_text = False
            try:
                if hasattr(self, "mgr") and self.mgr is not None:
                    if self._items and self._idx < len(self._items):
                        card = self._items[self._idx][0]
                        is_text = (card.get("card_type") == "text") if card else False
            except RuntimeError:
                pass
            if not is_text:
                self._trigger_center_fit()
        elif shortcut_manager.event_matches(e, "review.undo"):
            self._review_undo()
        elif shortcut_manager.event_matches(e, "review.redo"):
            self._review_redo()
        elif shortcut_manager.event_matches(e, "review.skip_session"):
            self._skip_session()
        elif shortcut_manager.event_matches(e, "review.super_skip"):
            self._super_skip()
        elif shortcut_manager.event_matches(e, "review.open_pdf"):
            self._open_current_pdf_in_reader()
        elif shortcut_manager.event_matches(e, "review.open_folder"):
            self._reveal_current_pdf_in_folder()
        elif shortcut_manager.event_matches(e, "review.copy_pdf") and not e.isAutoRepeat():
            self._copy_current_pdf_file_to_clipboard()
        elif shortcut_manager.event_matches(e, "review.annotate") and not e.isAutoRepeat():
            self._open_annotation_beta()
        elif shortcut_manager.event_matches(e, "review.edit_card"):
            self._edit_current_card()
        elif shortcut_manager.event_matches(e, "review.delete_card") and not e.isAutoRepeat():
            self._delete_current_card()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.browse_cards") and not e.isAutoRepeat():
            self._open_card_browser()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.prev_page") and not e.isAutoRepeat():
            self._go_prev_review_page()
        elif shortcut_manager.event_matches(e, "review.next_page") and not e.isAutoRepeat():
            self._go_next_review_page()
        elif shortcut_manager.event_matches(e, "review.pdf_contrast") and not e.isAutoRepeat():
            self._toggle_pdf_contrast()
        elif shortcut_manager.event_matches(e, "review.toggle_focus") and not e.isAutoRepeat():
            self._toggle_focus_mode()
        elif shortcut_manager.event_matches(e, "review.toggle_ultra_focus") and not e.isAutoRepeat():
            self._toggle_ultra_focus_mode()
        elif shortcut_manager.event_matches(e, "review.toggle_timer") and not e.isAutoRepeat():
            self._toggle_floating_timer_visibility()
        elif shortcut_manager.event_matches(e, "review.toggle_note") and not e.isAutoRepeat():
            self._toggle_hint_panel()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.toggle_pdf_notes") and not e.isAutoRepeat():
            self._toggle_pdf_notes()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.quick_note") and not e.isAutoRepeat():
            self._open_quick_note_editor()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.save_ink_clear") and not e.isAutoRepeat():
            self._save_review_ink_to_note(clear_ink=True)
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.save_ink_keep") and not e.isAutoRepeat():
            self._save_review_ink_to_note(clear_ink=False)
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.eraser_toggle") and not e.isAutoRepeat():
            self.canvas.ink_set_active(True)
            self.canvas.ink_set_mode("eraser")
            self._update_ink_hint()
            self._update_pen_button_states()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.pen_eraser_toggle") and not e.isAutoRepeat():
            if not getattr(self.canvas, "_ink_active", False):
                self.canvas.ink_set_active(True)
                self.canvas.ink_set_mode("pen")
            else:
                current_mode = self.canvas.ink_get_mode()
                new_mode = "eraser" if current_mode == "pen" else "pen"
                self.canvas.ink_set_mode(new_mode)
            self._update_ink_hint()
            self._update_pen_button_states()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.pen_toggle") and not e.isAutoRepeat():
            self.canvas.ink_set_active(True)
            self.canvas.ink_set_mode("pen")
            active = self.canvas._ink_active
            color = self.canvas._ink_colors[self.canvas._ink_color_idx]
            self.canvas._show_toast(
                f"✏ Pen {'ON' if active and self.canvas.ink_get_mode() == 'pen' else 'OFF'}  {color if active and self.canvas.ink_get_mode() == 'pen' else ''}"
            )
            self._update_ink_hint()
            self._update_pen_button_states()
            e.accept()
            return
        elif shortcut_manager.event_matches(e, "review.pen_mouse_toggle") and not e.isAutoRepeat():
            self.canvas.ink_toggle()
            active = self.canvas._ink_active
            color = self.canvas._ink_colors[self.canvas._ink_color_idx]
            self.canvas._show_toast(
                f"✏ Pen {'ON' if active else 'OFF'}  {color if active else ''}"
            )
            self._update_ink_hint()
            self._update_pen_button_states()
            e.accept()
            return
        elif (
            key in (Qt.Key_Equal, Qt.Key_Plus)
            and not (mods & Qt.ControlModifier)
        ):
            if getattr(self.canvas, "_ink_active", False):
                self.canvas.ink_adjust_width(0.4)
                self._capture_review_ink_width("width_plus")
            elif getattr(self.canvas, "_focus_mode", False) is True:
                self._adjust_focus_opacity(-0.05)
        elif (
            key == Qt.Key_Minus
            and not (mods & Qt.ControlModifier)
        ):
            if getattr(self.canvas, "_ink_active", False):
                self.canvas.ink_adjust_width(-0.4)
                self._capture_review_ink_width("width_minus")
            elif getattr(self.canvas, "_focus_mode", False) is True:
                self._adjust_focus_opacity(0.05)
        elif shortcut_manager.event_matches(e, "review.pen_color") and not e.isAutoRepeat():
            if self.canvas._ink_active:
                if bool(mods & Qt.ShiftModifier):
                    self._choose_pen_color_picker()
                else:
                    self.canvas.ink_cycle_color()
                    self._review_ink_color_idx = int(self.canvas._ink_color_idx)
                    self._save_review_ink_color()
                    self._update_pen_button_states()
        elif shortcut_manager.event_matches(e, "review.pen_clear") and not e.isAutoRepeat():
            self.canvas.ink_clear()
        elif (mods & Qt.ControlModifier and key == Qt.Key_C):
            self._copy_current_card_text()
            e.accept()
            return
        elif key == Qt.Key_Control and not e.isAutoRepeat():
            if getattr(self, "canvas", None) and getattr(self.canvas, "_ink_active", False):
                self._was_ink_active_before_ctrl = True
                self.canvas.ink_set_active(False)
                self._update_ink_hint()
        elif key == Qt.Key_D and not e.isAutoRepeat():
            self._debug_report("D key (manual)")
        else:
            super().keyPressEvent(e)

    def _copy_current_card_text(self):
        if not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, _ = self._items[self._idx]
        if not card:
            return
        
        q = card.get("question", "").strip()
        a = card.get("answer", "").strip()
        
        # If card is revealed, copy "Front — Back", else copy "Front"
        is_revealed = self._rating_frame.isVisible()
        if card.get("card_type") == "text":
            if is_revealed and a:
                text_to_copy = f"{q} — {a}" if q else a
            else:
                text_to_copy = q if q else a
        else:
            text_to_copy = card.get("title", "") or card.get("name", "")
            
        if text_to_copy:
            clipboard = QApplication.clipboard()
            clipboard.setText(text_to_copy)
            snippet = (text_to_copy[:50] + "...") if len(text_to_copy) > 50 else text_to_copy
            if hasattr(self.canvas, "_show_toast"):
                self.canvas._show_toast(f"📋 Copied: {snippet}")

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Control and not e.isAutoRepeat():
            if getattr(self, "_was_ink_active_before_ctrl", False):
                if getattr(self, "canvas", None):
                    self.canvas.ink_set_active(True)
                    self._update_ink_hint()
                self._was_ink_active_before_ctrl = False
        super().keyReleaseEvent(e)

    def _rating_quality_for_event(self, event):
        for action_id, quality in self.RATING_SHORTCUT_ACTIONS:
            if shortcut_manager.event_matches(event, action_id):
                return quality
        return None

    def _reveal_current(self):
        if not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, _ = self._items[self._idx]

        if hasattr(self, "_stacked_widget") and self._stacked_widget.currentIndex() == 2:
            if hasattr(self, "_mcq_review_widget"):
                self._mcq_review_widget.reveal_answer()
            if getattr(self, "burst", None) is not None:
                self.burst.spawn_burst(self.rect().center().x(), self.rect().center().y(), "cyan", count=25)
            self._reveal_bar.hide()
            self._show_overlay(self._rating_frame)
            if hasattr(self, "_mcq_review_widget"):
                self._mcq_review_widget.setFocus()
            return

        if card.get("card_type") == "text":
            px = self._render_text_card_to_pixmap(card, is_revealed=True)
            self.canvas._px = px
            self.canvas._spx_cache.clear()
            if self._user_zoom_scale is not None:
                self.canvas._scale = self._user_zoom_scale
                self.canvas._on_zoom()
            else:
                self._zoom_fit()
            self.canvas.update()
            self.setFocus()
        elif box_idx is None:
            self.canvas.reveal_all()
        elif isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            for b in self.canvas._boxes:
                if b.get("group_id", "") == gid:
                    b["revealed"] = True
            self.canvas._redraw()
        else:
            if 0 <= box_idx < len(self.canvas._boxes):
                self.canvas._boxes[box_idx]["revealed"] = True
                self.canvas._redraw()
                
        # Spawn retro burst
        if getattr(self, "burst", None) is not None:
            self.burst.spawn_burst(self.rect().center().x(), self.rect().center().y(), "cyan", count=25)
            
        self._reveal_bar.hide()
        self._show_overlay(self._rating_frame)

        # Note drawer auto-reveal on Space (reveal answer) has been disabled per user request.
        pass

    def _on_mcq_answer_submitted(self):
        self._reveal_bar.hide()
        self._show_overlay(self._rating_frame)

    def _on_mcq_option_selected(self, label: str, is_correct: bool):
        if getattr(self, "burst", None) is not None:
            color = "green" if is_correct else "red"
            self.burst.spawn_burst(self.rect().center().x(), self.rect().center().y(), color, count=25)
        self._reveal_bar.hide()
        self._show_overlay(self._rating_frame)

    def _exit_peek(self):
        if self._peek_idx is None:
            return
        self._peek_idx = None
        self._peek_origin_idx = None
        if hasattr(self.canvas, "set_peek_active"):
            self.canvas.set_peek_active(False)
        if hasattr(self.canvas, "clear_peek_target"):
            self.canvas.clear_peek_target()
        self._rebuild_queue()
        self._center_on_target()

    def _jump_to_queue_index(self, idx, from_peek=False):
        if not (0 <= idx < len(self._items)):
            return
        if self._peek_origin_idx is None:
            self._peek_origin_idx = self._idx
        self._peek_idx = idx
        card, box_idx, _ = self._items[idx]
        if hasattr(self.canvas, "set_peek_target_box"):
            if isinstance(box_idx, tuple) and box_idx[0] == "group":
                self.canvas.set_peek_target_group(box_idx[1])
            else:
                self.canvas.set_peek_target_box(
                    box_idx if isinstance(box_idx, int) else -1
                )
        if hasattr(self.canvas, "set_peek_active"):
            self.canvas.set_peek_active(True)
        self._rebuild_queue(peek_idx=idx)
        self._center_on_target()

    def _on_queue_item_clicked(self, item):
        idx = item.data(QUEUE_INDEX_ROLE)
        if idx is None:
            return
        self._jump_to_queue_index(int(idx))

    def _set_fullscreen_ui(self, fullscreen: bool):
        self._hdr_widget.setVisible(not fullscreen)
        self.lbl_title.setVisible(False)  # always hidden
        self._hint_label.setVisible(not fullscreen)

    def _setup_ui(self):
        dojo = _is_dojo()
        from theme_manager import get_palette

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        self._theme = theme
        p = get_palette(theme)

        is_cyan_theme = theme in ("manhattan", "tmnt")
        hover_bg_raw = "0, 240, 255" if is_cyan_theme else "114, 255, 79"

        # ── resolved palette ──────────────────────────────────────────────────
        bg = p.get("C_BG", C_BG)
        surface = p.get("C_SURFACE", C_SURFACE)
        card = p.get("C_CARD", C_CARD)
        accent = p.get("C_ACCENT", C_ACCENT)
        accent2 = p.get("C_PURPLE", C_ACCENT)
        text = p.get("C_TEXT", C_TEXT)
        subtext = p.get("C_SUBTEXT", C_SUBTEXT)
        border = p.get("C_BORDER", C_BORDER)
        orange = p.get("C_ORANGE", "#FFA200" if dojo else "#FAB387")
        font = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")

        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ── Icon imports ───────────────────────────────────────────────────────
        from ui.review_icons import (
            icon_zoom_in, icon_zoom_out, icon_zoom_fit, icon_crosshair,
            icon_chevron_left, icon_chevron_right, icon_contrast, icon_focus,
        )
        _icon_fg = accent if dojo else text
        _icon_sz = 22  # rendered icon bitmap size

        # ── Header container (two rows) ────────────────────────────────────────
        hdr_w = QFrame()
        if dojo:
            hdr_w.setStyleSheet(
                f"QFrame{{background:{surface};"
                f"border-bottom:2px solid {accent};border-radius:0;}}"
            )
        else:
            hdr_w.setStyleSheet(
                f"QFrame{{background:{surface};"
                f"border-bottom:1px solid {border};border-radius:0;}}"
            )
        hdr_vbox = QVBoxLayout(hdr_w)
        hdr_vbox.setContentsMargins(0, 0, 0, 0)
        hdr_vbox.setSpacing(0)

        # ══════════════════════════════════════════════════════════════════════
        #  ROW 1 — Session info  +  Primary actions
        # ══════════════════════════════════════════════════════════════════════
        row1_w = QWidget()
        row1_w.setStyleSheet("background:transparent;")
        row1 = QHBoxLayout(row1_w)
        row1.setContentsMargins(14, 4, 14, 2)
        row1.setSpacing(10)

        self.lbl_filename = QLabel("")
        if dojo:
            self.lbl_filename.setFont(QFont(font, 8))
            self.lbl_filename.setStyleSheet(
                f"color:{subtext};letter-spacing:1px;font-family:{font};"
            )
        else:
            self.lbl_filename.setFont(QFont("Segoe UI", 10))
            self.lbl_filename.setStyleSheet(
                f"color:{subtext};"
            )
        row1.addWidget(self.lbl_filename)


        def _hdr_btn(label, primary=False):
            b = QPushButton(label)
            if dojo:
                if primary:
                    b.setStyleSheet(
                        f"QPushButton{{background:{accent};color:{bg};"
                        f"border:none;border-radius:2px;padding:4px 14px;"
                        f"font-size:7.5px;font-weight:900;font-family:{font};"
                        f"letter-spacing:0.5px;}}"
                        f"QPushButton:hover{{background:white;color:{bg};}}"
                    )
                else:
                    b.setStyleSheet(
                        f"QPushButton{{background:{card};color:{text};"
                        f"border:1px solid {border};border-radius:2px;"
                        f"padding:4px 14px;font-size:7.5px;"
                        f"font-family:{font};letter-spacing:0.5px;}}"
                        f"QPushButton:hover{{background:rgba({hover_bg_raw},0.08);"
                        f"border:1px solid {accent};}}"
                    )
            else:
                if primary:
                    b.setStyleSheet(
                        f"QPushButton{{background:{accent};color:white;border:none;"
                        f"border-radius:6px;padding:4px 14px;"
                        f"font-size:12px;font-weight:bold;}}"
                        f"QPushButton:hover{{background:#6A58E0;}}"
                    )
                else:
                    b.setStyleSheet(
                        f"QPushButton{{background:{card};color:{text};"
                        f"border:1px solid {border};border-radius:6px;"
                        f"padding:4px 14px;font-size:12px;}}"
                        f"QPushButton:hover{{background:{surface};}}"
                    )
            return b

        b_edit = _hdr_btn("✏ Edit Card", primary=True)
        b_edit.clicked.connect(self._edit_current_card)
        self._btn_card_manager = _hdr_btn("📋 Card Manager")
        self._btn_card_manager.setToolTip("Open Bulk Card Manager to search, filter, edit, or delete cards (Ctrl+B)")
        self._btn_card_manager.clicked.connect(self._open_card_browser)
        self._btn_annot = _hdr_btn("🖊 Annotate Scroll")
        self._btn_annot.clicked.connect(self._open_annotation_beta)
        
        self._btn_note = _hdr_btn("💡 Note")
        self._btn_note.setCheckable(True)
        self._btn_note.setChecked(False)
        if dojo:
            self._btn_note.setStyleSheet(
                self._btn_note.styleSheet()
                + f"QPushButton:checked{{background:{accent2};color:white;"
                f"border:1px solid {accent2};}}"
            )
        else:
            self._btn_note.setStyleSheet(
                f"QPushButton{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:6px;"
                f"padding:4px 14px;font-size:12px;}}"
                f"QPushButton:checked{{background:#6A3FBF;color:white;"
                f"border:1px solid {accent};}}"
                f"QPushButton:hover{{background:{surface};}}"
            )
        self._btn_note.clicked.connect(self._toggle_hint_panel)
        self._btn_note.setEnabled(False)

        self._btn_pdf_note = _hdr_btn("📄 PDF Notes")
        self._btn_pdf_note.clicked.connect(self._open_pdf_notes_editor)
        self._btn_pdf_note.setEnabled(False)

        self._btn_save_ink = _hdr_btn("🎨 Save Ink")
        self._btn_save_ink.clicked.connect(self._save_review_ink_to_note)
        self._btn_save_ink.setEnabled(False)
        
        self._btn_focus_canvas = _hdr_btn("🎯 Focus")
        self._btn_focus_canvas.setCheckable(True)
        self._btn_focus_canvas.setChecked(False)
        if dojo:
            self._btn_focus_canvas.setStyleSheet(
                self._btn_focus_canvas.styleSheet()
                + f"QPushButton:checked{{background:{accent2};color:white;"
                f"border:1px solid {accent2};}}"
            )
        else:
            self._btn_focus_canvas.setStyleSheet(
                f"QPushButton{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:6px;"
                f"padding:4px 14px;font-size:12px;}}"
                f"QPushButton:checked{{background:#6A3FBF;color:white;"
                f"border:1px solid {accent};}}"
                f"QPushButton:hover{{background:{surface};}}"
            )
        self._btn_focus_canvas.clicked.connect(self._toggle_focus_mode)

        self._btn_focus_opacity_minus = _hdr_btn("−")
        self._btn_focus_opacity_minus.setFixedWidth(28)
        self._btn_focus_opacity_minus.setToolTip("Decrease Focus (Brighter)")
        self._btn_focus_opacity_minus.setStyleSheet(
            self._btn_focus_opacity_minus.styleSheet() + " QPushButton { padding: 0px; font-size: 16px; font-weight: bold; }"
        )
        self._btn_focus_opacity_minus.clicked.connect(lambda: self._adjust_focus_opacity(0.05))

        self._btn_focus_opacity_plus = _hdr_btn("+")
        self._btn_focus_opacity_plus.setFixedWidth(28)
        self._btn_focus_opacity_plus.setToolTip("Increase Focus (Darker)")
        self._btn_focus_opacity_plus.setStyleSheet(
            self._btn_focus_opacity_plus.styleSheet() + " QPushButton { padding: 0px; font-size: 16px; font-weight: bold; }"
        )
        self._btn_focus_opacity_plus.clicked.connect(lambda: self._adjust_focus_opacity(-0.05))

        self._btn_ultra_focus = _hdr_btn("⚡ Ultra Focus")
        self._btn_ultra_focus.setCheckable(True)
        self._btn_ultra_focus.setChecked(False)
        self._btn_ultra_focus.setToolTip("Ultra Focus Mode: Only active question is visible, rest is solid color (Ctrl+Shift+F)")
        if dojo:
            self._btn_ultra_focus.setStyleSheet(
                self._btn_ultra_focus.styleSheet()
                + f"QPushButton:checked{{background:{accent2};color:white;"
                f"border:1px solid {accent2};}}"
            )
        else:
            self._btn_ultra_focus.setStyleSheet(
                f"QPushButton{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:6px;"
                f"padding:4px 14px;font-size:12px;}}"
                f"QPushButton:checked{{background:#8E24AA;color:white;"
                f"border:1px solid {accent};}}"
                f"QPushButton:hover{{background:{surface};}}"
            )
        self._btn_ultra_focus.clicked.connect(self._toggle_ultra_focus_mode)
        
        row1.addWidget(b_edit)
        row1.addWidget(self._btn_card_manager)
        row1.addWidget(self._btn_annot)
        row1.addWidget(self._btn_note)
        row1.addWidget(self._btn_pdf_note)
        row1.addWidget(self._btn_save_ink)
        row1.addWidget(self._btn_focus_canvas)
        row1.addWidget(self._btn_focus_opacity_minus)
        row1.addWidget(self._btn_focus_opacity_plus)
        row1.addWidget(self._btn_ultra_focus)

        self._btn_options = _hdr_btn("⚙️ Options")
        from PyQt5.QtWidgets import QMenu, QAction
        self._menu_options = QMenu(self)
        self._menu_options.setStyleSheet(
            f"QMenu {{ background-color: {card}; color: {text}; border: 1px solid {border}; border-radius: 4px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px 6px 20px; border-radius: 2px; }}"
            f"QMenu::item:selected {{ background-color: {accent}; color: white; }}"
            f"QMenu::item:checked {{ font-weight: bold; }}"
        )
        
        self._act_hide_all = QAction("🟧 Hide All, Guess One", self, checkable=True)
        self._act_hide_all.setChecked(True)
        self._act_hide_all.triggered.connect(self._on_hide_all_toggled)
        self._menu_options.addAction(self._act_hide_all)

        self._act_ultra_focus = QAction("⚡ Ultra Focus Mode", self, checkable=True)
        self._act_ultra_focus.setChecked(False)
        self._act_ultra_focus.triggered.connect(self._toggle_ultra_focus_mode)
        self._menu_options.addAction(self._act_ultra_focus)
        
        self._act_summary = QAction("📊 Show Summary Popup", self, checkable=True)
        self._act_summary.setChecked(self._show_summary_popup)
        self._act_summary.triggered.connect(self._on_summary_toggled)
        self._menu_options.addAction(self._act_summary)
        
        self._act_cache = QAction("💾 Show Cache Panel", self, checkable=True)
        self._act_cache.setChecked(False)
        self._act_cache.triggered.connect(self._toggle_cache_panel)
        self._menu_options.addAction(self._act_cache)
        
        self._menu_options.addSeparator()

        self._act_card_manager = QAction("📋 Bulk Card Manager", self)
        self._act_card_manager.setToolTip("Open Card Manager to view, search, and bulk manage cards (Ctrl+B)")
        self._act_card_manager.triggered.connect(self._open_card_browser)
        self._menu_options.addAction(self._act_card_manager)
        
        self._menu_options.aboutToShow.connect(self._update_options_menu_states)
        
        self._btn_options.setMenu(self._menu_options)
        row1.addWidget(self._btn_options)

        from data_manager import store
        auto_reveal = store.get().get("_auto_reveal", False)
        self._btn_auto_reveal = _hdr_btn("👁 Auto-Reveal")
        self._btn_auto_reveal.setCheckable(True)
        self._btn_auto_reveal.setChecked(auto_reveal)
        if dojo:
            self._btn_auto_reveal.setStyleSheet(
                self._btn_auto_reveal.styleSheet()
                + f"QPushButton:checked{{background:{accent2};color:white;"
                f"border:1px solid {accent2};}}"
            )
        else:
            self._btn_auto_reveal.setStyleSheet(
                f"QPushButton{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:6px;"
                f"padding:4px 14px;font-size:12px;}}"
                f"QPushButton:checked{{background:#6A3FBF;color:white;"
                f"border:1px solid {accent};}}"
                f"QPushButton:hover{{background:{surface};}}"
            )
        self._btn_auto_reveal.clicked.connect(self._toggle_auto_reveal)
        row1.addWidget(self._btn_auto_reveal)

        b_exit = _hdr_btn("✕ Exit")
        b_exit.clicked.connect(self.cancelled.emit)
        row1.addWidget(b_exit)

        hdr_vbox.addWidget(row1_w)

        # ── thin divider between rows ──────────────────────────────────────────
        _row_div = QFrame()
        _row_div.setFixedHeight(1)
        _row_div.setStyleSheet(
            f"background:{accent if dojo else border};"
        )
        hdr_vbox.addWidget(_row_div)

        # ══════════════════════════════════════════════════════════════════════
        #  ROW 2 — View controls:  Page Nav  |  Zoom  |  Invert
        # ══════════════════════════════════════════════════════════════════════
        row2_w = QWidget()
        row2_w.setStyleSheet("background:transparent;")
        row2 = QHBoxLayout(row2_w)
        row2.setContentsMargins(14, 3, 14, 4)
        row2.setSpacing(6)

        # ── helper: icon button (bigger, with proper icons) ────────────────
        _ib_size = 32  # button size
        def _icon_btn(icon: QIcon, tip: str, sz: int = _ib_size):
            b = QPushButton()
            b.setToolTip(tip)
            b.setIcon(icon)
            b.setIconSize(QSize(_icon_sz, _icon_sz))
            b.setFixedSize(sz, sz)
            b.setFocusPolicy(Qt.NoFocus)
            if dojo:
                b.setStyleSheet(
                    f"QPushButton{{background:{card};color:{accent};"
                    f"border:1px solid {border};border-radius:2px;}}"
                    f"QPushButton:hover{{background:rgba({hover_bg_raw},0.15);"
                    f"border:1px solid {accent};}}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton{{background:{card};color:{text};"
                    f"border:1px solid {border};border-radius:6px;}}"
                    f"QPushButton:hover{{background:{surface};"
                    f"border:1px solid {accent};}}"
                )
            return b

        # ── helper: vertical separator ─────────────────────────────────────
        def _vsep():
            sep = QFrame()
            sep.setFixedWidth(1)
            sep.setFixedHeight(22)
            sep.setStyleSheet(f"background:{border};")
            return sep

        # ── Card progress (moved from Row 1) ─────────────────────────────
        self.lbl_prog = QLabel("Card 1/1")
        if dojo:
            self.lbl_prog.setFont(QFont(font, 9, QFont.Bold))
            self.lbl_prog.setStyleSheet(
                f"color:{accent};letter-spacing:2px;font-family:{font};"
            )
        else:
            self.lbl_prog.setFont(QFont("Segoe UI", 11, QFont.Bold))
        row2.addWidget(self.lbl_prog)

        self.lbl_sm2 = QLabel("")
        if dojo:
            self.lbl_sm2.setStyleSheet(
                f"background:{card};color:{accent2};"
                f"border:1px solid {accent2};border-radius:2px;"
                f"padding:2px 8px;font-size:9px;font-family:{font};"
                f"letter-spacing:1px;"
            )
        else:
            self.lbl_sm2.setStyleSheet(
                f"background:{card};color:{subtext};"
                f"border-radius:6px;padding:3px 10px;font-size:11px;"
            )
        row2.addWidget(self.lbl_sm2)

        self.prog = QProgressBar()
        self.prog.setFixedHeight(6 if dojo else 8)
        self.prog.setTextVisible(False)
        if dojo:
            self.prog.setStyleSheet(
                f"QProgressBar{{background:{card};border-radius:3px;"
                f"border:1px solid {border};}}"
                f"QProgressBar::chunk{{background:{accent};border-radius:3px;}}"
            )
            
            # Shifting laser sweep timer
            self._prog_glow_step = 0
            self._prog_timer = QTimer(self)
            def _animate_prog():
                import os
                if os.environ.get("ANKI_HOME_ANIMATIONS", "").strip().lower() in {"0", "false", "no", "off"}:
                    return
                self._prog_glow_step = (self._prog_glow_step + 3) % 100
                s1 = max(0, self._prog_glow_step - 15) / 100.0
                s2 = self._prog_glow_step / 100.0
                s3 = min(100, self._prog_glow_step + 15) / 100.0
                self.prog.setStyleSheet(
                    f"QProgressBar{{background:{card};border-radius:3px;border:1px solid {border};}}"
                    f"QProgressBar::chunk{{background:qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                    f"stop:0 {accent}, stop:{s1} {accent}, stop:{s2} #ffffff, stop:{s3} {accent}, stop:1 {accent});"
                    f"border-radius:3px;}}"
                )
            self._prog_timer.timeout.connect(_animate_prog)
            from theme_manager import is_retro_theme
            if is_retro_theme(theme) and os.environ.get("ANKI_HOME_ANIMATIONS", "").strip().lower() not in {"0", "false", "no", "off"}:
                self._prog_timer.start(40)
        else:
            self.prog.setStyleSheet(
                f"QProgressBar{{background:{card};border-radius:4px;}}"
                f"QProgressBar::chunk{{background:{accent};border-radius:4px;}}"
            )
        row2.addWidget(self.prog, stretch=1)

        row2.addWidget(_vsep())

        # ── Group 1: Page Navigation ──────────────────────────────────────
        _lbl_page = QLabel("PAGE")
        _lbl_page.setStyleSheet(
            f"color:{subtext};background:transparent;"
            f"font-size:{'7px' if dojo else '9px'};"
            f"font-weight:bold;letter-spacing:1px;"
            + (f"font-family:{font};" if dojo else "")
        )
        row2.addWidget(_lbl_page)

        self._btn_prev_page = _icon_btn(
            icon_chevron_left(_icon_sz, _icon_fg), "Previous PDF page  PgUp", 34
        )
        self._btn_next_page = _icon_btn(
            icon_chevron_right(_icon_sz, _icon_fg), "Next PDF page  PgDn", 34
        )
        self._btn_prev_page.clicked.connect(self._go_prev_review_page)
        self._btn_next_page.clicked.connect(self._go_next_review_page)
        row2.addWidget(self._btn_prev_page)

        self._page_jump = QLineEdit()
        self._page_jump.setFixedWidth(46)
        self._page_jump.setFixedHeight(28)
        self._page_jump.setAlignment(Qt.AlignCenter)
        if dojo:
            self._page_jump.setStyleSheet(
                f"QLineEdit{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:2px;"
                f"font-size:10px;font-family:{font};}}"
            )
        else:
            self._page_jump.setStyleSheet(
                f"QLineEdit{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:4px;"
                f"font-size:11px;}}"
            )
        self._page_jump.returnPressed.connect(self._jump_to_review_page_from_input)
        row2.addWidget(self._page_jump)

        self._page_total = QLabel("/ 0")
        self._page_total.setStyleSheet(
            f"color:{subtext};background:transparent;"
            f"font-size:{'9px' if dojo else '11px'};"
            + (f"font-family:{font};" if dojo else "")
        )
        row2.addWidget(self._page_total)
        row2.addWidget(self._btn_next_page)

        row2.addWidget(_vsep())

        # ── Group 2: Zoom Controls ────────────────────────────────────────
        _lbl_zoom = QLabel("ZOOM")
        _lbl_zoom.setStyleSheet(
            f"color:{subtext};background:transparent;"
            f"font-size:{'7px' if dojo else '9px'};"
            f"font-weight:bold;letter-spacing:1px;"
            + (f"font-family:{font};" if dojo else "")
        )
        row2.addWidget(_lbl_zoom)

        b_zin = _icon_btn(icon_zoom_in(_icon_sz, _icon_fg), "Zoom In  Ctrl++")
        b_zout = _icon_btn(icon_zoom_out(_icon_sz, _icon_fg), "Zoom Out  Ctrl+−")
        b_zfit = _icon_btn(icon_zoom_fit(_icon_sz, _icon_fg), "Zoom Fit  Ctrl+0")
        b_center = _icon_btn(icon_crosshair(_icon_sz, _icon_fg), "Center on active mask  C")

        def _manual_zoom(direction: int):
            if direction > 0:
                self.canvas.zoom_in()
            else:
                self.canvas.zoom_out()
            self._user_zoom_scale = self.canvas._scale

        def _on_zoom_fit_btn():
            self._user_zoom_scale = None
            self._zoom_fit()

        b_zin.clicked.connect(lambda: _manual_zoom(+1))
        b_zout.clicked.connect(lambda: _manual_zoom(-1))
        b_zfit.clicked.connect(_on_zoom_fit_btn)
        b_center.clicked.connect(self._center_on_target)
        row2.addWidget(b_zin)
        row2.addWidget(b_zout)
        row2.addWidget(b_zfit)
        row2.addWidget(b_center)

        row2.addWidget(_vsep())

        # ── Group 3: View Toggles ─────────────────────────────────────────
        _lbl_view = QLabel("VIEW")
        _lbl_view.setStyleSheet(
            f"color:{subtext};background:transparent;"
            f"font-size:{'7px' if dojo else '9px'};"
            f"font-weight:bold;letter-spacing:1px;"
            + (f"font-family:{font};" if dojo else "")
        )
        row2.addWidget(_lbl_view)

        self._btn_invert_pdf = _icon_btn(
            icon_contrast(_icon_sz, _icon_fg),
            "Toggle PDF Inversion (Dark / High Contrast)  I"
        )
        # make the invert button slightly more prominent
        if dojo:
            self._btn_invert_pdf.setStyleSheet(
                f"QPushButton{{background:{card};color:{accent};"
                f"border:1px solid {accent};border-radius:2px;}}"
                f"QPushButton:hover{{background:rgba({hover_bg_raw},0.20);"
                f"border:1px solid {accent};}}"
            )
        else:
            self._btn_invert_pdf.setStyleSheet(
                f"QPushButton{{background:{card};color:{text};"
                f"border:1px solid {accent};border-radius:6px;}}"
                f"QPushButton:hover{{background:{surface};"
                f"border:1px solid {accent};}}"
            )
        self._btn_invert_pdf.clicked.connect(self._toggle_pdf_contrast)
        row2.addWidget(self._btn_invert_pdf)

        self._update_focus_mode_button_style()

        row2.addWidget(_vsep())

        # ── Group 4: Pen / Ink Tools ──────────────────────────────────────
        _lbl_pen = QLabel("PEN")
        _lbl_pen.setStyleSheet(
            f"color:{subtext};background:transparent;"
            f"font-size:{'7px' if dojo else '9px'};"
            f"font-weight:bold;letter-spacing:1px;"
            + (f"font-family:{font};" if dojo else "")
        )
        row2.addWidget(_lbl_pen)

        self._btn_toggle_pen = _icon_btn(QIcon(), "Toggle Pen Drawing  Alt / P", 28)
        self._btn_toggle_pen.setText("🖊")
        self._btn_toggle_pen.clicked.connect(self._toggle_pen_drawing)
        row2.addWidget(self._btn_toggle_pen)

        self._btn_eraser = _icon_btn(QIcon(), "Toggle Eraser Tool  Shift+`", 28)
        self._btn_eraser.setText("🧹")
        self._btn_eraser.clicked.connect(self._toggle_eraser)
        row2.addWidget(self._btn_eraser)

        self._btn_pen_color = _icon_btn(QIcon(), "Choose Custom Pen Color (Click to pick, Shift+X to open dialog)", 28)
        self._btn_pen_color.setText("🎨")
        self._btn_pen_color.clicked.connect(self._choose_pen_color_picker)
        row2.addWidget(self._btn_pen_color)

        self._btn_pen_clear = _icon_btn(QIcon(), "Clear All Pen Strokes  Delete", 28)
        self._btn_pen_clear.setText("🗑")
        self._btn_pen_clear.clicked.connect(self._clear_pen_strokes)
        row2.addWidget(self._btn_pen_clear)

        from PyQt5.QtWidgets import QComboBox
        self._btn_review_pen_perf = QComboBox()
        self._btn_review_pen_perf.setFocusPolicy(Qt.NoFocus)
        self._btn_review_pen_perf.addItems([
            "Classic" if dojo else "Classic Smooth",
            "Incremental" if dojo else "Incremental Bezier",
            "Polyline" if dojo else "Raw Polyline",
            "Filtered" if dojo else "Distance-Filtered"
        ])
        self._btn_review_pen_perf.setCursor(Qt.PointingHandCursor)
        self._btn_review_pen_perf.setToolTip("Change Pen Mode (Beta)")
        
        if dojo:
            self._btn_review_pen_perf.setStyleSheet(
                f"QComboBox{{background:{card};color:{accent};"
                f"border:1px solid {border};border-radius:2px;"
                f"padding:2px 4px;font-family:{font};font-size:9px;font-weight:bold;}}"
                f"QComboBox QAbstractItemView{{"
                f"background-color:{card};color:{accent};"
                f"border:1px solid {border};"
                f"selection-background-color:{surface};selection-color:{accent};}}"
            )
        else:
            self._btn_review_pen_perf.setStyleSheet(
                f"QComboBox{{background:{card};color:{text};"
                f"border:1px solid {border};border-radius:6px;"
                f"padding:2px 8px;font-size:11px;font-weight:bold;}}"
                f"QComboBox QAbstractItemView{{"
                f"background-color:{card};color:{text};"
                f"border:1px solid {border};"
                f"selection-background-color:{surface};selection-color:{accent};}}"
            )
        
        _impl_to_idx = {"classic": 0, "incremental": 1, "polyline": 2, "filtered": 3}
        self._btn_review_pen_perf.setCurrentIndex(_impl_to_idx.get(self._review_pen_implementation, 0))
        self._btn_review_pen_perf.currentIndexChanged.connect(self._on_review_pen_perf_changed)
        row2.addWidget(self._btn_review_pen_perf)

        # Initialize the dynamic states of these buttons
        self._update_pen_button_states()

        row2.addStretch()
        hdr_vbox.addWidget(row2_w)

        L.addWidget(hdr_w)
        self._hdr_widget = hdr_w
        self._hdr_widget.hide()

        self.lbl_title = QLabel("")
        self.lbl_title.setFont(
            QFont(font if dojo else "Segoe UI", 10 if dojo else 12, QFont.Bold)
        )
        if dojo:
            self.lbl_title.setStyleSheet(
                f"color:{accent};background:{bg};"
                f"padding:4px 16px;border-bottom:2px solid {accent};"
                f"letter-spacing:3px;font-family:{font};"
            )
        else:
            self.lbl_title.setStyleSheet(
                f"color:{accent};background:{bg};"
                f"padding:4px 16px;border-bottom:1px solid {border};"
            )
        self.lbl_title.setFixedHeight(30)
        self.lbl_title.hide()
        L.addWidget(self.lbl_title)

        # ── Canvas scroll area ────────────────────────────────────────────────
        self._canvas_scroll = _ZoomableScrollArea()
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setAlignment(Qt.AlignCenter)
        self._canvas_scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{bg};}}"
            f"QScrollBar:vertical{{background:{surface};width:8px;border-radius:4px;}}"
            f"QScrollBar::handle:vertical{{background:{border};border-radius:4px;}}"
            f"QScrollBar:horizontal{{background:{surface};height:8px;border-radius:4px;}}"
            f"QScrollBar::handle:horizontal{{background:{border};border-radius:4px;}}"
        )
        self.canvas = OcclusionCanvas()
        self.canvas.set_mode("review")
        self.canvas._ink_width = float(self._review_ink_width)
        self.canvas._ink_colors = list(self._review_ink_colors)
        self.canvas._ink_color_idx = int(self._review_ink_color_idx)
        self.canvas._ink_implementation = self._review_pen_implementation
        self._activate_default_review_pen()
        self._update_pen_button_states()
        self.canvas.right_clicked.connect(self._toggle_chrome)
        self.canvas.right_clicked_box.connect(self._on_canvas_right_clicked_box)

        self._canvas_scroll.setWidget(self.canvas)
        self._canvas_scroll.set_canvas(self.canvas)
        self.canvas._zoom_timer.timeout.connect(self._on_canvas_zoom_settled)
        self._canvas_scroll.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._note_user_activity()
        )
        self._canvas_scroll.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._keep_floating_timer_on_top()
        )
        self._canvas_scroll.verticalScrollBar().valueChanged.connect(
            lambda *_: self._note_user_activity()
        )
        self._canvas_scroll.verticalScrollBar().valueChanged.connect(
            self._on_review_scroll_page_changed
        )

        self._sc_prev_page = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.prev_page")), self
        )
        self._sc_prev_page.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_prev_page.setAutoRepeat(False)
        self._sc_prev_page.activated.connect(self._go_prev_review_page)

        self._sc_next_page = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.next_page")), self
        )
        self._sc_next_page.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_next_page.setAutoRepeat(False)
        self._sc_next_page.activated.connect(self._go_next_review_page)

        self._sc_pdf_metadata = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.pdf_metadata")), self
        )
        self._sc_pdf_metadata.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_pdf_metadata.setAutoRepeat(False)
        self._sc_pdf_metadata.activated.connect(self._open_pdf_notes_editor)

        self._sc_toggle_note = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.toggle_note")), self
        )
        self._sc_toggle_note.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_toggle_note.setAutoRepeat(False)
        self._sc_toggle_note.activated.connect(self._toggle_hint_panel)

        self._sc_toggle_pdf_notes = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.toggle_pdf_notes")), self
        )
        self._sc_toggle_pdf_notes.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_toggle_pdf_notes.setAutoRepeat(False)
        self._sc_toggle_pdf_notes.activated.connect(self._toggle_pdf_notes)

        self._pdf_viewer = PdfViewerController(
            canvas=self.canvas,
            scroll_area=self._canvas_scroll,
            page_input=self._page_jump,
            page_total_label=self._page_total,
            prev_button=self._btn_prev_page,
            next_button=self._btn_next_page,
            total_pages_getter=lambda: len(getattr(self.canvas, "_pages", []) or []),
            debug_hook=self._review_nav_debug,
        )

        self._stacked_widget = QStackedWidget()
        self._stacked_widget.addWidget(self._canvas_scroll)
        self._text_review_widget = TextReviewWidget(self)
        self._text_review_widget.answer_submitted.connect(self._reveal_current)
        self._stacked_widget.addWidget(self._text_review_widget)
        self._mcq_review_widget = MCQReviewWidget(self)
        self._mcq_review_widget.answer_submitted.connect(self._on_mcq_answer_submitted)
        self._mcq_review_widget.option_selected.connect(self._on_mcq_option_selected)
        self._stacked_widget.addWidget(self._mcq_review_widget)

        self._canvas_stage = QWidget()
        self._canvas_stage.setStyleSheet(f"background:{bg};")

        canvas_stage_l = QVBoxLayout(self._canvas_stage)
        canvas_stage_l.setContentsMargins(0, 0, 0, 0)
        canvas_stage_l.addWidget(self._stacked_widget)
        self._stacked_widget.setMinimumWidth(300)

        # Slide-out Solution Drawer / Hint Panel (floating overlay)
        self._hint_panel = QFrame(self._canvas_stage)
        if dojo:
            self._hint_panel.setStyleSheet(
                f"QFrame{{background:{surface};border-left:2px solid {accent};border-radius:0;}}"
            )
        else:
            self._hint_panel.setStyleSheet(
                f"QFrame{{background:{surface};border-left:1px solid {border};border-radius:0;}}"
            )
        self._hint_panel.setMinimumWidth(200)
        self._hint_panel.hide()

        hp_layout = QVBoxLayout(self._hint_panel)
        hp_layout.setContentsMargins(12, 12, 12, 12)
        hp_layout.setSpacing(10)

        hp_hdr = QHBoxLayout()
        hp_hdr.setSpacing(6)
        self._btn_hint_tab_mask = QPushButton("💡 Mask")
        self._btn_hint_tab_pdf = QPushButton("📄 PDF")
        self._btn_hint_tab_mask.setFont(QFont(font if dojo else "Segoe UI", 10, QFont.Bold))
        self._btn_hint_tab_pdf.setFont(QFont(font if dojo else "Segoe UI", 10, QFont.Bold))
        self._btn_hint_tab_mask.setCursor(Qt.PointingHandCursor)
        self._btn_hint_tab_pdf.setCursor(Qt.PointingHandCursor)
        
        self._btn_hint_tab_mask.clicked.connect(lambda: self._set_hint_view_mode("mask"))
        self._btn_hint_tab_pdf.clicked.connect(lambda: self._set_hint_view_mode("pdf"))
        
        self._update_hint_tab_styles()
        
        hp_hdr.addWidget(self._btn_hint_tab_mask)
        hp_hdr.addWidget(self._btn_hint_tab_pdf)
        hp_hdr.addStretch()

        # Font size adjustment buttons
        self._hp_zoom_out = QPushButton("A-")
        self._hp_zoom_out.setToolTip("Decrease Font Size")
        self._hp_zoom_out.setFixedSize(28, 28)
        self._hp_zoom_out.setCursor(Qt.PointingHandCursor)
        
        self._hp_zoom_in = QPushButton("A+")
        self._hp_zoom_in.setToolTip("Increase Font Size")
        self._hp_zoom_in.setFixedSize(28, 28)
        self._hp_zoom_in.setCursor(Qt.PointingHandCursor)
        
        btn_style = (
            f"QPushButton{{background:{surface};color:{text};border:1px solid {border};border-radius:6px;"
            f"font-family:'{font if dojo else 'Segoe UI'}';font-weight:bold;font-size:11px;}}"
            f"QPushButton:hover{{background:{accent};color:{bg if theme != 'classic' else 'white'};border-color:{accent};}}"
        )
        self._hp_zoom_out.setStyleSheet(btn_style)
        self._hp_zoom_in.setStyleSheet(btn_style)
        
        self._hp_zoom_out.clicked.connect(self._zoom_hint_out)
        self._hp_zoom_in.clicked.connect(self._zoom_hint_in)
        
        hp_hdr.addWidget(self._hp_zoom_out)
        hp_hdr.addWidget(self._hp_zoom_in)

        hp_close = QPushButton("✕")
        hp_close.setFixedSize(28, 28)
        hp_close.setCursor(Qt.PointingHandCursor)
        hp_close.setStyleSheet(
            f"QPushButton{{background:{surface};color:{text};border:1px solid {border};border-radius:6px;"
            f"font-family:'{font if dojo else 'Segoe UI'}';font-weight:bold;font-size:11px;}}"
            f"QPushButton:hover{{background:#EF4444;color:white;border-color:#EF4444;}}"
        )
        hp_close.clicked.connect(self._toggle_hint_panel)
        hp_hdr.addWidget(hp_close)
        hp_layout.addLayout(hp_hdr)

        self._hint_browser = SelectableTextBrowser()
        self._hint_browser.setOpenExternalLinks(True)
        self._hint_browser.setContextMenuPolicy(Qt.CustomContextMenu)
        self._hint_browser.customContextMenuRequested.connect(self._show_hint_context_menu)
        self._hint_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scrollbar_style = (
            f"QTextBrowser {{ background: transparent; color: {text}; border: none; font-size: {self._hint_font_size}px; line-height: 1.4; }}"
            f"QScrollBar:vertical {{"
            f"    background: {surface};"
            f"    width: 10px;"
            f"    border-radius: 5px;"
            f"    margin: 0px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"    background: {subtext};"
            f"    min-height: 20px;"
            f"    border-radius: 5px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"    background: {accent};"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"    background: none;"
            f"    height: 0px;"
            f"}}"
        )
        self._hint_browser.setStyleSheet(scrollbar_style)
        hp_layout.addWidget(self._hint_browser)

        # Connect to scrollbar signals to save position
        vbar = self._hint_browser.verticalScrollBar()
        vbar.valueChanged.connect(self._on_hint_scrolled)
        
        self._resize_handle = ResizeHandle(self._hint_panel, self._on_hint_panel_resize)

        # Configure floating action buttons based on the active theme
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        if theme == "dojo":
            hint_text, hint_emoji, hint_border = "Jutsu Note", "📜", "#FFB7C5"
            sc_text, sc_emoji, sc_border = "Forge & Clear", "⚔", "#A6E3A1"
            sk_text, sk_emoji, sk_border = "Forge & Keep", "📌", "#89B4FA"
        elif theme in ("tmnt", "manhattan"):
            hint_text, hint_emoji, hint_border = "Ooze Hint", "🧪", "#A86CFF"
            sc_text, sc_emoji, sc_border = "Save & Clear", "🍕", "#39FF14"
            sk_text, sk_emoji, sk_border = "Save & Keep", "📌", "#FFA200"
        elif theme == "arcanum":
            hint_text, hint_emoji, hint_border = "Spell Note", "🔮", "#5FEAD0"
            sc_text, sc_emoji, sc_border = "Cast & Clear", "✨", "#6FE7A8"
            sk_text, sk_emoji, sk_border = "Cast & Keep", "📌", "#A78BFA"
        else:
            hint_text, hint_emoji, hint_border = "Hint", "💡", None
            sc_text, sc_emoji, sc_border = "Save & Clear", "💾", "#A6E3A1"
            sk_text, sk_emoji, sk_border = "Save & Keep", "📌", "#89B4FA"

        self._floating_hint_button = FloatingActionButton(
            self._canvas_stage,
            text=hint_text,
            emoji=hint_emoji,
            on_click=self._toggle_hint_panel,
            border_color_hex=hint_border
        )
        self._floating_hint_button.move(15, 15)
        self._floating_hint_button.hide()

        self._floating_save_clear_button = FloatingActionButton(
            self._canvas_stage,
            text=sc_text,
            emoji=sc_emoji,
            on_click=lambda: self._save_review_ink_to_note(clear_ink=True),
            border_color_hex=sc_border
        )
        self._floating_save_clear_button.move(105, 15)
        self._floating_save_clear_button.hide()

        self._floating_save_keep_button = FloatingActionButton(
            self._canvas_stage,
            text=sk_text,
            emoji=sk_emoji,
            on_click=lambda: self._save_review_ink_to_note(clear_ink=False),
            border_color_hex=sk_border
        )
        self._floating_save_keep_button.move(220, 15)
        self._floating_save_keep_button.hide()

        # Proximity detection timer for drawing/mouse near floating buttons
        self._save_buttons_slide_visible = False
        self._mouse_left_buttons_time = None
        self._proximity_timer = QTimer(self)
        self._proximity_timer.setInterval(100)
        self._proximity_timer.timeout.connect(self._check_floating_button_proximity)
        self._proximity_timer.start()

        self._floating_timer_frame = None
        self._floating_timer_mask = None
        self._floating_timer_session = None
        self._floating_timer_today = None
        self._floating_timer_queue = None
        if self._stimer:
            floating_timer = DraggableFrame(
                self._canvas_stage,
                on_release=self._save_floating_timer_position
            )
            floating_timer.setToolTip("Study timer")
            if dojo:
                floating_timer.setStyleSheet(
                    f"QFrame{{background:rgba(7,7,11,80);"
                    f"border:1px solid {border};border-radius:2px;}}"
                )
            else:
                floating_timer.setStyleSheet(
                    f"QFrame{{background:rgba(30,30,46,80);"
                    f"border:1px solid {border};border-radius:6px;}}"
                )
            ft_l = QVBoxLayout(floating_timer)
            ft_l.setContentsMargins(8, 5, 8, 5)
            ft_l.setSpacing(0)
            self._floating_timer_mask = QLabel(self._stimer.label_mask.text())
            self._floating_timer_session = QLabel(self._stimer.label_session.text())
            self._floating_timer_today = QLabel(self._stimer.label_today.text())
            self._floating_timer_queue = QLabel(
                f"QUEUE ({self._active_queue_count()})"
            )
            self._floating_timer_mask.setToolTip("Time spent on current question")
            self._floating_timer_session.setToolTip("Current review session time")
            self._floating_timer_today.setToolTip("Total focus time today")
            if dojo:
                is_ps = (font == "Press Start 2P")
                fw = "normal" if is_ps else "bold"
                q_sz = "8px" if is_ps else "10px"
                self._floating_timer_mask.setStyleSheet(
                    f"color:{orange};background:transparent;border:none;"
                    f"font-size:{self.FLOATING_TIMER_MASK_FONT_PX}px;"
                    f"font-weight:{fw};font-family:{font};"
                )
                self._floating_timer_session.setStyleSheet(
                    f"color:{accent};background:transparent;border:none;"
                    f"font-size:{self.FLOATING_TIMER_SESSION_FONT_PX}px;"
                    f"font-weight:{fw};font-family:{font};"
                )
                self._floating_timer_today.setStyleSheet(
                    f"color:{accent2};background:transparent;border:none;"
                    f"font-size:{self.FLOATING_TIMER_TODAY_FONT_PX}px;"
                    f"font-weight:{fw};font-family:{font};"
                )
                self._floating_timer_queue.setStyleSheet(
                    f"color:{subtext};background:transparent;border:none;"
                    f"font-size:{q_sz};font-weight:{fw};font-family:{font};"
                )
            else:
                self._floating_timer_mask.setStyleSheet(
                    f"color:{orange};background:transparent;border:none;"
                    f"font-size:{self.FLOATING_TIMER_MASK_FONT_PX}px;"
                    "font-weight:bold;"
                    "font-family:'Segoe UI Mono','Courier New',monospace;"
                )
                self._floating_timer_session.setStyleSheet(
                    "color:#CDD6F4;background:transparent;border:none;"
                    f"font-size:{self.FLOATING_TIMER_SESSION_FONT_PX}px;"
                    "font-weight:bold;"
                    "font-family:'Segoe UI Mono','Courier New',monospace;"
                )
                self._floating_timer_today.setStyleSheet(
                    f"color:{subtext};background:transparent;border:none;"
                    f"font-size:{self.FLOATING_TIMER_TODAY_FONT_PX}px;"
                    "font-weight:bold;"
                    "font-family:'Segoe UI Mono','Courier New',monospace;"
                )
                self._floating_timer_queue.setStyleSheet(
                    f"color:{subtext};background:transparent;border:none;"
                    "font-size:11px;font-weight:bold;"
                    "font-family:'Segoe UI Mono','Courier New',monospace;"
                )
            ft_l.addWidget(self._floating_timer_mask)
            ft_l.addWidget(self._floating_timer_session)
            ft_l.addWidget(self._floating_timer_today)
            ft_l.addWidget(self._floating_timer_queue)
            floating_timer.hide()
            self._floating_timer_frame = floating_timer
            self._floating_timer_sync_timer = QTimer(self)
            self._floating_timer_sync_timer.setInterval(1000)
            self._floating_timer_sync_timer.timeout.connect(self._sync_floating_timer)

        # ── Queue panel (right sidebar) ───────────────────────────────────────
        queue_panel = QWidget()
        queue_panel.setFixedWidth(200)
        queue_panel.hide()
        if dojo:
            queue_panel.setStyleSheet(
                f"background:{surface};border-left:1px solid {border};"
            )
        else:
            queue_panel.setStyleSheet(f"background:{surface};")
        qp_l = QVBoxLayout(queue_panel)
        qp_l.setContentsMargins(6, 8, 6, 8)
        qp_l.setSpacing(4)

        self._queue_timer_count = None
        if self._stimer:
            timer_frame = QFrame()
            if dojo:
                timer_frame.setStyleSheet(
                    f"QFrame{{background:{card};border-radius:2px;"
                    f"border:1px solid {border};}}"
                )
            else:
                timer_frame.setStyleSheet(
                    f"QFrame{{background:{card};border-radius:8px;"
                    f"border:1px solid {border};}}"
                )
            tf_l = QVBoxLayout(timer_frame)
            tf_l.setContentsMargins(8, 6, 8, 6)
            tf_l.setSpacing(2)

            tf_mask = QLabel("CURRENT QUESTION" if dojo else "Current question")
            tf_top = QLabel("CURRENT SESSION" if dojo else "Current session")
            tf_bot = QLabel("TODAY'S FOCUS" if dojo else "Today's focus")
            self._queue_timer_count = QLabel(
                f"TO REVIEW: {self._active_queue_count()}"
            )
            if dojo:
                tf_mask.setStyleSheet(
                    f"color:{subtext};font-size:7px;font-weight:bold;"
                    f"background:transparent;border:none;"
                    f"font-family:{font};letter-spacing:1.5px;"
                )
                tf_top.setStyleSheet(
                    f"color:{subtext};font-size:7px;font-weight:bold;"
                    f"background:transparent;border:none;"
                    f"font-family:{font};letter-spacing:1.5px;margin-top:4px;"
                )
                tf_bot.setStyleSheet(
                    f"color:{subtext};font-size:7px;font-weight:bold;"
                    f"background:transparent;border:none;"
                    f"font-family:{font};letter-spacing:1.5px;margin-top:4px;"
                )
                self._queue_timer_count.setStyleSheet(
                    f"color:{subtext};font-size:8px;font-weight:bold;"
                    f"background:transparent;border:none;font-family:{font};margin-top:4px;"
                )
                self._stimer.label_mask.setStyleSheet(
                    f"background:transparent;color:{orange};"
                    f"font-size:16px;font-weight:bold;"
                    f"font-family:{font};border:none;"
                )
                self._stimer.label_session.setStyleSheet(
                    f"background:transparent;color:{accent};"
                    f"font-size:16px;font-weight:bold;"
                    f"font-family:{font};border:none;"
                )
                self._stimer.label_today.setStyleSheet(
                    f"background:transparent;color:{accent2};"
                    f"font-size:14px;font-weight:bold;"
                    f"font-family:{font};border:none;"
                )
            else:
                tf_mask.setStyleSheet(
                    f"color:{subtext};font-size:10px;"
                    f"font-weight:bold;background:transparent;border:none;"
                )
                tf_top.setStyleSheet(
                    f"color:{subtext};font-size:10px;"
                    f"font-weight:bold;background:transparent;border:none;margin-top:4px;"
                )
                tf_bot.setStyleSheet(
                    f"color:{subtext};font-size:10px;"
                    f"font-weight:bold;background:transparent;border:none;margin-top:4px;"
                )
                self._queue_timer_count.setStyleSheet(
                    f"color:{subtext};font-size:10px;"
                    f"font-weight:bold;background:transparent;border:none;margin-top:4px;"
                )
                self._stimer.label_mask.setStyleSheet(
                    f"background:transparent;color:{orange};"
                    f"font-size:16px;font-weight:bold;"
                    f"font-family:'Segoe UI Mono','Courier New',monospace;"
                    f"border:none;"
                )
                self._stimer.label_session.setStyleSheet(
                    f"background:transparent;color:#CDD6F4;"
                    f"font-size:16px;font-weight:bold;"
                    f"font-family:'Segoe UI Mono','Courier New',monospace;"
                    f"border:none;"
                )
                self._stimer.label_today.setStyleSheet(
                    f"background:transparent;color:{subtext};"
                    f"font-size:14px;font-weight:bold;"
                    f"font-family:'Segoe UI Mono','Courier New',monospace;"
                    f"border:none;"
                )

            tf_l.addWidget(tf_mask)
            tf_l.addWidget(self._stimer.label_mask)
            tf_l.addWidget(tf_top)
            tf_l.addWidget(self._stimer.label_session)
            tf_l.addWidget(tf_bot)
            tf_l.addWidget(self._stimer.label_today)
            tf_l.addWidget(self._queue_timer_count)
            qp_l.addWidget(timer_frame)
            qp_l.addSpacing(6)

        queue_header = QWidget()
        queue_header_l = QHBoxLayout(queue_header)
        queue_header_l.setContentsMargins(0, 0, 0, 0)
        queue_header_l.setSpacing(4)

        self._queue_label = QLabel("▸  QUEUE" if dojo else "📋  Queue")
        if dojo:
            self._queue_label.setStyleSheet(
                f"color:{accent};font-size:8px;font-weight:bold;"
                f"font-family:{font};letter-spacing:2px;"
                f"padding-bottom:4px;"
            )
        else:
            self._queue_label.setStyleSheet(
                f"color:{subtext};font-size:11px;font-weight:bold;"
                f"padding-bottom:4px;"
            )
        queue_header_l.addWidget(self._queue_label, stretch=1)

        def _queue_icon_button(label, tip):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setFixedSize(26, 24)
            b.setFocusPolicy(Qt.NoFocus)
            if dojo:
                b.setStyleSheet(
                    f"QPushButton{{background:{card};color:{accent};"
                    f"border:1px solid {border};border-radius:2px;"
                    f"font-size:11px;padding:0;}}"
                    f"QPushButton:hover{{border:1px solid {accent};}}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton{{background:{card};color:{text};"
                    f"border:1px solid {border};border-radius:5px;"
                    f"font-size:12px;padding:0;}}"
                    f"QPushButton:hover{{background:{surface};}}"
                )
            return b

        self._queue_lock_button = _queue_icon_button("🔒", "Lock queue open")
        self._queue_hide_button = _queue_icon_button("›", "Hide queue")
        self._queue_lock_button.clicked.connect(self._toggle_queue_lock)
        self._queue_hide_button.clicked.connect(self._toggle_queue_drawer)
        queue_header_l.addWidget(self._queue_lock_button)
        queue_header_l.addWidget(self._queue_hide_button)
        if dojo:
            queue_header.setStyleSheet(f"border-bottom:1px solid {border};")
        else:
            queue_header.setStyleSheet(f"border-bottom:1px solid {border};")
        qp_l.addWidget(queue_header)

        self._queue_list = QListWidget()
        self._queue_list.setItemDelegate(QueueDelegate(self._queue_list))
        self._queue_list.setFocusPolicy(Qt.NoFocus)
        self._queue_list.itemClicked.connect(self._on_queue_item_clicked)
        self._queue_list.setStyleSheet(
            f"QListWidget{{background:{surface};border:none;padding:0;}}"
            f"QListWidget::item{{padding:0;}}"
        )
        qp_l.addWidget(self._queue_list, stretch=1)

        self._queue_panel = queue_panel
        self._queue_panel_docked = True
        mid_widget = QWidget()
        mid_l = QHBoxLayout(mid_widget)
        mid_l.setContentsMargins(0, 0, 0, 0)
        mid_l.setSpacing(0)
        mid_l.addWidget(self._canvas_stage, stretch=1)
        mid_l.addWidget(queue_panel)
        self._mid_widget = mid_widget
        self._mid_layout = mid_l
        L.addWidget(mid_widget, stretch=1)

        self._queue_edge_button = QPushButton("‹", self)
        self._queue_edge_button.setToolTip("Show queue")
        self._queue_edge_button.setFocusPolicy(Qt.NoFocus)
        self._queue_edge_button.setStyleSheet(
            f"QPushButton{{background:{accent};color:{bg};"
            f"border:1px solid {border};border-radius:6px;"
            f"font-size:22px;font-weight:bold;padding:0;}}"
            f"QPushButton:hover{{background:white;color:{bg};}}"
        )
        self._queue_edge_button.clicked.connect(self._open_queue_drawer)
        self._queue_edge_button.hide()
        self._apply_queue_drawer_state(recenter=False)
        QTimer.singleShot(0, self._finish_initial_overlay_placement)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bottom_w = QWidget()
        if dojo:
            bottom_w.setStyleSheet(
                f"background:{surface};border-top:1px solid {border};"
            )
        else:
            bottom_w.setStyleSheet(f"background:{surface};")
        bl = QVBoxLayout(bottom_w)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        hint_text = (
            "SPACE=REVEAL  •  1/2/3/4=RATE  •  C=FIT  •  N=NOTE  •  D=DEBUG  •  "
            "CTRL+SCROLL=ZOOM  •  H=PAN  •  L=COPY PDF  •  CTRL+L=OPEN FOLDER  •  "
            "ALT/P=PEN  •  X=COLOR  •  +/-=SIZE  •  DEL=CLEAR  •  F11"
            if dojo
            else "Space = reveal  •  1/2/3/4 = rate  •  C = fit+center  •  N = note  •  D = debug  •  "
            "Ctrl+Scroll = zoom  •  H = pan  •  L = copy PDF  •  Ctrl+L = open folder  •  "
            "Alt/P = pen  •  X = color  •  +/- = size  •  Del = clear pen  •  F11"
        )
        hint = QLabel(hint_text)
        self._hint_label = hint
        hint.setAlignment(Qt.AlignCenter)
        hint.setFixedHeight(22)
        if dojo:
            hint.setStyleSheet(
                f"color:{subtext};font-size:7px;"
                f"font-family:{font};letter-spacing:0.5px;"
                f"border-top:1px solid {border};padding:2px;"
            )
        else:
            hint.setStyleSheet(
                f"color:{subtext};font-size:11px;"
                f"border-top:1px solid {border};padding:2px;"
            )
        bl.addWidget(hint)
        self._hint_label = hint
        self._hint_label.hide()

        # ── Waiting state bar ─────────────────────────────────────────────────
        self._wait_bar = QFrame()
        self._wait_bar.setStyleSheet(f"QFrame{{background:{bg};}}")
        wb_l = QVBoxLayout(self._wait_bar)
        wb_l.setContentsMargins(0, 16, 0, 16)
        wb_l.setSpacing(6)
        self._wait_lbl_count = QLabel("")
        self._wait_lbl_count.setAlignment(Qt.AlignCenter)
        if dojo:
            self._wait_lbl_count.setStyleSheet(
                f"color:{accent};font-size:11px;font-weight:bold;"
                f"background:transparent;font-family:{font};letter-spacing:1px;"
            )
        else:
            self._wait_lbl_count.setStyleSheet(
                f"color:{text};font-size:14px;font-weight:bold;background:transparent;"
            )
        self._wait_lbl_countdown = QLabel("")
        self._wait_lbl_countdown.setAlignment(Qt.AlignCenter)
        self._wait_lbl_countdown.setStyleSheet(
            f"color:{subtext};font-size:12px;background:transparent;"
        )
        wb_l.addWidget(self._wait_lbl_count)
        wb_l.addWidget(self._wait_lbl_countdown)
        self._wait_bar.hide()
        bl.addWidget(self._wait_bar)
        L.addWidget(bottom_w)

        control_metrics = self._review_control_metrics(dojo)

        # ── Floating overlay: Show Answer button ──────────────────────────────
        self._reveal_bar = QFrame(self._canvas_stage)
        self._reveal_bar.setStyleSheet("QFrame{background:transparent;border:none;}")
        rb_l = QHBoxLayout(self._reveal_bar)
        rb_l.setContentsMargins(0, 0, 0, 20)
        rb_l.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        b_rev = QPushButton("👁  Show Answer  [Space]")
        b_rev.setMinimumHeight(control_metrics["reveal_min_height"])
        if dojo:
            b_rev.setStyleSheet(
                f"background:rgba(7,7,11,210);color:{accent};"
                f"border:1px solid {accent};border-radius:2px;"
                f"padding:{control_metrics['reveal_padding_y']}px "
                f"{control_metrics['reveal_padding_x']}px;"
                f"font-size:{control_metrics['reveal_font']}px;font-weight:900;"
                f"font-family:{font};letter-spacing:1px;"
            )
        else:
            b_rev.setStyleSheet(
                f"background:rgba(42,42,62,220);color:{text};"
                f"border:1px solid {border};border-radius:8px;"
                f"padding:{control_metrics['reveal_padding_y']}px "
                f"{control_metrics['reveal_padding_x']}px;"
                f"font-size:{control_metrics['reveal_font']}px;font-weight:bold;"
            )
        b_rev.clicked.connect(self._reveal_current)
        rb_l.addWidget(b_rev)

        # Add Skip Session button to reveal bar
        b_skip = QPushButton("⏭️ Skip  [S]")
        b_skip.setMinimumHeight(control_metrics["reveal_min_height"])
        if dojo:
            b_skip.setStyleSheet(
                f"background:rgba(7,7,11,210);color:{subtext};"
                f"border:1px solid {border};border-radius:2px;"
                f"padding:{control_metrics['reveal_padding_y']}px 20px;"
                f"font-size:{control_metrics['reveal_font']}px;font-weight:900;"
                f"font-family:{font};letter-spacing:1px;"
            )
        else:
            b_skip.setStyleSheet(
                f"background:rgba(42,42,62,220);color:{text};"
                f"border:1px solid {border};border-radius:8px;"
                f"padding:{control_metrics['reveal_padding_y']}px 20px;"
                f"font-size:{control_metrics['reveal_font']}px;font-weight:bold;"
            )
        b_skip.clicked.connect(self._skip_session)
        rb_l.addWidget(b_skip)

        # Add Super Skip button to reveal bar
        b_super = QPushButton("🌀 Super Skip  [Alt+S]")
        b_super.setMinimumHeight(control_metrics["reveal_min_height"])
        if dojo:
            b_super.setStyleSheet(
                f"background:rgba(7,7,11,210);color:{accent2};"
                f"border:1px solid {accent2};border-radius:2px;"
                f"padding:{control_metrics['reveal_padding_y']}px 20px;"
                f"font-size:{control_metrics['reveal_font']}px;font-weight:900;"
                f"font-family:{font};letter-spacing:1px;"
            )
        else:
            b_super.setStyleSheet(
                f"background:rgba(42,42,62,220);color:{accent2};"
                f"border:1px solid {border};border-radius:8px;"
                f"padding:{control_metrics['reveal_padding_y']}px 20px;"
                f"font-size:{control_metrics['reveal_font']}px;font-weight:bold;"
            )
        b_super.clicked.connect(self._super_skip)
        rb_l.addWidget(b_super)

        self._reveal_button = b_rev
        self._reveal_bar.hide()

        # ── Floating overlay: Rating buttons ──────────────────────────────────
        self._rating_frame = QFrame(self._canvas_stage)
        self._rating_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        rfl = QHBoxLayout(self._rating_frame)
        rfl.setContentsMargins(0, 0, 0, 0)
        rfl.setSpacing(control_metrics["rating_spacing"])
        rfl.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        RATING_COLORS = {
            "danger": ("#FF5555", "#FF8888", "#CC2222"),
            "hard": ("#E08030", "#FFB060", "#B05010"),
            "success": ("#50FA7B", "#80FFB0", "#20C040"),
            "warning": ("#4DC4FF", "#88DDFF", "#1A88CC"),
            "perfect": ("#BD93F9", "#D6B8FF", "#8F5CE6"),
        }
        RATING_COLORS_DOJO = {
            "danger": (p.get("C_RED", "#FF4444"), "#FF7777", "#CC1111"),
            "hard": (p.get("C_ORANGE", "#FF8C00"), "#FFB347", "#CC6600"),
            "success": (p.get("C_GREEN", "#72FF4F"), "#A0FF80", "#44CC20"),
            "warning": (p.get("C_PURPLE", "#A86CFF"), "#C899FF", "#7040CC"),
            "perfect": (p.get("C_YELLOW", "#FFD700"), "#FFE866", "#CCAA00"),
        }

        self._rating_btns = []
        self._prev_lbls = []
        color_map = RATING_COLORS_DOJO if dojo else RATING_COLORS
        for (orig_lbl, obj, q), color_lbl in zip(self.RATINGS, self.RATING_LABELS):
            bg_r, fg_hover, _ = color_map.get(obj, ("#555", "#FFF", "#333"))
            btn = QPushButton(
                f"{orig_lbl.split()[0]}  {orig_lbl.split()[1]}  ?  {color_lbl}"
            )
            btn.setFixedHeight(control_metrics["rating_height"])
            btn.setMinimumWidth(control_metrics["rating_min_width"])
            if dojo:
                btn.setStyleSheet(
                    f"QPushButton{{background:rgba(7,7,11,200);color:{bg_r};"
                    f"border:1px solid {bg_r};border-radius:2px;"
                    f"font-size:{control_metrics['rating_font']}px;font-weight:900;"
                    f"padding:0 {control_metrics['rating_padding_x']}px;"
                    f"font-family:{font};letter-spacing:0.5px;}}"
                    f"QPushButton:hover{{background:{bg_r};color:{bg};}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{bg_r};color:#1E1E2E;"
                    f"border:none;border-radius:8px;"
                    f"font-size:{control_metrics['rating_font']}px;font-weight:bold;"
                    f"padding:0 {control_metrics['rating_padding_x']}px;}}"
                    f"QPushButton:hover{{background:{fg_hover};color:#111;}}"
                )
            btn.clicked.connect(lambda _, qq=q: self._rate(qq))
            rfl.addWidget(btn)
            self._rating_btns.append(btn)
            self._prev_lbls.append((btn, q))

        # Add Skip Session button to rating frame
        b_skip_rate = QPushButton("⏭️ Skip  [S]")
        b_skip_rate.setFixedHeight(control_metrics["rating_height"])
        if dojo:
            b_skip_rate.setStyleSheet(
                f"QPushButton{{background:rgba(7,7,11,200);color:{subtext};"
                f"border:1px solid {border};border-radius:2px;"
                f"font-size:{control_metrics['rating_font']}px;font-weight:900;"
                f"padding:0 16px;"
                f"font-family:{font};letter-spacing:0.5px;}}"
                f"QPushButton:hover{{background:{border};color:{bg};}}"
            )
        else:
            b_skip_rate.setStyleSheet(
                f"QPushButton{{background:{surface};color:{text};"
                f"border:1px solid {border};border-radius:8px;"
                f"font-size:{control_metrics['rating_font']}px;font-weight:bold;"
                f"padding:0 16px;}}"
                f"QPushButton:hover{{background:{border};color:{text};}}"
            )
        b_skip_rate.clicked.connect(self._skip_session)
        rfl.addWidget(b_skip_rate)

        # Add Super Skip button to rating frame
        b_super_rate = QPushButton("🌀 Super Skip  [Alt+S]")
        b_super_rate.setFixedHeight(control_metrics["rating_height"])
        if dojo:
            b_super_rate.setStyleSheet(
                f"QPushButton{{background:rgba(7,7,11,200);color:{accent2};"
                f"border:1px solid {accent2};border-radius:2px;"
                f"font-size:{control_metrics['rating_font']}px;font-weight:900;"
                f"padding:0 16px;"
                f"font-family:{font};letter-spacing:0.5px;}}"
                f"QPushButton:hover{{background:{accent2};color:{bg};}}"
            )
        else:
            b_super_rate.setStyleSheet(
                f"QPushButton{{background:{surface};color:{accent2};"
                f"border:1.5px solid {accent2};border-radius:8px;"
                f"font-size:{control_metrics['rating_font']}px;font-weight:bold;"
                f"padding:0 16px;}}"
                f"QPushButton:hover{{background:{accent2};color:white;}}"
            )
        b_super_rate.clicked.connect(self._super_skip)
        rfl.addWidget(b_super_rate)

        self._rating_frame.hide()
        self._mid_row_widget = self._reveal_bar

        # CRT and Particle Burst overlays
        self.crt = None
        self.burst = None
        from theme_manager import is_retro_theme
        if is_retro_theme(theme):
            self.crt = CRTOverlay(self)
            self.burst = ParticleBurstOverlay(self)

    def _update_ink_hint(self):
        """Canvas toasts handle the visible pen status in review mode."""
        pass

    def _zoom_hint_in(self):
        if self._hint_font_size < 40:
            self._hint_font_size += 1
            self._apply_hint_font_size()

    def _zoom_hint_out(self):
        if self._hint_font_size > 8:
            self._hint_font_size -= 1
            self._apply_hint_font_size()

    def _zoom_hint_reset(self):
        self._hint_font_size = 14
        self._apply_hint_font_size()

    def _apply_hint_font_size(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        text_color = p.get("C_TEXT", "#CDD6F4")
        surface_color = p.get("C_SURFACE", "#1E1E2E")
        subtext_color = p.get("C_SUBTEXT", "#A6ADC8")
        accent_color = p.get("C_ACCENT", "#7C6AF7")
        
        scrollbar_style = (
            f"QTextBrowser {{ background: transparent; color: {text_color}; border: none; font-size: {self._hint_font_size}px; line-height: 1.4; }}"
            f"QScrollBar:vertical {{"
            f"    background: {surface_color};"
            f"    width: 10px;"
            f"    border-radius: 5px;"
            f"    margin: 0px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"    background: {subtext_color};"
            f"    min-height: 20px;"
            f"    border-radius: 5px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"    background: {accent_color};"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"    background: none;"
            f"    height: 0px;"
            f"}}"
        )
        self._hint_browser.setStyleSheet(scrollbar_style)
        
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/hint_font_size", self._hint_font_size)
        settings.sync()
        
        if self._hint_panel.isVisible():
            self._update_mask_note_ui(keep_visible=True)

    def _on_hint_panel_resize(self, new_width):
        self._user_hint_width = new_width
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/hint_panel_width", self._user_hint_width)
        settings.sync()
        self._reposition_hint_panel()
        if hasattr(self, "_hint_panel") and self._hint_panel is not None and self._hint_panel.isVisible():
            self._update_mask_note_ui(keep_visible=True)

    def _reposition_hint_panel(self):
        if not hasattr(self, "_hint_panel") or self._hint_panel is None:
            return
        w = self._canvas_stage.width()
        h = self._canvas_stage.height()
        panel_w = getattr(self, "_user_hint_width", 360)
        self._hint_panel.setGeometry(w - panel_w, 0, panel_w, h)
        if hasattr(self, "_resize_handle"):
            self._resize_handle.setGeometry(0, 0, 6, h)

    def _update_hint_scroll_indicators(self):
        pass

    def _activate_default_review_pen(self):
        canvas = self.__dict__.get("canvas", None)
        if canvas is None:
            return
        canvas._ink_width = float(self.__dict__.get("_review_ink_width", 1.2))
        if "_review_ink_colors" in self.__dict__:
            canvas._ink_colors = list(self.__dict__["_review_ink_colors"])
        if "_review_ink_color_idx" in self.__dict__:
            canvas._ink_color_idx = int(self.__dict__["_review_ink_color_idx"])
        if hasattr(canvas, "ink_set_active"):
            canvas.ink_set_active(True)
        else:
            canvas._ink_active = True

    def _load_review_ink_width(self):
        raw = QSettings("AnkiOcclusion", "App").value("review/ink_width", 1.2)
        try:
            width = float(raw)
        except (TypeError, ValueError):
            width = 1.2
        width = max(0.4, min(12.0, width))
        return width

    def _save_review_ink_width(self):
        width = max(0.4, min(12.0, float(self._review_ink_width)))
        self._review_ink_width = width
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/ink_width", width)
        settings.sync()

    def _capture_review_ink_width(self, reason=""):
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        self._review_ink_width = float(
            getattr(canvas, "_ink_width", self._review_ink_width)
        )
        self._save_review_ink_width()

    def _load_review_ink_color(self):
        settings = QSettings("AnkiOcclusion", "App")
        colors = settings.value("review/ink_colors", ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"])
        if isinstance(colors, str):
            import json
            try:
                colors = json.loads(colors)
            except Exception:
                colors = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]
        elif not isinstance(colors, list):
            colors = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]
        colors = [str(c).upper() for c in colors if c]
        if not colors:
            colors = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]

        idx = settings.value("review/ink_color_idx", 0)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        if idx < 0 or idx >= len(colors):
            idx = 0
        return colors, idx

    def _save_review_ink_color(self):
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        colors = list(canvas._ink_colors)
        idx = int(canvas._ink_color_idx)
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/ink_colors", colors)
        settings.setValue("review/ink_color_idx", idx)
        settings.sync()

    def _on_hide_all_toggled(self):
        if self._act_hide_all.isChecked():
            self.canvas.set_review_style("hide_all")
        else:
            self.canvas.set_review_style("hide_one")

    def _on_summary_toggled(self):
        self._show_summary_popup = self._act_summary.isChecked()
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("review/show_summary_popup", self._show_summary_popup)
        settings.sync()

    def _update_options_menu_states(self):
        is_hide_all = self.canvas._review_mode_style == "hide_all" if getattr(self, "canvas", None) is not None else True
        self._act_hide_all.setChecked(is_hide_all)
        if hasattr(self, "_act_ultra_focus"):
            is_ultra = (getattr(self.canvas, "_ultra_focus_mode", False) is True) if getattr(self, "canvas", None) is not None else False
            self._act_ultra_focus.setChecked(is_ultra)
        self._act_summary.setChecked(self._show_summary_popup)
        is_cache_visible = self._cache_panel.isVisible() if getattr(self, "_cache_panel", None) is not None else False
        self._act_cache.setChecked(is_cache_visible)

    def _toggle_auto_reveal(self):
        from data_manager import store
        enabled = self._btn_auto_reveal.isChecked()
        store.get()["_auto_reveal"] = enabled
        store.mark_dirty()
        if enabled and self._reveal_bar.isVisible():
            self._reveal_current()

    def _maybe_auto_reveal(self):
        from data_manager import store
        if store.get().get("_auto_reveal", False):
            QTimer.singleShot(60, self._reveal_current)

    def _on_canvas_zoom_settled(self):
        """Ctrl+scroll zoom settle hone ke baad — user zoom yaad rakho."""
        self._user_zoom_scale = self.canvas._scale

    def _zoom_fit(self):
        vp = self._canvas_scroll.viewport()
        if self.canvas._pages:
            self._pdf_viewer.reset_fit()
            return
        w, h = self.canvas._canvas_wh()
        if w < 1 or h < 1:
            return
        card = self._items[self._idx][0] if (0 <= self._idx < len(self._items)) else None
        if card and card.get("card_type") == "text":
            avail_w = max(vp.width() - 40, 1)
            avail_h = max(vp.height() - 20, 1)
            scale = min(avail_w / w, avail_h / h)
            self.canvas._scale = max(0.5, min(scale, 1.25))
            self.canvas._on_zoom()
            return
        available_w = max(vp.width(), 1)
        self.canvas._scale = available_w / w
        if self._review_verbose_debug_enabled():
            print(
                "[DEBUG][review_image_fit] "
                f"img={w}x{h} viewport={vp.width()}x{vp.height()} "
                f"scale={self.canvas._scale:.4f}"
            )
        self.canvas._on_zoom()

    def _update_review_page_nav_ui(self, *_):
        self._pdf_viewer.refresh_page_ui()
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
        has_pages = self._pdf_viewer.page_count() > 0
        if hasattr(self, "_btn_invert_pdf"):
            self._btn_invert_pdf.setVisible(has_pages)
            self._update_invert_pdf_button_style()

    def _update_invert_pdf_button_style(self):
        if not hasattr(self, "_btn_invert_pdf"):
            return
        from data_manager import store
        invert = store.get().get("_invert_pdf", False)
        dojo = _is_dojo()
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = _get_palette(theme)
        card = p["C_CARD"]
        accent = p["C_ACCENT"]
        border = p["C_BORDER"]
        text = p["C_TEXT"]
        surface = p["C_SURFACE"]
        is_cyan = theme in ("manhattan", "tmnt")
        hover_bg = "rgba(0,240,255,0.12)" if is_cyan else "rgba(114,255,79,0.12)"
        
        if invert:
            if dojo:
                self._btn_invert_pdf.setStyleSheet(
                    f"QPushButton{{background:{accent};color:{p['C_BG']};"
                    f"border:1px solid {accent};border-radius:2px;font-size:13px;}}"
                )
            else:
                self._btn_invert_pdf.setStyleSheet(
                    f"QPushButton{{background:{accent};color:white;"
                    f"border:1px solid {accent};border-radius:5px;font-size:13px;}}"
                )
        else:
            if dojo:
                self._btn_invert_pdf.setStyleSheet(
                    f"QPushButton{{background:{card};color:{accent};"
                    f"border:1px solid {border};border-radius:2px;font-size:13px;}}"
                    f"QPushButton:hover{{background:{hover_bg};"
                    f"border:1px solid {accent};}}"
                )
            else:
                self._btn_invert_pdf.setStyleSheet(
                    f"QPushButton{{background:{card};color:{text};"
                    f"border:1px solid {border};border-radius:5px;font-size:13px;}}"
                    f"QPushButton:hover{{background:{surface};}}"
                )

    def _toggle_pdf_contrast(self):
        from data_manager import store
        invert = not store.get().get("_invert_pdf", False)
        store.get()["_invert_pdf"] = invert
        store.mark_dirty()
        
        self._update_invert_pdf_button_style()
        if self.canvas._px is not None and not self.canvas._px.isNull():
            from PyQt5.QtGui import QImage
            img = self.canvas._px.toImage()
            img.invertPixels(QImage.InvertRgb)
            self.canvas.load_pixmap(QPixmap.fromImage(img))
        else:
            self._reload_pdf_contrast()

    def _toggle_focus_mode(self):
        enabled = not (getattr(self.canvas, "_focus_mode", False) is True)
        self.canvas.set_focus_mode(enabled)
        self._update_focus_mode_button_style()
        self.canvas._show_toast(
            f"🌫️ Focus Mode {'ON' if enabled else 'OFF'} (Opacity: {int(self.canvas.get_bg_opacity() * 100)}%)"
        )

    def _toggle_ultra_focus_mode(self):
        enabled = not (getattr(self.canvas, "_ultra_focus_mode", False) is True)
        self.canvas.set_ultra_focus_mode(enabled)
        self._update_focus_mode_button_style()
        self.canvas._show_toast(
            f"⚡ Ultra Focus Mode {'ON' if enabled else 'OFF'}"
        )

    def _adjust_focus_opacity(self, delta: float):
        if not (getattr(self.canvas, "_focus_mode", False) is True):
            self.canvas.set_focus_mode(True)
            self._update_focus_mode_button_style()
        new_op = self.canvas.get_bg_opacity() + delta
        self.canvas.set_bg_opacity(new_op)
        self.canvas._show_toast(f"🌫️ Focus Opacity: {int(self.canvas.get_bg_opacity() * 100)}%")

    def _update_focus_mode_button_style(self):
        if hasattr(self, "_btn_focus_canvas"):
            enabled = (getattr(self.canvas, "_focus_mode", False) is True) if getattr(self, "canvas", None) is not None else False
            self._btn_focus_canvas.setChecked(enabled)
        if hasattr(self, "_btn_ultra_focus"):
            ultra_enabled = (getattr(self.canvas, "_ultra_focus_mode", False) is True) if getattr(self, "canvas", None) is not None else False
            self._btn_ultra_focus.setChecked(ultra_enabled)
        if hasattr(self, "_act_ultra_focus"):
            ultra_enabled = (getattr(self.canvas, "_ultra_focus_mode", False) is True) if getattr(self, "canvas", None) is not None else False
            self._act_ultra_focus.setChecked(ultra_enabled)

    def _toggle_pen_drawing(self):
        active = getattr(self.canvas, "_ink_active", False)
        mode = self.canvas.ink_get_mode() if hasattr(self.canvas, "ink_get_mode") else "pen"
        
        if not active:
            self.canvas.ink_set_active(True)
        else:
            if mode == "pen":
                self.canvas.ink_set_active(False)
            else:
                self.canvas.ink_set_mode("pen")
                
        active = self.canvas._ink_active
        color = self.canvas._ink_colors[self.canvas._ink_color_idx]
        self.canvas._show_toast(
            f"✏ Pen {'ON' if active and self.canvas.ink_get_mode() == 'pen' else 'OFF'}  {color if active and self.canvas.ink_get_mode() == 'pen' else ''}"
        )
        self._update_ink_hint()
        self._update_pen_button_states()

    def _toggle_eraser(self):
        active = getattr(self.canvas, "_ink_active", False)
        mode = self.canvas.ink_get_mode() if hasattr(self.canvas, "ink_get_mode") else "pen"
        
        if not active:
            self.canvas.ink_set_active(True)
            self.canvas.ink_set_mode("eraser")
        else:
            if mode == "eraser":
                self.canvas.ink_set_active(False)
            else:
                self.canvas.ink_set_mode("eraser")
                
        self._update_ink_hint()
        self._update_pen_button_states()

    def _choose_pen_color_picker(self):
        from PyQt5.QtWidgets import QColorDialog
        from PyQt5.QtGui import QColor
        current_color = QColor(self.canvas._ink_colors[self.canvas._ink_color_idx])
        chosen = QColorDialog.getColor(current_color, self, "Choose Pen Color")
        if chosen.isValid():
            chosen_hex = chosen.name().upper()
            if chosen_hex in self.canvas._ink_colors:
                self.canvas._ink_color_idx = self.canvas._ink_colors.index(chosen_hex)
            else:
                self.canvas._ink_colors.append(chosen_hex)
                self.canvas._ink_color_idx = len(self.canvas._ink_colors) - 1
            self._review_ink_colors = list(self.canvas._ink_colors)
            self._review_ink_color_idx = int(self.canvas._ink_color_idx)
            self._save_review_ink_color()
            if hasattr(self, "_text_review_widget") and hasattr(self._text_review_widget, "scratchpad"):
                self._text_review_widget.scratchpad.active_color = chosen
            self.canvas._show_toast(f"✏ Ink Color: {chosen_hex}")
            self._update_pen_button_states()

    def _clear_pen_strokes(self):
        self.canvas.ink_clear()
        if hasattr(self, "_text_review_widget") and hasattr(self._text_review_widget, "scratchpad"):
            self._text_review_widget.scratchpad.clear()

    def _on_review_pen_perf_changed(self, idx):
        _idx_to_impl = {0: "classic", 1: "incremental", 2: "polyline", 3: "filtered"}
        impl = _idx_to_impl.get(idx, "classic")
        self._review_pen_implementation = impl
        self.canvas._ink_implementation = impl
        
        from PyQt5.QtCore import QSettings
        QSettings("AnkiOcclusion", "App").setValue("review/pen_implementation", impl)
        
        _names = {
            "classic": "Classic Smooth",
            "incremental": "Incremental Bezier",
            "polyline": "Raw Polyline",
            "filtered": "Distance-Filtered"
        }
        name = _names.get(impl, "Classic Smooth")
        self.canvas._show_toast(f"🖊 Pen: {name}")

    def _update_pen_button_states(self):
        if not hasattr(self, "_btn_toggle_pen") or self._btn_toggle_pen is None:
            return
        if not hasattr(self, "canvas") or self.canvas is None:
            return
        active = getattr(self.canvas, "_ink_active", False)
        mode = self.canvas.ink_get_mode() if hasattr(self.canvas, "ink_get_mode") else "pen"
        color = self.canvas._ink_colors[self.canvas._ink_color_idx]
        dojo = _is_dojo()
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        is_cyan = theme in ("manhattan", "tmnt")
        bg_color = "rgba(0,240,255,0.18)" if is_cyan else ("rgba(114,255,79,0.18)" if dojo else "rgba(124,106,247,0.15)")
        
        # Style Pen button
        if active and mode == "pen":
            self._btn_toggle_pen.setStyleSheet(
                f"QPushButton{{background:{bg_color};border:1.5px solid {color};"
                f"border-radius:4px;font-size:12px;font-weight:bold;"
                f"padding:0px;letter-spacing:0px;text-transform:none;}}"
            )
        else:
            self._btn_toggle_pen.setStyleSheet(
                f"QPushButton{{background:transparent;border:1px solid {_tc('#45475A', '#1A1A26')};"
                f"border-radius:4px;font-size:12px;"
                f"padding:0px;letter-spacing:0px;text-transform:none;}}"
            )

        # Style Eraser button
        if hasattr(self, "_btn_eraser") and self._btn_eraser is not None:
            if active and mode == "eraser":
                self._btn_eraser.setStyleSheet(
                    f"QPushButton{{background:{bg_color};border:1.5px solid #F38BA8;"
                    f"border-radius:4px;font-size:12px;font-weight:bold;"
                    f"padding:0px;letter-spacing:0px;text-transform:none;}}"
                )
            else:
                self._btn_eraser.setStyleSheet(
                    f"QPushButton{{background:transparent;border:1px solid {_tc('#45475A', '#1A1A26')};"
                    f"border-radius:4px;font-size:12px;"
                    f"padding:0px;letter-spacing:0px;text-transform:none;}}"
                )

        self._btn_pen_color.setStyleSheet(
            f"QPushButton{{border:1.5px solid {color};border-radius:4px;"
            f"background:rgba(255,255,255,0.06);font-size:12px;"
            f"padding:0px;letter-spacing:0px;text-transform:none;}}"
        )

        self._btn_pen_clear.setStyleSheet(
            f"QPushButton{{border:1px solid {_tc('#45475A', '#1A1A26')};border-radius:4px;"
            f"background:transparent;font-size:12px;"
            f"padding:0px;letter-spacing:0px;text-transform:none;}}"
        )

        # Dynamically show/hide hovering save buttons based on pen activity
        self._update_floating_buttons_layout()

    def _reload_pdf_contrast(self):
        path = getattr(self.canvas, "_current_pdf_path", None)
        if not path or not os.path.exists(path):
            return
        
        # Stop loading threads
        if hasattr(self, "_pdf_loader_thread") and self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            t = self._pdf_loader_thread
            self._add_thread_to_cleanups(t)
            t.stop()
            t.quit()
        self._pdf_loader_thread = None

        if hasattr(self, "_pdf_ondemand_thread") and self._pdf_ondemand_thread and self._pdf_ondemand_thread.isRunning():
            t = self._pdf_ondemand_thread
            self._add_thread_to_cleanups(t)
            t.stop()
            t.quit()
        self._pdf_ondemand_thread = None
            
        self._review_canvas_real_pages = set()
        
        from pdf_engine import load_pdf_skeleton, build_skeleton_placeholders
        skeleton = load_pdf_skeleton(path, zoom=self._pdf_render_zoom)
        if skeleton and not getattr(skeleton, "error", None):
            pages = list(
                getattr(skeleton, "placeholders", None)
                or build_skeleton_placeholders(getattr(skeleton, "page_dims", []))
            )
            self.canvas.load_pages(pages)
            QTimer.singleShot(50, self._canvas_scroll._emit_visible_pages)

    def _review_nav_debug(self, action: str, **data):
        return

    def _pdf_quality_debug(self, action: str, **data):
        return

    def _log_review_scroll_profile(
        self,
        *,
        value,
        page_zero,
        page_changed,
        page_calc_ms,
        page_ui_ms,
        overlay_ms,
        total_ms,
    ):
        if not self._review_scroll_profile_enabled():
            return
        from ui.review.profiler import log_review_scroll_profile
        log_review_scroll_profile(
            self,
            value=value,
            page_zero=page_zero,
            page_changed=page_changed,
            page_calc_ms=page_calc_ms,
            page_ui_ms=page_ui_ms,
            overlay_ms=overlay_ms,
            total_ms=total_ms,
        )

    def _set_review_page_ui(self, current_zero: int):
        self._pdf_viewer.set_page_ui(current_zero)
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero

    def _on_review_scroll_page_changed(self, value: int):
        handler_t0 = time.perf_counter()
        calc_t0 = handler_t0
        page_zero = self.canvas.get_current_page(value)
        page_calc_ms = (time.perf_counter() - calc_t0) * 1000.0
        page_changed = page_zero != self._review_ui_page_zero
        page_ui_ms = 0.0
        if page_changed:
            self._review_nav_debug("scroll", value=value, page=page_zero + 1)
            ui_t0 = time.perf_counter()
            self._pdf_viewer.set_page_ui(page_zero)
            self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
            page_ui_ms = (time.perf_counter() - ui_t0) * 1000.0
        self._log_review_scroll_profile(
            value=value,
            page_zero=page_zero,
            page_changed=page_changed,
            page_calc_ms=page_calc_ms,
            page_ui_ms=page_ui_ms,
            overlay_ms=0.0,
            total_ms=(time.perf_counter() - handler_t0) * 1000.0,
        )

    def _go_to_review_page(self, page_zero: int):
        self._pdf_viewer.go_to_page(page_zero)
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
        self._keep_floating_timer_on_top()

    def _finalize_review_page_jump(self, seq: int, target: int):
        self._pdf_viewer._finalize_page_jump(seq, target)
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
        self._keep_floating_timer_on_top()

    def _nav_current_review_page(self) -> int:
        return self._pdf_viewer.nav_current_page()

    def _go_prev_review_page(self):
        self._pdf_viewer.go_prev_page()
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
        self._keep_floating_timer_on_top()

    def _go_next_review_page(self):
        self._pdf_viewer.go_next_page()
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
        self._keep_floating_timer_on_top()

    def _jump_to_review_page_from_input(self):
        self._pdf_viewer.jump_from_input()
        self._review_ui_page_zero = self._pdf_viewer._ui_page_zero
        self._keep_floating_timer_on_top()

    def _center_on_target(self):
        QTimer.singleShot(0, self._do_center_on_target)

    def _do_center_on_target(self):
        vp = self._canvas_scroll.viewport()
        view_w = vp.width()
        view_h = vp.height()

        # Canvas se scroll position lo — canvas size se calculate hoti hai,
        # scrollbar.maximum() pe depend nahi karta (jo late update hota hai)
        pos = self.canvas.get_target_scroll_pos(view_w, view_h)

        # If target is not set yet (e.g. first load), try to find it from current item
        if pos is None and 0 <= self._idx < len(self._items):
            pos = self.canvas.get_target_scroll_pos(view_w, view_h)

        if pos is None:
            return

        hval, vval = pos
        self._canvas_scroll.horizontalScrollBar().setValue(hval)
        self._canvas_scroll.verticalScrollBar().setValue(vval)

    def _debug_report(self, trigger: str = "manual"):
        """
        Press D in review screen to print a full diagnostic report to terminal.
        Also called automatically on C and Space.

        Covers:
          - Which widget has keyboard focus
          - Canvas scale, size, logical size
          - Viewport size
          - Scroll position (current H/V values and maximums)
          - Target mask rect (scaled) and computed scroll-to position
          - Current card index, box_idx, sm2 state
          - Reveal bar / rating frame visibility
          - PDF path + page count in cache
        """
        import time

        sep = "─" * 60
        vp = self._canvas_scroll.viewport()
        view_w = vp.width()
        view_h = vp.height()
        hsb = self._canvas_scroll.horizontalScrollBar()
        vsb = self._canvas_scroll.verticalScrollBar()
        cw, ch = self.canvas._canvas_wh()
        focused = QApplication.focusWidget()

        lines = [
            "",
            sep,
            f"  🔍 DEBUG REPORT  —  trigger: [{trigger}]  @ {time.strftime('%H:%M:%S')}",
            sep,
            f"  Focus widget    : {type(focused).__name__} (id={id(focused)})",
            f"  Canvas mode     : {self.canvas._mode}",
            f"  Canvas scale    : {self.canvas._scale:.4f}",
            f"  Canvas logical  : {cw} × {ch} px (image-space)",
            f"  Canvas widget   : {self.canvas.width()} × {self.canvas.height()} px (screen)",
            f"  Viewport        : {view_w} × {view_h} px",
            f"  Scroll H        : {hsb.value()} / {hsb.maximum()}",
            f"  Scroll V        : {vsb.value()} / {vsb.maximum()}",
        ]

        # Target mask
        tr = self.canvas.get_target_scaled_rect()
        if tr:
            lines.append(
                f"  Target rect     : x={tr.x():.1f} y={tr.y():.1f} "
                f"w={tr.width():.1f} h={tr.height():.1f}  (screen-space)"
            )
            pos = self.canvas.get_target_scroll_pos(view_w, view_h)
            if pos:
                lines.append(f"  Computed scroll : H={pos[0]}  V={pos[1]}")
        else:
            lines.append(
                f"  Target rect     : None (target_idx={self.canvas._target_idx}, "
                f"group='{self.canvas._target_group_id}')"
            )

        # Current item
        if 0 <= self._idx < len(self._items):
            card, box_idx, sm2_obj = self._items[self._idx]
            lines += [
                f"  Card idx        : {self._idx} / {len(self._items) - 1}",
                f"  Card title      : {card.get('title','?')}",
                f"  Box idx         : {box_idx}",
                f"  SM2 state       : {sm2_obj.get('sched_state','?')}  due={sm2_obj.get('sm2_due','?')}",
                f"  Total boxes     : {len(card.get('boxes', []))}",
            ]
            pdf_path = resolve_asset_path(card.get("pdf_path", ""))
            if pdf_path:
                cached_pages = PAGE_CACHE.cached_page_count(pdf_path, variant=self._pdf_render_zoom)
                lines.append(f"  PDF path        : {os.path.basename(pdf_path)}")
                lines.append(f"  Cached pages    : {cached_pages}")
            lines.append(f"  Canvas pages    : {len(self.canvas._pages)}")

        # UI state
        lines += [
            f"  Reveal bar      : {'visible' if self._reveal_bar.isVisible() else 'hidden'}",
            f"  Rating frame    : {'visible' if self._rating_frame.isVisible() else 'hidden'}",
            sep,
            "",
        ]

        print("\n".join(lines))
        # Also show as canvas toast so it's visible without terminal
        self.canvas._show_toast(f"📋 Debug report printed to terminal  [{trigger}]")

    def _edit_current_card(self):
        # After session complete _idx == len(_items), use last card
        idx = self._idx
        if idx >= len(self._items):
            idx = len(self._items) - 1
        if not (0 <= idx < len(self._items)):
            return
        card, box_idx, sm2_obj = self._items[idx]

        if card.get("card_type") == "text":
            dlg = TextCardEditorDialog(self, card=dict(card), data=self._data, deck=None)
            self._active_editor = dlg
            dlg.finished.connect(
                lambda result, d=dlg, c=card: self._finish_edit_current_text_card(d, c, result)
            )
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return

        scroll_pos = self._canvas_scroll.verticalScrollBar().value()
        review_scale = self.canvas._scale
        img_y = scroll_pos / max(review_scale, 0.01)

        # ── O(1) snapshot: box_ids before edit ────────────────────────────────
        before_ids = {
            b.get("box_id", ""): b.get("group_id", "")
            for b in card.get("boxes", [])
            if b.get("box_id")
        }

        dlg = CardEditorDialog(
            self,
            card=dict(card),
            data=self._data,
            initial_scroll=0,
            initial_page=None,
            initial_img_y=img_y,
        )
        self._active_editor = dlg
        dlg.finished.connect(
            lambda result, d=dlg, c=card, b=before_ids: self._finish_edit_current_card(
                d, c, b, result
            )
        )
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.showFullScreen()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _finish_edit_current_text_card(self, dlg, card, result):
        if getattr(self, "_active_editor", None) is dlg:
            self._active_editor = None
        if result != QDialog.Accepted:
            dlg.deleteLater()
            return
            
        edited = dlg.get_card()
        # Preserve SM-2 state of the card
        SM2_KEYS = (
            "sched_state",
            "sched_step",
            "sm2_interval",
            "sm2_ease",
            "sm2_due",
            "sm2_last_quality",
            "sm2_repetitions",
            "reviews",
        )
        for k in SM2_KEYS:
            if k in card:
                edited[k] = card[k]
                
        card.update(edited)
        card_id = card.get("_id")
        if card_id is not None and hasattr(self, "_text_card_cache"):
            self._text_card_cache.pop((card_id, True), None)
            self._text_card_cache.pop((card_id, False), None)
        if self._data:
            store.mark_dirty()
            self._review_data_dirty = True
            
        self._items = [
            (item[0], None, item[0]) if (id(item[0]) == id(card) or (card.get("_id") and item[0].get("_id") == card.get("_id"))) else item 
            for item in self._items
        ]
        self.mgr._queue_needs_full_rebuild = True
        self._rebuild_queue()
        self._load_item()
        dlg.deleteLater()

    def _finish_edit_current_card(self, dlg, card, before_ids, result):
        if getattr(self, "_active_editor", None) is dlg:
            self._active_editor = None
        if result != QDialog.Accepted:
            self._user_zoom_scale = None
            self._reload_current_canvas()
            dlg.deleteLater()
            return

        edited = dlg.get_card()

        # [FIX] Preserve SM-2 data on existing boxes — editor returns fresh box
        # dicts that don't have SM-2 fields. If we do card.update(edited) blindly,
        # the new boxes list replaces the old one and all SM-2 state is lost.
        # Solution: merge SM-2 fields from old boxes into edited boxes by box_id.
        old_boxes_by_id = {b.get("box_id", ""): b for b in card.get("boxes", [])}
        SM2_KEYS = (
            "sched_state",
            "sched_step",
            "sm2_interval",
            "sm2_ease",
            "sm2_due",
            "sm2_last_quality",
            "sm2_repetitions",
            "reviews",
        )
        for new_box in edited.get("boxes", []):
            bid = new_box.get("box_id", "")
            if bid and bid in old_boxes_by_id:
                old = old_boxes_by_id[bid]
                for k in SM2_KEYS:
                    if k in old:
                        new_box[k] = old[k]  # preserve SM-2 state

        card.update(edited)
        if self._data:
            store.mark_dirty()
            self._review_data_dirty = True

        after_ids = {
            b.get("box_id", ""): b.get("group_id", "")
            for b in card.get("boxes", [])
            if b.get("box_id")
        }

        # ── O(M) Surgical Update: Remove old entries for this card ────────────
        # Pehle is card ke saare purane queue items nikaal dete hain
        # index preserve karne ki zaroorat nahi kyunki queue due-date sorted rehti hai
        self._items = [item for item in self._items if id(item[0]) != id(card)]

        # O(1) tracking sets se bhi purane IDs hatao
        # (Is card ke current boxes ke box_ids/group_ids ko session tracker se saaf karo)
        for bid, gid in before_ids.items():
            self._queued_ids.discard(bid)
            if gid:
                self._queued_ids.discard(gid)

        # ── O(M) detect NEW due boxes → add them to queue ─────────────────────
        seen_new_groups = set()
        for box in card.get("boxes", []):
            bid = box.get("box_id", "")
            gid = box.get("group_id", "")
            track_id = gid if gid else bid
            if not track_id:
                continue

            # Skip if already added (prevents group duplication within this card scan)
            if track_id in seen_new_groups or track_id in self._queued_ids:
                continue

            sm2_init(box)
            if is_due_today(box):
                self._queued_ids.add(track_id)
                if gid:
                    seen_new_groups.add(gid)
                    self._items.append((card, ("group", gid), box))
                else:
                    i = card.get("boxes", []).index(box)
                    self._items.append((card, i, box))

        # Re-sort only if we added/updated items to keep logical flow
        self._items.sort(key=lambda x: x[2].get("sm2_due", ""))
        self.mgr._queue_needs_full_rebuild = True
        self._clear_review_loading_caches()

        # After sort, finished items (future due) are at the end.
        # Find the first item that is still due today (active).
        new_idx = 0
        for i, (_, _, sm2) in enumerate(self._items):
            if is_due_today(sm2):
                new_idx = i
                break
        self._idx = new_idx

        self._user_zoom_scale = None
        self._rebuild_queue()
        self._reload_current_canvas()
        dlg.deleteLater()

    def _delete_current_card(self):
        if not self._items or not (0 <= self._idx < len(self._items)):
            return
        card, box_idx, sm2_obj = self._items[self._idx]
        
        # Get clean descriptive title for confirmation
        card_type = card.get("card_type", "pdf")
        if card_type == "text":
            title = card.get("title") or card.get("question", "")
            title_clean = " ".join(re.sub(r'<[^>]+>', ' ', title).split())[:60]
        else:
            title_clean = card.get("title") or os.path.basename(card.get("pdf_path", "") or card.get("image_path", ""))
            
        confirm = QMessageBox.question(
            self,
            "Delete Card Confirmation",
            f"Are you sure you want to permanently delete this card from the deck?\n\n\"{title_clean}\"",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        # Find parent deck and delete card
        deleted = False
        def _walk_and_remove(d):
            nonlocal deleted
            if not d:
                return
            cards = d.get("cards", [])
            for i, c in enumerate(cards):
                if c is card or (card.get("_id") and c.get("_id") == card.get("_id")):
                    cards.pop(i)
                    deleted = True
                    return
            for sub in d.get("children", []):
                _walk_and_remove(sub)
                if deleted:
                    return
            for sub in d.get("subdecks", []):
                _walk_and_remove(sub)
                if deleted:
                    return

        decks = self._data.get("decks", [])
        if isinstance(decks, dict):
            decks = list(decks.values())
        for d in decks:
            _walk_and_remove(d)
            if deleted:
                break

        # Remove from active queue
        self._items = [
            item for item in self._items 
            if not (item[0] is card or (card.get("_id") and item[0].get("_id") == card.get("_id")))
        ]
        
        card_id = card.get("_id")
        if card_id is not None and hasattr(self, "_text_card_cache"):
            self._text_card_cache.pop((card_id, True), None)
            self._text_card_cache.pop((card_id, False), None)

        store.mark_dirty()
        try:
            store.save_force(async_save=True)
        except Exception:
            pass

        self.canvas._show_toast("🗑️ Card deleted successfully")
        
        if hasattr(self, "prog") and hasattr(self, "lbl_prog"):
            self.prog.setMaximum(max(1, len(self._items)))
            
        if not self._items:
            self._finish_session()
        else:
            if self._idx >= len(self._items):
                self._idx = len(self._items) - 1
            if hasattr(self, "lbl_prog"):
                self.lbl_prog.setText(f"Card {self._idx + 1}/{len(self._items)}")
            self.mgr._queue_needs_full_rebuild = True
            self._rebuild_queue()
            self._load_item()

    def _find_card_deck(self, target_card):
        if not target_card or not self._data:
            return None
        def _walk(d):
            if not d:
                return None
            for c in d.get("cards", []):
                if c is target_card or (target_card.get("_id") and c.get("_id") == target_card.get("_id")):
                    return d
            for sub in d.get("children", []):
                res = _walk(sub)
                if res:
                    return res
            for sub in d.get("subdecks", []):
                res = _walk(sub)
                if res:
                    return res
            return None
        decks = self._data.get("decks", [])
        if isinstance(decks, dict):
            decks = list(decks.values())
        for d in decks:
            res = _walk(d)
            if res:
                return res
        return None

    def _open_card_browser(self):
        from ui.card_browser_dialog import CardBrowserDialog
        current_card = self._items[self._idx][0] if (self._items and 0 <= self._idx < len(self._items)) else None
        current_deck = self._find_card_deck(current_card)
        dlg = CardBrowserDialog(self, deck=current_deck, data=self._data, review_screen=self)
        dlg.exec_()
        if hasattr(self, "_load_item") and getattr(self, "_items", None) and 0 <= self._idx < len(self._items):
            self._load_item()

    def _open_current_pdf_in_reader(self):
        from ui.review.external_reader import open_current_pdf_in_reader
        open_current_pdf_in_reader(self)

    def _current_pdf_path_for_shortcuts(self):
        from ui.review.external_reader import current_pdf_path_for_shortcuts
        return current_pdf_path_for_shortcuts(self)

    def _copy_current_pdf_file_to_clipboard(self):
        from ui.review.external_reader import copy_current_pdf_file_to_clipboard
        copy_current_pdf_file_to_clipboard(self)

    def _reveal_current_pdf_in_folder(self):
        from ui.review.external_reader import reveal_current_pdf_in_folder
        reveal_current_pdf_in_folder(self)

    def _open_annotation_beta(self):
        if self._items and self._idx < len(self._items):
            card, _, _ = self._items[self._idx]
            if card.get("card_type") == "text":
                self.canvas._show_toast("Annotations are not supported for text cards")
                return
        from ui.review.annotation_handler import open_annotation_beta
        open_annotation_beta(self)

    def _annotation_window_flags(self):
        from ui.review.annotation_handler import annotation_window_flags
        return annotation_window_flags(self)

    def _prepare_annotation_window(self, dialog):
        from ui.review.annotation_handler import prepare_annotation_window
        prepare_annotation_window(self, dialog)

    def _install_annotation_switch_shortcuts(self, dialog):
        from ui.review.annotation_handler import install_annotation_switch_shortcuts
        install_annotation_switch_shortcuts(self, dialog)

    def _focus_active_annotation_window(self):
        from ui.review.annotation_handler import focus_active_annotation_window
        focus_active_annotation_window(self)

    def _focus_review_window(self):
        from ui.review.annotation_handler import focus_review_window
        focus_review_window(self)

    def _finish_annotation_beta(self, dialog, path: str, result):
        from ui.review.annotation_handler import finish_annotation_beta
        finish_annotation_beta(self, dialog, path, result)

    def _pause_review_lazy_activity_for_annotation(self):
        from ui.review.annotation_handler import pause_review_lazy_activity_for_annotation
        pause_review_lazy_activity_for_annotation(self)

    def _resume_review_lazy_activity_after_annotation(self, path: str | None = None):
        from ui.review.annotation_handler import resume_review_lazy_activity_after_annotation
        resume_review_lazy_activity_after_annotation(self, path)

    def _clear_review_loading_caches(self):
        from ui.review.annotation_handler import clear_review_loading_caches
        clear_review_loading_caches(self)

    def _review_box_signature(self, boxes):
        from ui.review.annotation_handler import review_box_signature
        return review_box_signature(self, boxes)

    def _adapt_review_boxes(self, card, path):
        from ui.review.annotation_handler import adapt_review_boxes
        return adapt_review_boxes(self, card, path)

    def _start_review_lazy_trace(self, page_nums, ttl_seconds: float = 8.0):
        from ui.review.annotation_handler import start_review_lazy_trace
        start_review_lazy_trace(self, page_nums, ttl_seconds)

    def _apply_annotation_beta_refresh(
        self, path: str, changed_pages, return_page: int | None
    ):
        from ui.review.annotation_handler import apply_annotation_beta_refresh
        apply_annotation_beta_refresh(self, path, changed_pages, return_page)

    def _render_text_card_to_pixmap(self, card, is_revealed):
        card_id = card.get("_id")
        if card_id is not None and hasattr(self, "_text_card_cache"):
            cache_key = (card_id, is_revealed)
            if cache_key in self._text_card_cache:
                val = self._text_card_cache.pop(cache_key)
                self._text_card_cache[cache_key] = val
                return val

        from ui.text_review_widget import get_base_url
        from theme_manager import get_palette

        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        
        # Determine theme-tailored high-contrast colors
        if theme in ("tmnt", "manhattan"):
            card_bg_hex = "#121622"
            card_border_hex = "#00f0ff"
            text_color_hex = "#FFFFFF"
            answer_color_hex = "#39ff14"
            subtext_color_hex = "#8FA4BF"
            header_color_hex = "#00F0FF"
        elif theme == "dojo":
            card_bg_hex = "#0F0F17"
            card_border_hex = "#A86CFF"
            text_color_hex = "#FFFFFF"
            answer_color_hex = "#72FF4F"
            subtext_color_hex = "#8C9BB4"
            header_color_hex = "#A86CFF"
        elif theme == "arcanum":
            card_bg_hex = "#16131D"
            card_border_hex = "#C89B3C"
            text_color_hex = "#F5E6C8"
            answer_color_hex = "#FFD700"
            subtext_color_hex = "#B09F8C"
            header_color_hex = "#C89B3C"
        else:  # classic / dark
            card_bg_hex = "#1E202C"
            card_border_hex = "#5C7CFA"
            text_color_hex = "#FFFFFF"
            answer_color_hex = "#50FA7B"
            subtext_color_hex = "#A6ADC8"
            header_color_hex = "#5C7CFA"

        border_color_hex = p.get("C_BORDER", "#45475A")
        body_font = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        header_font = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")

        # Create QTextDocument
        doc = QTextDocument()
        doc.setBaseUrl(get_base_url())

        # Setup base styling with universal high-contrast color selectors
        css = f"""
        * {{
            color: {text_color_hex};
        }}
        body {{
            background-color: transparent;
            color: {text_color_hex};
            font-family: {body_font};
            font-size: 18px;
            margin: 0;
            padding: 0;
        }}
        .question {{
            color: {text_color_hex};
            font-size: 24px;
            font-weight: bold;
            line-height: 1.35;
            margin: 0 0 10px 0;
        }}
        .answer-hdr {{
            color: {header_color_hex};
            font-family: {header_font};
            font-size: 11px;
            font-weight: bold;
            letter-spacing: 1px;
            margin: 8px 0 6px 0;
        }}
        .answer {{
            color: {answer_color_hex};
            font-size: 21px;
            font-weight: 500;
            line-height: 1.4;
            margin: 0 0 8px 0;
        }}
        hr {{
            border: none;
            border-top: 1px solid {border_color_hex};
            margin: 12px 0;
        }}
        """
        doc.setDefaultStyleSheet(css)

        # Build HTML content
        question = card.get("question", "")
        answer = card.get("answer", "")

        def format_field(text):
            if not text:
                return ""
            import re
            if "<!doctype" in text.lower() or "<html" in text.lower():
                body_match = re.search(r'<body[^>]*>(.*?)</body>', text, re.DOTALL | re.IGNORECASE)
                if body_match:
                    text = body_match.group(1).strip()
            if "<img" in text or "<p" in text or "<div" in text or "<span" in text or "<br" in text or "<table" in text:
                return text
            import html
            return html.escape(text).replace("\n", "<br>")

        q_html = format_field(question)
        
        # Parse img tags and resolve local paths into resources for document rendering
        # Also clean img tags to remove original sizes and use width=860px
        def process_html_images(html_content):
            if not html_content:
                return ""
            # Find all image sources
            sources = _RE_IMG_SRC.findall(html_content)
            
            base_url = get_base_url()
            base_path = ""
            if base_url.isLocalFile():
                base_path = base_url.toLocalFile()
                
            for src in sources:
                abs_path = src
                if not os.path.isabs(src):
                    if base_path:
                        abs_path = os.path.join(base_path, src)
                    else:
                        from storage_paths import get_mission_archive_root
                        root = get_mission_archive_root()
                        if root:
                            abs_path = os.path.join(root, src)
                abs_path = os.path.normpath(abs_path)
                
                if os.path.exists(abs_path):
                    pixmap = QPixmap(abs_path)
                    if not pixmap.isNull():
                        w = pixmap.width()
                        if w > 0:
                            # Scale pixmap smoothly to width 860
                            scaled_pixmap = pixmap.scaledToWidth(860, Qt.SmoothTransformation)
                            doc.addResource(QTextDocument.ImageResource, QUrl(src), scaled_pixmap)
                            doc.addResource(QTextDocument.ImageResource, QUrl.fromLocalFile(abs_path), scaled_pixmap)
            
            # Clean and resize img tags
            def clean_and_resize_img_tags(match):
                tag = match.group(0)
                tag = re.sub(r'width\s*=\s*["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
                tag = re.sub(r'height\s*=\s*["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
                tag = re.sub(r'style\s*=\s*["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
                tag = tag[:-1] + ' width="860">'
                return tag
                
            cleaned = _RE_IMG.sub(clean_and_resize_img_tags, html_content)
            # Clean inline font-size to allow default css style scaling
            cleaned = _RE_FONT_SIZE.sub('', cleaned)
            return cleaned

        q_html = process_html_images(q_html)

        # Build Header Badges
        badges_html = []
        
        # 1. Topic Context Anchor Badge
        context_anchor = str(card.get("context_anchor", "") or "").strip()
        if context_anchor:
            import html
            badges_html.append(
                f'<span style="background-color: rgba(92, 124, 250, 0.18); color: {header_color_hex}; border: 1px solid {header_color_hex}; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold; font-family: {header_font}; margin-right: 8px;">📌 {html.escape(context_anchor)}</span>'
            )
            
        # 2. Priority Tier Badge (80/20 Rule)
        p_tier = card.get("priority_tier")
        try:
            p_tier = int(p_tier) if p_tier is not None else 1
        except (ValueError, TypeError):
            p_tier = 1
            
        if p_tier == 1:
            badges_html.append(
                f'<span style="background-color: rgba(255, 184, 108, 0.2); color: #FFB86C; border: 1px solid #FFB86C; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold; font-family: {header_font}; margin-right: 8px;">🔥 80/20 CORE</span>'
            )
        elif p_tier == 2:
            badges_html.append(
                f'<span style="background-color: rgba(139, 233, 253, 0.2); color: #8BE9FD; border: 1px solid #8BE9FD; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold; font-family: {header_font}; margin-right: 8px;">⚡ 80/20 DETAIL</span>'
            )
            
        # 3. Chain Order Badge
        chain_order = card.get("chain_order", 0)
        parent_chain_id = card.get("parent_chain_id")
        if chain_order or parent_chain_id:
            order_text = f"Step {chain_order}" if chain_order else "Linked Chain"
            badges_html.append(
                f'<span style="background-color: rgba(255, 215, 0, 0.2); color: #FFD700; border: 1px solid #FFD700; border-radius: 4px; padding: 3px 8px; font-size: 11px; font-weight: bold; font-family: {header_font}; margin-right: 8px;">🔗 {order_text}</span>'
            )

        header_bar_html = f'<div style="margin-bottom: 14px; line-height: 1.8;">{" ".join(badges_html)}</div>' if badges_html else ""

        html_body = f'''
        <div style="color: {text_color_hex}; font-family: {body_font};">
            {header_bar_html}
            <div class="question" style="color: {text_color_hex}; font-size: 24px; font-weight: bold; line-height: 1.35; margin: 0 0 10px 0;">
                {q_html}
            </div>
        '''

        if is_revealed:
            a_html = format_field(answer)
            a_html = process_html_images(a_html)
            html_body += f'''
            <hr style="border: none; border-top: 1px solid {border_color_hex}; margin: 14px 0 10px 0;">
            <div class="answer-hdr" style="color: {header_color_hex}; font-size: 11px; font-weight: bold; letter-spacing: 1px; margin: 4px 0 6px 0;">
                ANSWER / MEANING:
            </div>
            <div class="answer" style="color: {answer_color_hex}; font-size: 21px; font-weight: 500; line-height: 1.4; margin: 0 0 10px 0;">
                {a_html}
            </div>
            '''
            
            # Trap note display
            trap_note = str(card.get("trap_note", "") or "").strip()
            if trap_note:
                t_html = format_field(trap_note)
                t_html = process_html_images(t_html)
                html_body += f'''
                <div style="background-color: rgba(255, 107, 107, 0.12); border-left: 3px solid #FF6B6B; border-radius: 4px; padding: 8px 12px; margin-top: 10px; margin-bottom: 6px;">
                    <div style="color: #FF6B6B; font-size: 11px; font-weight: bold; letter-spacing: 0.8px; margin-bottom: 4px;">
                        ⚠️ EXAM TRAP / KEY PITFALL:
                    </div>
                    <div style="color: #FFA066; font-size: 15px; line-height: 1.35;">
                        {t_html}
                    </div>
                </div>
                '''

            # Deep Theory & Background Notes if present
            notes = str(card.get("notes", "") or "").strip()
            if notes and notes != trap_note:
                n_html = format_field(notes)
                n_html = process_html_images(n_html)
                html_body += f'''
                <div style="background-color: rgba(92, 124, 250, 0.08); border-left: 3px solid #5C7CFA; border-radius: 4px; padding: 10px 14px; margin-top: 10px; margin-bottom: 6px;">
                    <div style="color: {header_color_hex}; font-size: 11px; font-weight: bold; letter-spacing: 0.8px; margin-bottom: 6px;">
                        📝 DEEP CONCEPT & BACKGROUND:
                    </div>
                    <div style="color: {subtext_color_hex}; font-size: 15px; line-height: 1.45;">
                        {n_html}
                    </div>
                </div>
                '''

        html_body += '</div>'

        doc.setHtml(html_body)
        
        card_width = 1000
        text_content_w = 880.0
        doc.setTextWidth(text_content_w)

        h = int(doc.size().height())
        content_pad_top = 28
        content_pad_bottom = 28
        rating_bar_clearance = 120  # Always reserve clearance at the bottom for the floating review rating bar
        
        card_frame_h = h + content_pad_top + content_pad_bottom
        total_height = max(320, card_frame_h + rating_bar_clearance)
        
        # Pixmap background matches canvas background
        canvas_bg = p.get("C_BG", "#07070B")
        px = QPixmap(card_width, total_height)
        px.fill(QColor(canvas_bg))
        
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # Draw sleek rounded card frame
        card_rect = QRectF(25, 20, card_width - 50, card_frame_h)
        painter.setBrush(QBrush(QColor(card_bg_hex)))
        painter.setPen(QPen(QColor(card_border_hex), 1.5))
        painter.drawRoundedRect(card_rect, 10, 10)
        
        # Draw document inside card with compact padding
        painter.setPen(QColor(text_color_hex))
        painter.translate(60, 20 + content_pad_top)
        doc.drawContents(painter, QRectF(0, 0, text_content_w, h))
        painter.end()

        if card_id is not None and hasattr(self, "_text_card_cache"):
            cache_key = (card_id, is_revealed)
            self._text_card_cache[cache_key] = px
            if len(self._text_card_cache) > 8:
                self._text_card_cache.popitem(last=False)

        return px

    def _reload_current_canvas(self, view_idx=None):
        """
        STEP 4 — Skeleton-first lazy loading.

        Flow:
          1. Image card      → unchanged (direct QPixmap load)
          2. PDF             → always skeleton-first lazy path:
               a. load_pdf_skeleton() — grey placeholders, ~5ms
               b. canvas ready instantly with correct layout + page_tops
               c. _start_priority_render() — queue pages first
               d. scroll → _on_visible_pages_changed() → on-demand rest
          3. PDF missing     → grey fallback (unchanged)

        Terminal prints every decision point.
        """
        if view_idx is None:
            view_idx = self._idx

        if not (0 <= view_idx < len(self._items)):
            return
        card, box_idx, _ = self._items[view_idx]
        if card.get("card_type") == "text":
            return
        reload_t0 = time.perf_counter()
        self._bg_pending_inserts.clear()
        self._pending_skeleton_result = None
        self._close_bg_prefetch_dialog()
        self._stop_skeleton_thread()

        t_start = time.perf_counter()
        display_path = resolve_asset_path(
            card.get("pdf_path", "") or card.get("image_path", "?")
        )
        fname = os.path.basename(display_path)

        # ── 1. IMAGE CARD ─────────────────────────────────────────────────────
        image_path = resolve_asset_path(card.get("image_path", ""))
        if card.get("image_path") and not card.get("pdf_path") and os.path.exists(image_path):
            px = QPixmap(image_path)
            if px and not px.isNull():
                self._apply_canvas(card, box_idx, px)
            return

        # ── 2. PDF CARD ───────────────────────────────────────────────────────
        if card.get("pdf_path") and PDF_SUPPORT:
            path = resolve_asset_path(card.get("pdf_path", ""))
            self._pdf_watcher.watch_pdf(path)

            # ── 2a. PDF missing ───────────────────────────────────────────────
            if not os.path.exists(path):
                self._canvas_pdf_path = ""  # FIX 1: kills stale thread signals
                self.canvas.load_pixmap(QPixmap())
                boxes = card.get("boxes", [])
                if boxes:
                    display_boxes = [{**b, "revealed": False} for b in boxes]
                    self.canvas.set_boxes_with_state(display_boxes)
                    tgt = box_idx if isinstance(box_idx, int) else -1
                    self.canvas.set_target_box(tgt)
                    self.canvas.set_mode("review")
                    self.canvas._show_toast(
                        "PDF not found — Edit Card > Relink PDF to fix"
                    )
                self._show_overlay(self._reveal_bar)
                self._rating_frame.hide()
                self.setFocus()
                return

            # ── 2b. Review always stays queue-first lazy, even if the disk cache
            #        already has every page. We do not hydrate the whole PDF into
            #        the review canvas upfront anymore.
            total_pages = get_pdf_page_count(path)
            self._pdf_render_zoom = choose_pdf_render_zoom(total_pages)
            previous_zoom = PAGE_CACHE.get_render_zoom(path)
            profile_t0 = time.perf_counter()
            cached_before = (
                PAGE_CACHE.cached_page_count(path, total_pages)
                if hasattr(PAGE_CACHE, "cached_page_count")
                else "?"
            )
            profile_reset = ensure_pdf_cache_profile(path, self._pdf_render_zoom)
            cached_after = (
                PAGE_CACHE.cached_page_count(path, total_pages)
                if hasattr(PAGE_CACHE, "cached_page_count")
                else "?"
            )
            profile_ms = (time.perf_counter() - profile_t0) * 1000.0
            self._review_profile_log(
                "pdf_profile",
                file=fname,
                pages=total_pages,
                zoom=self._pdf_render_zoom,
                cached_before=f"{cached_before}/{total_pages}",
                cached_after=f"{cached_after}/{total_pages}",
                reset=profile_reset,
                elapsed=f"{(time.perf_counter() - reload_t0) * 1000:.1f}ms",
            )
            perf_log(
                "review_pdf_profile",
                file=fname,
                pages=total_pages,
                zoom=self._pdf_render_zoom,
                previous_zoom=previous_zoom,
                reset_cache=profile_reset,
                cached_before=cached_before,
                cached_after=cached_after,
                profile_ms=round(profile_ms, 3),
                load_item_ms=round((time.perf_counter() - reload_t0) * 1000.0, 3),
            )
            self._pdf_quality_debug(
                "profile",
                pages=total_pages,
                zoom=self._pdf_render_zoom,
                reset_cache=profile_reset,
            )

            # ── 2c. NEW LAZY PATH — skeleton first ────────────────────────────
            self._pending_skeleton_result = {
                "card": card,
                "box_idx": box_idx,
                "clean_pages": {},
                "path": path,
                "t_start": t_start,
            }
            self._start_review_skeleton_thread(path)
            return

        # ── 3. FALLBACK — no image, no pdf ────────────────────────────────────

    # ── STEP 4 HELPERS ────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_review_pages(page_nums, max_items: int = 10):
        pages = [int(pn) for pn in (page_nums or [])]
        if not pages:
            return "none"
        shown = ", ".join(f"p.{pn + 1}" for pn in pages[:max_items])
        if len(pages) > max_items:
            shown += f", ... (+{len(pages) - max_items})"
        return shown

    def _card_review_pages(self, card, box_ref, path=None):
        c_boxes = card.get("boxes", [])
        selected_boxes = []
        if isinstance(box_ref, tuple) and box_ref[0] == "group":
            gid = box_ref[1]
            selected_boxes = [b for b in c_boxes if b.get("group_id") == gid]
        elif isinstance(box_ref, int) and 0 <= box_ref < len(c_boxes):
            selected_boxes = [c_boxes[box_ref]]
        needs_page_inference = any(
            box.get("page_num") is None for box in selected_boxes
        )
        if path and needs_page_inference and "_pdf_render_zoom" in self.__dict__:
            c_boxes = self._adapt_review_boxes(card, path)
        pages = []
        if isinstance(box_ref, tuple) and box_ref[0] == "group":
            gid = box_ref[1]
            for box in c_boxes:
                if box.get("group_id") == gid:
                    pn = box.get("page_num")
                    if pn is not None:
                        pages.append(pn)
        elif isinstance(box_ref, int) and 0 <= box_ref < len(c_boxes):
            pn = c_boxes[box_ref].get("page_num")
            if pn is not None:
                pages.append(pn)
        return pages

    def _get_priority_pages(self, card, box_idx, total_pages, path=None):
        """
        Return only the queued review pages from this same PDF.
        These pages render FIRST so the viewport stays responsive while the
        current review session is warming up.

        The goal is simple:
          1. current mask page
          2. other review pages from the same PDF
        Everything else stays lazy and scroll-driven.
        """
        card_path = resolve_asset_path(path or card.get("pdf_path", ""))
        cache_key = (
            os.path.abspath(card_path) if card_path else "",
            id(card),
            repr(box_idx),
            int(total_pages or 0),
        )
        priority_cache = self.__dict__.setdefault("_review_priority_pages_cache", {})
        cached = priority_cache.get(cache_key)
        if cached is not None:
            self._review_profile_count("priority_pages_hit")
            self._review_profile_log(
                "priority_pages",
                result="hit",
                pages=self._fmt_review_pages(cached),
            )
            return list(cached)
        self._review_profile_count("priority_pages_miss")

        def _clean(page_nums):
            result = []
            seen = set()
            for pn in page_nums or []:
                if pn is None:
                    continue
                pn = max(0, min(int(pn), max(0, int(total_pages) - 1)))
                if pn in seen:
                    continue
                seen.add(pn)
                result.append(pn)
            return result

        raw_current_pages = _clean(self._card_review_pages(card, box_idx))
        current_pages = _clean(self._card_review_pages(card, box_idx, card_path))
        if (
            current_pages
            and current_pages != raw_current_pages
            and self._review_verbose_debug_enabled()
        ):
            print(
                "[DEBUG][review_queue_pages] "
                f"inferred_current={self._fmt_review_pages(current_pages)} "
                f"raw={self._fmt_review_pages(raw_current_pages)}"
            )
        session_pages = []
        # Preload every due page from the same PDF that is already in this
        # review session. This keeps the current PDF warm without fanning out
        # into a full-document background fill.
        if card_path:
            for c, box_ref, _sm2 in self._items:
                if resolve_asset_path(c.get("pdf_path", "")) != card_path:
                    continue
                session_pages.extend(self._card_review_pages(c, box_ref, card_path))

        # Current box page(s) must come first, even if they are far past the
        # RAM cache limit. The rest is only a small warmup window.
        ordered = current_pages + sorted(_clean(session_pages))
        result = _clean(ordered)
        if len(result) > self.PRIORITY_PAGE_LIMIT:
            result = result[: self.PRIORITY_PAGE_LIMIT]
        if self._review_verbose_debug_enabled():
            if result:
                print(
                    "[DEBUG][review_queue_pages] "
                    f"current={self._fmt_review_pages(current_pages)} "
                    f"priority={self._fmt_review_pages(result)} "
                    f"limit={self.PRIORITY_PAGE_LIMIT}"
                )
            else:
                print("[DEBUG][review_queue_pages] priority none")
        priority_cache[cache_key] = tuple(result)
        while len(priority_cache) > 16:
            priority_cache.pop(next(iter(priority_cache)))
        self._review_profile_log(
            "priority_pages",
            result="miss",
            current=self._fmt_review_pages(current_pages),
            priority=self._fmt_review_pages(result),
            session_candidates=len(session_pages),
        )
        return result

    def _add_thread_to_cleanups(self, t):
        if not hasattr(self, "_pending_worker_cleanups") or self._pending_worker_cleanups is None:
            self._pending_worker_cleanups = []
        try:
            self._pending_worker_cleanups = [x for x in self._pending_worker_cleanups if not x.isFinished()]
        except Exception:
            pass
        if len(self._pending_worker_cleanups) >= 16:
            self._pending_worker_cleanups.pop(0)
        
        self._pending_worker_cleanups.append(t)
        t.finished.connect(
            lambda obj=t: self._pending_worker_cleanups.remove(obj)
            if (hasattr(self, "_pending_worker_cleanups") and self._pending_worker_cleanups and obj in self._pending_worker_cleanups)
            else None
        )

    def _stop_skeleton_thread(self, shutdown=False):
        if self._skeleton_thread and self._skeleton_thread.isRunning():
            t = self._skeleton_thread
            if shutdown:
                t.stop()
                t.quit()
                t.wait(500)
            else:
                self._add_thread_to_cleanups(t)
                t.stop()
                t.quit()
        self._skeleton_thread = None

    def _start_review_skeleton_thread(self, path):
        self._stop_skeleton_thread()
        self._skeleton_thread = PdfSkeletonThread(
            path, zoom=self._pdf_render_zoom, parent=self
        )
        self._skeleton_thread.done.connect(
            lambda skel, p=path: self._on_review_skeleton_ready(p, skel)
        )
        self._skeleton_thread.error.connect(
            lambda err, p=path: self._on_review_skeleton_error(p, err)
        )
        self._skeleton_thread.start()

    def _on_review_skeleton_error(self, path, err):
        pending = self._pending_skeleton_result
        if not pending or pending.get("path") != path:
            return
        card = pending.get("card")
        box_idx = pending.get("box_idx")
        self._pending_skeleton_result = None
        self._start_review_pdf_thread(card, box_idx)

    def _on_review_skeleton_ready(self, path, skel):
        pending = self._pending_skeleton_result
        if not pending or pending.get("path") != path:
            return
        self._pending_skeleton_result = None
        if not skel or getattr(skel, "error", None):
            self._on_review_skeleton_error(
                path, getattr(skel, "error", "Could not build PDF skeleton")
            )
            return
        self._apply_review_skeleton_result(
            pending["card"],
            pending["box_idx"],
            pending["clean_pages"],
            path,
            skel,
            pending["t_start"],
        )

    def _apply_review_skeleton_result(
        self, card, box_idx, clean_pages, path, skel, t_start
    ):
        pages = (
            list(skel.placeholders)
            if getattr(skel, "placeholders", None)
            else build_skeleton_placeholders(getattr(skel, "page_dims", []))
        )
        for i, pg in clean_pages.items():
            if 0 <= i < len(pages):
                pages[i] = pg
        if clean_pages:
            cached_idxs = sorted(clean_pages.keys())
            self._debug_review_lazy_pages_loaded(source="cache", page_nums=cached_idxs)
        self._apply_canvas_pages(card, box_idx, pages)
        self._review_canvas_real_pages = {int(i) for i in clean_pages.keys()}
        self._review_render_inflight_pages = set()
        self.canvas._show_toast(f"⏳ Loading p.1–{skel.total_pages}...")
        t_skel_ms = (time.perf_counter() - t_start) * 1000

        priority_pages = self._get_priority_pages(card, box_idx, skel.total_pages, path)
        self._review_profile_log(
            "skeleton_ready",
            pages=skel.total_pages,
            clean_pages=len(clean_pages),
            priority_count=len(priority_pages),
            elapsed=f"{t_skel_ms:.1f}ms",
        )
        if self._review_verbose_debug_enabled():
            print(
                "[DEBUG][review_load] "
                f"skeleton_ready pages={skel.total_pages} "
                f"cache_ram_limit={getattr(PAGE_CACHE, '_max_pages', '?')} "
                f"priority_count={len(priority_pages)} "
                f"priority={self._fmt_review_pages(priority_pages)} "
                f"t={t_skel_ms:.1f}ms"
            )
        self._start_priority_render(path, priority_pages, skel.total_pages)
        self._wire_scroll_ondemand(path, skel.total_pages)

    def _start_priority_render(self, path, priority_pages, total_pages):
        """
        Launch PdfOnDemandThread for priority pages.
        On each page_ready → canvas.inject_page().
        Non-priority pages stay lazy until they become visible.

        FIX 1: We stamp self._canvas_pdf_path = path here.
        _on_page_ready checks this stamp before injecting —
        if user switched card mid-render, stamp changes and
        stale signals are silently dropped. No more 'canvas has 0 pages'.
        """
        self._stop_ondemand_thread()
        self._ondemand_kind = "priority"
        self._background_fill_state = None
        self._bg_pending_inserts.clear()
        self._priority_pages = set(priority_pages)

        # ── FIX 1: stamp current PDF path on canvas ───────────────────────────
        # This is the guard key — _on_page_ready compares against this.
        self._canvas_pdf_path = path
        self.canvas._current_pdf_path = path

        cached_priority_pages = {}
        to_render = []
        priority_t0 = time.perf_counter()
        for page_num in priority_pages:
            cached_page = PAGE_CACHE.get(path, page_num)
            if cached_page is not None and not cached_page.isNull():
                cached_priority_pages[page_num] = cached_page
            else:
                to_render.append(page_num)
        self._review_render_inflight_pages = set(int(p) for p in to_render)
        self._review_profile_log(
            "priority_split",
            requested=len(priority_pages),
            cache_hits=len(cached_priority_pages),
            renders=len(to_render),
            elapsed=f"{(time.perf_counter() - priority_t0) * 1000:.1f}ms",
        )

        # Inject already-cached pages immediately (no thread needed)
        for pn, pg in cached_priority_pages.items():
            if pg and not pg.isNull():
                self._debug_review_lazy_page_loaded(
                    source="cache",
                    page_num=pn,
                    pixmap=pg,
                    kind="priority",
                    canvas_wh=f"{self.canvas.width()}x{self.canvas.height()}px",
                )
                self.canvas.inject_page(pn, pg)
                self.__dict__.setdefault("_review_canvas_real_pages", set()).add(
                    int(pn)
                )
                self._debug_review_page_injection(
                    page_num=pn, injected=True, kind="priority"
                )

        if not to_render:
            self._background_fill_state = None
            self._bg_remaining = None
            self._ondemand_kind = None
            return

        print(
            "[DEBUG][review_priority] "
            f"start render={self._fmt_review_pages(to_render)} "
            f"cached={self._fmt_review_pages(cached_priority_pages.keys())}"
        )
        self._ondemand_thread = PdfOnDemandThread(
            path, to_render, zoom=self._pdf_render_zoom, parent=self
        )
        request_thread = self._ondemand_thread
        self._ondemand_path = path
        self._ondemand_total = total_pages
        self._ondemand_kind = "priority"
        self._ondemand_requested_pages = set(int(p) for p in to_render)
        self.__dict__.setdefault("_ondemand_request_pages_by_thread", {})[
            id(request_thread)
        ] = set(
            int(p) for p in to_render
        )

        self._ondemand_thread.page_ready.connect(self._on_page_ready)
        self._ondemand_thread.batch_done.connect(
            lambda rendered, thread=request_thread: self._on_priority_batch_done(
                path, priority_pages, total_pages, thread
            )
        )
        self._ondemand_thread.error.connect(lambda err: None)
        self._ondemand_thread.start()

    def _requested_pages_for_thread(self, thread):
        if thread is None:
            return set(self.__dict__.pop("_ondemand_requested_pages", set()) or set())
        requests = self.__dict__.setdefault("_ondemand_request_pages_by_thread", {})
        requested = set(requests.pop(id(thread), set()) or set())
        if thread is getattr(self, "_ondemand_thread", None):
            requested |= set(self.__dict__.pop("_ondemand_requested_pages", set()) or set())
        return requested

    def _on_priority_batch_done(self, path, priority_pages, total_pages, thread=None):
        requested = self._requested_pages_for_thread(thread)
        self.__dict__.setdefault("_review_render_inflight_pages", set()).difference_update(
            requested
        )
        if thread is not None and thread is not getattr(self, "_ondemand_thread", None):
            print(
                "[DEBUG][review_priority] "
                f"stale_done requested={self._fmt_review_pages(requested)}"
            )
            return
        self._background_fill_state = None
        self._bg_remaining = None
        self._ondemand_kind = None
        pending = self._pending_visible_request
        self._pending_visible_request = None
        print(
            "[DEBUG][review_priority] "
            f"done requested={self._fmt_review_pages(requested)} "
            f"pending_visible={self._fmt_review_pages(pending[1] if pending else [])}"
        )
        if pending and pending[0] == getattr(self, "_ondemand_path", None):
            pending_path, pending_pages = pending
            fresh_needed = self._review_pages_needing_render(
                pending_path,
                pending_pages,
                context="after_priority",
            )
            if fresh_needed:
                self._start_visible_page_request(pending_path, fresh_needed)

    # ── LRU window size for background fill ───────────────────────────────────
    # Background fill renders at most this many pages beyond priority set.
    # Keeps RAM bounded even for huge PDFs.
    # On-demand scroll handles anything outside this window.
    _BG_FILL_WINDOW = 15

    # Background fill runs in small batches so it can yield to scroll-driven
    # visible-page loads instead of monopolizing the render thread.
    _BG_FILL_BATCH = 2
    _BG_FILL_DELAY_MS = 250

    def _canvas_alive(self):
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return False
        try:
            canvas.objectName()
            return True
        except RuntimeError:
            return False

    def _safe_canvas_toast(self, msg):
        if not self._canvas_alive():
            print(f"[DEBUG][review_bg] toast_skip reason=canvas_deleted msg={msg}")
            return
        try:
            self.canvas._show_toast(msg)
        except RuntimeError as exc:
            print(f"[DEBUG][review_bg] toast_skip reason=qt_deleted error={exc}")

    def _queue_background_ready(self, path, rendered):
        if path != getattr(self, "_canvas_pdf_path", None):
            print(f"[DEBUG][review_bg] stale_ready_skip path={path}")
            return
        ready = [pn for pn in rendered if PAGE_CACHE.get(path, pn) is not None]
        if not ready:
            return
        for pn in ready:
            cached = PAGE_CACHE.get(path, pn)
            if cached and not cached.isNull():
                self._bg_pending_inserts[pn] = cached
        self._bg_prefetch_rendered_count += len(ready)
        total = self._bg_prefetch_total_pages or max(
            self._bg_prefetch_rendered_count, 1
        )
        self._bg_prefetch_cached_count = min(
            self._bg_prefetch_cached_count + len(ready), total
        )
        msg = "BG ready: " + ", ".join(f"p.{pn+1}" for pn in sorted(ready))
        self._safe_canvas_toast(msg)
        self._note_user_activity()

    def _flush_pending_background_inserts(self):
        if not self._bg_pending_inserts:
            return
        current_path = getattr(self, "_canvas_pdf_path", None)
        if not current_path:
            self._bg_pending_inserts.clear()
            return
        if self._pending_visible_request:
            if self._ui_idle_timer is not None:
                self._ui_idle_timer.start()
            return
        if (
            self._ondemand_thread
            and self._ondemand_thread.isRunning()
            and getattr(self, "_ondemand_kind", None) == "visible"
        ):
            if self._ui_idle_timer is not None:
                self._ui_idle_timer.start()
            return
        if (
            self._ondemand_thread
            and self._ondemand_thread.isRunning()
            and getattr(self, "_ondemand_kind", None) == "background"
        ):
            # let the background render continue, but flush only on idle timeout
            return
        if not self._canvas_alive():
            print("[DEBUG][review_bg] insert_skip reason=canvas_deleted")
            self._bg_pending_inserts.clear()
            return
        # The old prefetch-accept dialog was removed, so background-ready pages
        # must auto-insert as soon as the UI is idle instead of waiting on a
        # flag that no longer has a user-facing control.
        ready_items = sorted(self._bg_pending_inserts.items())
        self._bg_pending_inserts.clear()
        for pn, pg in ready_items:
            pg = self._coerce_page_pixmap(pg)
            if pg is None:
                continue
            self._debug_review_lazy_page_loaded(
                source="cache",
                page_num=pn,
                pixmap=pg,
                kind="background",
                canvas_wh=f"{self.canvas.width()}x{self.canvas.height()}px",
            )
            self.canvas.inject_page(pn, pg)
            self.__dict__.setdefault("_review_canvas_real_pages", set()).add(int(pn))
            self._debug_review_page_injection(
                page_num=pn, injected=True, kind="background"
            )
        if ready_items:
            self._safe_canvas_toast(
                "Inserted " + ", ".join(f"p.{pn+1}" for pn, _ in ready_items)
            )

    def _start_background_fill(self, path, already_rendered, total_pages):
        if path != getattr(self, "_canvas_pdf_path", None):
            print(f"[DEBUG][review_bg] start_skip reason=stale_path path={path}")
            return
        if not self._canvas_alive():
            print("[DEBUG][review_bg] start_skip reason=canvas_deleted")
            return
        scan_t0 = time.perf_counter()
        cached_indices = set(PAGE_CACHE.cached_page_indices(path, total_pages, variant=self._pdf_render_zoom))
        cached_pages = len(cached_indices)
        perf_log(
            "review_bg_fill_count_scan",
            file=os.path.basename(path),
            total_pages=total_pages,
            cache_probes=total_pages,
            cached_pages=cached_pages,
            elapsed_ms=round((time.perf_counter() - scan_t0) * 1000.0, 3),
        )
        self._bg_accept_mode = False
        self._bg_prefetch_total_pages = total_pages
        self._bg_prefetch_cached_count = cached_pages
        self._bg_prefetch_rendered_count = len(already_rendered)
        self._show_bg_prefetch_dialog(path, total_pages)
        self._sync_bg_prefetch_dialog(path, total_pages, done=False)
        self._safe_canvas_toast(f"Ready: {cached_pages}/{total_pages} pages cached")

        # Defer if a visible-page request is in flight. Scroll responsiveness
        # wins over background cache completion.
        if self._ondemand_thread and self._ondemand_thread.isRunning():
            if getattr(self, "_ondemand_kind", None) == "visible":
                self._background_fill_state = (
                    path,
                    list(already_rendered),
                    total_pages,
                )
                return
            if getattr(self, "_ondemand_kind", None) == "background":
                return

        # ?? FIX 1 guard: if card switched, abort ?????????????????????????????
        if getattr(self, "_canvas_pdf_path", None) != path:
            return

        all_pages = set(range(total_pages))
        canvas_real = set(self.__dict__.get("_review_canvas_real_pages", set()) or set())
        pending_bg = set((self.__dict__.get("_bg_pending_inserts", {}) or {}).keys())
        skip_scan_t0 = time.perf_counter()
        cached_skip_pages = cached_indices
        perf_log(
            "review_bg_fill_remaining_scan",
            file=os.path.basename(path),
            total_pages=total_pages,
            cache_probes=total_pages,
            cached_pages=len(cached_skip_pages),
            already_rendered=len(already_rendered or []),
            canvas_real=len(canvas_real),
            pending_bg=len(pending_bg),
            elapsed_ms=round((time.perf_counter() - skip_scan_t0) * 1000.0, 3),
        )
        skip = set(already_rendered) | cached_skip_pages | canvas_real | pending_bg
        remaining = sorted(all_pages - skip)

        if not remaining:
            self._safe_canvas_toast(f"PDF ready: {total_pages} pages")
            self._background_fill_state = None
            self._bg_remaining = None
            self._ondemand_kind = None
            self._bg_accept_mode = True
            self._sync_bg_prefetch_dialog(path, total_pages, done=True)
            return

        priority_pages = set(getattr(self, "_priority_pages", set()) or set())
        background_done = set(already_rendered) - priority_pages
        remaining_slots = max(0, self._BG_FILL_WINDOW - len(background_done))
        if remaining_slots <= 0:
            self._background_fill_state = None
            self._bg_remaining = None
            self._ondemand_kind = None
            return

        windowed = remaining[: min(self._BG_FILL_BATCH, remaining_slots)]
        next_rendered = sorted(set(already_rendered) | set(windowed))
        self._bg_remaining = set(remaining)

        self._stop_ondemand_thread()
        self._ondemand_kind = "background"
        self._background_fill_state = (path, next_rendered, total_pages)

        # Verify canvas is still intact after stop (regression check for the wipe bug)
        if not self._canvas_alive():
            print("[DEBUG][review_bg] start_skip reason=canvas_deleted")
            return
        canvas_pages_after_stop = len(self.canvas._pages)
        if canvas_pages_after_stop == 0:
            return

        self._ondemand_thread = PdfOnDemandThread(
            path, windowed, zoom=self._pdf_render_zoom, parent=self
        )
        request_thread = self._ondemand_thread
        self._ondemand_path = path
        self._ondemand_total = total_pages
        self._ondemand_kind = "background"
        self._review_render_inflight_pages = set(int(p) for p in windowed)
        self._ondemand_requested_pages = set(int(p) for p in windowed)
        self.__dict__.setdefault("_ondemand_request_pages_by_thread", {})[
            id(request_thread)
        ] = set(
            int(p) for p in windowed
        )
        print(
            "[DEBUG][review_bg] "
            f"start window={self._fmt_review_pages(windowed)} "
            f"remaining={len(remaining)} slots={remaining_slots}"
        )

        self._ondemand_thread.page_ready.connect(self._on_page_ready)
        self._ondemand_thread.batch_done.connect(
            lambda rendered, thread=request_thread, p=path, ar=next_rendered, tp=total_pages: self._on_background_fill_batch_done(
                rendered, p, ar, tp, thread
            )
        )
        self._ondemand_thread.error.connect(lambda err: None)
        self._ondemand_thread.start()

    def _on_background_fill_batch_done(
        self, rendered, path, already_rendered, total_pages, thread=None
    ):
        requested = self._requested_pages_for_thread(thread)
        self.__dict__.setdefault("_review_render_inflight_pages", set()).difference_update(
            requested
        )
        if thread is not None and thread is not getattr(self, "_ondemand_thread", None):
            print(
                "[DEBUG][review_bg] "
                f"stale_done requested={self._fmt_review_pages(requested)}"
            )
            return
        if path != getattr(self, "_canvas_pdf_path", None):
            print(f"[DEBUG][review_bg] batch_skip reason=stale_path path={path}")
            self._background_fill_state = None
            self._bg_remaining = None
            self._ondemand_kind = None
            return
        combined = sorted(set(already_rendered) | set(rendered))
        self._queue_background_ready(path, rendered)
        canvas_real = set(self.__dict__.get("_review_canvas_real_pages", set()) or set())
        pending_bg = set((self.__dict__.get("_bg_pending_inserts", {}) or {}).keys())
        scan_t0 = time.perf_counter()

        rendered_set = set(rendered)
        if getattr(self, "_bg_remaining", None) is not None:
            self._bg_remaining.difference_update(rendered_set)
            self._bg_remaining.difference_update(canvas_real)
            self._bg_remaining.difference_update(pending_bg)

        has_remaining = bool(self._bg_remaining) if getattr(self, "_bg_remaining", None) is not None else False
        remaining_count = len(self._bg_remaining) if getattr(self, "_bg_remaining", None) is not None else 0

        perf_log(
            "review_bg_batch_remaining_scan",
            file=os.path.basename(path),
            total_pages=total_pages,
            remaining=remaining_count,
            combined=len(combined),
            canvas_real=len(canvas_real),
            pending_bg=len(pending_bg),
            elapsed_ms=round((time.perf_counter() - scan_t0) * 1000.0, 3),
        )

        if has_remaining:
            self._background_fill_state = (path, combined, total_pages)
            self._ondemand_kind = None
            self._sync_bg_prefetch_dialog(path, total_pages, done=False)
            print(
                "[DEBUG][review_bg] "
                f"batch_done rendered={self._fmt_review_pages(rendered)} "
                f"requested={self._fmt_review_pages(requested)} "
                f"remaining={remaining_count}"
            )
            if self._ui_idle_timer is not None:
                self._ui_idle_timer.start(self._BG_FILL_DELAY_MS)
            return

        self._background_fill_state = None
        self._bg_remaining = None
        self._ondemand_kind = None
        self._bg_accept_mode = True
        self._sync_bg_prefetch_dialog(path, total_pages, done=True)
        print(
            "[DEBUG][review_bg] "
            f"done rendered={self._fmt_review_pages(rendered)} "
            f"requested={self._fmt_review_pages(requested)}"
        )
        self._safe_canvas_toast(f"PDF ready: {total_pages} pages")

    def _wire_scroll_ondemand(self, path, total_pages):
        """
        Connect scroll area's visible_pages_changed signal → on-demand render.
        Safe to call multiple times — disconnects old connection first.
        """
        try:
            self._canvas_scroll.visible_pages_changed.disconnect(
                self._on_visible_pages_changed
            )
        except Exception:
            pass  # not connected yet — fine

        # Store path+total for use in the slot
        self._ondemand_path = path
        self._ondemand_total = total_pages
        self._visible_debug_seen_pages = set()

        self._canvas_scroll.visible_pages_changed.connect(
            self._on_visible_pages_changed
        )

    def _review_pages_needing_render(self, path, page_nums, context="visible"):
        t0 = time.perf_counter()
        real_pages = set(self.__dict__.get("_review_canvas_real_pages", set()) or set())
        pending_bg = set((self.__dict__.get("_bg_pending_inserts", {}) or {}).keys())
        inflight = set(
            self.__dict__.get("_review_render_inflight_pages", set()) or set()
        )
        pending = self.__dict__.get("_pending_visible_request")
        pending_visible = (
            set(int(pn) for pn in (pending[1] or []))
            if pending and pending[0] == path
            else set()
        )
        needed = []
        skipped = {
            "canvas_real": 0,
            "pending_bg": 0,
            "inflight": 0,
            "pending_visible": 0,
            "cache_hot": 0,
        }
        candidates = sorted({int(pn) for pn in (page_nums or [])})
        cache_checks = 0
        cache_hits = 0
        for pn in candidates:
            if pn in real_pages:
                skipped["canvas_real"] += 1
                continue
            if pn in pending_bg:
                skipped["pending_bg"] += 1
                continue
            if pn in inflight:
                skipped["inflight"] += 1
                continue
            if pn in pending_visible:
                skipped["pending_visible"] += 1
                continue
            cache_checks += 1
            cached = PAGE_CACHE.get(path, pn, ram_only=True)
            if cached is not None and not cached.isNull():
                cache_hits += 1
                skipped["cache_hot"] += 1
                continue
            needed.append(pn)

        if self._review_verbose_debug_enabled():
            print(
                "[DEBUG][review_decision] "
                f"context={context} candidates={self._fmt_review_pages(page_nums)} "
                f"need={self._fmt_review_pages(needed)} "
                f"skip_canvas={skipped['canvas_real']} "
                f"skip_cache={skipped['cache_hot']} "
                f"skip_inflight={skipped['inflight']} "
                f"skip_pending={skipped['pending_visible']} "
                f"skip_bg={skipped['pending_bg']}"
            )
        perf_log(
            "review_pages_needing_render",
            context=context,
            file=os.path.basename(path) if path else "",
            candidates=len(candidates),
            needed=len(needed),
            cache_checks=cache_checks,
            cache_hits=cache_hits,
            skipped=skipped,
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        return needed

    def _on_visible_pages_changed(self, first, last):
        """
        Called 120ms after scroll stops (debounced).
        Renders any visible pages that are still placeholders.
        """
        self._note_user_activity()
        path = getattr(self, "_ondemand_path", None)
        total_pages = getattr(self, "_ondemand_total", 0)

        if not path:
            return
        if self.__dict__.get("_review_defer_visible_until_centered", False):
            return

        first = max(0, int(first))
        last = max(first, int(last))
        visible_pages = list(range(first, last + 1))
        prev_visible = set(
            self.__dict__.get("_visible_debug_seen_pages", set()) or set()
        )
        entered_pages = [pn for pn in visible_pages if pn not in prev_visible]
        self._visible_debug_seen_pages = set(visible_pages)
        if entered_pages and self._review_verbose_debug_enabled():
            current_page = visible_pages[len(visible_pages) // 2]
            entered_states = ", ".join(
                f"p.{pn + 1}:{self._review_page_view_state(path, pn)}"
                for pn in entered_pages
            )
            print(
                f"[DEBUG][review_viewport] visible=p.{first + 1}-p.{last + 1} "
                f"current=p.{current_page + 1}:{self._review_page_view_state(path, current_page)} "
                f"entered={entered_states}"
            )

        self._inject_cached_visible_pages(path, visible_pages)
        needed = self._review_pages_needing_render(
            path,
            range(first, last + 1),
            context="visible",
        )

        if not needed:
            return

        if self._ondemand_thread and self._ondemand_thread.isRunning():
            kind = getattr(self, "_ondemand_kind", None)
            if kind in ("background", "priority"):
                if self._review_verbose_debug_enabled():
                    print(
                        "[DEBUG][review_ondemand] "
                        f"preempt kind={kind} need={self._fmt_review_pages(needed)}"
                    )
                self._stop_ondemand_thread()
                self._ondemand_kind = None
                self._start_visible_page_request(path, needed)
                return

            if self._review_verbose_debug_enabled():
                print(
                    "[DEBUG][review_ondemand] "
                    f"queue_visible kind={kind} need={self._fmt_review_pages(needed)}"
                )
            self._pending_visible_request = (path, list(needed))
            return

        self._start_visible_page_request(path, needed)

    def _inject_cached_visible_pages(self, path, visible_pages):
        t0 = time.perf_counter()
        visible_pages = [int(pn) for pn in (visible_pages or [])]
        real_pages = set(self.__dict__.get("_review_canvas_real_pages", set()) or set())
        pending_bg = set((self.__dict__.get("_bg_pending_inserts", {}) or {}).keys())
        inflight = set(
            self.__dict__.get("_review_render_inflight_pages", set()) or set()
        )
        injected = []
        cache_checks = 0
        cache_hits = 0
        for pn in visible_pages:
            if pn in real_pages or pn in pending_bg or pn in inflight:
                continue
            cache_checks += 1
            cached = PAGE_CACHE.get(path, pn, ram_only=True)
            if cached is None or cached.isNull():
                continue
            cache_hits += 1
            self._debug_review_lazy_page_loaded(
                source="cache",
                page_num=pn,
                pixmap=cached,
                kind="visible_cache",
                canvas_wh=f"{self.canvas.width()}x{self.canvas.height()}px",
            )
            self.canvas.inject_page(pn, cached)
            self.__dict__.setdefault("_review_canvas_real_pages", set()).add(pn)
            self._debug_review_page_injection(
                page_num=pn, injected=True, kind="visible_cache"
            )
            injected.append(pn)
        perf_log(
            "review_inject_cached_visible",
            file=os.path.basename(path) if path else "",
            visible=len(visible_pages),
            injected=len(injected),
            cache_checks=cache_checks,
            cache_hits=cache_hits,
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        if injected:
            if self._review_verbose_debug_enabled():
                print(
                    "[DEBUG][review_visible_cache] hydrate "
                    + ", ".join(f"p.{pn + 1}" for pn in injected)
                )
            self._update_review_page_nav_ui()

    def _start_visible_page_request(self, path, needed):
        self._pending_visible_request = None
        needed = self._review_pages_needing_render(
            path,
            needed,
            context="start_visible",
        )
        if needed:
            if self._review_verbose_debug_enabled():
                print(
                    "[DEBUG][review_ondemand] render_request "
                    + ", ".join(f"p.{pn + 1}" for pn in needed)
                )
        else:
            return
        self.__dict__.setdefault("_review_render_inflight_pages", set()).update(needed)
        self._ondemand_kind = "visible"
        self._ondemand_thread = PdfOnDemandThread(
            path, needed, zoom=self._pdf_render_zoom, parent=self
        )
        request_thread = self._ondemand_thread
        self._ondemand_requested_pages = set(int(p) for p in needed)
        self.__dict__.setdefault("_ondemand_request_pages_by_thread", {})[
            id(request_thread)
        ] = set(
            int(p) for p in needed
        )
        self._ondemand_thread.page_ready.connect(self._on_page_ready)
        self._ondemand_thread.batch_done.connect(
            lambda rendered, thread=request_thread: self._on_visible_pages_batch_done(
                rendered, thread
            )
        )
        self._ondemand_thread.start()

    def _on_visible_pages_batch_done(self, rendered, thread=None):
        self._note_user_activity()
        requested = self._requested_pages_for_thread(thread)
        self.__dict__.setdefault("_review_render_inflight_pages", set()).difference_update(
            requested
        )
        if thread is not None and thread is not getattr(self, "_ondemand_thread", None):
            return

        pending = self._pending_visible_request
        self._pending_visible_request = None
        if pending and pending[0] == getattr(self, "_ondemand_path", None):
            path, needed = pending
            fresh_needed = self._review_pages_needing_render(
                path,
                needed,
                context="after_visible",
            )
            if fresh_needed:
                self._start_visible_page_request(path, fresh_needed)
            else:
                self._ondemand_kind = None
        elif getattr(self, "_ondemand_kind", None) == "visible":
            self._ondemand_kind = None
        if self._review_verbose_debug_enabled():
            print(
                "[DEBUG][review_ondemand] "
                f"batch_done requested={self._fmt_review_pages(requested)} "
                f"rendered={self._fmt_review_pages(rendered)} "
                f"pending={self._fmt_review_pages(pending[1] if pending else [])}"
            )

        bg_state = self._background_fill_state
        if (
            bg_state
            and not (self._ondemand_thread and self._ondemand_thread.isRunning())
            and not self._pending_visible_request
        ):
            bg_path, bg_already_rendered, bg_total = bg_state
            if getattr(self, "_canvas_pdf_path", None) == bg_path:
                self._start_background_fill(bg_path, bg_already_rendered, bg_total)

    def _on_page_ready(self, page_num, qpx):
        """
        Slot — called from PdfOnDemandThread.page_ready signal.

        FIX 1: Check _canvas_pdf_path stamp before injecting.
        If user switched to a different card mid-render, the thread's
        path no longer matches the canvas's current PDF — drop the signal.
        This is what caused 'canvas has 0 pages' — canvas was already
        wiped by the new card's load_pages() call.
        """
        current_path = getattr(self, "_canvas_pdf_path", None)
        thread_path = getattr(self, "_ondemand_path", None)
        page_num = int(page_num)
        self.__dict__.setdefault("_review_render_inflight_pages", set()).discard(
            page_num
        )

        if current_path != thread_path:
            self._debug_review_page_injection(
                page_num=page_num,
                injected=False,
                kind=getattr(self, "_ondemand_kind", None) or "visible",
                reason="stale_path",
            )
            return

        canvas_len = len(self.canvas._pages)
        canvas_wh = f"{self.canvas.width()}x{self.canvas.height()}px"

        # Guard: canvas wiped — should not happen after _stop_ondemand_thread fix
        if canvas_len == 0:
            self._debug_review_page_injection(
                page_num=page_num,
                injected=False,
                kind=getattr(self, "_ondemand_kind", None) or "visible",
                reason="canvas_empty",
            )
            return

        cache_px = self._coerce_page_pixmap(qpx)
        if cache_px is None:
            self._debug_review_page_injection(
                page_num=page_num,
                injected=False,
                kind=getattr(self, "_ondemand_kind", None) or "visible",
                reason="null_page",
            )
            return

        load_kind = getattr(self, "_ondemand_kind", None) or "visible"
        self._debug_review_lazy_page_loaded(
            source="render",
            page_num=page_num,
            pixmap=cache_px,
            kind=load_kind,
            canvas_wh=canvas_wh,
        )

        if getattr(self, "_ondemand_kind", None) == "background":
            self._bg_pending_inserts[page_num] = cache_px
            self._debug_review_page_injection(
                page_num=page_num,
                injected=False,
                kind=load_kind,
                reason="queued_pending_insert",
            )
            return
        from PyQt5.QtGui import QPixmap

        if isinstance(cache_px, QPixmap):
            PAGE_CACHE.put(
                thread_path, page_num, cache_px, render_zoom=self._pdf_render_zoom
            )
        self.canvas.inject_page(page_num, cache_px)
        self.__dict__.setdefault("_review_canvas_real_pages", set()).add(page_num)
        self._debug_review_page_injection(
            page_num=page_num,
            injected=True,
            kind=load_kind,
        )
        if load_kind == "visible" and self._review_verbose_debug_enabled():
            print(f"[DEBUG][review_ondemand] loaded p.{page_num + 1}")
        self._update_review_page_nav_ui()

    @staticmethod
    def _coerce_page_pixmap(page_obj):
        from PyQt5.QtGui import QImage, QPixmap

        if isinstance(page_obj, QPixmap):
            return page_obj if not page_obj.isNull() else None
        if isinstance(page_obj, QImage):
            px = QPixmap.fromImage(page_obj)
            return px if not px.isNull() else None
        if page_obj is not None and hasattr(page_obj, "isNull"):
            try:
                is_null = page_obj.isNull()
                if isinstance(is_null, bool) and is_null:
                    return None
                return page_obj
            except Exception:
                return page_obj
        return None

    def _debug_review_lazy_page_loaded(
        self, source: str, page_num: int, pixmap, kind: str = "", canvas_wh: str = ""
    ):
        if not self._review_verbose_debug_enabled():
            return
        if self.__dict__.get("_review_lazy_trace_suspended", False):
            return
        page_num = int(page_num)
        emoji = "⚡" if str(source).strip().lower() == "cache" else "👀"
        print(f"[DEBUG][review_lazy] {emoji} p.{page_num + 1}")

    def _review_page_view_state(self, path: str, page_num: int) -> str:
        page_num = int(page_num)
        if page_num in set(
            self.__dict__.get("_review_canvas_real_pages", set()) or set()
        ):
            return "canvas_real"
        if page_num in set((self.__dict__.get("_bg_pending_inserts", {}) or {}).keys()):
            return "rendered_waiting_inject"
        pending = self.__dict__.get("_pending_visible_request")
        if pending and pending[0] == path and page_num in set(pending[1] or []):
            return "queued_visible_render"
        if page_num in set(
            self.__dict__.get("_review_render_inflight_pages", set()) or set()
        ):
            return "rendering"
        cached = PAGE_CACHE.get(path, page_num, ram_only=True)
        if cached is not None and not cached.isNull():
            return "cache_hot_canvas_gray"
        pages = getattr(getattr(self, "canvas", None), "_pages", None) or []
        if (
            0 <= page_num < len(pages)
            and pages[page_num] is not None
            and not pages[page_num].isNull()
        ):
            return "placeholder_gray"
        return "canvas_missing"

    def _debug_review_page_injection(
        self, page_num: int, injected: bool, kind: str = "", reason: str = ""
    ):
        if not self._review_verbose_debug_enabled():
            return
        page_num = int(page_num)
        status = "yes" if injected else "no"
        parts = [f"[DEBUG][review_inject] p.{page_num + 1} injected={status}"]
        if kind:
            parts.append(f"kind={kind}")
        if reason:
            parts.append(f"reason={reason}")
        print(" ".join(parts))

    def _debug_review_lazy_pages_loaded(self, source: str, page_nums):
        for page_num in page_nums or []:
            self._debug_review_lazy_page_loaded(
                source=source, page_num=page_num, pixmap=None
            )

    def _stop_ondemand_thread(self):
        """
        Safely stop any running PdfOnDemandThread.

        ── BUG FIX (v20-patch) ──────────────────────────────────────────────────
        BEFORE (broken):
            if thread running  → stop it
            else               → canvas.load_pixmap(QPixmap())   ← WIPED _pages!

        The else branch fired every time _stop_ondemand_thread() was called when
        no thread was running yet — e.g. the very first call from
        _start_background_fill() right after skeleton load.
        load_pixmap(null-QPixmap) sets _pages=[] and resizes canvas to 1×1 px,
        so every subsequent inject_page() hit "out of range (canvas has 0 pages)".

        FIX: simply remove the else branch. Callers that need UI resets
        (_show_overlay, _rating_frame.hide) already do so themselves.
        ─────────────────────────────────────────────────────────────────────────
        """
    def _stop_ondemand_thread(self, shutdown=False):
        """
        Stop the on-demand page rendering thread.
        """
        t = getattr(self, "_ondemand_thread", None)
        if t and t.isRunning():
            if shutdown:
                t.stop()
                t.quit()
                t.wait(400)
            else:
                self._add_thread_to_cleanups(t)
                t.stop()
                t.quit()
        requested = set(self.__dict__.pop("_ondemand_requested_pages", set()) or set())
        if requested:
            self.__dict__.setdefault(
                "_review_render_inflight_pages", set()
            ).difference_update(requested)
        requests = self.__dict__.setdefault("_ondemand_request_pages_by_thread", {})
        requests.clear()
        # Always clear the reference so the next start gets a fresh thread
        self._ondemand_thread = None

    def _apply_canvas(self, card, box_idx, px):
        """Pixmap + boxes canvas pe set karo — sync aur async dono paths use karte hain."""
        self._current_pixmap = px
        _pdf_path = resolve_asset_path(card.get("pdf_path", ""))
        # [PIXMAP REGISTRY] ReviewWindow ka current pixmap + canvas track karo
        from cache_manager import PIXMAP_REGISTRY

        PIXMAP_REGISTRY.register(
            f"review_current_{id(self)}", self, "_current_pixmap", _pdf_path
        )
        self.canvas._current_pdf_path = _pdf_path
        boxes = card.get("boxes", [])
        from data_manager import store
        invert = store.get().get("_invert_pdf", False)
        if invert and px and not px.isNull():
            from PyQt5.QtGui import QImage
            img = px.toImage()
            img.invertPixels(QImage.InvertRgb)
            px_to_load = QPixmap.fromImage(img)
        else:
            px_to_load = px
        self.canvas.load_pixmap(px_to_load)
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            display_boxes = [
                {
                    **{
                        k: b[k]
                        for k in (
                            "rect",
                            "label",
                            "shape",
                            "angle",
                            "group_id",
                            "box_id",
                            "note",
                        )
                        if k in b
                    },
                    "rect": b["rect"],
                    "label": b.get("label", ""),
                    "note": b.get("note", ""),
                    "revealed": False,
                }
                for b in boxes
            ]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(-1)
            self.canvas.set_mode("review")
            self.canvas.set_target_group(gid)
        elif box_idx is None:
            display_boxes = [
                {
                    "rect": b["rect"],
                    "label": b.get("label", ""),
                    "note": b.get("note", ""),
                    "shape": b.get("shape", "rect"),
                    "angle": b.get("angle", 0.0),
                    "group_id": b.get("group_id", ""),
                    "revealed": False,
                }
                for i, b in enumerate(boxes)
            ]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(-1)
            self.canvas.set_mode("review")
        else:
            display_boxes = [
                {
                    "rect": b["rect"],
                    "label": b.get("label", ""),
                    "note": b.get("note", ""),
                    "shape": b.get("shape", "rect"),
                    "angle": b.get("angle", 0.0),
                    "group_id": b.get("group_id", ""),
                    "revealed": False,
                }
                for i, b in enumerate(boxes)
            ]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(box_idx)
            self.canvas.set_mode("review")

        # FIX: retain user-set zoom for image cards too
        from PyQt5.QtCore import QTimer

        def _apply_zoom_and_center_img():
            if self._user_zoom_scale is not None:
                self.canvas._scale = self._user_zoom_scale
                self.canvas._on_zoom()
            else:
                self._zoom_fit()
            self._center_on_target()
            self._update_review_page_nav_ui()

        QTimer.singleShot(0, _apply_zoom_and_center_img)
        self._update_mask_note_ui()
        self._update_pen_button_states()

    def _apply_canvas_pages(self, card, box_idx, pages):
        """File: anki_occlusion_v19.py -> Class: ReviewScreen"""
        path = resolve_asset_path(card.get("pdf_path", ""))
        self._canvas_pdf_path = path
        self.canvas._current_pdf_path = path
        self._review_defer_visible_until_centered = True
        if hasattr(self.canvas, "clear_peek_target"):
            self.canvas.clear_peek_target()

        # 1. Load ALL pages
        self.canvas.load_pages(pages)

        # 3. set_mode FIRST so it doesn't wipe revealed state set below
        self.canvas.set_mode("review")

        # 4. Setup boxes state (must come AFTER set_mode)
        boxes = card.get("boxes", []) or []
        source_box_zoom = card.get("_pdf_box_render_zoom")
        if source_box_zoom is None:
            source_box_zoom = PDF_LEGACY_BOX_ZOOM
        if path and boxes:
            boxes = self._adapt_review_boxes(card, path)
            self._pdf_quality_debug(
                "box_remap",
                source_zoom=source_box_zoom,
                target_zoom=self._pdf_render_zoom,
                boxes=len(boxes),
            )
        if isinstance(box_idx, tuple) and box_idx[0] == "group":
            gid = box_idx[1]
            display_boxes = [{**b, "revealed": False} for b in boxes]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_group(gid)
        else:
            display_boxes = [{**b, "revealed": False} for i, b in enumerate(boxes)]
            self.canvas.set_boxes_with_state(display_boxes)
            self.canvas.set_target_box(box_idx if box_idx is not None else -1)

        # 5. Always reset UI state — Show Answer bar visible, rating hidden
        self._show_overlay(self._reveal_bar)
        self._rating_frame.hide()
        self._maybe_auto_reveal()

        # 6. Zoom fit + center (deferred so viewport geometry is final)
        from PyQt5.QtCore import QTimer

        if self._pending_reload_page is not None:
            reload_page = self._pending_reload_page
            self._pending_reload_page = None
            def _apply_reload_zoom_and_page(pg=reload_page):
                self._zoom_fit()
                self.canvas.scroll_to_page(pg, self._canvas_scroll)
                self._review_defer_visible_until_centered = False
                self._canvas_scroll._emit_visible_pages()

            QTimer.singleShot(0, _apply_reload_zoom_and_page)
        else:
            # FIX: retain user-set zoom across cards
            def _apply_zoom_and_center():
                if self._user_zoom_scale is not None:
                    self.canvas._scale = self._user_zoom_scale
                    self.canvas._on_zoom()
                else:
                    self._zoom_fit()
                self._center_on_target()
                self._review_defer_visible_until_centered = False
                self._canvas_scroll._emit_visible_pages()

            QTimer.singleShot(0, _apply_zoom_and_center)
        QTimer.singleShot(0, self._update_review_page_nav_ui)

        # 7. Rebuild queue now that _page_tops is populated with real page positions
        QTimer.singleShot(50, self._rebuild_queue)
        QTimer.singleShot(120, self._canvas_scroll._emit_visible_pages)
        self._update_mask_note_ui()
        self._update_pen_button_states()

    def _start_review_pdf_thread(self, card, box_idx):
        path = resolve_asset_path(card.get("pdf_path", ""))
        if (
            hasattr(self, "_pdf_loader_thread")
            and self._pdf_loader_thread
            and self._pdf_loader_thread.isRunning()
        ):
            t = self._pdf_loader_thread
            self._add_thread_to_cleanups(t)
            t.stop()
            t.quit()

        self._pdf_render_zoom = choose_pdf_render_zoom(get_pdf_page_count(path))
        profile_reset = ensure_pdf_cache_profile(path, self._pdf_render_zoom)
        self._pdf_quality_debug(
            "fallback_loader",
            pages=get_pdf_page_count(path),
            zoom=self._pdf_render_zoom,
            reset_cache=profile_reset,
        )
        self._pdf_loader_thread = PdfLoaderThread(
            path, zoom=self._pdf_render_zoom, parent=self
        )
        self._pending_review_card = card
        self._pending_review_box_idx = box_idx
        self._review_loader_logged_pages = 0

        # [FIX] Show first chunk instantly as pages arrive
        self._pdf_loader_thread.pages_ready.connect(self._on_review_pages_chunk)
        self._pdf_loader_thread.done.connect(self._on_review_pages_ready)
        self._pdf_loader_thread.start()

        # Show loading toast immediately
        total = get_pdf_page_count(path) or "?"
        self.canvas._show_toast(f"⏳ Loading PDF... 0/{total} pages")
        self._pdf_total_pages = total

    def _coerce_loader_pages_to_pixmaps(self, path: str, pages: list):
        out = []
        for page_num, page_obj in enumerate(pages or []):
            px = self._coerce_page_pixmap(page_obj)
            if px is not None:
                PAGE_CACHE.put(
                    path,
                    page_num,
                    px,
                    render_zoom=self._pdf_render_zoom,
                )
            out.append(px)
        return out

    def _on_review_pages_chunk(self, pages, loaded, total):
        """Show first pages as soon as first chunk arrives — don't wait for full load."""
        card = self._pending_review_card
        box_idx = self._pending_review_box_idx
        path = resolve_asset_path(card.get("pdf_path", ""))
        pages = self._coerce_loader_pages_to_pixmaps(path, pages)
        start_idx = int(getattr(self, "_review_loader_logged_pages", 0) or 0)
        end_idx = min(int(loaded or 0), len(pages or []))
        if end_idx > start_idx:
            self._debug_review_lazy_pages_loaded(
                source="render", page_nums=range(start_idx, end_idx)
            )
            self._review_loader_logged_pages = end_idx
        if pages:
            self._apply_canvas_pages(card, box_idx, pages)
            self._review_canvas_real_pages = set(range(len(pages)))
            self._review_render_inflight_pages.clear()
        self.canvas._show_toast(f"⏳ Loading PDF... {loaded}/{total} pages")

    def _on_review_pages_ready(self, pages, err):
        if not pages or err:
            return
        card = self._pending_review_card
        box_idx = self._pending_review_box_idx
        path = resolve_asset_path(card.get("pdf_path", ""))
        pages = self._coerce_loader_pages_to_pixmaps(path, pages)
        start_idx = int(getattr(self, "_review_loader_logged_pages", 0) or 0)
        end_idx = len(pages or [])
        if end_idx > start_idx:
            self._debug_review_lazy_pages_loaded(
                source="render", page_nums=range(start_idx, end_idx)
            )
            self._review_loader_logged_pages = end_idx
        self._apply_canvas_pages(card, box_idx, pages)
        self._review_canvas_real_pages = set(range(len(pages)))
        self._review_render_inflight_pages.clear()
        self.canvas._show_toast(f"✅ PDF loaded — {len(pages)} pages")

    def _finish(self):
        # [BUG 1 FIX] Check if any learning/relearn items are still pending
        # (e.g. m1 got Again → due in 1min, but m2/m3 finished early)
        # If yes, wait and re-check instead of ending the session.
        pending_learning = [
            (i, sm2_obj)
            for i, (_, _, sm2_obj) in enumerate(self._items)
            if sm2_obj.get("sched_state") in ("learning", "relearn")
        ]
        if pending_learning:
            # Find the earliest due learning item
            earliest_idx, earliest_obj = min(
                pending_learning, key=lambda x: x[1].get("sm2_due", "")
            )
            due_str = earliest_obj.get("sm2_due", "")
            try:
                from datetime import datetime as _dt

                due_dt = _dt.fromisoformat(due_str)
                wait_ms = max(0, int((_dt.now() - due_dt).total_seconds() * -1000))
            except Exception:
                wait_ms = 0
            if wait_ms > 0:
                # Show waiting state — re-check when earliest card becomes due
                self._show_waiting_state(wait_ms, len(pending_learning))
                return
            else:
                # Due time already passed — jump to that item directly
                self._idx = earliest_idx
                self._load_item()
                return

        self.prog.setValue(len(self._items))
        self._show_session_summary()

    def _show_session_summary(self):
        """Session khatam — stats dialog dikhao."""
        if hasattr(self.parent(), "clear_last_review_session"):
            self.parent().clear_last_review_session()
        has_pdf = any(bool(card.get("pdf_path")) for card, _, _ in self._items) if self._items else False
        if has_pdf and self.__dict__.get("_show_summary_popup", True):
            from ui.review.summary_dialog import ReviewSessionSummaryDialog
            dialog = ReviewSessionSummaryDialog(self)
            dialog.exec_()
        self.finished.emit()

    def _show_waiting_state(self, wait_ms: int, pending_count: int):
        """Learning cards pending hain — countdown show karo, session end mat karo."""
        secs = max(1, wait_ms // 1000)
        self._reveal_bar.hide()
        self._rating_frame.hide()
        # _wait_bar is a proper QFrame already in the layout (created in _setup_ui)
        mins, s = divmod(secs, 60)
        self._wait_lbl_countdown.setText(f"next card in  {mins}m {s:02d}s")
        self._wait_lbl_count.setText(f"⏳  {pending_count} card(s) still in learning")
        self._wait_bar.show()
        QTimer.singleShot(1000, self._check_learning_due)


# ═══════════════════════════════════════════════════════════════════════════════


class PdfMetadataDialog(QDialog):
    def __init__(self, lecture_num, notes_html, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit PDF Reference Notes & Metadata")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setWindowState(Qt.WindowMaximized)
        self.resize(750, 550)
        
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        from theme_manager import get_palette
        p = get_palette(theme)
        bg = p.get("C_BG", "#1E1E2E")
        surface = p.get("C_SURFACE", "#24283B")
        text = p.get("C_TEXT", "#CDD6F4")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        font_family = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        
        self.setStyleSheet(
            f"QDialog{{background:{bg};}}"
            f"QLabel{{color:{text};font-family:'{font_family}';font-size:12px;font-weight:bold;}}"
            f"QLineEdit{{background:{surface};color:{text};border:1px solid {border};border-radius:4px;padding:6px;font-size:12px;}}"
            f"QPushButton{{font-family:'{font_family}';font-size:12px;font-weight:bold;}}"
        )
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Lecture field
        lbl_lec = QLabel("Lecture Info (e.g., Lecture 5 / Chapter 2):")
        self.inp_lecture = QLineEdit()
        self.inp_lecture.setText(lecture_num)
        self.inp_lecture.setPlaceholderText("Enter lecture info, chapter number, or key topics...")
        
        layout.addWidget(lbl_lec)
        layout.addWidget(self.inp_lecture)
        
        # Notes field
        lbl_notes = QLabel("PDF-wide Reference Notes / Formulas / Images:")
        layout.addWidget(lbl_notes)
        
        from editor_ui import RichTextEdit
        self.inp_notes = RichTextEdit()
        self.inp_notes.setPlaceholderText("Type formulas, paste screen grabs (Ctrl+V), or drag and drop images here...")
        self.inp_notes.setStyleSheet(
            f"QTextEdit{{background:{surface};color:{text};border:1px solid {border};"
            f"border-radius:6px;padding:8px;font-size:13px;}}"
        )
        if "<img" in notes_html or "<html>" in notes_html or "<p>" in notes_html:
            self.inp_notes.setHtml(notes_html)
        else:
            self.inp_notes.setPlainText(notes_html)
            
        self.inp_notes.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.inp_notes, stretch=1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_save = QPushButton("💾 Save PDF Data")
        self.btn_save.setFixedHeight(34)
        if theme != "classic":
            self.btn_save.setStyleSheet(
                f"QPushButton{{background:{accent};color:{bg};border:none;border-radius:6px;padding:0 24px;font-size:13px;font-weight:bold;}}"
                f"QPushButton:hover{{background:white;color:{bg};}}"
            )
        else:
            self.btn_save.setStyleSheet(
                f"QPushButton{{background:{accent};color:white;border:none;border-radius:6px;padding:0 24px;font-size:13px;font-weight:bold;}}"
                f"QPushButton:hover{{background:#6A58E0;}}"
            )
        self.btn_save.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton("✕ Cancel")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{text};border:1px solid {border};border-radius:6px;padding:0 20px;font-size:13px;}}"
            f"QPushButton:hover{{background:{surface};}}"
        )
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)
