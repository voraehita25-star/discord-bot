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
# Claude's document content block accepts PDF natively. Older SDK versions
# may not expose DocumentBlockParam, so we keep the shape as a plain dict
# typed as ``Any`` in the public alias to stay version-agnostic.
type ClaudeContentBlockParam = TextBlockParam | ImageBlockParam | dict[str, Any]

CLAUDE_IMAGE_MEDIA_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }
)


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


def build_claude_pdf_document_block(
    data: Any,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Build a Claude `document` content block for a base64 PDF.

    The PDF is forwarded to Anthropic unchanged so Claude's PDF pipeline can
    parse text layer AND interpret images/tables/figures inside the PDF
    natively. Cap at 32 MB / 100 pages is enforced upstream — we don't
    re-validate here because the SDK also surfaces 413 errors on overlarge
    uploads.

    ``title`` is optional — when supplied, the Anthropic API shows it in
    citations and error messages, which keeps logs readable when multiple
    PDFs are attached.
    """
    block: dict[str, Any] = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": str(data),
        },
    }
    if title:
        block["title"] = str(title)[:200]
    return block


def build_claude_text_document_block(
    text: Any,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Build a Claude `document` content block for a plain-text file.

    Preferred over inlining text into a TextBlock when you want Claude to
    treat it as a distinct reference document (better for RAG-style uses
    and citation tracking). For short snippets, a regular TextBlock is
    cheaper; for full file attachments a document block keeps the prompt
    structure cleaner.
    """
    block: dict[str, Any] = {
        "type": "document",
        "source": {
            "type": "text",
            "media_type": "text/plain",
            "data": str(text),
        },
    }
    if title:
        block["title"] = str(title)[:200]
    return block


def build_claude_message(
    role: ClaudeMessageRole,
    content: str | list[ClaudeContentBlockParam],
) -> MessageParam:
    """Build a typed Claude message param.

    The cast to ``Any`` silences a mypy false-positive: the Anthropic SDK's
    ``MessageParam.content`` is a strict union of TypedDicts, and our mixed
    list of TextBlockParam / ImageBlockParam / document dicts (PDF+text) is
    shape-compatible but not type-compatible. At runtime the SDK accepts it
    without issue — PDF + text document blocks go through Anthropic's API as
    regular content blocks.
    """
    return {"role": role, "content": cast(Any, content)}


def build_single_user_text_messages(text: Any) -> list[MessageParam]:
    """Build a minimal Claude message list for one user prompt."""
    return [build_claude_message("user", str(text))]


def _ephemeral_cache_control() -> dict[str, str]:
    """Return the Anthropic ``ephemeral`` cache-control marker.

    Using a helper keeps the literal out of the call sites and makes it easy to
    swap for future Anthropic cache modes without hunting dict literals.
    """
    return {"type": "ephemeral"}


def build_split_cached_system_prompt(
    stable_text: str,
    volatile_text: str = "",
) -> list[dict[str, Any]]:
    """Wrap a system prompt as ``stable_text`` (cached) + ``volatile_text`` (uncached).

    Use when the system prompt has a small per-turn piece — typically the
    current timestamp — that would otherwise invalidate the entire prompt
    cache for every request. The stable block keeps its ``cache_control:
    ephemeral`` marker so Anthropic reuses it for ~5 minutes; the volatile
    block is left uncached and rebuilt each turn. The order matters:
    Anthropic caches the *prefix* up to the marker, so the stable block
    must come first for the cache to apply.

    When ``volatile_text`` is empty this returns a single cached block, so
    callers can pass an optional volatile suffix without branching on its
    presence.
    """
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": stable_text, "cache_control": _ephemeral_cache_control()},
    ]
    if volatile_text:
        blocks.append({"type": "text", "text": volatile_text})
    return blocks
