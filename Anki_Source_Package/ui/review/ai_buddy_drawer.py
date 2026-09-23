"""
Socratic AI Study Buddy Drawer for ReviewScreen.
Provides live peer discussion, voice-to-text recall evaluation,
high-fidelity text-to-speech (TTS) spoken discussion, SSC exam trap analysis,
and memory anchoring via Google Gemini with dynamic font scaling.
"""

from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextBrowser, QScrollArea, QDialog, QComboBox, QCheckBox,
    QPlainTextEdit, QApplication, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, pyqtSignal, QSettings, QTimer, QUrl, QEvent
from PyQt5.QtGui import QColor, QFont, QCursor, QDesktopServices
from theme_manager import get_palette
import html
import re

from services.ai_coach_service import (
    get_ai_settings, save_ai_settings, build_card_context, AICoachWorker,
    cycle_next_key, parse_api_keys, DEFAULT_MODEL, FALLBACK_MODEL,
    DEFAULT_TTS_VOICE
)
from services.voice_input_service import VoiceInputWorker
from services.tts_service import TTSEngine, AVAILABLE_VOICES


class AISettingsDialog(QDialog):
    """Configuration modal for Gemini API Key, model version, and voice options."""
    settings_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Study Buddy — सेटिंग्स")
        self.setFixedSize(620, 780)
        self.setStyleSheet("""
            QDialog {
                background-color: #181825;
                color: #CDD6F4;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel {
                color: #CDD6F4;
            }
            QLineEdit, QComboBox, QPlainTextEdit {
                background: #1E1E2E;
                color: #CDD6F4;
                border: 1.5px solid #45475A;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 14px;
            }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                border: 1.5px solid #CBA6F7;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox QAbstractItemView {
                background: #1E1E2E;
                color: #CDD6F4;
                selection-background-color: #CBA6F7;
                selection-color: #11111B;
                padding: 6px;
                font-size: 14px;
            }
            QCheckBox {
                color: #CDD6F4;
                spacing: 12px;
                padding: 5px 0;
            }
            QCheckBox::indicator {
                width: 22px;
                height: 22px;
                border-radius: 5px;
                border: 1.5px solid #45475A;
                background: #1E1E2E;
            }
            QCheckBox::indicator:checked {
                background: #CBA6F7;
                border-color: #CBA6F7;
            }
            QPushButton#btn_save {
                background: #CBA6F7;
                color: #11111B;
                border: none;
                border-radius: 8px;
                padding: 12px 36px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton#btn_save:hover {
                background: #B4BEFE;
            }
            QPushButton#btn_cancel {
                background: #313244;
                color: #CDD6F4;
                border: 1.5px solid #45475A;
                border-radius: 8px;
                padding: 12px 28px;
                font-weight: 600;
                font-size: 15px;
            }
            QPushButton#btn_cancel:hover {
                background: #45475A;
            }
        """)
        self._init_ui()

    def _init_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(30, 24, 30, 24)
        L.setSpacing(12)

        # 1. Title (H1 - Level 1)
        title = QLabel("⚙️ AI Study Buddy सेटिंग्स")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setStyleSheet("color: #CBA6F7; margin-bottom: 2px;")
        L.addWidget(title)

        # Description (Level 5 - Supporting)
        desc = QLabel(
            "Google Gemini की मुफ़्त API Key दर्ज करें।\n"
            "💡 आप 2-3 अलग-अलग Google खातों की Keys डाल सकते हैं। एक Key की सीमा पूरी होने पर ऐप बिना रुके अपने आप अगली Key पर स्विच हो जाएगा!"
        )
        desc.setFont(QFont("Segoe UI", 13, QFont.Normal))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #BAC2DE; line-height: 1.5;")
        L.addWidget(desc)

        cfg = get_ai_settings()

        # 2. Multi-Key input (Level 2 Label + Level 3 Input)
        lbl_keys = QLabel("🔑 Google Gemini API Keys (मल्टीपल अकाउंट्स सपोर्ट):")
        lbl_keys.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_keys.setStyleSheet("color: #CDD6F4; margin-top: 4px;")
        L.addWidget(lbl_keys)

        self.edit_keys = QPlainTextEdit()
        self.edit_keys.setFont(QFont("Consolas", 13))
        self.edit_keys.setPlainText(cfg.get("api_key_raw", ""))
        self.edit_keys.setPlaceholderText(
            "AIzaSy... (Account 1)\n"
            "AIzaSy... (Account 2)\n"
            "AIzaSy... (Account 3)\n\n"
            "(अलग-अलग Google खातों की Keys नई लाइन या अल्पविराम से दर्ज करें)"
        )
        self.edit_keys.setFixedHeight(80)
        L.addWidget(self.edit_keys)

        self.lbl_key_count = QLabel("")
        self.lbl_key_count.setFont(QFont("Segoe UI", 13, QFont.DemiBold))
        L.addWidget(self.lbl_key_count)
        self.edit_keys.textChanged.connect(self._update_key_count_label)
        self._update_key_count_label()

        # Key link info
        link_lbl = QLabel("<a href='https://aistudio.google.com/app/apikey' style='color: #89B4FA; font-weight: bold;'>👉 मुफ़्त API Key प्राप्त करें (Google AI Studio)</a>")
        link_lbl.setFont(QFont("Segoe UI", 13, QFont.DemiBold))
        link_lbl.setOpenExternalLinks(True)
        L.addWidget(link_lbl)

        # 3. Model Selector (Level 2 Label + Level 3 Input)
        lbl_model = QLabel("🧠 AI मॉडल इंजन:")
        lbl_model.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_model.setStyleSheet("color: #CDD6F4; margin-top: 4px;")
        L.addWidget(lbl_model)

        self.combo_model = QComboBox()
        self.combo_model.setFont(QFont("Segoe UI", 14))
        self.combo_model.setFixedHeight(44)
        self.combo_model.addItem("Gemini 3.8 Flash (ब्लीडिंग-एज • सबसे लेटेस्ट)", "gemini-3.8-flash")
        self.combo_model.addItem("Gemini 3.7 Flash (उन्नत रीजनिंग व मल्टीमॉडल)", "gemini-3.7-flash")
        self.combo_model.addItem("Gemini 3.5 Flash (एजेंटिक वर्कफ़्लो • सुपरफ़ास्ट)", "gemini-3.5-flash")
        self.combo_model.addItem("Gemini 3.0 Flash (स्टेबल फ्लैश 3.0)", "gemini-3.0-flash")
        self.combo_model.addItem("Gemini 2.5 Flash (क्लासिक 2.5)", "gemini-2.5-flash")
        self.combo_model.addItem("Gemini 2.0 Flash (क्लासिक स्टेबल 2.0)", "gemini-2.0-flash")
        self.combo_model.addItem("Gemini 1.5 Flash (विरासत स्टेबल 1.5)", "gemini-1.5-flash")
        self.combo_model.addItem("Gemini 1.5 Pro (उच्च क्षमता • डीप रीजनिंग)", "gemini-1.5-pro")
        current_m = cfg.get("model_name", "gemini-3.8-flash")
        idx = self.combo_model.findData(current_m)
        if idx >= 0:
            self.combo_model.setCurrentIndex(idx)
        else:
            self.combo_model.addItem(f"{current_m} (कस्टम)", current_m)
            self.combo_model.setCurrentIndex(self.combo_model.count() - 1)
        L.addWidget(self.combo_model)

        # 4. TTS & Voice Row (Level 2 Label + Level 3 Input)
        lbl_tts = QLabel("🔊 AI स्पीच (बोलकर सुनाने की आवाज़):")
        lbl_tts.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_tts.setStyleSheet("color: #CDD6F4; margin-top: 4px;")
        L.addWidget(lbl_tts)

        tts_row = QHBoxLayout()
        tts_row.setSpacing(10)

        self.combo_tts_voice = QComboBox()
        self.combo_tts_voice.setFont(QFont("Segoe UI", 14))
        self.combo_tts_voice.setFixedHeight(44)
        for v_label, v_val in AVAILABLE_VOICES:
            self.combo_tts_voice.addItem(v_label, v_val)
        v_idx = self.combo_tts_voice.findData(cfg.get("tts_voice", DEFAULT_TTS_VOICE))
        if v_idx >= 0:
            self.combo_tts_voice.setCurrentIndex(v_idx)
        tts_row.addWidget(self.combo_tts_voice, stretch=2)

        self.combo_tts_speed = QComboBox()
        self.combo_tts_speed.setFont(QFont("Segoe UI", 14))
        self.combo_tts_speed.setFixedHeight(44)
        self.combo_tts_speed.addItem("सामान्य (1.0x)", "+0%")
        self.combo_tts_speed.addItem("थोड़ा तेज़ (1.15x)", "+15%")
        self.combo_tts_speed.addItem("काफ़ी तेज़ (1.3x)", "+30%")
        sp_idx = self.combo_tts_speed.findData(cfg.get("tts_speed", "+0%"))
        if sp_idx >= 0:
            self.combo_tts_speed.setCurrentIndex(sp_idx)
        tts_row.addWidget(self.combo_tts_speed, stretch=1)
        L.addLayout(tts_row)

        # 5. Mic Language
        lbl_mic = QLabel("🎙️ माइक वॉइस भाषा (सुनने हेतु):")
        lbl_mic.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_mic.setStyleSheet("color: #CDD6F4; margin-top: 4px;")
        L.addWidget(lbl_mic)

        self.combo_lang = QComboBox()
        self.combo_lang.setFont(QFont("Segoe UI", 14))
        self.combo_lang.setFixedHeight(44)
        self.combo_lang.addItem("हिंदी व हिंग्लिश (hi-IN • डिफ़ॉल्ट)", "hi-IN")
        self.combo_lang.addItem("English (en-IN)", "en-IN")
        l_idx = self.combo_lang.findData(cfg["voice_lang"])
        if l_idx >= 0:
            self.combo_lang.setCurrentIndex(l_idx)
        L.addWidget(self.combo_lang)

        # 6. Checkboxes (Level 4)
        self.chk_auto_speak = QCheckBox("🔊 AI उत्तर बोलकर सुनाए (Auto Speak / Voice Discussion)")
        self.chk_auto_speak.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.chk_auto_speak.setChecked(cfg.get("auto_speak", True))
        self.chk_auto_speak.setStyleSheet("color: #A6E3A1; margin-top: 4px;")
        L.addWidget(self.chk_auto_speak)

        self.chk_continuous = QCheckBox("🔄 सतत बातचीत मोड (Continuous Live Mode • उत्तर के बाद अपने आप फिर से सुनें)")
        self.chk_continuous.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.chk_continuous.setChecked(cfg.get("continuous_mode", True))
        self.chk_continuous.setStyleSheet("color: #89B4FA; margin-top: 2px;")
        L.addWidget(self.chk_continuous)

        self.chk_auto = QCheckBox("कार्ड बदलते ही अपने आप सुनना शुरू करें (Auto Push-to-Talk)")
        self.chk_auto.setFont(QFont("Segoe UI", 14, QFont.DemiBold))
        self.chk_auto.setChecked(cfg["auto_listen"])
        self.chk_auto.setStyleSheet("color: #CDD6F4; margin-top: 2px;")
        L.addWidget(self.chk_auto)

        L.addStretch()

        # 7. Action Buttons (Importance-Based Button Hierarchy)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        btn_cancel = QPushButton("रद्द करें")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.setFont(QFont("Segoe UI", 15, QFont.DemiBold))
        btn_cancel.setFixedHeight(46)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("सहेजें (Save)")
        btn_save.setObjectName("btn_save")
        btn_save.setFont(QFont("Segoe UI", 16, QFont.Bold))
        btn_save.setFixedHeight(46)
        btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        L.addLayout(btn_row)

    def _update_key_count_label(self):
        txt = self.edit_keys.toPlainText().strip()
        keys = parse_api_keys(txt)
        count = len(keys)
        if count == 0:
            self.lbl_key_count.setText("⚠️ कोई API Key नहीं डाली गई है।")
            self.lbl_key_count.setStyleSheet("font-size: 13px; color: #F38BA8; font-weight: bold;")
        elif count == 1:
            self.lbl_key_count.setText("✅ 1 API Key सक्रिय (दैनिक कोटा: ~1,500 फ्री रिक्वेस्ट्स)")
            self.lbl_key_count.setStyleSheet("font-size: 13px; color: #A6E3A1; font-weight: bold;")
        else:
            self.lbl_key_count.setText(
                f"🚀 {count} API Keys पहचानी गईं! (दैनिक कोटा: ~{count * 1500:,} रिक्वेस्ट्स • ऑटो-फ़ेलओवर सक्रिय)"
            )
            self.lbl_key_count.setStyleSheet("font-size: 13.5px; color: #CBA6F7; font-weight: bold;")

    def _save(self):
        raw_keys = self.edit_keys.toPlainText().strip()
        model = self.combo_model.currentData()
        lang = self.combo_lang.currentData()
        auto_l = self.chk_auto.isChecked()
        auto_sp = self.chk_auto_speak.isChecked()
        cont_mode = self.chk_continuous.isChecked()
        tts_v = self.combo_tts_voice.currentData()
        tts_sp = self.combo_tts_speed.currentData()
        save_ai_settings(
            api_key=raw_keys,
            model_name=model,
            auto_listen=auto_l,
            voice_lang=lang,
            auto_speak=auto_sp,
            continuous_mode=cont_mode,
            tts_voice=tts_v,
            tts_speed=tts_sp
        )
        self.settings_saved.emit()
        self.accept()


