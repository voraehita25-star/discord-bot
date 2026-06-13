"""Tests for the dashboard "AI History" feature (Discord ai_history viewer/editor).

Covers, per the wire contract:
- the five WS handlers (list_ai_channels / load_ai_history /
  edit_ai_history_message / delete_ai_history_message /
  restore_ai_history_message) — success, validation errors, DB
  unavailability, snowflake-as-string serialization, the
  five-state live_session field (patched / not_loaded / no_match /
  unavailable / error) plus the legacy live_session_patched boolean
- the new Database methods against a real SQLite file
  (get_ai_history_message / update_ai_history_content / delete_ai_history_row
  / restore_ai_history_row / get_ai_history_neighbor_rows
  / last_active in get_all_ai_channels_summary)
- ChatManager.patch_history_content / remove_history_content /
  insert_history_content (in-memory mirroring after an external DB
  edit/delete/restore)
- ws_dashboard routing + rate-exemption wiring
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


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
    """Create a mocked Database instance with the AI-history methods."""
    db = MagicMock()
    db.get_all_ai_channels_summary = AsyncMock(return_value=[])
    db.get_ai_history = AsyncMock(return_value=[])
    db.get_ai_history_count = AsyncMock(return_value=0)
    db.get_ai_history_message = AsyncMock(return_value=None)
    db.update_ai_history_content = AsyncMock(return_value=True)
    db.count_identical_history_rows_before = AsyncMock(return_value=0)
    db.count_identical_history_rows = AsyncMock(return_value=1)
    db.get_ai_history_neighbor_rows = AsyncMock(return_value=(None, None))
    return db


def _fake_chat_manager(
    channels: dict[int, object] | None = None,
    patched: bool = False,
    chats: dict[int, object] | None = None,
):
    """A stand-in for the registry's ChatManager: a .bot with get_channel +
    patch/remove + the live-session ``chats`` dict (empty by default — the
    handlers only invoke patch/remove when the channel id is a key)."""
    lookup = channels or {}
    cm = SimpleNamespace(
        bot=SimpleNamespace(get_channel=lookup.get),
        chats=chats if chats is not None else {},
        patch_history_content=MagicMock(return_value=patched),
        remove_history_content=MagicMock(return_value=patched),
        insert_history_content=MagicMock(return_value=patched),
    )
    return cm


# ===================================================================
# handle_list_ai_channels
# ===================================================================


class TestListAiChannels:
    @pytest.mark.asyncio
    async def test_success_names_sorting_and_snowflake_strings(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_list_ai_channels

        mock_db.get_all_ai_channels_summary.return_value = [
            {"channel_id": 111, "message_count": 5, "last_active": "2024-05-01T00:00:00+00:00"},
            {"channel_id": 222, "message_count": 2, "last_active": None},
            {"channel_id": 333, "message_count": 9, "last_active": "2024-06-01T00:00:00+00:00"},
        ]
        cm = _fake_chat_manager(
            channels={111: SimpleNamespace(guild=SimpleNamespace(name="MyGuild"), name="general")}
        )
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_list_ai_channels(ws)

        msg = ws.last()
        assert msg["type"] == "ai_channels_list"
        chans = msg["channels"]
        # last_active DESC, nulls last
        assert [c["channel_id"] for c in chans] == ["333", "111", "222"]
        assert all(isinstance(c["channel_id"], str) for c in chans)
        by_id = {c["channel_id"]: c for c in chans}
        assert by_id["111"]["name"] == "MyGuild / #general"
        assert by_id["222"]["name"] == "Channel 222"  # bot can't see it
        assert by_id["333"]["name"] == "Channel 333"
        assert by_id["111"]["message_count"] == 5
        assert by_id["222"]["last_active"] is None

    @pytest.mark.asyncio
    async def test_dm_channel_name(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_list_ai_channels

        mock_db.get_all_ai_channels_summary.return_value = [
            {"channel_id": 5, "message_count": 1, "last_active": None},
        ]
        cm = _fake_chat_manager(channels={5: SimpleNamespace(guild=None, name="friend")})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_list_ai_channels(ws)
        assert ws.last()["channels"][0]["name"] == "DM / #friend"

    @pytest.mark.asyncio
    async def test_fallback_names_without_chat_manager(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_list_ai_channels

        mock_db.get_all_ai_channels_summary.return_value = [
            {"channel_id": 987654321098765432, "message_count": 1, "last_active": None},
        ]
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_list_ai_channels(ws)
        chan = ws.last()["channels"][0]
        assert chan["name"] == "Channel 987654321098765432"
        assert chan["channel_id"] == "987654321098765432"

    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_list_ai_channels

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_list_ai_channels(ws)
        assert ws.last()["type"] == "error"
        assert ws.last()["code"] == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_db_error_internal_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_list_ai_channels

        mock_db.get_all_ai_channels_summary.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_list_ai_channels(ws)
        assert ws.last()["code"] == "INTERNAL_ERROR"


# ===================================================================
# handle_load_ai_history
# ===================================================================


class TestLoadAiHistory:
    @pytest.mark.asyncio
    async def test_success_serialization(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        mock_db.get_ai_history.return_value = [
            {
                "id": 7,
                "local_id": 5,
                "role": "user",
                "content": "hi",
                "message_id": 1234567890123456789,
                "timestamp": "2024-01-01T00:00:00+00:00",
                "user_id": 9876543210987654321,
            },
            {
                "id": 9,
                "local_id": 6,
                "role": "model",
                "content": "yo",
                "message_id": None,
                "timestamp": None,
                "user_id": None,
            },
        ]
        mock_db.get_ai_history_count.return_value = 120
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_ai_history(ws, {"channel_id": "424242424242424242"})

        msg = ws.last()
        assert msg["type"] == "ai_history_loaded"
        assert msg["channel_id"] == "424242424242424242"
        assert msg["total_count"] == 120
        assert msg["has_more"] is True
        first, second = msg["messages"]
        # Row ids stay numbers; snowflakes are strings; None stays null.
        assert first["id"] == 7 and isinstance(first["id"], int)
        assert first["local_id"] == 5
        assert first["message_id"] == "1234567890123456789"
        assert first["user_id"] == "9876543210987654321"
        assert second["message_id"] is None
        assert second["user_id"] is None
        assert second["timestamp"] is None
        # Untruncated responses don't carry the truncated flag.
        assert "truncated" not in msg
        # channel_id used as int internally
        mock_db.get_ai_history.assert_awaited_once_with(424242424242424242, limit=200)

    @pytest.mark.asyncio
    async def test_accepts_numeric_channel_id(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_ai_history(ws, {"channel_id": 123, "limit": 50})
        assert ws.last()["type"] == "ai_history_loaded"
        assert ws.last()["channel_id"] == "123"
        # total_count (0) == len(messages) (0) — the has_more=False boundary.
        assert ws.last()["has_more"] is False
        mock_db.get_ai_history.assert_awaited_once_with(123, limit=50)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("raw_limit", "expected"),
        [
            (99999, 2000),
            (0, 1),
            (-5, 1),
            ("garbage", 200),
            (None, 200),
            (True, 200),
            # Exact clamp boundaries + the int() coercion paths.
            (1, 1),
            (2000, 2000),
            (2001, 2000),
            ("500", 500),
            (12.7, 12),
        ],
    )
    async def test_limit_clamping(self, ws, mock_db, raw_limit, expected):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_ai_history(ws, {"channel_id": "123", "limit": raw_limit})
        mock_db.get_ai_history.assert_awaited_once_with(123, limit=expected)

    @pytest.mark.asyncio
    async def test_missing_channel_id(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        await handle_load_ai_history(ws, {})
        assert ws.last()["code"] == "MISSING_ID"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad",
        [
            "abc",
            "12a",
            "-5",
            "1" * 21,
            1.5,
            ["1"],
            # Above SQLite's signed-64-bit max: would raise OverflowError at
            # bind time (surfacing as INTERNAL_ERROR) if accepted.
            "99999999999999999999",
            str(2**63),
        ],
    )
    async def test_invalid_channel_id(self, ws, bad):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        await handle_load_ai_history(ws, {"channel_id": bad})
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    async def test_response_budget_truncates_oldest_and_sets_flag(self, ws, mock_db):
        """B5: the cumulative content budget drops the OLDEST rows and flags it."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        mock_db.get_ai_history.return_value = [
            {
                "id": i,
                "local_id": i,
                "role": "user",
                "content": c,
                "message_id": None,
                "timestamp": None,
                "user_id": None,
            }
            for i, c in ((1, "a" * 6), (2, "b" * 6), (3, "c" * 6))
        ]
        mock_db.get_ai_history_count.return_value = 3
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.MAX_HISTORY_RESPONSE_CHARS", 10),
        ):
            await handle_load_ai_history(ws, {"channel_id": "123"})

        msg = ws.last()
        assert msg["type"] == "ai_history_loaded"
        # Newest row kept, the two oldest dropped by the 10-char budget.
        assert [m["id"] for m in msg["messages"]] == [3]
        assert msg["truncated"] is True
        assert msg["has_more"] is True  # total_count (3) > len(messages) (1)

    @pytest.mark.asyncio
    async def test_response_budget_always_keeps_newest_row(self, ws, mock_db):
        """B5: even a single over-budget row is kept (never an empty reply)."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        mock_db.get_ai_history.return_value = [
            {
                "id": 1,
                "local_id": 1,
                "role": "model",
                "content": "x" * 100,
                "message_id": None,
                "timestamp": None,
                "user_id": None,
            }
        ]
        mock_db.get_ai_history_count.return_value = 1
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.MAX_HISTORY_RESPONSE_CHARS", 1),
        ):
            await handle_load_ai_history(ws, {"channel_id": "123"})

        msg = ws.last()
        assert len(msg["messages"]) == 1
        assert "truncated" not in msg  # nothing was dropped
        assert msg["has_more"] is False

    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_load_ai_history(ws, {"channel_id": "123"})
        assert ws.last()["code"] == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_db_error_internal_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_load_ai_history

        mock_db.get_ai_history.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_ai_history(ws, {"channel_id": "123"})
        assert ws.last()["code"] == "INTERNAL_ERROR"


# ===================================================================
# handle_edit_ai_history_message
# ===================================================================

_ROW = {
    "id": 7,
    "local_id": 5,
    "role": "user",
    "content": "old text",
    "message_id": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
    "user_id": None,
}


class TestLiveSessionSyncResetsCliSession:
    """Every dashboard AI-history mutation must drop the channel's Discord
    Claude-CLI --resume session: the server-side session context still holds
    the pre-mutation history, and under delta-on-resume prompts the next turn
    would keep answering from the contradicted context forever. The reset
    lives in _live_session_sync, which all three handlers call on success."""

    def test_reset_called_even_when_cm_unavailable(self):
        from cogs.ai_core.api.dashboard_handlers import _live_session_sync

        with patch("cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session") as reset:
            state, patched = _live_session_sync(None, 123, lambda cm: True)
        reset.assert_called_once_with(123)
        assert state == "unavailable"
        assert patched is False

    def test_reset_called_when_session_loaded(self):
        from cogs.ai_core.api.dashboard_handlers import _live_session_sync

        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with patch("cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session") as reset:
            state, patched = _live_session_sync(cm, 123, lambda c: True)
        reset.assert_called_once_with(123)
        assert (state, patched) == ("patched", True)

    def test_reset_failure_never_breaks_the_sync(self):
        from cogs.ai_core.api.dashboard_handlers import _live_session_sync

        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with patch(
            "cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session",
            side_effect=RuntimeError("boom"),
        ):
            state, patched = _live_session_sync(cm, 123, lambda c: True)
        assert (state, patched) == ("patched", True)

    @pytest.mark.asyncio
    async def test_edit_handler_resets_cli_session_end_to_end(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        cm = _fake_chat_manager(patched=True, chats={424242424242424242: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
            patch("cogs.ai_core.api.discord_chat_claude_cli.reset_channel_session") as reset,
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "424242424242424242", "id": 7, "content": "new text"}
            )
        assert ws.last()["type"] == "ai_history_message_edited"
        reset.assert_called_once_with(424242424242424242)


class TestEditAiHistoryMessage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("patched", "expected_state"), [(True, "patched"), (False, "no_match")]
    )
    async def test_success_live_session_states(self, ws, mock_db, patched, expected_state):
        """Session loaded: matcher hit -> "patched", matcher miss -> "no_match"."""
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        cm = _fake_chat_manager(patched=patched, chats={424242424242424242: object()})
        mock_edit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id", mock_edit),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "424242424242424242", "id": 7, "content": "new text"}
            )

        msg = ws.last()
        assert msg["type"] == "ai_history_message_edited"
        assert msg["channel_id"] == "424242424242424242"
        assert msg["id"] == 7
        assert msg["content"] == "new text"
        assert msg["live_session"] == expected_state
        assert msg["live_session_patched"] is patched
        mock_db.get_ai_history_message.assert_awaited_once_with(424242424242424242, 7)
        mock_edit.assert_awaited_once_with(424242424242424242, 7, "new text")
        cm.patch_history_content.assert_called_once_with(
            424242424242424242, row=dict(_ROW), new_content="new text", occurrence=0
        )

    @pytest.mark.asyncio
    async def test_session_not_loaded_skips_patch(self, ws, mock_db):
        """Channel not in cm.chats (restart / idle eviction): the benign common
        case. The matcher must NOT run — nothing in RAM can go stale, and a
        False return would be indistinguishable from a real miss."""
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        cm = _fake_chat_manager(patched=True)  # chats defaults to {}
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "123", "id": 7, "content": "new text"}
            )

        msg = ws.last()
        assert msg["type"] == "ai_history_message_edited"
        assert msg["live_session"] == "not_loaded"
        assert msg["live_session_patched"] is False
        cm.patch_history_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_twin_ordinal_computed_and_passed_to_patch(self, ws, mock_db):
        """B3: message_id-less rows get their twin ordinal from the DB count."""
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_db.count_identical_history_rows_before.return_value = 2
        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "123", "id": 7, "content": "new text"}
            )

        mock_db.count_identical_history_rows_before.assert_awaited_once_with(
            123, 7, "user", "2024-01-01T00:00:00+00:00", "old text"
        )
        cm.patch_history_content.assert_called_once_with(
            123, row=dict(_ROW), new_content="new text", occurrence=2
        )

    @pytest.mark.asyncio
    async def test_row_with_message_id_skips_twin_count(self, ws, mock_db):
        """B3: rows carrying a message_id are matched by id — no COUNT query."""
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        row = dict(_ROW)
        row["message_id"] = 555
        mock_db.get_ai_history_message.return_value = row
        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "123", "id": 7, "content": "new text"}
            )

        mock_db.count_identical_history_rows_before.assert_not_awaited()
        cm.patch_history_content.assert_called_once_with(
            123, row=row, new_content="new text", occurrence=0
        )

    @pytest.mark.asyncio
    async def test_no_chat_manager_means_unavailable(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "123", "id": 7, "content": "new text"}
            )
        assert ws.last()["live_session"] == "unavailable"
        assert ws.last()["live_session_patched"] is False

    @pytest.mark.asyncio
    async def test_patch_exception_does_not_fail_request(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        cm = _fake_chat_manager(chats={123: object()})
        cm.patch_history_content.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "123", "id": 7, "content": "new text"}
            )
        msg = ws.last()
        assert msg["type"] == "ai_history_message_edited"
        assert msg["live_session"] == "error"
        assert msg["live_session_patched"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"id": 7, "content": "x"},  # no channel_id
            {"channel_id": "123", "content": "x"},  # no row id
            {"channel_id": "", "id": 7, "content": "x"},  # empty channel_id
        ],
    )
    async def test_missing_ids(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        await handle_edit_ai_history_message(ws, payload)
        assert ws.last()["code"] == "MISSING_ID"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"channel_id": "abc", "id": 7, "content": "x"},
            {"channel_id": "123", "id": -7, "content": "x"},
            {"channel_id": "123", "id": 0, "content": "x"},
            {"channel_id": "123", "id": "7b", "content": "x"},
            {"channel_id": "123", "id": True, "content": "x"},
            {"channel_id": "123", "id": 1.5, "content": "x"},
            # Above SQLite's signed-64-bit max (the JSON-int path previously
            # had no upper bound at all — 10**100 was accepted).
            {"channel_id": "123", "id": 2**63, "content": "x"},
            {"channel_id": "123", "id": 10**100, "content": "x"},
            {"channel_id": str(2**63), "id": 7, "content": "x"},
        ],
    )
    async def test_invalid_ids(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        await handle_edit_ai_history_message(ws, payload)
        assert ws.last()["code"] == "INVALID_ID"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content", [None, "", "   \n\t "])
    async def test_missing_content(self, ws, content):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": content})
        assert ws.last()["code"] == "MISSING_CONTENT"

    @pytest.mark.asyncio
    async def test_content_too_long(self, ws):
        from cogs.ai_core.api.dashboard_handlers import (
            MAX_EDIT_CONTENT_LENGTH,
            handle_edit_ai_history_message,
        )

        await handle_edit_ai_history_message(
            ws, {"channel_id": "123", "id": 7, "content": "x" * (MAX_EDIT_CONTENT_LENGTH + 1)}
        )
        assert ws.last()["code"] == "CONTENT_TOO_LONG"

    @pytest.mark.asyncio
    async def test_content_exactly_max_length_succeeds(self, ws, mock_db):
        """The strict > comparison: exactly MAX_EDIT_CONTENT_LENGTH must pass."""
        from cogs.ai_core.api.dashboard_handlers import (
            MAX_EDIT_CONTENT_LENGTH,
            handle_edit_ai_history_message,
        )

        content = "x" * MAX_EDIT_CONTENT_LENGTH
        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_edit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id", mock_edit),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_edit_ai_history_message(
                ws, {"channel_id": "123", "id": 7, "content": content}
            )
        msg = ws.last()
        assert msg["type"] == "ai_history_message_edited"
        assert msg["content"] == content
        mock_edit.assert_awaited_once_with(123, 7, content)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", [123, ["x"]])
    async def test_non_string_content_coerced(self, ws, mock_db, raw):
        """The deliberate str(...).strip() coercion path for non-string payloads."""
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        expected = str(raw).strip()
        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_edit = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id", mock_edit),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": raw})
        msg = ws.last()
        assert msg["type"] == "ai_history_message_edited"
        assert msg["content"] == expected
        mock_edit.assert_awaited_once_with(123, 7, expected)

    @pytest.mark.asyncio
    async def test_msg_not_found(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = None
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_update_race_reports_not_found(self, ws, mock_db):
        """Row read OK but UPDATE matched nothing (raced a delete/prune)."""
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=False),
            ),
        ):
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
        assert ws.last()["code"] == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_db_error_internal_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
        assert ws.last()["code"] == "INTERNAL_ERROR"


# ===================================================================
# handle_delete_ai_history_message
# ===================================================================


class TestDeleteAiHistoryMessage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("patched", "expected_state"), [(True, "patched"), (False, "no_match")]
    )
    async def test_success_live_session_states_and_total_count(
        self, ws, mock_db, patched, expected_state
    ):
        """Session loaded: matcher hit -> "patched", matcher miss -> "no_match"."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_db.get_ai_history_count.return_value = 41
        cm = _fake_chat_manager(patched=patched, chats={424242424242424242: object()})
        mock_delete = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id", mock_delete),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_delete_ai_history_message(
                ws, {"channel_id": "424242424242424242", "id": 7}
            )

        msg = ws.last()
        assert msg["type"] == "ai_history_message_deleted"
        assert msg["channel_id"] == "424242424242424242"
        assert msg["id"] == 7 and isinstance(msg["id"], int)
        assert msg["live_session"] == expected_state
        assert msg["live_session_patched"] is patched
        # Post-delete count for the channel, per the wire contract.
        assert msg["total_count"] == 41
        mock_db.get_ai_history_message.assert_awaited_once_with(424242424242424242, 7)
        mock_delete.assert_awaited_once_with(424242424242424242, 7)
        mock_db.get_ai_history_count.assert_awaited_once_with(424242424242424242)
        cm.remove_history_content.assert_called_once_with(
            424242424242424242, row=dict(_ROW), occurrence=0
        )

    @pytest.mark.asyncio
    async def test_session_not_loaded_skips_remove(self, ws, mock_db):
        """Channel not in cm.chats (restart / idle eviction): the benign common
        case. The matcher must NOT run — nothing in RAM can resurrect the
        deleted row, and a False return would be indistinguishable from a
        real miss."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        cm = _fake_chat_manager(patched=True)  # chats defaults to {}
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})

        msg = ws.last()
        assert msg["type"] == "ai_history_message_deleted"
        assert msg["live_session"] == "not_loaded"
        assert msg["live_session_patched"] is False
        cm.remove_history_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_digit_string_row_id(self, ws, mock_db):
        """The row id is a number on the wire, but a digit string is tolerated
        like the edit op."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_delete = AsyncMock(return_value=True)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id", mock_delete),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": 123, "id": "7"})
        msg = ws.last()
        assert msg["type"] == "ai_history_message_deleted"
        assert msg["id"] == 7 and isinstance(msg["id"], int)
        mock_delete.assert_awaited_once_with(123, 7)

    @pytest.mark.asyncio
    async def test_twin_ordinal_computed_and_passed_to_remove(self, ws, mock_db):
        """message_id-less rows get their twin ordinal from the DB count."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_db.count_identical_history_rows_before.return_value = 2
        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})

        mock_db.count_identical_history_rows_before.assert_awaited_once_with(
            123, 7, "user", "2024-01-01T00:00:00+00:00", "old text"
        )
        cm.remove_history_content.assert_called_once_with(123, row=dict(_ROW), occurrence=2)

    @pytest.mark.asyncio
    async def test_row_with_message_id_skips_twin_count(self, ws, mock_db):
        """Rows carrying a message_id are matched by id — no COUNT query."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        row = dict(_ROW)
        row["message_id"] = 555
        mock_db.get_ai_history_message.return_value = row
        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})

        mock_db.count_identical_history_rows_before.assert_not_awaited()
        cm.remove_history_content.assert_called_once_with(123, row=row, occurrence=0)

    @pytest.mark.asyncio
    async def test_no_chat_manager_means_unavailable(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        assert ws.last()["live_session"] == "unavailable"
        assert ws.last()["live_session_patched"] is False

    @pytest.mark.asyncio
    async def test_remove_exception_does_not_fail_request(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        cm = _fake_chat_manager(chats={123: object()})
        cm.remove_history_content.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        msg = ws.last()
        assert msg["type"] == "ai_history_message_deleted"
        assert msg["live_session"] == "error"
        assert msg["live_session_patched"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"id": 7},  # no channel_id
            {"channel_id": "123"},  # no row id
            {"channel_id": "", "id": 7},  # empty channel_id
        ],
    )
    async def test_missing_ids(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        await handle_delete_ai_history_message(ws, payload)
        assert ws.last()["code"] == "MISSING_ID"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"channel_id": "abc", "id": 7},
            {"channel_id": "123", "id": -7},
            {"channel_id": "123", "id": 0},
            {"channel_id": "123", "id": "7b"},
            {"channel_id": "123", "id": True},
            {"channel_id": "123", "id": 1.5},
            # Above SQLite's signed-64-bit max (same caps as the edit op).
            {"channel_id": "123", "id": 2**63},
            {"channel_id": "123", "id": 10**100},
            {"channel_id": str(2**63), "id": 7},
        ],
    )
    async def test_invalid_ids(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        await handle_delete_ai_history_message(ws, payload)
        assert ws.last()["code"] == "INVALID_ID"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    async def test_msg_not_found(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = None
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_race_reports_not_found(self, ws, mock_db):
        """Row read OK but DELETE matched nothing (raced a prune/delete)."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=False),
            ),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        assert ws.last()["code"] == "MSG_NOT_FOUND"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        assert ws.last()["code"] == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_db_error_internal_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        assert ws.last()["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_count_error_after_delete_still_acks_without_total_count(self, ws, mock_db):
        """The post-delete COUNT is best-effort: the row is already durably
        deleted, so a COUNT failure must NOT turn the ack into
        INTERNAL_ERROR (the client would keep showing a deleted row). The
        ack is sent without total_count and the frontend falls back to a
        local decrement."""
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        mock_db.get_ai_history_count.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                AsyncMock(return_value=True),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
        assert ws.last()["type"] == "ai_history_message_deleted"
        assert "total_count" not in ws.last()
        assert ws.last()["live_session"] == "unavailable"
        assert ws.last()["live_session_patched"] is False


# ===================================================================
# handle_restore_ai_history_message (undo of a history delete)
# ===================================================================

# The wire-side message object — byte-for-byte what the client received in
# ai_history_loaded (snowflakes as digit strings, None stays null). The
# handler parses it back into the DB-row shape (_ROW above).
_RESTORE_MSG = {
    "id": 7,
    "local_id": 5,
    "role": "user",
    "content": "old text",
    "message_id": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
    "user_id": None,
}


class TestRestoreAiHistoryMessage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("db_result", ["restored", "exists_same"])
    @pytest.mark.parametrize(
        ("patched", "expected_state"), [(True, "patched"), (False, "no_match")]
    )
    async def test_success_live_session_states_and_total_count(
        self, ws, mock_db, db_result, patched, expected_state
    ):
        """Both 'restored' and the idempotent 'exists_same' ack as success,
        with the live session evaluated as usual either way."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        prev_row = {**_ROW, "id": 6, "content": "before"}
        next_row = {**_ROW, "id": 9, "content": "after"}
        mock_db.get_ai_history_neighbor_rows.return_value = (prev_row, next_row)
        mock_db.get_ai_history_count.return_value = 42
        cm = _fake_chat_manager(patched=patched, chats={424242424242424242: object()})
        mock_restore = AsyncMock(return_value=db_result)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.restore_message_by_row", mock_restore),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "424242424242424242", "message": dict(_RESTORE_MSG)}
            )

        msg = ws.last()
        assert msg["type"] == "ai_history_message_restored"
        assert msg["channel_id"] == "424242424242424242"
        assert msg["id"] == 7 and isinstance(msg["id"], int)
        assert msg["live_session"] == expected_state
        assert msg["live_session_patched"] is patched
        # Post-restore count for the channel, per the wire contract.
        assert msg["total_count"] == 42
        # The validated row reaches the DB with parsed values (== _ROW).
        mock_restore.assert_awaited_once_with(424242424242424242, dict(_ROW))
        mock_db.get_ai_history_neighbor_rows.assert_awaited_once_with(424242424242424242, 7)
        mock_db.get_ai_history_count.assert_awaited_once_with(424242424242424242)
        cm.insert_history_content.assert_called_once_with(
            424242424242424242,
            row=dict(_ROW),
            prev_row=prev_row,
            next_row=next_row,
            prev_occurrence=0,
            next_occurrence=0,
            expected_twins=1,
        )

    @pytest.mark.asyncio
    async def test_snowflake_strings_parsed_to_ints(self, ws, mock_db):
        """message_id/user_id arrive as digit strings and must reach the DB
        (and the in-memory matcher) as ints — the same values
        get_ai_history_message would return."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        wire_msg = {
            **_RESTORE_MSG,
            "message_id": "1234567890123456789",
            "user_id": "1111111111111111111",
        }
        mock_restore = AsyncMock(return_value="restored")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.restore_message_by_row", mock_restore),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_restore_ai_history_message(ws, {"channel_id": "123", "message": wire_msg})

        assert ws.last()["type"] == "ai_history_message_restored"
        expected_row = {
            **_ROW,
            "message_id": 1234567890123456789,
            "user_id": 1111111111111111111,
        }
        mock_restore.assert_awaited_once_with(123, expected_row)

    @pytest.mark.asyncio
    async def test_null_optional_fields_and_zero_local_id_accepted(self, ws, mock_db):
        """local_id 0 (non-negative) and all-NULL optional fields are valid —
        they round-trip as None into the DB row."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        wire_msg = {
            "id": 7,
            "local_id": 0,
            "role": "model",
            "content": "x",
            "message_id": None,
            "timestamp": None,
            "user_id": None,
        }
        mock_restore = AsyncMock(return_value="restored")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.restore_message_by_row", mock_restore),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_restore_ai_history_message(ws, {"channel_id": "123", "message": wire_msg})

        assert ws.last()["type"] == "ai_history_message_restored"
        mock_restore.assert_awaited_once_with(
            123,
            {
                "id": 7,
                "local_id": 0,
                "role": "model",
                "content": "x",
                "message_id": None,
                "timestamp": None,
                "user_id": None,
            },
        )

    @pytest.mark.asyncio
    async def test_content_preserved_verbatim_not_stripped(self, ws, mock_db):
        """Unlike the edit op, restore must NOT strip: the idempotency check
        and the live-session matcher compare exact strings against the
        original row."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        content = "  padded original \n"
        mock_restore = AsyncMock(return_value="restored")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.restore_message_by_row", mock_restore),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "content": content}}
            )
        assert ws.last()["type"] == "ai_history_message_restored"
        assert mock_restore.await_args.args[1]["content"] == content

    @pytest.mark.asyncio
    async def test_session_not_loaded_skips_insert(self, ws, mock_db):
        """Channel not in cm.chats: the benign common case — the matcher must
        NOT run (nothing in RAM can go stale)."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        cm = _fake_chat_manager(patched=True)  # chats defaults to {}
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="restored"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )

        msg = ws.last()
        assert msg["type"] == "ai_history_message_restored"
        assert msg["live_session"] == "not_loaded"
        assert msg["live_session_patched"] is False
        cm.insert_history_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_chat_manager_means_unavailable(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="restored"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        assert ws.last()["live_session"] == "unavailable"
        assert ws.last()["live_session_patched"] is False

    @pytest.mark.asyncio
    async def test_insert_exception_does_not_fail_request(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        cm = _fake_chat_manager(chats={123: object()})
        cm.insert_history_content.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="restored"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        msg = ws.last()
        assert msg["type"] == "ai_history_message_restored"
        assert msg["live_session"] == "error"
        assert msg["live_session_patched"] is False

    @pytest.mark.asyncio
    async def test_row_conflict(self, ws, mock_db):
        """'conflict' from the DB layer -> ROW_CONFLICT; no live-session work
        (the neighbor anchors ARE pre-fetched — they must be read before the
        restore so the restored row can't pollute the twin ordinals — but the
        expected-twins count and the memory insert are skipped)."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="conflict"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        assert ws.last()["code"] == "ROW_CONFLICT"
        assert ws.last()["scope"] == "ai_history"
        mock_db.count_identical_history_rows.assert_not_awaited()
        cm.insert_history_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_watermark_rejected_as_row_conflict(self, ws, mock_db):
        """B5: 'stale' from restore_message_by_row (the row id predates the
        channel's last force-replace rewrite) -> ROW_CONFLICT with the
        rewrite-specific message, so the frontend's discard+reload handling
        covers it. No expected-twins work, no live-session work."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="stale"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        msg = ws.last()
        assert msg["code"] == "ROW_CONFLICT"
        assert msg["message"] == "History was rewritten since this undo was recorded"
        assert msg["scope"] == "ai_history"
        mock_db.count_identical_history_rows.assert_not_awaited()
        cm.insert_history_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_midless_anchor_ordinals_and_expected_twins_threaded(self, ws, mock_db):
        """B1+B2: message_id-less anchors get their twin ordinals computed
        (count_identical_history_rows_before, BEFORE the restore) and the
        restored row gets its post-restore DB twin count
        (count_identical_history_rows) — all threaded into
        insert_history_content."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        ts = "2024-01-01T00:00:00+00:00"
        prev_row = {**_ROW, "id": 6, "content": "X", "timestamp": ts}
        next_row = {**_ROW, "id": 9, "content": "X", "timestamp": ts}
        mock_db.get_ai_history_neighbor_rows.return_value = (prev_row, next_row)
        mock_db.count_identical_history_rows.return_value = 3

        call_order: list[str] = []

        async def fake_ordinal(cid, anchor_id, role, anchor_ts, content):
            # prev anchor (id 6) has 1 earlier twin, next anchor (id 9) has 2.
            call_order.append("ordinal")
            return 1 if anchor_id == 6 else 2

        mock_db.count_identical_history_rows_before = AsyncMock(side_effect=fake_ordinal)

        async def fake_restore(cid, row):
            call_order.append("restore")
            return "restored"

        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(side_effect=fake_restore),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )

        assert ws.last()["type"] == "ai_history_message_restored"
        # Ordinals computed BEFORE the DB restore (the just-restored row must
        # not pollute the counts).
        assert call_order == ["ordinal", "ordinal", "restore"]
        assert mock_db.count_identical_history_rows_before.await_args_list[0].args == (
            123,
            6,
            "user",
            ts,
            "X",
        )
        assert mock_db.count_identical_history_rows_before.await_args_list[1].args == (
            123,
            9,
            "user",
            ts,
            "X",
        )
        # _RESTORE_MSG is message_id-less -> post-restore twin count fetched.
        mock_db.count_identical_history_rows.assert_awaited_once_with(
            123, "user", _RESTORE_MSG["timestamp"], _RESTORE_MSG["content"]
        )
        cm.insert_history_content.assert_called_once_with(
            123,
            row=dict(_ROW),
            prev_row=prev_row,
            next_row=next_row,
            prev_occurrence=1,
            next_occurrence=2,
            expected_twins=3,
        )

    @pytest.mark.asyncio
    async def test_message_id_row_skips_twin_counts(self, ws, mock_db):
        """Rows carrying a message_id are matched by it in memory — neither
        the anchor ordinals (mid anchors) nor the expected-twins count apply."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        prev_row = {**_ROW, "id": 6, "content": "before", "message_id": 60}
        next_row = {**_ROW, "id": 9, "content": "after", "message_id": 90}
        mock_db.get_ai_history_neighbor_rows.return_value = (prev_row, next_row)
        cm = _fake_chat_manager(patched=True, chats={123: object()})
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="restored"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=cm),
        ):
            await handle_restore_ai_history_message(
                ws,
                {
                    "channel_id": "123",
                    "message": {**_RESTORE_MSG, "message_id": "1234567890123456789"},
                },
            )

        assert ws.last()["type"] == "ai_history_message_restored"
        mock_db.count_identical_history_rows_before.assert_not_awaited()
        mock_db.count_identical_history_rows.assert_not_awaited()
        cm.insert_history_content.assert_called_once_with(
            123,
            row={**_ROW, "message_id": 1234567890123456789},
            prev_row=prev_row,
            next_row=next_row,
            prev_occurrence=0,
            next_occurrence=0,
            expected_twins=1,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"message": dict(_RESTORE_MSG)},  # no channel_id
            {"channel_id": "", "message": dict(_RESTORE_MSG)},  # empty channel_id
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": None}},  # no row id
        ],
    )
    async def test_missing_ids(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        await handle_restore_ai_history_message(ws, payload)
        assert ws.last()["code"] == "MISSING_ID"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"channel_id": "abc", "message": dict(_RESTORE_MSG)},
            {"channel_id": str(2**63), "message": dict(_RESTORE_MSG)},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": -7}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": 0}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": "7b"}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": True}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": 1.5}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "id": 2**63}},
            # Malformed snowflakes (the contract: "<digits>" | null).
            {"channel_id": "123", "message": {**_RESTORE_MSG, "message_id": "abc"}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "message_id": "1" * 21}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "message_id": str(2**63)}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "message_id": True}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "user_id": "abc"}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "user_id": 1.5}},
        ],
    )
    async def test_invalid_ids(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        await handle_restore_ai_history_message(ws, payload)
        assert ws.last()["code"] == "INVALID_ID"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"channel_id": "123"},  # message missing entirely
            {"channel_id": "123", "message": None},
            {"channel_id": "123", "message": "x"},
            {"channel_id": "123", "message": ["x"]},
            {"channel_id": "123", "message": 5},
            # role must be exactly 'user' or 'model'.
            {"channel_id": "123", "message": {**_RESTORE_MSG, "role": None}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "role": "assistant"}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "role": "USER"}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "role": True}},
            # content must be a string (no edit-style coercion here).
            {"channel_id": "123", "message": {**_RESTORE_MSG, "content": 123}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "content": ["x"]}},
            # local_id: None or a non-negative int within SQLite range.
            {"channel_id": "123", "message": {**_RESTORE_MSG, "local_id": -1}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "local_id": True}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "local_id": "5"}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "local_id": 1.5}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "local_id": 2**63}},
            # timestamp: None or a short string.
            {"channel_id": "123", "message": {**_RESTORE_MSG, "timestamp": 123}},
            {"channel_id": "123", "message": {**_RESTORE_MSG, "timestamp": "x" * 65}},
        ],
    )
    async def test_invalid_payload_shapes(self, ws, payload):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        await handle_restore_ai_history_message(ws, payload)
        assert ws.last()["code"] == "INVALID_PAYLOAD"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content", [None, "", "   \n\t "])
    async def test_missing_content(self, ws, content):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        await handle_restore_ai_history_message(
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "content": content}}
        )
        assert ws.last()["code"] == "MISSING_CONTENT"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    async def test_content_too_long(self, ws):
        from cogs.ai_core.api.dashboard_handlers import (
            MAX_EDIT_CONTENT_LENGTH,
            handle_restore_ai_history_message,
        )

        await handle_restore_ai_history_message(
            ws,
            {
                "channel_id": "123",
                "message": {**_RESTORE_MSG, "content": "x" * (MAX_EDIT_CONTENT_LENGTH + 1)},
            },
        )
        assert ws.last()["code"] == "CONTENT_TOO_LONG"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    async def test_content_exactly_max_length_succeeds(self, ws, mock_db):
        """The strict > comparison: exactly MAX_EDIT_CONTENT_LENGTH must pass."""
        from cogs.ai_core.api.dashboard_handlers import (
            MAX_EDIT_CONTENT_LENGTH,
            handle_restore_ai_history_message,
        )

        content = "x" * MAX_EDIT_CONTENT_LENGTH
        mock_restore = AsyncMock(return_value="restored")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.restore_message_by_row", mock_restore),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "content": content}}
            )
        assert ws.last()["type"] == "ai_history_message_restored"
        assert mock_restore.await_args.args[1]["content"] == content

    @pytest.mark.asyncio
    async def test_db_unavailable(self, ws):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        assert ws.last()["code"] == "DB_UNAVAILABLE"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    async def test_db_error_internal_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        assert ws.last()["code"] == "INTERNAL_ERROR"
        assert ws.last()["scope"] == "ai_history"

    @pytest.mark.asyncio
    async def test_count_error_after_restore_still_acks_without_total_count(self, ws, mock_db):
        """The post-restore COUNT is best-effort: the row is already durably
        restored, so a COUNT failure must NOT turn the ack into
        INTERNAL_ERROR (the client would keep hiding a row that is back)."""
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        mock_db.get_ai_history_count.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(return_value="restored"),
            ),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            await handle_restore_ai_history_message(
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        assert ws.last()["type"] == "ai_history_message_restored"
        assert "total_count" not in ws.last()
        assert ws.last()["live_session"] == "unavailable"
        assert ws.last()["live_session_patched"] is False


# ===================================================================
# Error-envelope scope tagging (B8)
# ===================================================================


class TestAiHistoryErrorScope:
    """Every error envelope from the three AI-history handlers must carry
    scope="ai_history": the dashboard shares one socket and one error shape
    with chat streaming, and an unscoped history error would trigger
    ChatManager's full chat-stream teardown (and chat errors would unstick
    the history editor's Save button)."""

    @pytest.mark.asyncio
    async def test_validation_and_db_unavailable_errors_carry_scope(self, ws):
        from cogs.ai_core.api.dashboard_handlers import (
            MAX_EDIT_CONTENT_LENGTH,
            handle_delete_ai_history_message,
            handle_edit_ai_history_message,
            handle_list_ai_channels,
            handle_load_ai_history,
        )

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_list_ai_channels(ws)  # DB_UNAVAILABLE
            await handle_load_ai_history(ws, {"channel_id": "123"})  # DB_UNAVAILABLE
            await handle_edit_ai_history_message(  # DB_UNAVAILABLE
                ws, {"channel_id": "123", "id": 7, "content": "x"}
            )
            await handle_delete_ai_history_message(  # DB_UNAVAILABLE
                ws, {"channel_id": "123", "id": 7}
            )
        await handle_load_ai_history(ws, {})  # MISSING_ID
        await handle_load_ai_history(ws, {"channel_id": "abc"})  # INVALID_ID
        await handle_edit_ai_history_message(ws, {"id": 7, "content": "x"})  # MISSING_ID
        await handle_edit_ai_history_message(  # INVALID_ID (channel)
            ws, {"channel_id": "abc", "id": 7, "content": "x"}
        )
        await handle_edit_ai_history_message(  # INVALID_ID (row id)
            ws, {"channel_id": "123", "id": 0, "content": "x"}
        )
        await handle_edit_ai_history_message(  # MISSING_CONTENT
            ws, {"channel_id": "123", "id": 7, "content": "   "}
        )
        await handle_edit_ai_history_message(  # CONTENT_TOO_LONG
            ws, {"channel_id": "123", "id": 7, "content": "x" * (MAX_EDIT_CONTENT_LENGTH + 1)}
        )
        await handle_delete_ai_history_message(ws, {"id": 7})  # MISSING_ID
        await handle_delete_ai_history_message(  # INVALID_ID (channel)
            ws, {"channel_id": "abc", "id": 7}
        )
        await handle_delete_ai_history_message(  # INVALID_ID (row id)
            ws, {"channel_id": "123", "id": 0}
        )

        errors = ws.find("error")
        assert len(errors) == 14
        assert all(e.get("scope") == "ai_history" for e in errors)

    @pytest.mark.asyncio
    async def test_not_found_and_internal_errors_carry_scope(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import (
            handle_delete_ai_history_message,
            handle_edit_ai_history_message,
            handle_list_ai_channels,
            handle_load_ai_history,
        )

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
        ):
            mock_db.get_ai_history_message.return_value = None  # MSG_NOT_FOUND (pre-read)
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
            mock_db.get_ai_history_message.side_effect = RuntimeError("boom")  # INTERNAL_ERROR
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
            await handle_delete_ai_history_message(ws, {"channel_id": "123", "id": 7})
            mock_db.get_ai_history.side_effect = RuntimeError("boom")  # INTERNAL_ERROR
            await handle_load_ai_history(ws, {"channel_id": "123"})
            mock_db.get_all_ai_channels_summary.side_effect = RuntimeError("boom")
            await handle_list_ai_channels(ws)  # INTERNAL_ERROR

        errors = ws.find("error")
        assert [e["code"] for e in errors] == [
            "MSG_NOT_FOUND",
            "MSG_NOT_FOUND",
            "INTERNAL_ERROR",
            "INTERNAL_ERROR",
            "INTERNAL_ERROR",
            "INTERNAL_ERROR",
        ]
        assert all(e.get("scope") == "ai_history" for e in errors)

    @pytest.mark.asyncio
    async def test_restore_errors_carry_scope(self, ws, mock_db):
        """Every error envelope from the restore handler — one per code —
        must carry scope="ai_history" (same teardown-crosstalk rationale as
        the other history ops)."""
        from cogs.ai_core.api.dashboard_handlers import (
            MAX_EDIT_CONTENT_LENGTH,
            handle_restore_ai_history_message,
        )

        with patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", False):
            await handle_restore_ai_history_message(  # DB_UNAVAILABLE
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
        await handle_restore_ai_history_message(  # MISSING_ID (channel)
            ws, {"message": dict(_RESTORE_MSG)}
        )
        await handle_restore_ai_history_message(  # INVALID_ID (channel)
            ws, {"channel_id": "abc", "message": dict(_RESTORE_MSG)}
        )
        await handle_restore_ai_history_message(  # INVALID_PAYLOAD (shape)
            ws, {"channel_id": "123"}
        )
        await handle_restore_ai_history_message(  # MISSING_ID (row id)
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "id": None}}
        )
        await handle_restore_ai_history_message(  # INVALID_ID (row id)
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "id": 0}}
        )
        await handle_restore_ai_history_message(  # INVALID_PAYLOAD (role)
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "role": "assistant"}}
        )
        await handle_restore_ai_history_message(  # MISSING_CONTENT
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "content": "   "}}
        )
        await handle_restore_ai_history_message(  # CONTENT_TOO_LONG
            ws,
            {
                "channel_id": "123",
                "message": {**_RESTORE_MSG, "content": "x" * (MAX_EDIT_CONTENT_LENGTH + 1)},
            },
        )
        await handle_restore_ai_history_message(  # INVALID_ID (message_id)
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "message_id": "abc"}}
        )
        await handle_restore_ai_history_message(  # INVALID_PAYLOAD (local_id)
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "local_id": -1}}
        )
        await handle_restore_ai_history_message(  # INVALID_PAYLOAD (timestamp)
            ws, {"channel_id": "123", "message": {**_RESTORE_MSG, "timestamp": "x" * 65}}
        )
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                AsyncMock(side_effect=["conflict", RuntimeError("boom")]),
            ),
        ):
            await handle_restore_ai_history_message(  # ROW_CONFLICT
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )
            await handle_restore_ai_history_message(  # INTERNAL_ERROR
                ws, {"channel_id": "123", "message": dict(_RESTORE_MSG)}
            )

        errors = ws.find("error")
        assert [e["code"] for e in errors] == [
            "DB_UNAVAILABLE",
            "MISSING_ID",
            "INVALID_ID",
            "INVALID_PAYLOAD",
            "MISSING_ID",
            "INVALID_ID",
            "INVALID_PAYLOAD",
            "MISSING_CONTENT",
            "CONTENT_TOO_LONG",
            "INVALID_ID",
            "INVALID_PAYLOAD",
            "INVALID_PAYLOAD",
            "ROW_CONFLICT",
            "INTERNAL_ERROR",
        ]
        assert all(e.get("scope") == "ai_history" for e in errors)

    @pytest.mark.asyncio
    async def test_update_race_not_found_carries_scope(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        mock_db.get_ai_history_message.return_value = dict(_ROW)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch(
                "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                AsyncMock(return_value=False),
            ),
        ):
            await handle_edit_ai_history_message(ws, {"channel_id": "123", "id": 7, "content": "x"})
        assert ws.last()["code"] == "MSG_NOT_FOUND"
        assert ws.last()["scope"] == "ai_history"


