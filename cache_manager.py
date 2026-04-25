"""
cache_manager.py  —  Cache Inspector & Manager Panel
=====================================================
Replaces the hardcoded limits in pdf_engine.py:
  • LRUPageCache(max_pages=15)       → UNLIMITED
  • DiskCombinedCache(max_pdfs=3,    → UNLIMITED (no LRU eviction)
                      ttl_minutes=2) → NO TTL

Shows a floating side panel with:
  • Per-PDF: disk cache size + RAM page cache size + mask cache size
  • "🗑 Remove" button per PDF  → clears its disk cache + RAM pages + mask layer
  • "🧹 Clear All" button       → nukes everything
  • Live refresh every 5 seconds + manual Refresh button

HOW TO INTEGRATE
─────────────────
1. In pdf_engine.py  replace the last two lines:
       PAGE_CACHE     = LRUPageCache(max_pages=15)
       COMBINED_CACHE = DiskCombinedCache(max_pdfs=3, ttl_minutes=2)
   with:
       PAGE_CACHE     = LRUPageCache()            # unlimited
       COMBINED_CACHE = DiskCombinedCache()       # unlimited, no TTL

2. In anki_occlusion_v19.py  (MainWindow.__init__)  add anywhere after
   self.setCentralWidget(home):
       from cache_manager import CacheManagerPanel
       self._cache_panel = CacheManagerPanel(parent=self)
       self._cache_panel.show()

   Or wire it to a menu / toolbar button:
       btn = QPushButton("💾 Cache")
       btn.clicked.connect(self._toggle_cache_panel)
       ...
       def _toggle_cache_panel(self):
           if self._cache_panel.isVisible():
               self._cache_panel.hide()
           else:
               self._cache_panel.show()
               self._cache_panel.refresh()
"""

import os
import hashlib
import tempfile
import time
from collections import OrderedDict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPalette, QFont

# ── Theme (matches your app) ─────────────────────────────────────────────────
C_BG      = "#1E1E2E"
C_SURFACE = "#2A2A3E"
C_CARD    = "#313145"
C_ACCENT  = "#7C6AF7"
C_GREEN   = "#50FA7B"
C_RED     = "#FF5555"
C_YELLOW  = "#F1FA8C"
C_TEXT    = "#CDD6F4"
C_SUBTEXT = "#A6ADC8"
C_BORDER  = "#45475A"

