# ═══════════════════════════════════════════════════════════════════════════════
#  INTEGRATION PATCH  for  anki_occlusion_v19.py
#  Target: replace ad-hoc thread/inject tangle with PageScheduler
#
#  HOW TO USE
#  ──────────
#  This file is a self-documenting patch — each section shows:
#    REMOVE  : the old block (exact lines to delete)
#    REPLACE : the new block to put in its place
#  Apply changes in the order shown.
#
#  After applying, anki_occlusion_v19.py gains:
#    • O(1) per-page state lookup
#    • Priority 0/1/2 system (due-today / neighbour / background)
#    • Worker thread NEVER calls inject_page()
#    • QTimer injects exactly ONE page per 16-ms tick
#    • Scrolling guard — injection paused while user scrolls
#    • Smooth Accept-All via deque drain
#    • all_done signal → "Accept remaining pages" button auto-shows
# ═══════════════════════════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 1 — ADD IMPORT at the top of anki_occlusion_v19.py
# ───────────────────────────────────────────────────────────────────────────────
#
# FIND this existing import block (around line 53):
#
#   from sm2_engine import (
#       is_due_now, is_due_today, sm2_is_due, sm2_days_left,
#       ...
#   )
#
# ADD directly below it:
#
#   from page_scheduler import PageScheduler
#


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 2 — ReviewScreen.__init__  (around line 318)
# Replace OLD state attributes with scheduler bootstrap
# ───────────────────────────────────────────────────────────────────────────────

# ── REMOVE these lines from __init__ ─────────────────────────────────────────
REMOVE_FROM_INIT = """
        self._pending_visible_request = None
        self._pending_skeleton_result = None
        self._background_fill_state = None
        self._ondemand_kind = None
        self._ondemand_thread = None
        self._bg_pending_inserts = {}
        self._bg_accept_mode = False
        self._bg_prefetch_dialog = None
        self._bg_prefetch_total_pages = 0
        self._bg_prefetch_cached_count = 0
        self._bg_prefetch_rendered_count = 0
        self._ui_idle_timer = QTimer(self)
        self._ui_idle_timer.setSingleShot(True)
        self._ui_idle_timer.setInterval(220)
        self._ui_idle_timer.timeout.connect(self._on_ui_idle_timeout)
"""

# ── REPLACE WITH ──────────────────────────────────────────────────────────────
ADD_TO_INIT = """
        # ── Page Scheduler (replaces ad-hoc thread/inject tangle) ────────────
        self._pending_skeleton_result = None   # kept for skeleton handshake only
        self._scheduler = PageScheduler(canvas=self.canvas, parent=self)
        self._scheduler.all_done.connect(self._on_all_pages_done)
        self._scheduler.page_injected.connect(self._on_page_injected)
"""

# NOTE: self._pending_skeleton_result is still needed for the skeleton thread
# handshake in _on_review_skeleton_ready — keep that one attribute only.


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 3 — Replace _start_priority_render  (around line 1490)
# ───────────────────────────────────────────────────────────────────────────────

# ── REMOVE the entire old method body ────────────────────────────────────────
OLD_START_PRIORITY_RENDER = '''
    def _start_priority_render(self, path, priority_pages, total_pages):
        """
        Launch PdfOnDemandThread for priority pages.
        On each page_ready → canvas.inject_page().
        On batch_done → start background fill for remaining pages.
        """
        self._stop_ondemand_thread()
        self._ondemand_kind = "priority"
        self._background_fill_state = None
        self._bg_pending_inserts.clear()

        # ── FIX 1: stamp current PDF path on canvas ───────────────────────────
        self._canvas_pdf_path = path
        self.canvas._current_pdf_path = path
        ... (rest of old body)
'''

# ── REPLACE WITH ──────────────────────────────────────────────────────────────
NEW_START_PRIORITY_RENDER = '''
    def _start_priority_render(self, path, priority_pages, total_pages):
        """
        Delegate to PageScheduler.

        priority_pages : pages with masks due today + their neighbours.
        All other pages are rendered in background batches by the scheduler.
        """
        # Stamp PDF path on canvas (stale-signal guard)
        self._canvas_pdf_path = path
        self.canvas._current_pdf_path = path
        print(f"[DEBUG][priority_render] 🔑 canvas_pdf_path stamped: "
              f"{os.path.basename(path)}")

        # Build due-page set (priority 0 in scheduler)
        due_set = set(priority_pages)

        # Initialise scheduler — resets all per-page state
        self._scheduler.init_pdf(path, total_pages, due_page_nums=list(due_set))

        print(f"[DEBUG][priority_render] ▶ scheduler started  "
              f"total={total_pages}  priority_pages={[p+1 for p in sorted(due_set)]}")
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 4 — Replace _wire_scroll_ondemand  (around line 1722)
# ───────────────────────────────────────────────────────────────────────────────

OLD_WIRE_SCROLL = '''
    def _wire_scroll_ondemand(self, path, total_pages):
        try:
            self._canvas_scroll.visible_pages_changed.disconnect(
                self._on_visible_pages_changed)
        except Exception:
            pass
        self._ondemand_path  = path
        self._ondemand_total = total_pages
        self._canvas_scroll.visible_pages_changed.connect(
            self._on_visible_pages_changed)
        print(f"[DEBUG][wire_scroll] ✅ scroll→on-demand wired  "
              f"path={os.path.basename(path)}  total={total_pages}")
