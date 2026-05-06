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
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


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

    CRITICAL = 0  # Run first (e.g., save state)
    HIGH = 10  # Important (e.g., flush queues)
    NORMAL = 50  # Standard cleanup
    LOW = 90  # Can be skipped if timeout
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
        # Threading lock guarding the lazy-init of the asyncio primitives
        # above. Without this, two coroutines calling ``_get_lock`` /
        # ``_get_shutdown_event`` concurrently could each see ``None`` and
        # construct distinct Lock/Event objects — the later writer wins,
        # but the earlier coroutine ends up holding a lock no one else
        # ever observes. Using threading.Lock keeps the gate cheap and
        # safe even when called from a signal-handler thread before any
        # event loop is running.
        self._init_lock: threading.Lock = threading.Lock()
        self._pending_shutdown_task: asyncio.Task[ShutdownState] | None = None
        # Strong refs for tasks spawned from signal handlers, so they are not
        # GC'd before they run. Initialized here so AttributeError can't occur
        # if setup_async_signal_handlers is never called or is called twice.
        self._signal_tasks: set[asyncio.Task] = set()

        self.logger = logging.getLogger("ShutdownManager")

        # Register atexit handler for sync cleanup
        atexit.register(self._atexit_handler)

    def _get_shutdown_event(self) -> asyncio.Event:
        """Lazily create the shutdown event in the correct event loop.

        Double-checked locking under the threading.Lock so concurrent
        callers can't each construct their own Event.
        """
        if self._shutdown_event is None:
            with self._init_lock:
                if self._shutdown_event is None:
                    self._shutdown_event = asyncio.Event()
        return self._shutdown_event

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the lock in the correct event loop.

        Double-checked locking under the threading.Lock so concurrent
        callers can't each construct their own Lock.
        """
        if self._lock is None:
            with self._init_lock:
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
        import inspect

        is_async = inspect.iscoroutinefunction(callback)

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
            name,
            priority.name,
            timeout,
        )

    def unregister(self, name: str) -> bool:
        """Unregister a cleanup handler by name."""
        initial_count = len(self._handlers)
        self._handlers = [h for h in self._handlers if h.name != name]
        removed = len(self._handlers) < initial_count

        if removed:
            self.logger.debug("Unregistered cleanup handler: %s", name)

        return removed

    async def _run_handler(self, handler: CleanupHandler, *, timeout: float | None = None) -> bool:
        """Run a single cleanup handler with timeout.

        Pass `timeout` to override the handler's configured timeout for this
        single invocation (used by shutdown() when it needs to honour a
        global remaining-time budget). Doing it via parameter avoids the
        previous pattern of mutating handler.timeout in place, which was
        not atomic and could be observed by other coroutines.
        """
        effective_timeout = handler.timeout if timeout is None else timeout
        try:
            self.logger.info("🔄 Running cleanup: %s", handler.name)

            if handler.is_async:
                await asyncio.wait_for(handler.callback(), timeout=effective_timeout)
            else:
                # Run sync callback in executor.
                loop = asyncio.get_running_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, handler.callback), timeout=effective_timeout
                )

            self.logger.info("✅ Cleanup complete: %s", handler.name)
            self._state.handlers_run += 1
            return True

        except TimeoutError:
            msg = f"Cleanup timed out after {effective_timeout}s: {handler.name}"
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
            phase_handlers = [h for h in self._handlers if h.priority in priorities]

            if not phase_handlers:
                continue

            self.logger.info("📍 Phase: %s (%d handlers)", phase.name, len(phase_handlers))

            if remaining_time <= 0:
                # No budget left — skip the entire phase rather than walking
                # one-by-one and incrementing the skip counter for each.
                for handler in phase_handlers:
                    self.logger.warning("⏱️ Timeout reached, skipping: %s", handler.name)
                    self._state.handlers_skipped += 1
                continue

            # Run all handlers in this phase concurrently. The previous
            # serial execution caused 10 handlers × 5s timeouts = 50s total,
            # which routinely blew past the 30s shutdown budget. Parallel
            # execution lets the budget be O(max(timeout)) instead of
            # O(sum(timeout)), and the per-handler timeout still applies.
            phase_budget = remaining_time
            tasks = [
                asyncio.create_task(
                    self._run_handler(h, timeout=min(h.timeout, phase_budget)),
                    name=f"shutdown:{h.name}",
                )
                for h in phase_handlers
            ]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=phase_budget,
                )
            except TimeoutError:
                # Whole phase exceeded budget — cancel any stragglers so the
                # bot doesn't sit there waiting for handlers that are stuck.
                for t in tasks:
                    if not t.done():
                        t.cancel()
                self.logger.warning(
                    "⏱️ Phase %s budget exhausted; cancelled %d in-flight handler(s)",
                    phase.name,
                    sum(1 for t in tasks if t.cancelled()),
                )

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
        """Synchronous shutdown for use in signal handlers.

        If a loop is already running, schedule the shutdown on it via
        `call_soon_threadsafe` (signal handlers are NOT in async context).
        If no loop is running, run a fresh one. We avoid `asyncio.run`
        inside an already-running loop because that raises and historically
        could deadlock with the main loop's primitives.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Schedule via call_soon_threadsafe — safe from signal context.
            # Use `create_task` directly: `ensure_future` with a loop=
            # kwarg is deprecated in 3.10+ and removed in 3.12+, and the
            # callback fires on the loop thread anyway.
            def _schedule() -> None:
                task = asyncio.create_task(self.shutdown(signal_name))
                self._pending_shutdown_task = task

            try:
                loop.call_soon_threadsafe(_schedule)
            except RuntimeError:
                # Loop closed between get + call — fall through to fresh run.
                asyncio.run(self.shutdown(signal_name))
            return

        # No loop running — own it.
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
                # Run sync handlers only (no event loop available). Use a
                # worker thread + join(timeout=...) so a hung handler doesn't
                # stall interpreter shutdown indefinitely. Daemon threads
                # exit with the interpreter so leaked workers can't keep
                # the process alive.
                # Spawn ALL workers first, then join them — parallelises the
                # wait so total atexit time is bounded by max(timeout) rather
                # than sum(timeouts) when many handlers are registered.
                import threading as _thr

                workers: list[tuple[Any, Any, _thr.Thread]] = []
                for handler in self._handlers:
                    if handler.is_async:
                        continue
                    try:
                        worker = _thr.Thread(
                            target=handler.callback,
                            name=f"atexit-{handler.name}",
                            daemon=True,
                        )
                        worker.start()
                        workers.append((handler.name, handler.timeout, worker))
                    except Exception as shutdown_err:
                        logger.debug("Shutdown handler error (ignored): %s", shutdown_err)

                for name, timeout, worker in workers:
                    try:
                        worker.join(timeout=timeout)
                        if worker.is_alive():
                            # Daemon threads are killed mid-syscall when the
                            # interpreter exits, which can leave external
                            # state (open files, locks, sockets) inconsistent.
                            # Surface this loudly so the operator can either
                            # shorten the handler or extend its timeout.
                            logger.warning(
                                "atexit handler %s exceeded %ss timeout and "
                                "is still running; daemon thread will be killed "
                                "by interpreter shutdown — external state may "
                                "be left inconsistent.",
                                name,
                                timeout,
                            )
                    except Exception as join_err:
                        logger.debug("Shutdown join error (ignored): %s", join_err)
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

        # Strong refs to in-flight signal tasks live in self._signal_tasks
        # (initialized in __init__). Re-initializing here would drop refs
        # for tasks already spawned by an earlier setup, so we leave it.

        def _make_handler(sig_value: int):
            def _handler() -> None:
                task = asyncio.create_task(self.shutdown(signal.Signals(sig_value).name))
                self._signal_tasks.add(task)
                task.add_done_callback(self._signal_tasks.discard)

            return _handler

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _make_handler(sig))

        self.logger.info("🛡️ Async signal handlers registered: SIGTERM, SIGINT")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals.

        Two-phase semantics:
          1st signal → schedule graceful shutdown (run async cleanups)
          2nd signal during shutdown → ``os._exit(1)`` (hard exit)

        We use ``os._exit`` rather than ``sys.exit`` because we're in a
        signal handler: ``sys.exit`` raises ``SystemExit`` from the signal
        frame, which can deadlock with locks held by the interrupted code
        path or be swallowed by a wrapping ``except Exception``. ``os._exit``
        bypasses all Python-level cleanup and the kernel reaps the process
        immediately — that's what we actually want when the user is asking
        for an emergency exit on Ctrl-C #2.
        """
        sig_name = signal.Signals(signum).name
        self.logger.info("🛑 Received signal: %s", sig_name)

        if self._state.phase != ShutdownPhase.RUNNING:
            self.logger.warning("Force exit requested during shutdown")
            os._exit(1)

        # Schedule async shutdown but do NOT exit immediately --
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
