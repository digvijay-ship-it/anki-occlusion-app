import os
import subprocess
import base64
import io
import threading
import time

from PyQt5.QtCore import QThread, pyqtSignal

_worker_process = None
_worker_lock = threading.RLock()
_worker_io_lock = threading.Lock()
_worker_ready = False
_worker_started = False
_worker_thread = None


def _reset_worker_state(proc=None):
    global _worker_process, _worker_ready, _worker_started
    with _worker_lock:
        if proc is not None and _worker_process is not proc:
            return
        old_proc = _worker_process
        _worker_process = None
        _worker_ready = False
        _worker_started = False
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
        proc = subprocess.Popen(
            [os.sys.executable, script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # Block until worker loads model and prints READY
        ready_msg = proc.stdout.readline().strip()
        if ready_msg == "READY":
            with _worker_lock:
                _worker_process = proc
                _worker_ready = True
            print("[ocr_engine] Local TF background worker is READY!")
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


def ocr_number(pil_img) -> str:
    _ensure_worker_started()
    print("[ocr_engine] Requesting local subprocess OCR prediction...")

    # Wait up to 30s for worker to boot (first call after Anki loads)
    deadline = time.time() + 30
    while time.time() < deadline:
        with _worker_lock:
            ready = _worker_ready
        if ready:
            break
        print("[ocr_engine] Worker still booting, waiting...")
        time.sleep(0.5)

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

            response = proc.stdout.readline().strip()

            if response.startswith("RESULT:"):
                res = response[len("RESULT:") :]
                print(f"[ocr_engine] Local Worker predicted: '{res}'")
                return res
            if response == "":
                _reset_worker_state(proc)
                print("[ocr_engine] Local Worker exited unexpectedly.")
                return ""
            else:
                print(f"[ocr_engine] Local Worker returned error: {response}")
                return ""
        except Exception as e:
            _reset_worker_state(proc)
            print(f"[ocr_engine] Subprocess communication error: {e}")
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
