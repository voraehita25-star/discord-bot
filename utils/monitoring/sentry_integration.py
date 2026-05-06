"""
Sentry Error Tracking Integration
Provides automatic error tracking and performance monitoring.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import os
from collections.abc import Callable
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
        # NOTE: We deliberately raise the breadcrumb capture level to WARNING.
        # Sentry's LoggingIntegration installs its OWN handler that does NOT
        # honor the SensitiveDataFilter on the project's main handlers, so any
        # INFO-level log line containing a Discord token, API key, or other
        # secret would otherwise be sent as a breadcrumb on the next captured
        # exception. The before_breadcrumb hook below is a defense-in-depth
        # second pass that runs the same redaction regex.
        logging_integration = LoggingIntegration(
            level=logging.WARNING,  # Capture WARNING and above as breadcrumbs
            event_level=logging.ERROR,  # Send errors as events
        )

        # Lazy import to avoid a hard dependency on logger module shape during
        # init failure modes.
        _redact_sensitive: Callable[[str], str] | None
        try:
            from utils.monitoring.logger import _redact_sensitive as _redact_fn

            _redact_sensitive = _redact_fn
        except Exception:  # pragma: no cover - defense in depth
            _redact_sensitive = None

        def _scrub_breadcrumb(
            crumb: dict[str, Any], _hint: dict[str, Any]
        ) -> dict[str, Any] | None:
            if _redact_sensitive is None:
                return crumb
            try:
                msg = crumb.get("message")
                if isinstance(msg, str):
                    crumb["message"] = _redact_sensitive(msg)
                data = crumb.get("data")
                if isinstance(data, dict):
                    for k, v in list(data.items()):
                        if isinstance(v, str):
                            data[k] = _redact_sensitive(v)
            except Exception:
                # Never let scrubbing crash the client — drop the crumb instead.
                return None
            return crumb

        def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
            """Strip frame-local variables from stacktraces.

            ``attach_stacktrace=True`` plus the SDK default of capturing
            local variables means a single ``logger.warning(...)`` can ship
            a stack frame containing API keys / tokens / DB rows to Sentry.
            We walk the event's exception chain + threads and clear the
            ``vars`` dict on every frame; we also re-redact the top-level
            message in case anything slipped past the breadcrumb hook.
            """
            try:
                if _redact_sensitive is not None:
                    msg = event.get("message")
                    if isinstance(msg, str):
                        event["message"] = _redact_sensitive(msg)

                def _scrub_stack(stack: dict[str, Any]) -> None:
                    frames = stack.get("frames") or []
                    for frame in frames:
                        if isinstance(frame, dict):
                            # Drop locals; they're the prime exfil vector.
                            frame.pop("vars", None)

                for exc in (event.get("exception") or {}).get("values") or []:
                    stack = exc.get("stacktrace")
                    if isinstance(stack, dict):
                        _scrub_stack(stack)
                for thread in (event.get("threads") or {}).get("values") or []:
                    stack = thread.get("stacktrace")
                    if isinstance(stack, dict):
                        _scrub_stack(stack)
            except Exception:
                # Failing to scrub must not poison legitimate events; drop instead.
                return None
            return event

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
            # Locals get scrubbed in before_send — explicitly disable here
            # too so any SDK that respects it skips capture entirely.
            include_local_variables=False,
            before_breadcrumb=_scrub_breadcrumb,
            before_send=_scrub_event,
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
        with sentry_sdk.new_scope() as scope:
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
        with sentry_sdk.new_scope() as scope:
            if context:
                for key, value in context.items():
                    scope.set_extra(key, value)

            return sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]

    except Exception as e:
        logger.debug("Failed to capture message to Sentry: %s", e)
        return None


def set_user_context(user_id: int, username: str | None = None) -> None:
    """Set user context on Sentry's ISOLATION scope (per-task).

    The previous implementation called ``sentry_sdk.set_user`` directly,
    which writes to the global scope. The docstring promised isolation
    but the code didn't deliver — every subsequent unrelated event in
    the same process inherited whichever user was set last, including
    background tasks that touched no Discord user at all.

    This now writes to the current isolation scope so the binding is
    confined to the task that called it. Callers who need true
    fire-and-forget global tagging should use ``set_user_global``.
    """
    if not SENTRY_AVAILABLE:
        return
    payload = {"id": str(user_id), "username": username}
    # Newer sentry_sdk exposes get_isolation_scope(); fall back gracefully.
    get_iso = getattr(sentry_sdk, "get_isolation_scope", None)
    if callable(get_iso):
        try:
            get_iso().set_user(payload)
            return
        except Exception:
            logger.debug("isolation_scope unavailable; falling back to global")
    sentry_sdk.set_user(payload)


def set_user_global(user_id: int, username: str | None = None) -> None:
    """Set user on the GLOBAL Sentry scope. Use for process-wide tagging only."""
    if not SENTRY_AVAILABLE:
        return
    sentry_sdk.set_user({"id": str(user_id), "username": username})


def add_breadcrumb(
    message: str, category: str = "custom", level: str = "info", data: dict | None = None
) -> None:
    """Add a breadcrumb for debugging context."""
    if SENTRY_AVAILABLE:
        sentry_sdk.add_breadcrumb(message=message, category=category, level=level, data=data or {})
