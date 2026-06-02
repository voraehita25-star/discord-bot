"""
Input Sanitization Module.
Provides functions to sanitize user input for safe use in Discord operations.
Protects against malicious input in AI-controlled operations.
"""

from __future__ import annotations

import re
import unicodedata

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
    if not name:
        return "untitled"
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
    if not name:
        return "unnamed-role"
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

    # Escape dangerous mentions by inserting zero-width space.
    # NFKC normalisation handles compatibility decompositions like
    # full-width "\uff20" \u2192 "@" so the @everyone/@here regex below
    # catches them. NOTE: NFKC does NOT fold Latin/Cyrillic/Greek script
    # confusables (e.g. Cyrillic "\u0435" stays distinct from Latin "e"),
    # so a string like "@\u0435veryone" passes through unescaped. Discord
    # itself doesn't ping on confusables either, but be aware this is
    # NOT a confusables-defeating filter \u2014 only a width-fold one.
    content = unicodedata.normalize("NFKC", content)
    # Sanitize BEFORE truncation to avoid splitting escape sequences.
    # Idempotency guard: skip the substitution when a ZWSP is ALREADY
    # the next char after the ``@``. Without this, repeated sanitizer
    # passes (e.g. a value that's stored, fetched, and re-displayed)
    # accumulate ``\u200b`` chars: ``@everyone`` \u2192
    # ``@\u200beveryone`` \u2192 ``@\u200b\u200beveryone`` \u2192 \u2026 Use a
    # negative lookahead so the substitution only fires the first time.
    content = re.sub(r"@(?!\u200b)everyone", "@\u200beveryone", content, flags=re.IGNORECASE)
    content = re.sub(r"@(?!\u200b)here", "@\u200bhere", content, flags=re.IGNORECASE)

    # Escape role mentions (<@&ROLE_ID>) and user mentions (<@USER_ID>)
    # from AI output. Same idempotency guard via negative lookahead.
    content = re.sub(r"<@&(?!\u200b)(\d+)>", "<@&\u200b\\1>", content)
    content = re.sub(r"<@!?(?!\u200b)(\d+)>", "<@\u200b\\1>", content)

    # Limit length (after sanitization to preserve escape sequences).
    # Walk back from the slice point to the last non-combining
    # codepoint so a Thai cluster (base + tone marks) doesn't get split
    # mid-character — slicing inside the cluster renders as a stray
    # combining mark on the ``...`` ellipsis. ``unicodedata.combining``
    # returns 0 for the base char, non-zero for combining marks above
    # it; rewind until we land on a base. Cap the rewind so a degenerate
    # input full of combining marks doesn't truncate to nothing.
    if len(content) > max_length:
        cut = max_length - 3
        rewind_limit = max(0, cut - 16)
        while cut > rewind_limit and unicodedata.combining(content[cut]):
            cut -= 1
        content = content[:cut] + "..."
    return content


__all__ = ["sanitize_channel_name", "sanitize_message_content", "sanitize_role_name"]
