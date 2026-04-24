"""
Core Module - Performance, Message Queue, and Context Building.
"""

from .context_builder import AIContext, ContextBuilder, context_builder
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
    "AIContext",
    "ContextBuilder",
    "MessageQueue",
    "PendingMessage",
    "PerformanceTracker",
    "RequestDeduplicator",
    "context_builder",
    "message_queue",
    "performance_tracker",
    "request_deduplicator",
]
