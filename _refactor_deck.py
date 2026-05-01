import os

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'import theme_manager' not in content:
        content = content.replace('import tempfile', 'import tempfile\nimport theme_manager')

    # UI DECK TREE
    if 'ui/deck_tree.py' in filepath.replace('\\\\', '/'):
        content = content.replace(
            'logo.setStyleSheet(f"color:{C_GREEN};font-size:18px;")',
            'logo.setStyleSheet(theme_manager.get_style("dt_logo", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'title.setStyleSheet(f"color:{C_GREEN};letter-spacing:2px;")',
            'title.setStyleSheet(theme_manager.get_style("dt_title", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'search_box.setStyleSheet(f"background:transparent;border:1px solid {C_BORDER};border-radius:4px;")',
            'search_box.setStyleSheet(theme_manager.get_style("dt_search_box", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'search_icon.setStyleSheet(f"color:{C_SUBTEXT};border:none;")',
            'search_icon.setStyleSheet(theme_manager.get_style("dt_search_icon", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self.search_in.setStyleSheet(f"background:transparent;border:none;color:{C_TEXT};")',
            'self.search_in.setStyleSheet(theme_manager.get_style("dt_search_in", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'shortcut_badge.setStyleSheet(f"color:{C_SUBTEXT};background:rgba(255,255,255,0.05);border-radius:3px;padding:2px 4px;font-size:9px;border:none;")',
            'shortcut_badge.setStyleSheet(theme_manager.get_style("dt_shortcut_badge", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'hdr_dojo.setStyleSheet(f"color:{C_SUBTEXT};letter-spacing:2px;background:transparent;")',
            'hdr_dojo.setStyleSheet(theme_manager.get_style("dt_hdr_dojo", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'db_new.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:6px 12px;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}")',
            'db_new.setStyleSheet(theme_manager.get_style("dt_btn_new", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'db_sub.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:6px 12px;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}")',
            'db_sub.setStyleSheet(theme_manager.get_style("dt_btn_new", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'db_del.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C_BORDER};color:{C_SUBTEXT};border-radius:4px;font-size:16px;}} QPushButton:hover{{background:rgba(255,255,255,0.05);}}")',
            'db_del.setStyleSheet(theme_manager.get_style("dt_btn_del", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self._drop_hint.setStyleSheet("background:#534AB7;color:white;font-size:11px;padding:4px 8px;border-radius:4px;")',
            'self._drop_hint.setStyleSheet(theme_manager.get_style("dt_drop_hint", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self._drop_hint.setStyleSheet(\n                        "background:#1D9E75;color:white;font-size:11px;"\n                        "padding:4px 8px;border-radius:4px;")',
            'self._drop_hint.setStyleSheet(theme_manager.get_style("dt_drop_hint_danger", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self._drop_hint.setStyleSheet(\n                        "background:#534AB7;color:white;font-size:11px;"\n                        "padding:4px 8px;border-radius:4px;")',
            'self._drop_hint.setStyleSheet(theme_manager.get_style("dt_drop_hint", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'hdr.setStyleSheet(\n            f"QFrame{{background:{C_CARD};"\n            f"border-bottom:1px solid {C_BORDER};border-radius:0px;}}")',
            'hdr.setStyleSheet(theme_manager.get_style("dt_hdr", "dojo"))'
        )
        content = content.replace(
            'title.setStyleSheet(\n            f"color:{C_TEXT};font-size:11px;font-weight:bold;")',
            'title.setStyleSheet(theme_manager.get_style("dt_title", "dojo"))'
        )
        content = content.replace(
            'self._lbl_total.setStyleSheet(\n            f"color:{C_GREEN};font-size:10px;")',
            'self._lbl_total.setStyleSheet(theme_manager.get_style("dt_lbl_total", "dojo"))'
        )
        content = content.replace(
            'scroll.setStyleSheet(\n            f"QScrollArea{{border:none;background:transparent;}}"\n            f"QScrollBar:vertical{{background:{C_SURFACE};width:5px;border-radius:2px;}}"\n            f"QScrollBar::handle:vertical{{background:{C_BORDER};border-radius:2px;}}")',
            'scroll.setStyleSheet(theme_manager.get_style("dt_scroll", "dojo"))'
        )
        content = content.replace(
            'btn_all.setStyleSheet(\n            f"background:#444460;color:{C_TEXT};border:none;"\n            f"border-top:1px solid {C_BORDER};"\n            f"border-radius:0px;padding:8px;font-size:11px;")',
            'btn_all.setStyleSheet(theme_manager.get_style("dt_btn_all", "dojo"))'
        )
        content = content.replace(
            'empty.setStyleSheet(f"color:{C_SUBTEXT};font-size:10px;")',
            'empty.setStyleSheet(theme_manager.get_style("dt_empty", "dojo"))'
        )
        content = content.replace(
            'card.setStyleSheet(\n            f"QFrame{{background:{C_CARD};"\n            f"border:1px solid {C_BORDER};border-radius:6px;}}"\n            f"QLabel{{background:transparent;}}")',
            'card.setStyleSheet(theme_manager.get_style("dt_card", "dojo"))'
        )
        content = content.replace(
            'name_lbl.setStyleSheet(\n            f"color:{C_TEXT};font-size:10px;font-weight:bold;")',
            'name_lbl.setStyleSheet(theme_manager.get_style("dt_name_lbl", "dojo"))'
        )
        content = content.replace(
            'vl2.setStyleSheet(f"color:{C_GREEN};font-size:10px;")',
            'vl2.setStyleSheet(theme_manager.get_style("dt_due_val", "dojo"))'
        )
        content = content.replace(
            'tl.setStyleSheet(\n            f"color:{C_SUBTEXT};font-size:10px;font-weight:bold;")',
            'tl.setStyleSheet(theme_manager.get_style("dt_btn", "dojo"))'
        )
        content = content.replace(
            'btn.setStyleSheet(\n            f"background:{C_RED};color:white;border:none;"\n            f"border-radius:4px;font-size:11px;padding:0px;")',
            'btn.setStyleSheet(theme_manager.get_style("dt_btn", "dojo"))'
        )

    # PATCH DECK TREE
    if 'patch_deck_tree.py' in filepath.replace('\\\\', '/'):
        content = content.replace(
            'logo.setStyleSheet(f"color:{C_GREEN};font-size:18px;")',
            'logo.setStyleSheet(theme_manager.get_style("dt_logo", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'title.setStyleSheet(f"color:{C_GREEN};letter-spacing:2px;")',
            'title.setStyleSheet(theme_manager.get_style("dt_title", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'search_box.setStyleSheet(f"background:transparent;border:1px solid {C_BORDER};border-radius:4px;")',
            'search_box.setStyleSheet(theme_manager.get_style("dt_search_box", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'search_icon.setStyleSheet(f"color:{C_SUBTEXT};border:none;")',
            'search_icon.setStyleSheet(theme_manager.get_style("dt_search_icon", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self.search_in.setStyleSheet(f"background:transparent;border:none;color:{C_TEXT};")',
            'self.search_in.setStyleSheet(theme_manager.get_style("dt_search_in", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'shortcut_badge.setStyleSheet(f"color:{C_SUBTEXT};background:rgba(255,255,255,0.05);border-radius:3px;padding:2px 4px;font-size:9px;border:none;")',
            'shortcut_badge.setStyleSheet(theme_manager.get_style("dt_shortcut_badge", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'hdr_dojo.setStyleSheet(f"color:{C_SUBTEXT};letter-spacing:2px;background:transparent;")',
            'hdr_dojo.setStyleSheet(theme_manager.get_style("dt_hdr_dojo", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'db_new.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:6px 12px;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}")',
            'db_new.setStyleSheet(theme_manager.get_style("dt_btn_new", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'db_sub.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C_GREEN};color:{C_GREEN};border-radius:4px;padding:6px 12px;}} QPushButton:hover{{background:rgba(80,250,123,0.1);}}")',
            'db_sub.setStyleSheet(theme_manager.get_style("dt_btn_new", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'db_del.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C_BORDER};color:{C_SUBTEXT};border-radius:4px;font-size:16px;}} QPushButton:hover{{background:rgba(255,255,255,0.05);}}")',
            'db_del.setStyleSheet(theme_manager.get_style("dt_btn_del", getattr(self, \'_theme\', \'classic\')))'
        )
        content = content.replace(
            'self._drop_hint.setStyleSheet("background:#534AB7;color:white;font-size:11px;padding:4px 8px;border-radius:4px;")',
            'self._drop_hint.setStyleSheet(theme_manager.get_style("dt_drop_hint", getattr(self, \'_theme\', \'classic\')))'
        )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process_file('ui/deck_tree.py')
process_file('patch_deck_tree.py')
print('Done deck_tree patching')
