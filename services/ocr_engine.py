import os
import subprocess
import base64
import io
import threading
import time

_worker_process = None
_worker_lock = threading.Lock()
_worker_ready = False


def _init_worker_thread():
    global _worker_process, _worker_ready
    script_path = os.path.join(os.path.dirname(__file__), "tf_worker.py")
    try:
        print("[ocr_engine] Booting local TF background worker...")
        proc = subprocess.Popen(
            ["python", script_path],
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
            print(f"[ocr_engine] TF background worker error: {ready_msg}")
    except Exception as e:
        print(f"[ocr_engine] Failed to start local worker process: {e}")


threading.Thread(target=_init_worker_thread, daemon=True).start()


def ocr_number(pil_img) -> str:
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
        if not _worker_ready or _worker_process is None:
            print("[ocr_engine] Worker failed to boot.")
            return ""

        try:
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

            _worker_process.stdin.write(b64_str + "\n")
            _worker_process.stdin.flush()

            response = _worker_process.stdout.readline().strip()

            if response.startswith("RESULT:"):
                res = response[len("RESULT:") :]
                print(f"[ocr_engine] Local Worker predicted: '{res}'")
                return res
            else:
                print(f"[ocr_engine] Local Worker returned error: {response}")
                return ""
        except Exception as e:
            print(f"[ocr_engine] Subprocess communication error: {e}")
            return ""
