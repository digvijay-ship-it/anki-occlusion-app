from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy, QPushButton, QApplication, QProgressBar, QWidget
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

from theme_manager import get_palette as _get_palette

# Classic colors
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
C_GROUP = "#BD93F9"

DOJO = {
    "bg": "#07070B",
    "surface": "#0F0F17",
    "card": "#14141F",
    "accent": "#72FF4F",
    "accent2": "#A86CFF",
    "green": "#72FF4F",
    "red": "#FF4444",
    "yellow": "#FFD700",
    "text": "#E0E0FF",
    "subtext": "#5F627D",
    "border": "#1A1A26",
    "font": "'Orbitron', 'Share Tech Mono', monospace",
}

def _is_dojo() -> bool:
    app = QApplication.instance()
    theme = getattr(app, "_active_theme", "classic")
    from theme_manager import is_retro_theme
    return is_retro_theme(theme) or theme == "dojo"

class ReviewSessionSummaryDialog(QDialog):
    def __init__(self, rs, parent=None):
        dlg_parent = parent if isinstance(parent, QWidget) else (rs if isinstance(rs, QWidget) else None)
        super().__init__(dlg_parent)
        self.rs = rs
        self._setup_ui()

    def _setup_ui(self):
        app = QApplication.instance()
        theme_mode = getattr(app, "_active_theme", "classic")
        palette = _get_palette(theme_mode)

        bg = palette["C_BG"]
        surface = palette["C_SURFACE"]
        card = palette["C_CARD"]
        accent = palette["C_ACCENT"]
        green = palette["C_GREEN"]
        red = palette["C_RED"]
        yellow = palette["C_YELLOW"]
        text = palette["C_TEXT"]
        subtext = palette["C_SUBTEXT"]
        border = palette["C_BORDER"]
        orange = palette["C_ORANGE"]
        purple = palette["C_PURPLE"]
        font = palette["header_font"]
        body_font = palette["body_font"]

        from theme_manager import is_retro_theme
        dojo = is_retro_theme(theme_mode) or theme_mode == "dojo"

        # Calculate hover/pressed colors dynamically based on accent
        q_accent = QColor(accent)
        if q_accent.lightness() > 128:
            q_hover = q_accent.darker(110)
            q_pressed = q_accent.darker(125)
        else:
            q_hover = q_accent.lighter(110)
            q_pressed = q_accent.lighter(125)
        hover_color = q_hover.name()
        pressed_color = q_pressed.name()

        is_practice = getattr(self.rs, "is_practice", False) or getattr(getattr(self.rs, "mgr", None), "is_practice", False)
        session_ratings = getattr(getattr(self.rs, "mgr", None), "_session_ratings", [])

        again = hard = good = easy = perfect = 0
        if session_ratings:
            for entry in session_ratings:
                q = entry.get("quality", -1)
                if q == 1:
                    again += 1
                elif q == 3:
                    hard += 1
                elif q == 4:
                    good += 1
                elif q == 5:
                    easy += 1
                elif q == 6:
                    perfect += 1
        else:
            for _, _, sm2_obj in self.rs._items:
                q = sm2_obj.get("sm2_last_quality", -1)
                if q == 1:
                    again += 1
                elif q == 3:
                    hard += 1
                elif q == 4:
                    good += 1
                elif q == 5:
                    easy += 1
                elif q == 6:
                    perfect += 1

        total = again + hard + good + easy + perfect
        if total == 0 and self.rs._done > 0:
            total = self.rs._done
        retention = round((good + easy + perfect) / total * 100) if total else 0

        if is_practice:
            self.setWindowTitle("🎯 Practice Mode — Performance Report Card")
        else:
            self.setWindowTitle("Mission Complete" if dojo else "Session Complete")
        
        import os
        from session_timer import normalize_pdf_path
        pdf_paths = []
        if self.rs._items:
            for card, _, _ in self.rs._items:
                path = card.get("pdf_path", "")
                if path:
                    norm_path = normalize_pdf_path(path)
                    if norm_path not in pdf_paths:
                        pdf_paths.append(norm_path)
                        
        base_height = 510 if dojo else 470
        additional_height = len(pdf_paths) * 120
        self.setFixedSize(620, base_height + additional_height)
        if dojo:
            self.setStyleSheet(
                f"QDialog {{ background: {bg}; border: 1px solid {accent}; }}"
                f"QWidget {{ background: {bg}; }}"
                f"QLabel {{ color: {text}; background: transparent; }}"
            )
        else:
            self.setStyleSheet(
                f"QDialog {{ background: {bg}; }}"
                f"QLabel {{ color: {text}; background: transparent; }}"
            )
        L = QVBoxLayout(self)
        L.setContentsMargins(28, 28, 28, 28)
        L.setSpacing(18)

        # Title
        if is_practice:
            if dojo:
                if theme_mode == "arcanum":
                    title_text = "🔮  PRACTICE RITUAL REPORT"
                elif theme_mode in ("tmnt", "manhattan"):
                    title_text = "🐢  PRACTICE COMBAT REPORT"
                else:
                    title_text = "🎯  PRACTICE PERFORMANCE REPORT"
            else:
                title_text = "🎯  Practice Report Card"
        else:
            if dojo:
                if theme_mode == "manhattan":
                    title_text = "🐢  STAGE CLEAR"
                elif theme_mode == "arcanum":
                    title_text = "🔮  RITUAL COMPLETE"
                elif theme_mode == "tmnt":
                    title_text = "🐢  MISSION COMPLETE"
                else:
                    title_text = "🥷  MISSION COMPLETE"
            else:
                title_text = "🎉  Session Complete"

        title = QLabel(title_text)
        if dojo:
            font_weight = QFont.Normal if theme_mode == "manhattan" else QFont.Bold
            title.setFont(QFont(font, 18, font_weight))
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet(
                f"color:{accent};background:transparent;"
                f"letter-spacing:3px;font-family:{font};"
                f"border-bottom:1px solid {border};padding-bottom:10px;"
            )
        else:
            title.setFont(QFont(font, 20, QFont.Bold))
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet(f"color:{accent};background:transparent;font-family:{font};")
        L.addWidget(title)

        # Columns container
        cols_w = QWidget()
        cols_w.setStyleSheet("background: transparent;")
        cols_l = QHBoxLayout(cols_w)
        cols_l.setContentsMargins(0, 0, 0, 0)
        cols_l.setSpacing(24)

        # LEFT COLUMN: Overview Card
        left_card = QFrame()
        left_card.setObjectName("left_card")
        if dojo:
            left_card.setStyleSheet(
                f"QFrame#left_card {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; }}"
            )
        else:
            left_card.setStyleSheet(
                f"QFrame#left_card {{ background: {card}; border: 1px solid {border}; border-radius: 8px; }}"
            )
        
        left_l = QVBoxLayout(left_card)
        left_l.setContentsMargins(16, 16, 16, 16)
        left_l.setSpacing(8)

        # Retention Rate Circle/Label
        ret_hdr = QLabel("RETENTION" if dojo else "Retention")
        if dojo:
            ret_hdr.setStyleSheet(f"color:{subtext};font-size:11px;font-family:{font};letter-spacing:1px;font-weight:bold;")
        else:
            ret_hdr.setStyleSheet(f"color:{subtext};font-size:12px;font-family:{body_font};font-weight:bold;")
        ret_hdr.setAlignment(Qt.AlignCenter)
        left_l.addWidget(ret_hdr)

        ret_color = green if retention >= 80 else yellow if retention >= 60 else red
        ret_val = QLabel(f"{retention}%")
        if dojo:
            ret_val.setStyleSheet(f"color:{ret_color};font-size:42px;font-family:{font};font-weight:bold;")
        else:
            ret_val.setStyleSheet(f"color:{ret_color};font-size:42px;font-family:{font};font-weight:bold;")
        ret_val.setAlignment(Qt.AlignCenter)
        left_l.addWidget(ret_val)

        # Retention indicator segment bar
        bar_w = QFrame()
        bar_w.setFrameShape(QFrame.NoFrame)
        bar_w.setStyleSheet("background:transparent;")
        bar_l = QHBoxLayout(bar_w)
        bar_l.setContentsMargins(0, 4, 0, 8)
        bar_l.setSpacing(2)
        ret_colors = [
            (again, red),
            (hard, orange),
            (good, green),
            (easy, yellow),
            (perfect, purple),
        ]
        for count, color in ret_colors:
            if count and total:
                seg = QFrame()
                seg.setFixedHeight(6 if dojo else 8)
                seg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                seg.setStyleSheet(f"background:{color};border-radius:3px;")
                bar_l.addWidget(seg, stretch=count)
        left_l.addWidget(bar_w)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{border};")
        sep.setFixedHeight(1)
        left_l.addWidget(sep)

        # Stats rows
        def _left_stat_row(label, value, color=None, highlight=False):
            row = QFrame()
            if highlight:
                col = QColor(accent)
                bg_color = f"rgba({col.red()}, {col.green()}, {col.blue()}, 0.12)"
                row.setObjectName("highlight_row")
                row.setStyleSheet(
                    f"QFrame#highlight_row {{"
                    f"  background: {bg_color};"
                    f"  border: 1px solid {accent};"
                    f"  border-radius: 4px;"
                    f"}}"
                    f"QLabel {{"
                    f"  background: transparent;"
                    f"  border: none;"
                    f"}}"
                )
                rl = QHBoxLayout(row)
                rl.setContentsMargins(8, 6, 8, 6)
            else:
                row.setStyleSheet("background: transparent;")
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 4, 0, 4)
            
            lbl = QLabel(label)
            if dojo:
                lbl.setStyleSheet(f"color:{accent if highlight else subtext};font-size:{'12px' if highlight else '11px'};font-family:{font};letter-spacing:1px;font-weight:bold;")
            else:
                lbl.setStyleSheet(f"color:{accent if highlight else subtext};font-size:{'13px' if highlight else '12px'};font-family:{body_font};font-weight:bold;")
                
            val = QLabel(str(value))
            v_color = color or (accent if highlight else text)
            if dojo:
                val.setStyleSheet(f"color:{v_color};font-size:{'15px' if highlight else '13px'};font-family:{font};font-weight:bold;")
            else:
                val.setStyleSheet(f"color:{v_color};font-size:{'15px' if highlight else '13px'};font-family:{body_font};font-weight:bold;")
            val.setAlignment(Qt.AlignRight)
            
            rl.addWidget(lbl)
            rl.addWidget(val)
            return row

        left_l.addWidget(_left_stat_row("TOTAL REVIEWED" if dojo else "Total Reviewed", self.rs._done))

        session_seconds = self.rs._stimer._session_elapsed if self.rs._stimer else 0
        def _fmt_duration(secs):
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            if h > 0:
                return f"{h}h {m}m {s}s"
            elif m > 0:
                return f"{m}m {s}s"
            return f"{s}s"

        session_time_str = _fmt_duration(session_seconds)
        left_l.addWidget(_left_stat_row("TIME SPENT" if dojo else "Time Spent", session_time_str))

        if total > 0:
            avg_secs = round(session_seconds / total)
            avg_time_str = _fmt_duration(avg_secs)
        else:
            avg_time_str = "0s"
        left_l.addWidget(_left_stat_row("AVG TIME/CARD" if dojo else "Avg Time/Card", avg_time_str, highlight=True))

        if pdf_paths and self.rs._stimer:
            for pdf_path in pdf_paths:
                sep_pdf = QFrame()
                sep_pdf.setFrameShape(QFrame.HLine)
                sep_pdf.setStyleSheet(f"background:{border};")
                sep_pdf.setFixedHeight(1)
                left_l.addWidget(sep_pdf)
                
                fn = os.path.basename(pdf_path)
                if len(fn) > 35:
                    fn = fn[:32] + "..."
                pdf_hdr = QLabel(fn.upper() if dojo else fn)
                if dojo:
                    pdf_hdr.setStyleSheet(
                        f"color:{accent};font-size:11px;font-family:{font};"
                        f"letter-spacing:1.5px;font-weight:bold;margin-top:8px;margin-bottom:4px;"
                    )
                else:
                    pdf_hdr.setStyleSheet(
                        f"color:{accent};font-size:13px;font-family:{body_font};"
                        f"font-weight:bold;margin-top:8px;margin-bottom:4px;"
                    )
                left_l.addWidget(pdf_hdr)
                
                pdf_secs = self.rs._stimer._pdf_seconds.get(pdf_path, 0)
                pdf_cards = self.rs._stimer._pdf_cards_today.get(pdf_path, 0)
                
                left_l.addWidget(_left_stat_row("TODAY'S TIME" if dojo else "Today's Time", _fmt_duration(pdf_secs)))
                left_l.addWidget(_left_stat_row("TODAY'S CARDS" if dojo else "Today's Cards", pdf_cards))
                
                if pdf_cards > 0:
                    pdf_avg = round(pdf_secs / pdf_cards)
                    pdf_avg_str = _fmt_duration(pdf_avg)
                else:
                    pdf_avg_str = "0s"
                left_l.addWidget(_left_stat_row("TODAY'S AVG/CARD" if dojo else "Today's Avg/Card", pdf_avg_str, highlight=True))

        left_l.addStretch()
        cols_l.addWidget(left_card)

        # RIGHT COLUMN: Rating Breakdown
        right_pane = QWidget()
        right_pane.setStyleSheet("background: transparent;")
        right_l = QVBoxLayout(right_pane)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(10)

        breakdown_title = QLabel("PERFORMANCE" if dojo else "Performance")
        if dojo:
            breakdown_title.setStyleSheet(f"color:{accent};font-size:12px;font-family:{font};letter-spacing:1.5px;font-weight:bold;border-bottom:1px solid {border};padding-bottom:4px;")
        else:
            breakdown_title.setStyleSheet(f"color:{accent};font-size:14px;font-family:{body_font};font-weight:bold;border-bottom:1px solid {border};padding-bottom:4px;")
        right_l.addWidget(breakdown_title)

        def _breakdown_row(label, count, color):
            row = QFrame()
            row.setStyleSheet("background: transparent;")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 2, 0, 2)
            rl.setSpacing(4)
            
            hdr = QWidget()
            hdr.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(hdr)
            hl.setContentsMargins(0, 0, 0, 0)
            
            lbl = QLabel(label)
            if dojo:
                lbl.setStyleSheet(f"color:{text};font-size:12px;font-family:{font};")
            else:
                lbl.setStyleSheet(f"color:{text};font-size:13px;font-family:{body_font};")
                
            pct = round(count / total * 100) if total else 0
            val = QLabel(f"{count} ({pct}%)")
            if dojo:
                val.setStyleSheet(f"color:{color};font-size:13px;font-family:{font};font-weight:bold;")
            else:
                val.setStyleSheet(f"color:{color};font-size:13px;font-family:{body_font};font-weight:bold;")
            val.setAlignment(Qt.AlignRight)
            
            hl.addWidget(lbl)
            hl.addWidget(val)
            rl.addWidget(hdr)
            
            bar = QProgressBar()
            bar.setRange(0, total if total > 0 else 1)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(6 if dojo else 8)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background: {border};
                    border: none;
                    border-radius: 3px;
                }}
                QProgressBar::chunk {{
                    background: {color};
                    border-radius: 3px;
                }}
            """)
            rl.addWidget(bar)
            return row

        right_l.addWidget(_breakdown_row("🔁 AGAIN" if dojo else "🔁 Again", again, red))
        right_l.addWidget(_breakdown_row("😓 HARD" if dojo else "😓 Hard", hard, orange))
        right_l.addWidget(_breakdown_row("✅ GOOD" if dojo else "✅ Good", good, green))
        right_l.addWidget(_breakdown_row("⚡ EASY" if dojo else "⚡ Easy", easy, yellow))
        right_l.addWidget(_breakdown_row("⭐ PERFECT" if dojo else "⭐ Perfect", perfect, purple))
        right_l.addStretch()

        cols_l.addWidget(right_pane)
        cols_l.setStretch(0, 1)
        cols_l.setStretch(1, 1)
        L.addWidget(cols_w)

        # Ninja motivational quote for dojo
        if dojo and retention >= 80:
            if theme_mode == "arcanum":
                quote_text = '"THE STARS ALIGN. EXCELLENT CASTING, ARCHMAGE."'
            else:
                quote_text = '"COWABUNGA! EXCELLENT WORK, NINJA."'
            q_lbl = QLabel(quote_text)
            q_lbl.setAlignment(Qt.AlignCenter)
            q_lbl.setWordWrap(True)
            q_lbl.setStyleSheet(
                f"color:{accent};font-size:10px;font-family:{font};"
                f"letter-spacing:1px;background:transparent;"
            )
            L.addWidget(q_lbl)

        # Close button
        btn = QPushButton("CLOSE" if dojo else "Close")
        if dojo:
            weight_str = "normal" if theme_mode == "manhattan" else "bold" if theme_mode == "arcanum" else "900"
            v_pad = "0px" if theme_mode == "manhattan" else "8px"
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background:{accent};color:{bg};border:none;border-radius:2px;"
                f"  padding:{v_pad} 24px;font-size:13px;font-weight:{weight_str};"
                f"  font-family:{font};letter-spacing:1px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background:white;color:{bg};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background:rgba(255,255,255,0.8);"
                f"}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background:{accent} !important;"
                f"  color:white !important;"
                f"  border:none;"
                f"  border-radius:8px;"
                f"  padding:8px 24px;"
                f"  font-size:13px;"
                f"  font-weight:bold;"
                f"  font-family:{body_font};"
                f"}}"
                f"QPushButton:hover {{"
                f"  background:{hover_color} !important;"
                f"  color:white !important;"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background:{pressed_color} !important;"
                f"  color:white !important;"
                f"}}"
            )
        btn.clicked.connect(self.accept)
        L.addWidget(btn, alignment=Qt.AlignCenter)
