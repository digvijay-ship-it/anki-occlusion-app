# ═══════════════════════════════════════════════════════════════════════════════
#  PDF ENGINE  —  Virtual Page Renderer  (v22 — Lazy Loading)
#
#  KEY CHANGE (v22) — STEP 2: PdfSkeletonLoader
#    ❌  PdfLoaderThread renders ALL pages upfront — 100-page PDF = 300MB RAM
#        aur ~8 sec wait before user can do anything.
#    ✅  PdfSkeletonLoader: zero rendering — sirf fitz.open() karke har page
#        ka rect (width × height) padhta hai. In dimensions se grey placeholder
#        QPixmaps banata hai. Canvas turant ready — ~5ms, ~1KB RAM per page.
#        Actual pixels baad mein PdfOnDemandThread inject karta hai (Step 3).
#
#  KEY CHANGE from v20:
#    ❌  pdf_page_to_pixmap() wrote every page to a temp PNG on disk, then
#        read it back — 150 disk I/O ops for a 50-page PDF = UI freeze.
#    ✅  Now uses fitz.Pixmap.tobytes("png") → QPixmap.loadFromData() —
#        pure in-RAM conversion, zero disk touch per page.
#
#  KEY CHANGE from v18/v19:
#    ❌  One giant combined QPixmap  (broke at >32 767 px — Qt hard limit)
#    ✅  List[QPixmap] — one entry per PDF page, drawn on-demand in paintEvent
#
#  Public API:
#    PdfSkeletonLoader — NEW: returns (placeholders, page_dims) instantly
#    PdfLoaderThread   — emits pages_ready(list[QPixmap], int, int) + done/error
#    pdf_page_to_pixmap(page, mat) → QPixmap
#    PAGE_CACHE        — imported from cache_manager
# ═══════════════════════════════════════════════════════════════════════════════

import os
import time
import math
import hashlib 
from collections import OrderedDict

from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPixmap, QImage, QColor, QPainter

from cache_manager import PAGE_CACHE

# PyMuPDF
try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# How many pages to emit per chunk so the canvas updates quickly
CHUNK_SIZE = 500

# Skeleton placeholder color — dark grey, matches app background
SKELETON_COLOR = "#2A2A3E"
SKELETON_CACHE_MAX = 8
_SKELETON_CACHE = OrderedDict()
_SKELETON_PLACEHOLDER_CACHE = OrderedDict()
_SKELETON_PLACEHOLDER_CACHE_MAX = 32


def _get_skeleton_placeholder(w_px: int, h_px: int) -> QPixmap:
    """
    Return a shared placeholder pixmap for a given size.

    The skeleton loader only needs a stable drawing surface for unloaded pages.
    Reusing one pixmap per size avoids allocating the same full-resolution
    placeholder hundreds of times for documents whose pages share dimensions.
    """
    key = (int(w_px), int(h_px))
    cached = _SKELETON_PLACEHOLDER_CACHE.get(key)
    if cached is not None:
        _SKELETON_PLACEHOLDER_CACHE.move_to_end(key)
        return cached

    qpx = QPixmap(key[0], key[1])
    qpx.fill(QColor(SKELETON_COLOR))
    _SKELETON_PLACEHOLDER_CACHE[key] = qpx
    _SKELETON_PLACEHOLDER_CACHE.move_to_end(key)
    while len(_SKELETON_PLACEHOLDER_CACHE) > _SKELETON_PLACEHOLDER_CACHE_MAX:
        _SKELETON_PLACEHOLDER_CACHE.popitem(last=False)
    return qpx


def build_skeleton_placeholders(page_dims: list[tuple[int, int]]) -> list[QPixmap]:
    """
    Build reusable placeholder pixmaps on the GUI thread from page dimensions.
    This keeps QPixmap creation out of worker threads.
    """
    return [_get_skeleton_placeholder(w_px, h_px) for (w_px, h_px) in page_dims]


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — PDF SKELETON LOADER
#  Zero rendering. Sirf page dimensions padhta hai, grey placeholders banata hai.
# ═══════════════════════════════════════════════════════════════════════════════

