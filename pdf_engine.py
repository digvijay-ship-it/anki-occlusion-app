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
#    ✅  Now uses fitz raw samples → QImage.copy() — no temp file and no
#        PNG encode/decode round trip while loading pages.
#
#  KEY CHANGE from v18/v19:
#    ❌  One giant combined QPixmap  (broke at >32 767 px — Qt hard limit)
#    ✅  List[QPixmap] — one entry per PDF page, drawn on-demand in paintEvent
#
#  Public API:
#    PdfSkeletonLoader — NEW: returns (placeholders, page_dims) instantly
#    PdfLoaderThread   — emits pages_ready(list[QImage], int, int) + done/error
#    pdf_page_to_pixmap(page, mat) → QPixmap
#    PAGE_CACHE        — imported from cache_manager
# ═══════════════════════════════════════════════════════════════════════════════

import os
import time
import math
import hashlib 
import copy
from collections import OrderedDict

from PyQt5.QtCore import QThread, pyqtSignal, Qt, QRunnable, QThreadPool, QObject
from PyQt5.QtGui import QPixmap, QImage, QColor, QPainter

from cache_manager import PAGE_CACHE
from perf_utils import perf_log

# PyMuPDF
try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# How many pages to emit per chunk so the canvas updates quickly
CHUNK_SIZE = 500
PDF_RENDER_ZOOM = 1.5
PDF_HASH_ZOOM = 0.2
PDF_LOW_PAGE_THRESHOLD = 40
PDF_RENDER_ZOOM_SMALL_DOC = 3.0
PDF_RENDER_ZOOM_LARGE_DOC = 2.0
PDF_LEGACY_BOX_ZOOM = 1.5

# Skeleton placeholder color — dark grey, matches app background
SKELETON_COLOR = "#2A2A3E"
SKELETON_CACHE_MAX = 8
_SKELETON_CACHE = OrderedDict()
_SKELETON_DIMS_CACHE = OrderedDict()
_SKELETON_PLACEHOLDER_CACHE = OrderedDict()
_SKELETON_PLACEHOLDER_CACHE_MAX = 32


def choose_pdf_render_zoom(page_count: int) -> float:
    try:
        count = int(page_count)
    except (TypeError, ValueError):
        count = PDF_LOW_PAGE_THRESHOLD
    return PDF_RENDER_ZOOM_SMALL_DOC if count < PDF_LOW_PAGE_THRESHOLD else PDF_RENDER_ZOOM_LARGE_DOC


def get_pdf_render_zoom_for_path(path: str) -> float:
    if not PDF_SUPPORT or not os.path.exists(path):
        return PDF_RENDER_ZOOM_LARGE_DOC
    doc = None
    try:
        doc = fitz.open(path)
        return choose_pdf_render_zoom(len(doc))
    except Exception:
        return PDF_RENDER_ZOOM_LARGE_DOC
    finally:
        if doc is not None:
            doc.close()


def ensure_pdf_cache_profile(path: str, render_zoom: float, cache_variant: str | None = None) -> bool:
    if PAGE_CACHE.matches_render_zoom(path, render_zoom, variant=cache_variant):
        return False
    PAGE_CACHE.invalidate_pdf(path, variant=cache_variant)
    PAGE_CACHE.set_render_zoom(path, render_zoom, variant=cache_variant)
    return True


def get_cached_pdf_page_set(
    path: str,
    total_pages: int | None = None,
    cache_variant: str | None = None,
    hydrate_pages=False,
) -> dict:
    """
    Shared cache-first PDF page lookup for editor/review/annotation.

    By default this only discovers cached page indices. Pass hydrate_pages=True
    or an iterable of page numbers when the caller needs actual QPixmaps.
    """
    try:
        total = max(0, int(total_pages or 0))
    except (TypeError, ValueError):
        total = 0

    if hasattr(PAGE_CACHE, "cached_page_indices"):
        cached_page_indices = PAGE_CACHE.cached_page_indices(
            path, total, variant=cache_variant
        )
    else:
        cached_page_indices = []
        for page_num in range(total):
            px = PAGE_CACHE.get(path, page_num, variant=cache_variant)
            if px is not None and not px.isNull():
                cached_page_indices.append(page_num)

    cached_index_set = {int(page_num) for page_num in cached_page_indices}
    cached_pages_by_index = {}

    if hydrate_pages is True:
        hydrate_targets = cached_index_set
    elif hydrate_pages:
        hydrate_targets = {
            int(page_num)
            for page_num in hydrate_pages
            if int(page_num) in cached_index_set
        }
    else:
        hydrate_targets = set()

    for page_num in sorted(hydrate_targets):
        px = PAGE_CACHE.get(path, page_num, variant=cache_variant)
        if px is not None and not px.isNull():
            cached_pages_by_index[page_num] = px

    return {
        "total_pages": total,
        "cached_page_indices": sorted(cached_index_set),
        "cached_pages_by_index": cached_pages_by_index,
        "cache_hit_count": len(cached_index_set),
        "cache_miss_count": max(0, total - len(cached_index_set)),
    }


