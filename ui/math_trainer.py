"""
Math Trainer — Native PyQt5 Page for Anki Occlusion
=====================================================
Fully integrated into the Anki Occlusion UI.
- No separate window, no subprocess
- Matches app theme (C_BG, C_ACCENT, etc.)
- 3 pages: Type Select → Challenge Select → Practice
- Single instance enforced by HomeScreen
- Voice input via SpeechRecognition (optional)
- Closes cleanly when main app closes
"""

import random, json, os, threading

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QScrollArea, QCheckBox, QLineEdit,
    QGridLayout, QSizePolicy, QApplication
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor

# ── Theme (mirrors home_screen.py) ──────────────────────────────────────────
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

CONFIG_FILE = os.path.join(os.path.expanduser("~"), "math_trainer_config.json")

# ── Optional voice ───────────────────────────────────────────────────────────
try:
    import speech_recognition as sr
    _VOICE = True
except ImportError:
    _VOICE = False


def _btn(text, color=C_ACCENT, text_color="white", h=40, w=None, font_size=13, bold=True):
    b = QPushButton(text)
    fw = "bold" if bold else "normal"
    style = (
        f"QPushButton{{background:{color};color:{text_color};border:none;"
        f"border-radius:8px;padding:8px 18px;font-size:{font_size}px;font-weight:{fw};}}"
        f"QPushButton:hover{{background:{color}CC;}}"
        f"QPushButton:pressed{{background:{color}99;}}"
    )
    b.setStyleSheet(style)
    b.setFixedHeight(h)
    if w:
        b.setFixedWidth(w)
    return b


def _label(text, size=13, color=C_TEXT, bold=False, align=Qt.AlignLeft):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};background:transparent;font-size:{size}px;"
                    f"font-weight:{'bold' if bold else 'normal'};")
    l.setAlignment(align)
    l.setWordWrap(True)
    return l


# ═══════════════════════════════════════════════════════════════════════════════
#  MATH TRAINER WIDGET  (the single page that replaces DeckView in the splitter)
# ═══════════════════════════════════════════════════════════════════════════════

