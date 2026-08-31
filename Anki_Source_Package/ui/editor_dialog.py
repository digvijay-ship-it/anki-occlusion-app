import os
import sys
import time
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QListWidget,
    QFrame,
    QScrollArea,
    QMessageBox,
    QFileDialog,
    QFormLayout,
    QTextEdit,
    QSizePolicy,
    QDialog,
    QApplication,
    QSplitter,
    QShortcut,
    QCheckBox,
)
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QSize,
    pyqtSignal,
    QFileSystemWatcher,
    QMimeData,
    QUrl,
)
from PyQt5.QtGui import QFont, QIcon, QPixmap, QDesktopServices, QKeySequence
from sm2_engine import sm2_init
from data_manager import new_box_id
from services import recovery_manager, shortcut_manager
from services.ocr_engine import OcrTextThread, clean_ocr_title
from ui.canvas.retro_effects import CRTOverlay
from pdf_engine import (
    PDF_SUPPORT,
    PAGE_CACHE,
    PdfLoaderThread,
    PdfOnDemandThread,
    load_pdf_skeleton,
    build_skeleton_placeholders,
    get_changed_pages,
    choose_pdf_render_zoom,
    ensure_pdf_cache_profile,
    adapt_pdf_boxes_to_render_zoom,
    PDF_LEGACY_BOX_ZOOM,
    get_cached_pdf_page_set,
)
from perf_utils import get_pdf_page_count, perf_log, trace_perf, log_memory
from storage_paths import (
    build_archive_asset_path,
    find_deck_segments,
    has_mission_archive,
    import_asset_into_archive,
    relocate_pdf_for_deck,
    resolve_asset_path,
)

from editor_ui import OcclusionCanvas, _ZoomableScrollArea, ToolBar, MaskPanel, RichTextEdit
from ui.pdf_annotation_dialog import PdfAnnotationDialog
from ui.pdf_viewer_controller import PdfViewerController

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
EDITOR_VERBOSE_ENV = "ANKI_EDITOR_VERBOSE"
EDITOR_SCROLL_PROFILE_ENV = "ANKI_EDITOR_SCROLL_PROFILE"

#  CARD EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════════════════════


