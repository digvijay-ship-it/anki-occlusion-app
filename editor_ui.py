"""
editor_ui.py  —  v22  (Snappy Performance Edition)
================================================

v22 Performance Fixes (6 independent bottlenecks eliminated):
  [FIX-1] paintEvent: Single-image (_px) was re-scaled from scratch on EVERY
      paintEvent — scroll, drag, ink, everything. Now cached in _spx_cache
      same as PDF pages. Eliminates the #1 scroll lag source for image cards.

  [FIX-2] paintEvent direct-draw fallback (large PDFs): Was redrawing ALL
      masks on every scroll event regardless of clip rect. Now checks
      clip.intersects(sr) and skips off-screen boxes entirely.

  [FIX-3] Ink _ink_move: Was calling full-canvas update() on every mouse move.
      Now computes a tight bounding rect of just the last segment (typically
      <50×50px) and calls update(rect). 10–50x fewer pixels repainted per event.

  [FIX-4] _draw_ink_layer: Was calling drawLine() in a Python loop for every
      segment — N separate GPU round-trips per stroke. Now uses drawPolyline()
      for a single GPU call per stroke regardless of point count.

  [FIX-5] Mask drawing (_drawing mode): Was calling full-canvas update() on
      every mouseMoveEvent. Now only repaints the union of old+new live_rect.

  [FIX-6] Mask move drag: Was full-canvas update() on every pixel of drag.
      Now repaints only the union of old+new box screen rect + handle padding.

  [FIX-7] Mask rotate drag: Same as FIX-6 — partial rect update only.

v21 Bug Fix / Cleanup:
  PROBLEM: Masks were not loading after a certain page number due to giant QPixmap allocation limits.
  FIX:
    • The legacy mask-cache layer has been removed entirely.
    • Masks are now drawn directly in paintEvent per box, clipped to the viewport.
    • No offscreen QPixmap is allocated for masks, eliminating texture size limits and reducing memory usage.

v20 (Virtual Page Renderer):
  v17 introduced _build_combined_from_pages() which creates ONE giant QPixmap
  from all PDF pages stacked vertically. Qt silently truncates any QPixmap
  whose height exceeds 32 767 px (GPU texture limit). A 42-page A4 PDF at
  1.5x zoom = ~50 000 px tall → bottom ~12 pages were invisible black.

HOW IT'S FIXED — Virtual Page Renderer:
  OcclusionCanvas now stores  self._pages : list[QPixmap]  — one per PDF page.
  paintEvent draws ONLY the pages whose screen rect intersects the clip region.
  The widget is resized to the full virtual height (sum of all page heights +
  gaps), so the QScrollArea scrollbar is always correct — giving the same
  smooth continuous-scroll feeling as before.
  No single pixmap is ever larger than one page (~1 200 px) — Qt limit bypassed.

BACKWARD COMPATIBILITY:
  • load_pixmap(px)  — single-image mode, unchanged
  • load_pages(pages) — new; replaces load_pixmap(combined_px)
  • append_pages(pages) — progressive loading chunks
  • All box / mask / zoom / ink / undo APIs identical
  • CardEditorDialog, MaskPanel, ToolBar, _ZoomableScrollArea — unchanged
  • anki_occlusion_v19.py requires two small edits (see bottom of this file)
"""

import sys
from datetime import datetime
import math
import os
import time
import fitz
import copy
import uuid

from PyQt5.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QListWidget,
    QFrame,
    QScrollArea,
    QAbstractScrollArea,
    QMessageBox,
    QFileDialog,
    QFormLayout,
    QTextEdit,
    QSizePolicy,
    QDialog,
    QApplication,
    QMenu,
)
from PyQt5.QtCore import (
    Qt,
    QPointF,
    QRectF,
    QTimer,
    pyqtSignal,
    QSize,
    QEvent,
    QUrl,
    QFileSystemWatcher,
)
from PyQt5.QtGui import (
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QFont,
    QCursor,
    QBrush,
    QDesktopServices,
    QImage,
)

from sm2_engine import sm2_init
from pdf_engine import (
    PDF_SUPPORT,
    PdfLoaderThread,
    pdf_page_to_pixmap,
)
from cache_manager import PAGE_CACHE, PIXMAP_REGISTRY
from data_manager import new_box_id

C_GREEN = "#50FA7B"
C_MASK = "#F7916A"
C_ACCENT = "#7C6AF7"
C_YELLOW = "#F1FA8C"
PAGE_GAP = 12  # vertical gap between pages in image-space pixels
EDITOR_PDF_ZOOM = 1.5

