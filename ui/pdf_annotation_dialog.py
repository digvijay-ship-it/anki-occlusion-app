import os

from PyQt5.QtCore import (
    QByteArray,
    QBuffer,
    QIODevice,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QEvent,
    pyqtSignal,
    QSettings,
)
from PyQt5.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QColorDialog,
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

from pdf_engine import (
    PAGE_CACHE,
    PdfOnDemandThread,
    get_cached_pdf_page_set,
    load_pdf_skeleton,
)
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
        if (
            obj in (self.viewport(), self._canvas)
            and event.type() == QEvent.NativeGesture
        ):
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
    image_move_finished = pyqtSignal(int, int, str, object, object)

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
        self._image_drag_item = None
        self._image_drag_page = None
        self._image_drag_start = None
        self._image_drag_start_global = None
        self._image_drag_start_rect = None
        self._image_drag_current_page = None
        self._selected_image_page = None
        self._selected_image_id = None
        self._resize_handle = None  # "tl"|"tr"|"bl"|"br" = resize; None = move
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
        if tool == "image":
            self.setCursor(Qt.ArrowCursor)
        elif tool == "erase":
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
        scroll_area.verticalScrollBar().setValue(
            int(self._page_tops[page_num] * self._scale)
        )

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
            rect = QRectF(
                0.0,
                float(top),
                float(px.width()) * self._scale,
                float(px.height()) * self._scale,
            )
            if rect.bottom() < clip.top() or rect.top() > clip.bottom():
                continue
            p.fillRect(rect, Qt.white)
            p.drawPixmap(rect, px, QRectF(px.rect()))
            p.setPen(QPen(QColor("#4A4A5A"), 1))
            p.drawRect(rect)
            self._draw_page_overlays(p, idx, rect.top())

        if self._live_points and self._drawing_page is not None:
            self._draw_points(p, self._live_points, self._drawing_page, self._live_tool)
            
        if self._tool == "image" and self._image_drag_item is not None and self._image_drag_page is not None:
            current_page = getattr(self, "_image_drag_current_page", self._image_drag_page)
            if current_page is None:
                current_page = self._image_drag_page
            self._draw_image_item_global(p, self._image_drag_item, current_page)

        p.end()

    def _draw_image_item_global(self, painter: QPainter, item, page_num: int):
        pixmap = item.get("pixmap")
        rect = self._item_rect(item)
        if pixmap is None or pixmap.isNull() or rect is None:
            return
        top = self._page_tops[page_num] * self._scale
        target = QRectF(
            rect.x() * self._scale,
            top + rect.y() * self._scale,
            rect.width() * self._scale,
            rect.height() * self._scale,
        )
        painter.save()
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        
        # also draw selection lines
        painter.setPen(
            QPen(QColor("#00E5FF"), max(1.0, 1.2 * self._scale), Qt.DashLine)
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(target)
        
        # draw resize handles
        hr = max(5.0, 5.0 * self._scale)
        painter.setPen(QPen(QColor("#FFDD55"), 1.5))
        painter.setBrush(Qt.white)
        for cx, cy in [
            (target.left(), target.top()),
            (target.right(), target.top()),
            (target.left(), target.bottom()),
            (target.right(), target.bottom()),
        ]:
            painter.drawRect(QRectF(cx - hr / 2, cy - hr / 2, hr, hr))
        painter.restore()

    def _draw_page_overlays(self, painter: QPainter, page_num: int, top: float):
        if not self._overlay_provider:
            return
        items = list(self._overlay_provider(page_num))
        for item in items:
            if self._is_selectable_visual(item):
                self._draw_image_item(painter, item, page_num)
                self._draw_image_selection(painter, item, page_num)
        for item in items:
            if self._is_selectable_visual(item):
                continue
            self._draw_points(
                painter,
                item.get("points", []),
                page_num,
                item.get("kind", "pen"),
                color=item.get("color"),
                width=item.get("width"),
                opacity=item.get("opacity", 1.0),
            )

    def _draw_image_item(self, painter: QPainter, item, page_num: int):
        if self._tool == "image" and self._image_drag_item is not None:
            if item.get("id") == self._image_drag_item.get("id") and page_num == self._image_drag_page:
                return
        pixmap = item.get("pixmap")
        rect = self._item_rect(item)
        if pixmap is None or pixmap.isNull() or rect is None:
            return
        is_existing = item.get("source") == "existing"
        is_selected = item.get("id") == self._selected_image_id
        in_img_tool = getattr(self, "_tool", "") == "image"
        if is_existing and not is_selected and not in_img_tool:
            return
        top = self._page_tops[page_num] * self._scale
        target = QRectF(
            rect.x() * self._scale,
            top + rect.y() * self._scale,
            rect.width() * self._scale,
            rect.height() * self._scale,
        )
        painter.save()
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        if self._tool == "image":
            painter.setPen(
                QPen(QColor("#00E5FF"), max(1.0, 1.0 * self._scale), Qt.DashLine)
            )
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(target)
        painter.restore()

    def _draw_image_selection(self, painter: QPainter, item, page_num: int):
        if self._tool == "image" and self._image_drag_item is not None:
            if item.get("id") == self._image_drag_item.get("id") and page_num == self._image_drag_page:
                return
        if self._tool != "image" and item.get("id") != self._selected_image_id:
            return
        rect = self._item_rect(item)
        if rect is None:
            return
        top = self._page_tops[page_num] * self._scale
        target = QRectF(
            rect.x() * self._scale,
            top + rect.y() * self._scale,
            rect.width() * self._scale,
            rect.height() * self._scale,
        )
        painter.save()
        is_sel = item.get("id") == self._selected_image_id
        color = QColor("#FFDD55") if is_sel else QColor("#00E5FF")
        painter.setPen(QPen(color, max(1.0, 1.2 * self._scale), Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(target)
        if is_sel:
            hr = max(5.0, 5.0 * self._scale)
            painter.setPen(QPen(QColor("#FFDD55"), 1.5))
            painter.setBrush(Qt.white)
            for cx, cy in [
                (target.left(), target.top()),
                (target.right(), target.top()),
                (target.left(), target.bottom()),
                (target.right(), target.bottom()),
            ]:
                painter.drawRect(QRectF(cx - hr / 2, cy - hr / 2, hr, hr))
        painter.restore()

    def _draw_points(
        self,
        painter: QPainter,
        points,
        page_num: int,
        tool: str,
        color=None,
        width=None,
        opacity=1.0,
    ):
        pts = [
            pt if isinstance(pt, QPointF) else QPointF(pt[0], pt[1]) for pt in points
        ]
        if len(pts) < 2:
            return
        top = self._page_tops[page_num] * self._scale
        path = QPainterPath()
        path.moveTo(pts[0].x() * self._scale, top + pts[0].y() * self._scale)
        for idx in range(1, len(pts) - 1):
            mid = QPointF(
                (pts[idx].x() + pts[idx + 1].x()) / 2.0,
                (pts[idx].y() + pts[idx + 1].y()) / 2.0,
            )
            path.quadTo(
                pts[idx].x() * self._scale,
                top + pts[idx].y() * self._scale,
                mid.x() * self._scale,
                top + mid.y() * self._scale,
            )
        last = pts[-1]
        path.lineTo(last.x() * self._scale, top + last.y() * self._scale)
        pen_color = QColor(color or ("#FFD54A" if tool == "highlight" else "#FF4444"))
        painter.save()
        painter.setOpacity(float(opacity))
        pen = QPen(
            pen_color,
            max(
                1.0,
                float(width or (12.0 if tool == "highlight" else 2.8)) * self._scale,
            ),
        )
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
        if self._tool == "image":
            handle = self._handle_at(page_num, point)
            if handle is not None:
                item = (
                    next(
                        (
                            i
                            for i in self._overlay_provider(page_num)
                            if i.get("id") == self._selected_image_id
                        ),
                        None,
                    )
                    if self._overlay_provider
                    else None
                )
                if item is not None:
                    self._resize_handle = handle
                    self._image_drag_item = item
                    self._image_drag_page = page_num
                    self._image_drag_current_page = page_num
                    self._image_drag_start = QPointF(point)
                    self._image_drag_start_global = QPointF(event.pos())
                    self._image_drag_start_rect = self._item_rect(item)
                return
            item = self._image_item_at(page_num, point)
            if item is None:
                self.clear_selected_image()
                self._resize_handle = None
                return
            self._selected_image_page = page_num
            self._selected_image_id = item.get("id")
            self._image_drag_item = item
            self._image_drag_page = page_num
            self._image_drag_current_page = page_num
            self._image_drag_start = QPointF(point)
            self._image_drag_start_global = QPointF(event.pos())
            self._image_drag_start_rect = self._item_rect(item)
            self._resize_handle = None
            return
        if self._tool == "erase":
            self._erase_active = True
            self.erase_dragged.emit(page_num, point)
            return
        self._drawing_page = page_num
        self._live_tool = self._tool
        self._live_points = [point]
        self.update()

    def mouseMoveEvent(self, event):
        page_num, point = self._page_info_for_pos(event.pos())
        if self._tool == "image":
            # Active drag logic
            if self._image_drag_item is not None:
                if point is None and not self._resize_handle:
                    pass
                if (
                    self._image_drag_page is None
                    or self._image_drag_start is None
                    or self._image_drag_start_rect is None
                ):
                    return
                orig = self._image_drag_start_rect
                if self._resize_handle:
                    dx = point.x() - self._image_drag_start.x() if point else 0
                    dy = point.y() - self._image_drag_start.y() if point else 0
                    h = self._resize_handle
                    fx = orig.right() if h in ("tl", "bl") else orig.left()
                    fy = orig.bottom() if h in ("tl", "tr") else orig.top()
                    mx = (orig.left() + dx) if h in ("tl", "bl") else (orig.right() + dx)
                    my = (orig.top() + dy) if h in ("tl", "tr") else (orig.bottom() + dy)
                    new_rect = QRectF(
                        min(fx, mx),
                        min(fy, my),
                        max(8.0, abs(mx - fx)),
                        max(8.0, abs(my - fy)),
                    )
                    self._image_drag_item["rect"] = self._clamp_image_rect(
                        self._image_drag_page, new_rect
                    )
                else:
                    delta = QPointF(
                        (event.pos().x() - self._image_drag_start_global.x()) / self._scale,
                        (event.pos().y() - self._image_drag_start_global.y()) / self._scale,
                    )
                    
                    moved = QRectF(orig)
                    moved.translate(delta)
                    
                    target_page = page_num
                    if target_page is None:
                        # Fallback to the center of the dragged rect if mouse is in a gap
                        global_center_y = self._page_tops[self._image_drag_page] + moved.center().y()
                        target_page, _ = self._page_info_for_pos(QPointF(moved.center().x() * self._scale, global_center_y * self._scale))
                    
                    if target_page is None:
                        target_page = self._image_drag_page
                        
                    y_offset = self._page_tops[self._image_drag_page] - self._page_tops[target_page]
                    moved.translate(0, y_offset)
                    
                    clamped = self._clamp_image_rect(target_page, moved)
                    
                    self._image_drag_item["rect"] = clamped
                    self._image_drag_current_page = target_page

                cursors = {
                    "tl": Qt.SizeFDiagCursor,
                    "br": Qt.SizeFDiagCursor,
                    "tr": Qt.SizeBDiagCursor,
                    "bl": Qt.SizeBDiagCursor,
                }
                self.setCursor(cursors.get(self._resize_handle, Qt.SizeAllCursor))
                self.update()
                return

            # Hover logic (not dragging)
            if page_num is not None and point is not None:
                handle = self._handle_at(page_num, point)
                if handle:
                    cursors = {
                        "tl": Qt.SizeFDiagCursor,
                        "br": Qt.SizeFDiagCursor,
                        "tr": Qt.SizeBDiagCursor,
                        "bl": Qt.SizeBDiagCursor,
                    }
                    self.setCursor(cursors.get(handle, Qt.ArrowCursor))
                    return
                item = self._image_item_at(page_num, point)
                if item is not None:
                    self.setCursor(Qt.SizeAllCursor)
                    return

            # Default image tool cursor
            self.set_tool("image")
            return

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
        if self._tool == "image":
            if self._image_drag_item is not None and self._image_drag_page is not None:
                rect = self._item_rect(self._image_drag_item)
                if rect is None:
                    rect = QRectF()
                
                target_page = getattr(self, "_image_drag_current_page", self._image_drag_page)
                if target_page is None:
                    target_page = self._image_drag_page
                
                self.image_move_finished.emit(
                    self._image_drag_page,
                    target_page,
                    self._image_drag_item["id"],
                    QRectF(self._image_drag_start_rect),
                    rect,
                )
            self._image_drag_item = None
            self._image_drag_page = None
            self._image_drag_start = None
            self._image_drag_start_rect = None
            self._image_drag_current_page = None
            self._resize_handle = None
            self.setCursor(Qt.SizeAllCursor)
            return
        if self._tool == "erase":
            self._erase_active = False
            return
        if self._drawing_page is not None and len(self._live_points) >= 2:
            self.stroke_finished.emit(
                self._drawing_page, self._live_tool, list(self._live_points)
            )
        self._drawing_page = None
        self._live_points = []
        self.update()

    def _handle_at(self, page_num: int, point: QPointF):
        """Return corner name (tl/tr/bl/br) if point hits a resize handle."""
        if (
            self._selected_image_id is None
            or self._selected_image_page != page_num
            or not self._overlay_provider
        ):
            return None
        item = next(
            (
                i
                for i in self._overlay_provider(page_num)
                if i.get("id") == self._selected_image_id
            ),
            None,
        )
        if item is None:
            return None
        rect = self._item_rect(item)
        if rect is None:
            return None
        hr = max(6.0, 6.0 / max(self._scale, 0.1))  # handle radius in image-space
        corners = {
            "tl": (rect.left(), rect.top()),
            "tr": (rect.right(), rect.top()),
            "bl": (rect.left(), rect.bottom()),
            "br": (rect.right(), rect.bottom()),
        }
        for name, (cx, cy) in corners.items():
            if abs(point.x() - cx) <= hr and abs(point.y() - cy) <= hr:
                return name
        return None

    def _image_item_at(self, page_num: int, point: QPointF):
        if not self._overlay_provider:
            return None
        for item in reversed(list(self._overlay_provider(page_num))):
            if not self._is_selectable_visual(item):
                continue
            rect = self._item_rect(item)
            if rect is None:
                continue
            if rect.contains(point):
                return item
        return None

    @staticmethod
    def _is_selectable_visual(item):
        return item.get("kind") in {"image", "stamp"}

    @staticmethod
    def _item_rect(item):
        rect = item.get("rect")
        if rect is None:
            return None
        if isinstance(rect, QRectF):
            return QRectF(rect)
        if item.get("source") == "existing" and item.get("kind") in {"image", "stamp"}:
            return QRectF(
                float(rect[0]),
                float(rect[1]),
                max(1.0, float(rect[2]) - float(rect[0])),
                max(1.0, float(rect[3]) - float(rect[1])),
            )
        return QRectF(*rect)

    def _clamp_image_rect(self, page_num: int, rect: QRectF) -> QRectF:
        if page_num is None or page_num < 0 or page_num >= len(self._pages):
            return QRectF(rect)
        page = self._pages[page_num]
        page_w = max(float(page.width()), 1.0)
        page_h = max(float(page.height()), 1.0)
        width = min(max(rect.width(), 1.0), page_w)
        height = min(max(rect.height(), 1.0), page_h)
        x = max(0.0, min(page_w - width, rect.x()))
        y = max(0.0, min(page_h - height, rect.y()))
        return QRectF(x, y, width, height)

    def selected_image(self):
        if self._selected_image_page is None or not self._selected_image_id:
            return None, None
        return self._selected_image_page, self._selected_image_id

    def select_image(self, page_num: int, item_id: str):
        self._selected_image_page = int(page_num)
        self._selected_image_id = item_id
        self.update()

    def clear_selected_image(self):
        self._selected_image_page = None
        self._selected_image_id = None
        self.update()


class PdfAnnotationDialog(QDialog):
    PEN_DEFAULT_COLOR = "#FF4444"
    PEN_DEFAULT_WIDTH = 2.8
    PREFETCH_RADIUS = 1

    def __init__(
        self,
        pdf_path: str,
        parent=None,
        initial_page: int = 0,
        initial_anchor_y: float | None = None,
    ):
        super().__init__(parent)
        self.pdf_path = os.path.abspath(pdf_path)
        self.initial_page = max(0, int(initial_page or 0))
        self.initial_anchor_y = initial_anchor_y
        self.session = PdfAnnotationSession(
            self.pdf_path,
            initial_page=self.initial_page,
            preload_radius=self.PREFETCH_RADIUS,
        )
        self._annotation_pen_color = self._load_annotation_pen_color()
        self._annotation_pen_width = self._load_annotation_pen_width()
        self._current_page_zero = self.initial_page
        self._loader_thread = None
        self._loader_targets = ()
        self._saved_pages = []
        self.return_page = self.initial_page
        self.return_anchor_y = initial_anchor_y
        self._setup_ui()
        self._load_pages()

    def _debug(self, action: str, **data):
        return

    def _target_page_window(self, center_page: int):
        total = max(0, int(getattr(self.session, "page_count", 0) or 0))
        if total <= 0:
            return []
        center = max(0, min(int(center_page), total - 1))
        start = max(0, center - self.PREFETCH_RADIUS)
        end = min(total - 1, center + self.PREFETCH_RADIUS)
        return list(range(start, end + 1))

    def _ensure_annotation_window(self, center_page: int, reason: str):
        loaded = self.session.ensure_existing_annotations_loaded(
            center_page=center_page,
            radius=self.PREFETCH_RADIUS,
        )
        if loaded:
            self.canvas.update()
        return loaded

    def _stop_loader_thread(self):
        thread = getattr(self, "_loader_thread", None)
        if thread and thread.isRunning():
            thread.stop()
            thread.quit()
            thread.wait(500)
        self._loader_thread = None
        self._loader_targets = ()

    def _ensure_render_window(self, center_page: int, reason: str):
        targets = self._target_page_window(center_page)
        if not targets:
            return []
        missing = []
        for page_num in targets:
            cached = PAGE_CACHE.get(self.pdf_path, page_num)
            if cached is not None and not cached.isNull():
                self.canvas.replace_page(page_num, cached)
                continue
            missing.append(page_num)
        target_key = tuple(missing)
        if not missing:
            self.lbl_status.setText(f"ready p.{center_page + 1}")
            self._stop_loader_thread()
            return []
        if (
            self._loader_thread
            and self._loader_thread.isRunning()
            and target_key == self._loader_targets
        ):
            return list(missing)
        self._stop_loader_thread()
        self._loader_targets = target_key
        self.lbl_status.setText(
            f"loading p.{missing[0] + 1}"
            if len(missing) == 1
            else "loading " + ", ".join(f"p.{pn + 1}" for pn in missing)
        )
        self._loader_thread = PdfOnDemandThread(
            self.pdf_path,
            page_nums=missing,
            zoom=self.session.render_zoom,
            parent=self,
        )
        self._loader_thread.page_ready.connect(self._on_page_ready)
        self._loader_thread.batch_done.connect(self._on_render_window_done)
        self._loader_thread.error.connect(self._on_render_window_error)
        self._loader_thread.start()
        return list(missing)

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
        self.btn_color = QPushButton("🎨 Ink")
        self.btn_erase = QPushButton("🧽 Erase")
        self.btn_image = QPushButton("🖼 Move Image")
        self.btn_pen.setCheckable(True)
        self.btn_highlight.setCheckable(True)
        self.btn_erase.setCheckable(True)
        self.btn_image.setCheckable(True)
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

        for btn in (
            self.btn_undo,
            self.btn_redo,
            self.btn_pen,
            self.btn_highlight,
            self.btn_color,
            self.btn_erase,
            self.btn_image,
        ):
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
        self.btn_color.clicked.connect(self._choose_pen_color)
        self.btn_erase.clicked.connect(lambda: self._set_tool("erase"))
        self.btn_image.clicked.connect(lambda: self._set_tool("image"))
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
        self.canvas.image_move_finished.connect(self._on_image_move_finished)

        QShortcut(Qt.CTRL + Qt.Key_S, self, activated=self._save_pdf)
        QShortcut(Qt.CTRL + Qt.Key_V, self, activated=self._paste_clipboard_image)
        QShortcut(Qt.Key_Delete, self, activated=self._delete_selected_image)
        QShortcut(Qt.CTRL + Qt.Key_Z, self, activated=self._undo)
        QShortcut(Qt.CTRL + Qt.Key_Y, self, activated=self._redo)
        QShortcut(Qt.Key_Left, self, activated=self._viewer.go_prev_page)
        QShortcut(Qt.Key_Right, self, activated=self._viewer.go_next_page)
        QShortcut(Qt.Key_1, self, activated=lambda: self._set_tool("pen"))
        QShortcut(Qt.Key_2, self, activated=lambda: self._set_tool("highlight"))
        QShortcut(Qt.Key_3, self, activated=lambda: self._set_tool("erase"))
        QShortcut(Qt.Key_P, self, activated=lambda: self._set_tool("pen"))
        QShortcut(Qt.Key_E, self, activated=lambda: self._set_tool("erase"))
        QShortcut(Qt.Key_S, self, activated=lambda: self._set_tool("image"))
        QShortcut(Qt.Key_Minus, self, activated=lambda: self._adjust_pen_width(-0.4))
        QShortcut(Qt.Key_Equal, self, activated=lambda: self._adjust_pen_width(0.4))
        QShortcut(Qt.Key_Plus, self, activated=lambda: self._adjust_pen_width(0.4))
        QShortcut(Qt.Key_0, self, activated=self._reset_pen_style)
        QShortcut(Qt.Key_C, self, activated=self._viewer.reset_fit)
        self._update_pen_controls()

    def exec_(self):
        self.showMaximized()
        return super().exec_()

    def _set_tool(self, tool: str):
        self.btn_pen.setChecked(tool == "pen")
        self.btn_highlight.setChecked(tool == "highlight")
        self.btn_erase.setChecked(tool == "erase")
        self.btn_image.setChecked(tool == "image")
        self.canvas.set_tool(tool)
        if tool == "image":
            self.lbl_status.setText("image move mode: drag pasted screenshot")
        elif tool == "pen":
            self.lbl_status.setText(
                f"pen {self._annotation_pen_width:.1f}px {self._annotation_pen_color}"
            )
        self._update_pen_controls()

    def _annotation_pen_style_override(self, tool: str) -> dict | None:
        if tool != "pen":
            return None
        return {
            "color": self._annotation_pen_color,
            "width": float(self._annotation_pen_width),
        }

    def _load_annotation_pen_color(self) -> str:
        raw = QSettings("AnkiOcclusion", "App").value(
            "annotation/pen_color", self.PEN_DEFAULT_COLOR
        )
        color = str(raw or self.PEN_DEFAULT_COLOR).strip() or self.PEN_DEFAULT_COLOR
        if not QColor(color).isValid():
            color = self.PEN_DEFAULT_COLOR
        return color

    def _load_annotation_pen_width(self) -> float:
        raw = QSettings("AnkiOcclusion", "App").value(
            "annotation/pen_width", self.PEN_DEFAULT_WIDTH
        )
        try:
            width = float(raw)
        except (TypeError, ValueError):
            width = self.PEN_DEFAULT_WIDTH
        width = max(0.8, min(24.0, width))
        return width

    def _save_annotation_pen_settings(self):
        settings = QSettings("AnkiOcclusion", "App")
        settings.setValue("annotation/pen_color", self._annotation_pen_color)
        settings.setValue("annotation/pen_width", float(self._annotation_pen_width))
        settings.sync()
        self._debug(
            "save_pen_settings",
            color=self._annotation_pen_color,
            width=f"{self._annotation_pen_width:.1f}",
        )

    def _update_pen_controls(self):
        color = QColor(self._annotation_pen_color)
        color_name = color.name() if color.isValid() else self.PEN_DEFAULT_COLOR
        self.btn_color.setStyleSheet(
            "QPushButton{"
            f"background:{color_name};"
            "color:#111111;border:1px solid #45475A;border-radius:6px;padding:6px 10px;font-weight:bold;}"
            "QPushButton:hover{background:#FFFFFF;}"
        )
        self.btn_color.setText(f"🎨 {self._annotation_pen_width:.1f}px")
        self.btn_color.setEnabled(getattr(self.canvas, "_tool", "pen") == "pen")

    def _adjust_pen_width(self, delta: float):
        if getattr(self.canvas, "_tool", "pen") != "pen":
            self.lbl_status.setText("pen width shortcuts apply in pen tool")
            return
        self._annotation_pen_width = max(
            0.8, min(24.0, float(self._annotation_pen_width) + float(delta))
        )
        self._save_annotation_pen_settings()
        self._update_pen_controls()
        self.lbl_status.setText(
            f"pen {self._annotation_pen_width:.1f}px {self._annotation_pen_color}"
        )
        self._debug(
            "pen_width_adjust", delta=delta, width=f"{self._annotation_pen_width:.1f}"
        )

    def _reset_pen_style(self):
        self._annotation_pen_color = self.PEN_DEFAULT_COLOR
        self._annotation_pen_width = float(self.PEN_DEFAULT_WIDTH)
        self._save_annotation_pen_settings()
        self._update_pen_controls()
        self.lbl_status.setText(
            f"pen reset {self._annotation_pen_width:.1f}px {self._annotation_pen_color}"
        )
        self._debug(
            "pen_reset",
            color=self._annotation_pen_color,
            width=f"{self._annotation_pen_width:.1f}",
        )

    def _choose_pen_color(self):
        chosen = QColorDialog.getColor(
            QColor(self._annotation_pen_color), self, "Choose Pen Color"
        )
        if not chosen.isValid():
            self._debug("pen_color_cancel")
            return
        self._annotation_pen_color = chosen.name()
        self._save_annotation_pen_settings()
        self._update_pen_controls()
        self.lbl_status.setText(
            f"pen {self._annotation_pen_width:.1f}px {self._annotation_pen_color}"
        )
        self._debug("pen_color_pick", color=self._annotation_pen_color)

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
        base_pages = (
            list(skeleton.placeholders)
            if skeleton and not skeleton.error
            else [QPixmap() for _ in range(total)]
        )
        for page_num, px in cached_pages.items():
            if 0 <= page_num < len(base_pages):
                base_pages[page_num] = px
        self.canvas.load_pages(base_pages)
        self._viewer.reset_fit()
        self._viewer.set_page_ui(self.initial_page)
        if self.initial_anchor_y is not None:
            self._schedule_initial_anchor_restore("open")
        else:
            self._viewer.restore_position(page_zero=self.initial_page)
        self._ensure_annotation_window(self.initial_page, reason="open")
        self._ensure_render_window(self.initial_page, reason="open")

    def _apply_initial_anchor_position(
        self, reason: str = "manual", finalize: bool = False
    ):
        if self.initial_anchor_y is None:
            return False
        img_y = float(self.initial_anchor_y)
        scale = max(float(getattr(self.canvas, "_scale", 1.0) or 1.0), 0.01)
        scroll_y = int(img_y * scale)
        self.scroll.verticalScrollBar().setValue(scroll_y)
        if finalize:
            self.initial_anchor_y = None
        return True

    def _schedule_initial_anchor_restore(self, reason: str, delays_ms=(0, 35, 90)):
        if self.initial_anchor_y is None:
            return
        delays = list(delays_ms) if delays_ms else [0]
        for idx, delay in enumerate(delays):
            finalize = idx == len(delays) - 1
            QTimer.singleShot(
                int(delay),
                lambda rsn=f"{reason}@{delay}ms", fin=finalize: self._apply_initial_anchor_position(
                    rsn, finalize=fin
                ),
            )

    def _on_page_ready(self, page_num, qpx):
        if qpx is None:
            return
        pixmap = qpx if isinstance(qpx, QPixmap) else QPixmap.fromImage(qpx)
        if pixmap.isNull():
            return
        print(f"[DEBUG][annotation_lazy] 👀 p.{int(page_num) + 1}")
        self.canvas.replace_page(page_num, pixmap)

    def _on_render_window_done(self, rendered_pages):
        self._loader_thread = None
        self._loader_targets = ()
        current = self._current_page_zero
        self.lbl_status.setText(f"ready p.{current + 1}")

    def _on_render_window_error(self, message: str):
        self._loader_thread = None
        self._loader_targets = ()
        self.lbl_status.setText(message or "render failed")

    def _on_scroll_changed(self, value: int):
        page_zero = self.canvas.get_current_page(value)
        if page_zero != self._current_page_zero:
            self._debug("scroll", value=value, page=page_zero + 1)
            self._ensure_annotation_window(page_zero, reason="scroll")
            self._ensure_render_window(page_zero, reason="scroll")
        self._current_page_zero = page_zero
        self._viewer.set_page_ui(page_zero)
        self.return_page = page_zero

    def _on_stroke_finished(self, page_num: int, tool: str, points):
        item = self.session.add_new_item(
            page_num,
            tool,
            points,
            style_override=self._annotation_pen_style_override(tool),
        )
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

    def _on_image_move_finished(
        self, old_page: int, target_page: int, item_id: str, old_rect: QRectF, rect: QRectF
    ):
        if old_page == target_page:
            if self.session.move_image_item(old_page, item_id, rect, old_rect=old_rect):
                self.lbl_status.setText(f"moved screenshot p.{target_page + 1}")
                if item_id.startswith("existing:"):
                    preview = self.session.build_page_preview(target_page)
                    if preview is not None and not preview.isNull():
                        self.canvas.replace_page(target_page, preview)
                self.canvas.update()
        else:
            item = next((i for i in self.session.get_new_items_for_page(old_page) if i.get("id") == item_id), None)
            if item and item.get("image_bytes"):
                if self.session.delete_image_item(old_page, item_id):
                    new_item = self.session.add_image_item(target_page, item.get("image_bytes"), item.get("pixmap"), rect)
                    if new_item:
                        self.lbl_status.setText(f"moved screenshot p.{target_page + 1}")
                        self.canvas.select_image(target_page, new_item["id"])
                        if item_id.startswith("existing:"):
                            preview = self.session.build_page_preview(target_page)
                            if preview is not None and not preview.isNull():
                                self.canvas.replace_page(target_page, preview)
                            old_preview = self.session.build_page_preview(old_page)
                            if old_preview is not None and not old_preview.isNull():
                                self.canvas.replace_page(old_page, old_preview)
                        self.canvas.update()

    def _delete_selected_image(self):
        page_num, item_id = self.canvas.selected_image()
        if page_num is None or not item_id:
            self.lbl_status.setText("no screenshot selected")
            return
        if not self.session.delete_image_item(page_num, item_id):
            self.lbl_status.setText("selected screenshot could not be deleted")
            return
        self.canvas.clear_selected_image()
        preview = self.session.build_page_preview(page_num)
        if preview is not None and not preview.isNull():
            self.canvas.replace_page(page_num, preview)
        else:
            self.canvas.update()
        self.lbl_status.setText(f"deleted screenshot p.{page_num + 1}; save to persist")

    def _paste_clipboard_image(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if not mime.hasImage():
            self.lbl_status.setText("clipboard has no image")
            return
        image = clipboard.image()
        if image.isNull():
            self.lbl_status.setText("clipboard image is empty")
            return
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        image_bytes = bytes(data)
        pixmap = QPixmap.fromImage(image)
        page_num = self.canvas.get_current_page(self.scroll.verticalScrollBar().value())
        rect = self._default_image_rect(page_num, pixmap)
        item = self.session.add_image_item(page_num, image_bytes, pixmap, rect)
        if item is None:
            self.lbl_status.setText("could not paste screenshot")
            return
        self._set_tool("image")
        self.canvas.select_image(page_num, item["id"])
        self.lbl_status.setText(f"pasted screenshot p.{page_num + 1}; press P to write")
        self.canvas.update()

    def _default_image_rect(self, page_num: int, pixmap: QPixmap) -> QRectF:
        if page_num < 0 or page_num >= len(self.canvas._pages) or pixmap.isNull():
            return QRectF(20.0, 20.0, 200.0, 120.0)
        page = self.canvas._pages[page_num]
        page_w = max(float(page.width()), 1.0)
        page_h = max(float(page.height()), 1.0)
        target_w = min(page_w * 0.60, max(page_w * 0.28, float(pixmap.width())))
        target_h = target_w * float(pixmap.height()) / max(float(pixmap.width()), 1.0)
        if target_h > page_h * 0.45:
            target_h = page_h * 0.45
            target_w = (
                target_h * float(pixmap.width()) / max(float(pixmap.height()), 1.0)
            )

        viewport_center_x = (
            self.scroll.horizontalScrollBar().value()
            + self.scroll.viewport().width() / 2.0
        ) / max(self.canvas.zoom(), 0.01)
        viewport_center_y = (
            self.scroll.verticalScrollBar().value()
            + self.scroll.viewport().height() / 2.0
        ) / max(self.canvas.zoom(), 0.01)
        page_top = (
            self.canvas._page_tops[page_num]
            if page_num < len(self.canvas._page_tops)
            else 0
        )
        local_y = viewport_center_y - page_top
        x = max(0.0, min(page_w - target_w, viewport_center_x - target_w / 2.0))
        y = max(0.0, min(page_h - target_h, local_y - target_h / 2.0))
        return QRectF(x, y, target_w, target_h)

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
        if self.__dict__.get("_save_in_progress", False):
            return
        self._save_in_progress = True
        try:
            try:
                changed_pages = self.session.save()
            except Exception as ex:
                QMessageBox.warning(
                    self, "Annotation Save Failed", f"Could not update PDF:\n{ex}"
                )
                self.lbl_status.setText("save failed")
                return
            self._saved_pages = changed_pages
            # Clear selection — saved items become "existing:" source.
            # Leaving them selected would draw a floating overlay on top
            # of the freshly rendered page background.
            self.canvas.clear_selected_image()
            for page_num in changed_pages:
                # session.save() already re-rendered dirty pages into PAGE_CACHE.
                # Pull fresh pixmap from cache.
                px = PAGE_CACHE.get(self.pdf_path, page_num)
                if px is not None and not px.isNull():
                    self.canvas.replace_page(page_num, px)
                else:
                    preview = self.session.build_page_preview(page_num)
                    if preview is not None and not preview.isNull():
                        self.canvas.replace_page(page_num, preview)
            self.canvas.update()
            if changed_pages:
                self.lbl_status.setText(
                    "saved " + ", ".join(f"p.{pn + 1}" for pn in changed_pages)
                )
            else:
                self.lbl_status.setText("no changes")
        finally:
            self._save_in_progress = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_viewer"):
            QTimer.singleShot(0, self._viewer.on_resize)
        if self.initial_anchor_y is not None:
            self._schedule_initial_anchor_restore("resize", delays_ms=(0, 35))

    def closeEvent(self, event):
        self._stop_loader_thread()
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
