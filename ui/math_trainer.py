"""
Math Trainer — Ninja Dojo Edition
Native PyQt5 page for Anki Occlusion.
Matches the Ninja theme: Orbitron font, #07070B bg, #72FF4F green, particle canvas.
"""
import random, json, os, threading, math
import ui.home_screen

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QScrollArea, QLineEdit, QGridLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QThread, pyqtSlot
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFont, QBrush,
    QPainterPath, QLinearGradient, QPolygonF
)

try:
    import speech_recognition as sr
    _VOICE = True
except ImportError:
    _VOICE = False

CONFIG_FILE = os.path.join(os.path.expanduser("~"), "math_trainer_config.json")

# ── Colours ───────────────────────────────────────────────────────────────────
BG      = QColor("#07070B")
SURFACE = QColor("#0F0F17")
CARD    = QColor("#0D0D16")
BORDER  = QColor("#1A1A26")
GREEN   = QColor("#72FF4F")
PURPLE  = QColor("#A86CFF")
BLUE    = QColor("#4FC3F7")
RED     = QColor("#FF5555")
YELLOW  = QColor("#F1FA8C")
TEXT    = QColor("#E0E0FF")
SUBTEXT = QColor("#A6ADC8")
ORANG   = QColor("#FF4444")

def _h(c): return c.name()


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
            self._pts.append({
                'x': random.uniform(0, w), 'y': random.uniform(0, h),
                'vx': random.uniform(-0.25, 0.25), 'vy': random.uniform(-0.25, 0.25),
                'r': random.uniform(1, 2.5), 'c': c
            })

    def resizeEvent(self, e):
        self._init_pts()
        super().resizeEvent(e)

    def _tick(self):
        w, h = self.width(), self.height()
        for p in self._pts:
            p['x'] += p['vx']; p['y'] += p['vy']
            if p['x'] < 0 or p['x'] > w: p['vx'] *= -1
            if p['y'] < 0 or p['y'] > h: p['vy'] *= -1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pts = self._pts
        for i, a in enumerate(pts):
            col = QColor(a['c']); col.setAlphaF(0.45)
            p.setBrush(QBrush(col)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(a['x'], a['y']), a['r'], a['r'])
            for b in pts[i+1:]:
                dx, dy = a['x']-b['x'], a['y']-b['y']
                dist = math.sqrt(dx*dx + dy*dy)
                if dist < 130:
                    lc = QColor(a['c']); lc.setAlphaF(0.07*(1-dist/130))
                    p.setPen(QPen(lc, 0.5))
                    p.drawLine(QPointF(a['x'], a['y']), QPointF(b['x'], b['y']))
        p.end()


# ── Hex Logo ──────────────────────────────────────────────────────────────────
class HexLogo(QWidget):
    def __init__(self, size=34, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        t = QTimer(self); t.timeout.connect(self._spin); t.start(50)

    def _spin(self):
        self._angle = (self._angle + 1) % 360
        self.update()

    def _hex(self, cx, cy, r, offset):
        pts = []
        for i in range(6):
            a = math.radians(60*i + offset - 90)
            pts.append(QPointF(cx + r*math.cos(a), cy + r*math.sin(a)))
        return QPolygonF(pts)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width()/2, self.height()/2
        r = self.width()/2 - 2
        p.setPen(QPen(GREEN, 1.5)); p.setBrush(Qt.NoBrush)
        p.drawPolygon(self._hex(cx, cy, r, 0))
        p.save(); p.translate(cx, cy); p.rotate(self._angle)
        dc = QColor(GREEN); dc.setAlphaF(0.3)
        pen2 = QPen(dc, 0.5); pen2.setStyle(Qt.DashLine)
        p.setPen(pen2); p.drawPolygon(self._hex(0, 0, r, 0))
        p.restore()
        p.setPen(QPen(GREEN))
        p.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY, 13, QFont.Bold))
        p.drawText(self.rect(), Qt.AlignCenter, "∑")
        p.end()


