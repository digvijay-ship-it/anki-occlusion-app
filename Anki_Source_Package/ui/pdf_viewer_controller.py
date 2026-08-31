from PyQt5.QtCore import QTimer


class PdfViewerController:
    """
    Shared PDF viewer behavior for editor, review, and annotation.

    This controller only handles viewer interaction/state:
      - fit-width zoom
      - page UI sync
      - prev/next/jump navigation
      - restore page after load

    It intentionally does NOT own loading, saving, or review/editor-specific logic.
    """

    def __init__(
        self,
        *,
        canvas,
        scroll_area,
        page_input,
        page_total_label,
        prev_button,
        next_button,
        total_pages_getter=None,
        debug_hook=None,
    ):
        self.canvas = canvas
        self.scroll_area = scroll_area
        self.page_input = page_input
        self.page_total_label = page_total_label
        self.prev_button = prev_button
        self.next_button = next_button
        self.total_pages_getter = total_pages_getter
        self.debug_hook = debug_hook or (lambda *_args, **_kwargs: None)
        self._ui_page_zero = 0
        self._nav_seq = 0
        self._manual_zoom = False

    def page_count(self) -> int:
        if self.total_pages_getter is not None:
            try:
                total = int(self.total_pages_getter() or 0)
                if total >= 0:
                    return total
            except Exception:
                pass
        return int(len(getattr(self.canvas, "_pages", []) or []))

    def current_page(self) -> int:
        total = self.page_count()
        if total <= 0:
            return 0
        value = self.scroll_area.verticalScrollBar().value()
        return max(0, min(int(self.canvas.get_current_page(value)), total - 1))

    def set_page_ui(self, current_zero: int) -> None:
        total = self.page_count()
        if total <= 0:
            self._ui_page_zero = 0
            self.page_input.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.page_total_label.setText("/ 0")
            self.page_input.clear()
            return
        current_zero = max(0, min(int(current_zero), total - 1))
        self._ui_page_zero = current_zero
        self.page_input.setEnabled(True)
        self.prev_button.setEnabled(current_zero > 0)
        self.next_button.setEnabled(current_zero < total - 1)
        self.page_total_label.setText(f"/ {total}")
        self.page_input.setText(str(current_zero + 1))

    def refresh_page_ui(self, *_args) -> None:
        self.set_page_ui(self.current_page())

    def fit_width(self, force: bool = False) -> None:
        if self.page_count() <= 0:
            return
        if not force and self._manual_zoom:
            return
        self.canvas.zoom_fit_width(self.scroll_area.viewport().width())
        self.debug_hook("fit_width", force=force, page=self.current_page() + 1)

    def reset_fit(self) -> None:
        self._manual_zoom = False
        self.fit_width(force=True)

    def on_resize(self) -> None:
        self.fit_width(force=False)

    def zoom_in(self) -> None:
        if self.page_count() <= 0:
            return
        self._manual_zoom = True
        self.canvas.zoom_in()
        self.debug_hook("zoom_in", scale=getattr(self.canvas, "_scale", None))
        self.refresh_page_ui()

    def zoom_out(self) -> None:
        if self.page_count() <= 0:
            return
        self._manual_zoom = True
        self.canvas.zoom_out()
        self.debug_hook("zoom_out", scale=getattr(self.canvas, "_scale", None))
        self.refresh_page_ui()

    def go_to_page(self, page_zero: int) -> None:
        total = self.page_count()
        if total <= 0:
            return
        page_zero = max(0, min(int(page_zero), total - 1))
        self._nav_seq += 1
        nav_seq = self._nav_seq
        self.debug_hook(
            "goto", seq=nav_seq, target=page_zero + 1, current=self._ui_page_zero + 1
        )
        self.set_page_ui(page_zero)
        try:
            self.canvas.setFocus()
        except Exception:
            pass
        self.canvas.scroll_to_page(page_zero, self.scroll_area)
        QTimer.singleShot(
            0, lambda pg=page_zero: self.canvas.scroll_to_page(pg, self.scroll_area)
        )
        QTimer.singleShot(
            35, lambda pg=page_zero: self.canvas.scroll_to_page(pg, self.scroll_area)
        )
        QTimer.singleShot(
            80,
            lambda seq=nav_seq, target=page_zero: self._finalize_page_jump(seq, target),
        )

    def _finalize_page_jump(self, seq: int, target: int) -> None:
        if seq != self._nav_seq:
            return
        actual = self.current_page()
        self.debug_hook("settled", seq=seq, target=target + 1, actual=actual + 1)
        self.set_page_ui(actual)

    def nav_current_page(self) -> int:
        total = self.page_count()
        if total <= 0:
            return 0
        return max(0, min(self._ui_page_zero, total - 1))

    def go_prev_page(self) -> None:
        self.go_to_page(self.nav_current_page() - 1)

    def go_next_page(self) -> None:
        self.go_to_page(self.nav_current_page() + 1)

    def jump_from_input(self) -> None:
        try:
            page_one = int((self.page_input.text() or "1").strip())
        except ValueError:
            self.refresh_page_ui()
            return
        self.go_to_page(page_one - 1)

    def restore_position(self, page_zero=None, scroll_value=None) -> None:
        if page_zero is not None:
            QTimer.singleShot(0, lambda pg=int(page_zero): self.go_to_page(pg))
            return
        if scroll_value is not None:
            QTimer.singleShot(
                0,
                lambda sv=int(
                    scroll_value
                ): self.scroll_area.verticalScrollBar().setValue(sv),
            )