class CardEditorDialog(QDialog):
    def __init__(
        self,
        parent=None,
        card=None,
        data=None,
        deck=None,
        initial_scroll=0,
        initial_page=None,
        initial_img_y=None,
        recovery_draft=None,
    ):
        super().__init__(parent)
        self._initial_img_y = initial_img_y
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        self.card = card or {}
        self._recovery_initial_card = dict(card or {})
        self._opened_from_recovery = isinstance(recovery_draft, dict)
        self._recovery_mode = (
            recovery_draft.get("mode", "add")
            if self._opened_from_recovery
            else ("edit" if card else "add")
        )
        self._recovery_draft_id = (
            recovery_draft.get("draft_id")
            if self._opened_from_recovery and recovery_draft.get("draft_id")
            else recovery_manager.new_draft_id()
        )
        self._recovery_draft_cleared = False
        self._recovery_accepted = False
        self._recovery_autosave_ready = False
        self._recovery_dirty = False
        self._card_saved_once = False
        self._recovery_created_at = self.card.get("created") or datetime.now().isoformat()
        self._last_recovery_draft_fingerprint = None
        self._initial_scroll = initial_scroll
        self._initial_page = initial_page
        self._pdf_pages = []
        self._cur_page = 0
        self._data = data
        self._deck = deck
        self._auto_subdeck_name = None
        self._watcher = QFileSystemWatcher()
        self._ignored_watch_paths = {}
        self._watched_path = None
        self._reload_timer = QTimer()
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._reload_pdf)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._pdf_loader_thread = None
        self._pdf_ondemand_thread = None
        self._pdf_total_pages = 0
        self._pdf_render_zoom = 2.0
        self._pending_boxes_need_pdf_adapt = False
        self._ui_page_zero = 0
        self._nav_seq = 0
        self._pending_boxes = []
        self._editor_ondemand_path = None
        self._editor_ondemand_total = 0
        self._editor_pending_visible_request = None
        self._editor_canvas_real_pages = set()
        self._editor_render_inflight_pages = set()
        self._editor_visible_debug_seen_pages = set()
        self._editor_load_t0 = None
        self._editor_ondemand_requested_pages = set()
        self._editor_ondemand_request_pages_by_thread = {}
        self._editor_scroll_profile_last_event_ts = None
        self._editor_scroll_profile_last_log_ts = 0.0
        self._editor_last_decision_stats = {}
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._zoom_fit)
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(2000)
        self._recovery_timer.timeout.connect(self._write_recovery_draft)
        self._setup_ui()
        
        # Instantiate CRT overlay if theme is retro
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        self.crt = None
        from theme_manager import is_retro_theme
        if is_retro_theme(theme):
            self.crt = CRTOverlay(self)
            self.crt.trigger_boot_flicker()

        if self._opened_from_recovery:
            self._apply_recovery_restore_notice(recovery_draft)
        if card:
            self._load_card(card)
        self._setup_recovery_autosave()

    def exec_(self):
        print("[DEBUG][editor_mode] enter_fullscreen_default")
        self.showFullScreen()
        return super().exec_()

    def showEvent(self, event):
        # Mask editing is render/input intensive.  Pause decorative effects
        # before child widgets receive their show events.
        from ui.canvas.retro_effects import suspend_animations

        suspend_animations(self)
        super().showEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)
        from ui.canvas.retro_effects import resume_animations

        resume_animations(self)

    def _apply_recovery_restore_notice(self, draft):
        source = ""
        try:
            card = (draft or {}).get("card", {}) or {}
            source = os.path.basename(card.get("pdf_path") or card.get("image_path") or "")
        except Exception:
            source = ""
        suffix = f" - {source}" if source else ""
        self.setWindowTitle(f"Restoring recovered draft{suffix}")
        if hasattr(self, "_hint_label"):
            self._hint_label.setText(
                "Restoring recovered draft. If the page is blank for a moment, "
                "wait while the PDF loads."
            )

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._schedule_zoom_fit()
        if getattr(self, "crt", None) is not None:
            self.crt.setGeometry(self.rect())
            self.crt.raise_()

    def _setup_ui(self):
        from theme_manager import get_palette
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        self._p = p
        self._hf = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        self._bf = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")

        self.setStyleSheet(f"""
            QDialog {{ background: {p.get('C_BG', '#ECECEC')}; }}
            QWidget {{ background: {p.get('C_BG', '#ECECEC')}; color: {p.get('C_TEXT', '#222')}; font-family: {self._bf}; font-size: 12px; }}
            QFrame  {{ background: {p.get('C_BG', '#ECECEC')}; border: none; border-radius: 0; }}
            QLabel  {{ background: transparent; color: {p.get('C_TEXT', '#333')}; font-family: {self._hf}; }}
            QLineEdit, QTextEdit {{
                background: {p.get('C_CARD', 'white')}; color: {p.get('C_TEXT', '#111')};
                border: 1px solid {p.get('C_BORDER', '#CCC')}; border-radius: 4px; padding: 4px; font-family: {self._bf}; }}
            QListWidget {{
                background: {p.get('C_CARD', 'white')}; color: {p.get('C_TEXT', '#111')};
                border: 1px solid {p.get('C_BORDER', '#CCC')}; border-radius: 4px; font-family: {self._bf}; }}
            QListWidget::item:selected {{ background: {p.get('C_ACCENT', '#4A90D9')}; color: {p.get('C_BG', 'white')}; }}
            QPushButton {{
                background: {p.get('C_SURFACE', '#E8E8E8')}; color: {p.get('C_TEXT', '#333')};
                border: 1px solid {p.get('C_BORDER', '#BBB')}; border-radius: 4px;
                padding: 4px 10px; font-size: 12px; font-family: {self._hf}; font-weight: bold; }}
            QPushButton:hover   {{ background: {p.get('C_CARD', '#D8D8D8')}; }}
            QPushButton:pressed {{ background: {p.get('C_BORDER', '#C8C8C8')}; }}
            QPushButton#accent  {{ background: {p.get('C_ACCENT', '#4A90D9')}; color: {p.get('C_BG', 'white')}; border: 1px solid {p.get('C_ACCENT', '#3A7FC9')}; }}
            QPushButton#accent:hover {{ background: white; color: {p.get('C_BG', '#111')}; }}
            QPushButton#danger  {{ background: {p.get('C_RED', '#E05555')}; color: {p.get('C_BG', 'white')}; border: none; }}
            QPushButton#danger:hover {{ background: white; color: {p.get('C_BG', '#111')}; }}
            QPushButton#success {{ background: {p.get('C_GREEN', '#4CAF50')}; color: {p.get('C_BG', 'white')}; border: none; }}
            QPushButton#success:hover {{ background: white; color: {p.get('C_BG', '#111')}; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical   {{ background:{p.get('C_SURFACE', '#CCC')}; width:10px; border-radius:5px; }}
            QScrollBar::handle:vertical {{ background:{p.get('C_BORDER', '#999')}; border-radius:5px; }}
            QScrollBar:horizontal {{ background:{p.get('C_SURFACE', '#CCC')}; height:10px; border-radius:5px; }}
            QScrollBar::handle:horizontal {{ background:{p.get('C_BORDER', '#999')}; border-radius:5px; }}
        """)

        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # ── top bar ───────────────────────────────────────────────────────────
        top_bar = QFrame()
        top_bar.setFixedHeight(46)
        top_bar.setStyleSheet(
            f"QFrame{{background:{p.get('C_SURFACE', '#F0F0F0')};border-bottom:1px solid {p.get('C_BORDER', '#C8C8C8')};border-radius:0;}}"
            f"QPushButton{{background:transparent;border:none;border-radius:4px;"
            f"padding:4px 10px;font-size:13px;color:{p.get('C_TEXT', '#333')};min-height:32px;font-family:{self._hf};}}"
            f"QPushButton:hover{{background:{p.get('C_CARD', '#DDD')};}}"
            f"QPushButton:pressed{{background:{p.get('C_BORDER', '#CCC')};}}"
            f"QPushButton:checked{{background:{p.get('C_ACCENT', '#C8D8EE')};color:{p.get('C_BG', '#1a5ca8')};}}"
        )
        tl = QHBoxLayout(top_bar)
        tl.setContentsMargins(6, 4, 6, 4)
        tl.setSpacing(2)

        def _tbtn(label, tip, checkable=False, w=None):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFixedHeight(34)
            if w:
                b.setFixedWidth(w)
            return b

        def _sep():
            s = QFrame()
            s.setFrameShape(QFrame.VLine)
            s.setStyleSheet(
                f"QFrame{{background:{p.get('C_BORDER', '#C0C0C0')};margin:5px 4px;}}"
            )
            s.setFixedWidth(1)
            return s

        btn_img = _tbtn("🖼 Image", "Load Image")
        btn_paste = _tbtn("📋 Paste", "Paste image from clipboard  Ctrl+V")
        btn_pdf = _tbtn("📄 PDF", "Load PDF")
        btn_pdf.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT:
            btn_pdf.setToolTip("pip install pymupdf")
        btn_img.clicked.connect(self._load_image)
        btn_paste.clicked.connect(self._paste_image)
        btn_pdf.clicked.connect(self._load_pdf)

        btn_undo = _tbtn("↩", "Undo  Ctrl+Z", w=36)
        btn_redo = _tbtn("↪", "Redo  Ctrl+Y", w=36)
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        btn_redo.clicked.connect(lambda: self.canvas.redo())

        btn_zi = _tbtn("🔍+", "Zoom In", w=46)
        btn_zo = _tbtn("🔍−", "Zoom Out", w=46)
        btn_zf = _tbtn("⊡", "Zoom Fit", w=32)
        btn_del = _tbtn("🗑", "Delete selected  Del", w=32)
        btn_clear = _tbtn("✕ All", "Clear all masks")
        btn_grp = _tbtn("⛓ Group", "Group selected masks  [G]")
        btn_ungrp = _tbtn("⛓ Ungroup", "Ungroup  [Shift+G]")
        btn_grp.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:4px;"
            f"padding:4px 10px;font-size:13px;color:{p.get('C_ACCENT', '#1a5ca8')};min-height:32px;}}"
            f"QPushButton:hover{{background:{p.get('C_SURFACE', '#D0E4FF')};}}"
        )
        btn_ungrp.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:4px;"
            f"padding:4px 10px;font-size:13px;color:{p.get('C_SUBTEXT', '#888')};min-height:32px;}}"
            f"QPushButton:hover{{background:{p.get('C_SURFACE', '#EEE')};}}"
        )
        btn_grp.clicked.connect(lambda: self.canvas.group_selected())
        btn_ungrp.clicked.connect(lambda: self.canvas.ungroup_selected())

        self.btn_open_ext = _tbtn("📂 Open PDF", "Open in system PDF reader")
        self.btn_open_ext.clicked.connect(self._open_in_reader)
        self.btn_open_ext.setVisible(False)

        self.btn_annotate_beta = _tbtn(
            "🖊 Anotate Scroll", "Open in-app scroll annotation editor  Ctrl+T"
        )
        self.btn_annotate_beta.clicked.connect(self._open_annotation_beta)
        self.btn_annotate_beta.setVisible(False)

        self.btn_relink = _tbtn(
            "🔄 Relink PDF", "Replace the PDF source file — keeps all existing masks"
        )
        self.btn_relink.setEnabled(PDF_SUPPORT)
        self.btn_relink.clicked.connect(self._relink_pdf)
        self.btn_relink.setVisible(False)

        self.btn_crop = _tbtn(
            "✂ Crop Image", "Crop the background image"
        )
        self.btn_crop.clicked.connect(self._crop_background_image)
        self.btn_crop.setVisible(False)
        self.btn_relink.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;border-radius:4px;"
            f"padding:4px 10px;font-size:13px;color:{p.get('C_ORANGE', '#8B4513')};min-height:32px;}}"
            f"QPushButton:hover{{background:{p.get('C_SURFACE', '#FFE4C4')};}}"
        )

        self.lbl_sync = QLabel("")
        self.lbl_sync.setStyleSheet(
            f"background:transparent;font-size:11px;color:{p.get('C_SUBTEXT', '#666')};font-family:{self._bf};"
        )
        self.lbl_sync.setVisible(False)

        for w in [
            btn_img,
            btn_paste,
            btn_pdf,
            _sep(),
            btn_undo,
            btn_redo,
            _sep(),
            btn_zi,
            btn_zo,
            btn_zf,
            _sep(),
            btn_del,
            btn_clear,
            _sep(),
            btn_grp,
            btn_ungrp,
            _sep(),
            self.btn_open_ext,
            self.btn_annotate_beta,
            self.btn_relink,
            self.btn_crop,
            self.lbl_sync,
        ]:
            tl.addWidget(w)
        tl.addStretch()

        self.btn_cancel = _tbtn("Cancel", "Discard changes")
        btn_save = QPushButton("💾  Save Card")
        btn_save.setFixedHeight(34)
        btn_save.setToolTip("Save")
        btn_save.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border:1px solid #3A9040;"
            "border-radius:4px;padding:4px 16px;font-size:13px;min-height:32px;}"
            "QPushButton:hover{background:#3A9040;}"
        )
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_save.clicked.connect(self._save)
        tl.addWidget(self.btn_cancel)
        tl.addSpacing(4)
        tl.addWidget(btn_save)
        L.addWidget(top_bar)

        # ── pdf bar ───────────────────────────────────────────────────────────
        self.pdf_bar = QWidget()
        self.pdf_bar.setStyleSheet(
            f"background:{p.get('C_SURFACE', '#E8E8E8')};border-bottom:1px solid {p.get('C_BORDER', '#CCC')};"
        )
        pb = QHBoxLayout(self.pdf_bar)
        pb.setContentsMargins(10, 2, 10, 2)
        self.btn_prev_page = _tbtn("←", "Previous page", w=30)
        self.btn_prev_page.setFocusPolicy(Qt.NoFocus)
        self.btn_prev_page.clicked.connect(self._go_prev_page)
        self.btn_next_page = _tbtn("→", "Next page", w=30)
        self.btn_next_page.setFocusPolicy(Qt.NoFocus)
        self.btn_next_page.clicked.connect(self._go_next_page)
        self.inp_page_jump = QLineEdit()
        self.inp_page_jump.setFixedWidth(52)
        self.inp_page_jump.setAlignment(Qt.AlignCenter)
        self.inp_page_jump.setPlaceholderText("1")
        self.inp_page_jump.returnPressed.connect(self._jump_to_page_from_input)
        self.lbl_page_total = QLabel("/ 0")
        self.lbl_page_total.setStyleSheet(
            f"color:{p.get('C_SUBTEXT', '#555')};font-size:11px;background:transparent;font-family:{self._bf};"
        )
        self.lbl_pg = QLabel("")
        self.lbl_pg.setStyleSheet(
            f"color:{p.get('C_SUBTEXT', '#555')};font-size:11px;background:transparent;font-family:{self._bf};"
        )
        self.btn_invert_pdf = _tbtn("◑", "Toggle PDF Inversion (Dark Mode / High Contrast)", w=32)
        self.btn_invert_pdf.setFocusPolicy(Qt.NoFocus)
        self.btn_invert_pdf.clicked.connect(self._toggle_pdf_contrast)

        pb.addWidget(self.btn_prev_page)
        pb.addWidget(self.btn_next_page)
        pb.addSpacing(6)
        pb.addWidget(self.inp_page_jump)
        pb.addWidget(self.lbl_page_total)
        pb.addSpacing(12)
        pb.addWidget(self.lbl_pg)
        pb.addSpacing(12)
        pb.addWidget(self.btn_invert_pdf)
        pb.addStretch()
        self.pdf_bar.setFixedHeight(38)
        self.pdf_bar.hide()
        L.addWidget(self.pdf_bar)

        # ── main row ──────────────────────────────────────────────────────────
        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(0)
        self.toolbar = ToolBar()
        main_row.addWidget(self.toolbar)

        sc = _ZoomableScrollArea()
        sc.setWidgetResizable(False)
        sc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc.setStyleSheet(
            f"QScrollArea{{background:{p.get('C_BG', '#787878')};border:none;}}"
        )
        self.canvas = OcclusionCanvas()
        self.canvas.setStyleSheet("background:transparent;")
        sc.setWidget(self.canvas)
        sc.set_canvas(self.canvas)
        self.toolbar.tool_changed.connect(self.canvas.set_tool)
        sc.verticalScrollBar().valueChanged.connect(self._on_scroll_pdf_page_changed)
        main_row.addWidget(sc, stretch=1)
        self._sc = sc
        self._sc_prev_page = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.prev_page")), self
        )
        self._sc_prev_page.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_prev_page.setAutoRepeat(False)
        self._sc_prev_page.activated.connect(self._go_prev_page)
        self._sc_next_page = QShortcut(
            QKeySequence(shortcut_manager.shortcut_text("review.next_page")), self
        )
        self._sc_next_page.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_next_page.setAutoRepeat(False)
        self._sc_next_page.activated.connect(self._go_next_page)
        self._pdf_viewer = PdfViewerController(
            canvas=self.canvas,
            scroll_area=self._sc,
            page_input=self.inp_page_jump,
            page_total_label=self.lbl_page_total,
            prev_button=self.btn_prev_page,
            next_button=self.btn_next_page,
            total_pages_getter=lambda: int(
                self._pdf_total_pages or len(getattr(self.canvas, "_pages", []) or [])
            ),
            debug_hook=self._editor_nav_debug,
        )

        # ── right panel ───────────────────────────────────────────────────────
        right_panel = QWidget()
        right_panel.setFixedWidth(240)
        right_panel.setStyleSheet(
            f"QWidget{{background:{p.get('C_SURFACE', '#F5F5F5')};}}QFrame{{background:{p.get('C_SURFACE', '#F5F5F5')};border:none;}}"
        )
        rp = QVBoxLayout(right_panel)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.setSpacing(0)

        ml_hdr = QFrame()
        ml_hdr.setFixedHeight(28)
        ml_hdr.setStyleSheet(
            f"QFrame{{background:{p.get('C_CARD', '#E0E0E0')};border-bottom:1px solid {p.get('C_BORDER', '#CCC')};}}"
            f"QLabel{{color:{p.get('C_TEXT', '#444')};font-size:11px;font-weight:bold;background:transparent;font-family:{self._hf};}}"
        )
        ml_hl = QHBoxLayout(ml_hdr)
        ml_hl.setContentsMargins(8, 0, 8, 0)
        ml_hl.addWidget(QLabel("Masks"))
        ml_hl.addStretch()
        rp.addWidget(ml_hdr)

        self.mask_panel = MaskPanel(self.canvas)
        rp.addWidget(self.mask_panel, stretch=1)
        self.mask_panel.list_w.currentRowChanged.connect(self._center_on_mask)

        ci_hdr = QFrame()
        ci_hdr.setFixedHeight(28)
        ci_hdr.setStyleSheet(
            f"QFrame{{background:{p.get('C_CARD', '#E0E0E0')};border-top:1px solid {p.get('C_BORDER', '#CCC')};"
            f"border-bottom:1px solid {p.get('C_BORDER', '#CCC')};}}"
            f"QLabel{{color:{p.get('C_TEXT', '#444')};font-size:11px;font-weight:bold;background:transparent;font-family:{self._hf};}}"
        )
        ci_hl = QHBoxLayout(ci_hdr)
        ci_hl.setContentsMargins(8, 0, 8, 0)
        ci_hl.addWidget(QLabel("Card Info"))
        rp.addWidget(ci_hdr)

        ci_body = QWidget()
        ci_body.setStyleSheet(f"QWidget{{background:{p.get('C_SURFACE', '#F5F5F5')};}}")
        cib = QFormLayout(ci_body)
        cib.setContentsMargins(8, 8, 8, 8)
        cib.setSpacing(6)
        self.inp_title = QLineEdit()
        self.inp_title.setPlaceholderText("Card title…")
        self.inp_tags = QLineEdit()
        self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_notes = RichTextEdit()
        self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(64)
        self.chk_formula = QCheckBox("Mark as Formula")
        self.chk_formula.setToolTip("Formula cards are excluded from normal reviews and can be viewed/practiced anytime.")
        cib.addRow("Title:", self.inp_title)
        cib.addRow("Tags:", self.inp_tags)
        cib.addRow("Notes:", self.inp_notes)
        cib.addRow("", self.chk_formula)
        rp.addWidget(ci_body)
        main_row.addWidget(right_panel)

        body_w = QWidget()
        body_w.setLayout(main_row)
        L.addWidget(body_w, stretch=1)

        hint_bar = QFrame()
        hint_bar.setFixedHeight(20)
        hint_bar.setStyleSheet(
            "QFrame{background:#E8E8E8;border-top:1px solid #CCC;border-radius:0;}"
            "QLabel{background:transparent;color:#777;font-size:10px;}"
        )
        hl = QHBoxLayout(hint_bar)
        hl.setContentsMargins(10, 0, 10, 0)
        self._hint_label = QLabel(
            "V=Select  R=Rect  E=Ellipse  T=Label  |  "
            "Hold Alt=temp select  Alt+Click=multi-select  |  "
            "G=group  Shift+G=ungroup  |  "
            "Drag ↻=rotate  Del=delete  Ctrl+Z/Y=undo/redo  |  "
            "L=copy PDF  Ctrl+L=open folder  |  "
            "Middle-click drag or H = Pan  (tablet/stylus)"
        )
        hl.addWidget(self._hint_label)
        hl.addStretch()
        L.addWidget(hint_bar)

        btn_zi.clicked.connect(lambda: self.canvas.zoom_in())
        btn_zo.clicked.connect(lambda: self.canvas.zoom_out())
        btn_zf.clicked.connect(self._zoom_fit)
        btn_del.clicked.connect(lambda: self.canvas.delete_selected_boxes())
        btn_clear.clicked.connect(self.canvas.clear_all)

    def _setup_recovery_autosave(self):
        self._recovery_autosave_ready = True
        self.canvas.boxes_changed.connect(
            lambda _boxes: self._schedule_recovery_draft("boxes")
        )
        self.inp_title.textChanged.connect(
            lambda _text: self._schedule_recovery_draft("title")
        )
        self.inp_tags.textChanged.connect(
            lambda _text: self._schedule_recovery_draft("tags")
        )
        self.inp_notes.textChanged.connect(
            lambda: self._schedule_recovery_draft("notes")
        )

    def _schedule_recovery_draft(self, _reason="change"):
        if self._recovery_draft_cleared or self._recovery_accepted:
            return
        if not self._recovery_autosave_ready:
            return
        self._recovery_dirty = True
        self._recovery_timer.start()
        print(
            "[DEBUG][recovery] editor_draft_scheduled "
            f"reason={_reason} delay_ms={self._recovery_timer.interval()}"
        )

    def _has_recovery_content(self):
        try:
            boxes = self.canvas.get_boxes() if hasattr(self, "canvas") else []
        except Exception:
            boxes = []
        if not boxes:
            boxes = list(getattr(self, "_pending_boxes", []) or self.card.get("boxes", []) or [])
        return bool(
            self.card.get("pdf_path")
            or self.card.get("image_path")
            or boxes
            or self.inp_title.text().strip()
            or self.inp_tags.text().strip()
            or self.inp_notes.toPlainText().strip()
        )

    def _current_recovery_card(self):
        card = dict(self.card)
        boxes = self.canvas.get_boxes() if hasattr(self, "canvas") else []
        if not boxes:
            boxes = list(getattr(self, "_pending_boxes", []) or card.get("boxes", []) or [])
        card.update(
            {
                "title": self.inp_title.text().strip() or card.get("title", ""),
                "tags": [
                    t.strip() for t in self.inp_tags.text().split(",") if t.strip()
                ],
                "notes": self.inp_notes.toHtml() if "<img" in self.inp_notes.toHtml() else self.inp_notes.toPlainText(),
                "boxes": boxes,
                "created": card.get("created") or self._recovery_created_at,
                "reviews": card.get("reviews", 0),
            }
        )
        if self._auto_subdeck_name:
            card["_auto_subdeck"] = self._auto_subdeck_name
        if card.get("pdf_path"):
            card["_pdf_box_render_zoom"] = float(
                self._pdf_render_zoom or PDF_LEGACY_BOX_ZOOM
            )
        return card

    @staticmethod
    def _recovery_payload_fingerprint(payload):
        return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)

    def _write_recovery_draft(self):
        if self._recovery_draft_cleared or self._recovery_accepted:
            return None
        if not self._has_recovery_content():
            return None
        deck = self._deck if isinstance(self._deck, dict) else {}
        payload = {
            "draft_id": self._recovery_draft_id,
            "mode": self._recovery_mode,
            "deck": {
                "id": deck.get("_id"),
                "name": deck.get("name", ""),
                "path": recovery_manager.find_deck_path(self._data, deck),
            },
            "initial_card_locator": recovery_manager.find_card_locator(
                self._data, self._recovery_initial_card, deck
            )
            if self._recovery_mode == "edit"
            else {},
            "card": self._current_recovery_card(),
        }
        fingerprint = self._recovery_payload_fingerprint(payload)
        if fingerprint == self.__dict__.get("_last_recovery_draft_fingerprint"):
            print(
                "[DEBUG][recovery] editor_draft_skipped "
                f"reason=unchanged boxes={len(payload.get('card', {}).get('boxes', []))}"
            )
            return None
        saved = recovery_manager.save_editor_draft(payload)
        self._last_recovery_draft_fingerprint = fingerprint
        self._recovery_dirty = True
        print(
            "[DEBUG][recovery] editor_draft_saved "
            f"id={saved.get('draft_id')} boxes={len(saved.get('card', {}).get('boxes', []))}"
        )
        return saved

    def _write_recovery_checkpoint(self, reason="checkpoint"):
        saved = self._write_recovery_draft()
        if saved:
            print(f"[DEBUG][recovery] editor_draft_checkpoint reason={reason}")
        return saved

    def clear_recovery_draft(self):
        self._recovery_draft_cleared = True
        self._recovery_timer.stop()
        recovery_manager.delete_editor_draft(self._recovery_draft_id)

    def _confirm_recovery_close(self):
        if self._recovery_accepted or self._recovery_draft_cleared:
            return True
        if not self._recovery_dirty:
            return True
        if not self._has_recovery_content():
            return True
        self._write_recovery_checkpoint("close")
        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved Draft")
        msg.setText("Keep this unsaved card draft for recovery?")
        msg.setInformativeText(
            "Keeping it lets the Recovery Center reopen this PDF/card after a crash or accidental close."
        )
        discard_btn = msg.addButton("Discard", QMessageBox.DestructiveRole)
        keep_btn = msg.addButton("Keep Draft", QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("Cancel Close", QMessageBox.RejectRole)
        msg.setDefaultButton(keep_btn)
        msg.exec_()
        clicked = msg.clickedButton()
        if clicked is cancel_btn:
            return False
        if clicked is discard_btn:
            self.clear_recovery_draft()
        return True

    def _zoom_fit(self):
        vp = self._sc.viewport()
        if getattr(self.canvas, "_pages", None):
            self._pdf_viewer.reset_fit()
            self._schedule_initial_view_restore("post_zoom_fit", delays_ms=(0, 35, 90))
            if getattr(self, "_editor_ondemand_path", None):
                QTimer.singleShot(120, self._sc._emit_visible_pages)
        else:
            self.canvas.zoom_fit_width(vp.width())

    def _editor_nav_debug(self, action: str, **data):
        return

    @staticmethod
    def _editor_verbose_debug_enabled():
        raw = os.environ.get(EDITOR_VERBOSE_ENV, "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _editor_scroll_profile_enabled():
        raw = os.environ.get(EDITOR_SCROLL_PROFILE_ENV, "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def _log_editor_scroll_profile(
        self,
        *,
        first,
        last,
        entered_pages,
        needed,
        inject_stats,
        decision_stats,
        total_ms,
        queued,
        render_started,
    ):
        if not self._editor_scroll_profile_enabled():
            return
        now = time.perf_counter()
        prev_ts = self.__dict__.get("_editor_scroll_profile_last_event_ts")
        event_dt_ms = 0.0 if prev_ts is None else (now - float(prev_ts)) * 1000.0
        self._editor_scroll_profile_last_event_ts = now

        # Log each expensive scroll pass, each render/queue decision, and a
        # periodic heartbeat while scrolling so smoothness can be judged.
        last_log = float(self.__dict__.get("_editor_scroll_profile_last_log_ts", 0.0) or 0.0)
        should_log = (
            total_ms >= 8.0
            or bool(needed)
            or int((inject_stats or {}).get("injected", 0)) > 0
            or (now - last_log) >= 1.0
        )
        if not should_log:
            return
        self._editor_scroll_profile_last_log_ts = now

        rate = 1000.0 / event_dt_ms if event_dt_ms > 0 else 0.0
        inflight = len(self.__dict__.get("_editor_render_inflight_pages", set()) or set())
        pending = self.__dict__.get("_editor_pending_visible_request")
        pending_count = len(pending[1] or []) if pending else 0
        print(
            "[PROFILE][editor_scroll] "
            f"visible=p.{first + 1}-p.{last + 1} "
            f"entered={len(entered_pages or [])} "
            f"dt={event_dt_ms:.1f}ms "
            f"rate={rate:.1f}/s "
            f"total={total_ms:.1f}ms "
            f"inject={float((inject_stats or {}).get('elapsed_ms', 0.0)):.1f}ms "
            f"decide={float((decision_stats or {}).get('elapsed_ms', 0.0)):.1f}ms "
            f"cache_checks={int((inject_stats or {}).get('cache_checks', 0)) + int((decision_stats or {}).get('cache_checks', 0))} "
            f"cache_hits={int((inject_stats or {}).get('cache_hits', 0)) + int((decision_stats or {}).get('cache_hits', 0))} "
            f"injected={int((inject_stats or {}).get('injected', 0))} "
            f"need={self._fmt_editor_pages(needed)} "
            f"inflight={inflight} "
            f"pending={pending_count} "
            f"queued={'yes' if queued else 'no'} "
            f"render={'yes' if render_started else 'no'}"
        )

    def _pdf_quality_debug(self, action: str, **data):
        parts = " ".join(f"{key}={value}" for key, value in data.items())
        print(f"[DEBUG][pdf_quality][editor] {action} {parts}".rstrip())

    @staticmethod
    def _fmt_editor_pages(page_nums, max_items: int = 10):
        pages = [int(pn) for pn in (page_nums or [])]
        if not pages:
            return "none"
        shown = ", ".join(f"p.{pn + 1}" for pn in pages[:max_items])
        if len(pages) > max_items:
            shown += f", ... (+{len(pages) - max_items})"
        return shown

    @staticmethod
    def _editor_cache_count(path, total_pages):
        if hasattr(PAGE_CACHE, "cached_page_count"):
            return PAGE_CACHE.cached_page_count(path, total_pages)
        if hasattr(PAGE_CACHE, "cached_page_indices"):
            return len(PAGE_CACHE.cached_page_indices(path, total_pages))
        return "?"

    def _editor_pages_needing_render(self, path, page_nums, context="visible"):
        t0 = time.perf_counter()
        real_pages = set(self.__dict__.get("_editor_canvas_real_pages", set()) or set())
        inflight = set(
            self.__dict__.get("_editor_render_inflight_pages", set()) or set()
        )
        pending = self.__dict__.get("_editor_pending_visible_request")
        pending_visible = (
            set(int(pn) for pn in (pending[1] or [])) if pending and pending[0] == path else set()
        )
        needed = []
        skipped = {
            "canvas_real": 0,
            "cache_hot": 0,
            "inflight": 0,
            "pending_visible": 0,
        }
        cache_checks = 0
        cache_hits = 0
        for pn in sorted({int(pn) for pn in (page_nums or [])}):
            if pn in real_pages:
                skipped["canvas_real"] += 1
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
        self._editor_last_decision_stats = {
            "cache_checks": cache_checks,
            "cache_hits": cache_hits,
            "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
            "skipped": dict(skipped),
        }
        if self._editor_verbose_debug_enabled():
            print(
                "[DEBUG][editor_decision] "
                f"context={context} candidates={self._fmt_editor_pages(page_nums)} "
                f"need={self._fmt_editor_pages(needed)} "
                f"skip_canvas={skipped['canvas_real']} "
                f"skip_cache={skipped['cache_hot']} "
                f"skip_inflight={skipped['inflight']} "
                f"skip_pending={skipped['pending_visible']}"
            )
        perf_log(
            "editor_pages_needing_render",
            context=context,
            file=os.path.basename(path) if path else "",
            candidates=len(sorted({int(pn) for pn in (page_nums or [])})),
            needed=len(needed),
            cache_checks=cache_checks,
            cache_hits=cache_hits,
            skipped=skipped,
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        return needed

    def _set_pdf_page_ui(self, current_zero: int):
        self._pdf_viewer.set_page_ui(current_zero)
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _update_pdf_nav_ui(self, *_):
        self._pdf_viewer.refresh_page_ui()
        self._ui_page_zero = self._pdf_viewer._ui_page_zero
        has_pages = self._pdf_viewer.page_count() > 0
        if hasattr(self, "btn_invert_pdf"):
            self.btn_invert_pdf.setVisible(has_pages)
            self._update_invert_pdf_button_style()

    def _update_invert_pdf_button_style(self):
        if not hasattr(self, "btn_invert_pdf"):
            return
        from data_manager import store
        invert = store.get().get("_invert_pdf", False)
        p = self._p
        card = p.get("C_CARD", "#F8F9FA")
        accent = p.get("C_ACCENT", "#4C6EF5")
        border = p.get("C_BORDER", "#DEE2E6")
        text = p.get("C_TEXT", "#212529")
        surface = p.get("C_SURFACE", "#FFFFFF")
        if invert:
            self.btn_invert_pdf.setStyleSheet(
                f"QPushButton{{background:{accent};color:white;"
                f"border:1px solid {accent};border-radius:5px;font-size:13px;}}"
            )
        else:
            self.btn_invert_pdf.setStyleSheet(
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

    def _reload_pdf_contrast(self):
        path = getattr(self.canvas, "_current_pdf_path", None)
        if not path or not os.path.exists(path):
            return
        self._stop_pdf_threads()
        self._editor_canvas_real_pages = set()
        
        skeleton = load_pdf_skeleton(path, zoom=self._pdf_render_zoom)
        if skeleton and not getattr(skeleton, "error", None):
            pages = list(
                getattr(skeleton, "placeholders", None)
                or build_skeleton_placeholders(getattr(skeleton, "page_dims", []))
            )
            self.canvas.load_pages(pages)
            QTimer.singleShot(50, self._sc._emit_visible_pages)

    def _on_scroll_pdf_page_changed(self, value: int):
        page_zero = self._current_visible_page()
        if page_zero != self._ui_page_zero:
            self._editor_nav_debug("scroll", value=value, page=page_zero + 1)
        self._pdf_viewer.set_page_ui(page_zero)
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _go_to_page(self, page_zero: int):
        self._pdf_viewer.go_to_page(page_zero)
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _finalize_pdf_page_jump(self, seq: int, target: int):
        self._pdf_viewer._finalize_page_jump(seq, target)
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _nav_current_page(self) -> int:
        return self._pdf_viewer.nav_current_page()

    def _go_prev_page(self):
        self._pdf_viewer.go_prev_page()
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _go_next_page(self):
        self._pdf_viewer.go_next_page()
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _jump_to_page_from_input(self):
        self._pdf_viewer.jump_from_input()
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _schedule_zoom_fit(self, delay_ms=120):
        if getattr(self, "canvas", None) and self.canvas._pages:
            self._fit_timer.start(delay_ms)

    def _center_on_mask(self, row):
        if not (0 <= row < len(self.canvas._boxes)):
            return
        r = self.canvas._sr(self.canvas._boxes[row]["rect"])
        vbar = self._sc.verticalScrollBar()
        hbar = self._sc.horizontalScrollBar()
        hbar.setValue(int(max(0, r.center().x() - self._sc.viewport().width() // 2)))
        vbar.setValue(int(max(0, r.center().y() - self._sc.viewport().height() // 2)))

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        clean_mods = mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        
        # Ctrl+? toggle to open shortcuts dialog
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

        if shortcut_manager.event_matches(e, "review.fullscreen"):
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
        elif shortcut_manager.event_matches(e, "review.undo"):
            self.canvas.undo()
        elif shortcut_manager.event_matches(e, "review.redo"):
            self.canvas.redo()
        elif shortcut_manager.event_matches(e, "home.save"):
            self._save(keep_open=False)
            e.accept()
            return

        elif shortcut_manager.event_matches(e, "review.open_pdf"):
            self._open_in_reader()
        elif shortcut_manager.event_matches(e, "review.open_folder"):
            self._reveal_current_pdf_in_folder()
        elif shortcut_manager.event_matches(e, "review.annotate"):
            self._open_annotation_beta()
        elif mods & Qt.ControlModifier and key == Qt.Key_V:
            self._paste_image()
        elif shortcut_manager.event_matches(e, "review.copy_pdf") and not e.isAutoRepeat():
            self._copy_current_pdf_file_to_clipboard()
        elif shortcut_manager.event_matches(e, "review.prev_page") and not e.isAutoRepeat():
            self._go_prev_page()
        elif shortcut_manager.event_matches(e, "review.next_page") and not e.isAutoRepeat():
            self._go_next_page()
        elif shortcut_manager.event_matches(e, "review.pdf_contrast") and not e.isAutoRepeat():
            self._toggle_pdf_contrast()
        elif key == Qt.Key_V:
            self.toolbar.select_tool("select")
        elif key == Qt.Key_R:
            self.toolbar.select_tool("rect")
        elif key == Qt.Key_E:
            self.toolbar.select_tool("ellipse")
        elif key == Qt.Key_T:
            self.toolbar.select_tool("text")
        else:
            super().keyPressEvent(e)

    def _resolve_source_path(self, stored_path: str) -> str:
        return resolve_asset_path(stored_path)

    def _check_and_handle_duplicate(self, file_path, is_paste=False) -> bool:
        """
        Check if the file_path is already used in an existing card.
        If a duplicate is found, warn the user and offer options to:
          - Yes: Edit existing card (rejects dialog with switch_to_edit_card_id set)
          - No: Add anyway (continues import)
          - Cancel: Abort
        Returns True if the operation should be aborted/cancelled, False if it can proceed.
        """
        import os
        if not file_path or not os.path.exists(file_path):
            return False

        from data_manager import compute_file_sha256, compute_image_dhash, find_duplicate_card, hamming_distance
        
        # Calculate SHA-256 and dHash
        file_sha = compute_file_sha256(file_path)
        dhash = ""
        is_pdf = file_path.lower().endswith('.pdf')
        if not is_pdf:
            dhash = compute_image_dhash(file_path)
            
        current_title = self.inp_title.text().strip()
        deck_id = self._deck.get("_id") if isinstance(self._deck, dict) else None
        
        # Search for duplicate
        dup_card, dup_deck = find_duplicate_card(self._data, file_sha, dhash, current_title, target_deck_id=deck_id)
        if not dup_card:
            # No duplicate, store the new hashes on this card
            if file_sha:
                self.card["file_hash"] = file_sha
            if dhash:
                self.card["visual_hash"] = dhash
            return False

        # Exclude checking the card currently being edited
        if dup_card.get("_id") == self.card.get("_id"):
            if file_sha:
                self.card["file_hash"] = file_sha
            if dhash:
                self.card["visual_hash"] = dhash
            return False

        # Determine duplicate type
        if file_sha and dup_card.get("file_hash") == file_sha:
            dup_type = "exact same file content"
        elif dhash and dup_card.get("visual_hash") and hamming_distance(dhash, dup_card.get("visual_hash")) <= 2:
            dup_type = "visually similar image (screenshot)"
        else:
            dup_type = "same card title"

        # Show confirmation warning
        msg = (
            f"Duplicate card detected by {dup_type}!\n\n"
            f"Card Title: '{dup_card.get('title', 'Untitled')}'\n"
            f"Deck: '{dup_deck.get('name', 'Unknown')}'\n\n"
            f"Would you like to edit the existing card instead?"
        )
        
        reply = QMessageBox.warning(
            self,
            "Duplicate Card Detected",
            msg,
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        
        if reply == QMessageBox.Yes:
            self.switch_to_edit_card_id = dup_card.get("_id")
            self.reject()
            return True
        elif reply == QMessageBox.Cancel:
            return True

        # User clicked No (Add anyway) -> Save new hashes and proceed
        if file_sha:
            self.card["file_hash"] = file_sha
        if dhash:
            self.card["visual_hash"] = dhash
        return False

    def _current_deck_segments(self):
        deck = getattr(self, "_deck", None)
        deck_id = deck.get("_id") if isinstance(deck, dict) else None
        if deck_id is None:
            return []
        return find_deck_segments(self._data, deck_id)

    def _store_archive_asset(self, source_path: str, kind: str) -> str:
        if not source_path:
            return ""
        if has_mission_archive():
            deck_segments = self._current_deck_segments() if kind == "pdfs" else None
            stored_path = import_asset_into_archive(
                source_path,
                kind,
                deck_segments=deck_segments,
            )
            print(
                "[DEBUG][mission_archive] editor_store_asset "
                f"kind={kind} source={source_path} deck={'/'.join(deck_segments or [])} stored={stored_path}"
            )
            return stored_path
        abs_path = os.path.abspath(source_path)
        print(
            "[DEBUG][mission_archive] editor_store_asset_legacy "
            f"kind={kind} path={abs_path}"
        )
        return abs_path

    def _prepare_pasted_image_target(self) -> tuple[str, str]:
        if has_mission_archive():
            abs_path, rel_path = build_archive_asset_path("images", "anki_paste.png")
            print(
                "[DEBUG][mission_archive] editor_paste_target "
                f"abs={abs_path} stored={rel_path}"
            )
            return abs_path, rel_path
        import tempfile as _tmp

        fd, tmp_path = _tmp.mkstemp(
            suffix=".png",
            prefix="anki_paste_",
            dir=os.path.expanduser("~"),
        )
        os.close(fd)
        print(f"[DEBUG][mission_archive] editor_paste_target_legacy abs={tmp_path}")
        return tmp_path, tmp_path

    def _stop_ocr_thread(self):
        if hasattr(self, "_ocr_text_thread") and self._ocr_text_thread:
            if self._ocr_text_thread.isRunning():
                try:
                    self._ocr_text_thread.terminate()
                    self._ocr_text_thread.wait()
                except Exception:
                    pass
            self._ocr_text_thread = None

    def _trigger_ocr_for_image(self, abs_image_path: str, default_title: str):
        self._stop_ocr_thread()
        self._ocr_text_thread = OcrTextThread(abs_image_path, default_title, self)
        self._ocr_text_thread.result.connect(self._on_ocr_result)
        self._ocr_text_thread.start()

    def _on_ocr_result(self, raw_text: str, default_title: str):
        if not raw_text:
            return
        cleaned = clean_ocr_title(raw_text)
        if not cleaned:
            return
        current_title = self.inp_title.text().strip()
        is_default = (
            not current_title 
            or current_title == default_title 
            or current_title == "Pasted Image"
            or current_title == "Untitled"
        )
        if is_default:
            self.inp_title.setText(cleaned)
            self._schedule_recovery_draft("title")

    def _crop_background_image(self):
        if self.canvas._px is None or self.canvas._px.isNull():
            QMessageBox.warning(self, "No Image", "No background image loaded to crop.")
            return

        from ui.crop_dialog import CropImageDialog
        dialog = CropImageDialog(self.canvas._px, self)
        if dialog.exec_() == QDialog.Accepted:
            cropped_pixmap = dialog.get_cropped_pixmap()
            if not cropped_pixmap.isNull():
                from storage_paths import resolve_asset_path
                stored_path = self.card.get("image_path")
                if stored_path:
                    abs_path = resolve_asset_path(stored_path)
                    if abs_path and os.path.exists(abs_path):
                        if cropped_pixmap.save(abs_path, "PNG"):
                            x, y, w, h = dialog.get_crop_geometry()
                            boxes = self.canvas.get_boxes()
                            for box in boxes:
                                rect = box["rect"]
                                rect[0] = rect[0] - x
                                rect[1] = rect[1] - y
                            self.canvas.load_pixmap(cropped_pixmap)
                            self.canvas.set_boxes(boxes)
                            self.mask_panel._refresh(boxes)
                            self._write_recovery_checkpoint("image_cropped")
                            self.canvas._show_toast("✂ Image cropped")
                        else:
                            QMessageBox.warning(self, "Error", "Could not save cropped image.")

    # ── image / paste ─────────────────────────────────────────────────────────

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        if self._check_and_handle_duplicate(path):
            return
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
        try:
            stored_path = self._store_archive_asset(path, "images")
        except Exception as ex:
            QMessageBox.warning(self, "Error", f"Could not archive image:\n{ex}")
            return
        self.card["image_path"] = stored_path
        self.card.pop("pdf_path", None)
        self._pdf_pages = []
        self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False)
        self.btn_crop.setVisible(True)
        self.lbl_sync.setVisible(False)
        self._stop_watch()
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
        self._update_pdf_nav_ui()
        if not self.inp_title.text():
            default_title = os.path.splitext(os.path.basename(path))[0]
            self.inp_title.setText(default_title)
            self._trigger_ocr_for_image(path, default_title)
        self._write_recovery_checkpoint("image_loaded")

    def _paste_image(self):
        clipboard = QApplication.clipboard()
        px = clipboard.pixmap()
        if px.isNull():
            img = clipboard.image()
            if not img.isNull():
                px = QPixmap.fromImage(img)
        if px.isNull():
            QMessageBox.information(
                self, "Nothing to paste", "Clipboard mein koi image nahi hai."
            )
            return
        tmp_path, stored_path = self._prepare_pasted_image_target()
        if not px.save(tmp_path, "PNG"):
            QMessageBox.warning(self, "Error", "Could not save pasted image.")
            return
        if self._check_and_handle_duplicate(tmp_path, is_paste=True):
            try:
                import os
                os.remove(tmp_path)
            except Exception:
                pass
            return
        self.card["image_path"] = stored_path
        self.card.pop("pdf_path", None)
        self._pdf_pages = []
        self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False)
        self.btn_crop.setVisible(True)
        self.lbl_sync.setVisible(False)
        self._stop_watch()
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
        self._update_pdf_nav_ui()
        if not self.inp_title.text():
            self.inp_title.setText("Pasted Image")
            self._trigger_ocr_for_image(tmp_path, "Pasted Image")
        self._write_recovery_checkpoint("image_pasted")

    # ── PDF loading ───────────────────────────────────────────────────────────

    def _load_pdf(self):
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf")
            return
        start_dir = ""
        if getattr(self, "_deck", None):
            start_dir = self._deck.get("pdf_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Load PDF", start_dir, "PDF (*.pdf)"
        )
        if not path:
            return
        if self._check_and_handle_duplicate(path):
            return
        if getattr(self, "_deck", None):
            self._deck["pdf_dir"] = os.path.dirname(path)
        try:
            stored_path = self._store_archive_asset(path, "pdfs")
        except Exception as ex:
            QMessageBox.warning(self, "Error", f"Could not archive PDF:\n{ex}")
            return
        abs_path = self._resolve_source_path(stored_path)
        self.card["pdf_path"] = stored_path
        self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
        self._pending_boxes = []
        self.btn_relink.setVisible(True)
        self.btn_crop.setVisible(False)
        self._show_pdf_loading(True)
        self._load_pdf_direct(abs_path)
        self._write_recovery_checkpoint("pdf_loaded")

    def _stop_pdf_threads(self, shutdown=False):
        """Stop any running PDF render thread."""
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            if shutdown:
                self._pdf_loader_thread.wait(500)
            else:
                t = self._pdf_loader_thread
                if not hasattr(self, "_pending_worker_cleanups"):
                    self._pending_worker_cleanups = []
                self._pending_worker_cleanups.append(t)
                t.finished.connect(lambda obj=t: self._pending_worker_cleanups.remove(obj) if obj in self._pending_worker_cleanups else None)
        self._pdf_loader_thread = None
        if self._pdf_ondemand_thread and self._pdf_ondemand_thread.isRunning():
            self._pdf_ondemand_thread.stop()
            self._pdf_ondemand_thread.quit()
            if shutdown:
                self._pdf_ondemand_thread.wait(500)
            else:
                t = self._pdf_ondemand_thread
                if not hasattr(self, "_pending_worker_cleanups"):
                    self._pending_worker_cleanups = []
                self._pending_worker_cleanups.append(t)
                t.finished.connect(lambda obj=t: self._pending_worker_cleanups.remove(obj) if obj in self._pending_worker_cleanups else None)
        self._pdf_ondemand_thread = None
        self._editor_pending_visible_request = None
        self._editor_render_inflight_pages = set()

    def _load_pdf_direct(self, path: str):
        """
        Load a PDF into the editor.

        Strategy:
          1. Build a skeleton immediately so page layout and masks appear fast.
          2. Hydrate visible cache-hot pages into the canvas on demand.
          3. Render only visible cache misses as you scroll.
          4. Fall back to the old full-document loader if skeleton build fails.
        """
        load_t0 = time.perf_counter()
        self._editor_load_t0 = load_t0
        print(
            "[DEBUG][editor_load] start "
            f"file={os.path.basename(path)}"
        )
        self._stop_pdf_threads()
        self._watch_pdf(path)
        self._show_pdf_loading(False)

        # ── Count pages ───────────────────────────────────────────────────────
        total_pages = get_pdf_page_count(path)
        if total_pages <= 0:
            QMessageBox.warning(self, "PDF Error", f"Could not open PDF:\n{path}")
            return

        self._pdf_total_pages = total_pages
        self._pdf_render_zoom = choose_pdf_render_zoom(total_pages)
        previous_zoom = PAGE_CACHE.get_render_zoom(path)
        cached_before = self._editor_cache_count(path, total_pages)
        profile_t0 = time.perf_counter()
        profile_reset = ensure_pdf_cache_profile(path, self._pdf_render_zoom)
        cached_after = self._editor_cache_count(path, total_pages)
        print(
            "[DEBUG][editor_cache_profile] "
            f"file={os.path.basename(path)} pages={total_pages} "
            f"previous_zoom={previous_zoom} target_zoom={self._pdf_render_zoom} "
            f"reset_cache={profile_reset} "
            f"cached_before={cached_before}/{total_pages} "
            f"cached_after={cached_after}/{total_pages} "
            f"t={(time.perf_counter() - profile_t0) * 1000:.1f}ms"
        )
        perf_log(
            "editor_pdf_profile",
            file=os.path.basename(path),
            pages=total_pages,
            zoom=self._pdf_render_zoom,
            previous_zoom=previous_zoom,
            reset_cache=profile_reset,
            cached_before=cached_before,
            cached_after=cached_after,
            elapsed_ms=round((time.perf_counter() - profile_t0) * 1000.0, 3),
        )
        self._pdf_quality_debug(
            "profile",
            pages=total_pages,
            zoom=self._pdf_render_zoom,
            reset_cache=profile_reset,
        )
        skeleton_t0 = time.perf_counter()
        skeleton = load_pdf_skeleton(path, zoom=self._pdf_render_zoom)
        skeleton_ms = (time.perf_counter() - skeleton_t0) * 1000
        if skeleton and not getattr(skeleton, "error", None):
            pages = list(
                getattr(skeleton, "placeholders", None)
                or build_skeleton_placeholders(getattr(skeleton, "page_dims", []))
            )
            self._finish_pdf_load(path, pages, real_pages=set())
            self._wire_editor_scroll_ondemand(path, total_pages)
            self.lbl_sync.setText("⏳ PDF ready on demand")
            self.lbl_sync.setStyleSheet(
                f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
            )
            self.lbl_sync.setVisible(True)
            print(
                "[DEBUG][editor_skeleton] ready "
                f"pages={total_pages} placeholders={len(pages)} "
                f"dims={len(getattr(skeleton, 'page_dims', []) or [])} "
                f"t={skeleton_ms:.1f}ms"
            )
            print(
                "[DEBUG][editor_ondemand] skeleton_ready "
                f"pages={total_pages} total={(time.perf_counter() - load_t0) * 1000:.1f}ms"
            )
            QTimer.singleShot(120, self._sc._emit_visible_pages)
            return

        # Fallback path if skeleton build fails.
        cache_state = get_cached_pdf_page_set(path, total_pages)
        self.lbl_sync.setText(f"⏳ Rendering {cache_state['cache_miss_count']} pages…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
        )
        self.lbl_sync.setVisible(True)
        self._show_pdf_loading(True)
        print(
            "[DEBUG][editor_ondemand] skeleton_fallback_render "
            f"path={os.path.basename(path)} skeleton_t={skeleton_ms:.1f}ms "
            f"error={getattr(skeleton, 'error', None)}"
        )
        self._pdf_loader_thread = PdfLoaderThread(
            path, zoom=self._pdf_render_zoom, parent=self
        )
        self._pdf_loader_thread.done.connect(self._on_pdf_done)
        self._pdf_loader_thread.start()

    def _finish_pdf_load(self, path: str, pages: list, real_pages=None):
        """
        Common finalisation after pages are ready (cache hit or render done).
        Loads pages into canvas, restores boxes, sets scroll position.
        """
        finish_t0 = time.perf_counter()
        self.canvas._current_pdf_path = path
        self._editor_ondemand_path = path
        self._editor_ondemand_total = len(pages or [])
        self._editor_visible_debug_seen_pages = set()
        self._editor_canvas_real_pages = set(int(pn) for pn in (real_pages or set()))
        self._editor_render_inflight_pages.clear()
        self._editor_pending_visible_request = None
        existing_boxes = self.canvas.get_boxes()
        canvas_t0 = time.perf_counter()
        self.canvas.load_pages(pages)
        print(
            "[DEBUG][editor_canvas] load_pages "
            f"pages={len(pages or [])} real_pages={len(real_pages or set())} "
            f"t={(time.perf_counter() - canvas_t0) * 1000:.1f}ms"
        )
        self._after_load_scroll()
        self._schedule_zoom_fit(80)

        n = len(pages)
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  {n} page{'s' if n != 1 else ''}"
        )
        self.pdf_bar.show()
        self._update_pdf_nav_ui()

        if not self.inp_title.text():
            self.inp_title.setText(self._auto_subdeck_name or "")

        boxes_to_restore = (
            self._pending_boxes or existing_boxes or list(self.card.get("boxes", []))
        )
        boxes_source = (
            "pending"
            if self._pending_boxes
            else "existing_canvas"
            if existing_boxes
            else "card"
        )
        adapt_t0 = time.perf_counter()
        adapted_boxes = False
        if boxes_to_restore:
            if self._pending_boxes_need_pdf_adapt:
                source_zoom = self.card.get("_pdf_box_render_zoom")
                if source_zoom is None:
                    source_zoom = PDF_LEGACY_BOX_ZOOM
                boxes_to_restore = adapt_pdf_boxes_to_render_zoom(
                    path,
                    boxes_to_restore,
                    source_zoom,
                    self._pdf_render_zoom,
                )
                self._pdf_quality_debug(
                    "box_remap",
                    source_zoom=source_zoom,
                    target_zoom=self._pdf_render_zoom,
                    boxes=len(boxes_to_restore),
                )
                self._pending_boxes_need_pdf_adapt = False
                adapted_boxes = True
            self.canvas.set_boxes(boxes_to_restore)
            self.mask_panel._refresh(boxes_to_restore)
        print(
            "[DEBUG][editor_boxes] restore "
            f"source={boxes_source} boxes={len(boxes_to_restore or [])} "
            f"adapted={'yes' if adapted_boxes else 'no'} "
            f"t={(time.perf_counter() - adapt_t0) * 1000:.1f}ms"
        )
        self._pending_boxes = []
        self.btn_open_ext.setVisible(True)
        self.btn_annotate_beta.setVisible(True)
        total_ms = (
            (time.perf_counter() - float(self._editor_load_t0)) * 1000
            if self._editor_load_t0
            else (time.perf_counter() - finish_t0) * 1000
        )
        print(
            "[DEBUG][editor_load] finish "
            f"file={os.path.basename(path)} pages={len(pages or [])} "
            f"total={total_ms:.1f}ms"
        )

    def _wire_editor_scroll_ondemand(self, path: str, total_pages: int):
        try:
            self._sc.visible_pages_changed.disconnect(
                self._on_editor_visible_pages_changed
            )
        except Exception:
            pass
        self._editor_ondemand_path = path
        self._editor_ondemand_total = int(total_pages or 0)
        self._editor_visible_debug_seen_pages = set()
        self._sc.visible_pages_changed.connect(self._on_editor_visible_pages_changed)
        print(
            "[DEBUG][editor_ondemand] wired "
            f"pages={int(total_pages or 0)} path={os.path.basename(path)}"
        )

    def _on_editor_visible_pages_changed(self, first, last):
        handler_t0 = time.perf_counter()
        path = getattr(self, "_editor_ondemand_path", None)
        if not path:
            return
        first = max(0, int(first))
        last = max(first, int(last))
        visible_pages = list(range(first, last + 1))
        prev_visible = set(
            self.__dict__.get("_editor_visible_debug_seen_pages", set()) or set()
        )
        entered_pages = [pn for pn in visible_pages if pn not in prev_visible]
        self._editor_visible_debug_seen_pages = set(visible_pages)
        if entered_pages and self._editor_verbose_debug_enabled():
            current_page = visible_pages[len(visible_pages) // 2]
            entered_states = ", ".join(
                f"p.{pn + 1}:{self._editor_page_view_state(path, pn)}"
                for pn in entered_pages
            )
            print(
                f"[DEBUG][editor_viewport] visible=p.{first + 1}-p.{last + 1} "
                f"current=p.{current_page + 1}:{self._editor_page_view_state(path, current_page)} "
                f"entered={entered_states}"
            )
        inject_stats = self._inject_editor_cached_visible_pages(path, visible_pages)
        needed = self._editor_pages_needing_render(path, visible_pages)
        decision_stats = dict(self.__dict__.get("_editor_last_decision_stats", {}) or {})
        if not needed:
            self._log_editor_scroll_profile(
                first=first,
                last=last,
                entered_pages=entered_pages,
                needed=needed,
                inject_stats=inject_stats,
                decision_stats=decision_stats,
                total_ms=(time.perf_counter() - handler_t0) * 1000.0,
                queued=False,
                render_started=False,
            )
            return
        if self._pdf_ondemand_thread and self._pdf_ondemand_thread.isRunning():
            self._editor_pending_visible_request = (path, list(needed))
            print(
                "[DEBUG][editor_ondemand] queue_visible "
                f"need={self._fmt_editor_pages(needed)}"
            )
            self._log_editor_scroll_profile(
                first=first,
                last=last,
                entered_pages=entered_pages,
                needed=needed,
                inject_stats=inject_stats,
                decision_stats=decision_stats,
                total_ms=(time.perf_counter() - handler_t0) * 1000.0,
                queued=True,
                render_started=False,
            )
            return
        self._start_editor_visible_page_request(path, needed)
        self._log_editor_scroll_profile(
            first=first,
            last=last,
            entered_pages=entered_pages,
            needed=needed,
            inject_stats=inject_stats,
            decision_stats=decision_stats,
            total_ms=(time.perf_counter() - handler_t0) * 1000.0,
            queued=False,
            render_started=True,
        )

    def _inject_editor_cached_visible_pages(self, path, visible_pages):
        t0 = time.perf_counter()
        visible_pages = [int(pn) for pn in (visible_pages or [])]
        real_pages = set(self.__dict__.get("_editor_canvas_real_pages", set()) or set())
        inflight = set(
            self.__dict__.get("_editor_render_inflight_pages", set()) or set()
        )
        injected = []
        cache_checks = 0
        cache_hits = 0
        for pn in visible_pages:
            if pn in real_pages or pn in inflight:
                continue
            cache_checks += 1
            cached = PAGE_CACHE.get(path, pn, ram_only=True)
            if cached is None or cached.isNull():
                continue
            cache_hits += 1
            if self._editor_verbose_debug_enabled():
                print(f"[DEBUG][editor_lazy] ⚡ p.{pn + 1}")
            self.canvas.inject_page(pn, cached)
            self.__dict__.setdefault("_editor_canvas_real_pages", set()).add(pn)
            if self._editor_verbose_debug_enabled():
                print(
                    f"[DEBUG][editor_inject] p.{pn + 1} injected=yes kind=visible_cache"
                )
            injected.append(pn)
        if injected:
            if self._editor_verbose_debug_enabled():
                print(
                    "[DEBUG][editor_visible_cache] hydrate "
                    + ", ".join(f"p.{pn + 1}" for pn in injected)
                )
            self._update_pdf_nav_ui()
        perf_log(
            "editor_inject_cached_visible",
            file=os.path.basename(path) if path else "",
            visible=len(visible_pages),
            injected=len(injected),
            cache_checks=cache_checks,
            cache_hits=cache_hits,
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        return {
            "cache_checks": cache_checks,
            "cache_hits": cache_hits,
            "injected": len(injected),
            "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
        }

    def _start_editor_visible_page_request(self, path, needed):
        needed = sorted({int(pn) for pn in (needed or [])})
        self._editor_pending_visible_request = None
        if needed:
            print(
                "[DEBUG][editor_ondemand] render_request "
                + ", ".join(f"p.{pn + 1}" for pn in needed)
            )
        else:
            print("[DEBUG][editor_ondemand] render_request skipped need=none")
        self.__dict__.setdefault("_editor_render_inflight_pages", set()).update(needed)
        self._editor_ondemand_requested_pages = set(needed)
        self._pdf_ondemand_thread = PdfOnDemandThread(
            path, needed, zoom=self._pdf_render_zoom, parent=self
        )
        request_thread = self._pdf_ondemand_thread
        self.__dict__.setdefault("_editor_ondemand_request_pages_by_thread", {})[
            id(request_thread)
        ] = set(needed)
        self._pdf_ondemand_thread.page_ready.connect(self._on_editor_page_ready)
        self._pdf_ondemand_thread.batch_done.connect(
            lambda rendered, thread=request_thread: self._on_editor_visible_pages_batch_done(
                rendered, thread
            )
        )
        self._pdf_ondemand_thread.error.connect(lambda err: None)
        self._pdf_ondemand_thread.start()

    def _editor_requested_pages_for_thread(self, thread):
        if thread is None:
            return set(self.__dict__.pop("_editor_ondemand_requested_pages", set()) or set())
        requests = self.__dict__.setdefault("_editor_ondemand_request_pages_by_thread", {})
        requested = set(requests.pop(id(thread), set()) or set())
        if thread is getattr(self, "_pdf_ondemand_thread", None):
            requested |= set(
                self.__dict__.pop("_editor_ondemand_requested_pages", set()) or set()
            )
        return requested

    def _on_editor_visible_pages_batch_done(self, rendered, thread=None):
        requested = self._editor_requested_pages_for_thread(thread)
        self.__dict__.setdefault("_editor_render_inflight_pages", set()).difference_update(
            requested
        )
        if thread is not None and thread is not getattr(self, "_pdf_ondemand_thread", None):
            print(
                "[DEBUG][editor_ondemand] stale_done "
                f"requested={self._fmt_editor_pages(requested)} "
                f"rendered={self._fmt_editor_pages(rendered)}"
            )
            return
        if thread is not None:
            self._pdf_ondemand_thread = None
        pending = self._editor_pending_visible_request
        self._editor_pending_visible_request = None
        print(
            "[DEBUG][editor_ondemand] batch_done "
            f"requested={self._fmt_editor_pages(requested)} "
            f"rendered={self._fmt_editor_pages(rendered)} "
            f"pending={self._fmt_editor_pages(pending[1] if pending else [])}"
        )
        if pending and pending[0] == getattr(self, "_editor_ondemand_path", None):
            path, needed = pending
            fresh_needed = self._editor_pages_needing_render(
                path, needed, context="after_visible"
            )
            if fresh_needed:
                self._start_editor_visible_page_request(path, fresh_needed)

    def _on_editor_page_ready(self, page_num, qpx):
        from PyQt5.QtGui import QImage, QPixmap

        path = getattr(self, "_editor_ondemand_path", None)
        page_num = int(page_num)
        self.__dict__.setdefault("_editor_render_inflight_pages", set()).discard(
            page_num
        )
        if path != getattr(self.canvas, "_current_pdf_path", None):
            if self._editor_verbose_debug_enabled():
                print(
                    f"[DEBUG][editor_inject] p.{page_num + 1} injected=no reason=stale_path"
                )
            return
        if not getattr(self.canvas, "_pages", None):
            if self._editor_verbose_debug_enabled():
                print(
                    f"[DEBUG][editor_inject] p.{page_num + 1} injected=no reason=canvas_empty"
                )
            return
        if self._editor_verbose_debug_enabled():
            print(f"[DEBUG][editor_lazy] 👀 p.{page_num + 1}")
        cache_px = None
        if isinstance(qpx, QPixmap):
            cache_px = qpx
        elif isinstance(qpx, QImage):
            cache_px = QPixmap.fromImage(qpx)
        if cache_px is not None and not cache_px.isNull():
            PAGE_CACHE.put(path, page_num, cache_px, render_zoom=self._pdf_render_zoom)
        self.canvas.inject_page(page_num, cache_px if cache_px is not None else qpx)
        self.__dict__.setdefault("_editor_canvas_real_pages", set()).add(page_num)
        if self._editor_verbose_debug_enabled():
            print(f"[DEBUG][editor_inject] p.{page_num + 1} injected=yes kind=visible")
        print(f"[DEBUG][editor_ondemand] loaded p.{page_num + 1}")
        self._update_pdf_nav_ui()

    def _editor_page_view_state(self, path: str, page_num: int) -> str:
        page_num = int(page_num)
        if page_num in set(
            self.__dict__.get("_editor_canvas_real_pages", set()) or set()
        ):
            return "canvas_real"
        pending = self.__dict__.get("_editor_pending_visible_request")
        if pending and pending[0] == path and page_num in set(pending[1] or []):
            return "queued_visible_render"
        if page_num in set(
            self.__dict__.get("_editor_render_inflight_pages", set()) or set()
        ):
            return "rendering"
        cached = PAGE_CACHE.get(path, page_num, ram_only=True)
        if cached is not None and not cached.isNull():
            return "cache_hot_canvas_gray"
        pages = getattr(self.canvas, "_pages", None) or []
        if (
            0 <= page_num < len(pages)
            and pages[page_num] is not None
            and not pages[page_num].isNull()
        ):
            return "placeholder_gray"
        return "canvas_missing"

    def _after_load_scroll(self):
        """Scroll to exact image-space position after canvas is ready."""
        self._schedule_initial_view_restore("after_load")

    def _apply_initial_view_position(
        self, reason: str = "manual", finalize: bool = False
    ):
        vbar = self._sc.verticalScrollBar()
        if self._initial_img_y is not None:
            img_y = float(self._initial_img_y)
            editor_scale = max(float(getattr(self.canvas, "_scale", 1.0) or 1.0), 0.01)
            scroll_y = int(img_y * editor_scale)
            print(
                f"[DEBUG][editor_restore] apply_img_y reason={reason} "
                f"img_y={img_y:.2f} scale={editor_scale:.4f} scroll_y={scroll_y}"
            )
            vbar.setValue(scroll_y)
            if finalize:
                self._initial_img_y = None
            return True
        if self._initial_page is not None and self._initial_page >= 0:
            pg = int(self._initial_page)
            print(f"[DEBUG][editor_restore] apply_page reason={reason} page={pg + 1}")
            self.canvas.scroll_to_page(pg, self._sc)
            if finalize:
                self._initial_page = None
            return True
        if self._initial_scroll > 0:
            sv = int(self._initial_scroll)
            print(f"[DEBUG][editor_restore] apply_scroll reason={reason} scroll_y={sv}")
            vbar.setValue(sv)
            if finalize:
                self._initial_scroll = 0
            return True
        return False

    def _schedule_initial_view_restore(self, reason: str, delays_ms=(30, 90, 180)):
        if (
            self._initial_img_y is None
            and not (self._initial_page is not None and self._initial_page >= 0)
            and self._initial_scroll <= 0
        ):
            return

        delays = list(delays_ms) if delays_ms else [0]
        for idx, delay in enumerate(delays):
            finalize = idx == len(delays) - 1
            QTimer.singleShot(
                int(delay),
                lambda rsn=f"{reason}@{delay}ms", fin=finalize: self._apply_initial_view_position(
                    rsn, finalize=fin
                ),
            )

    def _current_visible_page(self) -> int:
        scroll_pos = self._sc.verticalScrollBar().value()
        return self.canvas.get_current_page(scroll_pos)

    def _coerce_loader_pages_to_pixmaps(self, path: str, pages: list):
        from PyQt5.QtGui import QImage, QPixmap

        out = []
        for page_num, page_obj in enumerate(pages or []):
            if isinstance(page_obj, QPixmap):
                px = page_obj
            elif isinstance(page_obj, QImage):
                px = QPixmap.fromImage(page_obj)
            else:
                px = page_obj
            if px is not None and hasattr(px, "isNull") and not px.isNull():
                PAGE_CACHE.put(path, page_num, px, render_zoom=self._pdf_render_zoom)
            out.append(px)
        return out

    def _on_pdf_done(self, pages: list, err):
        """Called by PdfLoaderThread when all pages are rendered."""
        done_t0 = time.perf_counter()
        self._show_pdf_loading(False)
        path = self._resolve_source_path(self.card.get("pdf_path", ""))
        if not pages:
            print(f"[DEBUG][editor_loader] done error={err}")
            QMessageBox.warning(self, "PDF Error", err or "Could not render PDF.")
            return
        pages = self._coerce_loader_pages_to_pixmaps(path, pages)
        self._finish_pdf_load(path, pages, real_pages=set(range(len(pages))))
        print(
            "[DEBUG][editor_loader] done "
            f"pages={len(pages)} t={(time.perf_counter() - done_t0) * 1000:.1f}ms"
        )
        self.lbl_sync.setText(f"✅ Rendered {len(pages)} pages")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_GREEN', C_GREEN)};font-size:11px;background:transparent;font-weight:bold;"
        )
        self.lbl_sync.setVisible(True)

    def _show_pdf_loading(self, loading: bool):
        if loading:
            self.setWindowTitle("Occlusion Card Editor  ⏳ Loading PDF…")
            self.lbl_sync.setVisible(True)
            self.lbl_sync.setText("⏳ Loading PDF…")
            self.lbl_sync.setStyleSheet(
                f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
            )
        else:
            self.setWindowTitle("Occlusion Card Editor")

    # ── card load ─────────────────────────────────────────────────────────────

    def _load_card(self, card):
        """File: editor_ui.py -> Class: CardEditorDialog"""
        load_t0 = time.perf_counter()
        self.inp_title.setText(card.get("title", ""))
        self.inp_tags.setText(", ".join(card.get("tags", [])))
        self.chk_formula.setChecked(card.get("is_formula", False))
        notes = card.get("notes", "")
        if "<img" in notes or "<html>" in notes or "<p>" in notes:
            self.inp_notes.setHtml(notes)
        else:
            self.inp_notes.setPlainText(notes)

        current_boxes = card.get("boxes", [])
        image_path = self._resolve_source_path(card.get("image_path", ""))
        pdf_path = self._resolve_source_path(card.get("pdf_path", ""))

        if card.get("image_path") and os.path.exists(image_path):
            print(
                "[DEBUG][editor_card] load "
                f"source=image boxes={len(current_boxes or [])} "
                f"file={os.path.basename(image_path)}"
            )
            px = QPixmap(image_path)
            if px and not px.isNull():
                from data_manager import store
                invert = store.get().get("_invert_pdf", False)
                if invert:
                    from PyQt5.QtGui import QImage
                    img = px.toImage()
                    img.invertPixels(QImage.InvertRgb)
                    px = QPixmap.fromImage(img)
                self.canvas.load_pixmap(px)
            if current_boxes:
                self.canvas.set_boxes(current_boxes)
                self.mask_panel._refresh(current_boxes)
            self._schedule_initial_view_restore("image_load")
            self.btn_crop.setVisible(True)
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(pdf_path):
            self.card["pdf_path"] = card.get("pdf_path", "")
            self._auto_subdeck_name = os.path.splitext(os.path.basename(pdf_path))[0]
            self._pending_boxes = current_boxes
            self._pending_boxes_need_pdf_adapt = True
            self.btn_relink.setVisible(True)
            self.btn_crop.setVisible(False)
            self._show_pdf_loading(True)
            print(
                "[DEBUG][editor_card] load "
                f"source=pdf boxes={len(current_boxes or [])} "
                f"file={os.path.basename(pdf_path)} "
                f"t={(time.perf_counter() - load_t0) * 1000:.1f}ms"
            )
            self._load_pdf_direct(pdf_path)
        elif card.get("pdf_path") and not os.path.exists(pdf_path):
            print(
                "[DEBUG][editor_card] load "
                f"source=missing_pdf boxes={len(current_boxes or [])} "
                f"file={os.path.basename(pdf_path)}"
            )
            self.btn_relink.setVisible(True)
            self.btn_crop.setVisible(False)
            self.lbl_sync.setVisible(True)
            self.lbl_sync.setText("⚠ PDF not found — click 🔄 Relink PDF to fix")
            self.lbl_sync.setStyleSheet(
                "color:#CC6600;font-size:11px;background:transparent;font-weight:bold;"
            )
            # Apply masks directly to canvas right now — no PDF load will trigger
            # _on_pdf_done so _pending_boxes would never get restored otherwise
            if current_boxes:
                self._pending_boxes = current_boxes
                self.canvas.set_boxes(current_boxes)
                self.mask_panel._refresh(current_boxes)

    # ── file watcher (live sync) ───────────────────────────────────────────────

    def _watch_pdf(self, path: str):
        self._stop_watch()
        self._watched_path = path
        self._watcher.addPath(path)
        self.btn_open_ext.setVisible(True)
        self.btn_relink.setVisible(True)
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("🟢 Live Sync: watching")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_GREEN', C_GREEN)};font-size:11px;background:transparent;font-weight:bold;"
        )

    def _stop_watch(self):
        if self._watched_path:
            self._watcher.removePath(self._watched_path)
            self._watched_path = None
        self._reload_timer.stop()

    def _on_file_changed(self, path: str):
        key = os.path.abspath(path) if path else ""
        if key and self._ignored_watch_paths.get(key, 0) > 0:
            self._ignored_watch_paths[key] -= 1
            if self._ignored_watch_paths[key] <= 0:
                self._ignored_watch_paths.pop(key, None)
            if path and os.path.exists(path) and path not in self._watcher.files():
                self._watcher.addPath(path)
            return
        self.lbl_sync.setText("🟡 Live Sync: change detected…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
        )
        self._reload_timer.start()

    def _reload_pdf(self):
        path = self._watched_path
        if not path or not os.path.exists(path):
            QTimer.singleShot(500, self._reload_pdf)
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)
        reload_t0 = time.perf_counter()
        changed = get_changed_pages(path)
        if changed is None:
            PAGE_CACHE.invalidate_pdf(path)
            changed_text = "all"
        else:
            PAGE_CACHE.invalidate_pages(path, changed)
            changed_text = self._fmt_editor_pages(changed)
        print(
            "[DEBUG][editor_reload] "
            f"file={os.path.basename(path)} changed={changed_text} "
            f"hash_t={(time.perf_counter() - reload_t0) * 1000:.1f}ms"
        )

        saved_boxes = self.canvas.get_boxes()
        self._pending_boxes = saved_boxes
        self._pending_boxes_need_pdf_adapt = False
        self.lbl_sync.setText("🟡 Live Sync: reloading…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
        )
        self._load_pdf_direct(path)

    def _open_in_reader(self):
        path = self._current_pdf_path_for_shortcuts()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
            return
        import subprocess

        page = self._current_visible_page() + 1
        try:
            pdf_url = QUrl.fromLocalFile(path)
            pdf_url.setFragment(f"page={page}")
            if QDesktopServices.openUrl(pdf_url):
                return
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            QMessageBox.warning(self, "Could not open", f"Could not open PDF:\n{ex}")

    def _current_pdf_path_for_shortcuts(self) -> str:
        path = self._resolve_source_path(
            self.card.get("pdf_path") or self._watched_path
        )
        if not path or not os.path.exists(path):
            return ""
        return path

    def _copy_current_pdf_file_to_clipboard(self):
        path = self._current_pdf_path_for_shortcuts()
        if not path:
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        QApplication.clipboard().setMimeData(mime)
        print(f"[DEBUG][editor_pdf_shortcut] copied_file {path}")
        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("Copied PDF file")

    def _reveal_current_pdf_in_folder(self):
        path = self._current_pdf_path_for_shortcuts()
        if not path:
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
            return
        try:
            import subprocess

            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
            print(f"[DEBUG][editor_pdf_shortcut] reveal_path {path}")
            self.lbl_sync.setVisible(True)
            self.lbl_sync.setText("Opened PDF folder")
        except Exception as ex:
            QMessageBox.warning(
                self, "Could not open location", f"Could not open PDF location:\n{ex}"
            )

    def _open_annotation_beta(self):
        path = self._resolve_source_path(
            self.card.get("pdf_path") or self._watched_path
        )
        if not path or not os.path.exists(path):
            image_path = self._resolve_source_path(self.card.get("image_path", ""))
            if image_path and os.path.exists(image_path):
                try:
                    import fitz
                    from storage_paths import build_archive_asset_path
                    import data_manager
                    
                    stem = os.path.splitext(os.path.basename(image_path))[0]
                    pdf_abs_path, pdf_rel_path = build_archive_asset_path("pdfs", f"{stem}.pdf")
                    
                    doc = fitz.open()
                    img_doc = fitz.open(image_path)
                    pdf_bytes = img_doc.convert_to_pdf()
                    img_doc.close()
                    
                    pdf_mem = fitz.open("pdf", pdf_bytes)
                    doc.insert_pdf(pdf_mem)
                    doc.save(pdf_abs_path)
                    doc.close()
                    
                    self.card["pdf_path"] = pdf_rel_path
                    data_manager.store.mark_dirty()
                    data_manager.store.save_force(async_save=True)
                    path = pdf_abs_path
                except Exception as e:
                    print(f"[ERROR][editor_dialog] Failed to convert image to PDF: {e}")
                    QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
                    return
            else:
                QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
                return
        page_zero = self._current_visible_page()
        scroll_y = self._sc.verticalScrollBar().value()
        editor_scale = max(float(getattr(self.canvas, "_scale", 1.0) or 1.0), 0.01)
        img_y = float(scroll_y) / editor_scale
        print(
            f"[DEBUG][editor_annotation] handoff "
            f"page={page_zero + 1} scroll_y={scroll_y} scale={editor_scale:.4f} img_y={img_y:.2f}"
        )
        dialog = PdfAnnotationDialog(
            path,
            parent=self,
            initial_page=page_zero,
            initial_anchor_y=img_y,
        )
        dialog.exec_()
        self._apply_annotation_beta_refresh(
            path, dialog._saved_pages, dialog.return_page, dialog.return_anchor_y
        )

    def _apply_annotation_beta_refresh(
        self, path: str, changed_pages, return_page: int, return_scroll: int | None
    ):
        refresh_t0 = time.perf_counter()
        if not changed_pages:
            print(
                "[DEBUG][editor_annotation] refresh "
                f"changed=none return_page={return_page} return_scroll={return_scroll}"
            )
            if return_page is not None:
                QTimer.singleShot(0, lambda pg=return_page: self._go_to_page(pg))
            return
        key = os.path.abspath(path)
        self._ignored_watch_paths[key] = self._ignored_watch_paths.get(key, 0) + 2
        self._pdf_quality_debug(
            "annotation_refresh",
            pages=[pn + 1 for pn in changed_pages],
            zoom=self._pdf_render_zoom,
        )
        for page_num in sorted(set(int(pn) for pn in changed_pages)):
            px = PAGE_CACHE.get(path, page_num)
            if px is not None and not px.isNull():
                if self._editor_verbose_debug_enabled():
                    print(f"[DEBUG][editor_lazy] ⚡ p.{page_num + 1}")
                self.canvas.inject_page(page_num, px)
                self.__dict__.setdefault("_editor_canvas_real_pages", set()).add(
                    page_num
                )
                if self._editor_verbose_debug_enabled():
                    print(
                        f"[DEBUG][editor_inject] p.{page_num + 1} injected=yes kind=annotation_refresh"
                    )
        self._update_pdf_nav_ui()
        print(
            "[DEBUG][editor_annotation] refresh "
            f"changed={self._fmt_editor_pages(changed_pages)} "
            f"return_page={return_page} return_scroll={return_scroll} "
            f"t={(time.perf_counter() - refresh_t0) * 1000:.1f}ms"
        )
        if return_page is not None:
            QTimer.singleShot(0, lambda pg=return_page: self._go_to_page(pg))
        elif return_scroll is not None:
            QTimer.singleShot(
                0,
                lambda sv=return_scroll: self._sc.verticalScrollBar().setValue(int(sv)),
            )

    def _relink_pdf(self):
        """Pick a new PDF file — replaces the stored path but keeps ALL existing masks."""
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf")
            return

        old_path = self._resolve_source_path(
            self.card.get("pdf_path", "") or self._watched_path or ""
        )
        start_dir = os.path.dirname(old_path) if old_path else ""
        if not start_dir and getattr(self, "_deck", None):
            start_dir = self._deck.get("pdf_dir", "")

        new_path, _ = QFileDialog.getOpenFileName(
            self, "Choose New PDF File", start_dir, "PDF (*.pdf)"
        )
        if not new_path:
            return
        if getattr(self, "_deck", None):
            self._deck["pdf_dir"] = os.path.dirname(new_path)
        try:
            stored_new_path = self._store_archive_asset(new_path, "pdfs")
        except Exception as ex:
            QMessageBox.warning(self, "Error", f"Could not archive PDF:\n{ex}")
            return
        resolved_new_path = self._resolve_source_path(stored_new_path)

        # Confirm so user doesn't accidentally overwrite with wrong file
        reply = QMessageBox.question(
            self,
            "Relink PDF",
            f"Replace source PDF with:\n{new_path}\n\n"
            "All your existing masks will be kept exactly as they are.\n"
            "The new PDF will be used as the background going forward.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        # Save masks — prefer canvas if it has boxes loaded (normal relink),
        # fall back to card["boxes"] when canvas is empty (broken-path relink)
        canvas_boxes = self.canvas.get_boxes()
        saved_boxes = canvas_boxes if canvas_boxes else list(self.card.get("boxes", []))

        # Invalidate old cache, update stored path
        if old_path:
            PAGE_CACHE.invalidate_pdf(old_path)
        self.card["pdf_path"] = stored_new_path
        self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(new_path))[0]

        # _pending_boxes makes _on_pdf_done restore masks after load
        self._pending_boxes = saved_boxes
        self._pending_boxes_need_pdf_adapt = True

        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("🔄 Relinking…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
        )

        self._show_pdf_loading(True)
        self._load_pdf_direct(resolved_new_path)
        self._write_recovery_checkpoint("pdf_relinked")

    # ── save / close ──────────────────────────────────────────────────────────

    @staticmethod
    def _queue_collection_save():
        """Persist completed mask edits without blocking the editor window."""
        from data_manager import store

        store.mark_dirty()
        store.save_soon(min_interval=0.0, delay_from_now=False)

    @trace_perf
    def _save(self, keep_open=False):
        save_t0 = time.perf_counter()
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self, "No Source", "Load an image or PDF first.")
            return
        old_boxes = self.card.get("boxes", [])
        new_boxes = self.canvas.get_boxes()
        SM2_KEYS = (
            "sm2_interval",
            "sm2_repetitions",
            "sm2_ease",
            "sm2_due",
            "sm2_last_quality",
            "box_id",
            "sched_state",
            "sched_step",
            "reviews",
        )
        old_by_id = {b["box_id"]: b for b in old_boxes if "box_id" in b}
        merged = []
        for nb in new_boxes:
            old = old_by_id.get(nb.get("box_id"))
            if old:
                for k in SM2_KEYS:
                    if k in old:
                        nb[k] = old[k]
            if "box_id" not in nb:
                nb["box_id"] = new_box_id()
            merged.append(nb)
        self.card.update(
            {
                "title": self.inp_title.text().strip() or "Untitled",
                "tags": [
                    t.strip() for t in self.inp_tags.text().split(",") if t.strip()
                ],
                "notes": self.inp_notes.toHtml() if "<img" in self.inp_notes.toHtml() else self.inp_notes.toPlainText(),
                "boxes": merged,
                "created": self.card.get("created", datetime.now().isoformat()),
                "reviews": self.card.get("reviews", 0),
                "is_formula": self.chk_formula.isChecked(),
            }
        )
        if self.card.get("pdf_path"):
            self.card["_pdf_box_render_zoom"] = float(
                self._pdf_render_zoom or PDF_LEGACY_BOX_ZOOM
            )
        if self._auto_subdeck_name:
            self.card["_auto_subdeck"] = self._auto_subdeck_name
        sm2_init(self.card)
        for box in self.card.get("boxes", []):
            sm2_init(box)
        print(
            "[DEBUG][editor_save] "
            f"source={'pdf' if self.card.get('pdf_path') else 'image'} "
            f"old_boxes={len(old_boxes or [])} "
            f"new_boxes={len(new_boxes or [])} "
            f"merged={len(merged)} "
            f"pdf_zoom={self.card.get('_pdf_box_render_zoom', 'none')} "
            f"t={(time.perf_counter() - save_t0) * 1000:.1f}ms"
        )
        self._write_recovery_checkpoint("save_card")

        # Save to database/deck
        if self._recovery_mode == "add":
            card_to_add = self.card
            subdeck_name = self._auto_subdeck_name
            if subdeck_name and self._deck:
                if self._deck.get("name", "").strip().lower() == subdeck_name.strip().lower():
                    target_deck = self._deck
                else:
                    target_deck = None
                    for child in self._deck.get("children", []):
                        if child.get("name", "").strip().lower() == subdeck_name.strip().lower():
                            target_deck = child
                            break
                    if target_deck is None:
                        from data_manager import next_deck_id
                        target_deck = {
                            "_id": next_deck_id(self._data),
                            "name": subdeck_name,
                            "cards": [],
                            "children": [],
                            "created": datetime.now().isoformat(),
                        }
                        self._deck.setdefault("children", []).append(target_deck)
                if card_to_add not in target_deck.setdefault("cards", []):
                    target_deck.setdefault("cards", []).append(card_to_add)
            elif self._deck:
                if has_mission_archive() and card_to_add.get("pdf_path"):
                    deck_segments = find_deck_segments(self._data, self._deck.get("_id"))
                    relocate_pdf_for_deck(card_to_add, deck_segments)
                if card_to_add not in self._deck.setdefault("cards", []):
                    self._deck.setdefault("cards", []).append(card_to_add)
        elif self._recovery_mode == "edit":
            orig_card = None
            card_id = self.card.get("_id")
            if card_id is not None:
                def _find(d):
                    for c in d.get("cards", []):
                        if c.get("_id") == card_id:
                            return c
                    for child in d.get("children", []):
                        res = _find(child)
                        if res:
                            return res
                    return None
                if self._deck:
                    orig_card = _find(self._deck)
                if not orig_card and self._data:
                    for d in self._data.get("decks", []):
                        orig_card = _find(d)
                        if orig_card:
                            break
            if orig_card:
                orig_card.clear()
                orig_card.update(self.card)

        # A full collection snapshot can be expensive on a large deck.  The
        # recovery checkpoint above is already durable, so coalesce the normal
        # collection write off the UI thread and return to review immediately.
        self._queue_collection_save()
        self._card_saved_once = True

        if hasattr(self, "btn_cancel"):
            self.btn_cancel.setText("Done")
            self.btn_cancel.setToolTip("Close window")

        if keep_open:
            self.canvas._show_toast("💾 Progress Saved (Cloud deferred)")
            print("[EditCardDialog] Ctrl+S — local save triggered (cloud sync deferred)")
            return

        self.canvas._show_toast("💾 Card saved")

        if self._recovery_mode == "add":
            self.clear_recovery_draft()
            self._reset_for_next_card()
        else:
            self.accept()

    def _reset_for_next_card(self):
        self.card = {}
        self._recovery_initial_card = {}
        self._recovery_draft_id = recovery_manager.new_draft_id()
        self._recovery_draft_cleared = False
        self._recovery_dirty = False
        self._recovery_created_at = datetime.now().isoformat()
        self._last_recovery_draft_fingerprint = None
        self._auto_subdeck_name = None

        # Clear inputs
        self.inp_title.clear()
        self.inp_tags.clear()
        self.inp_notes.clear()

        # Clear canvas
        self.canvas._pages = []
        self.canvas._px = None
        self.canvas._boxes = []
        self.canvas._selected_idx = -1
        self.canvas._selected_indices = set()
        self.canvas.update()

        # Stop watch/threads
        self._stop_watch()
        self._stop_pdf_threads()
        self._stop_ocr_thread()
        self._pdf_pages = []
        self._cur_page = 0
        self._pdf_total_pages = 0
        self._editor_canvas_real_pages = set()
        self._editor_render_inflight_pages = set()
        self._editor_visible_debug_seen_pages = set()
        self._pending_boxes = []
        self._editor_ondemand_path = None

        # Reset UI elements
        self.pdf_bar.setVisible(False)
        self.btn_open_ext.setVisible(False)
        self.btn_annotate_beta.setVisible(False)
        self.btn_relink.setVisible(False)
        self.btn_crop.setVisible(False)
        self.lbl_sync.setVisible(False)
        self.lbl_sync.setText("")
        self.setWindowTitle("Occlusion Card Editor")
        self.mask_panel._refresh([])

    def _on_cancel_clicked(self):
        if getattr(self, "_card_saved_once", False):
            self.accept()
        else:
            self.reject()

    def get_card(self):
        return self.card

    def _cleanup_editor_resources(self):
        from ui.canvas.retro_effects import resume_animations

        resume_animations(self)
        try:
            self._recovery_timer.stop()
        except Exception:
            pass
        try:
            self._stop_watch()
        except Exception:
            pass
        try:
            self._stop_pdf_threads(shutdown=True)
        except Exception:
            pass
        try:
            self._stop_ocr_thread()
        except Exception:
            pass
        self._pdf_pages = []
        if hasattr(self, "canvas") and self.canvas is not None:
            try:
                self.canvas._pages = []
                self.canvas._px = None
                if hasattr(self.canvas, "_spx_cache"):
                    self.canvas._spx_cache.clear()
            except Exception:
                pass
        try:
            from PyQt5.QtGui import QPixmapCache
            QPixmapCache.clear()
            import fitz
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass
        import gc
        gc.collect()
        log_memory("Card Editor Exit (Memory Reclaimed)")

    @trace_perf
    def closeEvent(self, e):
        if getattr(self, "_card_saved_once", False):
            self.accept()
            e.accept()
            return

        if not self._confirm_recovery_close():
            e.ignore()
            return
        self._cleanup_editor_resources()
        super().closeEvent(e)

    def reject(self):
        if getattr(self, "_card_saved_once", False):
            self.accept()
            return

        if not self._confirm_recovery_close():
            return
        self._cleanup_editor_resources()
        super().reject()

    def accept(self):
        from perf_utils import invalidate_deck_stats

        invalidate_deck_stats()
        self._recovery_accepted = True
        self._cleanup_editor_resources()
        super().accept()


# ═══════════════════════════════════════════════════════════════════════════════
