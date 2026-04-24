"""
Unit Tests for Circuit Breaker Module
Tests circuit breaker state transitions, failure detection, and recovery.
"""

# Import the module under test
import sys
import time

import pytest

sys.path.insert(0, "c:/Users/ME/BOT")

from utils.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    gemini_circuit,
    get_all_circuit_status,
    spotify_circuit,
)


class TestCircuitBreakerStates:
    """Tests for circuit breaker state transitions."""

    @pytest.fixture
    def breaker(self):
        """Create a fresh circuit breaker for testing."""
        return CircuitBreaker(
            name="test_breaker", failure_threshold=3, reset_timeout=5.0, half_open_max_calls=2
        )

    def test_initial_state_is_closed(self, breaker):
        """Test that initial state is CLOSED."""
        assert breaker.state == CircuitState.CLOSED

    def test_can_execute_in_closed_state(self, breaker):
        """Test that execution is allowed when closed."""
        assert breaker.can_execute() is True

    def test_state_opens_after_threshold_failures(self, breaker):
        """Test that circuit opens after reaching failure threshold."""
        # Record failures up to threshold
        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN

    def test_cannot_execute_in_open_state(self, breaker):
        """Test that execution is blocked when open."""
        # Force open state
        for _ in range(3):
            breaker.record_failure()

        assert breaker.can_execute() is False

    def test_state_transitions_to_half_open_after_timeout(self, breaker):
        """Test that state goes to HALF_OPEN after reset_timeout."""
        # Force open state
        for _ in range(3):
            breaker.record_failure()

        # Simulate time passing
        breaker._last_failure_time = time.time() - 10  # 10 seconds ago

        assert breaker.state == CircuitState.HALF_OPEN

    def test_can_execute_limited_in_half_open(self, breaker):
        """Test that limited executions are allowed in half-open state."""
        # Force to half-open state
        for _ in range(3):
            breaker.record_failure()
        breaker._last_failure_time = time.time() - 10

        # Should allow up to half_open_max_calls
        assert breaker.can_execute() is True
        assert breaker.can_execute() is True
        assert breaker.can_execute() is False  # Exceeds max

    def test_success_in_half_open_closes_circuit(self, breaker):
        """Test that success in half-open state closes the circuit."""
        # Force to half-open state
        for _ in range(3):
            breaker.record_failure()
        breaker._last_failure_time = time.time() - 10
        breaker._state = CircuitState.HALF_OPEN  # Force state

        breaker.record_success()

        assert breaker.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens_circuit(self, breaker):
        """Test that failure in half-open state reopens the circuit."""
        # Force to half-open state
        for _ in range(3):
            breaker.record_failure()
        breaker._last_failure_time = time.time() - 10
        breaker._state = CircuitState.HALF_OPEN  # Force state

        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerRecovery:
    """Tests for circuit breaker recovery mechanisms."""

    @pytest.fixture
    def breaker(self):
        return CircuitBreaker(
            name="recovery_test", failure_threshold=2, reset_timeout=2.0, half_open_max_calls=1
        )

    def test_success_reduces_failure_count(self, breaker):
        """Test that success reduces failure count in closed state."""
        breaker.record_failure()
        initial_count = breaker._failure_count

        breaker.record_success()

        assert breaker._failure_count < initial_count

    def test_reset_clears_state(self, breaker):
        """Test that reset clears all state."""
        # Force to open state
        breaker.record_failure()
        breaker.record_failure()

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0
        assert breaker._success_count == 0
        assert breaker._last_failure_time is None

    def test_get_status_returns_dict(self, breaker):
        """Test that get_status returns a dictionary with expected keys."""
        status = breaker.get_status()

        assert isinstance(status, dict)
        assert "name" in status
        assert "state" in status
        assert "failure_count" in status
        assert "success_count" in status
        assert "config" in status


class TestGlobalCircuitBreakers:
    """Tests for global circuit breaker instances."""

    def test_gemini_circuit_exists(self):
        """Test that gemini_circuit is initialized."""
        assert gemini_circuit is not None
        assert gemini_circuit.name == "gemini_api"

    def test_spotify_circuit_exists(self):
        """Test that spotify_circuit is initialized."""
        assert spotify_circuit is not None
        assert spotify_circuit.name == "spotify_api"

    def test_get_all_circuit_status(self):
        """Test that get_all_circuit_status returns all circuit statuses."""
        status = get_all_circuit_status()

        assert isinstance(status, dict)
        assert "gemini" in status
        assert "spotify" in status
        assert status["gemini"]["name"] == "gemini_api"
        assert status["spotify"]["name"] == "spotify_api"


class TestCircuitBreakerOpenError:
    """Tests for CircuitBreakerOpenError exception."""

    def test_exception_can_be_raised(self):
        """Test that the exception can be raised and caught."""
        with pytest.raises(CircuitBreakerOpenError):
            raise CircuitBreakerOpenError("Service unavailable")

    def test_exception_message(self):
        """Test that exception carries the correct message."""
        try:
            raise CircuitBreakerOpenError("Test message")
        except CircuitBreakerOpenError as e:
            assert str(e) == "Test message"


class TestCircuitBreakerEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_single_failure_does_not_open(self):
        """Test that a single failure doesn't open the circuit."""
        breaker = CircuitBreaker(name="edge_test", failure_threshold=5)

        breaker.record_failure()

        assert breaker.state == CircuitState.CLOSED

    def test_failure_count_exactly_at_threshold(self):
        """Test behavior when failure count exactly reaches threshold."""
        breaker = CircuitBreaker(name="threshold_test", failure_threshold=3)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_multiple_successes_reduces_count_correctly(self):
        """Test that multiple successes reduce failure count correctly."""
        breaker = CircuitBreaker(name="multi_success_test", failure_threshold=5)

        # Add some failures
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()

        # Record successes
        breaker.record_success()
        breaker.record_success()
        breaker.record_success()

        assert breaker._failure_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