# ===================================================================
# ChatManager.patch_history_content
# ===================================================================


def _bare_manager(chats):
    """A ChatManager with just the ``chats`` dict — bypasses heavy __init__."""
    from cogs.ai_core.logic import ChatManager

    cm = ChatManager.__new__(ChatManager)
    cm.chats = chats
    return cm


class TestPatchHistoryContent:
    def test_patches_by_message_id(self):
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["hi"], "message_id": 10},
                        {"role": "model", "parts": ["old"], "message_id": 20},
                    ]
                }
            }
        )
        row = {"id": 2, "role": "model", "content": "old", "message_id": 20, "timestamp": None}
        assert cm.patch_history_content(50, row=row, new_content="new") is True
        assert cm.chats[50]["history"][1]["parts"] == ["new"]
        assert cm.chats[50]["history"][0]["parts"] == ["hi"]  # untouched

    def test_message_id_not_in_memory_returns_false(self):
        cm = _bare_manager({50: {"history": [{"role": "user", "parts": ["hi"], "message_id": 10}]}})
        row = {"id": 2, "role": "user", "content": "hi", "message_id": 999, "timestamp": None}
        assert cm.patch_history_content(50, row=row, new_content="new") is False
        assert cm.chats[50]["history"][0]["parts"] == ["hi"]

    def test_fallback_matches_role_timestamp_and_old_content(self):
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["other"], "timestamp": ts},
                        {"role": "model", "parts": ["old"], "timestamp": ts},
                    ]
                }
            }
        )
        # DB rows store the same instant in a different-but-equivalent format.
        row = {
            "id": 3,
            "role": "model",
            "content": "old",
            "message_id": None,
            "timestamp": "2024-01-01T00:00:00Z",
        }
        assert cm.patch_history_content(50, row=row, new_content="new") is True
        assert cm.chats[50]["history"][1]["parts"] == ["new"]
        assert cm.chats[50]["history"][0]["parts"] == ["other"]  # content mismatch skipped

    def test_fallback_no_match_returns_false(self):
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {
                            "role": "user",
                            "parts": ["something else"],
                            "timestamp": "2024-01-01T00:00:00+00:00",
                        }
                    ]
                }
            }
        )
        row = {
            "id": 3,
            "role": "user",
            "content": "old",
            "message_id": None,
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        assert cm.patch_history_content(50, row=row, new_content="new") is False

    def test_session_not_loaded_returns_false(self):
        cm = _bare_manager({})
        row = {"id": 1, "role": "user", "content": "old", "message_id": None, "timestamp": None}
        assert cm.patch_history_content(99, row=row, new_content="new") is False

    def test_occurrence_targets_second_of_identical_twins(self):
        """B3: identical (role, timestamp, content) twins — occurrence picks
        the right one instead of always patching the first."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                    ]
                }
            }
        )
        row = {"id": 9, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.patch_history_content(50, row=row, new_content="new", occurrence=1) is True
        assert cm.chats[50]["history"][0]["parts"] == ["twin"]  # first twin untouched
        assert cm.chats[50]["history"][1]["parts"] == ["new"]

    def test_occurrence_zero_default_patches_first_twin(self):
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                    ]
                }
            }
        )
        row = {"id": 8, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.patch_history_content(50, row=row, new_content="new") is True
        assert cm.chats[50]["history"][0]["parts"] == ["new"]
        assert cm.chats[50]["history"][1]["parts"] == ["twin"]

    def test_occurrence_beyond_matches_clamps_to_last(self):
        """Fewer twins than the ordinal: clamp to the LAST match (best-effort
        beats no-patch — an unpatched stale item would clobber the DB edit)."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                    ]
                }
            }
        )
        row = {"id": 9, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.patch_history_content(50, row=row, new_content="new", occurrence=5) is True
        assert cm.chats[50]["history"][0]["parts"] == ["twin"]
        assert cm.chats[50]["history"][1]["parts"] == ["new"]


# ===================================================================
# ChatManager.remove_history_content
# (same matching logic as patch_history_content — shared
#  _find_history_item_index — so the cases below mirror the patch suite)
# ===================================================================


class TestRemoveHistoryContent:
    def test_removes_by_message_id(self):
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["hi"], "message_id": 10},
                        {"role": "model", "parts": ["old"], "message_id": 20},
                    ]
                }
            }
        )
        row = {"id": 2, "role": "model", "content": "old", "message_id": 20, "timestamp": None}
        assert cm.remove_history_content(50, row=row) is True
        assert cm.chats[50]["history"] == [{"role": "user", "parts": ["hi"], "message_id": 10}]

    def test_message_id_not_in_memory_returns_false(self):
        cm = _bare_manager({50: {"history": [{"role": "user", "parts": ["hi"], "message_id": 10}]}})
        row = {"id": 2, "role": "user", "content": "hi", "message_id": 999, "timestamp": None}
        assert cm.remove_history_content(50, row=row) is False
        assert len(cm.chats[50]["history"]) == 1

    def test_fallback_matches_role_timestamp_and_content(self):
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["other"], "timestamp": ts},
                        {"role": "model", "parts": ["old"], "timestamp": ts},
                    ]
                }
            }
        )
        # DB rows store the same instant in a different-but-equivalent format.
        row = {
            "id": 3,
            "role": "model",
            "content": "old",
            "message_id": None,
            "timestamp": "2024-01-01T00:00:00Z",
        }
        assert cm.remove_history_content(50, row=row) is True
        # Content mismatch skipped — only the matching item is gone.
        assert cm.chats[50]["history"] == [{"role": "model", "parts": ["other"], "timestamp": ts}]

    def test_fallback_no_match_returns_false(self):
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {
                            "role": "user",
                            "parts": ["something else"],
                            "timestamp": "2024-01-01T00:00:00+00:00",
                        }
                    ]
                }
            }
        )
        row = {
            "id": 3,
            "role": "user",
            "content": "old",
            "message_id": None,
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        assert cm.remove_history_content(50, row=row) is False
        assert len(cm.chats[50]["history"]) == 1

    def test_session_not_loaded_returns_false(self):
        cm = _bare_manager({})
        row = {"id": 1, "role": "user", "content": "old", "message_id": None, "timestamp": None}
        assert cm.remove_history_content(99, row=row) is False

    def test_occurrence_targets_second_of_identical_twins(self):
        """Identical (role, timestamp, content) twins — occurrence picks the
        right one instead of always removing the first."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "n": 0},
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "n": 1},
                    ]
                }
            }
        )
        row = {"id": 9, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.remove_history_content(50, row=row, occurrence=1) is True
        assert [item["n"] for item in cm.chats[50]["history"]] == [0]  # first twin survives

    def test_occurrence_zero_default_removes_first_twin(self):
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "n": 0},
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "n": 1},
                    ]
                }
            }
        )
        row = {"id": 8, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.remove_history_content(50, row=row) is True
        assert [item["n"] for item in cm.chats[50]["history"]] == [1]

    def test_fallback_skips_message_id_carrying_twins(self):
        """Mixed twin set: an in-memory item that carries a message_id maps to
        a non-NULL-message_id DB row, so the fallback must skip it — the
        ordinal from count_identical_history_rows_before counts only
        message_id IS NULL rows. Without the skip, deleting the NULL-id DB
        twin removes the id-carrying memory item, breaking the Discord-side
        delete mirror for that message and letting the next diff-save
        resurrect the deleted row."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        # Back-filled twin (corresponds to DB row with message_id=111)
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "message_id": 111},
                        # NULL-message_id twin — the one the dashboard deletes
                        {"role": "model", "parts": ["twin"], "timestamp": ts},
                    ]
                }
            }
        )
        # DB ordinal: no NULL-message_id twins precede the target -> occurrence=0
        row = {"id": 2, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.remove_history_content(50, row=row, occurrence=0) is True
        # The id-carrying twin must survive; the NULL-id twin is gone.
        assert cm.chats[50]["history"] == [
            {"role": "model", "parts": ["twin"], "timestamp": ts, "message_id": 111}
        ]

    def test_occurrence_beyond_matches_clamps_to_last(self):
        """Fewer twins than the ordinal: clamp to the LAST match (best-effort
        beats no-removal — a stale item would resurrect the deleted row on
        the next save)."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "n": 0},
                        {"role": "model", "parts": ["twin"], "timestamp": ts, "n": 1},
                    ]
                }
            }
        )
        row = {"id": 9, "role": "model", "content": "twin", "message_id": None, "timestamp": ts}
        assert cm.remove_history_content(50, row=row, occurrence=5) is True
        assert [item["n"] for item in cm.chats[50]["history"]] == [0]


# ===================================================================
# ChatManager.insert_history_content
# (anchor matching via the shared _find_history_item_index; item built
#  exactly like storage.load_history's row->item conversion)
# ===================================================================


class TestInsertHistoryContent:
    @staticmethod
    def _row(row_id, content, message_id=None, ts="2024-01-01T00:00:00+00:00", user_id=None):
        return {
            "id": row_id,
            "local_id": row_id,
            "role": "user",
            "content": content,
            "message_id": message_id,
            "timestamp": ts,
            "user_id": user_id,
        }

    def test_inserts_before_matching_next_row(self):
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["a"], "timestamp": ts, "message_id": 10},
                        {"role": "user", "parts": ["c"], "timestamp": ts, "message_id": 30},
                    ]
                }
            }
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(2, "b", message_id=20),
                prev_row=self._row(1, "a", message_id=10),
                next_row=self._row(3, "c", message_id=30),
            )
            is True
        )
        history = cm.chats[50]["history"]
        assert [item["parts"] for item in history] == [["a"], ["b"], ["c"]]

    def test_inserts_after_prev_row_when_next_missing(self):
        """Deleted-then-restored LAST row: no next neighbor exists."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {50: {"history": [{"role": "user", "parts": ["a"], "timestamp": ts, "message_id": 10}]}}
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(2, "b", message_id=20),
                prev_row=self._row(1, "a", message_id=10),
                next_row=None,
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["a"], ["b"]]

    def test_falls_back_to_prev_when_next_unmatched(self):
        """next_row exists in the DB but its item is not in memory (e.g. the
        session was loaded before that turn): anchor on prev instead."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {50: {"history": [{"role": "user", "parts": ["a"], "timestamp": ts, "message_id": 10}]}}
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(2, "b", message_id=20),
                prev_row=self._row(1, "a", message_id=10),
                next_row=self._row(3, "c", message_id=999),
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["a"], ["b"]]

    def test_no_anchor_returns_false_and_list_unchanged(self):
        """Never append blindly: a force-save would persist a wrong order —
        the DB is already correct and the caller reports no_match."""
        ts = "2024-01-01T00:00:00+00:00"
        original = [{"role": "user", "parts": ["unrelated"], "timestamp": ts, "message_id": 77}]
        cm = _bare_manager({50: {"history": list(original)}})
        assert (
            cm.insert_history_content(
                50,
                row=self._row(2, "b", message_id=20),
                prev_row=self._row(1, "a", message_id=10),
                next_row=self._row(3, "c", message_id=30),
            )
            is False
        )
        assert cm.chats[50]["history"] == original

    def test_both_neighbors_none_with_empty_memory_seeds_at_zero(self):
        """B6: restoring a channel's ONLY row into an EMPTY loaded session is
        provably unambiguous — seed at index 0 (and write back through the
        session, not the ``or []`` fallback list), re-seeding the anchor
        chain so full-channel undo sequences repopulate live memory."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager({50: {"history": []}})
        assert (
            cm.insert_history_content(
                50, row=self._row(1, "only", ts=ts), prev_row=None, next_row=None
            )
            is True
        )
        assert cm.chats[50]["history"] == [{"role": "user", "parts": ["only"], "timestamp": ts}]

    def test_both_neighbors_none_with_missing_history_key_seeds_at_zero(self):
        """Same seed case when the session has no 'history' key at all — the
        ``or []`` fallback list must not swallow the write."""
        cm = _bare_manager({50: {}})
        assert (
            cm.insert_history_content(50, row=self._row(1, "only"), prev_row=None, next_row=None)
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["only"]]

    def test_both_neighbors_none_with_nonempty_memory_returns_false(self):
        """Both anchors None but memory holds items (unsaved/stale): order is
        genuinely ambiguous — keep refusing (caller reports no_match)."""
        ts = "2024-01-01T00:00:00+00:00"
        original = [{"role": "user", "parts": ["unsaved"], "timestamp": ts}]
        cm = _bare_manager({50: {"history": list(original)}})
        assert (
            cm.insert_history_content(50, row=self._row(1, "only"), prev_row=None, next_row=None)
            is False
        )
        assert cm.chats[50]["history"] == original

    def test_full_channel_undo_sequence_repopulates_memory(self):
        """B6 cascade: undoing a full-channel delete one row at a time — the
        first restore seeds the empty memory, each later restore anchors on
        the previously restored row."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager({50: {"history": []}})
        rows = [self._row(i, f"m{i}", ts=ts) for i in (1, 2, 3)]
        # LIFO undo order: 3 (anchors miss -> would have been no_match
        # pre-fix), then 2, then 1.
        assert cm.insert_history_content(50, row=rows[2], prev_row=None, next_row=None) is True
        assert cm.insert_history_content(50, row=rows[1], prev_row=None, next_row=rows[2]) is True
        assert cm.insert_history_content(50, row=rows[0], prev_row=None, next_row=rows[1]) is True
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["m1"], ["m2"], ["m3"]]

    def test_session_not_loaded_returns_false(self):
        cm = _bare_manager({})
        assert (
            cm.insert_history_content(
                99, row=self._row(2, "b"), prev_row=self._row(1, "a"), next_row=None
            )
            is False
        )

    def test_item_shape_matches_load_history_conversion_full(self):
        """All bookkeeping fields non-NULL -> carried onto the item (same
        rule as storage.load_history's row->item conversion)."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {50: {"history": [{"role": "user", "parts": ["a"], "timestamp": ts, "message_id": 10}]}}
        )
        row = {
            "id": 2,
            "local_id": 9,
            "role": "model",
            "content": "b",
            "message_id": 20,
            "timestamp": ts,
            "user_id": 42,
        }
        assert (
            cm.insert_history_content(
                50, row=row, prev_row=self._row(1, "a", message_id=10), next_row=None
            )
            is True
        )
        assert cm.chats[50]["history"][1] == {
            "role": "model",
            "parts": ["b"],
            "timestamp": ts,
            "message_id": 20,
            "user_id": 42,
        }

    def test_item_shape_omits_null_bookkeeping_keys(self):
        """NULL timestamp/message_id/user_id -> the keys are ABSENT (not
        None), exactly like load_history; row id/local_id never leak in."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {50: {"history": [{"role": "user", "parts": ["a"], "timestamp": ts, "message_id": 10}]}}
        )
        row = {
            "id": 2,
            "local_id": 9,
            "role": "model",
            "content": "b",
            "message_id": None,
            "timestamp": None,
            "user_id": None,
        }
        assert (
            cm.insert_history_content(
                50, row=row, prev_row=self._row(1, "a", message_id=10), next_row=None
            )
            is True
        )
        assert cm.chats[50]["history"][1] == {"role": "model", "parts": ["b"]}

    def test_already_present_row_is_not_duplicated(self):
        """Idempotent retry (exists_same), or the delete's memory removal had
        missed: the item never left memory — inserting again would duplicate
        it and a force-save would persist the duplicate."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["a"], "timestamp": ts, "message_id": 10},
                        {"role": "user", "parts": ["b"], "timestamp": ts, "message_id": 20},
                        {"role": "user", "parts": ["c"], "timestamp": ts, "message_id": 30},
                    ]
                }
            }
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(2, "b", message_id=20),
                prev_row=self._row(1, "a", message_id=10),
                next_row=self._row(3, "c", message_id=30),
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["a"], ["b"], ["c"]]

    def test_midless_twin_restored_despite_surviving_twin(self):
        """B1: memory holds ONE surviving mid-less twin while the DB (post-
        restore) holds TWO — mere existence must not skip the insert (the
        old guard matched the survivor and silently dropped the restore).
        The next_row anchor (the surviving twin at occurrence 0) places the
        restored copy before it."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["anchor"], "timestamp": ts, "message_id": 5},
                        {"role": "user", "parts": ["twin"], "timestamp": ts},
                    ]
                }
            }
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(10, "twin", ts=ts),
                prev_row=self._row(5, "anchor", message_id=5, ts=ts),
                next_row=self._row(20, "twin", ts=ts),
                expected_twins=2,
            )
            is True
        )
        history = cm.chats[50]["history"]
        assert [item["parts"] for item in history] == [["anchor"], ["twin"], ["twin"]]
        # Memory now matches the DB's twin count.
        assert sum(1 for item in history if item["parts"] == ["twin"]) == 2

    def test_midless_twin_idempotent_retry_not_duplicated(self):
        """B1: idempotent retry — memory already holds as many mid-less twins
        as the DB does (expected_twins met), so the insert is skipped."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["anchor"], "timestamp": ts, "message_id": 5},
                        {"role": "user", "parts": ["twin"], "timestamp": ts},
                        {"role": "user", "parts": ["twin"], "timestamp": ts},
                    ]
                }
            }
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(10, "twin", ts=ts),
                prev_row=self._row(5, "anchor", message_id=5, ts=ts),
                next_row=self._row(20, "twin", ts=ts),
                expected_twins=2,
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [
            ["anchor"],
            ["twin"],
            ["twin"],
        ]

    def test_midless_row_default_expected_twins_keeps_existence_guard(self):
        """expected_twins defaults to 1: a mid-less row whose item is already
        in memory is skipped exactly like before (no behavior change for
        plain retries without twins)."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager({50: {"history": [{"role": "user", "parts": ["b"], "timestamp": ts}]}})
        assert (
            cm.insert_history_content(
                50, row=self._row(2, "b", ts=ts), prev_row=None, next_row=None
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["b"]]

    def test_next_anchor_occurrence_targets_actual_db_neighbor(self):
        """B2: the next_row anchor is itself a mid-less twin — its twin
        ordinal must pick the ACTUAL DB neighbor, not the earliest twin
        (which would displace the restored row across everything between
        the twins)."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["X"], "timestamp": ts},
                        {"role": "user", "parts": ["hello"], "timestamp": ts, "message_id": 2},
                        {"role": "user", "parts": ["X"], "timestamp": ts},
                    ]
                }
            }
        )
        # DB ids: X(1), hello(2), R(3, deleted), X(4). R's next neighbor is
        # the SECOND X twin (ordinal 1).
        assert (
            cm.insert_history_content(
                50,
                row=self._row(3, "R", ts=ts),
                prev_row=self._row(2, "hello", message_id=2, ts=ts),
                next_row=self._row(4, "X", ts=ts),
                next_occurrence=1,
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [
            ["X"],
            ["hello"],
            ["R"],
            ["X"],
        ]

    def test_prev_anchor_occurrence_targets_actual_db_neighbor(self):
        """B2 mirror case for the prev anchor: restore after the SECOND twin,
        not after the earliest one."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["X"], "timestamp": ts},
                        {"role": "user", "parts": ["hello"], "timestamp": ts, "message_id": 2},
                        {"role": "user", "parts": ["X"], "timestamp": ts},
                    ]
                }
            }
        )
        # DB ids: X(1), hello(2), X(3), R(4, deleted). R's prev neighbor is
        # the SECOND X twin (ordinal 1); R has no next neighbor.
        assert (
            cm.insert_history_content(
                50,
                row=self._row(4, "R", ts=ts),
                prev_row=self._row(3, "X", ts=ts),
                next_row=None,
                prev_occurrence=1,
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [
            ["X"],
            ["hello"],
            ["X"],
            ["R"],
        ]

    def test_anchor_occurrence_beyond_matches_clamps_to_last(self):
        """Memory holds fewer anchor twins than the DB: clamp to the LAST
        match (same best-effort rule as the edit/delete ordinal machinery)."""
        ts = "2024-01-01T00:00:00+00:00"
        cm = _bare_manager(
            {
                50: {
                    "history": [
                        {"role": "user", "parts": ["X"], "timestamp": ts},
                        {"role": "user", "parts": ["X"], "timestamp": ts},
                    ]
                }
            }
        )
        assert (
            cm.insert_history_content(
                50,
                row=self._row(9, "R", ts=ts),
                prev_row=self._row(5, "X", ts=ts),
                next_row=None,
                prev_occurrence=4,
            )
            is True
        )
        assert [item["parts"] for item in cm.chats[50]["history"]] == [["X"], ["X"], ["R"]]


# ===================================================================
# Real-SQLite tests for the new Database methods
# (fixture pattern copied from tests/test_dashboard_pin_integration.py)
# ===================================================================


@pytest_asyncio.fixture
async def fresh_db():
    """Build an isolated Database instance without touching the singleton."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    tmp = tempfile.mkdtemp(prefix="ai-history-test-")
    data_dir = Path(tmp) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "bot_database.db"

    # init_schema creates `data/backups/` relative to CWD — chdir for isolation.
    original_cwd = Path.cwd()
    os.chdir(tmp)
    try:
        from utils.database import database as db_module

        # Bypass __new__ singleton — we want a standalone Database that doesn't
        # mutate any class-level state.
        instance = object.__new__(db_module.Database)
        # Manually initialize the attributes that __init__ normally sets.
        instance._initialized = True  # Prevent __init__ body from running again if called.
        instance.db_path = str(db_file)
        instance._schema_initialized = False
        instance._export_pending = False
        instance._export_delay = 3
        instance._export_tasks = set()
        instance._pool_semaphore = None
        instance._connection_count = 0
        instance._inflight_count = 0
        instance._conn_pool = None
        instance._pool_initialized = False
        instance._checkpoint_task = None
        instance._export_pending_keys = set()
        instance._dashboard_export_pending = set()
        import asyncio

        instance._export_lock = asyncio.Lock()
        instance._write_lock = None

        await instance.init_schema()
        try:
            yield instance
        finally:
            await instance.close_pool()
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_get_ai_history_message_roundtrip(fresh_db):
    row_id = await fresh_db.save_ai_message(
        123, "user", "hello", message_id=999, user_id=42, timestamp="2024-01-01T00:00:00+00:00"
    )
    assert row_id > 0

    row = await fresh_db.get_ai_history_message(123, row_id)
    assert row is not None
    assert row["id"] == row_id
    assert row["local_id"] == 1
    assert row["role"] == "user"
    assert row["content"] == "hello"
    assert row["message_id"] == 999
    assert row["user_id"] == 42
    assert row["timestamp"] == "2024-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_update_content_by_row_id_with_null_message_id(fresh_db):
    """Rows with message_id IS NULL are unreachable by message_id but editable by row id."""
    row_id = await fresh_db.save_ai_message(123, "model", "original")  # message_id stays NULL

    assert await fresh_db.update_ai_history_content(123, row_id, "edited") is True

    row = await fresh_db.get_ai_history_message(123, row_id)
    assert row is not None
    assert row["content"] == "edited"
    assert row["message_id"] is None


@pytest.mark.asyncio
async def test_update_wrong_channel_returns_false(fresh_db):
    row_id = await fresh_db.save_ai_message(123, "user", "hello")

    assert await fresh_db.update_ai_history_content(456, row_id, "nope") is False

    # Original row untouched; cross-channel read returns None.
    row = await fresh_db.get_ai_history_message(123, row_id)
    assert row is not None and row["content"] == "hello"
    assert await fresh_db.get_ai_history_message(456, row_id) is None


@pytest.mark.asyncio
async def test_get_ai_history_message_missing_returns_none(fresh_db):
    assert await fresh_db.get_ai_history_message(123, 424242) is None


@pytest.mark.asyncio
async def test_delete_ai_history_row_with_null_message_id(fresh_db):
    """Rows with message_id IS NULL are unreachable by message_id but deletable by row id."""
    row_id = await fresh_db.save_ai_message(123, "model", "doomed")  # message_id stays NULL
    keeper_id = await fresh_db.save_ai_message(123, "user", "keeper")
    assert await fresh_db.get_ai_history_count(123) == 2

    assert await fresh_db.delete_ai_history_row(123, row_id) is True

    # The row is gone, the count dropped, and the neighbor survived.
    assert await fresh_db.get_ai_history_message(123, row_id) is None
    assert await fresh_db.get_ai_history_count(123) == 1
    row = await fresh_db.get_ai_history_message(123, keeper_id)
    assert row is not None and row["content"] == "keeper"

    # A second delete of the same id matches nothing.
    assert await fresh_db.delete_ai_history_row(123, row_id) is False


@pytest.mark.asyncio
async def test_delete_wrong_channel_returns_false(fresh_db):
    row_id = await fresh_db.save_ai_message(123, "user", "hello")

    assert await fresh_db.delete_ai_history_row(456, row_id) is False

    # Original row untouched; channel scoping held.
    row = await fresh_db.get_ai_history_message(123, row_id)
    assert row is not None and row["content"] == "hello"
    assert await fresh_db.get_ai_history_count(123) == 1


@pytest.mark.asyncio
async def test_delete_ai_history_row_schedules_export_like_update(fresh_db):
    """Export-side-effect parity with update_ai_history_content: a successful
    delete schedules the channel's auto-export; a no-op delete does not."""
    row_id = await fresh_db.save_ai_message(321, "model", "to delete")
    # save_ai_message itself schedules an export — clear the slate so the
    # assertions below observe the delete's behavior, not the save's.
    fresh_db._export_pending_keys.clear()

    # No-op delete (wrong channel): nothing scheduled.
    assert await fresh_db.delete_ai_history_row(999, row_id) is False
    assert "channel_999" not in fresh_db._export_pending_keys

    assert await fresh_db.delete_ai_history_row(321, row_id) is True
    assert "channel_321" in fresh_db._export_pending_keys


@pytest.mark.asyncio
async def test_channels_summary_includes_last_active(fresh_db):
    await fresh_db.save_ai_message(1, "user", "a", timestamp="2024-01-01T00:00:00+00:00")
    await fresh_db.save_ai_message(1, "model", "b", timestamp="2024-06-01T00:00:00+00:00")
    await fresh_db.save_ai_message(2, "user", "c", timestamp="2024-03-01T00:00:00+00:00")

    summary = await fresh_db.get_all_ai_channels_summary()
    by_channel = {s["channel_id"]: s for s in summary}
    assert by_channel[1]["message_count"] == 2
    # SQLite datetime() canonicalizes to 'YYYY-MM-DD HH:MM:SS' (UTC) so MAX
    # compares chronologically across mixed legacy/ISO-T formats.
    assert by_channel[1]["last_active"] == "2024-06-01 00:00:00"
    assert by_channel[2]["last_active"] == "2024-03-01 00:00:00"


@pytest.mark.asyncio
async def test_channels_summary_last_active_mixed_formats_chronological(fresh_db):
    """B4: a same-day legacy 'YYYY-MM-DD HH:MM:SS' row at 23:59 must beat an
    ISO-T row at 00:00 — lexicographic MAX picked the T row ('T' > ' ')."""
    await fresh_db.save_ai_message(9, "user", "a", timestamp="2026-05-13T00:00:00+00:00")
    await fresh_db.save_ai_message(9, "model", "b", timestamp="2026-05-13 23:59:00")

    summary = await fresh_db.get_all_ai_channels_summary()
    by_channel = {s["channel_id"]: s for s in summary}
    assert by_channel[9]["last_active"] == "2026-05-13 23:59:00"


@pytest.mark.asyncio
async def test_thai_emoji_content_roundtrip(fresh_db):
    """Unicode round-trip through the real SQLite update/read pair — the
    docs/content in this codebase are Thai-heavy, so non-ASCII must survive."""
    thai = "สวัสดีครับ ผมชื่อเฟาสต์ \U0001f916"
    row_id = await fresh_db.save_ai_message(123, "model", thai)
    row = await fresh_db.get_ai_history_message(123, row_id)
    assert row is not None and row["content"] == thai

    edited = "แก้ไขแล้วนะครับ ✅🎉 ภาษาไทย + emoji 😀"
    assert await fresh_db.update_ai_history_content(123, row_id, edited) is True
    row = await fresh_db.get_ai_history_message(123, row_id)
    assert row is not None and row["content"] == edited


@pytest.mark.asyncio
async def test_count_identical_history_rows_before(fresh_db):
    """B3: twin ordinal counting (message_id IS NULL, timestamp IS ?)."""
    ts = "2024-01-01T00:00:00+00:00"
    ids = [await fresh_db.save_ai_message(31, "model", "twin", timestamp=ts) for _ in range(3)]
    # A row with a message_id and a different-content row must not count.
    await fresh_db.save_ai_message(31, "model", "twin", message_id=777, timestamp=ts)
    await fresh_db.save_ai_message(31, "model", "other", timestamp=ts)

    counts = [
        await fresh_db.count_identical_history_rows_before(31, rid, "model", ts, "twin")
        for rid in ids
    ]
    assert counts == [0, 1, 2]
    # Channel scoping: nothing counted for another channel.
    assert await fresh_db.count_identical_history_rows_before(32, ids[2], "model", ts, "twin") == 0


@pytest.mark.asyncio
async def test_count_identical_history_rows_total(fresh_db):
    """B1: total twin count (no id bound) — the DB side of the restore
    handler's expected-twins computation. Same filters as the _before
    variant: message_id IS NULL only, timestamp IS ? (NULL matches NULL),
    channel-scoped."""
    ts = "2024-01-01T00:00:00+00:00"
    for _ in range(3):
        await fresh_db.save_ai_message(33, "model", "twin", timestamp=ts)
    # A message_id-carrying twin and a different-content row must not count.
    await fresh_db.save_ai_message(33, "model", "twin", message_id=777, timestamp=ts)
    await fresh_db.save_ai_message(33, "model", "other", timestamp=ts)

    assert await fresh_db.count_identical_history_rows(33, "model", ts, "twin") == 3
    assert await fresh_db.count_identical_history_rows(33, "model", ts, "other") == 1
    assert await fresh_db.count_identical_history_rows(33, "user", ts, "twin") == 0
    # Channel scoping: nothing counted for another channel.
    assert await fresh_db.count_identical_history_rows(34, "model", ts, "twin") == 0


@pytest.mark.asyncio
async def test_get_ai_history_includes_local_id(fresh_db):
    await fresh_db.save_ai_message(7, "user", "x")
    await fresh_db.save_ai_message(7, "model", "y")

    rows = await fresh_db.get_ai_history(7, limit=10)
    assert [r["local_id"] for r in rows] == [1, 2]

    rows_unlimited = await fresh_db.get_ai_history(7)
    assert [r["local_id"] for r in rows_unlimited] == [1, 2]


@pytest.mark.asyncio
async def test_restore_round_trip_preserves_id_and_ordering(fresh_db):
    """Delete then restore: the row comes back with its ORIGINAL primary-key
    id, so get_ai_history returns it in its original position between its
    neighbors (ordering is by id)."""
    ts = "2024-01-01T00:00:00+00:00"
    ids = [await fresh_db.save_ai_message(55, "user", f"m{i}", timestamp=ts) for i in range(3)]
    row = await fresh_db.get_ai_history_message(55, ids[1])
    assert row is not None

    assert await fresh_db.delete_ai_history_row(55, ids[1]) is True
    assert await fresh_db.get_ai_history_count(55) == 2

    assert await fresh_db.restore_ai_history_row(55, dict(row)) == "restored"
    assert await fresh_db.get_ai_history_count(55) == 3
    rows = await fresh_db.get_ai_history(55)
    assert [r["id"] for r in rows] == ids
    assert [r["content"] for r in rows] == ["m0", "m1", "m2"]
    # The restored row is column-for-column the original.
    assert rows[1] == row


@pytest.mark.asyncio
async def test_restore_exists_same_is_idempotent(fresh_db):
    """A retry (lost ack) finds the row already back with the same role AND
    content -> 'exists_same', and nothing is duplicated."""
    row_id = await fresh_db.save_ai_message(56, "model", "kept")
    row = await fresh_db.get_ai_history_message(56, row_id)
    assert row is not None

    assert await fresh_db.restore_ai_history_row(56, dict(row)) == "exists_same"
    assert await fresh_db.get_ai_history_count(56) == 1


@pytest.mark.asyncio
async def test_restore_conflict_on_different_content_or_role(fresh_db):
    """The id is occupied by a DIFFERENT row (recycled id) -> 'conflict',
    and the existing row is left untouched."""
    row_id = await fresh_db.save_ai_message(57, "model", "current")
    row = await fresh_db.get_ai_history_message(57, row_id)
    assert row is not None

    assert await fresh_db.restore_ai_history_row(57, {**row, "content": "other"}) == "conflict"
    assert await fresh_db.restore_ai_history_row(57, {**row, "role": "user"}) == "conflict"
    kept = await fresh_db.get_ai_history_message(57, row_id)
    assert kept is not None and kept["content"] == "current" and kept["role"] == "model"


@pytest.mark.asyncio
async def test_restore_conflict_via_message_id_unique_index(fresh_db):
    """The PK id is free, but another row in the channel already carries the
    restored row's message_id: the partial unique index on
    (channel_id, message_id) rejects the insert -> 'conflict'."""
    row_id = await fresh_db.save_ai_message(58, "user", "original", message_id=777)
    row = await fresh_db.get_ai_history_message(58, row_id)
    assert row is not None

    assert await fresh_db.delete_ai_history_row(58, row_id) is True
    # The same Discord message gets re-saved under a NEW row id.
    new_id = await fresh_db.save_ai_message(58, "user", "resaved", message_id=777)
    assert new_id != row_id

    assert await fresh_db.restore_ai_history_row(58, dict(row)) == "conflict"
    # The failed insert must not have landed.
    assert await fresh_db.get_ai_history_message(58, row_id) is None
    assert await fresh_db.get_ai_history_count(58) == 1


@pytest.mark.asyncio
async def test_restore_with_null_optional_fields(fresh_db):
    """NULL message_id/timestamp/user_id/local_id are inserted verbatim and
    read back as None — in particular the NULL timestamp must NOT be
    backfilled by the column default (the live-session matcher compares it)."""
    anchor_id = await fresh_db.save_ai_message(59, "user", "anchor")
    row = {
        "id": anchor_id + 50,
        "local_id": None,
        "role": "model",
        "content": "ghost",
        "message_id": None,
        "timestamp": None,
        "user_id": None,
    }
    assert await fresh_db.restore_ai_history_row(59, dict(row)) == "restored"

    got = await fresh_db.get_ai_history_message(59, anchor_id + 50)
    assert got == row


@pytest.mark.asyncio
async def test_restore_schedules_export_like_delete(fresh_db):
    """Export-side-effect parity with the sibling methods: a real insert
    schedules the channel's auto-export; exists_same/conflict do not."""
    row_id = await fresh_db.save_ai_message(60, "model", "to restore")
    row = await fresh_db.get_ai_history_message(60, row_id)
    assert await fresh_db.delete_ai_history_row(60, row_id) is True
    fresh_db._export_pending_keys.clear()

    assert await fresh_db.restore_ai_history_row(60, dict(row)) == "restored"
    assert "channel_60" in fresh_db._export_pending_keys

    fresh_db._export_pending_keys.clear()
    assert await fresh_db.restore_ai_history_row(60, dict(row)) == "exists_same"
    assert await fresh_db.restore_ai_history_row(60, {**row, "content": "other"}) == "conflict"
    assert "channel_60" not in fresh_db._export_pending_keys


async def _create_summaries_table(fresh_db, channel_id, end_time):
    """Create the lazily-created conversation_summaries table (same DDL as
    SummaryArchiver.init_schema) and insert one summary row for the channel."""
    async with fresh_db.get_write_connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                user_id INTEGER,
                summary TEXT NOT NULL,
                key_topics TEXT,
                key_decisions TEXT,
                start_time DATETIME,
                end_time DATETIME,
                message_count INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute(
            """INSERT INTO conversation_summaries
               (channel_id, summary, end_time, message_count) VALUES (?, ?, ?, ?)""",
            (channel_id, "summary text", end_time, 20),
        )
        await conn.commit()


async def _get_summarized_at(fresh_db, channel_id, row_id):
    async with fresh_db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT summarized_at FROM ai_history WHERE channel_id = ? AND id = ?",
            (channel_id, row_id),
        )
        fetched = await cursor.fetchone()
        assert fetched is not None
        return fetched[0]


@pytest.mark.asyncio
async def test_restore_restamps_summarized_at_when_covered_by_summary(fresh_db):
    """B3: a restored row whose timestamp falls within the channel's newest
    summary window gets summarized_at re-stamped (the wire contract cannot
    round-trip the stamp), so the consolidator sweep does NOT re-select it
    (no duplicate facts in long-term memory; with
    CONSOLIDATOR_DELETE_ORIGINALS=1 it would even re-delete the row)."""
    row_ts = "2024-01-01T10:00:00+00:00"
    row_id = await fresh_db.save_ai_message(62, "user", "already summarized", timestamp=row_ts)
    row = await fresh_db.get_ai_history_message(62, row_id)
    assert row is not None
    # end_time uses a SPACE separator on purpose: 'T' > ' ' lexically, so a
    # raw-string compare would wrongly say row > boundary — the re-stamp must
    # compare via datetime.fromisoformat (chronologically row < boundary).
    await _create_summaries_table(fresh_db, 62, "2024-01-01 12:00:00+00:00")

    assert await fresh_db.delete_ai_history_row(62, row_id) is True
    assert await fresh_db.restore_ai_history_row(62, dict(row)) == "restored"

    assert await _get_summarized_at(fresh_db, 62, row_id) is not None
    # The consolidator's sweep (summarized_at IS NULL + older than cutoff)
    # must no longer select the restored row.
    async with fresh_db.get_connection() as conn:
        cursor = await conn.execute(
            """SELECT id FROM ai_history
               WHERE channel_id = ? AND summarized_at IS NULL AND timestamp < ?""",
            (62, "2026-01-01T00:00:00+00:00"),
        )
        assert await cursor.fetchall() == []
    # The row still reads back like the original through the wire-contract
    # columns (summarized_at is not part of get_ai_history_message).
    assert await fresh_db.get_ai_history_message(62, row_id) == row


@pytest.mark.asyncio
async def test_restore_summarized_at_null_without_summaries_table(fresh_db):
    """B3: conversation_summaries is created lazily and may not exist — a
    missing table means 'never summarized' and must not fail the restore."""
    row_id = await fresh_db.save_ai_message(63, "user", "x", timestamp="2024-01-01T00:00:00+00:00")
    row = await fresh_db.get_ai_history_message(63, row_id)
    assert await fresh_db.delete_ai_history_row(63, row_id) is True

    assert await fresh_db.restore_ai_history_row(63, dict(row)) == "restored"
    assert await _get_summarized_at(fresh_db, 63, row_id) is None


@pytest.mark.asyncio
async def test_restore_summarized_at_null_when_row_newer_than_summaries(fresh_db):
    """B3: a row newer than the channel's newest summary window was never
    rolled into a summary — no stamp."""
    row_ts = "2024-06-01T00:00:00+00:00"
    row_id = await fresh_db.save_ai_message(64, "user", "newer", timestamp=row_ts)
    row = await fresh_db.get_ai_history_message(64, row_id)
    await _create_summaries_table(fresh_db, 64, "2024-01-01T12:00:00+00:00")

    assert await fresh_db.delete_ai_history_row(64, row_id) is True
    assert await fresh_db.restore_ai_history_row(64, dict(row)) == "restored"
    assert await _get_summarized_at(fresh_db, 64, row_id) is None


@pytest.mark.asyncio
async def test_restore_summarized_at_null_for_null_timestamp_or_other_channel(fresh_db):
    """B3 edge cases: a NULL-timestamp row can't be compared (no stamp), and
    another channel's summaries must not bleed over."""
    await _create_summaries_table(fresh_db, 65, "2030-01-01T00:00:00+00:00")

    # NULL timestamp: inserted verbatim (existing contract) — no stamp.
    anchor_id = await fresh_db.save_ai_message(65, "user", "anchor")
    null_ts_row = {
        "id": anchor_id + 50,
        "local_id": None,
        "role": "model",
        "content": "ghost",
        "message_id": None,
        "timestamp": None,
        "user_id": None,
    }
    assert await fresh_db.restore_ai_history_row(65, dict(null_ts_row)) == "restored"
    assert await _get_summarized_at(fresh_db, 65, anchor_id + 50) is None

    # Channel scoping: channel 66 has no summaries of its own.
    row_id = await fresh_db.save_ai_message(66, "user", "x", timestamp="2024-01-01T00:00:00+00:00")
    row = await fresh_db.get_ai_history_message(66, row_id)
    assert await fresh_db.delete_ai_history_row(66, row_id) is True
    assert await fresh_db.restore_ai_history_row(66, dict(row)) == "restored"
    assert await _get_summarized_at(fresh_db, 66, row_id) is None


@pytest.mark.asyncio
async def test_restore_reassigns_taken_local_id(fresh_db):
    """B4: the deleted row held MAX(local_id) and a later save re-issued it —
    the restore must NOT create a duplicate (channel_id, local_id) pair (the
    auto-export renames local_id to 'id'; duplicates make it ambiguous).
    The restored row gets MAX(local_id)+1 instead."""
    ids = [await fresh_db.save_ai_message(67, "user", f"m{i}") for i in range(3)]
    deleted = await fresh_db.get_ai_history_message(67, ids[2])
    assert deleted is not None and deleted["local_id"] == 3

    assert await fresh_db.delete_ai_history_row(67, ids[2]) is True
    # The conversation continues: the next save re-issues local_id 3.
    new_id = await fresh_db.save_ai_message(67, "user", "newer")
    new_row = await fresh_db.get_ai_history_message(67, new_id)
    assert new_row is not None and new_row["local_id"] == 3

    assert await fresh_db.restore_ai_history_row(67, dict(deleted)) == "restored"
    restored = await fresh_db.get_ai_history_message(67, ids[2])
    assert restored is not None and restored["local_id"] == 4
    # No duplicate (channel_id, local_id) pairs remain.
    rows = await fresh_db.get_ai_history(67)
    local_ids = [r["local_id"] for r in rows]
    assert sorted(local_ids) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_restore_keeps_original_local_id_when_free(fresh_db):
    """B4 control: the common case — the original local_id is still free, so
    the restore stays byte-identical to the original row."""
    ids = [await fresh_db.save_ai_message(68, "user", f"m{i}") for i in range(3)]
    deleted = await fresh_db.get_ai_history_message(68, ids[1])

    assert await fresh_db.delete_ai_history_row(68, ids[1]) is True
    assert await fresh_db.restore_ai_history_row(68, dict(deleted)) == "restored"
    assert await fresh_db.get_ai_history_message(68, ids[1]) == deleted


@pytest.mark.asyncio
async def test_get_ai_history_neighbor_rows(fresh_db):
    """Full prev/next rows by id within the channel; None at the edges; the
    deleted row's own id still anchors between its old neighbors."""
    ids = [await fresh_db.save_ai_message(61, "user", f"m{i}") for i in range(3)]
    rows = await fresh_db.get_ai_history(61)

    prev_row, next_row = await fresh_db.get_ai_history_neighbor_rows(61, ids[1])
    assert prev_row == rows[0]
    assert next_row == rows[2]

    # Edges: first row has no prev, last row has no next.
    assert await fresh_db.get_ai_history_neighbor_rows(61, ids[0]) == (None, rows[1])
    assert await fresh_db.get_ai_history_neighbor_rows(61, ids[2]) == (rows[1], None)

    # The row id need not exist (the restore computes anchors for a row that
    # was just re-inserted — and a deleted id behaves the same way).
    await fresh_db.delete_ai_history_row(61, ids[1])
    prev_row, next_row = await fresh_db.get_ai_history_neighbor_rows(61, ids[1])
    assert prev_row == rows[0]
    assert next_row == rows[2]

    # Channel scoping: another channel sees nothing.
    assert await fresh_db.get_ai_history_neighbor_rows(999, ids[1]) == (None, None)


@pytest.mark.asyncio
async def test_force_replace_watermark_rejects_pre_rewrite_undo(fresh_db):
    """B5: _replace_history_db (force=True save) DELETE-all + re-INSERTs with
    fresh AUTOINCREMENT ids and records the smallest id it minted; a restore
    of a row id BELOW that watermark (an undo entry captured before the
    rewrite) is rejected as 'stale' — it would otherwise silently land at
    position 0 with a success ack. Rows deleted AFTER the rewrite carry ids
    >= the watermark and still restore normally."""
    import cogs.ai_core.storage as storage

    channel_id = 69
    ts = "2024-01-01T00:00:00+00:00"
    ids = [
        await fresh_db.save_ai_message(channel_id, "user", f"m{i}", timestamp=ts) for i in range(3)
    ]
    deleted = await fresh_db.get_ai_history_message(channel_id, ids[1])
    assert deleted is not None
    assert await fresh_db.delete_ai_history_row(channel_id, ids[1]) is True

    chat_data = {
        "history": [
            {"role": "user", "parts": ["m0"], "timestamp": ts},
            {"role": "user", "parts": ["m2"], "timestamp": ts},
        ],
        "_db_loaded": True,
    }
    try:
        with (
            patch.object(storage, "db", fresh_db),
            patch.object(storage, "DATABASE_AVAILABLE", True),
        ):
            assert await storage._replace_history_db(channel_id, chat_data, 100) is True

            rows = await fresh_db.get_ai_history(channel_id)
            new_min_id = min(r["id"] for r in rows)
            # AUTOINCREMENT: every rewritten row got a fresh id above the old max.
            assert new_min_id > max(ids)
            assert storage._post_replace_min_id[channel_id] == new_min_id

            # The pre-rewrite undo entry is stale — rejected, nothing inserted.
            assert await storage.restore_message_by_row(channel_id, dict(deleted)) == "stale"
            assert await fresh_db.get_ai_history_count(channel_id) == 2

            # A row deleted AFTER the rewrite restores normally.
            victim = (await fresh_db.get_ai_history(channel_id))[-1]
            assert await fresh_db.delete_ai_history_row(channel_id, victim["id"]) is True
            assert await storage.restore_message_by_row(channel_id, dict(victim)) == "restored"
            assert await fresh_db.get_ai_history_count(channel_id) == 2
    finally:
        _storage_cleanup(channel_id)


@pytest.mark.asyncio
async def test_restore_without_prior_force_replace_unaffected(fresh_db):
    """B5 control: no force-replace ever ran for the channel (no watermark
    entry) — restore behaves exactly as before."""
    import cogs.ai_core.storage as storage

    channel_id = 70
    row_id = await fresh_db.save_ai_message(channel_id, "user", "x")
    row = await fresh_db.get_ai_history_message(channel_id, row_id)
    assert await fresh_db.delete_ai_history_row(channel_id, row_id) is True

    try:
        with (
            patch.object(storage, "db", fresh_db),
            patch.object(storage, "DATABASE_AVAILABLE", True),
        ):
            assert channel_id not in storage._post_replace_min_id
            assert await storage.restore_message_by_row(channel_id, dict(row)) == "restored"
    finally:
        _storage_cleanup(channel_id)


# ===================================================================
# ws_dashboard routing + rate-exemption wiring
# (server fixture recipe from tests/test_ws_dashboard.py)
# ===================================================================


@pytest.fixture()
def server():
    """Create a DashboardWebSocketServer with a mocked Gemini client."""
    with patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "ANTHROPIC_API_KEY": "",
            "DEFAULT_AI_PROVIDER": "gemini",
            "DASHBOARD_WS_TOKEN": "",
            # Pin the SDK path explicitly — see tests/test_ws_dashboard.py for
            # the full rationale (module default is "cli").
            "CLAUDE_BACKEND": "api",
        },
    ):
        with patch("cogs.ai_core.api.ws_dashboard.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            import cogs.ai_core.api.ws_dashboard as ws_module
            from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

            with patch.object(ws_module, "_CLAUDE_BACKEND", "api"):
                srv = DashboardWebSocketServer()
                srv.gemini_client = MagicMock()
                yield srv


class TestAiHistoryRouting:
    @pytest.mark.asyncio
    async def test_routes_list_ai_channels(self, server, ws):
        with patch(
            "cogs.ai_core.api.ws_dashboard.handle_list_ai_channels", new_callable=AsyncMock
        ) as handler:
            await server.handle_message(ws, {"type": "list_ai_channels"}, "c1")
        handler.assert_awaited_once_with(ws)

    @pytest.mark.asyncio
    async def test_routes_load_ai_history(self, server, ws):
        data = {"type": "load_ai_history", "channel_id": "123", "limit": 10}
        with patch(
            "cogs.ai_core.api.ws_dashboard.handle_load_ai_history", new_callable=AsyncMock
        ) as handler:
            await server.handle_message(ws, data, "c1")
        handler.assert_awaited_once_with(ws, data)

    @pytest.mark.asyncio
    async def test_routes_edit_ai_history_message(self, server, ws):
        data = {"type": "edit_ai_history_message", "channel_id": "123", "id": 7, "content": "x"}
        with patch(
            "cogs.ai_core.api.ws_dashboard.handle_edit_ai_history_message",
            new_callable=AsyncMock,
        ) as handler:
            await server.handle_message(ws, data, "c1")
        handler.assert_awaited_once_with(ws, data)

    @pytest.mark.asyncio
    async def test_routes_delete_ai_history_message(self, server, ws):
        data = {"type": "delete_ai_history_message", "channel_id": "123", "id": 7}
        with patch(
            "cogs.ai_core.api.ws_dashboard.handle_delete_ai_history_message",
            new_callable=AsyncMock,
        ) as handler:
            await server.handle_message(ws, data, "c1")
        handler.assert_awaited_once_with(ws, data)

    @pytest.mark.asyncio
    async def test_routes_restore_ai_history_message(self, server, ws):
        data = {
            "type": "restore_ai_history_message",
            "channel_id": "123",
            "message": dict(_RESTORE_MSG),
        }
        with patch(
            "cogs.ai_core.api.ws_dashboard.handle_restore_ai_history_message",
            new_callable=AsyncMock,
        ) as handler:
            await server.handle_message(ws, data, "c1")
        handler.assert_awaited_once_with(ws, data)

    def test_rate_exemption_wiring(self):
        from cogs.ai_core.api.ws_dashboard import DashboardWebSocketServer

        exempt = DashboardWebSocketServer.RATE_EXEMPT_MESSAGE_TYPES
        assert "list_ai_channels" in exempt
        # B6: the heaviest read op (up to 2000 full-content rows serialized on
        # the bot's event loop) must NOT be exempt — like the write ops below.
        assert "load_ai_history" not in exempt
        # The write ops must stay rate-limited.
        assert "edit_ai_history_message" not in exempt
        assert "delete_ai_history_message" not in exempt
        assert "restore_ai_history_message" not in exempt


# ===================================================================
# Concurrency regressions: edit vs in-flight load (B1) and
# edit vs diff-mode save (B2)
# ===================================================================


def _session_harness():
    """A minimal SessionMixin consumer exercising the real get_chat_session."""
    from cogs.ai_core.session_mixin import SessionMixin

    harness_cls = type(
        "_SessionHarness", (SessionMixin,), {"_enforce_channel_limit": lambda self: 0}
    )
    mgr = harness_cls()
    mgr.bot = MagicMock()
    mgr.client = object()  # truthy — skip the CLI-mode gate
    mgr.chats = {}
    mgr.last_accessed = {}
    return mgr


def _storage_cleanup(channel_id):
    import cogs.ai_core.storage as storage

    storage.invalidate_cache(channel_id)
    storage._db_loaded_channels.discard(channel_id)
    storage._history_locks.pop(channel_id, None)
    storage._post_replace_min_id.pop(channel_id, None)


class TestEditDuringInflightLoad:
    """B1: a dashboard edit completing while a session load's DB read is in
    flight must not be clobbered by the pre-edit snapshot (stale cache store
    + stale session registration)."""

    @pytest.mark.asyncio
    async def test_edit_during_db_read_not_lost(self):
        import cogs.ai_core.storage as storage

        channel_id = 777_000_001
        ts = "2024-01-01T00:00:00+00:00"
        pre_rows = [{"id": 1, "role": "user", "content": "old", "timestamp": ts}]
        post_rows = [{"id": 1, "role": "user", "content": "edited", "timestamp": ts}]

        load_started = asyncio.Event()
        edit_done = asyncio.Event()
        calls = {"n": 0}

        async def fake_get_ai_history(cid, limit=None):
            calls["n"] += 1
            if calls["n"] == 1:
                load_started.set()
                # The dashboard edit runs to completion INSIDE this await —
                # the returned rows are the pre-edit WAL snapshot.
                await edit_done.wait()
                return [dict(r) for r in pre_rows]
            return [dict(r) for r in post_rows]

        fake_db = SimpleNamespace(
            get_ai_history=fake_get_ai_history,
            get_ai_metadata=AsyncMock(return_value={"thinking_enabled": True}),
        )

        mgr = _session_harness()
        try:
            with (
                patch.object(storage, "db", fake_db),
                patch.object(storage, "DATABASE_AVAILABLE", True),
            ):
                storage.invalidate_cache(channel_id)  # clean slate
                task = asyncio.create_task(mgr.get_chat_session(channel_id))
                await asyncio.wait_for(load_started.wait(), timeout=5)
                # The "edit": the DB row is already updated (post_rows), and
                # edit_message_by_row_id invalidates the cache (generation bump).
                storage.invalidate_cache(channel_id)
                edit_done.set()
                session = await asyncio.wait_for(task, timeout=5)

            assert session is not None
            # The registered session must hold the EDITED content...
            assert session["history"][0]["parts"] == ["edited"]
            assert mgr.chats[channel_id]["history"][0]["parts"] == ["edited"]
            # ...and the cache must not have been re-poisoned with pre-edit rows.
            with storage._cache_lock:
                cached = storage._history_cache.get(channel_id)
            if cached is not None:
                assert cached[1][0]["parts"] == ["edited"]
        finally:
            _storage_cleanup(channel_id)

    @pytest.mark.asyncio
    async def test_edit_during_metadata_load_not_lost(self):
        """The residual window: edit lands during the load_metadata await,
        AFTER load_history returned — get_chat_session's generation re-check
        must re-read before registering the session."""
        import cogs.ai_core.storage as storage

        channel_id = 777_000_002
        ts = "2024-01-01T00:00:00+00:00"
        rows_holder = {"rows": [{"id": 1, "role": "user", "content": "old", "timestamp": ts}]}

        meta_started = asyncio.Event()
        edit_done = asyncio.Event()

        async def fake_get_ai_history(cid, limit=None):
            return [dict(r) for r in rows_holder["rows"]]

        async def fake_get_ai_metadata(cid):
            meta_started.set()
            await edit_done.wait()
            return {"thinking_enabled": True}

        fake_db = SimpleNamespace(
            get_ai_history=fake_get_ai_history,
            get_ai_metadata=fake_get_ai_metadata,
        )

        mgr = _session_harness()
        try:
            with (
                patch.object(storage, "db", fake_db),
                patch.object(storage, "DATABASE_AVAILABLE", True),
            ):
                storage.invalidate_cache(channel_id)
                task = asyncio.create_task(mgr.get_chat_session(channel_id))
                await asyncio.wait_for(meta_started.wait(), timeout=5)
                # The "edit" lands while load_metadata is awaiting.
                rows_holder["rows"] = [
                    {"id": 1, "role": "user", "content": "edited", "timestamp": ts}
                ]
                storage.invalidate_cache(channel_id)
                edit_done.set()
                session = await asyncio.wait_for(task, timeout=5)

            assert session is not None
            assert session["history"][0]["parts"] == ["edited"]
            assert mgr.chats[channel_id]["history"][0]["parts"] == ["edited"]
        finally:
            _storage_cleanup(channel_id)


class TestEditSerializedAgainstSave:
    """B2: the per-channel history lock makes the dashboard edit atomic
    relative to a diff-mode save's fetch+diff+write, so the edited
    message_id-less row cannot be duplicated via the no-overlap fallback."""

    @pytest.mark.asyncio
    async def test_edit_blocks_until_diff_save_finishes(self, ws):
        import cogs.ai_core.storage as storage
        from cogs.ai_core.api.dashboard_handlers import handle_edit_ai_history_message

        channel_id = 777_000_003
        ts = "2024-01-01T00:00:00+00:00"
        db_row = {
            "id": 1,
            "local_id": 1,
            "role": "user",
            "content": "old",
            "message_id": None,
            "timestamp": ts,
            "user_id": None,
        }

        events: list[str] = []
        fetch_started = asyncio.Event()
        release_fetch = asyncio.Event()

        async def fake_get_ai_history(cid, limit=None):
            events.append("save_fetch_start")
            fetch_started.set()
            await release_fetch.wait()
            events.append("save_fetch_end")
            return [dict(db_row)]

        fake_storage_db = SimpleNamespace(
            get_ai_history=fake_get_ai_history,
            save_ai_messages_batch=AsyncMock(),
            get_ai_history_count=AsyncMock(return_value=1),
            prune_ai_history=AsyncMock(),
            save_ai_metadata=AsyncMock(),
        )

        chat_data = {
            "history": [{"role": "user", "parts": ["old"], "timestamp": ts}],
            "_db_loaded": True,
        }

        handler_db = MagicMock()
        handler_db.get_ai_history_message = AsyncMock(return_value=dict(db_row))
        handler_db.count_identical_history_rows_before = AsyncMock(return_value=0)

        async def fake_edit(cid, row_id, content):
            events.append("edit_update")
            return True

        try:
            with (
                patch.object(storage, "db", fake_storage_db),
                patch.object(storage, "DATABASE_AVAILABLE", True),
                patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=handler_db),
                patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
                patch(
                    "cogs.ai_core.api.dashboard_handlers.edit_message_by_row_id",
                    AsyncMock(side_effect=fake_edit),
                ),
                patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
            ):
                save_task = asyncio.create_task(
                    storage._save_history_db(channel_id, chat_data, 100)
                )
                await asyncio.wait_for(fetch_started.wait(), timeout=5)
                edit_task = asyncio.create_task(
                    handle_edit_ai_history_message(
                        ws, {"channel_id": str(channel_id), "id": 1, "content": "edited"}
                    )
                )
                # Let the edit task run up to (and block on) the channel lock.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert "edit_update" not in events  # serialized behind the save
                release_fetch.set()
                assert await asyncio.wait_for(save_task, timeout=5) is True
                await asyncio.wait_for(edit_task, timeout=5)

            # The edit's DB update ran strictly AFTER the save's fetch+diff
            # region — no stale-snapshot duplicate insert is possible.
            assert events.index("edit_update") > events.index("save_fetch_end")
            assert ws.last()["type"] == "ai_history_message_edited"
            # The matching overlap meant nothing new to write.
            fake_storage_db.save_ai_messages_batch.assert_not_awaited()
        finally:
            _storage_cleanup(channel_id)


