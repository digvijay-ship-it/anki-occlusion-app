"""
retro_effects.py — High-fidelity 8-bit visual effects library for TMNT & Manhattan modes
======================================================================================
Provides scanline overlays, CRT boot flicker animations, falling pixel particles,
and high-impact particle burst explosions to deliver premium retro-arcade game styling.
"""

import random
import math
import weakref
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QRect, QPoint, QTime
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush
from theme_manager import is_retro_theme

# Weak registry to dynamically control running widgets when animations are toggled
_active_retro_widgets = weakref.WeakSet()

def register_retro_widget(widget):
    _active_retro_widgets.add(widget)

def sync_all_retro_widgets():
    for w in list(_active_retro_widgets):
        try:
            w.sync_timer()
        except Exception:
            pass

def _home_animations_enabled():
    try:
        import os
        raw = os.environ.get("ANKI_HOME_ANIMATIONS", "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        from data_manager import store
        user_override = store.get().get("_home_animations")
        if user_override is not None:
            return bool(user_override)
    except Exception:
        pass
    return False  # Default to False: keeping hardware strain at 0% by default!

# ── CRT Monitor Scanlines & Sweep Overlay ────────────────────────────────────
class CRTOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self._flicker_opacity = 0.08
        self._boot_flicker_active = False
        self._boot_ticks = 0
        
        # Timer for scanline raster flicker & sweep animation
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        
        register_retro_widget(self)
        self.sync_timer()

    def _is_theme_active(self):
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
            return theme in ("tmnt", "manhattan")
        except Exception:
            return True

    def sync_timer(self):
        should_run = self.isVisible() and _home_animations_enabled() and self._is_theme_active()
        if should_run:
            if not self._timer.isActive():
                interval = 30 if self._boot_flicker_active else 40
                self._timer.start(interval)
        else:
            if self._timer.isActive():
                self._timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.sync_timer()

    def trigger_boot_flicker(self):
        """Simulates a physical cathode ray tube monitor warming up with rapid flashes."""
        if not _home_animations_enabled():
            return
        self._boot_flicker_active = True
        self._boot_ticks = 0
        self.sync_timer()

    def _on_tick(self):
        if not _home_animations_enabled() or not self._is_theme_active():
            self.sync_timer()
            return

        if self._boot_flicker_active:
            self._boot_ticks += 1
            # Rapid high contrast flickering
            if self._boot_ticks < 12:
                # Random drops and spikes
                self._flicker_opacity = random.choice([0.4, 0.05, 0.7, 0.0, 0.9, 0.1])
            else:
                self._boot_flicker_active = False
                self._flicker_opacity = 0.08
                self._timer.start(40) # restore regular frequency
        else:
            # Subtle low-frequency ambient CRT raster buzz
            self._flicker_opacity = random.uniform(0.06, 0.10)
        self.update()

    def paintEvent(self, event):
        # Only draw scanlines if retro mode is active
        if not self._is_theme_active():
            return

        painter = QPainter(self)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False) # retro block pixelation

        h = self.height()
        w = self.width()

        # 1. Repeating 4px horizontal scanlines
        pen = QPen(QColor(0, 0, 0, int(255 * self._flicker_opacity)))
        pen.setWidth(1)
        painter.setPen(pen)
        for y in range(0, h, 4):
            painter.drawLine(0, y, w, y)

        # 2. Scrolling neon cyber sweep line - only when animations are active
        if _home_animations_enabled():
            # Time-based position calculation
            ms = QTime.currentTime().msec() + QTime.currentTime().second() * 1000
            sweep_y = int((ms / 2500.0) * h) % max(1, h)
            
            # Soft cyber neon highlight brush
            sweep_color = QColor(0, 240, 255, 15) # Cyber Cyan glow
            painter.fillRect(0, sweep_y, w, 3, sweep_color)

        painter.restore()


# ── Falling Pixel Particles (Ooze or Pizza) ──────────────────────────────────
class OozeParticle:
    def __init__(self, x, y, size, speed, color):
        self.x = x
        self.y = y
        self.size = size
        self.speed = speed
        self.color = color

class EmberMote:
    """Warm spark drifting upward (candlelight). Used by ARCANUM."""
    def __init__(self, x, y, size, speed, color):
        self.x = x
        self.y = y
        self.size = size
        self.speed = speed      # negative = upward
        self.color = color
        self.life = random.uniform(0.6, 1.0)

