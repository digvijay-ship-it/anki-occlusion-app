from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from functools import lru_cache

from PyQt5.QtGui import QImage, QPixmap


DLL_BASENAME = "anki_pdf_native.dll"


@dataclass(frozen=True)
class NativePdfBackendStatus:
    requested: str
    available: bool
    active: bool
    is_stub: bool
    path: str = ""
    version: str = ""
    error: str = ""


@dataclass(frozen=True)
class NativePdfPageMetrics:
    page_index: int
    width: float
    height: float


@dataclass(frozen=True)
class NativePdfRenderedPage:
    page_index: int
    width: int
    height: int
    stride: int
    bgra: bytes

    def to_qimage(self) -> QImage:
        img = QImage(self.bgra, self.width, self.height, self.stride, QImage.Format_ARGB32)
        return img.copy()

    def to_qpixmap(self) -> QPixmap:
        return QPixmap.fromImage(self.to_qimage())


class NativePdfDocument:
    def __init__(self, backend: "NativePdfBackend", handle: ctypes.c_void_p, path: str):
        self._backend = backend
        self._handle = handle
        self.path = path

    @property
    def closed(self) -> bool:
        return not bool(self._handle and self._handle.value)

    def close(self) -> None:
        if self.closed:
            return
        self._backend._close_document_handle(self._handle)
        self._handle = ctypes.c_void_p()

    def page_count(self) -> int:
        self._ensure_open()
        return self._backend._page_count(self._handle)

    def page_metrics(self, page_index: int) -> NativePdfPageMetrics:
        self._ensure_open()
        width = ctypes.c_double()
        height = ctypes.c_double()
        ok = self._backend._page_size(self._handle, int(page_index), width, height)
        if not ok:
            raise RuntimeError(self._backend.last_error())
        return NativePdfPageMetrics(page_index=int(page_index), width=float(width.value), height=float(height.value))

    def render_page(self, page_index: int, zoom: float) -> NativePdfRenderedPage:
        self._ensure_open()
        buf_ptr = ctypes.POINTER(ctypes.c_ubyte)()
        width = ctypes.c_int()
        height = ctypes.c_int()
        stride = ctypes.c_int()
        ok = self._backend._render_page_bgra(
            self._handle,
            int(page_index),
            float(zoom),
            ctypes.byref(buf_ptr),
            ctypes.byref(width),
            ctypes.byref(height),
            ctypes.byref(stride),
        )
        if not ok:
            raise RuntimeError(self._backend.last_error())
        try:
            size = max(0, int(stride.value)) * max(0, int(height.value))
            payload = ctypes.string_at(buf_ptr, size)
        finally:
            self._backend._free_buffer(buf_ptr)
        return NativePdfRenderedPage(
            page_index=int(page_index),
            width=int(width.value),
            height=int(height.value),
            stride=int(stride.value),
            bgra=payload,
        )

    def render_page_qpixmap(self, page_index: int, zoom: float) -> QPixmap:
        return self.render_page(page_index, zoom).to_qpixmap()

    def _ensure_open(self) -> None:
        if self.closed:
            raise RuntimeError("Native PDF document already closed")

    def __enter__(self) -> "NativePdfDocument":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class NativePdfBackend:
    """ctypes bridge for the future native MuPDF DLL."""

    def __init__(self):
        self._dll = None
        self._path = ""
        self._error = ""

    def load(self) -> bool:
        if self._dll is not None:
            return True
        path = _find_native_backend_dll()
        if not path:
            self._error = f"{DLL_BASENAME} not found"
            return False
        try:
            dll = ctypes.CDLL(path)
            self._configure_dll(dll)
            self._dll = dll
            self._path = path
            self._error = ""
            return True
        except OSError as ex:
            self._error = str(ex)
            return False
        except Exception as ex:
            self._error = str(ex)
            return False

    def _configure_dll(self, dll) -> None:
        if hasattr(dll, "ao_pdf_backend_version"):
            dll.ao_pdf_backend_version.restype = ctypes.c_char_p
        if hasattr(dll, "ao_pdf_last_error"):
            dll.ao_pdf_last_error.restype = ctypes.c_char_p
        if hasattr(dll, "ao_pdf_backend_is_stub"):
            dll.ao_pdf_backend_is_stub.restype = ctypes.c_int

        if hasattr(dll, "ao_pdf_open_document"):
            dll.ao_pdf_open_document.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
            dll.ao_pdf_open_document.restype = ctypes.c_int
        if hasattr(dll, "ao_pdf_close_document"):
            dll.ao_pdf_close_document.argtypes = [ctypes.c_void_p]
            dll.ao_pdf_close_document.restype = None
        if hasattr(dll, "ao_pdf_get_page_count"):
            dll.ao_pdf_get_page_count.argtypes = [ctypes.c_void_p]
            dll.ao_pdf_get_page_count.restype = ctypes.c_int
        if hasattr(dll, "ao_pdf_get_page_size"):
            dll.ao_pdf_get_page_size.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
            ]
            dll.ao_pdf_get_page_size.restype = ctypes.c_int
        if hasattr(dll, "ao_pdf_render_page_bgra"):
            dll.ao_pdf_render_page_bgra.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_double,
                ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            dll.ao_pdf_render_page_bgra.restype = ctypes.c_int
        if hasattr(dll, "ao_pdf_free_buffer"):
            dll.ao_pdf_free_buffer.argtypes = [ctypes.c_void_p]
            dll.ao_pdf_free_buffer.restype = None

    @property
    def path(self) -> str:
        return self._path

    @property
    def error(self) -> str:
        return self._error

    def version(self) -> str:
        if self._dll is None and not self.load():
            return ""
        try:
            raw = self._dll.ao_pdf_backend_version()
            if not raw:
                return ""
            return raw.decode("utf-8", errors="replace")
        except Exception as ex:
            self._error = str(ex)
            return ""

    def last_error(self) -> str:
        if self._dll is None and not self.load():
            return self._error
        try:
            raw = self._dll.ao_pdf_last_error()
            if not raw:
                return self._error
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return self._error

    def is_stub(self) -> bool:
        if self._dll is None and not self.load():
            return False
        try:
            if not hasattr(self._dll, "ao_pdf_backend_is_stub"):
                return False
            return bool(self._dll.ao_pdf_backend_is_stub())
        except Exception as ex:
            self._error = str(ex)
            return False

    def can_render(self) -> bool:
        if not self.load() or self.is_stub():
            return False
        required = (
            "ao_pdf_open_document",
            "ao_pdf_close_document",
            "ao_pdf_get_page_count",
            "ao_pdf_get_page_size",
            "ao_pdf_render_page_bgra",
            "ao_pdf_free_buffer",
        )
        return all(hasattr(self._dll, name) for name in required)

    def open_document(self, path: str) -> NativePdfDocument:
        if not self.can_render():
            raise RuntimeError(self.last_error() or "Native PDF backend is not ready")
        handle = ctypes.c_void_p()
        path_utf8 = os.path.abspath(path).encode("utf-8", errors="surrogatepass")
        ok = self._dll.ao_pdf_open_document(path_utf8, ctypes.byref(handle))
        if not ok or not handle.value:
            raise RuntimeError(self.last_error() or f"Could not open PDF: {path}")
        return NativePdfDocument(self, handle, os.path.abspath(path))

    def _close_document_handle(self, handle: ctypes.c_void_p) -> None:
        if self._dll is not None and handle and handle.value and hasattr(self._dll, "ao_pdf_close_document"):
            self._dll.ao_pdf_close_document(handle)

    def _page_count(self, handle: ctypes.c_void_p) -> int:
        count = int(self._dll.ao_pdf_get_page_count(handle))
        if count < 0:
            raise RuntimeError(self.last_error())
        return count

    def _page_size(self, handle: ctypes.c_void_p, page_index: int, width, height) -> bool:
        return bool(self._dll.ao_pdf_get_page_size(handle, int(page_index), ctypes.byref(width), ctypes.byref(height)))

    def _render_page_bgra(self, handle: ctypes.c_void_p, page_index: int, zoom: float, out_buf, out_width, out_height, out_stride) -> bool:
        return bool(
            self._dll.ao_pdf_render_page_bgra(
                handle,
                int(page_index),
                float(zoom),
                out_buf,
                out_width,
                out_height,
                out_stride,
            )
        )

    def _free_buffer(self, buf_ptr) -> None:
        if self._dll is not None and hasattr(self._dll, "ao_pdf_free_buffer") and buf_ptr:
            self._dll.ao_pdf_free_buffer(buf_ptr)


