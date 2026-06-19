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

CONFIG_FILE = os.path.join(os.path.expanduser("~"), "math_trainer_config.json")

# ── Colours ───────────────────────────────────────────────────────────────────
BG = QColor("#07070B")
SURFACE = QColor("#0F0F17")
CARD = QColor("#0D0D16")
BORDER = QColor("#1A1A26")
GREEN = QColor("#72FF4F")
PURPLE = QColor("#A86CFF")
BLUE = QColor("#4FC3F7")
RED = QColor("#FF5555")
YELLOW = QColor("#F1FA8C")
TEXT = QColor("#E0E0FF")
SUBTEXT = QColor("#A6ADC8")
ORANG = QColor("#FF4444")


def _h(c):
    return c.name()


# ── Scratchpad Canvas ──────────────────────────────────────────────────────────
class MathScratchpad(QWidget):
    drawing_finished = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self._strokes = []
        self._current = []
        self._backing_store = None
        self._pen_color = GREEN
        self._pen_width = 4.5

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(800)
        self._idle_timer.timeout.connect(self._trigger_ocr)

    def _init_backing_store(self):
        w, h = max(10, self.width()), max(10, self.height())
        if self._backing_store is None or self._backing_store.width() != w or self._backing_store.height() != h:
            old = self._backing_store
            self._backing_store = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            self._backing_store.fill(Qt.transparent)
            if old and not old.isNull():
                p = QPainter(self._backing_store)
                p.drawImage(0, 0, old)
                p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._init_backing_store()

    def clear(self):
        self._strokes = []
        self._current = []
        if self._backing_store:
            self._backing_store.fill(Qt.transparent)
        self.update()

    def _redraw_backing_store(self):
        if self._backing_store is None or self._backing_store.isNull():
            self._init_backing_store()
        self._backing_store.fill(Qt.transparent)
        
        p = QPainter(self._backing_store)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(
            QPen(
                self._pen_color,
                self._pen_width,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        
        from ui.canvas.geometry import smooth_points_to_path
        
        for stroke in self._strokes:
            if len(stroke) >= 2:
                path = smooth_points_to_path(stroke, scale=1.0)
                p.drawPath(path)
                
        if len(self._current) >= 2:
            path = smooth_points_to_path(self._current, scale=1.0)
            p.drawPath(path)
            
        p.end()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(0, 0, 0, 210)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(GREEN, 2))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        p.setFont(QFont("Arial", 9))
        label_col = QColor(GREEN)
        label_col.setAlphaF(0.7)
        p.setPen(QPen(label_col))
        p.drawText(12, 22, "✏  DRAW HERE")
        if self._backing_store and not self._backing_store.isNull():
            p.drawImage(0, 0, self._backing_store)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._idle_timer.stop()
            self._current = [e.localPos()]
            self.update()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._idle_timer.stop()
            self._current.append(e.localPos())
            if len(self._current) >= 2:
                self._redraw_backing_store()
                self.update()
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if len(self._current) >= 2:
                self._strokes.append(list(self._current))
            self._current = []
            self._redraw_backing_store()
            self._idle_timer.start()
            self.update()
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def _trigger_ocr(self):
        if not self._strokes:
            return
        from PIL import Image, ImageDraw as PilDraw

        img = Image.new("RGB", (self.width(), self.height()), "white")
        draw = PilDraw.Draw(img)
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            pts = [(p.x(), p.y()) for p in stroke]
            draw.line(pts, fill="black", width=18, joint="curve")
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
        self._timer.start(30)
        self._init_pts()

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
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(20)

    def _tick(self):
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
        self._build()
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
        self._config = {"tables": {}, "squares": {}, "cubes": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    self._config = json.load(f)
            except:
                pass

    def _save_config(self):
        self._config["tables"] = {str(k): int(v) for k, v in self._tchk.items()}
        if self._rchk:
            key = "squares" if self._mode == 2 else "cubes"
            self._config[key] = {str(k): int(v) for k, v in self._rchk.items()}
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

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.go_back()
            e.accept()
            return
        elif e.key() == Qt.Key_QuoteLeft:
            self._toggle_pen()
            e.accept()
            return
        elif e.key() == Qt.Key_Space:
            self._reveal()
            e.accept()
            return
        super().keyPressEvent(e)

    def eventFilter(self, obj, e):
        if hasattr(self, "_ans_in") and obj == self._ans_in and e.type() == QEvent.KeyPress:
            if e.key() == Qt.Key_Space:
                self._reveal()
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

        hero = QLabel("MATH DOJO")
        hero.setFont(QFont(self._hf, 42, QFont.Black))
        hero.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:4px;font-size:42pt;"
        )
        hero.setAlignment(Qt.AlignCenter)
        L.addWidget(hero)

        sub = QLabel("— CHOOSE YOUR DISCIPLINE —")
        sub.setFont(QFont(self._hf, 12))
        sub.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:3px;font-size:12pt;"
        )
        sub.setAlignment(Qt.AlignCenter)
        L.addWidget(sub)
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
        back = self._mk_back_btn()
        back.clicked.connect(lambda: self._show(0))
        hl.addWidget(back)
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
        lbl1 = QLabel("— SELECT TABLES (1–45) —")
        lbl1.setFont(QFont(self._hf, 7))
        lbl1.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1.5px;"
        )
        tsl.addWidget(lbl1)
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
            b.clicked.connect(lambda _, n=i: self._toggle_tab(n))
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
        lbl2 = QLabel("— SELECT TIMER —")
        lbl2.setFont(QFont(self._hf, 7))
        lbl2.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;letter-spacing:1.5px;"
        )
        tmsl.addWidget(lbl2)
        tm_gw = QWidget()
        tm_gw.setStyleSheet(
            f"background:{self._p.get('C_SURFACE', _h(SURFACE))};border-radius:4px;"
        )
        tm_grid = QHBoxLayout(tm_gw)
        tm_grid.setContentsMargins(8, 8, 8, 8)
        tm_grid.setSpacing(6)
        self._timer_btns = {}
        for mins, txt in [(0, "NONE"), (1, "1 MIN"), (3, "3 MIN"), (5, "5 MIN")]:
            b = self._mk_rcb(txt, mins == 0)
            b.clicked.connect(lambda _, m=mins: self._set_timer_val(m))
            self._timer_btns[mins] = b
            tm_grid.addWidget(b)
        tmsl.addWidget(tm_gw)
        bl.addWidget(self._tmr_sec)

        self._warn_lbl = QLabel("")
        self._warn_lbl.setFont(QFont(self._hf, 8))
        self._warn_lbl.setStyleSheet(
            f"color:{self._p.get('C_RED', _h(RED))};background:transparent;"
        )
        bl.addWidget(self._warn_lbl)

        start = QPushButton("▶  START MISSION")
        start.setFixedHeight(44)
        start.setFont(QFont(self._hf, 10, QFont.Black))
        start.setStyleSheet(f"""
            QPushButton{{background:{self._p.get('C_GREEN', _h(GREEN))};color:#07070B;border:none;
                border-radius:4px;letter-spacing:2px;}}
            QPushButton:hover{{background:white;}}
            QPushButton:pressed{{background:{self._p.get('C_GREEN', _h(GREEN))};}}
        """)
        start.clicked.connect(self._start_practice)
        bl.addWidget(start)
        bl.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        L.addWidget(scroll, 1)
        return p

    def _mk_back_btn(self):
        b = QPushButton("◀ BACK")
        b.setFixedSize(120, 28)
        b.setFont(QFont(self._hf, 7))
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;background:transparent;border:1px solid {self._p.get('C_BORDER', _h(BORDER))};
                color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};border-radius:3px;letter-spacing:1px;}}
            QPushButton:hover{{border-color:{self._p.get('C_GREEN', _h(GREEN))};color:{self._p.get('C_GREEN', _h(GREEN))};}}
        """)
        return b

    def _mk_cb(self, text, checked, color):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setFixedSize(54, 48)
        b.setFont(QFont("Arial", 14, QFont.Bold))
        c_hex = _h(color)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:14pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:3px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(114,255,79,0.12);border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _mk_rcb(self, text, checked):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setFixedSize(102, 48)
        b.setFont(QFont("Arial", 12, QFont.Bold))
        c_hex = _h(PURPLE)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:12pt;background:#0D0D16;color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};
                border:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:3px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(168,108,255,0.12);border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _toggle_tab(self, n):
        self._tchk[n] = self._tab_btns[n].isChecked()
        self._save_config()

    def _toggle_rng(self, key, btn):
        self._rchk[key] = btn.isChecked()
        self._save_config()

    def _set_timer_val(self, m):
        self._selected_timer = m
        for k, b in self._timer_btns.items():
            b.setChecked(k == m)

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
        back2 = self._mk_back_btn()
        back2.clicked.connect(lambda: self._show(1))
        hl.addWidget(back2)
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

        # ── LEFT PANEL (60%) — question + answer + scratchpad ─────────────
        left = QWidget()
        left.setStyleSheet("background:transparent;")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(24, 16, 12, 16)
        left_layout.setSpacing(10)

        # Giant question display
        self._scan_card = ScanCard()
        self._scan_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._scan_card.setFixedHeight(200)
        inner = QVBoxLayout(self._scan_card)
        inner.setContentsMargins(10, 4, 10, 4)
        self._q_lbl = QLabel("?")
        self._q_lbl.setFont(QFont(self._hf, 96, QFont.Black))  # BIG font
        self._q_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:4px;font-size:96pt;"
        )
        self._q_lbl.setAlignment(Qt.AlignCenter)
        inner.addWidget(self._q_lbl)
        left_layout.addWidget(self._scan_card)

        # Answer input — large
        self._ans_in = QLineEdit()
        self._ans_in.installEventFilter(self)
        self._ans_in.setPlaceholderText("?")
        self._ans_in.setAlignment(Qt.AlignCenter)
        self._ans_in.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._ans_in.setFixedHeight(120)
        self._ans_in.setFont(QFont(self._hf, 72, QFont.Bold))
        self._ANS_SS = (
            f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_TEXT', _h(TEXT))};font-size:72pt;"
            f"border:2px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:6px;padding:6px;}}"
            f"QLineEdit:focus{{border:2px solid {self._p.get('C_GREEN', _h(GREEN))};}} "
        )
        self._ans_in.setStyleSheet(self._ANS_SS)
        self._ans_in.textChanged.connect(self._auto_check)
        self._ans_in.returnPressed.connect(self._check)
        left_layout.addWidget(self._ans_in)

        # Feedback label
        self._fb_lbl = QLabel("")
        self._fb_lbl.setFont(QFont(self._hf, 28, QFont.Bold))
        self._fb_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:1px;"
        )
        self._fb_lbl.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self._fb_lbl)

        # Scratchpad — fills remaining space
        self._scratchpad = MathScratchpad(self)
        self._scratchpad.drawing_finished.connect(self._handle_drawn_image)
        self._scratchpad.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self._scratchpad, 1)

        # Reveal button (shown on wrong answer)
        self._show_ans_btn = QPushButton("REVEAL ANSWER 👁")
        self._show_ans_btn.setFixedHeight(44)
        self._show_ans_btn.setFont(QFont(self._hf, 11, QFont.Bold))
        self._show_ans_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {self._p.get('C_YELLOW', _h(YELLOW))};"
            f"color:{self._p.get('C_YELLOW', _h(YELLOW))};border-radius:3px;padding:0 14px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(241,250,140,0.1);}}"
        )
        self._show_ans_btn.hide()
        self._show_ans_btn.clicked.connect(self._reveal)
        left_layout.addWidget(self._show_ans_btn)

        # ── RIGHT PANEL (40%) — reveal / reference ────────────────────────
        self._right_panel = QFrame()
        self._right_panel.setStyleSheet(
            f"QFrame{{background:{self._p.get('C_SURFACE', _h(SURFACE))};"
            f"border-left:1px solid {self._p.get('C_BORDER', _h(BORDER))};border-radius:0;}}"
        )
        self._right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(12, 16, 16, 16)
        right_layout.setSpacing(8)

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

        # Hint when nothing revealed yet
        self._reveal_hint = QLabel(
            "Draw your answer\nor type it in.\n\nWrong answer?\nHit REVEAL to see\nthe full table here."
        )
        self._reveal_hint.setFont(QFont(self._hf, 13))
        self._reveal_hint.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
        )
        self._reveal_hint.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self._reveal_hint, 1)

        # Reveal content scroll
        self._reveal_scroll = QScrollArea()
        self._reveal_scroll.setStyleSheet(
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QScrollBar:vertical{{background:{self._p.get('C_CARD', _h(CARD))};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{self._p.get('C_BORDER', _h(BORDER))};border-radius:3px;}}"
        )
        self._reveal_lbl = QLabel("")
        self._reveal_lbl.setFont(QFont("Courier New", 16))
        self._reveal_lbl.setStyleSheet(
            f"color:{self._p.get('C_BLUE', _h(BLUE))};background:transparent;padding:4px;"
        )
        self._reveal_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._reveal_scroll.setWidget(self._reveal_lbl)
        self._reveal_scroll.setWidgetResizable(True)
        self._reveal_scroll.hide()
        right_layout.addWidget(self._reveal_scroll, 1)

        # Assemble split: 60 / 40
        split_layout.addWidget(left, 6)
        split_layout.addWidget(self._right_panel, 4)

        L.addWidget(split, 1)
        return p

    def _handle_drawn_image(self, img):
        print("[MathTrainer] Received image, queueing OCR...")
        import inspect

        print(
            f"[MathTrainer] OcrNumberThread loaded from: {inspect.getsourcefile(OcrNumberThread)}"
        )
        if self._run_ocr_async(img, source="scratchpad_idle"):
            self._scratchpad.clear()

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
            self._ans_in.setText(predicted)
            self._sb_status.setText("READY")
        else:
            self._sb_status.setText("NO OCR")

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
        back2 = self._mk_back_btn()
        back2.setText("◀ HOME")
        back2.clicked.connect(lambda: self._show(0))
        hl.addWidget(back2)
        title = QLabel("MISSION REPORT")
        title.setFont(QFont(self._hf, 11, QFont.Bold))
        title.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:2px;"
        )
        hl.addWidget(title)
        hl.addStretch()
        L.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(40, 40, 40, 40)
        bl.setAlignment(Qt.AlignCenter)
        bl.setSpacing(20)

        self._rep_score = QLabel("0 CORRECT")
        self._rep_score.setFont(QFont(self._hf, 36, QFont.Black))
        self._rep_score.setStyleSheet(
            f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;"
        )
        self._rep_score.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_score)

        self._rep_acc = QLabel("ACCURACY: 0%")
        self._rep_acc.setFont(QFont(self._hf, 16, QFont.Bold))
        self._rep_acc.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;"
        )
        self._rep_acc.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_acc)

        self._rep_speed = QLabel("SPEED: 0s / Q")
        self._rep_speed.setFont(QFont(self._hf, 12))
        self._rep_speed.setStyleSheet(
            f"color:{self._p.get('C_SUBTEXT', _h(SUBTEXT))};background:transparent;"
        )
        self._rep_speed.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._rep_speed)

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
            b.clicked.connect(lambda _, k=key, btn=b: self._toggle_rng(k, btn))
            self._rng_grid.addWidget(b, idx // 5, idx % 5)

    # ── Practice ──────────────────────────────────────────────────────────────
    def _start_practice(self):
        self._warn_lbl.setText("")
        sel = [
            k for k, v in (self._tchk if self._mode == 1 else self._rchk).items() if v
        ]
        if not sel:
            self._warn_lbl.setText("SELECT AT LEAST ONE TARGET, NINJA!")
            return
        labels = {1: "TABLES", 2: "SQUARES", 3: "CUBES"}
        colors = {1: BLUE, 2: PURPLE, 3: RED}
        c = colors[self._mode]
        c_hex = _h(c)
        self._mode_badge.setText(f"{labels[self._mode]} MODE")
        self._mode_badge.setStyleSheet(
            f"color:{c_hex};background:transparent;"
            f"border:1px solid {c_hex};border-radius:3px;padding:2px 8px;"
            f"font-family:self._hf;font-size:7px;font-weight:bold;letter-spacing:1px;"
        )
        self._top_mode_lbl.setText(f"{labels[self._mode]} MODE")
        self._top_mode_lbl.setStyleSheet(
            f"color:{c_hex};background:transparent;letter-spacing:1px;"
        )
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

    def _show_report(self):
        total = self._correct_count + self._wrong_count
        acc = int((self._correct_count / total * 100) if total > 0 else 0)
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
        self._show(3)

    def _gen_q(self):
        # Reset right panel to hint state
        self._reveal_scroll.hide()
        self._reveal_hint.show()
        self._show_ans_btn.hide()
        self._fb_lbl.setText("")
        self._fb_lbl.setStyleSheet(
            f"color:{self._p.get('C_TEXT', _h(TEXT))};background:transparent;letter-spacing:1px;"
        )
        self._ans_in.setText("")
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

        if self._mode == 1:
            sel = [k for k, v in self._tchk.items() if v]
            while True:
                n1 = random.choice(sel)
                n2 = random.choice([2, 3, 4, 5, 6, 7, 8, 9])
                q_key = (n1, n2)
                if self._last_q != q_key or len(sel) == 1:
                    self._last_q = q_key
                    break
            self._ans = n1 * n2
            self._q_lbl.setText(f"{n1} × {n2} = ?")
        else:
            sel = [k for k, v in self._rchk.items() if v]
            while True:
                r = random.choice(sel)
                s, e = map(int, r.split("-"))
                num = random.randint(s, e)
                q_key = num
                if self._last_q != q_key or (len(sel) == 1 and s == e):
                    self._last_q = q_key
                    break
            if self._mode == 2:
                self._ans = num * num
                self._q_lbl.setText(f"{num}² = ?")
            else:
                self._ans = num * num * num
                self._q_lbl.setText(f"{num}³ = ?")

        self._q_attempted = False
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
        v = self._ans_in.text()
        if not v or len(v) != len(str(self._ans)):
            return
        try:
            if int(v) == self._ans:
                if getattr(self, "burst", None) is not None:
                    c = self._ans_in.mapTo(self, self._ans_in.rect().center())
                    self.burst.spawn_burst(c.x(), c.y(), "green", count=25)
                if not getattr(self, "_q_attempted", False):
                    self._correct_count += 1
                self._streak += 1
                from data_manager import store
                vol = store.get().get("_volume", 40) / 100.0
                if self._streak > 0 and self._streak % 5 == 0:
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
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_GREEN', _h(GREEN))};font-size:72pt;"
                    f"border:2px solid {self._p.get('C_GREEN', _h(GREEN))};border-radius:6px;padding:6px;}}"
                )
                msgs = [
                    "COWABUNGA!",
                    "CORRECT!",
                    "LETHAL!",
                    "PERFECT!",
                    "NAILED IT!",
                    "KAME-HA!",
                ]
                self._fb_lbl.setText(random.choice(msgs))
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;letter-spacing:1px;"
                )
                self._sb_status.setText(f"COMBO x{self._streak}")
                self._reveal_scroll.hide()
                self._reveal_hint.show()
                self._show_ans_btn.hide()
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
                self._streak = 0
                self._combo_val.setText("0")
                self._combo_val.setStyleSheet(
                    f"color:{self._p.get('C_ORANGE', _h(ORANG))};background:transparent;min-width:24px;"
                )
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{self._p.get('C_CARD', _h(CARD))};color:{self._p.get('C_RED', _h(RED))};font-size:72pt;"
                    f"border:2px solid {self._p.get('C_RED', _h(RED))};border-radius:6px;padding:6px;}}"
                )
                self._fb_lbl.setText("WRONG! ADJUST OR REVEAL.")
                self._fb_lbl.setStyleSheet(
                    f"color:{self._p.get('C_RED', _h(RED))};background:transparent;letter-spacing:1px;"
                )
                self._sb_status.setText("COMBO BROKEN")
                self._show_ans_btn.show()
        except ValueError:
            pass

    def _reveal(self):
        self._show_ans_btn.hide()
        self._reveal_hint.hide()
        q = self._q_lbl.text()
        if self._mode == 1:
            base = int(q.split("×")[0].strip())
            asked = int(q.split("×")[1].split("=")[0].strip())
            lines = [
                ("▶" if i == asked else "·") + f"  {base} × {i:>2}  =  {base*i}"
                for i in range(1, 21)
            ]
            self._reveal_lbl.setText("\n".join(lines))
        else:
            self._reveal_lbl.setText(f"ANSWER:\n\n{q.replace('?', str(self._ans))}")
            self._reveal_lbl.setStyleSheet(
                f"color:{self._p.get('C_GREEN', _h(GREEN))};background:transparent;padding:4px;font-size:22pt;"
            )
        self._reveal_scroll.show()
