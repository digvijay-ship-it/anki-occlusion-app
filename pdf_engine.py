# ═══════════════════════════════════════════════════════════════════════════════
#  PDF ENGINE  —  Virtual Page Renderer  (v20)
#
#  KEY CHANGE from v18/v19:
#    ❌  One giant combined QPixmap  (broke at >32 767 px — Qt hard limit)
#    ✅  List[QPixmap] — one entry per PDF page, drawn on-demand in paintEvent
#
#  Public API (unchanged for callers):
#    PdfLoaderThread   — emits pages_ready(list[QPixmap], int, int) + done/error
#    pdf_page_to_pixmap(page, mat) → QPixmap
#    PAGE_CACHE        — imported from cache_manager
# ═══════════════════════════════════════════════════════════════════════════════

import os
import tempfile

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QPixmap

from cache_manager import PAGE_CACHE

# PyMuPDF
try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# How many pages to emit per chunk so the canvas updates quickly
CHUNK_SIZE = 40


# ═══════════════════════════════════════════════════════════════════════════════
#  LOW-LEVEL PAGE RENDER
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_page_to_pixmap(page, mat) -> QPixmap:
    """Render one fitz page → QPixmap via a temp PNG (avoids Qt raw-bytes issues)."""
    pix = page.get_pixmap(matrix=mat, alpha=False)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pix.save(tmp)
        return QPixmap(tmp)
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  PDF LOADER THREAD  —  emits individual page QPixmaps, never a combined one
# ═══════════════════════════════════════════════════════════════════════════════

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