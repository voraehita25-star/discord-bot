# pylint: disable=protected-access
"""
Unit Tests for Error Recovery Module.
Tests retry logic, graceful degradation, and health monitoring.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


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
        from utils.reliability.error_recovery import retry_async, RetryConfig

        async def success_func():
            return "success"

        config = RetryConfig(max_retries=3)
        result = await retry_async(success_func, config=config)

        assert result == "success"

    async def test_success_after_retry(self):
        """Test success after initial failures."""
        from utils.reliability.error_recovery import retry_async, RetryConfig

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
        from utils.reliability.error_recovery import retry_async, RetryConfig

        async def always_fails():
            raise ValueError("Always fails")

        config = RetryConfig(max_retries=2, base_delay=0.01)
        result = await retry_async(always_fails, config=config, fallback="default")

        assert result == "default"

    async def test_on_retry_callback(self):
        """Test on_retry callback is called."""
        from utils.reliability.error_recovery import retry_async, RetryConfig

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
        from utils.reliability.error_recovery import with_retry, RetryConfig

        @with_retry(config=RetryConfig(max_retries=2))
        async def my_func():
            return "result"

        result = await my_func()
        assert result == "result"

    async def test_decorator_with_fallback(self):
        """Test decorator with fallback value."""
        from utils.reliability.error_recovery import with_retry, RetryConfig

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

    def test_singleton_exists(self):
        """Test that service_monitor singleton is accessible."""
        from utils.reliability.error_recovery import service_monitor

        assert service_monitor is not None

    def test_singleton_has_methods(self):
        """Test singleton has required methods."""
        from utils.reliability.error_recovery import service_monitor

        assert hasattr(service_monitor, "record_success")
        assert hasattr(service_monitor, "record_failure")
        assert hasattr(service_monitor, "is_healthy")
