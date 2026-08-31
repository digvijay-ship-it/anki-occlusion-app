from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QTimer, QSize
from PyQt5.QtGui import QCursor

def apply_queue_drawer_state(self, recenter: bool = True):
    queue_panel = self.__dict__.get("_queue_panel")
    queue_list = self.__dict__.get("_queue_list")
    edge_button = self.__dict__.get("_queue_edge_button")
    lock_button = self.__dict__.get("_queue_lock_button")
    hide_button = self.__dict__.get("_queue_hide_button")
    if queue_panel is None:
        return

    locked = bool(self.__dict__.get("_queue_locked", True))
    open_now = locked or bool(self.__dict__.get("_queue_drawer_open", True))
    self._set_queue_panel_docked(locked)
    if not locked:
        queue_panel.hide()
    if queue_list is not None:
        queue_list.setVisible(open_now)

    if lock_button is not None:
        lock_button.setText("🔒" if locked else "🔓")
        lock_button.setToolTip(
            "Queue locked open" if locked else "Queue unlocked"
        )
    if hide_button is not None:
        hide_button.setVisible(not locked)
        hide_button.setText("›" if open_now else "‹")
        hide_button.setToolTip(
            "Hide queue items" if open_now else "Show queue items"
        )
    if edge_button is not None:
        edge_button.setVisible(False)
        self._queue_edge_handle_visible = False

    self._reposition_queue_overlay()
    queue_panel.setVisible(open_now)
    self._update_floating_timer_visibility()

    if locked or not open_now:
        self._cancel_queue_auto_hide()

    if recenter:
        QTimer.singleShot(0, self._trigger_center_fit)

def set_queue_panel_docked(self, docked: bool):
    queue_panel = self.__dict__.get("_queue_panel")
    canvas_stage = self.__dict__.get("_canvas_stage")
    mid_layout = self.__dict__.get("_mid_layout")
    mid_widget = self.__dict__.get("_mid_widget")
    if (
        queue_panel is None
        or canvas_stage is None
        or mid_layout is None
        or mid_widget is None
    ):
        return

    if docked:
        if self.__dict__.get("_queue_panel_docked", True):
            queue_panel.setFixedWidth(200)
            queue_panel.setMinimumHeight(0)
            queue_panel.setMaximumHeight(16777215)
            return
        queue_panel.hide()
        queue_panel.setParent(mid_widget)
        mid_layout.addWidget(queue_panel)
        self._queue_panel_docked = True
        queue_panel.setFixedWidth(200)
        queue_panel.setMinimumHeight(0)
        queue_panel.setMaximumHeight(16777215)
        queue_panel.show()
        return

    if not self.__dict__.get("_queue_panel_docked", True):
        return
    queue_panel.hide()
    mid_layout.removeWidget(queue_panel)
    queue_panel.setParent(canvas_stage)
    self._queue_panel_docked = False
    queue_panel.setFixedWidth(200)

def reposition_queue_overlay(self):
    queue_panel = self.__dict__.get("_queue_panel")
    canvas_stage = self.__dict__.get("_canvas_stage")
    if (
        queue_panel is None
        or canvas_stage is None
        or self.__dict__.get("_queue_panel_docked", True)
    ):
        return

    width = 200
    locked = bool(self.__dict__.get("_queue_locked", True))
    open_now = locked or bool(self.__dict__.get("_queue_drawer_open", True))
    queue_panel.setFixedWidth(width)
    if open_now:
        queue_panel.setMinimumHeight(0)
        queue_panel.setMaximumHeight(16777215)
        queue_panel.setFixedHeight(max(1, canvas_stage.height()))
    else:
        queue_panel.adjustSize()
        compact_height = min(
            max(queue_panel.sizeHint().height(), queue_panel.minimumSizeHint().height()),
            max(1, canvas_stage.height()),
        )
        queue_panel.setFixedHeight(compact_height)

    queue_panel.move(max(0, canvas_stage.width() - width - 8), 0)
    queue_panel.raise_()

