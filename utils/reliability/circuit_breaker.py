"""
Circuit Breaker Pattern Implementation
Provides automatic failure detection and recovery for external API calls.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Circuit tripped, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit Breaker for protecting against cascading failures.

    Usage:
        breaker = CircuitBreaker(name="gemini_api")

        if breaker.can_execute():
            try:
                result = await api_call()
                breaker.record_success()
            except Exception as e:
                breaker.record_failure()
                raise
        else:
            raise CircuitBreakerOpenError("Service unavailable")
    """

    name: str
    failure_threshold: int = 5  # Failures before opening
    reset_timeout: float = 60.0  # Seconds before trying again
    half_open_max_calls: int = 3  # Calls allowed in half-open state
    # If a half-open call doesn't report success/failure within this many
    # seconds, the slot it consumed is forgiven so the circuit can keep
    # admitting probes. Without this, fire-and-forget callers that crash
    # silently could permanently starve the circuit.
    half_open_call_timeout: float = 60.0

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float | None = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    # Successes observed since entering the current HALF_OPEN window.
    # The circuit only closes once this reaches ``half_open_max_calls`` —
    # without that gate, the *first* probe success would close the circuit
    # while the remaining (max_calls - 1) probes were still in flight.
    # Those probes might then fail and force a flap back to OPEN.
    _half_open_successes: int = field(default=0, init=False)
    # Timestamps of in-flight half-open call admissions, for the timeout
    # forgive logic above.
    _half_open_call_starts: list[float] = field(default_factory=list, init=False)
    _current_reset_timeout: float | None = field(default=None, init=False)
    # Thread-safe lock for state transitions (used for both sync and async paths)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    # Async-safe lock for async-path callers — using threading.Lock from
    # within asyncio coroutines blocks the event loop on contention.
    # Lazily initialized in __post_init__ so we don't bind to an event loop
    # at module import time (no loop may be running yet).
    _async_lock: asyncio.Lock | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        # Lazy-init in async_* methods is safer; we just declare the attr.
        self._async_lock = None

    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning from OPEN to HALF_OPEN if timeout elapsed.

        Thread-safe: Uses lock to prevent race conditions during state transition.
        """
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time
                and (
                    time.time() - self._last_failure_time
                    >= (self._current_reset_timeout or self.reset_timeout)
                )
            ):
                self._transition_to_unlocked(CircuitState.HALF_OPEN)
            return self._state

    def _transition_to_unlocked(self, new_state: CircuitState) -> None:
        """Internal transition without lock (caller must hold lock).

        Note: All state modifications happen within the lock to prevent
        race conditions during state transitions.
        """
        old_state = self._state
        self._state = new_state

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._half_open_call_starts.clear()
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._half_open_call_starts.clear()
            self._last_failure_time = None  # Also reset last failure time
            self._current_reset_timeout = None
        elif new_state == CircuitState.OPEN:
            # Jitter the reset timeout to prevent thundering herd
            self._current_reset_timeout = self.reset_timeout + random.uniform(
                0, self.reset_timeout * 0.3
            )

        if old_state != new_state:
            logger.info(
                "⚡ Circuit Breaker [%s]: %s -> %s", self.name, old_state.value, new_state.value
            )

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state with logging (thread-safe)."""
        with self._lock:
            self._transition_to_unlocked(new_state)

    def can_execute(self) -> bool:
        """Check if a request can be executed (thread-safe)."""
        now = time.time()
        with self._lock:
            # Check for state transition from OPEN to HALF_OPEN
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time
                and (
                    now - self._last_failure_time
                    >= (self._current_reset_timeout or self.reset_timeout)
                )
            ):
                self._transition_to_unlocked(CircuitState.HALF_OPEN)

            current_state = self._state

            if current_state == CircuitState.CLOSED:
                return True
            elif current_state == CircuitState.HALF_OPEN:
                # Forgive any half-open admissions that have outlived the
                # call timeout — without this, fire-and-forget callers that
                # crashed silently could permanently exhaust the slot pool
                # and starve the circuit.
                if self._half_open_call_starts:
                    # Forgive only genuinely IN-FLIGHT probes that outlived the
                    # call timeout. Completed probes are popped on record_*,
                    # so _half_open_call_starts holds only still-running ones —
                    # no success clamp here (the old clamp wiped successes
                    # earned by completed probes, wedging HALF_OPEN forever
                    # under sparse traffic).
                    cutoff = now - self.half_open_call_timeout
                    self._half_open_call_starts = [
                        ts for ts in self._half_open_call_starts if ts > cutoff
                    ]
                    self._half_open_calls = len(self._half_open_call_starts)
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    self._half_open_call_starts.append(now)
                    return True
                return False
            else:  # OPEN
                return False

    def record_success(self) -> None:
        """Record a successful execution (thread-safe)."""
        with self._lock:
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                # This probe COMPLETED — remove its admission timestamp from
                # the in-flight set so a later ``can_execute`` can't mistake
                # it for a stuck probe and forgive away its success credit.
                if self._half_open_call_starts:
                    self._half_open_call_starts.pop(0)
                    self._half_open_calls = len(self._half_open_call_starts)
                self._half_open_successes += 1
                # Wait until ALL admitted probes confirm before closing —
                # otherwise the first 1/3 probes could succeed, the circuit
                # closes, and then the remaining flying probes fail and
                # immediately re-open it (state flap). The forgive timer in
                # ``can_execute`` guarantees stuck probes won't permanently
                # block the close.
                if self._half_open_successes >= self.half_open_max_calls:
                    self._transition_to_unlocked(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                if self._failure_count > 0:
                    self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Record a failed execution (thread-safe)."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Failed in half-open state -> back to open
                self._transition_to_unlocked(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to_unlocked(CircuitState.OPEN)
                    logger.warning(
                        "⚡ Circuit Breaker [%s]: OPENED after %d failures",
                        self.name,
                        self._failure_count,
                    )

    def get_status(self) -> dict[str, Any]:
        """Get current circuit breaker status (thread-safe)."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure": self._last_failure_time,
                "config": {
                    "failure_threshold": self.failure_threshold,
                    "reset_timeout": self.reset_timeout,
                },
            }

    def reset(self) -> None:
        """Manually reset the circuit breaker (thread-safe)."""
        with self._lock:
            self._transition_to_unlocked(CircuitState.CLOSED)
            # Note: _transition_to_unlocked already resets these when transitioning to CLOSED
            # but we explicitly set them here for clarity on manual reset
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
        logger.info("⚡ Circuit Breaker [%s]: Manually reset", self.name)

    def _get_async_lock(self) -> asyncio.Lock:
        """Lazily allocate the asyncio.Lock so we bind to the running loop."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    async def async_can_execute(self) -> bool:
        """Async-safe version of can_execute.

        Uses an asyncio.Lock so concurrent coroutines don't block the event
        loop. The body mirrors the sync ``can_execute`` logic.

        Also takes the sync ``self._lock`` while mutating shared counters so
        a sync caller from another thread can't race on read-modify-write
        of ``_failure_count`` / ``_success_count`` / ``_half_open_*``. The
        threading lock is held briefly so it doesn't stall the event loop.
        """
        async with self._get_async_lock():
            with self._lock:
                now = time.time()
                # Check for state transition from OPEN to HALF_OPEN
                if (
                    self._state == CircuitState.OPEN
                    and self._last_failure_time
                    and (
                        now - self._last_failure_time
                        >= (self._current_reset_timeout or self.reset_timeout)
                    )
                ):
                    self._transition_to_unlocked(CircuitState.HALF_OPEN)

                current_state = self._state

                if current_state == CircuitState.CLOSED:
                    return True
                elif current_state == CircuitState.HALF_OPEN:
                    if self._half_open_call_starts:
                        # Forgive only genuinely IN-FLIGHT probes that outlived
                        # the call timeout (mirrors the fixed sync can_execute).
                        # NO success clamp here — completed probes are popped in
                        # async_record_success, so the old clamp wiped successes
                        # they earned and could wedge HALF_OPEN forever under
                        # sparse traffic.
                        cutoff = now - self.half_open_call_timeout
                        self._half_open_call_starts = [
                            ts for ts in self._half_open_call_starts if ts > cutoff
                        ]
                        self._half_open_calls = len(self._half_open_call_starts)
                    if self._half_open_calls < self.half_open_max_calls:
                        self._half_open_calls += 1
                        self._half_open_call_starts.append(now)
                        return True
                    return False
                else:  # OPEN
                    return False

    async def async_record_success(self) -> None:
        """Async-safe version of record_success.

        Mirrors the sync ``record_success`` logic but under an asyncio.Lock.
        Also holds ``self._lock`` so sync/async callers can't lose updates
        to ``_success_count`` / ``_failure_count``. The threading lock is a
        regular ``with`` (not ``async with``) — it's acquired and released
        synchronously inside the asyncio coroutine.
        """
        async with self._get_async_lock():
            with self._lock:
                self._success_count += 1

                if self._state == CircuitState.HALF_OPEN:
                    # This probe COMPLETED — pop its admission timestamp from
                    # the in-flight set so a later ``async_can_execute`` can't
                    # mistake it for a stuck probe and forgive away its success
                    # credit. Mirrors the fixed sync ``record_success`` exactly;
                    # the previous async path only ran a forgive filter + clamp,
                    # which wiped legitimately-earned successes under sparse
                    # traffic and could wedge HALF_OPEN forever.
                    if self._half_open_call_starts:
                        self._half_open_call_starts.pop(0)
                        self._half_open_calls = len(self._half_open_call_starts)
                    self._half_open_successes += 1
                    if self._half_open_successes >= self.half_open_max_calls:
                        self._transition_to_unlocked(CircuitState.CLOSED)
                elif self._state == CircuitState.CLOSED:
                    if self._failure_count > 0:
                        self._failure_count = max(0, self._failure_count - 1)

    async def async_record_failure(self) -> None:
        """Async-safe version of record_failure.

        Mirrors the sync ``record_failure`` logic but under an asyncio.Lock.
        Also holds ``self._lock`` to serialise with sync callers.
        """
        async with self._get_async_lock():
            with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.time()

                if self._state == CircuitState.HALF_OPEN:
                    self._transition_to_unlocked(CircuitState.OPEN)
                elif self._state == CircuitState.CLOSED:
                    if self._failure_count >= self.failure_threshold:
                        self._transition_to_unlocked(CircuitState.OPEN)
                        logger.warning(
                            "⚡ Circuit Breaker [%s]: OPENED after %d failures",
                            self.name,
                            self._failure_count,
                        )


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request cannot proceed."""


# ==================== Global Circuit Breakers ====================

# Gemini API circuit breaker
gemini_circuit = CircuitBreaker(
    name="gemini_api", failure_threshold=5, reset_timeout=60.0, half_open_max_calls=2
)

# Spotify API circuit breaker
spotify_circuit = CircuitBreaker(
    name="spotify_api", failure_threshold=3, reset_timeout=30.0, half_open_max_calls=1
)

# Service-name → CircuitBreaker registry. ``error_recovery.retry_async``
# previously hard-coded the ``gemini`` lookup, so retrying any other service
# silently bypassed its breaker. New services register here and the
# generic retry path picks them up via ``get_circuit_for_service``.
# Register under BOTH the short alias and the canonical ``.name`` so a
# lookup by either spelling resolves to the same breaker — previously
# ``get_circuit_for_service("gemini_api")`` (matching the breaker's own
# ``name``) returned None while ``"gemini"`` worked.
_CIRCUIT_REGISTRY: dict[str, CircuitBreaker] = {
    "gemini": gemini_circuit,
    "gemini_api": gemini_circuit,
    "spotify": spotify_circuit,
    "spotify_api": spotify_circuit,
}


def register_circuit(service_name: str, breaker: CircuitBreaker) -> None:
    """Register a circuit breaker so the generic retry path can find it."""
    _CIRCUIT_REGISTRY[service_name] = breaker


def get_circuit_for_service(service_name: str) -> CircuitBreaker | None:
    """Look up a circuit breaker by the canonical service name."""
    return _CIRCUIT_REGISTRY.get(service_name)


def get_all_circuit_status() -> dict[str, dict]:
    """Get status of all circuit breakers."""
    return {name: cb.get_status() for name, cb in _CIRCUIT_REGISTRY.items()}
