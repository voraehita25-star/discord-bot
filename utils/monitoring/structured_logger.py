# pyright: reportAttributeAccessIssue=false
"""
Structured Logging Module for Discord Bot.
Provides JSON-formatted logging with context tracking, performance timing, and ELK/monitoring support.

Note: Type checker warnings for dynamic LogRecord attributes are suppressed
because Python's logging module supports adding custom attributes via the extra parameter.

Features:
- JSON-formatted log output for easy parsing
- Request context tracking (user, channel, guild)
- Correlation IDs for request tracing
- Performance timing and metrics
- Log level filtering by module
- Rotating file output
- ELK Stack / Prometheus / Loki compatible
"""

from __future__ import annotations

import collections
import contextvars
import functools
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# Context variable for request tracking
_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("log_context")
_log_context.set({})  # Initialize with empty dict


@dataclass
class LogContext:
    """Context data for structured log entries."""

    request_id: str | None = None
    correlation_id: str | None = None
    user_id: int | None = None
    channel_id: int | None = None
    guild_id: int | None = None
    command: str | None = None
    service: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {k: v for k, v in asdict(self).items() if v is not None and v != {}}
        return result


class StructuredFormatter(logging.Formatter):
    """
    JSON-formatted log formatter with rich context.

    Output format compatible with ELK Stack, Loki, and other log aggregators.
    """

    # Fields to exclude from extra data
    RESERVED_ATTRS = {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "message",
        "context",
        "extra_data",
        "duration_ms",
    }

    def __init__(
        self,
        include_timestamp: bool = True,
        include_hostname: bool = False,
        include_process: bool = False,
        service_name: str = "discord-bot",
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_hostname = include_hostname
        self.include_process = include_process
        self.service_name = service_name

        if include_hostname:
            import socket

            self._hostname = socket.gethostname()
        else:
            self._hostname = None

    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_entry: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Optional timestamp (ISO 8601 format)
        if self.include_timestamp:
            log_entry["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Service identification
        log_entry["service"] = self.service_name

        # Optional hostname
        if self._hostname:
            log_entry["hostname"] = self._hostname

        # Optional process info
        if self.include_process:
            log_entry["process"] = {
                "id": record.process,
                "name": record.processName,
            }

        # Source location
        log_entry["source"] = {
            "file": record.filename,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context from context variable
        ctx = _log_context.get()
        if ctx:
            log_entry["context"] = ctx

        # Add context from record if available
        if hasattr(record, "context") and record.context:
            if "context" not in log_entry:
                log_entry["context"] = {}
            log_entry["context"].update(record.context)

        # Add timing if available
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        # Add extra fields from record
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        # Add any non-reserved extra attributes
        extra_attrs = {}
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                extra_attrs[key] = value

        if extra_attrs:
            if "data" not in log_entry:
                log_entry["data"] = {}
            log_entry["data"].update(extra_attrs)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "stacktrace": self.formatException(record.exc_info),
            }

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter for console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname

        if self.use_colors:
            color = self.COLORS.get(level, "")
            level_str = f"{color}{level:8}{self.RESET}"
        else:
            level_str = f"{level:8}"

        message = record.getMessage()

        # Add context info if available
        ctx = _log_context.get()
        ctx_str = ""
        if ctx:
            parts = []
            if ctx.get("request_id"):
                parts.append(f"req={ctx['request_id'][:8]}")
            if ctx.get("user_id"):
                parts.append(f"user={ctx['user_id']}")
            if parts:
                ctx_str = f" [{', '.join(parts)}]"

        base = f"{timestamp} | {level_str} | {record.name}{ctx_str} | {message}"

        # Add exception if present
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)

        return base


class StructuredLogger:
    """
    Structured logger with context support and correlation tracking.

    Usage:
        logger = StructuredLogger('ai_module')

        # With context manager
        with logger.context(user_id=123, channel_id=456):
            logger.info("Processing request")

        # With correlation ID for request tracing
        with logger.request(user_id=123) as req_id:
            logger.info("Started processing")
            # ... do work ...
            logger.info("Completed")

        # Log structured events
        logger.log_event("ai_response", tokens=500, latency_ms=150)
    """

    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self._context_stack: list[dict[str, Any]] = []

    @contextmanager
    def context(self, **kwargs):
        """Context manager for adding context to log entries."""
        # Push context
        current = _log_context.get().copy()
        current.update(kwargs)
        token = _log_context.set(current)

        try:
            # Only pass known LogContext fields; put the rest in 'extra'
            known_fields = {"request_id", "correlation_id", "user_id", "channel_id", "guild_id", "command", "service"}
            ctx_kwargs = {k: v for k, v in kwargs.items() if k in known_fields}
            extra_kwargs = {k: v for k, v in kwargs.items() if k not in known_fields}
            if extra_kwargs:
                ctx_kwargs["extra"] = extra_kwargs
            yield LogContext(**ctx_kwargs)
        finally:
            _log_context.reset(token)

    @contextmanager
    def request(
        self,
        user_id: int | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
        command: str | None = None,
        **extra,
    ):
        """
        Context manager for request tracking with auto-generated correlation ID.

        Yields the request ID for logging or response headers.
        """
        request_id = str(uuid.uuid4())[:8]

        ctx = {
            "request_id": request_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "guild_id": guild_id,
            "command": command,
            **extra,
        }
        # Remove None values
        ctx = {k: v for k, v in ctx.items() if v is not None}

        with self.context(**ctx):
            yield request_id

    def _log(self, level: int, message: str, **extra) -> None:
        """Internal logging method with context support."""
        record_extra = {}

        # Get context from context variable
        ctx = _log_context.get()
        if ctx:
            record_extra["context"] = ctx

        if extra:
            record_extra["extra_data"] = extra

        # Create log record with extra attributes
        self.logger.log(level, message, extra=record_extra)

    def debug(self, message: str, **extra) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, **extra)

    def info(self, message: str, **extra) -> None:
        """Log info message."""
        self._log(logging.INFO, message, **extra)

    def warning(self, message: str, **extra) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, **extra)

    def error(self, message: str, **extra) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, **extra)

    def log_event(self, event_name: str, **data) -> None:
        """
        Log a structured event with data.

        Args:
            event_name: Name of the event (e.g., 'ai_response', 'cache_hit')
            **data: Event data to include
        """
        self.info(f"Event: {event_name}", event=event_name, **data)

    def log_error_with_context(
        self,
        message: str,
        error: Exception,
        **extra,
    ) -> None:
        """
        Log an error with full exception context.

        Args:
            message: Error message
            error: Exception instance
            **extra: Additional context
        """
        self.logger.error(
            message,
            exc_info=(type(error), error, error.__traceback__),
            extra={
                "extra_data": {
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    **extra,
                }
            },
        )


