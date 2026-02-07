"""
Input Sanitization Module.
Provides functions to sanitize user input for safe use in Discord operations.
Protects against malicious input in AI-controlled operations.
"""

from __future__ import annotations

import re

# Regex patterns for validation
_SAFE_CHANNEL_NAME = re.compile(r"[^a-zA-Z0-9\-_\u0E00-\u0E7F\s]")
_SAFE_ROLE_NAME = re.compile(r"[<>@#&]")


def sanitize_channel_name(name: str, max_length: int = 100) -> str:
    """Sanitize channel name to prevent injection attacks.

    Args:
        name: Raw channel name from AI
        max_length: Maximum allowed length

    Returns:
        Sanitized channel name
    """
    # Remove potentially dangerous characters
    cleaned = _SAFE_CHANNEL_NAME.sub("", name)
    # Normalize whitespace to dashes (Discord channel format)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    # Remove consecutive dashes
    cleaned = re.sub(r"-+", "-", cleaned)
    # Limit length and remove leading/trailing dashes
    result = cleaned[:max_length].strip("-")
    return result or "untitled"


def sanitize_role_name(name: str, max_length: int = 100) -> str:
    """Sanitize role name to prevent mention injection.

    Args:
        name: Raw role name from AI
        max_length: Maximum allowed length

    Returns:
        Sanitized role name
    """
    # Remove characters that could be used for mention injection
    cleaned = _SAFE_ROLE_NAME.sub("", name)
    return cleaned.strip()[:max_length] or "unnamed-role"


def sanitize_message_content(content: str, max_length: int = 2000) -> str:
    """Sanitize message content for safe sending.

    Args:
        content: Raw message content
        max_length: Maximum allowed length

    Returns:
        Sanitized message content
    """
    # Handle None input
    if content is None:
        return ""

    # Escape dangerous mentions by inserting zero-width space
    content = content.replace("@everyone", "@\u200beveryone")
    content = content.replace("@here", "@\u200bhere")

    # Limit length
    if len(content) > max_length:
        content = content[: max_length - 3] + "..."
    return content


__all__ = ["sanitize_channel_name", "sanitize_message_content", "sanitize_role_name"]
