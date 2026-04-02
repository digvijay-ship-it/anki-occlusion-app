
# ═══════════════════════════════════════════════════════════════════════════════
#  PDF HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

import os
import tempfile
from collections import OrderedDict

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QColor, QPainter, QPen

# PyMuPDF Import
try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

CHUNK_SIZE = 30   # Kitne pages ek baar mein load hon

# ═══════════════════════════════════════════════════════════════════════════════
#  LRU PAGE CACHE  (v18 — RAM Encounter Fix)
# ═══════════════════════════════════════════════════════════════════════════════

class LRUPageCache:
    def __init__(self, max_pages: int = 15):
        self._cache = OrderedDict()
        self._max = max_pages

    def get(self, path: str, page_num: int):
        key = (path, page_num)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, path: str, page_num: int, pixmap: QPixmap):
        key = (path, page_num)
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def invalidate_pdf(self, path: str):
        keys_to_del = [k for k in self._cache if k[0] == path]
        for k in keys_to_del: del self._cache[k]
PAGE_CACHE = LRUPageCache(max_pages=15)

# Global singleton — poore app mein ek hi LRU cache

def pdf_page_to_pixmap(page, mat):
    pix = page.get_pixmap(matrix=mat, alpha=False)
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pix.save(tmp_path)
        qpx = QPixmap(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return qpx

def pdf_to_pixmaps(path: str, zoom: float = 1.5):
    """
    [LRU CACHE v18] Individual pages pehle PAGE_CACHE se lo.
    Cache miss hone par fitz se load karo aur cache mein daalo.
    """
    pages, errors = [], []
    if not PDF_SUPPORT:
        return pages, "PyMuPDF not installed — run: pip install pymupdf"
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            return pages, "PDF is password-protected / encrypted."
        mat = fitz.Matrix(zoom, zoom)
        for page_num in range(len(doc)):
            # Pehle LRU cache check karo
            cached = PAGE_CACHE.get(path, page_num)
            if cached:
                pages.append(cached)
                continue
            try:
                qpx = pdf_page_to_pixmap(doc.load_page(page_num), mat)
                if qpx.isNull():
                    errors.append(f"Page {page_num+1}: null pixmap")
                else:
                    PAGE_CACHE.put(path, page_num, qpx)
                    pages.append(qpx)
            except Exception as e:
                errors.append(f"Page {page_num+1}: {e}")
        doc.close()
    except Exception as e:
        return pages, str(e)
    err_str = "\n".join(errors) if errors and not pages else None
    return pages, err_str

# ═══════════════════════════════════════════════════════════════════════════════
#  PDF LOADER THREAD  (Progressive chunk loading — 10 pages at a time)
# ═══════════════════════════════════════════════════════════════════════════════

CHUNK_SIZE = 30   # Kitne pages ek baar mein load hon

def _build_combined_from_pages(pages):
    """Pages list se ek combined QPixmap banao."""
    if not pages:
        return QPixmap()
    GAP       = 12
    SEP_COLOR = QColor("#45475A")
    total_w   = max(p.width()  for p in pages)
    total_h   = sum(p.height() for p in pages) + GAP * (len(pages) - 1)
    combined  = QPixmap(total_w, total_h)
    combined.fill(QColor("#1E1E2E"))
    painter = QPainter(combined)
    y = 0
    for i, px in enumerate(pages):
        painter.drawPixmap(0, y, px)
        y += px.height()
        if i < len(pages) - 1:
            painter.setPen(QPen(SEP_COLOR, 2))
            painter.drawLine(0, y + GAP // 2, total_w, y + GAP // 2)
            y += GAP
    painter.end()
    return combined
def pdf_to_combined_pixmap(path: str, zoom: float = 1.5):
    """
    [LRU CACHE v18 ENCOUNTER] 
    यह फंक्शन PDF के पेजों को लोड करके उन्हें एक साथ जोड़ता है।
    """
    if not PDF_SUPPORT:
        return QPixmap(), 0, "PyMuPDF not installed"
    
    try:
        doc = fitz.open(path)
        total_pages = len(doc)
        mat = fitz.Matrix(zoom, zoom)
        all_pages = []

        for i in range(total_pages):
            # LRU Cache से पेज उठाओ या नया लोड करो
            cached = PAGE_CACHE.get(path, i)
            if cached:
                all_pages.append(cached)
            else:
                qpx = pdf_page_to_pixmap(doc.load_page(i), mat)
                if not qpx.isNull():
                    PAGE_CACHE.put(path, i, qpx)
                    all_pages.append(qpx)
        
        doc.close()
        # अब इन पेजों को एक लंबी इमेज में कंबाइन करो
        combined = _build_combined_from_pages(all_pages)
        return combined, total_pages, None

    except Exception as e:
        return QPixmap(), 0, str(e)

class PdfLoaderThread(QThread):
    """
    [PROGRESSIVE LOADING v17]
    10-10 pages ka chunk emit karta hai — user pehle chunk se kaam shuru
    kar sakta hai jabki baaki background mein load hote hain.
    """
    chunk_ready = pyqtSignal(object, int, int)  # (QPixmap combined_so_far, loaded, total)
    done        = pyqtSignal(object, object)    # (QPixmap final_combined, error_str or None)
    error       = pyqtSignal(str)

    def __init__(self, path: str, chunk_size: int = CHUNK_SIZE, parent=None):
        super().__init__(parent)
        self._path       = path
        self._chunk_size = chunk_size
        self._stop_flag  = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        if not PDF_SUPPORT:
            self.done.emit(QPixmap(), "PyMuPDF not installed")
            return
        try:
            doc = fitz.open(self._path)
            if doc.is_encrypted:
                self.done.emit(QPixmap(), "PDF is password-protected.")
                return
            total   = len(doc)
            mat     = fitz.Matrix(1.5, 1.5)
            all_pages = []

            for page_num in range(total):
                if self._stop_flag:
                    doc.close()
                    return

                # [LRU CACHE v18] Pehle cache check karo — fitz call hi mat karo!
                cached = PAGE_CACHE.get(self._path, page_num)
                if cached:
                    qpx = cached
                else:
                    try:
                        qpx = pdf_page_to_pixmap(doc.load_page(page_num), mat)
                        if not qpx.isNull():
                            PAGE_CACHE.put(self._path, page_num, qpx)
                    except Exception:
                        continue

                if not qpx.isNull():
                    all_pages.append(qpx)

                # Har CHUNK_SIZE pages ke baad preview emit karo
                loaded = len(all_pages)
                if loaded > 0 and loaded % self._chunk_size == 0:
                    preview = _build_combined_from_pages(all_pages)
                    self.chunk_ready.emit(preview, loaded, total)

            doc.close()
            if self._stop_flag:
                return
            final = _build_combined_from_pages(all_pages)
            self.done.emit(final, None)

        except Exception as ex:
            self.done.emit(QPixmap(), str(ex))