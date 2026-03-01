"""
Dashboard CRUD handlers for conversations, memories, and profiles.

These are standalone async functions called by the main WebSocket server.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp.web import WebSocketResponse

from .dashboard_config import DASHBOARD_ROLE_PRESETS, DB_AVAILABLE


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
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to list conversations"})


async def handle_load_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Load a specific conversation with messages."""
    conversation_id = data.get("id")

    if not conversation_id:
        await ws.send_json({"type": "error", "code": "MISSING_ID", "message": "Missing conversation ID"})
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

        await ws.send_json({
            "type": "conversation_loaded",
            "conversation": {
                **conversation,
                "role_name": preset["name"],
                "role_emoji": preset["emoji"],
                "role_color": preset["color"],
            },
            "messages": messages,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to load conversation"})


async def handle_delete_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a conversation."""
    conversation_id = data.get("id")

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_DELETE", "message": "Cannot delete: missing ID or DB unavailable"})
        return

    try:
        db = _get_db()
        await db.delete_dashboard_conversation(conversation_id)
        await ws.send_json({
            "type": "conversation_deleted",
            "id": conversation_id,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to delete conversation"})


async def handle_star_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Toggle star status of a conversation."""
    conversation_id = data.get("id")
    starred = data.get("starred", True)

    logging.info("Star conversation request: id=%s, starred=%s", conversation_id, starred)

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_UPDATE", "message": "Cannot update: missing ID or DB unavailable"})
        return

    try:
        db = _get_db()
        result = await db.update_dashboard_conversation_star(conversation_id, starred)
        logging.info("Star update result: %s", result)
        await ws.send_json({
            "type": "conversation_starred",
            "id": conversation_id,
            "starred": starred,
        })
        logging.info("Sent conversation_starred response")
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to star conversation"})


async def handle_rename_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Rename a conversation."""
    conversation_id = data.get("id")
    new_title = data.get("title", "").strip()

    if not conversation_id or not new_title or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_RENAME", "message": "Cannot rename: missing ID, title, or DB unavailable"})
        return

    try:
        db = _get_db()
        await db.rename_dashboard_conversation(conversation_id, new_title)
        await ws.send_json({
            "type": "conversation_renamed",
            "id": conversation_id,
            "title": new_title,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to rename conversation"})


async def handle_export_conversation(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Export a conversation to JSON."""
    conversation_id = data.get("id")
    export_format = data.get("format", "json")

    if not conversation_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_EXPORT", "message": "Cannot export: missing ID or DB unavailable"})
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
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
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

    try:
        db = _get_db()
        updated = await db.update_dashboard_message(int(message_id), content)
        if not updated:
            await ws.send_json({"type": "error", "code": "MSG_NOT_FOUND", "message": "Message not found"})
            return

        deleted_count = 0
        if regenerate and conversation_id:
            deleted_count = await db.delete_dashboard_messages_after(conversation_id, int(message_id))

        await ws.send_json({
            "type": "message_edited",
            "message_id": message_id,
            "content": content,
            "conversation_id": conversation_id,
            "regenerate": regenerate,
            "deleted_after": deleted_count,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to edit message"})


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
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
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

    try:
        db = _get_db()
        memory_id = await db.save_dashboard_memory(content, category)
        await ws.send_json({
            "type": "memory_saved",
            "id": memory_id,
            "content": content,
            "category": category,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
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
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to get memories"})


async def handle_delete_memory(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Delete a memory."""
    memory_id = data.get("id")

    if not memory_id or not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "CANNOT_DELETE_MEMORY", "message": "Cannot delete: missing ID or DB unavailable"})
        return

    try:
        db = _get_db()
        await db.delete_dashboard_memory(memory_id)
        await ws.send_json({
            "type": "memory_deleted",
            "id": memory_id,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
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
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to get profile"})


async def handle_save_profile(ws: WebSocketResponse, data: dict[str, Any]) -> None:
    """Save user profile."""
    profile_data = data.get("profile", {})

    if not DB_AVAILABLE:
        await ws.send_json({"type": "error", "code": "DB_UNAVAILABLE", "message": "Cannot save profile: DB unavailable"})
        return

    try:
        db = _get_db()
        await db.save_dashboard_user_profile(
            display_name=profile_data.get("display_name", "User"),
            bio=profile_data.get("bio"),
            preferences=profile_data.get("preferences"),
            # Note: is_creator is NOT accepted from client input for security
        )
        await ws.send_json({
            "type": "profile_saved",
            "profile": profile_data,
        })
    except Exception as e:
        logging.error("WebSocket handler error: %s", e)
        await ws.send_json({"type": "error", "code": "INTERNAL_ERROR", "message": "Failed to save profile"})
