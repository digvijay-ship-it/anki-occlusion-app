"""
AI Coach Service for Anki Occlusion.
Provides Socratic peer study buddy capabilities using Google Gemini (default: gemini-2.0-flash).
Extracts card context, evaluates student recall, highlights missing SSC exam traps,
and provides cross-subject mnemonics in natural Hindi / Hinglish.
"""

import json
import re
import html
import requests
from PyQt5.QtCore import QThread, pyqtSignal, QSettings


SETTINGS_GROUP = "AnkiOcclusion"
SETTINGS_SECTION = "AISettings"
KEY_API_KEY = "gemini_api_key"
KEY_MODEL_NAME = "gemini_model_name"
KEY_AUTO_LISTEN = "auto_listen_enabled"
KEY_VOICE_LANG = "voice_language"

DEFAULT_MODEL = "gemini-2.0-flash"
FALLBACK_MODEL = "gemini-1.5-flash"


def get_ai_settings():
    s = QSettings(SETTINGS_GROUP, SETTINGS_SECTION)
    api_key = s.value(KEY_API_KEY, "", type=str)
    model_name = s.value(KEY_MODEL_NAME, DEFAULT_MODEL, type=str)
    auto_listen = s.value(KEY_AUTO_LISTEN, False, type=bool)
    voice_lang = s.value(KEY_VOICE_LANG, "hi-IN", type=str)
    return {
        "api_key": api_key.strip() if api_key else "",
        "model_name": model_name.strip() if model_name else DEFAULT_MODEL,
        "auto_listen": auto_listen,
        "voice_lang": voice_lang or "hi-IN",
    }


def save_ai_settings(api_key: str = None, model_name: str = None, auto_listen: bool = None, voice_lang: str = None):
    s = QSettings(SETTINGS_GROUP, SETTINGS_SECTION)
    if api_key is not None:
        s.setValue(KEY_API_KEY, str(api_key).strip())
    if model_name is not None:
        s.setValue(KEY_MODEL_NAME, str(model_name).strip())
    if auto_listen is not None:
        s.setValue(KEY_AUTO_LISTEN, bool(auto_listen))
    if voice_lang is not None:
        s.setValue(KEY_VOICE_LANG, str(voice_lang).strip())


def strip_html_tags(text: str) -> str:
    """Strip HTML markup to pass clean text to the AI model."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return text.strip()


def build_card_context(card: dict, active_box=None, deck_name: str = "") -> dict:
    """
    Extracts high-fidelity context from Text, MCQ, or Occlusion cards
    to supply to the Socratic AI Study Buddy.
    """
    if not card:
        return {"summary": "No active card context."}

    card_type = card.get("card_type", "")
    context_anchor = card.get("context_anchor", "")
    tags = card.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    ctx = {
        "deck_name": deck_name or card.get("deck_name", ""),
        "card_type": card_type,
        "topic_anchor": context_anchor,
        "tags": tags,
    }

    if card_type == "mcq":
        ctx["question"] = strip_html_tags(card.get("question", ""))
        options_raw = card.get("options", [])
        opts_list = []
        for opt in options_raw:
            if isinstance(opt, dict):
                lbl = opt.get("label", "")
                txt = opt.get("text", "")
                eng = opt.get("english_word", "")
                hnd = opt.get("hindi", "")
                opts_list.append(f"{lbl}: {txt} {f'({eng})' if eng else ''} {f'- {hnd}' if hnd else ''}".strip())
            else:
                opts_list.append(str(opt))
        ctx["options"] = opts_list
        ctx["correct_answer"] = card.get("correct_option", "")
        sol_data = card.get("solution_data", {})
        if isinstance(sol_data, dict):
            ctx["solution_statement"] = strip_html_tags(sol_data.get("statement", ""))
            ctx["key_points"] = strip_html_tags(sol_data.get("key_points", ""))
            ctx["additional_info"] = strip_html_tags(sol_data.get("additional_information", ""))
        ctx["notes"] = strip_html_tags(card.get("notes", "") or card.get("note", ""))

    elif card_type == "text":
        ctx["question"] = strip_html_tags(card.get("question", ""))
        ctx["answer"] = strip_html_tags(card.get("answer", ""))
        ctx["notes"] = strip_html_tags(card.get("notes", "") or card.get("note", ""))
        if card.get("mnemonics"):
            ctx["mnemonic"] = strip_html_tags(card.get("mnemonics"))
        if card.get("related_concepts"):
            ctx["related_concepts"] = card.get("related_concepts")

    else:
        # Occlusion / Image / PDF
        box_note = ""
        box_label = ""
        if active_box:
            if isinstance(active_box, dict):
                box_note = active_box.get("note", "") or active_box.get("notes", "")
                box_label = active_box.get("label", "")
            else:
                box_note = getattr(active_box, "note", "") or getattr(active_box, "notes", "")
                box_label = getattr(active_box, "label", "")
        ctx["question"] = f"Masked Target Box: {box_label}" if box_label else "Image/PDF Occlusion Question"
        ctx["answer"] = strip_html_tags(box_note) if box_note else "Check underlying image note."
        ctx["card_notes"] = strip_html_tags(card.get("notes", "") or card.get("note", ""))

    return ctx


SOCRATIC_SYSTEM_PROMPT = """You are "Study Buddy" (सहपाठी), an ultra-smart, encouraging, and witty peer study partner helping the student prepare for India's premier government exams (SSC CGL, CHSL, MTS, CPO, NTPC, Railways).

Your Persona:
- You speak exclusively in natural, friendly, spoken Hindi (Devanagari script with natural English/Hinglish keywords like "Recall", "Trap", "Fact", "Option", "Rule").
- You are NOT a stiff professor or textbook bot. You talk like an energetic, brilliant peer sitting across the study desk.
- Keep responses SHARP, CONCISE, and PUNCHY (max 3-5 sentences total). The student is actively reviewing flashcards; do not waste their study time with long essays.

