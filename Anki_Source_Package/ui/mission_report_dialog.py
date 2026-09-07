# -*- coding: utf-8 -*-
"""
ui/mission_report_dialog.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dedicated Full-Screen Mission Report Card view.
Displays comprehensive daily study metrics, rating breakdown, study rank,
and an interactive hierarchical collapsible deck tree.
Features full-page body-stack capture, complete background animation suspension
to eliminate CPU/GPU processing waste, robust global keyboard arrow day navigation,
and crisp typography.
"""

import os
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QScrollArea,
    QFrame,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QApplication,
    QCalendarWidget,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QDate, QSize, QEvent
from PyQt5.QtGui import QFont, QColor, QIcon, QPainter, QCursor

from theme_manager import get_palette, is_retro_theme
from services.activity_stats import (
    get_daily_activity_stats,
    get_daily_focus_seconds,
    calculate_study_rank,
)


def _is_ninja() -> bool:
    try:
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        return is_retro_theme(theme) or theme == "dojo"
    except Exception:
        return False


class _ReportDatePicker(QDialog):
    date_selected = pyqtSignal(str)

    def __init__(self, current_date_str, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        app = QApplication.instance()
        theme = getattr(app, "_active_theme", "classic")
        p = get_palette(theme)
        
        c_bg = p.get("C_SURFACE", "#14141F")
        c_border = p.get("C_BORDER", "#1A1A26")
        c_text = p.get("C_TEXT", "#E0E0FF")
        c_card = p.get("C_CARD", "#1E1E2E")
        c_accent = p.get("C_ACCENT", "#72FF4F")
        c_subtext = p.get("C_SUBTEXT", "#5F627D")

        self.setStyleSheet(f"""
            QDialog {{ background:{c_bg}; border:2px solid {c_border}; border-radius:10px; }}
            QCalendarWidget QWidget {{ background:{c_bg}; color:{c_text}; }}
            QCalendarWidget QAbstractItemView:enabled {{
                background:{c_card}; color:{c_text};
                selection-background-color:{c_accent};
                selection-color:#000000;
                font-size: 13px;
            }}
            QCalendarWidget QToolButton {{
                background:{c_card}; color:{c_text};
                border:none; border-radius:4px; padding:6px 12px;
                font-weight:bold; font-size:14px;
            }}
            QCalendarWidget QToolButton:hover {{ background:{c_accent}; color:#000000; }}
            QCalendarWidget #qt_calendar_navigationbar {{
                background:{c_bg}; padding:6px;
            }}
            QCalendarWidget QAbstractItemView:disabled {{ color:{c_subtext}; }}
        """)
        L = QVBoxLayout(self)
        L.setContentsMargins(10, 10, 10, 10)
        cal = QCalendarWidget()
        cal.setGridVisible(False)
        cal.setMaximumDate(QDate.currentDate())
        try:
            qd = QDate.fromString(current_date_str, "yyyy-MM-dd")
            if qd.isValid():
                cal.setSelectedDate(qd)
        except Exception:
            pass
        cal.clicked.connect(
            lambda qd: (
                self.date_selected.emit(qd.toString("yyyy-MM-dd")),
                self.accept(),
            )
        )
        L.addWidget(cal)


class MissionReportDialog(QWidget):
    """Dedicated Full-Screen Daily Study Mission Report Card Page."""
    closed = pyqtSignal()

    def __init__(self, initial_date: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("mission_report_page")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        app = QApplication.instance()
        self._theme = getattr(app, "_active_theme", "classic")
        self._ninja = _is_ninja()
        self._p = get_palette(self._theme)

        self._current_date = initial_date or date.today().isoformat()
        self._filter_installed = False

        self._init_ui()
        self._load_date_data(self._current_date)

    def _init_ui(self):
        bg = self._p.get("C_BG", "#07070B" if self._ninja else "#1E1E2E")
        c_surface = self._p.get("C_SURFACE", "#0F0F17" if self._ninja else "#252538")
        c_text = self._p.get("C_TEXT", "#E0E0FF")
        c_border = self._p.get("C_BORDER", "#1A1A26")
        hf = self._p.get("header_font", "sans-serif").split(",")[0].strip("'")
        bf = self._p.get("body_font", "sans-serif").split(",")[0].strip("'")

        self.setStyleSheet(f"""
            QWidget#mission_report_page {{
                background-color: {bg};
                color: {c_text};
            }}
            QLabel {{
                color: {c_text};
                font-family: {bf}, 'Segoe UI', Arial;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. Top Header Bar (Full Width) ───────────────────────────────────
        top_frame = QFrame()
        top_frame.setFixedHeight(64)
        top_frame.setStyleSheet(f"""
            QFrame {{
                background: {c_surface};
                border-bottom: 1px solid {c_border};
            }}
        """)
        top_l = QHBoxLayout(top_frame)
        top_l.setContentsMargins(24, 0, 24, 0)
        top_l.setSpacing(14)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        lbl_title = QLabel("⛩ MISSION REPORT CARD" if self._ninja else "📊 DAILY MISSION REPORT")
        lbl_title.setStyleSheet(f"""
            color: {self._p.get('C_ACCENT', '#72FF4F')};
            font-family: {hf}, 'Segoe UI', Arial;
            font-size: 20px;
            font-weight: bold;
            letter-spacing: 2px;
        """)
        self._lbl_subtitle = QLabel("")
        self._lbl_subtitle.setStyleSheet(f"color: {self._p.get('C_SUBTEXT', '#888')}; font-size: 12px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(self._lbl_subtitle)
        top_l.addLayout(title_box)

        top_l.addStretch()

        # Date controls (Using crystal-clear ASCII/Unicode fonts)
        self._btn_prev = QPushButton("◀")
        self._btn_prev.setFixedSize(36, 36)
        self._btn_prev.setCursor(Qt.PointingHandCursor)
        self._btn_prev.setToolTip("Previous Day (← Left Arrow / A)")
        self._btn_prev.setStyleSheet(self._btn_style_secondary(font_size=12, bold=True))
        self._btn_prev.clicked.connect(self._go_prev)

        self._btn_date = QPushButton()
        self._btn_date.setFixedHeight(36)
        self._btn_date.setCursor(Qt.PointingHandCursor)
        self._btn_date.setToolTip("Click to pick date from calendar")
        self._btn_date.setStyleSheet(self._btn_style_secondary(font_size=13, bold=True))
        self._btn_date.clicked.connect(self._open_date_picker)

        self._btn_next = QPushButton("▶")
        self._btn_next.setFixedSize(36, 36)
        self._btn_next.setCursor(Qt.PointingHandCursor)
        self._btn_next.setToolTip("Next Day (→ Right Arrow / D)")
        self._btn_next.setStyleSheet(self._btn_style_secondary(font_size=12, bold=True))
        self._btn_next.clicked.connect(self._go_next)

        btn_today = QPushButton("TODAY")
        btn_today.setFixedHeight(36)
        btn_today.setCursor(Qt.PointingHandCursor)
        btn_today.setToolTip("Jump to Today (T)")
        btn_today.setStyleSheet(self._btn_style_accent(font_size=12))
        btn_today.clicked.connect(self._go_today)

        top_l.addWidget(self._btn_prev)
        top_l.addWidget(self._btn_date)
        top_l.addWidget(self._btn_next)
        top_l.addWidget(btn_today)

        btn_close = QPushButton("✕ CLOSE")
        btn_close.setFixedHeight(36)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setToolTip("Exit Mission Report (Esc)")
        btn_close.setStyleSheet(self._btn_style_close())
        btn_close.clicked.connect(self._on_close)
        top_l.addWidget(btn_close)

        root.addWidget(top_frame)

        # ── Scroll Area for Full-Screen Content ──────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 24, 32, 24)
        cl.setSpacing(20)

        # Empty state label
        self._lbl_empty = QLabel("No study activity or focus time recorded for this day.")
        self._lbl_empty.setAlignment(Qt.AlignCenter)
        self._lbl_empty.setStyleSheet(f"color: {self._p.get('C_SUBTEXT', '#888')}; font-size: 18px; padding: 120px 20px;")
        cl.addWidget(self._lbl_empty)

        # Main stats container
        self._stats_container = QWidget()
        self._stats_container.setStyleSheet("background: transparent;")
        scl = QVBoxLayout(self._stats_container)
        scl.setContentsMargins(0, 0, 0, 0)
        scl.setSpacing(20)

        # ── 2. Top Metric Cards (Focus Time, Cards, Retention, Rank) ─────────
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(18)

        self._card_focus, self._lbl_val_focus = self._create_metric_card("⏱ FOCUS TIME", "0m")
        self._card_cards, self._lbl_val_cards = self._create_metric_card("🎴 CARDS REVIEWED", "0")
        self._card_ret, self._lbl_val_ret = self._create_metric_card("🎯 RETENTION", "0%")
        self._card_rank, self._lbl_val_rank = self._create_metric_card("🥋 MISSION RANK", "REST DAY", subtext="Meditation")

        metrics_row.addWidget(self._card_focus)
        metrics_row.addWidget(self._card_cards)
        metrics_row.addWidget(self._card_ret)
        metrics_row.addWidget(self._card_rank)
        scl.addLayout(metrics_row)

        # ── 3. Rating Breakdown Progress Bars ─────────────────────────────────
        breakdown_frame = QFrame()
        breakdown_frame.setStyleSheet(self._card_box_style())
        b_layout = QVBoxLayout(breakdown_frame)
        b_layout.setContentsMargins(22, 20, 22, 20)
        b_layout.setSpacing(14)

        b_header = QLabel("⚡ RATING BREAKDOWN" if self._ninja else "📊 Rating Breakdown")
        b_header.setStyleSheet(f"color: {self._p.get('C_ACCENT', '#72FF4F')}; font-weight: bold; font-size: 15px; letter-spacing: 1.5px;")
        b_layout.addWidget(b_header)

        self._rating_bars = {}
        rating_defs = [
            ("again", "AGAIN", self._p.get("C_RED", "#FF5555")),
            ("hard", "HARD", self._p.get("C_ORANGE", "#FFB86C")),
            ("good", "GOOD", self._p.get("C_GREEN", "#50FA7B")),
            ("easy", "EASY", self._p.get("C_YELLOW", "#F1FA8C")),
            ("perfect", "PERFECT", self._p.get("C_PURPLE", "#BD93F9")),
        ]

        for key, name, color in rating_defs:
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 3, 0, 3)
            rl.setSpacing(16)

            lbl_name = QLabel(name if self._ninja else name.capitalize())
            lbl_name.setFixedWidth(110)
            lbl_name.setStyleSheet(f"color: {self._p.get('C_TEXT', '#FFF')}; font-size: 14px; font-weight: bold;")

            bar = QProgressBar()
            bar.setFixedHeight(14)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"""
                QProgressBar {{ background: {self._p.get('C_BORDER', '#333')}; border: none; border-radius: 7px; }}
                QProgressBar::chunk {{ background: {color}; border-radius: 7px; }}
            """)

            lbl_val = QLabel("0 (0%)")
            lbl_val.setFixedWidth(130)
            lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_val.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")

            rl.addWidget(lbl_name)
            rl.addWidget(bar, stretch=1)
            rl.addWidget(lbl_val)

            b_layout.addWidget(row)
            self._rating_bars[key] = (bar, lbl_val)

        scl.addWidget(breakdown_frame)

        # ── 4. Hierarchical Collapsible Deck Tree ─────────────────────────────
        tree_frame = QFrame()
        tree_frame.setStyleSheet(self._card_box_style())
        t_layout = QVBoxLayout(tree_frame)
        t_layout.setContentsMargins(22, 20, 22, 20)
        t_layout.setSpacing(14)

        tree_header_row = QHBoxLayout()
        self._lbl_decks_title = QLabel("🗂️ DECKS COVERED")
        self._lbl_decks_title.setStyleSheet(f"color: {self._p.get('C_ACCENT', '#72FF4F')}; font-weight: bold; font-size: 15px; letter-spacing: 1.5px;")
        tree_header_row.addWidget(self._lbl_decks_title)
        tree_header_row.addStretch()

        btn_expand_all = QPushButton("▾ Expand All")
        btn_expand_all.setFixedHeight(30)
        btn_expand_all.setCursor(Qt.PointingHandCursor)
        btn_expand_all.setStyleSheet(self._btn_style_small(font_size=12))
        btn_expand_all.clicked.connect(lambda: self._tree_widget.expandAll())

        btn_collapse_all = QPushButton("▸ Collapse All")
        btn_collapse_all.setFixedHeight(30)
        btn_collapse_all.setCursor(Qt.PointingHandCursor)
        btn_collapse_all.setStyleSheet(self._btn_style_small(font_size=12))
        btn_collapse_all.clicked.connect(lambda: self._tree_widget.collapseAll())

        tree_header_row.addWidget(btn_expand_all)
        tree_header_row.addWidget(btn_collapse_all)
        t_layout.addLayout(tree_header_row)

        # QTreeWidget for Hierarchical Structure (Large full screen styling)
        self._tree_widget = QTreeWidget()
        self._tree_widget.setHeaderLabels(["Deck / Topic", "Time Spent", "Cards Completed"])
        self._tree_widget.setColumnCount(3)
        self._tree_widget.header().setStretchLastSection(False)
        self._tree_widget.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree_widget.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self._tree_widget.setColumnWidth(1, 150)
        self._tree_widget.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self._tree_widget.setColumnWidth(2, 220)
        hdr = self._tree_widget.headerItem()
        if hdr:
            hdr.setTextAlignment(0, Qt.AlignLeft | Qt.AlignVCenter)
            hdr.setTextAlignment(1, Qt.AlignCenter | Qt.AlignVCenter)
            hdr.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        self._tree_widget.setAnimated(True)
        self._tree_widget.setIndentation(32)
        self._tree_widget.setMinimumHeight(340)

        c_card = self._p.get("C_CARD", "#14141F")
        c_accent = self._p.get("C_ACCENT", "#72FF4F")
        c_purple = self._p.get("C_PURPLE", "#A86CFF")

        self._tree_widget.setStyleSheet(f"""
            QTreeWidget {{
                background: {c_card};
                border: 1px solid {c_border};
                border-radius: 8px;
                padding: 12px 14px;
                color: {c_text};
                font-size: 15px;
            }}
            QTreeWidget::item {{
                padding: 9px 10px;
                border-radius: 5px;
                margin: 2px 0px;
            }}
            QTreeWidget::item:hover {{
                background: rgba(114, 255, 79, 0.08);
            }}
            QTreeWidget::item:selected {{
                background: rgba(168, 108, 255, 0.2);
                color: {c_text};
            }}
            QHeaderView::section {{
                background: transparent;
                color: {self._p.get('C_SUBTEXT', '#888')};
                border: none;
                border-bottom: 1px solid {c_border};
                padding: 8px 12px;
                font-weight: bold;
                font-size: 14px;
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                border-image: none;
                image: none;
            }}
        """)
        t_layout.addWidget(self._tree_widget)
        scl.addWidget(tree_frame)

        # ── 5. Bottom Action Bar (Integrated Inside Content) ───────────────────
        bot_bar = QHBoxLayout()
        bot_bar.setContentsMargins(0, 10, 0, 10)
        bot_bar.setSpacing(14)

        self._lbl_copied_status = QLabel("")
        self._lbl_copied_status.setStyleSheet(f"color: {self._p.get('C_GREEN', '#50FA7B')}; font-weight: bold; font-size: 14px;")
        bot_bar.addWidget(self._lbl_copied_status)
        bot_bar.addStretch()

        btn_copy = QPushButton("📋 Copy Summary")
        btn_copy.setFixedHeight(40)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.setStyleSheet(self._btn_style_secondary(font_size=13))
        btn_copy.clicked.connect(self._copy_summary_to_clipboard)
        bot_bar.addWidget(btn_copy)

        btn_bottom_close = QPushButton("✕ Close Report")
        btn_bottom_close.setFixedHeight(40)
        btn_bottom_close.setMinimumWidth(130)
        btn_bottom_close.setCursor(Qt.PointingHandCursor)
        btn_bottom_close.setStyleSheet(self._btn_style_accent(font_size=13))
        btn_bottom_close.clicked.connect(self._on_close)
        bot_bar.addWidget(btn_bottom_close)

        scl.addLayout(bot_bar)

        cl.addWidget(self._stats_container)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    def _create_metric_card(self, title: str, initial_val: str, subtext: str = None):
        card = QFrame()
        card.setStyleSheet(self._card_box_style())
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(6)

        lbl_hdr = QLabel(title)
        lbl_hdr.setAlignment(Qt.AlignCenter)
        lbl_hdr.setStyleSheet(f"color: {self._p.get('C_SUBTEXT', '#888')}; font-size: 13px; font-weight: bold; letter-spacing: 0.8px;")

        lbl_val = QLabel(initial_val)
        lbl_val.setAlignment(Qt.AlignCenter)
        lbl_val.setStyleSheet(f"color: {self._p.get('C_TEXT', '#FFF')}; font-size: 28px; font-weight: bold;")

        cl.addWidget(lbl_hdr)
        cl.addWidget(lbl_val)

        if subtext:
            lbl_sub = QLabel(subtext)
            lbl_sub.setAlignment(Qt.AlignCenter)
            lbl_sub.setStyleSheet(f"color: {self._p.get('C_SUBTEXT', '#888')}; font-size: 12px;")
            cl.addWidget(lbl_sub)
            card._sub_label = lbl_sub

        return card, lbl_val

    def _load_date_data(self, date_str: str):
        self._current_date = date_str
        self._lbl_copied_status.setText("")

        # Format date for display
        try:
            d_obj = datetime.strptime(date_str, "%Y-%m-%d")
            display_date = d_obj.strftime("%A, %d %b %Y")
        except Exception:
            display_date = date_str

        self._btn_date.setText(f"📅  {display_date}")
        self._lbl_subtitle.setText(f"Study statistics and mission debrief for {display_date}")

        stats = get_daily_activity_stats(date_str)
        focus_secs = get_daily_focus_seconds(date_str)

        has_activity = (stats["total"] > 0) or (focus_secs > 0)

        if not has_activity:
            self._lbl_empty.show()
            self._stats_container.hide()
            return

        self._lbl_empty.hide()
        self._stats_container.show()

        # 1. Focus Time
        h, rem = divmod(focus_secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            time_str = f"{h}h {m}m"
        elif m:
            time_str = f"{m}m"
        else:
            time_str = f"{s}s"
        self._lbl_val_focus.setText(time_str)

        # 2. Total Cards
        self._lbl_val_cards.setText(str(stats["total"]))

        # 3. Retention Rate
        retention = stats["retention"]
        self._lbl_val_ret.setText(f"{retention}%")
        green = self._p.get("C_GREEN", "#50FA7B")
        yellow = self._p.get("C_YELLOW", "#F1FA8C")
        red = self._p.get("C_RED", "#FF5555")
        ret_color = green if retention >= 80 else yellow if retention >= 60 else red
        self._lbl_val_ret.setStyleSheet(f"color: {ret_color}; font-size: 28px; font-weight: bold;")

        # 4. Rank Badge
        rank_info = calculate_study_rank(stats["total"], retention)
        self._lbl_val_rank.setText(rank_info["rank"])
        self._lbl_val_rank.setStyleSheet(f"color: {rank_info['color']}; font-size: 24px; font-weight: bold;")
        if hasattr(self._card_rank, "_sub_label"):
            self._card_rank._sub_label.setText(rank_info["title"])
            self._card_rank._sub_label.setStyleSheet(f"color: {rank_info['color']}; font-size: 12px;")

        # 5. Rating Breakdown
        total_rated = (
            stats["again"]
            + stats["hard"]
            + stats["good"]
            + stats["easy"]
            + stats["perfect"]
        )
        for rating_key in ["again", "hard", "good", "easy", "perfect"]:
            count = stats[rating_key]
            bar, lbl_val = self._rating_bars[rating_key]
            bar.setRange(0, total_rated if total_rated > 0 else 1)
            bar.setValue(count)
            pct = round(count / total_rated * 100) if total_rated > 0 else 0
            lbl_val.setText(f"{count} ({pct}%)")

        # 6. Populate Deck Tree
        self._tree_widget.clear()
        hdr = self._tree_widget.headerItem()
        if hdr:
            hdr.setTextAlignment(0, Qt.AlignLeft | Qt.AlignVCenter)
            hdr.setTextAlignment(1, Qt.AlignCenter | Qt.AlignVCenter)
            hdr.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        total_deck_reviews = sum(node["total_reviews"] for node in stats["tree"])
        total_deck_secs = sum(node.get("total_seconds", 0) for node in stats["tree"])
        from services.activity_stats import format_activity_duration
        deck_time_formatted = format_activity_duration(total_deck_secs) if total_deck_secs > 0 else time_str
        self._lbl_decks_title.setText(
            f"🗂️ DECKS COVERED ({len(stats['tree'])} Parent Topics · {total_deck_reviews} Cards Completed · ⏱ {deck_time_formatted})"
        )

        def _add_tree_node(parent_item, node_data):
            name = node_data.get("name", "Unnamed Deck")
            total_revs = node_data.get("total_reviews", 0)
            self_revs = node_data.get("self_reviews", 0)
            total_secs = node_data.get("total_seconds", 0)
            node_time_str = node_data.get("time_str", "0s")
            has_children = bool(node_data.get("children"))

            # Prefix icon
            prefix = "📁 " if has_children else "🎴 "
            display_text = f"{prefix}{name}"

            if parent_item is None:
                item = QTreeWidgetItem(self._tree_widget)
            else:
                item = QTreeWidgetItem(parent_item)

            item.setText(0, display_text)
            item.setText(1, f"⏱ {node_time_str}")
            item.setText(2, f"{total_revs} card(s) completed")
            item.setTextAlignment(1, Qt.AlignCenter | Qt.AlignVCenter)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)

            # Styling for parent vs leaf
            if has_children:
                font = item.font(0)
                font.setBold(True)
                font.setPointSize(11)
                item.setFont(0, font)
                item.setFont(1, font)
                item.setFont(2, font)
                item.setForeground(0, QColor(self._p.get("C_TEXT", "#FFF")))
                item.setForeground(1, QColor(self._p.get("C_YELLOW", "#F1FA8C")))
                item.setForeground(2, QColor(self._p.get("C_ACCENT", "#72FF4F")))
            else:
                font = item.font(0)
                font.setPointSize(11)
                item.setFont(0, font)
                item.setFont(1, font)
                item.setFont(2, font)
                item.setForeground(0, QColor(self._p.get("C_TEXT", "#DDD")))
                item.setForeground(1, QColor(self._p.get("C_YELLOW", "#F1FA8C")))
                item.setForeground(2, QColor(self._p.get("C_PURPLE", "#BD93F9")))

            for child in node_data["children"]:
                _add_tree_node(item, child)

        for top_node in stats["tree"]:
            _add_tree_node(None, top_node)

        # By default, keep tree collapsed (unexpanded)
        self._tree_widget.collapseAll()

    # ── Animation Suspension & Lifecycle ──────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from ui.canvas.retro_effects import suspend_animations
            suspend_animations(self)
        except Exception:
            pass

        # Install application-wide event filter so arrow keys always work
        app = QApplication.instance()
        if app and not self._filter_installed:
            app.installEventFilter(self)
            self._filter_installed = True

    def hideEvent(self, event):
        app = QApplication.instance()
        if app and self._filter_installed:
            app.removeEventFilter(self)
            self._filter_installed = False

        try:
            from ui.canvas.retro_effects import resume_animations
            resume_animations(self)
        except Exception:
            pass
        super().hideEvent(event)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app and self._filter_installed:
            app.removeEventFilter(self)
            self._filter_installed = False

        try:
            from ui.canvas.retro_effects import resume_animations
            resume_animations(self)
        except Exception:
            pass
        super().closeEvent(event)

    def _on_close(self):
        self.closed.emit()

    # ── Date Navigation Handlers ──────────────────────────────────────────────

    def _go_prev(self):
        try:
            d = datetime.strptime(self._current_date, "%Y-%m-%d").date()
            prev_d = (d - timedelta(days=1)).isoformat()
            self._load_date_data(prev_d)
        except Exception:
            pass

    def _go_next(self):
        try:
            d = datetime.strptime(self._current_date, "%Y-%m-%d").date()
            if d < date.today():
                next_d = (d + timedelta(days=1)).isoformat()
                self._load_date_data(next_d)
        except Exception:
            pass

    def _go_today(self):
        self._load_date_data(date.today().isoformat())

    def _open_date_picker(self):
        picker = _ReportDatePicker(self._current_date, self)
        picker.date_selected.connect(self._load_date_data)
        # Position below the date button
        pos = self._btn_date.mapToGlobal(self._btn_date.rect().bottomLeft())
        picker.move(pos)
        picker.exec_()

    # ── Global KeyPress Event Filter (Arrow Keys for Day Navigation) ─────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and self.isVisible():
            key = event.key()
            # Left arrow / A key -> Previous day
            if key in (Qt.Key_Left, Qt.Key_A):
                self._go_prev()
                return True
            # Right arrow / D key -> Next day
            elif key in (Qt.Key_Right, Qt.Key_D):
                self._go_next()
                return True
            # T / Home -> Today
            elif key in (Qt.Key_T, Qt.Key_Home):
                self._go_today()
                return True
            # Esc / Ctrl+R -> Close
            elif key == Qt.Key_Escape or ((event.modifiers() & Qt.ControlModifier) and key == Qt.Key_R):
                self._on_close()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if (mods & Qt.ControlModifier) and key == Qt.Key_R:
            self._on_close()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_A):
            self._go_prev()
            event.accept()
            return
        elif key in (Qt.Key_Right, Qt.Key_D):
            self._go_next()
            event.accept()
            return
        elif key in (Qt.Key_T, Qt.Key_Home):
            self._go_today()
            event.accept()
            return
        elif key == Qt.Key_Escape:
            self._on_close()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── Clipboard Action ──────────────────────────────────────────────────────

    def _copy_summary_to_clipboard(self):
        stats = get_daily_activity_stats(self._current_date)
        focus_secs = get_daily_focus_seconds(self._current_date)

        h, rem = divmod(focus_secs, 3600)
        m, s = divmod(rem, 60)
        time_str = f"{h}h {m}m" if h else f"{m}m" if m else f"{s}s"

        rank = calculate_study_rank(stats["total"], stats["retention"])

        lines = [
            f"🎯 Mission Report — {self._current_date}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⏱ Focus Time: {time_str}",
            f"🎴 Cards Reviewed: {stats['total']}",
            f"🎯 Retention Rate: {stats['retention']}%",
            f"🥋 Study Rank: {rank['rank']} ({rank['title']})",
            f"",
            f"📊 Ratings:",
            f"  Again: {stats['again']} | Hard: {stats['hard']} | Good: {stats['good']} | Easy: {stats['easy']} | Perfect: {stats['perfect']}",
            f"",
            f"🗂️ Decks Studied:",
        ]

        def _format_tree(nodes, depth=0):
            for n in nodes:
                indent = "  " * depth
                t_str = n.get("time_str", "0s")
                lines.append(f"{indent}• {n['name']}: ⏱ {t_str} · {n['total_reviews']} review(s)")
                _format_tree(n["children"], depth + 1)

        _format_tree(stats["tree"])

        text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self._lbl_copied_status.setText("✓ Report copied to clipboard!")

    # ── Style Helpers ─────────────────────────────────────────────────────────

    def _card_box_style(self):
        c_card = self._p.get("C_CARD", "#14141F")
        c_border = self._p.get("C_BORDER", "#1A1A26")
        return f"""
            QFrame {{
                background: {c_card};
                border: 1px solid {c_border};
                border-radius: 8px;
            }}
        """

    def _btn_style_accent(self, font_size=12):
        c_accent = self._p.get("C_ACCENT", "#72FF4F")
        return f"""
            QPushButton {{
                background: {c_accent};
                color: #07070B;
                border: none;
                border-radius: 5px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: {font_size}px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """

    def _btn_style_secondary(self, font_size=12, bold=False):
        c_card = self._p.get("C_CARD", "#14141F")
        c_text = self._p.get("C_TEXT", "#E0E0FF")
        c_border = self._p.get("C_BORDER", "#1A1A26")
        c_accent = self._p.get("C_ACCENT", "#72FF4F")
        weight = "bold" if bold else "normal"
        return f"""
            QPushButton {{
                background: {c_card};
                color: {c_text};
                border: 1px solid {c_border};
                border-radius: 5px;
                padding: 6px 14px;
                font-size: {font_size}px;
                font-weight: {weight};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QPushButton:hover {{
                border-color: {c_accent};
                color: {c_accent};
            }}
        """

    def _btn_style_small(self, font_size=11):
        c_card = self._p.get("C_CARD", "#14141F")
        c_sub = self._p.get("C_SUBTEXT", "#888")
        c_border = self._p.get("C_BORDER", "#1A1A26")
        c_accent = self._p.get("C_ACCENT", "#72FF4F")
        return f"""
            QPushButton {{
                background: {c_card};
                color: {c_sub};
                border: 1px solid {c_border};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: {font_size}px;
            }}
            QPushButton:hover {{
                border-color: {c_accent};
                color: {c_accent};
            }}
        """

    def _btn_style_close(self):
        c_card = self._p.get("C_CARD", "#14141F")
        c_sub = self._p.get("C_SUBTEXT", "#888")
        c_border = self._p.get("C_BORDER", "#1A1A26")
        c_red = self._p.get("C_RED", "#FF5555")
        return f"""
            QPushButton {{
                background: {c_card};
                color: {c_sub};
                border: 1px solid {c_border};
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {c_red};
                color: {c_red};
            }}
        """