def reposition_queue_edge_handle(self):
    edge_button = self.__dict__.get("_queue_edge_button")
    if edge_button is None:
        return
    width = max(edge_button.sizeHint().width(), 28)
    height = max(edge_button.sizeHint().height(), 58)
    edge_button.setFixedSize(width, height)
    edge_button.move(
        max(0, self.width() - width),
        max(0, (self.height() - height) // 2),
    )

def event_pos_in_self(self, event, source=None):
    try:
        global_pos = event.globalPos()
        if global_pos is not None:
            return self.mapFromGlobal(global_pos)
    except Exception:
        pass
    if isinstance(source, QWidget):
        try:
            return source.mapTo(self, event.pos())
        except Exception:
            pass
    try:
        return event.pos()
    except Exception:
        return None

def queue_edge_handle_hot(self, pos) -> bool:
    if pos is None:
        return False
    edge_button = self.__dict__.get("_queue_edge_button")
    if isinstance(edge_button, QWidget) and not edge_button.isHidden():
        grace = int(self.QUEUE_EDGE_HANDLE_GRACE_PX)
        if edge_button.geometry().adjusted(-grace, -grace, grace, grace).contains(pos):
            return True
    try:
        return pos.x() >= self.width() - int(self.QUEUE_EDGE_HANDLE_HOT_ZONE_PX)
    except Exception:
        return False

def hide_queue_edge_handle(self, reason: str = "left_edge"):
    edge_button = self.__dict__.get("_queue_edge_button")
    if edge_button is None:
        return
    self._queue_edge_handle_visible = False
    edge_button.hide()

def maybe_show_queue_edge_handle(self, event, source=None):
    queue_panel = self.__dict__.get("_queue_panel")
    if queue_panel is not None and queue_panel.isVisible():
        self._hide_queue_edge_handle("queue_visible")
        return
    if self.__dict__.get("_queue_locked", True):
        self._hide_queue_edge_handle("locked")
        return
    if self.__dict__.get("_queue_drawer_open", True):
        self._hide_queue_edge_handle("queue_open")
        return
    edge_button = self.__dict__.get("_queue_edge_button")
    if edge_button is None:
        return
    if not self._queue_edge_handle_hot(self._event_pos_in_self(event, source)):
        self._hide_queue_edge_handle("left_edge")
        return
    self._reposition_queue_edge_handle()
    self._queue_edge_handle_visible = True
    edge_button.show()
    edge_button.raise_()

def event_global_pos(self, event):
    try:
        return event.globalPos()
    except Exception:
        return QCursor.pos()

def queue_contains_global_pos(self, global_pos) -> bool:
    queue_panel = self.__dict__.get("_queue_panel")
    if queue_panel is None or not queue_panel.isVisible():
        return False
    return queue_panel.rect().contains(queue_panel.mapFromGlobal(global_pos))

def cancel_queue_auto_hide(self):
    timer = self.__dict__.get("_queue_auto_hide_timer")
    if timer is not None:
        timer.stop()

def schedule_queue_auto_hide(self):
    timer = self.__dict__.get("_queue_auto_hide_timer")
    if timer is not None:
        if not timer.isActive():
            timer.start(self.QUEUE_AUTO_HIDE_MS)

def update_queue_auto_hide_from_event(self, event):
    if self.__dict__.get("_queue_locked", True):
        self._cancel_queue_auto_hide()
        return
    if not self.__dict__.get("_queue_drawer_open", True):
        self._cancel_queue_auto_hide()
        return
    queue_panel = self.__dict__.get("_queue_panel")
    if queue_panel is None or not queue_panel.isVisible():
        self._cancel_queue_auto_hide()
        return
    if self._queue_contains_global_pos(self._event_global_pos(event)):
        self._cancel_queue_auto_hide()
    else:
        self._schedule_queue_auto_hide()

def hide_queue_drawer_after_delay(self):
    if self.__dict__.get("_queue_locked", True):
        return
    if not self.__dict__.get("_queue_drawer_open", True):
        return
    if self._queue_contains_global_pos(QCursor.pos()):
        self._cancel_queue_auto_hide()
        return
    self._hide_queue_drawer()
