import os

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'import theme_manager' not in content:
        content = content.replace('import tempfile', 'import tempfile\nimport theme_manager')
        content = content.replace('import sys, os, copy, uuid, math, time', 'import sys, os, copy, uuid, math, time\nimport theme_manager')

    if 'ui/deck_view.py' in filepath.replace('\\\\', '/'):
        content = content.replace(
            'self.setStyleSheet(f"""\n            QFrame {{ background: transparent; border-radius: 8px; }}\n        """)',
            'self.setStyleSheet(theme_manager.get_style("dv_card", "dojo"))'
        )
        content = content.replace(
            'self.icon_lbl.setStyleSheet(f"color: {color_hex}; font-size: 32px;")',
            'self.icon_lbl.setStyleSheet(theme_manager.get_style("dv_icon_lbl", "dojo").format(color_hex=color_hex))'
        )
        content = content.replace(
            'self.val_lbl.setStyleSheet(f"color: {color_hex}; font-size: 32px; font-weight: 900; font-family: \'Orbitron\'; letter-spacing: -1px;")',
            'self.val_lbl.setStyleSheet(theme_manager.get_style("dv_val_lbl", "dojo").format(color_hex=color_hex))'
        )
        content = content.replace(
            'title_lbl.setStyleSheet(f"color: #A6ADC8; font-size: 10px; font-weight: 800; font-family: \'Orbitron\'; letter-spacing: 1px;")',
            'title_lbl.setStyleSheet(theme_manager.get_style("dv_title_lbl", "dojo"))'
        )
        content = content.replace(
            'sub_lbl.setStyleSheet(f"color: #5F627D; font-size: 11px;")',
            'sub_lbl.setStyleSheet(theme_manager.get_style("dv_sub_lbl", "dojo"))'
        )
        content = content.replace(
            'title.setStyleSheet("color: #BD93F9; font-size: 12px; font-weight: 900; font-family: \'Orbitron\'; letter-spacing: 2px;")',
            'title.setStyleSheet(theme_manager.get_style("dv_info_title", "dojo"))'
        )
        content = content.replace(
            'desc.setStyleSheet("color: #CDD6F4; font-size: 14px;")',
            'desc.setStyleSheet(theme_manager.get_style("dv_info_desc", "dojo"))'
        )
        content = content.replace(
            'quote.setStyleSheet("color: #50FA7B; font-size: 12px; font-weight: bold; font-family: monospace;")',
            'quote.setStyleSheet(theme_manager.get_style("dv_info_quote", "dojo"))'
        )
        content = content.replace(
            'self.btn_train.setStyleSheet("""\n            QPushButton {\n                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #50FA7B, stop:1 #8BE9FD);\n                color: #282A36; border: none; border-radius: 8px; font-family: \'Orbitron\'; font-weight: 900; font-size: 16px; padding: 12px 24px;\n            }\n            QPushButton:hover { background: #8BE9FD; }\n        """)',
            'self.btn_train.setStyleSheet(theme_manager.get_style("dv_btn_train", "dojo"))'
        )
        content = content.replace(
            'self.btn_all.setStyleSheet("""\n            QPushButton { background: transparent; border: 2px solid #5F627D; color: #CDD6F4; border-radius: 8px; font-family: \'Orbitron\'; font-weight: bold; font-size: 14px; padding: 12px 24px; }\n            QPushButton:hover { background: rgba(255,255,255,0.05); border-color: #CDD6F4; }\n        """)',
            'self.btn_all.setStyleSheet(theme_manager.get_style("dv_btn_all", "dojo"))'
        )
        content = content.replace(
            'self.lbl_deck_sub.setStyleSheet("color: #5F627D; font-size: 11px; font-weight: bold; font-family: \'Orbitron\'; letter-spacing: 1px;")',
            'self.lbl_deck_sub.setStyleSheet(theme_manager.get_style("dv_lbl_deck_sub", "dojo"))'
        )
        content = content.replace(
            'self.lbl_stats.setStyleSheet(f"color:{C_SUBTEXT};")',
            'self.lbl_stats.setStyleSheet(theme_manager.get_style("dv_lbl_stats", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self.dojo_container.setStyleSheet("""\n            #dojoContainer {\n                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E1E2E, stop:1 #11111B);\n            }\n        """)',
            'self.dojo_container.setStyleSheet(theme_manager.get_style("dv_dojo_container", "dojo"))'
        )
        content = content.replace(
            'self.lbl_deck.setStyleSheet("color: #72FF4F; font-size: 24px; font-weight: 900; font-family: \'Orbitron\'; letter-spacing: 2px;")',
            'self.lbl_deck.setStyleSheet(theme_manager.get_style("dv_lbl_deck_title", "dojo"))'
        )

    if 'dojo_assets.py' in filepath.replace('\\\\', '/'):
        if 'import theme_manager' not in content:
            content = "import theme_manager\n" + content
        content = content.replace(
            'w.setStyleSheet("background:rgba(20, 20, 31, 0.6); border: 1px solid #A86CFF; border-radius: 8px; margin-top: 6px; margin-bottom: 6px;")',
            'w.setStyleSheet(theme_manager.get_style("da_card_purple", "dojo"))'
        )
        content = content.replace(
            'icon.setStyleSheet("border:none; background:transparent;")',
            'icon.setStyleSheet(theme_manager.get_style("da_icon", "dojo"))'
        )
        content = content.replace(
            'lbl.setStyleSheet("color:#A86CFF; font-size:10px; font-weight:bold; border:none; background:transparent;")',
            'lbl.setStyleSheet(theme_manager.get_style("da_lbl_purple", "dojo"))'
        )
        content = content.replace(
            'w.setStyleSheet("background:rgba(20, 20, 31, 0.6); border: 1px solid #72FF4F; border-radius: 8px; margin-top: 6px; margin-bottom: 6px;")',
            'w.setStyleSheet(theme_manager.get_style("da_card_green", "dojo"))'
        )
        content = content.replace(
            'lbl.setStyleSheet("color:#72FF4F; font-size:10px; font-weight:bold; border:none; background:transparent;")',
            'lbl.setStyleSheet(theme_manager.get_style("da_lbl_green", "dojo"))'
        )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process_file('ui/deck_view.py')
process_file('dojo_assets.py')
print('Done view and assets patching')
