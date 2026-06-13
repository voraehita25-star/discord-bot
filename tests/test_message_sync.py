"""Tests for Discord→memory sync: deleting/editing a Discord message mirrors
into the AI's stored conversation history ('like reading live').

Covers:
- ChatManager.remove_message_from_history / edit_message_in_history
  (in-memory mutation + persistence delegation)
- The AICog raw listeners (on_raw_message_delete / on_raw_bulk_message_delete /
  on_raw_message_edit) delegating to the ChatManager.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# ChatManager memory mutation
# ============================================================================


def _bare_manager(chats):
    """A ChatManager with just the ``chats`` dict — bypasses heavy __init__."""
    from cogs.ai_core.logic import ChatManager

    cm = ChatManager.__new__(ChatManager)
    cm.chats = chats
    return cm


class TestRemoveMessageFromHistory:
    @pytest.mark.asyncio
    async def test_removes_matching_entry_in_memory_and_db(self):
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["hi"], "message_id": 10},
                        {"role": "model", "parts": ["hello"]},
                        {"role": "user", "parts": ["bye"], "message_id": 20},
                    ]
                }
            }
        )
        with patch(
            "cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=1)
        ) as mock_del:
            result = await cm.remove_message_from_history(50, 10)

        assert result is True
        remaining = [item.get("message_id") for item in cm.chats[50]["history"]]
        assert 10 not in remaining
        assert 20 in remaining  # untouched
        # The bot's reply (no message_id) is left intact — it's still visible in Discord.
        assert any(item["role"] == "model" for item in cm.chats[50]["history"])
        mock_del.assert_awaited_once_with(50, 10)

    @pytest.mark.asyncio
    async def test_db_only_when_session_not_loaded(self):
        cm = _bare_manager({})
        with patch(
            "cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=1)
        ) as mock_del:
            result = await cm.remove_message_from_history(99, 5)

        assert result is True  # DB delete counted even with nothing in memory
        mock_del.assert_awaited_once_with(99, 5)

    @pytest.mark.asyncio
    async def test_returns_false_when_nothing_matched(self):
        cm = _bare_manager({50: {"history": [{"role": "user", "parts": ["hi"], "message_id": 10}]}})
        with patch("cogs.ai_core.logic.delete_message_by_id", AsyncMock(return_value=0)):
            result = await cm.remove_message_from_history(50, 999)

        assert result is False
        assert len(cm.chats[50]["history"]) == 1  # unchanged


class TestEditMessageInHistory:
    @pytest.mark.asyncio
    async def test_updates_matching_entry_in_memory_and_db(self):
        cm = _bare_manager(
            {50: {"history": [{"role": "user", "parts": ["old"], "message_id": 10}]}}
        )
        with patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=1)) as mock_edit:
            result = await cm.edit_message_in_history(50, 10, "new")

        assert result is True
        assert cm.chats[50]["history"][0]["parts"] == ["new"]
        mock_edit.assert_awaited_once_with(50, 10, "new")

    @pytest.mark.asyncio
    async def test_returns_false_when_nothing_matched(self):
        cm = _bare_manager({})
        with patch("cogs.ai_core.logic.edit_message_by_id", AsyncMock(return_value=0)):
            result = await cm.edit_message_in_history(50, 10, "new")

        assert result is False


# ============================================================================
# AICog raw listeners
# ============================================================================


def _make_cog():
    from cogs.ai_core.ai_cog import AI

    bot = MagicMock()
    with (
        patch("cogs.ai_core.ai_cog.ChatManager") as mock_cm,
        patch("cogs.ai_core.ai_cog.rate_limiter"),
    ):
        cm = MagicMock()
        cm.chats = {}
        cm.processing_locks = {}
        mock_cm.return_value = cm
        cog = AI(bot)
    return cog


class TestRawListeners:
    @pytest.mark.asyncio
    async def test_on_raw_message_delete_delegates(self):
        cog = _make_cog()
        cog.chat_manager.remove_message_from_history = AsyncMock(return_value=True)
        payload = MagicMock()
        payload.channel_id = 50
        payload.message_id = 10

        await cog.on_raw_message_delete(payload)

        cog.chat_manager.remove_message_from_history.assert_awaited_once_with(50, 10)

    @pytest.mark.asyncio
    async def test_on_raw_message_delete_swallows_errors(self):
        cog = _make_cog()
        cog.chat_manager.remove_message_from_history = AsyncMock(side_effect=RuntimeError("boom"))
        payload = MagicMock()
        payload.channel_id = 50
        payload.message_id = 10

        # Must not raise — a failed sync should never crash the event loop.
        await cog.on_raw_message_delete(payload)

    @pytest.mark.asyncio
    async def test_on_raw_bulk_message_delete_delegates_per_id(self):
        cog = _make_cog()
        cog.chat_manager.remove_message_from_history = AsyncMock(return_value=True)
        payload = MagicMock()
        payload.channel_id = 50
        payload.message_ids = {10, 20, 30}

        await cog.on_raw_bulk_message_delete(payload)

        assert cog.chat_manager.remove_message_from_history.await_count == 3

    @pytest.mark.asyncio
    async def test_on_raw_message_edit_delegates_with_content(self):
        cog = _make_cog()
        cog.chat_manager.edit_message_in_history = AsyncMock(return_value=True)
        payload = MagicMock()
        payload.channel_id = 50
        payload.message_id = 10
        payload.data = {"content": "new text"}

        await cog.on_raw_message_edit(payload)

        cog.chat_manager.edit_message_in_history.assert_awaited_once_with(50, 10, "new text")

    @pytest.mark.asyncio
    async def test_on_raw_message_edit_skips_without_content(self):
        cog = _make_cog()
        cog.chat_manager.edit_message_in_history = AsyncMock()
        payload = MagicMock()
        payload.channel_id = 50
        payload.message_id = 10
        payload.data = {}  # embed-only / attachment edit — no text change

        await cog.on_raw_message_edit(payload)

        cog.chat_manager.edit_message_in_history.assert_not_awaited()
