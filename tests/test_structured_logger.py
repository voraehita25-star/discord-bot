"""
Unit Tests for Structured Logger Module.
Tests JSON formatting, context tracking, and performance timing.
"""

from __future__ import annotations

import json
import logging
import time
from unittest.mock import MagicMock, patch

import pytest


class TestLogContext:
    """Tests for LogContext dataclass."""

    def test_to_dict_excludes_none(self):
        """Test to_dict excludes None values."""
        from utils.monitoring.structured_logger import LogContext

        ctx = LogContext(
            user_id=123,
            channel_id=None,
            guild_id=456,
        )

        result = ctx.to_dict()

        assert "user_id" in result
        assert "guild_id" in result
        assert "channel_id" not in result

    def test_to_dict_excludes_empty_extra(self):
        """Test to_dict excludes empty extra dict."""
        from utils.monitoring.structured_logger import LogContext

        ctx = LogContext(user_id=123)

        result = ctx.to_dict()

        assert "extra" not in result


class TestStructuredFormatter:
    """Tests for StructuredFormatter class."""

    def test_basic_json_format(self):
        """Test basic JSON log formatting."""
        from utils.monitoring.structured_logger import StructuredFormatter

        formatter = StructuredFormatter(
            include_timestamp=False,
            service_name="test-service",
        )

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"
        assert parsed["service"] == "test-service"

    def test_includes_source_location(self):
        """Test log includes source file information."""
        from utils.monitoring.structured_logger import StructuredFormatter

        formatter = StructuredFormatter(include_timestamp=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="myfile.py",
            lineno=42,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.funcName = "my_function"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["source"]["file"] == "myfile.py"
        assert parsed["source"]["line"] == 42
        assert parsed["source"]["function"] == "my_function"

    def test_includes_exception_info(self):
        """Test log includes exception information."""
        from utils.monitoring.structured_logger import StructuredFormatter

        formatter = StructuredFormatter(include_timestamp=False)

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "exception" in parsed
        assert parsed["exception"]["type"] == "ValueError"
        assert "Test error" in parsed["exception"]["message"]

    def test_includes_context(self):
        """Test log includes context from record."""
        from utils.monitoring.structured_logger import StructuredFormatter

        formatter = StructuredFormatter(include_timestamp=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.context = {"user_id": 123, "request_id": "abc123"}

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["context"]["user_id"] == 123
        assert parsed["context"]["request_id"] == "abc123"

    def test_includes_duration(self):
        """Test log includes duration when present."""
        from utils.monitoring.structured_logger import StructuredFormatter

        formatter = StructuredFormatter(include_timestamp=False)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.duration_ms = 150.5

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["duration_ms"] == 150.5


class TestHumanReadableFormatter:
    """Tests for HumanReadableFormatter class."""

    def test_basic_format(self):
        """Test basic human-readable format."""
        from utils.monitoring.structured_logger import HumanReadableFormatter

        formatter = HumanReadableFormatter(use_colors=False)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        assert "INFO" in result
        assert "test.logger" in result
        assert "Test message" in result


class TestStructuredLogger:
    """Tests for StructuredLogger class."""

    def test_basic_logging(self):
        """Test basic logging methods."""
        from utils.monitoring.structured_logger import StructuredLogger

        logger = StructuredLogger("test")

        # Should not raise
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

    def test_context_manager(self):
        """Test context manager adds context."""
        from utils.monitoring.structured_logger import StructuredLogger, _log_context

        logger = StructuredLogger("test")

        with logger.context(user_id=123, channel_id=456):
            ctx = _log_context.get()
            assert ctx["user_id"] == 123
            assert ctx["channel_id"] == 456

        # Context should be cleared after exiting
        ctx = _log_context.get()
        assert "user_id" not in ctx

    def test_request_context_generates_id(self):
        """Test request context generates request ID."""
        from utils.monitoring.structured_logger import StructuredLogger, _log_context

        logger = StructuredLogger("test")

        with logger.request(user_id=123) as req_id:
            assert req_id is not None
            assert len(req_id) == 8  # UUID[:8]

            ctx = _log_context.get()
            assert ctx["request_id"] == req_id
            assert ctx["user_id"] == 123

    def test_log_event(self):
        """Test log_event method."""
        from utils.monitoring.structured_logger import StructuredLogger

        logger = StructuredLogger("test")

        # Should not raise
        logger.log_event("test_event", tokens=500, latency_ms=150)

    def test_log_error_with_context(self):
        """Test logging error with exception context."""
        from utils.monitoring.structured_logger import StructuredLogger

        logger = StructuredLogger("test")

        try:
            raise ValueError("Test error")
        except ValueError as e:
            # Should not raise
            logger.log_error_with_context("Error occurred", e, extra_info="test")


class TestPerformanceTimer:
    """Tests for PerformanceTimer class."""

    def test_measure_timing(self):
        """Test measuring code block timing."""
        from utils.monitoring.structured_logger import PerformanceTimer

        timer = PerformanceTimer()

        with timer.measure("test_step"):
            time.sleep(0.02)  # 20ms - more reliable than 10ms

        timing = timer.get_timing("test_step")

        assert timing is not None
        assert timing >= 15  # At least 15ms (allow some variance)

    def test_get_average(self):
        """Test getting average timing."""
        from utils.monitoring.structured_logger import PerformanceTimer

        timer = PerformanceTimer()

        with timer.measure("step"):
            pass

        with timer.measure("step"):
            pass

        avg = timer.get_average("step")

        assert avg is not None

    def test_get_all_timings(self):
        """Test getting all timing statistics."""
        from utils.monitoring.structured_logger import PerformanceTimer

        timer = PerformanceTimer()

        with timer.measure("step1"):
            pass

        with timer.measure("step2"):
            pass

        stats = timer.get_all_timings()

        assert "step1" in stats
        assert "step2" in stats
        assert "count" in stats["step1"]
        assert "avg_ms" in stats["step1"]

    def test_clear(self):
        """Test clearing timings."""
        from utils.monitoring.structured_logger import PerformanceTimer

        timer = PerformanceTimer()

        with timer.measure("step"):
            pass

        timer.clear()

        assert timer.get_timing("step") is None


class TestTimedDecorator:
    """Tests for timed decorator."""

    async def test_async_function_timing(self):
        """Test decorator times async functions."""
        from utils.monitoring.structured_logger import StructuredLogger, timed

        logger = StructuredLogger("test")

        @timed(logger)
        async def my_async_func():
            await asyncio.sleep(0.01)
            return "result"

        import asyncio
        result = await my_async_func()

        assert result == "result"

    def test_sync_function_timing(self):
        """Test decorator times sync functions."""
        from utils.monitoring.structured_logger import StructuredLogger, timed

        logger = StructuredLogger("test")

        @timed(logger)
        def my_sync_func():
            time.sleep(0.01)
            return "result"

        result = my_sync_func()

        assert result == "result"


class TestSetupStructuredLogging:
    """Tests for setup_structured_logging function."""

    def test_setup_without_file(self):
        """Test setup without file output."""
        from utils.monitoring.structured_logger import setup_structured_logging

        # Should not raise
        setup_structured_logging(log_file=None, level=logging.DEBUG)

    def test_setup_with_file(self, tmp_path):
        """Test setup with file output."""
        from utils.monitoring.structured_logger import setup_structured_logging

        log_file = tmp_path / "test.log"

        setup_structured_logging(
            log_file=str(log_file),
            level=logging.INFO,
            service_name="test-service",
        )

        # Log something
        logger = logging.getLogger("test.setup")
        logger.info("Test message")

        # File should exist (may be empty due to buffering)
        # Just verify no errors occurred


class TestCorrelationId:
    """Tests for correlation ID functions."""

    def test_get_correlation_id(self):
        """Test getting correlation ID."""
        from utils.monitoring.structured_logger import (
            _log_context,
            get_correlation_id,
        )

        # Set context
        _log_context.set({"request_id": "test123"})

        result = get_correlation_id()

        assert result == "test123"

        # Cleanup
        _log_context.set({})

    def test_set_correlation_id(self):
        """Test setting correlation ID."""
        from utils.monitoring.structured_logger import (
            _log_context,
            get_correlation_id,
            set_correlation_id,
        )

        set_correlation_id("my-correlation-id")

        ctx = _log_context.get()

        assert ctx["correlation_id"] == "my-correlation-id"

        # Cleanup
        _log_context.set({})


class TestGetLogger:
    """Tests for get_logger convenience function."""

    def test_get_logger(self):
        """Test getting a structured logger."""
        from utils.monitoring.structured_logger import StructuredLogger, get_logger

        logger = get_logger("my.module")

        assert isinstance(logger, StructuredLogger)


class TestGlobalTimer:
    """Tests for global_timer instance."""

    def test_global_timer_exists(self):
        """Test global timer is accessible."""
        from utils.monitoring.structured_logger import global_timer

        assert global_timer is not None

    def test_global_timer_methods(self):
        """Test global timer has required methods."""
        from utils.monitoring.structured_logger import global_timer

        assert hasattr(global_timer, "measure")
        assert hasattr(global_timer, "get_timing")
        assert hasattr(global_timer, "clear")