class MathTrainerPage(QWidget):
    """
    Drop-in replacement for DeckView.
    HomeScreen calls:
        show_math_trainer()   — swap DeckView → MathTrainerPage
        hide_math_trainer()   — swap back
    """
    closed = pyqtSignal()   # emitted when user clicks ← Back from page 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QWidget{{background:{C_BG};}}")
        self._current_mode   = 1      # 1=Tables 2=Squares 3=Cubes
        self._correct_answer = 0
        self._streak         = 0
        self._wrong_attempts = 0
        self._table_vars     = {}     # {int: bool}
        self._range_vars     = {}     # {str: bool}
        self._voice_thread   = None
        self._config         = {}

        self._load_config()
        self._build_ui()
        self._show_page(0)

    # ── Config ───────────────────────────────────────────────────────────────
    def _load_config(self):
        self._config = {"tables": {}, "squares": {}, "cubes": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self._config = json.load(f)
            except Exception:
                pass

    def _save_config(self):
        self._config["tables"] = {str(k): int(v) for k, v in self._table_vars.items()}
        if self._range_vars:
            key = "squares" if self._current_mode == 2 else "cubes"
            self._config[key] = {str(k): int(v) for k, v in self._range_vars.items()}
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config, f)
        except Exception:
            pass

    # ── UI Build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──────────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(52)
        top.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border-radius:0px;"
            f"border-bottom:1px solid {C_BORDER};}}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 0, 20, 0)

        self._back_btn = QPushButton("◀  Back")
        self._back_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_SUBTEXT};"
            f"border:1px solid {C_BORDER};border-radius:6px;padding:4px 14px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_CARD};color:{C_TEXT};}}")
        self._back_btn.clicked.connect(self._on_back)

        title = QLabel("🧮  Math Trainer")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet(f"color:{C_ACCENT};background:transparent;")

        self._streak_lbl = QLabel("🔥 0")
        self._streak_lbl.setStyleSheet(
            f"color:#FFA500;font-size:14px;font-weight:bold;background:transparent;")

        tl.addWidget(self._back_btn)
        tl.addSpacing(16)
        tl.addWidget(title)
        tl.addStretch()
        tl.addWidget(self._streak_lbl)

        root.addWidget(top)

        # ── Stacked pages container ───────────────────────────────────────────
        self._stack = QWidget()
        self._stack.setStyleSheet(f"background:{C_BG};")
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)

        self._page0 = self._build_page0()   # Type Select
        self._page1 = self._build_page1()   # Challenge Select
        self._page2 = self._build_page2()   # Practice

        for p in (self._page0, self._page1, self._page2):
            self._stack_layout.addWidget(p)

        root.addWidget(self._stack, stretch=1)

    # ── Page 0: Type Select ──────────────────────────────────────────────────
    def _build_page0(self):
        p = QWidget()
        p.setStyleSheet(f"background:{C_BG};")
        L = QVBoxLayout(p)
        L.setAlignment(Qt.AlignCenter)
        L.setSpacing(20)

        L.addStretch()
        lbl = _label("🎯  Choose Training Type", 22, C_ACCENT, bold=True, align=Qt.AlignCenter)
        sub = _label("What do you want to practice today?", 13, C_SUBTEXT, align=Qt.AlignCenter)
        L.addWidget(lbl)
        L.addWidget(sub)
        L.addSpacing(20)

        cards = [
            (1, "📖  Tables  (पहाड़े)",  "#1f538d", "Multiplication tables 1–45"),
            (2, "²   Squares (वर्ग)",    "#6a0dad", "Perfect squares practice"),
            (3, "³   Cubes   (घन)",      "#8b0000", "Perfect cubes practice"),
        ]
        for mode_id, label, color, subtitle in cards:
            card = QPushButton(f"{label}\n{subtitle}")
            card.setStyleSheet(
                f"QPushButton{{background:{color};color:white;border:none;"
                f"border-radius:12px;padding:16px 32px;"
                f"font-size:15px;font-weight:bold;text-align:center;}}"
                f"QPushButton:hover{{background:{color}CC;}}"
                f"QPushButton:pressed{{background:{color}99;}}")
            card.setFixedSize(360, 72)
            card.clicked.connect(lambda _, m=mode_id: self._select_mode(m))
            L.addWidget(card, alignment=Qt.AlignCenter)

        L.addStretch()
        return p

    # ── Page 1: Challenge Select ─────────────────────────────────────────────
    def _build_page1(self):
        p = QWidget()
        p.setStyleSheet(f"background:{C_BG};")
        L = QVBoxLayout(p)
        L.setContentsMargins(40, 24, 40, 24)
        L.setSpacing(12)

        self._challenge_title = _label("Select Challenge", 18, C_ACCENT, bold=True, align=Qt.AlignCenter)
        L.addWidget(self._challenge_title)

        # Tables checkboxes
        self._tables_widget = QWidget()
        self._tables_widget.setStyleSheet(f"background:{C_SURFACE};border-radius:8px;")
        tw_scroll = QScrollArea()
        tw_scroll.setWidget(self._tables_widget)
        tw_scroll.setWidgetResizable(True)
        tw_scroll.setFixedHeight(200)
        tw_scroll.setStyleSheet("QScrollArea{border:1px solid " + C_BORDER + ";border-radius:8px;}")

        grid = QGridLayout(self._tables_widget)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(4)
        self._table_checks = {}
        for i in range(1, 46):
            saved = bool(self._config.get("tables", {}).get(str(i), 0))
            cb = QCheckBox(str(i))
            cb.setChecked(saved)
            cb.setStyleSheet(
                f"QCheckBox{{color:{C_TEXT};font-size:12px;background:transparent;}}"
                f"QCheckBox::indicator{{width:14px;height:14px;}}"
                f"QCheckBox::indicator:checked{{background:{C_ACCENT};border-radius:3px;}}"
                f"QCheckBox::indicator:unchecked{{background:{C_CARD};border:1px solid {C_BORDER};border-radius:3px;}}")
            cb.stateChanged.connect(self._save_config)
            grid.addWidget(cb, (i-1)//9, (i-1)%9)
            self._table_checks[i] = cb
            self._table_vars[i] = False

        # Ranges (squares/cubes)
        self._ranges_widget = QWidget()
        self._ranges_widget.setStyleSheet(f"background:{C_SURFACE};border-radius:8px;")
        rw_scroll = QScrollArea()
        rw_scroll.setWidget(self._ranges_widget)
        rw_scroll.setWidgetResizable(True)
        rw_scroll.setFixedHeight(200)
        rw_scroll.setStyleSheet("QScrollArea{border:1px solid " + C_BORDER + ";border-radius:8px;}")
        self._range_grid_layout = QGridLayout(self._ranges_widget)
        self._range_grid_layout.setContentsMargins(8, 8, 8, 8)
        self._range_grid_layout.setSpacing(6)
        self._range_checks = {}

        self._tw_scroll  = tw_scroll
        self._rw_scroll  = rw_scroll
        L.addWidget(tw_scroll)
        L.addWidget(rw_scroll)

        self._warn_lbl = _label("", 12, C_RED, align=Qt.AlignCenter)
        L.addWidget(self._warn_lbl)

        start_btn = _btn("🚀  Start Practice", C_GREEN, "#1E1E2E", h=44)
        start_btn.clicked.connect(self._start_practice)
        L.addWidget(start_btn, alignment=Qt.AlignCenter)
        start_btn.setFixedWidth(220)

        return p

    # ── Page 2: Practice ─────────────────────────────────────────────────────
    def _build_page2(self):
        p = QWidget()
        p.setStyleSheet(f"background:{C_BG};")
        L = QVBoxLayout(p)
        L.setContentsMargins(60, 30, 60, 30)
        L.setSpacing(16)

        # Mode label
        self._mode_lbl = _label("", 13, C_ACCENT, bold=True, align=Qt.AlignCenter)
        L.addWidget(self._mode_lbl)

        # Question card
        q_frame = QFrame()
        q_frame.setStyleSheet(
            f"QFrame{{background:{C_SURFACE};border-radius:16px;"
            f"border:1px solid {C_BORDER};}}")
        q_frame.setFixedHeight(130)
        ql = QVBoxLayout(q_frame)
        self._question_lbl = QLabel("")
        self._question_lbl.setFont(QFont("Segoe UI", 42, QFont.Bold))
        self._question_lbl.setStyleSheet(f"color:{C_TEXT};background:transparent;")
        self._question_lbl.setAlignment(Qt.AlignCenter)
        ql.addWidget(self._question_lbl)
        L.addWidget(q_frame)

        # Answer row
        ans_row = QWidget()
        ans_row.setStyleSheet("background:transparent;")
        al = QHBoxLayout(ans_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setAlignment(Qt.AlignCenter)

        self._answer_entry = QLineEdit()
        self._answer_entry.setPlaceholderText("Answer")
        self._answer_entry.setFont(QFont("Segoe UI", 24))
        self._answer_entry.setAlignment(Qt.AlignCenter)
        self._answer_entry.setFixedSize(200, 52)
        self._answer_entry.setStyleSheet(
            f"QLineEdit{{background:{C_CARD};color:{C_TEXT};"
            f"border:2px solid {C_BORDER};border-radius:10px;padding:6px;}}"
            f"QLineEdit:focus{{border:2px solid {C_ACCENT};}}")
        self._answer_entry.textChanged.connect(self._auto_check)
        self._answer_entry.returnPressed.connect(self._check_answer)

        al.addWidget(self._answer_entry)

        if _VOICE:
            self._mic_btn = _btn("🎙️", C_CARD, C_TEXT, h=52, w=52)
            self._mic_btn.clicked.connect(self._listen_voice)
            al.addSpacing(10)
            al.addWidget(self._mic_btn)

        L.addWidget(ans_row)

        # Feedback
        self._feedback_lbl = _label("", 14, C_TEXT, align=Qt.AlignCenter)
        L.addWidget(self._feedback_lbl)

        # Show answer button (hidden by default)
        self._show_ans_btn = _btn("Show Answer 👀", C_YELLOW, "#1E1E2E", h=36, w=180)
        self._show_ans_btn.clicked.connect(self._reveal_answer)
        self._show_ans_btn.hide()
        L.addWidget(self._show_ans_btn, alignment=Qt.AlignCenter)

        # Reveal box (table scroll)
        self._reveal_scroll = QScrollArea()
        self._reveal_scroll.setFixedHeight(180)
        self._reveal_scroll.setStyleSheet(
            f"QScrollArea{{background:{C_CARD};border-radius:10px;"
            f"border:1px solid {C_BORDER};}}")
        self._reveal_lbl = QLabel("")
        self._reveal_lbl.setFont(QFont("Courier New", 14))
        self._reveal_lbl.setStyleSheet(f"color:#00D2FF;background:transparent;padding:10px;")
        self._reveal_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._reveal_scroll.setWidget(self._reveal_lbl)
        self._reveal_scroll.setWidgetResizable(True)
        self._reveal_scroll.hide()
        L.addWidget(self._reveal_scroll)

        L.addStretch()
        return p

    # ── Page navigation ───────────────────────────────────────────────────────
    def _show_page(self, idx):
        self._current_page = idx
        self._page0.setVisible(idx == 0)
        self._page1.setVisible(idx == 1)
        self._page2.setVisible(idx == 2)

        # Back button: on page 0 it exits Math Trainer entirely
        self._back_btn.setText("✕  Close" if idx == 0 else "◀  Back")
        self._streak_lbl.setVisible(idx == 2)

    def _on_back(self):
        idx = getattr(self, "_current_page", 0)
        if idx == 0:
            self.closed.emit()
        elif idx == 1:
            self._show_page(0)
        else:
            self._show_page(1)

    # ── Mode selection ────────────────────────────────────────────────────────
    def _select_mode(self, mode):
        self._current_mode = mode
        self._refresh_challenge_page()
        self._show_page(1)

    def _refresh_challenge_page(self):
        self._warn_lbl.setText("")
        if self._current_mode == 1:
            self._challenge_title.setText("Select Tables  (1 – 45)")
            self._rw_scroll.hide()
            self._tw_scroll.show()
        else:
            name     = "Squares" if self._current_mode == 2 else "Cubes"
            max_val  = 50 if self._current_mode == 2 else 30
            mode_key = "squares" if self._current_mode == 2 else "cubes"
            self._challenge_title.setText(f"Select {name} Range")
            self._tw_scroll.hide()
            self._populate_ranges(max_val, mode_key)
            self._rw_scroll.show()

    def _populate_ranges(self, max_val, mode_key):
        # Clear old checkboxes
        for cb in self._range_checks.values():
            cb.deleteLater()
        self._range_checks.clear()
        self._range_vars.clear()

        ranges = [f"{i}-{i+4}" for i in range(1, max_val + 1, 5)]
        for idx, r in enumerate(ranges):
            saved = bool(self._config.get(mode_key, {}).get(r, False))
            cb = QCheckBox(r)
            cb.setChecked(saved)
            cb.setStyleSheet(
                f"QCheckBox{{color:{C_TEXT};font-size:12px;background:transparent;}}"
                f"QCheckBox::indicator{{width:14px;height:14px;}}"
                f"QCheckBox::indicator:checked{{background:{C_ACCENT};border-radius:3px;}}"
                f"QCheckBox::indicator:unchecked{{background:{C_CARD};border:1px solid {C_BORDER};border-radius:3px;}}")
            cb.stateChanged.connect(self._save_config)
            self._range_grid_layout.addWidget(cb, idx // 5, idx % 5)
            self._range_checks[r] = cb
            self._range_vars[r] = saved

    # ── Start practice ────────────────────────────────────────────────────────
    def _start_practice(self):
        self._warn_lbl.setText("")
        if self._current_mode == 1:
            selected = [i for i, cb in self._table_checks.items() if cb.isChecked()]
            if not selected:
                self._warn_lbl.setText("⚠️  Please select at least one table!")
                return
        else:
            selected = [r for r, cb in self._range_checks.items() if cb.isChecked()]
            if not selected:
                self._warn_lbl.setText("⚠️  Please select at least one range!")
                return

        names = {1: "📖  Tables Mode", 2: "²  Squares Mode", 3: "³  Cubes Mode"}
        self._mode_lbl.setText(names[self._current_mode])
        self._streak = 0
        self._streak_lbl.setText("🔥 0")
        self._show_page(2)
        self._generate_question()

    # ── Question generation ───────────────────────────────────────────────────
    def _generate_question(self):
        self._reveal_scroll.hide()
        self._show_ans_btn.hide()
        self._wrong_attempts = 0
        self._answer_entry.setText("")
        self._answer_entry.setStyleSheet(
            f"QLineEdit{{background:{C_CARD};color:{C_TEXT};"
            f"border:2px solid {C_BORDER};border-radius:10px;padding:6px;}}"
            f"QLineEdit:focus{{border:2px solid {C_ACCENT};}}")
        self._feedback_lbl.setText("")
        self._feedback_lbl.setStyleSheet(f"color:{C_TEXT};background:transparent;font-size:14px;")

        if self._current_mode == 1:
            selected = [i for i, cb in self._table_checks.items() if cb.isChecked()]
            n1 = random.choice(selected)
            n2 = random.choice([x for x in range(2, 11) if x != 10])
            self._correct_answer = n1 * n2
            self._question_lbl.setText(f"{n1} × {n2} = ?")
        else:
            selected = [r for r, cb in self._range_checks.items() if cb.isChecked()]
            possible = []
            for r in selected:
                s, e = map(int, r.split("-"))
                possible.extend(range(s, e + 1))
            num = random.choice(possible)
            if self._current_mode == 2:
                self._correct_answer = num * num
                self._question_lbl.setText(f"{num}² = ?")
            else:
                self._correct_answer = num * num * num
                self._question_lbl.setText(f"{num}³ = ?")

        self._answer_entry.setFocus()

    # ── Answer checking ───────────────────────────────────────────────────────
    def _auto_check(self, text):
        digits = "".join(c for c in text if c.isdigit())
        if digits != text:
            self._answer_entry.blockSignals(True)
            self._answer_entry.setText(digits)
            self._answer_entry.blockSignals(False)
            return
        if digits and len(digits) == len(str(self._correct_answer)):
            QTimer.singleShot(300, self._check_answer)

    def _check_answer(self):
        text = self._answer_entry.text()
        if not text or len(text) != len(str(self._correct_answer)):
            return
        try:
            if int(text) == self._correct_answer:
                self._streak += 1
                self._streak_lbl.setText(f"🔥 {self._streak}")
                self._reveal_scroll.hide()
                self._show_ans_btn.hide()
                self._feedback_lbl.setText("✅  बिल्कुल सही!")
                self._feedback_lbl.setStyleSheet(
                    f"color:{C_GREEN};background:transparent;font-size:14px;font-weight:bold;")
                self._answer_entry.setStyleSheet(
                    f"QLineEdit{{background:{C_CARD};color:{C_GREEN};"
                    f"border:2px solid {C_GREEN};border-radius:10px;padding:6px;}}")
                QTimer.singleShot(600, self._generate_question)
            else:
                self._streak = 0
                self._streak_lbl.setText("🔥 0")
                self._wrong_attempts += 1
                self._feedback_lbl.setText("❌  Wrong! Try again or reveal.")
                self._feedback_lbl.setStyleSheet(
                    f"color:{C_RED};background:transparent;font-size:14px;font-weight:bold;")
                self._blink_red()
                self._show_ans_btn.show()
        except ValueError:
            self._feedback_lbl.setText("⚠️  सिर्फ numbers टाइप करें!")

    def _blink_red(self, count=0):
        if count >= 6:
            self._answer_entry.setStyleSheet(
                f"QLineEdit{{background:{C_CARD};color:{C_TEXT};"
                f"border:2px solid {C_BORDER};border-radius:10px;padding:6px;}}"
                f"QLineEdit:focus{{border:2px solid {C_ACCENT};}}")
            return
        color = C_RED if count % 2 == 0 else C_BORDER
        self._answer_entry.setStyleSheet(
            f"QLineEdit{{background:{C_CARD};color:{C_RED if count%2==0 else C_TEXT};"
            f"border:2px solid {color};border-radius:10px;padding:6px;}}")
        QTimer.singleShot(150, lambda: self._blink_red(count + 1))

    # ── Reveal answer ─────────────────────────────────────────────────────────
    def _reveal_answer(self):
        self._show_ans_btn.hide()
        q = self._question_lbl.text()
        if self._current_mode == 1:
            base  = int(q.split("×")[0].strip())
            asked = int(q.split("×")[1].split("=")[0].strip())
            lines = [
                f"{'►' if i == asked else ' '} {base} × {i:>2}  =  {base * i}"
                for i in range(1, 21)
            ]
            self._reveal_lbl.setText("\n".join(lines))
            self._reveal_scroll.show()
        else:
            self._feedback_lbl.setText(
                f"👉  {q.replace('?', str(self._correct_answer))}")
            self._feedback_lbl.setStyleSheet(
                f"color:#00D2FF;background:transparent;font-size:15px;font-weight:bold;")

    # ── Voice ─────────────────────────────────────────────────────────────────
    def _listen_voice(self):
        if not _VOICE:
            return
        self._mic_btn.setText("...")
        self._feedback_lbl.setText("Listening... 🎙️")
        self._voice_thread = threading.Thread(target=self._recognize, daemon=True)
        self._voice_thread.start()

    def _recognize(self):
        r = sr.Recognizer()
        try:
            with sr.Microphone() as src:
                r.adjust_for_ambient_noise(src, duration=0.5)
                audio = r.listen(src, timeout=4, phrase_time_limit=4)
                text  = r.recognize_google(audio, language="hi-IN").lower()
                word_map = {"to":"2","too":"2","two":"2","do":"2",
                            "tree":"3","three":"3","for":"4","four":"4",
                            "ate":"8","eight":"8","one":"1","won":"1"}
                digits = "".join(
                    filter(str.isdigit,
                           " ".join(word_map.get(w, w) for w in text.split())))
                if digits:
                    QTimer.singleShot(0, lambda: self._voice_done(digits))
                else:
                    QTimer.singleShot(0, lambda: self._voice_fail(f"Heard '{text}' — no numbers"))
        except Exception as ex:
            QTimer.singleShot(0, lambda: self._voice_fail(str(ex)))
        finally:
            QTimer.singleShot(0, self._mic_reset)

    def _voice_done(self, digits):
        self._answer_entry.setText(digits)
        self._check_answer()

    def _voice_fail(self, msg):
        self._feedback_lbl.setText(msg)

    def _mic_reset(self):
        if _VOICE and hasattr(self, "_mic_btn"):
            self._mic_btn.setText("🎙️")