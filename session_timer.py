# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION TIMER  —  Anki Occlusion  v2
#
#  BEHAVIOUR
#  ─────────
#  • Counts time only while ReviewScreen is open.
#  • State persists in  ~/anki_timer_state.json  { "date": "…", "seconds": N }
#    → same-day restarts resume where they left off.
#    → new calendar day → resets to 0 automatically.
#  • On app close calls flush_to_journal() which writes / updates a dedicated
#    "focus_seconds" key in ~/anki_journal.json for today's entry, AND adds
#    a visible text block near the top of today's journal page:
#
#        ⏱ Focus today: 1h 24m
#
#    If the line already exists it is updated in place (no duplicates).
#
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import tempfile
from datetime import date

from PyQt5.QtCore import QObject, QEvent, QTimer, Qt
from PyQt5.QtWidgets import QLabel, QApplication, QWidget

# ── File paths ────────────────────────────────────────────────────────────────
_STATE_FILE = os.path.join(os.path.expanduser("~"), "anki_timer_state.json")
_JOURNAL_FILE = os.path.join(os.path.expanduser("~"), "anki_journal.json")

# Tag used to find & update the line so we never duplicate it
_JOURNAL_TAG = "\u23f1 Focus today:"

# Position + style of the focus line on the journal canvas
_TEXT_X = 60
_TEXT_Y = 80
_TEXT_SIZE = 15
_TEXT_COLOR = "#7C6AF7"  # accent purple — stands out clearly


# ─────────────────────────────────────────────────────────────────────────────
#  PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────


def _load_state() -> int:
    today = date.today().isoformat()
    if not os.path.exists(_STATE_FILE):
        return 0
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today:
            return max(0, int(data.get("seconds", 0)))
    except Exception:
        pass
    return 0


def _save_state(seconds: int):
    _atomic_write(_STATE_FILE, {"date": date.today().isoformat(), "seconds": seconds})


def _atomic_write(path: str, data: dict):
    dir_ = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
#  JOURNAL
# ─────────────────────────────────────────────────────────────────────────────


