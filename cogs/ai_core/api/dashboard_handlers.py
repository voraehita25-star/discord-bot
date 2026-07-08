"""
Dashboard CRUD handlers for conversations, memories, and profiles.

These are standalone async functions called by the main WebSocket server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from itertools import islice
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiohttp.web import WebSocketResponse

    from ..logic import ChatManager

MAX_PREFERENCE_KEYS = 50  # Prevent DoS via unbounded dict keys
# Edit-message content cap. Mirrors ``WSDashboardServer.MAX_CONTENT_LENGTH``
# so an edit of a previously-sent long message hits the same limit as the
# original send. Kept in this module too because the WS handlers don't
# import the server class — and a hardcoded literal in two places drifts
# silently when one gets bumped.
MAX_EDIT_CONTENT_LENGTH = 200_000

# Cumulative content budget for one ``ai_history_loaded`` reply. Rows are
# individually unbounded (the edit op above allows 200K chars/row, 2000 rows
# ≈ 400MB worst case), and the dashboard client silently DROPS any frame over
# 50MB (ws-client.ts MAX_MESSAGE_LENGTH) while ``ws.send_json`` serializes the
# whole payload synchronously on the event loop the Discord bot shares. ~20MB
# of content keeps the final JSON well under the client's cap and the
# serialization stall negligible.
MAX_HISTORY_RESPONSE_CHARS = 20_000_000


def _dumps_utf8(obj: Any) -> str:
    """json.dumps with ensure_ascii=False for the big-payload sends.

    aiohttp's default ``json.dumps`` escapes every non-ASCII char into a
    6-char ``\\uXXXX`` sequence, so a Thai-heavy payload that passes the
    20M-char budget above could still serialize to >50M chars on the wire and
    be silently dropped by the client (ws-client.ts measures the raw frame
    text against MAX_MESSAGE_LENGTH). With ensure_ascii=False the frame length
    stays ≈ the budgeted char count (WebSocket text frames are UTF-8 anyway),
    and as a bonus Thai history payloads shrink ~6x.
    """
    return json.dumps(obj, ensure_ascii=False)


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

from ..storage import (
    delete_message_by_row_id,
    edit_message_by_row_id,
    get_history_lock,
    restore_message_by_row,
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


# Per-conversation regenerate lock — serializes concurrent EDIT requests
# (double-click, tab resend). NOTE: update+delete atomicity against
# concurrent SEND paths (which never take this lock) is provided by the
# single-transaction ``edit_and_truncate_dashboard_message`` instead.
# Capped to bound dict growth in long-running deployments; LRU eviction
# on first miss past the cap.
_REGEN_LOCKS: dict[str, asyncio.Lock] = {}
_REGEN_LOCKS_MAX = 256


def _get_regen_lock(key: str) -> asyncio.Lock:
    lock = _REGEN_LOCKS.get(key)
    if lock is None:
        # Evict the oldest entry if we're at the cap. Plain dict is
        # insertion-ordered in CPython 3.7+, so ``next(iter(...))``
        # gives us the LRU candidate. Skip eviction if its lock is
        # held — releasing a held lock by GC would orphan waiters.
        # ``.locked()`` alone is NOT enough: right after release() there is
        # a window where locked() is False but a woken waiter hasn't resumed
        # yet — evicting then orphans that waiter and a later setdefault
        # mints a second lock for the same conversation, letting two edit
        # bodies run concurrently. Reuse the CLI module's waiter probe
        # (lazy import, matching this module's other imports from it).
        if len(_REGEN_LOCKS) >= _REGEN_LOCKS_MAX:
            from .dashboard_chat_claude_cli import _lock_has_pending_waiters

            for candidate_key in list(_REGEN_LOCKS.keys()):
                candidate = _REGEN_LOCKS.get(candidate_key)
                if (
                    candidate is not None
                    and not candidate.locked()
                    and not _lock_has_pending_waiters(candidate)
                ):
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

        # Fold this conversation's persistent document memories into the estimate
        # so the context-window bar reflects auto-injected docs ON OPEN, before any
        # real turn. build_user_context injects these every turn (dashboard_common
        # ~454-505); this pre-turn estimate previously omitted them, so attached
        # files looked "uncounted" (the meter counted only the chat history) until
        # the first send. Cap at the same MAX_INJECT_CHARS budget the prompt
        # builder enforces so a huge library can't inflate the bar past what is
        # actually injected. A real stream_end reading supersedes this estimate.
        doc_chars = 0
        try:
            async with db.get_connection() as conn:
                cur = await conn.execute(
                    "SELECT COALESCE(SUM(char_count), 0) "
                    "FROM dashboard_document_memories WHERE source_conversation_id = ?",
                    (conversation_id,),
                )
                row = await cur.fetchone()
                doc_chars = min(400_000, int(row[0] or 0))
        except Exception:
            logger.debug("Doc-memory token estimate skipped", exc_info=True)
            doc_chars = 0
        total_chars += doc_chars

        estimated_tokens = max(1, total_chars // 3)

        # Cumulative content budget (see MAX_HISTORY_RESPONSE_CHARS): the token
        # estimate above still sums the FULL history so the context-window
        # indicator is unchanged, but the WIRE payload is capped because the
        # dashboard client silently DROPS any frame over 50MB (ws-client.ts
        # MAX_MESSAGE_LENGTH). Iterate NEWEST-first so truncation drops the
        # OLDEST messages, then re-reverse to restore ascending order. Always
        # keep at least one message.
        budgeted: list[dict[str, Any]] = []
        budget = MAX_HISTORY_RESPONSE_CHARS
        truncated = False
        for msg in reversed(messages):
            size = len(msg.get("content") or "") + len(msg.get("thinking") or "")
            # Base64 image data-URLs ride along in the same frame and dominate
            # the wire size for image-heavy conversations (10MB decoded ≈ 13.3M
            # chars encoded, per message) — they MUST count against the budget
            # or the frame silently exceeds the client's 50MB drop cap and the
            # conversation permanently fails to open.
            for _img in msg.get("images") or []:
                if isinstance(_img, str):
                    size += len(_img)
            if budget - size < 0:
                if budgeted:
                    # An OLDER message pushed us over — drop it and everything
                    # older (newest-first iteration makes the drop the oldest).
                    truncated = True
                    break
                # The NEWEST message ALONE exceeds the frame budget. Shipping it
                # whole would overflow the client's 50MB hard-drop cap
                # (ws-client.ts MAX_MESSAGE_LENGTH), the client would silently
                # discard the frame, and the conversation would never open. The
                # base64 images dominate that size, so strip them from the WIRE
                # COPY only (the stored DB row is untouched) and leave a marker
                # so the bubble still renders — a degraded-but-openable
                # conversation beats an undeliverable frame. With no images to
                # strip (pathologically large text) there's nothing safe to trim
                # without corrupting the message, so ship it best-effort.
                if any(isinstance(_i, str) for _i in msg.get("images") or []):
                    _marker = "[image too large to display]"
                    _text = msg.get("content") or ""
                    budgeted.append(
                        {
                            **msg,
                            "images": [],
                            "content": f"{_text}\n\n{_marker}" if _text else _marker,
                        }
                    )
                else:
                    budgeted.append(msg)
                truncated = True
                break
            budget -= size
            budgeted.append(msg)
        budgeted.reverse()

        ai_provider = conversation.get("ai_provider", DEFAULT_AI_PROVIDER)
        context_window = CLAUDE_CONTEXT_WINDOW if ai_provider == "claude" else GEMINI_CONTEXT_WINDOW

        # Include the conversation's tags (#22) so the UI can render chips immediately.
        tags = await db.get_conversation_tags(conversation_id)

        payload: dict[str, Any] = {
            "type": "conversation_loaded",
            "conversation": {
                **conversation,
                "role_name": preset["name"],
                "role_emoji": preset["emoji"],
                "role_color": preset["color"],
                "tags": tags,
            },
            "messages": budgeted,
            "token_usage": {
                "input_tokens": estimated_tokens,
                "output_tokens": 0,
                "total_tokens": estimated_tokens,
                "context_window": context_window,
            },
        }
        if truncated:
            payload["truncated"] = True
        await ws.send_json(payload, dumps=_dumps_utf8)
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
    # Coerce to a real bool to match the pin/like handlers — guards against a
    # non-bool JSON payload flipping the star the wrong way.
    starred = bool(data.get("starred", True))

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
        # A truncated JSON/markdown/html export is corrupt, so surface an
        # explicit error instead of letting the dashboard client silently DROP
        # an oversized frame (ws-client.ts MAX_MESSAGE_LENGTH, ~50MB). The 20M
        # char cap (MAX_HISTORY_RESPONSE_CHARS) stays safely under it incl. the
        # JSON envelope overhead.
        if isinstance(export_data, str) and len(export_data) > MAX_HISTORY_RESPONSE_CHARS:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "EXPORT_TOO_LARGE",
                    "message": "Conversation too large to export over the dashboard",
                }
            )
            return
        await ws.send_json(
            {
                "type": "conversation_exported",
                "id": conversation_id,
                "format": export_format,
                "data": export_data,
            },
            dumps=_dumps_utf8,
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
    # Normalize to str. The DB stores conversation_id as TEXT and the CLI
    # session map (_CONVERSATION_SESSIONS) is keyed by str — leaving an int
    # here split the _REGEN_LOCKS key (int N vs str "N" → no serialization)
    # AND made delete_session_file(int) silently no-op, so the CLI --resume
    # session was never wiped after an edit (stale-transcript replay).
    if isinstance(conversation_id, int):
        conversation_id = str(conversation_id)

    # Validate format (defense in depth, consistent with every other
    # conversation-scoped handler — load/delete/star/rename/export/tag).
    # Gated on ``is not None`` because edit permits a null conversation_id;
    # this rejects junk ids (spaces, control chars) before they churn the
    # LRU-capped _REGEN_LOCKS dict and reach the DB / CLI-session map.
    if conversation_id is not None and not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"}
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
        # The lock serializes concurrent EDIT requests (double-click, tab
        # resend). True update+delete atomicity against concurrent SENDs —
        # which never take this lock — comes from the single-transaction
        # ``edit_and_truncate_dashboard_message`` below.
        regen_lock_key = conversation_id or f"_msg:{message_id_int}"
        async with _get_regen_lock(regen_lock_key):
            # Pass conversation_id to enforce ownership — without this the
            # client could edit any message ID in any conversation by guessing.
            deleted_count = 0
            if regenerate and conversation_id:
                updated, deleted_count = await db.edit_and_truncate_dashboard_message(
                    message_id_int, content, conversation_id
                )
            else:
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

        # Reflect what actually happened: truncation only ran on the
        # `regenerate and conversation_id` branch above. Echoing the raw
        # request flag would tell the client to optimistically drop messages
        # that were never deleted from the DB.
        did_truncate = bool(regenerate and conversation_id)
        await ws.send_json(
            {
                "type": "message_edited",
                "message_id": message_id,
                "content": content,
                "conversation_id": conversation_id,
                "regenerate": did_truncate,
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

    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID"}
        )
        return
    if not DB_AVAILABLE:
        await ws.send_json(
            {"type": "error", "code": "DB_UNAVAILABLE", "message": "Database not available"}
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

    if not _validate_conversation_id(conversation_id):
        await ws.send_json(
            {"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID"}
        )
        return
    if not DB_AVAILABLE:
        await ws.send_json(
            {"type": "error", "code": "DB_UNAVAILABLE", "message": "Database not available"}
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
        # Require a positive id so int 0 and string "0" are handled
        # identically (dashboard ids are AUTOINCREMENT from 1 — id 0 never
        # matches, so a 0 here would only issue a guaranteed-miss delete).
        if pair_message_id_int is not None and pair_message_id_int > 0:
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
        # Strict scope rule: the caller's scope must EXACTLY equal the
        # document's owner. Normalise a falsy conversation_id ("" / None) to
        # None first — the previous two-condition guard skipped BOTH checks
        # when conversation_id was falsy, so a client that simply omitted
        # conversation_id could delete a conversation-scoped (or any) document.
        # A global doc (owner None) is now only deletable globally (caller None);
        # a conversation doc only by a caller in that exact conversation.
        caller_scope = conversation_id or None
        if owner != caller_scope:
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
        #
        # Defence-in-depth PARITY with extract_from_payload (document_extractor):
        # the persisted name is re-emitted as a Markdown header line by
        # build_user_context, so neutralise everything that could start a new
        # line or spoof a Markdown header / role marker. We REMOVE (not collapse
        # to a space) every line-break and separator — C0 controls incl. CR/LF/
        # TAB, DEL, NEL (U+0085), LINE/PARAGRAPH SEPARATOR (U+2028/U+2029) and the
        # zero-width / BOM range — plus ``#``. Removal (rather than replacing with
        # a space) is deliberate: a space would turn ``report\nAssistant:`` into a
        # mid-line ``report Assistant:`` that slips past the ^-anchored emit-layer
        # role-marker defang (_DOC_ROLE_LEAK_RE); removing the break keeps it a
        # single token the emit-layer backstop (py-aicore-api-1) still neutralises.
        sanitised_filename = (
            re.sub(
                r"[\x00-\x1f\x7f\u0085\u2028\u2029\u200b-\u200f\u2060\ufeff/\\#]",
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
        # Strict scope rule (see handle_delete_document_memory): normalise a
        # falsy conversation_id to None and require an exact match, so an
        # omitted conversation_id can't skip the check and modify any document.
        caller_scope = conversation_id or None
        if owner != caller_scope:
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
        # Strict scope rule (see handle_delete_document_memory): normalise a
        # falsy conversation_id to None and require an exact match, so an
        # omitted conversation_id can't skip the check and read any document.
        caller_scope = conversation_id or None
        if owner != caller_scope:
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

    # A non-dict "profile" (client sends a string/list/number) would crash the
    # .get() calls below into a generic INTERNAL_ERROR. Reject it explicitly.
    if not isinstance(profile_data, dict):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ARG",
                "message": "profile must be an object",
            }
        )
        return

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
        # ``preferences`` is persisted into a TEXT column (``str | None``), and
        # the read path renders it back into the model context as a string. The
        # dashboard UI sends it as a free-text string (a textarea); a structured
        # client may instead send a dict. Both must end up as ``str | None`` —
        # sqlite cannot bind a dict, and (the original bug) the dict-only branch
        # silently dropped the string the real UI actually sends.
        prefs_present = "preferences" in profile_data  # profile_data guaranteed dict above
        raw_prefs = profile_data.get("preferences")
        sanitized_prefs: str | None = None
        truncated_prefs = False
        # Reject a preferences key that is present but neither str nor dict
        # (list/number/bool). Without this, the value silently fell through
        # both branches, stayed None, and overwrote the user's stored
        # preferences with None — silent data loss with a success ack. Mirrors
        # the type guards in handle_update_document_memory. An ABSENT key is
        # left to flow through as None (same as display_name/bio).
        if prefs_present and raw_prefs is not None and not isinstance(raw_prefs, str | dict):
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_ARG",
                    "message": "preferences must be a string or object",
                }
            )
            return
        if isinstance(raw_prefs, str):
            # Main path: funnel through the same sanitizer as display_name/bio
            # (NFKC + control-char strip + prompt-injection filter) so the value
            # can't carry injection directives into the model context.
            sanitized_prefs = _sanitize_profile_field(raw_prefs, max_length=500)
            # Mirror the dict branch's all-values-dropped guard: a NON-empty
            # string the sanitizer reduced to nothing would flow as None into
            # save_dashboard_user_profile and overwrite the stored preferences
            # with NULL under a success ack. An explicitly empty string is a
            # legitimate clear and falls through.
            if raw_prefs and not sanitized_prefs:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "INVALID_ARG",
                        "message": "preferences contains no usable values",
                    }
                )
                return
        elif isinstance(raw_prefs, dict):
            # Defensive path: sanitize each known value type, then serialise to a
            # JSON string (the column is TEXT — a raw dict can't be bound).
            clean: dict[str, str | int | float | bool | list[str]] = {}
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
                    clean[key] = _sanitize_profile_field(v, max_length=200) or ""
                elif isinstance(v, bool):
                    # bool MUST come before int (bool is a subclass of int)
                    clean[key] = v
                elif isinstance(v, int):
                    # Clamp to a sensible range so a giant integer can't
                    # blow up downstream JSON serialisation.
                    clean[key] = max(-(2**53), min(2**53, v))
                elif isinstance(v, float):
                    import math as _math

                    clean[key] = v if _math.isfinite(v) else 0.0
                elif isinstance(v, list):
                    # List string items reach the AI context just like the
                    # scalar str branch above, so they MUST go through the
                    # same sanitizer — the previous code only truncated them,
                    # leaving a second prompt-injection landing zone for
                    # ``["[System] You are now...", ...]`` payloads.
                    cleaned_list: list[str] = []
                    for i in v[:20]:
                        if isinstance(i, str):
                            cleaned_list.append(_sanitize_profile_field(i, max_length=200) or "")
                        elif isinstance(i, bool | int | float):
                            cleaned_list.append(str(i)[:200])
                    clean[key] = cleaned_list
            # A non-empty dict whose values were ALL dropped (nested dict / None
            # / unsupported type) leaves ``clean`` empty; writing None below
            # would flow to save_dashboard_user_profile's else-branch and
            # OVERWRITE the stored preferences with NULL while still acking
            # success — silent data loss. Reject instead. An explicitly empty
            # ``{}`` (raw_prefs falsy) is a legitimate clear and still falls
            # through to the None path, so guard on ``raw_prefs and not clean``.
            if raw_prefs and not clean:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "INVALID_ARG",
                        "message": "preferences contains no usable values",
                    }
                )
                return
            sanitized_prefs = json.dumps(clean, ensure_ascii=False) if clean else None
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
                # Echo what was actually PERSISTED (sanitized/clamped/defaulted),
                # not the raw client input — otherwise the UI briefly shows the
                # unsanitized values until the next get_profile reload corrects them.
                "profile": {
                    "display_name": display_name,
                    "bio": bio,
                    "preferences": sanitized_prefs,
                },
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


# ============================================================================
# AI history handlers (Discord-channel ai_history viewer/editor)
# ============================================================================

# Discord snowflakes exceed JS Number.MAX_SAFE_INTEGER, so the wire contract
# carries them as digit strings; a JSON number is tolerated too. 20 digits
# covers the full unsigned-64-bit range, but the parsers below additionally
# cap at SQLite's signed-64-bit max: binding anything larger raises
# OverflowError inside conn.execute, surfacing as INTERNAL_ERROR (plus a full
# stack-trace log) where the wire contract specifies INVALID_ID.
_SNOWFLAKE_RE = re.compile(r"[0-9]{1,20}")
_SQLITE_INT_MAX = (1 << 63) - 1


def _parse_snowflake(value: Any) -> int | None:
    """Parse a Discord snowflake (digit string or JSON number) to int.

    Returns None for anything malformed: non-digit strings, negatives,
    floats, bools (an int subclass — must be rejected explicitly), >20 digits,
    values above SQLite's signed-64-bit max.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not _SNOWFLAKE_RE.fullmatch(value):
        return None
    parsed = int(value)
    return parsed if parsed <= _SQLITE_INT_MAX else None