def _page_tops_from_dims(page_dims: list[tuple[int, int]], page_gap: int = 12) -> list[int]:
    tops = []
    top = 0
    for idx, (_w, h) in enumerate(page_dims or []):
        tops.append(top)
        top += int(h)
        if idx < len(page_dims) - 1:
            top += int(page_gap)
    return tops


def _infer_page_num_from_rect(rect, page_tops: list[int], page_dims: list[tuple[int, int]]) -> int:
    if not page_tops or not page_dims:
        return 0
    cy = float(rect[1]) + float(rect[3]) / 2.0
    page_num = 0
    for idx, top in enumerate(page_tops):
        height = float(page_dims[idx][1]) if idx < len(page_dims) else 0.0
        if cy >= top and cy <= top + height:
            return idx
        if cy >= top:
            page_num = idx
        else:
            break
    return max(0, min(page_num, len(page_dims) - 1))


def infer_source_zoom(page_dims_1_0, boxes, nominal_source_zoom, page_gap=12) -> float:
    candidates = [3.0, 2.0, 1.5]
    if nominal_source_zoom not in candidates:
        candidates.append(nominal_source_zoom)

    zoom_validity = {}
    zoom_page_matches = {}

    accumulated_height = []
    current_h = 0.0
    for w, h in page_dims_1_0:
        accumulated_height.append(current_h)
        current_h += h

    for z in candidates:
        page_tops_z = [z * h_cum + idx * page_gap for idx, h_cum in enumerate(accumulated_height)]
        page_dims_z = [(z * w, z * h) for w, h in page_dims_1_0]

        valid_count = 0
        match_count = 0
        for box in boxes:
            rect = box.get("rect")
            if not isinstance(rect, (list, tuple)) or len(rect) < 4:
                continue

            page_num = _infer_page_num_from_rect(rect, page_tops_z, page_dims_z)
            if page_num >= len(page_dims_1_0):
                continue

            saved_page_num = box.get("page_num")
            if saved_page_num is not None:
                try:
                    if int(saved_page_num) == page_num:
                        match_count += 1
                except (TypeError, ValueError):
                    pass

            page_w, page_h = page_dims_z[page_num]
            page_top = page_tops_z[page_num]
            page_bottom = page_top + page_h

            x = float(rect[0])
            y = float(rect[1])
            w = float(rect[2])
            h = float(rect[3])

            x_ok = (-5.0 <= x) and (x + w <= page_w + 5.0)
            y_ok = (page_top - 5.0 <= y) and (y + h <= page_bottom + 5.0)

            if x_ok and y_ok:
                valid_count += 1

        zoom_validity[z] = valid_count
        zoom_page_matches[z] = match_count

    nominal_validity = zoom_validity.get(nominal_source_zoom, 0)
    nominal_matches = zoom_page_matches.get(nominal_source_zoom, 0)

    # Check if database page numbers are reliable. If all page numbers are 0 but some
    # boxes have Y coordinates pointing to page > 0 at nominal zoom, they are unreliable.
    db_page_nums_reliable = True
    if boxes:
        all_zero = all(int(box.get("page_num", 0)) == 0 for box in boxes)
        if all_zero:
            nominal_tops = [nominal_source_zoom * h_cum + idx * page_gap for idx, h_cum in enumerate(accumulated_height)]
            nominal_dims = [(nominal_source_zoom * w, nominal_source_zoom * h) for w, h in page_dims_1_0]
            for box in boxes:
                rect = box.get("rect")
                if isinstance(rect, (list, tuple)) and len(rect) >= 4:
                    p_num = _infer_page_num_from_rect(rect, nominal_tops, nominal_dims)
                    if p_num > 0:
                        db_page_nums_reliable = False
                        break

    best_zoom = nominal_source_zoom
    total_boxes = len(boxes)
    nominal_valid_ratio = nominal_validity / max(total_boxes, 1)

    if db_page_nums_reliable and total_boxes >= 3:
        # Primary metric is match count
        max_matches = nominal_matches
        for z in [3.0, 2.0, 1.5]:
            z_matches = zoom_page_matches.get(z, 0)
            if z_matches > max_matches:
                max_matches = z_matches
                best_zoom = z
    else:
        # Primary metric is validity count. Only heal if nominal validity is low (< 90%)
        # and another candidate has strictly higher validity.
        if nominal_valid_ratio < 0.90:
            max_validity = nominal_validity
            for z in [3.0, 2.0, 1.5]:
                z_valid = zoom_validity.get(z, 0)
                if z_valid > max_validity:
                    max_validity = z_valid
                    best_zoom = z

    if best_zoom != nominal_source_zoom:
        return best_zoom
    return None


