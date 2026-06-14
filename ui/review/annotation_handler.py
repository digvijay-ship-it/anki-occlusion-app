import os
import copy
import time
from PyQt5.QtWidgets import QMessageBox, QShortcut
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import Qt

from storage_paths import resolve_asset_path
from ui.pdf_annotation_dialog import PdfAnnotationDialog
from pdf_engine import adapt_pdf_boxes_to_render_zoom, PDF_LEGACY_BOX_ZOOM, PAGE_CACHE

def open_annotation_beta(self):
    idx = self._idx
    if idx >= len(self._items):
        idx = len(self._items) - 1
    if not (0 <= idx < len(self._items)):
        return
    card, _box_idx, _ = self._items[idx]
    import ui.review_screen
    resolve_asset_path_func = getattr(ui.review_screen, "resolve_asset_path", resolve_asset_path)
    os_mod = getattr(ui.review_screen, "os", os)
    pdf_anno_dlg_cls = getattr(ui.review_screen, "PdfAnnotationDialog", PdfAnnotationDialog)

    path = resolve_asset_path_func(card.get("pdf_path", ""))
    if not path or not os_mod.path.exists(path):
        image_path = resolve_asset_path_func(card.get("image_path", ""))
        if image_path and os_mod.path.exists(image_path):
            try:
                import fitz
                from storage_paths import build_archive_asset_path
                import data_manager
                
                stem = os_mod.path.splitext(os_mod.path.basename(image_path))[0]
                pdf_abs_path, pdf_rel_path = build_archive_asset_path("pdfs", f"{stem}.pdf")
                
                doc = fitz.open()
                img_doc = fitz.open(image_path)
                pdf_bytes = img_doc.convert_to_pdf()
                img_doc.close()
                
                pdf_mem = fitz.open("pdf", pdf_bytes)
                doc.insert_pdf(pdf_mem)
                doc.save(pdf_abs_path)
                doc.close()
                
                card["pdf_path"] = pdf_rel_path
                data_manager.store.mark_dirty()
                data_manager.store.save_force()
                path = pdf_abs_path
            except Exception as e:
                print(f"[ERROR][annotation_handler] Failed to convert image to PDF: {e}")
                QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
                return
        else:
            QMessageBox.warning(self, "No PDF", "No PDF is currently loaded.")
            return
    page_zero = self.canvas.get_current_page(
        self._canvas_scroll.verticalScrollBar().value()
    )
    scroll_y = self._canvas_scroll.verticalScrollBar().value()
    review_scale = max(float(getattr(self.canvas, "_scale", 1.0) or 1.0), 0.01)
    img_y = float(scroll_y) / review_scale
    print(
        f"[DEBUG][review_annotation] handoff "
        f"page={page_zero + 1} scroll_y={scroll_y} scale={review_scale:.4f} img_y={img_y:.2f}"
    )
    active_dialog = self.__dict__.get("_active_annotation_dialog")
    if active_dialog is not None and active_dialog.isVisible():
        if hasattr(active_dialog, "retarget_from_review"):
            active_dialog.retarget_from_review(page_zero, img_y)
        if hasattr(active_dialog, "showFullScreen"):
            active_dialog.showFullScreen()
        active_dialog.raise_()
        active_dialog.activateWindow()
        return
    dialog = pdf_anno_dlg_cls(
        path,
        parent=None,
        initial_page=page_zero,
        initial_anchor_y=img_y,
    )
    self._active_annotation_dialog = dialog
    dialog.finished.connect(
        lambda result, d=dialog, p=path: self._finish_annotation_beta(
            d, p, result
        )
    )
    self._pause_review_lazy_activity_for_annotation()
    self._prepare_annotation_window(dialog)
    dialog.showFullScreen()
    dialog.raise_()
    dialog.activateWindow()

def annotation_window_flags(self):
    return Qt.Window | Qt.FramelessWindowHint

