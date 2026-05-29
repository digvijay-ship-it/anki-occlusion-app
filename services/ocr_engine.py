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


# ── Model Training ────────────────────────────────────────────────────────────


def _get_model(force_retrain=True):
    """
    Trains an advanced, highly robust CNN OCR model on a 3x expanded
    offline augmented MNIST dataset. Uses deep conv layers, batch normalization,
    dropout, learning rate callbacks, and saves it to the standard path.
    """
    import tensorflow as tf
    from tensorflow.keras import callbacks
    import cv2
    import numpy as np

    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = os.path.normpath(os.path.join(current_dir, "..", "assets", "model"))
    model_path = os.path.join(model_dir, "mnist_math_cnn.keras")

    if not force_retrain and os.path.exists(model_path):
        try:
            print(f"[ocr_engine] Loading existing model from {model_path}")
            return tf.keras.models.load_model(model_path)
        except Exception as e:
            print(f"[ocr_engine] Failed to load existing model: {e}. Re-training...")

    print("[ocr_engine] Loading MNIST dataset...")
    (x_train, y_train), (x_test, y_test) = tf.keras.datasets.mnist.load_data()

    print("[ocr_engine] Generating 3x expanded augmented dataset offline using OpenCV...")
    augmented_x = []
    augmented_y = []

    def augment(img):
        # Random rotation (-12 to 12 degrees)
        angle = np.random.uniform(-12, 12)
        M_rot = cv2.getRotationMatrix2D((14, 14), angle, 1.0)
        img_aug = cv2.warpAffine(img, M_rot, (28, 28))

        # Random translation (-3 to 3 pixels)
        dx = np.random.randint(-3, 4)
        dy = np.random.randint(-3, 4)
        M_trans = np.float32([[1, 0, dx], [0, 1, dy]])
        img_aug = cv2.warpAffine(img_aug, M_trans, (28, 28))

        # Random zoom (0.88 to 1.12 factor)
        zoom = np.random.uniform(0.88, 1.12)
        M_zoom = cv2.getRotationMatrix2D((14, 14), 0, zoom)
        img_aug = cv2.warpAffine(img_aug, M_zoom, (28, 28))

        return img_aug

    for i in range(len(x_train)):
        img = x_train[i]
        lbl = y_train[i]
        
        # 1. Original
        augmented_x.append(img.reshape(28, 28, 1))
        augmented_y.append(lbl)
        
        # 2. Augmentation Copy A
        augmented_x.append(augment(img).reshape(28, 28, 1))
        augmented_y.append(lbl)
        
        # 3. Augmentation Copy B
        augmented_x.append(augment(img).reshape(28, 28, 1))
        augmented_y.append(lbl)

    x_train_expanded = np.array(augmented_x, dtype='float32') / 255.0
    y_train_expanded = np.array(augmented_y, dtype='int32')

    x_test_expanded = x_test.reshape(-1, 28, 28, 1).astype('float32') / 255.0
    y_test_expanded = y_test.astype('int32')

    print(f"[ocr_engine] Dataset expanded to {len(x_train_expanded)} training images.")
    print("[ocr_engine] Initializing Advanced Deep CNN structure...")

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(28, 28, 1)),
        
        # Conv Block 1
        tf.keras.layers.Conv2D(32, (3, 3), padding='same', activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Conv2D(32, (3, 3), padding='same', activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.MaxPooling2D((2, 2)),
        tf.keras.layers.Dropout(0.25),
        
        # Conv Block 2
        tf.keras.layers.Conv2D(64, (3, 3), padding='same', activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Conv2D(64, (3, 3), padding='same', activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.MaxPooling2D((2, 2)),
        tf.keras.layers.Dropout(0.25),
        
        # Conv Block 3
        tf.keras.layers.Conv2D(128, (3, 3), padding='same', activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.MaxPooling2D((2, 2)),
        tf.keras.layers.Dropout(0.3),
        
        # Classification dense block
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(256, activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.5),
        tf.keras.layers.Dense(10, activation='softmax')
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )

    lr_reduction = callbacks.ReduceLROnPlateau(
        monitor='val_loss',
        patience=4,
        verbose=1,
        factor=0.5,
        min_lr=1e-6
    )

    early_stopping = callbacks.EarlyStopping(
        monitor='val_accuracy',
        patience=15,
        restore_best_weights=True,
        verbose=1
    )

    os.makedirs(model_dir, exist_ok=True)
    
    # 10 epochs on 180k images runs for about 60-80 mins on CPU, ensuring deep training
    print("[ocr_engine] Commencing training (10 epochs, batch size 128)...")
    model.fit(
        x_train_expanded, y_train_expanded,
        epochs=10,
        batch_size=128,
        validation_data=(x_test_expanded, y_test_expanded),
        callbacks=[lr_reduction, early_stopping]
    )
    
    model.save(model_path)
    print(f"[ocr_engine] Advanced model trained and saved successfully to: {model_path}")
    return model

