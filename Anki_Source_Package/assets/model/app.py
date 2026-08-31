import os
import tkinter as tk
from tkinter import font as tkfont
import numpy as np
import random
import cv2
from PIL import Image, ImageDraw, ImageOps
import tensorflow as tf

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
MODEL_FILE = "mnist_math_cnn.keras"

# ── Train Model Once ────────────────────────────────────────────────────────
if not os.path.exists(MODEL_FILE):
    print("Training CNN once. Wait 1 min...")
    (x_train, y_train), _ = tf.keras.datasets.mnist.load_data()
    x_train = x_train.reshape(-1, 28, 28, 1).astype('float32') / 255.0
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(28,28,1)),
        tf.keras.layers.Conv2D(32, (3,3), activation='relu'),
        tf.keras.layers.MaxPooling2D(2,2),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(128, activation='relu'),
        tf.keras.layers.Dense(10, activation='softmax')
    ])
    model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
    model.fit(x_train, y_train, epochs=3, batch_size=128)
    model.save(MODEL_FILE)
    print("Done. Saved.")
else:
    model = tf.keras.models.load_model(MODEL_FILE)

# ── Config ────────────────────────────────────────────────────────────────────
STROKE_COLOR = "#1a1a2e"
CANVAS_BG    = "#ffffff"
APP_BG       = "#0f0f23"
CARD_BG      = "#1a1a2e"
ACCENT       = "#7c6af7"
TEXT_LIGHT   = "#e8e6ff"
TEXT_MUTED   = "#8b8aad"
SUCCESS      = "#4ade80"
FAIL         = "#f87171"

OPERATIONS = {
    "+": lambda a, b: (f"{a} + {b}", a + b),
    "-": lambda a, b: (f"{a} - {b}", a - b),
    "×": lambda a, b: (f"{a} × {b}", a * b),
}

def ocr_number(pil_img):
    img_gray = np.array(ImageOps.invert(pil_img.convert('L')))
    _, thresh = cv2.threshold(img_gray, 50, 255, cv2.THRESH_BINARY)
    
    # Split digits
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[0]) # Read Left to Right
    
    result = ""
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 5 and h < 5: continue # Drop noise
        
        digit = thresh[y:y+h, x:x+w]
        side = max(w, h)
        pad_x, pad_y = (side - w) // 2, (side - h) // 2
        square = np.pad(digit, ((pad_y, side-h-pad_y), (pad_x, side-w-pad_x)), 'constant')
        
        # MNIST format: 20x20 center, 28x28 total
        resized = cv2.resize(square, (20, 20), interpolation=cv2.INTER_AREA)
        final = np.pad(resized, ((4,4), (4,4)), 'constant').astype('float32') / 255.0
        
        pred = np.argmax(model.predict(final.reshape(1, 28, 28, 1), verbose=0))
        result += str(pred)
        
    return result