class PdfSkeletonResult:
    """
    PdfSkeletonLoader ka return value.

    Attributes:
        placeholders : list[QPixmap]  — grey QPixmaps, correct size per page
        page_dims    : list[tuple]    — [(w_px, h_px), ...] at zoom resolution
        total_pages  : int
        error        : str | None     — None if success
    """
    __slots__ = ("placeholders", "page_dims", "total_pages", "error")

    def __init__(self, placeholders, page_dims, total_pages, error=None):
        self.placeholders = placeholders
        self.page_dims    = page_dims
        self.total_pages  = total_pages
        self.error        = error


class PdfSkeletonThread(QThread):
    """
    Build the lightweight skeleton off the UI thread.

    The returned PdfSkeletonResult is the same object load_pdf_skeleton()
    produces, but the expensive file scan / placeholder construction no longer
    blocks the Qt event loop.
    """
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, path: str, zoom: float = 1.5, parent=None):
        super().__init__(parent)
        self._path = path
        self._zoom = zoom
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            if self._stop_flag:
                return
            result = _compute_pdf_skeleton_dims(self._path, zoom=self._zoom)
            if self._stop_flag:
                return
            if result.error:
                self.error.emit(result.error)
                return
            self.done.emit(result)
        except Exception as ex:
            self.error.emit(str(ex))


def _skeleton_cache_key(path: str, zoom: float):
    st = os.stat(path)
    return (os.path.abspath(path), int(st.st_mtime_ns), st.st_size, float(zoom))


def _clone_skeleton_result(result: PdfSkeletonResult) -> PdfSkeletonResult:
    return PdfSkeletonResult(
        list(result.placeholders),
        list(result.page_dims),
        result.total_pages,
        result.error,
    )


def _compute_pdf_skeleton_dims(path: str, zoom: float = 1.5) -> PdfSkeletonResult:
    """
    Worker-safe skeleton scan. Computes page sizes only, without creating QPixmaps.
    """
    t_start = time.perf_counter()

    if not PDF_SUPPORT:
        print("[DEBUG][skeleton] ❌ PyMuPDF not installed")
        return PdfSkeletonResult([], [], 0, "PyMuPDF not installed")

    if not os.path.exists(path):
        print(f"[DEBUG][skeleton] ❌ File not found: {path}")
        return PdfSkeletonResult([], [], 0, f"File not found: {path}")

    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            doc.close()
            print(f"[DEBUG][skeleton] ❌ PDF is password-protected: {path}")
            return PdfSkeletonResult([], [], 0, "PDF is password-protected")

        total = len(doc)
        page_dims = []


        _mat0 = fitz.Matrix(zoom, zoom)
        _pix0 = doc[0].get_pixmap(matrix=_mat0, alpha=False)
        _ref_w = _pix0.width
        _ref_h = _pix0.height

        for i in range(total):
            if i == 0:
                w_px, h_px = _ref_w, _ref_h
            else:
                _r = doc[i].rect
                if abs(_r.width - doc[0].rect.width) < 0.5 and abs(_r.height - doc[0].rect.height) < 0.5:
                    w_px, h_px = _ref_w, _ref_h
                else:
                    _pix_i = doc[i].get_pixmap(matrix=_mat0, alpha=False)
                    w_px, h_px = _pix_i.width, _pix_i.height
            page_dims.append((max(1, w_px), max(1, h_px)))

        doc.close()

        return PdfSkeletonResult([], page_dims, total, None)
    except Exception as ex:
        print(f"[DEBUG][skeleton] ❌ Exception: {ex}")
        return PdfSkeletonResult([], [], 0, str(ex))


def invalidate_pdf_skeleton(path: str):
    abs_path = os.path.abspath(path)
    keys = [k for k in _SKELETON_CACHE if k[0] == abs_path]
    for key in keys:
        del _SKELETON_CACHE[key]


