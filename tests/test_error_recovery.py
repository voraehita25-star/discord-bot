# pylint: disable=protected-access
"""
Unit Tests for Error Recovery Module.
Tests retry logic, graceful degradation, and health monitoring.
"""

from __future__ import annotations


class TestRetryConfig:
    """Tests for RetryConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        from utils.reliability.error_recovery import RetryConfig

        config = RetryConfig()

        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0

    def test_custom_config(self):
        """Test custom configuration."""
        from utils.reliability.error_recovery import RetryConfig

        config = RetryConfig(max_retries=5, base_delay=0.5)

        assert config.max_retries == 5
        assert config.base_delay == 0.5


class TestPresetConfigs:
    """Tests for preset configurations."""

    def test_aggressive_config(self):
        """Test RETRY_AGGRESSIVE preset."""
        from utils.reliability.error_recovery import RETRY_AGGRESSIVE

        assert RETRY_AGGRESSIVE.max_retries == 5
        assert RETRY_AGGRESSIVE.base_delay == 0.5

    def test_standard_config(self):
        """Test RETRY_STANDARD preset."""
        from utils.reliability.error_recovery import RETRY_STANDARD

        assert RETRY_STANDARD.max_retries == 3

    def test_conservative_config(self):
        """Test RETRY_CONSERVATIVE preset."""
        from utils.reliability.error_recovery import RETRY_CONSERVATIVE

        assert RETRY_CONSERVATIVE.max_retries == 2
        assert RETRY_CONSERVATIVE.base_delay == 2.0


class TestRetryAsync:
    """Tests for retry_async function."""

    async def test_success_on_first_try(self):
        """Test successful execution without retries."""
        from utils.reliability.error_recovery import RetryConfig, retry_async

        async def success_func():
            return "success"

        config = RetryConfig(max_retries=3)
        result = await retry_async(success_func, config=config)

        assert result == "success"

    async def test_success_after_retry(self):
        """Test success after initial failures."""
        from utils.reliability.error_recovery import RetryConfig, retry_async

        call_count = 0

        async def eventually_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Not yet")
            return "success"

        config = RetryConfig(max_retries=5, base_delay=0.01)
        result = await retry_async(eventually_succeeds, config=config)

        assert result == "success"
        assert call_count == 3

    async def test_fallback_on_all_failures(self):
        """Test fallback value returned when all retries fail."""
        from utils.reliability.error_recovery import RetryConfig, retry_async

        async def always_fails():
            raise ValueError("Always fails")

        config = RetryConfig(max_retries=2, base_delay=0.01)
        result = await retry_async(always_fails, config=config, fallback="default")

        assert result == "default"

    async def test_on_retry_callback(self):
        """Test on_retry callback is called."""
        from utils.reliability.error_recovery import RetryConfig, retry_async

        retry_calls = []

        def on_retry(attempt, error):
            retry_calls.append((attempt, str(error)))

        async def fails_twice():
            if len(retry_calls) < 2:
                raise ValueError("Fail")
            return "success"

        config = RetryConfig(max_retries=5, base_delay=0.01)
        await retry_async(fails_twice, config=config, on_retry=on_retry)

        assert len(retry_calls) == 2


class TestWithRetryDecorator:
    """Tests for with_retry decorator."""

    async def test_decorator_success(self):
        """Test decorator on successful function."""
        from utils.reliability.error_recovery import RetryConfig, with_retry

        @with_retry(config=RetryConfig(max_retries=2))
        async def my_func():
            return "result"

        result = await my_func()
        assert result == "result"

    async def test_decorator_with_fallback(self):
        """Test decorator with fallback value."""
        from utils.reliability.error_recovery import RetryConfig, with_retry

        @with_retry(config=RetryConfig(max_retries=1, base_delay=0.01), fallback="fallback")
        async def always_fails():
            raise ValueError("Error")

        result = await always_fails()
        assert result == "fallback"


class TestServiceHealthMonitor:
    """Tests for ServiceHealthMonitor class."""

    def test_record_success(self):
        """Test recording successful requests."""
        from utils.reliability.error_recovery import ServiceHealthMonitor

        monitor = ServiceHealthMonitor()
        monitor.record_success("api")

        assert monitor.is_healthy("api") is True

    def test_unhealthy_after_failures(self):
        """Test service becomes unhealthy after many failures."""
        from utils.reliability.error_recovery import ServiceHealthMonitor

        monitor = ServiceHealthMonitor(window_size=10, failure_threshold=0.5)

        # Record 6 failures (60% failure rate)
        for _ in range(6):
            monitor.record_failure("api", "timeout")
        # Record 4 successes
        for _ in range(4):
            monitor.record_success("api")

        assert monitor.is_healthy("api") is False

    def test_healthy_after_recovry(self):
        """Test service becomes healthy after recovery."""
        from utils.reliability.error_recovery import ServiceHealthMonitor

        monitor = ServiceHealthMonitor(window_size=10, failure_threshold=0.5)

        # First make it unhealthy
        for _ in range(10):
            monitor.record_failure("api")

        assert monitor.is_healthy("api") is False

        # Now recover
        for _ in range(10):
            monitor.record_success("api")

        assert monitor.is_healthy("api") is True

    def test_get_status(self):
        """Test getting service status."""
        from utils.reliability.error_recovery import ServiceHealthMonitor

        monitor = ServiceHealthMonitor()
        monitor.record_success("api")
        monitor.record_failure("api", "error message")

        status = monitor.get_status("api")

        assert "healthy" in status
        assert "success_rate" in status
        assert "last_error" in status
        assert status["requests"] == 2


class TestServiceMonitorSingleton:
    """Tests for service_monitor singleton."""

    def test_singleton_has_methods(self):
        """Test singleton has required methods."""
        from utils.reliability.error_recovery import service_monitor

        assert hasattr(service_monitor, "record_success")
        assert hasattr(service_monitor, "record_failure")
        assert hasattr(service_monitor, "is_healthy")


class TestJitterStrategies:
    """Tests for smart jitter strategies."""

    def test_jitter_strategy_enum_values(self):
        """Test JitterStrategy enum has expected values."""
        from utils.reliability.error_recovery import JitterStrategy

        assert JitterStrategy.NONE.value == "none"
        assert JitterStrategy.FULL.value == "full"
        assert JitterStrategy.EQUAL.value == "equal"
        assert JitterStrategy.DECORRELATED.value == "decorrelated"

    def test_no_jitter_produces_deterministic_delay(self):
        """Test NONE jitter produces deterministic delays."""
        from utils.reliability.error_recovery import (
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            exponential_base=2.0,
            jitter_strategy=JitterStrategy.NONE,
            adaptive_multiplier=False,
        )

        # Without jitter, delay should be exactly base * 2^attempt
        assert calculate_delay_sync(0, config) == 1.0  # 1 * 2^0 = 1
        assert calculate_delay_sync(1, config) == 2.0  # 1 * 2^1 = 2
        assert calculate_delay_sync(2, config) == 4.0  # 1 * 2^2 = 4

    def test_full_jitter_within_bounds(self):
        """Test FULL jitter produces delays within expected bounds."""
        from utils.reliability.error_recovery import (
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter_strategy=JitterStrategy.FULL,
            adaptive_multiplier=False,
        )

        # Full jitter: 0 <= delay <= min(cap, base * 2^attempt)
        for _ in range(100):
            delay = calculate_delay_sync(2, config)  # max would be 4.0
            assert 0 <= delay <= 4.0

    def test_equal_jitter_within_bounds(self):
        """Test EQUAL jitter produces delays within expected bounds."""
        from utils.reliability.error_recovery import (
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter_strategy=JitterStrategy.EQUAL,
            adaptive_multiplier=False,
        )

        # Equal jitter: delay = temp/2 + random(0, temp/2)
        # For attempt 2: temp = 4.0, so 2.0 <= delay <= 4.0
        for _ in range(100):
            delay = calculate_delay_sync(2, config)
            assert 2.0 <= delay <= 4.0

    def test_decorrelated_jitter_uses_previous_delay(self):
        """Test DECORRELATED jitter uses previous delay."""
        from utils.reliability.error_recovery import (
            BackoffState,
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            max_delay=100.0,
            jitter_strategy=JitterStrategy.DECORRELATED,
            adaptive_multiplier=False,
        )

        state = BackoffState(previous_delay=2.0)

        # Decorrelated: delay = random(base, prev * 3)
        # With prev=2.0: 1.0 <= delay <= 6.0
        for _ in range(100):
            delay = calculate_delay_sync(0, config, state)
            assert 1.0 <= delay <= 6.0
            state.previous_delay = 2.0  # Reset for consistent testing

    def test_max_delay_cap_respected(self):
        """Test max_delay caps the calculated delay."""
        from utils.reliability.error_recovery import (
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            max_delay=5.0,
            exponential_base=2.0,
            jitter_strategy=JitterStrategy.NONE,
            adaptive_multiplier=False,
        )

        # Attempt 10 would be 1024 without cap, but should be 5.0
        delay = calculate_delay_sync(10, config)
        assert delay == 5.0


class TestAdaptiveBackoff:
    """Tests for adaptive backoff based on service health."""

    def test_adaptive_multiplier_increases_delay_for_unhealthy_service(self):
        """Test delays are increased when service is unhealthy."""
        from utils.reliability.error_recovery import (
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            jitter_strategy=JitterStrategy.NONE,
            adaptive_multiplier=True,
        )

        # 50% health means 1.5x multiplier
        delay_unhealthy = calculate_delay_sync(0, config, service_health=0.5)
        delay_healthy = calculate_delay_sync(0, config, service_health=1.0)

        assert delay_unhealthy > delay_healthy
        assert delay_unhealthy == 1.5  # 1.0 * 1.5

    def test_adaptive_multiplier_disabled(self):
        """Test adaptive multiplier can be disabled."""
        from utils.reliability.error_recovery import (
            JitterStrategy,
            RetryConfig,
            calculate_delay_sync,
        )

        config = RetryConfig(
            base_delay=1.0,
            jitter_strategy=JitterStrategy.NONE,
            adaptive_multiplier=False,
        )

        # Even with 0% health, delay should be unchanged
        delay = calculate_delay_sync(0, config, service_health=0.0)
        assert delay == 1.0


class TestExtractRetryAfter:
    """Tests for extract_retry_after function."""

    def test_extract_from_google_api_error(self):
        """Test extracting retry_delay from Google API errors."""
        from utils.reliability.error_recovery import extract_retry_after

        class MockGoogleError(Exception):
            retry_delay = 30.0

        result = extract_retry_after(MockGoogleError())
        assert result == 30.0

    def test_extract_from_headers(self):
        """Test extracting Retry-After from headers."""
        from utils.reliability.error_recovery import extract_retry_after

        class MockError(Exception):
            headers = {"Retry-After": "60"}

        result = extract_retry_after(MockError())
        assert result == 60.0

    def test_extract_from_response_headers(self):
        """Test extracting from response.headers."""
        from utils.reliability.error_recovery import extract_retry_after

        class MockResponse:
            headers = {"Retry-After": "45"}

        class MockError(Exception):
            response = MockResponse()

        result = extract_retry_after(MockError())
        assert result == 45.0

    def test_returns_none_when_not_found(self):
        """Test returns None when Retry-After not found."""
        from utils.reliability.error_recovery import extract_retry_after

        result = extract_retry_after(ValueError("simple error"))
        assert result is None


class TestRetryApiPreset:
    """Tests for RETRY_API preset configuration."""

    def test_retry_api_preset_exists(self):
        """Test RETRY_API preset is available."""
        from utils.reliability.error_recovery import RETRY_API

        assert RETRY_API is not None

    def test_retry_api_has_correct_settings(self):
        """Test RETRY_API has appropriate settings for API calls."""
        from utils.reliability.error_recovery import RETRY_API, JitterStrategy

        assert RETRY_API.max_retries == 4
        assert RETRY_API.jitter_strategy == JitterStrategy.DECORRELATED
        assert RETRY_API.respect_retry_after is True
        assert RETRY_API.adaptive_multiplier is True


class TestBackoffState:
    """Tests for BackoffState tracking."""

    def test_backoff_state_initialization(self):
        """Test BackoffState initializes with defaults."""
        from utils.reliability.error_recovery import BackoffState

        state = BackoffState()
        assert state.previous_delay == 0.0
        assert state.consecutive_failures == 0
        assert state.last_failure_time == 0.0

    def test_backoff_state_tracking(self):
        """Test backoff state is tracked per key."""
        from utils.reliability.error_recovery import (
            _get_backoff_state,
            _reset_backoff_state,
        )

        state1 = _get_backoff_state("service_a")
        state1.consecutive_failures = 5

        state2 = _get_backoff_state("service_b")
        state2.consecutive_failures = 3

        # States should be independent
        assert _get_backoff_state("service_a").consecutive_failures == 5
        assert _get_backoff_state("service_b").consecutive_failures == 3

        # Reset should only affect specific key
        _reset_backoff_state("service_a")
        assert _get_backoff_state("service_a").consecutive_failures == 0
        assert _get_backoff_state("service_b").consecutive_failures == 3


class TestWithRetryEnhanced:
    """Tests for enhanced with_retry decorator."""

    async def test_decorator_with_service_name(self):
        """Test decorator passes service_name correctly."""
        from utils.reliability.error_recovery import RetryConfig, with_retry

        @with_retry(
            config=RetryConfig(max_retries=2, base_delay=0.01),
            service_name="test_service",
        )
        async def my_func():
            return "result"

        result = await my_func()
        assert result == "result"

    async def test_decorator_with_on_retry_callback(self):
        """Test decorator with on_retry callback."""
        from utils.reliability.error_recovery import RetryConfig, with_retry

        retry_attempts = []

        def track_retry(attempt, error):
            retry_attempts.append(attempt)

        call_count = 0

        @with_retry(
            config=RetryConfig(max_retries=3, base_delay=0.01),
            on_retry=track_retry,
        )
        async def fails_once():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("First attempt fails")
            return "success"

        result = await fails_once()
        assert result == "success"
        assert retry_attempts == [1]  # Only 1 retry needed