def _parse_history_row_id(value: Any) -> int | None:
    """Parse an ``ai_history`` primary-key id (positive int; digit string ok)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not _SNOWFLAKE_RE.fullmatch(value):
            return None
        value = int(value)
    if not isinstance(value, int) or value <= 0 or value > _SQLITE_INT_MAX:
        return None
    return value


def _get_chat_manager() -> ChatManager | None:
    """Resolve the live ChatManager (None when the AI cog isn't loaded).

    Module-local indirection (mirroring ``_get_db``) so handler tests patch a
    single name here instead of reaching into the registry module.
    """
    from .chat_manager_registry import get_chat_manager

    return get_chat_manager()


def _live_session_sync(
    cm: ChatManager | None, channel_id: int, sync: Callable[[ChatManager], bool]
) -> tuple[str, bool]:
    """Best-effort live-session sync after a durable DB edit/delete.

    Returns ``(live_session, live_session_patched)`` for the ack.
    ``live_session`` is a five-state string so the frontend can tell the
    benign miss apart from the warning-worthy one:

    - ``"unavailable"`` — AI cog not loaded; no live memory exists at all.
    - ``"not_loaded"`` — the channel's session isn't in bot RAM (restart, or
      evicted after idle). Benign and the common case: the DB is the source
      of truth and the next session load reads the fresh rows. ``sync`` is
      NOT called — there is nothing in memory to go stale, and a False
      return here would be indistinguishable from a real matcher miss.
    - ``"patched"`` — the in-memory item was updated/removed.
    - ``"no_match"`` — the session IS loaded but the matcher missed: stale
      RAM can clobber the DB edit (or resurrect the deleted row) on the
      next save, so this one deserves a warning.
    - ``"error"`` — the sync call raised. The DB mutation already
      succeeded, so the request must never fail over the best-effort
      memory work; the exception is logged and reported as this state.

    ``live_session_patched`` stays in the ack for backward compat and is
    True only for ``"patched"``.

    Side effect: always drops the channel's Discord Claude-CLI ``--resume``
    session (when the CLI backend module is importable) — the server-side
    session context still contains the pre-mutation history, and under
    delta-on-resume prompts the next turn would otherwise keep answering
    from the contradicted context forever.
    """
    try:
        from .discord_chat_claude_cli import reset_channel_session

        reset_channel_session(channel_id)
    except Exception:
        logger.exception("Failed to reset Discord CLI session for channel %s", channel_id)
    if cm is None:
        return "unavailable", False
    if channel_id not in cm.chats:
        return "not_loaded", False
    try:
        return ("patched", True) if sync(cm) else ("no_match", False)
    except Exception:
        logger.exception("Live-session sync failed for channel %s", channel_id)
        return "error", False


async def handle_list_ai_channels(ws: WebSocketResponse) -> None:
    """List Discord channels that have rows in ``ai_history``.

    Error envelopes from the three AI-history handlers all carry
    ``"scope": "ai_history"``: the dashboard shares one socket and one
    ``{type: "error"}`` shape between chat streaming and this feature, and an
    unscoped history error would trigger ChatManager's full chat-stream
    teardown (and vice versa, chat errors would unstick the history editor).
    """
    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
                "scope": "ai_history",
            }
        )
        return

    try:
        db = _get_db()
        summaries = await db.get_all_ai_channels_summary()

        # Resolve channel names through the live bot when the AI cog is loaded
        # (the dashboard runs in the same process, so ``get_channel`` is a
        # cache lookup). Formatting mirrors
        # ``ResponseMixin._get_chat_history_index``: guild + #channel, "DM"
        # for guildless channels, and a plain "Channel <id>" fallback when the
        # bot can't see the channel (or no cog is registered).
        cm = _get_chat_manager()
        bot = getattr(cm, "bot", None) if cm is not None else None

        channels: list[dict[str, Any]] = []
        for s in summaries:
            cid = s["channel_id"]
            name = f"Channel {cid}"
            if bot is not None:
                channel = bot.get_channel(cid)
                if channel is not None:
                    guild = getattr(channel, "guild", None)
                    guild_name = guild.name if guild else "DM"
                    channel_name = getattr(channel, "name", None) or "Unknown"
                    name = f"{guild_name} / #{channel_name}"
            channels.append(
                {
                    # Snowflakes go over the wire as strings — they exceed JS
                    # Number.MAX_SAFE_INTEGER and would lose precision.
                    "channel_id": str(cid),
                    "name": name,
                    "message_count": s["message_count"],
                    "last_active": s.get("last_active"),
                }
            )

        # last_active DESC with NULLs last. Key is (has_timestamp, timestamp)
        # reversed: non-null entries (True, ts) sort before null ones
        # (False, "") and among themselves by ISO timestamp descending.
        channels.sort(
            key=lambda c: (c["last_active"] is not None, c["last_active"] or ""),
            reverse=True,
        )

        await ws.send_json({"type": "ai_channels_list", "channels": channels})
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to list AI channels",
                "scope": "ai_history",
            }
        )


async def handle_load_ai_history(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Load a channel's ``ai_history`` rows (newest ``limit``, ascending id order)."""
    raw_channel = data.get("channel_id")
    if raw_channel is None or raw_channel == "":
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_ID",
                "message": "Missing channel ID",
                "scope": "ai_history",
            }
        )
        return
    channel_id = _parse_snowflake(raw_channel)
    if channel_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid channel ID format",
                "scope": "ai_history",
            }
        )
        return

    # limit: default 200, clamped to [1, 2000]. Non-numeric garbage falls back
    # to the default rather than erroring — the contract defines no error code
    # for a bad limit and the value gets clamped anyway.
    raw_limit = data.get("limit", 200)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int | float | str):
        limit = 200
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, OverflowError):
            limit = 200
    limit = max(1, min(2000, limit))

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
                "scope": "ai_history",
            }
        )
        return

    try:
        db = _get_db()
        rows = await db.get_ai_history(channel_id, limit=limit)
        total_count = await db.get_ai_history_count(channel_id)

        # Cumulative content budget (see MAX_HISTORY_RESPONSE_CHARS): iterate
        # NEWEST-first so truncation drops the OLDEST rows, then re-reverse to
        # restore ascending order. Always keep at least one row.
        messages: list[dict[str, Any]] = []
        budget = MAX_HISTORY_RESPONSE_CHARS
        truncated = False
        for row in reversed(rows):
            content = row["content"] or ""
            if messages and budget - len(content) < 0:
                truncated = True
                break
            budget -= len(content)
            messages.append(
                {
                    # Row "id" / "local_id" are small DB integers — they stay
                    # numbers. Snowflakes (message_id/user_id) become strings,
                    # None stays null.
                    "id": row["id"],
                    "local_id": row.get("local_id"),
                    "role": row["role"],
                    "content": content,
                    "message_id": (
                        str(row["message_id"]) if row.get("message_id") is not None else None
                    ),
                    "timestamp": row.get("timestamp"),
                    "user_id": str(row["user_id"]) if row.get("user_id") is not None else None,
                }
            )
        messages.reverse()

        payload: dict[str, Any] = {
            "type": "ai_history_loaded",
            "channel_id": str(channel_id),
            "messages": messages,
            "total_count": total_count,
            "has_more": total_count > len(messages),
        }
        if truncated:
            # The frontend stops offering "Load all" when the server itself
            # truncated — a bigger limit could not deliver more rows.
            payload["truncated"] = True
        await ws.send_json(payload, dumps=_dumps_utf8)
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to load AI history",
                "scope": "ai_history",
            }
        )


