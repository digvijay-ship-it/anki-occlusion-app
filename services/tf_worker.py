import os
import sys
import base64
import io
import numpy as np
import cv2
from PIL import Image, ImageOps

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf


def predict(model, pil_img):
    img_gray = np.array(ImageOps.invert(pil_img.convert("L")))
    _, thresh = cv2.threshold(img_gray, 50, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[0])

    batch = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 5 and h < 5:
            continue
        digit = thresh[y : y + h, x : x + w]
        side = max(w, h)
        pad_x, pad_y = (side - w) // 2, (side - h) // 2
        square = np.pad(
            digit, ((pad_y, side - h - pad_y), (pad_x, side - w - pad_x)), "constant"
        )
        resized = cv2.resize(square, (20, 20), interpolation=cv2.INTER_AREA)
        final = np.pad(resized, ((4, 4), (4, 4)), "constant").astype("float32") / 255.0
        batch.append(final.reshape(28, 28, 1))

    if not batch:
        return ""

    preds = np.argmax(model.predict(np.array(batch), verbose=0), axis=1)
    return "".join(str(p) for p in preds)


def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.normpath(
        os.path.join(current_dir, "..", "assets", "model", "mnist_math_cnn.keras")
    )

    try:
        if not os.path.exists(model_path):
            print(f"ERROR: Model not found at {model_path}", flush=True)
            return
        model = tf.keras.models.load_model(model_path)
        # Warmup: kill first-inference TF graph overhead
        model.predict(np.zeros((1, 28, 28, 1)), verbose=0)
        print("READY", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "EXIT":
            break
        try:
            img_data = base64.b64decode(line)
            pil_img = Image.open(io.BytesIO(img_data))
            result = predict(model, pil_img)
            print(f"RESULT:{result}", flush=True)
        except Exception as e:
            print(f"ERROR:{e}", flush=True)


if __name__ == "__main__":
    main()
