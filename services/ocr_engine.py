import os
import subprocess
import base64
import io
import threading
import time
import tempfile
import queue

from PyQt5.QtCore import QThread, pyqtSignal, QObject

class OcrSignals(QObject):
    ready = pyqtSignal()

SIGNALS = OcrSignals()

_worker_process = None
_worker_lock = threading.RLock()
_worker_io_lock = threading.Lock()
_worker_ready = False
_worker_started = False
_worker_thread = None
_worker_ready_event = threading.Event()


def _readline_with_timeout(proc, timeout=15):
    """Read one line from worker stdout with a timeout using a queue."""
    q = queue.Queue()
    def _reader():
        try:
            line = proc.stdout.readline()
            q.put(line)
        except Exception:
            q.put(None)
    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        res = q.get(timeout=timeout)
        if res is None:
            return ""
        return res
    except queue.Empty:
        return ""


def _reset_worker_state(proc=None):
    global _worker_process, _worker_ready, _worker_started
    with _worker_lock:
        if proc is not None and _worker_process is not proc:
            return
        old_proc = _worker_process
        _worker_process = None
        _worker_ready = False
        _worker_started = False
        _worker_ready_event.clear()
    if old_proc is not None:
        try:
            if old_proc.stdin:
                old_proc.stdin.write("EXIT\n")
                old_proc.stdin.flush()
        except Exception:
            pass
        try:
            if old_proc.poll() is None:
                old_proc.terminate()
        except Exception:
            pass


def _init_worker_thread():
    global _worker_process, _worker_ready, _worker_started
    script_path = os.path.join(os.path.dirname(__file__), "tf_worker.py")
    try:
        print("[ocr_engine] Booting local TF background worker...")
        log_path = os.path.join(tempfile.gettempdir(), 'anki_tf_worker.log')
        try:
            stderr_log = open(log_path, "a", encoding="utf-8")
        except Exception:
            stderr_log = subprocess.DEVNULL
            
        proc = subprocess.Popen(
            [os.sys.executable, script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_log,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # Block until worker loads model and prints READY
        ready_msg = _readline_with_timeout(proc, timeout=30).strip()
        if ready_msg == "READY":
            with _worker_lock:
                _worker_process = proc
                _worker_ready = True
                _worker_ready_event.set()
            print("[ocr_engine] Local TF background worker is READY!")
            SIGNALS.ready.emit()
        else:
            with _worker_lock:
                _worker_started = False
            try:
                proc.terminate()
            except Exception:
                pass
            print(f"[ocr_engine] TF background worker error: {ready_msg}")
    except Exception as e:
        with _worker_lock:
            _worker_started = False
        print(f"[ocr_engine] Failed to start local worker process: {e}")


def _ensure_worker_started():
    global _worker_started, _worker_thread
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        _worker_thread = threading.Thread(
            target=_init_worker_thread, daemon=True, name="OCR-TF-Worker-Boot"
        )
        _worker_thread.start()


def warm_up():
    """Eager-starts the OCR worker subprocess in the background."""
    _ensure_worker_started()


def shutdown():
    """Stops the OCR worker subprocess and frees memory."""
    print("[ocr_engine] Shutting down OCR background worker...")
    _reset_worker_state()


def is_ready() -> bool:
    """Returns True if the OCR worker is loaded and ready."""
    with _worker_lock:
        return _worker_ready


def ocr_number(pil_img, _retried=False) -> str:
    _ensure_worker_started()
    print("[ocr_engine] Requesting local subprocess OCR prediction...")

    # Wait up to 30s for worker to boot (first call after Anki loads)
    with _worker_lock:
        ready = _worker_ready
    if not ready:
        if not _worker_ready_event.wait(timeout=30):
            print("[ocr_engine] Worker failed to boot in time.")
            return ""

    with _worker_lock:
        proc = _worker_process if _worker_ready else None
        if proc is None:
            print("[ocr_engine] Worker failed to boot.")
            return ""

    with _worker_io_lock:
        with _worker_lock:
            if not _worker_ready or _worker_process is not proc:
                  print("[ocr_engine] Worker is not ready.")
                  return ""

        try:
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

            proc.stdin.write(b64_str + "\n")
            proc.stdin.flush()

            response = _readline_with_timeout(proc, timeout=15).strip()

            if response.startswith("RESULT:"):
                res = response[len("RESULT:") :]
                print(f"[ocr_engine] Local Worker predicted: '{res}'")
                return res
            if response == "":
                _reset_worker_state(proc)
                print("[ocr_engine] Local Worker exited unexpectedly.")
                if not _retried:
                    print("[ocr_engine] Retrying OCR request once...")
                    _ensure_worker_started()
                    return ocr_number(pil_img, _retried=True)
                return ""
            else:
                print(f"[ocr_engine] Local Worker returned error: {response}")
                return ""
        except Exception as e:
            _reset_worker_state(proc)
            print(f"[ocr_engine] Subprocess communication error: {e}")
            if not _retried:
                print("[ocr_engine] Retrying OCR request once...")
                _ensure_worker_started()
                return ocr_number(pil_img, _retried=True)
            return ""


class OcrNumberThread(QThread):
    result = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, pil_img, parent=None):
        super().__init__(parent)
        self._pil_img = pil_img

    def run(self):
        print("[DEBUG][ocr_async] start")
        try:
            predicted = ocr_number(self._pil_img)
        except Exception as exc:
            print(f"[DEBUG][ocr_async] failed error={exc}")
            self.failed.emit(str(exc))
            self.result.emit("")
            return
        print(f"[DEBUG][ocr_async] done result={predicted!r}")
        self.result.emit(predicted or "")
