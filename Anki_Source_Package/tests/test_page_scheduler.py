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

    def test_not_done_count_and_completion_tracking(self):
        scheduler = PageScheduler(MagicMock())
        scheduler._path = "deck.pdf"
        scheduler.pages = {
            0: PageState(status="not_loaded"),
            1: PageState(status="not_loaded"),
            2: PageState(status="not_loaded"),
        }
        # Initially, self._not_done_count is None.
        # Check completion triggers initialization
        scheduler._check_completion()
        self.assertEqual(scheduler._not_done_count, 3)

        # Transition 0 to loading (still not done)
        scheduler._update_page_status(0, "loading")
        self.assertEqual(scheduler._not_done_count, 3)

        # Transition 0 to loaded (done!)
        scheduler._update_page_status(0, "loaded")
        self.assertEqual(scheduler._not_done_count, 2)

        # Transition 1 to injected (done!)
        scheduler._update_page_status(1, "injected")
        self.assertEqual(scheduler._not_done_count, 1)

        # Transition 1 back to not_loaded (oops, not done again!)
        scheduler._update_page_status(1, "not_loaded")
        self.assertEqual(scheduler._not_done_count, 2)

        # Complete the rest
        scheduler._update_page_status(1, "loaded")
        scheduler._update_page_status(2, "loaded")
        self.assertEqual(scheduler._not_done_count, 0)
        
        # Verify signal emission on completion
        scheduler.all_done = MagicMock()
        scheduler._check_completion()
        scheduler.all_done.emit.assert_called_once()

    def test_enqueue_queue_capping(self):
        scheduler = PageScheduler(MagicMock())
        scheduler._path = "deck.pdf"
        scheduler.pages = {i: PageState() for i in range(100)}
        for i in range(100):
            scheduler.pages[i].priority = i
        
        for i in range(64):
            scheduler._enqueue_if_not_present(i)
        
        self.assertEqual(len(scheduler.inject_queue), 64)
        self.assertIn(63, scheduler._inject_set)
        
        scheduler._enqueue_if_not_present(64)
        self.assertEqual(len(scheduler.inject_queue), 64)
        self.assertNotIn(63, scheduler._inject_set)
        self.assertIn(64, scheduler._inject_set)


if __name__ == "__main__":
    unittest.main()
