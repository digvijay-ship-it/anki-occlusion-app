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
import weakref
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


def normalize_pdf_path(path: str) -> str:
    if not path:
        return ""
    return os.path.normpath(path).replace("\\", "/").lower()


def _load_state_dict() -> dict:
    today = date.today().isoformat()
    if not os.path.exists(_STATE_FILE):
        return {}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except Exception:
        pass
    return {}


def _load_state() -> int:
    state_dict = _load_state_dict()
    return max(0, int(state_dict.get("seconds", 0)))


def _save_state(seconds: int, pdf_seconds: dict = None, pdf_cards_today: dict = None, mask_seconds: dict = None, deck_seconds: dict = None):
    data = {
        "date": date.today().isoformat(),
        "seconds": seconds
    }
    if pdf_seconds is not None:
        data["pdf_seconds"] = pdf_seconds
    if pdf_cards_today is not None:
        data["pdf_cards_today"] = pdf_cards_today
    if mask_seconds is not None:
        data["mask_seconds"] = mask_seconds
    if deck_seconds is not None:
        data["deck_seconds"] = deck_seconds
    _atomic_write(_STATE_FILE, data)


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


def _write_focus_to_journal_for_date(day: str, seconds: int, deck_seconds: dict = None):
    if seconds < 0 or not day:
        return

    try:
        from services.journal_manager import _load_journal, _save_journal
        journal = _load_journal()
    except Exception as e:
        print(f"[ERROR][session_timer] Aborting write to journal to prevent data loss: {e}")
        return

    # Normalise entry
    entry = journal.get(day, {})
    if isinstance(entry, list):
        entry = {"strokes": entry, "texts": []}
    if not isinstance(entry, dict):
        entry = {"strokes": [], "texts": []}

    entry["focus_seconds"] = seconds
    if deck_seconds is not None:
        entry["deck_seconds"] = deck_seconds

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
    
    try:
        _save_journal(journal)
    except Exception as e:
        print(f"[ERROR][session_timer] Failed to save journal: {e}")


def _write_focus_to_journal(seconds: int, deck_seconds: dict = None):
    _write_focus_to_journal_for_date(date.today().isoformat(), seconds, deck_seconds)


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
        if event.type() in _ACTIVITY_EVENTS:
            # Fast O(1) bypass: if already marked active, skip redundant scope checks
            if self._timer._idle_seconds == 0:
                return False
            if self._timer._is_activity_scope(obj):
                self._timer.note_activity()
        return False


