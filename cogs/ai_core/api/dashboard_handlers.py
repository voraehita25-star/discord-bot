"""
Dashboard CRUD handlers for conversations, memories, and profiles.

These are standalone async functions called by the main WebSocket server.
"""

from __future__ import annotations

import asyncio
import logging
import re
from itertools import islice
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

MAX_PREFERENCE_KEYS = 50  # Prevent DoS via unbounded dict keys
# Edit-message content cap. Mirrors ``WSDashboardServer.MAX_CONTENT_LENGTH``
# so an edit of a previously-sent long message hits the same limit as the
# original send. Kept in this module too because the WS handlers don't
# import the server class — and a hardcoded literal in two places drifts
# silently when one gets bumped.
MAX_EDIT_CONTENT_LENGTH = 200_000

# Unicode bidirectional override marks that ``str.isprintable`` returns
# True for (U+200E/U+200F LRM/RLM, U+202A-U+202E LRE/RLE/PDF/LRO/RLO,
# U+2066-U+2069 LRI/RLI/FSI/PDI). When rendered in a conversation title
# they can visually reorder adjacent text, letting a malicious title
# spoof another conversation's name in the sidebar. Frozen at module
# scope so the rename handler doesn't rebuild it on every call.
_BIDI_MARKS = frozenset(
    chr(c)
    for c in (
        # Bidi overrides (the original set)
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        # Invisible / zero-width chars that ``str.isprintable()`` returns
        # True for but visually hide content (homoglyph-with-padding
        # attacks against display rendering).
        0x200B,  # ZERO WIDTH SPACE
        0x200C,  # ZERO WIDTH NON-JOINER
        0x200D,  # ZERO WIDTH JOINER
        0x2060,  # WORD JOINER
        0xFEFF,  # ZERO WIDTH NO-BREAK SPACE (BOM)
    )
)

from .dashboard_common import invalidate_user_context_cache, sanitize_profile_field
from .dashboard_config import (
    CLAUDE_CONTEXT_WINDOW,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    DEFAULT_AI_PROVIDER,
    GEMINI_CONTEXT_WINDOW,
)

logger = logging.getLogger(__name__)


# Lazy import Database to avoid circular imports
def _get_db():
    from .dashboard_config import Database

    return Database()


# Per-conversation regenerate lock — held across the
# ``update_dashboard_message`` / ``delete_dashboard_messages_after``
# pair so a concurrent send can't slip a new message into the gap and
# get wiped by the delete-after-pivot. Capped to bound dict growth in
# long-running deployments; LRU eviction on first miss past the cap.
_REGEN_LOCKS: dict[str, asyncio.Lock] = {}
_REGEN_LOCKS_MAX = 256


def _get_regen_lock(key: str) -> asyncio.Lock:
    lock = _REGEN_LOCKS.get(key)
    if lock is None:
        # Evict the oldest entry if we're at the cap. Plain dict is
        # insertion-ordered in CPython 3.7+, so ``next(iter(...))``
        # gives us the LRU candidate. Skip eviction if its lock is
        # held — releasing a held lock by GC would orphan waiters.
        if len(_REGEN_LOCKS) >= _REGEN_LOCKS_MAX:
            for candidate_key in list(_REGEN_LOCKS.keys()):
                candidate = _REGEN_LOCKS.get(candidate_key)
                if candidate is not None and not candidate.locked():
                    _REGEN_LOCKS.pop(candidate_key, None)
                    break
        lock = _REGEN_LOCKS.setdefault(key, asyncio.Lock())
    return lock


# ============================================================================
# Conversation handlers
# ============================================================================


