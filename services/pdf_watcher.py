import os
from PyQt5.QtCore import QObject, pyqtSignal, QFileSystemWatcher, QTimer
from pdf_engine import PAGE_CACHE, invalidate_pdf_skeleton

class PdfWatcher(QObject):
    file_changed = pyqtSignal(str)
    reload_requested = pyqtSignal(str, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watched_pdf_path = None
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self._reload_modified_pdf)
        self._watcher.fileChanged.connect(self._on_pdf_file_changed)
        self.get_current_page_cb = None
        self.get_hint_cb = None

    def watch_pdf(self, path: str):
        self.stop_watch()
        self._watched_pdf_path = path
        if path and os.path.exists(path):
            self._watcher.addPath(path)

    def stop_watch(self):
        if self._watched_pdf_path:
            try:
                self._watcher.removePath(self._watched_pdf_path)
            except Exception:
                pass
            self._watched_pdf_path = None
        self._reload_timer.stop()

    def _on_pdf_file_changed(self, path: str):
        if not path: return
        self.file_changed.emit(path)
        self._reload_timer.start()

    def _reload_modified_pdf(self):
        path = self._watched_pdf_path
        if not path: return
        if not os.path.exists(path):
            QTimer.singleShot(500, self._reload_modified_pdf)
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)

        current_page = None
        target_page = None
        if self.get_current_page_cb:
            current_page = self.get_current_page_cb()
            target_page = current_page
            
        if self.get_hint_cb:
            hint_path, hint_page = self.get_hint_cb()
            if hint_path == path and hint_page is not None:
                target_page = hint_page

        from pdf_engine import get_changed_pages
        changed = get_changed_pages(path)
        if changed is None:
            PAGE_CACHE.invalidate_pdf(path)
            invalidate_pdf_skeleton(path)
        else:
            PAGE_CACHE.invalidate_pages(path, changed)
            invalidate_pdf_skeleton(path)
            
        self.reload_requested.emit(path, current_page, target_page)
