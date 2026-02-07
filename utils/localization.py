# pylint: disable=line-too-long
"""
Localization Module for Discord Bot.
Provides centralized multi-language message management (Thai/English).
"""

from __future__ import annotations

import contextlib
import logging
from enum import Enum


class Language(Enum):
    """Supported languages."""

    THAI = "th"
    ENGLISH = "en"


# Default language
DEFAULT_LANGUAGE = Language.THAI


# Message definitions by category
MESSAGES = {
    # ==================== AI System Messages ====================
    "ai_busy": {
        "th": "⏳ ระบบ AI กำลังพักผ่อนสักครู่ กรุณาลองใหม่อีกครั้งในอีก 1 นาที",
        "en": "⏳ AI system is taking a short break. Please try again in 1 minute",
    },
    "ai_error": {
        "th": "❌ เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้ง",
        "en": "❌ Processing error occurred. Please try again",
    },
    "ai_context_cleared": {
        "th": "🗑️ ล้างบริบทการสนทนาแล้ว เริ่มต้นใหม่!",
        "en": "🗑️ Conversation context cleared. Starting fresh!",
    },
    "ai_thinking_on": {
        "th": "🧠 เปิดโหมดคิดวิเคราะห์แล้ว",
        "en": "🧠 Thinking mode enabled",
    },
    "ai_thinking_off": {
        "th": "⚡ ปิดโหมดคิดวิเคราะห์แล้ว (ตอบเร็วขึ้น)",
        "en": "⚡ Thinking mode disabled (faster responses)",
    },
    "ai_streaming_on": {
        "th": "📡 เปิดโหมด Streaming แล้ว",
        "en": "📡 Streaming mode enabled",
    },
    "ai_streaming_off": {
        "th": "📝 ปิดโหมด Streaming แล้ว",
        "en": "📝 Streaming mode disabled",
    },
    "ai_rate_limited": {
        "th": "⏰ คุณส่งข้อความเร็วเกินไป กรุณารอสักครู่",
        "en": "⏰ You're sending messages too quickly. Please wait a moment",
    },
    # ==================== Voice/Music Messages ====================
    "voice_not_connected": {
        "th": "❌ Bot ไม่ได้อยู่ในห้องเสียง",
        "en": "❌ Bot is not in a voice channel",
    },
    "voice_user_not_connected": {
        "th": "❌ คุณต้องอยู่ในห้องเสียงก่อน",
        "en": "❌ You must be in a voice channel first",
    },
    "voice_joined": {
        "th": "✅ เข้าไปรอใน **{channel}** แล้ว",
        "en": "✅ Joined **{channel}**",
    },
    "voice_left": {
        "th": "✅ ออกจาก **{channel}** แล้ว",
        "en": "✅ Left **{channel}**",
    },
    "music_no_track": {
        "th": "❌ ไม่มีเพลงให้{action}",
        "en": "❌ No track to {action}",
    },
    "music_paused": {
        "th": "⏸️ หยุดชั่วคราว",
        "en": "⏸️ Paused",
    },
    "music_resumed": {
        "th": "▶️ เล่นต่อ",
        "en": "▶️ Resumed",
    },
    "music_skipped": {
        "th": "⏭️ ข้ามเพลง",
        "en": "⏭️ Skipped",
    },
    "music_stopped": {
        "th": "⏹️ หยุดเล่นและล้างคิวแล้ว",
        "en": "⏹️ Stopped and cleared queue",
    },
    "music_loop_on": {
        "th": "🔁 เปิดโหมดวนซ้ำ",
        "en": "🔁 Loop mode enabled",
    },
    "music_loop_off": {
        "th": "➡️ ปิดโหมดวนซ้ำ",
        "en": "➡️ Loop mode disabled",
    },
    "music_queue_empty": {
        "th": "📭 คิวว่างเปล่า",
        "en": "📭 Queue is empty",
    },
    "music_added_to_queue": {
        "th": "✅ เพิ่ม **{title}** ลงคิวแล้ว",
        "en": "✅ Added **{title}** to queue",
    },
    # ==================== Permission Messages ====================
    "no_permission": {
        "th": "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
        "en": "❌ You don't have permission to use this command",
    },
    "owner_only": {
        "th": "❌ คำสั่งนี้สำหรับเจ้าของบอทเท่านั้น",
        "en": "❌ This command is for the bot owner only",
    },
    "missing_args": {
        "th": "❌ ขาดข้อมูลที่จำเป็น: {args}",
        "en": "❌ Missing required arguments: {args}",
    },
    # ==================== General Messages ====================
    "success": {
        "th": "✅ สำเร็จ",
        "en": "✅ Success",
    },
    "error": {
        "th": "❌ เกิดข้อผิดพลาด",
        "en": "❌ An error occurred",
    },
    "loading": {
        "th": "⏳ กำลังโหลด...",
        "en": "⏳ Loading...",
    },
    "processing": {
        "th": "⚙️ กำลังประมวลผล...",
        "en": "⚙️ Processing...",
    },
    "invalid_input": {
        "th": "❌ ข้อมูลไม่ถูกต้อง",
        "en": "❌ Invalid input",
    },
    "not_found": {
        "th": "❌ ไม่พบ {item}",
        "en": "❌ {item} not found",
    },
    "cooldown": {
        "th": "⏰ กรุณารอ {seconds:.1f} วินาที",
        "en": "⏰ Please wait {seconds:.1f} seconds",
    },
    # ==================== Memory System ====================
    "memory_saved": {
        "th": "💾 บันทึกความทรงจำแล้ว",
        "en": "💾 Memory saved",
    },
    "memory_cleared": {
        "th": "🗑️ ล้างความทรงจำแล้ว",
        "en": "🗑️ Memory cleared",
    },
    "history_exported": {
        "th": "📤 ส่งออกประวัติแล้ว ({count} ข้อความ)",
        "en": "📤 History exported ({count} messages)",
    },
}


