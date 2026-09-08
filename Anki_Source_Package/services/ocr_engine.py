import os
import cv2
import numpy as np
from PIL import Image, ImageOps
import threading
from PyQt5.QtCore import QThread, pyqtSignal, QObject

try:
    from storage_paths import app_resource_path
except ImportError:
    def app_resource_path(*parts):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(current_dir, "..", *parts))

class OcrSignals(QObject):
    ready = pyqtSignal()

SIGNALS = OcrSignals()

_net = None
_net_lock = threading.Lock()

_warmup_done = False

def warm_up():
    """Eager-loads the ONNX model using OpenCV DNN."""
    global _net
    with _net_lock:
        if _net is None:
            onnx_path = app_resource_path("assets", "model", "mnist_math_cnn.onnx")
            if not os.path.exists(onnx_path):
                current_dir = os.path.dirname(os.path.abspath(__file__))
                onnx_path = os.path.normpath(os.path.join(current_dir, "..", "web", "frontend", "public", "model", "mnist_math_cnn.onnx"))
                if not os.path.exists(onnx_path):
                    onnx_path = os.path.normpath(os.path.join(current_dir, "web", "frontend", "public", "model", "mnist_math_cnn.onnx"))
            
            if os.path.exists(onnx_path):
                try:
                    _net = cv2.dnn.readNetFromONNX(onnx_path)
                    print(f"[ocr_engine] OpenCV DNN loaded ONNX model from {onnx_path}")
                    SIGNALS.ready.emit()
                except Exception as e:
                    print(f"[ocr_engine] Failed to load ONNX model using OpenCV DNN: {e}")

def shutdown():
    """Clears the loaded network model from memory."""
    global _net
    with _net_lock:
        _net = None
    print("[ocr_engine] OpenCV DNN OCR model unloaded.")

def is_ready() -> bool:
    """Returns True if the ONNX model is loaded and ready."""
    with _net_lock:
        return _net is not None

