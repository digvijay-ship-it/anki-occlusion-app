import math
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel
from PyQt5.QtGui import QPainter, QColor, QPen, QPixmap, QFont
from PyQt5.QtCore import Qt, QPoint

class ArcaneAssets:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_archmage_widget(self, parent=None, scale=1.0):
        frame = QFrame(parent)
        frame.setObjectName("archmage_mentor_card")
        
        # Determine exact pixel padding and sizes using scale
        p_lr = int(8 * scale)
        p_tb = int(4 * scale)
        spacing = int(8 * scale)
        
        frame.setStyleSheet(
            f"QFrame#archmage_mentor_card {{"
            f"   background: rgba(31, 27, 56, 0.6);"
            f"   border: 1px solid #5FEAD0;"
            f"   border-radius: 8px;"
            f"}}"
        )
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(p_lr, p_tb, p_lr, p_tb)
        layout.setSpacing(spacing)
        
        # Procedurally draw sigil eye/rune
        sigil_size = int(28 * scale)
        pixmap = QPixmap(sigil_size, sigil_size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        pen = QPen(QColor("#5FEAD0"))
        pen.setWidth(max(1, int(1.5 * scale)))
        painter.setPen(pen)
        
        cx = sigil_size / 2.0
        cy = sigil_size / 2.0
        r_outer = sigil_size * 0.4
        
        # Outer circle of sigil
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(r_outer), int(r_outer))
        
        # Triangle inside the circle
        points = []
        for i in range(3):
            angle = i * 2 * math.pi / 3 - math.pi / 2
            px = cx + r_outer * math.cos(angle)
            py = cy + r_outer * math.sin(angle)
            points.append(QPoint(int(px), int(py)))
        painter.drawPolygon(*points)
        
        # Center glowing pupil
        painter.setBrush(QColor("#5FEAD0"))
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(r_outer * 0.25), int(r_outer * 0.25))
        painter.end()
        
        avatar = QLabel()
        avatar.setPixmap(pixmap)
        avatar.setFixedSize(sigil_size, sigil_size)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(avatar)
        
        quote = QLabel("“KNOWLEDGE IS THE ONLY MAGIC.”")
        quote.setStyleSheet(
            f"color: #A78BFA; background: transparent; border: none; font-weight: bold; font-family: 'Cinzel';"
        )
        quote.setFont(QFont("Cinzel", int(6.5 * scale), QFont.Bold))
        quote.setWordWrap(True)
        
        name = QLabel("— THE ARCHMAGE")
        name.setStyleSheet(
            f"color: #8E86B0; background: transparent; border: none; font-family: 'Cinzel';"
        )
        name.setFont(QFont("Cinzel", int(6.5 * scale)))
        
        from PyQt5.QtWidgets import QVBoxLayout
        v_layout = QVBoxLayout()
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(int(1 * scale))
        v_layout.addWidget(quote)
        v_layout.addWidget(name)
        
        layout.addLayout(v_layout, 1)
        
        # Expose labels so HomeScreen can reference them safely if needed
        frame.quote_lbl = quote
        frame.name_lbl = name
        
        return frame
