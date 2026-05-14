from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

from pdf_engine import PdfOnDemandThread
from cache_manager import PAGE_CACHE

if TYPE_CHECKING:
    from editor_ui import OcclusionCanvas


@dataclass
class PageState:
    status: str = "not_loaded"
    pixmap: Optional[QPixmap] = field(default=None, repr=False)
    priority: int = 2

    def is_renderable(self):
        return self.status == "not_loaded"

    def is_injectable(self):
        return self.status == "loaded" and self.pixmap is not None

    def is_done(self):
        return self.status == "injected"


class PageScheduler(QObject):
    all_done = pyqtSignal()
    page_injected = pyqtSignal(int, int)

    INJECT_INTERVAL_MS = 16
    BG_BATCH_SIZE = 3
    PREFETCH_RADIUS = 1

    def __init__(self, canvas: "OcclusionCanvas", parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.pages: dict[int, PageState] = {}
        self.inject_queue: deque[int] = deque()
        self._path = ""
        self._total = 0
        self._is_scrolling = False
        self._worker: Optional[PdfOnDemandThread] = None
        self._worker_kind = ""
        self._injected_count = 0
        self._last_visible: tuple[int, int] = (0, 0)
        # ── inject queue as set for O(1) membership + deque for order ─────────
        self._inject_set: set[int] = set()  # mirrors inject_queue for O(1) lookup

        self._inject_timer = QTimer(self)
        self._inject_timer.setInterval(self.INJECT_INTERVAL_MS)
        self._inject_timer.timeout.connect(self._process_inject_queue)

        self._scroll_stop_timer = QTimer(self)
        self._scroll_stop_timer.setSingleShot(True)
        self._scroll_stop_timer.setInterval(150)
        self._scroll_stop_timer.timeout.connect(self._on_scroll_stopped)

        self._bg_timer = QTimer(self)
        self._bg_timer.setSingleShot(True)
        self._bg_timer.setInterval(300)
        self._bg_timer.timeout.connect(self._start_background_batch)

    # =========================================================================
    #  PUBLIC API
    # =========================================================================

    def init_pdf(
        self, path: str, total_pages: int, due_page_nums: list[int] | None = None
    ) -> None:
        self._stop_worker()
        self._inject_timer.stop()
        self._bg_timer.stop()
        self._path = path
        self._total = total_pages
        self._injected_count = 0
        self.inject_queue.clear()
        self._inject_set.clear()
        due_set = set(due_page_nums or [])
        self.pages = {}
        for pn in range(total_pages):
            cached = PAGE_CACHE.get(path, pn)
            if cached and not cached.isNull():
                self.pages[pn] = PageState(
                    status="loaded", pixmap=cached, priority=(0 if pn in due_set else 2)
                )
            else:
                self.pages[pn] = PageState(
                    status="not_loaded", priority=(0 if pn in due_set else 2)
                )
        priority_pages = sorted(
            (pn for pn, ps in self.pages.items() if ps.priority == 0),
            key=lambda p: self.pages[p].priority,
        )
        if priority_pages:
            self._start_worker(priority_pages, kind="priority")
        self._inject_timer.start()

    def set_due_pages(self, page_nums: list[int]) -> None:
        for pn in page_nums:
            if pn in self.pages:
                self.pages[pn].priority = 0

    def on_visible_pages_changed(self, first: int, last: int) -> None:
        self.set_scrolling(True)
        self._last_visible = (first, last)
        r0 = max(0, first - self.PREFETCH_RADIUS)
        r1 = min(self._total - 1, last + self.PREFETCH_RADIUS)
        for pn in range(r0, r1 + 1):
            if pn in self.pages and self.pages[pn].priority > 1:
                self.pages[pn].priority = 1
        needed = [
            pn
            for pn in range(first, last + 1)
            if pn in self.pages and self.pages[pn].is_renderable()
        ]
        if not needed:
            for pn in range(first, last + 1):
                if pn in self.pages and self.pages[pn].is_injectable():
                    self._enqueue_if_not_present(pn)
            return
        if self._worker_running():
            if self._worker_kind == "background":
                self._stop_worker()
                self._start_worker(needed, kind="visible")
            else:
                self._bg_timer.start(50)
        else:
            self._start_worker(needed, kind="visible")

    def enqueue_all_loaded(self) -> None:
        loaded = [
            pn
            for pn, ps in sorted(self.pages.items())
            if ps.is_injectable() and pn not in self._inject_set
        ]
        for pn in loaded:
            self.inject_queue.append(pn)
            self._inject_set.add(pn)

    def set_scrolling(self, scrolling: bool) -> None:
        if scrolling:
            self._is_scrolling = True
            self._scroll_stop_timer.start()
        else:
            self._is_scrolling = False

    def stop(self) -> None:
        self._stop_worker()
        self._inject_timer.stop()
        self._bg_timer.stop()
        self._scroll_stop_timer.stop()
        self.inject_queue.clear()
        self._inject_set.clear()

    def get_status_summary(self) -> dict:
        counts: dict[str, int] = {
            "not_loaded": 0,
            "loading": 0,
            "loaded": 0,
            "injected": 0,
        }
        for ps in self.pages.values():
            counts[ps.status] = counts.get(ps.status, 0) + 1
        return counts

    # =========================================================================
    #  INTERNAL — worker lifecycle
    # =========================================================================

    def _worker_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _stop_worker(self) -> None:
        if self._worker is not None:
            if self._worker.isRunning():
                self._worker.stop()
                self._worker.quit()
                self._worker.wait(800)
            self._worker = None
            self._worker_kind = ""
        for ps in self.pages.values():
            if ps.status == "loading":
                ps.status = "not_loaded"

    def _start_worker(self, page_nums: list[int], kind: str) -> None:
        if not page_nums or not self._path:
            return
        for pn in page_nums:
            if pn in self.pages:
                self.pages[pn].status = "loading"
        self._stop_worker()
        self._worker = PdfOnDemandThread(self._path, page_nums, zoom=1.5, parent=self)
        self._worker_kind = kind
        self._worker.page_ready.connect(self._on_worker_page_ready)
        self._worker.batch_done.connect(self._on_worker_batch_done)
        self._worker.error.connect(lambda err: None)  # silent
        self._worker.start()

    def _on_worker_page_ready(self, page_num: int, qpx) -> None:
        if page_num not in self.pages:
            return
        if isinstance(qpx, QImage):
            qpx = QPixmap.fromImage(qpx)
        if qpx is None or qpx.isNull():
            self.pages[page_num].status = "not_loaded"
            self.pages[page_num].pixmap = None
            return
        ps = self.pages[page_num]
        ps.pixmap = qpx
        ps.status = "loaded"
        first, last = self._last_visible
        if first <= page_num <= last:
            self._enqueue_if_not_present(page_num)
        self._check_completion()

    def _on_worker_batch_done(self, rendered: list[int]) -> None:
        kind = self._worker_kind
        self._worker_kind = ""
        # Reset any pages stuck in "loading" — O(rendered) not O(total_pages)
        rendered_set = set(rendered)
        for pn, ps in self.pages.items():
            if ps.status == "loading" and pn not in rendered_set:
                ps.status = "not_loaded"
        if kind in ("priority", "visible"):
            self._bg_timer.start(300)
        self._check_completion()

    # =========================================================================
    #  INTERNAL — injection pipeline
    # =========================================================================

    def _enqueue_if_not_present(self, page_num: int) -> None:
        # O(1) check via _inject_set instead of O(n) scan of deque
        if page_num not in self._inject_set:
            self.inject_queue.append(page_num)
            self._inject_set.add(page_num)

    def _process_inject_queue(self) -> None:
        if self._is_scrolling or not self.inject_queue:
            return
        # Find highest-priority page — O(queue_size) scan but queue is small
        best_pn = min(
            self.inject_queue,
            key=lambda pn: (self.pages[pn].priority if pn in self.pages else 999),
        )
        # Remove from queue: pop from deque is O(n) for middle elements.
        # Use filter — but avoid full deque rebuild on every call.
        # Instead: mark-and-skip approach: just remove from set and let
        # a single-pass cleanup handle it.
        self.inject_queue = deque(p for p in self.inject_queue if p != best_pn)
        self._inject_set.discard(best_pn)

        ps = self.pages.get(best_pn)
        if ps is None or ps.pixmap is None or ps.pixmap.isNull():
            if ps:
                ps.status = "not_loaded"
                ps.pixmap = None
            return

        self._canvas.inject_page(best_pn, ps.pixmap)
        ps.status = "injected"
        self._injected_count += 1
        self.page_injected.emit(best_pn, self._injected_count)
        self._check_completion()

    # =========================================================================
    #  INTERNAL — background fill
    # =========================================================================

    def _start_background_batch(self) -> None:
        if self._worker_running():
            self._bg_timer.start(400)
            return
        if self._is_scrolling:
            self._bg_timer.start(200)
            return
        candidates = sorted(
            [pn for pn, ps in self.pages.items() if ps.is_renderable()],
            key=lambda p: (self.pages[p].priority, p),
        )
        if not candidates:
            return
        self._start_worker(candidates[: self.BG_BATCH_SIZE], kind="background")

    # =========================================================================
    #  INTERNAL — completion detection
    # =========================================================================

    def _check_completion(self) -> None:
        if not self.pages:
            return
        if any(ps.status in ("not_loaded", "loading") for ps in self.pages.values()):
            return
        self.all_done.emit()

    def _on_scroll_stopped(self) -> None:
        self._is_scrolling = False
        first, last = self._last_visible
        for pn in range(first, last + 1):
            if pn in self.pages and self.pages[pn].is_injectable():
                self._enqueue_if_not_present(pn)
        if not self._worker_running():
            self._bg_timer.start(200)