class TestDeleteSerializedAgainstSave:
    """Same B2 rule for the delete op: the per-channel history lock makes the
    dashboard delete atomic relative to a diff-mode save's fetch+diff+write,
    so a stale snapshot cannot re-insert (resurrect) the deleted
    message_id-less row via the no-overlap fallback."""

    @pytest.mark.asyncio
    async def test_delete_blocks_until_diff_save_finishes(self, ws):
        import cogs.ai_core.storage as storage
        from cogs.ai_core.api.dashboard_handlers import handle_delete_ai_history_message

        channel_id = 777_000_004
        ts = "2024-01-01T00:00:00+00:00"
        db_row = {
            "id": 1,
            "local_id": 1,
            "role": "user",
            "content": "old",
            "message_id": None,
            "timestamp": ts,
            "user_id": None,
        }

        events: list[str] = []
        fetch_started = asyncio.Event()
        release_fetch = asyncio.Event()

        async def fake_get_ai_history(cid, limit=None):
            events.append("save_fetch_start")
            fetch_started.set()
            await release_fetch.wait()
            events.append("save_fetch_end")
            return [dict(db_row)]

        fake_storage_db = SimpleNamespace(
            get_ai_history=fake_get_ai_history,
            save_ai_messages_batch=AsyncMock(),
            get_ai_history_count=AsyncMock(return_value=1),
            prune_ai_history=AsyncMock(),
            save_ai_metadata=AsyncMock(),
        )

        chat_data = {
            "history": [{"role": "user", "parts": ["old"], "timestamp": ts}],
            "_db_loaded": True,
        }

        handler_db = MagicMock()
        handler_db.get_ai_history_message = AsyncMock(return_value=dict(db_row))
        handler_db.count_identical_history_rows_before = AsyncMock(return_value=0)
        handler_db.get_ai_history_count = AsyncMock(return_value=0)

        async def fake_delete(cid, row_id):
            events.append("delete_row")
            return True

        try:
            with (
                patch.object(storage, "db", fake_storage_db),
                patch.object(storage, "DATABASE_AVAILABLE", True),
                patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=handler_db),
                patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
                patch(
                    "cogs.ai_core.api.dashboard_handlers.delete_message_by_row_id",
                    AsyncMock(side_effect=fake_delete),
                ),
                patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
            ):
                save_task = asyncio.create_task(
                    storage._save_history_db(channel_id, chat_data, 100)
                )
                await asyncio.wait_for(fetch_started.wait(), timeout=5)
                delete_task = asyncio.create_task(
                    handle_delete_ai_history_message(ws, {"channel_id": str(channel_id), "id": 1})
                )
                # Let the delete task run up to (and block on) the channel lock.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert "delete_row" not in events  # serialized behind the save
                release_fetch.set()
                assert await asyncio.wait_for(save_task, timeout=5) is True
                await asyncio.wait_for(delete_task, timeout=5)

            # The delete's DB DELETE ran strictly AFTER the save's fetch+diff
            # region — no stale-snapshot resurrection is possible.
            assert events.index("delete_row") > events.index("save_fetch_end")
            msg = ws.last()
            assert msg["type"] == "ai_history_message_deleted"
            assert msg["total_count"] == 0
            # The matching overlap meant nothing new to write.
            fake_storage_db.save_ai_messages_batch.assert_not_awaited()
        finally:
            _storage_cleanup(channel_id)


