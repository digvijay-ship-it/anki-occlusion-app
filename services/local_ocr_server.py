import os
import sys
import io
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import cv2
from PIL import Image, ImageOps
import tensorflow as tf

current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, "..", "assets", "model", "mnist_math_cnn.keras")
model_path = os.path.normpath(model_path)
model = tf.keras.models.load_model(model_path)

# Warmup: eliminates first-call TF graph overhead
model.predict(np.zeros((1, 28, 28, 1)), verbose=0)
print("Model warmed up.")


def predict(pil_img):
    img_gray = np.array(ImageOps.invert(pil_img.convert("L")))
    _, thresh = cv2.threshold(img_gray, 50, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[0])

    batch = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 5 and h < 5:
            continue  # Drop noise
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

    # ONE batch predict call — eliminates per-digit overhead
    preds = np.argmax(model.predict(np.array(batch), verbose=0), axis=1)
    return "".join(str(p) for p in preds)


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        if self.path == "/predict":
            try:
                content_length = int(self.headers["Content-Length"])
                post_data = self.rfile.read(content_length)
                img = Image.open(io.BytesIO(post_data))
                res = predict(img)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"result": res}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 50051), RequestHandler)
    print("Local OCR Server running on port 50051")
    server.serve_forever()
