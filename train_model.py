import os
import sys

# Optional: You can comment out the next line if you want to see ALL TensorFlow logs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# ⚡ CRITICAL: Import tensorflow before importing services.ocr_engine (which loads PyQt5).
# On Windows, loading PyQt5 DLLs before TensorFlow's native DLLs causes initialization (DllMain) failure.
import tensorflow as tf

print("=====================================================")
print("  MATH DOJO - ADVANCED MODEL TRAINING SCRIPT")
print("=====================================================")
print("Loading TensorFlow and preparing to train the model...")
print("This process trains an advanced, highly robust CNN for 10")
print("epochs with Batch Normalization, Dropout, and learning rate scheduling.")
print("Training will take approximately 60 to 80 minutes on CPU...")
print("=====================================================\n")

# Import the get_model function which contains our training logic
from services.ocr_engine import _get_model

# Trigger the training manually!
model = _get_model()

if model is not None:
    print("\n=====================================================")
    print("SUCCESS! The model has been trained and saved.")
    print("You can now launch the Math Practice app normally.")
    print("=====================================================")
else:
    print("\n[!] Training failed or TensorFlow is not available in this environment.")
