from PyQt5.QtWidgets import QWidget, QScrollArea, QApplication, QLabel
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, QEvent, QPoint
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
    right_clicked_box = pyqtSignal(int, QPoint)

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
        self._stroke_seq = 0
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
        self._ink_implementation = "filtered"
        self._ink_current_stable_path = QPainterPath()
        self._ink_current_path = QPainterPath()
        self._ink_mode = "pen"
        self._ink_erasing = False
        self._ink_undo_stack = []
        self._ink_redo_stack = []
        self._ink_pre_erase_snapshot = None



        # ── focus mode ────────────────────────────────────────────────────────
        from PyQt5.QtCore import QSettings
        focus_settings = QSettings("AnkiOcclusion", "FocusModeSettings")
        val = focus_settings.value("focus_mode_enabled", "false")
        self._focus_mode = (val == "true" or val is True)
        val_ultra = focus_settings.value("ultra_focus_enabled", "false")
        self._ultra_focus_mode = (val_ultra == "true" or val_ultra is True)
        try:
            self._bg_opacity = float(focus_settings.value("bg_opacity", 0.2))
        except (ValueError, TypeError):
            self._bg_opacity = 0.2


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

    def set_focus_mode(self, enabled: bool):
        self._focus_mode = enabled
        from PyQt5.QtCore import QSettings
        settings = QSettings("AnkiOcclusion", "FocusModeSettings")
        settings.setValue("focus_mode_enabled", "true" if enabled else "false")
        self.update()

    def is_focus_mode(self) -> bool:
        return self._focus_mode

    def set_ultra_focus_mode(self, enabled: bool):
        self._ultra_focus_mode = bool(enabled)
        from PyQt5.QtCore import QSettings
        settings = QSettings("AnkiOcclusion", "FocusModeSettings")
        settings.setValue("ultra_focus_enabled", "true" if enabled else "false")
        self.update()

    def is_ultra_focus_mode(self) -> bool:
        return getattr(self, "_ultra_focus_mode", False)

    def set_bg_opacity(self, opacity: float):
        self._bg_opacity = max(0.0, min(1.0, round(opacity, 2)))
        from PyQt5.QtCore import QSettings
        settings = QSettings("AnkiOcclusion", "FocusModeSettings")
        settings.setValue("bg_opacity", self._bg_opacity)
        self.update()

    def get_bg_opacity(self) -> float:
        return self._bg_opacity