# ── App ───────────────────────────────────────────────────────────────────────
class MathPracticeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Math Practice (AI Local)")
        self.root.configure(bg=APP_BG)
        self.root.geometry("560x800")
        self.root.resizable(False, False)

        self.score = 0
        self.total = 0
        self.streak = 0
        self.drawing = False
        self.last_x = self.last_y = 0
        self.stroke_width = 16
        self.num_range = (1, 10)

        self._build_ui()
        self._new_question()

    def _build_ui(self):
        f_title = tkfont.Font(family="Helvetica", size=13, weight="bold")
        f_score = tkfont.Font(family="Helvetica", size=11)
        f_q = tkfont.Font(family="Helvetica", size=46, weight="bold")
        f_label = tkfont.Font(family="Helvetica", size=11)
        f_result = tkfont.Font(family="Helvetica", size=15, weight="bold")
        f_big = tkfont.Font(family="Helvetica", size=22, weight="bold")

        hdr = tk.Frame(self.root, bg=APP_BG)
        hdr.pack(fill="x", padx=24, pady=(20, 0))
        tk.Label(hdr, text="✦ Math Practice • Local CNN", bg=APP_BG, fg=TEXT_LIGHT, font=f_title).pack(side="left")
        self.score_lbl = tk.Label(hdr, text="0 / 0  🔥0", bg=APP_BG, fg=TEXT_MUTED, font=f_score)
        self.score_lbl.pack(side="right")

        card = tk.Frame(self.root, bg=CARD_BG)
        card.pack(fill="x", padx=24, pady=16)
        self.diff_lbl = tk.Label(card, text="", bg=CARD_BG, fg=ACCENT, font=f_label)
        self.diff_lbl.pack(pady=(14, 0))
        self.q_lbl = tk.Label(card, text="", bg=CARD_BG, fg=TEXT_LIGHT, font=f_q)
        self.q_lbl.pack(pady=(4, 14))

        diff_row = tk.Frame(self.root, bg=APP_BG)
        diff_row.pack(pady=(0, 10))
        for label, rng in [("Easy", (1, 10)), ("Medium", (10, 50)), ("Hard", (50, 200))]:
            tk.Button(diff_row, text=label, bg=CARD_BG, fg=TEXT_MUTED, activebackground=ACCENT, 
                      activeforeground="#fff", relief="flat", bd=0, padx=14, pady=5, font=f_label, 
                      cursor="hand2", command=lambda r=rng: self._set_range(r)).pack(side="left", padx=5)

        row = tk.Frame(self.root, bg=APP_BG)
        row.pack(fill="x", padx=24, pady=(0, 6))
        tk.Label(row, text="✏ Write your answer", bg=APP_BG, fg=TEXT_MUTED, font=f_label).pack(side="left")
        
        self.stroke_var = tk.IntVar(value=16)
        tk.Scale(row, from_=6, to=30, orient="horizontal", variable=self.stroke_var, bg=APP_BG, fg=TEXT_MUTED,
                 troughcolor=CARD_BG, highlightthickness=0, bd=0, length=80, showvalue=False,
                 command=lambda v: setattr(self, "stroke_width", int(v))).pack(side="right")

        self.canvas = tk.Canvas(self.root, width=512, height=220, bg=CANVAS_BG, cursor="crosshair",
                                highlightthickness=1, highlightbackground=ACCENT)
        self.canvas.pack(padx=24)
        self._reset_pil()
        self.canvas.bind("<ButtonPress-1>", self._start)
        self.canvas.bind("<B1-Motion>", self._draw)
        self.canvas.bind("<ButtonRelease-1>", self._stop)

        btn_row = tk.Frame(self.root, bg=APP_BG)
        btn_row.pack(pady=10)
        self._btn(btn_row, "✓  Check", ACCENT, self._check).pack(side="left", padx=6)
        self._btn(btn_row, "Clear", CARD_BG, self._clear).pack(side="left", padx=6)
        self._btn(btn_row, "Skip →", CARD_BG, self._new_question).pack(side="left", padx=6)

        self.result_lbl = tk.Label(self.root, text="", bg=APP_BG, font=f_result)
        self.result_lbl.pack(pady=4)

        rec_frame = tk.Frame(self.root, bg=CARD_BG)
        rec_frame.pack(fill="x", padx=24, pady=(4, 0))
        tk.Label(rec_frame, text="Recognised:", bg=CARD_BG, fg=TEXT_MUTED, font=f_label).pack(side="left", padx=10, pady=8)
        self.rec_lbl = tk.Label(rec_frame, text="—", bg=CARD_BG, fg=TEXT_LIGHT, font=f_big)
        self.rec_lbl.pack(side="left", pady=8)

    def _btn(self, parent, text, bg, cmd):
        return tk.Button(parent, text=text, bg=bg, fg=TEXT_LIGHT, activebackground=ACCENT,
                         activeforeground="#fff", relief="flat", bd=0, padx=18, pady=9,
                         font=tkfont.Font(family="Helvetica", size=11, weight="bold"),
                         cursor="hand2", command=cmd)

    def _reset_pil(self):
        self.pil_img = Image.new("RGB", (512, 220), "white")
        self.pil_draw = ImageDraw.Draw(self.pil_img)

    def _start(self, e):
        self.drawing = True
        self.last_x, self.last_y = e.x, e.y

    def _draw(self, e):
        if not self.drawing: return
        w = self.stroke_width
        self.canvas.create_line(self.last_x, self.last_y, e.x, e.y, fill=STROKE_COLOR, width=w, capstyle="round", smooth=True)
        self.pil_draw.line([self.last_x, self.last_y, e.x, e.y], fill=STROKE_COLOR, width=w)
        self.last_x, self.last_y = e.x, e.y

    def _stop(self, e): self.drawing = False

    def _clear(self):
        self.canvas.delete("all")
        self._reset_pil()
        self.rec_lbl.config(text="—")
        self.result_lbl.config(text="")

    def _set_range(self, r):
        self.num_range = r
        self._new_question()

    def _new_question(self):
        self._clear()
        op = random.choice(list(OPERATIONS.keys()))
        lo, hi = self.num_range
        a, b = random.randint(lo, hi), random.randint(lo, hi)
        if op == "-" and b > a: a, b = b, a # Force positive answer
        self.question, self.answer = OPERATIONS[op](a, b)
        self.q_lbl.config(text=self.question)
        self.diff_lbl.config(text=f"Range  {lo}–{hi}  •  {op}")

    def _check(self):
        self.result_lbl.config(text="Predicting...", fg=TEXT_MUTED)
        self.root.update()

        try:
            recognised = ocr_number(self.pil_img)
            self.rec_lbl.config(text=recognised if recognised else "?")

            guessed = int(recognised) if recognised else None
            self.total += 1
            if guessed == self.answer:
                self.score += 1
                self.streak += 1
                self.result_lbl.config(text=f"✓  Correct!  Answer = {self.answer}", fg=SUCCESS)
            else:
                self.streak = 0
                self.result_lbl.config(text=f"✗  Wrong.  Answer = {self.answer}  (read: {recognised or '?'})", fg=FAIL)

            self._update_score()
            self.root.after(1800, self._new_question)

        except Exception as ex:
            self.result_lbl.config(text=f"Error: {ex}", fg=FAIL)

    def _update_score(self):
        pct = int(self.score / self.total * 100) if self.total else 0
        self.score_lbl.config(text=f"{self.score}/{self.total} ({pct}%)  🔥{self.streak}")

if __name__ == "__main__":
    root = tk.Tk()
    app = MathPracticeApp(root)
    root.mainloop()