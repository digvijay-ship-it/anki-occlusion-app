from __future__ import annotations

import os
import sys
import time
import tempfile
import hashlib
from collections import OrderedDict, deque
from dataclasses import dataclass

import fitz
from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolBar,
    QWidget,
)

PAGE_GAP = 8
TILE_SIZE = 640
CACHE_LIMIT_BYTES = None
DISK_CACHE_ROOT = os.path.join(tempfile.gettempdir(), "anki_pdf_tile_cache")
SETTINGS_PATH = os.path.join(tempfile.gettempdir(), "anki_pdf_tile_viewer_settings.txt")
MAX_RENDER_QUEUE = 20000
AUTO_LOAD_FULL_PDF = False
KEEP_FULL_PDF_IN_RAM = True
RENDER_VIEWPORT_FRACTION = 0.80


@dataclass(frozen=True)
class TileRequest:
    version: int
    key: tuple
    page_num: int
    zoom: float
    clip: tuple


class TileRenderThread(QThread):
    tile_ready = pyqtSignal(int, object, object, float)
    render_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        import threading

        self._cv = threading.Condition()
        self._path = ""
        self._version = 0
        self._queue = deque()
        self._queued_keys = set()
        self._stop = False

    def set_document(self, path: str, version: int):
        with self._cv:
            self._path = os.path.abspath(path) if path else ""
            self._version = int(version)
            self._queue.clear()
            self._queued_keys.clear()
            self._cv.notify_all()

    def request_tiles(self, requests: list[TileRequest]):
        if not requests:
            return
        with self._cv:
            current = self._version
            added = 0
            # Latest visible tiles should jump ahead of old background work.
            for req in reversed(requests[:96]):
                if req.version != current:
                    continue
                if req.key in self._queued_keys:
                    continue
                self._queue.appendleft(req)
                self._queued_keys.add(req.key)
                added += 1
            while len(self._queue) > MAX_RENDER_QUEUE:
                old = self._queue.pop()
                self._queued_keys.discard(old.key)
            if added:
                self._cv.notify_all()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def run(self):
        doc = None
        active_path = ""
        active_version = -1

        while True:
            with self._cv:
                while (
                    not self._stop
                    and not self._queue
                    and active_version == self._version
                ):
                    self._cv.wait()
                if self._stop:
                    break

                if active_version != self._version or active_path != self._path:
                    if doc is not None:
                        try:
                            doc.close()
                        except Exception:
                            pass
                    doc = None
                    active_path = self._path
                    active_version = self._version
                    self._queue.clear()
                    self._queued_keys.clear()

                if not active_path:
                    continue

                if not self._queue:
                    continue
                req = self._queue.popleft()
                self._queued_keys.discard(req.key)

            if req.version != active_version:
                continue

            try:
                if doc is None:
                    doc = fitz.open(active_path)
                    if doc.is_encrypted:
                        self.render_error.emit("PDF is password protected.")
                        continue

                if req.page_num < 0 or req.page_num >= len(doc):
                    continue

                t0 = time.perf_counter()
                page = doc.load_page(req.page_num)
                mat = fitz.Matrix(req.zoom, req.zoom)
                clip = fitz.Rect(*req.clip)
                pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False, annots=False)

                # Direct raw pixels: no PNG encode/decode round trip.
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format_RGB888,
                ).copy()
                self.tile_ready.emit(
                    req.version, req.key, img, (time.perf_counter() - t0) * 1000
                )
            except Exception as ex:
                self.render_error.emit(str(ex))

        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


