"""
thread_manager.py — Centralized lifecycle management for background QThreads.
Ensures clean teardown, prevents ghost threads, and simplifies cancellation.
"""

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from typing import Dict, List, Optional, Any
import time

class ThreadManager(QObject):
    """
    A registry for all active background threads.
    Tracks thread state and ensures they are cleanly terminated on close.
    """
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._threads: Dict[str, QThread] = {}

    def register(self, tag: str, thread: QThread) -> None:
        """
        Register a thread under a specific tag.
        If a thread with the same tag exists, it is stopped first.
        """
        self.stop(tag)
        self._threads[tag] = thread
        thread.finished.connect(lambda: self._on_thread_finished(tag))

    def _on_thread_finished(self, tag: str) -> None:
        """Cleanup after a thread finishes naturally."""
        if tag in self._threads:
            del self._threads[tag]

    def stop(self, tag: str, wait_ms: int = 500) -> None:
        """
        Safely stop and join a specific thread by tag.
        """
        thread = self._threads.pop(tag, None)
        if thread and thread.isRunning():
            if hasattr(thread, "stop"):
                thread.stop()
            thread.quit()
            if not thread.wait(wait_ms):
                print(f"[ThreadManager] ⚠ Thread '{tag}' timed out during wait — terminating.")
                thread.terminate()
                thread.wait()

    def stop_all(self, wait_ms: int = 1000) -> None:
        """
        Stop all registered threads (call on app exit).
        """
        tags = list(self._threads.keys())
        for tag in tags:
            self.stop(tag, wait_ms=wait_ms)
        self._threads.clear()

    def is_running(self, tag: str) -> bool:
        """Check if a specific thread is currently active."""
        thread = self._threads.get(tag)
        return thread is not None and thread.isRunning()

# Global singleton for the application
manager = ThreadManager()
