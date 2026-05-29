import os
import sys

# Optional: suppress TF warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import tensorflow as tf
import tf2onnx

current_dir = os.path.dirname(os.path.abspath(__file__))
keras_model_path = os.path.join(current_dir, "assets", "model", "mnist_math_cnn.keras")
onnx_model_dir = os.path.join(current_dir, "web", "frontend", "public", "model")
onnx_model_path = os.path.join(onnx_model_dir, "mnist_math_cnn.onnx")

print("=====================================================")
print("  MATH DOJO - MODEL CONVERSION TO ONNX (WEB)")
print("=====================================================")

if not os.path.exists(keras_model_path):
    print(f"[!] Error: Keras model file not found at {keras_model_path}")
    sys.exit(1)

print(f"[+] Loading Keras model from {keras_model_path} ...")
try:
    model = tf.keras.models.load_model(keras_model_path)
    print("[+] Model loaded successfully.")
except Exception as e:
    print(f"[!] Failed to load model: {e}")
    sys.exit(1)

print(f"[+] Preparing output directory: {onnx_model_dir}")
os.makedirs(onnx_model_dir, exist_ok=True)

print("[+] Converting Keras model to ONNX format...")
try:
    # Set input signature for standard float32 shape matching Keras inputs [None, 28, 28, 1]
    input_spec = (tf.TensorSpec((None, 28, 28, 1), tf.float32, name="input"),)
    
    model_proto, _ = tf2onnx.convert.from_keras(
        model, 
        input_signature=input_spec, 
        opset=13, 
        output_path=onnx_model_path
    )
    print(f"\n[+] SUCCESS! Model converted and saved to static public asset:")
    print(f"    --> {onnx_model_path}")
    print("=====================================================")
except Exception as e:
    print(f"\n[!] Conversion failed: {e}")
    sys.exit(1)