def preprocess_digit_image(pil_img):
    """
    Extracts, merges, pads, and resizes individual digit contours from a PIL image
    into a batch of normalized 28x28x1 float32 numpy arrays with center-of-mass alignment,
    along with structural metadata (loop detection) for disambiguation.
    """
    img_gray = np.array(ImageOps.invert(pil_img.convert("L")))
    _, thresh = cv2.threshold(img_gray, 50, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < 25 or w < 3 or h < 6:
            continue
        # Drop flat horizontal strike-through noise lines
        if w / max(1, h) > 4.5 and h < 8:
            continue
        boxes.append([x, y, w, h])

    if not boxes:
        return None

    # Sort boxes left to right
    boxes.sort(key=lambda b: b[0])

    # Merge horizontally overlapping contours (e.g. top bar of 5 over belly, crossbar of 4)
    # NEVER merge side-by-side digits with a horizontal gap!
    merged = []
    for b in boxes:
        if not merged:
            merged.append(b)
            continue
        prev_x, prev_y, prev_w, prev_h = merged[-1]
        overlap_x = min(prev_x + prev_w, b[0] + b[2]) - max(prev_x, b[0])
        min_w = min(prev_w, b[2])
        if overlap_x > 0 and (overlap_x / float(min_w) > 0.35):
            nx = min(prev_x, b[0])
            ny = min(prev_y, b[1])
            nw = max(prev_x + prev_w, b[0] + b[2]) - nx
            nh = max(prev_y + prev_h, b[1] + b[3]) - ny
            merged[-1] = [nx, ny, nw, nh]
        else:
            merged.append(b)

    batch = []
    meta = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for b in merged:
        x, y, w, h = b
        digit = thresh[y : y + h, x : x + w]

        # 1. Morphological dilation: restores stroke body to match MNIST distribution
        dilated = cv2.dilate(digit, kernel, iterations=1)

        # 2. Topological loop / hole check in upper half
        upper = dilated[: int(h * 0.65), :]
        u_cnts, u_hier = cv2.findContours(upper, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        has_loop = False
        if u_hier is not None:
            for i, hi in enumerate(u_hier[0]):
                if hi[3] != -1 and cv2.contourArea(u_cnts[i]) >= 2:
                    has_loop = True
                    break

        # 3. Geometric mass distribution (upper half vs lower half)
        h_half = max(1, h // 2)
        upper_pixels = int(cv2.countNonZero(dilated[:h_half, :]))
        lower_pixels = int(cv2.countNonZero(dilated[h_half:, :]))
        total_pixels = max(1, upper_pixels + lower_pixels)
        upper_ratio = upper_pixels / float(total_pixels)
        meta.append({"has_loop": has_loop, "upper_ratio": upper_ratio, "w": w, "h": h})

        # 4. Aspect-ratio preserved resize to 20x20
        if h > w:
            nh = 20
            nw = max(1, int(round(w * 20.0 / h)))
        else:
            nw = 20
            nh = max(1, int(round(h * 20.0 / w)))
        resized = cv2.resize(dilated, (nw, nh), interpolation=cv2.INTER_AREA)

        # 5. Pad to 28x28
        pt = (28 - nh) // 2
        pb = 28 - nh - pt
        pl = (28 - nw) // 2
        pr = 28 - nw - pl
        padded = np.pad(resized, ((pt, pb), (pl, pr)), "constant")

        # 6. Center of mass alignment (Yann LeCun MNIST standard)
        M = cv2.moments(padded)
        if M["m00"] > 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            sx = int(round(13.5 - cx))
            sy = int(round(13.5 - cy))
            sx = max(-4, min(4, sx))
            sy = max(-4, min(4, sy))
            M_s = np.float32([[1, 0, sx], [0, 1, sy]])
            padded = cv2.warpAffine(padded, M_s, (28, 28))

        final = padded.astype("float32").reshape(28, 28, 1) / 255.0
        batch.append(final)

    if not batch:
        return None
    return np.array(batch, dtype=np.float32), meta

def ocr_number(pil_img, _retried=False) -> str:
    global _net, _warmup_done
    if not _warmup_done:
        warm_up()
        _warmup_done = True
    
    with _net_lock:
        if _net is None:
            print("[ocr_engine] Model not loaded.")
            return ""

    try:
        prep = preprocess_digit_image(pil_img)
        if prep is None:
            return ""
        batch_arr, meta = prep
        
        with _net_lock:
            _net.setInput(batch_arr)
            out = _net.forward()
        
        out = out.reshape(-1, 10)
        
        result = []
        for i in range(len(batch_arr)):
            probs = out[i]
            top1 = int(np.argmax(probs))
            top2 = int(np.argsort(probs)[::-1][1])
            has_loop = meta[i]["has_loop"]
            upper_ratio = meta[i].get("upper_ratio", 0.5)
            
            pred = top1
            # 1. Disambiguate 3 vs 9 using topological loop invariant
            if top1 == 3 and has_loop and (probs[9] > 0.05 or top2 == 9):
                pred = 9
            elif top1 == 9 and not has_loop and probs[3] > 0.35 and probs[9] < 0.65:
                pred = 3
            # 2. Disambiguate 1 vs 9 and 7 vs 9: A digit 1 or 7 NEVER has an upper closed loop!
            elif (top1 == 1 or top1 == 7) and has_loop and (probs[9] > 0.05 or top2 == 9):
                pred = 9
            elif top1 == 1 and upper_ratio > 0.52 and (probs[9] > 0.10 or top2 == 9):
                pred = 9
            # 3. Disambiguate 5 vs 9 using vertical mass distribution:
            # 9 has its loop/mass concentrated in the upper half (> 0.58).
            # 5 has its belly in the lower half (< 0.45).
            elif top1 == 5 and upper_ratio > 0.58 and (probs[9] > 0.05 or top2 == 9):
                pred = 9
            elif top1 == 9 and upper_ratio < 0.40 and (probs[5] > 0.10 or top2 == 5):
                pred = 5
                
            result.append(str(pred))
            
        res = "".join(result)
        print(f"[ocr_engine] OpenCV DNN predicted: '{res}'")
        return res
    except Exception as e:
        print(f"[ocr_engine] Prediction failed: {e}")
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


def run_native_ocr(image_path: str) -> str:
    if not image_path or not os.path.exists(image_path):
        return ""
    try:
        from storage_paths import app_resource_path
        ps_script = app_resource_path("services", "run_ocr.ps1")
        if not os.path.exists(ps_script):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            ps_script = os.path.join(current_dir, "run_ocr.ps1")
            
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", ps_script,
            "-ImagePath", image_path
        ]
        
        import subprocess
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0 # SW_HIDE
            
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            timeout=15
        )
        if res.returncode == 0:
            return res.stdout.strip()
        else:
            print(f"[OCR] PowerShell OCR failed: {res.stderr}")
            return ""
    except Exception as e:
        print(f"[OCR] Failed to execute native OCR: {e}")
        return ""


def clean_ocr_title(text: str) -> str:
    if not text:
        return ""
    import re
    cleaned = re.sub(r'\s+', ' ', text).strip()
    if not cleaned:
        return ""
    q_match = re.search(r'^.*?\?', cleaned)
    if q_match:
        cleaned = q_match.group(0)
    
    if len(cleaned) > 60:
        truncated = cleaned[:60]
        last_space = truncated.rfind(' ')
        if last_space > 30:
            cleaned = truncated[:last_space] + "..."
        else:
            cleaned = truncated + "..."
    return cleaned


class OcrTextThread(QThread):
    result = pyqtSignal(str, str)
    
    def __init__(self, image_path: str, default_title: str, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._default_title = default_title
        
    def run(self):
        try:
            raw_text = run_native_ocr(self._image_path)
            self.result.emit(raw_text, self._default_title)
        except Exception as e:
            print(f"[ocr_engine] OcrTextThread failed: {e}")
            self.result.emit("", self._default_title)


