# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE SCHEDULER  —  State-Based Priority Loader  (v1)
#
#  PURPOSE
#  -------
#  Replaces the ad-hoc _ondemand_thread / _bg_pending_inserts / _bg_accept_mode
#  tangle in ReviewScreen with a single, testable state machine.
#
#  ARCHITECTURE
#  ─────────────
#
#   ┌──────────────────────────────────────────────────────────────────────────┐
#   │  PageScheduler (lives on GUI thread)                                     │
#   │                                                                          │
#   │  self.pages : dict[int → PageState]   — O(1) status + priority lookup   │
#   │  self.inject_queue : deque[int]       — pages ready to be injected       │
#   │                                                                          │
#   │  QTimer (16 ms)                                                          │
#   │    └─► process_inject_queue()         — injects ONE page per tick        │
#   │                                                                          │
#   │  PdfOnDemandThread (worker)                                              │
#   │    page_ready  ──► _on_worker_page_ready()   (store in PageState, never  │
#   │    batch_done  ──► _on_worker_batch_done()    inject directly)           │
#   └──────────────────────────────────────────────────────────────────────────┘
#
#  PAGE STATUS LIFECYCLE
#  ─────────────────────
#  not_loaded  →  loading  →  loaded  →  injected
#                              │
#                    inject_queue picks it up (status == "loaded")
#                    QTimer calls inject_page(), sets status = "injected"
#
#  PRIORITY VALUES
#  ───────────────
#   0  — pages with masks due today (set externally by caller)
#   1  — current visible page ±1 neighbours
#   2  — all other pages (background fill)
#
#  CONSTRAINTS  (identical to the spec)
#  ────────────────────────────────────
#   • Worker thread NEVER calls inject_page() — only stores QPixmap + sets "loaded"
#   • update(QRect) only — no full-canvas update() without a rect
#   • Mask and ink layers are untouched
#   • inject_queue processes ONE page per 16-ms tick
#   • While user is scrolling (is_scrolling flag) injection is paused
#
#  INTEGRATION
#  ───────────
#  1. Instantiate in ReviewScreen.__init__:
#       self._scheduler = PageScheduler(canvas=self.canvas, parent=self)
#
#  2. When a PDF is opened / card loaded:
#       self._scheduler.init_pdf(path, total_pages, due_page_nums)
#
#  3. Wire visible_pages_changed signal:
#       self._canvas_scroll.visible_pages_changed.connect(
#           self._scheduler.on_visible_pages_changed)
#
#  4. Wire Accept button:
#       self.btn_accept.clicked.connect(self._scheduler.enqueue_all_loaded)
#
#  5. Wire completion callback:
#       self._scheduler.all_done.connect(self._on_all_pages_done)
#
#  6. Scrolling guard — in ReviewScreen._on_scroll / _note_user_activity:
#       self._scheduler.set_scrolling(True)   # scroll started
#       self._scheduler.set_scrolling(False)  # 150 ms after scroll stopped
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap

from pdf_engine import PdfOnDemandThread
from cache_manager import PAGE_CACHE

if TYPE_CHECKING:
    from editor_ui import OcclusionCanvas


# ─────────────────────────────────────────────────────────────────────────────
#  PageState  —  one slot per PDF page
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PageState:
    """Tracks rendering + injection status for one PDF page."""
    status:   str           = "not_loaded"  # not_loaded | loading | loaded | injected
    pixmap:   Optional[QPixmap] = field(default=None, repr=False)
    priority: int           = 2             # 0=due-today  1=neighbour  2=background

    # ── helpers ──────────────────────────────────────────────────────────────

    def is_renderable(self) -> bool:
        """True when we should ask the worker to render this page."""
        return self.status == "not_loaded"

    def is_injectable(self) -> bool:
        """True when a real pixmap is waiting to be put onto the canvas."""
        return self.status == "loaded" and self.pixmap is not None

    def is_done(self) -> bool:
        """True when the page has already been placed on the canvas."""
        return self.status == "injected"


# ─────────────────────────────────────────────────────────────────────────────
#  PageScheduler
# ─────────────────────────────────────────────────────────────────────────────

