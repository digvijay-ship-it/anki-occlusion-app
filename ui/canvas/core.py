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
import os

from collections import OrderedDict
from cache_manager import PIXMAP_REGISTRY

from .colors import (
    C_BG, C_SURFACE, C_CARD, C_ACCENT, C_GREEN, C_RED, C_YELLOW,
    C_TEXT, C_SUBTEXT, C_BORDER, PAGE_GAP, REVEAL_COLOR
)


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
        self._spx_cache = OrderedDict()
        self.SPX_CACHE_MAX = 24

        # Cache paint profile environment variable to avoid os.environ lookups during hot paintEvent calls
        self._paint_profile_enabled = (
            os.environ.get("ANKI_CANVAS_PAINT_PROFILE", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
