"""
Performance Metrics Module
Handles performance tracking and statistics for AI processing steps.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..data.constants import PERFORMANCE_SAMPLES_MAX


class PerformanceTracker:
    """Tracks performance metrics for AI processing steps."""

    # Maximum number of tracked step types to prevent unbounded growth
    MAX_TRACKED_STEPS = 50

    def __init__(self) -> None:
        """Initialize the performance tracker."""
        self._metrics: dict[str, list[float]] = {
            "rag_search": [],
            "api_call": [],
            "streaming": [],
            "post_process": [],
            "total": [],
            "context_build": [],
            "response_send": [],
        }

    def record_timing(self, step: str, duration: float) -> None:
        """Record timing for a processing step.

        Args:
            step: Name of the processing step
            duration: Duration in seconds
        """
        if step not in self._metrics:
            # Prevent unbounded growth of step types
            if len(self._metrics) >= self.MAX_TRACKED_STEPS:
                logging.warning(
                    "⚠️ PerformanceTracker: Max steps (%d) reached, ignoring new step: %s",
                    self.MAX_TRACKED_STEPS,
                    step,
                )
                return
            self._metrics[step] = []

        metrics_list = self._metrics[step]

        # Keep only last PERFORMANCE_SAMPLES_MAX samples per step
        if len(metrics_list) >= PERFORMANCE_SAMPLES_MAX:
            metrics_list.pop(0)
        metrics_list.append(duration)

    def get_stats(self) -> dict[str, Any]:
        """Get performance statistics for all processing steps.

        Returns:
            Dictionary with statistics for each step
        """
        stats = {}
        for key, values in self._metrics.items():
            if values:
                stats[key] = {
                    "count": len(values),
                    "avg_ms": round(sum(values) / len(values) * 1000, 2),
                    "max_ms": round(max(values) * 1000, 2),
                    "min_ms": round(min(values) * 1000, 2),
                }
            else:
                stats[key] = {"count": 0, "avg_ms": 0, "max_ms": 0, "min_ms": 0}
        return stats

    def get_step_stats(self, step: str) -> dict[str, Any]:
        """Get statistics for a specific step.

        Args:
            step: Name of the processing step

        Returns:
            Dictionary with statistics for the step
        """
        values = self._metrics.get(step, [])
        if values:
            return {
                "count": len(values),
                "avg_ms": round(sum(values) / len(values) * 1000, 2),
                "max_ms": round(max(values) * 1000, 2),
                "min_ms": round(min(values) * 1000, 2),
            }
        return {"count": 0, "avg_ms": 0, "max_ms": 0, "min_ms": 0}

    def clear_metrics(self, step: str | None = None) -> None:
        """Clear performance metrics.

        Args:
            step: Specific step to clear, or None to clear all
        """
        if step is None:
            for key in self._metrics:
                self._metrics[key] = []
        elif step in self._metrics:
            self._metrics[step] = []

    def get_summary(self) -> str:
        """Get a human-readable summary of performance metrics.

        Returns:
            Formatted string with performance summary
        """
        stats = self.get_stats()
        lines = ["📊 Performance Summary:"]
        for step, data in stats.items():
            if data["count"] > 0:
                lines.append(
                    f"  {step}: avg={data['avg_ms']}ms, "
                    f"max={data['max_ms']}ms, "
                    f"samples={data['count']}"
                )
        return "\n".join(lines) if len(lines) > 1 else "No performance data available"


class RequestDeduplicator:
    """Handles request deduplication to prevent double-submit."""

    def __init__(self) -> None:
        """Initialize the request deduplicator."""
        self._pending_requests: dict[str, float] = {}  # request_key -> timestamp

    def is_duplicate(self, request_key: str) -> bool:
        """Check if a request is a duplicate.

        Args:
            request_key: Unique identifier for the request

        Returns:
            True if request is a duplicate
        """
        return request_key in self._pending_requests

    def add_request(self, request_key: str) -> None:
        """Add a request to the pending set.

        Args:
            request_key: Unique identifier for the request
        """
        self._pending_requests[request_key] = time.time()

    def remove_request(self, request_key: str) -> None:
        """Remove a request from the pending set.

        Args:
            request_key: Unique identifier for the request
        """
        self._pending_requests.pop(request_key, None)

    def cleanup(self, max_age: float = 60.0) -> int:
        """Clean up old pending requests to prevent memory leaks.

        Args:
            max_age: Maximum age in seconds before a request is considered stale

        Returns:
            Number of requests cleaned up
        """
        now = time.time()
        old_keys = [k for k, t in self._pending_requests.items() if now - t > max_age]
        for k in old_keys:
            del self._pending_requests[k]
        if old_keys:
            logging.debug("🧹 Cleaned up %d stale pending request keys", len(old_keys))
        return len(old_keys)

    def get_pending_count(self) -> int:
        """Get the number of pending requests.

        Returns:
            Number of pending requests
        """
        return len(self._pending_requests)

    @staticmethod
    def generate_key(channel_id: int, user_id: int, message: str) -> str:
        """Generate a unique request key.

        Args:
            channel_id: Channel ID
            user_id: User ID
            message: Message content

        Returns:
            Unique request key
        """
        msg_hash = hash(message[:50] if message else "")
        return f"{channel_id}:{user_id}:{msg_hash}"


# Module-level instances for easy access
performance_tracker = PerformanceTracker()
request_deduplicator = RequestDeduplicator()
