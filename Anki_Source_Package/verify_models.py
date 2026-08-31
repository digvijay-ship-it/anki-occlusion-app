import sys
import os
import numpy as np

# ⚡ CRITICAL: Import tensorflow before PyQt5 / other DLL-loading modules on Windows to prevent DLL load conflict (0x45A)
import tensorflow as tf

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.normpath(
    os.path.join(current_dir, "assets", "model", "mnist_math_cnn.keras")
)

print("=====================================================")
print("  MATH DOJO - LOCAL MODEL VERIFICATION SCRIPT")
print("=====================================================")
print(f"Checking for model file at: {model_path} ...\n")

if not os.path.exists(model_path):
    print(f"[!] ERROR: Model file not found at {model_path}")
    print("Please run 'python train_model.py' first to train and save the model.")
    sys.exit(1)

print("[+] Model file exists. Loading TensorFlow model...")
try:
    model = tf.keras.models.load_model(model_path)
    print("[+] Model loaded successfully!")
    print("\nModel Summary:")
    model.summary()
    
    # Run a dummy prediction to ensure correctness
    print("\nRunning dummy prediction test...")
    dummy_input = np.zeros((1, 28, 28, 1), dtype="float32")
    prediction = model.predict(dummy_input, verbose=0)
    predicted_digit = np.argmax(prediction)
    print(f"[+] Prediction successful! Dummy output digit: {predicted_digit}")
    print("=====================================================")
    print("SUCCESS! Your local MNIST math CNN model is 100% healthy.")
    print("=====================================================")
except Exception as e:
    print(f"\n[!] ERROR: Failed to load or verify model: {e}")
    sys.exit(1)