async def handle_edit_ai_history_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Edit one ``ai_history`` row's content by primary-key id.

    Updates the DB row first, then patches the live in-memory session (when
    that channel's chat is loaded). The memory patch is NOT optional polish:
    a DB-only edit gets destroyed later — force=True saves DELETE+reinsert
    the in-memory list, and diff-mode saves match overlap by
    timestamp+role+SHA256(content), so the external edit breaks the hash and
    the stale in-memory tail is re-upserted over it.
    """
    raw_channel = data.get("channel_id")
    raw_row_id = data.get("id")
    if raw_channel is None or raw_channel == "" or raw_row_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_ID",
                "message": "Missing channel ID or message id",
                "scope": "ai_history",
            }
        )
        return

    channel_id = _parse_snowflake(raw_channel)
    if channel_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid channel ID format",
                "scope": "ai_history",
            }
        )
        return
    row_id = _parse_history_row_id(raw_row_id)
    if row_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid history message id",
                "scope": "ai_history",
            }
        )
        return

    # Coerce-then-strip mirrors ``handle_edit_message``: a non-string payload
    # (number, list) must not crash on ``.strip()``.
    raw_content = data.get("content")
    content = str(raw_content).strip() if raw_content is not None else ""
    if not content:
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_CONTENT",
                "message": "Missing message content",
                "scope": "ai_history",
            }
        )
        return
    if len(content) > MAX_EDIT_CONTENT_LENGTH:
        await ws.send_json(
            {
                "type": "error",
                "code": "CONTENT_TOO_LONG",
                "message": f"Content too long (max {MAX_EDIT_CONTENT_LENGTH:,} characters)",
                "scope": "ai_history",
            }
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
                "scope": "ai_history",
            }
        )
        return

    try:
        db = _get_db()
        # Per-channel lock shared with the save paths (_save_history_db /
        # _replace_history_db) AND with concurrent edits: it makes the
        # read-row + UPDATE + memory-patch atomic relative to a save's
        # fetch+diff+write (which would otherwise duplicate the edited row via
        # the no-overlap fallback) and to a second edit's pre-edit read (which
        # would otherwise patch memory against a stale old-content snapshot
        # and silently revert on the next force save). Nothing in here awaits
        # anything that takes the same lock; patch_history_content is sync.
        async with get_history_lock(channel_id):
            # Read the pre-edit row first: MSG_NOT_FOUND needs the
            # channel-scoped existence check, and the in-memory patch below
            # matches against the OLD content/timestamp (that's what the live
            # session still holds).
            row = await db.get_ai_history_message(channel_id, row_id)
            if row is None:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "MSG_NOT_FOUND",
                        "message": "History message not found",
                        "scope": "ai_history",
                    }
                )
                return

            # message_id-less rows are matched in memory by (role, timestamp,
            # content) — identical "twins" are indistinguishable on those
            # keys, so compute the edited row's ordinal among its twins (in id
            # order, which equals memory order) for position-precise patching.
            occurrence = 0
            if row.get("message_id") is None:
                occurrence = await db.count_identical_history_rows_before(
                    channel_id,
                    row_id,
                    row.get("role") or "user",
                    row.get("timestamp"),
                    row.get("content") or "",
                )

            # DB first (TTL cache invalidated inside), memory second — if the
            # process dies between the two, the durable state is the edited one.
            updated = await edit_message_by_row_id(channel_id, row_id, content)
            if not updated:
                # Row vanished between the read and the UPDATE (concurrent prune
                # or delete) — report it like a missing row.
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "MSG_NOT_FOUND",
                        "message": "History message not found",
                        "scope": "ai_history",
                    }
                )
                return

            # Five-state outcome (see _live_session_sync): only a loaded
            # session with a missed matcher warrants a frontend warning.
            live_session, live_session_patched = _live_session_sync(
                _get_chat_manager(),
                channel_id,
                lambda m: m.patch_history_content(
                    channel_id, row=row, new_content=content, occurrence=occurrence
                ),
            )

        await ws.send_json(
            {
                "type": "ai_history_message_edited",
                "channel_id": str(channel_id),
                "id": row_id,
                "content": content,
                "live_session": live_session,
                "live_session_patched": live_session_patched,
            }
        )
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to edit AI history message",
                "scope": "ai_history",
            }
        )


async def handle_delete_ai_history_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete one ``ai_history`` row by primary-key id.

    Deletes the DB row first, then removes the matching item from the live
    in-memory session (when that channel's chat is loaded). The memory
    removal is NOT optional polish: a DB-only delete gets resurrected later —
    force=True saves DELETE+reinsert the in-memory list (the deleted row
    included), and diff-mode saves re-append the unmatched stale tail via the
    no-overlap fallback.
    """
    raw_channel = data.get("channel_id")
    raw_row_id = data.get("id")
    if raw_channel is None or raw_channel == "" or raw_row_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_ID",
                "message": "Missing channel ID or message id",
                "scope": "ai_history",
            }
        )
        return

    channel_id = _parse_snowflake(raw_channel)
    if channel_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid channel ID format",
                "scope": "ai_history",
            }
        )
        return
    row_id = _parse_history_row_id(raw_row_id)
    if row_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid history message id",
                "scope": "ai_history",
            }
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
                "scope": "ai_history",
            }
        )
        return

    try:
        db = _get_db()
        # Same per-channel lock discipline as the edit handler: read-row +
        # DELETE + memory removal must be atomic relative to a save's
        # fetch+diff+write (a stale snapshot would re-insert the deleted row)
        # and to a concurrent edit/delete's pre-mutation read. Nothing in here
        # awaits anything that takes the same lock; remove_history_content is
        # sync.
        async with get_history_lock(channel_id):
            # Read the row first: MSG_NOT_FOUND needs the channel-scoped
            # existence check, and the in-memory removal below matches against
            # the row's content/timestamp (that's what the live session holds).
            row = await db.get_ai_history_message(channel_id, row_id)
            if row is None:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "MSG_NOT_FOUND",
                        "message": "History message not found",
                        "scope": "ai_history",
                    }
                )
                return

            # message_id-less rows are matched in memory by (role, timestamp,
            # content) — identical "twins" are indistinguishable on those
            # keys, so compute the deleted row's ordinal among its twins (in
            # id order, which equals memory order) for position-precise
            # removal.
            occurrence = 0
            if row.get("message_id") is None:
                occurrence = await db.count_identical_history_rows_before(
                    channel_id,
                    row_id,
                    row.get("role") or "user",
                    row.get("timestamp"),
                    row.get("content") or "",
                )

            # DB first (TTL cache invalidated inside), memory second — if the
            # process dies between the two, the durable state is the deleted
            # one.
            deleted = await delete_message_by_row_id(channel_id, row_id)
            if not deleted:
                # Row vanished between the read and the DELETE (concurrent
                # prune or delete) — report it like a missing row.
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "MSG_NOT_FOUND",
                        "message": "History message not found",
                        "scope": "ai_history",
                    }
                )
                return

            # Five-state outcome (see _live_session_sync): only a loaded
            # session with a missed matcher warrants a frontend warning.
            live_session, live_session_patched = _live_session_sync(
                _get_chat_manager(),
                channel_id,
                lambda m: m.remove_history_content(channel_id, row=row, occurrence=occurrence),
            )

        # Outside the lock — a plain COUNT needs no serialization against
        # saves. Best-effort: the row is already durably deleted, so a COUNT
        # failure must not turn the ack into INTERNAL_ERROR (the client would
        # keep showing a row that is gone). The frontend falls back to a
        # local decrement when total_count is absent.
        ack: dict[str, Any] = {
            "type": "ai_history_message_deleted",
            "channel_id": str(channel_id),
            "id": row_id,
            "live_session": live_session,
            "live_session_patched": live_session_patched,
        }
        try:
            ack["total_count"] = await db.get_ai_history_count(channel_id)
        except Exception:
            logger.exception("Post-delete count failed for channel %s", channel_id)
        await ws.send_json(ack)
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to delete AI history message",
                "scope": "ai_history",
            }
        )