class AIBuddyDrawer(QFrame):
    """
    Slide-out Socratic AI Study Buddy Drawer on ReviewScreen.
    Displays:
    1. Status header with active card summary, TTS toggle, font zoom & settings.
    2. Quick Prompt Chips (Recall, Trap, Mnemonic, 360° Link).
    3. Rich conversational history with dynamic font scaling and audio replay.
    4. Voice (Push-to-Talk) & text input bar.
    """
    SETTINGS_WIDTH_KEY = "review/ai_buddy_width"
    SETTINGS_FONT_SIZE_KEY = "review/ai_buddy_font_size"
    DEFAULT_WIDTH = 540
    MIN_WIDTH = 380
    RESIZE_MARGIN = 8

    DEFAULT_FONT_SIZE = 16
    MIN_FONT_SIZE = 13
    MAX_FONT_SIZE = 28

    def __init__(self, review_screen, parent=None):
        super().__init__(parent or review_screen)
        self.rs = review_screen
        self.setObjectName("ai_buddy_drawer")
        self._current_card = None
        self._active_box = None
        self._current_context = {}
        self._worker = None
        self._voice_worker = None
        self._is_listening = False
        self._continuous_active = False

        self._resizing = False
        self._drag_start_x = 0
        self._drag_start_w = self.DEFAULT_WIDTH

        settings = QSettings("AnkiOcclusion", "App")
        saved_w = settings.value(self.SETTINGS_WIDTH_KEY, self.DEFAULT_WIDTH, type=int)
        self._drawer_width = max(self.MIN_WIDTH, saved_w if isinstance(saved_w, int) and saved_w > 0 else self.DEFAULT_WIDTH)

        saved_fs = settings.value(self.SETTINGS_FONT_SIZE_KEY, self.DEFAULT_FONT_SIZE, type=int)
        self._font_size = max(self.MIN_FONT_SIZE, min(self.MAX_FONT_SIZE, saved_fs if isinstance(saved_fs, int) and saved_fs > 0 else self.DEFAULT_FONT_SIZE))

        # Message history: list of {"id": int, "role": str, "text": str, "raw_text": str}
        self._messages = []
        self._msg_counter = 0

        # TTS Engine
        self.tts_engine = TTSEngine(self)
        self.tts_engine.speech_started.connect(self._on_speech_started)
        self.tts_engine.speech_finished.connect(self._on_speech_finished)
        self.tts_engine.speech_stopped.connect(self._on_speech_stopped)
        self.tts_engine.error_occurred.connect(self._on_tts_error)

        self.setMouseTracking(True)
        self.setFixedWidth(self._drawer_width)
        self._setup_ui()
        self.update_key_status()
        self.hide()

    def _setup_ui(self):
        theme = getattr(self.rs, "theme", "classic")
        p = get_palette(theme)
        self.p = p

        bg = p.get("C_SURFACE", "#1A1A24")
        border = p.get("C_BORDER", "#2E2E3E")
        text = p.get("C_TEXT", "#FFFFFF")
        accent = "#CBA6F7"

        self.setStyleSheet(f"""
            QFrame#ai_buddy_drawer {{
                background-color: {bg};
                border-left: 2.5px solid {accent};
                border-top: 1px solid {border};
                border-bottom: 1px solid {border};
                border-radius: 0px;
            }}
            QLabel {{
                color: {text};
                font-family: 'Segoe UI', sans-serif;
            }}
            QLineEdit {{
                background: #11111B;
                color: #CDD6F4;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border: 1px solid {accent};
            }}
            QPushButton#btn_chip {{
                background: rgba(203, 166, 247, 0.12);
                color: #CBA6F7;
                border: 1px solid rgba(203, 166, 247, 0.35);
                border-radius: 12px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#btn_chip:hover {{
                background: rgba(203, 166, 247, 0.25);
                border-color: #CBA6F7;
            }}
            QPushButton#btn_mic {{
                background: #313244;
                color: #F38BA8;
                border: 1.5px solid #45475A;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 15px;
                font-weight: bold;
            }}
            QPushButton#btn_mic_active {{
                background: #F38BA8;
                color: #11111B;
                border: 1.5px solid #F38BA8;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 15px;
                font-weight: bold;
            }}
            QPushButton#btn_send {{
                background: {accent};
                color: #11111B;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton#btn_send:hover {{
                background: #B4BEFE;
            }}
        """)

        L = QVBoxLayout(self)
        L.setContentsMargins(14, 12, 14, 12)
        L.setSpacing(10)

        # ── 1. HEADER BAR ─────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        icon_lbl = QLabel("🤖")
        icon_lbl.setStyleSheet("font-size: 22px;")
        hdr.addWidget(icon_lbl)

        v_title = QVBoxLayout()
        v_title.setSpacing(1)
        self.lbl_title = QLabel("AI STUDY BUDDY (सहपाठी)")
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #CBA6F7;")
        v_title.addWidget(self.lbl_title)

        self.lbl_status = QLabel("🟢 Gemini • तैयार")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #A6ADC8;")
        v_title.addWidget(self.lbl_status)
        hdr.addLayout(v_title)

        hdr.addStretch()

        # Continuous Live Mode Toggle Button
        self.btn_live_mode = QPushButton("🔁 लाइव बातचीत")
        self.btn_live_mode.setObjectName("btn_live_mode")
        self.btn_live_mode.setFixedHeight(28)
        self.btn_live_mode.setToolTip("सतत बातचीत मोड (Continuous Live Mode • Alt+L)\nहाथों से मुक्त: आप बोलें ➔ AI बोलकर उत्तर देगा ➔ फिर बिना बटन दबाए अपने आप सुनेगा!")
        self.btn_live_mode.setStyleSheet("""
            QPushButton#btn_live_mode {
                background: rgba(137, 180, 250, 0.12);
                color: #89B4FA;
                border: 1px solid rgba(137, 180, 250, 0.35);
                border-radius: 14px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#btn_live_mode:hover {
                background: rgba(137, 180, 250, 0.25);
                border-color: #89B4FA;
            }
        """)
        self.btn_live_mode.clicked.connect(self.toggle_continuous_mode)
        hdr.addWidget(self.btn_live_mode)

        # Audio Mute/Unmute Toggle
        cfg = get_ai_settings()
        self.btn_audio_toggle = QPushButton("🔊" if cfg.get("auto_speak", True) else "🔇")
        self.btn_audio_toggle.setFixedSize(28, 28)
        self.btn_audio_toggle.setObjectName("btn_audio_toggle")
        self.btn_audio_toggle.setToolTip("AI आवाज़ बोलना चालू/बंद करें (Alt+S)")
        self.btn_audio_toggle.setStyleSheet("""
            QPushButton#btn_audio_toggle {
                background: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton#btn_audio_toggle:hover {
                background: #45475A;
                border-color: #89B4FA;
            }
        """)
        self.btn_audio_toggle.clicked.connect(self._toggle_auto_speak)
        hdr.addWidget(self.btn_audio_toggle)

        # Stop Speaking Button (visible only when speaking)
        self.btn_audio_stop = QPushButton("⏹️")
        self.btn_audio_stop.setFixedSize(28, 28)
        self.btn_audio_stop.setObjectName("btn_audio_stop")
        self.btn_audio_stop.setToolTip("बोलना तुरंत रोकें")
        self.btn_audio_stop.setStyleSheet("""
            QPushButton#btn_audio_stop {
                background: #F38BA8;
                color: #11111B;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#btn_audio_stop:hover {
                background: #EBA0AC;
            }
        """)
        self.btn_audio_stop.clicked.connect(self._stop_speech)
        self.btn_audio_stop.hide()
        hdr.addWidget(self.btn_audio_stop)

        # Font Zoom Controls
        zoom_frame = QFrame()
        zoom_frame.setStyleSheet("background: #1E1E2E; border: 1px solid #313244; border-radius: 5px;")
        zoom_layout = QHBoxLayout(zoom_frame)
        zoom_layout.setContentsMargins(4, 2, 4, 2)
        zoom_layout.setSpacing(2)

        self.btn_font_minus = QPushButton("A-")
        self.btn_font_minus.setFixedSize(24, 24)
        self.btn_font_minus.setToolTip("फ़ॉन्ट छोटा करें (Ctrl + -)")
        self.btn_font_minus.setStyleSheet("background: transparent; color: #CDD6F4; border: none; font-size: 11px; font-weight: bold;")
        self.btn_font_minus.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(self.btn_font_minus)

        self.lbl_font_size = QLabel(f"{self._font_size}px")
        self.lbl_font_size.setFixedWidth(34)
        self.lbl_font_size.setAlignment(Qt.AlignCenter)
        self.lbl_font_size.setToolTip("क्लिक करके डिफ़ॉल्ट साइज़ (16px) पर रीसेट करें")
        self.lbl_font_size.setStyleSheet("font-size: 11px; color: #CBA6F7; font-weight: bold; border: none;")
        self.lbl_font_size.setCursor(QCursor(Qt.PointingHandCursor))
        self.lbl_font_size.mousePressEvent = lambda e: self.reset_font_size()
        zoom_layout.addWidget(self.lbl_font_size)

        self.btn_font_plus = QPushButton("A+")
        self.btn_font_plus.setFixedSize(24, 24)
        self.btn_font_plus.setToolTip("फ़ॉन्ट बड़ा करें (Ctrl + +)")
        self.btn_font_plus.setStyleSheet("background: transparent; color: #CDD6F4; border: none; font-size: 11px; font-weight: bold;")
        self.btn_font_plus.clicked.connect(self.zoom_in)
        zoom_layout.addWidget(self.btn_font_plus)
        hdr.addWidget(zoom_frame)

        # Key Switcher Button
        self.btn_key_toggle = QPushButton("🔑 1/1")
        self.btn_key_toggle.setObjectName("btn_key_toggle")
        self.btn_key_toggle.setFixedHeight(28)
        self.btn_key_toggle.setToolTip("सक्रिय API Key बदलें (Alt+K) • ऑटो-फ़ेलओवर सक्रिय")
        self.btn_key_toggle.setStyleSheet("""
            QPushButton#btn_key_toggle {
                background: rgba(137, 180, 250, 0.15);
                color: #89B4FA;
                border: 1px solid rgba(137, 180, 250, 0.35);
                border-radius: 14px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton#btn_key_toggle:hover {
                background: rgba(137, 180, 250, 0.28);
                border-color: #89B4FA;
            }
        """)
        self.btn_key_toggle.clicked.connect(self.cycle_api_key)
        hdr.addWidget(self.btn_key_toggle)

        # Settings Button
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setObjectName("btn_settings")
        self.btn_settings.setFixedSize(28, 28)
        self.btn_settings.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_settings.setToolTip("AI सेटिंग्स व API Key")
        self.btn_settings.setStyleSheet("""
            QPushButton#btn_settings {
                background: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton#btn_settings:hover {
                background: #45475A;
                border-color: #89B4FA;
            }
        """)
        self.btn_settings.clicked.connect(self._open_settings)
        hdr.addWidget(self.btn_settings)

        # Close Button
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btn_close")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_close.setToolTip("ड्रॉअर बंद करें (Alt+D या Esc)")
        self.btn_close.setStyleSheet("""
            QPushButton#btn_close {
                background: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#btn_close:hover {
                background: #F38BA8;
                color: #11111B;
            }
        """)
        self.btn_close.clicked.connect(self.close_drawer)
        hdr.addWidget(self.btn_close)
        L.addLayout(hdr)

        # ── 2. QUICK CHIPS ROW ────────────────────────────────────────────────
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)

        self.chip_recall = QPushButton("🎙️ Assess Recall")
        self.chip_recall.setObjectName("btn_chip")
        self.chip_recall.setToolTip("माइक से बोलें और AI से अपने उत्तर का मूल्यांकन कराएं (Alt+V)")
        self.chip_recall.clicked.connect(self._toggle_voice_input)
        chips_row.addWidget(self.chip_recall)

        self.chip_trap = QPushButton("🎯 SSC Trap")
        self.chip_trap.setObjectName("btn_chip")
        self.chip_trap.setToolTip("इस सवाल का मुख्य ट्रैप व कन्फ़्यूज़न पॉइंट पूछें")
        self.chip_trap.clicked.connect(lambda: self._send_quick_prompt("trap"))
        chips_row.addWidget(self.chip_trap)

        self.chip_mnemonic = QPushButton("💡 Memory Trick")
        self.chip_mnemonic.setObjectName("btn_chip")
        self.chip_mnemonic.setToolTip("इस सवाल को याद रखने की शॉर्ट ट्रिक पूछें")
        self.chip_mnemonic.clicked.connect(lambda: self._send_quick_prompt("mnemonic"))
        chips_row.addWidget(self.chip_mnemonic)

        self.chip_connect = QPushButton("🔗 360° Link")
        self.chip_connect.setObjectName("btn_chip")
        self.chip_connect.setToolTip("दूसरे विषयों से इसका कनेक्शन पूछें")
        self.chip_connect.clicked.connect(lambda: self._send_quick_prompt("connect"))
        chips_row.addWidget(self.chip_connect)

        chips_row.addStretch()
        L.addLayout(chips_row)

        # ── 3. CHAT DISPLAY ───────────────────────────────────────────────────
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.anchorClicked.connect(self._on_anchor_clicked)
        self.chat_view.installEventFilter(self)
        self.chat_view.setStyleSheet("""
            QTextBrowser {
                background-color: #11111B;
                border: 1px solid #313244;
                border-radius: 8px;
                padding: 10px;
                color: #CDD6F4;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        L.addWidget(self.chat_view, stretch=1)

        # ── 4. INPUT ROW ──────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        # Voice Input Button
        self.btn_mic = QPushButton("🎙️")
        self.btn_mic.setObjectName("btn_mic")
        self.btn_mic.setFixedSize(40, 40)
        self.btn_mic.setToolTip("माइक ऑन/ऑफ करें (Push to Talk • Alt+V)")
        self.btn_mic.clicked.connect(self._toggle_voice_input)
        input_row.addWidget(self.btn_mic)

        # Text input
        self.edit_input = QLineEdit()
        self.edit_input.setPlaceholderText("अपना उत्तर बोलें (Alt+V) या यहाँ टाइप करें...")
        self.edit_input.returnPressed.connect(self._on_send_clicked)
        input_row.addWidget(self.edit_input, stretch=1)

        # Send Button
        self.btn_send = QPushButton("भेजें")
        self.btn_send.setObjectName("btn_send")
        self.btn_send.setFixedHeight(40)
        self.btn_send.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self.btn_send)

        L.addLayout(input_row)

        self._refresh_status_label()

    # ── FONT ZOOM LOGIC ───────────────────────────────────────────────────────
    def zoom_in(self):
        if self._font_size < self.MAX_FONT_SIZE:
            self._font_size += 1
            self._apply_font_size()

    def zoom_out(self):
        if self._font_size > self.MIN_FONT_SIZE:
            self._font_size -= 1
            self._apply_font_size()

    def reset_font_size(self):
        self._font_size = self.DEFAULT_FONT_SIZE
        self._apply_font_size()

    def _apply_font_size(self):
        self.lbl_font_size.setText(f"{self._font_size}px")
        s = QSettings("AnkiOcclusion", "App")
        s.setValue(self.SETTINGS_FONT_SIZE_KEY, self._font_size)
        self._render_chat()

    def eventFilter(self, obj, event):
        if obj == self.chat_view and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True
        return super().eventFilter(obj, event)

    # ── CHAT RENDERING ────────────────────────────────────────────────────────
    def _render_chat(self):
        fs = self._font_size
        css = f"""
        <style>
            body {{
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                font-size: {fs}px;
                line-height: 1.6;
                color: #CDD6F4;
                margin: 0;
                padding: 4px;
            }}
            .welcome-box {{
                background: #181825;
                border-left: 3.5px solid #89B4FA;
                border-radius: 6px;
                padding: 10px 14px;
                margin-bottom: 12px;
                font-size: {max(13, fs - 1)}px;
                color: #BAC2DE;
            }}
            .user-row {{
                margin: 10px 0;
                text-align: right;
            }}
            .user-bubble {{
                display: inline-block;
                background: #313244;
                color: #CDD6F4;
                padding: 10px 16px;
                border-radius: 14px;
                border-bottom-right-radius: 2px;
                max-width: 86%;
                text-align: left;
                font-size: {fs}px;
            }}
            .ai-row {{
                margin: 12px 0;
            }}
            .ai-bubble {{
                background: rgba(203, 166, 247, 0.09);
                border-left: 3.5px solid #CBA6F7;
                color: #CDD6F4;
                padding: 12px 16px;
                border-radius: 10px;
                font-size: {fs}px;
            }}
            .ai-header {{
                margin-bottom: 6px;
                color: #CBA6F7;
                font-weight: bold;
                font-size: {max(13, fs)}px;
            }}
            .replay-btn {{
                color: #89B4FA;
                text-decoration: none;
                font-size: {max(11, fs - 4)}px;
                background: #1E1E2E;
                border: 1px solid #45475A;
                padding: 2px 8px;
                border-radius: 4px;
                margin-left: 8px;
            }}
            .system-bubble {{
                background: rgba(243, 139, 168, 0.12);
                border: 1px solid #F38BA8;
                color: #F38BA8;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: {max(12, fs - 2)}px;
                margin: 6px 0;
            }}
            .failover-bubble {{
                background: rgba(249, 226, 175, 0.15);
                border: 1px solid rgba(249, 226, 175, 0.4);
                color: #F9E2AF;
                padding: 5px 12px;
                border-radius: 10px;
                font-size: {max(11, fs - 3)}px;
                text-align: center;
                margin: 6px 0;
            }}
        </style>
        """

        html_body = []
        for msg in self._messages:
            m_role = msg["role"]
            m_text = msg["text"]
            m_id = msg.get("id", 0)

            if m_role == "welcome":
                html_body.append(f"<div class='welcome-box'>{m_text}</div>")

            elif m_role == "user":
                esc = html.escape(m_text).replace("\n", "<br>")
                html_body.append(f"""
                <div class='user-row'>
                    <div class='user-bubble'>
                        🗣️ <b>आप:</b><br>{esc}
                    </div>
                </div>
                """)

            elif m_role == "ai":
                formatted = html.escape(m_text)
                formatted = formatted.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
                formatted = re.sub(r'\*\*(.+?)\*\*', r'<b style="color: #CBA6F7;">\1</b>', formatted)
                formatted = formatted.replace("\n", "<br>")

                replay_link = f"<a class='replay-btn' href='speak:{m_id}'>🔊 फिर से सुनें</a>"
                html_body.append(f"""
                <div class='ai-row'>
                    <div class='ai-bubble'>
                        <div class='ai-header'>
                            🤖 <b>Study Buddy (सहपाठी):</b> {replay_link}
                        </div>
                        {formatted}
                    </div>
                </div>
                """)

            elif m_role == "failover":
                html_body.append(f"<div class='failover-bubble'>{m_text}</div>")

            elif m_role == "system":
                html_body.append(f"<div class='system-bubble'>{m_text}</div>")

        full_html = css + "".join(html_body)
        self.chat_view.setHtml(full_html)
        self._scroll_chat_to_bottom()

    def _scroll_chat_to_bottom(self):
        sb = self.chat_view.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _on_anchor_clicked(self, url: QUrl):
        s = url.toString()
        if s.startswith("speak:"):
            try:
                m_id = int(s.split(":")[1])
                for m in self._messages:
                    if m.get("id") == m_id:
                        cfg = get_ai_settings()
                        self.tts_engine.speak(m.get("raw_text", m["text"]), voice=cfg["tts_voice"], rate=cfg["tts_speed"])
                        break
            except Exception:
                pass
        elif s.startswith("http"):
            QDesktopServices.openUrl(url)

    # ── TTS CONTROLS ──────────────────────────────────────────────────────────
    def _toggle_auto_speak(self):
        cfg = get_ai_settings()
        new_val = not cfg.get("auto_speak", True)
        save_ai_settings(auto_speak=new_val)
        self.btn_audio_toggle.setText("🔊" if new_val else "🔇")
        if not new_val:
            self.tts_engine.stop()
            self._show_toast("🔇 AI वॉइस म्यूट (अब केवल टेक्स्ट दिखेगा)")
        else:
            self._show_toast("🔊 AI वॉइस सक्रिय (AI उत्तर बोलकर सुनाएगा)")

    def _stop_speech(self):
        self.tts_engine.stop()

    def _on_speech_started(self, file_path: str):
        self.btn_audio_stop.show()
        self.lbl_status.setText("🔊 बोल रहा हूँ...")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #A6E3A1; font-weight: bold;")

    def _on_speech_finished(self):
        self.btn_audio_stop.hide()
        if self._continuous_active and self.isVisible():
            self.lbl_status.setText("🎙️ आपकी बारी • बोलिए (लाइव बातचीत)...")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #A6E3A1; font-weight: bold;")
            QTimer.singleShot(400, self._auto_restart_voice_if_live)
        else:
            self._refresh_status_label()

    def _auto_restart_voice_if_live(self):
        if self._continuous_active and self.isVisible() and not self._is_listening and not self.tts_engine.is_speaking():
            self._start_voice_input()

    def _on_speech_stopped(self):
        self.btn_audio_stop.hide()
        self._refresh_status_label()

    def _on_tts_error(self, err: str):
        self.btn_audio_stop.hide()
        self._refresh_status_label()

    # ── CARD TRANSITION ───────────────────────────────────────────────────────
    def set_current_card(self, card: dict, active_box=None, sm2_obj=None):
        """Called automatically whenever the ReviewScreen transitions to a new card."""
        self._current_card = card
        self._active_box = active_box
        self._stop_speech()
        if self._voice_worker and self._voice_worker.isRunning():
            self._voice_worker.cancel()

        try:
            deck_name = getattr(self.rs, "deck_name", "") or (card.get("deck_name", "") if card else "")
            self._current_context = build_card_context(card, active_box, deck_name)
        except Exception as e:
            self._current_context = {"summary": "Card context unavailable.", "error": str(e), "question": ""}

        # Reset chat history for this active card
        self._messages = []
        self._msg_counter = 0

        q_text = self._current_context.get("question", "")
        if not isinstance(q_text, str):
            q_text = str(q_text or "")
        if len(q_text) > 120:
            q_text = q_text[:117] + "..."

        welcome_text = f"""
            📌 <b>सक्रिय प्रश्न:</b> {html.escape(q_text)}<br>
            <i>माइक का बटन 🎙️ (या <b>Alt+V</b> / <b>Alt+L</b>) दबाकर अपना जवाब बोलें, या नीचे सवाल पूछें।</i>
        """
        self._msg_counter += 1
        self._messages.append({
            "id": self._msg_counter,
            "role": "welcome",
            "text": welcome_text,
            "raw_text": ""
        })
        self._render_chat()

        cfg = get_ai_settings()
        if (self._continuous_active or cfg["auto_listen"]) and self.isVisible():
            QTimer.singleShot(400, self._auto_restart_voice_if_live if self._continuous_active else self._start_voice_input)

    def _open_settings(self):
        try:
            dlg = AISettingsDialog(self)
            dlg.settings_saved.connect(self._on_settings_saved)
            dlg.exec_()
        except Exception as e:
            print(f"[AISettings] Error opening settings dialog: {e}")
            self._show_toast(f"⚠️ सेटिंग्स खोलने में समस्या: {e}")

    def _on_settings_saved(self):
        cfg = get_ai_settings()
        self.btn_audio_toggle.setText("🔊" if cfg.get("auto_speak", True) else "🔇")
        self._refresh_status_label()

    def toggle_drawer(self):
        if self.isVisible():
            self.close_drawer()
        else:
            self.open_drawer()

    def open_drawer(self):
        self.update_geometry()
        self.show()
        self.raise_()
        self._refresh_status_label()
        self.edit_input.setFocus()

    def close_drawer(self):
        self._continuous_active = False
        self._update_live_mode_ui()
        self._stop_speech()
        if self._voice_worker and self._voice_worker.isRunning():
            self._voice_worker.cancel()
        self.hide()

    def update_geometry(self):
        p = self.parentWidget() or self.rs
        if not p:
            return
        dw = getattr(self, "_drawer_width", self.DEFAULT_WIDTH)
        self.setGeometry(p.width() - dw, 0, dw, p.height())

    # ── VOICE INPUT HANDLING ──────────────────────────────────────────────────
    def _toggle_voice_input(self):
        if self._is_listening:
            if self._continuous_active:
                self._continuous_active = False
                self._update_live_mode_ui()
            self._stop_voice_input()
        else:
            cfg = get_ai_settings()
            if cfg.get("continuous_mode", False):
                self._continuous_active = True
                self._update_live_mode_ui()
            self._start_voice_input()

    def _start_voice_input(self):
        self._stop_speech()  # Stop AI talking when student begins speaking
        if self._voice_worker and self._voice_worker.isRunning():
            return
        cfg = get_ai_settings()
        self._is_listening = True
        self.btn_mic.setObjectName("btn_mic_active")
        self.btn_mic.setText("🔴")
        self.btn_mic.setStyleSheet("background: #F38BA8; color: #11111B; font-weight: bold;")

        status_prefix = "🟢 [लाइव] " if self._continuous_active else "🎙️ "
        self.lbl_status.setText(f"{status_prefix}सुन रहा हूँ... (बोलिए)")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #F38BA8; font-weight: bold;")

        self._voice_worker = VoiceInputWorker(
            language=cfg["voice_lang"],
            phrase_limit=60,
            pause_threshold=2.0,
            timeout=12,
            parent=self
        )
        self._voice_worker.listening_audio.connect(self._on_voice_listening)
        self._voice_worker.transcribing_audio.connect(lambda: self.lbl_status.setText("⏳ ट्रांसक्राइब कर रहा हूँ..."))
        self._voice_worker.text_ready.connect(self._on_voice_text_ready)
        self._voice_worker.timed_out.connect(self._on_voice_timed_out)
        self._voice_worker.error_occurred.connect(self._on_voice_error)
        self._voice_worker.finished.connect(self._on_voice_finished)
        self._voice_worker.start()

    def _on_voice_listening(self):
        status_prefix = "🟢 [लाइव] " if self._continuous_active else "🎙️ "
        self.lbl_status.setText(f"{status_prefix}सुन रहा हूँ... (बोलिए)")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #F38BA8; font-weight: bold;")

    def _on_voice_timed_out(self):
        if self._continuous_active and self.isVisible():
            self.lbl_status.setText("🟢 लाइव मोड सक्रिय • मैं सुन रहा हूँ...")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #A6E3A1;")
            QTimer.singleShot(300, self._auto_restart_voice_if_live)
        else:
            self._refresh_status_label()

    def _stop_voice_input(self):
        if self._voice_worker and self._voice_worker.isRunning():
            self._voice_worker.cancel()
        self._on_voice_finished()

    def _on_voice_finished(self):
        self._is_listening = False
        self.btn_mic.setObjectName("btn_mic")
        self.btn_mic.setText("🎙️")
        self.btn_mic.setStyleSheet("background: #313244; color: #F38BA8; font-weight: bold;")
        self._refresh_status_label()

    def _on_voice_text_ready(self, spoken_text: str):
        self.edit_input.setText(spoken_text)
        self._on_send_clicked()

    def _on_voice_error(self, err_msg: str):
        if self._continuous_active and "साफ़ सुनाई नहीं दी" in err_msg:
            self.lbl_status.setText("⚠️ आवाज़ स्पष्ट नहीं थी • कृपया दोबारा बोलें...")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #F9E2AF;")
            QTimer.singleShot(800, self._auto_restart_voice_if_live)
        else:
            self._append_system_bubble(err_msg)

    # ── QUERY & CHAT HANDLING ─────────────────────────────────────────────────
    def _send_quick_prompt(self, mode: str):
        self._stop_speech()
        self._dispatch_ai_query(user_text="", mode=mode)

    def _on_send_clicked(self):
        self._stop_speech()
        text = self.edit_input.text().strip()
        if not text:
            return
        self.edit_input.clear()
        self._append_user_bubble(text)
        self._dispatch_ai_query(user_text=text, mode="recall")

    def _dispatch_ai_query(self, user_text: str, mode: str = "recall"):
        if self._worker and self._worker.isRunning():
            return

        cfg = get_ai_settings()
        if not cfg["api_key"]:
            self._open_settings()
            return

        self.lbl_status.setText("⚡ विचार कर रहा हूँ...")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #F9E2AF; font-weight: bold;")
        self.btn_send.setEnabled(False)

        self._worker = AICoachWorker(self._current_context, user_text, prompt_mode=mode, parent=self)
        self._worker.response_ready.connect(self._on_ai_response_ready)
        self._worker.error_occurred.connect(self._on_ai_error)
        self._worker.key_switched.connect(self._on_key_switched)
        self._worker.finished.connect(lambda: self.btn_send.setEnabled(True))
        self._worker.start()

    def _on_ai_response_ready(self, reply_text: str):
        self._refresh_status_label()
        self._append_ai_bubble(reply_text)

        cfg = get_ai_settings()
        if cfg.get("auto_speak", True):
            self.tts_engine.speak(reply_text, voice=cfg["tts_voice"], rate=cfg["tts_speed"])
        elif self._continuous_active and self.isVisible():
            # Auto-speak is OFF, wait 2.5s for user to read text, then resume listening
            QTimer.singleShot(2500, self._auto_restart_voice_if_live)

    def _on_ai_error(self, err_msg: str):
        self._refresh_status_label()
        self._append_system_bubble(err_msg)

    def _append_user_bubble(self, text: str):
        self._msg_counter += 1
        self._messages.append({
            "id": self._msg_counter,
            "role": "user",
            "text": text,
            "raw_text": text
        })
        self._render_chat()

    def _append_ai_bubble(self, text: str):
        self._msg_counter += 1
        self._messages.append({
            "id": self._msg_counter,
            "role": "ai",
            "text": text,
            "raw_text": text
        })
        self._render_chat()

    def _append_system_bubble(self, text: str):
        self._msg_counter += 1
        self._messages.append({
            "id": self._msg_counter,
            "role": "system",
            "text": text,
            "raw_text": ""
        })
        self._render_chat()

    # ── MULTI-KEY POOL & ROTATION ─────────────────────────────────────────────
    def cycle_api_key(self):
        """Manually cycle to the next API key in the pool and show toast/status."""
        new_idx, total, new_key = cycle_next_key()
        if total == 0:
            self._open_settings()
            return
        if total <= 1:
            self._show_toast("🔑 केवल 1 Key उपलब्ध है (⚙️ सेटिंग्स में अन्य अकाउंट्स की Keys जोड़ें)")
            return
        self.update_key_status()
        self._show_toast(f"🔄 सक्रिय API Key बदली गई: Key {new_idx}/{total}")

    def update_key_status(self):
        cfg = get_ai_settings()
        total = cfg["total_keys"]
        active = cfg["active_key_index"] + 1 if total > 0 else 0
        if total > 1:
            self.btn_key_toggle.setText(f"🔑 {active}/{total}")
            self.btn_key_toggle.show()
            self.btn_key_toggle.setToolTip(f"सक्रिय Key {active}/{total} • क्लिक करें या Alt+K दबाकर बदलें")
            self.lbl_status.setText(f"🟢 Key {active}/{total} • {cfg['model_name']}")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #A6ADC8;")
        elif total == 1:
            self.btn_key_toggle.setText("🔑 1/1")
            self.btn_key_toggle.show()
            self.btn_key_toggle.setToolTip("1 Key सक्रिय (दैनिक कोटा: ~1,500 रिक्वेस्ट्स)")
            self.lbl_status.setText(f"🟢 {cfg['model_name']} • तैयार")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #A6ADC8;")
        else:
            self.btn_key_toggle.setText("🔑 Key जोड़ें")
            self.btn_key_toggle.show()
            self.btn_key_toggle.setToolTip("कोई API Key नहीं है — क्लिक करके अपनी Google Gemini API Key जोड़ें")
            self.lbl_status.setText("🔴 कोई Key नहीं (⚙️ दबाएँ)")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #F38BA8; font-weight: bold;")

    def _refresh_status_label(self):
        if self.tts_engine.is_speaking():
            self.lbl_status.setText("🔊 बोल रहा हूँ...")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #A6E3A1; font-weight: bold;")
        else:
            self.update_key_status()

    def _on_key_switched(self, new_idx: int, total: int, reason: str):
        self.update_key_status()
        self._msg_counter += 1
        msg = f"🔄 <b>[ऑटो-फ़ेलओवर]:</b> {reason} — बिना रुकावट <b>Key {new_idx}/{total}</b> पर स्विच किया गया!"
        self._messages.append({
            "id": self._msg_counter,
            "role": "failover",
            "text": msg,
            "raw_text": ""
        })
        self._render_chat()

    def _show_toast(self, message: str):
        if hasattr(self.rs, "_show_review_toast"):
            self.rs._show_review_toast(message)
        else:
            self._append_system_bubble(message)

    # ── CONTINUOUS LIVE CONVERSATION MODE ─────────────────────────────────────
    def toggle_continuous_mode(self, force_state: bool = None):
        if force_state is not None:
            self._continuous_active = force_state
        else:
            self._continuous_active = not self._continuous_active

        self._update_live_mode_ui()

        if self._continuous_active:
            self._show_toast("🟢 सतत बातचीत मोड चालू — अब बिना Alt+V दबाए लगातार बात करें!")
            if not self._is_listening and not self.tts_engine.is_speaking():
                self._start_voice_input()
        else:
            self._show_toast("⚪ सतत बातचीत मोड बंद")
            if self._is_listening:
                self._stop_voice_input()

    def _update_live_mode_ui(self):
        if not hasattr(self, "btn_live_mode"):
            return
        if self._continuous_active:
            self.btn_live_mode.setText("🟢 लाइव मोड ON")
            self.btn_live_mode.setStyleSheet("""
                QPushButton#btn_live_mode {
                    background: #A6E3A1;
                    color: #11111B;
                    border: 1.5px solid #A6E3A1;
                    border-radius: 14px;
                    padding: 2px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton#btn_live_mode:hover {
                    background: #94E2D5;
                }
            """)
        else:
            self.btn_live_mode.setText("🔁 लाइव बातचीत")
            self.btn_live_mode.setStyleSheet("""
                QPushButton#btn_live_mode {
                    background: rgba(137, 180, 250, 0.12);
                    color: #89B4FA;
                    border: 1px solid rgba(137, 180, 250, 0.35);
                    border-radius: 14px;
                    padding: 2px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton#btn_live_mode:hover {
                    background: rgba(137, 180, 250, 0.25);
                    border-color: #89B4FA;
                }
            """)

    def keyPressEvent(self, e):
        mods = e.modifiers()
        key = e.key()

        if mods == Qt.AltModifier and key == Qt.Key_L:
            self.toggle_continuous_mode()
            e.accept()
            return

        if mods == Qt.AltModifier and key == Qt.Key_V:
            self._toggle_voice_input()
            e.accept()
            return

        if mods == Qt.AltModifier and key == Qt.Key_K:
            self.cycle_api_key()
            e.accept()
            return

        if mods == Qt.AltModifier and key == Qt.Key_S:
            self._toggle_auto_speak()
            e.accept()
            return

        if mods == Qt.ControlModifier:
            if key in (Qt.Key_Plus, Qt.Key_Equal):
                self.zoom_in()
                e.accept()
                return
            elif key == Qt.Key_Minus:
                self.zoom_out()
                e.accept()
                return
            elif key == Qt.Key_0:
                self.reset_font_size()
                e.accept()
                return

        if key == Qt.Key_Escape:
            self.close_drawer()
            e.accept()
            return

        super().keyPressEvent(e)

    # ── RESIZE HANDLING ───────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.pos().x() <= self.RESIZE_MARGIN:
            self._resizing = True
            self._drag_start_x = e.globalPos().x()
            self._drag_start_w = self.width()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resizing:
            delta_x = e.globalPos().x() - self._drag_start_x
            new_w = max(self.MIN_WIDTH, self._drag_start_w - delta_x)
            p = self.parentWidget() or self.rs
            if p:
                new_w = min(new_w, int(p.width() * 0.85))
            self._drawer_width = new_w
            self.setFixedWidth(new_w)
            self.update_geometry()
            e.accept()
            return
        if e.pos().x() <= self.RESIZE_MARGIN:
            self.setCursor(QCursor(Qt.SizeHorCursor))
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resizing:
            self._resizing = False
            self.setCursor(QCursor(Qt.ArrowCursor))
            s = QSettings("AnkiOcclusion", "App")
            s.setValue(self.SETTINGS_WIDTH_KEY, self.width())
            e.accept()
            return
        super().mouseReleaseEvent(e)