'''

NEW_WIRE_SCROLL = '''
    def _wire_scroll_ondemand(self, path, total_pages):
        """Wire scroll signal → scheduler (idempotent — safe to call multiple times)."""
        try:
            self._canvas_scroll.visible_pages_changed.disconnect(
                self._on_visible_pages_changed)
        except Exception:
            pass
        self._canvas_scroll.visible_pages_changed.connect(
            self._on_visible_pages_changed)
        print(f"[DEBUG][wire_scroll] ✅ scroll→scheduler wired  "
              f"path={os.path.basename(path)}  total={total_pages}")
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 5 — Replace _on_visible_pages_changed  (around line 1742)
# ───────────────────────────────────────────────────────────────────────────────

OLD_ON_VISIBLE = '''
    def _on_visible_pages_changed(self, first, last):
        """
        Called 120ms after scroll stops (debounced).
        Renders any visible pages that are still placeholders.
        """
        self._note_user_activity()
        path        = getattr(self, "_ondemand_path", None)
        total_pages = getattr(self, "_ondemand_total", 0)
        if not path:
            return
        needed = [pn for pn in range(first, last + 1) if PAGE_CACHE.get(path, pn) is None]
        if not needed:
            ...
        if self._ondemand_thread and self._ondemand_thread.isRunning():
            ...
        self._start_visible_page_request(path, needed)
'''

NEW_ON_VISIBLE = '''
    def _on_visible_pages_changed(self, first: int, last: int) -> None:
        """
        Scroll signal handler — delegates entirely to PageScheduler.

        The scheduler decides whether to:
          • immediately enqueue already-loaded pages for injection
          • start a new visible-page render worker
          • preempt a background worker
        """
        self._scheduler.set_scrolling(True)   # pause injection during scroll
        self._scheduler.on_visible_pages_changed(first, last)
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 6 — Replace _stop_ondemand_thread  (around line 1852)
# ───────────────────────────────────────────────────────────────────────────────

OLD_STOP_ONDEMAND = '''
    def _stop_ondemand_thread(self):
        """
        Safely stop any running PdfOnDemandThread.
        ...
        """
        t = getattr(self, "_ondemand_thread", None)
        ...
        self._ondemand_thread = None
'''

NEW_STOP_ONDEMAND = '''
    def _stop_ondemand_thread(self):
        """Legacy shim — callers can still call this; delegates to scheduler."""
        self._scheduler.stop()
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 7 — Replace _on_page_ready  (around line 1837)
# ───────────────────────────────────────────────────────────────────────────────

OLD_ON_PAGE_READY = '''
    def _on_page_ready(self, page_num, qpx):
        """
        Slot — called from PdfOnDemandThread.page_ready signal.
        ...
        """
        current_path = getattr(self, "_canvas_pdf_path", None)
        ...
        self.canvas.inject_page(page_num, qpx)
'''

NEW_ON_PAGE_READY = '''
    def _on_page_ready(self, page_num, qpx):
        """
        Legacy slot — kept for any code paths that bypass the scheduler
        (e.g., fallback PdfLoaderThread in _start_review_pdf_thread).

        Normal path: scheduler's worker emits page_ready → _scheduler._on_worker_page_ready()
        This slot handles only the fallback PdfLoaderThread path.
        """
        current_path = getattr(self, "_canvas_pdf_path", None)
        thread_path  = getattr(self, "_ondemand_path", None)
        if current_path and current_path != thread_path:
            print(f"[DEBUG][page_ready] 🚫 STALE SIGNAL DROPPED p.{page_num+1} — "
                  f"path mismatch (card switched mid-render)")
            return
        # Route through scheduler so injection still goes through the queue
        if page_num in self._scheduler.pages:
            ps = self._scheduler.pages[page_num]
            if ps.status not in ("loaded", "injected"):
                from PyQt5.QtGui import QPixmap as _QP
                ps.pixmap = qpx
                ps.status = "loaded"
                first, last = self._scheduler._last_visible
                if first <= page_num <= last:
                    self._scheduler._enqueue_if_not_present(page_num)
        else:
            # Scheduler not initialised yet (early fallback) — inject directly
            if len(self.canvas._pages) > 0:
                self.canvas.inject_page(page_num, qpx)
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 8 — Replace Accept button handler  (around line 225 / _accept_clicked)
# ───────────────────────────────────────────────────────────────────────────────

OLD_ACCEPT_CLICKED = '''
    def _accept_clicked(self):
        ...