def load_pdf_skeleton(path: str, zoom: float = 1.5) -> PdfSkeletonResult:
    """
    Synchronous [तुरंत] skeleton loader — call this on the main thread.
    Completes in ~5ms regardless of PDF size.

    What it does:
      1. fitz.open()  — open PDF (no rendering)
      2. page.rect    — read each page's width/height (no rendering)
      3. Scale dims by zoom factor (same as PdfLoaderThread uses)
      4. Create grey QPixmap of exact size per page
      5. Return PdfSkeletonResult

    What it does NOT do:
      - Never calls page.get_pixmap()  — zero pixel rendering
      - Never touches PAGE_CACHE       — cache is for real pages only
      - Never spawns a thread          — caller decides threading

    Terminal debug output shows timing + per-page dimensions.
    """
    t_start = time.perf_counter()
    cache_key = None

    if not PDF_SUPPORT:
        print("[DEBUG][skeleton] ❌ PyMuPDF not installed")
        return PdfSkeletonResult([], [], 0, "PyMuPDF not installed")

    if not os.path.exists(path):
        print(f"[DEBUG][skeleton] ❌ File not found: {path}")
        return PdfSkeletonResult([], [], 0, f"File not found: {path}")

    try:
        cache_key = _skeleton_cache_key(path, zoom)
        cached = _SKELETON_CACHE.get(cache_key)
        if cached is not None:
            _SKELETON_CACHE.move_to_end(cache_key)
            t_ms = (time.perf_counter() - t_start) * 1000
            return _clone_skeleton_result(cached)

        doc = fitz.open(path)

        if doc.is_encrypted:
            doc.close()
            print(f"[DEBUG][skeleton] ❌ PDF is password-protected: {path}")
            return PdfSkeletonResult([], [], 0, "PDF is password-protected")

        total        = len(doc)
        placeholders = []
        page_dims    = []

        # ── Render page 0 once to get EXACT fitz pixel dimensions ────────────
        # int(rect * zoom) truncates differently than fitz's internal rounding,
        # causing a 1px mismatch on every inject_page → layout recompute → jitter.
        # Rendering page 0 gives us the canonical size fitz will use for all pages.
        _mat0  = fitz.Matrix(zoom, zoom)
        _pix0  = doc[0].get_pixmap(matrix=_mat0, alpha=False)
        _ref_w = _pix0.width
        _ref_h = _pix0.height
        # ─────────────────────────────────────────────────────────────────────

        for i in range(total):
            rect  = doc[i].rect                       # fitz.Rect — no rendering
            # Use ref dims for page 0 (already rendered above).
            # For other pages with the same mediabox (99% of PDFs) reuse ref dims.
            # For pages with different size, fall back to a quick render.
            if i == 0:
                w_px, h_px = _ref_w, _ref_h
            else:
                _r = doc[i].rect
                if abs(_r.width - doc[0].rect.width) < 0.5 and abs(_r.height - doc[0].rect.height) < 0.5:
                    # Same mediabox — fitz will produce identical pixel dims
                    w_px, h_px = _ref_w, _ref_h
                else:
                    # Different page size — render to get exact dims (rare)
                    _pix_i = doc[i].get_pixmap(matrix=_mat0, alpha=False)
                    w_px, h_px = _pix_i.width, _pix_i.height
            w_px = max(1, w_px)
            h_px = max(1, h_px)
            page_dims.append((w_px, h_px))

            # Reuse one shared placeholder surface per size.
            # Page labels are intentionally omitted here to keep the skeleton cheap.
            qpx = _get_skeleton_placeholder(w_px, h_px)

            placeholders.append(qpx)

        doc.close()

        t_ms = (time.perf_counter() - t_start) * 1000

        # ─────────────────────────────────────────────────────────────────────

        result = PdfSkeletonResult(placeholders, page_dims, total, None)
        if cache_key is not None:
            _SKELETON_CACHE[cache_key] = result
            _SKELETON_CACHE.move_to_end(cache_key)
            while len(_SKELETON_CACHE) > SKELETON_CACHE_MAX:
                _SKELETON_CACHE.popitem(last=False)
        return _clone_skeleton_result(result)

    except Exception as ex:
        print(f"[DEBUG][skeleton] ❌ Exception: {ex}")
        return PdfSkeletonResult([], [], 0, str(ex))


# ═══════════════════════════════════════════════════════════════════════════════
#  LOW-LEVEL PAGE RENDER
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_page_to_pixmap(page, mat, clip=None) -> QPixmap:
    """Render one fitz page → QPixmap (GUI thread only).

    NOTE: Call this ONLY from the GUI thread.
    For worker threads, use pdf_page_to_image() instead.
    """
    return QPixmap.fromImage(pdf_page_to_image(page, mat, clip))


