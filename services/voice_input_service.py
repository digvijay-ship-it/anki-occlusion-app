"""
Voice Input Service for Anki Occlusion.
Provides asynchronous, non-blocking microphone recording and speech-to-text
using SpeechRecognition (Google Speech API: hi-IN with en-IN fallback),
with generous pause thresholds and sensitive noise calibration so natural
speech pauses never get cut off prematurely.
"""

from PyQt5.QtCore import QThread, pyqtSignal
import speech_recognition as sr
import logging

logger = logging.getLogger(__name__)


class VoiceInputWorker(QThread):
    """
    Background worker that listens to the microphone, records student speech,
    and converts it to text in real-time without freezing the GUI.
    """
    started_recording = pyqtSignal()
    listening_audio = pyqtSignal()
    transcribing_audio = pyqtSignal()
    text_ready = pyqtSignal(str)
    timed_out = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        language: str = "hi-IN",
        phrase_limit: int = 60,
        pause_threshold: float = 2.0,
        timeout: int = 12,
        parent=None
    ):
        super().__init__(parent)
        self.language = language or "hi-IN"
        self.phrase_limit = phrase_limit or 60
        self.pause_threshold = pause_threshold or 2.0
        self.timeout = timeout or 12
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        self.started_recording.emit()
        recognizer = sr.Recognizer()

        # Generous pause threshold so natural thinking pauses don't cut off mid-sentence
        recognizer.pause_threshold = self.pause_threshold
        recognizer.non_speaking_duration = 0.8
        recognizer.phrase_threshold = 0.3
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_adjustment_damping = 0.15
        recognizer.dynamic_energy_ratio = 1.5

        try:
            with sr.Microphone() as source:
                if self._is_cancelled:
                    return

                # Quick ambient noise adjustment (0.3 sec)
                recognizer.adjust_for_ambient_noise(source, duration=0.3)

                # Clamp energy threshold into realistic vocal range so it stays sensitive
                if recognizer.energy_threshold > 1200:
                    recognizer.energy_threshold = 1200
                elif recognizer.energy_threshold < 150:
                    recognizer.energy_threshold = 150

                self.listening_audio.emit()
                
                # Listen with timeout
                audio = recognizer.listen(
                    source,
                    timeout=self.timeout,
                    phrase_time_limit=self.phrase_limit
                )

            if self._is_cancelled:
                return

            self.transcribing_audio.emit()
            
            # 1. Try with user's primary language (default: hi-IN)
            transcription = ""
            try:
                transcription = recognizer.recognize_google(audio, language=self.language)
            except sr.UnknownValueError:
                # 2. Fallback to Indian English (en-IN) if primary language didn't match
                if self.language != "en-IN":
                    try:
                        transcription = recognizer.recognize_google(audio, language="en-IN")
                    except Exception:
                        transcription = ""
            except Exception as e:
                logger.warning(f"[VoiceInput] Google STT error: {e}")
                transcription = ""

            if self._is_cancelled:
                return

            if transcription and transcription.strip():
                self.text_ready.emit(transcription.strip())
            else:
                self.error_occurred.emit("⚠️ आवाज़ साफ़ सुनाई नहीं दी। कृपया थोड़ा नज़दीक होकर दोबारा बोलें।")

        except sr.WaitTimeoutError:
            if not self._is_cancelled:
                self.timed_out.emit()
        except Exception as e:
            if not self._is_cancelled:
                self.error_occurred.emit(f"⚠️ माइक त्रुटि: {str(e)}")