'''

NEW_ACCEPT_CLICKED = '''
    def _accept_clicked(self):
        """
        User pressed "Accept All".
        Enqueue every rendered-but-not-injected page via the scheduler.
        The QTimer drains the queue one page per tick — no UI freeze.
        """
        self._scheduler.enqueue_all_loaded()
        self.btn_accept.setEnabled(False)
        self.canvas._show_toast("⏳ Injecting pages…")
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 9 — ADD two new methods to ReviewScreen
# ───────────────────────────────────────────────────────────────────────────────

NEW_METHODS = '''
    # ── Scheduler callbacks ──────────────────────────────────────────────────

    def _on_all_pages_done(self):
        """
        Called by scheduler when every page is loaded or injected.
        Show the "Accept remaining pages" button.
        """
        summary = self._scheduler.get_status_summary()
        loaded_count  = summary.get("loaded", 0)
        inject_count  = summary.get("injected", 0)
        print(f"[SCHED][complete] all_done  loaded={loaded_count}  injected={inject_count}")

        if loaded_count > 0:
            # Some pages are rendered but not yet on canvas — offer Accept
            self.btn_accept.setEnabled(True)
            self.canvas._show_toast(
                f"✅ {inject_count} pages ready  •  {loaded_count} waiting — press Accept"
            )
        else:
            self.canvas._show_toast(f"✅ All {inject_count} pages injected")
            self.btn_accept.setEnabled(False)

    def _on_page_injected(self, page_num: int, total_injected: int):
        """
        Called after each individual page injection.
        Update the status label (lbl_pg / toast) with progress.
        """
        total = self._scheduler._total
        if total > 0:
            pct = int(total_injected / total * 100)
            self.canvas._show_toast(f"⏳ {total_injected}/{total} pages ({pct}%)")
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 10 — closeEvent / teardown
# ───────────────────────────────────────────────────────────────────────────────
# In closeEvent (around line 408), ADD before super().closeEvent(e):
#
#   self._scheduler.stop()
#
# This stops the inject timer and any running worker cleanly.


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 11 — _note_user_activity  (around line 430)
# Replace or augment with scrolling notification to scheduler
# ───────────────────────────────────────────────────────────────────────────────

OLD_NOTE_USER_ACTIVITY = '''
    def _note_user_activity(self):
        self._ui_idle_timer.start()
'''

NEW_NOTE_USER_ACTIVITY = '''
    def _note_user_activity(self):
        """Notify scheduler that the user is active (scroll / interaction)."""
        self._scheduler.set_scrolling(True)
'''


# ───────────────────────────────────────────────────────────────────────────────
# PATCH 12 — REMOVE methods made obsolete by scheduler
# ───────────────────────────────────────────────────────────────────────────────
#
# These methods can be safely deleted (or left as no-ops if you prefer):
#
#   _start_background_fill()
#   _on_background_batch_done()
#   _queue_background_ready()
#   _flush_pending_background_inserts()
#   _on_ui_idle_timeout()
#   _start_visible_page_request()
#   _on_visible_pages_batch_done()
#   _on_priority_batch_done()
#   _accept_bg_prefetch()
#   _show_bg_prefetch_dialog()
#   _sync_bg_prefetch_dialog()
#   _close_bg_prefetch_dialog()
#
# All of their responsibilities are now handled inside PageScheduler.
# Keeping them as stubs (pass) is safe during a phased migration.


# ───────────────────────────────────────────────────────────────────────────────
# QUICK REFERENCE — Page State Machine
# ───────────────────────────────────────────────────────────────────────────────
#
#  not_loaded ──► loading ──► loaded ──► injected
#                    │                      ▲
#                    └── worker killed ──►  │
#                        reset to           │
#                        not_loaded         │
#                                      QTimer tick
#                                      (inject_page)
#
#  Priority:
#    0 = pages with masks due today   → rendered first, injected first
#    1 = visible ± PREFETCH_RADIUS    → rendered second
#    2 = everything else              → background batches of BG_BATCH_SIZE
#
#  Injection guard:
#    is_scrolling == True  →  _process_inject_queue() returns immediately
#    is_scrolling == False →  normal 1-page-per-16ms drain