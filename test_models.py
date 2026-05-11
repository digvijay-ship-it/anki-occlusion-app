import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from services.ocr_engine import GEMINI_API_KEY
import google.generativeai as genai

genai.configure(api_key=GEMINI_API_KEY)

try:
    models = genai.list_models()
    print("Available models:")
    for m in models:
        if "generateContent" in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
