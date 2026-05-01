import sys
with open('ui/deck_tree.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Make DeckItemDelegate accept theme
delegate_old = '''class DeckItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):'''
delegate_new = '''class DeckItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, theme="classic"):
        super().__init__(parent)
        self.theme = theme

    def paint(self, painter, option, index):
        if self.theme != "dojo":
            super().paint(painter, option, index)
            return
'''
if delegate_old in content:
    content = content.replace(delegate_old, delegate_new)
    print("Patched DeckItemDelegate")

# Update DeckTree init
init_old = '''class DeckTree(QWidget):
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data'''
init_new = '''class DeckTree(QWidget):
    deck_selected = pyqtSignal(object)

    def __init__(self, data: dict, theme="classic", parent=None):
        super().__init__(parent)
        self._data = data
        self._theme = theme'''
if init_old in content:
    content = content.replace(init_old, init_new)
    print("Patched DeckTree.__init__")

# Update blink tick for classic text
blink_old = '''                badge = f"🔴{due}" if self._blink_state else f"⭕{due}"
                item.setText(0, f"  📂  {name}  {badge}")'''
blink_new = '''                badge = f"🔴{due}" if self._blink_state else f"⭕{due}"
                if getattr(self, '_theme', 'classic') == "classic":
                    item.setText(0, f"  📂  {name}  {badge}")
                else:
                    item.setText(0, "")'''
if blink_old in content:
    content = content.replace(blink_old, blink_new)
    print("Patched blink_tick")

# Update make_item
make_old = '''        due   = _total_due(deck)
        item  = QTreeWidgetItem([""]) # Text is handled by delegate'''
make_new = '''        due   = _total_due(deck)
        badge = f"🔴{due}" if due else "✅"
        text = f"  📂  {deck['name']}  {badge}" if getattr(self, '_theme', 'classic') == "classic" else ""
        item  = QTreeWidgetItem([text])'''
if make_old in content:
    content = content.replace(make_old, make_new)
    print("Patched make_item")

# Define new _setup_ui and set_theme
setup_ui_start = content.find('    def _setup_ui(self):')
setup_ui_end = content.find('    def refresh(self):')

new_setup_ui = '''    def set_theme(self, theme):
        self._theme = theme
        self._delegate.theme = theme
        if theme == "dojo":
            self._classic_hdr.hide()
            self._classic_btns_w.hide()
            self._dojo_hdr_w.show()
            self._dojo_btns_w.show()
            self.layout().setContentsMargins(0, 0, 0, 0)
        else:
            self._dojo_hdr_w.hide()
            self._dojo_btns_w.hide()
            self._classic_hdr.show()
            self._classic_btns_w.show()
            self.layout().setContentsMargins(0, 0, 0, 0)
        self.refresh()

    def _setup_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0)
        L.setSpacing(6)

        # --- Classic Header ---
        self._classic_hdr = QLabel("📚  Decks")
        self._classic_hdr.setFont(QFont("Segoe UI", 13, QFont.Bold))
        L.addWidget(self._classic_hdr)

        # --- Dojo Header ---
        self._dojo_hdr_w = QWidget()
        dhl = QVBoxLayout(self._dojo_hdr_w)
        dhl.setContentsMargins(12, 16, 12, 0)
        dhl.setSpacing(10)
        
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        logo = QLabel("⛩") 
        logo.setStyleSheet(theme_manager.get_style("dt_logo", getattr(self, '_theme', 'classic')))
        top_row.addWidget(logo)
        title = QLabel("DOJO CAVA")
        title.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(theme_manager.get_style("dt_title", getattr(self, '_theme', 'classic')))
        top_row.addWidget(title)
        top_row.addStretch()
        dhl.addLayout(top_row)
        dhl.addSpacing(4)
        
        search_box = QFrame()
        search_box.setStyleSheet(theme_manager.get_style("dt_search_box", getattr(self, '_theme', 'classic')))
        search_box.setFixedHeight(32)
        sh_l = QHBoxLayout(search_box)
        sh_l.setContentsMargins(8, 0, 8, 0)
        search_icon = QLabel("⌕")
        search_icon.setStyleSheet(theme_manager.get_style("dt_search_icon", getattr(self, '_theme', 'classic')))
        sh_l.addWidget(search_icon)
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Search scrolls...")
        self.search_in.setStyleSheet(theme_manager.get_style("dt_search_in", getattr(self, '_theme', 'classic')))
        sh_l.addWidget(self.search_in)
        shortcut_badge = QLabel("CTRL+K")
        shortcut_badge.setStyleSheet(theme_manager.get_style("dt_shortcut_badge", getattr(self, '_theme', 'classic')))
        sh_l.addWidget(shortcut_badge)
        dhl.addWidget(search_box)
        dhl.addSpacing(6)
        
        hdr_dojo = QLabel("— YOUR DOJOS —")
        hdr_dojo.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY, 9))
        hdr_dojo.setStyleSheet(theme_manager.get_style("dt_hdr_dojo", getattr(self, '_theme', 'classic')))
        dhl.addWidget(hdr_dojo)
        L.addWidget(self._dojo_hdr_w)

        self.tree = _DeckTreeWidget()
        self._delegate = DeckItemDelegate(self.tree, getattr(self, '_theme', 'classic'))
        self.tree.setItemDelegate(self._delegate)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.viewport().setAcceptDrops(True)
        self.tree.dropEvent    = self._on_tree_drop
        self.tree.dragEnterEvent = self._on_drag_enter
        self.tree.dragMoveEvent  = self._on_drag_move
        self.tree.dragLeaveEvent = self._on_drag_leave
        L.addWidget(self.tree, stretch=1)
        
        # --- Classic Buttons ---
        self._classic_btns_w = QWidget()
        cbl = QHBoxLayout(self._classic_btns_w)
        cbl.setContentsMargins(0,0,0,0)
        cb_new = QPushButton("＋ Deck")
        cb_new.clicked.connect(lambda: self._new_deck(None))
        cb_sub = QPushButton("＋ Sub")
        cb_sub.clicked.connect(self._new_subdeck)
        cb_del = QPushButton("🗑")
        cb_del.setObjectName("danger")
        cb_del.setFixedWidth(36)
        cb_del.clicked.connect(self._delete_selected)
        cbl.addWidget(cb_new)
        cbl.addWidget(cb_sub)
        cbl.addStretch()
        cbl.addWidget(cb_del)
        L.addWidget(self._classic_btns_w)
        
        # --- Dojo Buttons ---
        self._dojo_btns_w = QWidget()
        dbl = QHBoxLayout(self._dojo_btns_w)
        dbl.setContentsMargins(12,0,12,12)
        db_new = QPushButton("⊕ NEW DOJO")
        db_new.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY, 9, QFont.Bold))
        db_new.setStyleSheet(theme_manager.get_style("dt_btn_new", getattr(self, '_theme', 'classic')))
        db_new.clicked.connect(lambda: self._new_deck(None))
        db_sub = QPushButton("⊕ SUB")
        db_sub.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY, 9, QFont.Bold))
        db_sub.setStyleSheet(theme_manager.get_style("dt_btn_new", getattr(self, '_theme', 'classic')))
        db_sub.clicked.connect(self._new_subdeck)
        db_del = QPushButton("⚙")
        db_del.setFixedSize(32, 32)
        db_del.setStyleSheet(theme_manager.get_style("dt_btn_del", getattr(self, '_theme', 'classic')))
        dbl.addWidget(db_new)
        dbl.addWidget(db_sub)
        dbl.addStretch()
        dbl.addWidget(db_del)
        L.addWidget(self._dojo_btns_w)
        
        # Drop hint
        self._drop_hint = QLabel("↕ Reorder — hold Ctrl to nest inside")
        self._drop_hint.setStyleSheet(theme_manager.get_style("dt_drop_hint", getattr(self, '_theme', 'classic')))
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setVisible(False)
        L.addWidget(self._drop_hint)
        
        self.set_theme(getattr(self, '_theme', 'classic'))

'''

if setup_ui_start != -1 and setup_ui_end != -1:
    content = content[:setup_ui_start] + new_setup_ui + content[setup_ui_end:]
    print("Patched setup_ui")

with open('ui/deck_tree.py', 'w', encoding='utf-8') as f:
    f.write(content)