async def handle_restore_ai_history_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Restore (undo-delete) one ``ai_history`` row with its original id.

    ``data["message"]`` is byte-for-byte the message object the client
    received in ``ai_history_loaded`` (snowflakes as digit strings). The row
    is re-INSERTed with its ORIGINAL primary-key id — ``ai_history`` ordering
    is by id, so it returns to its original position. Idempotent: if the id
    already exists in the channel with the SAME role AND content, the restore
    acks as success (already restored); a different row under that id (or a
    (channel_id, message_id) unique-index hit) is ROW_CONFLICT. A row id that
    predates the channel's last force-replace rewrite (``'stale'`` from
    ``restore_message_by_row``) is also ROW_CONFLICT — the original position
    no longer exists, so the frontend discards the undo entry and reloads.

    DB first, then the live in-memory session is patched (when that channel's
    chat is loaded) — mirroring the edit/delete handlers: a DB-only restore
    gets destroyed later by a force=True save (delete+reinsert of the
    in-memory list, restored row excluded). The neighbor anchors and their
    twin ordinals are computed BEFORE the DB insert so the just-restored row
    cannot pollute the counts; the restored row's own DB twin count is read
    AFTER it (memory must end up with as many twins as the DB holds).
    """
    raw_channel = data.get("channel_id")
    if raw_channel is None or raw_channel == "":
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_ID",
                "message": "Missing channel ID",
                "scope": "ai_history",
            }
        )
        return
    channel_id = _parse_snowflake(raw_channel)
    if channel_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid channel ID format",
                "scope": "ai_history",
            }
        )
        return

    message = data.get("message")
    if not isinstance(message, dict):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_PAYLOAD",
                "message": "Missing or invalid message payload",
                "scope": "ai_history",
            }
        )
        return

    raw_row_id = message.get("id")
    if raw_row_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_ID",
                "message": "Missing message id",
                "scope": "ai_history",
            }
        )
        return
    row_id = _parse_history_row_id(raw_row_id)
    if row_id is None:
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_ID",
                "message": "Invalid history message id",
                "scope": "ai_history",
            }
        )
        return

    # role feeds the CHECK(role IN ('user','model')) column constraint AND the
    # idempotency comparison — only the two literal strings pass (a bool/int/
    # None fails the membership test).
    role = message.get("role")
    if role not in ("user", "model"):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_PAYLOAD",
                "message": "Invalid message role",
                "scope": "ai_history",
            }
        )
        return

    # Content must round-trip byte-for-byte (the idempotency check and the
    # live-session matcher both compare exact strings), so unlike the edit op
    # nothing is coerced or stripped — strip() is validation-only here.
    raw_content = message.get("content")
    if raw_content is not None and not isinstance(raw_content, str):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_PAYLOAD",
                "message": "Invalid message content",
                "scope": "ai_history",
            }
        )
        return
    if raw_content is None or not raw_content.strip():
        await ws.send_json(
            {
                "type": "error",
                "code": "MISSING_CONTENT",
                "message": "Missing message content",
                "scope": "ai_history",
            }
        )
        return
    content = raw_content
    if len(content) > MAX_EDIT_CONTENT_LENGTH:
        await ws.send_json(
            {
                "type": "error",
                "code": "CONTENT_TOO_LONG",
                "message": f"Content too long (max {MAX_EDIT_CONTENT_LENGTH:,} characters)",
                "scope": "ai_history",
            }
        )
        return

    # Snowflakes arrive as digit strings (None stays None); anything else is
    # malformed.
    message_id: int | None = None
    raw_message_id = message.get("message_id")
    if raw_message_id is not None:
        message_id = _parse_snowflake(raw_message_id)
        if message_id is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_ID",
                    "message": "Invalid message_id format",
                    "scope": "ai_history",
                }
            )
            return
    user_id: int | None = None
    raw_user_id = message.get("user_id")
    if raw_user_id is not None:
        user_id = _parse_snowflake(raw_user_id)
        if user_id is None:
            await ws.send_json(
                {
                    "type": "error",
                    "code": "INVALID_ID",
                    "message": "Invalid user_id format",
                    "scope": "ai_history",
                }
            )
            return

    # local_id is a small per-channel DB counter — a JSON number on the wire
    # (bools are int subclasses and must be rejected explicitly).
    local_id = message.get("local_id")
    if local_id is not None and (
        isinstance(local_id, bool)
        or not isinstance(local_id, int)
        or local_id < 0
        or local_id > _SQLITE_INT_MAX
    ):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_PAYLOAD",
                "message": "Invalid message local_id",
                "scope": "ai_history",
            }
        )
        return

    # timestamp is stored verbatim; 64 chars covers every format the save
    # paths write (ISO-8601 with offset) with headroom, while still bounding
    # the column against arbitrary blobs.
    timestamp = message.get("timestamp")
    if timestamp is not None and (not isinstance(timestamp, str) or len(timestamp) > 64):
        await ws.send_json(
            {
                "type": "error",
                "code": "INVALID_PAYLOAD",
                "message": "Invalid message timestamp",
                "scope": "ai_history",
            }
        )
        return

    if not DB_AVAILABLE:
        await ws.send_json(
            {
                "type": "error",
                "code": "DB_UNAVAILABLE",
                "message": "Database not available",
                "scope": "ai_history",
            }
        )
        return

    # The validated row, shaped like a get_ai_history_message result (parsed
    # ints, not wire strings) — both the DB insert and the in-memory matcher
    # consume this.
    row: dict[str, Any] = {
        "id": row_id,
        "local_id": local_id,
        "role": role,
        "content": content,
        "message_id": message_id,
        "timestamp": timestamp,
        "user_id": user_id,
    }

    try:
        db = _get_db()
        # Same per-channel lock discipline as the edit/delete handlers: the
        # INSERT + neighbor reads + memory insert must be atomic relative to
        # a save's fetch+diff+write (a save between the INSERT and the memory
        # patch would see the restored row as not-in-memory) and to a
        # concurrent edit/delete's pre-mutation read. Nothing in here awaits
        # anything that takes the same lock; insert_history_content is sync.
        async with get_history_lock(channel_id):
            # Anchors + twin ordinals BEFORE the DB restore so the
            # just-restored row cannot pollute the counts (the neighbor query
            # itself is unaffected — it keys on id </> row_id). message_id-less
            # anchors are matched in memory by (role, timestamp, content), so
            # each needs its ordinal among identical twins (id order equals
            # memory order on load) — the same machinery the edit/delete
            # handlers use — or the insert anchors on the earliest twin
            # instead of the actual DB neighbor.
            prev_row, next_row = await db.get_ai_history_neighbor_rows(channel_id, row_id)
            prev_occ = next_occ = 0
            if prev_row is not None and prev_row.get("message_id") is None:
                prev_occ = await db.count_identical_history_rows_before(
                    channel_id,
                    prev_row["id"],
                    prev_row.get("role") or "user",
                    prev_row.get("timestamp"),
                    prev_row.get("content") or "",
                )
            if next_row is not None and next_row.get("message_id") is None:
                next_occ = await db.count_identical_history_rows_before(
                    channel_id,
                    next_row["id"],
                    next_row.get("role") or "user",
                    next_row.get("timestamp"),
                    next_row.get("content") or "",
                )

            result = await restore_message_by_row(channel_id, row)
            if result == "stale":
                # The channel's history was force-replace rewritten (fresh
                # ids) after this undo entry was captured — the original
                # position no longer exists. ROW_CONFLICT so the frontend's
                # discard+reload handling covers it.
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "ROW_CONFLICT",
                        "message": "History was rewritten since this undo was recorded",
                        "scope": "ai_history",
                    }
                )
                return
            if result == "conflict":
                await ws.send_json(
                    {
                        "type": "error",
                        "code": "ROW_CONFLICT",
                        "message": "A different message already occupies this history slot",
                        "scope": "ai_history",
                    }
                )
                return

            # 'restored' and 'exists_same' both ack as success — the latter is
            # the idempotent retry (lost ack / second client) and the live
            # session is evaluated as usual either way.

            # The restored row's own post-restore DB twin count (mid-less rows
            # only): insert_history_content's skip-insert guard compares the
            # in-memory twin count against it — mere existence cannot tell
            # "the restored row is back in memory" from "a surviving identical
            # twin is in memory".
            expected_twins = 1
            if row.get("message_id") is None:
                expected_twins = await db.count_identical_history_rows(
                    channel_id,
                    row.get("role") or "user",
                    row.get("timestamp"),
                    row.get("content") or "",
                )

            # Five-state outcome (see _live_session_sync): only a loaded
            # session with a missed anchor warrants a frontend warning.
            live_session, live_session_patched = _live_session_sync(
                _get_chat_manager(),
                channel_id,
                lambda m: m.insert_history_content(
                    channel_id,
                    row=row,
                    prev_row=prev_row,
                    next_row=next_row,
                    prev_occurrence=prev_occ,
                    next_occurrence=next_occ,
                    expected_twins=expected_twins,
                ),
            )

        # Outside the lock — a plain COUNT needs no serialization against
        # saves. Best-effort: the row is already durably restored, so a COUNT
        # failure must not turn the ack into INTERNAL_ERROR (the client would
        # keep hiding a row that is back). The frontend falls back to a local
        # increment when total_count is absent.
        ack: dict[str, Any] = {
            "type": "ai_history_message_restored",
            "channel_id": str(channel_id),
            "id": row_id,
            "live_session": live_session,
            "live_session_patched": live_session_patched,
        }
        try:
            ack["total_count"] = await db.get_ai_history_count(channel_id)
        except Exception:
            logger.exception("Post-restore count failed for channel %s", channel_id)
        await ws.send_json(ack)
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json(
            {
                "type": "error",
                "code": "INTERNAL_ERROR",
                "message": "Failed to restore AI history message",
                "scope": "ai_history",
            }
        )