async def handle_list_conversations(ws: WebSocketResponse) -> None:
    """List all dashboard conversations."""
    if not DB_AVAILABLE:
        await ws.send_json({"type": "conversations_list", "conversations": []})
        return

    try:
        db = _get_db()
        conversations = await db.get_dashboard_conversations()
        await ws.send_json(
            {
                "type": "conversations_list",
                "conversations": conversations,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to list conversations"}
        )


async def handle_load_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Load a specific conversation with messages."""
    conversation_id = data.get("id")

    if not conversation_id:
        await ws.send_json(
            {"type": "error", "code": "MISSING_ID", "message": "Missing conversation ID"}
        )
        return

    # Validate conversation_id format (defense in depth - DB also validates)
    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"}
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {"type": "error", "code": "DB_UNAVAILABLE", "message": "Database not available"}
        )
        return

    try:
        db = _get_db()
        conversation = await db.get_dashboard_conversation(conversation_id)
        messages = await db.get_dashboard_messages(conversation_id)

        if not conversation:
            await ws.send_json(
                {"type": "error", "code": "CONV_NOT_FOUND", "message": "Conversation not found"}
            )
            return

        preset = DASHBOARD_ROLE_PRESETS.get(
            conversation.get("role_preset", "general"), DASHBOARD_ROLE_PRESETS["general"]
        )

        # Estimate tokens from conversation history for context window indicator
        total_chars = len(preset.get("system_instruction", ""))
        for msg in messages:
            content = msg.get("content") or ""
            total_chars += len(content)
            thinking = msg.get("thinking") or ""
            total_chars += len(thinking)
        estimated_tokens = max(1, total_chars // 3)

        ai_provider = conversation.get("ai_provider", DEFAULT_AI_PROVIDER)
        context_window = CLAUDE_CONTEXT_WINDOW if ai_provider == "claude" else GEMINI_CONTEXT_WINDOW

        # Include the conversation's tags (#22) so the UI can render chips immediately.
        tags = await db.get_conversation_tags(conversation_id)

        await ws.send_json(
            {
                "type": "conversation_loaded",
                "conversation": {
                    **conversation,
                    "role_name": preset["name"],
                    "role_emoji": preset["emoji"],
                    "role_color": preset["color"],
                    "tags": tags,
                },
                "messages": messages,
                "token_usage": {
                    "input_tokens": estimated_tokens,
                    "output_tokens": 0,
                    "total_tokens": estimated_tokens,
                    "context_window": context_window,
                },
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to load conversation"}
        )


async def handle_delete_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a conversation."""
    conversation_id = data.get("id")

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_DELETE",
                "message": "Cannot delete: missing ID or DB unavailable",
            }
        )
        return

    # Validate conversation_id format
    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"}
        )
        return

    try:
        db = _get_db()
        await db.delete_dashboard_conversation(conversation_id)
        # Also delete the Claude Code CLI session .jsonl for this conversation,
        # if the CLI backend ever handled it. No-op for conversations created
        # under CLAUDE_BACKEND=api (session map never got populated) — hence
        # the broad try/except so a cleanup failure never blocks the reply.
        try:
            from .dashboard_chat_claude_cli import delete_session_file as _delete_cli_session

            await _delete_cli_session(conversation_id)
        except Exception:
            logger.exception("Claude CLI session cleanup failed for %s", conversation_id)
        await ws.send_json(
            {
                "type": "conversation_deleted",
                "id": conversation_id,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to delete conversation"}
        )


async def handle_star_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle star status of a conversation."""
    conversation_id = data.get("id")
    starred = data.get("starred", True)

    logger.info("Star conversation request: id=%s, starred=%s", conversation_id, starred)

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_UPDATE",
                "message": "Cannot update: missing ID or DB unavailable",
            }
        )
        return

    # Validate conversation_id format
    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"}
        )
        return

    try:
        db = _get_db()
        result = await db.update_dashboard_conversation_star(conversation_id, starred)
        logger.info("Star update result: %s", result)
        await ws.send_json(
            {
                "type": "conversation_starred",
                "id": conversation_id,
                "starred": starred,
            }
        )
        logger.info("Sent conversation_starred response")
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to star conversation"}
        )


async def handle_rename_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Rename a conversation."""
    conversation_id = data.get("id")
    # Coerce to string before strip; a non-string payload (number, null, list)
    # would otherwise crash on .strip() and tear down the WS connection.
    raw_title = data.get("title", "")
    new_title = str(raw_title).strip() if raw_title is not None else ""

    if not conversation_id or not new_title or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_RENAME",
                "message": "Cannot rename: missing ID, title, or DB unavailable",
            }
        )
        return

    # Validate conversation_id format
    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"}
        )
        return

    if len(new_title) > 200:
        await ws.send_json(
            {
                "type": "error",
                "code": "TITLE_TOO_LONG",
                "message": "Title too long (max 200 characters)",
            }
        )
        return
    # Strip non-printable characters (null bytes, control chars, etc.)
    # AND Unicode bidirectional override marks (see ``_BIDI_MARKS`` at
    # module scope for the rationale).
    new_title = "".join(
        ch for ch in new_title if ch.isprintable() and ch not in _BIDI_MARKS
    ).strip()
    if not new_title:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_TITLE",
                "message": "Title contains only invalid characters",
            }
        )
        return

    try:
        db = _get_db()
        await db.rename_dashboard_conversation(conversation_id, new_title)
        await ws.send_json(
            {
                "type": "conversation_renamed",
                "id": conversation_id,
                "title": new_title,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to rename conversation"}
        )


async def handle_export_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Export a conversation to JSON."""
    conversation_id = data.get("id")
    export_format = data.get("format", "json")

    # Validate export_format
    valid_formats = ("json", "markdown", "html", "txt")
    if export_format not in valid_formats:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_FORMAT",
                "message": f"Invalid export format. Use one of: {', '.join(valid_formats)}",
            }
        )
        return

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_EXPORT",
                "message": "Cannot export: missing ID or DB unavailable",
            }
        )
        return

    # Validate conversation_id format
    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"}
        )
        return

    try:
        db = _get_db()
        export_data = await db.export_dashboard_conversation(conversation_id, export_format)
        await ws.send_json(
            {
                "type": "conversation_exported",
                "id": conversation_id,
                "format": export_format,
                "data": export_data,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to export conversation"}
        )


# ============================================================================
# Message edit/delete handlers
# ============================================================================


async def handle_edit_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Edit a message's content. If regenerate=True for user messages, deletes all subsequent messages."""
    message_id = data.get("message_id")
    raw_content = data.get("content", "")
    # Coerce content to string before strip; a non-string payload (number,
    # list) would otherwise crash on .strip().
    content = str(raw_content).strip() if raw_content is not None else ""
    regenerate = data.get("regenerate", False)
    conversation_id = data.get("conversation_id")

    # Reject unhashable conversation_id up front. The previous code used
    # it as a key in ``_REGEN_LOCKS`` via ``_get_regen_lock`` — a dict
    # payload like ``{"$": "system"}`` would raise TypeError when hashed
    # and fall into the broad except as INTERNAL_ERROR.
    if conversation_id is not None and not isinstance(conversation_id, (str, int)):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID type"}
        )
        return

    if not message_id or not content or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_EDIT",
                "message": "Cannot edit: missing data or DB unavailable",
            }
        )
        return

    # Enforce content size limit. Matches the fresh-message limit in
    # WSDashboardServer.MAX_CONTENT_LENGTH so a user editing a long
    # message they previously sent doesn't hit a stricter cap on edit.
    if len(content) > MAX_EDIT_CONTENT_LENGTH:
        await ws.send_json(
            {
                "type": "error",
                "code": "CONTENT_TOO_LONG",
                "message": (f"Content too long (max {MAX_EDIT_CONTENT_LENGTH:,} characters)"),
            }
        )
        return

    # Validate message_id is numeric
    try:
        message_id_int = int(message_id)
    except (ValueError, TypeError):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid message ID"})
        return

    try:
        db = _get_db()
        # Hold a per-conversation lock across update + delete so a
        # concurrent send (from a second dashboard window or a tab
        # reload that resends the same edit) can't insert a new message
        # between ``update_dashboard_message`` and
        # ``delete_dashboard_messages_after`` — the new message would
        # otherwise be wiped by the delete-after-pivot, surprising the
        # user.
        regen_lock_key = conversation_id or f"_msg:{message_id_int}"
        async with _get_regen_lock(regen_lock_key):
            # Pass conversation_id to enforce ownership — without this the
            # client could edit any message ID in any conversation by guessing.
            updated = await db.update_dashboard_message(
                message_id_int,
                content,
                expected_conversation_id=conversation_id,
            )
            if not updated:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "MSG_NOT_FOUND",
                        "message": "Message not found",
                    }
                )
                return

            deleted_count = 0
            if regenerate and conversation_id:
                deleted_count = await db.delete_dashboard_messages_after(
                    conversation_id, message_id_int
                )

        # Edit/regenerate diverges the DB from Claude's server-side --resume
        # transcript. If we leave the CLI session id in place, the next turn
        # would --resume the old jsonl and replay the pre-edit content as if
        # nothing changed. Wipe the session pointer + jsonl so the next CLI
        # turn starts fresh from the current DB state via the prompt builder's
        # `# Conversation so far` block. No-op in API mode.
        if conversation_id:
            try:
                from .dashboard_chat_claude_cli import delete_session_file as _delete_cli_session

                await _delete_cli_session(conversation_id)
            except Exception:
                logger.exception("Claude CLI session reset failed for %s", conversation_id)

        await ws.send_json(
            {
                "type": "message_edited",
                "message_id": message_id,
                "content": content,
                "conversation_id": conversation_id,
                "regenerate": regenerate,
                "deleted_after": deleted_count,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to edit message"}
        )


async def handle_pin_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle the pin state of a dashboard message."""
    message_id = data.get("message_id")
    pinned = bool(data.get("pinned", True))

    if not message_id or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_PIN",
                "message": "Cannot pin: missing ID or DB unavailable",
            }
        )
        return

    try:
        message_id_int = int(message_id)
    except (ValueError, TypeError):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid message ID"})
        return

    try:
        db = _get_db()
        updated = await db.update_dashboard_message_pin(message_id_int, pinned)
        if not updated:
            await ws.send_json(
                {"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"}
            )
            return
        await ws.send_json(
            {
                "type": "message_pinned",
                "message_id": message_id,
                "pinned": pinned,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to pin message"}
        )


async def handle_like_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle the 'liked' flag on a dashboard message (#20b)."""
    message_id = data.get("message_id")
    liked = bool(data.get("liked", True))

    if not message_id or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_LIKE",
                "message": "Cannot like: missing ID or DB unavailable",
            }
        )
        return

    try:
        message_id_int = int(message_id)
    except (ValueError, TypeError):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid message ID"})
        return

    try:
        db = _get_db()
        updated = await db.update_dashboard_message_liked(message_id_int, liked)
        if not updated:
            await ws.send_json(
                {"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"}
            )
            return
        await ws.send_json(
            {
                "type": "message_liked",
                "message_id": message_id,
                "liked": liked,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to like message"}
        )


# ============================================================================
# Conversation tag handlers (#22)
# ============================================================================

_VALID_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
# Compile once at module load — ``_validate_conversation_id`` is called on
# every WS message that carries a conv id (chat send, edit, delete, tag
# add/remove, document attach, etc.), so even re's internal cache lookup
# is avoidable overhead at that scale.
_CONVERSATION_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}\Z")


