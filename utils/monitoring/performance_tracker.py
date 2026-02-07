"""
Performance Tracker Module for Discord Bot.
Tracks response times and provides percentile statistics.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class PerformanceStats:
    """Performance statistics with percentiles."""

    count: int = 0
    total_time: float = 0.0
    min_time: float = float("inf")
    max_time: float = 0.0
    recent_times: deque = field(default_factory=lambda: deque(maxlen=1000))
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def record(self, duration: float) -> None:
        """Record a timing measurement."""
        with self._lock:
            self.count += 1
            self.total_time += duration
            self.min_time = min(self.min_time, duration)
            self.max_time = max(self.max_time, duration)
            self.recent_times.append(duration)

    @property
    def avg_time(self) -> float:
        """Average response time."""
        return self.total_time / max(1, self.count)

    @property
    def p50(self) -> float:
        """50th percentile (median)."""
        if not self.recent_times:
            return 0.0
        sorted_times = sorted(self.recent_times)
        return sorted_times[len(sorted_times) // 2]

    @property
    def p95(self) -> float:
        """95th percentile."""
        if not self.recent_times:
            return 0.0
        sorted_times = sorted(self.recent_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    @property
    def p99(self) -> float:
        """99th percentile."""
        if not self.recent_times:
            return 0.0
        sorted_times = sorted(self.recent_times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    @property
    def stddev(self) -> float:
        """Standard deviation."""
        if len(self.recent_times) < 2:
            return 0.0
        try:
            return statistics.stdev(self.recent_times)
        except statistics.StatisticsError:
            return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Export stats as dictionary."""
        return {
            "count": self.count,
            "avg_ms": round(self.avg_time * 1000, 2),
            "min_ms": round(self.min_time * 1000, 2) if self.min_time != float("inf") else 0,
            "max_ms": round(self.max_time * 1000, 2),
            "p50_ms": round(self.p50 * 1000, 2),
            "p95_ms": round(self.p95 * 1000, 2),
            "p99_ms": round(self.p99 * 1000, 2),
            "stddev_ms": round(self.stddev * 1000, 2),
        }


class PerformanceTracker:
    """
    Tracks performance metrics across different operations.

    Usage:
        tracker = PerformanceTracker()

        # Context manager for timing
        with tracker.measure("ai_response"):
            response = await call_ai()

        # Manual timing
        start = tracker.start_timer()
        result = await some_operation()
        tracker.record("operation_name", start)

        # Get stats
        stats = tracker.get_stats("ai_response")
        print(f"P95: {stats['p95_ms']}ms")
    """

    def __init__(self, max_history_hours: int = 24):
        self._stats: dict[str, PerformanceStats] = defaultdict(PerformanceStats)
        self._hourly_stats: dict[str, dict[str, PerformanceStats]] = defaultdict(
            lambda: defaultdict(PerformanceStats)
        )
        self._max_history_hours = max_history_hours
        self._cleanup_task: asyncio.Task | None = None
        self.logger = logging.getLogger("PerformanceTracker")

    def start_timer(self) -> float:
        """Start a timer, returns start time."""
        return time.perf_counter()

    def record(self, operation: str, start_time: float) -> float:
        """Record timing for an operation. Returns duration."""
        duration = time.perf_counter() - start_time
        self._stats[operation].record(duration)

        # Also track hourly stats
        hour_key = datetime.now().strftime("%Y-%m-%d-%H")
        self._hourly_stats[operation][hour_key].record(duration)

        self.logger.debug("%s: %.2fms", operation, duration * 1000)
        return duration

    class _TimerContext:
        """Context manager for timing operations."""

        def __init__(self, tracker: PerformanceTracker, operation: str):
            self.tracker = tracker
            self.operation = operation
            self.start_time = 0.0
            self.duration = 0.0

        def __enter__(self):
            self.start_time = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.duration = self.tracker.record(self.operation, self.start_time)
            return False

    def measure(self, operation: str) -> _TimerContext:
        """Context manager for measuring operation time."""
        return self._TimerContext(self, operation)

    def get_stats(self, operation: str) -> dict[str, Any]:
        """Get statistics for an operation."""
        if operation not in self._stats:
            return {"count": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0}
        return self._stats[operation].to_dict()

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all operations."""
        return {op: stats.to_dict() for op, stats in self._stats.items()}

    def get_hourly_trend(self, operation: str, hours: int = 24) -> list[dict[str, Any]]:
        """Get hourly performance trend for last N hours."""
        if operation not in self._hourly_stats:
            return []

        trends = []
        for i in range(hours - 1, -1, -1):
            hour = datetime.now() - timedelta(hours=i)
            hour_key = hour.strftime("%Y-%m-%d-%H")
            if hour_key in self._hourly_stats[operation]:
                stats = self._hourly_stats[operation][hour_key]
                trends.append(
                    {
                        "hour": hour_key,
                        "count": stats.count,
                        "avg_ms": round(stats.avg_time * 1000, 2),
                        "p95_ms": round(stats.p95 * 1000, 2),
                    }
                )
            else:
                trends.append({"hour": hour_key, "count": 0, "avg_ms": 0, "p95_ms": 0})

        return trends

    def cleanup_old_stats(self) -> int:
        """Remove hourly stats older than max_history_hours."""
        cutoff = datetime.now() - timedelta(hours=self._max_history_hours)
        cutoff_key = cutoff.strftime("%Y-%m-%d-%H")
        removed = 0

        for operation in self._hourly_stats:
            old_keys = [k for k in self._hourly_stats[operation] if k < cutoff_key]
            for key in old_keys:
                del self._hourly_stats[operation][key]
                removed += 1

        if removed > 0:
            self.logger.info("Cleaned up %d old performance records", removed)

        return removed

    def start_cleanup_task(self, interval: float = 3600.0) -> None:
        """Start background task to periodically clean up old stats.

        Args:
            interval: Cleanup interval in seconds (default: 1 hour)
        """
        async def _cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    self.cleanup_old_stats()
                except asyncio.CancelledError:
                    break

        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(_cleanup_loop())
            self.logger.info("Started periodic cleanup task (interval: %.0fs)", interval)

    async def stop_cleanup_task(self) -> None:
        """Stop the cleanup background task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None
            self.logger.info("Stopped periodic cleanup task")

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all tracked operations."""
        summary = {
            "operations": len(self._stats),
            "total_measurements": sum(s.count for s in self._stats.values()),
            "stats": {},
        }

        for op, stats in self._stats.items():
            summary["stats"][op] = {
                "count": stats.count,
                "avg_ms": round(stats.avg_time * 1000, 2),
                "p50_ms": round(stats.p50 * 1000, 2),
                "p95_ms": round(stats.p95 * 1000, 2),
                "p99_ms": round(stats.p99 * 1000, 2),
            }

        return summary


# Global performance tracker instance
perf_tracker = PerformanceTracker()


def track_performance(operation: str):
    """Decorator to track function performance."""

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with perf_tracker.measure(operation):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with perf_tracker.measure(operation):
                return func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