class TestRestoreSerializedAgainstSave:
    """Same B2 rule for the restore op: the per-channel history lock makes
    the dashboard restore (INSERT + neighbor reads + memory insert) atomic
    relative to a diff-mode save's fetch+diff+write, so a save's stale
    snapshot cannot interleave with the half-applied restore."""

    @pytest.mark.asyncio
    async def test_restore_blocks_until_diff_save_finishes(self, ws):
        import cogs.ai_core.storage as storage
        from cogs.ai_core.api.dashboard_handlers import handle_restore_ai_history_message

        channel_id = 777_000_005
        ts = "2024-01-01T00:00:00+00:00"
        db_row = {
            "id": 1,
            "local_id": 1,
            "role": "user",
            "content": "old",
            "message_id": None,
            "timestamp": ts,
            "user_id": None,
        }

        events: list[str] = []
        fetch_started = asyncio.Event()
        release_fetch = asyncio.Event()

        async def fake_get_ai_history(cid, limit=None):
            events.append("save_fetch_start")
            fetch_started.set()
            await release_fetch.wait()
            events.append("save_fetch_end")
            return [dict(db_row)]

        fake_storage_db = SimpleNamespace(
            get_ai_history=fake_get_ai_history,
            save_ai_messages_batch=AsyncMock(),
            get_ai_history_count=AsyncMock(return_value=1),
            prune_ai_history=AsyncMock(),
            save_ai_metadata=AsyncMock(),
        )

        chat_data = {
            "history": [{"role": "user", "parts": ["old"], "timestamp": ts}],
            "_db_loaded": True,
        }

        handler_db = MagicMock()
        handler_db.get_ai_history_neighbor_rows = AsyncMock(return_value=(dict(db_row), None))
        handler_db.get_ai_history_count = AsyncMock(return_value=2)
        handler_db.count_identical_history_rows_before = AsyncMock(return_value=0)
        handler_db.count_identical_history_rows = AsyncMock(return_value=1)

        async def fake_restore(cid, row):
            events.append("restore_row")
            return "restored"

        wire_msg = {
            "id": 2,
            "local_id": 2,
            "role": "model",
            "content": "restored text",
            "message_id": None,
            "timestamp": ts,
            "user_id": None,
        }

        try:
            with (
                patch.object(storage, "db", fake_storage_db),
                patch.object(storage, "DATABASE_AVAILABLE", True),
                patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=handler_db),
                patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
                patch(
                    "cogs.ai_core.api.dashboard_handlers.restore_message_by_row",
                    AsyncMock(side_effect=fake_restore),
                ),
                patch("cogs.ai_core.api.dashboard_handlers._get_chat_manager", return_value=None),
            ):
                save_task = asyncio.create_task(
                    storage._save_history_db(channel_id, chat_data, 100)
                )
                await asyncio.wait_for(fetch_started.wait(), timeout=5)
                restore_task = asyncio.create_task(
                    handle_restore_ai_history_message(
                        ws, {"channel_id": str(channel_id), "message": wire_msg}
                    )
                )
                # Let the restore task run up to (and block on) the channel lock.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                assert "restore_row" not in events  # serialized behind the save
                release_fetch.set()
                assert await asyncio.wait_for(save_task, timeout=5) is True
                await asyncio.wait_for(restore_task, timeout=5)

            # The restore's DB INSERT ran strictly AFTER the save's fetch+diff
            # region — no stale-snapshot interleaving is possible.
            assert events.index("restore_row") > events.index("save_fetch_end")
            msg = ws.last()
            assert msg["type"] == "ai_history_message_restored"
            assert msg["total_count"] == 2
            # The matching overlap meant nothing new to write.
            fake_storage_db.save_ai_messages_batch.assert_not_awaited()
        finally:
            _storage_cleanup(channel_id)
