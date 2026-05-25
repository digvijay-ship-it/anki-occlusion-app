from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import (
    QCursor,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QPixmap,
    QPainterPath,
    QTransform,
)

import uuid
import time
import math
import copy

from cache_manager import MASK_REGISTRY, PIXMAP_REGISTRY

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


# Dummy values that were in editor_ui
PAGE_GAP = 12
REVEAL_COLOR = "#00000000"  # transparent


def _point_in_rotated_box(px, py, cx, cy, w, h, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    return abs(lx) <= w / 2 and abs(ly) <= h / 2


def _point_in_rotated_ellipse(px, py, cx, cy, rx, ry, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    if rx < 1 or ry < 1:
        return False
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1


from .state import CanvasStateMixin
from .renderer import CanvasRendererMixin
from .interaction import CanvasInteractionMixin


class OcclusionCanvas(
    CanvasStateMixin, CanvasRendererMixin, CanvasInteractionMixin, QWidget
):
    mask_selected = pyqtSignal(int)
    label_changed = pyqtSignal(int, str)
    boxes_changed = pyqtSignal(list)
    zoom_changed = pyqtSignal(float)
    ink_changed = pyqtSignal()
    right_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tell Qt this widget paints every pixel itself — no background blend needed.
        # This eliminates the implicit background fill pass Qt does before paintEvent,
        # which is the main cause of scroll lag on large canvas widgets.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

        # ── image sources ─────────────────────────────────────────────────────
        self._px = None  # QPixmap | None  — single-image mode
        self._pages = []  # list[QPixmap]   — PDF page list (image-space)
        self._page_tops = []  # list[int]        — y-offset of each page (image-space)
        self._total_h = 0  # int              — virtual canvas height (image-space)
        self._total_w = 0  # int              — max page width (image-space)

        # ── interaction ───────────────────────────────────────────────────────
        self._HANDLE_R = 4
        self._boxes = []
        self._mode = "edit"
        self._tool = "rect"
        self._scale = 1.0
        self._selected_idx = -1
        self._selected_indices = set()
        self._selection_scope = ""
        self._target_idx = -1
        self._target_group_id = ""
        self._peek_target_idx = -1
        self._peek_target_group_id = ""
        self._review_mode_style = "hide_all"
        self._peek_active = False

        self._drawing = False
        self._start = QPointF()
        self._live_rect = QRectF()

        self._drag_op = None
        self._drag_handle = -1
        self._drag_start_pos = QPointF()
        self._drag_orig_box = None
        self._drag_orig_boxes = None

        from collections import deque as _deque

        self._undo_stack = _deque(maxlen=100)
        self._redo_stack = _deque(maxlen=100)

        # ── mask GPU cache ────────────────────────────────────────────────────
        self._mask_cache_layer = None  # QPixmap
        self._mask_cache_dirty = True
        self._mask_cache_rebuild_pending = False

        # ── ink layer ─────────────────────────────────────────────────────────
        self._ink_active = False
        self._ink_strokes = []
        self._ink_current = []
        self._ink_color_idx = 0
        self._ink_colors = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]
        self._ink_width = 1.2
        self._ink_ctrl_last_time = 0.0
        self._ink_pending_mask_idx = -1
        self._ink_pending_press_ip = None
        self._ink_pending_press_sp = None
        self._ink_pending_press_time = 0.0
        self._ink_input_kind = None

        # ── zoom ──────────────────────────────────────────────────────────────
        self._fast_zoom = False
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._finalize_zoom)

        self._smooth_timer = QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.timeout.connect(self._apply_smooth)

        # ── per-page scaled pixmap cache ──────────────────────────────────────
        # dict: page_idx → (scale_at_cache_time, QPixmap)
        self._spx_cache = {}

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