class RetroParticlePanel(QWidget):
    def __init__(self, parent=None, is_ooze=True):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.is_ooze = is_ooze
        self.particles = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_particles)
        
        register_retro_widget(self)
        self.sync_timer()

    def _is_theme_active(self):
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
            return is_retro_theme(theme)
        except Exception:
            return True

    def _is_ember_theme(self):
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            return getattr(app, "_active_theme", "classic") == "arcanum"
        except Exception:
            return False

    def sync_timer(self):
        should_run = self.isVisible() and _home_animations_enabled() and self._is_theme_active()
        if should_run:
            if not self.timer.isActive():
                self.timer.start(33) # ~30 FPS
            if not self.particles:
                self.init_particles()
        else:
            if self.timer.isActive():
                self.timer.stop()
            if not _home_animations_enabled() and self.particles:
                self.particles = []
                self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.sync_timer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.init_particles()

    def init_particles(self):
        self.particles = []
        if not _home_animations_enabled() or not self._is_theme_active():
            return
        w = max(10, self.width())
        h = max(10, self.height())
        # Dense particles for sewer ooze, light pizza rain
        if self._is_ember_theme():
            count = 20
        else:
            count = 16 if self.is_ooze else 8
        for _ in range(count):
            self.particles.append(self.create_particle(random.randint(0, h)))

    def create_particle(self, start_y=0):
        if self._is_ember_theme():
            colors = [QColor("#F0A35E"), QColor("#F4D35E"), QColor("#FF5C7A")]
            color = random.choice(colors)
            color.setAlpha(random.randint(80, 200))
            return EmberMote(
                x=random.randint(0, max(10, self.width())),
                y=start_y,
                size=random.randint(2, 5),
                speed=random.uniform(-1.5, -0.4),
                color=color
            )

        # Manhattan project colors: Green/Ooze, Pizza Orange, Accent Cyan
        if self.is_ooze:
            colors = [QColor("#39ff14"), QColor("#00f0ff"), QColor("#32cd32")]
        else:
            colors = [QColor("#ffa200"), QColor("#ff4d5a"), QColor("#00f0ff")]

        color = random.choice(colors)
        color.setAlpha(random.randint(60, 140)) # transparent floating shapes

        return OozeParticle(
            x=random.randint(0, max(10, self.width())),
            y=start_y,
            size=random.randint(3, 6),
            speed=random.uniform(0.6, 2.0),
            color=color
        )

    def update_particles(self):
        if not _home_animations_enabled() or not self._is_theme_active():
            self.sync_timer()
            return
        w = max(10, self.width())
        h = max(10, self.height())
        is_ember = self._is_ember_theme()
        for p in self.particles:
            if is_ember:
                p.y += p.speed
                p.life -= 0.015
                if p.y < 0 or p.life <= 0:
                    p.y = h
                    p.x = random.randint(0, w)
                    p.speed = random.uniform(-1.5, -0.4)
                    p.life = random.uniform(0.6, 1.0)
                    p.color.setAlpha(random.randint(80, 200))
            else:
                p.y += p.speed
                if p.y > h:
                    p.y = 0
                    p.x = random.randint(0, w)
                    p.speed = random.uniform(0.6, 2.0)
        self.update()

    def paintEvent(self, event):
        # Only render if active theme supports it
        if not self._is_theme_active() or not _home_animations_enabled() or not self.particles:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False) # crisp arcade pixel edges
        is_ember = self._is_ember_theme()
        for p in self.particles:
            if is_ember:
                c = QColor(p.color)
                c.setAlpha(int(c.alpha() * max(0.0, min(1.0, p.life))))
                painter.fillRect(int(p.x), int(p.y), p.size, p.size, c)
            else:
                painter.fillRect(int(p.x), int(p.y), p.size, p.size, p.color)


# ── Explosive Particle Burst Overlay ─────────────────────────────────────────
class BurstBlock:
    def __init__(self, x, y, vx, vy, size, color, alpha=255):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.size = size
        self.color = color
        self.alpha = alpha

class ParticleBurstOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.blocks = []
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        
        register_retro_widget(self)
        self.sync_timer()

    def _is_theme_active(self):
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
            return is_retro_theme(theme)
        except Exception:
            return True

    def sync_timer(self):
        should_run = self.isVisible() and _home_animations_enabled() and self._is_theme_active() and bool(self.blocks)
        if should_run:
            if not self.timer.isActive():
                self.timer.start(25) # high refresh rate for physics
        else:
            if self.timer.isActive():
                self.timer.stop()
            if not _home_animations_enabled() and self.blocks:
                self.blocks = []
                self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.sync_timer()

    def spawn_burst(self, px, py, color_tone="cyan", count=25):
        """Spawns an array of blocky pixel chunks exploding from (px, py)."""
        if not _home_animations_enabled() or not self._is_theme_active():
            return
        
        if color_tone == "green":
            colors = [QColor("#39ff14"), QColor("#32cd32"), QColor("#a8ff60")]
        elif color_tone == "red":
            colors = [QColor("#ff0055"), QColor("#ff4d4d"), QColor("#ffa200")]
        else: # cyan / purple / perfect
            try:
                from PyQt5.QtWidgets import QApplication
                app = QApplication.instance()
                theme = getattr(app, "_active_theme", "classic")
            except Exception:
                theme = "classic"
            if theme == "arcanum":
                colors = [QColor("#5FEAD0"), QColor("#A78BFA"), QColor("#EDE6D6")]
            else:
                colors = [QColor("#00f0ff"), QColor("#a86cff"), QColor("#ffffff")]

        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2.5, 7.5)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            size = random.randint(4, 9)
            color = random.choice(colors)
            
            self.blocks.append(BurstBlock(
                x=float(px),
                y=float(py),
                vx=vx,
                vy=vy,
                size=size,
                color=color,
                alpha=255
            ))
        self.sync_timer()
        self.update()

    def _on_tick(self):
        if not self.blocks or not _home_animations_enabled() or not self._is_theme_active():
            self.sync_timer()
            return
        
        # Apply simple drag & gravity to drifting pixel blocks
        active = []
        for b in self.blocks:
            b.x += b.vx
            b.y += b.vy
            b.vx *= 0.93 # drag coefficient
            b.vy *= 0.93
            b.vy += 0.15 # retro gravity pull
            b.alpha -= 8 # fade speed
            
            if b.alpha > 0:
                active.append(b)
        self.blocks = active
        
        if not self.blocks:
            self.sync_timer()
        self.update()

    def paintEvent(self, event):
        if not self.blocks or not _home_animations_enabled() or not self._is_theme_active():
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        for b in self.blocks:
            c = QColor(b.color)
            c.setAlpha(max(0, min(255, b.alpha)))
            painter.fillRect(int(b.x - b.size/2), int(b.y - b.size/2), b.size, b.size, c)


# ── Sliding/Dripping Sewer Ooze Border Decor ────────────────────────────────
class OozeDrip:
    def __init__(self, x, length, max_len, speed):
        self.x = x
        self.length = length
        self.max_len = max_len
        self.speed = speed

class OozeDripWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedHeight(30) # drip height
        self.drips = []
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        
        register_retro_widget(self)
        self.sync_timer()

    def _is_theme_active(self):
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
            return is_retro_theme(theme)
        except Exception:
            return True

    def sync_timer(self):
        should_run = self.isVisible() and _home_animations_enabled() and self._is_theme_active()
        if should_run:
            if not self.timer.isActive():
                self.timer.start(40)
            if not self.drips:
                self.init_drips()
        else:
            if self.timer.isActive():
                self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.sync_timer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.init_drips()

    def init_drips(self):
        self.drips = []
        if not self._is_theme_active():
            return
        w = max(10, self.width())
        # Place drips every 16 pixels
        for x in range(0, w, 16):
            max_len = random.randint(8, 24)
            self.drips.append(OozeDrip(
                x=x,
                length=float(random.randint(0, max_len // 2)),
                max_len=max_len,
                speed=random.uniform(0.1, 0.4)
            ))

    def _tick(self):
        if not _home_animations_enabled() or not self._is_theme_active():
            self.sync_timer()
            return
        for d in self.drips:
            # Oscillate length to simulate dripping fluid tension
            d.length += d.speed
            if d.length > d.max_len or d.length < 2:
                d.speed = -d.speed # drip bounce back
        self.update()

    def paintEvent(self, event):
        if not self._is_theme_active():
            return

        if not self.drips:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        # Get active theme color
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            theme = getattr(app, "_active_theme", "classic")
        except Exception:
            theme = "classic"
            
        if theme == "arcanum":
            drip_color = QColor("#5FEAD0")
        else:
            drip_color = QColor("#39ff14")
            
        pen = QPen(drip_color)
        pen.setWidth(4)
        painter.setPen(pen)
        
        for d in self.drips:
            # Draw a thick blocky line down
            painter.drawLine(d.x, 0, d.x, int(d.length))
            # Draw a dripping drop pixel at the tip
            painter.fillRect(d.x - 2, int(d.length) - 1, 5, 4, drip_color)
