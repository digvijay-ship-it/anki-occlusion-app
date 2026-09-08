"""
Math Trainer — Ninja Dojo Edition
Native PyQt5 page for Anki Occlusion.
Matches the Ninja theme: Orbitron font, #07070B bg, #72FF4F green, particle canvas.
"""

import random, json, os, math
from theme_manager import get_palette
from PyQt5.QtWidgets import QApplication

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QScrollArea,
    QLineEdit,
    QGridLayout,
    QSizePolicy,
    QShortcut,
    QComboBox,
    QSpinBox,
    QDialog,
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QEvent, QRect, QUrl
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QPen,
    QFont,
    QBrush,
    QPainterPath,
    QLinearGradient,
    QPolygonF,
    QCursor,
    QKeySequence,
    QPixmap,
    QImage,
)
from PyQt5.QtMultimedia import QSoundEffect

from ui.canvas.retro_effects import CRTOverlay, ParticleBurstOverlay, _home_animations_enabled
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_paths import app_resource_path
from services.ocr_engine import OcrNumberThread

import tempfile
if "unittest" in sys.modules or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    CONFIG_FILE = os.path.join(tempfile.gettempdir(), "math_trainer_config_test.json")
else:
    CONFIG_FILE = os.path.join(os.path.expanduser("~"), "math_trainer_config.json")


# ── Colours ───────────────────────────────────────────────────────────────────
BG = QColor("#07070B")
SURFACE = QColor("#0F0F17")
CARD = QColor("#0D0D16")
BORDER = QColor("#1A1A26")
GREEN = QColor("#72FF4F")
PURPLE = QColor("#A86CFF")
BLUE = QColor("#4FC3F7")
CYAN = QColor("#4FC3F7")
RED = QColor("#FF5555")
YELLOW = QColor("#F1FA8C")
TEXT = QColor("#E0E0FF")
SUBTEXT = QColor("#A6ADC8")
MUTED = QColor("#6C7086")
ORANG = QColor("#FF4444")


def _h(c):
    return c.name()