def _fmt_human(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def _load_journal():
    journal = {}
    if os.path.exists(_JOURNAL_FILE):
        try:
            with open(_JOURNAL_FILE, "r", encoding="utf-8") as f:
                journal = json.load(f)
        except Exception:
            journal = {}
    return journal


def _write_focus_to_journal_for_date(day: str, seconds: int):
    if seconds <= 0 or not day:
        return

    journal = _load_journal()

    # Normalise entry
    entry = journal.get(day, {})
    if isinstance(entry, list):
        entry = {"strokes": entry, "texts": []}
    if not isinstance(entry, dict):
        entry = {"strokes": [], "texts": []}

    entry["focus_seconds"] = seconds

    label = f"{_JOURNAL_TAG} {_fmt_human(seconds)}"
    text_obj = {
        "x": _TEXT_X,
        "y": _TEXT_Y,
        "text": label,
        "color": _TEXT_COLOR,
        "size": _TEXT_SIZE,
    }

    texts = entry.get("texts", [])
    if not isinstance(texts, list):
        texts = []

    idx = next(
        (
            i
            for i, t in enumerate(texts)
            if isinstance(t, dict) and str(t.get("text", "")).startswith(_JOURNAL_TAG)
        ),
        None,
    )
    if idx is not None:
        texts[idx] = text_obj
    else:
        texts.insert(0, text_obj)

    entry["texts"] = texts
    journal[day] = entry
    _atomic_write(_JOURNAL_FILE, journal)


def _write_focus_to_journal(seconds: int):
    _write_focus_to_journal_for_date(date.today().isoformat(), seconds)


# ─────────────────────────────────────────────────────────────────────────────
#  SESSION TIMER CLASS
# ─────────────────────────────────────────────────────────────────────────────


_ACTIVITY_EVENTS = frozenset(
    (
        QEvent.MouseMove,
        QEvent.HoverMove,
        QEvent.Wheel,
        QEvent.KeyPress,
        QEvent.MouseButtonPress,
        QEvent.MouseButtonRelease,
        QEvent.TabletMove,
        QEvent.TabletPress,
        QEvent.TabletRelease,
        QEvent.TouchBegin,
        QEvent.TouchUpdate,
    )
)


class _ActivityEventFilter(QObject):
    def __init__(self, timer):
        super().__init__()
        self._timer = timer

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ChildAdded:
            try:
                self._timer._enable_mouse_tracking(event.child())
            except Exception:
                pass
        elif event.type() in _ACTIVITY_EVENTS and self._timer._is_activity_scope(obj):
            self._timer.note_activity()
        return False


class SessionTimer:
    """
    Persistent per-day stopwatch.

    embed  self.label  in any layout.
    Call   flush_to_journal()  on app close.
    """

    def __init__(self, parent=None):
        self._current_day = date.today().isoformat()
        self._elapsed = _load_state()
        self._session_elapsed = 0
        self._idle_seconds = 0
        self._idle_limit_seconds = 60
        self._running = False
        self._activity_parent = parent
        self._activity_filter = _ActivityEventFilter(self)
        self._activity_filter_installed = False

        self.label = QLabel(self._make_text())
        self.label.setToolTip(
            "Time studied today  \u2022  pauses after 1 minute without app activity"
        )

        self.label_session = QLabel(self._fmt(self._session_elapsed))
        self.label_today = QLabel(self._fmt(self._elapsed))

        self._tick_timer = QTimer(parent)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self._save_timer = QTimer(parent)
        self._save_timer.setInterval(30_000)
        self._save_timer.timeout.connect(lambda: _save_state(self._elapsed))

    def note_activity(self):
        self._idle_seconds = 0

    def _is_activity_scope(self, obj) -> bool:
        root = self._activity_parent
        if root is None:
            return True
        cur = obj
        while cur is not None:
            if cur is root:
                return True
            try:
                cur = cur.parent()
            except Exception:
                return False
        return False

    def _enable_mouse_tracking(self, root=None):
        root = root or self._activity_parent
        if root is None:
            return
        if isinstance(root, QWidget):
            root.setMouseTracking(True)
            for child in root.findChildren(QWidget):
                child.setMouseTracking(True)

    def _install_activity_filter(self):
        if self._activity_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._enable_mouse_tracking()
        app.installEventFilter(self._activity_filter)
        self._activity_filter_installed = True
        self.note_activity()

    def _remove_activity_filter(self):
        if not self._activity_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._activity_filter)
        self._activity_filter_installed = False

    def _rollover_if_needed(self):
        today = date.today().isoformat()
        if today == self._current_day:
            return
        _write_focus_to_journal_for_date(self._current_day, self._elapsed)
        self._current_day = today
        self._elapsed = 0
        self.label.setText(self._make_text())
        self.label_today.setText(self._fmt(self._elapsed))
        _save_state(self._elapsed)

    def start(self):
        if not self._running:
            self._rollover_if_needed()
            self._install_activity_filter()
            self._running = True
            self._tick_timer.start()
            self._save_timer.start()

    def stop(self):
        if self._running:
            self._rollover_if_needed()
            self._running = False
            self._tick_timer.stop()
            self._save_timer.stop()
            self._remove_activity_filter()
            _save_state(self._elapsed)

    def flush_to_journal(self):
        self._rollover_if_needed()
        _save_state(self._elapsed)
        _write_focus_to_journal(self._elapsed)

    def elapsed_str(self) -> str:
        return self._fmt(self._elapsed)

    @property
    def elapsed_seconds(self) -> int:
        return self._elapsed

    def _tick(self):
        self._rollover_if_needed()

        # Check if application has focus (active window)
        if not QApplication.activeWindow():
            return

        self._idle_seconds += 1

        if self._idle_seconds == 120:
            QApplication.beep()

        if self._idle_seconds > self._idle_limit_seconds:
            return

        self._elapsed += 1
        self._session_elapsed += 1
        self.label.setText(self._make_text())
        self.label_session.setText(self._fmt(self._session_elapsed))
        self.label_today.setText(self._fmt(self._elapsed))

    def _make_text(self) -> str:
        return self._fmt(self._elapsed)

    @staticmethod
    def _fmt(secs: int) -> str:
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