class PerformanceTimer:
    """
    Context manager for timing code blocks.

    Usage:
        timer = PerformanceTimer()

        with timer.measure("api_call"):
            result = await api_call()

        print(timer.get_timing("api_call"))  # 150.5
    """

    def __init__(self, max_entries: int = 1000):
        self._timings: dict[str, collections.deque[float]] = {}
        self._max_entries = max_entries
        self._current_step: str | None = None
        self._start_time: float = 0

    @contextmanager
    def measure(self, step_name: str):
        """Measure duration of a code block."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            if step_name not in self._timings:
                self._timings[step_name] = collections.deque(maxlen=self._max_entries)
            self._timings[step_name].append(duration_ms)

    def get_timing(self, step_name: str) -> float | None:
        """Get the last timing for a step."""
        timings = self._timings.get(step_name, [])
        return timings[-1] if timings else None

    def get_average(self, step_name: str) -> float | None:
        """Get average timing for a step."""
        timings = self._timings.get(step_name, [])
        return sum(timings) / len(timings) if timings else None

    def get_all_timings(self) -> dict[str, dict[str, float]]:
        """Get statistics for all recorded timings."""
        stats = {}
        for name, times in self._timings.items():
            if times:
                stats[name] = {
                    "count": len(times),
                    "avg_ms": sum(times) / len(times),
                    "min_ms": min(times),
                    "max_ms": max(times),
                    "last_ms": times[-1],
                }
        return stats

    def clear(self) -> None:
        """Clear all recorded timings."""
        self._timings.clear()


def timed(logger: StructuredLogger | None = None):
    """
    Decorator to time function execution.

    Usage:
        @timed(logger)
        async def my_function():
            ...
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                if logger:
                    logger.debug(
                        f"Function {func.__name__} completed",
                        function=func.__name__,
                        duration_ms=round(duration_ms, 2),
                    )

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                if logger:
                    logger.debug(
                        f"Function {func.__name__} completed",
                        function=func.__name__,
                        duration_ms=round(duration_ms, 2),
                    )

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def setup_structured_logging(
    log_file: str | None = None,
    level: int = logging.INFO,
    service_name: str = "discord-bot",
    json_console: bool = False,
    max_file_size_mb: int = 10,
    backup_count: int = 5,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_file: Optional path to JSON log file
        level: Logging level
        service_name: Service name for log entries
        json_console: Use JSON format for console output
        max_file_size_mb: Max size of log file before rotation
        backup_count: Number of backup files to keep
    """
    root_logger = logging.getLogger()

    # Prevent duplicate handlers on re-initialization
    root_logger.handlers.clear()

    # Create formatters
    json_formatter = StructuredFormatter(service_name=service_name)
    human_formatter = HumanReadableFormatter()

    # Configure console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(json_formatter if json_console else human_formatter)
    root_logger.addHandler(console_handler)

    # Configure JSON file handler with rotation
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(level)


def get_correlation_id() -> str | None:
    """Get current correlation/request ID from context."""
    ctx = _log_context.get()
    return ctx.get("request_id") or ctx.get("correlation_id")


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in current context."""
    current = _log_context.get().copy()
    current["correlation_id"] = correlation_id
    _log_context.set(current)


# Convenience function for creating loggers
def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)


def log_ai_request(
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
    **extra,
) -> None:
    """
    Log an AI request with structured data.

    Args:
        user_id: Discord user ID
        channel_id: Discord channel ID
        guild_id: Discord guild ID
        message: User message (truncated for privacy)
        response_length: Length of AI response
        duration_ms: Request duration in milliseconds
        model: AI model used
        tokens_in: Input token count
        tokens_out: Output token count
        error: Error message if request failed
        **extra: Additional data to log
    """
    logger = get_logger("ai_request")

    data = {
        "user_id": user_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
        "response_length": response_length,
        "duration_ms": duration_ms,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "error": error,
        **extra,
    }

    # Remove None values
    data = {k: v for k, v in data.items() if v is not None}

    # Truncate message for privacy
    if message:
        data["message_preview"] = message[:100] + "..." if len(message) > 100 else message

    if error:
        logger.error("AI request failed", **data)
    else:
        logger.info("AI request completed", **data)


# Global timer instance for shared timing
global_timer = PerformanceTimer()
