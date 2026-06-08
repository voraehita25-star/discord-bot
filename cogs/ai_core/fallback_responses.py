"""
Fallback Response System for AI Graceful Degradation.
Provides pre-defined responses when API is unavailable or fails.
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

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

    # Track the last few messages shown per (user_id, intent) so the same
    # user doesn't see identical fallback strings on back-to-back errors.
    # Keyed by ``(user_id, intent_key)`` — ``None`` user maps to a single
    # global rotation pool. Bounded with maxlen so the dict only ever holds
    # the recent N entries per key.
    _RECENT_HISTORY_LEN: ClassVar[int] = 3
    # Cap how many distinct (user, intent) pairs we track to keep memory
    # bounded — past this we drop the oldest pair when adding a new one.
    _RECENT_HISTORY_MAX_KEYS: ClassVar[int] = 1000

    def __init__(self):
        self.logger = logging.getLogger("FallbackSystem")
        self._fallback_count = 0
        self._recent: dict[tuple[int | None, str], deque[str]] = defaultdict(
            lambda: deque(maxlen=self._RECENT_HISTORY_LEN),
        )
        # Insertion-order list of keys for LRU-style eviction when over capacity.
        self._recent_order: deque[tuple[int | None, str]] = deque()

    def _remember_fallback(self, key: tuple[int | None, str], message: str) -> None:
        """Record that ``message`` was shown for ``key`` and evict if over capacity."""
        # `key not in self._recent` is the right check, but
        # `self._recent[key].append(...)` below is a defaultdict access that
        # auto-creates the entry — so a key seen before but evicted from
        # `_recent` would NOT trigger the order-list append, leaving it in
        # `_recent_order` only as the prior (now stale) entry. Use explicit
        # contains check + create to keep `_recent_order` in lockstep with
        # `_recent` membership.
        if key not in self._recent:
            self._recent_order.append(key)
            # Bound dict size — drop the oldest tracked pair.
            while len(self._recent_order) > self._RECENT_HISTORY_MAX_KEYS:
                evict = self._recent_order.popleft()
                self._recent.pop(evict, None)
        self._recent[key].append(message)

    def should_use_fallback(self) -> bool:
        """Check if fallback should be used based on circuit breaker state."""
        if CIRCUIT_BREAKER_AVAILABLE:
            return gemini_circuit.state == CircuitState.OPEN
        return False

    def get_by_intent(
        self,
        intent: str,
        reason: FallbackReason = FallbackReason.UNKNOWN,
        user_id: int | None = None,
    ) -> FallbackResponse:
        """
        Get a fallback response based on detected intent.

        Args:
            intent: Intent string (e.g., 'greeting', 'question')
            reason: Reason for fallback
            user_id: Optional user id. When supplied, the same user won't
                see the same fallback twice in a row (we track the last
                ``_RECENT_HISTORY_LEN`` messages per user/intent and pick
                from the unseen pool first).

        Returns:
            FallbackResponse with appropriate message
        """
        intent_key = intent.lower() if isinstance(intent, str) else "casual"

        # Try intent-specific fallback first
        messages = INTENT_FALLBACKS.get(intent_key, INTENT_FALLBACKS["casual"])

        # Filter out anything we've shown this user recently. If the entire
        # pool has been seen (smaller than _RECENT_HISTORY_LEN, or user
        # hammering the same intent), fall back to the full list rather than
        # erroring or returning empty.
        history_key = (user_id, intent_key)
        recent = self._recent.get(history_key)
        if recent:
            available = [m for m in messages if m not in recent]
            if not available:
                available = messages
        else:
            available = messages

        message = random.choice(available)
        self._remember_fallback(history_key, message)

        self._fallback_count += 1
        self.logger.info(
            "Using fallback response #%d for intent: %s", self._fallback_count, intent_key
        )

        return FallbackResponse(
            message=message, reason=reason, should_retry=True, retry_after_seconds=5.0
        )

    def get_by_reason(
        self,
        reason: FallbackReason,
        *,
        user_id: int | None = None,
        **kwargs,
    ) -> FallbackResponse:
        """
        Get a fallback response based on failure reason.

        Args:
            reason: Reason for fallback
            user_id: Optional user id for per-user rotation (avoids showing
                the same message back-to-back to the same user).
            **kwargs: Format arguments (e.g., seconds=30 for rate limit)

        Returns:
            FallbackResponse with appropriate message
        """
        messages = REASON_FALLBACKS.get(reason, REASON_FALLBACKS[FallbackReason.UNKNOWN])

        # Per-user rotation — same scheme as ``get_by_intent``. We rotate by
        # the *raw* template (pre-format) so two requests with different
        # ``seconds=`` kwargs don't both count as the same shown message.
        history_key = (user_id, f"reason:{reason.value}")
        recent = self._recent.get(history_key)
        if recent:
            available = [m for m in messages if m not in recent]
            if not available:
                available = messages
        else:
            available = messages
        message = random.choice(available)
        self._remember_fallback(history_key, message)

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
    intent: str | None = None,
    reason: FallbackReason = FallbackReason.UNKNOWN,
    *,
    user_id: int | None = None,
    **kwargs,
) -> str:
    """
    Convenience function to get a fallback response message.

    Args:
        intent: Optional intent for intent-based fallback
        reason: Reason for fallback
        user_id: Optional user id — passed through to enable per-user
            rotation so the same user doesn't see the same message twice
            in a row.
        **kwargs: Format arguments

    Returns:
        Fallback message string
    """
    if intent:
        return fallback_system.get_by_intent(intent, reason, user_id=user_id).message
    return fallback_system.get_by_reason(reason, user_id=user_id, **kwargs).message
