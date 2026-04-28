import os
from PyQt5.QtGui import QPixmap, QPainter, QPainterPath, QImage
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtWidgets import QLabel, QFrame, QVBoxLayout, QHBoxLayout

_ASSETS_DIR = "assets/themes/dojo"

class DojoAssets:
    _instance = None
    
    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = DojoAssets()
        return cls._instance
        
    def __init__(self):
        def _get_path(name):
            clean = os.path.join(_ASSETS_DIR, name + "_clean.png")
            if os.path.exists(clean): return clean
            return os.path.join(_ASSETS_DIR, name)

        self.ui_sheet = QPixmap(_get_path("Fantasy_ninja_UI_202604270705.jpeg"))
        self.clan_sheet = QPixmap(_get_path("Fantasy_ninja_clan_202604270705.jpeg"))
        self.pizza_pix = QPixmap(_get_path("Retro_arcade_pizza_202604270705.jpeg"))
        self.turtle_pix = QPixmap(_get_path("Cyber_ninja_turtle_202604270705.jpeg"))

        self._prepare_subtle_backgrounds()
    def _prepare_subtle_backgrounds(self):
        """Creates low-opacity versions of backgrounds for CSS usage."""
        def _make_subtle(src_name, dst_name, opacity):
            src_path = os.path.join(_ASSETS_DIR, src_name)
            dst_path = os.path.join(_ASSETS_DIR, dst_name)
            if not os.path.exists(src_path): return
            if os.path.exists(dst_path): return # Already generated
            
            img = QImage(src_path)
            if img.isNull(): return
            
            # Create translucent pixmap
            pix = QPixmap(img.size())
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setOpacity(opacity)
            p.drawImage(0, 0, img)
            p.end()
            pix.save(dst_path, "PNG")

        _make_subtle("wall_main.png", "wall_main_subtle.png", 0.10)
        _make_subtle("wall_hex_accent.png", "wall_hex_subtle.png", 0.15)
        _make_subtle("panel_overlay.png", "panel_overlay_subtle.png", 0.30)
        
    def get_ui_icon(self, index, size=64):
        if self.ui_sheet.isNull(): return QPixmap()
        w = 1376 // 3
        h = 768 // 2
        col = index % 3
        row = index // 3
        rect = QRect(col * w, row * h, w, h)
        cropped = self.ui_sheet.copy(rect)
        
        out_pix = QPixmap(size, size)
        out_pix.fill(Qt.transparent)
        painter = QPainter(out_pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, cropped.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        painter.end()
        return out_pix
        
    def get_clan_icon(self, name, size=48):
        if self.clan_sheet.isNull(): return QPixmap()
        w = 1376 // 2
        h = 768 // 2
        mapping = {"math": 0, "physics": 1, "history": 2, "biology": 3}
        
        # Match substring for clan names
        idx = None
        name_lower = name.lower()
        for k, v in mapping.items():
            if k in name_lower:
                idx = v
                break
                
        if idx is None: return QPixmap()
        col = idx % 2
        row = idx // 2
        rect = QRect(col * w, row * h, w, h)
        cropped = self.clan_sheet.copy(rect)
        
        out_pix = QPixmap(size, size)
        out_pix.fill(Qt.transparent)
        painter = QPainter(out_pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, cropped.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        painter.end()
        return out_pix

    def get_turtle_widget(self):
        w = QFrame()
        w.setObjectName("mentor_card")
        w.setStyleSheet("background:rgba(20, 20, 31, 0.6); border: 1px solid #A86CFF; border-radius: 8px; margin-top: 6px; margin-bottom: 6px;")
        ql = QHBoxLayout(w)
        ql.setContentsMargins(12, 12, 12, 12)
        ql.setSpacing(12)
        
        icon = QLabel()
        if not self.turtle_pix.isNull():
            size = 48
            scaled = self.turtle_pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            out_pix = QPixmap(size, size)
            out_pix.fill(Qt.transparent)
            p = QPainter(out_pix)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, size, size)
            p.setClipPath(path)
            p.drawPixmap(0, 0, scaled)
            p.end()
            icon.setPixmap(out_pix)
            
        icon.setStyleSheet("border:none; background:transparent;")
        lbl = QLabel('"FOCUS. TRAIN. MASTER."\n- DONATELLO')
        lbl.setStyleSheet("color:#A86CFF; font-size:10px; font-weight:bold; border:none; background:transparent;")
        ql.addWidget(icon)
        ql.addWidget(lbl)
        return w

    def get_pizza_widget(self):
        w = QFrame()
        w.setObjectName("pizza_card")
        w.setStyleSheet("background:rgba(20, 20, 31, 0.6); border: 1px solid #72FF4F; border-radius: 8px; margin-top: 6px; margin-bottom: 6px;")
        pl = QHBoxLayout(w)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(12)
        
        icon = QLabel()
        if not self.pizza_pix.isNull():
            icon.setPixmap(self.pizza_pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon.setStyleSheet("border:none; background:transparent;")
        
        lbl = QLabel("FUEL UP, NINJA!\nTake breaks.\nYour brain is not a robot.")
        lbl.setStyleSheet("color:#72FF4F; font-size:10px; font-weight:bold; border:none; background:transparent;")
        
        pl.addWidget(icon)
        pl.addWidget(lbl)
        return w
