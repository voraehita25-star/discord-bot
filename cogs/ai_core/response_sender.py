"""
Backward compatibility re-export for response_sender module.
This file re-exports from response/ subdirectory.
"""

from .response.response_sender import (
    ResponseSender,
    SendResult,
    response_sender,
    CHARACTER_TAG_PATTERN,
    URL_PATTERN,
    MENTION_PATTERN,
)

# Alias for backward compatibility
PATTERN_CHARACTER_TAG = CHARACTER_TAG_PATTERN

__all__ = [
    "ResponseSender",
    "SendResult",
    "response_sender",
    "PATTERN_CHARACTER_TAG",
    "CHARACTER_TAG_PATTERN",
    "URL_PATTERN",
    "MENTION_PATTERN",
]