def _validate_conversation_id(conversation_id: Any) -> bool:
    return isinstance(conversation_id, str) and bool(_CONVERSATION_ID_RE.match(conversation_id))


async def handle_add_conversation_tag(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Attach a tag to a conversation."""
    conversation_id = data.get("conversation_id")
    # ``data.get("tag")`` may return non-strings (number, list, dict) which
    # would crash ``.strip()`` with AttributeError. Coerce to string up
    # front so the validation regex below produces a clean rejection
    # rather than an opaque INTERNAL_ERROR via the broad except handler.
    raw_tag = data.get("tag")
    tag = str(raw_tag).strip().lower() if raw_tag is not None else ""

    if not DB_AVAILABLE or not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID"}
        )
        return
    if not _VALID_TAG_RE.match(tag):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_TAG",
                "message": "Tag must be 1-64 chars, lowercase alphanumerics + _ - (must start with a letter or digit)",
            }
        )
        return

    try:
        db = _get_db()
        added = await db.add_conversation_tag(conversation_id, tag)
        tags = await db.get_conversation_tags(conversation_id)
        await ws.send_json(
            {
                "type": "conversation_tagged",
                "conversation_id": conversation_id,
                "tag": tag,
                "added": added,
                "tags": tags,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to add tag"}
        )


async def handle_remove_conversation_tag(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Detach a tag from a conversation."""
    conversation_id = data.get("conversation_id")
    raw_tag = data.get("tag")
    tag = str(raw_tag).strip().lower() if raw_tag is not None else ""

    if not DB_AVAILABLE or not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID"}
        )
        return
    if not tag:
        await ws.send_json({"type": "error", "code": "INVALID_TAG", "message": "Tag required"})
        return

    try:
        db = _get_db()
        removed = await db.remove_conversation_tag(conversation_id, tag)
        tags = await db.get_conversation_tags(conversation_id)
        await ws.send_json(
            {
                "type": "conversation_untagged",
                "conversation_id": conversation_id,
                "tag": tag,
                "removed": removed,
                "tags": tags,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to remove tag"}
        )


async def handle_list_all_tags(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Return every distinct tag in the DB with its usage count. Powers a tag-picker UI."""
    del data  # no input
    if not DB_AVAILABLE:
        await ws.send_json({"type": "all_tags", "tags": []})
        return
    try:
        db = _get_db()
        tags = await db.list_all_conversation_tags()
        await ws.send_json({"type": "all_tags", "tags": tags})
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to list tags"}
        )


async def handle_delete_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a message. If delete_pair=True, also deletes the paired response (next message)."""
    message_id = data.get("message_id")
    delete_pair = data.get("delete_pair", False)
    pair_message_id = data.get("pair_message_id")
    # Conversation scope: callers that have already authenticated a
    # conversation context should pass it so a forged ``message_id`` from
    # an unrelated conversation can't be deleted via this handler. Older
    # clients that don't send it fall through to an unscoped delete (no
    # behaviour change), but the dashboard's TS client always sends it.
    expected_conv_raw = data.get("conversation_id")
    expected_conv: str | None = None
    if isinstance(expected_conv_raw, str) and _validate_conversation_id(expected_conv_raw):
        expected_conv = expected_conv_raw

    if not message_id or not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "CANNOT_DELETE",
                "message": "Cannot delete: missing ID or DB unavailable",
            }
        )
        return

    # Validate message_id (and the optional pair) up front so a non-numeric
    # client payload yields a clear 400-style error rather than being caught
    # by the broad Exception handler below as INTERNAL_ERROR.
    try:
        message_id_int = int(message_id)
    except (TypeError, ValueError):
        await ws.send_json(
            {"type": "error", "code": "BAD_REQUEST", "message": "Invalid message ID"}
        )
        return
    pair_message_id_int: int | None = None
    if delete_pair and pair_message_id:
        try:
            pair_message_id_int = int(pair_message_id)
        except (TypeError, ValueError):
            await ws.send_json(
                {"type": "error", "code": "BAD_REQUEST", "message": "Invalid pair message ID"}
            )
            return

    try:
        db = _get_db()
        conv_id = await db.delete_dashboard_message(
            message_id_int,
            expected_conversation_id=expected_conv,
        )
        if not conv_id:
            await ws.send_json(
                {"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"}
            )
            return

        # Delete paired message if requested. Defence-in-depth: the pair must
        # live in the SAME conversation as the primary message — otherwise a
        # caller knowing two unrelated message ids could delete one from each
        # conversation in a single request. ``conv_id`` was returned by the
        # primary delete above so we already have the authoritative scope.
        deleted_pair_id = None
        if pair_message_id_int is not None:
            pair_conv_id = await db.delete_dashboard_message(
                pair_message_id_int,
                expected_conversation_id=conv_id,
            )
            if pair_conv_id:
                deleted_pair_id = pair_message_id

        # Same divergence problem as edit: the DB now lacks messages that
        # Claude's --resume transcript still has, so the next CLI turn would
        # replay the deleted content. Drop the session pointer + jsonl.
        cli_cleanup_failed = False
        try:
            from .dashboard_chat_claude_cli import delete_session_file as _delete_cli_session

            await _delete_cli_session(conv_id)
        except Exception:
            cli_cleanup_failed = True
            logger.exception("Claude CLI session reset failed for %s", conv_id)

        # Tell the client when CLI cleanup failed so the dashboard can
        # surface a "next turn may replay deleted content; reload to
        # force a fresh session" hint. Previously the divergence was
        # silent — the user got "message deleted" success but their
        # next message looked like the bot had a memory bug.
        await ws.send_json(
            {
                "type": "message_deleted",
                "message_id": message_id,
                "pair_message_id": deleted_pair_id,
                "conversation_id": conv_id,
                "cli_session_diverged": cli_cleanup_failed,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to delete message"}
        )


# ============================================================================
# Profile handlers
# ============================================================================


async def handle_get_profile(ws: WebSocketResponse) -> None:
    """Get user profile."""
    if not DB_AVAILABLE:
        await ws.send_json({"type": "profile", "profile": {}})
        return

    try:
        db = _get_db()
        profile = await db.get_dashboard_user_profile()
        await ws.send_json(
            {
                "type": "profile",
                "profile": profile or {},
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to get profile"}
        )


def _sanitize_profile_field(value: str | None, max_length: int = 200) -> str | None:
    """Sanitize a profile text field.

    Delegates to ``dashboard_common.sanitize_profile_field`` so the chat
    path and the profile-save path use identical defenses (NFKC
    normalisation, control-char strip, prompt-injection word filter).
    Without this, a user could store a ``display_name`` containing
    Unicode lookalikes / zalgo / mathematical-bold "system" that bypass
    the prompt-injection filter when the name is later rendered into
    the model's context.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = sanitize_profile_field(value, max_len=max_length)
    return cleaned or None


async def handle_list_conversation_documents(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """List all documents (PDF / text / code) attached in a specific conversation.

    Returns metadata only — ``extracted_text`` is omitted to keep the frame
    small. The chat-header "📎 Files" panel renders filename + kind + size +
    date from this payload; if the user wants to see full contents, they
    ask the AI ("what's in character.pdf?").
    """
    conversation_id = data.get("conversation_id")
    if not conversation_id or not isinstance(conversation_id, str):
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_ID",
                "message": "Missing conversation ID",
            }
        )
        return
    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid conversation ID format",
            }
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "conversation_documents",
                "conversation_id": conversation_id,
                "documents": [],
            }
        )
        return

    try:
        db = _get_db()
        # Metadata-only listing + explicit conversation scope. We can't use
        # ``list_document_memories`` (no scope arg) nor ``get_document_memories``
        # (returns extracted_text — wastes bandwidth); the query here picks
        # the middle ground.
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT id, filename, file_kind, char_count, page_count, created_at
                   FROM dashboard_document_memories
                   WHERE source_conversation_id = ?
                   ORDER BY created_at DESC""",
                (conversation_id,),
            )
            rows = await cursor.fetchall()
        documents = [
            {
                "id": r[0],
                "filename": r[1],
                "file_kind": r[2],
                "char_count": r[3],
                "page_count": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
        await ws.send_json(
            {
                "type": "conversation_documents",
                "conversation_id": conversation_id,
                "documents": documents,
            }
        )
    except Exception:
        logger.exception("Failed to list conversation documents")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to list documents",
            }
        )


async def handle_delete_document_memory(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a single document memory by id.

    Frontend sends ``{type: 'delete_document_memory', id: <int>,
    conversation_id: <str>}``. We verify the id belongs to the stated
    conversation before deleting — defense against a compromised client
    nuking documents from a different conversation by sending a fabricated id.
    """
    raw_id = data.get("id")
    conversation_id = data.get("conversation_id")
    if raw_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid document id",
            }
        )
        return
    try:
        memory_id = int(raw_id)
    except (TypeError, ValueError):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid document id",
            }
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
            }
        )
        return

    try:
        db = _get_db()
        # Scope check: only delete if the document belongs to the stated
        # conversation. Prevents cross-conversation deletion even if a
        # malicious client guesses or enumerates ids.
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT source_conversation_id FROM dashboard_document_memories WHERE id = ?",
                (memory_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            # Idempotent: missing id is treated as already-deleted. Matches
            # REST DELETE semantics and avoids confusing the UI when the
            # user clicks delete twice quickly.
            await ws.send_json(
                {
                    "type": "document_memory_deleted",
                    "id": memory_id,
                    "conversation_id": conversation_id,
                }
            )
            return
        owner = row[0]
        # Three-way scope rule:
        #   - owner set + matches conversation_id: allowed
        #   - owner set + different conversation_id: forbidden
        #   - owner None (global doc): only allowed when caller is also
        #     acting globally (conversation_id None). Previously the
        #     ``owner and owner != conversation_id`` short-circuit treated
        #     ``owner=None`` as a wildcard — ANY conversation could delete
        #     global docs, which is an obvious privilege escalation.
        if owner is None and conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "Global document cannot be deleted from a conversation scope",
                }
            )
            return
        if owner and conversation_id and owner != conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "Document does not belong to this conversation",
                }
            )
            return
        await db.delete_document_memory(memory_id)
        # Drop cached user_context so the next AI turn rebuilds without this doc.
        # Use the document's owner conversation rather than the (possibly None)
        # ``conversation_id`` from the request — the doc may have been a global
        # one with no conversation scope, in which case ``owner`` is None and
        # we fall back to invalidating the request's conversation.
        invalidate_user_context_cache(owner or conversation_id)
        await ws.send_json(
            {
                "type": "document_memory_deleted",
                "id": memory_id,
                "conversation_id": conversation_id,
            }
        )
    except Exception:
        logger.exception("Failed to delete document memory")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to delete document",
            }
        )


async def handle_update_document_memory(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Update a document memory's filename and/or extracted text.

    Frontend sends ``{type: 'update_document_memory', id, conversation_id,
    filename?, extracted_text?}``. Either ``filename`` or ``extracted_text``
    (or both) must be provided — missing fields preserve the existing value.

    Same scope check as delete: the id must belong to ``conversation_id`` so
    a compromised client can't edit documents in a different conversation
    by fabricating an id.
    """
    raw_id = data.get("id")
    conversation_id = data.get("conversation_id")
    new_filename = data.get("filename")
    new_text = data.get("extracted_text")

    if raw_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid document id",
            }
        )
        return
    try:
        memory_id = int(raw_id)
    except (TypeError, ValueError):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid document id",
            }
        )
        return

    # Nothing to update? Treat as a no-op confirmation so the UI doesn't
    # need to special-case empty-patch submissions.
    if new_filename is None and new_text is None:
        await ws.send_json(
            {
                "type": "document_memory_updated",
                "id": memory_id,
                "conversation_id": conversation_id,
                "noop": True,
            }
        )
        return

    # Sanitise + cap incoming strings — mirrors the extractor's own caps so
    # we never persist something bigger than what ``extract_and_persist``
    # would have saved originally.
    sanitised_filename: str | None = None
    if new_filename is not None:
        if not isinstance(new_filename, str):
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_ARG",
                    "message": "filename must be a string",
                }
            )
            return
        # Basic filename cleanup: strip control chars AND path separators,
        # trim, cap length. The path-separator strip is defence-in-depth —
        # filenames are stored as display text and don't currently feed a
        # filesystem write path, but stripping ``/``, ``\`` and ``..``
        # sequences keeps that property safe against future code that does
        # use the value as a path component.
        sanitised_filename = (
            re.sub(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f/\\]",
                "",
                new_filename,
            )
            .replace("..", "")
            .strip()[:200]
        )
        if not sanitised_filename:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_ARG",
                    "message": "filename cannot be empty",
                }
            )
            return

    sanitised_text: str | None = None
    if new_text is not None:
        if not isinstance(new_text, str):
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_ARG",
                    "message": "extracted_text must be a string",
                }
            )
            return
        # Strip C0 controls except \t/\n; cap at same MAX_EXTRACTED_CHARS
        # used during first-upload extraction (500K chars). Users editing
        # a doc aren't allowed to persist more text than a fresh upload
        # could have.
        from .document_extractor import MAX_EXTRACTED_CHARS

        sanitised_text = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",
            "",
            new_text,
        )
        if len(sanitised_text) > MAX_EXTRACTED_CHARS:
            sanitised_text = sanitised_text[:MAX_EXTRACTED_CHARS]

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
            }
        )
        return

    try:
        db = _get_db()
        # Scope check: verify ownership before update, same pattern as delete.
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT source_conversation_id FROM dashboard_document_memories WHERE id = ?",
                (memory_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "NOT_FOUND",
                    "message": "Document not found",
                }
            )
            return
        owner = row[0]
        # Same three-way scope rule as the delete handler: a global doc
        # (owner=None) can only be modified by a global caller. See the
        # comment in handle_delete_document_memory for the rationale.
        if owner is None and conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "Global document cannot be modified from a conversation scope",
                }
            )
            return
        if owner and conversation_id and owner != conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "Document does not belong to this conversation",
                }
            )
            return

        updated = await db.update_document_memory(
            memory_id,
            filename=sanitised_filename,
            extracted_text=sanitised_text,
        )
        if not updated:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "NOT_FOUND",
                    "message": "Document not found",
                }
            )
            return

        # Doc text/filename changed — drop cached user_context so the next
        # turn rebuilds with the new content.
        invalidate_user_context_cache(owner or conversation_id)
        await ws.send_json(
            {
                "type": "document_memory_updated",
                "id": memory_id,
                "conversation_id": conversation_id,
                "filename": sanitised_filename,
                "char_count": len(sanitised_text) if sanitised_text is not None else None,
            }
        )
    except Exception:
        logger.exception("Failed to update document memory")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to update document",
            }
        )


