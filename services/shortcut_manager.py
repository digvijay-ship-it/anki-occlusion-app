from dataclasses import dataclass

from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QKeySequence


SETTINGS_ORG = "AnkiOcclusion"
SETTINGS_APP = "App"
SETTINGS_PREFIX = "shortcuts"


@dataclass(frozen=True)
class ShortcutAction:
    action_id: str
    context: str
    label: str
    default: str


SHORTCUT_ACTIONS = (
    ShortcutAction("home.save", "Home", "Save now", "Ctrl+S"),
    ShortcutAction("home.undo", "Home", "Undo deck/card change", "Ctrl+Z"),
    ShortcutAction("home.redo", "Home", "Redo deck/card change", "Ctrl+Y"),
    ShortcutAction("home.music_toggle", "Home", "Toggle music", "M"),
    ShortcutAction("home.music_next", "Home", "Next music track", "N"),
    ShortcutAction("review.fullscreen", "Review", "Toggle fullscreen", "F11"),
    ShortcutAction("review.cancel", "Review", "Leave review", "Esc"),
    ShortcutAction("review.reveal", "Review", "Reveal answer", "Space"),
    ShortcutAction("review.rate_again", "Review", "Rate Again", "1"),
    ShortcutAction("review.rate_hard", "Review", "Rate Hard", "2"),
    ShortcutAction("review.rate_good", "Review", "Rate Good", "3"),
    ShortcutAction("review.rate_easy", "Review", "Rate Easy", "4"),
    ShortcutAction("review.rate_perfect", "Review", "Rate Perfect", "5"),
    ShortcutAction("review.zoom_in", "Review", "Zoom in", "Ctrl++"),
    ShortcutAction("review.zoom_out", "Review", "Zoom out", "Ctrl+-"),
    ShortcutAction("review.zoom_reset", "Review", "Reset zoom", "Ctrl+0"),
    ShortcutAction("review.resize_fit", "Review", "Resize to fit", "R"),
    ShortcutAction("review.center", "Review", "Center current mask", "C"),
    ShortcutAction("review.undo", "Review", "Undo rating", "Ctrl+Z"),
    ShortcutAction("review.redo", "Review", "Redo rating", "Ctrl+Y"),
    ShortcutAction("review.open_pdf", "Review", "Open current PDF", "Ctrl+E"),
    ShortcutAction("review.open_folder", "Review", "Open PDF folder", "Ctrl+L"),
    ShortcutAction("review.copy_pdf", "Review", "Copy PDF path", "L"),
    ShortcutAction("review.annotate", "Review", "Anotate Scroll", "T"),
    ShortcutAction("review.edit_card", "Review", "Edit card", "E"),
    ShortcutAction("review.prev_page", "Review", "Previous page", "Left"),
    ShortcutAction("review.next_page", "Review", "Next page", "Right"),
    ShortcutAction("review.pen_toggle", "Review", "Toggle pen", "`"),
    ShortcutAction("review.pen_color", "Review", "Cycle pen color", "X"),
    ShortcutAction("review.pen_clear", "Review", "Clear pen marks", "Del"),
)


_ACTIONS_BY_ID = {action.action_id: action for action in SHORTCUT_ACTIONS}


def _settings():
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def _normalise_sequence(value: str) -> str:
    seq = QKeySequence(value or "")
    return seq.toString(QKeySequence.PortableText)


def default_shortcut(action_id: str) -> str:
    return _ACTIONS_BY_ID[action_id].default


def shortcut_text(action_id: str) -> str:
    settings = _settings()
    raw = settings.value(f"{SETTINGS_PREFIX}/{action_id}", default_shortcut(action_id))
    text = _normalise_sequence(str(raw or ""))
    return text or default_shortcut(action_id)


def set_shortcut(action_id: str, sequence: str):
    settings = _settings()
    text = _normalise_sequence(sequence)
    if not text:
        text = default_shortcut(action_id)
    settings.setValue(f"{SETTINGS_PREFIX}/{action_id}", text)


def reset_shortcuts():
    settings = _settings()
    settings.beginGroup(SETTINGS_PREFIX)
    settings.remove("")
    settings.endGroup()


def action_by_id(action_id: str) -> ShortcutAction:
    return _ACTIONS_BY_ID[action_id]


def all_actions():
    return SHORTCUT_ACTIONS


def _event_sequence_texts(event) -> set[str]:
    key = event.key()
    if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
        return set()
    mods = int(event.modifiers())
    texts = {
        QKeySequence(mods | int(key)).toString(QKeySequence.PortableText)
    }
    if key in (Qt.Key_Equal, Qt.Key_Plus) and event.modifiers() & Qt.ControlModifier:
        texts.add("Ctrl++")
        texts.add("Ctrl+=")
    return {_normalise_sequence(text) for text in texts if text}


def event_matches(event, action_id: str) -> bool:
    return shortcut_text(action_id) in _event_sequence_texts(event)
