"""Unit tests for the AI-tools IPC bridge (cogs.ai_core.api.ai_tools_ipc).

Covers tool-schema gating, the Gemini→MCP schema conversion, request auth, and
the memory/server dispatch (with the live managers mocked). The live
claude→MCP→IPC round-trip is exercised separately as an integration check.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.ai_core.api import ai_tools_ipc as ipc


class TestToolGating:
    def test_default_exposes_only_memory_tools(self, monkeypatch):
        monkeypatch.delenv("DASHBOARD_CLI_SERVER_ACTIONS", raising=False)
        monkeypatch.delenv("DASHBOARD_CLI_AI_TOOLS", raising=False)
        names = [t["name"] for t in ipc.list_tool_schemas()]
        assert names == ["remember", "recall_memory"]

    def test_server_actions_flag_adds_server_tools(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        names = [t["name"] for t in ipc.list_tool_schemas()]
        assert "remember" in names and "recall_memory" in names
        assert "create_text_channel" in names
        assert len(names) > 2

    def test_memory_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_AI_TOOLS", "0")
        monkeypatch.delenv("DASHBOARD_CLI_SERVER_ACTIONS", raising=False)
        assert ipc.list_tool_schemas() == []


class TestServerSchemaConversion:
    def test_excludes_remember_and_lowercases_types(self):
        schemas = ipc._server_tool_schemas()
        names = {t["name"] for t in schemas}
        assert "remember" not in names  # handled by the memory path
        assert "create_text_channel" in names
        ctc = next(t for t in schemas if t["name"] == "create_text_channel")
        assert ctc["inputSchema"]["type"] == "object"
        assert ctc["inputSchema"]["properties"]["name"]["type"] == "string"
        assert ctc["inputSchema"]["required"] == ["name"]


class TestAuth:
    def test_authed_rejects_wrong_token(self):
        inst = ipc._AiToolsIpc()
        inst.token = "right"
        req = SimpleNamespace(headers={"X-Token": "wrong"})
        assert inst._authed(req) is False

    def test_authed_rejects_when_no_token_set(self):
        inst = ipc._AiToolsIpc()
        inst.token = ""
        req = SimpleNamespace(headers={"X-Token": ""})
        assert inst._authed(req) is False

    def test_authed_accepts_matching_token(self):
        inst = ipc._AiToolsIpc()
        inst.token = "secret"
        req = SimpleNamespace(headers={"X-Token": "secret"})
        assert inst._authed(req) is True

    def test_authed_rejects_non_ascii_token_without_raising(self):
        # aiohttp decodes request headers as ISO-8859-1, so a header byte in
        # 0x80-0xFF arrives as a non-ASCII str. hmac.compare_digest raises
        # TypeError on non-ASCII *str* args — comparing bytes (the fix) must
        # fail closed with a clean False instead of a 500-causing TypeError.
        inst = ipc._AiToolsIpc()
        inst.token = "secret"
        req = SimpleNamespace(headers={"X-Token": "\x80\x81bad"})
        assert inst._authed(req) is False


class TestMemoryDispatch:
    async def test_recall_no_facts(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_AI_TOOLS", "1")
        from cogs.ai_core.memory import long_term_memory as ltm_mod

        monkeypatch.setattr(ltm_mod.long_term_memory, "get_user_facts", AsyncMock(return_value=[]))
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch("recall_memory", {}, {"user_id": 7})
        assert is_err is False
        assert "No stored facts" in text

    async def test_recall_with_facts_and_query_filter(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_AI_TOOLS", "1")
        from cogs.ai_core.memory import long_term_memory as ltm_mod

        facts = [SimpleNamespace(content="likes teal"), SimpleNamespace(content="dislikes onions")]
        monkeypatch.setattr(
            ltm_mod.long_term_memory, "get_user_facts", AsyncMock(return_value=facts)
        )
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch("recall_memory", {"query": "teal"}, {"user_id": 7})
        assert is_err is False
        assert "likes teal" in text
        assert "onions" not in text

    async def test_remember_calls_add_explicit_fact(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_AI_TOOLS", "1")
        from cogs.ai_core.memory import long_term_memory as ltm_mod

        mock_add = AsyncMock(return_value=SimpleNamespace(content="x"))
        monkeypatch.setattr(ltm_mod.long_term_memory, "add_explicit_fact", mock_add)
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch(
            "remember", {"content": "favorite color is teal"}, {"user_id": 7, "channel_id": 9}
        )
        assert is_err is False
        assert "Remembered" in text
        mock_add.assert_awaited_once()

    async def test_remember_empty_content_errors(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_AI_TOOLS", "1")
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch("remember", {"content": "   "}, {"user_id": 7})
        assert is_err is True

    async def test_memory_requires_user_context(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_AI_TOOLS", "1")
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch("recall_memory", {}, {})
        assert is_err is True
        assert "user context" in text.lower()


class TestServerDispatch:
    async def test_server_tool_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("DASHBOARD_CLI_SERVER_ACTIONS", raising=False)
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch("list_channels", {}, {"channel_id": 1, "user_id": 2})
        assert is_err is True
        assert "disabled" in text.lower()

    async def test_server_tool_enabled_dispatches_to_execute_tool_call(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        from cogs.ai_core import tools as tools_mod

        called = {}

        async def fake_exec(bot, channel, member, tool_call):
            called["name"] = tool_call.name
            called["input"] = tool_call.input
            called["member"] = member
            return "channels: #general"

        monkeypatch.setattr(tools_mod, "execute_tool_call", fake_exec)
        member = object()
        guild = SimpleNamespace(get_member=lambda uid: member)
        channel = SimpleNamespace(guild=guild)
        bot = SimpleNamespace(get_channel=lambda cid: channel)
        inst = ipc._AiToolsIpc()
        inst.bot = bot
        text, is_err = await inst._dispatch("list_channels", {}, {"channel_id": 10, "user_id": 20})
        assert is_err is False
        assert text == "channels: #general"
        assert called["name"] == "list_channels"
        assert called["member"] is member

    async def test_read_tool_returns_captured_channel_output(self, monkeypatch):
        # Read-only tools run against a capture channel; the AI must get the
        # DATA the cmd_ would have posted, not the "Listed channels" status.
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        from cogs.ai_core import tools as tools_mod

        async def fake_exec(bot, channel, member, tool_call):
            await channel.send("#general (ID: 1)\n#random (ID: 2)")
            return "Listed channels"

        monkeypatch.setattr(tools_mod, "execute_tool_call", fake_exec)
        member = object()
        guild = SimpleNamespace(get_member=lambda uid: member)
        channel = SimpleNamespace(guild=guild)
        bot = SimpleNamespace(get_channel=lambda cid: channel)
        inst = ipc._AiToolsIpc()
        inst.bot = bot
        text, is_err = await inst._dispatch("list_channels", {}, {"channel_id": 10, "user_id": 20})
        assert is_err is False
        assert "#general" in text and "#random" in text
        assert "Listed channels" not in text

    async def test_mutation_tool_uses_real_channel(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        from cogs.ai_core import tools as tools_mod

        seen = {}

        async def fake_exec(bot, channel, member, tool_call):
            seen["channel"] = channel
            return "Requested creation of text channel 'foo'"

        monkeypatch.setattr(tools_mod, "execute_tool_call", fake_exec)
        member = object()
        guild = SimpleNamespace(get_member=lambda uid: member)
        channel = SimpleNamespace(guild=guild)
        bot = SimpleNamespace(get_channel=lambda cid: channel)
        inst = ipc._AiToolsIpc()
        inst.bot = bot
        text, is_err = await inst._dispatch(
            "create_text_channel", {"name": "foo"}, {"channel_id": 10, "user_id": 20}
        )
        assert is_err is False
        assert "foo" in text
        assert seen["channel"] is channel  # real channel, NOT a capture wrapper

    async def test_permission_denial_marks_error(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        from cogs.ai_core import tools as tools_mod

        async def fake_exec(bot, channel, member, tool_call):
            return "⛔ Permission denied: requires manage_channels permission."

        monkeypatch.setattr(tools_mod, "execute_tool_call", fake_exec)
        member = object()
        guild = SimpleNamespace(get_member=lambda uid: member)
        channel = SimpleNamespace(guild=guild)
        bot = SimpleNamespace(get_channel=lambda cid: channel)
        inst = ipc._AiToolsIpc()
        inst.bot = bot
        text, is_err = await inst._dispatch(
            "create_text_channel", {"name": "x"}, {"channel_id": 10, "user_id": 20}
        )
        assert is_err is True
        assert "Permission denied" in text

    async def test_server_tool_missing_context_errors(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        inst = ipc._AiToolsIpc()
        inst.bot = SimpleNamespace(get_channel=lambda cid: None)
        text, is_err = await inst._dispatch("list_channels", {}, {})
        assert is_err is True

    async def test_unknown_tool_errors(self, monkeypatch):
        inst = ipc._AiToolsIpc()
        text, is_err = await inst._dispatch("does_not_exist", {}, {"user_id": 1})
        assert is_err is True
        assert "Unknown tool" in text


class TestServerDispatchIntegration:
    """Drives the REAL execute_tool_call (not mocked) through the capture
    channel, proving the read-data path returns actual guild state to the AI."""

    async def test_list_channels_returns_real_data_via_capture(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_CLI_SERVER_ACTIONS", "1")
        # Channels expose permissions_for so cmd_list_channels can run its
        # view-permission filter (the unfiltered else path now fails closed
        # for non-Member callers).
        _view_ok = SimpleNamespace(view_channel=True)
        text_channels = [
            SimpleNamespace(name="general", id=1, permissions_for=lambda _u: _view_ok),
            SimpleNamespace(name="random", id=2, permissions_for=lambda _u: _view_ok),
        ]
        # spec=discord.Member so the isinstance(_user, discord.Member) gate
        # passes (a duck-typed SimpleNamespace would now be refused).
        member = MagicMock(spec=discord.Member)
        member.display_name = "tester"
        member.guild_permissions = SimpleNamespace(
            administrator=False, manage_channels=False, manage_roles=False
        )
        guild = SimpleNamespace(text_channels=text_channels, get_member=lambda uid: member)
        channel = SimpleNamespace(guild=guild)
        bot = SimpleNamespace(get_channel=lambda cid: channel)
        inst = ipc._AiToolsIpc()
        inst.bot = bot
        text, is_err = await inst._dispatch("list_channels", {}, {"channel_id": 10, "user_id": 20})
        assert is_err is False
        # The AI gets the actual channel names (captured), not a status string.
        assert "general" in text
        assert "random" in text
        assert text != "Listed channels"
