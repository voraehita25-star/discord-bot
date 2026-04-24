"""
Sentry Error Tracking Integration
Provides automatic error tracking and performance monitoring.
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
import os
from typing import Any

# Try to import Sentry
try:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    logger.warning("⚠️ Sentry SDK not installed - error tracking disabled")


def init_sentry(
    dsn: str | None = None,
    environment: str = "production",
    release: str | None = None,
    sample_rate: float = 1.0,
    traces_sample_rate: float = 0.1,
) -> bool:
    """Initialize Sentry error tracking.

    Args:
        dsn: Sentry DSN (Data Source Name). If None, uses SENTRY_DSN env var.
        environment: Environment name (production, staging, development).
        release: Release version string.
        sample_rate: Error sampling rate (0.0-1.0).
        traces_sample_rate: Performance tracing rate (0.0-1.0).

    Returns:
        True if initialized successfully.
    """
    if not SENTRY_AVAILABLE:
        return False

    # Telemetry opt-out: the dashboard writes `data/telemetry_optout.flag` when
    # the user turns off "Send anonymous crash reports" (#35). We honor it
    # here so Sentry never initializes on an opted-out install. The flag is a
    # file (not env var) so it survives shell restarts and is obvious to
    # audit — you can `rm data/telemetry_optout.flag` to re-enable.
    try:
        from pathlib import Path as _P
        if (_P("data") / "telemetry_optout.flag").exists():
            logger.info("🛡️ Sentry disabled by user (telemetry_optout.flag present)")
            return False
    except Exception:
        # File access failures shouldn't block Sentry init — fall through.
        pass

    # Get DSN from env if not provided
    dsn = dsn or os.getenv("SENTRY_DSN")

    if not dsn:
        logger.info("ℹ️ Sentry DSN not configured - skipping initialization")
        return False

    try:
        # Configure logging integration
        logging_integration = LoggingIntegration(
            level=logging.INFO,  # Capture INFO and above as breadcrumbs
            event_level=logging.ERROR,  # Send errors as events
        )

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            sample_rate=sample_rate,
            traces_sample_rate=traces_sample_rate,
            integrations=[logging_integration],
            # Don't send PII
            send_default_pii=False,
            # Attach stacktrace to messages
            attach_stacktrace=True,
        )

        logger.info(
            "🛡️ Sentry initialized: env=%s, errors=%.0f%%, traces=%.0f%%",
            environment,
            sample_rate * 100,
            traces_sample_rate * 100,
        )
        return True

    except Exception:
        logger.exception("Failed to initialize Sentry")
        return False


def capture_exception(
    error: Exception,
    context: dict[str, Any] | None = None,
    user_id: int | None = None,
    guild_id: int | None = None,
) -> str | None:
    """Capture an exception with additional context.

    Args:
        error: The exception to capture.
        context: Additional context data.
        user_id: Discord user ID.
        guild_id: Discord guild ID.

    Returns:
        Sentry event ID if captured, None otherwise.
    """
    if not SENTRY_AVAILABLE:
        return None

    try:
        with sentry_sdk.push_scope() as scope:
            # Add user context
            if user_id:
                scope.set_user({"id": str(user_id)})

            # Add tags
            if guild_id:
                scope.set_tag("guild_id", str(guild_id))

            # Add extra context
            if context:
                for key, value in context.items():
                    scope.set_extra(key, value)

            return sentry_sdk.capture_exception(error)

    except Exception as e:
        logger.debug("Failed to capture exception to Sentry: %s", e)
        return None


def capture_message(
    message: str, level: str = "info", context: dict[str, Any] | None = None
) -> str | None:
    """Capture a message to Sentry.

    Args:
        message: The message to capture.
        level: Message level (debug, info, warning, error, fatal).
        context: Additional context data.

    Returns:
        Sentry event ID if captured, None otherwise.
    """
    if not SENTRY_AVAILABLE:
        return None

    try:
        with sentry_sdk.push_scope() as scope:
            if context:
                for key, value in context.items():
                    scope.set_extra(key, value)

            return sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]

    except Exception as e:
        logger.debug("Failed to capture message to Sentry: %s", e)
        return None


def set_user_context(user_id: int, username: str | None = None) -> None:
    """Set user context for subsequent events."""
    if SENTRY_AVAILABLE:
        sentry_sdk.set_user({"id": str(user_id), "username": username})


def add_breadcrumb(
    message: str, category: str = "custom", level: str = "info", data: dict | None = None
) -> None:
    """Add a breadcrumb for debugging context."""
    if SENTRY_AVAILABLE:
        sentry_sdk.add_breadcrumb(message=message, category=category, level=level, data=data or {})
