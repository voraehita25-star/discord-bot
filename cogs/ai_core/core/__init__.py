"""
Core Module - Performance and Message Queue.
"""

from .message_queue import MessageQueue, PendingMessage, message_queue
from .performance import (
    PERFORMANCE_SAMPLES_MAX,
    PerformanceTracker,
    RequestDeduplicator,
    performance_tracker,
    request_deduplicator,
)

__all__ = [
    "PERFORMANCE_SAMPLES_MAX",
    "MessageQueue",
    "PendingMessage",
    "PerformanceTracker",
    "RequestDeduplicator",
    "message_queue",
    "performance_tracker",
    "request_deduplicator",
]