Your 3-Part Evaluation Protocol when the student shares their recall/explanation:
1. 🟢 **प्रशंसा व सही हिस्से (Affirmation)**: Validate what the student recalled correctly (e.g. "शाबाश भाई! बिल्कुल सही पकड़ा...").
2. ⚠️ **छूटे हुए की-पॉइंट्स व SSC ट्रैप्स (Missing Crucial Trap Points)**: Point out 1-2 exact syllabus keywords, years, numbers, or examiner traps they missed.
3. 💡 **मेमोरी एंकर / चुटीला कनेक्ट (Mnemonic / Hook)**: Give a fast 1-sentence mental trick or cross-subject link to lock it in forever.

If the student asks a random doubt (even outside the card, e.g. "सबसे पहले कौन विदेशी आए थे?"):
- Answer directly and instantly with sharp facts, dates, and exam mnemonics.

Formatting: Use clean bullets (•), emojis (🟢, ⚠️, 💡), and bold text (**...**) for instant readability. Zero markdown fluff."""


class AICoachWorker(QThread):
    """
    Non-blocking background worker to execute Socratic AI requests via Gemini REST API.
    """
    started_query = pyqtSignal()
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, card_context: dict, user_message: str, prompt_mode: str = "recall", parent=None):
        super().__init__(parent)
        self.card_context = card_context
        self.user_message = user_message.strip() if user_message else ""
        self.prompt_mode = prompt_mode

    def run(self):
        self.started_query.emit()
        cfg = get_ai_settings()
        api_key = cfg["api_key"]
        model_name = cfg["model_name"] or DEFAULT_MODEL

        if not api_key:
            self.error_occurred.emit(
                "⚠️ **Gemini API Key missing!**\n\n"
                "कृपया ड्रॉअर में ऊपर ⚙️ सेटिंग्स बटन पर क्लिक करके अपनी मुफ़्त Google Gemini API Key दर्ज करें।"
            )
            return

        card_dump = json.dumps(self.card_context, ensure_ascii=False, indent=2)

        if self.prompt_mode == "trap":
            prompt_text = (
                f"Active Card Context:\n```json\n{card_dump}\n```\n\n"
                "User says: 'इस सवाल में SSC का मुख्य ट्रैप और सबसे ज़्यादा कन्फ़्यूज़िंग पॉइंट क्या है? समझाओ!'"
            )
        elif self.prompt_mode == "mnemonic":
            prompt_text = (
                f"Active Card Context:\n```json\n{card_dump}\n```\n\n"
                "User says: 'इस सवाल और इसके कॉन्सेप्ट को याद रखने की एक मज़ेदार और कभी न भूलने वाली ट्रिक/मेमोरी एंकर बताओ!'"
            )
        elif self.prompt_mode == "connect":
            prompt_text = (
                f"Active Card Context:\n```json\n{card_dump}\n```\n\n"
                "User says: 'इस सवाल को दूसरे SSC विषयों (History, Polity, Geography, Economics, Static GK) से 360° लिंक करके बताओ!'"
            )
        else:
            prompt_text = (
                f"Active Card Context:\n```json\n{card_dump}\n```\n\n"
                f"Student's Recall / Question:\n\"{self.user_message or 'मैंने यह कार्ड देखा, इसके मुख्य पॉइंट्स पर मुझसे चर्चा करो!'}\""
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_text}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": SOCRATIC_SYSTEM_PROMPT}]
            },
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 600
            }
        }

        try:
            resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    first_cand = candidates[0]
                    content = first_cand.get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        reply_text = parts[0].get("text", "").strip()
                        self.response_ready.emit(reply_text)
                        return
                self.error_occurred.emit("⚠️ AI ने कोई जवाब नहीं भेजा। कृपया दोबारा प्रयास करें।")
            elif resp.status_code == 400:
                err_data = resp.json().get("error", {})
                msg = err_data.get("message", "Invalid request")
                if "model" in msg.lower() and model_name == DEFAULT_MODEL:
                    fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/{FALLBACK_MODEL}:generateContent?key={api_key}"
                    resp2 = requests.post(fallback_url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
                    if resp2.status_code == 200:
                        data2 = resp2.json()
                        parts2 = data2.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        if parts2:
                            self.response_ready.emit(parts2[0].get("text", "").strip())
                            return
                self.error_occurred.emit(f"⚠️ **Google API Error (400):** {msg}")
            elif resp.status_code == 403:
                self.error_occurred.emit("⚠️ **Invalid API Key (403):** कृपया ⚙️ सेटिंग्स में अपनी सही Gemini API Key चेक करें।")
            elif resp.status_code == 429:
                self.error_occurred.emit("⏳ **Rate Limit Exceeded (429):** कृपया कुछ सेकंड इंतज़ार करके दोबारा पूछें।")
            else:
                self.error_occurred.emit(f"⚠️ **API Error ({resp.status_code}):** {resp.text[:150]}")
        except requests.exceptions.Timeout:
            self.error_occurred.emit("⏱️ **रिक्वेस्ट टाइमआउट:** सर्वर से जवाब आने में 15 सेकंड से अधिक समय लग गया। कृपया इंटरनेट कनेक्शन जांचें।")
        except requests.exceptions.ConnectionError:
            self.error_occurred.emit("🌐 **इंटरनेट कनेक्शन नहीं मिला:** कृपया अपना इंटरनेट चालू करें।")
        except Exception as e:
            self.error_occurred.emit(f"⚠️ **अज्ञात त्रुटि:** {str(e)}")