# ── Scan Card (animated top line) ────────────────────────────────────────────
class ScanCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(110)
        self._scan = 0.1; self._dir = 1
        t = QTimer(self); t.timeout.connect(self._tick); t.start(20)

    def _tick(self):
        self._scan += self._dir * 0.012
        if self._scan > 0.9: self._dir = -1
        if self._scan < 0.1: self._dir = 1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setBrush(QBrush(CARD)); p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(r, 6, 6)
        x = self.width() * self._scan
        span = self.width() * 0.35
        grad = QLinearGradient(max(0, x-span), 0, min(self.width(), x+span), 0)
        grad.setColorAt(0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.5, GREEN)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(QPen(QBrush(grad), 2))
        p.drawLine(int(max(0, x-span)), 0, int(min(self.width(), x+span)), 0)
        p.end()


# ── Voice Thread ──────────────────────────────────────────────────────────────
class VoiceThread(QThread):
    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def run(self):
        if not _VOICE:
            self.error.emit("pip install speechrecognition"); return
        r = sr.Recognizer()
        try:
            with sr.Microphone() as src:
                r.adjust_for_ambient_noise(src, duration=0.5)
                audio = r.listen(src, timeout=4, phrase_time_limit=4)
                text = r.recognize_google(audio, language="hi-IN").lower()
                wmap = {"to":"2","too":"2","two":"2","do":"2","three":"3","tree":"3",
                        "four":"4","for":"4","ate":"8","eight":"8","one":"1","won":"1",
                        "teen":"3","char":"4","paanch":"5","five":"5","chhe":"6","six":"6",
                        "saat":"7","seven":"7","aath":"8","nau":"9","nine":"9","ek":"1"}
                digits = "".join(filter(str.isdigit,
                    "".join(wmap.get(w, w) for w in text.split())))
                if digits: self.result.emit(digits)
                else: self.error.emit(f"Heard '{text}' — no numbers")
        except Exception as ex:
            self.error.emit(str(ex))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN PAGE WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class MathTrainerPage(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QWidget{{background:{_h(BG)};color:{_h(TEXT)};}}")
        self._mode = 1; self._ans = 0; self._streak = 0; self._qn = 0
        self._tchk = {}; self._rchk = {}
        self._voice_thread = None; self._config = {}
        self._load_config(); self._build(); self._show(0)

    # ── Config ────────────────────────────────────────────────────────────────
    def _load_config(self):
        self._config = {"tables":{}, "squares":{}, "cubes":{}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f: self._config = json.load(f)
            except: pass

    def _save_config(self):
        self._config["tables"] = {str(k): int(v) for k,v in self._tchk.items()}
        if self._rchk:
            key = "squares" if self._mode==2 else "cubes"
            self._config[key] = {str(k): int(v) for k,v in self._rchk.items()}
        try:
            with open(CONFIG_FILE,"w") as f: json.dump(self._config, f)
        except: pass

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Particle canvas (absolute overlay behind content)
        self._particles = ParticleCanvas(self)
        self._particles.setAttribute(Qt.WA_TransparentForMouseEvents)

        # ── Top Bar ──────────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(52)
        top.setStyleSheet(
            f"QFrame{{background:{_h(SURFACE)};border-bottom:1px solid {_h(BORDER)};border-radius:0;}}")
        tl = QHBoxLayout(top); tl.setContentsMargins(16,0,16,0); tl.setSpacing(10)

        self._hex = HexLogo(34); tl.addWidget(self._hex)

        titles = QWidget(); titles.setStyleSheet("background:transparent;")
        tvl = QVBoxLayout(titles); tvl.setContentsMargins(0,0,0,0); tvl.setSpacing(1)
        t1 = QLabel("MATH DOJO"); t1.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,11,QFont.Bold))
        t1.setStyleSheet(f"color:{_h(GREEN)};background:transparent;letter-spacing:2px;")
        t2 = QLabel("TABLES  •  SQUARES  •  CUBES  •  TRAINER")
        t2.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        t2.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;letter-spacing:1px;")
        tvl.addWidget(t1); tvl.addWidget(t2); tl.addWidget(titles)

        self._top_mode_lbl = QLabel("")
        self._top_mode_lbl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,8,QFont.Bold))
        self._top_mode_lbl.setStyleSheet(f"background:transparent;color:{_h(GREEN)};letter-spacing:1px;")
        self._top_mode_lbl.hide(); tl.addWidget(self._top_mode_lbl)
        tl.addStretch()

        combo_frame = QFrame()
        combo_frame.setStyleSheet(
            f"QFrame{{background:{_h(CARD)};border:1px solid {_h(BORDER)};border-radius:4px;}}")
        cl = QHBoxLayout(combo_frame); cl.setContentsMargins(10,4,10,4); cl.setSpacing(6)
        fire = QLabel("🔥"); fire.setFont(QFont("Segoe UI Emoji",12))
        fire.setStyleSheet("background:transparent;"); cl.addWidget(fire)
        clbl = QLabel("COMBO"); clbl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        clbl.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;letter-spacing:1px;"); cl.addWidget(clbl)
        self._combo_val = QLabel("0"); self._combo_val.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,15,QFont.Bold))
        self._combo_val.setStyleSheet(f"color:{_h(ORANG)};background:transparent;min-width:24px;")
        self._combo_val.setAlignment(Qt.AlignRight|Qt.AlignVCenter); cl.addWidget(self._combo_val)
        tl.addWidget(combo_frame)

        tl.addSpacing(8)
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet(f"QPushButton{{background:{_h(CARD)};color:{_h(SUBTEXT)};border:1px solid {_h(BORDER)};border-radius:4px;font-size:14px;}} QPushButton:hover{{color:{_h(RED)};border-color:{_h(RED)};}}")
        btn_close.clicked.connect(self.closed.emit)
        tl.addWidget(btn_close)

        root.addWidget(top)

        # ── Stack ─────────────────────────────────────────────────────────────
        self._stack = QWidget(); self._stack.setStyleSheet(f"background:{_h(BG)};")
        sl = QVBoxLayout(self._stack); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        self._p0 = self._build_p0()
        self._p1 = self._build_p1()
        self._p2 = self._build_p2()
        for w in (self._p0, self._p1, self._p2): sl.addWidget(w)
        root.addWidget(self._stack, 1)

        # ── Status Bar ────────────────────────────────────────────────────────
        sb = QFrame(); sb.setFixedHeight(26)
        sb.setStyleSheet(
            f"QFrame{{background:{_h(SURFACE)};border-top:1px solid {_h(BORDER)};border-radius:0;}}")
        sbl = QHBoxLayout(sb); sbl.setContentsMargins(12,0,12,0); sbl.setSpacing(8)
        dot = QLabel("●"); dot.setFont(QFont("Segoe UI",8))
        dot.setStyleSheet(f"color:{_h(GREEN)};background:transparent;"); sbl.addWidget(dot)
        static = QLabel("•  CALCULATION DOJO  •")
        static.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        static.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;"); sbl.addWidget(static)
        self._sb_status = QLabel("READY")
        self._sb_status.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        self._sb_status.setStyleSheet(f"color:{_h(GREEN)};background:transparent;"); sbl.addWidget(self._sb_status)
        sbl.addStretch()
        root.addWidget(sb)

    def resizeEvent(self, e):
        self._particles.setGeometry(0, 52, self.width(), self.height()-78)
        super().resizeEvent(e)

    def showEvent(self, e):
        self._particles.setGeometry(0, 52, self.width(), self.height()-78)
        self._particles.raise_()
        super().showEvent(e)

    # ── Page 0 ────────────────────────────────────────────────────────────────
    def _build_p0(self):
        p = QWidget(); p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p); L.setAlignment(Qt.AlignCenter); L.setSpacing(0)
        L.addStretch()

        hero = QLabel("MATH DOJO")
        hero.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,28,QFont.Black))
        hero.setStyleSheet(f"color:{_h(GREEN)};background:transparent;letter-spacing:4px;")
        hero.setAlignment(Qt.AlignCenter); L.addWidget(hero)

        sub = QLabel("— CHOOSE YOUR DISCIPLINE —")
        sub.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,8))
        sub.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;letter-spacing:3px;")
        sub.setAlignment(Qt.AlignCenter); L.addWidget(sub)
        L.addSpacing(24)

        for mode_id, icon, name, desc, color, bg_hex in [
            (1, "×",  "TABLES  —  पहाड़े",  "MULTIPLICATION 1–45",  BLUE,   "#0A1520"),
            (2, "x²", "SQUARES — वर्ग",      "PERFECT SQUARES",      PURPLE, "#120A20"),
            (3, "x³", "CUBES   — घन",        "PERFECT CUBES",        RED,    "#200A0A"),
        ]:
            c_hex = _h(color)
            # Use QFrame — no overlay blocking clicks
            card = QFrame()
            card.setFixedSize(360, 70)
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet(f"""
                QFrame{{background:{bg_hex};border:1px solid {c_hex}55;
                    border-left:3px solid {c_hex};border-radius:5px;}}
                QFrame:hover{{background:{bg_hex};border-color:{c_hex};
                    border-left:3px solid {c_hex};}}
            """)
            ol = QHBoxLayout(card); ol.setContentsMargins(12,0,12,0); ol.setSpacing(12)
            ic = QLabel(icon); ic.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,18,QFont.Black))
            ic.setStyleSheet(f"color:{c_hex};background:transparent;min-width:36px;")
            ic.setAttribute(Qt.WA_TransparentForMouseEvents)
            ic.setAlignment(Qt.AlignCenter); ol.addWidget(ic)
            tw = QWidget(); tw.setStyleSheet("background:transparent;")
            tw.setAttribute(Qt.WA_TransparentForMouseEvents)
            tvl = QVBoxLayout(tw); tvl.setContentsMargins(0,0,0,0); tvl.setSpacing(2)
            nl = QLabel(name); nl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,11,QFont.Bold))
            nl.setAttribute(Qt.WA_TransparentForMouseEvents)
            nl.setStyleSheet(f"color:{c_hex};background:transparent;letter-spacing:1px;")
            dl = QLabel(desc); dl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,8))
            dl.setAttribute(Qt.WA_TransparentForMouseEvents)
            dl.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;")
            tvl.addWidget(nl); tvl.addWidget(dl); ol.addWidget(tw)
            ol.addStretch()
            arr = QLabel("▶"); arr.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,14))
            arr.setAttribute(Qt.WA_TransparentForMouseEvents)
            arr.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;"); ol.addWidget(arr)
            card.mousePressEvent = lambda _, m=mode_id: self._select_mode(m)
            L.addWidget(card, 0, Qt.AlignHCenter); L.addSpacing(8)

        L.addStretch()
        return p

    # ── Page 1 ────────────────────────────────────────────────────────────────
    def _build_p1(self):
        p = QWidget(); p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        hdr = QFrame(); hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"QFrame{{background:{_h(SURFACE)};border-bottom:1px solid {_h(BORDER)};border-radius:0;}}")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16,0,16,0); hl.setSpacing(12)
        back = self._mk_back_btn(); back.clicked.connect(lambda: self._show(0)); hl.addWidget(back)
        self._p1_title = QLabel("SELECT CHALLENGE")
        self._p1_title.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,11,QFont.Bold))
        self._p1_title.setStyleSheet(f"color:{_h(GREEN)};background:transparent;letter-spacing:2px;")
        hl.addWidget(self._p1_title); L.addWidget(hdr)

        body = QWidget(); body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body); bl.setContentsMargins(16,12,16,12); bl.setSpacing(10)

        # Tables section
        self._tab_sec = QWidget(); self._tab_sec.setStyleSheet("background:transparent;")
        tsl = QVBoxLayout(self._tab_sec); tsl.setContentsMargins(0,0,0,0); tsl.setSpacing(6)
        lbl1 = QLabel("— SELECT TABLES (1–45) —"); lbl1.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        lbl1.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;letter-spacing:1.5px;")
        tsl.addWidget(lbl1)
        gw = QWidget(); gw.setStyleSheet(f"background:{_h(SURFACE)};border-radius:4px;")
        self._tab_grid = QGridLayout(gw)
        self._tab_grid.setContentsMargins(8,8,8,8); self._tab_grid.setSpacing(4)
        self._tab_btns = {}
        for i in range(1,46):
            saved = bool(self._config.get("tables",{}).get(str(i),0))
            self._tchk[i] = saved
            b = self._mk_cb(str(i), saved, GREEN)
            b.clicked.connect(lambda _,n=i: self._toggle_tab(n))
            self._tab_btns[i] = b
            self._tab_grid.addWidget(b,(i-1)//9,(i-1)%9)
        tsl.addWidget(gw); bl.addWidget(self._tab_sec)

        # Range section
        self._rng_sec = QWidget(); self._rng_sec.setStyleSheet("background:transparent;")
        rsl = QVBoxLayout(self._rng_sec); rsl.setContentsMargins(0,0,0,0); rsl.setSpacing(6)
        self._rng_sec_lbl = QLabel("— SELECT RANGE —"); self._rng_sec_lbl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        self._rng_sec_lbl.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;letter-spacing:1.5px;")
        rsl.addWidget(self._rng_sec_lbl)
        self._rng_gw = QWidget(); self._rng_gw.setStyleSheet(f"background:{_h(SURFACE)};border-radius:4px;")
        self._rng_grid = QGridLayout(self._rng_gw)
        self._rng_grid.setContentsMargins(8,8,8,8); self._rng_grid.setSpacing(6)
        rsl.addWidget(self._rng_gw); bl.addWidget(self._rng_sec); self._rng_sec.hide()

        self._warn_lbl = QLabel("")
        self._warn_lbl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,8))
        self._warn_lbl.setStyleSheet(f"color:{_h(RED)};background:transparent;"); bl.addWidget(self._warn_lbl)

        start = QPushButton("▶  START MISSION"); start.setFixedHeight(44)
        start.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,10,QFont.Black))
        start.setStyleSheet(f"""
            QPushButton{{background:{_h(GREEN)};color:#07070B;border:none;
                border-radius:4px;letter-spacing:2px;}}
            QPushButton:hover{{background:white;}}
            QPushButton:pressed{{background:{_h(GREEN)};}}
        """)
        start.clicked.connect(self._start_practice); bl.addWidget(start); bl.addStretch()

        scroll = QScrollArea(); scroll.setWidget(body); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}"); L.addWidget(scroll,1)
        return p

    def _mk_back_btn(self):
        b = QPushButton("◀ BACK"); b.setFixedSize(120, 28)
        b.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;background:transparent;border:1px solid {_h(BORDER)};
                color:{_h(SUBTEXT)};border-radius:3px;letter-spacing:1px;}}
            QPushButton:hover{{border-color:{_h(GREEN)};color:{_h(GREEN)};}}
        """)
        return b

    def _mk_cb(self, text, checked, color):
        b = QPushButton(text); b.setCheckable(True); b.setChecked(checked)
        b.setFixedSize(54, 48); b.setFont(QFont("Arial", 14, QFont.Bold))
        c_hex = _h(color)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:14pt;background:#0D0D16;color:{_h(SUBTEXT)};
                border:1px solid {_h(BORDER)};border-radius:3px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(114,255,79,0.12);
                border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _mk_rcb(self, text, checked):
        b = QPushButton(text); b.setCheckable(True); b.setChecked(checked)
        b.setFixedSize(102, 48); b.setFont(QFont("Arial", 12, QFont.Bold))
        c_hex = _h(PURPLE)
        b.setStyleSheet(f"""
            QPushButton{{padding:0px !important;margin:0px !important;font-family:Arial !important;font-weight:bold;font-size:12pt;background:#0D0D16;color:{_h(SUBTEXT)};
                border:1px solid {_h(BORDER)};border-radius:3px;}}
            QPushButton:hover{{border-color:{c_hex};color:{c_hex};}}
            QPushButton:checked{{background:rgba(168,108,255,0.12);
                border-color:{c_hex};color:{c_hex};}}
        """)
        return b

    def _toggle_tab(self, n):
        self._tchk[n] = self._tab_btns[n].isChecked(); self._save_config()

    def _toggle_rng(self, key, btn):
        self._rchk[key] = btn.isChecked(); self._save_config()

    # ── Page 2 ────────────────────────────────────────────────────────────────
    def _build_p2(self):
        p = QWidget(); p.setStyleSheet("background:transparent;")
        L = QVBoxLayout(p); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        hdr = QFrame(); hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"QFrame{{background:{_h(SURFACE)};border-bottom:1px solid {_h(BORDER)};border-radius:0;}}")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16,0,16,0); hl.setSpacing(10)
        back2 = self._mk_back_btn(); back2.clicked.connect(lambda: self._show(1)); hl.addWidget(back2)
        self._mode_badge = QLabel("")
        self._mode_badge.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7,QFont.Bold))
        self._mode_badge.setStyleSheet(
            f"color:{_h(BLUE)};background:rgba(79,195,247,0.1);"
            f"border:1px solid {_h(BLUE)};border-radius:3px;padding:2px 8px;letter-spacing:1px;")
        hl.addWidget(self._mode_badge); hl.addStretch()
        self._qcount_lbl = QLabel("MISSION 1"); self._qcount_lbl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7))
        self._qcount_lbl.setStyleSheet(f"color:{_h(SUBTEXT)};background:transparent;"); hl.addWidget(self._qcount_lbl)
        L.addWidget(hdr)

        body = QWidget(); body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body); bl.setContentsMargins(40,20,40,20)
        bl.setAlignment(Qt.AlignCenter); bl.setSpacing(12)

        self._scan_card = ScanCard(); self._scan_card.setMinimumHeight(110)
        inner = QVBoxLayout(self._scan_card)
        self._q_lbl = QLabel("?"); self._q_lbl.setFont(QFont("Segoe UI",76,QFont.Black))
        self._q_lbl.setStyleSheet(f"color:{_h(TEXT)};background:transparent;letter-spacing:4px;")
        self._q_lbl.setAlignment(Qt.AlignCenter); inner.addWidget(self._q_lbl)
        bl.addWidget(self._scan_card)

        ans_row = QWidget(); ans_row.setStyleSheet("background:transparent;")
        al = QHBoxLayout(ans_row); al.setAlignment(Qt.AlignCenter)
        al.setContentsMargins(0,0,0,0); al.setSpacing(10)
        self._ans_in = QLineEdit()
        self._ans_in.setPlaceholderText("?")
        self._ans_in.setAlignment(Qt.AlignCenter)
        self._ans_in.setFixedSize(190,52)
        self._ans_in.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,22,QFont.Bold))
        self._ANS_SS = (
            f"QLineEdit{{background:{_h(CARD)};color:{_h(TEXT)};"
            f"border:2px solid {_h(BORDER)};border-radius:4px;padding:6px;}}"
            f"QLineEdit:focus{{border:2px solid {_h(GREEN)};}} "
        )
        self._ans_in.setStyleSheet(self._ANS_SS)
        self._ans_in.textChanged.connect(self._auto_check)
        self._ans_in.returnPressed.connect(self._check)
        al.addWidget(self._ans_in)

        self._mic_btn = QPushButton("🎙"); self._mic_btn.setFixedSize(52,52)
        self._mic_btn.setFont(QFont("Segoe UI Emoji",18))
        self._mic_btn.setStyleSheet(
            f"QPushButton{{background:{_h(CARD)};border:1px solid {_h(BORDER)};"
            f"border-radius:4px;color:{_h(SUBTEXT)};}} "
            f"QPushButton:hover{{border-color:{_h(GREEN)};color:{_h(GREEN)};}} "
        )
        self._mic_btn.clicked.connect(self._voice); al.addWidget(self._mic_btn)
        bl.addWidget(ans_row)

        self._fb_lbl = QLabel("")
        self._fb_lbl.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,10,QFont.Bold))
        self._fb_lbl.setStyleSheet(f"color:{_h(TEXT)};background:transparent;letter-spacing:1px;")
        self._fb_lbl.setAlignment(Qt.AlignCenter); bl.addWidget(self._fb_lbl)

        self._show_ans_btn = QPushButton("REVEAL ANSWER 👁")
        self._show_ans_btn.setFixedHeight(34)
        self._show_ans_btn.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,7,QFont.Bold))
        self._show_ans_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {_h(YELLOW)};"
            f"color:{_h(YELLOW)};border-radius:3px;padding:0 14px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:rgba(241,250,140,0.1);}}"
        )
        self._show_ans_btn.hide()
        self._show_ans_btn.clicked.connect(self._reveal); bl.addWidget(self._show_ans_btn, 0, Qt.AlignCenter)

        self._reveal_scroll = QScrollArea()
        self._reveal_scroll.setStyleSheet(
            f"QScrollArea{{background:{_h(CARD)};border:1px solid {_h(BORDER)};border-radius:4px;}}")
        self._reveal_lbl = QLabel("")
        self._reveal_lbl.setFont(QFont("Courier New",12))
        self._reveal_lbl.setStyleSheet(f"color:{_h(BLUE)};background:transparent;padding:10px;")
        self._reveal_lbl.setAlignment(Qt.AlignLeft|Qt.AlignTop)
        self._reveal_scroll.setWidget(self._reveal_lbl)
        self._reveal_scroll.setWidgetResizable(True)
        self._reveal_scroll.hide(); bl.addWidget(self._reveal_scroll); bl.addStretch()

        L.addWidget(body,1)
        return p

    # ── Navigation ────────────────────────────────────────────────────────────
    def _show(self, idx):
        self._p0.setVisible(idx==0)
        self._p1.setVisible(idx==1)
        self._p2.setVisible(idx==2)
        if idx==0: self._top_mode_lbl.hide()

    def _select_mode(self, m):
        self._mode = m
        titles = {1:"SELECT TABLES (1–45)",2:"SELECT SQUARES RANGE",3:"SELECT CUBES RANGE"}
        self._p1_title.setText(titles[m])
        self._tab_sec.setVisible(m==1); self._rng_sec.setVisible(m!=1)
        if m!=1: self._build_ranges(50 if m==2 else 30)
        self._warn_lbl.setText(""); self._show(1)

    def _build_ranges(self, max_val):
        for i in reversed(range(self._rng_grid.count())):
            w = self._rng_grid.itemAt(i).widget()
            if w: w.deleteLater()
        self._rchk = {}
        mode_key = "squares" if self._mode==2 else "cubes"
        for idx, s in enumerate(range(1, max_val+1, 5)):
            e = min(s+4, max_val); key = f"{s}-{e}"
            saved = bool(self._config.get(mode_key,{}).get(key, False))
            self._rchk[key] = saved
            b = self._mk_rcb(key, saved)
            b.clicked.connect(lambda _,k=key,btn=b: self._toggle_rng(k,btn))
            self._rng_grid.addWidget(b, idx//5, idx%5)

    # ── Practice ──────────────────────────────────────────────────────────────
    def _start_practice(self):
        self._warn_lbl.setText("")
        sel = [k for k,v in (self._tchk if self._mode==1 else self._rchk).items() if v]
        if not sel:
            self._warn_lbl.setText("SELECT AT LEAST ONE TARGET, NINJA!"); return
        labels = {1:"TABLES",2:"SQUARES",3:"CUBES"}
        colors = {1:BLUE,2:PURPLE,3:RED}
        c = colors[self._mode]; c_hex = _h(c)
        self._mode_badge.setText(f"{labels[self._mode]} MODE")
        self._mode_badge.setStyleSheet(
            f"color:{c_hex};background:transparent;"
            f"border:1px solid {c_hex};border-radius:3px;padding:2px 8px;"
            f"font-family:ui.home_screen.NARUTO_FONT_FAMILY;font-size:7px;font-weight:bold;letter-spacing:1px;")
        self._top_mode_lbl.setText(f"{labels[self._mode]} MODE")
        self._top_mode_lbl.setStyleSheet(f"color:{c_hex};background:transparent;letter-spacing:1px;")
        self._top_mode_lbl.show()
        self._streak=0; self._qn=0
        self._combo_val.setText("0")
        self._combo_val.setStyleSheet(f"color:{_h(ORANG)};background:transparent;min-width:24px;")
        self._show(2); self._gen_q()

    def _gen_q(self):
        self._reveal_scroll.hide(); self._show_ans_btn.hide()
        self._fb_lbl.setText(""); self._fb_lbl.setStyleSheet(f"color:{_h(TEXT)};background:transparent;letter-spacing:1px;")
        self._ans_in.setText(""); self._ans_in.setStyleSheet(self._ANS_SS)
        self._qn += 1; self._qcount_lbl.setText(f"MISSION {self._qn}")
        self._sb_status.setText("TRAINING...")
        if self._mode==1:
            sel = [k for k,v in self._tchk.items() if v]
            n1 = random.choice(sel); n2 = random.choice([2,3,4,5,6,7,8,9])
            self._ans = n1*n2; self._q_lbl.setText(f"{n1} × {n2} = ?")
        else:
            sel = [k for k,v in self._rchk.items() if v]
            r = random.choice(sel); s,e = map(int, r.split("-"))
            num = random.randint(s,e)
            if self._mode==2: self._ans=num*num; self._q_lbl.setText(f"{num}² = ?")
            else:              self._ans=num*num*num; self._q_lbl.setText(f"{num}³ = ?")
        QTimer.singleShot(0, self._ans_in.setFocus)

    def _auto_check(self, text):
        digits = "".join(c for c in text if c.isdigit())
        if digits!=text:
            self._ans_in.blockSignals(True); self._ans_in.setText(digits); self._ans_in.blockSignals(False); return
        if digits and len(digits)==len(str(self._ans)):
            QTimer.singleShot(300, self._check)

    def _check(self):
        v = self._ans_in.text()
        if not v or len(v)!=len(str(self._ans)): return
        try:
            if int(v)==self._ans:
                self._streak += 1
                cv = self._streak; self._combo_val.setText(str(cv))
                color = _h(GREEN if cv>=10 else (YELLOW if cv>=5 else ORANG))
                self._combo_val.setStyleSheet(f"color:{color};background:transparent;min-width:24px;")
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{_h(CARD)};color:{_h(GREEN)};"
                    f"border:2px solid {_h(GREEN)};border-radius:4px;padding:6px;}}")
                msgs = ["COWABUNGA!","CORRECT!","LETHAL!","PERFECT!","NAILED IT!","KAME-HA!"]
                self._fb_lbl.setText(random.choice(msgs))
                self._fb_lbl.setStyleSheet(f"color:{_h(GREEN)};background:transparent;letter-spacing:1px;")
                self._sb_status.setText(f"COMBO x{self._streak}")
                self._reveal_scroll.hide(); self._show_ans_btn.hide()
                QTimer.singleShot(650, self._gen_q)
            else:
                self._streak=0; self._combo_val.setText("0")
                self._combo_val.setStyleSheet(f"color:{_h(ORANG)};background:transparent;min-width:24px;")
                self._ans_in.setStyleSheet(
                    f"QLineEdit{{background:{_h(CARD)};color:{_h(RED)};"
                    f"border:2px solid {_h(RED)};border-radius:4px;padding:6px;}}")
                self._fb_lbl.setText("WRONG! ADJUST OR REVEAL.")
                self._fb_lbl.setStyleSheet(f"color:{_h(RED)};background:transparent;letter-spacing:1px;")
                self._sb_status.setText("COMBO BROKEN"); self._show_ans_btn.show()
        except ValueError: pass

    def _reveal(self):
        self._show_ans_btn.hide()
        q = self._q_lbl.text()
        if self._mode==1:
            base  = int(q.split("×")[0].strip())
            asked = int(q.split("×")[1].split("=")[0].strip())
            lines = [("▶" if i==asked else "·")+f"  {base} × {i:>2}  =  {base*i}" for i in range(1,21)]
            self._reveal_lbl.setText("\n".join(lines)); self._reveal_scroll.show()
        else:
            self._fb_lbl.setText(f"ANSWER:  {q.replace('?',str(self._ans))}")
            self._fb_lbl.setStyleSheet(f"color:{_h(BLUE)};background:transparent;letter-spacing:1px;")

    # ── Voice ─────────────────────────────────────────────────────────────────
    def _voice(self):
        if not _VOICE:
            self._fb_lbl.setText("pip install speechrecognition"); return
        self._mic_btn.setText("…")
        self._fb_lbl.setText("LISTENING...")
        self._fb_lbl.setStyleSheet(f"color:{_h(BLUE)};background:transparent;letter-spacing:1px;")
        self._voice_thread = VoiceThread()
        self._voice_thread.result.connect(self._voice_done)
        self._voice_thread.error.connect(self._voice_err)
        self._voice_thread.finished.connect(lambda: self._mic_btn.setText("🎙"))
        self._voice_thread.start()

    @pyqtSlot(str)
    def _voice_done(self, digits):
        self._ans_in.setText(digits); self._check()

    @pyqtSlot(str)
    def _voice_err(self, msg):
        self._fb_lbl.setText(msg[:50])
        self._fb_lbl.setStyleSheet(f"color:{_h(YELLOW)};background:transparent;letter-spacing:1px;")