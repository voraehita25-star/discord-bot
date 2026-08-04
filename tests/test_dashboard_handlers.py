"""Tests for Dashboard CRUD handlers (dashboard_handlers.py).

Covers all handler functions: conversations, messages, profiles.
Each handler is tested for success, validation errors, and DB unavailability.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeWS:
    """Minimal fake aiohttp.web.WebSocketResponse for testing."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data: dict, **kwargs) -> None:  # kwargs: aiohttp accepts dumps=
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
    db.edit_and_truncate_dashboard_message = AsyncMock(return_value=(True, 0))
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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_conversation(ws, {"id": "nonexistent"})
        assert ws.last()["code"] == "CONV_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_load_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation

        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = [{"content": "hello"}]
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_conversation(ws, {"id": "c1"})
        assert ws.last()["type"] == "conversation_loaded"

    @staticmethod
    def _mock_doc_char_sum(mock_db, total):
        """Wire mock_db.get_connection() so the doc-memory SUM(char_count)
        aggregate returns ``total`` (as an async context manager)."""
        cursor = MagicMock()
        cursor.fetchone = AsyncMock(return_value=(total,))
        conn = MagicMock()
        conn.execute = AsyncMock(return_value=cursor)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_db.get_connection = MagicMock(return_value=cm)

    @pytest.mark.asyncio
    async def test_load_estimate_includes_document_memories(self, ws, mock_db):
        """The context-window estimate on OPEN folds in persistent document
        memories so attached files are counted before the first turn (the meter
        previously counted only chat history, so files looked 'uncounted')."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation

        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = []
        self._mock_doc_char_sum(mock_db, 30_000)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_conversation(ws, {"id": "c1"})
        loaded = ws.last()
        assert loaded["type"] == "conversation_loaded"
        # 30_000 doc chars // 3 = 10_000 tokens contributed by documents alone.
        assert loaded["token_usage"]["input_tokens"] >= 10_000

    @pytest.mark.asyncio
    async def test_load_estimate_caps_document_contribution(self, ws, mock_db):
        """A huge document library can't inflate the bar past the prompt
        builder's MAX_INJECT_CHARS (400k) injection budget."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation

        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = []
        self._mock_doc_char_sum(mock_db, 900_000)
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_load_conversation(ws, {"id": "c1"})
        tokens = ws.last()["token_usage"]["input_tokens"]
        # Capped at 400k chars -> ~133k tokens, far below the uncapped 900k//3 = 300k.
        assert 133_000 <= tokens < 200_000

    @pytest.mark.asyncio
    async def test_load_budget_truncates_oldest(self, ws, mock_db):
        """A conversation exceeding MAX_HISTORY_RESPONSE_CHARS is truncated
        newest-first (oldest dropped) so the wire frame stays under the client's
        50MB cap; ``truncated`` flags it."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation

        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = [
            {"id": i, "content": "x" * 6, "thinking": ""} for i in range(3)
        ]
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.MAX_HISTORY_RESPONSE_CHARS", 10),
        ):
            await handle_load_conversation(ws, {"id": "c1"})
        assert ws.last()["type"] == "conversation_loaded"
        # Only the newest message fits the 10-char budget; ids 0 and 1 dropped.
        assert [m["id"] for m in ws.last()["messages"]] == [2]
        assert ws.last()["truncated"] is True

    @pytest.mark.asyncio
    async def test_load_oversized_single_message_strips_images(self, ws, mock_db):
        """When the NEWEST message ALONE exceeds the wire budget, its base64
        images are stripped from the wire copy (with a marker) so the frame
        stays deliverable and the conversation still opens — instead of shipping
        an undeliverable >50MB frame the client silently drops. The stored DB
        row must NOT be mutated."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation

        big_image = "data:image/png;base64," + "A" * 200
        stored = [{"id": 7, "content": "look at this", "thinking": "", "images": [big_image]}]
        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = stored
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.MAX_HISTORY_RESPONSE_CHARS", 50),
        ):
            await handle_load_conversation(ws, {"id": "c1"})

        loaded = ws.last()
        assert loaded["type"] == "conversation_loaded"
        assert loaded["truncated"] is True
        # Conversation still opens with the single message present...
        assert len(loaded["messages"]) == 1
        wire = loaded["messages"][0]
        # ...but the heavy images are stripped from the wire copy and marked.
        assert wire["images"] == []
        assert "[image too large to display]" in wire["content"]
        # The stored DB row is untouched (only the outbound wire copy changed).
        assert stored[0]["images"] == [big_image]
        assert stored[0]["content"] == "look at this"

    @pytest.mark.asyncio
    async def test_load_oversized_single_message_no_images_ships_best_effort(self, ws, mock_db):
        """A single over-budget message with NO images (pathologically large
        text) has nothing safe to strip, so it's shipped best-effort and still
        flagged truncated — the conversation is not silently lost to an empty
        message list."""
        from cogs.ai_core.api.dashboard_handlers import handle_load_conversation

        mock_db.get_dashboard_conversation.return_value = {"id": "c1", "role_preset": "general"}
        mock_db.get_dashboard_messages.return_value = [
            {"id": 3, "content": "x" * 100, "thinking": ""}
        ]
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.MAX_HISTORY_RESPONSE_CHARS", 50),
        ):
            await handle_load_conversation(ws, {"id": "c1"})

        loaded = ws.last()
        assert loaded["type"] == "conversation_loaded"
        assert [m["id"] for m in loaded["messages"]] == [3]
        assert loaded["truncated"] is True


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

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_rename_conversation(ws, {"id": "c1", "title": "New Title"})
        assert ws.last()["type"] == "conversation_renamed"
        assert ws.last()["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_title_strips_non_printable(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_rename_conversation

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_export_conversation(ws, {"id": "c1", "format": "json"})
        assert ws.last()["type"] == "conversation_exported"

    @pytest.mark.asyncio
    async def test_export_too_large(self, ws, mock_db):
        """An export string over MAX_HISTORY_RESPONSE_CHARS is rejected with an
        explicit error rather than emitting a frame the client silently drops."""
        from cogs.ai_core.api.dashboard_handlers import handle_export_conversation

        mock_db.export_dashboard_conversation.return_value = "x" * 50
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            patch("cogs.ai_core.api.dashboard_handlers.MAX_HISTORY_RESPONSE_CHARS", 10),
        ):
            await handle_export_conversation(ws, {"id": "c1", "format": "json"})
        assert ws.last()["code"] == "EXPORT_TOO_LARGE"


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
            await handle_edit_message(ws, {"message_id": "1", "content": "A" * 200_001})
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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_edit_message(
                ws, {"message_id": "1", "content": "new", "conversation_id": "c1"}
            )
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_edit_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_edit_message(
                ws, {"message_id": "1", "content": "updated", "conversation_id": "c1"}
            )
        assert ws.last()["type"] == "message_edited"

    @pytest.mark.asyncio
    async def test_edit_with_regenerate(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message

        # Regenerate now uses the atomic single-transaction update+truncate.
        mock_db.edit_and_truncate_dashboard_message = AsyncMock(return_value=(True, 3))
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_edit_message(
                ws,
                {"message_id": "1", "content": "edit", "regenerate": True, "conversation_id": "c1"},
            )
        assert ws.last()["deleted_after"] == 3

    @pytest.mark.asyncio
    async def test_edit_resets_cli_session_so_resume_does_not_replay_old(self, ws, mock_db):
        """Save & Regenerate must drop the Claude CLI session pointer.
        Without this, the next CLI turn would --resume the original .jsonl
        and replay the pre-edit assistant reply as if nothing changed —
        which is exactly the "old chat keeps coming back" symptom users hit.
        """
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message

        cli_mod._CONVERSATION_SESSIONS["c1"] = "old-session-id"
        try:
            with (
                patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
                patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            ):
                await handle_edit_message(
                    ws,
                    {
                        "message_id": "1",
                        "content": "edit",
                        "regenerate": True,
                        "conversation_id": "c1",
                    },
                )
            assert "c1" not in cli_mod._CONVERSATION_SESSIONS
        finally:
            cli_mod._CONVERSATION_SESSIONS.pop("c1", None)

    @pytest.mark.asyncio
    async def test_cli_regeneration_does_not_duplicate_user_message(self, ws, mock_db):
        """Regenerate-after-edit (is_regeneration=True) must NOT re-persist the
        user turn under the CLI backend. handle_edit_message already updated the
        message and deleted everything after it, so the edited user turn is the
        last DB row. The CLI handler previously ignored is_regeneration and saved
        a second copy — the duplicate-user-message bug. Mirrors the validated
        skip in the SDK backend.
        """
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod

        mock_db.save_dashboard_message = AsyncMock(return_value=99)
        # Last DB row is the edited user message whose content matches → the
        # is_regeneration validation passes and the flag stays True.
        mock_db.get_dashboard_messages = AsyncMock(
            return_value=[{"id": 1, "role": "user", "content": "edited text"}]
        )
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "set"})
        mock_db.update_dashboard_conversation = AsyncMock()

        with (
            patch.object(cli_mod, "get_db", return_value=mock_db),
            patch.object(cli_mod, "DB_AVAILABLE", True),
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_resolve_claude_executable", return_value="claude"),
            patch.object(cli_mod, "_build_claude_argv", return_value=["claude", "-p"]),
            patch.object(cli_mod, "_track_session"),
            patch.object(cli_mod, "build_user_context", new=AsyncMock(return_value=("ctx", None))),
            patch.object(
                cli_mod, "_run_claude_subprocess", new=AsyncMock(return_value=("sess-1", {}))
            ),
        ):
            await cli_mod.handle_chat_message_claude_cli(
                ws,
                {
                    "conversation_id": "c1",
                    "content": "edited text",
                    "role_preset": "general",
                    "history": [],
                    "is_regeneration": True,
                },
                None,
            )

        user_saves = [
            call
            for call in mock_db.save_dashboard_message.call_args_list
            if len(call.args) >= 2 and call.args[1] == "user"
        ]
        assert user_saves == [], (
            "is_regeneration=True must skip re-saving the user message (CLI backend)"
        )

    @pytest.mark.asyncio
    async def test_cli_normal_message_saves_user_once(self, ws, mock_db):
        """Baseline guard: a NORMAL message (no is_regeneration) persists the
        user turn exactly once — proving the regeneration skip above didn't
        break ordinary persistence."""
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod

        mock_db.save_dashboard_message = AsyncMock(return_value=99)
        mock_db.get_dashboard_messages = AsyncMock(return_value=[])
        mock_db.get_dashboard_conversation = AsyncMock(return_value={"title": "set"})
        mock_db.update_dashboard_conversation = AsyncMock()

        with (
            patch.object(cli_mod, "get_db", return_value=mock_db),
            patch.object(cli_mod, "DB_AVAILABLE", True),
            patch.object(cli_mod, "is_cli_backend_ready", return_value=(True, "")),
            patch.object(cli_mod, "_resolve_claude_executable", return_value="claude"),
            patch.object(cli_mod, "_build_claude_argv", return_value=["claude", "-p"]),
            patch.object(cli_mod, "_track_session"),
            patch.object(cli_mod, "build_user_context", new=AsyncMock(return_value=("ctx", None))),
            patch.object(
                cli_mod, "_run_claude_subprocess", new=AsyncMock(return_value=("sess-1", {}))
            ),
        ):
            await cli_mod.handle_chat_message_claude_cli(
                ws,
                {
                    "conversation_id": "c1",
                    "content": "hello",
                    "role_preset": "general",
                    "history": [],
                },
                None,
            )

        user_saves = [
            call
            for call in mock_db.save_dashboard_message.call_args_list
            if len(call.args) >= 2 and call.args[1] == "user"
        ]
        assert len(user_saves) == 1, "a normal message must persist the user turn exactly once"

    @pytest.mark.asyncio
    async def test_plain_edit_also_resets_cli_session(self, ws, mock_db):
        """Even without regenerate=True the DB content diverges from the
        Claude --resume transcript, so the session pointer must be dropped."""
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
        from cogs.ai_core.api.dashboard_handlers import handle_edit_message

        cli_mod._CONVERSATION_SESSIONS["c2"] = "stale"
        try:
            with (
                patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
                patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            ):
                await handle_edit_message(
                    ws,
                    {
                        "message_id": "5",
                        "content": "fix typo",
                        "regenerate": False,
                        "conversation_id": "c2",
                    },
                )
            assert "c2" not in cli_mod._CONVERSATION_SESSIONS
        finally:
            cli_mod._CONVERSATION_SESSIONS.pop("c2", None)


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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_delete_message(ws, {"message_id": "999", "conversation_id": "c1"})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_delete_message(ws, {"message_id": "1", "conversation_id": "c1"})
        assert ws.last()["type"] == "message_deleted"

    @pytest.mark.asyncio
    async def test_delete_resets_cli_session(self, ws, mock_db):
        """Deleting a message in the middle of a conversation diverges the DB
        from the Claude --resume transcript — the session pointer must drop
        so the next CLI turn starts fresh."""
        from cogs.ai_core.api import dashboard_chat_claude_cli as cli_mod
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message

        mock_db.delete_dashboard_message.return_value = "c3"
        cli_mod._CONVERSATION_SESSIONS["c3"] = "stale-session"
        try:
            with (
                patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
                patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
            ):
                await handle_delete_message(ws, {"message_id": "1", "conversation_id": "c3"})
            assert "c3" not in cli_mod._CONVERSATION_SESSIONS
        finally:
            cli_mod._CONVERSATION_SESSIONS.pop("c3", None)

    @pytest.mark.asyncio
    async def test_delete_with_pair(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_delete_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_delete_message(
                ws,
                {
                    "message_id": "1",
                    "delete_pair": True,
                    "pair_message_id": "2",
                    "conversation_id": "c1",
                },
            )
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

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_pin_message(ws, {"message_id": "999", "pinned": True})
        assert ws.last()["code"] == "MSG_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_pin_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_pin_message(ws, {"message_id": "42", "pinned": True})
        last = ws.last()
        assert last["type"] == "message_pinned"
        assert last["pinned"] is True
        assert last["message_id"] == "42"
        mock_db.update_dashboard_message_pin.assert_awaited_once_with(42, True)

    @pytest.mark.asyncio
    async def test_unpin_success(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_pin_message(ws, {"message_id": "42", "pinned": False})
        assert ws.last()["pinned"] is False
        mock_db.update_dashboard_message_pin.assert_awaited_once_with(42, False)

    @pytest.mark.asyncio
    async def test_defaults_to_pinned_true_when_omitted(self, ws, mock_db):
        """If the client omits the `pinned` field, handler defaults to pinning."""
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_pin_message(ws, {"message_id": "42"})
        mock_db.update_dashboard_message_pin.assert_awaited_once_with(42, True)

    @pytest.mark.asyncio
    async def test_db_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_pin_message

        mock_db.update_dashboard_message_pin.side_effect = RuntimeError("boom")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_pin_message(ws, {"message_id": "42", "pinned": True})
        assert ws.last()["code"] == "INTERNAL_ERROR"


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
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
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

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_save_profile(ws, {"profile": {"display_name": "New Name"}})
        assert ws.last()["type"] == "profile_saved"

    @pytest.mark.asyncio
    async def test_save_db_error(self, ws, mock_db):
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile

        mock_db.save_dashboard_user_profile.side_effect = RuntimeError("DB error")
        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_save_profile(ws, {"profile": {"display_name": "Test"}})
        assert ws.last()["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_save_string_preferences_persisted(self, ws, mock_db):
        """The dashboard UI sends preferences as a free-text string; it must be
        persisted (not silently dropped) and passed to the DB as a str."""
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_save_profile(
                ws, {"profile": {"display_name": "U", "preferences": "likes dark mode"}}
            )
        assert ws.last()["type"] == "profile_saved"
        kwargs = mock_db.save_dashboard_user_profile.call_args.kwargs
        assert isinstance(kwargs["preferences"], str)
        assert kwargs["preferences"] == "likes dark mode"

    @pytest.mark.asyncio
    async def test_save_dict_preferences_serialized(self, ws, mock_db):
        """A structured dict preferences value must be JSON-serialized to a str —
        sqlite cannot bind a dict, so it must never reach the DB layer raw."""
        import json

        from cogs.ai_core.api.dashboard_handlers import handle_save_profile

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_save_profile(
                ws, {"profile": {"display_name": "U", "preferences": {"theme": "dark"}}}
            )
        assert ws.last()["type"] == "profile_saved"
        kwargs = mock_db.save_dashboard_user_profile.call_args.kwargs
        assert isinstance(kwargs["preferences"], str)
        assert json.loads(kwargs["preferences"]) == {"theme": "dark"}

    @pytest.mark.asyncio
    async def test_dict_preferences_all_unsupported_rejected(self, ws, mock_db):
        """A dict whose values are all unsupported (nested dict) sanitizes to an
        empty ``clean``; rejecting with INVALID_ARG prevents a NULL overwrite of
        the stored preferences — the DB write must never happen."""
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_save_profile(
                ws,
                {"profile": {"display_name": "U", "preferences": {"settings": {"theme": "dark"}}}},
            )
        assert ws.last()["code"] == "INVALID_ARG"
        mock_db.save_dashboard_user_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_dict_preferences_clears(self, ws, mock_db):
        """An explicitly empty ``{}`` is a legitimate clear: it must still save
        with preferences=None, not be rejected as INVALID_ARG."""
        from cogs.ai_core.api.dashboard_handlers import handle_save_profile

        with (
            patch("cogs.ai_core.api.dashboard_handlers._get_db", return_value=mock_db),
            patch("cogs.ai_core.api.dashboard_handlers.DB_AVAILABLE", True),
        ):
            await handle_save_profile(ws, {"profile": {"display_name": "U", "preferences": {}}})
        assert ws.last()["type"] == "profile_saved"
        kwargs = mock_db.save_dashboard_user_profile.call_args.kwargs
        assert kwargs["preferences"] is None


class TestDocumentMemoryScopeValidation:
    """The per-document handlers accept an ABSENT conversation scope (global
    documents), so they can't use ``_validate_conversation_id`` — but a
    falsy-yet-UNHASHABLE scope used to slip all the way through.

    ``[]`` and ``{}`` normalise to None via ``conversation_id or None``, so they
    passed the global-document scope check; the write then committed, and the
    trailing ``invalidate_user_context_cache(owner or conversation_id)`` raised
    TypeError on ``dict.pop``. The handler's broad ``except`` reported the
    SUCCESSFUL delete/update as INTERNAL_ERROR and the stale user_context was
    never dropped, so the next AI turn still saw the document. Intermittent, too:
    CPython skips hashing on an empty dict, so it only began failing once some
    conversation had cached a context.

    The guard runs before any DB access, so these need no database.
    """

    HANDLERS = (
        "handle_delete_document_memory",
        "handle_update_document_memory",
        "handle_get_document_memory_content",
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handler_name", HANDLERS)
    @pytest.mark.parametrize("bad_scope", [[], {}, set(), 0, 1, 2.5, True, ["x"], {"a": 1}])
    async def test_non_string_scope_is_rejected(self, ws, handler_name, bad_scope):
        import cogs.ai_core.api.dashboard_handlers as mod

        handler = getattr(mod, handler_name)
        with patch.object(mod, "_get_db") as get_db:
            await handler(ws, {"id": 1, "conversation_id": bad_scope})
        assert ws.last()["code"] == "INVALID_ARG"
        # Rejected before the handler ever reaches for the database.
        get_db.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handler_name", HANDLERS)
    @pytest.mark.parametrize("ok_scope", [None, "", "conv-1"])
    async def test_string_and_absent_scopes_are_not_rejected(self, ws, handler_name, ok_scope):
        # These must NOT be turned away by the new check — "" and None are the
        # legitimate spellings of "global document", and the guard sits ahead of
        # every other validation, so over-rejecting here would break the feature
        # outright. What the handler does AFTER the guard is not this test's
        # business, so assert only that the guard itself stayed silent.
        import cogs.ai_core.api.dashboard_handlers as mod

        handler = getattr(mod, handler_name)
        with patch.object(mod, "_get_db", side_effect=RuntimeError("stop here")):
            await handler(ws, {"id": 1, "conversation_id": ok_scope})
        assert not [m for m in ws.sent if m.get("message") == "Invalid conversation id"]


class TestAiHistoryIdParsers:
    """The entry gate for the four AI-history handlers, which edit and delete
    the AI's stored Discord history. Both parsers had zero coverage.

    The sharp edge is the ASCII restriction. ``int()`` happily accepts
    non-ASCII decimal digits — ``int("١٢٣") == 123`` — and ``str.isdigit()``
    returns True for them, so the obvious spellings of this parser would let a
    client address a row with a string that no ASCII comparison elsewhere would
    ever match. ``_SNOWFLAKE_RE.fullmatch`` restricts to ``[0-9]``, which is
    what makes that safe; pin it so a refactor to isdigit()/try-int can't
    silently widen the gate.
    """

    SQLITE_MAX = (1 << 63) - 1

    @staticmethod
    def _parsers():
        from cogs.ai_core.api.dashboard_handlers import (
            _parse_history_row_id,
            _parse_snowflake,
        )

        return _parse_snowflake, _parse_history_row_id

    @pytest.mark.parametrize(
        "value",
        [
            "\u0661\u0662\u0663",  # Arabic-Indic — int() accepts these
            "\u0e51\u0e52\u0e53",  # Thai
            "\uff11\uff12\uff13",  # Fullwidth
        ],
    )
    def test_non_ascii_digits_are_rejected(self, value):
        assert int(value) == 123, "precondition: int() really does accept these"
        snowflake, row_id = self._parsers()
        assert snowflake(value) is None
        assert row_id(value) is None

    @pytest.mark.parametrize(
        "value",
        [
            True,  # bool is an int subclass — must be rejected explicitly
            False,
            -5,
            "-5",
            1.5,
            5.0,  # a float that is integral is still not an id
            None,
            "",
            " 123 ",
            "+123",
            "0x1f",
            "1e5",
            "123\n",
            "123\x00",
            "1 OR 1=1",
            [1],
            {"a": 1},
            10**40,
            "1" * 21,  # over the 20-digit cap
            str(1 << 63),  # over SQLite's signed-64-bit max
        ],
    )
    def test_malformed_values_are_rejected_by_both(self, value):
        snowflake, row_id = self._parsers()
        assert snowflake(value) is None
        assert row_id(value) is None

    def test_accepts_well_formed_ids_in_both_wire_forms(self):
        snowflake, row_id = self._parsers()
        for form in ("123456789012345678", 123456789012345678):
            assert snowflake(form) == 123456789012345678
            assert row_id(form) == 123456789012345678
        assert snowflake(str(self.SQLITE_MAX)) == self.SQLITE_MAX
        assert row_id(str(self.SQLITE_MAX)) == self.SQLITE_MAX

    def test_zero_differs_between_the_two_parsers(self):
        # Documented split: a row id is a positive AUTOINCREMENT key, so 0 is
        # invalid; a snowflake parse only bounds the range, and a 0 channel
        # simply matches no row downstream.
        snowflake, row_id = self._parsers()
        assert row_id("0") is None
        assert row_id(0) is None
        assert snowflake("0") == 0

    @pytest.mark.parametrize("value", ["123456789012345678", 5, "000000000000000123"])
    def test_output_is_always_a_plain_int_in_sqlite_range(self, value):
        # Both results are bound straight into SQL, so a bool or an
        # out-of-range int must never survive parsing.
        snowflake, row_id = self._parsers()
        for out in (snowflake(value), row_id(value)):
            if out is None:
                continue
            assert type(out) is int
            assert 0 <= out <= self.SQLITE_MAX