# ── Scratchpad Canvas ──────────────────────────────────────────────────────────
class MathScratchpad(QWidget):
    drawing_finished = pyqtSignal(object)

    def __init__(self, parent=None, enable_ocr: bool = True, label: str = "✏  DRAW HERE"):
        super().__init__(parent)
        self._enable_ocr = enable_ocr
        self._label_text = label
        self.setMinimumHeight(150 if not enable_ocr else 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)  # Bypass alpha-blending parent compositing
        self.setAutoFillBackground(False)
        self._strokes = []
        self._stroke_widths = []
        self._current = []
        self._current_widths = []
        self._canvas_pixmap = None
        self._pen_color = GREEN
        self._pen_width = 5.2  # Rich, bold ink style
 
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(1500)
        self._idle_timer.timeout.connect(self._trigger_ocr)

    def resizeEvent(self, e):
        self._canvas_pixmap = None
        super().resizeEvent(e)

    def clear(self):
        strokes_to_save = [list(s) for s in self._strokes]
        if getattr(self, "_current", None) and len(self._current) >= 1:
            strokes_to_save.append(list(self._current))
        if strokes_to_save:
            self._last_strokes = strokes_to_save
            self._last_stroke_widths = [list(w) for w in self._stroke_widths]
        self._strokes = []
        self._stroke_widths = []
        self._current = []
        self._current_widths = []
        if hasattr(self, "_canvas_pixmap") and self._canvas_pixmap is not None:
            self._canvas_pixmap.fill(BG)
        self.update()

    def paintEvent(self, e):
        # Ensure backing pixmap is initialized
        if not hasattr(self, "_canvas_pixmap") or self._canvas_pixmap is None:
            from PyQt5.QtGui import QPixmap
            self._canvas_pixmap = QPixmap(self.size())
            self._canvas_pixmap.fill(BG)
            
            # Redraw any completed strokes with variable segment widths
            if self._strokes:
                pix_painter = QPainter(self._canvas_pixmap)
                pix_painter.setRenderHint(QPainter.Antialiasing)
                for stroke, widths in zip(self._strokes, self._stroke_widths):
                    for i in range(len(stroke) - 1):
                        p0 = stroke[i]
                        p1 = stroke[i+1]
                        w = widths[i] if i < len(widths) else self._pen_width
                        pen = QPen(self._pen_color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                        pix_painter.setPen(pen)
                        pix_painter.drawLine(p0, p1)
                pix_painter.end()

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # 1. Draw flat backing pixmap (0ms cost)
        p.drawPixmap(0, 0, self._canvas_pixmap)
        
        # 2. Draw border
        p.setPen(QPen(GREEN, 2))
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))
        
        # 3. Draw label
        p.setFont(QFont("Arial", 9))
        label_col = QColor(GREEN)
        label_col.setAlphaF(0.7)
        p.setPen(QPen(label_col))
        p.drawText(12, 22, self._label_text)
        
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if getattr(self, "_clear_on_next_press", False):
                self.clear()
                self._clear_on_next_press = False
            import time
            self._idle_timer.stop()
            self._current = [e.localPos()]
            self._current_widths = []
            self._last_time = time.time()
            self._last_point = e.localPos()
            self._current_width = 3.6  # rich solid start width
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clear()
            self._clear_on_next_press = False
            if self._enable_ocr:
                p = self.parent()
                while p:
                    if hasattr(p, "_clear_main_scratchpad"):
                        p._clear_main_scratchpad()
                        break
                    elif hasattr(p, "_on_clear_clicked"):
                        p._on_clear_clicked()
                        break
                    p = p.parent()
            e.accept()
        else:
            super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            import time
            self._idle_timer.stop()
            pt = e.localPos()
            
            # Distance filter to prevent duplicate/too close points (1 pixel threshold)
            if self._current:
                last_pt = self._current[-1]
                dx = pt.x() - last_pt.x()
                dy = pt.y() - last_pt.y()
                if dx * dx + dy * dy < 1.0:
                    return
            
            if self._current:
                p0 = self._current[-1]
                p1 = pt
                
                # Check backing pixmap is created
                if not hasattr(self, "_canvas_pixmap") or self._canvas_pixmap is None:
                    from PyQt5.QtGui import QPixmap
                    self._canvas_pixmap = QPixmap(self.size())
                    self._canvas_pixmap.fill(BG)
                
                # Calculate velocity for dynamic brush width
                now = time.time()
                dt = now - self._last_time
                if dt <= 0:
                    dt = 0.001
                
                dist = ((p1.x() - p0.x()) ** 2 + (p1.y() - p0.y()) ** 2) ** 0.5
                velocity = dist / dt
                
                # Map velocity to width (faster -> thinner, slower -> thicker)
                min_w = 4.0
                max_w = 7.5
                target_w = max_w - (max_w - min_w) * min(1.0, velocity / 1200.0)
                
                # Exponential smoothing (alpha = 0.20)
                w = 0.20 * target_w + 0.80 * self._current_width
                self._current_width = w
                self._current_widths.append(w)
                
                # Update variables for next movement
                self._last_time = now
                self._last_point = pt
                
                # Draw new segment directly onto the backing pixmap
                pix_painter = QPainter(self._canvas_pixmap)
                pix_painter.setRenderHint(QPainter.Antialiasing)
                pen = QPen(self._pen_color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                pix_painter.setPen(pen)
                pix_painter.drawLine(p0, p1)
                pix_painter.end()
                
                # Request a dirty-rect update for maximum performance
                pen_w = w + 10
                x0 = int(min(p0.x(), p1.x()) - pen_w)
                y0 = int(min(p0.y(), p1.y()) - pen_w)
                x1 = int(max(p0.x(), p1.x()) + pen_w)
                y1 = int(max(p0.y(), p1.y()) + pen_w)
                from PyQt5.QtCore import QRect
                self.update(QRect(x0, y0, x1 - x0, y1 - y0))
                
            self._current.append(pt)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if len(self._current) >= 2:
                self._strokes.append(list(self._current))
                self._stroke_widths.append(list(self._current_widths))
                
                # Redraw all completed strokes onto backing pixmap
                if hasattr(self, "_canvas_pixmap") and self._canvas_pixmap is not None:
                    self._canvas_pixmap.fill(BG)
                    pix_painter = QPainter(self._canvas_pixmap)
                    pix_painter.setRenderHint(QPainter.Antialiasing)
                    for stroke, widths in zip(self._strokes, self._stroke_widths):
                        for i in range(len(stroke) - 1):
                            p0 = stroke[i]
                            p1 = stroke[i+1]
                            w = widths[i] if i < len(widths) else self._pen_width
                            pen = QPen(self._pen_color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                            pix_painter.setPen(pen)
                            pix_painter.drawLine(p0, p1)
                    pix_painter.end()
                    
            self._current = []
            self._current_widths = []
            self.update()
            if self._enable_ocr:
                self._idle_timer.start()
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def _trigger_ocr(self):
        if not self._strokes:
            return
        from PIL import Image, ImageDraw as PilDraw

        # Compute dynamic stroke width based on drawing height to match MNIST stroke aspect ratio
        all_pts = [p for stroke in self._strokes for p in stroke]
        if all_pts:
            min_y = min(p.y() for p in all_pts)
            max_y = max(p.y() for p in all_pts)
            h = max_y - min_y
            w = max(8, min(14, int(h * 0.18)))
        else:
            w = 9

        img = Image.new("RGB", (self.width(), self.height()), "white")
        draw = PilDraw.Draw(img)
        for stroke in self._strokes:
            if not stroke:
                continue
            pts = [(int(p.x()), int(p.y())) for p in stroke]
            if len(pts) == 1:
                r = max(3, w // 2)
                draw.ellipse((pts[0][0] - r, pts[0][1] - r, pts[0][0] + r, pts[0][1] + r), fill="black")
            else:
                draw.line(pts, fill="black", width=w, joint="curve")
                r = max(2, w // 2)
                for pt in pts:
                    draw.ellipse((pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r), fill="black")
        self.drawing_finished.emit(img)


# ── Particle Canvas ───────────────────────────────────────────────────────────
class ParticleCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._pts = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._init_pts()

    def start_anim(self):
        if not _home_animations_enabled():
            return
        if not self._timer.isActive():
            self._timer.start(30)

    def stop_anim(self):
        self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self.start_anim()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.stop_anim()

    def _init_pts(self):
        self._pts = []
        w, h = max(self.width(), 400), max(self.height(), 600)
        cols = [GREEN, PURPLE, BLUE]
        for _ in range(22):
            c = random.choice(cols)
            self._pts.append(
                {
                    "x": random.uniform(0, w),
                    "y": random.uniform(0, h),
                    "vx": random.uniform(-0.25, 0.25),
                    "vy": random.uniform(-0.25, 0.25),
                    "r": random.uniform(1, 2.5),
                    "c": c,
                }
            )

    def resizeEvent(self, e):
        self._init_pts()
        super().resizeEvent(e)

    def _tick(self):
        if not _home_animations_enabled():
            self.stop_anim()
            self.update()
            return
        w, h = self.width(), self.height()
        for p in self._pts:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            if p["x"] < 0 or p["x"] > w:
                p["vx"] *= -1
            if p["y"] < 0 or p["y"] > h:
                p["vy"] *= -1
        self.update()

    def paintEvent(self, e):
        if not _home_animations_enabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pts = self._pts
        for i, a in enumerate(pts):
            col = QColor(a["c"])
            col.setAlphaF(0.45)
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(a["x"], a["y"]), a["r"], a["r"])
            for b in pts[i + 1 :]:
                dx, dy = a["x"] - b["x"], a["y"] - b["y"]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 130:
                    lc = QColor(a["c"])
                    lc.setAlphaF(0.07 * (1 - dist / 130))
                    p.setPen(QPen(lc, 0.5))
                    p.drawLine(QPointF(a["x"], a["y"]), QPointF(b["x"], b["y"]))
        p.end()


# ── Hex Logo ──────────────────────────────────────────────────────────────────
class HexLogo(QWidget):
    def __init__(self, size=34, parent=None):
        super().__init__(parent)
        from theme_manager import get_palette
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        self._hf = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        self.setFixedSize(size, size)
        self._angle = 0
        t = QTimer(self)
        t.timeout.connect(self._spin)
        t.start(50)

    def _spin(self):
        self._angle = (self._angle + 1) % 360
        self.update()

    def _hex(self, cx, cy, r, offset):
        pts = []
        for i in range(6):
            a = math.radians(60 * i + offset - 90)
            pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        return QPolygonF(pts)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = self.width() / 2 - 2
        p.setPen(QPen(GREEN, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(self._hex(cx, cy, r, 0))
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)
        dc = QColor(GREEN)
        dc.setAlphaF(0.3)
        pen2 = QPen(dc, 0.5)
        pen2.setStyle(Qt.DashLine)
        p.setPen(pen2)
        p.drawPolygon(self._hex(0, 0, r, 0))
        p.restore()
        p.setPen(QPen(GREEN))
        p.setFont(QFont(self._hf, 13, QFont.Bold))
        p.drawText(self.rect(), Qt.AlignCenter, "∑")
        p.end()


# ── Scan Card (animated top line) ────────────────────────────────────────────
class ScanCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self._scan = 0.1
        self._dir = 1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.sync_timer()

    def sync_timer(self):
        if _home_animations_enabled():
            if not self._timer.isActive():
                self._timer.start(20)
        else:
            if self._timer.isActive():
                self._timer.stop()

    def _tick(self):
        if not _home_animations_enabled():
            self.sync_timer()
            return
        self._scan += self._dir * 0.012
        if self._scan > 0.9:
            self._dir = -1
        if self._scan < 0.1:
            self._dir = 1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setBrush(QBrush(CARD))
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(r, 6, 6)
        if _home_animations_enabled():
            x = self.width() * self._scan
            span = self.width() * 0.35
            grad = QLinearGradient(max(0, x - span), 0, min(self.width(), x + span), 0)
            grad.setColorAt(0, QColor(0, 0, 0, 0))
            grad.setColorAt(0.5, GREEN)
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(QPen(QBrush(grad), 2))
            p.drawLine(int(max(0, x - span)), 0, int(min(self.width(), x + span)), 0)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  EXIT PRACTICE CONFIRMATION POPUP DIALOG
# ═══════════════════════════════════════════════════════════════════════════════
class DojoExitConfirmationDialog(QDialog):
    """
    Themed confirmation dialog when attempting to exit active practice mode via Escape.
    Styled with generous typography, dark ninja aesthetic, and large clear action buttons.
    """
    def __init__(self, parent=None, palette=None, font_family="Segoe UI"):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self._p = palette or {}
        self._hf = font_family

        scale = 1.0
        if parent and hasattr(parent, "_font_size"):
            scale = parent._font_size / 11.0

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)

        card = QFrame(self)
        c_card = self._p.get("C_CARD", "#13131F")
        c_red = self._p.get("C_RED", "#FF5555")
        c_green = self._p.get("C_GREEN", "#72FF4F")
        c_text = self._p.get("C_TEXT", "#F8F8F2")
        card.setStyleSheet(f"""
            QFrame {{
                background: {c_card};
                border: 2px solid {c_red};
                border-radius: 8px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(int(26 * scale), int(22 * scale), int(26 * scale), int(22 * scale))
        cl.setSpacing(int(14 * scale))

        title_lbl = QLabel("⚠️  ABANDON PRACTICE SESSION?")
        title_lbl.setFont(QFont(self._hf, int(15 * scale), QFont.Bold))
        title_lbl.setStyleSheet(f"color: {c_red}; background: transparent; letter-spacing: 1.5px;")
        title_lbl.setAlignment(Qt.AlignCenter)
        cl.addWidget(title_lbl)

        desc_lbl = QLabel("Are you sure you want to exit to the menu?\nYour active streak combo and current round progress will be lost.")
        desc_lbl.setFont(QFont(self._hf, int(12 * scale)))
        desc_lbl.setStyleSheet(f"color: {c_text}; background: transparent; line-height: 140%;")
        desc_lbl.setAlignment(Qt.AlignCenter)
        desc_lbl.setWordWrap(True)
        cl.addWidget(desc_lbl)

        cl.addSpacing(int(6 * scale))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(int(14 * scale))

        self.btn_cancel = QPushButton("▶  KEEP PRACTICING")
        self.btn_cancel.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
        self.btn_cancel.setFixedHeight(int(42 * scale))
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {c_green};
                color: #07070B;
                border: none;
                border-radius: 4px;
                padding: 0 {int(18 * scale)}px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: white; }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_cancel.setDefault(True)
        self.btn_cancel.setFocus()
        btn_row.addWidget(self.btn_cancel)

        self.btn_exit = QPushButton("✕  EXIT TO MENU")
        self.btn_exit.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
        self.btn_exit.setFixedHeight(int(42 * scale))
        self.btn_exit.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {c_red};
                border: 1px solid {c_red};
                border-radius: 4px;
                padding: 0 {int(18 * scale)}px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: rgba(255, 85, 85, 0.15);
                border-color: #FF6B6B;
                color: #FF6B6B;
            }}
        """)
        self.btn_exit.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_exit)

        cl.addLayout(btn_row)
        root_layout.addWidget(card)

        self.setFixedWidth(int(480 * scale))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN PAGE WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class MathTrainerPage(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from theme_manager import get_palette
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        self._p = p
        self._hf = p.get("header_font", "'Segoe UI'").split(",")[0].strip("'")
        self._bf = p.get("body_font", "'Segoe UI'").split(",")[0].strip("'")
        self.setStyleSheet(
            f"QWidget{{background:{p.get('C_BG', '#07070B')};color:{p.get('C_TEXT', '#E0E0FF')};}}"
        )
        self._mode = 1
        self._ans = 0
        self._streak = 0
        self._qn = 0
        self._tchk = {}
        self._rchk = {}
        self._config = {}
        self._last_q = None
        self._practice_timer = None
        self._selected_timer = 0
        self._correct_count = 0
        self._wrong_count = 0
        self._q_attempted = False
        self._all_pool = []
        self._active_deck = []
        self._priority_queue = []
        self._q_start_time = 0.0
        self._current_q_item = None

        # Scaling attributes
        self._font_size = 11
        self._mode_cards = []
        self._mode_icons = []
        self._mode_names = []
        self._mode_descs = []
        self._mode_arrows = []
        self._preset_btns = []

        self._snd_pick = QSoundEffect(self)
        self._snd_pick.setSource(
            QUrl.fromLocalFile(app_resource_path("assets", "music", "pickupCoin.wav"))
        )
        self._snd_pick.setVolume(0.5)

        self._snd_power = QSoundEffect(self)
        self._snd_power.setSource(
            QUrl.fromLocalFile(app_resource_path("assets", "music", "powerUp.wav"))
        )
        self._snd_power.setVolume(0.6)

        self._snd_hit = QSoundEffect(self)
        self._snd_hit.setSource(
            QUrl.fromLocalFile(app_resource_path("assets", "music", "hitHurt.wav"))
        )
        self._snd_hit.setVolume(0.5)

        self._load_config()
        self._font_size = self._get_font_size()
        self._build()
        self._update_widget_styles()
        self._show(0)

        # Retro effects overlays
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        self.crt = None
        self.burst = None
        from theme_manager import is_retro_theme
        if is_retro_theme(theme):
            self.crt = CRTOverlay(self)
            self.burst = ParticleBurstOverlay(self)

    # ── Config ────────────────────────────────────────────────────────────────
    def _load_config(self):
        self._config = {
            "tables": {},
            "squares": {},
            "cubes": {},
            "solo_focus_active": False,
            "solo_focus_table": 1,
            "selected_timer": 0,
            "streak_target": 5,
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    self._config = json.load(f)
            except:
                pass
        self._selected_timer = self._config.get("selected_timer", 0)
        self._streak_target = self._config.get("streak_target", 5)

    def _save_config(self):
        self._config["tables"] = {str(k): int(v) for k, v in self._tchk.items()}
        if self._rchk:
            key = "squares" if self._mode == 2 else "cubes"
            self._config[key] = {str(k): int(v) for k, v in self._rchk.items()}
        if hasattr(self, "_solo_btn") and hasattr(self, "_solo_combo"):
            self._config["solo_focus_active"] = self._solo_btn.isChecked()
            self._config["solo_focus_table"] = self._solo_combo.currentData()
        self._config["selected_timer"] = getattr(self, "_selected_timer", 0)
        self._config["streak_target"] = getattr(self, "_streak_target", 5)
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config, f)
        except:
            pass

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._particles = ParticleCanvas(self)
        self._particles.setAttribute(Qt.WA_TransparentForMouseEvents)

        # ── Top Bar ──────────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(52)
        top.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};border-bottom:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 0, 16, 0)
        tl.setSpacing(10)

        self._hex = HexLogo(34)
        tl.addWidget(self._hex)

        titles = QWidget()
        titles.setStyleSheet("background:transparent;")
        tvl = QVBoxLayout(titles)
        tvl.setContentsMargins(0, 0, 0, 0)
        tvl.setSpacing(1)
        t1 = QLabel("MATH DOJO")
        t1.setFont(QFont(self._hf, 11, QFont.Bold))
        t1.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:2px;"
        )
        t2 = QLabel("TABLES  •  SQUARES  •  CUBES  •  TRAINER")
        t2.setFont(QFont(self._hf, 7))
        t2.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1px;"
        )
        tvl.addWidget(t1)
        tvl.addWidget(t2)
        tl.addWidget(titles)

        self._top_mode_lbl = QLabel("")
        self._top_mode_lbl.setFont(QFont(self._hf, 8, QFont.Bold))
        self._top_mode_lbl.setStyleSheet(
            f"background:transparent;color:{self._p.get('C_GREEN', _h(GREEN))};letter-spacing:1px;"
        )
        self._top_mode_lbl.hide()
        tl.addWidget(self._top_mode_lbl)
        tl.addStretch()

        combo_frame = QFrame()
        combo_frame.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_CARD', _h(CARD))};border:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:4px;}}"
        )
        cl = QHBoxLayout(combo_frame)
        cl.setContentsMargins(10, 4, 10, 4)
        cl.setSpacing(6)
        fire = QLabel("🔥")
        fire.setFont(QFont("Segoe UI Emoji", 12))
        fire.setStyleSheet("background:transparent;")
        cl.addWidget(fire)
        clbl = QLabel("COMBO")
        clbl.setFont(QFont(self._hf, 7))
        clbl.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1px;"
        )
        cl.addWidget(clbl)
        self._combo_val = QLabel("0")
        self._combo_val.setFont(QFont(self._hf, 15, QFont.Bold))
        self._combo_val.setStyleSheet(
            f"color:{self._p.get('C_ORANGE', _h(ORANG))};background:transparent;min-width:24px;"
        )
        self._combo_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cl.addWidget(self._combo_val)
        tl.addWidget(combo_frame)

        tl.addSpacing(8)
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet(
            f"QPushButton{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};"
            f"border:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:4px;font-size:14px;}}"
            f"QPushButton:hover{{color:{self._p.get('C_RED', _h(RED))};border-color:{self._p.get('C_RED', _h(RED))};}}"
        )
        btn_close.clicked.connect(self.closed.emit)
        tl.addWidget(btn_close)
        root.addWidget(top)

        # ── Stack ─────────────────────────────────────────────────────────────
        self._stack = QWidget()
        self._stack.setStyleSheet(f"background:{self._p.get('C_BG', _h(BG))};")
        sl = QVBoxLayout(self._stack)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self._p0 = self._build_p0()
        self._p1 = self._build_p1()
        self._p2 = self._build_p2()
        self._p3 = self._build_p3()
        for w in (self._p0, self._p1, self._p2, self._p3):
            sl.addWidget(w)
        root.addWidget(self._stack, 1)

        # ── Status Bar ────────────────────────────────────────────────────────
        sb = QFrame()
        sb.setFixedHeight(26)
        sb.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};border-top:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(12, 0, 12, 0)
        sbl.setSpacing(8)
        dot = QLabel("●")
        dot.setFont(QFont("Segoe UI", 8))
        dot.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;"
        )
        sbl.addWidget(dot)
        static = QLabel("•  CALCULATION DOJO  •")
        static.setFont(QFont(self._hf, 7))
        static.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
        )
        sbl.addWidget(static)
        self._sb_status = QLabel("READY")
        self._sb_status.setFont(QFont(self._hf, 7))
        self._sb_status.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;"
        )
        sbl.addWidget(self._sb_status)
        sbl.addStretch()
        root.addWidget(sb)

    def resizeEvent(self, e):
        self._particles.setGeometry(0, 52, self.width(), self.height() - 78)
        super().resizeEvent(e)
        if getattr(self, "crt", None) is not None:
            self.crt.setGeometry(self.rect())
            self.crt.raise_()
        if getattr(self, "burst", None) is not None:
            self.burst.setGeometry(self.rect())
            self.burst.raise_()
            if self.crt is not None:
                self.crt.raise_()

    def showEvent(self, e):
        self._particles.setGeometry(0, 52, self.width(), self.height() - 78)
        self._particles.raise_()
        super().showEvent(e)
        if getattr(self, "crt", None) is not None:
            self.crt.setGeometry(self.rect())
            self.crt.raise_()
            self.crt.trigger_boot_flicker()
        if getattr(self, "burst", None) is not None:
            self.burst.setGeometry(self.rect())
            self.burst.raise_()
            if self.crt is not None:
                self.crt.raise_()

    def _shake_widget(self, w):
        if not _home_animations_enabled():
            return
        from PyQt5.QtCore import QSequentialAnimationGroup, QPropertyAnimation, QPoint
        pos = w.pos()
        seq = QSequentialAnimationGroup(self)
        for dx in [12, -12, 9, -9, 6, -6, 0]:
            anim = QPropertyAnimation(w, b"pos", self)
            anim.setDuration(40)
            anim.setStartValue(w.pos())
            anim.setEndValue(QPoint(pos.x() + dx, pos.y()))
            seq.addAnimation(anim)
        seq.start()

    def go_back(self):
        if not self._p2.isHidden():
            self._show(1)
        elif not self._p1.isHidden() or not self._p3.isHidden():
            self._show(0)
        elif not self._p0.isHidden():
            self.closed.emit()

    def _prompt_exit_confirmation(self):
        timer_was_active = False
        if getattr(self, "_practice_timer", None) and self._practice_timer.isActive():
            self._practice_timer.stop()
            timer_was_active = True

        dlg = DojoExitConfirmationDialog(self, palette=self._p, font_family=self._hf)
        res = dlg.exec_()
        dlg.deleteLater()

        if res == QDialog.Accepted:
            self._show(1)
        else:
            if timer_was_active and getattr(self, "_practice_timer", None):
                self._practice_timer.start(1000)
            if hasattr(self, "_ans_in") and self._ans_in:
                self._ans_in.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            if hasattr(self, "_p2") and not self._p2.isHidden():
                has_scratch = hasattr(self, "_scratchpad") and self._scratchpad and bool(self._scratchpad._strokes or getattr(self._scratchpad, "_current", None))
                has_side = hasattr(self, "_side_scratchpad") and self._side_scratchpad and bool(self._side_scratchpad._strokes or getattr(self._side_scratchpad, "_current", None))
                has_input = hasattr(self, "_ans_in") and bool(self._ans_in.text())
                if has_scratch or has_side or has_input:
                    self._on_clear_clicked()
                else:
                    self._prompt_exit_confirmation()
            else:
                self.go_back()
            e.accept()
            return
        elif e.key() == Qt.Key_QuoteLeft:
            self._toggle_pen()
            e.accept()
            return
        elif e.key() == Qt.Key_C and (e.modifiers() & Qt.ControlModifier):
            self._copy_misread_to_clipboard()
            e.accept()
            return
        elif e.key() == Qt.Key_Space:
            if getattr(self, "_is_revealed", False):
                self._gen_q()
            else:
                self._reveal()
            e.accept()
            return
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if getattr(self, "_is_revealed", False):
                self._gen_q()
                e.accept()
                return
        super().keyPressEvent(e)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.KeyPress:
            if e.key() == Qt.Key_C and (e.modifiers() & Qt.ControlModifier):
                self._copy_misread_to_clipboard()
                return True
            elif e.key() == Qt.Key_Space:
                if getattr(self, "_is_revealed", False):
                    self._gen_q()
                else:
                    self._reveal()
                return True
            elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
                if getattr(self, "_is_revealed", False):
                    self._gen_q()
                    return True
            elif e.key() == Qt.Key_Escape:
                if hasattr(self, "_p2") and not self._p2.isHidden():
                    has_scratch = hasattr(self, "_scratchpad") and self._scratchpad and bool(self._scratchpad._strokes or getattr(self._scratchpad, "_current", None))
                    has_side = hasattr(self, "_side_scratchpad") and self._side_scratchpad and bool(self._side_scratchpad._strokes or getattr(self._side_scratchpad, "_current", None))
                    has_input = hasattr(self, "_ans_in") and bool(self._ans_in.text())
                    if has_scratch or has_side or has_input:
                        self._on_clear_clicked()
                    else:
                        self._prompt_exit_confirmation()
                else:
                    self.go_back()
                return True
        return super().eventFilter(obj, e)

    def _toggle_pen(self):
        if hasattr(self, "_scratchpad"):
            if self._scratchpad._strokes or len(self._scratchpad._current) > 0:
                img = self._scratchpad.get_pil_image()
                if self._run_ocr_async(img, source="toggle_pen"):
                    self._scratchpad.clear()
            self._ans_in.setFocus()

    # ── Page 0 ────────────────────────────────────────────────────────────────
    def _build_p0(self):
        p = QWidget()
        p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p)
        L.setAlignment(Qt.AlignCenter)
        L.setSpacing(0)
        L.addStretch()

        self._hero_lbl = QLabel("MATH DOJO")
        self._hero_lbl.setFont(QFont(self._hf, 42, QFont.Black))
        self._hero_lbl.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:4px;font-size:42pt;"
        )
        self._hero_lbl.setAlignment(Qt.AlignCenter)
        L.addWidget(self._hero_lbl)

        self._sub_lbl = QLabel("— CHOOSE YOUR DISCIPLINE —")
        self._sub_lbl.setFont(QFont(self._hf, 12))
        self._sub_lbl.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:3px;font-size:12pt;"
        )
        self._sub_lbl.setAlignment(Qt.AlignCenter)
        L.addWidget(self._sub_lbl)
        L.addSpacing(24)

        for mode_id, icon, name, desc, color, bg_hex in [
            (1, "×", "TABLES  —  पहाड़े", "MULTIPLICATION 1–45", BLUE, "#0A1520"),
            (2, "x²", "SQUARES — वर्ग", "PERFECT SQUARES", PURPLE, "#120A20"),
            (3, "x³", "CUBES   — घन", "PERFECT CUBES", RED, "#200A0A"),
        ]:
            c_hex = _h(color)
            card = QFrame()
            card.setFixedSize(360, 70)
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet(f"""
                QFrame{{background:{bg_hex};border:1px solid {c_hex}55;
                    border-left:3px solid {c_hex};border-radius:5px;}}
                QFrame:hover{{background:{bg_hex};border-color:{c_hex};
                    border-left:3px solid {c_hex};}}
            """)
            ol = QHBoxLayout(card)
            ol.setContentsMargins(12, 0, 12, 0)
            ol.setSpacing(12)
            ic = QLabel(icon)
            ic.setFont(QFont(self._hf, 24, QFont.Black))
            ic.setStyleSheet(f"color:{c_hex};background:transparent;min-width:48px;font-size:24pt;")
            ic.setAttribute(Qt.WA_TransparentForMouseEvents)
            ic.setAlignment(Qt.AlignCenter)
            ol.addWidget(ic)
            tw = QWidget()
            tw.setStyleSheet("background:transparent;")
            tw.setAttribute(Qt.WA_TransparentForMouseEvents)
            tvl = QVBoxLayout(tw)
            tvl.setContentsMargins(0, 0, 0, 0)
            tvl.setSpacing(2)
            nl = QLabel(name)
            nl.setFont(QFont(self._hf, 14, QFont.Bold))
            nl.setAttribute(Qt.WA_TransparentForMouseEvents)
            nl.setStyleSheet(
                f"color:{c_hex};background:transparent;letter-spacing:1px;font-size:14pt;"
            )
            dl = QLabel(desc)
            dl.setFont(QFont(self._hf, 10))
            dl.setAttribute(Qt.WA_TransparentForMouseEvents)
            dl.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;font-size:10pt;"
            )
            tvl.addWidget(nl)
            tvl.addWidget(dl)
            ol.addWidget(tw)
            ol.addStretch()
            arr = QLabel("▶")
            arr.setFont(QFont(self._hf, 14))
            arr.setAttribute(Qt.WA_TransparentForMouseEvents)
            arr.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
            )
            ol.addWidget(arr)
            card.mousePressEvent = lambda _, m=mode_id: self._select_mode(m)
            
            # Store references
            self._mode_cards.append(card)
            self._mode_icons.append(ic)
            self._mode_names.append(nl)
            self._mode_descs.append(dl)
            self._mode_arrows.append(arr)
            
            L.addWidget(card, 0, Qt.AlignHCenter)
            L.addSpacing(8)

        L.addStretch()
        return p

    # ── Page 1 ────────────────────────────────────────────────────────────────
    def _build_p1(self):
        p = QWidget()
        p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};border-bottom:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(12)
        self._back_btn_p1 = self._mk_back_btn()
        self._back_btn_p1.clicked.connect(lambda: self._show(0))
        hl.addWidget(self._back_btn_p1)
        self._p1_title = QLabel("SELECT CHALLENGE")
        self._p1_title.setFont(QFont(self._hf, 11, QFont.Bold))
        self._p1_title.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:2px;"
        )
        hl.addWidget(self._p1_title)
        L.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(10)

        self._tab_sec = QWidget()
        self._tab_sec.setStyleSheet("background:transparent;")
        tsl = QVBoxLayout(self._tab_sec)
        tsl.setContentsMargins(0, 0, 0, 0)
        tsl.setSpacing(6)
        self._lbl_tables_title = QLabel("— SELECT TABLES (1–45) —")
        self._lbl_tables_title.setFont(QFont(self._hf, 10))
        self._lbl_tables_title.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1.5px;"
        )
        tsl.addWidget(self._lbl_tables_title)

        # ── Solo Focus Mode Controls ──
        solo_row = QWidget()
        solo_row.setStyleSheet("background:transparent;")
        solo_rl = QHBoxLayout(solo_row)
        solo_rl.setContentsMargins(0, 4, 0, 4)
        solo_rl.setSpacing(10)
        
        self._solo_btn = QPushButton("🎯 SOLO FOCUS: OFF")
        self._solo_btn.setCheckable(True)
        saved_solo = bool(self._config.get("solo_focus_active", False))
        self._solo_btn.setChecked(saved_solo)
        self._solo_btn.setText("🎯 SOLO FOCUS: ON" if saved_solo else "🎯 SOLO FOCUS: OFF")
        self._solo_btn.setMinimumWidth(280)
        self._solo_btn.setFixedHeight(36)
        self._solo_btn.setFont(QFont(self._hf, 12, QFont.Bold))
        c_green = _h(GREEN)
        self._solo_btn.setStyleSheet(f"""
            QPushButton{{
                font-family: {self._hf};
                font-size: 12px;
                font-weight: bold;
                background:#0D0D16; color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:3px;
            }}
            QPushButton:hover{{ border-color:{c_green}; color:{c_green}; }}
            QPushButton:checked{{ background:rgba(114,255,79,0.12); border-color:{c_green}; color:{c_green}; }}
        """)
        
        def _on_solo_toggled(checked):
            self._solo_btn.setText("🎯 SOLO FOCUS: ON" if checked else "🎯 SOLO FOCUS: OFF")
            self._save_config()
        self._solo_btn.toggled.connect(_on_solo_toggled)
        
        self._solo_combo = QComboBox()
        self._solo_combo.setFixedSize(140, 36)
        self._solo_combo.setFont(QFont("Arial", 12, QFont.Bold))
        for i in range(1, 46):
            self._solo_combo.addItem(f"Table {i}", i)
            
        saved_table = self._config.get("solo_focus_table", 1)
        idx = self._solo_combo.findData(saved_table)
        if idx >= 0:
            self._solo_combo.setCurrentIndex(idx)
        self._solo_combo.currentIndexChanged.connect(lambda: self._save_config())
            
        self._solo_combo.setStyleSheet(f"""
            QComboBox {{
                font-family: Arial;
                font-size: 12px;
                font-weight: bold;
                background: #0D0D16;
                color: {self._p.get('C_TEXT', _h(TEXT))};
                border: 1px solid {self._p.get('C_BORDER', _h(BORDER))};
                border-radius: 3px;
                padding: 4px 8px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                font-family: Arial;
                font-size: 12px;
                font-weight: bold;
                background: #0D0D16;
                color: {self._p.get('C_TEXT', _h(TEXT))};
                selection-background-color: {self._p.get('C_BORDER', _h(BORDER))};
                border: 1px solid {self._p.get('C_BORDER', _h(BORDER))};
            }}
        """)
        
        solo_rl.addWidget(self._solo_btn)
        solo_rl.addWidget(self._solo_combo)
        solo_rl.addStretch()
        tsl.addWidget(solo_row)

        # ── Quick Sets Controls ──
        quick_row = QWidget()
        quick_row.setStyleSheet("background:transparent;")
        quick_rl = QHBoxLayout(quick_row)
        quick_rl.setContentsMargins(0, 4, 0, 4)
        quick_rl.setSpacing(8)
        
        self._lbl_quick = QLabel("QUICK SETS:")
        self._lbl_quick.setFont(QFont(self._hf, 10, QFont.Bold))
        self._lbl_quick.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1px;"
        )
        quick_rl.addWidget(self._lbl_quick)
        
        quick_rl.addWidget(self._mk_preset_btn("6–12", 6, 12))
        quick_rl.addWidget(self._mk_preset_btn("12–19", 12, 19))
        quick_rl.addWidget(self._mk_preset_btn("20–29", 20, 29))
        quick_rl.addStretch()
        tsl.addWidget(quick_row)
        
        # ── Custom Range Controls ──
        custom_row = QWidget()
        custom_row.setStyleSheet("background:transparent;")
        custom_rl = QHBoxLayout(custom_row)
        custom_rl.setContentsMargins(0, 4, 0, 4)
        custom_rl.setSpacing(8)
        
        self._lbl_custom = QLabel("CUSTOM:")
        self._lbl_custom.setFont(QFont(self._hf, 10, QFont.Bold))
        self._lbl_custom.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1px;"
        )
        custom_rl.addWidget(self._lbl_custom)
        
        self._range_start = QSpinBox()
        self._range_start.setRange(1, 45)
        self._range_start.setValue(6)
        self._range_start.setFixedSize(50, 26)
        self._range_start.setFont(QFont(self._hf, 11))
        self._range_start.setStyleSheet(f"""
            QSpinBox {{
                font-family: {self._hf};
                font-size: 11px;
                background:#0D0D16; color:white;
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:3px;
                padding-left: 4px;
            }}
        """)
        custom_rl.addWidget(self._range_start)
        
        self._lbl_to = QLabel("to")
        self._lbl_to.setFont(QFont(self._hf, 10))
        self._lbl_to.setStyleSheet(f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;")
        custom_rl.addWidget(self._lbl_to)
        
        self._range_end = QSpinBox()
        self._range_end.setRange(1, 45)
        self._range_end.setValue(12)
        self._range_end.setFixedSize(50, 26)
        self._range_end.setFont(QFont(self._hf, 11))
        self._range_end.setStyleSheet(f"""
            QSpinBox {{
                font-family: {self._hf};
                font-size: 11px;
                background:#0D0D16; color:white;
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:3px;
                padding-left: 4px;
            }}
        """)
        custom_rl.addWidget(self._range_end)
        
        self._apply_btn = QPushButton("SET")
        self._apply_btn.setMinimumWidth(60)
        self._apply_btn.setFixedHeight(26)
        self._apply_btn.setFont(QFont(self._hf, 11, QFont.Bold))
        self._apply_btn.setStyleSheet(f"""
            QPushButton{{
                font-family: {self._hf};
                font-size: 11px;
                font-weight: bold;
                background:#0D0D16; color:{c_green};
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:3px;
            }}
            QPushButton:hover{{ border-color:{c_green}; color:white; }}
            QPushButton:pressed{{ background:rgba(114,255,79,0.12); }}
        """)
        self._apply_btn.clicked.connect(lambda: self._apply_range_selection(self._range_start.value(), self._range_end.value()))
        custom_rl.addWidget(self._apply_btn)
        
        self._clear_btn = QPushButton("CLEAR")
        self._clear_btn.setMinimumWidth(80)
        self._clear_btn.setFixedHeight(26)
        self._clear_btn.setFont(QFont(self._hf, 11, QFont.Bold))
        c_red = _h(RED)
        self._clear_btn.setStyleSheet(f"""
            QPushButton{{
                font-family: {self._hf};
                font-size: 11px;
                font-weight: bold;
                background:#0D0D16; color:{c_red};
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:3px;
            }}
            QPushButton:hover{{ border-color:{c_red}; color:white; }}
            QPushButton:pressed{{ background:rgba(255,68,68,0.12); }}
        """)
        self._clear_btn.clicked.connect(lambda: self._apply_range_selection(0, 0))
        custom_rl.addWidget(self._clear_btn)

        custom_rl.addStretch()
        tsl.addWidget(custom_row)

        gw = QWidget()
        gw.setStyleSheet(
            f"background:{self._p.get('C_SURFACE', _h(SURFACE))};border-radius:4px;"
        )
        self._tab_grid = QGridLayout(gw)
        self._tab_grid.setContentsMargins(8, 8, 8, 8)
        self._tab_grid.setSpacing(4)
        self._tab_btns = {}
        for i in range(1, 46):
            saved = bool(self._config.get("tables", {}).get(str(i), 0))
            self._tchk[i] = saved
            b = self._mk_cb(str(i), saved, GREEN)
            b.toggled.connect(lambda checked, n=i: self._toggle_tab(n, checked))
            self._tab_btns[i] = b
            self._tab_grid.addWidget(b, (i - 1) // 9, (i - 1) % 9)
        tsl.addWidget(gw)
        bl.addWidget(self._tab_sec)

        self._rng_sec = QWidget()
        self._rng_sec.setStyleSheet("background:transparent;")
        rsl = QVBoxLayout(self._rng_sec)
        rsl.setContentsMargins(0, 0, 0, 0)
        rsl.setSpacing(6)
        self._rng_sec_lbl = QLabel("— SELECT RANGE —")
        self._rng_sec_lbl.setFont(QFont(self._hf, 7))
        self._rng_sec_lbl.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1.5px;"
        )
        rsl.addWidget(self._rng_sec_lbl)
        self._rng_gw = QWidget()
        self._rng_gw.setStyleSheet(
            f"background:{self._p.get('C_SURFACE', _h(SURFACE))};border-radius:4px;"
        )
        self._rng_grid = QGridLayout(self._rng_gw)
        self._rng_grid.setContentsMargins(8, 8, 8, 8)
        self._rng_grid.setSpacing(6)
        rsl.addWidget(self._rng_gw)
        bl.addWidget(self._rng_sec)
        self._rng_sec.hide()

        self._tmr_sec = QWidget()
        self._tmr_sec.setStyleSheet("background:transparent;")
        tmsl = QVBoxLayout(self._tmr_sec)
        tmsl.setContentsMargins(0, 0, 0, 0)
        tmsl.setSpacing(6)
        self._lbl_timer_title = QLabel("— SELECT TIMER —")
        self._lbl_timer_title.setFont(QFont(self._hf, 7))
        self._lbl_timer_title.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1.5px;"
        )
        tmsl.addWidget(self._lbl_timer_title)
        tm_gw = QWidget()
        tm_gw.setStyleSheet(
            f"background:{self._p.get('C_SURFACE', _h(SURFACE))};border-radius:4px;"
        )
        tm_grid = QGridLayout(tm_gw)
        tm_grid.setContentsMargins(8, 8, 8, 8)
        tm_grid.setSpacing(6)
        self._timer_btns = {}
        timer_opts = [
            (0, "NONE"), (1, "1 MIN"), (2, "2 MIN"), (3, "3 MIN"), (5, "5 MIN"),
            (10, "10 MIN"), (15, "15 MIN"), (20, "20 MIN"), (25, "25 MIN"), (30, "30 MIN")
        ]
        cur_tmr = getattr(self, "_selected_timer", 0)
        for idx, (mins, txt) in enumerate(timer_opts):
            b = self._mk_rcb(txt, mins == cur_tmr)
            b.clicked.connect(lambda _, m=mins: self._set_timer_val(m))
            self._timer_btns[mins] = b
            r, c = divmod(idx, 5)
            tm_grid.addWidget(b, r, c)
        tmsl.addWidget(tm_gw)
        bl.addWidget(self._tmr_sec)

        # ── Streak Target Selection Section ────────────────────────────────────
        self._streak_sec = QWidget()
        self._streak_sec.setStyleSheet("background:transparent;")
        st_sl = QVBoxLayout(self._streak_sec)
        st_sl.setContentsMargins(0, 0, 0, 0)
        st_sl.setSpacing(6)
        self._lbl_streak_title = QLabel("— RETIRE CARD AFTER CONSECUTIVE STREAK —")
        self._lbl_streak_title.setFont(QFont(self._hf, 7))
        self._lbl_streak_title.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1.5px;"
        )
        st_sl.addWidget(self._lbl_streak_title)
        st_gw = QWidget()
        st_gw.setStyleSheet(
            f"background:{self._p.get('C_SURFACE', _h(SURFACE))};border-radius:4px;"
        )
        st_grid = QGridLayout(st_gw)
        st_grid.setContentsMargins(8, 8, 8, 8)
        st_grid.setSpacing(6)
        self._streak_btns = {}
        streak_opts = [
            (1, "1 STREAK"), (2, "2 STREAK"), (3, "3 STREAK"), (4, "4 STREAK"),
            (5, "5 STREAK ★"), (7, "7 STREAK"), (10, "10 STREAK"), (0, "OFF (ENDLESS ∞)")
        ]
        cur_stk = getattr(self, "_streak_target", 5)
        for idx, (s_val, txt) in enumerate(streak_opts):
            b = self._mk_scb(txt, s_val == cur_stk)
            b.clicked.connect(lambda _, s=s_val: self._set_streak_target(s))
            self._streak_btns[s_val] = b
            r, c = divmod(idx, 4)
            st_grid.addWidget(b, r, c)
        st_sl.addWidget(st_gw)
        bl.addWidget(self._streak_sec)

        self._warn_lbl = QLabel("")
        self._warn_lbl.setFont(QFont(self._hf, 11))
        self._warn_lbl.setStyleSheet(
            f"color:{self._p.get('C_RED', _h(RED))};background:transparent;"
        )
        bl.addWidget(self._warn_lbl)

        self._start_btn = QPushButton("▶  START MISSION")
        self._start_btn.setFixedHeight(44)
        self._start_btn.setFont(QFont(self._hf, 14, QFont.Black))
        self._start_btn.setStyleSheet(f"""
            QPushButton{{
                font-family: {self._hf};
                font-size: 14px;
                font-weight: 900;
                background:{self._p.get('C_GREEN', _h(GREEN))};color:#07070B;border:none;
                border-radius:4px;letter-spacing:2px;
            }}
            QPushButton:hover{{background:white;}}
            QPushButton:pressed{{background:{self._p.get('C_GREEN', _h(GREEN))};}}
        """)
        self._start_btn.clicked.connect(self._start_practice)
        bl.addWidget(self._start_btn)
        bl.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        L.addWidget(scroll, 1)
        return p

    def _mk_back_btn(self):
        scale = self._font_size / 11.0
        b = QPushButton("◀ BACK")
        b.setFixedSize(int(120 * scale), int(28 * scale))
        b.setFont(QFont(self._hf, int(11 * scale)))
        b.setStyleSheet(f"""
            QPushButton{{
                font-family: {self._hf};
                font-size: {int(11 * scale)}px;
                padding:0px !important;background:transparent;border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};
                color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};border-radius:{int(3*scale)}px;letter-spacing:{int(1*scale)}px;
            }}
            QPushButton:hover{{border-color:{self._p.get('C_GREEN', _h(GREEN))};color:{self._p.get('C_GREEN', _h(GREEN))};}}
        """)
        return b

    def _mk_cb(self, text, checked, color):
        scale = self._font_size / 11.0
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setFixedSize(int(54 * scale), int(48 * scale))
        b.setFont(QFont("Arial", int(14 * scale), QFont.Bold))
        c_hex = _h(color)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(14*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(114,255,79,0.12);border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _mk_rcb(self, text, checked):
        scale = self._font_size / 11.0
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setFixedSize(int(98 * scale), int(42 * scale))
        b.setFont(QFont("Arial", int(11 * scale), QFont.Bold))
        c_hex = _h(PURPLE)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(11*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(168,108,255,0.12);border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _mk_scb(self, text, checked):
        scale = self._font_size / 11.0
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setFixedSize(int(124 * scale), int(42 * scale))
        b.setFont(QFont("Arial", int(11 * scale), QFont.Bold))
        c_hex = _h(CYAN)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(11*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(79,195,247,0.12);border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _toggle_tab(self, n, checked):
        self._tchk[n] = checked
        self._save_config()

    def _toggle_rng(self, key, checked):
        self._rchk[key] = checked
        self._save_config()

    def _mk_preset_btn(self, text, start_val, end_val):
        scale = self._font_size / 11.0
        b = QPushButton(text)
        b.setMinimumWidth(int(80 * scale))
        b.setFixedHeight(int(26 * scale))
        b.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
        c_hex = _h(BLUE)
        b.setStyleSheet(f"""
            QPushButton{{
                font-family: {self._hf};
                font-size: {int(11 * scale)}px;
                font-weight: bold;
                background:#0D0D16; color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
            }}
            QPushButton:hover{{ border-color:{c_hex}; color:white; }}
            QPushButton:pressed{{ background:rgba(79,195,247,0.12); }}
        """)
        b.clicked.connect(lambda: self._apply_range_selection(start_val, end_val))
        if not hasattr(self, "_preset_btns"):
            self._preset_btns = []
        self._preset_btns.append(b)
        return b

    def _apply_range_selection(self, start_val, end_val):
        for i in range(1, 46):
            self._tchk[i] = False
            self._tab_btns[i].setChecked(False)
        
        if start_val > 0 and end_val > 0:
            s = min(start_val, end_val)
            e = max(start_val, end_val)
            for i in range(s, e + 1):
                if i in self._tchk:
                    self._tchk[i] = True
                    self._tab_btns[i].setChecked(True)
        self._save_config()

    def _set_timer_val(self, m):
        self._selected_timer = m
        for k, b in getattr(self, "_timer_btns", {}).items():
            b.setChecked(k == m)
        self._save_config()

    def _set_streak_target(self, s):
        self._streak_target = s
        for k, b in getattr(self, "_streak_btns", {}).items():
            b.setChecked(k == s)
        self._save_config()

    # ── Page 2 — 60/40 SPLIT LAYOUT ──────────────────────────────────────────
    def _build_p2(self):
        p = QWidget()
        p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        # Header bar
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};border-bottom:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(10)
        self._back_btn_p2 = self._mk_back_btn()
        self._back_btn_p2.clicked.connect(lambda: self._show(1))
        hl.addWidget(self._back_btn_p2)
        self._mode_badge = QLabel("")
        self._mode_badge.setFont(QFont(self._hf, 7, QFont.Bold))
        self._mode_badge.setStyleSheet(
            f"color:{self._p.get('C_BLUE', _h(BLUE))};background:rgba(79,195,247,0.1);"
            f"border:1px solid {self._p.get('C_BLUE', _h(BLUE))};border-radius:3px;padding:2px 8px;letter-spacing:1px;"
        )
        hl.addWidget(self._mode_badge)
        hl.addStretch()
        self._qcount_lbl = QLabel("MISSION 1")
        self._qcount_lbl.setFont(QFont(self._hf, 7))
        self._qcount_lbl.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
        )
        hl.addWidget(self._qcount_lbl)
        L.addWidget(hdr)

        # ── Main 60/40 horizontal split ──────────────────────────────────────
        split = QWidget()
        split.setStyleSheet("background:transparent;")
        split_layout = QHBoxLayout(split)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(0)

        # ── LEFT PANEL (70%) — question + answer + scratchpad ─────────────
        left = QWidget()
        left.setStyleSheet("background:transparent;")
        left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 8, 12, 8)
        left_layout.setSpacing(6)

        # Question display — compacted ~25% to maximize drawing canvas
        self._scan_card = ScanCard()
        self._scan_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._scan_card.setFixedHeight(160)
        inner = QVBoxLayout(self._scan_card)
        inner.setContentsMargins(16, 6, 16, 4)
        inner.setSpacing(2)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(4, 2, 4, 0)
        meta_row.setSpacing(10)
        self._q_pool_progress_lbl = QLabel("🎯 REMAINING: 0/0")
        self._q_pool_progress_lbl.setFont(QFont(self._hf, 11, QFont.Bold))
        self._q_pool_progress_lbl.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:0.5px;font-size:11pt;"
        )
        self._q_mastery_badge = QLabel("★ STREAK: 0/5  [ ○ ○ ○ ○ ○ ]")
        self._q_mastery_badge.setFont(QFont(self._hf, 12, QFont.Bold))
        self._q_mastery_badge.setStyleSheet(
            f"color:{self._p.get('C_CYAN', _h(CYAN))};background:transparent;letter-spacing:1px;font-size:12pt;"
        )
        meta_row.addWidget(self._q_pool_progress_lbl, 0, Qt.AlignLeft | Qt.AlignVCenter)
        meta_row.addStretch(1)
        meta_row.addWidget(self._q_mastery_badge, 0, Qt.AlignRight | Qt.AlignVCenter)
        inner.addLayout(meta_row)

        self._q_lbl = QLabel("?")
        self._q_lbl.setFont(QFont(self._hf, 40, QFont.Black))
        self._q_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:1px;font-size:40pt;"
        )
        self._q_lbl.setAlignment(Qt.AlignCenter)
        inner.addWidget(self._q_lbl)
        left_layout.addWidget(self._scan_card)

        # Answer input — compacted ~26% to maximize drawing canvas
        self._ans_in = QLineEdit()
        self._ans_in.installEventFilter(self)
        self._ans_in.setPlaceholderText("?")
        self._ans_in.setAlignment(Qt.AlignCenter)
        self._ans_in.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._ans_in.setFixedHeight(88)
        self._ans_in.setFont(QFont(self._hf, 52, QFont.Bold))
        self._ANS_SS = (
            f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_TEXT', _h(TEXT))};font-size:52pt;"
            f"border:2px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:6px;padding:4px;}}"
            f"QLineEdit:focus{{border:2px solid {self._p.get('C_GREEN', _h(GREEN))};}} "
        )
        self._ans_in.setStyleSheet(self._ANS_SS)
        self._ans_in.textChanged.connect(self._auto_check)
        self._ans_in.returnPressed.connect(self._check)
        left_layout.addWidget(self._ans_in)

        # Feedback label
        self._fb_lbl = QLabel("")
        self._fb_lbl.setFont(QFont(self._hf, 18, QFont.Bold))
        self._fb_lbl.setFixedHeight(30)
        self._fb_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:1px;font-size:18px;"
        )
        self._fb_lbl.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self._fb_lbl)

        # Scratchpad toolbar
        self._sp_bar = QHBoxLayout()
        self._sp_bar.setContentsMargins(0, 4, 0, 2)
        sp_hint_lbl = QLabel("✏ DRAW HERE (DBL-CLICK OR ESC TO CLEAR)")
        sp_hint_lbl.setFont(QFont(self._hf, 8, QFont.Bold))
        sp_hint_lbl.setStyleSheet(f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1px;")
        self._sp_bar.addWidget(sp_hint_lbl)
        self._sp_bar.addStretch(1)

        self._clear_btn = QPushButton("CLEAR ⌫ (Esc)")
        self._clear_btn.setFixedHeight(26)
        self._clear_btn.setFont(QFont(self._hf, 8, QFont.Bold))
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setStyleSheet(
            f"QPushButton{{font-family: {self._hf}; font-size: 8px; font-weight: bold; background:transparent;"
            f"border:1px solid {self._p.get('C_BORDER', _h(BORDER))};color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};"
            f"border-radius:3px;padding:0 10px;letter-spacing:1px;}}"
            f"QPushButton:hover{{border-color:{self._p.get('C_RED', _h(RED))};color:{self._p.get('C_RED', _h(RED))};}}"
        )
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        self._sp_bar.addWidget(self._clear_btn)

        self._copy_misread_btn = QPushButton("📸 COPY MISREAD (Ctrl+C)")
        self._copy_misread_btn.setFixedHeight(26)
        self._copy_misread_btn.setFont(QFont(self._hf, 8, QFont.Bold))
        self._copy_misread_btn.setCursor(Qt.PointingHandCursor)
        self._copy_misread_btn.setStyleSheet(
            f"QPushButton{{font-family: {self._hf}; font-size: 8px; font-weight: bold; background:transparent;"
            f"border:1px solid {self._p.get('C_RED', _h(RED))};color:{self._p.get('C_RED', _h(RED))};"
            f"border-radius:3px;padding:0 10px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(255,107,107,0.15);}}"
        )
        self._copy_misread_btn.clicked.connect(self._copy_misread_to_clipboard)
        self._sp_bar.addWidget(self._copy_misread_btn)

        self._reveal_bar_btn = QPushButton("REVEAL 👁 (Space)")
        self._reveal_bar_btn.setFixedHeight(26)
        self._reveal_bar_btn.setFont(QFont(self._hf, 8, QFont.Bold))
        self._reveal_bar_btn.setCursor(Qt.PointingHandCursor)
        self._reveal_bar_btn.setStyleSheet(
            f"QPushButton{{font-family: {self._hf}; font-size: 8px; font-weight: bold; background:transparent;"
            f"border:1px solid {self._p.get('C_YELLOW', _h(YELLOW))};color:{self._p.get('C_YELLOW', _h(YELLOW))};"
            f"border-radius:3px;padding:0 10px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(241,250,140,0.1);}}"
        )
        self._reveal_bar_btn.clicked.connect(self._on_reveal_clicked)
        self._sp_bar.addWidget(self._reveal_bar_btn)
        left_layout.addLayout(self._sp_bar)

        # Scratchpad — expands to fill all saved vertical real estate
        self._scratchpad = MathScratchpad(self, enable_ocr=True, label="✏  DRAW HERE")
        self._scratchpad.installEventFilter(self)
        self._scratchpad.drawing_finished.connect(self._handle_drawn_image)
        self._scratchpad.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._scratchpad.setMinimumHeight(240)
        left_layout.addWidget(self._scratchpad, 1)

        # Reveal button (shown on wrong answer)
        self._show_ans_btn = QPushButton("REVEAL ANSWER 👁")
        self._show_ans_btn.setFixedHeight(40)
        self._show_ans_btn.setFont(QFont(self._hf, 10, QFont.Bold))
        self._show_ans_btn.setStyleSheet(
            f"QPushButton{{font-family: {self._hf}; font-size: 10px; font-weight: bold; background:transparent;border:1px solid {self._p.get('C_YELLOW', _h(YELLOW))};"
            f"color:{self._p.get('C_YELLOW', _h(YELLOW))};border-radius:3px;padding:0 14px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(241,250,140,0.1);}}"
        )
        self._show_ans_btn.hide()
        self._show_ans_btn.clicked.connect(self._on_reveal_clicked)
        left_layout.addWidget(self._show_ans_btn)

        # ── RIGHT PANEL (30%) — compact reveal / reference + rough pad ────
        self._right_panel = QFrame()
        self._right_panel.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};"
            f"border-left:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        self._right_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(6)

        # Panel header
        rp_hdr = QLabel("▣  REFERENCE")
        rp_hdr.setFont(QFont(self._hf, 8, QFont.Bold))
        rp_hdr.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:2px;"
        )
        right_layout.addWidget(rp_hdr)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{self._p.get('C_BORDER', _h(BORDER))};")
        right_layout.addWidget(div)

        # Hint when nothing revealed yet (compact)
        self._reveal_hint = QLabel(
            "Draw your answer or type it in.\nHit Space or REVEAL to see answer."
        )
        self._reveal_hint.setFont(QFont(self._hf, 9))
        self._reveal_hint.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;padding:2px 0;"
        )
        self._reveal_hint.setAlignment(Qt.AlignCenter)
        self._reveal_hint.setFixedHeight(45)
        right_layout.addWidget(self._reveal_hint)

        # Compact Answer Card (for mode 2, 3, 4: squares, cubes, roots)
        self._reveal_card = QFrame()
        self._reveal_card.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_CARD', _h(CARD))};border:1px solid {self._p.get('C_GREEN', _h(GREEN))};border-radius:4px;}}"
        )
        rc_lay = QVBoxLayout(self._reveal_card)
        rc_lay.setContentsMargins(8, 6, 8, 6)
        rc_lay.setSpacing(2)
        self._reveal_card_hdr = QLabel("ANSWER")
        self._reveal_card_hdr.setFont(QFont(self._hf, 7, QFont.Bold))
        self._reveal_card_hdr.setStyleSheet(f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};letter-spacing:1px;background:transparent;")
        rc_lay.addWidget(self._reveal_card_hdr)
        self._reveal_card_val = QLabel("")
        self._reveal_card_val.setFont(QFont(self._hf, 18, QFont.Bold))
        self._reveal_card_val.setStyleSheet(f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;")
        self._reveal_card_val.setAlignment(Qt.AlignCenter)
        rc_lay.addWidget(self._reveal_card_val)
        self._reveal_card.hide()
        right_layout.addWidget(self._reveal_card)

        # Reveal content scroll (for mode 1: tables)
        self._reveal_scroll = QScrollArea()
        self._reveal_scroll.setStyleSheet(
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QScrollBar:vertical{{background:{self._p.get('C_CARD', _h(CARD))};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{self._p.get('C_BORDER', _h(BORDER))};border-radius:3px;}}"
        )
        self._reveal_scroll.setMaximumHeight(170)
        self._reveal_lbl = QLabel("")
        self._reveal_lbl.setFont(QFont("Courier New", 14))
        self._reveal_lbl.setStyleSheet(
            f"color:{self._p.get('C_BLUE', _h(BLUE))};background:transparent;padding:4px;"
        )
        self._reveal_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._reveal_scroll.setWidget(self._reveal_lbl)
        self._reveal_scroll.setWidgetResizable(True)
        self._reveal_scroll.hide()
        right_layout.addWidget(self._reveal_scroll)

        # Divider above rough pad
        div2 = QFrame()
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background:{self._p.get('C_BORDER', _h(BORDER))};")
        right_layout.addWidget(div2)

        # Rough pad toolbar
        self._side_sp_bar = QHBoxLayout()
        self._side_sp_bar.setContentsMargins(0, 2, 0, 2)
        side_hint_lbl = QLabel("✏ ROUGH PAD")
        side_hint_lbl.setFont(QFont(self._hf, 8, QFont.Bold))
        side_hint_lbl.setStyleSheet(f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1px;")
        self._side_sp_bar.addWidget(side_hint_lbl)
        self._side_sp_bar.addStretch(1)

        self._side_clear_btn = QPushButton("CLEAR ⌫")
        self._side_clear_btn.setFixedHeight(22)
        self._side_clear_btn.setFont(QFont(self._hf, 7, QFont.Bold))
        self._side_clear_btn.setCursor(Qt.PointingHandCursor)
        self._side_clear_btn.setStyleSheet(
            f"QPushButton{{font-family: {self._hf}; font-size: 7px; font-weight: bold; background:transparent;"
            f"border:1px solid {self._p.get('C_BORDER', _h(BORDER))};color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};"
            f"border-radius:3px;padding:0 8px;letter-spacing:1px;}}"
            f"QPushButton:hover{{border-color:{self._p.get('C_RED', _h(RED))};color:{self._p.get('C_RED', _h(RED))};}}"
        )
        self._side_clear_btn.clicked.connect(self._clear_side_scratchpad)
        self._side_sp_bar.addWidget(self._side_clear_btn)
        right_layout.addLayout(self._side_sp_bar)

        # Rough Scratchpad — expands to fill remaining space
        self._side_scratchpad = MathScratchpad(self, enable_ocr=False, label="✏  ROUGH PAD")
        self._side_scratchpad.installEventFilter(self)
        self._side_scratchpad.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self._side_scratchpad, 1)

        # Assemble split: 70 / 30
        split_layout.addWidget(left, 7)
        split_layout.addWidget(self._right_panel, 3)

        L.addWidget(split, 1)
        return p

    def _handle_drawn_image(self, img):
        print("[MathTrainer] Received image, queueing OCR...")
        self._run_ocr_async(img, source="scratchpad_idle")

    def _run_ocr_async(self, img, source: str = "unknown") -> bool:
        if getattr(self, "_ocr_thread", None) and self._ocr_thread.isRunning():
            print(f"[DEBUG][ocr_async] skip source={source} reason=busy")
            self._sb_status.setText("OCR BUSY")
            return False
        import time
        self._ocr_t0 = time.perf_counter()
        print(f"[DEBUG][ocr_async] queue source={source}")
        self._sb_status.setText("PREDICTING...")
        thread = OcrNumberThread(img, parent=self)
        self._ocr_thread = thread
        thread.result.connect(self._on_ocr_result)
        thread.failed.connect(self._on_ocr_failed)
        thread.finished.connect(lambda t=thread: self._on_ocr_finished(t))
        thread.start()
        return True

    def _on_ocr_result(self, predicted: str):
        import time
        elapsed = (time.perf_counter() - getattr(self, "_ocr_t0", time.perf_counter())) * 1000.0
        print(f"[PROFILE][math_ocr] OCR prediction succeeded in {elapsed:.1f}ms, result: '{predicted}'")
        if predicted:
            self._last_predicted_ocr = str(predicted)
            self._ans_in.setText(predicted)
            self._sb_status.setText("READY")
        else:
            self._sb_status.setText("NO OCR")

    def _clear_main_scratchpad(self):
        if hasattr(self, "_scratchpad") and self._scratchpad:
            self._scratchpad.clear()
            self._scratchpad._clear_on_next_press = False
        self._ans_in.setText("")
        self._ans_in.setStyleSheet(self._ANS_SS)
        self._fb_lbl.setText("")
        self._sb_status.setText("READY")
        self._ans_in.setFocus()

    def _on_clear_clicked(self):
        if hasattr(self, "_scratchpad") and self._scratchpad:
            self._scratchpad.clear()
            self._scratchpad._clear_on_next_press = False
        if hasattr(self, "_side_scratchpad") and self._side_scratchpad:
            self._side_scratchpad.clear()
            self._side_scratchpad._clear_on_next_press = False
        self._ans_in.setText("")
        self._ans_in.setStyleSheet(self._ANS_SS)
        self._fb_lbl.setText("")
        self._sb_status.setText("READY")
        self._ans_in.setFocus()

    def _clear_side_scratchpad(self):
        if hasattr(self, "_side_scratchpad") and self._side_scratchpad:
            self._side_scratchpad.clear()
            self._side_scratchpad._clear_on_next_press = False

    def _on_reveal_clicked(self):
        if getattr(self, "_is_revealed", False):
            self._gen_q()
        else:
            self._reveal()

    def _copy_misread_to_clipboard(self):
        import datetime, os
        
        # 1. Find strokes from active pads or fallback to last completed strokes
        strokes = []
        has_strokes = False
        using_prev_strokes = False
        
        # First check active scratchpad strokes
        for pad in [getattr(self, "_scratchpad", None), getattr(self, "_side_scratchpad", None)]:
            if pad and (pad._strokes or getattr(pad, "_current", None)):
                strokes = [list(s) for s in pad._strokes]
                if getattr(pad, "_current", None) and len(pad._current) >= 1:
                    strokes.append(list(pad._current))
                if strokes:
                    has_strokes = True
                    break

        # If active strokes are empty (e.g. question advanced or cleared), check backup
        if not has_strokes:
            for pad in [getattr(self, "_scratchpad", None), getattr(self, "_side_scratchpad", None)]:
                if pad and getattr(pad, "_last_strokes", None):
                    strokes = [list(s) for s in pad._last_strokes]
                    if strokes:
                        has_strokes = True
                        using_prev_strokes = True
                        break

        # Determine Question, Expected, and Perceived Answer
        # If we fell back to previous strokes AND current question hasn't been attempted yet,
        # fallback to the previous question's context!
        if using_prev_strokes and not getattr(self, "_q_attempted", False) and getattr(self, "_prev_ans", None):
            q_text = getattr(self, "_prev_q_text", self._q_lbl.text() if hasattr(self, "_q_lbl") else "?")
            expected_ans = str(getattr(self, "_prev_ans", "?"))
            perceived_ans = getattr(self, "_prev_predicted_ocr", "") or getattr(self, "_prev_wrong_text", "")
        else:
            q_text = self._q_lbl.text() if hasattr(self, "_q_lbl") else "?"
            expected_ans = str(getattr(self, "_ans", "?"))
            if getattr(self, "_is_revealed", False):
                # If revealed, ans_in holds expected_ans, so look for what OCR actually misread
                perceived_ans = getattr(self, "_last_predicted_ocr", "").strip() or getattr(self, "_last_wrong_text", "").strip()
            else:
                perceived_ans = self._ans_in.text().strip() if hasattr(self, "_ans_in") else ""
                if not perceived_ans:
                    perceived_ans = getattr(self, "_last_predicted_ocr", "").strip()
                if not perceived_ans:
                    perceived_ans = getattr(self, "_last_wrong_text", "").strip()
                if not perceived_ans:
                    perceived_ans = getattr(self, "_last_checked_answer", "").strip()

        # Dimensions
        card_w = 640
        card_h = 420
        pix = QPixmap(card_w, card_h)
        pix.fill(QColor("#07070B"))

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)

        # Header box: #12131A
        hdr_rect = QRect(0, 0, card_w, 110)
        painter.fillRect(hdr_rect, QColor("#12131A"))
        painter.setPen(QPen(QColor("#252836"), 1))
        painter.drawLine(0, 110, card_w, 110)

        # Badge
        badge_rect = QRect(16, 12, 180, 22)
        painter.fillRect(badge_rect, QColor(255, 107, 107, 40))
        painter.setPen(QPen(QColor("#FF6B6B"), 1))
        painter.drawRect(badge_rect)
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(badge_rect, Qt.AlignCenter, "OCR MISREAD REPORT")

        # Timestamp
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        painter.setPen(QPen(QColor("#888E9E")))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRect(card_w - 200, 12, 184, 22), Qt.AlignRight | Qt.AlignVCenter, now_str)

        # Non-overlapping two-row data grid with dynamic font metrics spacing
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        fm = painter.fontMetrics()
        get_w = getattr(fm, "horizontalAdvance", fm.width)
        
        # Row 1: QUESTION (left) and EXPECTED (right)
        painter.setPen(QPen(QColor("#888E9E")))
        painter.drawText(16, 62, "QUESTION:")
        q_w = get_w("QUESTION:")
        painter.setPen(QPen(QColor("#E2E8F0")))
        painter.drawText(16 + q_w + 12, 62, q_text)

        painter.setPen(QPen(QColor("#888E9E")))
        painter.drawText(330, 62, "EXPECTED:")
        exp_w = get_w("EXPECTED:")
        painter.setPen(QPen(QColor("#72FF4F")))
        painter.drawText(330 + exp_w + 12, 62, expected_ans)

        # Row 2: OCR PERCEIVED (wide row, generous spacing)
        painter.setPen(QPen(QColor("#888E9E")))
        painter.drawText(16, 94, "OCR PERCEIVED:")
        ocr_w = get_w("OCR PERCEIVED:")
        painter.setPen(QPen(QColor("#FF6B6B")))
        p_str = perceived_ans if perceived_ans else "(blank / no OCR)"
        painter.drawText(16 + ocr_w + 14, 94, p_str)

        # Drawing Canvas area: (0, 110) to (card_w, card_h)
        # Background grid
        painter.setPen(QPen(QColor(255, 255, 255, 12), 1, Qt.DotLine))
        for x in range(0, card_w, 40):
            painter.drawLine(x, 110, x, card_h)
        for y in range(110, card_h, 40):
            painter.drawLine(0, y, card_w, y)

        # Draw user handwriting
        if has_strokes and strokes:
            all_pts = [p for s in strokes for p in s]
            if all_pts:
                min_x = min(p.x() for p in all_pts)
                max_x = max(p.x() for p in all_pts)
                min_y = min(p.y() for p in all_pts)
                max_y = max(p.y() for p in all_pts)
                bw = max(1.0, max_x - min_x)
                bh = max(1.0, max_y - min_y)

                # Fit inside canvas area (margin 25)
                avail_w = card_w - 50
                avail_h = (card_h - 110) - 50
                fit_scale = min(2.5, min(avail_w / bw, avail_h / bh))

                center_dst_x = 25 + avail_w / 2.0
                center_dst_y = 110 + 25 + avail_h / 2.0

                src_cx = (min_x + max_x) / 2.0
                src_cy = (min_y + max_y) / 2.0

                for stroke in strokes:
                    if len(stroke) == 0:
                        continue
                    pen = QPen(QColor("#72FF4F"), max(2.5, 3.0 * fit_scale), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                    painter.setPen(pen)
                    if len(stroke) == 1:
                        p0 = stroke[0]
                        x0 = center_dst_x + (p0.x() - src_cx) * fit_scale
                        y0 = center_dst_y + (p0.y() - src_cy) * fit_scale
                        r = max(2.0, 2.5 * fit_scale)
                        painter.setBrush(QBrush(QColor("#72FF4F")))
                        painter.drawEllipse(QPointF(x0, y0), r, r)
                        painter.setBrush(Qt.NoBrush)
                    else:
                        for i in range(len(stroke) - 1):
                            p0 = stroke[i]
                            p1 = stroke[i+1]
                            x0 = center_dst_x + (p0.x() - src_cx) * fit_scale
                            y0 = center_dst_y + (p0.y() - src_cy) * fit_scale
                            x1 = center_dst_x + (p1.x() - src_cx) * fit_scale
                            y1 = center_dst_y + (p1.y() - src_cy) * fit_scale
                            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        else:
            painter.setPen(QPen(QColor("#888E9E")))
            painter.setFont(QFont("Segoe UI", 13, QFont.Bold))
            painter.drawText(QRect(0, 110, card_w, card_h - 110), Qt.AlignCenter, "(No ink drawn on scratchpad)")

        # Draw border around entire card
        painter.setPen(QPen(QColor("#FF6B6B"), 2))
        painter.drawRect(0, 0, card_w - 1, card_h - 1)
        painter.end()

        # 1. Copy to clipboard
        QApplication.clipboard().setPixmap(pix)

        # 2. Archive to disk in logs/ocr_misreads/
        try:
            from storage_paths import app_resource_path
            misread_dir = app_resource_path("logs", "ocr_misreads")
            os.makedirs(misread_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(misread_dir, f"misread_{ts}_{expected_ans}_vs_{perceived_ans or 'none'}.png")
            pix.save(file_path, "PNG")
            print(f"[MathTrainer] Saved misread diagnostic snapshot to: {file_path}")
        except Exception as e:
            print(f"[MathTrainer] Could not save misread snapshot to disk: {e}")

        # 3. Misread streak recovery: restore and credit previous streak
        scale = getattr(self, "_font_size", 11) / 11.0
        if hasattr(self, "_current_q_item") and self._current_q_item is not None:
            pre_s = getattr(self, "_pre_error_streak", None)
            if pre_s is not None:
                restored_s = pre_s + 1
            else:
                restored_s = self._item_streaks.get(self._current_q_item, 0) + 1

            self._item_streaks[self._current_q_item] = restored_s
            self._pre_error_streak = None

            target = getattr(self, "_streak_target", 5)
            retired = False
            if target > 0 and restored_s >= target and self._current_q_item in self._all_pool:
                retired = True
                self._mastered_items.add(self._current_q_item)
                self._all_pool.remove(self._current_q_item)
                self._active_deck = [item for item in self._active_deck if item != self._current_q_item]
                self._priority_queue = [e for e in self._priority_queue if e["item"] != self._current_q_item]

            self._update_mastery_ui()

            if retired:
                self._fb_lbl.setText("📸 MISREAD REPORTED • STREAK RESTORED & TARGET RETIRED! 🌟")
                if len(self._all_pool) == 0:
                    QTimer.singleShot(1000, self._show_all_mastered_celebration)
            else:
                if target == 0:
                    self._fb_lbl.setText(f"📸 MISREAD REPORTED • STREAK RESTORED TO {restored_s}! 🌟")
                else:
                    self._fb_lbl.setText(f"📸 MISREAD REPORTED • STREAK RESTORED TO {restored_s}/{target}! 🌟")
        else:
            self._fb_lbl.setText("📸 MISREAD COPIED TO CLIPBOARD! (PASTE WITH CTRL+V)")

        self._fb_lbl.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{int(18*scale)}px;font-weight:bold;"
        )
        self._sb_status.setText("CLIPBOARD READY (CTRL+V)")
        QTimer.singleShot(4000, lambda: self._fb_lbl.setText("") if "MISREAD" in self._fb_lbl.text() else None)

    def _on_ocr_failed(self, error: str):
        import time
        elapsed = (time.perf_counter() - getattr(self, "_ocr_t0", time.perf_counter())) * 1000.0
        print(f"[PROFILE][math_ocr] OCR prediction failed in {elapsed:.1f}ms, error: '{error}'")
        self._sb_status.setText("OCR ERROR")

    def _on_ocr_finished(self, thread):
        if getattr(self, "_ocr_thread", None) is thread:
            self._ocr_thread = None
        thread.deleteLater()

    # ── Page 3 (Report) ───────────────────────────────────────────────────────
    def _build_p3(self):
        p = QWidget()
        p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};border-bottom:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(10)
        self._back_btn_p3 = self._mk_back_btn()
        self._back_btn_p3.setText("◀ MENU")
        self._back_btn_p3.clicked.connect(lambda: self._show(1))
        hl.addWidget(self._back_btn_p3)
        self._p3_title = QLabel("MISSION REPORT")
        self._p3_title.setFont(QFont(self._hf, 11, QFont.Bold))
        self._p3_title.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:2px;"
        )
        hl.addWidget(self._p3_title)
        hl.addStretch()
        L.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(40, 24, 40, 24)
        bl.setAlignment(Qt.AlignCenter)
        bl.setSpacing(14)

        self._rep_trophy = QLabel("🏆")
        self._rep_trophy.setFont(QFont(self._hf, 44))
        self._rep_trophy.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_trophy)

        self._rep_badge = QLabel("SESSION COMPLETE")
        self._rep_badge.setFont(QFont(self._hf, 20, QFont.Bold))
        self._rep_badge.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:1.5px;"
        )
        self._rep_badge.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_badge)

        self._rep_score = QLabel("0 CORRECT")
        self._rep_score.setFont(QFont(self._hf, 32, QFont.Black))
        self._rep_score.setStyleSheet(
            f"color:{self._p.get('C_CYAN', _h(CYAN))};background:transparent;"
        )
        self._rep_score.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_score)

        self._rep_acc = QLabel("ACCURACY: 0%")
        self._rep_acc.setFont(QFont(self._hf, 15, QFont.Bold))
        self._rep_acc.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;"
        )
        self._rep_acc.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_acc)

        self._rep_speed = QLabel("SPEED: 0s / Q")
        self._rep_speed.setFont(QFont(self._hf, 13))
        self._rep_speed.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
        )
        self._rep_speed.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_speed)

        # Motivational Quote Card
        self._quote_card = QFrame()
        self._quote_card.setMaximumWidth(720)
        self._quote_card.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_CARD', _h(CARD))};"
            f"border:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:12px;padding:16px;}}"
        )
        ql = QVBoxLayout(self._quote_card)
        ql.setContentsMargins(24, 16, 24, 16)
        ql.setSpacing(8)

        self._quote_text_lbl = QLabel("")
        self._quote_text_lbl.setWordWrap(True)
        self._quote_text_lbl.setFont(QFont(self._hf, 15, QFont.Normal))
        self._quote_text_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;font-style:italic;line-height:1.4;"
        )
        self._quote_text_lbl.setAlignment(Qt.AlignCenter)
        ql.addWidget(self._quote_text_lbl)

        self._quote_author_lbl = QLabel("")
        self._quote_author_lbl.setFont(QFont(self._hf, 12, QFont.Bold))
        self._quote_author_lbl.setStyleSheet(
            f"color:{self._p.get('C_CYAN', _h(CYAN))};background:transparent;letter-spacing:1px;"
        )
        self._quote_author_lbl.setAlignment(Qt.AlignRight)
        ql.addWidget(self._quote_author_lbl)
        bl.addWidget(self._quote_card)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)
        btn_row.setAlignment(Qt.AlignCenter)

        self._p3_btn_menu = QPushButton("◀ BACK TO MENU")
        self._p3_btn_menu.setFixedHeight(46)
        self._p3_btn_menu.setFixedWidth(180)
        self._p3_btn_menu.setFont(QFont(self._hf, 11, QFont.Bold))
        self._p3_btn_menu.setStyleSheet(
            f"QPushButton{{background:{self._p.get('C_SURFACE', _h(SURFACE))};color:{self._p.get('C_TEXT', _h(TEXT))};"
            f"border:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:6px;letter-spacing:1px;}}"
            f"QPushButton:hover{{border-color:{self._p.get('C_CYAN', _h(CYAN))};color:{self._p.get('C_CYAN', _h(CYAN))};}}"
        )
        self._p3_btn_menu.clicked.connect(lambda: self._show(1))
        btn_row.addWidget(self._p3_btn_menu)

        self._p3_btn_again = QPushButton("PRACTICE AGAIN ↺")
        self._p3_btn_again.setFixedHeight(46)
        self._p3_btn_again.setFixedWidth(200)
        self._p3_btn_again.setFont(QFont(self._hf, 12, QFont.Bold))
        self._p3_btn_again.setStyleSheet(
            f"QPushButton{{background:{self._p.get('C_GREEN', _h(GREEN))};color:#000000;"
            f"border:none;border-radius:6px;font-weight:bold;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:#34d399;}}"
        )
        self._p3_btn_again.clicked.connect(self._start_practice)
        btn_row.addWidget(self._p3_btn_again)

        bl.addLayout(btn_row)

        L.addWidget(body, 1)
        return p

    def _trigger_home_cache_clear(self):
        w = self.parent()
        while w:
            if hasattr(w, "_clear_home_ram_caches"):
                w._clear_home_ram_caches()
                break
            w = w.parent()

    # ── Navigation ────────────────────────────────────────────────────────────
    def _show(self, idx):
        if idx != 2 and getattr(self, "_practice_timer", None):
            self._practice_timer.stop()
            self._practice_timer = None
        self._p0.setVisible(idx == 0)
        self._p1.setVisible(idx == 1)
        self._p2.setVisible(idx == 2)
        self._p3.setVisible(idx == 3)

        # Hide particles and stop animation when not on Home screen (Page 0)
        if hasattr(self, "_particles") and self._particles is not None:
            if idx == 0:
                self._particles.show()
                self._particles.start_anim()
            else:
                self._particles.hide()
                self._particles.stop_anim()

        if idx == 0:
            self._top_mode_lbl.hide()
            self._trigger_home_cache_clear()

    def _select_mode(self, m):
        self._mode = m
        titles = {
            1: "SELECT TABLES (1–45)",
            2: "SELECT SQUARES RANGE",
            3: "SELECT CUBES RANGE",
        }
        self._p1_title.setText(titles[m])
        self._tab_sec.setVisible(m == 1)
        self._rng_sec.setVisible(m != 1)
        if m != 1:
            self._build_ranges(50 if m == 2 else 30)
        self._warn_lbl.setText("")
        self._show(1)

    def _build_ranges(self, max_val):
        for i in reversed(range(self._rng_grid.count())):
            w = self._rng_grid.itemAt(i).widget()
            if w:
                w.deleteLater()
        self._rchk = {}
        mode_key = "squares" if self._mode == 2 else "cubes"
        for idx, s in enumerate(range(1, max_val + 1, 5)):
            e = min(s + 4, max_val)
            key = f"{s}-{e}"
            saved = bool(self._config.get(mode_key, {}).get(key, False))
            self._rchk[key] = saved
            b = self._mk_rcb(key, saved)
            b.toggled.connect(lambda checked, k=key: self._toggle_rng(k, checked))
            self._rng_grid.addWidget(b, idx // 5, idx % 5)

    def _build_pool(self):
        if self._mode == 1:
            if hasattr(self, "_solo_btn") and self._solo_btn.isChecked():
                t = self._solo_combo.currentData()
                return [(t, m) for m in [2, 3, 4, 5, 6, 7, 8, 9]]
            else:
                sel = [k for k, v in self._tchk.items() if v]
                if len(sel) > 1 and 1 in sel:
                    sel = [k for k in sel if k != 1]
                return list(sel) if sel else [1]
        else:
            sel = [k for k, v in self._rchk.items() if v]
            raw_nums = []
            for r in sel:
                s, e = map(int, r.split("-"))
                raw_nums.extend(range(s, e + 1))
            pool = [n for n in raw_nums if n != 1 and n % 10 != 0]
            if not pool:
                pool = raw_nums if raw_nums else [2]
            return pool

    # ── Practice ──────────────────────────────────────────────────────────────
    def _start_practice(self):
        self._warn_lbl.setText("")
        pool = self._build_pool()
        if not pool:
            self._warn_lbl.setText("SELECT AT LEAST ONE TARGET, NINJA!")
            return

        import time
        self._practice_start_wall_time = time.time()
        self._expected_base_pool = list(pool)
        self._all_pool = list(pool)
        self._active_deck = list(pool)
        random.shuffle(self._active_deck)
        self._priority_queue = []
        self._item_streaks = {item: 0 for item in pool}
        self._mastered_items = set()
        self._initial_pool_count = len(pool)
        self._last_q = None
        self._current_q_item = None
        self._q_start_time = 0.0

        labels = {1: "TABLES", 2: "SQUARES", 3: "CUBES"}
        self._mode_badge.setText(f"{labels[self._mode]} MODE")
        self._top_mode_lbl.setText(f"{labels[self._mode]} MODE")
        self._top_mode_lbl.show()
        self._streak = 0
        self._qn = 0
        self._combo_val.setText("0")
        self._combo_val.setStyleSheet(
            f"color:{self._p.get('C_ORANGE', _h(ORANG))};background:transparent;min-width:24px;"
        )
        self._correct_count = 0
        self._wrong_count = 0
        if getattr(self, "_practice_timer", None):
            self._practice_timer.stop()
        if self._selected_timer > 0:
            self._time_left = self._selected_timer * 60
            self._practice_timer = QTimer(self)
            self._practice_timer.timeout.connect(self._tick_timer)
            self._practice_timer.start(1000)
            self._qcount_lbl.setText(
                f"TIME: {self._time_left // 60}:{self._time_left % 60:02d}"
            )
        else:
            self._practice_timer = None
        self._show(2)
        self._update_widget_styles()
        self._gen_q()

    def _tick_timer(self):
        self._time_left -= 1
        self._qcount_lbl.setText(
            f"MISSION {self._qn} | TIME: {self._time_left // 60}:{self._time_left % 60:02d}"
        )
        if self._time_left <= 0:
            if self._practice_timer:
                self._practice_timer.stop()
            self._show_report()

    def _update_mastery_ui(self):
        if not hasattr(self, "_q_mastery_badge") or not hasattr(self, "_q_pool_progress_lbl"):
            return

        streak = 0
        if hasattr(self, "_current_q_item") and hasattr(self, "_item_streaks") and self._current_q_item is not None:
            streak = self._item_streaks.get(self._current_q_item, 0)

        target = getattr(self, "_streak_target", 5)
        scale = getattr(self, "_font_size", 11.0) / 11.0

        if target == 0:
            # ENDLESS mode: cards are never retired
            if streak >= 10:
                color = self._p.get('C_GREEN', _h(GREEN))
            elif streak >= 5:
                color = self._p.get('C_YELLOW', _h(YELLOW))
            elif streak > 0:
                color = self._p.get('C_CYAN', _h(CYAN))
            else:
                color = self._p.get('C_SUBTEXT', _h(SUBTEXT))
            streak_text = f"★ STREAK: {streak} (ENDLESS ∞)"
        else:
            streak_clamped = max(0, min(target, streak))
            filled_dots = "● " * streak_clamped
            empty_dots = "○ " * (target - streak_clamped)
            dots_str = (filled_dots + empty_dots).strip()

            if streak >= target:
                color = self._p.get('C_GREEN', _h(GREEN))
                streak_text = f"★ MASTERED! {target}/{target}  [ {dots_str} ]"
            elif streak >= max(1, target // 2 + 1):
                color = self._p.get('C_YELLOW', _h(YELLOW))
                streak_text = f"★ STREAK: {streak}/{target}  [ {dots_str} ]"
            elif streak > 0:
                color = self._p.get('C_CYAN', _h(CYAN))
                streak_text = f"★ STREAK: {streak}/{target}  [ {dots_str} ]"
            else:
                color = self._p.get('C_SUBTEXT', _h(SUBTEXT))
                streak_text = f"★ STREAK: 0/{target}  [ {dots_str} ]"

        self._q_mastery_badge.setText(streak_text)
        self._q_mastery_badge.setStyleSheet(
            f"color:{color};background:transparent;letter-spacing:1px;font-size:{int(12*scale)}pt;font-weight:bold;"
        )

        total = getattr(self, "_initial_pool_count", 0)
        active_remaining = len(getattr(self, "_all_pool", []))
        mastered_count = len(getattr(self, "_mastered_items", set()))
        if total == 0:
            total = active_remaining + mastered_count

        if target == 0:
            prog_text = f"🎯 ACTIVE TARGETS: {active_remaining} (ENDLESS)"
        elif mastered_count > 0:
            prog_text = f"🎯 REMAINING: {active_remaining}/{total}  ({mastered_count} DONE)"
        else:
            prog_text = f"🎯 REMAINING: {active_remaining}/{total}"
        self._q_pool_progress_lbl.setText(prog_text)
        self._q_pool_progress_lbl.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:0.5px;font-size:{int(11*scale)}pt;font-weight:bold;"
        )

    def _show_report(self):
        total = self._correct_count + self._wrong_count
        acc = int((self._correct_count / total * 100) if total > 0 else 0)
        self._p3_title.setText("MISSION REPORT")
        self._rep_trophy.setText("⏱")
        self._rep_badge.setText("TIME UP!")
        self._rep_score.setText(f"{self._correct_count} CORRECT")
        self._rep_acc.setText(f"ACCURACY: {acc}% ({self._correct_count}/{total} Qs)")
        q_per_min = (
            self._correct_count / self._selected_timer
            if self._selected_timer > 0
            else 0
        )
        self._rep_speed.setText(f"SPEED: {q_per_min:.1f} Q/MIN")
        if acc >= 90:
            self._rep_score.setStyleSheet(
                f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;"
            )
        elif acc >= 70:
            self._rep_score.setStyleSheet(
                f"color:{self._p.get('C_YELLOW', _h(YELLOW))};background:transparent;"
            )
        else:
            self._rep_score.setStyleSheet(
                f"color:{self._p.get('C_RED', _h(RED))};background:transparent;"
            )

        quotes = [
            ("“We are what we repeatedly do. Excellence, then, is not an act, but a habit.”", "Will Durant"),
            ("“Consistency is the DNA of mastery.”", "Robin Sharma"),
            ("“Pure mathematics is, in its way, the poetry of logical ideas.”", "Albert Einstein"),
            ("“Small daily improvements over time lead to stunning results.”", "Robin Sharma"),
        ]
        quote_text, quote_author = random.choice(quotes)
        self._quote_text_lbl.setText(quote_text)
        self._quote_author_lbl.setText(f"— {quote_author}")
        self._show(3)

    def _show_all_mastered_celebration(self):
        if getattr(self, "_practice_timer", None):
            self._practice_timer.stop()
            self._practice_timer = None

        from data_manager import store
        vol = store.get().get("_volume", 40) / 100.0
        self._snd_power.setVolume(vol)
        self._snd_power.play()

        total = self._correct_count + self._wrong_count
        acc = int((self._correct_count / total * 100) if total > 0 else 100)

        import time
        elapsed_sec = max(1.0, time.time() - getattr(self, "_practice_start_wall_time", time.time()))
        q_per_min = self._correct_count / (elapsed_sec / 60.0)

        quotes = [
            ("“We are what we repeatedly do. Excellence, then, is not an act, but a habit.”", "Will Durant"),
            ("“Consistency is the DNA of mastery.”", "Robin Sharma"),
            ("“Pure mathematics is, in its way, the poetry of logical ideas.”", "Albert Einstein"),
            ("“Small daily improvements over time lead to stunning results.”", "Robin Sharma"),
            ("“The only way to learn mathematics is to do mathematics.”", "Paul Halmos"),
            ("“Speed and precision are the natural byproducts of relentless practice.”", "Dojo Wisdom"),
            ("“There are no shortcuts to any place worth going.”", "Beverly Sills"),
            ("“Success is the sum of small efforts, repeated day in and day out.”", "Robert Collier"),
            ("“Discipline is the bridge between goals and accomplishment.”", "Jim Rohn"),
        ]
        quote_text, quote_author = random.choice(quotes)

        self._p3_title.setText("MASTERY CELEBRATION")
        self._rep_trophy.setText("🏆")
        self._rep_badge.setText("ALL TARGETS MASTERED!")
        self._rep_badge.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:2px;font-weight:bold;"
        )
        target = getattr(self, "_streak_target", 5)
        mastered_num = len(getattr(self, "_mastered_items", [])) or getattr(self, "_initial_pool_count", 0)
        self._rep_score.setText(f"{mastered_num} TARGETS RETIRED ({target}/{target} STREAK)")
        self._rep_score.setStyleSheet(
            f"color:{self._p.get('C_CYAN', _h(CYAN))};background:transparent;font-weight:900;"
        )
        self._rep_acc.setText(f"ACCURACY: {acc}%  •  TOTAL ATTEMPTS: {total}")
        self._rep_speed.setText(f"TIME: {int(elapsed_sec // 60)}m {int(elapsed_sec % 60):02d}s  •  SPEED: {q_per_min:.1f} Q/MIN")

        self._quote_text_lbl.setText(quote_text)
        self._quote_author_lbl.setText(f"— {quote_author}")
        self._show(3)

    def _pick_next_item(self):
        expected_pool = self._build_pool()
        if getattr(self, "_expected_base_pool", None) is None or set(self._expected_base_pool) != set(expected_pool):
            self._expected_base_pool = list(expected_pool)
            self._all_pool = list(expected_pool)
            self._active_deck = list(self._all_pool)
            random.shuffle(self._active_deck)
            self._priority_queue = []
            self._item_streaks = {item: 0 for item in expected_pool}
            self._mastered_items = set()
            self._initial_pool_count = len(expected_pool)

        if not self._all_pool:
            return None

        # 1. Check priority queue for items due at or before current mission (self._qn)
        # Prioritize "wrong" (urgent retry) over "slow" (reinforcement)
        # Filter priority queue to only items still in active _all_pool
        self._priority_queue = [e for e in self._priority_queue if e["item"] in self._all_pool]

        due_wrong = [i for i, entry in enumerate(self._priority_queue) 
                     if entry["due_at_qn"] <= self._qn and entry["reason"] == "wrong"]
        due_slow = [i for i, entry in enumerate(self._priority_queue) 
                    if entry["due_at_qn"] <= self._qn and entry["reason"] == "slow"]
        
        due_indices = due_wrong + due_slow
        
        chosen_entry = None
        for idx in due_indices:
            candidate = self._priority_queue[idx]
            cand_item = candidate["item"]
            total_items = len(self._all_pool) + len(self._priority_queue)
            if cand_item != self._last_q or total_items <= 1:
                chosen_entry = self._priority_queue.pop(idx)
                break
            else:
                candidate["due_at_qn"] = self._qn + 1
        
        if chosen_entry is not None:
            return chosen_entry["item"]
        
        # 2. Draw from active deck (guaranteed 100% round-robin coverage)
        self._active_deck = [item for item in self._active_deck if item in self._all_pool]
        if not self._active_deck:
            if not self._all_pool:
                return None
            self._active_deck = list(self._all_pool)
            random.shuffle(self._active_deck)
            if len(self._active_deck) > 1 and self._active_deck[0] == self._last_q:
                swap_idx = random.randint(1, len(self._active_deck) - 1)
                self._active_deck[0], self._active_deck[swap_idx] = self._active_deck[swap_idx], self._active_deck[0]
        
        if not self._active_deck:
            return None

        if len(self._active_deck) > 1 and self._active_deck[0] == self._last_q:
            swap_idx = random.randint(1, len(self._active_deck) - 1)
            self._active_deck[0], self._active_deck[swap_idx] = self._active_deck[swap_idx], self._active_deck[0]
            
        return self._active_deck.pop(0)

    def _gen_q(self):
        # Archive last question context for fallback in misread reports
        if hasattr(self, "_ans"):
            self._prev_q_text = self._q_lbl.text() if hasattr(self, "_q_lbl") else ""
            self._prev_ans = str(self._ans)
            self._prev_predicted_ocr = getattr(self, "_last_predicted_ocr", "")
            self._prev_wrong_text = getattr(self, "_last_wrong_text", "")

        self._last_predicted_ocr = ""
        self._last_wrong_text = ""
        self._last_checked_answer = ""
        self._pre_error_streak = None
        self._is_revealed = False
        if hasattr(self, "_reveal_bar_btn"):
            self._reveal_bar_btn.setText("REVEAL 👁 (Space)")
        # Reset right panel to hint state
        if hasattr(self, "_reveal_scroll"):
            self._reveal_scroll.hide()
        if hasattr(self, "_reveal_card"):
            self._reveal_card.hide()
        if hasattr(self, "_reveal_hint"):
            self._reveal_hint.show()
        self._show_ans_btn.hide()
        self._fb_lbl.setText("")
        self._fb_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:1px;"
        )
        self._ans_in.blockSignals(True)
        self._ans_in.setText("")
        self._ans_in.blockSignals(False)
        self._ans_in.setStyleSheet(self._ANS_SS)
        self._qn += 1
        if getattr(self, "_practice_timer", None):
            self._qcount_lbl.setText(
                f"MISSION {self._qn} | TIME: {self._time_left // 60}:{self._time_left % 60:02d}"
            )
        else:
            self._qcount_lbl.setText(f"MISSION {self._qn}")
        self._sb_status.setText("TRAINING...")
        if hasattr(self, "_scratchpad"):
            self._scratchpad.clear()
        if hasattr(self, "_side_scratchpad"):
            self._side_scratchpad.clear()

        scale = self._font_size / 11.0
        self._q_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:1px;font-size:{int(40*scale)}pt;"
        )

        q_item = self._pick_next_item()
        if q_item is None:
            self._show_all_mastered_celebration()
            return

        if self._mode == 1:
            if isinstance(q_item, tuple):
                n1, n2 = q_item
            else:
                n1 = q_item
                n2 = random.choice([2, 3, 4, 5, 6, 7, 8, 9])
            self._current_q_item = q_item
            self._last_q = q_item
            self._ans = n1 * n2
            self._q_lbl.setText(f"{n1} × {n2} = ?")
        elif self._mode == 2:
            num = q_item
            self._current_q_item = num
            self._last_q = num
            self._ans = num * num
            self._q_lbl.setText(f"{num}² = ?")
        else:
            num = q_item
            self._current_q_item = num
            self._last_q = num
            self._ans = num * num * num
            self._q_lbl.setText(f"{num}³ = ?")

        self._update_mastery_ui()
        self._q_attempted = False
        import time
        self._q_start_time = time.perf_counter()
        QTimer.singleShot(0, self._ans_in.setFocus)

    def _auto_check(self, text):
        digits = "".join(c for c in text if c.isdigit())
        if digits != text:
            self._ans_in.blockSignals(True)
            self._ans_in.setText(digits)
            self._ans_in.blockSignals(False)
            return
        if digits and len(digits) == len(str(self._ans)):
            QTimer.singleShot(300, self._check)

    def _check(self):
        if getattr(self, "_is_revealed", False):
            self._gen_q()
            return
        v = self._ans_in.text()
        if not v or len(v) != len(str(self._ans)):
            return
        self._last_checked_answer = str(v)
        try:
            scale = self._font_size / 11.0
            import time
            elapsed = time.perf_counter() - getattr(self, "_q_start_time", time.perf_counter())
            if int(v) == self._ans:
                if getattr(self, "burst", None) is not None:
                    c = self._ans_in.mapTo(self, self._ans_in.rect().center())
                    self.burst.spawn_burst(c.x(), c.y(), "green", count=25)
                first_try = not getattr(self, "_q_attempted", False)
                if first_try:
                    self._correct_count += 1
                self._streak += 1

                target = getattr(self, "_streak_target", 5)
                cur_item_streak = 0
                if hasattr(self, "_current_q_item") and self._current_q_item is not None:
                    cur_item_streak = self._item_streaks.get(self._current_q_item, 0) + 1
                    self._item_streaks[self._current_q_item] = cur_item_streak
                self._update_mastery_ui()

                from data_manager import store
                vol = store.get().get("_volume", 40) / 100.0
                if (target > 0 and cur_item_streak >= target) or (self._streak > 0 and self._streak % 5 == 0):
                    self._snd_power.setVolume(vol)
                    self._snd_power.play()
                else:
                    self._snd_pick.setVolume(vol)
                    self._snd_pick.play()
                cv = self._streak
                self._combo_val.setText(str(cv))
                color = _h(GREEN if cv >= 10 else (YELLOW if cv >= 5 else ORANG))
                self._combo_val.setStyleSheet(
                    f"color:{color};background:transparent;min-width:24px;"
                )
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_GREEN', _h(GREEN))};font-size:{int(52*scale)}pt;"
                    f"border:{int(2*scale)}px solid {self._p.get('C_GREEN', _h(GREEN))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
                )

                # Check if item reached streak target and retire it (if target > 0)
                retired = False
                if target > 0 and cur_item_streak >= target and hasattr(self, "_current_q_item") and self._current_q_item in self._all_pool:
                    retired = True
                    self._mastered_items.add(self._current_q_item)
                    self._all_pool.remove(self._current_q_item)
                    self._active_deck = [item for item in self._active_deck if item != self._current_q_item]
                    self._priority_queue = [e for e in self._priority_queue if e["item"] != self._current_q_item]
                    self._update_mastery_ui()

                # Feedback & Spaced Repetition logic
                if retired:
                    target_name = f"{self._current_q_item}³" if self._mode == 3 else (f"{self._current_q_item}²" if self._mode == 2 else f"{self._current_q_item}")
                    if len(self._all_pool) == 0:
                        self._fb_lbl.setText(f"🌟 ALL TARGETS MASTERED! ({target}/{target}) 🌟")
                    else:
                        self._fb_lbl.setText(f"🌟 {target_name} RETIRED! ({target}/{target}) 🌟")
                elif first_try and elapsed > 4.0:
                    # Correct, but slow/hesitant (> 4s) -> Re-queue for speed reinforcement!
                    if not any(e["item"] == self._current_q_item for e in self._priority_queue):
                        self._priority_queue.append({
                            "item": self._current_q_item,
                            "due_at_qn": self._qn + random.randint(3, 5),
                            "reason": "slow"
                        })
                    self._fb_lbl.setText(f"CORRECT! ({elapsed:.1f}s - BOOST SPEED)")
                else:
                    msgs = [
                        "COWABUNGA!",
                        "CORRECT!",
                        "LETHAL!",
                        "PERFECT!",
                        "NAILED IT!",
                        "KAME-HA!",
                    ]
                    self._fb_lbl.setText(random.choice(msgs))
                    # If it was in priority queue and answered fast (< 4s), it is mastered/cleared
                    self._priority_queue = [e for e in self._priority_queue if e["item"] != self._current_q_item]

                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{int(20*scale)}px;"
                )
                self._sb_status.setText(f"COMBO x{self._streak}")
                if hasattr(self, "_reveal_scroll"):
                    self._reveal_scroll.hide()
                if hasattr(self, "_reveal_card"):
                    self._reveal_card.hide()
                if hasattr(self, "_reveal_hint"):
                    self._reveal_hint.show()
                self._show_ans_btn.hide()

                if target > 0 and len(self._all_pool) == 0:
                    QTimer.singleShot(750, self._show_all_mastered_celebration)
                else:
                    QTimer.singleShot(650, self._gen_q)
            else:
                if getattr(self, "burst", None) is not None:
                    c = self._ans_in.mapTo(self, self._ans_in.rect().center())
                    self.burst.spawn_burst(c.x(), c.y(), "red", count=20)
                self._shake_widget(self._ans_in)
                from data_manager import store
                vol = store.get().get("_volume", 40) / 100.0
                self._snd_hit.setVolume(vol)
                self._snd_hit.play()
                if not getattr(self, "_q_attempted", False):
                    self._wrong_count += 1
                self._q_attempted = True

                # Soft penalty on wrong attempt: preserve pre-error streak and decrement by 1 instead of wipeout
                if hasattr(self, "_current_q_item") and self._current_q_item is not None:
                    cur_s = self._item_streaks.get(self._current_q_item, 0)
                    self._pre_error_streak = cur_s
                    self._item_streaks[self._current_q_item] = max(0, cur_s - 1)
                self._update_mastery_ui()

                # URGENT RETRY: Re-queue after 1 intervening question (self._qn + 2)
                self._priority_queue = [e for e in self._priority_queue if e["item"] != self._current_q_item]
                self._priority_queue.append({
                    "item": self._current_q_item,
                    "due_at_qn": self._qn + 2,
                    "reason": "wrong"
                })

                self._streak = 0
                self._combo_val.setText("0")
                self._combo_val.setStyleSheet(
                    f"color:{self._p.get('C_ORANGE', _h(ORANG))};background:transparent;min-width:24px;"
                )
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_RED', _h(RED))};font-size:{int(52*scale)}pt;"
                    f"border:{int(2*scale)}px solid {self._p.get('C_RED', _h(RED))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
                )
                self._fb_lbl.setText("WRONG! ADJUST OR REVEAL.")
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_RED', _h(RED))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{int(24*scale)}px;"
                )
                self._sb_status.setText("COMBO BROKEN")
                self._show_ans_btn.show()
                self._last_wrong_text = str(v)
                self._last_stroke_count = len(self._scratchpad._strokes) if hasattr(self, "_scratchpad") and self._scratchpad else 0
                QTimer.singleShot(1000, self._clear_wrong_answer)
        except ValueError:
            pass

    def _clear_wrong_answer(self):
        current_text = self._ans_in.text()
        last_wrong = getattr(self, "_last_wrong_text", None)
        
        strokes_changed = False
        currently_drawing = False
        if hasattr(self, "_scratchpad") and self._scratchpad:
            stroke_count = len(self._scratchpad._strokes)
            last_count = getattr(self, "_last_stroke_count", 0)
            strokes_changed = stroke_count != last_count
            currently_drawing = bool(getattr(self._scratchpad, "_current", None))
            
        if current_text == last_wrong and not strokes_changed and not currently_drawing:
            self._ans_in.setText("")
            self._ans_in.setStyleSheet(self._ANS_SS)
            if hasattr(self, "_scratchpad") and self._scratchpad:
                self._scratchpad._clear_on_next_press = True
            if hasattr(self, "_side_scratchpad") and self._side_scratchpad:
                self._side_scratchpad._clear_on_next_press = True

    def _reveal(self):
        if getattr(self, "_is_revealed", False):
            return
        self._is_revealed = True
        self._show_ans_btn.hide()
        self._reveal_hint.hide()

        # Schedule urgent retry for revealed question (user didn't know it!)
        if hasattr(self, "_current_q_item") and self._current_q_item is not None:
            self._priority_queue = [e for e in self._priority_queue if e["item"] != self._current_q_item]
            self._priority_queue.append({
                "item": self._current_q_item,
                "due_at_qn": self._qn + 2,
                "reason": "wrong"
            })

        if not getattr(self, "_q_attempted", False):
            self._wrong_count += 1
        self._q_attempted = True
        self._streak = 0
        if hasattr(self, "_current_q_item") and self._current_q_item is not None:
            self._item_streaks[self._current_q_item] = 0
        self._update_mastery_ui()
        self._combo_val.setText("0")
        self._combo_val.setStyleSheet(
            f"color:{self._p.get('C_ORANGE', _h(ORANG))};background:transparent;min-width:24px;"
        )

        q = self._q_lbl.text()
        scale = self._font_size / 11.0
        solved_q = q.replace("?", str(self._ans))

        self._q_lbl.setText(solved_q)
        self._q_lbl.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:1px;font-size:{int(42*scale)}pt;"
        )

        self._ans_in.blockSignals(True)
        self._ans_in.setText(str(self._ans))
        self._ans_in.blockSignals(False)
        self._ans_in.setStyleSheet(
            f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_YELLOW', _h(YELLOW))};font-size:{int(52*scale)}pt;"
            f"border:{int(2*scale)}px solid {self._p.get('C_YELLOW', _h(YELLOW))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
        )

        self._fb_lbl.setText("REVEALED • HIT SPACE OR ENTER FOR NEXT")
        self._fb_lbl.setStyleSheet(
            f"color:{self._p.get('C_YELLOW', _h(YELLOW))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{int(16*scale)}px;font-weight:bold;"
        )
        self._sb_status.setText("ANSWER REVEALED")

        if hasattr(self, "_reveal_bar_btn"):
            self._reveal_bar_btn.setText("NEXT ➔ (Space)")

        if hasattr(self, "_reveal_hint"):
            self._reveal_hint.hide()

        if self._mode == 1:
            if hasattr(self, "_reveal_card"):
                self._reveal_card.hide()
            base = int(q.split("×")[0].strip())
            asked = int(q.split("×")[1].split("=")[0].strip())
            lines = [
                ("▶" if i == asked else "·") + f"  {base} × {i:>2}  =  {base*i}"
                for i in range(1, 21)
            ]
            self._reveal_lbl.setText("\n".join(lines))
            self._reveal_lbl.setStyleSheet(
                f"color:{self._p.get('C_BLUE', _h(BLUE))};background:transparent;padding:{int(4*scale)}px;font-size:{int(14*scale)}pt;"
            )
            self._reveal_scroll.show()
        else:
            if hasattr(self, "_reveal_scroll"):
                self._reveal_scroll.hide()
            if hasattr(self, "_reveal_card"):
                self._reveal_card_val.setText(solved_q)
                self._reveal_card_val.setStyleSheet(
                    f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;font-size:{int(18*scale)}pt;font-weight:bold;"
                )
                self._reveal_card.show()
            else:
                self._reveal_lbl.setText(f"ANSWER:\n\n{solved_q}")
                self._reveal_scroll.show()

    def _get_font_size(self):
        win = self.window()
        if win and hasattr(win, "_font_size") and win._font_size is not None:
            return win._font_size
        p = self.parent()
        while p:
            if hasattr(p, "_font_size") and p._font_size is not None:
                return p._font_size
            if hasattr(p, "_font_size_val") and p._font_size_val is not None:
                return p._font_size_val
            p = p.parent()
        return 11

    def update_font_size(self, font_size):
        self._font_size = font_size
        self._update_widget_styles()

    def _update_widget_styles(self):
        scale = self._font_size / 11.0
        
        # 1. Page 0
        if hasattr(self, "_hero_lbl"):
            hero_font_size = int(42 * scale)
            self._hero_lbl.setFont(QFont(self._hf, hero_font_size, QFont.Black))
            self._hero_lbl.setStyleSheet(
                f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:{int(4 * scale)}px;font-size:{hero_font_size}pt;"
            )
        if hasattr(self, "_sub_lbl"):
            sub_font_size = int(12 * scale)
            self._sub_lbl.setFont(QFont(self._hf, sub_font_size))
            self._sub_lbl.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:{int(3 * scale)}px;font-size:{sub_font_size}pt;"
            )
            
        for i, card in enumerate(getattr(self, "_mode_cards", [])):
            card.setFixedSize(int(360 * scale), int(70 * scale))
            c_hex = _h([BLUE, PURPLE, RED][i])
            bg_hex = ["#0A1520", "#120A20", "#200A0A"][i]
            card.setStyleSheet(f"""
                QFrame{{background:{bg_hex};border:{int(1*scale)}px solid {c_hex}55;
                    border-left:{int(3*scale)}px solid {c_hex};border-radius:{int(5*scale)}px;}}
                QFrame:hover{{background:{bg_hex};border-color:{c_hex};
                    border-left:{int(3*scale)}px solid {c_hex};}}
            """)
        for i, ic in enumerate(getattr(self, "_mode_icons", [])):
            ic_font_size = int(24 * scale)
            ic.setFont(QFont(self._hf, ic_font_size, QFont.Black))
            c_hex = _h([BLUE, PURPLE, RED][i])
            ic.setStyleSheet(f"color:{c_hex};background:transparent;min-width:{int(48*scale)}px;font-size:{ic_font_size}pt;")
        for i, nl in enumerate(getattr(self, "_mode_names", [])):
            nl_font_size = int(14 * scale)
            nl.setFont(QFont(self._hf, nl_font_size, QFont.Bold))
            c_hex = _h([BLUE, PURPLE, RED][i])
            nl.setStyleSheet(f"color:{c_hex};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{nl_font_size}pt;")
        for dl in getattr(self, "_mode_descs", []):
            dl_font_size = int(10 * scale)
            dl.setFont(QFont(self._hf, dl_font_size))
            dl.setStyleSheet(f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;font-size:{dl_font_size}pt;")
        for i, arr in enumerate(getattr(self, "_mode_arrows", [])):
            arr_font_size = int(14 * scale)
            arr.setFont(QFont(self._hf, arr_font_size))
            c_hex = _h([BLUE, PURPLE, RED][i])
            arr.setStyleSheet(f"color:{c_hex};background:transparent;font-size:{arr_font_size}pt;")

        # 2. Page 1
        if hasattr(self, "_back_btn_p1"):
            self._back_btn_p1.setFixedSize(int(120 * scale), int(28 * scale))
            self._back_btn_p1.setFont(QFont(self._hf, int(11 * scale)))
            self._back_btn_p1.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    padding:0px !important;background:transparent;border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};
                    color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};border-radius:{int(3*scale)}px;letter-spacing:{int(1*scale)}px;
                }}
                QPushButton:hover{{border-color:{self._p.get('C_GREEN', _h(GREEN))};color:{self._p.get('C_GREEN', _h(GREEN))};}}
            """)
        if hasattr(self, "_p1_title"):
            self._p1_title.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
            self._p1_title.setStyleSheet(
                f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:{int(2 * scale)}px;"
            )
        if hasattr(self, "_lbl_tables_title"):
            self._lbl_tables_title.setFont(QFont(self._hf, int(10 * scale)))
            self._lbl_tables_title.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:{int(1.5 * scale)}px;"
            )
        if hasattr(self, "_solo_btn"):
            self._solo_btn.setMinimumWidth(int(280 * scale))
            self._solo_btn.setFixedHeight(int(36 * scale))
            self._solo_btn.setFont(QFont(self._hf, int(12 * scale), QFont.Bold))
            self._solo_btn.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(12 * scale)}px;
                    font-weight: bold;
                    background:#0D0D16; color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
                }}
                QPushButton:hover{{ border-color:{_h(GREEN)}; color:{_h(GREEN)}; }}
                QPushButton:checked{{ background:rgba(114,255,79,0.12); border-color:{_h(GREEN)}; color:{_h(GREEN)}; }}
            """)
        if hasattr(self, "_solo_combo"):
            self._solo_combo.setFixedSize(int(140 * scale), int(36 * scale))
            self._solo_combo.setFont(QFont("Arial", int(12 * scale), QFont.Bold))
            self._solo_combo.setStyleSheet(f"""
                QComboBox {{
                    font-family: Arial;
                    font-size: {int(12 * scale)}px;
                    font-weight: bold;
                    background: #0D0D16;
                    color: {self._p.get('C_TEXT', _h(TEXT))};
                    border: {int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};
                    border-radius: {int(3*scale)}px;
                    padding: {int(4*scale)}px {int(8*scale)}px;
                }}
                QComboBox::drop-down {{
                    border: none;
                }}
                QComboBox QAbstractItemView {{
                    font-family: Arial;
                    font-size: {int(12 * scale)}px;
                    font-weight: bold;
                    background: #0D0D16;
                    color: {self._p.get('C_TEXT', _h(TEXT))};
                    selection-background-color: {self._p.get('C_BORDER', _h(BORDER))};
                    border: {int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};
                }}
            """)
        if hasattr(self, "_lbl_quick"):
            self._lbl_quick.setFont(QFont(self._hf, int(10 * scale), QFont.Bold))
            self._lbl_quick.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:{int(1 * scale)}px;"
            )
        for b in getattr(self, "_preset_btns", []):
            b.setMinimumWidth(int(80 * scale))
            b.setFixedHeight(int(26 * scale))
            b.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
            b.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    font-weight: bold;
                    background:#0D0D16; color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
                }}
                QPushButton:hover{{ border-color:{_h(BLUE)}; color:white; }}
                QPushButton:pressed{{ background:rgba(79,195,247,0.12); }}
            """)
        if hasattr(self, "_lbl_custom"):
            self._lbl_custom.setFont(QFont(self._hf, int(10 * scale), QFont.Bold))
            self._lbl_custom.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:{int(1 * scale)}px;"
            )
        if hasattr(self, "_range_start"):
            self._range_start.setFixedSize(int(50 * scale), int(26 * scale))
            self._range_start.setFont(QFont(self._hf, int(11 * scale)))
            self._range_start.setStyleSheet(f"""
                QSpinBox {{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    background:#0D0D16; color:white;
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
                    padding-left: {int(4*scale)}px;
                }}
            """)
        if hasattr(self, "_lbl_to"):
            self._lbl_to.setFont(QFont(self._hf, int(10 * scale)))
            self._lbl_to.setStyleSheet(f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;")
        if hasattr(self, "_range_end"):
            self._range_end.setFixedSize(int(50 * scale), int(26 * scale))
            self._range_end.setFont(QFont(self._hf, int(11 * scale)))
            self._range_end.setStyleSheet(f"""
                QSpinBox {{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    background:#0D0D16; color:white;
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
                    padding-left: {int(4*scale)}px;
                }}
            """)
        if hasattr(self, "_apply_btn"):
            self._apply_btn.setMinimumWidth(int(60 * scale))
            self._apply_btn.setFixedHeight(int(26 * scale))
            self._apply_btn.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
            self._apply_btn.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    font-weight: bold;
                    background:#0D0D16; color:{_h(GREEN)};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
                }}
                QPushButton:hover{{ border-color:{_h(GREEN)}; color:white; }}
                QPushButton:pressed{{ background:rgba(114,255,79,0.12); }}
            """)
        if hasattr(self, "_clear_btn"):
            self._clear_btn.setMinimumWidth(int(80 * scale))
            self._clear_btn.setFixedHeight(int(26 * scale))
            self._clear_btn.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
            self._clear_btn.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    font-weight: bold;
                    background:#0D0D16; color:{_h(RED)};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))}; border-radius:{int(3*scale)}px;
                }}
                QPushButton:hover{{ border-color:{_h(RED)}; color:white; }}
                QPushButton:pressed{{ background:rgba(255,68,68,0.12); }}
            """)
        for b in getattr(self, "_tab_btns", {}).values():
            b.setFixedSize(int(54 * scale), int(48 * scale))
            b.setFont(QFont("Arial", int(14 * scale), QFont.Bold))
            b.setStyleSheet(f"""
                QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(14*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
                QPushButton:hover{{border-color:{_h(GREEN)};color:{_h(GREEN)};}}
                QPushButton:checked{{background:rgba(114,255,79,0.12);border-color:{_h(GREEN)};color:{_h(GREEN)};}}
            """)
        if hasattr(self, "_rng_gw"):
            for b in self._rng_gw.findChildren(QPushButton):
                b.setFixedSize(int(102 * scale), int(48 * scale))
                b.setFont(QFont("Arial", int(12 * scale), QFont.Bold))
                b.setStyleSheet(f"""
                    QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(12*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                        border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
                    QPushButton:hover{{border-color:{_h(PURPLE)};color:{_h(PURPLE)};}}
                    QPushButton:checked{{background:rgba(168,108,255,0.12);border-color:{_h(PURPLE)};color:{_h(PURPLE)};}}
                """)
        for b in getattr(self, "_timer_btns", {}).values():
            b.setFixedSize(int(98 * scale), int(42 * scale))
            b.setFont(QFont("Arial", int(11 * scale), QFont.Bold))
            b.setStyleSheet(f"""
                QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(11*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
                QPushButton:hover{{border-color:{_h(PURPLE)};color:{_h(PURPLE)};}}
                QPushButton:checked{{background:rgba(168,108,255,0.12);border-color:{_h(PURPLE)};color:{_h(PURPLE)};}}
            """)
        for b in getattr(self, "_streak_btns", {}).values():
            b.setFixedSize(int(124 * scale), int(42 * scale))
            b.setFont(QFont("Arial", int(11 * scale), QFont.Bold))
            b.setStyleSheet(f"""
                QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:{int(11*scale)}pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                    border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(3*scale)}px;}}
                QPushButton:hover{{border-color:{_h(CYAN)};color:{_h(CYAN)};}}
                QPushButton:checked{{background:rgba(79,195,247,0.12);border-color:{_h(CYAN)};color:{_h(CYAN)};}}
            """)
        if hasattr(self, "_lbl_timer_title"):
            self._lbl_timer_title.setFont(QFont(self._hf, int(7 * scale)))
            self._lbl_timer_title.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:{int(1.5 * scale)}px;"
            )
        if hasattr(self, "_lbl_streak_title"):
            self._lbl_streak_title.setFont(QFont(self._hf, int(7 * scale)))
            self._lbl_streak_title.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:{int(1.5 * scale)}px;"
            )
        if hasattr(self, "_warn_lbl"):
            self._warn_lbl.setFont(QFont(self._hf, int(11 * scale)))
            self._warn_lbl.setStyleSheet(
                f"color:{self._p.get('C_RED', _h(RED))};background:transparent;"
            )
        if hasattr(self, "_start_btn"):
            self._start_btn.setFixedHeight(int(44 * scale))
            self._start_btn.setFont(QFont(self._hf, int(14 * scale), QFont.Black))
            self._start_btn.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(14 * scale)}px;
                    font-weight: 900;
                    background:{self._p.get('C_GREEN', _h(GREEN))};color:#07070B;border:none;
                    border-radius:{int(4*scale)}px;letter-spacing:{int(2*scale)}px;
                }}
                QPushButton:hover{{background:white;}}
                QPushButton:pressed{{background:{self._p.get('C_GREEN', _h(GREEN))};}}
            """)

        # 3. Page 2
        if hasattr(self, "_back_btn_p2"):
            self._back_btn_p2.setFixedSize(int(120 * scale), int(28 * scale))
            self._back_btn_p2.setFont(QFont(self._hf, int(11 * scale)))
            self._back_btn_p2.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    padding:0px !important;background:transparent;border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};
                    color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};border-radius:{int(3*scale)}px;letter-spacing:{int(1*scale)}px;
                }}
                QPushButton:hover{{border-color:{self._p.get('C_GREEN', _h(GREEN))};color:{self._p.get('C_GREEN', _h(GREEN))};}}
            """)
        if hasattr(self, "_mode_badge"):
            c_hex = _h({1: BLUE, 2: PURPLE, 3: RED}[self._mode])
            self._mode_badge.setStyleSheet(
                f"color:{c_hex};background:transparent;"
                f"border:{int(1*scale)}px solid {c_hex};border-radius:{int(3*scale)}px;padding:{int(2*scale)}px {int(8*scale)}px;"
                f"font-family:{self._hf};font-size:{int(7*scale)}px;font-weight:bold;letter-spacing:{int(1*scale)}px;"
            )
        if hasattr(self, "_top_mode_lbl"):
            c_hex = _h({1: BLUE, 2: PURPLE, 3: RED}[self._mode])
            self._top_mode_lbl.setFont(QFont(self._hf, int(8 * scale), QFont.Bold))
            self._top_mode_lbl.setStyleSheet(
                f"background:transparent;color:{c_hex};letter-spacing:{int(1*scale)}px;"
            )
        if hasattr(self, "_qcount_lbl"):
            self._qcount_lbl.setFont(QFont(self._hf, int(7 * scale)))
            self._qcount_lbl.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
            )
        if hasattr(self, "_scan_card"):
            self._scan_card.setFixedHeight(int(150 * scale))
        if hasattr(self, "_q_lbl"):
            q_lbl_font_size = int(42 * scale)
            self._q_lbl.setFont(QFont(self._hf, q_lbl_font_size, QFont.Black))
            if getattr(self, "_is_revealed", False):
                self._q_lbl.setStyleSheet(
                    f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:{int(1 * scale)}px;font-size:{q_lbl_font_size}pt;"
                )
            else:
                self._q_lbl.setStyleSheet(
                    f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:{int(1 * scale)}px;font-size:{q_lbl_font_size}pt;"
                )
        if hasattr(self, "_ans_in"):
            ans_in_font_size = int(52 * scale)
            self._ans_in.setFixedHeight(int(88 * scale))
            self._ans_in.setFont(QFont(self._hf, ans_in_font_size, QFont.Bold))
            self._ANS_SS = (
                f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_TEXT', _h(TEXT))};font-size:{ans_in_font_size}pt;"
                f"border:{int(2*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
                f"QLineEdit:focus{{border:{int(2*scale)}px solid {self._p.get('C_GREEN', _h(GREEN))};}} "
            )
            if not self._fb_lbl.text() or self._fb_lbl.text() == "":
                self._ans_in.setStyleSheet(self._ANS_SS)
            elif "CORRECT" in self._fb_lbl.text() or "COWABUNGA" in self._fb_lbl.text() or "PERFECT" in self._fb_lbl.text() or "KAME-HA" in self._fb_lbl.text() or "LETHAL" in self._fb_lbl.text() or "NAILED" in self._fb_lbl.text():
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_GREEN', _h(GREEN))};font-size:{ans_in_font_size}pt;"
                    f"border:{int(2*scale)}px solid {self._p.get('C_GREEN', _h(GREEN))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
                )
            elif "REVEALED" in self._fb_lbl.text():
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_YELLOW', _h(YELLOW))};font-size:{ans_in_font_size}pt;"
                    f"border:{int(2*scale)}px solid {self._p.get('C_YELLOW', _h(YELLOW))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
                )
            else:
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_RED', _h(RED))};font-size:{ans_in_font_size}pt;"
                    f"border:{int(2*scale)}px solid {self._p.get('C_RED', _h(RED))};border-radius:{int(6*scale)}px;padding:{int(4*scale)}px;}}"
                )
        if hasattr(self, "_fb_lbl"):
            fb_font_size = int(18 * scale)
            self._fb_lbl.setFont(QFont(self._hf, fb_font_size, QFont.Bold))
            self._fb_lbl.setFixedHeight(int(30 * scale))
            if not self._fb_lbl.text() or self._fb_lbl.text() == "":
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{fb_font_size}px;"
                )
            elif "CORRECT" in self._fb_lbl.text() or "COWABUNGA" in self._fb_lbl.text() or "PERFECT" in self._fb_lbl.text() or "KAME-HA" in self._fb_lbl.text() or "LETHAL" in self._fb_lbl.text() or "NAILED" in self._fb_lbl.text():
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{fb_font_size}px;"
                )
            elif "REVEALED" in self._fb_lbl.text():
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_YELLOW', _h(YELLOW))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{int(16*scale)}px;font-weight:bold;"
                )
            else:
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_RED', _h(RED))};background:transparent;letter-spacing:{int(1*scale)}px;font-size:{fb_font_size}px;"
                )
        if hasattr(self, "_scratchpad"):
            self._scratchpad.setMinimumHeight(int(240 * scale))
        if hasattr(self, "_side_scratchpad"):
            self._side_scratchpad.setMinimumHeight(int(150 * scale))
        if hasattr(self, "_side_clear_btn"):
            self._side_clear_btn.setFixedHeight(int(22 * scale))
            self._side_clear_btn.setFont(QFont(self._hf, int(7 * scale), QFont.Bold))
        if hasattr(self, "_reveal_card_val"):
            self._reveal_card_val.setFont(QFont(self._hf, int(18 * scale), QFont.Bold))
        if hasattr(self, "_clear_btn"):
            self._clear_btn.setFixedHeight(int(26 * scale))
            self._clear_btn.setFont(QFont(self._hf, int(8 * scale), QFont.Bold))
        if hasattr(self, "_copy_misread_btn"):
            self._copy_misread_btn.setFixedHeight(int(26 * scale))
            self._copy_misread_btn.setFont(QFont(self._hf, int(8 * scale), QFont.Bold))
        if hasattr(self, "_reveal_bar_btn"):
            self._reveal_bar_btn.setFixedHeight(int(26 * scale))
            self._reveal_bar_btn.setFont(QFont(self._hf, int(8 * scale), QFont.Bold))
        if hasattr(self, "_show_ans_btn"):
            self._show_ans_btn.setFixedHeight(int(40 * scale))
            self._show_ans_btn.setFont(QFont(self._hf, int(10 * scale), QFont.Bold))
            self._show_ans_btn.setStyleSheet(
                f"QPushButton{{font-family: {self._hf}; font-size: {int(10 * scale)}px; font-weight: bold; background:transparent;border:{int(1*scale)}px solid {self._p.get('C_YELLOW', _h(YELLOW))};"
                f"color:{self._p.get('C_YELLOW', _h(YELLOW))};border-radius:{int(3*scale)}px;padding:0 {int(14*scale)}px;letter-spacing:{int(1*scale)}px;}}"
                f"QPushButton:hover{{background:rgba(241,250,140,0.1);}}"
            )
        if hasattr(self, "_reveal_hint"):
            self._reveal_hint.setFont(QFont(self._hf, int(9 * scale)))
            self._reveal_hint.setStyleSheet(
                f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;padding:{int(2*scale)}px 0;"
            )
        if hasattr(self, "_reveal_lbl"):
            self._reveal_lbl.setFont(QFont("Courier New", int(14 * scale)))
            self._reveal_lbl.setStyleSheet(
                f"color:{self._p.get('C_BLUE', _h(BLUE))};background:transparent;padding:{int(4*scale)}px;"
            )

        # 4. Page 3
        if hasattr(self, "_back_btn_p3"):
            self._back_btn_p3.setFixedSize(int(120 * scale), int(28 * scale))
            self._back_btn_p3.setFont(QFont(self._hf, int(11 * scale)))
            self._back_btn_p3.setStyleSheet(f"""
                QPushButton{{
                    font-family: {self._hf};
                    font-size: {int(11 * scale)}px;
                    padding:0px !important;background:transparent;border:{int(1*scale)}px solid {self._p.get('C_BORDER', _h(BORDER))};
                    color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};border-radius:{int(3*scale)}px;letter-spacing:{int(1*scale)}px;
                }}
                QPushButton:hover{{border-color:{self._p.get('C_GREEN', _h(GREEN))};color:{self._p.get('C_GREEN', _h(GREEN))};}}
            """)
        if hasattr(self, "_rep_trophy"):
            self._rep_trophy.setFont(QFont(self._hf, int(44 * scale)))
        if hasattr(self, "_rep_badge"):
            self._rep_badge.setFont(QFont(self._hf, int(20 * scale), QFont.Bold))
        if hasattr(self, "_rep_score"):
            self._rep_score.setFont(QFont(self._hf, int(30 * scale), QFont.Black))
        if hasattr(self, "_rep_acc"):
            self._rep_acc.setFont(QFont(self._hf, int(15 * scale), QFont.Bold))
        if hasattr(self, "_rep_speed"):
            self._rep_speed.setFont(QFont(self._hf, int(13 * scale)))
        if hasattr(self, "_quote_text_lbl"):
            self._quote_text_lbl.setFont(QFont(self._hf, int(15 * scale)))
        if hasattr(self, "_quote_author_lbl"):
            self._quote_author_lbl.setFont(QFont(self._hf, int(12 * scale), QFont.Bold))
        if hasattr(self, "_p3_btn_menu"):
            self._p3_btn_menu.setFixedHeight(int(46 * scale))
            self._p3_btn_menu.setFixedWidth(int(180 * scale))
            self._p3_btn_menu.setFont(QFont(self._hf, int(11 * scale), QFont.Bold))
        if hasattr(self, "_p3_btn_again"):
            self._p3_btn_again.setFixedHeight(int(46 * scale))
            self._p3_btn_again.setFixedWidth(int(200 * scale))
            self._p3_btn_again.setFont(QFont(self._hf, int(12 * scale), QFont.Bold))
        if hasattr(self, "_q_mastery_badge") and hasattr(self, "_q_pool_progress_lbl"):
            self._update_mastery_ui()