async def handle_get_document_memory_content(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Fetch a single document memory's full extracted text for editing.

    ``list_conversation_documents`` deliberately omits ``extracted_text`` to
    keep the list response lean; when the user clicks "Edit" we need the
    full content, so this endpoint returns just one row with everything.
    Scope-checked by conversation_id like the other per-doc handlers.
    """
    raw_id = data.get("id")
    conversation_id = data.get("conversation_id")
    if raw_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid document id",
            }
        )
        return
    try:
        memory_id = int(raw_id)
    except (TypeError, ValueError):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid document id",
            }
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
            }
        )
        return

    try:
        db = _get_db()
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT id, filename, file_kind, extracted_text, char_count,
                          page_count, source_conversation_id, created_at
                   FROM dashboard_document_memories WHERE id = ?""",
                (memory_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "NOT_FOUND",
                    "message": "Document not found",
                }
            )
            return
        owner = row[6]
        # Same three-way scope rule as delete/update — globals can't be
        # read through a conversation context, only by global callers.
        if owner is None and conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "Global document cannot be read from a conversation scope",
                }
            )
            return
        if owner and conversation_id and owner != conversation_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "FORBIDDEN",
                    "message": "Document does not belong to this conversation",
                }
            )
            return
        await ws.send_json(
            {
                "type": "document_memory_content",
                "document": {
                    "id": row[0],
                    "filename": row[1],
                    "file_kind": row[2],
                    "extracted_text": row[3],
                    "char_count": row[4],
                    "page_count": row[5],
                    "source_conversation_id": row[6],
                    "created_at": row[7],
                },
            }
        )
    except Exception:
        logger.exception("Failed to fetch document memory content")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to load document",
            }
        )