def adapt_pdf_boxes_to_render_zoom(
    path: str,
    boxes: list,
    source_zoom: float,
    target_zoom: float,
    page_gap: int = 12,
):
    """
    Remap PDF mask boxes from one render zoom to another.

    Older cards stored mask rects in image-space coordinates tied to the page
    pixmap size. When page render zoom changes (for example 1.5x -> 3x),
    those rects must be reprojected page-by-page or they drift badly.
    """
    cloned = copy.deepcopy(list(boxes or []))
    if source_zoom is None:
        source_zoom = 1.5
    if target_zoom is None:
        target_zoom = 1.5
    try:
        source_zoom = float(source_zoom)
        target_zoom = float(target_zoom)
    except (TypeError, ValueError):
        return cloned

    # Auto-healing heuristic for zoom mismatch (legacy cards missing box render zoom)
    dims_1_0 = load_pdf_page_dims(path, zoom=1.0)
    if not dims_1_0.error and dims_1_0.page_dims:
        inferred_zoom = infer_source_zoom(dims_1_0.page_dims, cloned, source_zoom, page_gap=page_gap)
        if inferred_zoom is not None and abs(inferred_zoom - source_zoom) > 0.01:
            print(f"[DEBUG][pdf_engine] Auto-healed source_zoom from {source_zoom} to {inferred_zoom} for {os.path.basename(path)}")
            source_zoom = inferred_zoom

    if not cloned or abs(source_zoom - target_zoom) <= 0.01:
        return cloned

    src = load_pdf_page_dims(path, zoom=source_zoom)
    dst = load_pdf_page_dims(path, zoom=target_zoom)
    if (
        src.error or dst.error or
        not src.page_dims or not dst.page_dims or
        len(src.page_dims) != len(dst.page_dims)
    ):
        scale = target_zoom / max(source_zoom, 0.01)
        for box in cloned:
            rect = box.get("rect")
            if not isinstance(rect, (list, tuple)) or len(rect) < 4:
                continue
            page_num = int(box.get("page_num", 0))
            gap_offset = float(page_num) * float(page_gap)
            rect_y_scaled = (float(rect[1]) - gap_offset) * scale + gap_offset
            box["rect"] = [
                float(rect[0]) * scale,
                rect_y_scaled,
                float(rect[2]) * scale,
                float(rect[3]) * scale,
            ]
        return cloned

    src_tops = _page_tops_from_dims(src.page_dims, page_gap=page_gap)
    dst_tops = _page_tops_from_dims(dst.page_dims, page_gap=page_gap)

    for box in cloned:
        rect = box.get("rect")
        if not isinstance(rect, (list, tuple)) or len(rect) < 4:
            continue
        # Always recompute source page from the old rect position.
        # Older saved page_num values can be stale or missing, especially for
        # later review items on multi-page PDFs after prior save/load cycles.
        page_num = _infer_page_num_from_rect(rect, src_tops, src.page_dims)
        page_num = max(0, min(page_num, len(src.page_dims) - 1))

        src_w, src_h = src.page_dims[page_num]
        dst_w, dst_h = dst.page_dims[page_num]
        sx = float(dst_w) / max(float(src_w), 1.0)
        sy = float(dst_h) / max(float(src_h), 1.0)
        local_x = float(rect[0])
        local_y = float(rect[1]) - float(src_tops[page_num])

        box["rect"] = [
            local_x * sx,
            float(dst_tops[page_num]) + (local_y * sy),
            float(rect[2]) * sx,
            float(rect[3]) * sy,
        ]
        box["page_num"] = page_num
    return cloned


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
            result = load_pdf_page_dims(self._path, zoom=self._zoom)
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


