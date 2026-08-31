import sys
import os
import subprocess
from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import QMimeData, QUrl
from PyQt5.QtGui import QDesktopServices

from storage_paths import resolve_asset_path

def open_current_pdf_in_reader(self):
    path = self._current_pdf_path_for_shortcuts()
    if not path:
        self.canvas._show_toast("No PDF loaded for this card")
        return
    idx = self._idx
    if idx >= len(self._items):
        idx = len(self._items) - 1
    if not (0 <= idx < len(self._items)):
        return

    scroll_pos = self._canvas_scroll.verticalScrollBar().value()
    current_page_zero = self.canvas.get_current_page(scroll_pos)
    current_page = current_page_zero + 1
    self._external_pdf_path_hint = path
    self._external_pdf_page_hint = current_page_zero

    try:
        if sys.platform == "win32":
            xchange_paths = [
                r"C:\Program Files\Tracker Software\PDF Editor\PDFXEdit.exe",
                r"C:\Program Files (x86)\Tracker Software\PDF Editor\PDFXEdit.exe",
                r"C:\Program Files\PDF-XChange\PDF-XChange Editor\PDFXEdit.exe",
                r"C:\Program Files (x86)\PDF-XChange\PDF-XChange Editor\PDFXEdit.exe",
            ]
            for exe in xchange_paths:
                if os.path.exists(exe):
                    subprocess.Popen([exe, "/A", f"page={current_page}", path])
                    self.canvas._show_toast(
                        f"📄 Opened p.{current_page} in PDF-XChange"
                    )
                    return

            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PDFXEdit.exe",
                )
                exe = winreg.QueryValue(key, None)
                winreg.CloseKey(key)
                if exe and os.path.exists(exe):
                    subprocess.Popen([exe, "/A", f"page={current_page}", path])
                    self.canvas._show_toast(
                        f"📄 Opened p.{current_page} in PDF-XChange"
                    )
                    return
            except Exception:
                pass

            os.startfile(path)
            self.canvas._show_toast(
                "📄 Opened PDF (page jump not supported by this reader)"
            )

        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
            self.canvas._show_toast(f"📄 Opened PDF p.{current_page}")
        else:
            subprocess.Popen(["xdg-open", path])
            self.canvas._show_toast(f"📄 Opened PDF p.{current_page}")

    except Exception as ex:
        QMessageBox.warning(
            self, "Could not open PDF", f"Could not open PDF:\n{ex}"
        )

def current_pdf_path_for_shortcuts(self):
    idx = self._idx
    if idx >= len(self._items):
        idx = len(self._items) - 1
    if not (0 <= idx < len(self._items)):
        return ""
    card, _, _ = self._items[idx]
    path = resolve_asset_path(card.get("pdf_path", ""))
    if not path or not os.path.exists(path):
        return ""
    return path

def copy_current_pdf_file_to_clipboard(self):
    path = self._current_pdf_path_for_shortcuts()
    if not path:
        self.canvas._show_toast("No PDF loaded for this card")
        return
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    QApplication.clipboard().setMimeData(mime)
    print(f"[DEBUG][review_pdf_shortcut] copied_file {path}")
    self.canvas._show_toast("Copied PDF file")

def reveal_current_pdf_in_folder(self):
    path = self._current_pdf_path_for_shortcuts()
    if not path:
        self.canvas._show_toast("No PDF loaded for this card")
        return
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        print(f"[DEBUG][review_pdf_shortcut] reveal_path {path}")
        self.canvas._show_toast("Opened PDF folder")
    except Exception as ex:
        QMessageBox.warning(
            self, "Could not open location", f"Could not open PDF location:\n{ex}"
        )
