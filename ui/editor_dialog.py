import os
import sys
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QListWidget, QFrame, QScrollArea, QMessageBox, QFileDialog,
    QFormLayout, QTextEdit, QSizePolicy, QDialog, QApplication, QSplitter
)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QFileSystemWatcher, QUrl
from PyQt5.QtGui import QFont, QIcon, QPixmap, QDesktopServices
from sm2_engine import sm2_init
from data_manager import new_box_id
from pdf_engine import PDF_SUPPORT, PAGE_CACHE, PdfLoaderThread

try:
    import fitz
except ImportError:
    pass

from editor_ui import OcclusionCanvas, _ZoomableScrollArea, ToolBar, MaskPanel

C_BG      = "#1E1E2E"
C_SURFACE = "#2A2A3E"
C_CARD    = "#313145"
C_ACCENT  = "#7C6AF7"
C_GREEN   = "#50FA7B"
C_RED     = "#FF5555"
C_YELLOW  = "#F1FA8C"
C_TEXT    = "#CDD6F4"
C_SUBTEXT = "#A6ADC8"
C_BORDER  = "#45475A"

#  CARD EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class CardEditorDialog(QDialog):
    def __init__(self, parent=None, card=None, data=None, deck=None,
             initial_scroll=0, initial_page=None, initial_img_y=None):
        super().__init__(parent)
        self._initial_img_y = initial_img_y
        self.setWindowTitle("Occlusion Card Editor")
        self.setMinimumSize(1100, 700)
        self.card               = card or {}
        self._initial_scroll    = initial_scroll
        self._initial_page      = initial_page
        self._pdf_pages         = []
        self._cur_page          = 0
        self._data              = data
        self._deck              = deck
        self._auto_subdeck_name = None
        self._watcher           = QFileSystemWatcher()
        self._watched_path      = None
        self._reload_timer      = QTimer()
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._reload_pdf)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._pdf_loader_thread = None
        self._pdf_total_pages   = 0
        self._pending_boxes     = []
        self._fit_timer         = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._zoom_fit)
        self._setup_ui()
        if card: self._load_card(card)

    def exec_(self):
        self.showMaximized()
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
        self._hf = p.get("header_font", "'Segoe UI'").split(',')[0].strip("'")
        self._bf = p.get("body_font", "'Segoe UI'").split(',')[0].strip("'")
        
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

        L = QVBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        # ── top bar ───────────────────────────────────────────────────────────
        top_bar = QFrame(); top_bar.setFixedHeight(46)
        top_bar.setStyleSheet(
            f"QFrame{{background:{p.get('C_SURFACE', '#F0F0F0')};border-bottom:1px solid {p.get('C_BORDER', '#C8C8C8')};border-radius:0;}}"
            f"QPushButton{{background:transparent;border:none;border-radius:4px;"
            f"padding:4px 10px;font-size:13px;color:{p.get('C_TEXT', '#333')};min-height:32px;font-family:{self._hf};}}"
            f"QPushButton:hover{{background:{p.get('C_CARD', '#DDD')};}}"
            f"QPushButton:pressed{{background:{p.get('C_BORDER', '#CCC')};}}"
            f"QPushButton:checked{{background:{p.get('C_ACCENT', '#C8D8EE')};color:{p.get('C_BG', '#1a5ca8')};}}")
        tl = QHBoxLayout(top_bar); tl.setContentsMargins(6,4,6,4); tl.setSpacing(2)

        def _tbtn(label, tip, checkable=False, w=None):
            b = QPushButton(label); b.setToolTip(tip)
            b.setCheckable(checkable); b.setFixedHeight(34)
            if w: b.setFixedWidth(w)
            return b

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.VLine)
            s.setStyleSheet(f"QFrame{{background:{p.get('C_BORDER', '#C0C0C0')};margin:5px 4px;}}")
            s.setFixedWidth(1); return s

        btn_img   = _tbtn("🖼 Image",     "Load Image")
        btn_paste = _tbtn("📋 Paste",     "Paste image from clipboard  Ctrl+V")
        btn_pdf   = _tbtn("📄 PDF",       "Load PDF")
        btn_pdf.setEnabled(PDF_SUPPORT)
        if not PDF_SUPPORT: btn_pdf.setToolTip("pip install pymupdf")
        btn_img.clicked.connect(self._load_image)
        btn_paste.clicked.connect(self._paste_image)
        btn_pdf.clicked.connect(self._load_pdf)

        btn_undo = _tbtn("↩","Undo  Ctrl+Z", w=36)
        btn_redo = _tbtn("↪","Redo  Ctrl+Y", w=36)
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        btn_redo.clicked.connect(lambda: self.canvas.redo())

        btn_zi = _tbtn("🔍+","Zoom In",  w=46)
        btn_zo = _tbtn("🔍−","Zoom Out", w=46)
        btn_zf = _tbtn("⊡",  "Zoom Fit", w=32)
        btn_del   = _tbtn("🗑",    "Delete selected  Del", w=32)
        btn_clear = _tbtn("✕ All", "Clear all masks")
        btn_grp   = _tbtn("⛓ Group",   "Group selected masks  [G]")
        btn_ungrp = _tbtn("⛓ Ungroup", "Ungroup  [Shift+G]")
        btn_grp.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#1a5ca8;min-height:32px;}"
            "QPushButton:hover{background:#D0E4FF;}")
        btn_ungrp.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#888;min-height:32px;}"
            "QPushButton:hover{background:#EEE;}")
        btn_grp.clicked.connect(lambda: self.canvas.group_selected())
        btn_ungrp.clicked.connect(lambda: self.canvas.ungroup_selected())

        self.btn_open_ext = _tbtn("📂 Open PDF", "Open in system PDF reader")
        self.btn_open_ext.clicked.connect(self._open_in_reader)
        self.btn_open_ext.setVisible(False)

        self.btn_relink = _tbtn("🔄 Relink PDF", "Replace the PDF source file — keeps all existing masks")
        self.btn_relink.setEnabled(PDF_SUPPORT)
        self.btn_relink.clicked.connect(self._relink_pdf)
        self.btn_relink.setVisible(False)
        self.btn_relink.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:4px;"
            "padding:4px 10px;font-size:13px;color:#8B4513;min-height:32px;}"
            "QPushButton:hover{background:#FFE4C4;}")

        self.lbl_sync = QLabel("")
        self.lbl_sync.setStyleSheet(f"background:transparent;font-size:11px;color:{p.get('C_SUBTEXT', '#666')};font-family:{self._bf};")
        self.lbl_sync.setVisible(False)

        for w in [btn_img, btn_paste, btn_pdf, _sep(),
                  btn_undo, btn_redo, _sep(),
                  btn_zi, btn_zo, btn_zf, _sep(),
                  btn_del, btn_clear, _sep(),
                  btn_grp, btn_ungrp, _sep(),
                  self.btn_open_ext, self.btn_relink, self.lbl_sync]:
            tl.addWidget(w)
        tl.addStretch()

        btn_cancel = _tbtn("Cancel", "Discard changes")
        btn_save   = QPushButton("💾  Save Card"); btn_save.setFixedHeight(34)
        btn_save.setToolTip("Save  Ctrl+S")
        btn_save.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;border:1px solid #3A9040;"
            "border-radius:4px;padding:4px 16px;font-size:13px;min-height:32px;}"
            "QPushButton:hover{background:#3A9040;}")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        tl.addWidget(btn_cancel); tl.addSpacing(4); tl.addWidget(btn_save)
        L.addWidget(top_bar)

        # ── pdf bar ───────────────────────────────────────────────────────────
        self.pdf_bar = QWidget()
        self.pdf_bar.setStyleSheet(f"background:{p.get('C_SURFACE', '#E8E8E8')};border-bottom:1px solid {p.get('C_BORDER', '#CCC')};")
        pb = QHBoxLayout(self.pdf_bar); pb.setContentsMargins(10,2,10,2)
        self.lbl_pg = QLabel("")
        self.lbl_pg.setStyleSheet(f"color:{p.get('C_SUBTEXT', '#555')};font-size:11px;background:transparent;font-family:{self._bf};")
        pb.addWidget(self.lbl_pg); pb.addStretch()
        self.pdf_bar.setFixedHeight(22); self.pdf_bar.hide()
        L.addWidget(self.pdf_bar)

        # ── main row ──────────────────────────────────────────────────────────
        main_row = QHBoxLayout(); main_row.setContentsMargins(0,0,0,0); main_row.setSpacing(0)
        self.toolbar = ToolBar(); main_row.addWidget(self.toolbar)

        sc = _ZoomableScrollArea(); sc.setWidgetResizable(False)
        sc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc.setStyleSheet(f"QScrollArea{{background:{p.get('C_BG', '#787878')};border:none;}}")
        self.canvas = OcclusionCanvas()
        self.canvas.setStyleSheet("background:transparent;")
        sc.setWidget(self.canvas); sc.set_canvas(self.canvas)
        self.toolbar.tool_changed.connect(self.canvas.set_tool)
        main_row.addWidget(sc, stretch=1)
        self._sc = sc

        # ── right panel ───────────────────────────────────────────────────────
        right_panel = QWidget(); right_panel.setFixedWidth(240)
        right_panel.setStyleSheet(f"QWidget{{background:{p.get('C_SURFACE', '#F5F5F5')};}}QFrame{{background:{p.get('C_SURFACE', '#F5F5F5')};border:none;}}")
        rp = QVBoxLayout(right_panel); rp.setContentsMargins(0,0,0,0); rp.setSpacing(0)

        ml_hdr = QFrame(); ml_hdr.setFixedHeight(28)
        ml_hdr.setStyleSheet(f"QFrame{{background:{p.get('C_CARD', '#E0E0E0')};border-bottom:1px solid {p.get('C_BORDER', '#CCC')};}}"
                             f"QLabel{{color:{p.get('C_TEXT', '#444')};font-size:11px;font-weight:bold;background:transparent;font-family:{self._hf};}}")
        ml_hl = QHBoxLayout(ml_hdr); ml_hl.setContentsMargins(8,0,8,0)
        ml_hl.addWidget(QLabel("Masks")); ml_hl.addStretch()
        rp.addWidget(ml_hdr)

        self.mask_panel = MaskPanel(self.canvas); rp.addWidget(self.mask_panel, stretch=1)
        self.mask_panel.list_w.currentRowChanged.connect(self._center_on_mask)

        ci_hdr = QFrame(); ci_hdr.setFixedHeight(28)
        ci_hdr.setStyleSheet(f"QFrame{{background:{p.get('C_CARD', '#E0E0E0')};border-top:1px solid {p.get('C_BORDER', '#CCC')};"
                             f"border-bottom:1px solid {p.get('C_BORDER', '#CCC')};}}"
                             f"QLabel{{color:{p.get('C_TEXT', '#444')};font-size:11px;font-weight:bold;background:transparent;font-family:{self._hf};}}")
        ci_hl = QHBoxLayout(ci_hdr); ci_hl.setContentsMargins(8,0,8,0)
        ci_hl.addWidget(QLabel("Card Info")); rp.addWidget(ci_hdr)

        ci_body = QWidget(); ci_body.setStyleSheet(f"QWidget{{background:{p.get('C_SURFACE', '#F5F5F5')};}}")
        cib = QFormLayout(ci_body); cib.setContentsMargins(8,8,8,8); cib.setSpacing(6)
        self.inp_title = QLineEdit(); self.inp_title.setPlaceholderText("Card title…")
        self.inp_tags  = QLineEdit(); self.inp_tags.setPlaceholderText("tag1, tag2…")
        self.inp_notes = QTextEdit(); self.inp_notes.setPlaceholderText("Hints / notes…")
        self.inp_notes.setMaximumHeight(64)
        cib.addRow("Title:", self.inp_title)
        cib.addRow("Tags:",  self.inp_tags)
        cib.addRow("Notes:", self.inp_notes)
        rp.addWidget(ci_body)
        main_row.addWidget(right_panel)

        body_w = QWidget(); body_w.setLayout(main_row)
        L.addWidget(body_w, stretch=1)

        hint_bar = QFrame(); hint_bar.setFixedHeight(20)
        hint_bar.setStyleSheet(
            "QFrame{background:#E8E8E8;border-top:1px solid #CCC;border-radius:0;}"
            "QLabel{background:transparent;color:#777;font-size:10px;}")
        hl = QHBoxLayout(hint_bar); hl.setContentsMargins(10,0,10,0)
        hl.addWidget(QLabel(
            "V=Select  R=Rect  E=Ellipse  T=Label  |  "
            "Hold Alt=temp select  Alt+Click=multi-select  |  "
            "G=group  Shift+G=ungroup  |  "
            "Drag ↻=rotate  Del=delete  Ctrl+Z/Y=undo/redo  |  "
            "Middle-click drag or H = Pan  (tablet/stylus)"))
        hl.addStretch(); L.addWidget(hint_bar)

        btn_zi.clicked.connect(lambda: self.canvas.zoom_in())
        btn_zo.clicked.connect(lambda: self.canvas.zoom_out())
        btn_zf.clicked.connect(self._zoom_fit)
        btn_del.clicked.connect(lambda: self.canvas.delete_selected_boxes())
        btn_clear.clicked.connect(self.canvas.clear_all)

    def _zoom_fit(self):
        vp = self._sc.viewport()
        self.canvas.zoom_fit_width(vp.width())

    def _schedule_zoom_fit(self, delay_ms=120):
        if getattr(self, "canvas", None) and self.canvas._pages:
            self._fit_timer.start(delay_ms)

    def _center_on_mask(self, row):
        if not (0 <= row < len(self.canvas._boxes)): return
        r    = self.canvas._sr(self.canvas._boxes[row]["rect"])
        vbar = self._sc.verticalScrollBar()
        hbar = self._sc.horizontalScrollBar()
        hbar.setValue(int(max(0, r.center().x() - self._sc.viewport().width()  // 2)))
        vbar.setValue(int(max(0, r.center().y() - self._sc.viewport().height() // 2)))

    def keyPressEvent(self, e):
        key = e.key(); mods = e.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:  self.canvas.undo()
        elif mods & Qt.ControlModifier and key == Qt.Key_X: self.canvas.redo()
        elif mods & Qt.ControlModifier and key == Qt.Key_S: self._save()
        elif mods & Qt.ControlModifier and key == Qt.Key_V: self._paste_image()
        elif key == Qt.Key_V: self.toolbar.select_tool("select")
        elif key == Qt.Key_R: self.toolbar.select_tool("rect")
        elif key == Qt.Key_E: self.toolbar.select_tool("ellipse")
        elif key == Qt.Key_T: self.toolbar.select_tool("text")
        else: super().keyPressEvent(e)

    # ── image / paste ─────────────────────────────────────────────────────────

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path: return
        px = QPixmap(path)
        if px.isNull(): QMessageBox.warning(self, "Error", "Could not load image."); return
        self.card["image_path"] = path; self.card.pop("pdf_path", None)
        self._pdf_pages = []; self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False); self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        if not self.inp_title.text():
            self.inp_title.setText(os.path.splitext(os.path.basename(path))[0])

    def _paste_image(self):
        clipboard = QApplication.clipboard()
        px = clipboard.pixmap()
        if px.isNull():
            img = clipboard.image()
            if not img.isNull(): px = QPixmap.fromImage(img)
        if px.isNull():
            QMessageBox.information(self, "Nothing to paste",
                "Clipboard mein koi image nahi hai."); return
        import tempfile as _tmp
        fd, tmp_path = _tmp.mkstemp(suffix=".png", prefix="anki_paste_",
                                    dir=os.path.expanduser("~"))
        os.close(fd)
        if not px.save(tmp_path, "PNG"):
            QMessageBox.warning(self, "Error", "Could not save pasted image."); return
        self.card["image_path"] = tmp_path; self.card.pop("pdf_path", None)
        self._pdf_pages = []; self.pdf_bar.hide()
        self.btn_open_ext.setVisible(False); self.lbl_sync.setVisible(False)
        self._stop_watch()
        self.canvas.load_pixmap(px)
        if not self.inp_title.text(): self.inp_title.setText("Pasted Image")

    # ── PDF loading ───────────────────────────────────────────────────────────

    def _load_pdf(self):
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf"); return
        path, _ = QFileDialog.getOpenFileName(self, "Load PDF", "", "PDF (*.pdf)")
        if not path: return
        self.card["pdf_path"] = path; self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
        self._pending_boxes = []
        self.btn_relink.setVisible(True)
        self._show_pdf_loading(True)
        self._load_pdf_direct(path)

    def _stop_pdf_threads(self):
        """Stop any running PDF render thread."""
        if self._pdf_loader_thread and self._pdf_loader_thread.isRunning():
            self._pdf_loader_thread.stop()
            self._pdf_loader_thread.quit()
            self._pdf_loader_thread.wait(500)
        self._pdf_loader_thread = None

    def _load_pdf_direct(self, path: str):
        """
        Load a PDF into the editor.

        Strategy (fast path first):
          1. Full disk/RAM cache hit  → load_pages() instantly, zero rendering.
          2. Partial cache hit        → load cached pages instantly, render missing
                                        ones in background via PdfLoaderThread.
          3. No cache                 → render all pages via PdfLoaderThread,
                                        show progress in lbl_sync.

        No skeleton, no lazy loading, no on-demand per-scroll rendering.
        The disk cache (LRUPageCache + DiskCombinedCache) makes repeat opens instant.
        """
        self._stop_pdf_threads()
        self._watch_pdf(path)
        self._show_pdf_loading(False)

        # ── Count pages ───────────────────────────────────────────────────────
        try:
            _doc = fitz.open(path)
            total_pages = len(_doc)
            _doc.close()
        except Exception as ex:
            print(f"[DEBUG][load] ❌ cannot open PDF: {ex}")
            QMessageBox.warning(self, "PDF Error", f"Could not open PDF:\n{ex}")
            return

        if total_pages <= 0:
            print(f"[DEBUG][load] ❌ zero pages: {path}")
            return

        self._pdf_total_pages = total_pages

        # ── Full cache hit → instant ──────────────────────────────────────────
        cached_pages = [PAGE_CACHE.get(path, i) for i in range(total_pages)]
        if all(p is not None and not p.isNull() for p in cached_pages):
            print(f"[DEBUG][load] ⚡ full cache hit — {total_pages} pages")
            self._finish_pdf_load(path, cached_pages)
            self.lbl_sync.setText("⚡ PDF ready from cache")
            self.lbl_sync.setStyleSheet(
                f"color:{self._p.get('C_GREEN', C_GREEN)};font-size:11px;background:transparent;font-weight:bold;")
            self.lbl_sync.setVisible(True)
            return

        # ── Cache miss (full or partial) → render in background ───────────────
        cached_count = sum(1 for p in cached_pages if p is not None and not p.isNull())
        print(f"[DEBUG][load] 🔄 rendering — {cached_count}/{total_pages} already cached")
        self.lbl_sync.setText(f"⏳ Rendering {total_pages - cached_count} pages…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;")
        self.lbl_sync.setVisible(True)
        self._show_pdf_loading(True)

        self._pdf_loader_thread = PdfLoaderThread(path, parent=self)
        self._pdf_loader_thread.done.connect(self._on_pdf_done)
        self._pdf_loader_thread.start()

    def _finish_pdf_load(self, path: str, pages: list):
        """
        Common finalisation after pages are ready (cache hit or render done).
        Loads pages into canvas, restores boxes, sets scroll position.
        """
        self.canvas._current_pdf_path = path
        existing_boxes = self.canvas.get_boxes()
        self.canvas.load_pages(pages)
        self._after_load_scroll()
        self._schedule_zoom_fit(80)

        n = len(pages)
        self.lbl_pg.setText(
            f"📄  {os.path.basename(path)}  —  {n} page{'s' if n != 1 else ''}")
        self.pdf_bar.show()

        if not self.inp_title.text():
            self.inp_title.setText(self._auto_subdeck_name or "")

        boxes_to_restore = (
            self._pending_boxes
            or existing_boxes
            or list(self.card.get("boxes", []))
        )
        if boxes_to_restore:
            self.canvas.set_boxes(boxes_to_restore)
            self.mask_panel._refresh(boxes_to_restore)
        self._pending_boxes = []

    def _after_load_scroll(self):
        """Scroll to exact image-space position after canvas is ready."""
        if self._initial_img_y is not None:
            img_y    = self._initial_img_y
            editor_scale = self.canvas._scale
            scroll_y = int(img_y * editor_scale)
            sv = scroll_y
            QTimer.singleShot(30, lambda:
                self._sc.verticalScrollBar().setValue(sv))
            self._initial_img_y = None
        elif self._initial_page is not None and self._initial_page >= 0:
            pg = self._initial_page
            sc = self._sc
            QTimer.singleShot(30, lambda: self.canvas.scroll_to_page(pg, sc))
            self._initial_page = None
        elif self._initial_scroll > 0:
            sv = self._initial_scroll
            QTimer.singleShot(30, lambda:
                self._sc.verticalScrollBar().setValue(sv))
            self._initial_scroll = 0

    def _current_visible_page(self) -> int:
        scroll_pos = self._sc.verticalScrollBar().value()
        return self.canvas.get_current_page(scroll_pos)

    def _on_pdf_done(self, pages: list, err):
        """Called by PdfLoaderThread when all pages are rendered."""
        self._show_pdf_loading(False)
        path = self.card.get("pdf_path", "")
        if not pages:
            QMessageBox.warning(self, "PDF Error", err or "Could not render PDF.")
            return
        self._finish_pdf_load(path, pages)
        self.lbl_sync.setText(f"✅ Rendered {len(pages)} pages")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_GREEN', C_GREEN)};font-size:11px;background:transparent;font-weight:bold;")
        self.lbl_sync.setVisible(True)

    def _show_pdf_loading(self, loading: bool):
        if loading:
            self.setWindowTitle("Occlusion Card Editor  ⏳ Loading PDF…")
            self.lbl_sync.setVisible(True); self.lbl_sync.setText("⏳ Loading PDF…")
            self.lbl_sync.setStyleSheet(
                f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;")
        else:
            self.setWindowTitle("Occlusion Card Editor")

    # ── card load ─────────────────────────────────────────────────────────────

    def _load_card(self, card):
        """File: editor_ui.py -> Class: CardEditorDialog"""
        self.inp_title.setText(card.get("title",""))
        self.inp_tags.setText(", ".join(card.get("tags",[])))
        self.inp_notes.setPlainText(card.get("notes",""))
        
        current_boxes = card.get("boxes", [])

        if card.get("image_path") and os.path.exists(card["image_path"]):
            px = QPixmap(card["image_path"])
            if px and not px.isNull(): self.canvas.load_pixmap(px)
            if current_boxes:
                self.canvas.set_boxes(current_boxes)
                self.mask_panel._refresh(current_boxes)
        elif card.get("pdf_path") and PDF_SUPPORT and os.path.exists(card["pdf_path"]):
            path = card["pdf_path"]
            self.card["pdf_path"] = path
            self._auto_subdeck_name = os.path.splitext(os.path.basename(path))[0]
            self._pending_boxes = current_boxes
            self.btn_relink.setVisible(True)
            self._show_pdf_loading(True)
            self._load_pdf_direct(path)
        elif card.get("pdf_path") and not os.path.exists(card["pdf_path"]):
            self.btn_relink.setVisible(True)
            self.lbl_sync.setVisible(True)
            self.lbl_sync.setText("⚠ PDF not found — click 🔄 Relink PDF to fix")
            self.lbl_sync.setStyleSheet(
                "color:#CC6600;font-size:11px;background:transparent;font-weight:bold;")
            # Apply masks directly to canvas right now — no PDF load will trigger
            # _on_pdf_done so _pending_boxes would never get restored otherwise
            if current_boxes:
                self._pending_boxes = current_boxes
                self.canvas.set_boxes(current_boxes)
                self.mask_panel._refresh(current_boxes)

    # ── file watcher (live sync) ───────────────────────────────────────────────

    def _watch_pdf(self, path: str):
        self._stop_watch(); self._watched_path = path
        self._watcher.addPath(path)
        self.btn_open_ext.setVisible(True)
        self.btn_relink.setVisible(True)
        self.lbl_sync.setVisible(True); self.lbl_sync.setText("🟢 Live Sync: watching")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_GREEN', C_GREEN)};font-size:11px;background:transparent;font-weight:bold;")

    def _stop_watch(self):
        if self._watched_path:
            self._watcher.removePath(self._watched_path); self._watched_path = None
        self._reload_timer.stop()

    def _on_file_changed(self, path: str):
        self.lbl_sync.setText("🟡 Live Sync: change detected…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;")
        self._reload_timer.start()

    def _reload_pdf(self):
        path = self._watched_path
        if not path or not os.path.exists(path):
            QTimer.singleShot(500, self._reload_pdf); return
        if path not in self._watcher.files(): self._watcher.addPath(path)
        PAGE_CACHE.invalidate_pdf(path)

        saved_boxes = self.canvas.get_boxes()
        self._pending_boxes = saved_boxes
        self.lbl_sync.setText("🟡 Live Sync: reloading…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;")
        self._load_pdf_direct(path)

    def _open_in_reader(self):
        path = self.card.get("pdf_path") or self._watched_path
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded."); return
        import subprocess
        page = self._current_visible_page() + 1
        try:
            pdf_url = QUrl.fromLocalFile(path)
            pdf_url.setFragment(f"page={page}")
            if QDesktopServices.openUrl(pdf_url):
                return
            if sys.platform == "win32":       os.startfile(path)
            elif sys.platform == "darwin":    subprocess.Popen(["open",     path])
            else:                             subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            QMessageBox.warning(self,"Could not open",f"Could not open PDF:\n{ex}")

    def _relink_pdf(self):
        """Pick a new PDF file — replaces the stored path but keeps ALL existing masks."""
        if not PDF_SUPPORT:
            QMessageBox.warning(self, "No PDF support", "pip install pymupdf"); return

        old_path = self.card.get("pdf_path", "") or self._watched_path or ""
        start_dir = os.path.dirname(old_path) if old_path else ""

        new_path, _ = QFileDialog.getOpenFileName(
            self, "Choose New PDF File", start_dir, "PDF (*.pdf)")
        if not new_path:
            return

        # Confirm so user doesn't accidentally overwrite with wrong file
        reply = QMessageBox.question(
            self, "Relink PDF",
            f"Replace source PDF with:\n{new_path}\n\n"
            "All your existing masks will be kept exactly as they are.\n"
            "The new PDF will be used as the background going forward.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return

        # Save masks — prefer canvas if it has boxes loaded (normal relink),
        # fall back to card["boxes"] when canvas is empty (broken-path relink)
        canvas_boxes = self.canvas.get_boxes()
        saved_boxes = canvas_boxes if canvas_boxes else list(self.card.get("boxes", []))

        # Invalidate old cache, update stored path
        if old_path:
            PAGE_CACHE.invalidate_pdf(old_path)
        self.card["pdf_path"] = new_path
        self.card.pop("image_path", None)
        self._auto_subdeck_name = os.path.splitext(os.path.basename(new_path))[0]

        # _pending_boxes makes _on_pdf_done restore masks after load
        self._pending_boxes = saved_boxes

        self.lbl_sync.setVisible(True)
        self.lbl_sync.setText("🔄 Relinking…")
        self.lbl_sync.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', C_YELLOW)};font-size:11px;background:transparent;font-weight:bold;")

        self._show_pdf_loading(True)
        self._load_pdf_direct(new_path)

    # ── save / close ──────────────────────────────────────────────────────────

    def _save(self):
        if not self.card.get("image_path") and not self.card.get("pdf_path"):
            QMessageBox.warning(self,"No Source","Load an image or PDF first."); return
        old_boxes = self.card.get("boxes",[])
        new_boxes = self.canvas.get_boxes()
        SM2_KEYS  = ("sm2_interval","sm2_repetitions","sm2_ease",
                     "sm2_due","sm2_last_quality","box_id",
                     "sched_state","sched_step","reviews")
        old_by_id = {b["box_id"]: b for b in old_boxes if "box_id" in b}
        merged = []
        for i, nb in enumerate(new_boxes):
            old = old_by_id.get(nb.get("box_id")) or (old_boxes[i] if i < len(old_boxes) else None)
            if old:
                for k in SM2_KEYS:
                    if k in old: nb[k] = old[k]
            if "box_id" not in nb: nb["box_id"] = new_box_id()
            merged.append(nb)
        self.card.update({"title":   self.inp_title.text().strip() or "Untitled",
                          "tags":    [t.strip() for t in self.inp_tags.text().split(",") if t.strip()],
                          "notes":   self.inp_notes.toPlainText(),
                          "boxes":   merged,
                          "created": self.card.get("created", datetime.now().isoformat()),
                          "reviews": self.card.get("reviews", 0)})
        if self._auto_subdeck_name: self.card["_auto_subdeck"] = self._auto_subdeck_name
        sm2_init(self.card)
        for box in self.card.get("boxes",[]): sm2_init(box)
        self.accept()

    def get_card(self): return self.card

    def closeEvent(self, e):
        self._stop_watch()
        self._stop_pdf_threads()
        super().closeEvent(e)

    def reject(self):
        self._stop_watch()
        self._stop_pdf_threads()
        super().reject()

    def accept(self):
        self._stop_watch(); super().accept()


# ═══════════════════════════════════════════════════════════════════════════════
