"""
Extended tests for cogs/ai_core/commands/server_commands.py
Comprehensive tests for channel, role, and permission management.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


class TestCmdCreateVoice:
    """Tests for cmd_create_voice function."""

    @pytest.mark.asyncio
    async def test_create_voice_channel_empty_name(self):
        """Test creating voice channel with empty name does nothing."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_guild = MagicMock(spec=discord.Guild)
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()

        await cmd_create_voice(mock_guild, mock_channel, "", [])
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_voice_channel_invalid_name(self):
        """Test creating voice channel with invalid name falls back to 'untitled'."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_voice_channel = MagicMock(spec=discord.VoiceChannel)
        mock_voice_channel.id = 456

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_voice_channel = AsyncMock(return_value=mock_voice_channel)
        mock_guild.categories = []
        mock_guild.me = MagicMock()
        mock_guild.me.id = 999
        mock_guild.id = 123456

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()

        # Name with only special chars is sanitized to "untitled" fallback
        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_voice(mock_guild, mock_channel, "@#$%^", [])

        # Channel should be created with fallback name "untitled"
        mock_guild.create_voice_channel.assert_called_once()
        call_args = mock_guild.create_voice_channel.call_args
        assert call_args[0][0] == "untitled"

    @pytest.mark.asyncio
    async def test_create_voice_channel_success(self):
        """Test successful voice channel creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_voice_channel = MagicMock(spec=discord.VoiceChannel)
        mock_voice_channel.id = 456

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_voice_channel = AsyncMock(return_value=mock_voice_channel)
        mock_guild.categories = []
        mock_guild.me = MagicMock()
        mock_guild.me.id = 999
        mock_guild.id = 123456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_voice(mock_guild, mock_origin, "test-voice", [])

        mock_guild.create_voice_channel.assert_called_once()
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_create_voice_channel_with_category(self):
        """Test creating voice channel in a category."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_category = MagicMock(spec=discord.CategoryChannel)
        mock_category.name = "Voice Channels"

        mock_voice_channel = MagicMock(spec=discord.VoiceChannel)

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_voice_channel = AsyncMock(return_value=mock_voice_channel)
        mock_guild.categories = [mock_category]
        mock_guild.me = MagicMock()

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=mock_category):
            with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
                await cmd_create_voice(mock_guild, mock_origin, "test-voice", ["test-voice", "Voice Channels"])

        mock_guild.create_voice_channel.assert_called()

    @pytest.mark.asyncio
    async def test_create_voice_channel_forbidden(self):
        """Test voice channel creation with forbidden error."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_voice_channel = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No permission"))
        mock_guild.categories = []

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_voice(mock_guild, mock_origin, "test-voice", [])
        mock_origin.send.assert_called()
        assert "ไม่มีสิทธิ์" in str(mock_origin.send.call_args)


