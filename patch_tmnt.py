import sys

with open('ui/tmnt_home.py', 'r', encoding='utf-8') as f:
    c = f.read()

bgm_code = '''
        font_layout = QHBoxLayout()
        font_layout.setSpacing(4)
        def _font_btn(text, delta):
            b = QPushButton(text)
            b.setFixedSize(28, 26)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {T_PANEL};
                    color: {T_SUBTEXT};
                    border: 1px solid {T_BORDER};
                    border-radius: 2px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {T_CARD}; color: {T_TEXT}; border-color: {T_GREEN}; }}
            """)
            b.clicked.connect(lambda _, d=delta: self.font_change.emit(d))
            return b

        font_layout.addWidget(_font_btn("A−", -1))
        font_layout.addWidget(_font_btn("A",   0))
        font_layout.addWidget(_font_btn("A+", +1))
        title_col.addLayout(font_layout)

        title_col.addSpacing(12)

        btn_bgm = QPushButton("🎵 BGM Toggle")
        btn_bgm.setFixedHeight(26)
        btn_bgm.setStyleSheet(f"""
            QPushButton {{
                background: {T_PANEL};
                color: {T_SUBTEXT};
                border: 1px solid {T_BORDER};
                border-radius: 2px;
                font-size: 10px;
                font-weight: bold;
                padding: 0 8px;
            }}
            QPushButton:hover {{ background: {T_CARD}; color: {T_TEXT}; border-color: {T_PURPLE}; }}
        """)
        btn_bgm.clicked.connect(self.bgm_toggle.emit)
        title_col.addWidget(btn_bgm)
'''

# Add signals to TMNTTopBar
c = c.replace('font_change         = pyqtSignal(int)   # -1 / 0 / +1', 'font_change         = pyqtSignal(int)\n    bgm_toggle          = pyqtSignal()')
c = c.replace('font_change         = pyqtSignal(int)', 'font_change         = pyqtSignal(int)\n    bgm_toggle          = pyqtSignal()')

# Inject bgm code right after app_name in TMNTTopBar
c = c.replace(
    'title_col.addWidget(app_name)\n        L.addLayout(title_col)\n\n        L.addStretch()', 
    'title_col.addWidget(app_name)\n        L.addLayout(title_col)\n' + bgm_code + '\n        L.addStretch()'
)

# Remove the old font buttons from TMNTBangaLab
old_font = '''        # ── Font buttons ──
        def _font_btn(text, delta):
            b = QPushButton(text)
            b.setFixedSize(28, 26)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {T_PANEL};
                    color: {T_SUBTEXT};
                    border: 1px solid {T_BORDER};
                    border-radius: 2px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {T_CARD}; color: {T_TEXT}; border-color: {T_GREEN}; }}
            """)
            b.clicked.connect(lambda: self.font_change.emit(delta))
            return b

        L.addWidget(_font_btn("A−", -1))
        L.addSpacing(2)
        L.addWidget(_font_btn("A",   0))
        L.addSpacing(2)
        L.addWidget(_font_btn("A+", +1))
        L.addSpacing(14)'''
c = c.replace(old_font, '')

# Wire up bgm_toggle in TMNTHomeLayout
c = c.replace('self.topbar.font_change.connect(self.font_change)', 'self.topbar.font_change.connect(self.font_change)\n        self.topbar.bgm_toggle.connect(self.bgm_toggle)')

with open('ui/tmnt_home.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Patch applied")