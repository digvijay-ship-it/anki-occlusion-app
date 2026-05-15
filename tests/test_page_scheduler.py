import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

from page_scheduler import PageScheduler, PageState


class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _FakeWorker:
    def __init__(self):
        self.page_ready = _FakeSignal()
        self.batch_done = _FakeSignal()
        self.error = _FakeSignal()
        self._running = False
        self.stop_called = False
        self.quit_called = False
        self.wait_called = False

    def isRunning(self):
        return self._running

    def start(self):
        self._running = True

    def stop(self):
        self.stop_called = True
        self._running = False

    def quit(self):
        self.quit_called = True

    def wait(self, _ms):
        self.wait_called = True
        return True


class PageSchedulerWorkerTests(unittest.TestCase):
    def _scheduler(self):
        scheduler = PageScheduler(MagicMock())
        scheduler._path = "deck.pdf"
        scheduler._last_visible = (0, 1)
        scheduler.pages = {0: PageState(), 1: PageState()}
        return scheduler

    def test_replaced_worker_signals_do_not_load_or_enqueue_stale_pages(self):
        scheduler = self._scheduler()
        first_worker = _FakeWorker()
        second_worker = _FakeWorker()
        pixmap = QPixmap(12, 12)
        pixmap.fill()

        with patch(
            "page_scheduler.PdfOnDemandThread",
            side_effect=[first_worker, second_worker],
        ):
            scheduler._start_worker([0], kind="background")
            old_page_ready = first_worker.page_ready.slots[0]
            old_batch_done = first_worker.batch_done.slots[0]

            scheduler._start_worker([1], kind="visible")

        self.assertTrue(first_worker.stop_called)
        self.assertEqual(scheduler.pages[0].status, "not_loaded")
        self.assertEqual(scheduler.pages[1].status, "loading")
        self.assertEqual(scheduler._worker_kind, "visible")

        old_batch_done([0])
        old_page_ready(0, pixmap)

        self.assertEqual(scheduler.pages[0].status, "not_loaded")
        self.assertNotIn(0, scheduler._inject_set)
        self.assertEqual(list(scheduler.inject_queue), [])
        self.assertEqual(scheduler._worker_kind, "visible")

        second_worker.page_ready.slots[0](1, pixmap)

        self.assertEqual(scheduler.pages[1].status, "loaded")
        self.assertEqual(list(scheduler.inject_queue), [1])


if __name__ == "__main__":
    unittest.main()
