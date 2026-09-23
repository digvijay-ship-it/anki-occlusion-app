"""
High-Fidelity Text-To-Speech (TTS) Service for AI Study Buddy.
Uses Microsoft Edge Neural TTS (edge-tts) for realistic, human-sounding
Hindi (hi-IN-MadhurNeural / hi-IN-SwaraNeural) and Indian English voices,
with asynchronous QMediaPlayer playback and safe resource cleanup.
"""

import os
import re
import html
import asyncio
import tempfile
import logging
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "hi-IN-MadhurNeural"
AVAILABLE_VOICES = [
    ("Madhur (हिंदी - ऊर्जावान सहपाठी / Male)", "hi-IN-MadhurNeural"),
    ("Swara (हिंदी - स्पष्ट व सहज / Female)", "hi-IN-SwaraNeural"),
    ("Prabhat (English - Indian Accent / Male)", "en-IN-PrabhatNeural"),
    ("Neerja (English - Indian Accent / Female)", "en-IN-NeerjaNeural"),
]


def clean_text_for_speech(text: str) -> str:
    """
    Cleans raw markdown, emojis, HTML, and formatting from AI replies
    to produce fluid, natural-sounding spoken sentences.
    """
    if not text:
        return ""

    # Decode any HTML entities
    t = html.unescape(text)

    # Remove HTML tags
    t = re.sub(r'<[^>]+>', ' ', t)

    # Remove markdown bold/italics
    t = re.sub(r'\*+([^*]+)\*+', r'\1', t)
    t = re.sub(r'_+([^_]+)_+', r'\1', t)

    # Remove code blocks
    t = re.sub(r'```[^`]*```', ' ', t)
    t = re.sub(r'`([^`]+)`', r'\1', t)

    # Remove Markdown links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)

    # Remove high-surrogate emojis and symbols that might trip TTS
    t = re.sub(r'[\U00010000-\U0010ffff]', ' ', t)

    # Remove list bullets and symbol markers at start of lines
    t = re.sub(r'^[•\-\*🔹🟢⚠️💡🚀📌✅❌🅰️🅱️🆎🅾️]+\s*', '', t, flags=re.MULTILINE)

    # Replace newlines with punctuation pause
    t = re.sub(r'\n+', '. ', t)

    # Clean multiple dots and spaces
    t = re.sub(r'\.{2,}', '.', t)
    t = re.sub(r'\s+', ' ', t)

    return t.strip()


class TTSWorker(QThread):
    """
    Background worker that communicates with edge-tts asynchronously
    and writes out an MP3 file without blocking the GUI thread.
    """
    audio_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%", parent=None):
        super().__init__(parent)
        self.text = text
        self.voice = voice or DEFAULT_VOICE
        self.rate = rate or "+0%"
        self._cancelled = False
        self._temp_path = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        if not self.text.strip():
            return

        cleaned_text = clean_text_for_speech(self.text)
        if not cleaned_text:
            return

        try:
            import edge_tts

            # Create dedicated temporary mp3 file
            fd, tmp_file = tempfile.mkstemp(suffix="_buddy_tts.mp3")
            os.close(fd)
            self._temp_path = tmp_file

            async def _synthesize():
                comm = edge_tts.Communicate(cleaned_text, voice=self.voice, rate=self.rate)
                await comm.save(tmp_file)

            asyncio.run(_synthesize())

            if self._cancelled:
                self._safe_cleanup(tmp_file)
                return

            if os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 0:
                self.audio_ready.emit(tmp_file)
            else:
                self.error_occurred.emit("TTS audio output file is empty.")

        except Exception as e:
            logger.warning(f"[TTSWorker] edge-tts error: {e}")
            if self._temp_path:
                self._safe_cleanup(self._temp_path)
            if not self._cancelled:
                self.error_occurred.emit(str(e))

    def _safe_cleanup(self, path: str):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


class TTSEngine(QObject):
    """
    Main TTS manager that coordinates TTSWorker synthesis,
    QMediaPlayer audio output, and event lifecycle.
    """
    speech_started = pyqtSignal(str)     # Emits file path
    speech_finished = pyqtSignal()
    speech_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._current_file = None
        self._is_playing = False
        self._is_synthesizing = False

        self._player = QMediaPlayer(self)
        self._player.stateChanged.connect(self._on_player_state_changed)
        self._player.error.connect(self._on_player_error)

    def is_speaking(self) -> bool:
        """Returns True if synthesizing or actively playing audio."""
        return self._is_synthesizing or self._is_playing

    def speak(self, text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%"):
        """Stop any active speech and speak the new text."""
        self.stop()

        if not text or not text.strip():
            return

        self._is_synthesizing = True
        self._worker = TTSWorker(text, voice=voice, rate=rate, parent=self)
        self._worker.audio_ready.connect(self._on_audio_ready)
        self._worker.error_occurred.connect(self._on_synthesis_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def stop(self):
        """Immediately stops synthesis and playback."""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(500)
            self._worker = None
        self._is_synthesizing = False

        if self._player.state() != QMediaPlayer.StoppedState:
            self._player.stop()

        # Unload media so Windows file lock is released
        self._player.setMedia(QMediaContent())
        self._cleanup_temp_file()

        if self._is_playing:
            self._is_playing = False
            self.speech_stopped.emit()

    def _on_audio_ready(self, file_path: str):
        self._is_synthesizing = False
        self._cleanup_temp_file()
        self._current_file = file_path

        if not os.path.exists(file_path):
            self.error_occurred.emit("Audio file not found on disk.")
            return

        self._is_playing = True
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
        self._player.play()
        self.speech_started.emit(file_path)

    def _on_synthesis_error(self, err_msg: str):
        self._is_synthesizing = False
        logger.warning(f"[TTSEngine] Synthesis error: {err_msg}")
        self.error_occurred.emit(err_msg)

    def _on_worker_finished(self):
        self._worker = None

    def _on_player_state_changed(self, state):
        if state == QMediaPlayer.StoppedState:
            if self._is_playing:
                self._is_playing = False
                self._player.setMedia(QMediaContent())  # Release lock
                self._cleanup_temp_file()
                self.speech_finished.emit()

    def _on_player_error(self):
        err = self._player.errorString()
        logger.warning(f"[TTSEngine] QMediaPlayer error: {err}")
        self.stop()
        self.error_occurred.emit(f"Playback error: {err}")

    def _cleanup_temp_file(self):
        if self._current_file:
            try:
                if os.path.exists(self._current_file):
                    os.remove(self._current_file)
            except Exception:
                pass
            self._current_file = None
