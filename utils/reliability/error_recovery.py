"""
Error Recovery Module for Discord Bot.
Provides retry logic and graceful degradation utilities.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        recoverable_errors: tuple = (Exception,),
    ):
        """
        Initialize retry configuration.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries in seconds
            max_delay: Maximum delay between retries
            exponential_base: Base for exponential backoff
            jitter: Add random jitter to prevent thundering herd
            recoverable_errors: Tuple of exception types to retry on
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.recoverable_errors = recoverable_errors


# Preset configurations for common scenarios
RETRY_AGGRESSIVE = RetryConfig(max_retries=5, base_delay=0.5, max_delay=10.0)
RETRY_STANDARD = RetryConfig(max_retries=3, base_delay=1.0, max_delay=30.0)
RETRY_CONSERVATIVE = RetryConfig(max_retries=2, base_delay=2.0, max_delay=60.0)


async def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for retry attempt with optional jitter."""
    import random

    delay = min(
        config.base_delay * (config.exponential_base**attempt),
        config.max_delay,
    )

    if config.jitter:
        # Add 0-50% jitter
        delay *= 1.0 + random.random() * 0.5

    return delay


async def retry_async(
    func: Callable,
    *args,
    config: RetryConfig | None = None,
    fallback: Any = None,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs,
) -> Any:
    """
    Execute an async function with automatic retry on failure.

    Args:
        func: Async function to execute
        *args: Positional arguments for the function
        config: Retry configuration
        fallback: Value to return if all retries fail
        on_retry: Callback called on each retry with (attempt, error)
        **kwargs: Keyword arguments for the function

    Returns:
        Function result or fallback value

    Example:
        result = await retry_async(
            fetch_data,
            url,
            config=RETRY_AGGRESSIVE,
            fallback=default_data,
        )
    """
    if config is None:
        config = RETRY_STANDARD

    last_error = None
    logger = logging.getLogger("ErrorRecovery")

    for attempt in range(config.max_retries):
        try:
            return await func(*args, **kwargs)
        except config.recoverable_errors as e:
            last_error = e

            if on_retry:
                on_retry(attempt + 1, e)

            if attempt < config.max_retries - 1:
                delay = await calculate_delay(attempt, config)
                logger.warning(
                    "⚠️ Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    config.max_retries,
                    str(e)[:100],
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "❌ All %d attempts failed for %s: %s",
                    config.max_retries,
                    func.__name__,
                    str(e)[:200],
                )

    # All retries failed
    if fallback is not None:
        logger.info("📦 Using fallback value after retries exhausted")
        return fallback

    raise last_error


def with_retry(
    config: RetryConfig | None = None,
    fallback: Any = None,
):
    """
    Decorator to add automatic retry to async functions.

    Usage:
        @with_retry(config=RETRY_AGGRESSIVE)
        async def fetch_data(url):
            return await http_get(url)

        @with_retry(fallback=[])
        async def get_items():
            return await db.get_items()
    """
    if config is None:
        config = RETRY_STANDARD

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_async(
                func,
                *args,
                config=config,
                fallback=fallback,
                **kwargs,
            )

        return wrapper

    return decorator


class GracefulDegradation:
    """
    Context manager for graceful degradation.

    Usage:
        async with GracefulDegradation(fallback="default") as gd:
            result = await risky_operation()

        # If exception occurred, result will be "default"
        final_result = gd.result if gd.success else gd.fallback
    """

    def __init__(
        self,
        fallback: Any = None,
        log_errors: bool = True,
        suppress_errors: tuple = (Exception,),
    ):
        self.fallback = fallback
        self.log_errors = log_errors
        self.suppress_errors = suppress_errors
        self.success = False
        self.result = None
        self.error = None
        self.logger = logging.getLogger("GracefulDegradation")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error = exc_val
            self.result = self.fallback

            if self.log_errors and issubclass(exc_type, self.suppress_errors):
                self.logger.warning(
                    "🔄 Graceful degradation activated: %s. Using fallback.",
                    str(exc_val)[:100],
                )
                return True  # Suppress the exception

            return False  # Re-raise

        self.success = True
        return False


class ServiceHealthMonitor:
    """
    Monitors health of external services and provides status.

    Usage:
        monitor = ServiceHealthMonitor()
        monitor.record_success("gemini")
        monitor.record_failure("gemini", "timeout")

        if monitor.is_healthy("gemini"):
            # Proceed with API call
    """

    def __init__(self, window_size: int = 100, failure_threshold: float = 0.5):
        """
        Initialize health monitor.

        Args:
            window_size: Number of recent requests to track
            failure_threshold: Failure rate threshold (0.0 - 1.0)
        """
        from collections import deque

        self._results: dict[str, deque] = {}
        self._window_size = window_size
        self._failure_threshold = failure_threshold
        self._last_errors: dict[str, str] = {}
        self.logger = logging.getLogger("ServiceHealthMonitor")

    def record_success(self, service: str) -> None:
        """Record a successful request."""
        self._ensure_service(service)
        self._results[service].append(True)

    def record_failure(self, service: str, error: str = "") -> None:
        """Record a failed request."""
        self._ensure_service(service)
        self._results[service].append(False)
        self._last_errors[service] = error

    def _ensure_service(self, service: str) -> None:
        """Ensure service tracking exists."""
        from collections import deque

        if service not in self._results:
            self._results[service] = deque(maxlen=self._window_size)

    def is_healthy(self, service: str) -> bool:
        """Check if service is healthy based on recent success rate."""
        if service not in self._results or len(self._results[service]) == 0:
            return True  # Assume healthy if no data

        success_count = sum(self._results[service])
        total = len(self._results[service])
        failure_rate = 1.0 - (success_count / total)

        return failure_rate < self._failure_threshold

    def get_status(self, service: str) -> dict[str, Any]:
        """Get detailed status for a service."""
        if service not in self._results:
            return {"healthy": True, "requests": 0, "success_rate": 1.0}

        results = self._results[service]
        total = len(results)
        success_count = sum(results)

        return {
            "healthy": self.is_healthy(service),
            "requests": total,
            "success_rate": success_count / max(1, total),
            "last_error": self._last_errors.get(service, ""),
        }

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Get status for all tracked services."""
        return {service: self.get_status(service) for service in self._results}


# Global service health monitor
service_monitor = ServiceHealthMonitor()