class TestCmdCreateCategory:
    """Tests for cmd_create_category function."""

    @pytest.mark.asyncio
    async def test_create_category_empty_name(self):
        """Test creating category with empty name does nothing."""
        from cogs.ai_core.commands.server_commands import cmd_create_category

        mock_guild = MagicMock(spec=discord.Guild)
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()

        await cmd_create_category(mock_guild, mock_channel, "", [])
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_category_invalid_name(self):
        """Test creating category with invalid name falls back to 'untitled'."""
        from cogs.ai_core.commands.server_commands import cmd_create_category

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_category = AsyncMock()

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()

        # Name with only special chars is sanitized to "untitled" fallback
        await cmd_create_category(mock_guild, mock_channel, "@#$%", [])

        # Category should be created with fallback name "untitled"
        mock_guild.create_category.assert_called_once_with("untitled")

    @pytest.mark.asyncio
    async def test_create_category_success(self):
        """Test successful category creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_category

        mock_category = MagicMock(spec=discord.CategoryChannel)

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_category = AsyncMock(return_value=mock_category)

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_category(mock_guild, mock_origin, "New-Category", [])

        mock_guild.create_category.assert_called_once()
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_create_category_forbidden(self):
        """Test category creation with forbidden error."""
        from cogs.ai_core.commands.server_commands import cmd_create_category

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_category = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No permission"))

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_category(mock_guild, mock_origin, "New-Category", [])
        assert "ไม่มีสิทธิ์" in str(mock_origin.send.call_args)


class TestCmdDeleteChannel:
    """Tests for cmd_delete_channel function."""

    @pytest.mark.asyncio
    async def test_delete_channel_success(self):
        """Test successful channel deletion."""
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        mock_text_channel = MagicMock(spec=discord.TextChannel)
        mock_text_channel.name = "test-channel"
        mock_text_channel.delete = AsyncMock()

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = [mock_text_channel]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_channel(mock_guild, mock_origin, "test-channel", [])

        mock_text_channel.delete.assert_called_once()
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_delete_channel_not_found(self):
        """Test deleting non-existent channel."""
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = []
        mock_guild.get_channel.return_value = None

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_channel(mock_guild, mock_origin, "nonexistent", [])

        mock_origin.send.assert_called()
        assert "ไม่พบช่อง" in str(mock_origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_channel_duplicate_names(self):
        """Test deleting channel with duplicate names shows warning."""
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        mock_channel1 = MagicMock(spec=discord.TextChannel)
        mock_channel1.name = "general"
        mock_channel2 = MagicMock(spec=discord.TextChannel)
        mock_channel2.name = "general"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = [mock_channel1, mock_channel2]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_channel(mock_guild, mock_origin, "general", [])

        mock_origin.send.assert_called()
        assert "ID" in str(mock_origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_channel_by_id(self):
        """Test deleting channel by ID."""
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "test-channel"
        mock_channel.delete = AsyncMock()

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = []
        mock_guild.get_channel.return_value = mock_channel

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_channel(mock_guild, mock_origin, "123456789", [])

        mock_channel.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_channel_forbidden(self):
        """Test deleting channel with forbidden error."""
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.name = "protected"
        mock_channel.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No permission"))

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = [mock_channel]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_channel(mock_guild, mock_origin, "protected", [])
        assert "ไม่มีสิทธิ์" in str(mock_origin.send.call_args)


class TestCmdCreateRole:
    """Tests for cmd_create_role function."""

    @pytest.mark.asyncio
    async def test_create_role_no_args(self):
        """Test creating role with no arguments."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_role(mock_guild, mock_origin, "", [])
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_create_role_empty_name(self):
        """Test creating role with empty name."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_role(mock_guild, mock_origin, "", ["   "])
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_create_role_success(self):
        """Test successful role creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.id = 999

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_role = AsyncMock(return_value=mock_role)
        mock_guild.me = MagicMock()
        mock_guild.me.id = 123
        mock_guild.id = 456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_role(mock_guild, mock_origin, "", ["TestRole"])

        mock_guild.create_role.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_role_with_color(self):
        """Test creating role with color."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_role = MagicMock(spec=discord.Role)

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_role = AsyncMock(return_value=mock_role)
        mock_guild.me = MagicMock()
        mock_guild.id = 456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_role(mock_guild, mock_origin, "", ["TestRole", "#FF5733"])

        mock_guild.create_role.assert_called()

    @pytest.mark.asyncio
    async def test_create_role_invalid_color(self):
        """Test creating role with invalid color uses default."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_role = MagicMock(spec=discord.Role)

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_role = AsyncMock(return_value=mock_role)
        mock_guild.me = MagicMock()

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_role(mock_guild, mock_origin, "", ["TestRole", "invalid"])

        mock_guild.create_role.assert_called()

    @pytest.mark.asyncio
    async def test_create_role_forbidden(self):
        """Test role creation with forbidden error."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_role = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No permission"))

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_role(mock_guild, mock_origin, "", ["TestRole"])
        assert "ไม่มีสิทธิ์" in str(mock_origin.send.call_args)


class TestCmdDeleteRole:
    """Tests for cmd_delete_role function."""

    @pytest.mark.asyncio
    async def test_delete_role_no_args(self):
        """Test deleting role with no arguments."""
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_role(mock_guild, mock_origin, "", [])
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_delete_role_success(self):
        """Test successful role deletion."""
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"
        mock_role.delete = AsyncMock()

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role]
        mock_guild.get_role.return_value = None

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_role(mock_guild, mock_origin, "", ["TestRole"])

        mock_role.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_role_not_found(self):
        """Test deleting non-existent role."""
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = []
        mock_guild.get_role.return_value = None

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_role(mock_guild, mock_origin, "", ["NonexistentRole"])
        assert "ไม่พบยศ" in str(mock_origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_role_duplicate_names(self):
        """Test deleting role with duplicate names shows warning."""
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        mock_role1 = MagicMock(spec=discord.Role)
        mock_role1.name = "Member"
        mock_role2 = MagicMock(spec=discord.Role)
        mock_role2.name = "Member"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role1, mock_role2]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_role(mock_guild, mock_origin, "", ["member"])
        assert "ID" in str(mock_origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_role_by_id(self):
        """Test deleting role by ID."""
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"
        mock_role.delete = AsyncMock()

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = []
        mock_guild.get_role.return_value = mock_role

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_delete_role(mock_guild, mock_origin, "", ["123456789"])

        mock_role.delete.assert_called_once()


class TestCmdAddRole:
    """Tests for cmd_add_role function."""

    @pytest.mark.asyncio
    async def test_add_role_insufficient_args(self):
        """Test adding role with insufficient arguments."""
        from cogs.ai_core.commands.server_commands import cmd_add_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_add_role(mock_guild, mock_origin, "", ["OnlyUser"])
        # Should not proceed without both user and role

    @pytest.mark.asyncio
    async def test_add_role_success(self):
        """Test successful role addition."""
        from cogs.ai_core.commands.server_commands import cmd_add_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"
        mock_role.position = 5
        mock_role.__ge__ = MagicMock(return_value=False)  # role < bot_top_role

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.name = "testuser"
        mock_member.add_roles = AsyncMock()

        bot_role = MagicMock(spec=discord.Role)
        bot_role.position = 10

        mock_bot = MagicMock()
        mock_bot.top_role = bot_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role]
        mock_guild.members = [mock_member]
        mock_guild.me = mock_bot

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[mock_role, mock_member]):
            with patch("cogs.ai_core.commands.server_commands.find_member", return_value=mock_member):
                await cmd_add_role(mock_guild, mock_origin, "", ["TestUser", "TestRole"])

        mock_member.add_roles.assert_called_once_with(mock_role)

    @pytest.mark.asyncio
    async def test_add_role_user_not_found(self):
        """Test adding role when user not found."""
        from cogs.ai_core.commands.server_commands import cmd_add_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role]
        mock_guild.members = []

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[mock_role, None]):
            with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
                await cmd_add_role(mock_guild, mock_origin, "", ["NonexistentUser", "TestRole"])

        assert "ไม่พบผู้ใช้" in str(mock_origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_hierarchy_check(self):
        """Test adding role blocked by hierarchy."""
        from cogs.ai_core.commands.server_commands import cmd_add_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "AdminRole"
        mock_role.position = 15
        mock_role.__ge__ = MagicMock(return_value=True)  # role >= bot_top_role

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"

        bot_role = MagicMock(spec=discord.Role)
        bot_role.position = 10

        mock_bot = MagicMock()
        mock_bot.top_role = bot_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role]
        mock_guild.members = [mock_member]
        mock_guild.me = mock_bot

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[mock_role, mock_member]):
            with patch("cogs.ai_core.commands.server_commands.find_member", return_value=mock_member):
                await cmd_add_role(mock_guild, mock_origin, "", ["TestUser", "AdminRole"])

        # Should show error about position
        assert "ตำแหน่ง" in str(mock_origin.send.call_args)


class TestCmdRemoveRole:
    """Tests for cmd_remove_role function."""

    @pytest.mark.asyncio
    async def test_remove_role_insufficient_args(self):
        """Test removing role with insufficient arguments."""
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_remove_role(mock_guild, mock_origin, "", ["OnlyUser"])

    @pytest.mark.asyncio
    async def test_remove_role_success(self):
        """Test successful role removal."""
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"
        mock_role.position = 5
        mock_role.__ge__ = MagicMock(return_value=False)

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.name = "testuser"
        mock_member.remove_roles = AsyncMock()

        bot_role = MagicMock(spec=discord.Role)
        bot_role.position = 10

        mock_bot = MagicMock()
        mock_bot.top_role = bot_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role]
        mock_guild.members = [mock_member]
        mock_guild.me = mock_bot

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[mock_role, mock_member]):
            with patch("cogs.ai_core.commands.server_commands.find_member", return_value=mock_member):
                await cmd_remove_role(mock_guild, mock_origin, "", ["TestUser", "TestRole"])

        mock_member.remove_roles.assert_called_once()


class TestCmdSetChannelPerm:
    """Tests for cmd_set_channel_perm function."""

    @pytest.mark.asyncio
    async def test_set_channel_perm_insufficient_args(self):
        """Test setting channel perm with insufficient args."""
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_set_channel_perm(mock_guild, mock_origin, "", ["channel", "role", "perm"])
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_set_channel_perm_invalid_value(self):
        """Test setting channel perm with invalid value."""
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        mock_guild = MagicMock(spec=discord.Guild)
        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_set_channel_perm(mock_guild, mock_origin, "", ["channel", "role", "perm", "invalid"])
        assert "true" in str(mock_origin.send.call_args).lower() or "false" in str(mock_origin.send.call_args).lower()

    @pytest.mark.asyncio
    async def test_set_channel_perm_channel_not_found(self):
        """Test setting channel perm when channel not found."""
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = []

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=None):
            await cmd_set_channel_perm(mock_guild, mock_origin, "", ["nonexistent", "role", "view_channel", "true"])

        assert "ไม่พบช่อง" in str(mock_origin.send.call_args)


class TestListCommands:
    """Tests for list commands."""

    @pytest.mark.asyncio
    async def test_list_channels(self):
        """Test listing channels."""
        from cogs.ai_core.commands.server_commands import cmd_list_channels

        mock_text = MagicMock(spec=discord.TextChannel)
        mock_text.name = "general"
        mock_text.type = discord.ChannelType.text

        mock_voice = MagicMock(spec=discord.VoiceChannel)
        mock_voice.name = "voice"
        mock_voice.type = discord.ChannelType.voice

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = [mock_text, mock_voice]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_list_channels(mock_guild, mock_origin, "", [])
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_list_roles(self):
        """Test listing roles."""
        from cogs.ai_core.commands.server_commands import cmd_list_roles

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "Admin"
        mock_role.id = 123
        mock_role.mentionable = True
        mock_role.color = discord.Color.blue()

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_list_roles(mock_guild, mock_origin, "", [])
        mock_origin.send.assert_called()

    @pytest.mark.asyncio
    async def test_list_members(self):
        """Test listing members."""
        from cogs.ai_core.commands.server_commands import cmd_list_members

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.name = "testuser"
        mock_member.id = 123
        mock_member.status = discord.Status.online

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.members = [mock_member]
        mock_guild.member_count = 1

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_list_members(mock_guild, mock_origin, "", [])
        mock_origin.send.assert_called()