class PageScheduler(QObject):
    """
    State-based scheduler that decouples page rendering from canvas injection.

    All public methods are GUI-thread-safe.  The worker thread communicates
    exclusively through Qt signals — it never calls inject_page() directly.
    """

    # Emitted when ALL pages reach "loaded" or "injected" — show Accept button
    all_done = pyqtSignal()

    # Emitted after each successful injection (page_num, pages_injected_so_far)
    page_injected = pyqtSignal(int, int)

    # Inject one page every this many milliseconds (≈ one frame)
    INJECT_INTERVAL_MS = 16

    # Max pages per background-render batch (keeps worker from monopolising CPU)
    BG_BATCH_SIZE = 3

    # How many neighbour pages to prefetch around the visible window
    PREFETCH_RADIUS = 1

    def __init__(self, canvas: "OcclusionCanvas", parent=None):
        super().__init__(parent)
        self._canvas: OcclusionCanvas = canvas

        # ── state ─────────────────────────────────────────────────────────────
        self.pages: dict[int, PageState] = {}       # page_num → PageState
        self.inject_queue: deque[int] = deque()     # pages ready for injection

        # ── runtime ───────────────────────────────────────────────────────────
        self._path: str = ""
        self._total: int = 0
        self._is_scrolling: bool = False
        self._worker: Optional[PdfOnDemandThread] = None
        self._worker_kind: str = ""   # "priority" | "visible" | "background"
        self._injected_count: int = 0
        self._last_visible: tuple[int, int] = (0, 0)

        # ── timers ────────────────────────────────────────────────────────────
        # Injection timer: fires every 16 ms, injects at most one page
        self._inject_timer = QTimer(self)
        self._inject_timer.setInterval(self.INJECT_INTERVAL_MS)
        self._inject_timer.timeout.connect(self._process_inject_queue)

        # Scroll-stop timer: marks scrolling=False after 150 ms of silence
        self._scroll_stop_timer = QTimer(self)
        self._scroll_stop_timer.setSingleShot(True)
        self._scroll_stop_timer.setInterval(150)
        self._scroll_stop_timer.timeout.connect(self._on_scroll_stopped)

        # Background fill timer: starts a small BG batch after idle
        self._bg_timer = QTimer(self)
        self._bg_timer.setSingleShot(True)
        self._bg_timer.setInterval(300)
        self._bg_timer.timeout.connect(self._start_background_batch)

    # =========================================================================
    #  PUBLIC API
    # =========================================================================

    def init_pdf(self, path: str, total_pages: int,
                 due_page_nums: list[int] | None = None) -> None:
        """
        Reset scheduler for a new PDF.

        Parameters
        ----------
        path          : absolute path to the PDF
        total_pages   : total page count
        due_page_nums : pages that have masks due today (get priority 0)
        """
        self._stop_worker()
        self._inject_timer.stop()
        self._bg_timer.stop()

        self._path = path
        self._total = total_pages
        self._injected_count = 0
        self.inject_queue.clear()

        due_set = set(due_page_nums or [])

        self.pages = {}
        for pn in range(total_pages):
            # If already in PAGE_CACHE, mark directly as loaded
            cached = PAGE_CACHE.get(path, pn)
            if cached and not cached.isNull():
                self.pages[pn] = PageState(
                    status="loaded",
                    pixmap=cached,
                    priority=(0 if pn in due_set else 2),
                )
            else:
                self.pages[pn] = PageState(
                    status="not_loaded",
                    priority=(0 if pn in due_set else 2),
                )

        print(f"[SCHED][init] path={os.path.basename(path)}  "
              f"total={total_pages}  due={sorted(due_set)}")

        # Kick off priority-0 pages immediately (masks due today)
        priority_pages = sorted(
            (pn for pn, ps in self.pages.items() if ps.priority == 0),
            key=lambda p: self.pages[p].priority,
        )
        if priority_pages:
            self._start_worker(priority_pages, kind="priority")

        self._inject_timer.start()

    def set_due_pages(self, page_nums: list[int]) -> None:
        """Elevate priority for pages with masks due today (can be called at any time)."""
        for pn in page_nums:
            if pn in self.pages:
                self.pages[pn].priority = 0
        print(f"[SCHED][due] elevated priority-0 for pages {page_nums}")

    def on_visible_pages_changed(self, first: int, last: int) -> None:
        """
        Called by the scroll area's visible_pages_changed signal.

        Marks neighbouring pages as priority-1 and ensures visible+neighbour
        pages are either already loading, already loaded, or queued for render.
        """
        self.set_scrolling(True)   # restart the scroll-stop timer

        self._last_visible = (first, last)

        r0 = max(0, first - self.PREFETCH_RADIUS)
        r1 = min(self._total - 1, last + self.PREFETCH_RADIUS)

        # Elevate priority of visible window + neighbours
        for pn in range(r0, r1 + 1):
            if pn in self.pages:
                if self.pages[pn].priority > 1:
                    self.pages[pn].priority = 1

        # Find pages that are visible and still not rendered
        needed = [
            pn for pn in range(first, last + 1)
            if pn in self.pages and self.pages[pn].is_renderable()
        ]

        if not needed:
            # All visible pages already loaded/injected — enqueue cached ones
            for pn in range(first, last + 1):
                if pn in self.pages and self.pages[pn].is_injectable():
                    self._enqueue_if_not_present(pn)
            return

        print(f"[SCHED][visible] p.{first+1}–p.{last+1}  need render: {[p+1 for p in needed]}")

        if self._worker_running():
            if self._worker_kind == "background":
                # Preempt background render for visible pages
                print("[SCHED][visible] preempting background worker")
                self._stop_worker()
                self._start_worker(needed, kind="visible")
            else:
                # Priority or visible worker running — prioritise these pages
                # by prepending to front of pending render list
                # (We can't interrupt mid-render; just note them for re-check)
                print(f"[SCHED][visible] worker busy ({self._worker_kind}), will retry")
                # Schedule a re-check via bg_timer
                self._bg_timer.start(50)
        else:
            self._start_worker(needed, kind="visible")

    def enqueue_all_loaded(self) -> None:
        """
        Accept-button handler.

        Adds ALL pages that are in "loaded" state (rendered but not yet on
        canvas) to the inject queue.  The QTimer then injects them one per
        tick — no UI stutter.
        """
        loaded = [
            pn for pn, ps in sorted(self.pages.items())
            if ps.is_injectable() and pn not in self.inject_queue
        ]
        self.inject_queue.extend(loaded)
        print(f"[SCHED][accept] enqueued {len(loaded)} loaded pages for injection")

    def set_scrolling(self, scrolling: bool) -> None:
        """
        Call with True on scroll start, False when scroll stops.
        The scheduler pauses injection while scrolling to keep the UI snappy.
        """
        if scrolling:
            self._is_scrolling = True
            self._scroll_stop_timer.start()   # restart 150-ms countdown
        else:
            self._is_scrolling = False

    def stop(self) -> None:
        """Tear down all timers and workers (call on card close / teardown)."""
        self._stop_worker()
        self._inject_timer.stop()
        self._bg_timer.stop()
        self._scroll_stop_timer.stop()
        self.inject_queue.clear()
        print("[SCHED][stop] scheduler stopped")

    def get_status_summary(self) -> dict:
        """Return counts per status — useful for debug / completion detection."""
        counts = {"not_loaded": 0, "loading": 0, "loaded": 0, "injected": 0}
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

        # Pages stuck in "loading" because their worker was killed — reset them
        for ps in self.pages.values():
            if ps.status == "loading":
                ps.status = "not_loaded"

    def _start_worker(self, page_nums: list[int], kind: str) -> None:
        """
        Spawn a PdfOnDemandThread for the given page numbers.

        The worker's page_ready signal stores the pixmap in PageState and
        sets status = "loaded".  It NEVER calls inject_page() directly.
        """
        if not page_nums or not self._path:
            return

        # Mark as loading
        for pn in page_nums:
            if pn in self.pages:
                self.pages[pn].status = "loading"

        self._stop_worker()

        self._worker = PdfOnDemandThread(
            self._path, page_nums, zoom=1.5, parent=self
        )
        self._worker_kind = kind

        # ── signals ──────────────────────────────────────────────────────────
        # page_ready → store pixmap, mark loaded, maybe enqueue for injection
        self._worker.page_ready.connect(self._on_worker_page_ready)
        self._worker.batch_done.connect(self._on_worker_batch_done)
        self._worker.error.connect(
            lambda err: print(f"[SCHED][worker] ❌ error: {err}")
        )

        self._worker.start()
        print(f"[SCHED][worker] ▶ started kind={kind}  pages={[p+1 for p in page_nums]}")

    # ── worker signal slots ───────────────────────────────────────────────────

    def _on_worker_page_ready(self, page_num: int, qpx: QPixmap) -> None:
        """
        Slot — fires on GUI thread via Qt queued connection.

        NEVER calls inject_page() here.
        Stores the pixmap and marks status = "loaded".
        Then enqueues the page for the QTimer injection pipeline.
        """
        if page_num not in self.pages:
            return

        ps = self.pages[page_num]
        ps.pixmap = qpx
        ps.status = "loaded"

        # Automatically enqueue visible pages for immediate injection
        first, last = self._last_visible
        if first <= page_num <= last:
            self._enqueue_if_not_present(page_num)
        # Non-visible loaded pages are enqueued only when:
        #   a) Accept button pressed  → enqueue_all_loaded()
        #   b) User scrolls to them   → on_visible_pages_changed() adds them

        self._check_completion()

    def _on_worker_batch_done(self, rendered: list[int]) -> None:
        kind = self._worker_kind
        print(f"[SCHED][worker] batch_done kind={kind}  rendered={[p+1 for p in rendered]}")
        self._worker_kind = ""

        # Reset any pages that were "loading" but not rendered (worker stopped early)
        for pn, ps in self.pages.items():
            if ps.status == "loading":
                ps.status = "not_loaded"

        if kind in ("priority", "visible"):
            # Schedule background fill after a short idle pause
            self._bg_timer.start(300)

        self._check_completion()

    # =========================================================================
    #  INTERNAL — injection pipeline
    # =========================================================================

    def _enqueue_if_not_present(self, page_num: int) -> None:
        if page_num not in self.inject_queue:
            self.inject_queue.append(page_num)

    def _process_inject_queue(self) -> None:
        """
        QTimer slot — fires every 16 ms.

        Injects at most ONE page per call:
          • Skip if user is scrolling (prevents jank during fast scroll)
          • Pick the highest-priority page from the queue
          • Call canvas.inject_page(page_num, pixmap)
          • Mark status = "injected"

        This is the ONLY place inject_page() is called.
        """
        if self._is_scrolling:
            return

        if not self.inject_queue:
            return

        # Find the highest-priority page in the queue (lowest priority number)
        best_pn = None
        best_pri = 999
        for pn in self.inject_queue:
            if pn in self.pages:
                pri = self.pages[pn].priority
                if pri < best_pri:
                    best_pri = pri
                    best_pn = pn

        if best_pn is None:
            self.inject_queue.clear()
            return

        # Remove from queue (deque has no O(1) arbitrary delete — rebuild)
        self.inject_queue = deque(p for p in self.inject_queue if p != best_pn)

        ps = self.pages[best_pn]

        # Guard: make sure pixmap is still valid
        if ps.pixmap is None or ps.pixmap.isNull():
            ps.status = "not_loaded"
            ps.pixmap = None
            print(f"[SCHED][inject] ⚠ p.{best_pn+1} pixmap gone — reset to not_loaded")
            return

        t0 = time.perf_counter()
        self._canvas.inject_page(best_pn, ps.pixmap)   # ← the ONLY inject_page call
        ps.status = "injected"
        self._injected_count += 1
        t_ms = (time.perf_counter() - t0) * 1000

        print(f"[SCHED][inject] ✅ p.{best_pn+1}  "
              f"pri={best_pri}  inject_time={t_ms:.1f}ms  "
              f"total_injected={self._injected_count}/{self._total}  "
              f"queue_remaining={len(self.inject_queue)}")

        self.page_injected.emit(best_pn, self._injected_count)
        self._check_completion()

    # =========================================================================
    #  INTERNAL — background fill
    # =========================================================================

    def _start_background_batch(self) -> None:
        """
        Timer slot — fires after a short idle period post priority/visible render.

        Picks the next BG_BATCH_SIZE not-loaded pages sorted by priority and
        starts a background worker for them.  Pauses if a visible-page worker
        is already running.
        """
        if self._worker_running():
            # Retry later — don't fight the visible-page worker
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

        batch = candidates[:self.BG_BATCH_SIZE]
        print(f"[SCHED][bg] starting batch: {[p+1 for p in batch]}")
        self._start_worker(batch, kind="background")

    # =========================================================================
    #  INTERNAL — completion detection
    # =========================================================================

    def _check_completion(self) -> None:
        """
        Emits all_done when every page is either "loaded" or "injected"
        (i.e., nothing remains in "not_loaded" or "loading").
        """
        if not self.pages:
            return
        if any(ps.status in ("not_loaded", "loading") for ps in self.pages.values()):
            return
        summary = self.get_status_summary()
        print(f"[SCHED][done] all pages loaded/injected: {summary}")
        self.all_done.emit()

    # =========================================================================
    #  INTERNAL — scroll-stop callback
    # =========================================================================

    def _on_scroll_stopped(self) -> None:
        self._is_scrolling = False
        # Resume injection immediately after scroll settles
        first, last = self._last_visible
        print(f"[SCHED][scroll_stop] scroll stopped — checking visible p.{first+1}–p.{last+1}")

        # Enqueue any loaded pages that are currently visible
        for pn in range(first, last + 1):
            if pn in self.pages and self.pages[pn].is_injectable():
                self._enqueue_if_not_present(pn)

        # Also kick a BG batch if nothing is rendering
        if not self._worker_running():
            self._bg_timer.start(200)