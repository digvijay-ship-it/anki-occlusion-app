"""
Universal Dialog Key Filter
===========================
Ensures consistent keyboard behavior across all confirmation dialogs and message boxes:
- Enter / Return  -> Triggers 'Yes', 'OK', or AcceptRole button.
- Escape          -> Triggers 'No', 'Cancel', or RejectRole button.
"""
from PyQt5.QtCore import QObject, QEvent, Qt
from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget


class UniversalDialogKeyFilter(QObject):
    """
    Application-wide event filter that intercepts KeyPress events on QMessageBox
    and its children to provide universal Enter (Yes) and Escape (No/Cancel) navigation.
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            # Check if event target is a QMessageBox or within a QMessageBox
            msg_box = None
            if isinstance(obj, QMessageBox):
                msg_box = obj
            elif isinstance(obj, QWidget):
                p = obj
                while p is not None:
                    if isinstance(p, QMessageBox):
                        msg_box = p
                        break
                    p = p.parentWidget()

            if msg_box is not None:
                key = event.key()

                # Handle ENTER / RETURN -> YES / OK / Accept
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    # 1. Check for standard QMessageBox.Yes button
                    yes_btn = msg_box.button(QMessageBox.Yes)
                    if yes_btn is not None and yes_btn.isEnabled():
                        yes_btn.click()
                        return True

                    # 2. Check for standard QMessageBox.Ok button
                    ok_btn = msg_box.button(QMessageBox.Ok)
                    if ok_btn is not None and ok_btn.isEnabled():
                        ok_btn.click()
                        return True

                    # 3. Check for any button with AcceptRole or YesRole
                    for btn in msg_box.buttons():
                        if msg_box.buttonRole(btn) in (QMessageBox.AcceptRole, QMessageBox.YesRole) and btn.isEnabled():
                            btn.click()
                            return True

                    # 4. Check for default button
                    def_btn = msg_box.defaultButton()
                    if def_btn is not None and def_btn.isEnabled():
                        def_btn.click()
                        return True

                    # 5. Fallback: click first enabled button
                    for btn in msg_box.buttons():
                        if btn.isEnabled():
                            btn.click()
                            return True
                    return True

                # Handle ESCAPE -> NO / CANCEL / Reject
                elif key == Qt.Key_Escape:
                    # 1. Check for standard QMessageBox.Cancel button
                    cancel_btn = msg_box.button(QMessageBox.Cancel)
                    if cancel_btn is not None and cancel_btn.isEnabled():
                        cancel_btn.click()
                        return True

                    # 2. Check for standard QMessageBox.No button
                    no_btn = msg_box.button(QMessageBox.No)
                    if no_btn is not None and no_btn.isEnabled():
                        no_btn.click()
                        return True

                    # 3. Check for explicit escape button
                    esc_btn = msg_box.escapeButton()
                    if esc_btn is not None and esc_btn.isEnabled():
                        esc_btn.click()
                        return True

                    # 4. Check for any button with RejectRole or NoRole
                    for btn in msg_box.buttons():
                        if msg_box.buttonRole(btn) in (QMessageBox.RejectRole, QMessageBox.NoRole) and btn.isEnabled():
                            btn.click()
                            return True

                    # 5. Check for button with DestructiveRole
                    for btn in msg_box.buttons():
                        if msg_box.buttonRole(btn) == QMessageBox.DestructiveRole and btn.isEnabled():
                            btn.click()
                            return True

                    # 6. If Ok button is present and no cancel/no exists (e.g. info/warning), dismiss via Ok
                    ok_btn = msg_box.button(QMessageBox.Ok)
                    if ok_btn is not None and ok_btn.isEnabled():
                        ok_btn.click()
                        return True

                    # 7. Fallback: reject dialog
                    msg_box.reject()
                    return True

        return super().eventFilter(obj, event)


_GLOBAL_FILTER_INSTANCE = None


def install_dialog_key_filter(app=None):
    """
    Installs the UniversalDialogKeyFilter on the QApplication instance.
    Idempotent: safe to call multiple times without creating duplicates.
    """
    global _GLOBAL_FILTER_INSTANCE
    if _GLOBAL_FILTER_INSTANCE is not None:
        return _GLOBAL_FILTER_INSTANCE

    target_app = app or QApplication.instance()
    if target_app is not None:
        _GLOBAL_FILTER_INSTANCE = UniversalDialogKeyFilter(target_app)
        target_app.installEventFilter(_GLOBAL_FILTER_INSTANCE)
    return _GLOBAL_FILTER_INSTANCE