def pdf_page_to_image(page, mat, clip=None) -> QImage:
    """Render one fitz page → QImage (thread-safe).

    QImage = raw pixel data only — safe to create in any thread.
    QPixmap = screen-optimized — GUI thread only.

    Worker threads use this. UI thread converts via QPixmap.fromImage().

    OLD: fitz → PNG bytes → QPixmap.loadFromData()  [not thread-safe]
    NEW: fitz → PNG bytes → QImage.loadFromData()   [thread-safe]
    """
    if clip is None:
        pix = page.get_pixmap(matrix=mat, alpha=False)
    else:
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    png_bytes = pix.tobytes("png")
    img = QImage()
    img.loadFromData(png_bytes, "PNG")
    return img


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — ON-DEMAND PAGE RENDER THREAD
#  Specific page numbers ki list lekar sirf unhe render karta hai.
#  Skeleton placeholders ko real QPixmaps se replace karne ke liye use hota hai.
# ═══════════════════════════════════════════════════════════════════════════════

class PdfOnDemandThread(QThread):
    """
    Render only the pages we actually need - not all 100.

    Signals:
        page_ready(page_num, QPixmap) - one page rendered and ready to inject.
        batch_done(list[int])          - all requested pages rendered.
        error(str)                     - something went wrong.

    Usage:
        t = PdfOnDemandThread(path, page_nums=[0, 3, 7, 12])
        t.page_ready.connect(canvas.inject_page)
        t.start()
    """

    page_ready = pyqtSignal(int, object)   # (page_num, QImage) — QImage is thread-safe
    batch_done = pyqtSignal(list)          # list[int] - rendered page nums
    error      = pyqtSignal(str)

    def __init__(self, path: str, page_nums: list, zoom: float = 1.5, parent=None):
        super().__init__(parent)
        self._path      = path
        self._zoom      = zoom
        self._stop_flag = False
        self._page_nums = [int(pn) for pn in page_nums]

    def stop(self):
        self._stop_flag = True
        print(f"[DEBUG][on_demand] stop() called - will exit after current page")

    def run(self):
        t_thread_start = time.perf_counter()
        fname = os.path.basename(self._path)

        print(f"[DEBUG][on_demand] -> Thread started")
        print(f"[DEBUG][on_demand]   file      : {fname}")
        print(f"[DEBUG][on_demand]   pages     : {self._page_nums}")
        print(f"[DEBUG][on_demand]   zoom      : {self._zoom}")

        if not PDF_SUPPORT:
            msg = "PyMuPDF not installed - run: pip install pymupdf"
            print(f"[DEBUG][on_demand] X {msg}")
            self.error.emit(msg)
            return

        if not os.path.exists(self._path):
            msg = f"File not found: {self._path}"
            print(f"[DEBUG][on_demand] X {msg}")
            self.error.emit(msg)
            return

        if not self._page_nums:
            print(f"[DEBUG][on_demand] warning: page_nums is empty - nothing to render")
            self.batch_done.emit([])
            return

        try:
            doc = fitz.open(self._path)

            if doc.is_encrypted:
                msg = "PDF is password-protected"
                print(f"[DEBUG][on_demand] X {msg}")
                self.error.emit(msg)
                doc.close()
                return

            total_in_doc = len(doc)
            mat          = fitz.Matrix(self._zoom, self._zoom)
            rendered     = []

            print(f"[DEBUG][on_demand]   doc_pages : {total_in_doc}")
            print(f"[DEBUG][on_demand] ------------------------------------------------")

            for page_num in self._page_nums:
                if self._stop_flag:
                    print(f"[DEBUG][on_demand] stop requested at page {page_num} ({len(rendered)}/{len(self._page_nums)} rendered)")
                    doc.close()
                    return

                if page_num < 0 or page_num >= total_in_doc:
                    print(f"[DEBUG][on_demand]   p.{page_num+1} warning: out of range (doc has {total_in_doc} pages) - skip")
                    continue

                t_page_start = time.perf_counter()
                cached = PAGE_CACHE.get(self._path, page_num)
                if cached and not cached.isNull():
                    t_ms = (time.perf_counter() - t_page_start) * 1000
                    print(f"[DEBUG][on_demand]   p.{page_num+1:>3} cache hit  ({t_ms:.1f}ms)  {cached.width()}x{cached.height()}px")
                    # PAGE_CACHE stores QPixmap — convert to QImage for thread-safe emit
                    self.page_ready.emit(page_num, cached.toImage())
                    rendered.append(page_num)
                    continue

                try:
                    # Use pdf_page_to_image (returns QImage — thread-safe)
                    # UI thread will convert to QPixmap via QPixmap.fromImage()
                    img = pdf_page_to_image(doc.load_page(page_num), mat)
                    t_ms = (time.perf_counter() - t_page_start) * 1000

                    if img.isNull():
                        print(f"[DEBUG][on_demand]   p.{page_num+1:>3} render returned null image")
                        continue

                    # Store as QPixmap in cache (cache is GUI-thread-read only)
                    qpx = QPixmap.fromImage(img)
                    PAGE_CACHE.put(self._path, page_num, qpx)

                    print(f"[DEBUG][on_demand]   p.{page_num+1:>3} rendered   ({t_ms:.1f}ms)  {img.width()}x{img.height()}px")
                    self.page_ready.emit(page_num, img)   # emit QImage — thread-safe
                    rendered.append(page_num)

                except Exception as ex:
                    print(f"[DEBUG][on_demand]   p.{page_num+1:>3} exception: {ex}")
                    continue

            doc.close()

            t_total_ms = (time.perf_counter() - t_thread_start) * 1000
            print(f"[DEBUG][on_demand] ------------------------------------------------")
            print(f"[DEBUG][on_demand] batch_done  rendered={len(rendered)}/{len(self._page_nums)}  total_time={t_total_ms:.1f}ms")

            self.batch_done.emit(rendered)

        except Exception as ex:
            print(f"[DEBUG][on_demand] Fatal exception: {ex}")
            self.error.emit(str(ex))