def prepare_annotation_window(self, dialog):
    dialog.setParent(None, Qt.Window)
    dialog.setWindowFlags(self._annotation_window_flags())
    dialog.setWindowModality(Qt.NonModal)
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        dialog.setWindowIcon(self.window().windowIcon())
    except Exception:
        pass
    self._install_annotation_switch_shortcuts(dialog)

def install_annotation_switch_shortcuts(self, dialog):
    try:
        review_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        review_shortcut.setContext(Qt.WindowShortcut)
        review_shortcut.activated.connect(self._focus_active_annotation_window)
        self._annotation_focus_shortcut = review_shortcut

        dialog_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), dialog)
        dialog_shortcut.setContext(Qt.WindowShortcut)
        dialog_shortcut.activated.connect(self._focus_review_window)
        dialog._review_focus_shortcut = dialog_shortcut
    except Exception:
        pass

def focus_active_annotation_window(self):
    dialog = self.__dict__.get("_active_annotation_dialog")
    if dialog is None or not dialog.isVisible():
        return
    if dialog.isMinimized():
        dialog.showNormal()
    dialog.raise_()
    dialog.activateWindow()

def focus_review_window(self):
    win = self.window()
    if win.isMinimized():
        win.showNormal()
    win.raise_()
    win.activateWindow()

def finish_annotation_beta(self, dialog, path: str, result):
    if self.__dict__.get("_active_annotation_dialog") is dialog:
        self._active_annotation_dialog = None
        self._annotation_focus_shortcut = None
    self._resume_review_lazy_activity_after_annotation(path)
    self._apply_annotation_beta_refresh(
        path,
        getattr(dialog, "_saved_pages", []),
        getattr(dialog, "return_page", None),
    )

def pause_review_lazy_activity_for_annotation(self):
    self._review_lazy_trace_suspended = True
    reveal_bar = getattr(self, "_reveal_bar", None)
    rating_frame = getattr(self, "_rating_frame", None)
    self._annotation_prev_reveal_visible = bool(
        reveal_bar is not None and reveal_bar.isVisible()
    )
    self._annotation_prev_rating_visible = bool(
        rating_frame is not None and rating_frame.isVisible()
    )
    if reveal_bar is not None:
        reveal_bar.hide()
    if rating_frame is not None:
        rating_frame.hide()
    timer = getattr(self, "_ui_idle_timer", None)
    if timer is not None:
        timer.stop()
    self._background_fill_state = None
    self._bg_pending_inserts.clear()
    self._pending_visible_request = False
    self._stop_ondemand_thread()
    watcher = self.__dict__.get("_pdf_watcher")
    if watcher is not None:
        watcher.stop_watch()

def resume_review_lazy_activity_after_annotation(self, path: str | None = None):
    self._review_lazy_trace_suspended = False
    reveal_bar = getattr(self, "_reveal_bar", None)
    rating_frame = getattr(self, "_rating_frame", None)
    if bool(self.__dict__.pop("_annotation_prev_rating_visible", False)):
        if rating_frame is not None:
            self._show_overlay(rating_frame)
    elif bool(self.__dict__.pop("_annotation_prev_reveal_visible", False)):
        if reveal_bar is not None:
            self._show_overlay(reveal_bar)
    if path:
        watcher = self.__dict__.get("_pdf_watcher")
        if watcher is not None:
            watcher.watch_pdf(path)

def clear_review_loading_caches(self):
    self.__dict__.setdefault("_review_priority_pages_cache", {}).clear()
    self.__dict__.setdefault("_review_adapted_boxes_cache", {}).clear()

def review_box_signature(self, boxes):
    sig = []
    for box in boxes or []:
        rect = box.get("rect", ())
        if isinstance(rect, (list, tuple)):
            rect_sig = tuple(rect[:4])
        else:
            rect_sig = repr(rect)
        sig.append(
            (
                box.get("box_id", ""),
                box.get("group_id", ""),
                rect_sig,
                box.get("shape", "rect"),
                box.get("angle", 0.0),
                box.get("page_num"),
            )
        )
    return tuple(sig)

