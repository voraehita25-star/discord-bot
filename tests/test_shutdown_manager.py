"""
Unit Tests for Shutdown Manager Module.
Tests graceful shutdown, cleanup handlers, and signal handling.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestShutdownPhaseAndPriority:
    """Tests for enums."""

    def test_shutdown_phases(self):
        """Test ShutdownPhase enum values."""
        from utils.reliability.shutdown_manager import ShutdownPhase

        assert ShutdownPhase.RUNNING.value < ShutdownPhase.INITIATED.value
        assert ShutdownPhase.COMPLETE.value > ShutdownPhase.CLEANUP.value

    def test_priority_ordering(self):
        """Test Priority enum ordering."""
        from utils.reliability.shutdown_manager import Priority

        assert Priority.CRITICAL.value < Priority.HIGH.value
        assert Priority.HIGH.value < Priority.NORMAL.value
        assert Priority.NORMAL.value < Priority.LOW.value
        assert Priority.LOW.value < Priority.BACKGROUND.value


class TestCleanupHandler:
    """Tests for CleanupHandler dataclass."""

    def test_handler_creation(self):
        """Test creating a cleanup handler."""
        from utils.reliability.shutdown_manager import CleanupHandler, Priority

        def my_cleanup():
            pass

        handler = CleanupHandler(
            name="test_handler",
            callback=my_cleanup,
            priority=Priority.HIGH,
            timeout=10.0,
        )

        assert handler.name == "test_handler"
        assert handler.priority == Priority.HIGH
        assert handler.timeout == 10.0
        assert handler.required is True


class TestShutdownState:
    """Tests for ShutdownState dataclass."""

    def test_initial_state(self):
        """Test initial shutdown state."""
        from utils.reliability.shutdown_manager import ShutdownPhase, ShutdownState

        state = ShutdownState()

        assert state.phase == ShutdownPhase.RUNNING
        assert state.initiated_at is None
        assert state.handlers_run == 0

    def test_duration_calculation(self):
        """Test duration calculation."""
        from utils.reliability.shutdown_manager import ShutdownState

        state = ShutdownState()
        state.initiated_at = 100.0
        state.completed_at = 105.0

        assert state.duration_seconds == 5.0


class TestShutdownManager:
    """Tests for ShutdownManager class."""

    def test_register_handler(self):
        """Test registering cleanup handlers."""
        from utils.reliability.shutdown_manager import Priority, ShutdownManager

        manager = ShutdownManager(timeout=10.0)

        def cleanup1():
            pass

        async def cleanup2():
            pass

        manager.register("sync_cleanup", cleanup1, priority=Priority.HIGH)
        manager.register("async_cleanup", cleanup2, priority=Priority.NORMAL)

        status = manager.get_status()

        assert status["handlers_count"] == 2
        assert any(h["name"] == "sync_cleanup" for h in status["registered_handlers"])
        assert any(h["name"] == "async_cleanup" for h in status["registered_handlers"])

    def test_handler_priority_sorting(self):
        """Test handlers are sorted by priority."""
        from utils.reliability.shutdown_manager import Priority, ShutdownManager

        manager = ShutdownManager(timeout=10.0)

        manager.register("low", lambda: None, priority=Priority.LOW)
        manager.register("critical", lambda: None, priority=Priority.CRITICAL)
        manager.register("normal", lambda: None, priority=Priority.NORMAL)

        handlers = manager._handlers
        priorities = [h.priority for h in handlers]

        assert priorities == [Priority.CRITICAL, Priority.NORMAL, Priority.LOW]

    def test_unregister_handler(self):
        """Test unregistering handlers."""
        from utils.reliability.shutdown_manager import ShutdownManager

        manager = ShutdownManager(timeout=10.0)
        manager.register("test", lambda: None)

        assert manager.unregister("test") is True
        assert manager.unregister("nonexistent") is False

    def test_is_shutting_down(self):
        """Test shutdown state checking."""
        from utils.reliability.shutdown_manager import ShutdownManager, ShutdownPhase

        manager = ShutdownManager(timeout=10.0)

        assert manager.is_shutting_down is False

        manager._state.phase = ShutdownPhase.INITIATED
        assert manager.is_shutting_down is True

    @pytest.mark.asyncio
    async def test_run_sync_handler(self):
        """Test running synchronous cleanup handler."""
        from utils.reliability.shutdown_manager import CleanupHandler, ShutdownManager

        manager = ShutdownManager(timeout=10.0)
        called = []

        def sync_cleanup():
            called.append("sync")

        handler = CleanupHandler(
            name="sync_test",
            callback=sync_cleanup,
            timeout=5.0,
            is_async=False,
        )

        result = await manager._run_handler(handler)

        assert result is True
        assert "sync" in called

    @pytest.mark.asyncio
    async def test_run_async_handler(self):
        """Test running asynchronous cleanup handler."""
        from utils.reliability.shutdown_manager import CleanupHandler, ShutdownManager

        manager = ShutdownManager(timeout=10.0)
        called = []

        async def async_cleanup():
            called.append("async")

        handler = CleanupHandler(
            name="async_test",
            callback=async_cleanup,
            timeout=5.0,
            is_async=True,
        )

        result = await manager._run_handler(handler)

        assert result is True
        assert "async" in called

    @pytest.mark.asyncio
    async def test_handler_timeout(self):
        """Test handler timeout handling."""
        from utils.reliability.shutdown_manager import CleanupHandler, ShutdownManager

        manager = ShutdownManager(timeout=10.0)

        async def slow_cleanup():
            await asyncio.sleep(10)  # Will timeout

        handler = CleanupHandler(
            name="slow_test",
            callback=slow_cleanup,
            timeout=0.1,  # Very short timeout
            is_async=True,
        )

        result = await manager._run_handler(handler)

        assert result is False
        assert manager._state.handlers_failed == 1

    @pytest.mark.asyncio
    async def test_handler_exception(self):
        """Test handler exception handling."""
        from utils.reliability.shutdown_manager import CleanupHandler, ShutdownManager

        manager = ShutdownManager(timeout=10.0)

        def failing_cleanup():
            raise ValueError("Test error")

        handler = CleanupHandler(
            name="failing_test",
            callback=failing_cleanup,
            timeout=5.0,
            is_async=False,
        )

        result = await manager._run_handler(handler)

        assert result is False
        assert len(manager._state.errors) == 1

    @pytest.mark.asyncio
    async def test_full_shutdown(self):
        """Test complete shutdown process."""
        from utils.reliability.shutdown_manager import Priority, ShutdownManager

        manager = ShutdownManager(timeout=10.0, force_exit=False)
        execution_order = []

        def critical_cleanup():
            execution_order.append("critical")

        def normal_cleanup():
            execution_order.append("normal")

        async def low_cleanup():
            execution_order.append("low")

        manager.register("critical", critical_cleanup, priority=Priority.CRITICAL)
        manager.register("normal", normal_cleanup, priority=Priority.NORMAL)
        manager.register("low", low_cleanup, priority=Priority.LOW)

        state = await manager.shutdown(signal_name="TEST")

        assert state.phase.name == "COMPLETE"
        assert state.handlers_run == 3
        assert state.signal_received == "TEST"
        # Check execution order matches priority
        assert execution_order == ["critical", "normal", "low"]

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        """Test shutdown can only be triggered once."""
        from utils.reliability.shutdown_manager import ShutdownManager

        manager = ShutdownManager(timeout=10.0, force_exit=False)

        state1 = await manager.shutdown()
        state2 = await manager.shutdown()

        # Second call should return same state without re-running
        assert state1 == state2

    def test_get_status(self):
        """Test getting manager status."""
        from utils.reliability.shutdown_manager import ShutdownManager

        manager = ShutdownManager(timeout=30.0)
        manager.register("test", lambda: None)

        status = manager.get_status()

        assert status["phase"] == "RUNNING"
        assert status["is_shutting_down"] is False
        assert status["handlers_count"] == 1
        assert status["timeout"] == 30.0


class TestOnShutdownDecorator:
    """Tests for on_shutdown decorator."""

    def test_decorator_registers_handler(self):
        """Test decorator registers function as handler."""
        from utils.reliability.shutdown_manager import (
            Priority,
            on_shutdown,
            shutdown_manager,
        )

        # Clear any existing handlers first
        original_handlers = shutdown_manager._handlers.copy()

        @on_shutdown(priority=Priority.HIGH, timeout=10.0)
        def my_cleanup():
            pass

        # Check handler was registered
        handler = next(
            (h for h in shutdown_manager._handlers if h.name == "my_cleanup"),
            None,
        )

        assert handler is not None
        assert handler.priority == Priority.HIGH
        assert handler.timeout == 10.0

        # Cleanup
        shutdown_manager._handlers = original_handlers


class TestGlobalShutdownManager:
    """Tests for global shutdown_manager instance."""

    def test_global_manager_exists(self):
        """Test global manager is accessible."""
        from utils.reliability.shutdown_manager import shutdown_manager

        assert shutdown_manager is not None

    def test_global_manager_default_timeout(self):
        """Test global manager has default timeout."""
        from utils.reliability.shutdown_manager import shutdown_manager

        assert shutdown_manager.timeout == 30.0

    def test_global_manager_methods(self):
        """Test global manager has required methods."""
        from utils.reliability.shutdown_manager import shutdown_manager

        assert hasattr(shutdown_manager, "register")
        assert hasattr(shutdown_manager, "shutdown")
        assert hasattr(shutdown_manager, "setup_signal_handlers")