def get_message(key: str, lang: Language = DEFAULT_LANGUAGE, **kwargs) -> str:
    """
    Get a localized message by key.

    Args:
        key: Message key (e.g., 'ai_busy')
        lang: Language to use (default: Thai)
        **kwargs: Format arguments for the message

    Returns:
        Localized message string
    """
    if key not in MESSAGES:
        return f"[Missing message: {key}]"

    lang_code = lang.value if isinstance(lang, Language) else lang
    msg_dict = MESSAGES[key]

    # Fallback to Thai if language not found
    message = msg_dict.get(lang_code, msg_dict.get("th", f"[{key}]"))

    # Format with kwargs if provided
    if kwargs:
        with contextlib.suppress(KeyError):
            message = message.format(**kwargs)

    return message


def msg(key: str, **kwargs) -> str:
    """Shorthand for get_message with default Thai language."""
    return get_message(key, DEFAULT_LANGUAGE, **kwargs)


def msg_en(key: str, **kwargs) -> str:
    """Shorthand for get_message with English language."""
    return get_message(key, Language.ENGLISH, **kwargs)


class LocalizedMessages:
    """
    Class-based interface for accessing localized messages.

    Usage:
        messages = LocalizedMessages(Language.THAI)
        print(messages.ai_busy)
        print(messages.get('voice_joined', channel='General'))
    """

    def __init__(self, lang: Language = DEFAULT_LANGUAGE):
        self.lang = lang

    def get(self, key: str, **kwargs) -> str:
        """Get a message with optional formatting."""
        return get_message(key, self.lang, **kwargs)

    def __getattr__(self, key: str) -> str:
        """Allow attribute-style access to messages."""
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in MESSAGES:
            logging.warning("Localization key not found: %s", key)
        return self.get(key)


# Pre-initialized message instances
thai_messages = LocalizedMessages(Language.THAI)
english_messages = LocalizedMessages(Language.ENGLISH)
