"""
Fallback Response System for AI Graceful Degradation.
Provides pre-defined responses when API is unavailable or fails.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from enum import Enum

# Try to import intent detector for intent-based fallbacks
try:
    from cogs.ai_core.processing.intent_detector import Intent

    INTENT_AVAILABLE = True
except ImportError:
    INTENT_AVAILABLE = False
    Intent = None  # type: ignore[assignment, misc]

# Try to import circuit breaker to check API status
try:
    from utils.reliability.circuit_breaker import CircuitState, gemini_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False


class FallbackReason(Enum):
    """Reason for using fallback response."""

    API_TIMEOUT = "api_timeout"
    API_ERROR = "api_error"
    CIRCUIT_OPEN = "circuit_open"
    RATE_LIMITED = "rate_limited"
    CONTEXT_TOO_LONG = "context_too_long"
    UNKNOWN = "unknown"


@dataclass
class FallbackResponse:
    """A fallback response with metadata."""

    message: str
    reason: FallbackReason
    should_retry: bool = True
    retry_after_seconds: float | None = None


# Fallback responses by intent (Thai language)
INTENT_FALLBACKS = {
    "greeting": [
        "สวัสดี! ขอโทษที ตอนนี้ระบบกำลังโหลดอยู่ ลองใหม่อีกครั้งนะ 😊",
        "หวัดดี! รอสักครู่นะ ระบบกำลังเตรียมพร้อม",
        "ดีจ้า! ขอเวลาสักครู่นะคะ ระบบกำลังทำงาน",
    ],
    "question": [
        "ขอโทษที ตอนนี้ไม่สามารถตอบคำถามได้ ลองถามใหม่อีกครั้งนะ",
        "ระบบกำลังพักผ่อนสักครู่ ลองใหม่ภายหลังนะ",
        "ขอโทษค่ะ มีปัญหาเล็กน้อย กรุณาถามใหม่อีกครั้ง",
    ],
    "command": [
        "⚠️ ไม่สามารถดำเนินการได้ในขณะนี้ กรุณาลองใหม่ภายหลัง",
        "⚠️ ระบบกำลังพักผ่อน กรุณารอสักครู่แล้วลองใหม่",
    ],
    "roleplay": [
        "*ดูเหมือนว่าจะมีปัญหาเล็กน้อย ขอเวลาสักครู่...*",
        "*หยุดชะงักสักครู่* ...ขอโทษนะ ต้องรอสักพัก",
    ],
    "emotional": [
        "ขอโทษนะ ตอนนี้ไม่สามารถตอบได้ แต่อยากให้รู้ว่าฟังอยู่นะ 💙",
        "เราอยู่ตรงนี้นะ รอสักครู่แล้วมาคุยกัน",
    ],
    "casual": [
        "ขอโทษที ลองใหม่อีกครั้งนะ 😊",
        "มีปัญหาเล็กน้อย รอสักครู่นะ",
        "ระบบกำลังโหลด กรุณาลองใหม่",
    ],
}

# Generic fallback responses by reason
REASON_FALLBACKS = {
    FallbackReason.API_TIMEOUT: [
        "⏳ การตอบกลับใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้ง",
        "⏳ ระบบตอบช้าผิดปกติ กรุณารอสักครู่แล้วลองใหม่",
    ],
    FallbackReason.API_ERROR: [
        "❌ เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้ง",
        "❌ มีปัญหาในการเชื่อมต่อระบบ กรุณารอสักครู่",
    ],
    FallbackReason.CIRCUIT_OPEN: [
        "⏳ ระบบ AI กำลังพักผ่อนสักครู่ กรุณาลองใหม่ในอีก 1 นาที",
        "⏳ ระบบกำลังฟื้นฟู กรุณารอสักครู่แล้วลองใหม่",
    ],
    FallbackReason.RATE_LIMITED: [
        "⏰ คุณส่งข้อความเร็วเกินไป กรุณารอ {seconds:.0f} วินาที",
        "⏰ กรุณารอสักครู่ก่อนส่งข้อความถัดไป",
    ],
    FallbackReason.CONTEXT_TOO_LONG: [
        "📝 บทสนทนายาวเกินไป ลองใช้คำสั่ง reset เพื่อเริ่มใหม่",
        "📝 หน่วยความจำเต็ม กรุณา reset การสนทนา",
    ],
    FallbackReason.UNKNOWN: [
        "ขอโทษที เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง",
        "มีปัญหาเล็กน้อย กรุณาลองใหม่",
    ],
}


class FallbackSystem:
    """
    Manages fallback responses for graceful degradation.

    Usage:
        fallback = FallbackSystem()

        # Get fallback by intent
        response = fallback.get_by_intent("greeting")

        # Get fallback by reason
        response = fallback.get_by_reason(FallbackReason.API_TIMEOUT)

        # Check if fallback should be used
        if fallback.should_use_fallback():
            response = fallback.get_by_reason(FallbackReason.CIRCUIT_OPEN)
    """

    def __init__(self):
        self.logger = logging.getLogger("FallbackSystem")
        self._fallback_count = 0

    def should_use_fallback(self) -> bool:
        """Check if fallback should be used based on circuit breaker state."""
        if CIRCUIT_BREAKER_AVAILABLE:
            return gemini_circuit.state == CircuitState.OPEN
        return False

    def get_by_intent(
        self, intent: str, reason: FallbackReason = FallbackReason.UNKNOWN
    ) -> FallbackResponse:
        """
        Get a fallback response based on detected intent.

        Args:
            intent: Intent string (e.g., 'greeting', 'question')
            reason: Reason for fallback

        Returns:
            FallbackResponse with appropriate message
        """
        intent_key = intent.lower() if isinstance(intent, str) else "casual"

        # Try intent-specific fallback first
        messages = INTENT_FALLBACKS.get(intent_key, INTENT_FALLBACKS["casual"])
        message = random.choice(messages)

        self._fallback_count += 1
        self.logger.info(
            "Using fallback response #%d for intent: %s", self._fallback_count, intent_key
        )

        return FallbackResponse(
            message=message, reason=reason, should_retry=True, retry_after_seconds=5.0
        )

    def get_by_reason(self, reason: FallbackReason, **kwargs) -> FallbackResponse:
        """
        Get a fallback response based on failure reason.

        Args:
            reason: Reason for fallback
            **kwargs: Format arguments (e.g., seconds=30 for rate limit)

        Returns:
            FallbackResponse with appropriate message
        """
        messages = REASON_FALLBACKS.get(reason, REASON_FALLBACKS[FallbackReason.UNKNOWN])
        message = random.choice(messages)

        # Format message with kwargs (provide defaults to avoid raw placeholders)
        try:
            fmt_kwargs = {"seconds": 30}
            fmt_kwargs.update(kwargs)
            message = message.format(**fmt_kwargs)
        except (KeyError, ValueError, IndexError):
            pass  # Leave message as-is if formatting fails

        # Determine retry settings
        should_retry = reason not in {FallbackReason.CONTEXT_TOO_LONG}
        retry_after = {
            FallbackReason.API_TIMEOUT: 5.0,
            FallbackReason.API_ERROR: 10.0,
            FallbackReason.CIRCUIT_OPEN: 60.0,
            FallbackReason.RATE_LIMITED: kwargs.get("seconds", 30.0),
        }.get(reason, 5.0)

        self._fallback_count += 1
        self.logger.info(
            "Using fallback response #%d for reason: %s", self._fallback_count, reason.value
        )

        return FallbackResponse(
            message=message,
            reason=reason,
            should_retry=should_retry,
            retry_after_seconds=retry_after,
        )

    def get_stats(self) -> dict:
        """Get fallback usage statistics."""
        return {
            "total_fallbacks": self._fallback_count,
            "circuit_state": (
                gemini_circuit.state.value if CIRCUIT_BREAKER_AVAILABLE else "unknown"
            ),
        }

    def reset_stats(self) -> None:
        """Reset fallback statistics."""
        self._fallback_count = 0


# Global fallback system instance
fallback_system = FallbackSystem()


def get_fallback_response(
    intent: str | None = None, reason: FallbackReason = FallbackReason.UNKNOWN, **kwargs
) -> str:
    """
    Convenience function to get a fallback response message.

    Args:
        intent: Optional intent for intent-based fallback
        reason: Reason for fallback
        **kwargs: Format arguments

    Returns:
        Fallback message string
    """
    if intent:
        return fallback_system.get_by_intent(intent, reason).message
    return fallback_system.get_by_reason(reason, **kwargs).message
