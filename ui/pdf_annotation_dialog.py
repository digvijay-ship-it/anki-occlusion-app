import os

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, QEvent, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QVBoxLayout,
    QWidget,
)

from pdf_engine import PAGE_CACHE, PdfLoaderThread, get_cached_pdf_page_set, load_pdf_skeleton
from services.pdf_annotation_service import PdfAnnotationSession
from ui.pdf_viewer_controller import PdfViewerController


PAGE_GAP = 10


class AnnotationScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = None
        self.viewport().installEventFilter(self)

    def set_canvas(self, canvas):
        self._canvas = canvas
        if self._canvas is not None:
            self._canvas.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj in (self.viewport(), self._canvas) and event.type() == QEvent.NativeGesture:
            if event.gestureType() == Qt.ZoomNativeGesture and self._canvas is not None:
                self._canvas.handle_native_zoom(event.value())
                return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):
        if (event.modifiers() & Qt.ControlModifier) and self._canvas is not None:
            self._canvas.handle_ctrl_wheel_zoom(event)
            return
        super().wheelEvent(event)


class PdfAnnotationCanvas(QWidget):
    stroke_finished = pyqtSignal(int, str, object)
    erase_dragged = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages = []
        self._page_tops = []
        self._scale = 1.0
        self._tool = "pen"
        self._overlay_provider = None
        self._drawing_page = None
        self._live_points = []
        self._live_tool = "pen"
        self._erase_active = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_overlay_provider(self, provider):
        self._overlay_provider = provider

    def load_pages(self, pages):
        self._pages = list(pages or [])
        self._page_tops = []
        y = 0
        max_w = 1
        for px in self._pages:
            self._page_tops.append(y)
            y += px.height() + PAGE_GAP
            max_w = max(max_w, px.width())
        total_h = max(1, y - PAGE_GAP if self._pages else 1)
        self.resize(int(max_w * self._scale), int(total_h * self._scale))
        self.setMinimumSize(int(max_w * self._scale), int(total_h * self._scale))
        self.updateGeometry()
        self.update()

    def replace_page(self, page_num: int, pixmap: QPixmap):
        if 0 <= page_num < len(self._pages):
            self._pages[page_num] = pixmap
            self.load_pages(self._pages)

    def set_tool(self, tool: str):
        self._tool = tool
        if tool == "erase":
            self.setCursor(Qt.ForbiddenCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def set_view_scale(self, scale: float):
        self._scale = max(0.2, min(4.0, float(scale)))
        self.load_pages(self._pages)
        self.repaint()

    def zoom(self):
        return self._scale

    def zoom_in(self):
        self.set_view_scale(self._scale * 1.10)

    def zoom_out(self):
        self.set_view_scale(self._scale / 1.10)

    def handle_native_zoom(self, gesture_value: float):
        self._scale = max(0.2, min(4.0, self._scale * (1.0 + float(gesture_value))))
        self.load_pages(self._pages)
        self.repaint()

    def handle_ctrl_wheel_zoom(self, event):
        angle = event.angleDelta().y()
        if angle == 0:
            event.accept()
            return
        factor = max(0.90, min(1.0 + (angle / 120.0) * 0.10, 1.11))
        self._scale = max(0.2, min(4.0, self._scale * factor))
        self.load_pages(self._pages)
        self.repaint()
        event.accept()

    def page_count(self):
        return len(self._pages)

    def current_page_index(self, scroll_value: int = 0) -> int:
        if not self._pages:
            return 0
        marker = max(0, int(scroll_value) + 1)
        for idx, top in enumerate(self._page_tops):
            bottom = top + self._pages[idx].height()
            if top <= marker / self._scale <= bottom:
                return idx
        return max(0, min(len(self._pages) - 1, len(self._pages) - 1))

    def get_current_page(self, scroll_value: int = 0) -> int:
        return self.current_page_index(scroll_value)

    def scroll_to_page(self, page_num: int, scroll_area: QScrollArea):
        if not self._pages:
            return
        page_num = max(0, min(int(page_num), len(self._pages) - 1))
        scroll_area.verticalScrollBar().setValue(int(self._page_tops[page_num] * self._scale))

    def zoom_fit_width(self, viewport_width: int):
        if not self._pages:
            return
        max_w = max(px.width() for px in self._pages)
        if max_w <= 0:
            return
        usable = max(1, int(viewport_width))
        self.set_view_scale(usable / max_w)

    def _page_info_for_pos(self, pos):
        if not self._pages:
            return None, None
        x = pos.x() / self._scale
        y = pos.y() / self._scale
        for idx, top in enumerate(self._page_tops):
            px = self._pages[idx]
            if top <= y <= top + px.height():
                return idx, QPointF(x, y - top)
        return None, None

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1E1E2E"))
        p.setRenderHint(QPainter.Antialiasing)
        clip = event.rect()
        for idx, px in enumerate(self._pages):
            top = int(self._page_tops[idx] * self._scale)
            rect = QRectF(0.0, float(top), float(px.width()) * self._scale, float(px.height()) * self._scale)
            if rect.bottom() < clip.top() or rect.top() > clip.bottom():
                continue
            p.fillRect(rect, Qt.white)
            p.drawPixmap(rect, px, QRectF(px.rect()))
            p.setPen(QPen(QColor("#4A4A5A"), 1))
            p.drawRect(rect)
            self._draw_page_overlays(p, idx, rect.top())

        if self._live_points and self._drawing_page is not None:
            self._draw_points(p, self._live_points, self._drawing_page, self._live_tool)
        p.end()

    def _draw_page_overlays(self, painter: QPainter, page_num: int, top: float):
        if not self._overlay_provider:
            return
        for item in self._overlay_provider(page_num):
            self._draw_points(painter, item.get("points", []), page_num, item.get("kind", "pen"), color=item.get("color"), width=item.get("width"), opacity=item.get("opacity", 1.0))

    def _draw_points(self, painter: QPainter, points, page_num: int, tool: str, color=None, width=None, opacity=1.0):
        pts = [pt if isinstance(pt, QPointF) else QPointF(pt[0], pt[1]) for pt in points]
        if len(pts) < 2:
            return
        top = self._page_tops[page_num] * self._scale
        path = QPainterPath()
        path.moveTo(pts[0].x() * self._scale, top + pts[0].y() * self._scale)
        for pt in pts[1:]:
            path.lineTo(pt.x() * self._scale, top + pt.y() * self._scale)
        pen_color = QColor(color or ("#FFD54A" if tool == "highlight" else "#FF4444"))
        painter.save()
        painter.setOpacity(float(opacity))
        pen = QPen(pen_color, max(1.0, float(width or (12.0 if tool == "highlight" else 2.8)) * self._scale))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.restore()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        page_num, point = self._page_info_for_pos(event.pos())
        if page_num is None:
            return
        if self._tool == "erase":
            print(
                f"[DEBUG][pdf_erase_drag] start page={page_num + 1} "
                f"x={point.x():.1f} y={point.y():.1f}"
            )
            self._erase_active = True
            self.erase_dragged.emit(page_num, point)
            return
        self._drawing_page = page_num
        self._live_tool = self._tool
        self._live_points = [point]
        self.update()

    def mouseMoveEvent(self, event):
        page_num, point = self._page_info_for_pos(event.pos())
        if self._tool == "erase" and self._erase_active and page_num is not None:
            self.erase_dragged.emit(page_num, point)
            return
        if self._drawing_page is None or page_num != self._drawing_page:
            return super().mouseMoveEvent(event)
        self._live_points.append(point)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        if self._tool == "erase":
            if self._erase_active:
                print("[DEBUG][pdf_erase_drag] stop")
            self._erase_active = False
            return
        if self._drawing_page is not None and len(self._live_points) >= 2:
            self.stroke_finished.emit(self._drawing_page, self._live_tool, list(self._live_points))
        self._drawing_page = None
        self._live_points = []
        self.update()


class PdfAnnotationDialog(QDialog):
    def __init__(self, pdf_path: str, parent=None, initial_page: int = 0, initial_anchor_y: float | None = None):
        super().__init__(parent)
        self.pdf_path = os.path.abspath(pdf_path)
        self.initial_page = max(0, int(initial_page or 0))
        self.initial_anchor_y = initial_anchor_y
        self.session = PdfAnnotationSession(self.pdf_path)
        self._current_page_zero = self.initial_page
        self._loader_thread = None
        self._saved_pages = []
        self.return_page = self.initial_page
        self.return_anchor_y = initial_anchor_y
        self._setup_ui()
        self._load_pages()

    def _debug(self, action: str, **data):
        parts = " ".join(f"{key}={value}" for key, value in data.items())
        print(f"[DEBUG][pdf_annotation_dialog] {action} {parts}".rstrip())

    def _setup_ui(self):
        self.setWindowTitle("PDF Annotation Editor (Beta)")
        self.setMinimumSize(1200, 800)
        self.setStyleSheet(
            "QDialog{background:#1E1E2E;color:#CDD6F4;}"
            "QWidget{background:#1E1E2E;color:#CDD6F4;font-family:'Segoe UI';font-size:12px;}"
            "QPushButton{background:#2A2A3E;color:#CDD6F4;border:1px solid #45475A;border-radius:6px;padding:6px 10px;font-weight:bold;}"
            "QPushButton:hover{background:#313145;}"
            "QPushButton:checked{background:#7C6AF7;color:white;}"
            "QLineEdit{background:#2A2A3E;color:#CDD6F4;border:1px solid #45475A;border-radius:6px;padding:4px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(8, 8, 8, 8)
        bar_l.setSpacing(6)

        self.btn_undo = QPushButton("↩ Undo")
        self.btn_redo = QPushButton("↪ Redo")
        self.btn_pen = QPushButton("🖊 Pen")
        self.btn_highlight = QPushButton("🟨 Highlight")
        self.btn_erase = QPushButton("🧽 Erase")
        self.btn_pen.setCheckable(True)
        self.btn_highlight.setCheckable(True)
        self.btn_erase.setCheckable(True)
        self.btn_pen.setChecked(True)
        self.btn_zoom_out = QPushButton("Zoom -")
        self.btn_zoom_in = QPushButton("Zoom +")
        self.btn_fit = QPushButton("Fit")
        self.btn_prev = QPushButton("←")
        self.btn_next = QPushButton("→")
        self.page_jump = QLineEdit()
        self.page_jump.setFixedWidth(52)
        self.page_jump.setAlignment(Qt.AlignCenter)
        self.lbl_page_total = QLabel("/ 0")
        self.btn_save = QPushButton("💾 Save PDF")
        self.btn_close = QPushButton("Close")
        self.lbl_status = QLabel("")
        self.lbl_title = QLabel(
            f"{os.path.basename(self.pdf_path)}  •  {self.session.page_count} pages  •  {self.session.render_label}"
        )

        for btn in (self.btn_undo, self.btn_redo, self.btn_pen, self.btn_highlight, self.btn_erase):
            bar_l.addWidget(btn)
        bar_l.addSpacing(8)
        bar_l.addWidget(self.btn_zoom_out)
        bar_l.addWidget(self.btn_zoom_in)
        bar_l.addWidget(self.btn_fit)
        bar_l.addWidget(self.btn_prev)
        bar_l.addWidget(self.btn_next)
        bar_l.addWidget(self.page_jump)
        bar_l.addWidget(self.lbl_page_total)
        bar_l.addSpacing(8)
        bar_l.addWidget(self.btn_save)
        bar_l.addStretch()
        bar_l.addWidget(self.lbl_title)
        bar_l.addStretch()
        bar_l.addWidget(self.lbl_status)
        bar_l.addWidget(self.btn_close)
        root.addWidget(bar)

        self.scroll = AnnotationScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.canvas = PdfAnnotationCanvas()
        self.canvas.set_overlay_provider(self.session.get_new_items_for_page)
        self.scroll.setWidget(self.canvas)
        self.scroll.set_canvas(self.canvas)
        root.addWidget(self.scroll, 1)
        self._viewer = PdfViewerController(
            canvas=self.canvas,
            scroll_area=self.scroll,
            page_input=self.page_jump,
            page_total_label=self.lbl_page_total,
            prev_button=self.btn_prev,
            next_button=self.btn_next,
            debug_hook=self._debug,
        )

        self.btn_pen.clicked.connect(lambda: self._set_tool("pen"))
        self.btn_highlight.clicked.connect(lambda: self._set_tool("highlight"))
        self.btn_erase.clicked.connect(lambda: self._set_tool("erase"))
        self.btn_zoom_out.clicked.connect(self._viewer.zoom_out)
        self.btn_zoom_in.clicked.connect(self._viewer.zoom_in)
        self.btn_fit.clicked.connect(self._viewer.reset_fit)
        self.btn_prev.clicked.connect(self._viewer.go_prev_page)
        self.btn_next.clicked.connect(self._viewer.go_next_page)
        self.page_jump.returnPressed.connect(self._viewer.jump_from_input)
        self.btn_undo.clicked.connect(self._undo)
        self.btn_redo.clicked.connect(self._redo)
        self.btn_save.clicked.connect(self._save_pdf)
        self.btn_close.clicked.connect(self.reject)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.canvas.stroke_finished.connect(self._on_stroke_finished)
        self.canvas.erase_dragged.connect(self._on_erase_dragged)

        QShortcut(Qt.CTRL + Qt.Key_S, self, activated=self._save_pdf)
        QShortcut(Qt.CTRL + Qt.Key_Z, self, activated=self._undo)
        QShortcut(Qt.CTRL + Qt.Key_Y, self, activated=self._redo)
        QShortcut(Qt.Key_Left, self, activated=self._viewer.go_prev_page)
        QShortcut(Qt.Key_Right, self, activated=self._viewer.go_next_page)
        QShortcut(Qt.Key_1, self, activated=lambda: self._set_tool("pen"))
        QShortcut(Qt.Key_2, self, activated=lambda: self._set_tool("highlight"))
        QShortcut(Qt.Key_3, self, activated=lambda: self._set_tool("erase"))
        QShortcut(Qt.Key_Minus, self, activated=self._viewer.zoom_out)
        QShortcut(Qt.Key_Equal, self, activated=self._viewer.zoom_in)
        QShortcut(Qt.Key_C, self, activated=self._viewer.reset_fit)

    def exec_(self):
        self.showMaximized()
        return super().exec_()

    def _set_tool(self, tool: str):
        self.btn_pen.setChecked(tool == "pen")
        self.btn_highlight.setChecked(tool == "highlight")
        self.btn_erase.setChecked(tool == "erase")
        self.canvas.set_tool(tool)

    def _load_pages(self):
        cache_state = get_cached_pdf_page_set(self.pdf_path, self.session.page_count)
        total = cache_state["total_pages"]
        cached_pages = cache_state["cached_pages_by_index"]
        self._debug(
            "open",
            pages=total,
            zoom=self.session.render_label,
            cache_hits=cache_state["cache_hit_count"],
            cache_misses=cache_state["cache_miss_count"],
            reset_cache=self.session.cache_reset,
        )
        skeleton = load_pdf_skeleton(self.pdf_path, zoom=self.session.render_zoom)
        base_pages = list(skeleton.placeholders) if skeleton and not skeleton.error else [QPixmap() for _ in range(total)]
        for page_num, px in cached_pages.items():
            if 0 <= page_num < len(base_pages):
                base_pages[page_num] = px
        self.canvas.load_pages(base_pages)
        self._viewer.reset_fit()
        self._viewer.set_page_ui(self.initial_page)
        self._viewer.restore_position(page_zero=self.initial_page)
        if len(cached_pages) == total:
            self.lbl_status.setText("cache ready")
            return
        self.lbl_status.setText("rendering missing pages…")
        self._loader_thread = PdfLoaderThread(self.pdf_path, zoom=self.session.render_zoom, parent=self)
        self._loader_thread.done.connect(self._on_pages_ready)
        self._loader_thread.start()

    def _on_pages_ready(self, pages, err):
        if err or not pages:
            self.lbl_status.setText(err or "render failed")
            return
        current = self._current_page_zero
        self.canvas.load_pages(pages)
        self._viewer.fit_width(force=False)
        self._viewer.restore_position(page_zero=current)
        self.lbl_status.setText("pages ready")

    def _on_scroll_changed(self, value: int):
        page_zero = self.canvas.get_current_page(value)
        if page_zero != self._current_page_zero:
            self._debug("scroll", value=value, page=page_zero + 1)
        self._current_page_zero = page_zero
        self._viewer.set_page_ui(page_zero)
        self.return_page = page_zero

    def _on_stroke_finished(self, page_num: int, tool: str, points):
        item = self.session.add_new_item(page_num, tool, points)
        if item is not None:
            self.canvas.update()
            self.lbl_status.setText(f"unsaved changes p.{page_num + 1}")

    def _on_erase_dragged(self, page_num: int, point):
        changed = self.session.erase_at_point(page_num, point)
        if not changed:
            return
        preview = self.session.build_page_preview(page_num)
        if preview is not None and not preview.isNull():
            self.canvas.replace_page(page_num, preview)
        else:
            self.canvas.update()
        self.lbl_status.setText(f"erase touched p.{page_num + 1}")

    def _undo(self):
        if not self.session.undo():
            return
        self._refresh_dirty_pages()
        self.lbl_status.setText("undo")

    def _redo(self):
        if not self.session.redo():
            return
        self._refresh_dirty_pages()
        self.lbl_status.setText("redo")

    def _refresh_dirty_pages(self):
        dirty = sorted(self.session.dirty_pages)
        for page_num in dirty:
            preview = self.session.build_page_preview(page_num)
            if preview is not None and not preview.isNull():
                self.canvas.replace_page(page_num, preview)
        self.canvas.update()

    def _save_pdf(self):
        try:
            changed_pages = self.session.save()
        except Exception as ex:
            QMessageBox.warning(self, "Annotation Save Failed", f"Could not update PDF:\n{ex}")
            self.lbl_status.setText("save failed")
            return
        self._saved_pages = changed_pages
        for page_num in changed_pages:
            px = PAGE_CACHE.get(self.pdf_path, page_num)
            if px is not None and not px.isNull():
                self.canvas.replace_page(page_num, px)
        self.canvas.update()
        if changed_pages:
            self.lbl_status.setText("saved " + ", ".join(f"p.{pn + 1}" for pn in changed_pages))
        else:
            self.lbl_status.setText("no changes")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_viewer"):
            QTimer.singleShot(0, self._viewer.on_resize)

    def closeEvent(self, event):
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.stop()
            self._loader_thread.quit()
            self._loader_thread.wait(500)
        self.return_page = self._current_page_zero
        self.return_anchor_y = self.scroll.verticalScrollBar().value()
        self.session.close()
        super().closeEvent(event)

    def reject(self):
        if self.session.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Discard Changes",
                "Unsaved annotation changes will be lost. Close anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        super().reject()