class SessionTimer:
    """
    Persistent per-day stopwatch.

    Embed self.label in any layout.
    Call flush_to_journal() on app close.
    """

    def __init__(self, parent=None):
        self._current_day = date.today().isoformat()
        self._elapsed = _load_state()
        state_dict = _load_state_dict()
        
        pdf_secs = state_dict.get("pdf_seconds", {})
        self._pdf_seconds = pdf_secs if isinstance(pdf_secs, dict) else {}
        pdf_cards = state_dict.get("pdf_cards_today", {})
        self._pdf_cards_today = pdf_cards if isinstance(pdf_cards, dict) else {}
        mask_secs = state_dict.get("mask_seconds", {})
        self._mask_seconds = mask_secs if isinstance(mask_secs, dict) else {}
        deck_secs = state_dict.get("deck_seconds", {})
        self._deck_seconds = deck_secs if isinstance(deck_secs, dict) else {}
        
        self._current_pdf = ""
        self._session_pdf_seconds = {}
        self._session_pdf_cards = {}
        self._current_mask = ""
        self._current_deck = ""
        self._session_deck_seconds = {}
        
        self._session_elapsed = 0
        self._card_visit_elapsed = 0
        self._idle_seconds = 0
        self._idle_limit_seconds = 180
        self._running = False
        self._activity_parent = parent
        self._scope_cache = weakref.WeakKeyDictionary()
        self._activity_filter = _ActivityEventFilter(self)
        self._activity_filter_installed = False

        self.label = QLabel(self._make_text())
        self.label.setToolTip(
            "Time studied today  \u2022  pauses after 3 minutes without app activity"
        )

        self.label_session = QLabel(self._fmt(self._session_elapsed))
        self.label_today = QLabel(self._fmt(self._elapsed))
        self.label_mask = QLabel(self._fmt(0))

        self._tick_timer = QTimer(parent)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self._save_timer = QTimer(parent)
        self._save_timer.setInterval(300_000)
        self._save_timer.timeout.connect(lambda: _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds))

    def note_activity(self):
        self._idle_seconds = 0

    def _is_activity_scope(self, obj) -> bool:
        root = self._activity_parent
        if root is None:
            return True
        try:
            return self._scope_cache[obj]
        except KeyError:
            pass
        except Exception:
            pass

        cur = obj
        in_scope = False
        while cur is not None:
            if cur is root:
                in_scope = True
                break
            try:
                cur = cur.parent()
            except Exception:
                break

        try:
            self._scope_cache[obj] = in_scope
        except Exception:
            pass
        return in_scope

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
        _write_focus_to_journal_for_date(self._current_day, self._elapsed, self._deck_seconds)
        self._current_day = today
        self._elapsed = 0
        self._pdf_seconds = {}
        self._pdf_cards_today = {}
        self._session_pdf_seconds = {}
        self._session_pdf_cards = {}
        self._mask_seconds = {}
        self._deck_seconds = {}
        self._session_deck_seconds = {}
        self._card_visit_elapsed = 0
        self.label.setText(self._make_text())
        self.label_today.setText(self._fmt(self._elapsed))
        self.label_mask.setText(self._fmt(0))
        _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)

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
            _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)

    def flush_to_journal(self):
        self._rollover_if_needed()
        _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)
        _write_focus_to_journal(self._elapsed, self._deck_seconds)

    def elapsed_str(self) -> str:
        return self._fmt(self._elapsed)

    @property
    def elapsed_seconds(self) -> int:
        return self._elapsed

    def set_current_pdf(self, pdf_path: str):
        self._current_pdf = normalize_pdf_path(pdf_path)

    def set_current_deck(self, deck_name: str):
        self._rollover_if_needed()
        self._current_deck = str(deck_name).strip() if deck_name else ""

    def get_current_deck_seconds(self) -> int:
        if not self._current_deck:
            return 0
        return self._deck_seconds.get(self._current_deck, 0)

    def set_current_mask(self, mask_key: str):
        self._rollover_if_needed()
        self._current_mask = mask_key or ""
        self._card_visit_elapsed = 0
        secs = self._mask_seconds.get(self._current_mask, 0) if self._current_mask else 0
        self.label_mask.setText(self._fmt(secs))
        _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)

    def get_current_mask_seconds(self) -> int:
        if not self._current_mask:
            return 0
        return self._mask_seconds.get(self._current_mask, 0)

    def reset_current_card_time(self) -> int:
        """
        Rewinds the time spent on the current card/mask back to 0,
        and deducts that elapsed time from today's focus time, session time,
        deck time, and PDF time.
        Returns the number of seconds rewound.
        """
        self._rollover_if_needed()
        deduct = 0
        if self._card_visit_elapsed > 0:
            deduct = self._card_visit_elapsed
        elif self._current_mask and self._mask_seconds.get(self._current_mask, 0) > 0:
            deduct = self._mask_seconds[self._current_mask]

        if deduct <= 0:
            if self._current_mask and self._current_mask in self._mask_seconds:
                self._mask_seconds[self._current_mask] = 0
            self.label_mask.setText(self._fmt(0))
            self._card_visit_elapsed = 0
            self._idle_seconds = 0
            return 0

        if self._current_mask:
            self._mask_seconds[self._current_mask] = max(0, self._mask_seconds.get(self._current_mask, 0) - deduct)

        self._elapsed = max(0, self._elapsed - deduct)
        self._session_elapsed = max(0, self._session_elapsed - deduct)

        if self._current_pdf:
            norm_path = normalize_pdf_path(self._current_pdf)
            if norm_path in self._pdf_seconds:
                self._pdf_seconds[norm_path] = max(0, self._pdf_seconds[norm_path] - deduct)
            if norm_path in self._session_pdf_seconds:
                self._session_pdf_seconds[norm_path] = max(0, self._session_pdf_seconds[norm_path] - deduct)

        if self._current_deck:
            if self._current_deck in self._deck_seconds:
                self._deck_seconds[self._current_deck] = max(0, self._deck_seconds[self._current_deck] - deduct)
            if self._current_deck in self._session_deck_seconds:
                self._session_deck_seconds[self._current_deck] = max(0, self._session_deck_seconds[self._current_deck] - deduct)

        self._card_visit_elapsed = 0
        self._idle_seconds = 0

        cur_mask_secs = self._mask_seconds.get(self._current_mask, 0) if self._current_mask else 0
        self.label_mask.setText(self._fmt(cur_mask_secs))
        self.label.setText(self._make_text())
        self.label_session.setText(self._fmt(self._session_elapsed))
        self.label_today.setText(self._fmt(self._elapsed))

        _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)
        _write_focus_to_journal(self._elapsed, self._deck_seconds)

        return deduct

    def record_card_review(self, pdf_path: str):
        if not pdf_path:
            return
        self._rollover_if_needed()
        norm_path = normalize_pdf_path(pdf_path)
        self._pdf_cards_today[norm_path] = self._pdf_cards_today.get(norm_path, 0) + 1
        self._session_pdf_cards[norm_path] = self._session_pdf_cards.get(norm_path, 0) + 1
        _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)

    def undo_card_review(self, pdf_path: str):
        if not pdf_path:
            return
        self._rollover_if_needed()
        norm_path = normalize_pdf_path(pdf_path)
        if norm_path in self._pdf_cards_today:
            self._pdf_cards_today[norm_path] = max(0, self._pdf_cards_today[norm_path] - 1)
        if norm_path in self._session_pdf_cards:
            self._session_pdf_cards[norm_path] = max(0, self._session_pdf_cards[norm_path] - 1)
        _save_state(self._elapsed, self._pdf_seconds, self._pdf_cards_today, self._mask_seconds, self._deck_seconds)

    def _tick(self):
        self._rollover_if_needed()

        # Check if application has focus (active window)
        # Relax this check to ensure the timer ticks if the application is still receiving user interaction.
        # If activeWindow is None but the user recently interacted (idle_seconds is very low), keep ticking.
        if not QApplication.activeWindow() and self._idle_seconds >= self._idle_limit_seconds:
            return

        self._idle_seconds += 1

        if self._idle_seconds == 240:
            QApplication.beep()

        if self._idle_seconds > self._idle_limit_seconds:
            return

        self._elapsed += 1
        self._session_elapsed += 1

        if self._current_pdf:
            norm_path = normalize_pdf_path(self._current_pdf)
            self._pdf_seconds[norm_path] = self._pdf_seconds.get(norm_path, 0) + 1
            self._session_pdf_seconds[norm_path] = self._session_pdf_seconds.get(norm_path, 0) + 1

        if self._current_deck:
            self._deck_seconds[self._current_deck] = self._deck_seconds.get(self._current_deck, 0) + 1
            self._session_deck_seconds[self._current_deck] = self._session_deck_seconds.get(self._current_deck, 0) + 1

        if self._current_mask:
            self._card_visit_elapsed += 1
            self._mask_seconds[self._current_mask] = self._mask_seconds.get(self._current_mask, 0) + 1
            self.label_mask.setText(self._fmt(self._mask_seconds[self._current_mask]))
        else:
            self.label_mask.setText(self._fmt(0))

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