def adapt_review_boxes(self, card, path):
    boxes = card.get("boxes", []) or []
    if not path or not boxes:
        return boxes

    adapt_t0 = time.perf_counter()
    source_zoom = card.get("_pdf_box_render_zoom")
    if source_zoom is None:
        source_zoom = PDF_LEGACY_BOX_ZOOM
    try:
        source_zoom_key = float(source_zoom)
    except (TypeError, ValueError):
        source_zoom_key = float(PDF_LEGACY_BOX_ZOOM)
    try:
        target_zoom_key = float(self._pdf_render_zoom)
    except (TypeError, ValueError):
        target_zoom_key = 0.0
    cache = self.__dict__.setdefault("_review_adapted_boxes_cache", {})
    key = (
        id(card),
        os.path.abspath(path),
        source_zoom_key,
        target_zoom_key,
        self._review_box_signature(boxes),
    )
    cached = cache.get(key)
    if cached is None:
        import ui.review_screen
        adapt_func = getattr(ui.review_screen, "adapt_pdf_boxes_to_render_zoom", adapt_pdf_boxes_to_render_zoom)
        cached = adapt_func(
            path,
            boxes,
            source_zoom,
            self._pdf_render_zoom,
        )
        cache[key] = cached
        while len(cache) > 32:
            cache.pop(next(iter(cache)))
        self._review_profile_count("adapt_boxes_miss")
        self._review_profile_log(
            "adapt_boxes",
            result="miss",
            boxes=len(boxes),
            elapsed=f"{(time.perf_counter() - adapt_t0) * 1000:.1f}ms",
        )
    else:
        self._review_profile_count("adapt_boxes_hit")
        self._review_profile_log(
            "adapt_boxes",
            result="hit",
            boxes=len(boxes),
            elapsed=f"{(time.perf_counter() - adapt_t0) * 1000:.1f}ms",
        )
    return copy.deepcopy(cached)

def start_review_lazy_trace(self, page_nums, ttl_seconds: float = 8.0):
    pages = {int(page_num) for page_num in (page_nums or [])}
    if not pages:
        self._review_lazy_trace_pages = set()
        self._review_lazy_trace_seen_pages = set()
        self._review_lazy_trace_until = 0.0
        return
    self._review_lazy_trace_pages = pages
    self._review_lazy_trace_seen_pages = set()
    self._review_lazy_trace_until = time.monotonic() + max(0.5, float(ttl_seconds))

def apply_annotation_beta_refresh(
    self, path: str, changed_pages, return_page: int | None
):
    if not changed_pages:
        self._trigger_center_fit()
        return
    refreshed_pages = sorted(set(int(pn) for pn in changed_pages))
    
    # Invalidate cached pages for the high-res review zoom variant
    PAGE_CACHE.invalidate_pages(path, refreshed_pages, variant=self._pdf_render_zoom)
    
    # Discard these pages from self._review_canvas_real_pages so that they are re-rendered
    for page_num in refreshed_pages:
        self.__dict__.setdefault("_review_canvas_real_pages", set()).discard(page_num)

    self._start_review_lazy_trace(refreshed_pages)
    key = os.path.abspath(path)
    if "_suppress_pdf_reload_until" not in self.__dict__:
        self._suppress_pdf_reload_until = {}
    self._suppress_pdf_reload_until[key] = time.monotonic() + 2.5
    self._pdf_watcher.ignore_next_change(path, count=3)
    print(
        "[DEBUG][review_after_edit] "
        + ", ".join(f"p.{page_num + 1}" for page_num in refreshed_pages)
    )
    for page_num in refreshed_pages:
        px = PAGE_CACHE.get(path, page_num)
        if px is not None and not px.isNull():
            self._debug_review_lazy_page_loaded(
                source="render", page_num=page_num, pixmap=px
            )
            self.canvas.inject_page(page_num, px)
            
    # Explicitly trigger visible pages changed to load the high-res annotated version
    self._canvas_scroll._emit_visible_pages()
    
    self._update_review_page_nav_ui()
    self._trigger_center_fit()
