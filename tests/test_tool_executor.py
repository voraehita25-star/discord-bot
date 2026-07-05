# pylint: disable=protected-access
"""
Unit Tests for Tool Executor Module.
Tests tool execution and webhook functionality.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestExecuteToolCall:
    """Tests for execute_tool_call function."""

    @pytest.mark.asyncio
    async def test_permission_denied_non_admin(self):
        """Test execute_tool_call denies non-admin users."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.display_name = "TestUser"
        user.guild_permissions.administrator = False

        tool_call = MagicMock()
        tool_call.name = "create_text_channel"
        tool_call.args = {"name": "test"}

        result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Permission denied" in result

    @pytest.mark.asyncio
    async def test_unknown_function(self):
        """Test execute_tool_call handles unknown functions."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "unknown_function_xyz"
        tool_call.args = {}

        result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Unknown function" in result

    @pytest.mark.asyncio
    async def test_remember_function(self):
        """Test remember function saves memory."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()
        channel.id = 123456789

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "remember"
        tool_call.args = {"content": "Remember this important fact"}

        with patch("cogs.ai_core.tools.tool_executor.rag_system") as mock_rag:
            mock_rag.add_memory = AsyncMock()
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Saved to long-term memory" in result

    @pytest.mark.asyncio
    async def test_remember_empty_content(self):
        """Test remember function handles empty content."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "remember"
        tool_call.args = {}

        result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Failed to save memory" in result


class TestExecuteServerCommand:
    """Tests for execute_server_command function."""

    @pytest.mark.asyncio
    async def test_permission_denied_non_admin(self):
        """Test execute_server_command denies non-admin users."""
        from cogs.ai_core.tools.tool_executor import execute_server_command

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()

        user = MagicMock()
        user.guild_permissions.administrator = False
        user.display_name = "TestUser"

        await execute_server_command(bot, channel, user, "create_text", "test")

        channel.send.assert_called()
        call_args = channel.send.call_args[0][0]
        assert "Admin" in call_args

    @pytest.mark.asyncio
    async def test_non_guild_channel(self):
        """Test execute_server_command handles non-guild channels."""
        from cogs.ai_core.tools.tool_executor import execute_server_command

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        channel.guild = None  # No guild

        user = MagicMock()
        user.guild_permissions.administrator = True

        await execute_server_command(bot, channel, user, "create_text", "test")

        channel.send.assert_called()
        call_args = channel.send.call_args[0][0]
        assert "server" in call_args.lower()

    @pytest.mark.asyncio
    async def test_name_too_long(self):
        """Test execute_server_command rejects long names."""
        from cogs.ai_core.tools.tool_executor import execute_server_command

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        long_name = "A" * 150  # Exceeds 100 char limit
        await execute_server_command(bot, channel, user, "create_text", long_name)

        channel.send.assert_called()
        call_args = channel.send.call_args[0][0]
        assert "ยาวเกินไป" in call_args

    @pytest.mark.asyncio
    async def test_unknown_command_type(self):
        """Test execute_server_command handles unknown command types."""
        from cogs.ai_core.tools.tool_executor import execute_server_command

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        # Unknown command type should just log warning, not crash
        await execute_server_command(bot, channel, user, "unknown_command_xyz", "test")


class TestSendAsWebhook:
    """Tests for send_as_webhook function."""

    @pytest.mark.asyncio
    async def test_no_webhook_permission(self):
        """Test send_as_webhook falls back when no permission."""
        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()

        permissions = MagicMock()
        permissions.manage_webhooks = False
        channel.permissions_for.return_value = permissions

        await send_as_webhook(bot, channel, "TestChar", "Hello!")

        channel.send.assert_called_once()
        call_args = channel.send.call_args[0][0]
        assert "TestChar" in call_args
        assert "Hello!" in call_args

    @pytest.mark.asyncio
    async def test_cached_webhook_success(self):
        """Test send_as_webhook uses cached webhook."""
        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.id = 123456
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()

        permissions = MagicMock()
        permissions.manage_webhooks = True
        channel.permissions_for.return_value = permissions

        mock_webhook = MagicMock()
        mock_webhook.send = AsyncMock(return_value=MagicMock())

        with patch("cogs.ai_core.tools.tool_executor.get_cached_webhook") as mock_get:
            mock_get.return_value = mock_webhook

            await send_as_webhook(bot, channel, "TestChar", "Hello!")

        mock_webhook.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_long_message_chunking(self):
        """Test send_as_webhook chunks long messages."""
        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.id = 123456
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()

        permissions = MagicMock()
        permissions.manage_webhooks = True
        channel.permissions_for.return_value = permissions

        mock_webhook = MagicMock()
        mock_webhook.send = AsyncMock(return_value=MagicMock())

        with patch("cogs.ai_core.tools.tool_executor.get_cached_webhook") as mock_get:
            mock_get.return_value = mock_webhook

            long_message = "A" * 3000  # Over 2000 limit
            await send_as_webhook(bot, channel, "TestChar", long_message)

        # Should be called twice (chunked)
        assert mock_webhook.send.call_count == 2

    @pytest.mark.asyncio
    async def test_fresh_webhook_partial_failure_sends_only_tail(self):
        """Fresh find/create webhook path: when a later chunk fails mid-send, only
        the UNDELIVERED tail goes to the plain fallback; already-delivered chunks
        are NOT re-posted (Finding 1). Regression for the duplicate/garbled output
        bug where the outer handler used to re-send the full original message.
        """
        import discord

        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.id = 987654
        channel.send = AsyncMock()
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()

        permissions = MagicMock()
        permissions.manage_webhooks = True
        channel.permissions_for.return_value = permissions

        channel.webhooks = AsyncMock(return_value=[])
        mock_webhook = MagicMock()
        mock_webhook.name = "AI: TestChar"
        mock_webhook.send = AsyncMock(
            side_effect=[MagicMock(), discord.HTTPException(MagicMock(), "boom")]
        )
        channel.create_webhook = AsyncMock(return_value=mock_webhook)

        # Splits into exactly two chunks at the space near 1500 (limit 2000).
        first = "A" * 1490
        tail = "B" * 1009
        message = first + " " + tail

        with (
            patch("cogs.ai_core.tools.tool_executor.get_cached_webhook", return_value=None),
            patch("cogs.ai_core.tools.tool_executor.set_cached_webhook"),
        ):
            await send_as_webhook(bot, channel, "TestChar", message)

        # Both chunks were attempted on the webhook (chunk 0 ok, chunk 1 raised).
        assert mock_webhook.send.call_count == 2
        # Plain fallback fired for the undelivered tail only.
        assert channel.send.called
        sent_text = "".join(str(c.args[0]) for c in channel.send.call_args_list)
        # The already-delivered first chunk must NOT be re-posted; only the tail.
        assert first not in sent_text
        assert "B" in sent_text

    @pytest.mark.asyncio
    async def test_webhook_escapes_legacy_bang_mention(self):
        """The webhook path delegates to the authoritative escape_mentions, so a
        legacy nickname mention <@!ID> keeps its bang (defanged to <@!\u200bID>,
        not <@\u200bID>). manage_webhooks False forces the plain-text fallback.
        """
        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.send = AsyncMock()
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()

        permissions = MagicMock()
        permissions.manage_webhooks = False
        channel.permissions_for.return_value = permissions

        await send_as_webhook(bot, channel, "TestChar", "yo <@!123>")

        channel.send.assert_called_once()
        content = channel.send.call_args[0][0]
        assert "<@!\u200b123>" in content
        assert "<@\u200b123>" not in content

    @pytest.mark.asyncio
    async def test_early_fallback_partial_failure_sends_only_tail(self):
        """Finding 1: when an EARLY plain-fallback path (here no manage_webhooks)
        fails AFTER delivering a chunk, the function-level handler must re-send
        ONLY the undelivered tail \u2014 already-delivered chunks are NOT re-posted.
        Before the fix, pending_chunks was None on this path so the handler
        re-sent the full original message and duplicated the first chunk.
        """
        import discord

        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()

        permissions = MagicMock()
        permissions.manage_webhooks = False  # forces the early plain-fallback path
        channel.permissions_for.return_value = permissions

        # chunk 0 ok, chunk 1 raises; the outer handler's tail re-send then ok.
        # A 4th entry lets the OLD (buggy) full re-send run to completion so the
        # count assertion fails cleanly rather than on StopIteration.
        channel.send = AsyncMock(
            side_effect=[
                MagicMock(),
                discord.HTTPException(MagicMock(), "boom"),
                MagicMock(),
                MagicMock(),
            ]
        )

        first = "A" * 1490
        tail = "B" * 1009
        message = first + " " + tail  # splits into exactly two plain chunks

        await send_as_webhook(bot, channel, "TestChar", message)

        sent_text = "".join(str(c.args[0]) for c in channel.send.call_args_list)
        # The already-delivered first chunk must appear EXACTLY once (not re-posted).
        assert sent_text.count(first) == 1
        # The undelivered tail is re-sent by the handler.
        assert tail in sent_text

    @pytest.mark.asyncio
    async def test_dm_early_path_returns_delivered_message(self):
        """Finding 2: the DM early path returns the delivered message object (not
        None) so logic.py can stamp its id for edit/delete mirroring.
        """
        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = None  # DM: no guild
        sentinel = MagicMock()
        channel.send = AsyncMock(return_value=sentinel)

        result = await send_as_webhook(bot, channel, "TestChar", "Hello!")

        assert result is sentinel

    @pytest.mark.asyncio
    async def test_thread_early_path_returns_delivered_message(self):
        """Finding 2: the thread early path (channel has no .webhooks) also returns
        the delivered message object rather than None.
        """
        from cogs.ai_core.tools.tool_executor import send_as_webhook

        bot = MagicMock()
        channel = MagicMock(spec=["guild", "send", "id"])  # no .webhooks attr
        channel.guild = MagicMock()
        sentinel = MagicMock()
        channel.send = AsyncMock(return_value=sentinel)

        result = await send_as_webhook(bot, channel, "TestChar", "Hello!")

        assert result is sentinel


class TestSafeSplitMessage:
    def test_no_orphaned_thai_mark_on_hard_cut(self):
        # Regression: 8 ASCII + a Thai syllable (base + 2 combining marks) +
        # filler with NO spaces/newlines forces a hard cut that pre-fix landed
        # between the combining marks, orphaning one at the next chunk's start
        # (renders as a stray ◌-form glyph). The hard-cut branch now rewinds past
        # the marks AND their base char, mirroring _split_for_discord.
        from cogs.ai_core.tools.tool_executor import _THAI_COMBINING, _safe_split_message

        text = "a" * 8 + "ก่่" + "b" * 10
        chunks = _safe_split_message(text, limit=10)
        assert len(chunks) > 1
        for c in chunks:
            assert c  # never an empty chunk
            assert ord(c[0]) not in _THAI_COMBINING  # no orphaned combining mark
        assert "".join(chunks) == text  # the hard cut loses no content

    def test_no_orphaned_thai_mark_on_base_boundary_cut(self):
        # Regression: a hard cut landing EXACTLY between a base char and its
        # FIRST combining mark ('…ก|่…'). The original rewind only inspected
        # the char BEFORE the cut (the base — not combining), so it never
        # fired and the mark started the next chunk as a stray ◌-form glyph.
        from cogs.ai_core.tools.tool_executor import _THAI_COMBINING, _safe_split_message

        text = "a" * 9 + "ก่" + "b" * 10  # cut at 10 lands on the mark
        chunks = _safe_split_message(text, limit=10)
        assert len(chunks) > 1
        for c in chunks:
            assert c
            assert ord(c[0]) not in _THAI_COMBINING
        assert "".join(chunks) == text

    def test_split_for_discord_no_orphaned_mark_both_boundaries(self):
        # The declared mirror in logic.py must handle both hard-cut shapes:
        # between two marks (ก่|่) and between base and first mark (ก|่).
        from cogs.ai_core.logic import _THAI_COMBINING, _split_for_discord

        for text in ("a" * 8 + "ก่่" + "b" * 10, "a" * 9 + "ก่" + "b" * 10):
            chunks = _split_for_discord(text, limit=10)
            assert len(chunks) > 1
            for c in chunks:
                assert c
                assert ord(c[0]) not in _THAI_COMBINING
            assert "".join(chunks) == text
        # And at the real Discord limit with spaceless Thai filler.
        text = "x" * 1999 + "กิ" + "y" * 50
        chunks = _split_for_discord(text)
        for c in chunks:
            assert ord(c[0]) not in _THAI_COMBINING
        assert "".join(chunks) == text


class TestModuleExports:
    """Tests for module exports."""

    def test_all_exports(self):
        """Test __all__ exports are defined."""
        from cogs.ai_core.tools.tool_executor import __all__

        assert "execute_server_command" in __all__
        assert "execute_tool_call" in __all__
        assert "send_as_webhook" in __all__

    def test_functions_callable(self):
        """Test exported functions are callable."""
        from cogs.ai_core.tools.tool_executor import (
            execute_server_command,
            execute_tool_call,
            send_as_webhook,
        )

        assert callable(execute_server_command)
        assert callable(execute_tool_call)
        assert callable(send_as_webhook)


class TestExecuteToolCallMoreFunctions:
    """Additional tests for execute_tool_call with various functions."""

    @pytest.mark.asyncio
    async def test_create_text_channel(self):
        """Test create_text_channel function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "create_text_channel"
        tool_call.args = {"name": "new-channel", "category": "Test Category"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_create_text", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested creation of text channel" in result
        assert "new-channel" in result

    @pytest.mark.asyncio
    async def test_create_voice_channel(self):
        """Test create_voice_channel function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "create_voice_channel"
        tool_call.args = {"name": "Voice Room", "category": None}

        with patch("cogs.ai_core.tools.tool_executor.cmd_create_voice", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested creation of voice channel" in result
        assert "Voice Room" in result

    @pytest.mark.asyncio
    async def test_create_category(self):
        """Test create_category function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "create_category"
        tool_call.args = {"name": "New Category"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_create_category", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested creation of category" in result

    @pytest.mark.asyncio
    async def test_delete_channel(self):
        """Test delete_channel function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "delete_channel"
        tool_call.args = {"name_or_id": "old-channel"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_delete_channel", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested deletion of channel" in result

    @pytest.mark.asyncio
    async def test_create_role(self):
        """Test create_role function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "create_role"
        tool_call.args = {"name": "New Role", "color_hex": "#FF0000"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_create_role", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested creation of role" in result

    @pytest.mark.asyncio
    async def test_delete_role(self):
        """Test delete_role function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "delete_role"
        tool_call.args = {"name_or_id": "Old Role"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_delete_role", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested deletion of role" in result

    @pytest.mark.asyncio
    async def test_add_role(self):
        """Test add_role function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "add_role"
        tool_call.args = {"user_name": "TestUser", "role_name": "Member"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_add_role", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested adding role" in result

    @pytest.mark.asyncio
    async def test_remove_role(self):
        """Test remove_role function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "remove_role"
        tool_call.args = {"user_name": "TestUser", "role_name": "Member"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_remove_role", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested removing role" in result

    @pytest.mark.asyncio
    async def test_list_channels(self):
        """Test list_channels function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "list_channels"
        tool_call.args = {}

        with patch("cogs.ai_core.tools.tool_executor.cmd_list_channels", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Listed channels" in result

    @pytest.mark.asyncio
    async def test_list_roles(self):
        """Test list_roles function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "list_roles"
        tool_call.args = {}

        with patch("cogs.ai_core.tools.tool_executor.cmd_list_roles", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Listed roles" in result

    @pytest.mark.asyncio
    async def test_list_members(self):
        """Test list_members function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "list_members"
        tool_call.args = {"limit": 100, "query": "admin"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_list_members", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Listed members" in result

    @pytest.mark.asyncio
    async def test_get_user_info(self):
        """Test get_user_info function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "get_user_info"
        tool_call.args = {"target": "SomeUser"}

        with patch("cogs.ai_core.tools.tool_executor.cmd_get_user_info", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested info for" in result

    @pytest.mark.asyncio
    async def test_list_members_denied_without_manage_guild(self):
        """A caller without manage_guild must get a denial, not a false success.

        Regression: ``list_members`` used to live in ``_READ_ONLY_TOOLS``, so any
        member passed the executor gate and the executor returned the
        success-shaped "Listed members" string to the model — even though
        ``cmd_list_members`` requires manage_guild and fails CLOSED. The executor
        now mirrors the handler tier and denies up front. ``cmd_list_members`` is
        deliberately NOT mocked: the denial must happen at the gate, before the
        handler is ever reached.
        """
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.display_name = "RegularMember"
        user.guild_permissions.administrator = False
        user.guild_permissions.manage_guild = False

        tool_call = MagicMock()
        tool_call.name = "list_members"
        tool_call.args = {"limit": 100, "query": "admin"}

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_list_members", new_callable=AsyncMock
        ) as mock_cmd:
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Permission denied" in result
        assert "manage_guild" in result
        assert "Listed members" not in result
        # Gate fired before the handler: no false success could leak to the model.
        mock_cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_info_denied_without_manage_guild(self):
        """A caller without manage_guild must get a denial, not a false success.

        Regression mirror of ``test_list_members_denied_without_manage_guild`` for
        ``get_user_info`` (handler ``cmd_get_user_info`` requires manage_guild and
        fails CLOSED). ``cmd_get_user_info`` is deliberately NOT mocked.
        """
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.display_name = "RegularMember"
        user.guild_permissions.administrator = False
        user.guild_permissions.manage_guild = False

        tool_call = MagicMock()
        tool_call.name = "get_user_info"
        tool_call.args = {"target": "SomeUser"}

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_get_user_info", new_callable=AsyncMock
        ) as mock_cmd:
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Permission denied" in result
        assert "manage_guild" in result
        assert "Requested info for" not in result
        mock_cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_members_allowed_with_manage_guild_non_admin(self):
        """A non-admin caller WITH manage_guild still succeeds (not over-restricted).

        Guards against the fix tightening the gate to admin-only: manage_guild
        alone must be sufficient, matching ``cmd_list_members``.
        """
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = False
        user.guild_permissions.manage_guild = True

        tool_call = MagicMock()
        tool_call.name = "list_members"
        tool_call.args = {}

        with patch("cogs.ai_core.tools.tool_executor.cmd_list_members", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Listed members" in result

    @pytest.mark.asyncio
    async def test_read_channel(self):
        """Test read_channel function.

        read_channel now performs a per-channel permission check via
        ``target_channel.permissions_for(user).read_messages`` to prevent
        a non-admin from asking the AI to relay messages from a private
        staff/mod channel they have no access to. The test patches
        ``discord.utils.get`` to return a controlled mock channel with
        the right permissions, so the auth check passes through.
        """
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        # Caller has read access on the target channel.
        target_channel = MagicMock()
        target_channel.permissions_for.return_value = MagicMock(
            read_messages=True,
            view_channel=True,
        )

        tool_call = MagicMock()
        tool_call.name = "read_channel"
        tool_call.args = {"channel_name": "general", "limit": 50}

        with (
            patch("cogs.ai_core.tools.tool_executor.cmd_read_channel", new_callable=AsyncMock),
            patch(
                "cogs.ai_core.tools.tool_executor.discord.utils.get", return_value=target_channel
            ),
        ):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested reading channel" in result

    @pytest.mark.asyncio
    async def test_set_channel_permission(self):
        """Test set_channel_permission function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "set_channel_permission"
        tool_call.args = {
            "channel_name": "general",
            "target_name": "Member",
            "permission": "send_messages",
            "value": True,
        }

        with patch("cogs.ai_core.tools.tool_executor.cmd_set_channel_perm", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested setting channel permission" in result

    @pytest.mark.asyncio
    async def test_set_role_permission(self):
        """Test set_role_permission function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "set_role_permission"
        tool_call.args = {
            "role_name": "Member",
            "permission": "manage_messages",
            "value": False,
        }

        with patch("cogs.ai_core.tools.tool_executor.cmd_set_role_perm", new_callable=AsyncMock):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Requested setting role permission" in result

    @pytest.mark.asyncio
    async def test_set_channel_permission_non_string_permission(self):
        """A non-string ``permission`` must yield a clear help message.

        Regression (audit py-ai-tools-1): the mutation branches did not
        isinstance-check string args, so a non-string (e.g. permission=123)
        hit ``.strip()`` downstream and surfaced as an opaque
        ``Error executing ...: AttributeError`` instead of guidance.
        """
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "set_channel_permission"
        tool_call.args = {
            "channel_name": "general",
            "target_name": "Member",
            "permission": 123,
            "value": True,
        }

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_set_channel_perm",
            new_callable=AsyncMock,
        ) as cmd:
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Missing/invalid argument for set_channel_permission" in result
        assert "AttributeError" not in result
        cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_role_permission_non_string_permission(self):
        """A non-string ``permission`` for set_role_permission must be rejected clearly."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "set_role_permission"
        tool_call.args = {
            "role_name": "Member",
            "permission": 123,
            "value": False,
        }

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_set_role_perm",
            new_callable=AsyncMock,
        ) as cmd:
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Missing/invalid argument for set_role_permission" in result
        assert "AttributeError" not in result
        cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_role_non_string_role_name(self):
        """A non-string ``role_name`` for add_role must give guidance, not AttributeError."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "add_role"
        tool_call.args = {"user_name": "TestUser", "role_name": 123}

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_add_role",
            new_callable=AsyncMock,
        ) as cmd:
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "add_role requires both user_name and role_name" in result
        assert "AttributeError" not in result
        cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_role_non_string_user_name(self):
        """A non-string ``user_name`` for remove_role must give guidance, not AttributeError."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "remove_role"
        tool_call.args = {"user_name": 123, "role_name": "Member"}

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_remove_role",
            new_callable=AsyncMock,
        ) as cmd:
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "remove_role requires both user_name and role_name" in result
        assert "AttributeError" not in result
        cmd.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_execution_error_handling(self):
        """Test error handling during tool execution."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "create_text_channel"
        tool_call.args = {"name": "test"}

        with patch(
            "cogs.ai_core.tools.tool_executor.cmd_create_text",
            new_callable=AsyncMock,
            side_effect=ValueError("Test error"),
        ):
            result = await execute_tool_call(bot, channel, user, tool_call)

        assert "Error executing" in result
