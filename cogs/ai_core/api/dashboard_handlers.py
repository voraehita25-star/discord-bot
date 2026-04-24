"""
Dashboard CRUD handlers for conversations, memories, and profiles.

These are standalone async functions called by the main WebSocket server.
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
import re
from itertools import islice
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

MAX_PREFERENCE_KEYS = 50  # Prevent DoS via unbounded dict keys

from .dashboard_config import (
    CLAUDE_CONTEXT_WINDOW,
    DASHBOARD_ROLE_PRESETS,
    DB_AVAILABLE,
    DEFAULT_AI_PROVIDER,
    GEMINI_CONTEXT_WINDOW,
)


# Lazy import Database to avoid circular imports
def _get_db():
    from .dashboard_config import Database
    return Database()


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
        await ws.send_json({
            "type": "conversations_list",
            "conversations": conversations,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to list conversations"})


async def handle_load_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Load a specific conversation with messages."""
    conversation_id = data.get("id")

    if not conversation_id:
        await ws.send_json({"type": "error", "code": "MISSING_ID", "message": "Missing conversation ID"})
        return

    # Validate conversation_id format (defense in depth - DB also validates)
    if not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"})
        return

    if not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "DB_UNAVAILABLE", "message": "Database not available"})
        return

    try:
        db = _get_db()
        conversation = await db.get_dashboard_conversation(conversation_id)
        messages = await db.get_dashboard_messages(conversation_id)

        if not conversation:
            await ws.send_json({"type": "error", "code": "CONV_NOT_FOUND", "message": "Conversation not found"})
            return

        preset = DASHBOARD_ROLE_PRESETS.get(
            conversation.get("role_preset", "general"),
            DASHBOARD_ROLE_PRESETS["general"]
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

        await ws.send_json({
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
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to load conversation"})


async def handle_delete_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a conversation."""
    conversation_id = data.get("id")

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_DELETE", "message": "Cannot delete: missing ID or DB unavailable"})
        return

    # Validate conversation_id format
    if not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"})
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
            _delete_cli_session(conversation_id)
        except Exception:
            logger.exception("Claude CLI session cleanup failed for %s", conversation_id)
        await ws.send_json({
            "type": "conversation_deleted",
            "id": conversation_id,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to delete conversation"})


async def handle_star_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle star status of a conversation."""
    conversation_id = data.get("id")
    starred = data.get("starred", True)

    logger.info("Star conversation request: id=%s, starred=%s", conversation_id, starred)

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_UPDATE", "message": "Cannot update: missing ID or DB unavailable"})
        return

    # Validate conversation_id format
    if not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"})
        return

    try:
        db = _get_db()
        result = await db.update_dashboard_conversation_star(conversation_id, starred)
        logger.info("Star update result: %s", result)
        await ws.send_json({
            "type": "conversation_starred",
            "id": conversation_id,
            "starred": starred,
        })
        logger.info("Sent conversation_starred response")
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to star conversation"})


async def handle_rename_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Rename a conversation."""
    conversation_id = data.get("id")
    new_title = data.get("title", "").strip()

    if not conversation_id or not new_title or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_RENAME", "message": "Cannot rename: missing ID, title, or DB unavailable"})
        return

    # Validate conversation_id format
    if not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"})
        return

    if len(new_title) > 200:
        await ws.send_json({"type": "error", "code": "TITLE_TOO_LONG", "message": "Title too long (max 200 characters)"})
        return
    # Strip non-printable characters (null bytes, control chars, etc.)
    new_title = "".join(ch for ch in new_title if ch.isprintable()).strip()
    if not new_title:
        await ws.send_json({"type": "error", "code": "INVALID_TITLE", "message": "Title contains only invalid characters"})
        return

    try:
        db = _get_db()
        await db.rename_dashboard_conversation(conversation_id, new_title)
        await ws.send_json({
            "type": "conversation_renamed",
            "id": conversation_id,
            "title": new_title,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to rename conversation"})


async def handle_export_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Export a conversation to JSON."""
    conversation_id = data.get("id")
    export_format = data.get("format", "json")

    # Validate export_format
    valid_formats = ("json", "markdown", "html", "txt")
    if export_format not in valid_formats:
        await ws.send_json({
            "type": "error",
            "code": "INVALID_FORMAT",
            "message": f"Invalid export format. Use one of: {', '.join(valid_formats)}",
        })
        return

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_EXPORT", "message": "Cannot export: missing ID or DB unavailable"})
        return

    # Validate conversation_id format
    if not isinstance(conversation_id, str) or not re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID format"})
        return

    try:
        db = _get_db()
        export_data = await db.export_dashboard_conversation(conversation_id, export_format)
        await ws.send_json({
            "type": "conversation_exported",
            "id": conversation_id,
            "format": export_format,
            "data": export_data,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to export conversation"})


# ============================================================================
# Message edit/delete handlers
# ============================================================================

async def handle_edit_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Edit a message's content. If regenerate=True for user messages, deletes all subsequent messages."""
    message_id = data.get("message_id")
    content = data.get("content", "").strip()
    regenerate = data.get("regenerate", False)
    conversation_id = data.get("conversation_id")

    if not message_id or not content or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_EDIT", "message": "Cannot edit: missing data or DB unavailable"})
        return

    # Enforce content size limit
    if len(content) > 50_000:
        await ws.send_json({"type": "error", "code": "CONTENT_TOO_LONG", "message": "Content too long (max 50,000 characters)"})
        return

    # Validate message_id is numeric
    try:
        message_id_int = int(message_id)
    except (ValueError, TypeError):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid message ID"})
        return

    try:
        db = _get_db()
        updated = await db.update_dashboard_message(message_id_int, content)
        if not updated:
            await ws.send_json({"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"})
            return

        deleted_count = 0
        if regenerate and conversation_id:
            deleted_count = await db.delete_dashboard_messages_after(conversation_id, message_id_int)

        await ws.send_json({
            "type": "message_edited",
            "message_id": message_id,
            "content": content,
            "conversation_id": conversation_id,
            "regenerate": regenerate,
            "deleted_after": deleted_count,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to edit message"})


async def handle_pin_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle the pin state of a dashboard message."""
    message_id = data.get("message_id")
    pinned = bool(data.get("pinned", True))

    if not message_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_PIN", "message": "Cannot pin: missing ID or DB unavailable"})
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
            await ws.send_json({"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"})
            return
        await ws.send_json({
            "type": "message_pinned",
            "message_id": message_id,
            "pinned": pinned,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to pin message"})


async def handle_like_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle the 'liked' flag on a dashboard message (#20b)."""
    message_id = data.get("message_id")
    liked = bool(data.get("liked", True))

    if not message_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_LIKE", "message": "Cannot like: missing ID or DB unavailable"})
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
            await ws.send_json({"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"})
            return
        await ws.send_json({
            "type": "message_liked",
            "message_id": message_id,
            "liked": liked,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to like message"})


# ============================================================================
# Conversation tag handlers (#22)
# ============================================================================

_VALID_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def _validate_conversation_id(conversation_id: Any) -> bool:
    return isinstance(conversation_id, str) and bool(re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id))


async def handle_add_conversation_tag(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Attach a tag to a conversation."""
    conversation_id = data.get("conversation_id")
    tag = (data.get("tag") or "").strip().lower()

    if not DB_AVAILABLE or not _validate_conversation_id(conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID"})
        return
    if not _VALID_TAG_RE.match(tag):
        await ws.send_json({
            "type": "error",
            "code": "INVALID_TAG",
            "message": "Tag must be 1-64 chars, lowercase alphanumerics + _ - (must start with a letter or digit)",
        })
        return

    try:
        db = _get_db()
        added = await db.add_conversation_tag(conversation_id, tag)
        tags = await db.get_conversation_tags(conversation_id)
        await ws.send_json({
            "type": "conversation_tagged",
            "conversation_id": conversation_id,
            "tag": tag,
            "added": added,
            "tags": tags,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to add tag"})


async def handle_remove_conversation_tag(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Detach a tag from a conversation."""
    conversation_id = data.get("conversation_id")
    tag = (data.get("tag") or "").strip().lower()

    if not DB_AVAILABLE or not _validate_conversation_id(conversation_id):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid conversation ID"})
        return
    if not tag:
        await ws.send_json({"type": "error", "code": "INVALID_TAG", "message": "Tag required"})
        return

    try:
        db = _get_db()
        removed = await db.remove_conversation_tag(conversation_id, tag)
        tags = await db.get_conversation_tags(conversation_id)
        await ws.send_json({
            "type": "conversation_untagged",
            "conversation_id": conversation_id,
            "tag": tag,
            "removed": removed,
            "tags": tags,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to remove tag"})


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
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to list tags"})


async def handle_delete_message(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a message. If delete_pair=True, also deletes the paired response (next message)."""
    message_id = data.get("message_id")
    delete_pair = data.get("delete_pair", False)
    pair_message_id = data.get("pair_message_id")

    if not message_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_DELETE", "message": "Cannot delete: missing ID or DB unavailable"})
        return

    try:
        db = _get_db()
        conv_id = await db.delete_dashboard_message(int(message_id))
        if not conv_id:
            await ws.send_json({"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"})
            return

        # Delete paired message if requested
        deleted_pair_id = None
        if delete_pair and pair_message_id:
            pair_conv_id = await db.delete_dashboard_message(int(pair_message_id))
            if pair_conv_id:
                deleted_pair_id = pair_message_id

        await ws.send_json({
            "type": "message_deleted",
            "message_id": message_id,
            "pair_message_id": deleted_pair_id,
            "conversation_id": conv_id,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to delete message"})


# ============================================================================
# Memory handlers
# ============================================================================

async def handle_save_memory(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Save a memory for the user."""
    content = data.get("content", "").strip()
    category = data.get("category", "general")

    if not content or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_SAVE_MEMORY", "message": "Cannot save: empty content or DB unavailable"})
        return

    # Enforce size limits
    if len(content) > 2000:
        await ws.send_json({"type": "error", "code": "CONTENT_TOO_LONG", "message": "Memory content too long (max 2,000 characters)"})
        return
    if len(category) > 50:
        await ws.send_json({"type": "error", "code": "CATEGORY_TOO_LONG", "message": "Category too long (max 50 characters)"})
        return

    try:
        db = _get_db()
        memory_id = await db.save_dashboard_memory(content, category)
        await ws.send_json({
            "type": "memory_saved",
            "id": memory_id,
            "content": content,
            "category": category,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to save memory"})


async def handle_get_memories(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Get all memories."""
    category = data.get("category")  # Optional filter

    if not DB_AVAILABLE:
        await ws.send_json({"type": "memories", "memories": []})
        return

    try:
        db = _get_db()
        memories = await db.get_dashboard_memories(category)
        await ws.send_json({
            "type": "memories",
            "memories": memories,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to get memories"})


async def handle_delete_memory(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a memory."""
    memory_id = data.get("id")

    if not memory_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_DELETE_MEMORY", "message": "Cannot delete: missing ID or DB unavailable"})
        return

    # Validate memory_id is numeric
    try:
        int(memory_id)
    except (ValueError, TypeError):
        await ws.send_json({"type": "error", "code": "INVALID_ID", "message": "Invalid memory ID"})
        return

    try:
        db = _get_db()
        await db.delete_dashboard_memory(int(memory_id))
        await ws.send_json({
            "type": "memory_deleted",
            "id": memory_id,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to delete memory"})


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
        await ws.send_json({
            "type": "profile",
            "profile": profile or {},
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to get profile"})


def _sanitize_profile_field(value: str | None, max_length: int = 200) -> str | None:
    """Sanitize a profile text field."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    # Strip control characters except newline/tab
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    # Truncate to max length
    return value[:max_length].strip() or None


async def handle_save_profile(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Save user profile."""
    profile_data = data.get("profile", {})

    if not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "DB_UNAVAILABLE", "message": "Cannot save profile: DB unavailable"})
        return

    try:
        db = _get_db()
        # Sanitize user-controlled text fields
        display_name = _sanitize_profile_field(profile_data.get("display_name"), max_length=50) or "User"
        bio = _sanitize_profile_field(profile_data.get("bio"), max_length=500)
        # Sanitize preferences: only allow known keys with safe values
        raw_prefs = profile_data.get("preferences")
        sanitized_prefs: dict[str, str | int | float | bool | list[str]] | None = None
        if isinstance(raw_prefs, dict):
            sanitized_prefs = {}
            for k, v in islice(raw_prefs.items(), MAX_PREFERENCE_KEYS):
                key = str(k)[:50]
                if isinstance(v, (str, int, float, bool)):
                    sanitized_prefs[key] = str(v)[:200] if isinstance(v, str) else v
                elif isinstance(v, list):
                    sanitized_prefs[key] = [str(i)[:200] for i in v[:20] if isinstance(i, (str, int, float, bool))]
        await db.save_dashboard_user_profile(
            display_name=display_name,
            bio=bio,
            preferences=sanitized_prefs,
            # Note: is_creator is NOT accepted from client input for security
        )
        await ws.send_json({
            "type": "profile_saved",
            "profile": profile_data,
        })
    except Exception:
        logger.exception("WebSocket handler error")
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to save profile"})

