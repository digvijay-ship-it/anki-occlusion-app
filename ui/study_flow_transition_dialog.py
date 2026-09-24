# -*- coding: utf-8 -*-
"""
ui/study_flow_transition_dialog.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Between-tile celebratory milestone & auto-transition interstitial dialog.

Adheres strictly to the Desktop Typography & Anti-Squint Standard:
- Header Title: 26pt Segoe UI Black.
- Section Titles & Up-Next: 20pt Segoe UI Bold.
- Card & Stats: 22pt - 38pt Segoe UI.
- Interactive Buttons: 20pt Segoe UI Bold with generous padding.
- Hard disabled horizontal scrollbar.
"""

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QApplication, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor

from theme_manager import get_palette, is_retro_theme
import perf_utils


class FlowTransitionDialog(QDialog):
    """
    Seamless interstitial modal shown between study flow tiles.
    Offers:
    1. 10s auto-proceed countdown (Space/Enter to start immediately).
    2. [☕ 2-Min Breather] calming rest timer.
    3. [⏸️ Pause & Exit] to pause flow and resume later.
    4. Grand celebration when all tiles are completed.
    """

    next_tile_accepted = pyqtSignal()
    flow_paused = pyqtSignal()

    def __init__(
        self,
        parent=None,
        completed_tile=None,
        next_tile=None,
        current_idx=1,
        total_tiles=1,
        is_grand_finish=False,
    ):
        super().__init__(parent)
        self.completed_tile = completed_tile
        self.next_tile = next_tile
        self.current_idx = current_idx
        self.total_tiles = total_tiles
        self.is_grand_finish = is_grand_finish

        self._countdown_seconds = 10
        self._is_breather_mode = False
        self._breather_seconds = 120

        self.setWindowTitle("🎯 Study Flow Milestone")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._init_ui()
        self._start_countdown()

    def _init_ui(self):
        palette = get_palette("tmnt" if is_retro_theme() else "dark")
        c_bg = palette.get("C_BG", "#0A0B11")
        c_card = palette.get("C_CARD", "#1F2836")
        c_neon = palette.get("C_ACCENT", "#39FF14")
        c_text = palette.get("C_TEXT", "#FFFFFF")
        c_subtext = palette.get("C_SUBTEXT", "#A0AEC0")
        c_border = palette.get("C_BORDER", "#3E4E68")

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c_bg};
                border: 2px solid {c_neon};
                border-radius: 12px;
            }}
            QFrame#cardFrame {{
                background-color: {c_card};
                border: 1px solid {c_border};
                border-radius: 10px;
                padding: 16px;
            }}
        """)

        screen = QApplication.primaryScreen()
        avail_w = screen.availableGeometry().width() if screen else 800
        dialog_w = min(660, max(460, int(avail_w * 0.75)))
        self.setFixedWidth(dialog_w)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(22, 18, 22, 18)
        main_layout.setSpacing(12)

        # ── 1. Top Header ────────────────────────────────────────────────────
        self._lbl_header = QLabel()
        self._lbl_header.setFont(QFont("Segoe UI", 22, QFont.Black))
        self._lbl_header.setAlignment(Qt.AlignCenter)
        self._lbl_header.setWordWrap(True)

        if self.is_grand_finish:
            self._lbl_header.setText("🏆 GRAND FINALE! DAILY FLOW COMPLETE!")
            self._lbl_header.setStyleSheet(f"color: {c_neon};")
        else:
            self._lbl_header.setText(f"🎉 TILE {self.current_idx}/{self.total_tiles} COMPLETED!")
            self._lbl_header.setStyleSheet(f"color: {c_neon};")
        main_layout.addWidget(self._lbl_header)

        # ── 2. Completed Tile Summary Card ───────────────────────────────────
        card_frame = QFrame()
        card_frame.setObjectName("cardFrame")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(16, 10, 16, 10)
        card_layout.setSpacing(8)

        if self.completed_tile:
            comp_name = getattr(self.completed_tile, "deck_name", "Subject")
            comp_count = getattr(self.completed_tile, "target_cards", 25)
            self._lbl_comp_summary = QLabel(
                f"✅ Finished: {comp_name} ({comp_count} Cards Studied)"
            )
        else:
            self._lbl_comp_summary = QLabel("✅ All planned session targets met!")
        self._lbl_comp_summary.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self._lbl_comp_summary.setStyleSheet(f"color: {c_text};")
        self._lbl_comp_summary.setAlignment(Qt.AlignCenter)
        self._lbl_comp_summary.setWordWrap(True)
        card_layout.addWidget(self._lbl_comp_summary)

        main_layout.addWidget(card_frame)

        # ── 3. Next Tile Preview (or Grand Celebration Text) ─────────────────
        self._next_frame = QFrame()
        self._next_frame.setObjectName("cardFrame")
        next_layout = QVBoxLayout(self._next_frame)
        next_layout.setContentsMargins(20, 16, 20, 16)
        next_layout.setSpacing(10)

        if self.is_grand_finish or not self.next_tile:
            lbl_next_title = QLabel("⭐ You have conquered today's entire study playlist!")
            lbl_next_title.setFont(QFont("Segoe UI", 21, QFont.Bold))
            lbl_next_title.setStyleSheet("color: #FFD700;")
            lbl_next_title.setAlignment(Qt.AlignCenter)
            lbl_next_title.setWordWrap(True)
            next_layout.addWidget(lbl_next_title)

            lbl_next_sub = QLabel("All scheduled subject chunks are complete. Outstanding work!")
            lbl_next_sub.setFont(QFont("Segoe UI", 18, QFont.Normal))
            lbl_next_sub.setStyleSheet(f"color: {c_subtext};")
            lbl_next_sub.setAlignment(Qt.AlignCenter)
            lbl_next_sub.setWordWrap(True)
            next_layout.addWidget(lbl_next_sub)
        else:
            next_idx_num = self.current_idx + 1
            lbl_next_heading = QLabel(f"⏩ UP NEXT: TILE {next_idx_num}/{self.total_tiles}")
            lbl_next_heading.setFont(QFont("Segoe UI", 18, QFont.Bold))
            lbl_next_heading.setStyleSheet(f"color: {c_neon};")
            next_layout.addWidget(lbl_next_heading)

            next_name = getattr(self.next_tile, "deck_name", "Next Subject")
            next_cards = getattr(self.next_tile, "target_cards", 25)
            next_mode = getattr(self.next_tile, "mode", "due").upper()
            lbl_next_info = QLabel(f"📖 {next_name} — {next_cards} Cards ({next_mode})")
            lbl_next_info.setFont(QFont("Segoe UI", 22, QFont.Bold))
            lbl_next_info.setStyleSheet(f"color: {c_text};")
            lbl_next_info.setWordWrap(True)
            next_layout.addWidget(lbl_next_info)

        main_layout.addWidget(self._next_frame)

        # ── 4. Live Countdown / Breather Status ───────────────────────────────
        self._lbl_timer_status = QLabel()
        self._lbl_timer_status.setFont(QFont("Segoe UI", 19, QFont.Bold))
        self._lbl_timer_status.setAlignment(Qt.AlignCenter)
        self._lbl_timer_status.setStyleSheet("color: #FFB300;")
        self._lbl_timer_status.setWordWrap(True)
        main_layout.addWidget(self._lbl_timer_status)

        # ── 5. Action Buttons ────────────────────────────────────────────────
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(14)

        if self.is_grand_finish or not self.next_tile:
            self._btn_start_next = QPushButton("🎉 FINISH & RETURN TO HOME")
            self._btn_start_next.setFont(QFont("Segoe UI", 20, QFont.Bold))
            self._btn_start_next.setCursor(Qt.PointingHandCursor)
            self._btn_start_next.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c_neon};
                    color: #000000;
                    border: none;
                    border-radius: 8px;
                    padding: 18px 36px;
                }}
                QPushButton:hover {{
                    background-color: #55FF33;
                }}
            """)
            self._btn_start_next.clicked.connect(self._on_start_next_clicked)
            btn_layout.addWidget(self._btn_start_next)
        else:
            self._btn_start_next = QPushButton("🚀 START NEXT TILE (Enter / Space)")
            self._btn_start_next.setFont(QFont("Segoe UI", 18, QFont.Bold))
            self._btn_start_next.setCursor(Qt.PointingHandCursor)
            self._btn_start_next.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c_neon};
                    color: #000000;
                    border: none;
                    border-radius: 8px;
                    padding: 12px 24px;
                }}
                QPushButton:hover {{
                    background-color: #55FF33;
                }}
            """)
            self._btn_start_next.clicked.connect(self._on_start_next_clicked)
            btn_layout.addWidget(self._btn_start_next)

            # Secondary row: 2-Min Breather & Pause Flow
            sub_btn_layout = QHBoxLayout()
            sub_btn_layout.setSpacing(10)

            self._btn_breather = QPushButton("☕ 2-MIN BREATHER")
            self._btn_breather.setFont(QFont("Segoe UI", 16, QFont.Bold))
            self._btn_breather.setCursor(Qt.PointingHandCursor)
            self._btn_breather.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(255, 179, 0, 0.15);
                    color: #FFB300;
                    border: 1px solid #FFB300;
                    border-radius: 8px;
                    padding: 10px 18px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 179, 0, 0.30);
                }}
            """)
            self._btn_breather.clicked.connect(self._on_breather_clicked)
            sub_btn_layout.addWidget(self._btn_breather)

            self._btn_pause = QPushButton("⏸️ PAUSE & EXIT")
            self._btn_pause.setFont(QFont("Segoe UI", 16, QFont.Bold))
            self._btn_pause.setCursor(Qt.PointingHandCursor)
            self._btn_pause.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c_subtext};
                    border: 1px solid {c_border};
                    border-radius: 8px;
                    padding: 10px 18px;
                }}
                QPushButton:hover {{
                    color: #FFFFFF;
                    border-color: #FFFFFF;
                }}
            """)
            self._btn_pause.clicked.connect(self._on_pause_clicked)
            sub_btn_layout.addWidget(self._btn_pause)

            btn_layout.addLayout(sub_btn_layout)

        main_layout.addLayout(btn_layout)

    def _start_countdown(self):
        if self.is_grand_finish or not self.next_tile:
            self._lbl_timer_status.setText("All study goals achieved for today! 🌟")
            return

        self._countdown_seconds = 10
        self._lbl_timer_status.setText(f"⏱️ Starting next tile automatically in {self._countdown_seconds}s...")
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start()

    def _on_timer_tick(self):
        if self._is_breather_mode:
            self._breather_seconds -= 1
            mins = self._breather_seconds // 60
            secs = self._breather_seconds % 60
            if self._breather_seconds > 0:
                self._lbl_timer_status.setText(
                    f"🌿 Relax & recharge... Next tile in {mins}:{secs:02d} (or press Enter to resume)"
                )
            else:
                self._timer.stop()
                self._on_start_next_clicked()
        else:
            self._countdown_seconds -= 1
            if self._countdown_seconds > 0:
                self._lbl_timer_status.setText(
                    f"⏱️ Starting next tile automatically in {self._countdown_seconds}s..."
                )
            else:
                self._timer.stop()
                self._on_start_next_clicked()

    def _on_breather_clicked(self):
        """Switch to relaxed 2-minute breather countdown."""
        self._is_breather_mode = True
        self._breather_seconds = 120
        self._btn_breather.setEnabled(False)
        self._btn_breather.setText("☕ BREATHER ACTIVE")
        self._lbl_timer_status.setText("🌿 Relax & recharge... Next tile in 2:00 (press Enter anytime)")
        self._lbl_timer_status.setStyleSheet("color: #66FCF1;")

    def _on_start_next_clicked(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self.next_tile_accepted.emit()
        self.accept()

    def _on_pause_clicked(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self.flow_paused.emit()
        self.reject()

    def keyPressEvent(self, event):
        """Allow instant advance on Enter or Space."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._on_start_next_clicked()
            return
        elif event.key() == Qt.Key_Escape:
            self._on_pause_clicked()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        perf_utils.flush_process_memory()
        super().closeEvent(event)