def _candidate_dll_paths() -> list[str]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    names = [
        os.environ.get("ANKI_NATIVE_PDF_DLL", "").strip(),
        os.path.join(root, DLL_BASENAME),
        os.path.join(root, "native", "bin", DLL_BASENAME),
        os.path.join(root, "native", "build", "Release", DLL_BASENAME),
        os.path.join(root, "native", "build", DLL_BASENAME),
    ]
    return [p for p in names if p]


def _find_native_backend_dll() -> str:
    for path in _candidate_dll_paths():
        if os.path.exists(path):
            return os.path.abspath(path)
    return ""


def requested_backend() -> str:
    mode = (os.environ.get("ANKI_PDF_BACKEND", "") or "").strip().lower()
    if mode in {"native", "python"}:
        return mode
    return "native"


@lru_cache(maxsize=1)
def get_native_backend() -> NativePdfBackend:
    return NativePdfBackend()


def native_backend_status() -> NativePdfBackendStatus:
    requested = requested_backend()
    backend = get_native_backend()
    available = backend.load()
    is_stub = backend.is_stub() if available else False
    active = requested == "native" and available and not is_stub and backend.can_render()
    version = backend.version() if available else ""
    error = backend.last_error() if (not active and available) else backend.last_error() if not available else ""
    return NativePdfBackendStatus(
        requested=requested,
        available=available,
        active=active,
        is_stub=is_stub,
        path=backend.path,
        version=version,
        error=error,
    )


def active_pdf_backend_name() -> str:
    status = native_backend_status()
    return "native" if status.active else "python"


def describe_pdf_backend() -> str:
    status = native_backend_status()
    if status.active:
        ver = f" ({status.version})" if status.version else ""
        return f"native MuPDF DLL{ver}"
    if status.is_stub:
        return "python fallback (native DLL stub only)"
    if status.requested == "native" and status.error:
        return f"python fallback ({status.error})"
    return "python PyMuPDF renderer"


def render_pdf_pages_native(path: str, page_nums, zoom: float) -> dict[int, QPixmap]:
    status = native_backend_status()
    if not status.active:
        return {}
    backend = get_native_backend()
    rendered = {}
    with backend.open_document(path) as doc:
        total = doc.page_count()
        targets = sorted({int(pn) for pn in (page_nums or []) if int(pn) >= 0})
        for page_num in targets:
            if page_num >= total:
                continue
            qpx = doc.render_page_qpixmap(page_num, zoom)
            if qpx is not None and not qpx.isNull():
                rendered[page_num] = qpx
    return rendered
