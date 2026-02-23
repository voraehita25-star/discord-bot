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
    async def test_read_channel(self):
        """Test read_channel function."""
        from cogs.ai_core.tools.tool_executor import execute_tool_call

        bot = MagicMock()
        channel = MagicMock()
        channel.guild = MagicMock()

        user = MagicMock()
        user.guild_permissions.administrator = True

        tool_call = MagicMock()
        tool_call.name = "read_channel"
        tool_call.args = {"channel_name": "general", "limit": 50}

        with patch("cogs.ai_core.tools.tool_executor.cmd_read_channel", new_callable=AsyncMock):
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
