"""
Backward compatibility re-export for message_queue module.
This file re-exports from core/ subdirectory.
"""

from .core.message_queue import (
    MessageQueue,
    PendingMessage,
    message_queue,
)

__all__ = [
    "MessageQueue",
    "PendingMessage",
    "message_queue",
]
