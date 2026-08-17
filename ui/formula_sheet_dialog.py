import os
import copy
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget, QPushButton,
    QFrame, QMessageBox, QSplitter, QListWidget, QListWidgetItem, QTextBrowser,
    QLineEdit, QStackedWidget, QApplication
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QImage, QPainter, QColor, QPen, QBrush

from theme_manager import get_palette, is_retro_theme
from storage_paths import resolve_asset_path
from data_manager import store
from pdf_engine import pdf_page_to_pixmap

# Simple custom widget to draw scaled occlusion backgrounds and overlay masks.
class FormulaPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.boxes = []
        self.revealed = False
        self.zoom_factor = 1.0

    def set_card(self, card):
        self.revealed = False
        pdf_path = resolve_asset_path(card.get("pdf_path", ""))
        image_path = resolve_asset_path(card.get("image_path", ""))
        self.boxes = card.get("boxes", [])

        # Clean old state
        self.pixmap = None

        if pdf_path and os.path.exists(pdf_path):
            page_num = 0
            if self.boxes:
                page_num = self.boxes[0].get("page_num", 0)
            self.zoom_factor = 1.5
            try:
                import fitz
                doc = fitz.open(pdf_path)
                if 0 <= page_num < len(doc):
                    page = doc[page_num]
                    mat = fitz.Matrix(self.zoom_factor, self.zoom_factor)
                    self.pixmap = pdf_page_to_pixmap(page, mat)
                    
                    # Adapt boxes to our fixed zoom factor
                    src_zoom = card.get("_pdf_box_render_zoom", 1.5)
                    from pdf_engine import adapt_pdf_boxes_to_render_zoom
                    self.boxes = adapt_pdf_boxes_to_render_zoom(pdf_path, self.boxes, src_zoom, self.zoom_factor)
                doc.close()
            except Exception as e:
                print(f"[FormulaPreview] Error rendering PDF: {e}")
        elif image_path and os.path.exists(image_path):
            self.pixmap = QPixmap(image_path)
            self.zoom_factor = 1.0

        self.updateGeometry()
        self.update()

    def set_revealed(self, revealed):
        self.revealed = revealed
        self.update()

    def paintEvent(self, event):
        if not self.pixmap:
            # Draw placeholder message
            painter = QPainter(self)
            painter.setPen(QColor("#777"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "No image or PDF source loaded")
            painter.end()
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        scaled_pix = self.pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        # Centering calculations
        dx = (rect.width() - scaled_pix.width()) // 2
        dy = (rect.height() - scaled_pix.height()) // 2
        painter.drawPixmap(dx, dy, scaled_pix)

        # Draw masks if not revealed
        if not self.revealed and self.boxes:
            scale_x = scaled_pix.width() / self.pixmap.width()
            scale_y = scaled_pix.height() / self.pixmap.height()

            # Nice semi-transparent theme colors
            theme = getattr(QApplication.instance(), "_active_theme", "classic")
            p = get_palette(theme)
            mask_color_hex = p.get("C_ACCENT", "#7C6AF7")
            mask_color = QColor(mask_color_hex)
            mask_color.setAlpha(200)  # semi-opaque

            for box in self.boxes:
                r = box.get("rect", [0, 0, 0, 0])
                bx = dx + r[0] * scale_x
                by = dy + r[1] * scale_y
                bw = r[2] * scale_x
                bh = r[3] * scale_y

                painter.setPen(QPen(mask_color, 1))
                painter.setBrush(QBrush(mask_color))

                shape = box.get("shape", "rect")
                if shape == "ellipse":
                    painter.drawEllipse(int(bx), int(by), int(bw), int(bh))
                else:
                    painter.drawRect(int(bx), int(by), int(bw), int(bh))
        painter.end()


class FormulaSheetDialog(QDialog):
    practice_requested = pyqtSignal(list)
    edit_requested = pyqtSignal(dict)

    def __init__(self, deck, data, parent=None):
        super().__init__(parent)
        self.deck = deck
        self.data = data
        self.formulas = []
        self.current_card = None
        self.revealed = False

        # Find all formula cards in DFS order
        self._collect_formulas(deck)

        self._setup_ui()
        self._load_styles()

    def _collect_formulas(self, d):
        for card in d.get("cards", []):
            if card.get("is_formula", False):
                self.formulas.append(card)
        for child in d.get("children", []):
            self._collect_formulas(child)

    def _setup_ui(self):
        self.setWindowTitle(f"📐 Formula Sheet — {self.deck.get('name', 'Deck')}")
        self.resize(900, 650)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # ── Header ──
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        self.lbl_header = QLabel("📐 Formula Reference Sheet")
        self.lbl_header.setFont(QFont("Segoe UI", 16, QFont.Bold))
        
        self.btn_practice = QPushButton("▶ Practice Formulas (Quiz)")
        self.btn_practice.setCursor(Qt.PointingHandCursor)
        self.btn_practice.clicked.connect(self._on_practice_clicked)
        if not self.formulas:
            self.btn_practice.setEnabled(False)

        hdr.addWidget(self.lbl_header)
        hdr.addStretch()
        hdr.addWidget(self.btn_practice)
        main_layout.addLayout(hdr)

        # ── Empty warning if no formulas ──
        if not self.formulas:
            self.warn_frame = QFrame()
            self.warn_frame.setObjectName("warn_frame")
            w_layout = QVBoxLayout(self.warn_frame)
            w_layout.setContentsMargins(20, 20, 20, 20)
            
            lbl_warn = QLabel(
                "❌ No formulas added in this deck yet.\n\n"
                "To add formulas here:\n"
                "1. Add or edit any card in this deck.\n"
                "2. In the card editor, check 'Mark as Formula'.\n"
                "3. Save the card, and it will be visible in this sheet anytime!"
            )
            lbl_warn.setAlignment(Qt.AlignCenter)
            lbl_warn.setStyleSheet("font-size: 14px; line-height: 1.5; font-weight: bold;")
            w_layout.addWidget(lbl_warn)
            main_layout.addWidget(self.warn_frame, stretch=1)
            
            # Close button
            btn_close = QPushButton("Close")
            btn_close.clicked.connect(self.accept)
            main_layout.addWidget(btn_close)
            return

        # ── Splitter layout ──
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter, stretch=1)

        # ── Left panel ──
        left_widget = QWidget()
        left_l = QVBoxLayout(left_widget)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(8)

        self.inp_search = QLineEdit()
        self.inp_search.setPlaceholderText("🔍 Search formulas…")
        self.inp_search.textChanged.connect(self._filter_list)
        left_l.addWidget(self.inp_search)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        left_l.addWidget(self.list_widget)
        self.splitter.addWidget(left_widget)

        # Populate list
        for f in self.formulas:
            item = QListWidgetItem(f.get("title", "Untitled"))
            # Attach actual card dict to item
            item.setData(Qt.UserRole, f)
            self.list_widget.addItem(item)

        # ── Right panel ──
        right_widget = QWidget()
        right_l = QVBoxLayout(right_widget)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(10)

        # Preview stacks
        self.stack = QStackedWidget()
        right_l.addWidget(self.stack, stretch=1)

        # Index 0: Empty state
        self.lbl_empty_preview = QLabel("Select a formula from the list to preview")
        self.lbl_empty_preview.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.lbl_empty_preview)

        # Index 1: Canvas preview (for occlusion)
        self.preview_canvas = FormulaPreviewWidget()
        self.stack.addWidget(self.preview_canvas)

        # Index 2: Text card preview
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        self.stack.addWidget(self.text_browser)

        # Control Row at bottom
        self.ctrl_row = QHBoxLayout()
        self.btn_reveal = QPushButton("👁️ Reveal Formula")
        self.btn_reveal.setCursor(Qt.PointingHandCursor)
        self.btn_reveal.clicked.connect(self._toggle_reveal)

        self.btn_edit = QPushButton("✏ Edit Card")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self._on_edit_clicked)

        self.ctrl_row.addWidget(self.btn_reveal)
        self.ctrl_row.addStretch()
        self.ctrl_row.addWidget(self.btn_edit)
        right_l.addLayout(self.ctrl_row)

        self.splitter.addWidget(right_widget)
        
        # Set initial splitter sizes (30% list, 70% preview)
        self.splitter.setSizes([270, 590])

        # Auto select first formula
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _load_styles(self):
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        scale = 1.0

        bg = p.get("C_BG", "#1E1E2E")
        surface = p.get("C_SURFACE", "#2A2A3E")
        card_bg = p.get("C_CARD", "#313145")
        text = p.get("C_TEXT", "#CDD6F4")
        subtext = p.get("C_SUBTEXT", "#A6ADC8")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        green = p.get("C_GREEN", "#50FA7B")

        # Global stylesheet
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg};
                color: {text};
            }}
            QLabel {{
                color: {text};
            }}
            QLineEdit {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {accent};
            }}
            QListWidget {{
                background: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background: {accent};
                color: white;
            }}
            QListWidget::item:hover:!selected {{
                background: {card_bg};
            }}
            QTextBrowser {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QFrame#warn_frame {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QPushButton {{
                background: {card_bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {surface};
                border-color: {accent};
            }}
        """)

        # Special button classes
        self.btn_practice.setStyleSheet(f"""
            QPushButton {{
                background: {green};
                color: {bg};
                border: 1px solid {green};
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
            }}
            QPushButton:hover {{
                background: white;
                color: {bg};
            }}
        """)

        self.btn_reveal.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {accent};
                border: 2px solid {accent};
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(124, 106, 247, 0.1);
            }}
        """)

    def _filter_list(self):
        query = self.inp_search.text().strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            matches = query in item.text().lower()
            item.setHidden(not matches)

    def _on_selection_changed(self, row):
        if row < 0:
            self.stack.setCurrentIndex(0)
            self.current_card = None
            return

        item = self.list_widget.item(row)
        card = item.data(Qt.UserRole)
        self.current_card = card
        self.revealed = False
        self.btn_reveal.setText("👁️ Reveal Formula")

        if card.get("card_type") == "text":
            self.stack.setCurrentIndex(2)
            self._render_text_preview()
        else:
            self.stack.setCurrentIndex(1)
            self.preview_canvas.set_card(card)

    def _toggle_reveal(self):
        if not self.current_card:
            return
        self.revealed = not self.revealed
        if self.revealed:
            self.btn_reveal.setText("🙈 Hide Formula")
        else:
            self.btn_reveal.setText("👁️ Reveal Formula")

        if self.current_card.get("card_type") == "text":
            self._render_text_preview()
        else:
            self.preview_canvas.set_revealed(self.revealed)

    def _render_text_preview(self):
        if not self.current_card:
            return
        card = self.current_card
        theme = getattr(QApplication.instance(), "_active_theme", "classic")
        p = get_palette(theme)
        card_bg = p.get("C_CARD", "#313145")
        text_color = p.get("C_TEXT", "#CDD6F4")
        subtext = p.get("C_SUBTEXT", "#A6ADC8")
        accent = p.get("C_ACCENT", "#7C6AF7")
        border = p.get("C_BORDER", "#45475A")
        green = p.get("C_GREEN", "#50FA7B")

        html = f"""
        <html>
        <body style="background-color: {card_bg}; color: {text_color}; font-family: 'Segoe UI', sans-serif; padding: 20px; font-size: 15px;">
            <div style="font-weight: bold; color: {accent}; margin-bottom: 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Question / Prompt:</div>
            <div style="margin-bottom: 24px; line-height: 1.5; font-size: 16px;">{card.get("question", "")}</div>
        """
        if card.get("notes"):
            html += f"""
            <div style="font-style: italic; color: {subtext}; border-left: 3px solid {accent}; padding-left: 12px; margin-bottom: 24px; font-size: 13px; line-height: 1.4;">
                {card.get("notes", "")}
            </div>
            """
        if self.revealed:
            html += f"""
            <hr style="border: 0; border-top: 1px solid {border}; margin: 24px 0;">
            <div style="font-weight: bold; color: {green}; margin-bottom: 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Answer / Formula:</div>
            <div style="line-height: 1.5; font-size: 16px; font-weight: bold;">{card.get("answer", "")}</div>
            """
        else:
            html += f"""
            <hr style="border: 0; border-top: 1px solid {border}; margin: 24px 0;">
            <div style="text-align: center; padding: 15px; color: {subtext}; font-size: 13px; font-style: italic;">
                Click "Reveal Formula" or press Space to show the answer
            </div>
            """
        html += """
        </body>
        </html>
        """
        self.text_browser.setHtml(html)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._toggle_reveal()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _on_practice_clicked(self):
        if self.formulas:
            self.practice_requested.emit(self.formulas)
            self.accept()

    def _on_edit_clicked(self):
        if self.current_card:
            self.edit_requested.emit(self.current_card)
            # Accept to close the sheet so we can edit cleanly
            self.accept()
