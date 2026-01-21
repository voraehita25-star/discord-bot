"""
Backward compatibility re-export for response_sender module.
This file re-exports from response/ subdirectory.
"""

from .response.response_sender import (
    CHARACTER_TAG_PATTERN,
    MENTION_PATTERN,
    URL_PATTERN,
    ResponseSender,
    SendResult,
    response_sender,
)

# Alias for backward compatibility
PATTERN_CHARACTER_TAG = CHARACTER_TAG_PATTERN

__all__ = [
    "CHARACTER_TAG_PATTERN",
    "MENTION_PATTERN",
    "PATTERN_CHARACTER_TAG",
    "URL_PATTERN",
    "ResponseSender",
    "SendResult",
    "response_sender",
]
