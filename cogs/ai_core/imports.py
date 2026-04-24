"""Centralized conditional imports for ai_core.

This module consolidates all optional dependencies and provides fallback stubs
when they are not available, ensuring the AI core can run even with missing packages.
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    pass


RecordTokenUsageFn = Callable[[int, int, int, int | None], None]
LogAIRequestFn = Callable[..., None]
AddFeedbackReactionsFn = Callable[[discord.Message], Coroutine[Any, Any, None]]

# ==========================================
# 1. Web & URL Fetching
# ==========================================
try:
    from utils.web.url_fetcher import (
        extract_urls,
        fetch_all_urls,
        format_url_content_for_context,
    )

    URL_FETCHER_AVAILABLE = True
except ImportError:
    URL_FETCHER_AVAILABLE = False

    def extract_urls(text: str) -> list[str]:
        return []

    async def fetch_all_urls(
        urls: list[str], max_urls: int = 3
    ) -> list[tuple[str, str, str | None]]:
        return []

    def format_url_content_for_context(fetched_urls: list[tuple[str, str, str | None]]) -> str:
        return ""

# ==========================================
# 2. AI Enhancements & Processing
# ==========================================
try:
    from .processing.guardrails import (
        is_silent_block,
        is_unrestricted,
        set_unrestricted,
        unrestricted_channels,
        validate_input_for_channel,
        validate_response,
        validate_response_for_channel,
    )

    GUARDRAILS_AVAILABLE = True
except ImportError:
    GUARDRAILS_AVAILABLE = False
    logger.critical(
        "⚠️ GUARDRAILS MODULE UNAVAILABLE — AI responses will NOT be filtered! "
        "Fix the import error in cogs.ai_core.processing.guardrails to restore safety checks."
    )

    _GUARDRAILS_WARNING = "guardrails_unavailable"

    def validate_response(response: str) -> tuple[bool, str, list[str]]:
        # Fail-open: allow responses through but flag them as unvalidated
        # Blocking all responses would cause a self-inflicted DoS
        return True, response, [_GUARDRAILS_WARNING]

    def is_unrestricted(channel_id: int) -> bool:
        return False

    def set_unrestricted(channel_id: int, enabled: bool) -> bool:
        return False

    unrestricted_channels = set()

    def validate_response_for_channel(
        response: str, channel_id: int
    ) -> tuple[bool, str, list[str]]:
        return True, response, [_GUARDRAILS_WARNING]

    def validate_input_for_channel(
        user_input: str, channel_id: int
    ) -> tuple[bool, str, float, list[str]]:
        return True, user_input, 0.0, []

    def is_silent_block(response: str, expected_min_length: int = 50) -> bool:
        return bool(not response or not response.strip())  # Only flag truly empty responses

try:
    from .processing.intent_detector import Intent, detect_intent  # noqa: F401

    INTENT_DETECTOR_AVAILABLE = True
except ImportError:
    INTENT_DETECTOR_AVAILABLE = False

# ==========================================
# 3. Cache & Memory
# ==========================================
try:
    from .cache.analytics import get_ai_stats, log_ai_interaction  # noqa: F401

    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False

try:
    from .cache.ai_cache import ai_cache, context_hasher  # noqa: F401

    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

try:
    from .memory.history_manager import history_manager  # noqa: F401 (re-exported)

    HISTORY_MANAGER_AVAILABLE = True
except ImportError:
    HISTORY_MANAGER_AVAILABLE = False

# ==========================================
# 4. Reliability & Monitoring
# ==========================================
try:
    from utils.reliability.circuit_breaker import gemini_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    gemini_circuit = None  # type: ignore[assignment]

try:
    from utils.monitoring.token_tracker import (
        record_token_usage as _record_token_usage,
        token_tracker,
    )

    TOKEN_TRACKER_AVAILABLE = True
    record_token_usage: RecordTokenUsageFn = _record_token_usage
except ImportError:
    TOKEN_TRACKER_AVAILABLE = False
    token_tracker = None  # type: ignore[assignment]

    def _record_token_usage(
        user_id: int, input_tokens: int, output_tokens: int, channel_id: int | None = None
    ) -> None:
        del user_id, input_tokens, output_tokens, channel_id

    record_token_usage = _record_token_usage

try:
    from .fallback_responses import fallback_system

    FALLBACK_AVAILABLE = True
except ImportError:
    FALLBACK_AVAILABLE = False
    fallback_system = None  # type: ignore[assignment]

try:
    from utils.monitoring.structured_logger import get_logger, log_ai_request as _log_ai_request

    structured_logger = get_logger("ai_logic")
    STRUCTURED_LOGGER_AVAILABLE = True
    log_ai_request: LogAIRequestFn = _log_ai_request
except ImportError:
    STRUCTURED_LOGGER_AVAILABLE = False
    structured_logger = None  # type: ignore[assignment]

    def _log_ai_request(
        user_id: int | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
        message: str | None = None,
        response_length: int | None = None,
        duration_ms: float | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        error: str | None = None,
        **extra: Any,
    ) -> None:
        del (
            user_id,
            channel_id,
            guild_id,
            message,
            response_length,
            duration_ms,
            model,
            tokens_in,
            tokens_out,
            error,
            extra,
        )

    log_ai_request = _log_ai_request

try:
    from utils.monitoring.performance_tracker import perf_tracker

    PERF_TRACKER_AVAILABLE = True
except ImportError:
    PERF_TRACKER_AVAILABLE = False
    perf_tracker = None  # type: ignore[assignment]

try:
    from utils.reliability.error_recovery import (
        GracefulDegradation as _GracefulDegradation,
        service_monitor,
    )

    GracefulDegradation: type[Any] = _GracefulDegradation
    ERROR_RECOVERY_AVAILABLE = True
except ImportError:
    ERROR_RECOVERY_AVAILABLE = False
    service_monitor = None  # type: ignore[assignment]

    class _FallbackGracefulDegradation:
        """Fallback stub for GracefulDegradation."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        async def __aenter__(self) -> _FallbackGracefulDegradation:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            del args
            return False

    GracefulDegradation = _FallbackGracefulDegradation

try:
    from utils.monitoring.feedback import (
        add_feedback_reactions as _add_feedback_reactions,
        feedback_collector,
    )

    FEEDBACK_AVAILABLE = True
    add_feedback_reactions: AddFeedbackReactionsFn = _add_feedback_reactions
except ImportError:
    FEEDBACK_AVAILABLE = False
    feedback_collector = None  # type: ignore[assignment]

    async def _add_feedback_reactions(message: discord.Message) -> None:
        del message

    add_feedback_reactions = _add_feedback_reactions

# ==========================================
# 5. Localization
# ==========================================
try:
    from utils.localization import msg, msg_en

    LOCALIZATION_AVAILABLE = True
except ImportError:
    LOCALIZATION_AVAILABLE = False

    def msg(key: str, **kwargs: Any) -> str:
        return key

    def msg_en(key: str, **kwargs: Any) -> str:
        return key

