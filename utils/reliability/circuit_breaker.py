"""
Circuit Breaker Pattern Implementation
Provides automatic failure detection and recovery for external API calls.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float | None = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    # Thread-safe lock for state transitions
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning from OPEN to HALF_OPEN if timeout elapsed.

        Thread-safe: Uses lock to prevent race conditions during state transition.
        """
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time
                and (time.time() - self._last_failure_time >= self.reset_timeout)
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
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None  # Also reset last failure time

        if old_state != new_state:
            logging.info(
                "⚡ Circuit Breaker [%s]: %s -> %s", self.name, old_state.value, new_state.value
            )

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state with logging (thread-safe)."""
        with self._lock:
            self._transition_to_unlocked(new_state)

    def can_execute(self) -> bool:
        """Check if a request can be executed (thread-safe)."""
        with self._lock:
            # Check for state transition from OPEN to HALF_OPEN
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time
                and (time.time() - self._last_failure_time >= self.reset_timeout)
            ):
                self._transition_to_unlocked(CircuitState.HALF_OPEN)

            current_state = self._state

            if current_state == CircuitState.CLOSED:
                return True
            elif current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
            else:  # OPEN
                return False

    def record_success(self) -> None:
        """Record a successful execution (thread-safe)."""
        with self._lock:
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                # Successful call in half-open state -> close circuit
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
                    logging.warning(
                        "⚡ Circuit Breaker [%s]: OPENED after %d failures",
                        self.name,
                        self._failure_count,
                    )

    def get_status(self) -> dict[str, Any]:
        """Get current circuit breaker status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": self._last_failure_time,
            "config": {
                "failure_threshold": self.failure_threshold,
                "reset_timeout": self.reset_timeout,
            },
        }

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logging.info("⚡ Circuit Breaker [%s]: Manually reset", self.name)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request cannot proceed."""

    pass


# ==================== Global Circuit Breakers ====================

# Gemini API circuit breaker
gemini_circuit = CircuitBreaker(
    name="gemini_api", failure_threshold=5, reset_timeout=60.0, half_open_max_calls=2
)

# Spotify API circuit breaker
spotify_circuit = CircuitBreaker(
    name="spotify_api", failure_threshold=3, reset_timeout=30.0, half_open_max_calls=1
)


def get_all_circuit_status() -> dict[str, dict]:
    """Get status of all circuit breakers."""
    return {"gemini": gemini_circuit.get_status(), "spotify": spotify_circuit.get_status()}