_QT_MAX_PX = 32_767  # Qt GPU texture hard limit — QPixmap silently fails above this


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _point_in_rotated_box(px, py, cx, cy, w, h, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    return abs(lx) <= w / 2 and abs(ly) <= h / 2


def _point_in_rotated_ellipse(px, py, cx, cy, rx, ry, angle_deg):
    rad = math.radians(-angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    lx = dx * cos_a - dy * sin_a
    ly = dx * sin_a + dy * cos_a
    if rx < 1 or ry < 1:
        return False
    return (lx / rx) ** 2 + (ly / ry) ** 2 <= 1.0


from ui.canvas.core import OcclusionCanvas

# ═══════════════════════════════════════════════════════════════════════════════
#  TOOL BAR
# ═══════════════════════════════════════════════════════════════════════════════


class ToolBar(QWidget):
    tool_changed = pyqtSignal(str)
    _TOOLS = [
        ("select", "⬡", "Select / Move / Resize / Rotate  [V]"),
        ("rect", "□", "Rectangle mask  [R]"),
        ("ellipse", "○", "Ellipse mask  [E]"),
        ("text", "T", "Edit label  [T]"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(50)
        self.setStyleSheet(
            "QWidget{background:#F0F0F0;border-right:1px solid #C8C8C8;}"
        )
        L = QVBoxLayout(self)
        L.setContentsMargins(5, 8, 5, 8)
        L.setSpacing(3)
        self._btns = {}
        for tool, icon, tip in self._TOOLS:
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedSize(40, 40)
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#333;border:none;"
                "border-radius:5px;font-size:20px;font-weight:bold;}"
                "QPushButton:checked{background:#4A90D9;color:white;}"
                "QPushButton:hover:!checked{background:#E0E0E0;}"
            )
            b.clicked.connect(lambda _, t=tool: self._select(t))
            L.addWidget(b)
            self._btns[tool] = b
        L.addStretch()
        self._select("rect")

    def _select(self, tool):
        for t, b in self._btns.items():
            b.setChecked(t == tool)
        self.tool_changed.emit(tool)

    def select_tool(self, tool):
        self._select(tool)


# ═══════════════════════════════════════════════════════════════════════════════
#  RICH TEXT EDIT (supports image pasting & drag-and-drop)
# ═══════════════════════════════════════════════════════════════════════════════

def get_base_url():
    from storage_paths import get_mission_archive_root, current_data_file
    root = get_mission_archive_root()
    if not root:
        root = os.path.dirname(current_data_file())
    if root:
        return QUrl.fromLocalFile(os.path.abspath(root) + "/")
    return QUrl()


class RichTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.document().setBaseUrl(get_base_url())
        self.document().setDefaultStyleSheet("img { max-width: 100%; }")
        self.setCursorWidth(2)

    def keyPressEvent(self, event):
        from PyQt5.QtGui import QKeySequence
        if event.matches(QKeySequence.Copy):
            self.copy()
            event.accept()
            return
        if event.matches(QKeySequence.Cut):
            self.cut()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy(self):
        cursor = self.textCursor()
        if self._try_copy_image(cursor):
            return
        super().copy()

    def cut(self):
        cursor = self.textCursor()
        if self._try_copy_image(cursor):
            cursor.removeSelectedText()
            return
        super().cut()

    def _try_copy_image(self, cursor):
        char_format = cursor.charFormat()
        # 2. Try character format after cursor (if not at end of document)
        try:
            pos = cursor.position()
            char_count = self.document().characterCount()
            is_before_end = int(pos) < int(char_count)
        except (TypeError, ValueError):
            is_before_end = False
        if not char_format.isImageFormat() and is_before_end:
            temp = self.textCursor()
            temp.setPosition(int(pos) + 1)
            char_format = temp.charFormat()
            
        # 3. If there is a selection, check within the selection range
        if not char_format.isImageFormat() and cursor.hasSelection():
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            temp = self.textCursor()
            for pos in range(start_pos + 1, end_pos + 1):
                temp.setPosition(pos)
                fmt = temp.charFormat()
                if fmt.isImageFormat():
                    char_format = fmt
                    break
            
        if char_format.isImageFormat():
            image_format = char_format.toImageFormat()
            image_name = image_format.name()
            
            from storage_paths import resolve_asset_path
            abs_path = resolve_asset_path(image_name)
            import os
            if abs_path and os.path.exists(abs_path):
                pixmap = QPixmap(abs_path)
                if not pixmap.isNull():
                    from PyQt5.QtCore import QMimeData, QByteArray, QBuffer, QIODevice
                    mime_data = QMimeData()
                    
                    data = QByteArray()
                    buffer = QBuffer(data)
                    buffer.open(QIODevice.WriteOnly)
                    pixmap.toImage().save(buffer, "PNG")
                    png_bytes = bytes(data)
                    
                    mime_data.setData("image/png", QByteArray(png_bytes))
                    mime_data.setImageData(pixmap.toImage())
                    
                    clipboard = QApplication.clipboard()
                    clipboard.setMimeData(mime_data)
                    return True
        return False

    def contextMenuEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        char_format = cursor.charFormat()
        
        is_img = False
        pos = cursor.position()
        doc = self.document()
        select_start = pos
        
        char_at = doc.characterAt(pos)
        char_prev = doc.characterAt(pos - 1) if pos > 0 else ""
        
        if char_at == '\ufffc':
            is_img = True
            select_start = pos
        elif char_prev == '\ufffc':
            is_img = True
            select_start = pos - 1
            
        if is_img:
            img_cursor = self.cursorForPosition(event.pos())
            img_cursor.setPosition(select_start)
            img_cursor.setPosition(select_start + 1, img_cursor.KeepAnchor)
            self.setTextCursor(img_cursor)
            cursor = img_cursor
            char_format = cursor.charFormat()
            
        menu = self.createStandardContextMenu()
        
        from PyQt5.QtGui import QKeySequence
        copy_action = None
        cut_action = None
        for action in menu.actions():
            text = action.text().replace("&", "")
            if text == "Copy" or (action.shortcut() and action.shortcut().matches(QKeySequence.Copy)):
                copy_action = action
            elif text == "Cut" or (action.shortcut() and action.shortcut().matches(QKeySequence.Cut)):
                cut_action = action
                
        if copy_action:
            custom_copy = menu.addAction("Copy")
            custom_copy.setShortcut(QKeySequence.Copy)
            custom_copy.triggered.connect(self.copy)
            menu.insertAction(copy_action, custom_copy)
            menu.removeAction(copy_action)
            
        if cut_action:
            custom_cut = menu.addAction("Cut")
            custom_cut.setShortcut(QKeySequence.Cut)
            custom_cut.triggered.connect(self.cut)
            menu.insertAction(cut_action, custom_cut)
            menu.removeAction(cut_action)
            
        if char_format.isImageFormat():
            image_format = char_format.toImageFormat()
            image_name = image_format.name()
            
            menu.addSeparator()
            crop_action = menu.addAction("✂ Crop Image")
            edit_sketch_action = menu.addAction("🎨 Edit Sketch")
            
            action = menu.exec_(event.globalPos())
            if action == crop_action:
                self._crop_inline_image(image_name, char_format, cursor)
            elif action == edit_sketch_action:
                self._edit_inline_sketch(image_name, char_format, cursor)
        else:
            menu.exec_(event.globalPos())

    def _crop_inline_image(self, image_name, char_format, cursor):
        from storage_paths import resolve_asset_path
        abs_path = resolve_asset_path(image_name)
        if not abs_path or not os.path.exists(abs_path):
            QMessageBox.warning(self, "Error", "Could not locate image path.")
            return
            
        pixmap = QPixmap(abs_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
            
        from ui.crop_dialog import CropImageDialog
        dialog = CropImageDialog(pixmap, self.window())
        if dialog.exec_() == QDialog.Accepted:
            cropped_pixmap = dialog.get_cropped_pixmap()
            if not cropped_pixmap.isNull():
                if cropped_pixmap.save(abs_path, "PNG"):
                    self.document().addResource(
                        self.document().ImageResource,
                        QUrl(image_name),
                        cropped_pixmap
                    )
                    html = self.toHtml()
                    self.setHtml(html)
                    
                    parent_win = self.window()
                    if hasattr(parent_win, "_write_recovery_checkpoint"):
                        parent_win._write_recovery_checkpoint("image_cropped")
                else:
                    QMessageBox.warning(self, "Error", "Could not save cropped image.")

    def _edit_inline_sketch(self, image_name, char_format, cursor):
        from storage_paths import resolve_asset_path
        abs_path = resolve_asset_path(image_name)
        if not abs_path or not os.path.exists(abs_path):
            QMessageBox.warning(self, "Error", "Could not locate image path.")
            return
            
        pixmap = QPixmap(abs_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Could not load image.")
            return
            
        from ui.quick_note_dialog import EditSketchDialog
        dialog = EditSketchDialog(pixmap, self.window())
        if dialog.exec_() == QDialog.Accepted:
            edited_pixmap = dialog.get_edited_pixmap()
            if not edited_pixmap.isNull():
                if edited_pixmap.save(abs_path, "PNG"):
                    self.document().addResource(
                        self.document().ImageResource,
                        QUrl(image_name),
                        edited_pixmap
                    )
                    html = self.toHtml()
                    self.setHtml(html)
                    
                    parent_win = self.window()
                    if hasattr(parent_win, "_write_recovery_checkpoint"):
                        parent_win._write_recovery_checkpoint("image_edited")
                else:
                    QMessageBox.warning(self, "Error", "Could not save edited sketch.")

    def insertFromMimeData(self, mimeData):
        from PyQt5.QtGui import QImage
        image = QImage()
        if mimeData.hasImage():
            val = mimeData.imageData()
            if val is not None:
                image = val.value() if hasattr(val, "value") else val
            if not isinstance(image, QImage) or image.isNull():
                image = QApplication.clipboard().image()

        if not image.isNull():
            self.insert_qimage(image)
            return
        if mimeData.hasUrls():
            for url in mimeData.urls():
                file_path = url.toLocalFile()
                if file_path and os.path.exists(file_path):
                    ext = os.path.splitext(file_path.lower())[1]
                    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                        self.insert_image_file(file_path)
            return
        super().insertFromMimeData(mimeData)

    def crop_image_borders(self, img_path):
        try:
            from PIL import Image
            if not os.path.exists(img_path):
                return
            img = Image.open(img_path)
            w, h = img.size
            if w <= 10 or h <= 10:
                return
            pixels = img.load()
            
            # Check background color based on corners
            def is_bg(pixel):
                if len(pixel) == 4:
                    r, g, b, a = pixel
                    if a < 15: # transparent
                        return True
                else:
                    r, g, b = pixel[:3]
                return r < 35 and g < 35 and b < 35

            def row_is_bg(y):
                non_bg = sum(not is_bg(pixels[x, y]) for x in range(w))
                return non_bg == 0

            def col_is_bg(x, y_start, y_end):
                non_bg = sum(not is_bg(pixels[x, y]) for y in range(y_start, y_end + 1))
                return non_bg == 0

            top = 0
            while top < h:
                if not row_is_bg(top):
                    break
                top += 1
                
            bottom = h - 1
            while bottom >= top:
                if not row_is_bg(bottom):
                    break
                bottom -= 1
                
            left = 0
            while left < w:
                if not col_is_bg(left, top, bottom):
                    break
                left += 1
                
            right = w - 1
            while right >= left:
                if not col_is_bg(right, top, bottom):
                    break
                right -= 1
                
            if left > right or top > bottom:
                return # entirely background
                
            # Add 10px padding gap around content
            pad = 10
            left_padded = max(0, left - pad)
            top_padded = max(0, top - pad)
            right_padded = min(w - 1, right + pad)
            bottom_padded = min(h - 1, bottom + pad)

            # If nothing is cropped, skip saving to avoid write churn
            if left_padded == 0 and right_padded == w - 1 and top_padded == 0 and bottom_padded == h - 1:
                return
                
            cropped_img = img.crop((left_padded, top_padded, right_padded + 1, bottom_padded + 1))
            cropped_img.save(img_path, "PNG")
        except Exception as e:
            print(f"Error auto-cropping image {img_path}: {e}")

    def insert_qimage(self, qimage):
        import uuid
        from storage_paths import has_mission_archive, build_archive_asset_path
        filename = f"paste_{uuid.uuid4().hex[:8]}.png"
        
        if has_mission_archive():
            abs_path, rel_path = build_archive_asset_path("images", filename)
        else:
            import tempfile
            temp_dir = tempfile.gettempdir()
            abs_path = os.path.normpath(os.path.join(temp_dir, filename))
            rel_path = abs_path
            
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        
        from PyQt5.QtGui import QImage
        if isinstance(qimage, QImage):
            qimage.save(abs_path, "PNG")
        else:
            img = qimage.value() if hasattr(qimage, "value") else qimage
            if hasattr(img, "save"):
                img.save(abs_path, "PNG")
            else:
                return
                
        self.crop_image_borders(abs_path)
        self.insert_image_html(rel_path)

    def insert_image_file(self, file_path):
        from storage_paths import has_mission_archive, import_asset_into_archive, resolve_asset_path
        try:
            if has_mission_archive():
                rel_path = import_asset_into_archive(file_path, "images")
                abs_path = resolve_asset_path(rel_path)
            else:
                rel_path = file_path
                abs_path = file_path
            self.crop_image_borders(abs_path)
            self.insert_image_html(rel_path)
        except Exception as e:
            print(f"Error importing image: {e}")

    def insert_image_html(self, rel_path):
        url_path = rel_path.replace("\\", "/")
        cursor = self.textCursor()
        cursor.insertHtml(f'<br><img src="{url_path}"/><br>&nbsp;')
        from PyQt5.QtGui import QTextCharFormat
        cursor.setCharFormat(QTextCharFormat())
        self.setTextCursor(cursor)


# ═══════════════════════════════════════════════════════════════════════════════
#  MASK PANEL
# ═══════════════════════════════════════════════════════════════════════════════


class MaskPanel(QWidget):
    def __init__(self, canvas: OcclusionCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._canvas.boxes_changed.connect(self._refresh)
        self._setup_ui()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(6, 6, 6, 6)
        L.setSpacing(4)
        self.list_w = QListWidget()
        self.list_w.currentRowChanged.connect(self._on_select)
        L.addWidget(self.list_w, stretch=1)
        
        lbl_e = QLabel("Label:")
        lbl_e.setStyleSheet("color:#555;font-size:11px;background:transparent;")
        L.addWidget(lbl_e)
        self.inp_label = QLineEdit()
        self.inp_label.setPlaceholderText("e.g. Mitochondria")
        self.inp_label.textChanged.connect(self._on_label_change)
        L.addWidget(self.inp_label)
        
        lbl_n = QLabel("Mask Note / Hint:")
        lbl_n.setStyleSheet("color:#555;font-size:11px;background:transparent;margin-top:4px;")
        L.addWidget(lbl_n)
        self.inp_note = RichTextEdit()
        self.inp_note.setPlaceholderText("Paste solution, hint text, or images...")
        self.inp_note.setMaximumHeight(80)
        self.inp_note.textChanged.connect(self._on_note_change)
        L.addWidget(self.inp_note)
        
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        b_del = QPushButton("🗑 Delete")
        b_del.setObjectName("danger")
        b_del.setFixedHeight(26)
        b_del.clicked.connect(self._delete_selected)
        b_clr = QPushButton("✕ Clear All")
        b_clr.setFixedHeight(26)
        b_clr.clicked.connect(self._canvas.clear_all)
        btn_row.addWidget(b_del)
        btn_row.addWidget(b_clr)
        L.addLayout(btn_row)

    def _refresh(self, boxes):
        self.list_w.blockSignals(True)
        self.list_w.clear()
        for i, b in enumerate(boxes):
            lbl = b.get("label") or f"Mask #{i+1}"
            gid = b.get("group_id", "")
            icon = "🔵" if gid else "🟧"
            badge = f" [{gid[:4]}]" if gid else ""
            self.list_w.addItem(f"  {icon} {lbl}{badge}")
        sel = self._canvas._selected_idx
        if 0 <= sel < self.list_w.count():
            self.list_w.setCurrentRow(sel)
            box = self._canvas._boxes[sel]
            
            new_label = box.get("label", "")
            if self.inp_label.text() != new_label:
                self.inp_label.blockSignals(True)
                self.inp_label.setText(new_label)
                self.inp_label.blockSignals(False)
            
            new_note = box.get("note", "")
            if self.inp_note.toPlainText() != new_note and self.inp_note.toHtml() != new_note:
                self.inp_note.blockSignals(True)
                if "<img" in new_note or "<html>" in new_note or "<p>" in new_note:
                    self.inp_note.setHtml(new_note)
                else:
                    self.inp_note.setPlainText(new_note)
                self.inp_note.blockSignals(False)
            
            self.inp_label.setEnabled(True)
            self.inp_note.setEnabled(True)
        else:
            self.inp_label.blockSignals(True)
            self.inp_label.clear()
            self.inp_label.blockSignals(False)
            
            self.inp_note.blockSignals(True)
            self.inp_note.clear()
            self.inp_note.blockSignals(False)
            
            self.inp_label.setEnabled(False)
            self.inp_note.setEnabled(False)
        self.list_w.blockSignals(False)

    def _on_select(self, row):
        self._canvas.highlight(row)
        if 0 <= row < len(self._canvas._boxes):
            box = self._canvas._boxes[row]
            
            new_label = box.get("label", "")
            if self.inp_label.text() != new_label:
                self.inp_label.blockSignals(True)
                self.inp_label.setText(new_label)
                self.inp_label.blockSignals(False)
            
            new_note = box.get("note", "")
            if self.inp_note.toPlainText() != new_note and self.inp_note.toHtml() != new_note:
                self.inp_note.blockSignals(True)
                if "<img" in new_note or "<html>" in new_note or "<p>" in new_note:
                    self.inp_note.setHtml(new_note)
                else:
                    self.inp_note.setPlainText(new_note)
                self.inp_note.blockSignals(False)
            
            self.inp_label.setEnabled(True)
            self.inp_note.setEnabled(True)
        else:
            self.inp_label.blockSignals(True)
            self.inp_label.clear()
            self.inp_label.blockSignals(False)
            
            self.inp_note.blockSignals(True)
            self.inp_note.clear()
            self.inp_note.blockSignals(False)
            
            self.inp_label.setEnabled(False)
            self.inp_note.setEnabled(False)

    def _on_label_change(self, text):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.update_label(row, text)
            self.list_w.currentItem().setText(f"  🟧 {text or f'Mask #{row+1}'}")

    def _on_note_change(self):
        row = self.list_w.currentRow()
        if row >= 0:
            if "<img" in self.inp_note.toHtml():
                text = self.inp_note.toHtml()
            else:
                text = self.inp_note.toPlainText()
            self._canvas.update_note(row, text)

    def _delete_selected(self):
        row = self.list_w.currentRow()
        if row >= 0:
            self._canvas.delete_box(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  ZOOMABLE SCROLL AREA  (unchanged from v19)
# ═══════════════════════════════════════════════════════════════════════════════


class _ZoomableScrollArea(QScrollArea):
    # ── NEW: emitted when vertical scroll position changes ────────────────────
    # Carries (first_visible_page, last_visible_page) — 0-based indices
    visible_pages_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = None
        self._pan_active = False
        self._pan_start_pos = None
        self._pan_hval = 0
        self._pan_vval = 0
        self._pan_mode = False
        self._space_held = False
        self._drag_threshold = 10
        self._is_actually_panning = False
        self._last_scroll_value = None
        self._last_scroll_ts = None
        self._last_visible_emit_ts = None
        self._last_scroll_range = None
        self._last_viewport_size = None
        self._scroll_direction = 0
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().installEventFilter(self)

        # Snappy single-step for keyboard arrows / scrollbar arrow buttons
        self.verticalScrollBar().setSingleStep(40)
        self.horizontalScrollBar().setSingleStep(40)

        # ── Scroll debounce timer — avoids firing on every pixel of scroll ───
        self._scroll_debounce = QTimer(self)
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.setInterval(150)  # backup emit after motion settles
        self._scroll_debounce.timeout.connect(self._emit_visible_pages)

        # Connect scrollbar AFTER it exists (post __init__)
        # Done lazily in set_canvas() instead

    def set_canvas(self, canvas):
        self._canvas = canvas
        canvas.installEventFilter(self)
        # Hook scrollbar valueChanged → debounce → visible_pages_changed
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)

    @property
    def pan_mode(self):
        return self._pan_mode

    def _on_scroll(self, value):
        """Raw scroll event — debounce so we don't fire 60× per swipe."""
        vbar = self.verticalScrollBar()
        now = time.perf_counter()
        prev_value = self._last_scroll_value
        prev_ts = self._last_scroll_ts
        delta = 0 if prev_value is None else value - prev_value
        dt_ms = 0.0 if prev_ts is None else (now - prev_ts) * 1000.0
        if delta > 0:
            self._scroll_direction = 1
        elif delta < 0:
            self._scroll_direction = -1
        page = (
            self._canvas.get_current_page(value) + 1
            if self._canvas and self._canvas._page_tops
            else 0
        )
        vp = self.viewport()
        range_now = (vbar.minimum(), vbar.maximum())
        viewport_now = (vp.width(), vp.height())

        self._last_scroll_value = value
        self._last_scroll_ts = now
        self._last_scroll_range = range_now
        self._last_viewport_size = viewport_now
        self._scroll_debounce.start()

        # Visible-page detection is deferred to _scroll_debounce (150ms after
        # motion stops) — see _emit_visible_pages. Doing it eagerly here runs
        # set-rebuilds + cache probes on the GUI thread every pixel of scroll.

    def _on_scroll_range_changed(self, minimum, maximum):
        prev = self._last_scroll_range
        value = self.verticalScrollBar().value()
        vp = self.viewport()
        self._last_scroll_range = (minimum, maximum)

    def _emit_visible_pages(self):
        """
        Called 120ms after scroll stops.
        Calculates which pages are currently visible in the viewport
        and emits visible_pages_changed(first, last).
        """
        if not self._canvas or not self._canvas._page_tops:
            return

        vp_h = self.viewport().height()
        scroll_y = self.verticalScrollBar().value()
        scale = self._canvas._scale

        # Convert screen coords → image-space
        img_top = scroll_y / max(scale, 0.01)
        img_bottom = (scroll_y + vp_h) / max(scale, 0.01)

        page_tops = self._canvas._page_tops
        pages = self._canvas._pages
        total = len(page_tops)

        first = 0
        last = total - 1

        for i, top in enumerate(page_tops):
            h = pages[i].height() if i < len(pages) else 0
            page_bot = top + h
            if page_bot < img_top:
                first = i + 1  # this page is above viewport
            if top > img_bottom:
                last = i - 1  # this page is below viewport
                break

        first = max(0, min(first, total - 1))
        last = max(0, min(last, total - 1))

        # Prefetch just one page in the scroll direction so the current page
        # and its neighbor stay ready without adding extra render churn.
        PREFETCH_PAGES = 1
        if self._scroll_direction > 0:
            last = min(total - 1, last + PREFETCH_PAGES)
        elif self._scroll_direction < 0:
            first = max(0, first - PREFETCH_PAGES)

        self._last_visible_emit_ts = time.perf_counter()
        self.visible_pages_changed.emit(first, last)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        vp = self.viewport()
        size_now = (vp.width(), vp.height())
        prev = self._last_viewport_size
        self._last_viewport_size = size_now

    def eventFilter(self, obj, e):
        if obj is self.viewport() or obj is self._canvas:
            t = e.type()
            if t == QEvent.MouseButtonRelease:
                if self._pan_active:
                    self._pan_active = False
                    self._pan_start_pos = None
                    self._is_actually_panning = False
                    self._clear_pan_cursor()
                    if self._pan_mode:
                        self._enter_pan_cursor()
                    return False
            elif t in (QEvent.Leave, QEvent.HoverLeave):
                if self._pan_active:
                    self._pan_active = False
                    self._pan_start_pos = None
                    self._is_actually_panning = False
                    self._clear_pan_cursor()
                return False
        return super().eventFilter(obj, e)

    def _set_pan_cursor(self, shape):
        c = QCursor(shape)
        self.viewport().setCursor(c)
        self.setCursor(c)
        if self._canvas:
            self._canvas.setCursor(c)

    def _clear_pan_cursor(self):
        self.viewport().unsetCursor()
        self.unsetCursor()
        if self._canvas:
            if getattr(self._canvas, "_mode", "") == "review":
                self._canvas.setCursor(QCursor(Qt.PointingHandCursor))
            else:
                self._canvas.set_tool(self._canvas._tool)

    def _enter_pan_cursor(self):
        self._set_pan_cursor(Qt.OpenHandCursor)

    def _exit_pan_cursor(self):
        self._clear_pan_cursor()

    def wheelEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self._canvas:
            self._canvas.wheelEvent(e)
            return

        # 1. Touchpads sending high-precision PIXEL deltas (typically macOS/some Windows Precision Touchpads)
        pd = e.pixelDelta()
        if pd is not None and not pd.isNull():
            # Amplify pixel-delta scrolling so it matches native scroll feel.
            _PIXEL_SCROLL_GAIN = 1.5
            dy = int(round(pd.y() * _PIXEL_SCROLL_GAIN))
            dx = int(round(pd.x() * _PIXEL_SCROLL_GAIN))
            if dy != 0:
                vbar = self.verticalScrollBar()
                vbar.setValue(vbar.value() - dy)
            if dx != 0:
                hbar = self.horizontalScrollBar()
                hbar.setValue(hbar.value() - dx)
            e.accept()
            return

        # 2. Fallback to angleDelta (standard mouse wheel, and trackpads on Windows where pixelDelta is null)
        ad = e.angleDelta()
        if ad is not None and not ad.isNull():
            # Standard mouse wheel scrolls in 120-unit ticks.
            # Map 120 units to 80 pixels for a snappy, responsive feel.
            # For touchpads sending small step deltas, it scales down proportionally and smoothly.
            _ANGLE_SCROLL_MULTIPLIER = 80.0 / 120.0
            dy = int(round(ad.y() * _ANGLE_SCROLL_MULTIPLIER))
            dx = int(round(ad.x() * _ANGLE_SCROLL_MULTIPLIER))
            if dy != 0:
                vbar = self.verticalScrollBar()
                vbar.setValue(vbar.value() - dy)
            if dx != 0:
                hbar = self.horizontalScrollBar()
                hbar.setValue(hbar.value() - dx)
            e.accept()
            return

        super().wheelEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_H and not e.isAutoRepeat():
            self._pan_mode = not self._pan_mode
            if self._pan_mode:
                self._enter_pan_cursor()
            else:
                self._exit_pan_cursor()
            e.accept()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        super().keyReleaseEvent(e)

    def _should_pan(self, e):
        if e.button() == Qt.MiddleButton:
            return True
        if e.button() == Qt.LeftButton and self.pan_mode:
            return True
        return False

    def mousePressEvent(self, e):
        if self._should_pan(e):
            self._pan_active = True
            self._pan_start_pos = e.globalPos()
            self._pan_hval = self.horizontalScrollBar().value()
            self._pan_vval = self.verticalScrollBar().value()
            self._is_actually_panning = False
            self._set_pan_cursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan_active and self._pan_start_pos is not None:
            dv = e.globalPos() - self._pan_start_pos
            if not self._is_actually_panning:
                if dv.manhattanLength() > self._drag_threshold:
                    self._is_actually_panning = True
                    self._set_pan_cursor(Qt.ClosedHandCursor)
                else:
                    return
            self.horizontalScrollBar().setValue(self._pan_hval - dv.x())
            self.verticalScrollBar().setValue(self._pan_vval - dv.y())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan_active:
            self._pan_active = False
            self._pan_start_pos = None
            self._is_actually_panning = False
            self._clear_pan_cursor()
            if self._pan_mode:
                self._enter_pan_cursor()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        if self._pan_active:
            self._pan_active = False
            self._pan_start_pos = None
            self._is_actually_panning = False
            self._clear_pan_cursor()
        super().leaveEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  CHANGES NEEDED IN anki_occlusion_v19.py
# ═══════════════════════════════════════════════════════════════════════════════
#
#  1. The import at the top — remove pdf_to_combined_pixmap, add nothing:
#       BEFORE:  from pdf_engine import (PDF_SUPPORT, PAGE_CACHE, pdf_to_combined_pixmap, PdfLoaderThread)
#       AFTER:   from pdf_engine import (PDF_SUPPORT, PAGE_CACHE, PdfLoaderThread)
#
#  2. In ReviewScreen._reload_current_canvas() replace the pdf branch:
#
#       BEFORE:
#           combined, _, _ = pdf_to_combined_pixmap(path)
#           if not combined.isNull():
#               px = combined
#           else:
#               self._start_review_pdf_thread(card, box_idx)
#               return
#
#       AFTER:
#           cached_pages = [PAGE_CACHE.get(path, i)
#                           for i in range(1000)          # walk until None
#                           if PAGE_CACHE.get(path, i)]
#           # stop at first missing page
#           clean = []
#           for i in range(10000):
#               pg = PAGE_CACHE.get(path, i)
#               if pg is None: break
#               clean.append(pg)
#           if clean:
#               self._apply_canvas_pages(card, box_idx, clean)
#               return
#           else:
#               self._start_review_pdf_thread(card, box_idx)
#               return
#
#  3. Add _apply_canvas_pages() next to _apply_canvas():
#
#       def _apply_canvas_pages(self, card, box_idx, pages):
#           self.canvas.load_pages(pages)
#           self._apply_canvas_boxes(card, box_idx)
#           QTimer.singleShot(30,  lambda: self._fit_zoom_pages(pages))
#           QTimer.singleShot(80,  lambda: self._scroll_to_mask(box_idx))
#
#  See full patch in the README or ask for the updated anki_occlusion_v19.py.
