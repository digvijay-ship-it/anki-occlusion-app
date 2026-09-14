"""
Socratic AI Study Buddy Drawer for ReviewScreen.
Provides live peer discussion, voice-to-text recall evaluation,
SSC exam trap analysis, and memory anchoring via Google Gemini 2.0 Flash.
"""

from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextBrowser, QScrollArea, QDialog, QComboBox, QCheckBox,
    QApplication, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, pyqtSignal, QSettings, QTimer
from PyQt5.QtGui import QColor, QFont, QCursor
from theme_manager import get_palette
import html

from services.ai_coach_service import (
    get_ai_settings, save_ai_settings, build_card_context, AICoachWorker,
    DEFAULT_MODEL, FALLBACK_MODEL
)
from services.voice_input_service import VoiceInputWorker


class AISettingsDialog(QDialog):
    """Configuration modal for Gemini API Key, model version, and voice options."""
    settings_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Study Buddy — सेटिंग्स")
        self.setFixedSize(480, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #181825;
                color: #CDD6F4;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #CDD6F4;
                font-size: 13px;
            }
            QLineEdit, QComboBox {
                background: #1E1E2E;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #CBA6F7;
            }
            QPushButton#btn_save {
                background: #CBA6F7;
                color: #11111B;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton#btn_save:hover {
                background: #B4BEFE;
            }
            QPushButton#btn_cancel {
                background: #313244;
                color: #CDD6F4;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
            }
        """)
        self._init_ui()

    def _init_ui(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(24, 20, 24, 20)
        L.setSpacing(14)

        title = QLabel("⚙️ AI Study Buddy सेटिंग्स")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #CBA6F7;")
        L.addWidget(title)

        desc = QLabel("Google Gemini की मुफ़्त API Key दर्ज करें। यह 100% मुफ़्त है और प्रतिदिन 1,500 चर्चाओं की अनुमति देती है।")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #A6ADC8; font-size: 12px; line-height: 1.4;")
        L.addWidget(desc)

        cfg = get_ai_settings()

        # API Key input
        L.addWidget(QLabel("🔑 Google Gemini API Key:"))
        self.edit_key = QLineEdit(cfg["api_key"])
        self.edit_key.setPlaceholderText("AIzaSy... (aistudio.google.com से मुफ़्त लें)")
        self.edit_key.setEchoMode(QLineEdit.Password)
        L.addWidget(self.edit_key)

        # Key link info
        link_lbl = QLabel("<a href='https://aistudio.google.com' style='color: #89B4FA;'>👉 यहाँ से अपनी मुफ़्त API Key प्राप्त करें (Google AI Studio)</a>")
        link_lbl.setOpenExternalLinks(True)
        L.addWidget(link_lbl)

        # Model Selector
        L.addWidget(QLabel("🧠 AI मॉडल इंजन:"))
        self.combo_model = QComboBox()
        self.combo_model.addItem("Gemini 2.0 Flash (सुपरफ़ास्ट, स्मार्ट • अनुशंसित)", "gemini-2.0-flash")
        self.combo_model.addItem("Gemini 1.5 Flash (क्लासिक स्टेबल)", "gemini-1.5-flash")
        idx = self.combo_model.findData(cfg["model_name"])
        if idx >= 0:
            self.combo_model.setCurrentIndex(idx)
        L.addWidget(self.combo_model)

        # Voice Language
        L.addWidget(QLabel("🎙️ माइक वॉइस भाषा:"))
        self.combo_lang = QComboBox()
        self.combo_lang.addItem("हिंदी व हिंग्लिश (hi-IN • डिफ़ॉल्ट)", "hi-IN")
        self.combo_lang.addItem("English (en-IN)", "en-IN")
        l_idx = self.combo_lang.findData(cfg["voice_lang"])
        if l_idx >= 0:
            self.combo_lang.setCurrentIndex(l_idx)
        L.addWidget(self.combo_lang)

        # Auto-Listen checkbox
        self.chk_auto = QCheckBox("कार्ड बदलते ही अपने आप सुनना शुरू करें (Auto Push-to-Talk)")
        self.chk_auto.setChecked(cfg["auto_listen"])
        self.chk_auto.setStyleSheet("color: #CDD6F4; font-size: 12px; margin-top: 4px;")
        L.addWidget(self.chk_auto)

        L.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("रद्द करें")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("सहेजें (Save)")
        btn_save.setObjectName("btn_save")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        L.addLayout(btn_row)

    def _save(self):
        key = self.edit_key.text().strip()
        model = self.combo_model.currentData()
        lang = self.combo_lang.currentData()
        auto_l = self.chk_auto.isChecked()
        save_ai_settings(api_key=key, model_name=model, auto_listen=auto_l, voice_lang=lang)
        self.settings_saved.emit()
        self.accept()


class AIBuddyDrawer(QFrame):
    """
    Slide-out Socratic AI Study Buddy Drawer on ReviewScreen.
    Displays:
    1. Status header with active card summary & settings.
    2. Quick Prompt Chips (Recall, Trap, Mnemonic, 360° Link).
    3. Rich conversational history with formatting.
    4. Voice (Push-to-Talk) & text input bar.
    """
    SETTINGS_WIDTH_KEY = "review/ai_buddy_width"
    DEFAULT_WIDTH = 480
    MIN_WIDTH = 340
    RESIZE_MARGIN = 8

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

        self._resizing = False
        self._drag_start_x = 0
        self._drag_start_w = self.DEFAULT_WIDTH

        settings = QSettings("AnkiOcclusion", "App")
        saved_w = settings.value(self.SETTINGS_WIDTH_KEY, self.DEFAULT_WIDTH, type=int)
        self._drawer_width = max(self.MIN_WIDTH, saved_w if isinstance(saved_w, int) and saved_w > 0 else self.DEFAULT_WIDTH)

        self.setMouseTracking(True)
        self.setFixedWidth(self._drawer_width)
        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        theme = getattr(self.rs, "theme", "classic")
        p = get_palette(theme)
        self.p = p

        bg = p.get("C_SURFACE", "#1A1A24")
        border = p.get("C_BORDER", "#2E2E3E")
        text = p.get("C_TEXT", "#FFFFFF")
        subtext = p.get("C_SUBTEXT", "#A0AEC0")
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
                padding: 9px 12px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {accent};
            }}
            QPushButton#btn_chip {{
                background: rgba(203, 166, 247, 0.12);
                color: #CBA6F7;
                border: 1px solid rgba(203, 166, 247, 0.35);
                border-radius: 12px;
                padding: 4px 10px;
                font-size: 11px;
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
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton#btn_mic_active {{
                background: #F38BA8;
                color: #11111B;
                border: 1.5px solid #F38BA8;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton#btn_send {{
                background: {accent};
                color: #11111B;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
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
        icon_lbl.setStyleSheet("font-size: 20px;")
        hdr.addWidget(icon_lbl)

        v_title = QVBoxLayout()
        v_title.setSpacing(1)
        self.lbl_title = QLabel("AI STUDY BUDDY (सहपाठी)")
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #CBA6F7;")
        v_title.addWidget(self.lbl_title)

        self.lbl_status = QLabel("🟢 Gemini 2.0 Flash • तैयार")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #A6ADC8;")
        v_title.addWidget(self.lbl_status)
        hdr.addLayout(v_title)

        hdr.addStretch()

        # Settings Button
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(30, 30)
        self.btn_settings.setToolTip("AI सेटिंग्स व API Key")
        self.btn_settings.setStyleSheet("background:#313244;color:#CDD6F4;border:none;border-radius:4px;font-size:14px;")
        self.btn_settings.clicked.connect(self._open_settings)
        hdr.addWidget(self.btn_settings)

        # Close Button
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.setToolTip("ड्रॉअर बंद करें (Alt+D या Esc)")
        self.btn_close.setStyleSheet("background:#313244;color:#CDD6F4;border:none;border-radius:4px;font-size:14px;font-weight:bold;")
        self.btn_close.clicked.connect(self.close_drawer)
        hdr.addWidget(self.btn_close)
        L.addLayout(hdr)

        # ── 2. QUICK CHIPS ROW ────────────────────────────────────────────────
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)

        self.chip_recall = QPushButton("🎙️ Assess Recall")
        self.chip_recall.setObjectName("btn_chip")
        self.chip_recall.setToolTip("माइक से बोलें और AI से अपने उत्तर का मूल्यांकन कराएं")
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
        self.chat_view.setOpenExternalLinks(True)
        self.chat_view.setStyleSheet("""
            QTextBrowser {
                background-color: #11111B;
                border: 1px solid #313244;
                border-radius: 8px;
                padding: 12px;
                color: #CDD6F4;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        L.addWidget(self.chat_view, stretch=1)

        # ── 4. INPUT ROW ──────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        # Voice Input Button
        self.btn_mic = QPushButton("🎙️")
        self.btn_mic.setObjectName("btn_mic")
        self.btn_mic.setFixedSize(38, 38)
        self.btn_mic.setToolTip("माइक ऑन/ऑफ करें (Push to Talk)")
        self.btn_mic.clicked.connect(self._toggle_voice_input)
        input_row.addWidget(self.btn_mic)

        # Text input
        self.edit_input = QLineEdit()
        self.edit_input.setPlaceholderText("अपना रिकॉल बोलें या यहाँ टाइप करें...")
        self.edit_input.returnPressed.connect(self._on_send_clicked)
        input_row.addWidget(self.edit_input, stretch=1)

        # Send Button
        self.btn_send = QPushButton("भेजें")
        self.btn_send.setObjectName("btn_send")
        self.btn_send.setFixedHeight(38)
        self.btn_send.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self.btn_send)

        L.addLayout(input_row)

        self._refresh_status_label()

    def _refresh_status_label(self):
        cfg = get_ai_settings()
        m = cfg["model_name"]
        if not cfg["api_key"]:
            self.lbl_status.setText("⚠️ API Key नहीं मिली (⚙️ सेटिंग्स में डालें)")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #F38BA8; font-weight: bold;")
        else:
            self.lbl_status.setText(f"🟢 {m} • तैयार")
            self.lbl_status.setStyleSheet("font-size: 11px; color: #A6ADC8;")

    def set_current_card(self, card: dict, active_box=None, sm2_obj=None):
        """Called automatically whenever the ReviewScreen transitions to a new card."""
        self._current_card = card
        self._active_box = active_box
        deck_name = getattr(self.rs, "deck_name", "") or (card.get("deck_name", "") if card else "")
        self._current_context = build_card_context(card, active_box, deck_name)

        # Reset chat view with welcoming prompt for this card
        q_text = self._current_context.get("question", "")
        if len(q_text) > 80:
            q_text = q_text[:77] + "..."
        welcome_html = f"""
        <div style='color: #A6ADC8; margin-bottom: 12px; font-size: 12px; border-bottom: 1px solid #313244; padding-bottom: 8px;'>
            📌 <b>सक्रिय प्रश्न:</b> {html.escape(q_text)}<br>
            <i>माइक का बटन 🎙️ दबाकर अपना जवाब बोलें, या नीचे से सवाल पूछें।</i>
        </div>
        """
        self.chat_view.setHtml(welcome_html)

        cfg = get_ai_settings()
        if cfg["auto_listen"] and self.isVisible():
            QTimer.singleShot(400, self._start_voice_input)

    def _open_settings(self):
        dlg = AISettingsDialog(self)
        dlg.settings_saved.connect(self._refresh_status_label)
        dlg.exec_()

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
        if self._voice_worker and self._voice_worker.isRunning():
            self._voice_worker.cancel()
        self.hide()

    def update_geometry(self):
        p = self.parentWidget() or self.rs
        if not p:
            return
        dw = getattr(self, "_drawer_width", self.DEFAULT_WIDTH)
        self.setGeometry(p.width() - dw, 0, dw, p.height())

    # ── 5. VOICE INPUT HANDLING ───────────────────────────────────────────────
    def _toggle_voice_input(self):
        if self._is_listening:
            self._stop_voice_input()
        else:
            self._start_voice_input()

    def _start_voice_input(self):
        if self._voice_worker and self._voice_worker.isRunning():
            return
        cfg = get_ai_settings()
        self._is_listening = True
        self.btn_mic.setObjectName("btn_mic_active")
        self.btn_mic.setText("🔴")
        self.btn_mic.setStyleSheet("background: #F38BA8; color: #11111B; font-weight: bold;")
        self.lbl_status.setText("🎙️ सुन रहा हूँ... (बोलिए)")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #F38BA8; font-weight: bold;")

        self._voice_worker = VoiceInputWorker(language=cfg["voice_lang"], phrase_limit=20, parent=self)
        self._voice_worker.listening_audio.connect(lambda: self.lbl_status.setText("🎙️ सुन रहा हूँ... (बोलिए)"))
        self._voice_worker.transcribing_audio.connect(lambda: self.lbl_status.setText("⏳ ट्रांसक्राइब कर रहा हूँ..."))
        self._voice_worker.text_ready.connect(self._on_voice_text_ready)
        self._voice_worker.error_occurred.connect(self._on_voice_error)
        self._voice_worker.finished.connect(self._on_voice_finished)
        self._voice_worker.start()

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
        self._append_system_bubble(err_msg)

    # ── 6. QUERY & CHAT HANDLING ──────────────────────────────────────────────
    def _send_quick_prompt(self, mode: str):
        self._dispatch_ai_query(user_text="", mode=mode)

    def _on_send_clicked(self):
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
        self._worker.finished.connect(lambda: self.btn_send.setEnabled(True))
        self._worker.start()

    def _on_ai_response_ready(self, reply_text: str):
        self._refresh_status_label()
        self._append_ai_bubble(reply_text)

    def _on_ai_error(self, err_msg: str):
        self._refresh_status_label()
        self._append_system_bubble(err_msg)

    def _append_user_bubble(self, text: str):
        esc_text = html.escape(text).replace("\n", "<br>")
        bubble_html = f"""
        <div style='margin-top: 10px; margin-bottom: 10px; text-align: right;'>
            <div style='display: inline-block; background: #313244; color: #CDD6F4; padding: 8px 14px; border-radius: 12px; border-bottom-right-radius: 2px; max-width: 85%; text-align: left;'>
                🗣️ <b>आप:</b><br>{esc_text}
            </div>
        </div>
        """
        self.chat_view.append(bubble_html)
        self._scroll_chat_to_bottom()

    def _append_ai_bubble(self, text: str):
        # Format markdown bold and bullets
        formatted = html.escape(text)
        formatted = formatted.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
        # Bold **text**
        import re
        formatted = re.sub(r'\*\*(.+?)\*\*', r'<b style="color: #CBA6F7;">\1</b>', formatted)
        formatted = formatted.replace("\n", "<br>")

        bubble_html = f"""
        <div style='margin-top: 10px; margin-bottom: 10px;'>
            <div style='background: rgba(203, 166, 247, 0.08); border-left: 3px solid #CBA6F7; color: #CDD6F4; padding: 10px 14px; border-radius: 8px;'>
                🤖 <b>Study Buddy (सहपाठी):</b><br>{formatted}
            </div>
        </div>
        """
        self.chat_view.append(bubble_html)
        self._scroll_chat_to_bottom()

    def _append_system_bubble(self, text: str):
        bubble_html = f"""
        <div style='margin-top: 6px; margin-bottom: 6px;'>
            <div style='background: rgba(243, 139, 168, 0.12); border: 1px solid #F38BA8; color: #F38BA8; padding: 6px 12px; border-radius: 6px; font-size: 12px;'>
                {text.replace("\n", "<br>")}
            </div>
        </div>
        """
        self.chat_view.append(bubble_html)
        self._scroll_chat_to_bottom()

    def _scroll_chat_to_bottom(self):
        sb = self.chat_view.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    # ── 7. RESIZE HANDLING ────────────────────────────────────────────────────
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
                new_w = min(new_w, int(p.width() * 0.75))
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