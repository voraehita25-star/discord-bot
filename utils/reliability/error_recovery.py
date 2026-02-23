"""
Error Recovery Module for Discord Bot.
Provides retry logic and graceful degradation utilities.

Enhanced with:
- Multiple jitter strategies (Full, Equal, Decorrelated)
- Circuit breaker integration
- Adaptive retry based on service health
- Slot-based backoff for API rate limits
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class JitterStrategy(Enum):
    """Jitter strategies for exponential backoff.

    See: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
    """

    NONE = "none"  # No jitter (not recommended)
    FULL = "full"  # sleep = random(0, min(cap, base * 2^attempt))
    EQUAL = "equal"  # sleep = min(cap, base * 2^attempt) / 2 + random(0, same/2)
    DECORRELATED = "decorrelated"  # sleep = min(cap, random(base, prev_sleep * 3))


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter_strategy: JitterStrategy = JitterStrategy.DECORRELATED
    recoverable_errors: tuple = (Exception,)
    # Advanced options
    respect_circuit_breaker: bool = True  # Stop retry if circuit is open
    respect_retry_after: bool = True  # Honor Retry-After headers (429s)
    adaptive_multiplier: bool = True  # Adjust based on service health

    # Legacy compatibility
    @property
    def jitter(self) -> bool:
        return self.jitter_strategy != JitterStrategy.NONE


# Preset configurations for common scenarios
RETRY_AGGRESSIVE = RetryConfig(
    max_retries=5,
    base_delay=0.5,
    max_delay=10.0,
    jitter_strategy=JitterStrategy.FULL,
)
RETRY_STANDARD = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    jitter_strategy=JitterStrategy.DECORRELATED,
)
RETRY_CONSERVATIVE = RetryConfig(
    max_retries=2,
    base_delay=2.0,
    max_delay=60.0,
    jitter_strategy=JitterStrategy.EQUAL,
)
# API-specific preset (respects rate limits)
RETRY_API = RetryConfig(
    max_retries=4,
    base_delay=1.0,
    max_delay=60.0,
    jitter_strategy=JitterStrategy.DECORRELATED,
    respect_retry_after=True,
    adaptive_multiplier=True,
)


@dataclass
class BackoffState:
    """Tracks state for decorrelated jitter across retries."""

    previous_delay: float = 0.0
    consecutive_failures: int = 0
    last_failure_time: float = 0.0


# Global backoff state per service/function with TTL cleanup
_backoff_states: dict[str, BackoffState] = {}
_backoff_states_lock = threading.Lock()  # Thread-safe lock for sync access
_backoff_states_async_lock = asyncio.Lock()  # Async lock for async access
_BACKOFF_STATE_TTL = 3600  # 1 hour TTL for backoff states
_MAX_BACKOFF_STATES = 1000  # Maximum number of states to keep


def _cleanup_old_backoff_states() -> None:
    """Remove old backoff states to prevent memory leak.

    Cleanup is triggered either when:
    1. State count exceeds MAX_BACKOFF_STATES
    2. Called periodically from _get_backoff_state
    """
    current_time = time.time()

    # Always perform TTL-based cleanup
    # Clean up states that are:
    # 1. Older than TTL with no failures (successful recovery)
    # 2. Older than 2x TTL regardless of failure count (very old)
    # 3. Have very high failure counts but are old (likely abandoned services)
    keys_to_remove = [
        key
        for key, state in _backoff_states.items()
        if (
            current_time - state.last_failure_time > _BACKOFF_STATE_TTL
            and state.consecutive_failures == 0
        )
        or (current_time - state.last_failure_time > _BACKOFF_STATE_TTL * 2)
        or (
            current_time - state.last_failure_time > _BACKOFF_STATE_TTL
            and state.consecutive_failures > 100
        )  # Likely abandoned
    ]
    for key in keys_to_remove:
        _backoff_states.pop(key, None)


# Counter for periodic cleanup trigger
_backoff_call_counter = 0


def _get_backoff_state(key: str) -> BackoffState:
    """Get or create backoff state for a key (thread-safe with sync lock)."""
    global _backoff_call_counter

    with _backoff_states_lock:
        _backoff_call_counter += 1

        # Periodically cleanup old states (every 100 calls or when over limit)
        # Use counter instead of modulo on dict size for reliable triggering
        if len(_backoff_states) >= _MAX_BACKOFF_STATES or _backoff_call_counter >= 100:
            _cleanup_old_backoff_states()
            _backoff_call_counter = 0

        if key not in _backoff_states:
            _backoff_states[key] = BackoffState()
        return _backoff_states[key]


async def _get_backoff_state_async(key: str) -> BackoffState:
    """Get or create backoff state for a key (async thread-safe)."""
    async with _backoff_states_async_lock:
        # Use the sync function which has its own thread lock
        return _get_backoff_state(key)


def _reset_backoff_state(key: str) -> None:
    """Reset backoff state after success.

    Note: This is called from async context via retry_async success path.
    Thread-safe via _backoff_states_lock.
    """
    with _backoff_states_lock:
        if key in _backoff_states:
            # Reset state instead of deleting to avoid re-creation overhead
            state = _backoff_states[key]
            state.previous_delay = 0.0
            state.consecutive_failures = 0


async def _reset_backoff_state_async(key: str) -> None:
    """Reset backoff state after success (async thread-safe)."""
    async with _backoff_states_async_lock:
        # Directly reset without calling _reset_backoff_state to avoid double-locking
        with _backoff_states_lock:
            if key in _backoff_states:
                state = _backoff_states[key]
                state.previous_delay = 0.0
                state.consecutive_failures = 0


def calculate_delay_sync(
    attempt: int,
    config: RetryConfig,
    state: BackoffState | None = None,
    service_health: float = 1.0,
) -> float:
    """
    Calculate delay for retry attempt with smart jitter.

    Args:
        attempt: Current attempt number (0-indexed)
        config: Retry configuration
        state: Optional backoff state for decorrelated jitter
        service_health: Service health score (0.0-1.0), lower = longer delays

    Returns:
        Delay in seconds before next retry
    """
    base_exp_delay = config.base_delay * (config.exponential_base**attempt)
    cap = config.max_delay

    if config.jitter_strategy == JitterStrategy.NONE:
        delay = min(base_exp_delay, cap)

    elif config.jitter_strategy == JitterStrategy.FULL:
        # Full Jitter: sleep = random(0, min(cap, base * 2^attempt))
        delay = random.uniform(0, min(cap, base_exp_delay))

    elif config.jitter_strategy == JitterStrategy.EQUAL:
        # Equal Jitter: sleep = temp/2 + random(0, temp/2)
        temp = min(cap, base_exp_delay)
        delay = temp / 2 + random.uniform(0, temp / 2)

    elif config.jitter_strategy == JitterStrategy.DECORRELATED:
        # Decorrelated Jitter: sleep = min(cap, random(base, prev * 3))
        if state and state.previous_delay > 0:
            delay = min(cap, random.uniform(config.base_delay, state.previous_delay * 3))
        else:
            delay = min(cap, random.uniform(config.base_delay, base_exp_delay))
        if state:
            state.previous_delay = delay

    else:
        delay = min(base_exp_delay, cap)

    # Adaptive multiplier: increase delay if service is unhealthy
    if config.adaptive_multiplier and service_health < 1.0:
        # Unhealthy service = longer delays (up to 2x)
        health_multiplier = 1.0 + (1.0 - service_health)
        delay *= health_multiplier

    return delay


async def calculate_delay(
    attempt: int,
    config: RetryConfig,
    state: BackoffState | None = None,
    service_health: float = 1.0,
) -> float:
    """Async wrapper for calculate_delay_sync."""
    return calculate_delay_sync(attempt, config, state, service_health)


def extract_retry_after(error: Exception) -> float | None:
    """
    Extract Retry-After value from HTTP errors.

    Supports:
    - aiohttp.ClientResponseError with headers
    - requests.Response exceptions
    - Google API errors with retry_delay
    """
    # Check for Google API retry_delay
    if hasattr(error, "retry_delay"):
        return error.retry_delay

    # Check for response headers
    if hasattr(error, "headers"):
        retry_after = error.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

    # Check for wrapped response
    if hasattr(error, "response") and hasattr(error.response, "headers"):
        retry_after = error.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

    return None


async def retry_async(
    func: Callable,
    *args,
    config: RetryConfig | None = None,
    fallback: Any = None,
    on_retry: Callable[[int, Exception], None] | None = None,
    service_name: str | None = None,
    **kwargs,
) -> Any:
    """
    Execute an async function with automatic retry on failure.

    Enhanced with:
    - Smart jitter strategies (decorrelated by default)
    - Circuit breaker integration
    - Retry-After header support
    - Service health-aware delays

    Args:
        func: Async function to execute
        *args: Positional arguments for the function
        config: Retry configuration
        fallback: Value to return if all retries fail
        on_retry: Callback called on each retry with (attempt, error)
        service_name: Optional service name for health tracking
        **kwargs: Keyword arguments for the function

    Returns:
        Function result or fallback value

    Example:
        result = await retry_async(
            fetch_data,
            url,
            config=RETRY_API,
            fallback=default_data,
            service_name="gemini",
        )
    """
    if config is None:
        config = RETRY_STANDARD

    last_error = None
    logger = logging.getLogger("ErrorRecovery")

    # Get backoff state for this function
    state_key = service_name or func.__name__
    state = await _get_backoff_state_async(state_key)

    # Get service health for adaptive delays
    service_health = 1.0
    if config.adaptive_multiplier and service_name:
        status = service_monitor.get_status(service_name)
        service_health = status.get("success_rate", 1.0)

    # Check circuit breaker before starting
    if config.respect_circuit_breaker:
        try:
            from .circuit_breaker import gemini_circuit

            if service_name == "gemini" and not gemini_circuit.can_execute():
                logger.warning("⚡ Circuit breaker OPEN - skipping retry for %s", service_name)
                if fallback is not None:
                    return fallback
                raise RuntimeError(f"Circuit breaker open for {service_name}")
        except ImportError:
            pass

    for attempt in range(config.max_retries):
        try:
            result = await func(*args, **kwargs)

            # Success! Reset backoff state and record health
            _reset_backoff_state(state_key)
            if service_name:
                service_monitor.record_success(service_name)

            return result

        except config.recoverable_errors as e:
            last_error = e
            state.consecutive_failures += 1
            state.last_failure_time = time.time()

            if service_name:
                service_monitor.record_failure(service_name, str(e)[:100])

            if on_retry:
                on_retry(attempt + 1, e)

            if attempt < config.max_retries - 1:
                # Calculate delay with smart jitter
                delay = await calculate_delay(attempt, config, state, service_health)

                # Honor Retry-After header if present
                if config.respect_retry_after:
                    retry_after = extract_retry_after(e)
                    if retry_after is not None:
                        delay = max(delay, retry_after)
                        logger.info("⏳ Respecting Retry-After: %.1fs", retry_after)

                logger.warning(
                    "⚠️ Attempt %d/%d failed: %s. Retrying in %.2fs (jitter: %s)...",
                    attempt + 1,
                    config.max_retries,
                    str(e)[:100],
                    delay,
                    config.jitter_strategy.value,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "❌ All %d attempts failed for %s: %s (total failures: %d)",
                    config.max_retries,
                    func.__name__,
                    str(e)[:200],
                    state.consecutive_failures,
                )

    # All retries failed
    if fallback is not None:
        logger.info("📦 Using fallback value after retries exhausted")
        return fallback

    if last_error is not None:
        raise last_error
    raise RuntimeError(
        f"retry_async failed for {func.__name__} with no error captured (max_retries={config.max_retries})"
    )


def with_retry(
    config: RetryConfig | None = None,
    fallback: Any = None,
    service_name: str | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
):
    """
    Decorator to add automatic retry to async functions.

    Enhanced with:
    - Service name for health tracking
    - Custom retry callback support
    - All smart backoff features from retry_async

    Usage:
        @with_retry(config=RETRY_API, service_name="gemini")
        async def fetch_data(url):
            return await http_get(url)

        @with_retry(fallback=[], on_retry=lambda a, e: print(f"Retry {a}"))
        async def get_items():
            return await db.get_items()

    Args:
        config: Retry configuration preset
        fallback: Value to return if all retries fail
        service_name: Service name for health monitoring
        on_retry: Callback(attempt, error) called on each retry
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
                on_retry=on_retry,
                service_name=service_name or func.__name__,
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
