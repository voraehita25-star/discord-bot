"""
Core Module - Performance, Message Queue, and Context Building.
"""

from .performance import (
    PerformanceTracker,
    RequestDeduplicator,
    performance_tracker,
    request_deduplicator,
    PERFORMANCE_SAMPLES_MAX,
)
from .message_queue import MessageQueue, PendingMessage, message_queue
from .context_builder import AIContext, ContextBuilder, context_builder

__all__ = [
    "PerformanceTracker",
    "RequestDeduplicator",
    "performance_tracker",
    "request_deduplicator",
    "PERFORMANCE_SAMPLES_MAX",
    "MessageQueue",
    "PendingMessage",
    "message_queue",
    "AIContext",
    "ContextBuilder",
    "context_builder",
]
