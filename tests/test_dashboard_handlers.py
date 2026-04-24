"""Tests for Dashboard CRUD handlers (dashboard_handlers.py).

Covers all handler functions: conversations, messages, memories, profiles.
Each handler is tested for success, validation errors, and DB unavailability.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeWS:
    """Minimal fake aiohttp.web.WebSocketResponse for testing."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    def last(self) -> dict:
        return self.sent[-1] if self.sent else {}

    def find(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


@pytest.fixture()
def ws():
    return FakeWS()


@pytest.fixture()
def mock_db():
    """Create a mocked Database instance."""
    db = MagicMock()
    db.get_dashboard_conversations = AsyncMock(return_value=[])
    db.get_dashboard_conversation = AsyncMock(return_value=None)
    db.get_dashboard_messages = AsyncMock(return_value=[])
    db.get_dashboard_messages_recent = AsyncMock(return_value=[])
    db.get_dashboard_messages_before = AsyncMock(return_value=[])
    db.get_dashboard_message_count = AsyncMock(return_value=0)
    db.has_messages_before = AsyncMock(return_value=False)
    db.delete_dashboard_conversation = AsyncMock()
    db.update_dashboard_conversation_star = AsyncMock(return_value=True)
    db.rename_dashboard_conversation = AsyncMock()
    db.export_dashboard_conversation = AsyncMock(return_value={})
    db.update_dashboard_message = AsyncMock(return_value=True)
    db.delete_dashboard_messages_after = AsyncMock(return_value=0)
    db.delete_dashboard_message = AsyncMock(return_value="conv-123")
    db.update_dashboard_message_pin = AsyncMock(return_value=True)
    db.update_dashboard_message_liked = AsyncMock(return_value=True)
    db.get_conversation_tags = AsyncMock(return_value=[])
    db.add_conversation_tag = AsyncMock(return_value=True)
    db.remove_conversation_tag = AsyncMock(return_value=True)
    db.list_all_conversation_tags = AsyncMock(return_value=[])
    db.save_dashboard_memory = AsyncMock(return_value=1)
    db.get_dashboard_memories = AsyncMock(return_value=[])
    db.delete_dashboard_memory = AsyncMock()
    db.get_dashboard_user_profile = AsyncMock(return_value={})
    db.save_dashboard_user_profile = AsyncMock()
    return db


# ===================================================================
# Conversation handlers
# ===================================================================

class TestListConversations:
    @pytest.mark.asyncio
    async def test_list_conversations_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_list_conversations
        mock_db.get_dashboard_conversations.return_value = [{"id": "c1", "title": "Test"}]
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_list_conversations(ws)
        assert ws.last()["type"] == "conversations_list"
        assert len(ws.last()["conversations"]) == 1

    @pytest.mark.asyncio
    async def test_list_conversations_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_list_conversations
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_list_conversations(ws)
        assert ws.last()["type"] == "conversations_list"
        assert ws.last()["conversations"] == []

    @pytest.mark.asyncio
    async def test_list_conversations_db_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_list_conversations
        mock_db.get_dashboard_conversations.side_effect = RuntimeError("DB error")
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_list_conversations(ws)
        assert ws.last()["type"] == "error"
        assert ws.last()["code"] == "INTERNAL_ERROR"


class TestLoadConversation:
    @pytest.mark.asyncio
    async def test_missing_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation
        await handle_load_conversation(ws, {})
        assert ws.last()["code"] == "MISSING_ID"

    @pytest.mark.asyncio
    async def test_invalid_id_format(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation
        await handle_load_conversation(ws, {"id": "conv!@#$"})
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    async def test_conversation_not_found(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_load_conversation(ws, {"id": "nonexistent"})
        assert ws.last()["code"] == "CONV_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_load_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation
        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = [{"content": "hello"}]
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_load_conversation(ws, {"id": "c1"})
        assert ws.last()["type"] == "conversation_loaded"


class TestDeleteConversation:
    @pytest.mark.asyncio
    async def test_missing_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_conversation
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_conversation(ws, {})
        assert ws.last()["code"] == "CANNOT_DELETE"

    @pytest.mark.asyncio
    async def test_invalid_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_conversation
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_conversation(ws, {"id": "bad!id"})
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    async def test_delete_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_conversation
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_conversation(ws, {"id": "c1"})
        assert ws.last()["type"] == "conversation_deleted"


class TestStarConversation:
    @pytest.mark.asyncio
    async def test_missing_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_star_conversation
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_star_conversation(ws, {})
        assert ws.last()["code"] == "CANNOT_UPDATE"

    @pytest.mark.asyncio
    async def test_star_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_star_conversation
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_star_conversation(ws, {"id": "c1", "starred": True})
        assert ws.last()["type"] == "conversation_starred"
        assert ws.last()["starred"] is True


class TestRenameConversation:
    @pytest.mark.asyncio
    async def test_missing_fields(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_rename_conversation
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_rename_conversation(ws, {"id": "c1"})
        assert ws.last()["code"] == "CANNOT_RENAME"

    @pytest.mark.asyncio
    async def test_title_too_long(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_rename_conversation
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_rename_conversation(ws, {"id": "c1", "title": "A" * 201})
        assert ws.last()["code"] == "TITLE_TOO_LONG"

    @pytest.mark.asyncio
    async def test_rename_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_rename_conversation
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_rename_conversation(ws, {"id": "c1", "title": "New Title"})
        assert ws.last()["type"] == "conversation_renamed"
        assert ws.last()["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_title_strips_non_printable(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_rename_conversation
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_rename_conversation(ws, {"id": "c1", "title": "Good\x00Title"})
        assert ws.last()["title"] == "GoodTitle"


class TestExportConversation:
    @pytest.mark.asyncio
    async def test_invalid_format(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_export_conversation
        await handle_export_conversation(ws, {"id": "c1", "format": "xml"})
        assert ws.last()["code"] == "INVALID_FORMAT"

    @pytest.mark.asyncio
    async def test_export_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_export_conversation
        mock_db.export_dashboard_conversation.return_value = {"messages": []}
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_export_conversation(ws, {"id": "c1", "format": "json"})
        assert ws.last()["type"] == "conversation_exported"


# ===================================================================
# Message handlers
# ===================================================================

class TestEditMessage:
    @pytest.mark.asyncio
    async def test_missing_data(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_edit_message(ws, {})
        assert ws.last()["code"] == "CANNOT_EDIT"

    @pytest.mark.asyncio
    async def test_content_too_long(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_edit_message(ws, {"message_id": "1", "content": "A" * 50_001})
        assert ws.last()["code"] == "CONTENT_TOO_LONG"

    @pytest.mark.asyncio
    async def test_invalid_message_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_edit_message(ws, {"message_id": "abc", "content": "test"})
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    async def test_message_not_found(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message
        mock_db.update_dashboard_message.return_value = False
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_edit_message(ws, {"message_id": "1", "content": "new"})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_edit_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_edit_message(ws, {"message_id": "1", "content": "updated"})
        assert ws.last()["type"] == "message_edited"

    @pytest.mark.asyncio
    async def test_edit_with_regenerate(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message
        mock_db.delete_dashboard_messages_after.return_value = 3
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_edit_message(ws, {
                "message_id": "1", "content": "edit", "regenerate": True, "conversation_id": "c1"
            })
        assert ws.last()["deleted_after"] == 3


class TestDeleteMessage:
    @pytest.mark.asyncio
    async def test_missing_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_message(ws, {})
        assert ws.last()["code"] == "CANNOT_DELETE"

    @pytest.mark.asyncio
    async def test_message_not_found(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message
        mock_db.delete_dashboard_message.return_value = None
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_message(ws, {"message_id": "999"})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_message(ws, {"message_id": "1"})
        assert ws.last()["type"] == "message_deleted"

    @pytest.mark.asyncio
    async def test_delete_with_pair(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_message(ws, {
                "message_id": "1", "delete_pair": True, "pair_message_id": "2"
            })
        assert ws.last()["pair_message_id"] == "2"


class TestPinMessage:
    """Coverage for the pin_message WS handler added with the #20 feature."""

    @pytest.mark.asyncio
    async def test_missing_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {})
        assert ws.last()["code"] == "CANNOT_PIN"

    @pytest.mark.asyncio
    async def test_invalid_id_format(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {"message_id": "not-a-number"})
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_pin_message(ws, {"message_id": "1", "pinned": True})
        assert ws.last()["code"] == "CANNOT_PIN"

    @pytest.mark.asyncio
    async def test_message_not_found(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        mock_db.update_dashboard_message_pin.return_value = False
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {"message_id": "999", "pinned": True})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_pin_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {"message_id": "42", "pinned": True})
        last = ws.last()
        assert last["type"] == "message_pinned"
        assert last["pinned"] is True
        assert last["message_id"] == "42"
        mock_db.update_dashboard_message_pin.assert_awaited_once_with(42, True)

    @pytest.mark.asyncio
    async def test_unpin_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {"message_id": "42", "pinned": False})
        assert ws.last()["pinned"] is False
        mock_db.update_dashboard_message_pin.assert_awaited_once_with(42, False)

    @pytest.mark.asyncio
    async def test_defaults_to_pinned_true_when_omitted(self, ws, mock_db):
        """If the client omits the `pinned` field, handler defaults to pinning."""
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {"message_id": "42"})
        mock_db.update_dashboard_message_pin.assert_awaited_once_with(42, True)

    @pytest.mark.asyncio
    async def test_db_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message
        mock_db.update_dashboard_message_pin.side_effect = RuntimeError("boom")
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_pin_message(ws, {"message_id": "42", "pinned": True})
        assert ws.last()["code"] == "INTERNAL_ERROR"


# ===================================================================
# Memory handlers
# ===================================================================

class TestSaveMemory:
    @pytest.mark.asyncio
    async def test_empty_content(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_save_memory
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_save_memory(ws, {"content": ""})
        assert ws.last()["code"] == "CANNOT_SAVE_MEMORY"

    @pytest.mark.asyncio
    async def test_content_too_long(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_save_memory
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_save_memory(ws, {"content": "A" * 2001})
        assert ws.last()["code"] == "CONTENT_TOO_LONG"

    @pytest.mark.asyncio
    async def test_category_too_long(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_save_memory
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_save_memory(ws, {"content": "test", "category": "A" * 51})
        assert ws.last()["code"] == "CATEGORY_TOO_LONG"

    @pytest.mark.asyncio
    async def test_save_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_save_memory
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_save_memory(ws, {"content": "Remember this", "category": "notes"})
        assert ws.last()["type"] == "memory_saved"
        assert ws.last()["content"] == "Remember this"


class TestGetMemories:
    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_get_memories
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_get_memories(ws, {})
        assert ws.last()["type"] == "memories"
        assert ws.last()["memories"] == []

    @pytest.mark.asyncio
    async def test_get_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_get_memories
        mock_db.get_dashboard_memories.return_value = [{"id": 1, "content": "test"}]
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_get_memories(ws, {})
        assert len(ws.last()["memories"]) == 1


class TestDeleteMemory:
    @pytest.mark.asyncio
    async def test_missing_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_memory
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_memory(ws, {})
        assert ws.last()["code"] == "CANNOT_DELETE_MEMORY"

    @pytest.mark.asyncio
    async def test_invalid_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_memory
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_memory(ws, {"id": "abc"})
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    async def test_delete_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_memory
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_delete_memory(ws, {"id": 1})
        assert ws.last()["type"] == "memory_deleted"


# ===================================================================
# Profile handlers
# ===================================================================

class TestGetProfile:
    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_get_profile
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_get_profile(ws)
        assert ws.last()["type"] == "profile"
        assert ws.last()["profile"] == {}

    @pytest.mark.asyncio
    async def test_get_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_get_profile
        mock_db.get_dashboard_user_profile.return_value = {"display_name": "User"}
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_get_profile(ws)
        assert ws.last()["profile"]["display_name"] == "User"


class TestSaveProfile:
    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile
        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_save_profile(ws, {"profile": {}})
        assert ws.last()["code"] == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_save_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_save_profile(ws, {"profile": {"display_name": "New Name"}})
        assert ws.last()["type"] == "profile_saved"

    @pytest.mark.asyncio
    async def test_save_db_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile
        mock_db.save_dashboard_user_profile.side_effect = RuntimeError("DB error")
        with patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db), \
             patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True):
            await handle_save_profile(ws, {"profile": {"display_name": "Test"}})
        assert ws.last()["code"] == "INTERNAL_ERROR"
