"""
Structured Logging Module for Discord Bot.
Provides JSON-formatted logging with context tracking and performance timing.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LogContext:
    """Context data for structured log entries."""

    request_id: str | None = None
    user_id: int | None = None
    channel_id: int | None = None
    guild_id: int | None = None
    command: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None and v != {}}


class StructuredFormatter(logging.Formatter):
    """JSON-formatted log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add context if available
        if hasattr(record, "context") and record.context:
            log_entry["context"] = record.context

        # Add timing if available
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class StructuredLogger:
    """
    Structured logger with context support.

    Usage:
        logger = StructuredLogger('ai_module')

        with logger.context(user_id=123, channel_id=456):
            logger.info("Processing request")

        logger.log_event("ai_response", tokens=500, latency_ms=150)
    """

    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self._context: LogContext | None = None

    @contextmanager
    def context(self, **kwargs):
        """Context manager for adding context to log entries."""
        old_context = self._context
        self._context = LogContext(**kwargs)
        try:
            yield self._context
        finally:
            self._context = old_context

    def _log(self, level: int, message: str, **extra) -> None:
        """Internal logging method with context support."""
        record_extra = {}

        if self._context:
            record_extra["context"] = self._context.to_dict()

        if extra:
            record_extra["extra_data"] = extra

        # Use LogRecord with extra attributes
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


class PerformanceTimer:
    """
    Context manager for timing code blocks.

    Usage:
        timer = PerformanceTimer()

        with timer.measure("api_call"):
            result = await api_call()

        print(timer.get_timing("api_call"))  # 150.5
    """

    def __init__(self):
        self._timings: dict[str, list[float]] = {}
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
                self._timings[step_name] = []
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


def setup_structured_logging(log_file: str | None = None, level: int = logging.INFO) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_file: Optional path to JSON log file
        level: Logging level
    """
    # Create JSON formatter
    json_formatter = StructuredFormatter()

    # Configure root logger for JSON output to file
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(json_formatter)
        file_handler.setLevel(level)
        logging.getLogger().addHandler(file_handler)


# Global timer instance for shared timing
global_timer = PerformanceTimer()
