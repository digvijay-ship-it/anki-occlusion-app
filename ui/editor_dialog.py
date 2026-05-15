import os
import sys
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
from PyQt5.QtGui import QFont, QIcon, QPixmap, QDesktopServices
from sm2_engine import sm2_init
from data_manager import new_box_id
from services import recovery_manager
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
from perf_utils import get_pdf_page_count
from storage_paths import (
    build_archive_asset_path,
    find_deck_segments,
    has_mission_archive,
    import_asset_into_archive,
    resolve_asset_path,
)

from editor_ui import OcclusionCanvas, _ZoomableScrollArea, ToolBar, MaskPanel
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
    ):
        super().__init__(parent)
        self._initial_img_y = initial_img_y
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        self.card = card or {}
        self._recovery_initial_card = dict(card or {})
        self._recovery_mode = "edit" if card else "add"
        self._recovery_draft_id = recovery_manager.new_draft_id()
        self._recovery_draft_cleared = False
        self._recovery_accepted = False
        self._recovery_autosave_ready = False
        self._recovery_dirty = False
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
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._zoom_fit)
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(2000)
        self._recovery_timer.timeout.connect(self._write_recovery_draft)
        self._setup_ui()
        if card:
            self._load_card(card)
        self._setup_recovery_autosave()

    def exec_(self):
        print("[DEBUG][editor_mode] enter_fullscreen_default")
        self.showFullScreen()
        return super().exec_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._schedule_zoom_fit()

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
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#1a5ca8;min-height:32px;}"
            "QPushButton:hover{background:#D0E4FF;}"
        )
        btn_ungrp.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#888;min-height:32px;}"
            "QPushButton:hover{background:#EEE;}"
        )
        btn_grp.clicked.connect(lambda: self.canvas.group_selected())
        btn_ungrp.clicked.connect(lambda: self.canvas.ungroup_selected())

        self.btn_open_ext = _tbtn("📂 Open PDF", "Open in system PDF reader")
        self.btn_open_ext.clicked.connect(self._open_in_reader)
        self.btn_open_ext.setVisible(False)

        self.btn_annotate_beta = _tbtn(
            "🖊 In-App Annotate (Beta)", "Open in-app PDF annotation editor  Ctrl+T"
        )
        self.btn_annotate_beta.clicked.connect(self._open_annotation_beta)
        self.btn_annotate_beta.setVisible(False)

        self.btn_relink = _tbtn(
            "🔄 Relink PDF", "Replace the PDF source file — keeps all existing masks"
        )
        self.btn_relink.setEnabled(PDF_SUPPORT)
        self.btn_relink.clicked.connect(self._relink_pdf)
        self.btn_relink.setVisible(False)
        self.btn_relink.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#8B4513;min-height:32px;}"
            "QPushButton:hover{background:#FFE4C4;}"
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
            self.lbl_sync,
        ]:
            tl.addWidget(w)
        tl.addStretch()

        btn_cancel = _tbtn("Cancel", "Discard changes")
        btn_save = QPushButton("💾  Save Card")
        btn_save.setFixedHeight(34)
        btn_save.setToolTip("Save  Ctrl+S")
        btn_save.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border:1px solid #3A9040;"
            "border-radius:4px;padding:4px 16px;font-size:13px;min-height:32px;}"
            "QPushButton:hover{background:#3A9040;}"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        tl.addWidget(btn_cancel)
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
        pb.addWidget(self.btn_prev_page)
        pb.addWidget(self.btn_next_page)
        pb.addSpacing(6)
        pb.addWidget(self.inp_page_jump)
        pb.addWidget(self.lbl_page_total)
        pb.addSpacing(12)
        pb.addWidget(self.lbl_pg)
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
        self._sc_prev_page = QShortcut(Qt.Key_Left, self)
        self._sc_prev_page.setContext(Qt.WidgetWithChildrenShortcut)
        self._sc_prev_page.setAutoRepeat(False)
        self._sc_prev_page.activated.connect(self._go_prev_page)
        self._sc_next_page = QShortcut(Qt.Key_Right, self)
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
        self.inp_notes = QTextEdit()
        self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(64)
        cib.addRow("Title:", self.inp_title)
        cib.addRow("Tags:", self.inp_tags)
        cib.addRow("Notes:", self.inp_notes)
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
            "Drag ↻=rotate  Del=delete  Ctrl+Z/Y=undo/redo  Ctrl+S=save  |  "
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
            lambda _boxes: self._write_recovery_checkpoint("boxes")
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
                "notes": self.inp_notes.toPlainText(),
                "boxes": boxes,
                "created": card.get("created", datetime.now().isoformat()),
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
        saved = recovery_manager.save_editor_draft(payload)
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

    def _pdf_quality_debug(self, action: str, **data):
        parts = " ".join(f"{key}={value}" for key, value in data.items())
        print(f"[DEBUG][pdf_quality][editor] {action} {parts}".rstrip())

    def _set_pdf_page_ui(self, current_zero: int):
        self._pdf_viewer.set_page_ui(current_zero)
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

    def _update_pdf_nav_ui(self, *_):
        self._pdf_viewer.refresh_page_ui()
        self._ui_page_zero = self._pdf_viewer._ui_page_zero

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
        if key == Qt.Key_F11:
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
        elif mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.canvas.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_Y:
            self.canvas.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_S:
            self._save()
        elif mods & Qt.ControlModifier and key == Qt.Key_E:
            self._open_in_reader()
        elif mods & Qt.ControlModifier and key == Qt.Key_L:
            self._reveal_current_pdf_in_folder()
        elif mods & Qt.ControlModifier and key == Qt.Key_T:
            self._open_annotation_beta()
        elif mods & Qt.ControlModifier and key == Qt.Key_V:
            self._paste_image()
        elif key == Qt.Key_L and not mods and not e.isAutoRepeat():
            self._copy_current_pdf_file_to_clipboard()
        elif key == Qt.Key_Left and not mods and not e.isAutoRepeat():
            self._go_prev_page()
        elif key == Qt.Key_Right and not mods and not e.isAutoRepeat():
            self._go_next_page()
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

    # ── image / paste ─────────────────────────────────────────────────────────

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
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
        self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        self._update_pdf_nav_ui()
        if not self.inp_title.text():
            self.inp_title.setText(os.path.splitext(os.path.basename(path))[0])
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
        self.card["image_path"] = stored_path
        self.card.pop("pdf_path", None)
        self._pdf_pages = []
        self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False)
        self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        self._update_pdf_nav_ui()
        if not self.inp_title.text():
            self.inp_title.setText("Pasted Image")
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
        self._show_pdf_loading(True)
        self._load_pdf_direct(abs_path)
        self._write_recovery_checkpoint("pdf_loaded")

    def _stop_pdf_threads(self):
        """Stop any running PDF render thread."""
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(500)
        self._pdf_loader_thread = None
        if self._pdf_ondemand_thread and self._pdf_ondemand_thread.isRunning():
            self._pdf_ondemand_thread.stop()
            self._pdf_ondemand_thread.quit()
            self._pdf_ondemand_thread.wait(500)
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
        profile_reset = ensure_pdf_cache_profile(path, self._pdf_render_zoom)
        self._pdf_quality_debug(
            "profile",
            pages=total_pages,
            zoom=self._pdf_render_zoom,
            reset_cache=profile_reset,
        )
        skeleton = load_pdf_skeleton(path, zoom=self._pdf_render_zoom)
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
            print(f"[DEBUG][editor_ondemand] skeleton_ready pages={total_pages}")
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
            f"[DEBUG][editor_ondemand] skeleton_fallback_render path={os.path.basename(path)}"
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
        self.canvas._current_pdf_path = path
        self._editor_ondemand_path = path
        self._editor_ondemand_total = len(pages or [])
        self._editor_visible_debug_seen_pages = set()
        self._editor_canvas_real_pages = set(int(pn) for pn in (real_pages or set()))
        self._editor_render_inflight_pages.clear()
        self._editor_pending_visible_request = None
        existing_boxes = self.canvas.get_boxes()
        self.canvas.load_pages(pages)
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
        if boxes_to_restore:
            if self._pending_boxes_need_pdf_adapt:
                source_zoom = self.card.get("_pdf_box_render_zoom", PDF_LEGACY_BOX_ZOOM)
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
            self.canvas.set_boxes(boxes_to_restore)
            self.mask_panel._refresh(boxes_to_restore)
        self._pending_boxes = []
        self.btn_open_ext.setVisible(True)
        self.btn_annotate_beta.setVisible(True)

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

    def _on_editor_visible_pages_changed(self, first, last):
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
        if entered_pages:
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
        self._inject_editor_cached_visible_pages(path, visible_pages)
        needed = [pn for pn in visible_pages if PAGE_CACHE.get(path, pn) is None]
        if not needed:
            return
        if self._pdf_ondemand_thread and self._pdf_ondemand_thread.isRunning():
            self._editor_pending_visible_request = (path, list(needed))
            return
        self._start_editor_visible_page_request(path, needed)

    def _inject_editor_cached_visible_pages(self, path, visible_pages):
        visible_pages = [int(pn) for pn in (visible_pages or [])]
        real_pages = set(self.__dict__.get("_editor_canvas_real_pages", set()) or set())
        inflight = set(
            self.__dict__.get("_editor_render_inflight_pages", set()) or set()
        )
        injected = []
        for pn in visible_pages:
            if pn in real_pages or pn in inflight:
                continue
            cached = PAGE_CACHE.get(path, pn)
            if cached is None or cached.isNull():
                continue
            print(f"[DEBUG][editor_lazy] ⚡ p.{pn + 1}")
            self.canvas.inject_page(pn, cached)
            self.__dict__.setdefault("_editor_canvas_real_pages", set()).add(pn)
            print(f"[DEBUG][editor_inject] p.{pn + 1} injected=yes kind=visible_cache")
            injected.append(pn)
        if injected:
            print(
                "[DEBUG][editor_visible_cache] hydrate "
                + ", ".join(f"p.{pn + 1}" for pn in injected)
            )
            self._update_pdf_nav_ui()

    def _start_editor_visible_page_request(self, path, needed):
        needed = sorted({int(pn) for pn in (needed or [])})
        self._editor_pending_visible_request = None
        if needed:
            print(
                "[DEBUG][editor_ondemand] render_request "
                + ", ".join(f"p.{pn + 1}" for pn in needed)
            )
        self.__dict__.setdefault("_editor_render_inflight_pages", set()).update(needed)
        self._pdf_ondemand_thread = PdfOnDemandThread(
            path, needed, zoom=self._pdf_render_zoom, parent=self
        )
        self._pdf_ondemand_thread.page_ready.connect(self._on_editor_page_ready)
        self._pdf_ondemand_thread.batch_done.connect(
            self._on_editor_visible_pages_batch_done
        )
        self._pdf_ondemand_thread.error.connect(lambda err: None)
        self._pdf_ondemand_thread.start()

    def _on_editor_visible_pages_batch_done(self, rendered):
        pending = self._editor_pending_visible_request
        self._editor_pending_visible_request = None
        if pending and pending[0] == getattr(self, "_editor_ondemand_path", None):
            path, needed = pending
            fresh_needed = [
                pn
                for pn in needed
                if pn
                not in set(
                    self.__dict__.get("_editor_canvas_real_pages", set()) or set()
                )
                and PAGE_CACHE.get(path, pn) is None
            ]
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
            print(
                f"[DEBUG][editor_inject] p.{page_num + 1} injected=no reason=stale_path"
            )
            return
        if not getattr(self.canvas, "_pages", None):
            print(
                f"[DEBUG][editor_inject] p.{page_num + 1} injected=no reason=canvas_empty"
            )
            return
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
        cached = PAGE_CACHE.get(path, page_num)
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

    def _on_pdf_done(self, pages: list, err):
        """Called by PdfLoaderThread when all pages are rendered."""
        self._show_pdf_loading(False)
        path = self._resolve_source_path(self.card.get("pdf_path", ""))
        if not pages:
            QMessageBox.warning(self, "PDF Error", err or "Could not render PDF.")
            return
        self._finish_pdf_load(path, pages, real_pages=set(range(len(pages))))
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
        self.inp_title.setText(card.get("title", ""))
        self.inp_tags.setText(", ".join(card.get("tags", [])))
        self.inp_notes.setPlainText(card.get("notes", ""))

        current_boxes = card.get("boxes", [])
        image_path = self._resolve_source_path(card.get("image_path", ""))
        pdf_path = self._resolve_source_path(card.get("pdf_path", ""))

        if card.get("image_path") and os.path.exists(image_path):
            px = QPixmap(image_path)
            if px and not px.isNull():
                self.canvas.load_pixmap(px)
            if current_boxes:
                self.canvas.set_boxes(current_boxes)
                self.mask_panel._refresh(current_boxes)
            self._schedule_initial_view_restore("image_load")
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(pdf_path):
            self.card["pdf_path"] = card.get("pdf_path", "")
            self._auto_subdeck_name = os.path.splitext(os.path.basename(pdf_path))[0]
            self._pending_boxes = current_boxes
            self._pending_boxes_need_pdf_adapt = True
            self.btn_relink.setVisible(True)
            self._show_pdf_loading(True)
            self._load_pdf_direct(pdf_path)
        elif card.get("pdf_path") and not os.path.exists(pdf_path):
            self.btn_relink.setVisible(True)
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
        changed = get_changed_pages(path)
        if changed is None:
            PAGE_CACHE.invalidate_pdf(path)
        else:
            PAGE_CACHE.invalidate_pages(path, changed)

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
        if not changed_pages:
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
                print(f"[DEBUG][editor_lazy] ⚡ p.{page_num + 1}")
                self.canvas.inject_page(page_num, px)
                self.__dict__.setdefault("_editor_canvas_real_pages", set()).add(
                    page_num
                )
                print(
                    f"[DEBUG][editor_inject] p.{page_num + 1} injected=yes kind=annotation_refresh"
                )
        self._update_pdf_nav_ui()
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
        self._pending_boxes_need_pdf_adapt = False

        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("🔄 Relinking…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;"
        )

        self._show_pdf_loading(True)
        self._load_pdf_direct(resolved_new_path)
        self._write_recovery_checkpoint("pdf_relinked")

    # ── save / close ──────────────────────────────────────────────────────────

    def _save(self):
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
                "notes": self.inp_notes.toPlainText(),
                "boxes": merged,
                "created": self.card.get("created", datetime.now().isoformat()),
                "reviews": self.card.get("reviews", 0),
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
        self._write_recovery_checkpoint("save_card")
        self.accept()

    def get_card(self):
        return self.card

    def closeEvent(self, e):
        from cache_manager import MASK_REGISTRY

        if not self._confirm_recovery_close():
            e.ignore()
            return
        self._recovery_timer.stop()
        MASK_REGISTRY.unregister(self.canvas)
        self._stop_watch()
        self._stop_pdf_threads()
        super().closeEvent(e)

    def reject(self):
        from cache_manager import MASK_REGISTRY

        if not self._confirm_recovery_close():
            return
        self._recovery_timer.stop()
        MASK_REGISTRY.unregister(self.canvas)
        self._stop_watch()
        self._stop_pdf_threads()
        super().reject()

    def accept(self):
        from cache_manager import MASK_REGISTRY
        from perf_utils import invalidate_deck_stats

        invalidate_deck_stats()
        self._recovery_accepted = True
        self._recovery_timer.stop()
        MASK_REGISTRY.unregister(self.canvas)
        self._stop_watch()
        super().accept()


# ═══════════════════════════════════════════════════════════════════════════════