class PdfTileCanvas(QWidget):
    page_changed = pyqtSignal(int, int)
    stats_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

        self._path = ""
        self._doc_cache_id = ""
        self._version = 0
        self._page_sizes: list[tuple[float, float]] = []
        self._page_rects: list[QRect] = []
        self._zoom = 1.5
        self._render_zoom = 1.5
        self._cache: OrderedDict[tuple, tuple[QPixmap, int]] = OrderedDict()
        self._cache_bytes = 0
        self._requested = set()
        self._pending_requests: list[TileRequest] = []
        self._preload_all_queue = deque()
        self._disk_hits_this_paint = 0
        self._last_stats_at = 0.0

        self._submit_timer = QTimer(self)
        self._submit_timer.setSingleShot(True)
        self._submit_timer.timeout.connect(self._submit_pending_requests)

        self._preload_timer = QTimer(self)
        self._preload_timer.setInterval(40)
        self._preload_timer.timeout.connect(self._submit_preload_batch)

        self._render_thread = TileRenderThread(self)
        self._render_thread.tile_ready.connect(self._on_tile_ready)
        self._render_thread.render_error.connect(self._on_render_error)
        self._render_thread.start()

    def close(self):
        self._render_thread.stop()
        self._render_thread.wait(1000)
        super().close()

    def load_pdf(self, path: str):
        path = os.path.abspath(path)
        doc = None
        try:
            doc = fitz.open(path)
            if doc.is_encrypted:
                raise RuntimeError("PDF is password protected.")
            sizes = []
            for i in range(len(doc)):
                rect = doc.load_page(i).rect
                sizes.append((float(rect.width), float(rect.height)))
        finally:
            if doc is not None:
                doc.close()

        self._path = path
        self._doc_cache_id = self._make_doc_cache_id(path)
        self._version += 1
        self._page_sizes = sizes
        self._cache.clear()
        self._cache_bytes = 0
        self._requested.clear()
        self._pending_requests.clear()
        self._preload_all_queue.clear()
        self._preload_timer.stop()
        self._render_thread.set_document(path, self._version)
        self._relayout()
        self.update()

    def clear_disk_cache(self):
        root = self._doc_cache_dir()
        if not root or not os.path.isdir(root):
            self.stats_changed.emit("no disk cache for this PDF")
            return
        removed = 0
        for name in os.listdir(root):
            path = os.path.join(root, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        self._cache.clear()
        self._cache_bytes = 0
        self._requested.clear()
        self._preload_all_queue.clear()
        self._preload_timer.stop()
        self.update()
        self.stats_changed.emit(f"cleared {removed} cached tiles")

    def load_all_pages(self):
        if not self._path or not self._page_rects:
            self.stats_changed.emit("open a PDF first")
            return

        # Reload is the only time we render at a new quality. Zooming only scales
        # these locked-in tiles until the user chooses Reload again.
        self._version += 1
        self._render_zoom = self._zoom
        self._cache.clear()
        self._cache_bytes = 0
        self._requested.clear()
        self._pending_requests.clear()
        self._preload_all_queue.clear()
        self._preload_timer.stop()
        self._render_thread.set_document(self._path, self._version)

        disk_loaded = self._load_all_cached_tiles_from_disk()
        queued = 0
        skipped = 0
        for page_num in range(len(self._page_sizes)):
            render_w, render_h = self._render_page_pixel_size(page_num)
            cols, rows = self._render_tile_counts(page_num)
            for ty in range(rows):
                for tx in range(cols):
                    key = self._tile_key(page_num, tx, ty)
                    if key in self._cache or key in self._requested:
                        skipped += 1
                        continue
                    x = tx * TILE_SIZE
                    y = ty * TILE_SIZE
                    w = min(TILE_SIZE, render_w - x)
                    h = min(TILE_SIZE, render_h - y)
                    if w <= 0 or h <= 0:
                        continue
                    x0 = x / self._render_zoom
                    y0 = y / self._render_zoom
                    x1 = min((x + w) / self._render_zoom, self._page_sizes[page_num][0])
                    y1 = min((y + h) / self._render_zoom, self._page_sizes[page_num][1])
                    self._requested.add(key)
                    self._preload_all_queue.append(
                        TileRequest(
                            self._version,
                            key,
                            page_num,
                            self._render_zoom,
                            (x0, y0, x1, y1),
                        )
                    )
                    queued += 1
        if queued:
            self._preload_timer.start()
            self.stats_changed.emit(
                f"full load: disk {disk_loaded} tiles, render {queued}, skipped {skipped}; "
                f"RAM {self._cache_bytes / 1024 / 1024:.0f}MB"
            )
        else:
            self.stats_changed.emit(
                f"full load ready from cache: disk {disk_loaded} tiles | "
                f"RAM {self._cache_bytes / 1024 / 1024:.0f}MB"
            )
        self.update()

    def _submit_preload_batch(self):
        if not self._preload_all_queue:
            self._preload_timer.stop()
            self.stats_changed.emit(
                f"full PDF queued complete | RAM {self._cache_bytes / 1024 / 1024:.0f}MB"
            )
            return
        batch = []
        while self._preload_all_queue and len(batch) < 48:
            req = self._preload_all_queue.popleft()
            if req.version == self._version:
                batch.append(req)
        if batch:
            self._render_thread.request_tiles(batch)
        self.stats_changed.emit(
            f"full load remaining {len(self._preload_all_queue)} tiles | RAM {self._cache_bytes / 1024 / 1024:.0f}MB"
        )

    def set_zoom(self, zoom: float, anchor: QPoint | None = None):
        if not self._page_sizes:
            return
        zoom = max(0.25, min(zoom, 5.0))
        if abs(zoom - self._zoom) < 0.001:
            return

        old_zoom = self._zoom
        self._zoom = zoom

        sc = self._scroll_area()
        anchor_page = None
        anchor_ratio = 0.0
        if sc is not None:
            y = sc.verticalScrollBar().value() + (
                anchor.y() if anchor else sc.viewport().height() // 2
            )
            for idx, rect in enumerate(self._page_rects):
                if rect.top() <= y <= rect.bottom():
                    anchor_page = idx
                    anchor_ratio = (y - rect.top()) / max(rect.height(), 1)
                    break

        self._relayout()

        if (
            sc is not None
            and anchor_page is not None
            and anchor_page < len(self._page_rects)
        ):
            new_rect = self._page_rects[anchor_page]
            new_y = int(new_rect.top() + anchor_ratio * new_rect.height())
            sc.verticalScrollBar().setValue(max(0, new_y - sc.viewport().height() // 2))
        self.update()
        self.stats_changed.emit(
            f"visual zoom {old_zoom:.2f} -> {self._zoom:.2f}; press Reload for sharp tiles"
        )

    def zoom(self) -> float:
        return self._zoom

    def fit_width(self):
        if not self._page_sizes:
            return
        sc = self._scroll_area()
        viewport_w = sc.viewport().width() if sc else self.width()
        max_page_w = max(w for w, _h in self._page_sizes)
        usable_w = max(1, int(viewport_w * RENDER_VIEWPORT_FRACTION) - (PAGE_GAP * 2) - 2)
        self.set_zoom(max(0.25, usable_w / max_page_w))

    def scroll_to_page(self, page_num: int):
        if not self._page_rects:
            return
        page_num = max(0, min(page_num, len(self._page_rects) - 1))
        sc = self._scroll_area()
        if sc is not None:
            sc.verticalScrollBar().setValue(self._page_rects[page_num].top())

    def page_count(self) -> int:
        return len(self._page_rects)

    def current_page_index(self, scroll_value: int | None = None) -> int:
        if not self._page_rects:
            return 0
        if scroll_value is None:
            sc = self._scroll_area()
            scroll_value = sc.verticalScrollBar().value() if sc is not None else 0
        marker = max(0, int(scroll_value) + 1)
        for idx, rect in enumerate(self._page_rects):
            if rect.top() <= marker <= rect.bottom():
                return idx
            if marker < rect.top():
                return max(0, idx - 1)
        return len(self._page_rects) - 1

    def _scroll_area(self):
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parent()
        return None

    def _relayout(self):
        rects = []
        y = PAGE_GAP
        max_w = 1
        for w_pt, h_pt in self._page_sizes:
            w = max(1, int(round(w_pt * self._zoom)))
            h = max(1, int(round(h_pt * self._zoom)))
            rects.append(QRect(PAGE_GAP, y, w, h))
            y += h + PAGE_GAP
            max_w = max(max_w, w + PAGE_GAP * 2)
        self._page_rects = rects
        self.setMinimumSize(max_w, max(1, y))
        self.resize(max_w, max(1, y))

    def _visible_rect(self) -> QRect:
        sc = self._scroll_area()
        if sc is None:
            return self.rect()
        return QRect(
            sc.horizontalScrollBar().value(),
            sc.verticalScrollBar().value(),
            sc.viewport().width(),
            sc.viewport().height(),
        )

    def _tile_key(self, page_num: int, tx: int, ty: int) -> tuple:
        return (self._version, page_num, round(self._render_zoom, 3), tx, ty, TILE_SIZE)

    def _render_page_pixel_size(self, page_num: int) -> tuple[int, int]:
        w_pt, h_pt = self._page_sizes[page_num]
        return (
            max(1, int(round(w_pt * self._render_zoom))),
            max(1, int(round(h_pt * self._render_zoom))),
        )

    def _render_tile_counts(self, page_num: int) -> tuple[int, int]:
        render_w, render_h = self._render_page_pixel_size(page_num)
        return (
            max(1, (render_w + TILE_SIZE - 1) // TILE_SIZE),
            max(1, (render_h + TILE_SIZE - 1) // TILE_SIZE),
        )

    def _tile_display_rect(
        self, page_num: int, tx: int, ty: int, render_w: int | None = None, render_h: int | None = None
    ) -> QRect:
        page_rect = self._page_rects[page_num]
        page_render_w, page_render_h = self._render_page_pixel_size(page_num)
        if render_w is None:
            render_w = min(TILE_SIZE, page_render_w - tx * TILE_SIZE)
        if render_h is None:
            render_h = min(TILE_SIZE, page_render_h - ty * TILE_SIZE)
        ratio = self._zoom / max(self._render_zoom, 0.001)
        return QRect(
            int(round(page_rect.left() + tx * TILE_SIZE * ratio)),
            int(round(page_rect.top() + ty * TILE_SIZE * ratio)),
            max(1, int(round(max(1, render_w) * ratio))),
            max(1, int(round(max(1, render_h) * ratio))),
        )

    def _make_doc_cache_id(self, path: str) -> str:
        try:
            st = os.stat(path)
            raw = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}".encode(
                "utf-8", errors="replace"
            )
        except OSError:
            raw = os.path.abspath(path).encode("utf-8", errors="replace")
        return hashlib.sha1(raw).hexdigest()[:24]

    def _doc_cache_dir(self) -> str:
        if not self._doc_cache_id:
            return ""
        return os.path.join(DISK_CACHE_ROOT, self._doc_cache_id)

    def _disk_tile_path(self, page_num: int, tx: int, ty: int) -> str:
        root = self._doc_cache_dir()
        zoom_key = int(round(self._render_zoom * 1000))
        return os.path.join(
            root, f"p{page_num:05d}_z{zoom_key:05d}_x{tx:04d}_y{ty:04d}.png"
        )

    def _load_tile_from_disk(self, page_num: int, tx: int, ty: int):
        path = self._disk_tile_path(page_num, tx, ty)
        if not path or not os.path.exists(path):
            return None
        key = self._tile_key(page_num, tx, ty)
        cached = self._cache.get(key)
        if cached:
            self._cache.move_to_end(key)
            return cached[0]
        pix = QPixmap(path)
        if pix.isNull():
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        size = pix.width() * pix.height() * 4
        self._cache[key] = (pix, size)
        self._cache_bytes += size
        self._evict_cache()
        self._disk_hits_this_paint += 1
        return pix

    def _load_all_cached_tiles_from_disk(self) -> int:
        loaded = 0
        for page_num in range(len(self._page_sizes)):
            cols, rows = self._render_tile_counts(page_num)
            for ty in range(rows):
                for tx in range(cols):
                    key = self._tile_key(page_num, tx, ty)
                    if key in self._cache:
                        continue
                    if self._load_tile_from_disk(page_num, tx, ty):
                        loaded += 1
        return loaded

    def _save_tile_to_disk(self, page_num: int, tx: int, ty: int, image: QImage):
        root = self._doc_cache_dir()
        if not root or image.isNull():
            return
        try:
            os.makedirs(root, exist_ok=True)
            path = self._disk_tile_path(page_num, tx, ty)
            tmp = f"{path}.tmp"
            if image.save(tmp, "PNG"):
                os.replace(tmp, path)
            elif os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

    def _queue_tile(self, page_num: int, tx: int, ty: int, display_tile: QRect):
        key = self._tile_key(page_num, tx, ty)
        if key in self._cache or key in self._requested:
            return
        page_rect = self._page_rects[page_num]
        x0 = tx * TILE_SIZE / self._zoom
        y0 = ty * TILE_SIZE / self._zoom
        x1 = min(
            (tx * TILE_SIZE + display_tile.width()) / self._zoom,
            self._page_sizes[page_num][0],
        )
        y1 = min(
            (ty * TILE_SIZE + display_tile.height()) / self._zoom,
            self._page_sizes[page_num][1],
        )
        if x1 <= x0 or y1 <= y0:
            return
        self._requested.add(key)
        self._pending_requests.append(
            TileRequest(
                self._version,
                key,
                page_num,
                self._zoom,
                (x0, y0, x1, y1),
            )
        )
        if not self._submit_timer.isActive():
            self._submit_timer.start(0)

    def _submit_pending_requests(self):
        if not self._pending_requests:
            return
        reqs = self._pending_requests
        self._pending_requests = []
        self._render_thread.request_tiles(reqs)

    def _on_tile_ready(self, version: int, key: tuple, image: QImage, render_ms: float):
        if version != self._version or image.isNull():
            return
        self._requested.discard(key)
        pix = QPixmap.fromImage(image)
        if pix.isNull():
            return

        size = pix.width() * pix.height() * 4
        old = self._cache.pop(key, None)
        if old:
            self._cache_bytes -= old[1]
        self._cache[key] = (pix, size)
        self._cache_bytes += size
        self._evict_cache()

        _version, page_num, _zoom, tx, ty, _tile_size = key
        self._save_tile_to_disk(page_num, tx, ty, image)
        dirty = self._tile_display_rect(page_num, tx, ty, pix.width(), pix.height())
        self.update(dirty.adjusted(-2, -2, 2, 2))

        now = time.perf_counter()
        if now - self._last_stats_at > 0.25:
            self._last_stats_at = now
            self.stats_changed.emit(
                f"tile p.{page_num + 1} {pix.width()}x{pix.height()} in {render_ms:.0f}ms | "
                f"cache {self._cache_bytes / 1024 / 1024:.0f}MB"
            )

    def _on_render_error(self, message: str):
        self.stats_changed.emit(f"render error: {message}")

    def _evict_cache(self):
        if CACHE_LIMIT_BYTES is None:
            return
        if KEEP_FULL_PDF_IN_RAM:
            return
        visible = self._visible_rect().adjusted(
            -TILE_SIZE, -TILE_SIZE, TILE_SIZE, TILE_SIZE
        )
        while self._cache_bytes > CACHE_LIMIT_BYTES and self._cache:
            victim_key = None
            for key in self._cache.keys():
                _version, page_num, _zoom, tx, ty, _tile_size = key
                if page_num >= len(self._page_rects):
                    victim_key = key
                    break
                page_rect = self._page_rects[page_num]
                tile_rect = QRect(
                    page_rect.left() + tx * TILE_SIZE,
                    page_rect.top() + ty * TILE_SIZE,
                    TILE_SIZE,
                    TILE_SIZE,
                )
                if not tile_rect.intersects(visible):
                    victim_key = key
                    break
            if victim_key is None:
                victim_key = next(iter(self._cache))
            _pix, size = self._cache.pop(victim_key)
            self._cache_bytes -= size

    def paintEvent(self, event):
        p = QPainter(self)
        clip = event.rect()
        p.fillRect(clip, QColor("#20202A"))
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        visible = self._visible_rect()
        first_visible = -1
        last_visible = -1
        self._disk_hits_this_paint = 0

        for page_num, page_rect in enumerate(self._page_rects):
            if page_rect.bottom() < clip.top():
                continue
            if page_rect.top() > clip.bottom():
                break

            if page_rect.intersects(visible):
                if first_visible < 0:
                    first_visible = page_num
                last_visible = page_num

            p.fillRect(page_rect, Qt.white)
            p.setPen(QPen(QColor("#A6A6B8"), 1))
            p.drawRect(page_rect.adjusted(0, 0, -1, -1))

            page_clip = page_rect.intersected(clip)
            if page_clip.isEmpty():
                continue

            local_clip = page_clip.translated(-page_rect.left(), -page_rect.top())
            ratio = self._zoom / max(self._render_zoom, 0.001)
            render_clip_left = int(local_clip.left() / ratio)
            render_clip_top = int(local_clip.top() / ratio)
            render_clip_right = int(local_clip.right() / ratio)
            render_clip_bottom = int(local_clip.bottom() / ratio)
            cols, rows = self._render_tile_counts(page_num)
            tx0 = max(0, min(cols - 1, render_clip_left // TILE_SIZE))
            ty0 = max(0, min(rows - 1, render_clip_top // TILE_SIZE))
            tx1 = max(0, min(cols - 1, render_clip_right // TILE_SIZE))
            ty1 = max(0, min(rows - 1, render_clip_bottom // TILE_SIZE))
            page_render_w, page_render_h = self._render_page_pixel_size(page_num)

            for ty in range(ty0, ty1 + 1):
                for tx in range(tx0, tx1 + 1):
                    x = tx * TILE_SIZE
                    y = ty * TILE_SIZE
                    w = min(TILE_SIZE, page_render_w - x)
                    h = min(TILE_SIZE, page_render_h - y)
                    if w <= 0 or h <= 0:
                        continue
                    tile_rect = self._tile_display_rect(page_num, tx, ty, w, h)
                    if not tile_rect.intersects(clip):
                        continue

                    key = self._tile_key(page_num, tx, ty)
                    entry = self._cache.get(key)
                    if entry:
                        pix, size = entry
                        self._cache.move_to_end(key)
                        p.drawPixmap(tile_rect, pix, pix.rect())
                    else:
                        pix = self._load_tile_from_disk(page_num, tx, ty)
                        if pix:
                            p.drawPixmap(tile_rect, pix, pix.rect())
                        else:
                            p.fillRect(tile_rect, QColor("#FAFAFA"))

            p.setPen(QPen(QColor("#72728A"), 1))
            p.drawText(
                page_rect.adjusted(8, 8, -8, -8),
                Qt.AlignTop | Qt.AlignRight,
                f"p.{page_num + 1}",
            )

        p.end()

        if self._disk_hits_this_paint:
            now = time.perf_counter()
            if now - self._last_stats_at > 0.25:
                self._last_stats_at = now
                self.stats_changed.emit(
                    f"disk cache hit {self._disk_hits_this_paint} tile(s) | "
                    f"RAM {self._cache_bytes / 1024 / 1024:.0f}MB"
                )

        if first_visible >= 0:
            self.page_changed.emit(first_visible + 1, len(self._page_rects))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self._zoom * factor, event.pos())
            event.accept()
            return
        super().wheelEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, initial_pdf: str = ""):
        super().__init__()
        self.setWindowTitle("Temp Sumatra-Style Tile PDF Viewer")
        self.resize(1280, 850)
        self._ui_page_zero = 0

        self.canvas = PdfTileCanvas(self)
        self.scroll = QScrollArea(self)
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.verticalScrollBar().valueChanged.connect(
            lambda _v: self.canvas.update()
        )
        self.scroll.horizontalScrollBar().valueChanged.connect(
            lambda _v: self.canvas.update()
        )
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.setCentralWidget(self.scroll)

        self.lbl_page = QLabel("No PDF")
        self.lbl_status = QLabel("Open a PDF to test tile rendering")
        self.canvas.page_changed.connect(self._on_canvas_page_changed)
        self.canvas.stats_changed.connect(self.lbl_status.setText)

        tb = QToolBar("PDF")
        tb.setMovable(False)
        self.addToolBar(tb)

        act_open = QAction("Open PDF", self)
        act_open.triggered.connect(self.open_pdf)
        tb.addAction(act_open)

        act_fit = QAction("Fit 80%", self)
        act_fit.triggered.connect(self.canvas.fit_width)
        tb.addAction(act_fit)

        act_clear_cache = QAction("Clear Cache", self)
        act_clear_cache.triggered.connect(self.canvas.clear_disk_cache)
        tb.addAction(act_clear_cache)

        act_reload = QAction("Reload", self)
        act_reload.triggered.connect(self.canvas.load_all_pages)
        tb.addAction(act_reload)

        act_zoom_out = QAction("Zoom -", self)
        act_zoom_out.triggered.connect(
            lambda: self.canvas.set_zoom(self.canvas.zoom() / 1.2)
        )
        tb.addAction(act_zoom_out)

        act_zoom_in = QAction("Zoom +", self)
        act_zoom_in.triggered.connect(
            lambda: self.canvas.set_zoom(self.canvas.zoom() * 1.2)
        )
        tb.addAction(act_zoom_in)

        tb.addSeparator()
        self.btn_prev_page = QPushButton("←")
        self.btn_prev_page.setToolTip("Previous page")
        self.btn_prev_page.clicked.connect(self._go_prev_page)
        tb.addWidget(self.btn_prev_page)

        self.btn_next_page = QPushButton("→")
        self.btn_next_page.setToolTip("Next page")
        self.btn_next_page.clicked.connect(self._go_next_page)
        tb.addWidget(self.btn_next_page)

        self.page_jump = QLineEdit()
        self.page_jump.setFixedWidth(52)
        self.page_jump.setAlignment(Qt.AlignCenter)
        self.page_jump.setPlaceholderText("1")
        self.page_jump.returnPressed.connect(self._jump_to_page_from_input)
        tb.addWidget(self.page_jump)

        self.lbl_page_total = QLabel("/ 0")
        tb.addWidget(self.lbl_page_total)
        tb.addSeparator()
        tb.addWidget(self.lbl_page)
        tb.addSeparator()
        tb.addWidget(self.lbl_status)
        self._set_page_ui(0)

        remembered_pdf = initial_pdf or self._load_last_pdf_path()
        if remembered_pdf:
            QTimer.singleShot(0, lambda p=remembered_pdf: self.load_pdf(p))

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key_Left
            and event.modifiers() == Qt.NoModifier
            and not event.isAutoRepeat()
        ):
            self._go_prev_page()
            event.accept()
            return
        if (
            event.key() == Qt.Key_Right
            and event.modifiers() == Qt.NoModifier
            and not event.isAutoRepeat()
        ):
            self._go_next_page()
            event.accept()
            return
        if event.key() == Qt.Key_F11:
            self.setWindowState(self.windowState() ^ Qt.WindowFullScreen)
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showMaximized()
            event.accept()
            return
        super().keyPressEvent(event)

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", os.path.expanduser("~"), "PDF files (*.pdf)"
        )
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str):
        try:
            self.lbl_status.setText("loading layout...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.canvas.load_pdf(path)
            self._save_last_pdf_path(path)
            QApplication.restoreOverrideCursor()
            self.lbl_status.setText(f"loaded: {os.path.basename(path)}")
            self._set_page_ui(0)
            QTimer.singleShot(0, self._fit_and_reload)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "PDF Load Failed", str(ex))

    def _fit_and_reload(self):
        self.canvas.fit_width()
        self.canvas.load_all_pages()
        self._set_page_ui(self.canvas.current_page_index())

    def _debug_nav(self, action: str, **data):
        parts = " ".join(f"{key}={value}" for key, value in data.items())
        print(f"[DEBUG][temp_nav] {action} {parts}".rstrip())

    def _set_page_ui(self, current_zero: int):
        total = self.canvas.page_count()
        if total <= 0:
            self._ui_page_zero = 0
            self.btn_prev_page.setEnabled(False)
            self.btn_next_page.setEnabled(False)
            self.page_jump.setEnabled(False)
            self.page_jump.clear()
            self.lbl_page_total.setText("/ 0")
            self.lbl_page.setText("No PDF")
            return
        current_zero = max(0, min(int(current_zero), total - 1))
        self._ui_page_zero = current_zero
        self.btn_prev_page.setEnabled(current_zero > 0)
        self.btn_next_page.setEnabled(current_zero < total - 1)
        self.page_jump.setEnabled(True)
        self.page_jump.setText(str(current_zero + 1))
        self.lbl_page_total.setText(f"/ {total}")
        self.lbl_page.setText(f"p.{current_zero + 1} / {total}")

    def _on_canvas_page_changed(self, page_one: int, total: int):
        self._set_page_ui(page_one - 1)

    def _on_scroll_changed(self, value: int):
        page_zero = self.canvas.current_page_index(value)
        if page_zero != self._ui_page_zero:
            self._debug_nav("scroll", value=value, page=page_zero + 1)
        self._set_page_ui(page_zero)

    def _go_to_page(self, page_zero: int):
        total = self.canvas.page_count()
        if total <= 0:
            return
        page_zero = max(0, min(int(page_zero), total - 1))
        self._debug_nav("goto", target=page_zero + 1, current=self._ui_page_zero + 1)
        self._set_page_ui(page_zero)
        self.canvas.scroll_to_page(page_zero)
        QTimer.singleShot(0, lambda pg=page_zero: self.canvas.scroll_to_page(pg))

    def _go_prev_page(self):
        self._go_to_page(self._ui_page_zero - 1)

    def _go_next_page(self):
        self._go_to_page(self._ui_page_zero + 1)

    def _jump_to_page_from_input(self):
        try:
            page_one = int((self.page_jump.text() or "1").strip())
        except ValueError:
            self._set_page_ui(self.canvas.current_page_index())
            return
        self._go_to_page(page_one - 1)

    def _load_last_pdf_path(self) -> str:
        try:
            if not os.path.exists(SETTINGS_PATH):
                return ""
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                path = f.read().strip()
            return path if path and os.path.exists(path) else ""
        except OSError:
            return ""

    def _save_last_pdf_path(self, path: str):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                f.write(os.path.abspath(path))
        except OSError:
            pass

    def closeEvent(self, event):
        self.canvas.close()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    initial = sys.argv[1] if len(sys.argv) > 1 else ""
    win = MainWindow(initial)
    win.showFullScreen()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
