from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QEvent
from PyQt5.QtGui import QCursor, QPainter, QColor, QPen, QBrush, QPixmap, QPainterPath, QTransform

import uuid
import time
import math
import copy

from cache_manager import MASK_REGISTRY, PIXMAP_REGISTRY
C_BG      = '#1E1E2E'
C_SURFACE = '#2A2A3E'
C_CARD    = '#313145'
C_ACCENT  = '#7C6AF7'
C_GREEN   = '#50FA7B'
C_RED     = '#FF5555'
C_YELLOW  = '#F1FA8C'
C_TEXT    = '#CDD6F4'
C_SUBTEXT = '#A6ADC8'
C_BORDER  = '#45475A'


# Dummy values that were in editor_ui
PAGE_GAP = 12
REVEAL_COLOR = "#00000000"  # transparent

def _point_in_rotated_box(px, py, cx, cy, w, h, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx =  dx * cos_a - dy * sin_a
    ly =  dx * sin_a + dy * cos_a
    return abs(lx) <= w / 2 and abs(ly) <= h / 2

def _point_in_rotated_ellipse(px, py, cx, cy, rx, ry, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx =  dx * cos_a - dy * sin_a
    ly =  dx * sin_a + dy * cos_a
    if rx < 1 or ry < 1:
        return False
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1

from .state import CanvasStateMixin
from .renderer import CanvasRendererMixin
from .interaction import CanvasInteractionMixin

class OcclusionCanvas(CanvasStateMixin, CanvasRendererMixin, CanvasInteractionMixin, QWidget):
    mask_selected = pyqtSignal(int)
    label_changed = pyqtSignal(int, str)
    boxes_changed = pyqtSignal(list)
    zoom_changed  = pyqtSignal(float)
    ink_changed   = pyqtSignal()
    right_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tell Qt this widget paints every pixel itself — no background blend needed.
        # This eliminates the implicit background fill pass Qt does before paintEvent,
        # which is the main cause of scroll lag on large canvas widgets.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

        # ── image sources ─────────────────────────────────────────────────────
        self._px        = None   # QPixmap | None  — single-image mode
        self._pages     = []     # list[QPixmap]   — PDF page list (image-space)
        self._page_tops = []     # list[int]        — y-offset of each page (image-space)
        self._total_h   = 0      # int              — virtual canvas height (image-space)
        self._total_w   = 0      # int              — max page width (image-space)

        # ── interaction ───────────────────────────────────────────────────────
        self._HANDLE_R         = 4
        self._boxes            = []
        self._mode             = "edit"
        self._tool             = "rect"
        self._scale            = 1.0
        self._selected_idx     = -1
        self._selected_indices = set()
        self._selection_scope  = ""
        self._target_idx       = -1
        self._target_group_id  = ""
        self._peek_target_idx  = -1
        self._peek_target_group_id = ""
        self._review_mode_style= "hide_all"
        self._peek_active      = False

        self._drawing        = False
        self._start          = QPointF()
        self._live_rect      = QRectF()

        self._drag_op        = None
        self._drag_handle    = -1
        self._drag_start_pos = QPointF()
        self._drag_orig_box  = None
        self._drag_orig_boxes = None

        self._undo_stack = []
        self._redo_stack = []

        # ── mask GPU cache ────────────────────────────────────────────────────
        self._mask_cache_layer = None   # QPixmap
        self._mask_cache_dirty = True

        # ── ink layer ─────────────────────────────────────────────────────────
        self._ink_active         = False
        self._ink_strokes        = []
        self._ink_current        = []
        self._ink_color_idx      = 0
        self._ink_colors         = ["#FF4444", "#FFD700", "#00FFFF", "#FFFFFF"]
        self._ink_width          = 1.2
        self._ink_ctrl_last_time = 0.0

        # ── zoom ──────────────────────────────────────────────────────────────
        self._fast_zoom  = False
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