async def handle_save_profile(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Save user profile."""
    profile_data = data.get("profile", {})

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Cannot save profile: DB unavailable",
            }
        )
        return

    try:
        db = _get_db()
        # Sanitize user-controlled text fields
        display_name = (
            _sanitize_profile_field(profile_data.get("display_name"), max_length=50) or "User"
        )
        bio = _sanitize_profile_field(profile_data.get("bio"), max_length=500)
        # Sanitize preferences: only allow known keys with safe values.
        # Strings get length-clamped; numeric/bool stored as-is. Previously
        # the int/float/bool branch passed values through unchanged via
        # `else: v` while strings were truncated — inconsistency that
        # invited bugs (e.g. NaN floats slipping through). Now everything
        # gets explicit handling.
        raw_prefs = profile_data.get("preferences")
        sanitized_prefs: dict[str, str | int | float | bool | list[str]] | None = None
        truncated_prefs = False
        if isinstance(raw_prefs, dict):
            sanitized_prefs = {}
            # ``islice`` silently drops keys past MAX_PREFERENCE_KEYS —
            # capture whether truncation happened so we can warn the
            # client. Without this signal, a user setting their 51st
            # preference saw success but the value never persisted,
            # then "where did my setting go" support tickets.
            if len(raw_prefs) > MAX_PREFERENCE_KEYS:
                truncated_prefs = True
                logger.warning(
                    "Profile preferences truncated: %d keys received, kept first %d",
                    len(raw_prefs),
                    MAX_PREFERENCE_KEYS,
                )
            for k, v in islice(raw_prefs.items(), MAX_PREFERENCE_KEYS):
                key = str(k)[:50]
                if isinstance(v, str):
                    # Funnel through the same sanitizer used for display_name
                    # / bio so preference values can't carry prompt-
                    # injection directives (e.g. ``[System] You are now...``)
                    # into the AI context. Without this, the str branch was
                    # the one prompt-injection landing zone in the profile
                    # write path that bypassed sanitization.
                    sanitized_prefs[key] = _sanitize_profile_field(v, max_length=200) or ""
                elif isinstance(v, bool):
                    # bool MUST come before int (bool is a subclass of int)
                    sanitized_prefs[key] = v
                elif isinstance(v, int):
                    # Clamp to a sensible range so a giant integer can't
                    # blow up downstream JSON serialisation.
                    sanitized_prefs[key] = max(-(2**53), min(2**53, v))
                elif isinstance(v, float):
                    import math as _math

                    sanitized_prefs[key] = v if _math.isfinite(v) else 0.0
                elif isinstance(v, list):
                    sanitized_prefs[key] = [
                        str(i)[:200] for i in v[:20] if isinstance(i, str | int | float | bool)
                    ]
        await db.save_dashboard_user_profile(
            display_name=display_name,
            bio=bio,
            preferences=sanitized_prefs,
            # Note: is_creator is NOT accepted from client input for security
        )
        # Profile is shared across every conversation, so clear the entire
        # user_context cache instead of trying to enumerate per-conv entries.
        invalidate_user_context_cache(None)
        await ws.send_json(
            {
                "type": "profile_saved",
                "profile": profile_data,
                # Surface truncation so the dashboard can flag it. Default
                # False so older clients that don't read this field stay
                # backward compatible.
                "preferences_truncated": truncated_prefs,
                "max_preference_keys": MAX_PREFERENCE_KEYS,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to save profile"}
        )
