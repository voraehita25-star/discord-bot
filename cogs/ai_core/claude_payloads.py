"""Shared typed payload helpers for Claude SDK interactions."""

from __future__ import annotations

from typing import Any, Literal, cast

from anthropic.types.image_block_param import ImageBlockParam
from anthropic.types.message_param import MessageParam
from anthropic.types.text_block_param import TextBlockParam

type ClaudeMessageRole = Literal["user", "assistant"]
type ClaudeImageMediaType = Literal[
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
]
type ClaudeContentBlockParam = TextBlockParam | ImageBlockParam

CLAUDE_IMAGE_MEDIA_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
})


def normalize_claude_image_media_type(media_type: Any) -> ClaudeImageMediaType | None:
    """Return a Claude-supported image MIME type or None."""
    if isinstance(media_type, str) and media_type in CLAUDE_IMAGE_MEDIA_TYPES:
        return cast(ClaudeImageMediaType, media_type)
    return None


def build_claude_text_block(text: Any) -> TextBlockParam:
    """Build a typed Claude text block."""
    return {"type": "text", "text": str(text)}


def build_claude_base64_image_block(data: Any, media_type: Any) -> ImageBlockParam | None:
    """Build a typed Claude image block for supported base64 images."""
    normalized_media_type = normalize_claude_image_media_type(media_type)
    if normalized_media_type is None:
        return None

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": normalized_media_type,
            "data": str(data),
        },
    }


def build_claude_message(
    role: ClaudeMessageRole,
    content: str | list[ClaudeContentBlockParam],
) -> MessageParam:
    """Build a typed Claude message param."""
    return {"role": role, "content": content}


def build_single_user_text_messages(text: Any) -> list[MessageParam]:
    """Build a minimal Claude message list for one user prompt."""
    return [build_claude_message("user", str(text))]


def _ephemeral_cache_control() -> dict[str, str]:
    """Return the Anthropic ``ephemeral`` cache-control marker.

    Using a helper keeps the literal out of the call sites and makes it easy to
    swap for future Anthropic cache modes without hunting dict literals.
    """
    return {"type": "ephemeral"}


def build_cached_system_prompt(system_text: str) -> list[dict[str, Any]]:
    """Wrap a system prompt string into Anthropic's list form with prompt caching enabled.

    The system prompt is mostly static per preset/session (persona + role +
    memories), so marking it with ``cache_control: ephemeral`` lets Anthropic
    reuse the prefix for 5 minutes, dropping input-token cost by ~90% on
    cache hits.
    """
    return [{"type": "text", "text": system_text, "cache_control": _ephemeral_cache_control()}]