def _page_rect_pixel_dims(page, zoom: float) -> tuple[int, int]:
    rect = page.rect
    return (
        max(1, int(math.ceil(float(rect.width) * float(zoom)))),
        max(1, int(math.ceil(float(rect.height) * float(zoom)))),
    )


def _compute_pdf_skeleton_dims(path: str, zoom: float = 1.5) -> PdfSkeletonResult:
    """
    Worker-safe skeleton scan. Computes page sizes only, without creating QPixmaps.
    """
    if not PDF_SUPPORT:
        return PdfSkeletonResult([], [], 0, "PyMuPDF not installed")

    if not os.path.exists(path):
        return PdfSkeletonResult([], [], 0, f"File not found: {path}")

    doc = None
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            return PdfSkeletonResult([], [], 0, "PDF is password-protected")

        total = len(doc)
        page_dims = []

        for i in range(total):
            w_px, h_px = _page_rect_pixel_dims(doc[i], zoom)
            page_dims.append((max(1, w_px), max(1, h_px)))

        return PdfSkeletonResult([], page_dims, total, None)
    except Exception as ex:
        return PdfSkeletonResult([], [], 0, str(ex))
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        try:
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass


def load_pdf_page_dims(path: str, zoom: float = 1.5) -> PdfSkeletonResult:
    """
    Cached dimension-only skeleton data.

    Use this when callers only need page geometry. Unlike load_pdf_skeleton(),
    this never creates placeholder QPixmaps, so box remapping cannot allocate a
    second full placeholder set for large PDFs.
    """
    if not PDF_SUPPORT or not os.path.exists(path):
        return _compute_pdf_skeleton_dims(path, zoom=zoom)
    try:
        cache_key = _skeleton_cache_key(path, zoom)
    except Exception:
        return _compute_pdf_skeleton_dims(path, zoom=zoom)
    cached = _SKELETON_DIMS_CACHE.get(cache_key)
    if cached is not None:
        _SKELETON_DIMS_CACHE.move_to_end(cache_key)
        return _clone_skeleton_result(cached)
    result = _compute_pdf_skeleton_dims(path, zoom=zoom)
    if not result.error:
        _SKELETON_DIMS_CACHE[cache_key] = result
        _SKELETON_DIMS_CACHE.move_to_end(cache_key)
        while len(_SKELETON_DIMS_CACHE) > SKELETON_CACHE_MAX:
            _SKELETON_DIMS_CACHE.popitem(last=False)
    return _clone_skeleton_result(result)


