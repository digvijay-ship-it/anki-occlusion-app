"""
Voice Input Service for Anki Occlusion.
Provides asynchronous, non-blocking microphone recording and speech-to-text
using SpeechRecognition (Google Speech API: hi-IN with en-IN fallback).
"""

from PyQt5.QtCore import QThread, pyqtSignal
import speech_recognition as sr


class VoiceInputWorker(QThread):
    """
    Background worker that listens to the microphone, records student speech,
    and converts it to text in real-time without freezing the GUI.
    """
    started_recording = pyqtSignal()
    listening_audio = pyqtSignal()
    transcribing_audio = pyqtSignal()
    text_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, language: str = "hi-IN", phrase_limit: int = 20, parent=None):
        super().__init__(parent)
        self.language = language or "hi-IN"
        self.phrase_limit = phrase_limit
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        self.started_recording.emit()
        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 1.0  # seconds of silence before finishing
        recognizer.dynamic_energy_threshold = True

        try:
            with sr.Microphone() as source:
                if self._is_cancelled:
                    return
                # Quick ambient noise adjustment (0.3 sec)
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                self.listening_audio.emit()
                
                # Listen with a timeout so it does not hang forever if user is silent
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=self.phrase_limit)

            if self._is_cancelled:
                return

            self.transcribing_audio.emit()
            
            # 1. Try with user's primary language (default: hi-IN)
            try:
                transcription = recognizer.recognize_google(audio, language=self.language)
            except sr.UnknownValueError:
                # 2. Fallback to English (en-IN) if Hindi couldn't decode
                if self.language != "en-IN":
                    try:
                        transcription = recognizer.recognize_google(audio, language="en-IN")
                    except Exception:
                        transcription = ""
                else:
                    transcription = ""

            if self._is_cancelled:
                return

            if transcription and transcription.strip():
                self.text_ready.emit(transcription.strip())
            else:
                self.error_occurred.emit("⚠️ आवाज़ साफ़ सुनाई नहीं दी। कृपया थोड़ा नज़दीक होकर दोबारा बोलें।")

        except sr.WaitTimeoutError:
            if not self._is_cancelled:
                self.error_occurred.emit("⏱️ कोई आवाज़ नहीं मिली (टाइमआउट)। माइक का बटन दबाकर बोलें।")
        except Exception as e:
            if not self._is_cancelled:
                self.error_occurred.emit(f"⚠️ माइक त्रुटि: {str(e)}")