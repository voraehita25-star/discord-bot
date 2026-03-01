"""
Graceful Shutdown Manager for Discord Bot.
Provides coordinated shutdown with cleanup handlers, timeout management, and signal handling.

Features:
- Register cleanup callbacks with priorities
- Graceful timeout with force-kill fallback
- Signal handling (SIGTERM, SIGINT)
- Async and sync cleanup support
- Shutdown state tracking
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal
import sys
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ShutdownPhase(Enum):
    """Phases of shutdown process."""

    RUNNING = auto()
    INITIATED = auto()
    STOPPING_SERVICES = auto()
    CLOSING_CONNECTIONS = auto()
    CLEANUP = auto()
    COMPLETE = auto()


class Priority(Enum):
    """Cleanup callback priority levels."""

    CRITICAL = 0    # Run first (e.g., save state)
    HIGH = 10       # Important (e.g., flush queues)
    NORMAL = 50     # Standard cleanup
    LOW = 90        # Can be skipped if timeout
    BACKGROUND = 100  # Background tasks


@dataclass
class CleanupHandler:
    """Registered cleanup handler."""

    name: str
    callback: Callable[[], Any] | Callable[[], Coroutine[Any, Any, Any]]
    priority: Priority = Priority.NORMAL
    timeout: float = 5.0
    is_async: bool = False
    required: bool = True  # If True, failure is logged as error


@dataclass
class ShutdownState:
    """Tracks shutdown state and statistics."""

    phase: ShutdownPhase = ShutdownPhase.RUNNING
    initiated_at: float | None = None
    completed_at: float | None = None
    signal_received: str | None = None
    handlers_run: int = 0
    handlers_failed: int = 0
    handlers_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float | None:
        """Get shutdown duration if complete."""
        if self.initiated_at and self.completed_at:
            return self.completed_at - self.initiated_at
        return None


class ShutdownManager:
    """
    Manages graceful shutdown with coordinated cleanup.

    Usage:
        manager = ShutdownManager(timeout=30.0)

        # Register cleanup handlers
        manager.register("database", db.close, priority=Priority.CRITICAL)
        manager.register("cache", cache.flush, priority=Priority.HIGH)
        manager.register("background_tasks", stop_tasks, priority=Priority.LOW)

        # Setup signal handlers
        manager.setup_signal_handlers()

        # Later, shutdown is triggered automatically on signals
        # Or manually:
        await manager.shutdown()
    """

    def __init__(
        self,
        timeout: float = 30.0,
        force_exit: bool = True,
        exit_code: int = 0,
    ):
        """
        Initialize shutdown manager.

        Args:
            timeout: Maximum seconds to wait for cleanup
            force_exit: Whether to force exit after timeout
            exit_code: Exit code to use on shutdown
        """
        self.timeout = timeout
        self.force_exit = force_exit
        self.exit_code = exit_code

        self._handlers: list[CleanupHandler] = []
        self._state = ShutdownState()
        # Defer Event creation to avoid binding to the wrong event loop at import time.
        # asyncio.Event() created here may be associated with no loop or a different loop.
        self._shutdown_event: asyncio.Event | None = None
        self._lock: asyncio.Lock | None = None
        self._pending_shutdown_task: asyncio.Task[ShutdownState] | None = None

        self.logger = logging.getLogger("ShutdownManager")

        # Register atexit handler for sync cleanup
        atexit.register(self._atexit_handler)

    def _get_shutdown_event(self) -> asyncio.Event:
        """Lazily create the shutdown event in the correct event loop."""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        return self._shutdown_event

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the lock in the correct event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def state(self) -> ShutdownState:
        """Get current shutdown state."""
        return self._state

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self._state.phase != ShutdownPhase.RUNNING

    def register(
        self,
        name: str,
        callback: Callable[[], Any] | Callable[[], Coroutine[Any, Any, Any]],
        priority: Priority = Priority.NORMAL,
        timeout: float = 5.0,
        required: bool = True,
    ) -> None:
        """
        Register a cleanup handler.

        Args:
            name: Handler name for logging
            callback: Cleanup function (sync or async)
            priority: Execution priority (lower = earlier)
            timeout: Timeout for this handler
            required: Whether failure should be logged as error
        """
        is_async = asyncio.iscoroutinefunction(callback)

        handler = CleanupHandler(
            name=name,
            callback=callback,
            priority=priority,
            timeout=timeout,
            is_async=is_async,
            required=required,
        )

        self._handlers.append(handler)
        self._handlers.sort(key=lambda h: h.priority.value)

        self.logger.debug(
            "Registered cleanup handler: %s (priority: %s, timeout: %.1fs)",
            name, priority.name, timeout
        )

    def unregister(self, name: str) -> bool:
        """Unregister a cleanup handler by name."""
        initial_count = len(self._handlers)
        self._handlers = [h for h in self._handlers if h.name != name]
        removed = len(self._handlers) < initial_count

        if removed:
            self.logger.debug("Unregistered cleanup handler: %s", name)

        return removed

    async def _run_handler(self, handler: CleanupHandler) -> bool:
        """Run a single cleanup handler with timeout."""
        try:
            self.logger.info("🔄 Running cleanup: %s", handler.name)

            if handler.is_async:
                await asyncio.wait_for(
                    handler.callback(),
                    timeout=handler.timeout
                )
            else:
                # Run sync callback in executor
                loop = asyncio.get_running_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, handler.callback),
                    timeout=handler.timeout
                )

            self.logger.info("✅ Cleanup complete: %s", handler.name)
            self._state.handlers_run += 1
            return True

        except asyncio.TimeoutError:
            msg = f"Cleanup timed out after {handler.timeout}s: {handler.name}"
            self._state.errors.append(msg)
            self._state.handlers_failed += 1

            if handler.required:
                self.logger.error("❌ %s", msg)
            else:
                self.logger.warning("⚠️ %s", msg)
            return False

        except Exception as e:
            msg = f"Cleanup failed: {handler.name}: {e}"
            self._state.errors.append(msg)
            self._state.handlers_failed += 1

            if handler.required:
                self.logger.error("❌ %s", msg)
            else:
                self.logger.warning("⚠️ %s", msg)
            return False

    async def shutdown(self, signal_name: str | None = None) -> ShutdownState:
        """
        Execute graceful shutdown.

        Args:
            signal_name: Name of signal that triggered shutdown (optional)

        Returns:
            Final shutdown state
        """
        async with self._get_lock():
            if self._state.phase != ShutdownPhase.RUNNING:
                self.logger.warning("Shutdown already in progress")
                return self._state

            self._state.phase = ShutdownPhase.INITIATED
            self._state.initiated_at = time.time()
            self._state.signal_received = signal_name

            if signal_name:
                self.logger.info("🛑 Shutdown initiated (signal: %s)", signal_name)
            else:
                self.logger.info("🛑 Shutdown initiated")

        start_time = time.time()
        remaining_time = self.timeout

        # Group handlers by priority phase
        phases = [
            (ShutdownPhase.STOPPING_SERVICES, [Priority.CRITICAL, Priority.HIGH]),
            (ShutdownPhase.CLOSING_CONNECTIONS, [Priority.NORMAL]),
            (ShutdownPhase.CLEANUP, [Priority.LOW, Priority.BACKGROUND]),
        ]

        for phase, priorities in phases:
            self._state.phase = phase
            phase_handlers = [
                h for h in self._handlers
                if h.priority in priorities
            ]

            if not phase_handlers:
                continue

            self.logger.info("📍 Phase: %s (%d handlers)", phase.name, len(phase_handlers))

            for handler in phase_handlers:
                if remaining_time <= 0:
                    self.logger.warning(
                        "⏱️ Timeout reached, skipping: %s",
                        handler.name
                    )
                    self._state.handlers_skipped += 1
                    continue

                # Adjust handler timeout based on remaining time
                effective_timeout = min(handler.timeout, remaining_time)
                # Use a local copy to avoid mutating the handler's original timeout
                original_timeout = handler.timeout
                handler.timeout = effective_timeout

                await self._run_handler(handler)

                # Restore original timeout
                handler.timeout = original_timeout

                elapsed = time.time() - start_time
                remaining_time = self.timeout - elapsed

        # Mark complete
        self._state.phase = ShutdownPhase.COMPLETE
        self._state.completed_at = time.time()

        # Set shutdown event
        self._get_shutdown_event().set()

        # Log summary
        duration = self._state.duration_seconds or 0
        self.logger.info(
            "👋 Shutdown complete in %.2fs (run: %d, failed: %d, skipped: %d)",
            duration,
            self._state.handlers_run,
            self._state.handlers_failed,
            self._state.handlers_skipped,
        )

        return self._state

    def shutdown_sync(self, signal_name: str | None = None) -> None:
        """Synchronous shutdown for use in signal handlers."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # Schedule shutdown in the running loop and store reference
                task = asyncio.create_task(self.shutdown(signal_name))
                # Store task reference to prevent garbage collection
                self._pending_shutdown_task = task
            else:
                loop.run_until_complete(self.shutdown(signal_name))
        except RuntimeError:
            # No running loop, create one
            asyncio.run(self.shutdown(signal_name))

    def _atexit_handler(self) -> None:
        """Handler for atexit - run sync cleanups silently.

        Note: During interpreter shutdown, stdout/stderr may be closed.
        We suppress logging here to avoid ValueError on closed streams.
        """
        if self._state.phase == ShutdownPhase.RUNNING:
            # Suppress logging errors during interpreter shutdown
            old_raise_exceptions = logging.raiseExceptions
            logging.raiseExceptions = False

            try:
                # Run sync handlers only (no event loop available)
                for handler in self._handlers:
                    if not handler.is_async:
                        try:
                            handler.callback()
                        except Exception as shutdown_err:
                            # Log to debug level to avoid stdout issues during interpreter shutdown
                            logging.debug("Shutdown handler error (ignored): %s", shutdown_err)
            finally:
                logging.raiseExceptions = old_raise_exceptions

    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        if sys.platform == "win32":
            # Windows: only SIGINT is reliably available
            signal.signal(signal.SIGINT, self._signal_handler)
            self.logger.info("🛡️ Signal handler registered: SIGINT")
        else:
            # Unix: SIGTERM and SIGINT
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, self._signal_handler)
            self.logger.info("🛡️ Signal handlers registered: SIGTERM, SIGINT")

    def setup_async_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        """Setup async-safe signal handlers."""
        if sys.platform == "win32":
            # Windows doesn't support loop.add_signal_handler
            return

        # Store task references to prevent GC collection
        self._signal_tasks: list[asyncio.Task] = []

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: self._signal_tasks.append(
                    asyncio.create_task(
                        self.shutdown(signal.Signals(s).name)
                    )
                ),
            )

        self.logger.info("🛡️ Async signal handlers registered: SIGTERM, SIGINT")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        sig_name = signal.Signals(signum).name
        self.logger.info("🛑 Received signal: %s", sig_name)

        if self._state.phase != ShutdownPhase.RUNNING:
            self.logger.warning("Force exit requested during shutdown")
            sys.exit(1)

        # Schedule async shutdown but do NOT sys.exit immediately --
        # let the event loop run the cleanup tasks first
        self.shutdown_sync(sig_name)

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown to complete."""
        await self._get_shutdown_event().wait()

    def get_status(self) -> dict[str, Any]:
        """Get current shutdown manager status."""
        return {
            "phase": self._state.phase.name,
            "is_shutting_down": self.is_shutting_down,
            "registered_handlers": [
                {
                    "name": h.name,
                    "priority": h.priority.name,
                    "timeout": h.timeout,
                    "is_async": h.is_async,
                    "required": h.required,
                }
                for h in self._handlers
            ],
            "handlers_count": len(self._handlers),
            "timeout": self.timeout,
        }


# Global shutdown manager instance
shutdown_manager = ShutdownManager(timeout=30.0)


# Convenience decorators
def on_shutdown(
    priority: Priority = Priority.NORMAL,
    timeout: float = 5.0,
    required: bool = True,
):
    """
    Decorator to register a function as shutdown handler.

    Usage:
        @on_shutdown(priority=Priority.HIGH)
        async def cleanup_cache():
            await cache.flush()
    """
    def decorator(func: Callable) -> Callable:
        shutdown_manager.register(
            name=func.__name__,
            callback=func,
            priority=priority,
            timeout=timeout,
            required=required,
        )
        return func
    return decorator
