from PyQt5.QtWidgets import QStyledItemDelegate, QApplication
from PyQt5.QtGui import QColor, QPainter, QBrush
from PyQt5.QtCore import Qt, QSize

# Constants from theme_manager / review_screen
from theme_manager import get_palette as _get_palette
_DARK = _get_palette("dark")
C_BG = _DARK["C_BG"]
C_SURFACE = _DARK["C_SURFACE"]
C_CARD = _DARK["C_CARD"]
C_ACCENT = _DARK["C_ACCENT"]
C_GREEN = _DARK["C_GREEN"]
C_RED = _DARK["C_RED"]
C_YELLOW = _DARK["C_YELLOW"]
C_TEXT = _DARK["C_TEXT"]
C_SUBTEXT = _DARK["C_SUBTEXT"]
C_BORDER = _DARK["C_BORDER"]

QUEUE_ROLE = Qt.UserRole + 10
QUEUE_INDEX_ROLE = Qt.UserRole + 11

class QueueDelegate(QStyledItemDelegate):
    # Classic colors
    COLORS = {
        "current": {"bg": QColor(C_GREEN), "fg": QColor("#1E1E2E")},
        "done": {"bg": QColor("#2A3A2A"), "fg": QColor("#6A8A6A")},
        "pending": {"bg": QColor(C_SURFACE), "fg": QColor(C_TEXT)},
        "relearn": {"bg": QColor("#3A2A1A"), "fg": QColor("#E08030")},
        "peek": {"bg": QColor("#B83B3B"), "fg": QColor("#FFF1F1")},
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_theme = None
        self._cached_cols = None

    def _get_cols(self, theme: str, state: str) -> dict:
        # Rebuild color map only when theme changes — not every paint call
        if theme != self._cached_theme:
            from theme_manager import get_palette

            self._cached_theme = theme
            if theme in ("dojo", "tmnt"):
                p = get_palette(theme)
                self._cached_cols = {
                    "current": {"bg": QColor(p["C_ACCENT"]), "fg": QColor(p["C_BG"])},
                    "done": {
                        "bg": QColor("#0A0A12" if theme == "dojo" else p["C_CARD"]),
                        "fg": QColor("#3A3A5A" if theme == "dojo" else p["C_SUBTEXT"]),
                    },
                    "pending": {
                        "bg": QColor(p["C_SURFACE"]),
                        "fg": QColor(p["C_TEXT"]),
                    },
                    "relearn": {
                        "bg": QColor(
                            "#1A0A05"
                            if theme == "dojo"
                            else p.get("C_ORANGE", "#FF8040")
                        ),
                        "fg": QColor(
                            "#FF8040" if theme == "dojo" else p.get("C_BG", "#000")
                        ),
                    },
                    "peek": {
                        "bg": QColor("#2A0505" if theme == "dojo" else p["C_RED"]),
                        "fg": QColor("#FF6060" if theme == "dojo" else p["C_BG"]),
                    },
                }
            else:
                self._cached_cols = self.COLORS
        return self._cached_cols[state]

    def paint(self, painter, option, index):
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        state = index.data(QUEUE_ROLE) or "pending"
        cols = self._get_cols(theme, state)

        painter.save()
        r = option.rect.adjusted(2, 2, -2, -2)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cols["bg"]))
        painter.drawRoundedRect(r, 5, 5)
        if state == "current":
            painter.setBrush(QBrush(QColor("#1E1E2E")))
            painter.drawRect(r.left(), r.top() + 4, 4, r.height() - 8)
        painter.setPen(cols["fg"])
        font = painter.font()
        font.setBold(state == "current")
        painter.setFont(font)
        painter.drawText(r.adjusted(10, 0, -4, 0), Qt.AlignVCenter, index.data())
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 34)