_SS = f"""
QWidget          {{ background:{C_BG}; color:{C_TEXT}; font-family:'Segoe UI'; font-size:13px; }}
QFrame#card      {{ background:{C_SURFACE}; border:1px solid {C_BORDER}; border-radius:8px; }}
QLabel           {{ background:transparent; color:{C_TEXT}; }}
QLabel#sub       {{ color:{C_SUBTEXT}; font-size:12px; }}
QLabel#size      {{ color:{C_GREEN}; font-weight:bold; }}
QLabel#title     {{ color:{C_TEXT}; font-weight:bold; font-size:14px; }}
QPushButton      {{ background:{C_ACCENT}; color:white; border:none; border-radius:6px;
                    padding:5px 12px; font-weight:bold; }}
QPushButton:hover{{ background:#6A58E0; }}
QPushButton#del  {{ background:{C_RED}; }}
QPushButton#del:hover{{ background:#CC3333; }}
QPushButton#clr  {{ background:#444460; color:{C_TEXT}; }}
QPushButton#clr:hover{{ background:#55557A; }}
QScrollArea      {{ border:none; background:transparent; }}
QScrollBar:vertical {{ background:{C_SURFACE}; width:6px; border-radius:3px; }}
QScrollBar::handle:vertical {{ background:{C_BORDER}; border-radius:3px; }}
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  BOUNDED LRU PAGE CACHE
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_PDF_IDLE_MINUTES = 5

class LRUPageCache:
    """
    In-RAM page cache with per-PDF inactivity expiry.
    If a PDF has not been touched for idle_minutes, all its cached pages are cleared.
    """
    def __init__(self, idle_minutes: float = DEFAULT_PDF_IDLE_MINUTES):
        self._cache = OrderedDict()
        self._hashes = {}   
        self._pdf_last_access  = {}   

    def _touch(self, path: str, now=None):
        pass   # No longer needed

    def expire_stale(self, now=None):
        pass   # Auto-clean removed — disk cache handles persistence

    # ── Disk helpers ──────────────────────────────────────────────────────────

    def _disk_page_path(self, path: str, page_num: int) -> str:
        """Return the PNG file path for a given PDF + page in the disk cache."""
        h = hashlib.md5(path.encode("utf-8")).hexdigest()
        # Use COMBINED_CACHE._dir at call time (not import time) so the
        # user-chosen location is always respected.
        cache_dir = COMBINED_CACHE._dir if "COMBINED_CACHE" in globals() else os.path.join(
            os.path.expanduser("~"), ".cache", "anki_occlusion"
        )
        page_dir = os.path.join(cache_dir, f"vcache_{h}")
        return os.path.join(page_dir, f"page_{page_num:04d}.png")

    def _save_to_disk(self, path: str, page_num: int, pixmap) -> None:
        """Save a QPixmap as PNG to disk. Silent on failure."""
        try:
            fpath = self._disk_page_path(path, page_num)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            if not os.path.exists(fpath):   # already saved → skip
                pixmap.save(fpath, "PNG")
        except Exception as e:
            print(f"[cache][_save_to_disk] ⚠ failed to save p.{page_num+1} → {e}")

    def _load_from_disk(self, path: str, page_num: int):
        """Try to load a QPixmap from disk. Returns None on miss."""
        try:
            fpath = self._disk_page_path(path, page_num)
            if not os.path.exists(fpath):
                return None
            from PyQt5.QtGui import QPixmap
            px = QPixmap(fpath)
            return px if not px.isNull() else None
        except Exception:
            return None

    # ── Main API ──────────────────────────────────────────────────────────────

    def get(self, path: str, page_num: int):
        self.expire_stale()
        key = (path, page_num)

        # 1. RAM hit — fastest
        if key in self._cache:
            self._cache.move_to_end(key)
            self._touch(path)
            return self._cache[key]

        # 2. Disk hit — load PNG → put back in RAM
        px = self._load_from_disk(path, page_num)
        if px is not None:
            self._cache[key] = px
            self._cache.move_to_end(key)
            self._touch(path)
            print(f"[cache][disk_hit] ⚡ p.{page_num+1}")
            return px

        return None

    def put(self, path: str, page_num: int, pixmap):
        self.expire_stale()
        key = (path, page_num)
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        self._touch(path)
        # Save to disk asynchronously — silent, non-blocking
        self._save_to_disk(path, page_num, pixmap)

    def invalidate_pdf(self, path: str):
        # RAM
        keys = [k for k in self._cache if k[0] == path]
        for k in keys:
            del self._cache[k]
        # Disk
        try:
            cache_dir = COMBINED_CACHE._dir if "COMBINED_CACHE" in globals() else ""
            if cache_dir:
                h = hashlib.md5(path.encode("utf-8")).hexdigest()
                v_dir = os.path.join(cache_dir, f"vcache_{h}")
                if os.path.exists(v_dir):
                    import shutil
                    shutil.rmtree(v_dir, ignore_errors=True)
        except Exception:
            pass
    def get_page_hash(self, path, page_num):
        return self._hashes.get((path, page_num))

    def set_page_hash(self, path, page_num, h):
        self._hashes[(path, page_num)] = h

    def invalidate_pages(self, path, page_nums):
        for pn in page_nums:
            key = (path, pn)
            self._cache.pop(key, None)
            try:
                fpath = self._disk_page_path(path, pn)
                if os.path.exists(fpath):
                    os.unlink(fpath)
            except Exception:
                pass
            
    def clear(self):
        ram_count = len(self._cache)
        self._cache.clear()
        self._pdf_last_access.clear()
        # Wipe all vcache_ folders from disk
        disk_deleted = 0
        try:
            cache_dir = COMBINED_CACHE._dir if "COMBINED_CACHE" in globals() else ""
            if cache_dir and os.path.exists(cache_dir):
                import shutil
                for name in os.listdir(cache_dir):
                    if name.startswith("vcache_"):
                        folder = os.path.join(cache_dir, name)
                        file_list = os.listdir(folder)
                        disk_deleted += len(file_list)
                        shutil.rmtree(folder, ignore_errors=True)
        except Exception as e:
            print(f"[cache][clear] ⚠ disk error: {e}")
        print(f"[cache][clear] 🗑 RAM cleared — {ram_count} pages | Disk cleared — {disk_deleted} PNG files deleted")
    def clear_ram_only(self):
        """Sirf RAM clear karo — disk PNG files safe rehte hain."""
        ram_count = len(self._cache)
        self._cache.clear()
        print(f"[cache][clear_ram_only] ✅ RAM cleared — {ram_count} pages removed, disk untouched")
    # ── Inspector helpers ─────────────────────────────────────────────────────

    def ram_bytes_for_pdf(self, path: str) -> int:
        """Estimate RAM bytes for all cached pages of one PDF."""
        total = 0
        for (p, _), px in self._cache.items():
            if p == path:
                total += px.width() * px.height() * 4   # RGBA = 4 bytes/pixel
        return total

    def all_cached_pdfs(self) -> set:
        return {p for (p, _) in self._cache}


# ═══════════════════════════════════════════════════════════════════════════════
#  UNLIMITED DISK COMBINED CACHE  (replaces the 3-PDF / 2-min limited one)
# ═══════════════════════════════════════════════════════════════════════════════

class DiskCombinedCache:
    """
    UNLIMITED disk cache for combined PDF pixmaps.
    No LRU cap, no TTL — files persist until invalidated or Clear All.
    """
    def __init__(self, cache_dir: str = ""):
        self._dir = cache_dir if cache_dir else os.path.join(
            os.path.expanduser("~"), ".cache", "anki_occlusion"
        )
        self._index = OrderedDict()   # pdf_path → cache_png_path  (LRU order for display only)
        os.makedirs(self._dir, exist_ok=True)
        self._rebuild_index()

    def _cache_path(self, pdf_path: str) -> str:
        h = hashlib.md5(pdf_path.encode("utf-8")).hexdigest()
        return os.path.join(self._dir, f"combined_{h}.png")

    def _rebuild_index(self):
        """On startup, re-register any existing cache files so the GUI shows them."""
        try:
            for fname in os.listdir(self._dir):
                if not fname.startswith("combined_") or fname.endswith(".meta"):
                    continue
                fpath = os.path.join(self._dir, fname)
                meta  = fpath + ".meta"
                if os.path.exists(meta):
                    # We can't reverse the hash to get pdf_path, so we store
                    # the hash-path as the key — good enough for size display.
                    self._index[fpath] = fpath
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, pdf_path: str):
        cache_file = self._cache_path(pdf_path)
        meta_file  = cache_file + ".meta"
        if not os.path.exists(cache_file) or not os.path.exists(meta_file):
            return None
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                total_pages = int(f.read().strip())
        except Exception:
            return None
        from PyQt5.QtGui import QPixmap
        px = QPixmap(cache_file)
        if px.isNull():
            return None
        # Update LRU order
        self._index.pop(pdf_path, None)
        self._index[pdf_path] = cache_file
        return (px, total_pages)

    def put(self, pdf_path: str, combined, total_pages: int):
        from PyQt5.QtGui import QPixmap
        if combined.isNull():
            return
        cache_file = self._cache_path(pdf_path)
        meta_file  = cache_file + ".meta"
        try:
            combined.save(cache_file, "PNG")
            with open(meta_file, "w", encoding="utf-8") as f:
                f.write(str(total_pages))
        except Exception:
            return
        self._index.pop(pdf_path, None)
        self._index[pdf_path] = cache_file

    def invalidate(self, pdf_path: str):
        cache_file = self._cache_path(pdf_path)
        self._index.pop(pdf_path, None)
        self._delete_files(cache_file)

    def clear(self):
        for pdf_path, cache_file in list(self._index.items()):
            self._delete_files(cache_file)
        self._index.clear()
        # Also wipe any orphan files
        try:
            for fname in os.listdir(self._dir):
                if fname.startswith("combined_"):
                    os.unlink(os.path.join(self._dir, fname))
        except Exception:
            pass

    @staticmethod
    def _delete_files(cache_file: str):
        for f in (cache_file, cache_file + ".meta"):
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except Exception:
                pass

    # ── Inspector helpers ─────────────────────────────────────────────────────

    def disk_bytes_for_pdf(self, pdf_path: str) -> int:
        """File: cache_manager.py -> Class: DiskCombinedCache"""
        import hashlib
        h = hashlib.md5(pdf_path.encode("utf-8")).hexdigest()
        # v20 virtual cache folder
        v_dir = os.path.join(self._dir, f"vcache_{h}")
        
        if not os.path.exists(v_dir): return 0
        total = 0
        try:
            for f in os.listdir(v_dir):
                total += os.path.getsize(os.path.join(v_dir, f))
        except Exception: pass
        return total
        
    def all_cached_pdfs(self) -> list:
        """Returns list of pdf_paths that have a disk cache entry."""
        return [p for p in self._index if os.path.exists(self._cache_path(p))]


# ═══════════════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL SINGLETONS  (same names as before — drop-in replacement)
# ═══════════════════════════════════════════════════════════════════════════════

PAGE_CACHE     = LRUPageCache()
def _load_cache_dir() -> str:
    try:
        from PyQt5.QtCore import QSettings
        s = QSettings("AnkiOcclusion", "App")
        return s.value("cache_dir", "")
    except Exception:
        return ""

COMBINED_CACHE = DiskCombinedCache(cache_dir=_load_cache_dir())


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n/1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n/1024**2:.1f} MB"
    return f"{n/1024**3:.2f} GB"

def _short_name(path: str) -> str:
    name = os.path.basename(path)
    return name if len(name) <= 36 else name[:33] + "..."


# ═══════════════════════════════════════════════════════════════════════════════
#  MASK CACHE REGISTRY
#  OcclusionCanvas instances register themselves here so we can query and
#  clear their _mask_cache_layer from outside.
# ═══════════════════════════════════════════════════════════════════════════════

class _MaskRegistry:
    """
    Global registry of live OcclusionCanvas instances, keyed by pdf_path.
    Canvas calls register(pdf_path, self) on load_pixmap / set_boxes.
    """
    def __init__(self):
        self._map = {}   # pdf_path → set of OcclusionCanvas

    def register(self, pdf_path: str, canvas):
        self._map.setdefault(pdf_path, set()).add(canvas)

    def unregister(self, canvas):
        for path, canvases in list(self._map.items()):
            canvases.discard(canvas)
            if not canvases:
                del self._map[path]

    def mask_bytes_for_pdf(self, pdf_path: str) -> int:
        total = 0
        for canvas in self._map.get(pdf_path, set()):
            try:
                layer = getattr(canvas, "_mask_cache_layer", None)
                if layer and not layer.isNull():
                    total += layer.width() * layer.height() * 4
            except RuntimeError:
                pass
        return total

    def invalidate_masks_for_pdf(self, pdf_path: str):
        """Force all canvases showing this PDF to rebuild their mask layer."""
        dead = set()
        for canvas in self._map.get(pdf_path, set()):
            try:
                canvas._mask_cache_layer = None
                canvas._mask_cache_dirty = True
                canvas.update()
            except RuntimeError:
                dead.add(canvas)
        if dead:
            self._map[pdf_path] -= dead

    def all_registered_pdfs(self) -> set:
        return set(self._map.keys())


MASK_REGISTRY = _MaskRegistry()


# ═══════════════════════════════════════════════════════════════════════════════
#  PIXMAP REGISTRY
#  Saare "hidden" large pixmaps jo panel mein nahi dikhte — inhe track karo:
#    • canvas._px           (original full PDF pixmap)
#    • canvas._cached_spx   (zoom-scaled copy)
#    • editor._combined_px  (CardEditorDialog combined pixmap)
#    • review._current_pixmap (ReviewWindow current pixmap)
#
#  Usage:
#    PIXMAP_REGISTRY.register("label", obj, "attr_name", pdf_path)
#    PIXMAP_REGISTRY.unregister("label")
# ═══════════════════════════════════════════════════════════════════════════════

class _PixmapRegistry:
    """
    Tracks arbitrary large QPixmap attributes on live objects.
    Each entry = (weak_obj_ref, attr_name, pdf_path)
    """
    def __init__(self):
        import weakref
        self._weakref = weakref
        self._entries = {}   # label → (weakref, attr_name, pdf_path)

    def register(self, label: str, obj, attr: str, pdf_path: str = ""):
        self._entries[label] = (self._weakref.ref(obj), attr, pdf_path)

    def unregister(self, label: str):
        self._entries.pop(label, None)

    def _px_bytes(self, px) -> int:
        if px is None or px.isNull():
            return 0
        return px.width() * px.height() * 4

    def bytes_for_pdf(self, pdf_path: str) -> int:
        total = 0
        dead = []
        for label, (wref, attr, path) in self._entries.items():
            obj = wref()
            if obj is None:
                dead.append(label)
                continue
            if path != pdf_path:
                continue
            px = getattr(obj, attr, None)
            total += self._px_bytes(px)
        for d in dead:
            self._entries.pop(d, None)
        return total

    def total_bytes(self) -> int:
        total = 0
        dead = []
        for label, (wref, attr, _) in self._entries.items():
            obj = wref()
            if obj is None:
                dead.append(label)
                continue
            px = getattr(obj, attr, None)
            total += self._px_bytes(px)
        for d in dead:
            self._entries.pop(d, None)
        return total

    def all_registered_pdfs(self) -> set:
        return {path for _, (_, _, path) in self._entries.items() if path}

    def breakdown(self, pdf_path: str) -> dict:
        """Returns {label: bytes} for a given pdf_path — for detailed display."""
        result = {}
        for label, (wref, attr, path) in self._entries.items():
            if path != pdf_path:
                continue
            obj = wref()
            if obj is None:
                continue
            px = getattr(obj, attr, None)
            b = self._px_bytes(px)
            if b > 0:
                result[label] = b
        return result


PIXMAP_REGISTRY = _PixmapRegistry()


# ═══════════════════════════════════════════════════════════════════════════════
#  CACHE MANAGER PANEL  (the actual GUI widget)
# ═══════════════════════════════════════════════════════════════════════════════

class CacheManagerPanel(QWidget):
    """
    Floating side panel.  Usage:
        panel = CacheManagerPanel(parent=main_window)
        panel.show()
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("💾 Cache Manager")
        self.setMinimumWidth(340)
        self.setMaximumWidth(420)
        self.setStyleSheet(_SS)

        self._build_ui()

        # Auto-refresh every 5 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(5000)

        self.refresh()

    # ── UI Construction ───────────────────────────────────────────────────────
    def _update_location_label(self):
        self._lbl_location.setText(f"📂 {COMBINED_CACHE._dir}")

    def _change_cache_location(self):
        from PyQt5.QtWidgets import QFileDialog
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Cache Folder", COMBINED_CACHE._dir
        )
        if not new_dir:
            return

        # Save to settings
        from PyQt5.QtCore import QSettings
        QSettings("AnkiOcclusion", "App").setValue("cache_dir", new_dir)

        # Move existing cache files to new location
        import shutil
        old_dir = COMBINED_CACHE._dir
        try:
            if os.path.exists(old_dir):
                for f in os.listdir(old_dir):
                    shutil.move(os.path.join(old_dir, f), new_dir)
        except Exception as e:
            print(f"[cache] move warning: {e}")

        # Update cache object
        COMBINED_CACHE._dir = new_dir
        COMBINED_CACHE._rebuild_index()
        self._update_location_label()
        self.refresh()
        
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("💾 Cache Manager")
        title.setObjectName("title")
        f = title.font(); f.setPointSize(13); title.setFont(f)
        hdr.addWidget(title)
        hdr.addStretch()

        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.setFixedWidth(90)
        btn_refresh.clicked.connect(self.refresh)
        hdr.addWidget(btn_refresh)
        root.addLayout(hdr)

        # Total usage label
        self._lbl_total = QLabel("Total: —")
        self._lbl_total.setObjectName("sub")
        root.addWidget(self._lbl_total)

        # Clear all
        btn_clear = QPushButton("🧹 Clear All Caches")
        btn_clear.setObjectName("clr")
        btn_clear.clicked.connect(self._clear_all)
        root.addWidget(btn_clear)
        # Cache location row
        loc_row = QHBoxLayout()
        self._lbl_location = QLabel("")
        self._lbl_location.setObjectName("sub")
        self._lbl_location.setWordWrap(True)
        loc_row.addWidget(self._lbl_location, stretch=1)

        btn_location = QPushButton("📁 Change")
        btn_location.setFixedWidth(90)
        btn_location.clicked.connect(self._change_cache_location)
        loc_row.addWidget(btn_location)
        root.addLayout(loc_row)

        self._update_location_label()

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{C_BORDER}; max-height:1px;")
        root.addWidget(sep)

        # Scroll area for per-PDF cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

        # Status bar
        self._lbl_status = QLabel("Auto-refresh: every 5s")
        self._lbl_status.setObjectName("sub")
        root.addWidget(self._lbl_status)

    # ── Refresh / Data ────────────────────────────────────────────────────────

    def refresh(self):
        # Collect all PDFs known to any cache
        known = set()
        known.update(COMBINED_CACHE.all_cached_pdfs())
        known.update(PAGE_CACHE.all_cached_pdfs())
        known.update(MASK_REGISTRY.all_registered_pdfs())
        known.update(PIXMAP_REGISTRY.all_registered_pdfs())

        # Clear old cards
        while self._list_layout.count() > 1:   # keep the trailing stretch
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_bytes = 0
        visible_count = 0
        for pdf_path in sorted(known):
            disk_b   = COMBINED_CACHE.disk_bytes_for_pdf(pdf_path)
            ram_b    = PAGE_CACHE.ram_bytes_for_pdf(pdf_path)
            mask_b   = MASK_REGISTRY.mask_bytes_for_pdf(pdf_path)
            hidden_b = PIXMAP_REGISTRY.bytes_for_pdf(pdf_path)
            hidden_detail = PIXMAP_REGISTRY.breakdown(pdf_path)
            total    = disk_b + ram_b + mask_b + hidden_b

            # Only show PDFs that are actually holding RAM right now.
            # disk_b is excluded from this check — disk cache persists
            # after Ctrl+C RAM clear, so a PDF with only disk_b > 0
            # is not consuming any active memory and should not appear.
            active_ram = ram_b + mask_b + hidden_b
            if active_ram == 0:
                continue

            total_bytes += total
            visible_count += 1
            card = self._make_card(pdf_path, disk_b, ram_b, mask_b,
                                   hidden_b, hidden_detail, total)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

        if not visible_count:
            empty = QLabel("No cached PDFs yet.")
            empty.setObjectName("sub")
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)

        self._lbl_total.setText(
            f"Total cache: {_fmt_bytes(total_bytes)}  "
            f"({visible_count} PDF{'s' if visible_count != 1 else ''} in RAM)"
        )
        self._lbl_status.setText(
            f"Last refresh: {time.strftime('%H:%M:%S')}  •  Auto: every 5s"
        )

    def _make_card(self, pdf_path, disk_b, ram_b, mask_b,
                   hidden_b, hidden_detail, total_b) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        vl = QVBoxLayout(card)
        vl.setContentsMargins(10, 8, 10, 8)
        vl.setSpacing(4)

        # File name
        name_lbl = QLabel(_short_name(pdf_path))
        name_lbl.setObjectName("title")
        name_lbl.setToolTip(pdf_path)
        vl.addWidget(name_lbl)

        # Size rows
        def _row(icon, label, value, dim=False):
            hl = QHBoxLayout()
            hl.setSpacing(6)
            ico = QLabel(icon); ico.setFixedWidth(18)
            lbl = QLabel(label); lbl.setObjectName("sub")
            val = QLabel(value)
            val.setObjectName("size" if not dim else "sub")
            val.setAlignment(Qt.AlignRight)
            hl.addWidget(ico)
            hl.addWidget(lbl, stretch=1)
            hl.addWidget(val)
            return hl

        
        vl.addLayout(_row("💿", "Disk  (rendered pages)", _fmt_bytes(disk_b)))
        vl.addLayout(_row("🧠", "RAM   (page pixmaps)",   _fmt_bytes(ram_b)))
        vl.addLayout(_row("🎭", "GPU   (mask layer)",     _fmt_bytes(mask_b)))

        # Hidden pixmaps — show each one individually
        _HIDDEN_LABEL_MAP = [
            ("canvas_px_",       "📄", "Canvas original px"),
            ("canvas_spx_",      "🔍", "Canvas scaled px (zoom copy)"),
            ("editor_combined_", "📑", "Editor combined px"),
            ("review_current_",  "▶",  "Review current px"),
        ]
        def _friendly(key):
            for prefix, icon, name in _HIDDEN_LABEL_MAP:
                if key.startswith(prefix):
                    return icon, name
            return "📦", key

        if hidden_b > 0:
            div2 = QFrame(); div2.setFrameShape(QFrame.HLine)
            div2.setStyleSheet(f"background:{C_BORDER}; max-height:1px;")
            vl.addWidget(div2)
            for lbl_key, b in hidden_detail.items():
                icon, friendly = _friendly(lbl_key)
                vl.addLayout(_row(icon, friendly, _fmt_bytes(b), dim=False))
        else:
            div2 = QFrame(); div2.setFrameShape(QFrame.HLine)
            div2.setStyleSheet(f"background:{C_BORDER}; max-height:1px;")
            vl.addWidget(div2)
            vl.addLayout(_row("📦", "Hidden RAM pixmaps", "0 B", dim=True))

        # Divider before total
        div = QFrame(); div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"background:{C_BORDER}; max-height:1px;")
        vl.addWidget(div)

        # Total + remove button
        hl_bot = QHBoxLayout()
        total_lbl = QLabel(f"Total: {_fmt_bytes(total_b)}")
        total_lbl.setObjectName("size")
        hl_bot.addWidget(total_lbl, stretch=1)

        btn = QPushButton("🗑 Remove")
        btn.setObjectName("del")
        btn.setFixedWidth(90)
        btn.clicked.connect(lambda _, p=pdf_path: self._remove_pdf(p))
        hl_bot.addWidget(btn)
        vl.addLayout(hl_bot)

        return card

    # ── Actions ───────────────────────────────────────────────────────────────

    def _remove_pdf(self, pdf_path: str):
        COMBINED_CACHE.invalidate(pdf_path)
        PAGE_CACHE.invalidate_pdf(pdf_path)
        MASK_REGISTRY.invalidate_masks_for_pdf(pdf_path)
        self.refresh()

    def _clear_all(self):
        COMBINED_CACHE.clear()
        PAGE_CACHE.clear_ram_only()
        # Invalidate all registered mask caches
        for pdf_path in list(MASK_REGISTRY.all_registered_pdfs()):
            MASK_REGISTRY.invalidate_masks_for_pdf(pdf_path)
        self.refresh()