def invalidate_pdf_skeleton(path: str):
    abs_path = os.path.abspath(path)
    keys = [k for k in _SKELETON_CACHE if k[0] == abs_path]
    for key in keys:
        del _SKELETON_CACHE[key]
    dim_keys = [k for k in _SKELETON_DIMS_CACHE if k[0] == abs_path]
    for key in dim_keys:
        del _SKELETON_DIMS_CACHE[key]


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

    Returns placeholders and page dimensions without rendering full page pixels.
    """
    cache_key = None

    if not PDF_SUPPORT:
        return PdfSkeletonResult([], [], 0, "PyMuPDF not installed")

    if not os.path.exists(path):
        return PdfSkeletonResult([], [], 0, f"File not found: {path}")

    doc = None
    try:
        cache_key = _skeleton_cache_key(path, zoom)
        cached = _SKELETON_CACHE.get(cache_key)
        if cached is not None:
            _SKELETON_CACHE.move_to_end(cache_key)
            return _clone_skeleton_result(cached)

        doc = fitz.open(path)

        if doc.is_encrypted:
            return PdfSkeletonResult([], [], 0, "PDF is password-protected")

        total        = len(doc)
        placeholders = []
        page_dims    = []

        for i in range(total):
            w_px, h_px = _page_rect_pixel_dims(doc[i], zoom)
            w_px = max(1, w_px)
            h_px = max(1, h_px)
            page_dims.append((w_px, h_px))

            # Reuse one shared placeholder surface per size.
            # Page labels are intentionally omitted here to keep the skeleton cheap.
            qpx = _get_skeleton_placeholder(w_px, h_px)

            placeholders.append(qpx)

        # ─────────────────────────────────────────────────────────────────────

        result = PdfSkeletonResult(placeholders, page_dims, total, None)
        if cache_key is not None:
            _SKELETON_CACHE[cache_key] = result
            _SKELETON_CACHE.move_to_end(cache_key)
            while len(_SKELETON_CACHE) > SKELETON_CACHE_MAX:
                _SKELETON_CACHE.popitem(last=False)
        return _clone_skeleton_result(result)

    except Exception as ex:
        return PdfSkeletonResult([], [], 0, str(ex))
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        try:
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  LOW-LEVEL PAGE RENDER
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_page_to_pixmap(page, mat, clip=None, show_annots: bool = True) -> QPixmap:
    """Render one fitz page → QPixmap (GUI thread only).

    NOTE: Call this ONLY from the GUI thread.
    For worker threads, use pdf_page_to_image() instead.
    """
    return QPixmap.fromImage(pdf_page_to_image(page, mat, clip, show_annots=show_annots))


def pdf_page_to_image(page, mat, clip=None, show_annots: bool = True) -> QImage:
    """Render one fitz page → QImage (thread-safe).

    QImage = raw pixel data only — safe to create in any thread.
    QPixmap = screen-optimized — GUI thread only.

    Worker threads use this. UI thread converts via QPixmap.fromImage().

    OLD: fitz → PNG bytes → QImage.loadFromData()
    NEW: fitz raw RGB samples → QImage.copy()
    """
    if clip is None:
        pix = page.get_pixmap(matrix=mat, alpha=False, annots=show_annots)
    else:
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False, annots=show_annots)
    # Same idea as temp.py: avoid PNG compression/decompression while rendering.
    # copy() detaches the QImage from MuPDF's temporary sample buffer safely.
    qimg = QImage(
        pix.samples,
        pix.width,
        pix.height,
        pix.stride,
        QImage.Format_RGB888,
    ).copy()
    from cache_manager import get_pdf_invert_setting
    if get_pdf_invert_setting():
        qimg.invertPixels(QImage.InvertRgb)
    return qimg


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — ON-DEMAND PAGE RENDER THREAD
#  Specific page numbers ki list lekar sirf unhe render karta hai.
#  Skeleton placeholders ko real QPixmaps se replace karne ke liye use hota hai.
# ═══════════════════════════════════════════════════════════════════════════════

PDF_RENDER_DEBUG = os.environ.get("ANKI_PDF_RENDER_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _render_debug(message: str):
    if PDF_RENDER_DEBUG:
        print(message)


class PdfOnDemandThread(QObject):
    """
    Render only the pages we actually need - not all 100.
    Uses QThreadPool for high performance and thread recycling,
    but implements the exact same API as QThread.
    """

    page_ready = pyqtSignal(int, object)   # (page_num, QImage) — QImage is thread-safe
    batch_done = pyqtSignal(list)          # list[int] - rendered page nums
    error      = pyqtSignal(str)
    finished   = pyqtSignal()
    started    = pyqtSignal()

    def __init__(
        self,
        path: str,
        page_nums: list,
        zoom: float = PDF_RENDER_ZOOM,
        use_cache: bool = True,
        store_cache: bool = True,
        cache_variant: str | None = None,
        show_annots: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._path      = path
        self._zoom      = zoom
        self._stop_flag = False
        self._page_nums = [int(pn) for pn in page_nums]
        self._use_cache = bool(use_cache)
        self._store_cache = bool(store_cache)
        self._cache_variant = cache_variant
        self._show_annots = bool(show_annots)
        self._is_running = False
        self._runnable = None

    def isRunning(self):
        return self._is_running

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._stop_flag = False
        self.started.emit()

        class RenderRunnable(QRunnable):
            def __init__(self, outer):
                super().__init__()
                self.outer = outer

            def run(self):
                try:
                    self.outer.run()
                finally:
                    self.outer._is_running = False
                    self.outer.finished.emit()

        self._runnable = RenderRunnable(self)
        QThreadPool.globalInstance().start(self._runnable)

    def stop(self):
        self._stop_flag = True
        _render_debug("[DEBUG][on_demand] stop() called - will exit after current page")

    def quit(self):
        self.stop()

    def wait(self, timeout_ms=500):
        start_time = time.monotonic()
        while self._is_running:
            if (time.monotonic() - start_time) * 1000 > timeout_ms:
                return False
            time.sleep(0.01)
        return True

    def run(self):
        t_thread_start = time.perf_counter()
        fname = os.path.basename(self._path)
        perf_log(
            "pdf_on_demand_start",
            file=fname,
            requested=len(self._page_nums),
            pages=self._page_nums[:25],
            zoom=self._zoom,
            use_cache=self._use_cache,
            store_cache=self._store_cache,
            variant=self._cache_variant or "default",
        )

        _render_debug("[DEBUG][on_demand] -> Thread started")
        _render_debug(f"[DEBUG][on_demand]   file      : {fname}")
        _render_debug(f"[DEBUG][on_demand]   pages     : {self._page_nums}")
        _render_debug(f"[DEBUG][on_demand]   zoom      : {self._zoom}")

        if not PDF_SUPPORT:
            msg = "PyMuPDF not installed - run: pip install pymupdf"
            self.error.emit(msg)
            return

        if not os.path.exists(self._path):
            msg = f"File not found: {self._path}"
            self.error.emit(msg)
            return

        if not self._page_nums:
            _render_debug("[DEBUG][on_demand] warning: page_nums is empty - nothing to render")
            self.batch_done.emit([])
            return

        doc = None
        try:
            doc = fitz.open(self._path)

            if doc.is_encrypted:
                msg = "PDF is password-protected"
                self.error.emit(msg)
                return

            total_in_doc = len(doc)
            mat          = fitz.Matrix(self._zoom, self._zoom)
            rendered     = []

            _render_debug(f"[DEBUG][on_demand]   doc_pages : {total_in_doc}")
            _render_debug("[DEBUG][on_demand] ------------------------------------------------")

            for page_num in self._page_nums:
                if self._stop_flag:
                    _render_debug(f"[DEBUG][on_demand] stop requested at page {page_num} ({len(rendered)}/{len(self._page_nums)} rendered)")
                    perf_log(
                        "pdf_on_demand_stop",
                        file=fname,
                        rendered=len(rendered),
                        requested=len(self._page_nums),
                        elapsed_ms=round((time.perf_counter() - t_thread_start) * 1000.0, 3),
                    )
                    return

                if page_num < 0 or page_num >= total_in_doc:
                    _render_debug(f"[DEBUG][on_demand]   p.{page_num+1} warning: out of range (doc has {total_in_doc} pages) - skip")
                    continue

                t_page_start = time.perf_counter()
                cached = PAGE_CACHE.get_image(self._path, page_num, variant=self._cache_variant) if self._use_cache else None
                if cached and not cached.isNull():
                    t_ms = (time.perf_counter() - t_page_start) * 1000
                    _render_debug(f"[DEBUG][on_demand]   p.{page_num+1:>3} cache hit  ({t_ms:.1f}ms)  {cached.width()}x{cached.height()}px")
                    perf_log(
                        "pdf_on_demand_page",
                        file=fname,
                        page=page_num,
                        source="cache",
                        width=cached.width(),
                        height=cached.height(),
                        elapsed_ms=round(t_ms, 3),
                    )
                    self.page_ready.emit(page_num, cached)
                    rendered.append(page_num)
                    continue

                try:
                    # Use pdf_page_to_image (returns QImage — thread-safe)
                    # UI thread will convert to QPixmap via QPixmap.fromImage()
                    img = pdf_page_to_image(doc.load_page(page_num), mat, show_annots=self._show_annots)
                    t_ms = (time.perf_counter() - t_page_start) * 1000

                    if img.isNull():
                        _render_debug(f"[DEBUG][on_demand]   p.{page_num+1:>3} render returned null image")
                        continue

                    _render_debug(f"[DEBUG][on_demand]   p.{page_num+1:>3} rendered   ({t_ms:.1f}ms)  {img.width()}x{img.height()}px")
                    perf_log(
                        "pdf_on_demand_page",
                        file=fname,
                        page=page_num,
                        source="render",
                        width=img.width(),
                        height=img.height(),
                        elapsed_ms=round(t_ms, 3),
                    )
                    self.page_ready.emit(page_num, img)   # emit QImage — thread-safe
                    rendered.append(page_num)

                except Exception as ex:
                    print(f"[pdf_render] page {page_num+1} failed: {ex}")
                    continue

            t_total_ms = (time.perf_counter() - t_thread_start) * 1000
            _render_debug("[DEBUG][on_demand] ------------------------------------------------")
            _render_debug(f"[DEBUG][on_demand] batch_done  rendered={len(rendered)}/{len(self._page_nums)}  total_time={t_total_ms:.1f}ms")
            perf_log(
                "pdf_on_demand_done",
                file=fname,
                rendered=len(rendered),
                requested=len(self._page_nums),
                elapsed_ms=round(t_total_ms, 3),
            )

            self.batch_done.emit(rendered)

        except Exception as ex:
            print(f"[pdf_render] fatal render error: {ex}")
            self.error.emit(str(ex))
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            try:
                fitz.TOOLS.store_shrink(100)
            except Exception:
                pass


def render_pdf_pages(path: str, page_nums, zoom: float = PDF_RENDER_ZOOM, cache_variant: str | None = None, show_annots: bool = True) -> dict:
    if not PDF_SUPPORT or not os.path.exists(path):
        return {}
    rendered = {}
    doc = None
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            return {}
        mat = fitz.Matrix(zoom, zoom)
        targets = sorted({int(pn) for pn in (page_nums or []) if int(pn) >= 0})
        for page_num in targets:
            if page_num >= len(doc):
                continue
            qpx = pdf_page_to_pixmap(doc.load_page(page_num), mat, show_annots=show_annots)
            if qpx.isNull():
                continue
            PAGE_CACHE.put(path, page_num, qpx, variant=cache_variant, render_zoom=zoom)
            rendered[page_num] = qpx
        return rendered
    except Exception as ex:
        print(f"[render_pdf_pages] error: {ex}")
        return {}
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        try:
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass


def render_pdf_pages_from_doc(doc, path: str, page_nums, zoom: float = PDF_RENDER_ZOOM, cache_variant: str | None = None, show_annots: bool = True) -> dict:
    rendered = {}
    mat = fitz.Matrix(zoom, zoom)
    targets = sorted({int(pn) for pn in (page_nums or []) if int(pn) >= 0})
    total = len(doc)
    for page_num in targets:
        if page_num < 0 or page_num >= total:
            continue
        qpx = pdf_page_to_pixmap(doc.load_page(page_num), mat, show_annots=show_annots)
        if qpx.isNull():
            continue
        PAGE_CACHE.put(path, page_num, qpx, variant=cache_variant, render_zoom=zoom)
        rendered[page_num] = qpx
    return rendered


def update_page_hashes(path: str, page_nums=None, zoom: float = PDF_HASH_ZOOM):
    if not PDF_SUPPORT or not os.path.exists(path):
        return
    doc = None
    try:
        doc = fitz.open(path)
        mat = fitz.Matrix(zoom, zoom)
        if page_nums is None:
            targets = range(len(doc))
        else:
            targets = sorted({int(pn) for pn in page_nums if int(pn) >= 0})
        for page_num in targets:
            if page_num >= len(doc):
                continue
            pix = doc[page_num].get_pixmap(matrix=mat, alpha=False)
            PAGE_CACHE.set_page_hash(path, page_num, hashlib.md5(pix.samples).hexdigest())
    except Exception as ex:
        print(f"[update_page_hashes] error: {ex}")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        try:
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass

def get_changed_pages(path: str):
    if not PDF_SUPPORT or not os.path.exists(path):
        return None
    t0 = time.perf_counter()
    total = 0
    doc = None
    try:
        doc = fitz.open(path)
        changed = []
        mat = fitz.Matrix(PDF_HASH_ZOOM, PDF_HASH_ZOOM)   # 20% zoom — sirf hash ke liye
        total = len(doc)
        for i in range(total):
            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
            new_hash = hashlib.md5(pix.samples).hexdigest()
            old_hash = PAGE_CACHE.get_page_hash(path, i)
            if old_hash is None or old_hash != new_hash:
                changed.append(i)
            PAGE_CACHE.set_page_hash(path, i, new_hash)
        perf_log(
            "pdf_changed_pages_scan",
            file=os.path.basename(path),
            pages=total,
            changed=len(changed),
            zoom=PDF_HASH_ZOOM,
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        return changed
    except Exception as ex:
        print(f"[changed_pages] error: {ex}")
        perf_log(
            "pdf_changed_pages_scan",
            file=os.path.basename(path),
            pages=total,
            error=str(ex),
            elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )
        return None
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        try:
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass
    
class PdfLoaderThread(QObject):
    # Emitted every CHUNK_SIZE pages:  (pages_so_far, loaded_count, total_count)
    pages_ready = pyqtSignal(object, int, int)   # object = list[QImage]

    # Emitted once at the end:  (all_pages, error_str_or_None)
    done  = pyqtSignal(object, object)           # object = list[QImage]
    error = pyqtSignal(str)
    finished = pyqtSignal()
    started = pyqtSignal()

    def __init__(self, path: str, zoom: float = PDF_RENDER_ZOOM,
                 chunk_size: int = CHUNK_SIZE, use_cache: bool = True,
                 store_cache: bool = True, cache_variant: str | None = None,
                 show_annots: bool = True, parent=None):
        super().__init__(parent)
        self._path       = path
        self._zoom       = zoom
        self._chunk_size = chunk_size
        self._use_cache  = bool(use_cache)
        self._store_cache = bool(store_cache)
        self._stop_flag  = False
        self._cache_variant = cache_variant
        self._show_annots = bool(show_annots)
        self._is_running = False
        self._runnable = None

    def isRunning(self):
        return self._is_running

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._stop_flag = False
        self.started.emit()

        class LoaderRunnable(QRunnable):
            def __init__(self, outer):
                super().__init__()
                self.outer = outer

            def run(self):
                try:
                    self.outer.run()
                finally:
                    self.outer._is_running = False
                    self.outer.finished.emit()

        self._runnable = LoaderRunnable(self)
        QThreadPool.globalInstance().start(self._runnable)

    def stop(self):
        self._stop_flag = True

    def quit(self):
        self.stop()

    def wait(self, timeout_ms=500):
        start_time = time.monotonic()
        while self._is_running:
            if (time.monotonic() - start_time) * 1000 > timeout_ms:
                return False
            time.sleep(0.01)
        return True

    def run(self):
        t_thread_start = time.perf_counter()
        fname = os.path.basename(self._path)
        if not PDF_SUPPORT:
            self.done.emit([], "PyMuPDF not installed — run: pip install pymupdf")
            return
        doc = None
        try:
            doc = fitz.open(self._path)
            if doc.is_encrypted:
                self.done.emit([], "PDF is password-protected.")
                return

            total = len(doc)
            mat   = fitz.Matrix(self._zoom, self._zoom)
            pages : list[QImage] = []
            last_emitted = 0
            cache_hits = 0
            rendered_pages = 0

            print(
                "[DEBUG][pdf_loader] "
                f"start file={os.path.basename(self._path)} pages={total} "
                f"zoom={self._zoom} cache={self._use_cache}"
            )
            perf_log(
                "pdf_loader_start",
                file=fname,
                pages=total,
                zoom=self._zoom,
                chunk_size=self._chunk_size,
                use_cache=self._use_cache,
                store_cache=self._store_cache,
                variant=self._cache_variant or "default",
            )

            for page_num in range(total):
                if self._stop_flag:
                    return

                # Cache hit?
                cached = PAGE_CACHE.get_image(self._path, page_num, variant=self._cache_variant) if self._use_cache else None
                if cached and not cached.isNull():
                    pages.append(cached)
                    cache_hits += 1
                else:
                    try:
                        img = pdf_page_to_image(doc.load_page(page_num), mat, show_annots=self._show_annots)
                        if not img.isNull():
                            if self._store_cache and hasattr(PAGE_CACHE, "put_image"):
                                PAGE_CACHE.put_image(
                                    self._path,
                                    page_num,
                                    img,
                                    variant=self._cache_variant,
                                    render_zoom=self._zoom,
                                )
                            pages.append(img)
                            rendered_pages += 1
                    except Exception:
                        continue  # skip bad page, keep going

                loaded = len(pages)
                if loaded - last_emitted >= self._chunk_size:
                    print(
                        "[DEBUG][pdf_loader] "
                        f"chunk loaded={loaded}/{total} "
                        f"cache_hits={cache_hits} rendered={rendered_pages}"
                    )
                    perf_log(
                        "pdf_loader_chunk",
                        file=fname,
                        loaded=loaded,
                        pages=total,
                        cache_hits=cache_hits,
                        rendered=rendered_pages,
                        elapsed_ms=round((time.perf_counter() - t0 if 't0' in locals() else time.perf_counter() - t_thread_start) * 1000.0, 3),
                    )
                    self.pages_ready.emit(list(pages), loaded, total)
                    last_emitted = loaded

            if self._stop_flag:
                return

            # Final emit (catches leftover pages not in last chunk)
            print(
                "[DEBUG][pdf_loader] "
                f"done loaded={len(pages)}/{total} "
                f"cache_hits={cache_hits} rendered={rendered_pages}"
            )
            perf_log(
                "pdf_loader_done",
                file=fname,
                loaded=len(pages),
                pages=total,
                cache_hits=cache_hits,
                rendered=rendered_pages,
                elapsed_ms=round((time.perf_counter() - t_thread_start) * 1000.0, 3),
            )
            self.done.emit(list(pages), None)

        except Exception as ex:
            perf_log(
                "pdf_loader_done",
                file=fname,
                error=str(ex),
                elapsed_ms=round((time.perf_counter() - t_thread_start) * 1000.0, 3),
            )
            self.done.emit([], str(ex))
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            try:
                fitz.TOOLS.store_shrink(100)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