def get_changed_pages(path: str):
    if not PDF_SUPPORT or not os.path.exists(path):
        return None
    try:
        doc = fitz.open(path)
        changed = []
        mat = fitz.Matrix(0.2, 0.2)   # 20% zoom — sirf hash ke liye
        for i in range(len(doc)):
            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
            new_hash = hashlib.md5(pix.samples).hexdigest()
            old_hash = PAGE_CACHE.get_page_hash(path, i)
            if old_hash is None or old_hash != new_hash:
                changed.append(i)
            PAGE_CACHE.set_page_hash(path, i, new_hash)
        doc.close()
        return changed
    except Exception as ex:
        print(f"[changed_pages] error: {ex}")
        return None
    
class PdfLoaderThread(QThread):
    # Emitted every CHUNK_SIZE pages:  (pages_so_far, loaded_count, total_count)
    pages_ready = pyqtSignal(object, int, int)   # object = list[QPixmap]

    # Emitted once at the end:  (all_pages, error_str_or_None)
    done  = pyqtSignal(object, object)           # object = list[QPixmap]
    error = pyqtSignal(str)

    def __init__(self, path: str, zoom: float = 1.5,
                 chunk_size: int = CHUNK_SIZE, parent=None):
        super().__init__(parent)
        self._path       = path
        self._zoom       = zoom
        self._chunk_size = chunk_size
        self._stop_flag  = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        if not PDF_SUPPORT:
            self.done.emit([], "PyMuPDF not installed — run: pip install pymupdf")
            return
        try:
            doc = fitz.open(self._path)
            if doc.is_encrypted:
                self.done.emit([], "PDF is password-protected.")
                return

            total = len(doc)
            mat   = fitz.Matrix(self._zoom, self._zoom)
            pages : list[QPixmap] = []
            last_emitted = 0

            for page_num in range(total):
                if self._stop_flag:
                    doc.close()
                    return

                # Cache hit?
                cached = PAGE_CACHE.get(self._path, page_num)
                if cached and not cached.isNull():
                    pages.append(cached)
                else:
                    try:
                        qpx = pdf_page_to_pixmap(doc.load_page(page_num), mat)
                        if not qpx.isNull():
                            PAGE_CACHE.put(self._path, page_num, qpx)
                            pages.append(qpx)
                    except Exception:
                        continue  # skip bad page, keep going

                loaded = len(pages)
                if loaded - last_emitted >= self._chunk_size:
                    self.pages_ready.emit(list(pages), loaded, total)
                    last_emitted = loaded

            doc.close()

            if self._stop_flag:
                return

            # Final emit (catches leftover pages not in last chunk)
            self.done.emit(list(pages), None)

        except Exception as ex:
            self.done.emit([], str(ex))


# ═══════════════════════════════════════════════════════════════════════════════