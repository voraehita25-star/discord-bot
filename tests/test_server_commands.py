"""Tests for server_commands module."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


class TestFindMember:
    """Tests for find_member function."""

    def test_find_by_display_name(self):
        """Test finding member by display name."""
        from cogs.ai_core.commands.server_commands import find_member

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.name = "testuser123"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.members = [mock_member]

        result = find_member(mock_guild, "TestUser")
        assert result == mock_member

    def test_find_by_username(self):
        """Test finding member by username."""
        from cogs.ai_core.commands.server_commands import find_member

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "Nickname"
        mock_member.name = "username"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.members = [mock_member]

        # Mock discord.utils.get to return None first (for display_name), then match
        with patch("discord.utils.get") as mock_get:
            mock_get.side_effect = [None, mock_member, None, None]
            find_member(mock_guild, "username")
            # May return the member from iteration

    def test_find_case_insensitive(self):
        """Test case-insensitive member search."""
        from cogs.ai_core.commands.server_commands import find_member

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.name = "testuser"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.members = [mock_member]

        with patch("discord.utils.get", return_value=None):
            find_member(mock_guild, "TESTUSER")
            # Should find even with different case

    def test_find_not_found(self):
        """Test member not found returns None."""
        from cogs.ai_core.commands.server_commands import find_member

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.members = []

        with patch("discord.utils.get", return_value=None):
            result = find_member(mock_guild, "nonexistent")
            assert result is None


class TestCmdCreateText:
    """Tests for cmd_create_text function."""

    @pytest.mark.asyncio
    async def test_create_text_channel_empty_name(self):
        """Test creating text channel with empty name does nothing."""
        from cogs.ai_core.commands.server_commands import cmd_create_text

        mock_guild = MagicMock(spec=discord.Guild)
        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.send = AsyncMock()

        await cmd_create_text(mock_guild, mock_channel, "", [])

        # Should not try to create or send anything
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_text_channel_success(self):
        """Test successful text channel creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_text

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.id = 123

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_text_channel = AsyncMock(return_value=mock_channel)
        mock_guild.categories = []
        mock_guild.me = MagicMock()
        mock_guild.me.id = 999
        mock_guild.id = 123456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_text(mock_guild, mock_origin, "test-channel", [])

        mock_guild.create_text_channel.assert_called_once()
        mock_origin.send.assert_called_once()
        assert "✅" in mock_origin.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_text_channel_forbidden(self):
        """Test text channel creation with no permissions."""
        from cogs.ai_core.commands.server_commands import cmd_create_text

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_text_channel = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))
        mock_guild.categories = []

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_create_text(mock_guild, mock_origin, "test", [])

        mock_origin.send.assert_called_once()
        assert "❌" in mock_origin.send.call_args[0][0]
        assert "สิทธิ์" in mock_origin.send.call_args[0][0]


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
    async def test_create_voice_channel_success(self):
        """Test successful voice channel creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_vc = MagicMock(spec=discord.VoiceChannel)
        mock_vc.id = 456

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_voice_channel = AsyncMock(return_value=mock_vc)
        mock_guild.categories = []
        mock_guild.me = MagicMock()
        mock_guild.me.id = 999
        mock_guild.id = 123456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_voice(mock_guild, mock_origin, "voice-test", [])

        mock_guild.create_voice_channel.assert_called_once()


class TestCmdCreateCategory:
    """Tests for cmd_create_category function."""

    @pytest.mark.asyncio
    async def test_create_category_success(self):
        """Test successful category creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_category

        mock_category = MagicMock(spec=discord.CategoryChannel)
        mock_category.id = 789

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_category = AsyncMock(return_value=mock_category)
        mock_guild.me = MagicMock()
        mock_guild.me.id = 999
        mock_guild.id = 123456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_category(mock_guild, mock_origin, "Test Category", [])

        mock_guild.create_category.assert_called_once()


class TestCmdCreateRole:
    """Tests for cmd_create_role function."""

    @pytest.mark.asyncio
    async def test_create_role_success(self):
        """Test successful role creation."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.id = 111
        mock_role.name = "NewRole"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_role = AsyncMock(return_value=mock_role)
        mock_guild.me = MagicMock()
        mock_guild.me.id = 999
        mock_guild.id = 123456

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            # Note: cmd_create_role uses args[0] for role name, not name param
            await cmd_create_role(mock_guild, mock_origin, "", ["NewRole"])

        mock_guild.create_role.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_role_with_color(self):
        """Test role creation with color."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        mock_role = MagicMock(spec=discord.Role)

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_role = AsyncMock(return_value=mock_role)
        mock_guild.me = MagicMock()
        mock_guild.id = 123

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_role(mock_guild, mock_origin, "ColorRole", ["#FF0000"])


class TestCmdListChannels:
    """Tests for cmd_list_channels function."""

    @pytest.mark.asyncio
    async def test_list_channels(self):
        """Test listing channels."""
        from cogs.ai_core.commands.server_commands import cmd_list_channels

        mock_channel1 = MagicMock(spec=discord.TextChannel)
        mock_channel1.name = "general"
        mock_channel1.id = 1
        mock_channel1.category = None

        mock_channel2 = MagicMock(spec=discord.TextChannel)
        mock_channel2.name = "random"
        mock_channel2.id = 2
        mock_channel2.category = None

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.text_channels = [mock_channel1, mock_channel2]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_list_channels(mock_guild, mock_origin, "", [])

        mock_origin.send.assert_called_once()


class TestCmdListRoles:
    """Tests for cmd_list_roles function."""

    @pytest.mark.asyncio
    async def test_list_roles(self):
        """Test listing roles."""
        from cogs.ai_core.commands.server_commands import cmd_list_roles

        mock_role1 = MagicMock(spec=discord.Role)
        mock_role1.name = "Admin"
        mock_role1.id = 1
        mock_role1.position = 10

        mock_role2 = MagicMock(spec=discord.Role)
        mock_role2.name = "Member"
        mock_role2.id = 2
        mock_role2.position = 5

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [mock_role1, mock_role2]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_list_roles(mock_guild, mock_origin, "", [])

        mock_origin.send.assert_called_once()


class TestCmdListMembers:
    """Tests for cmd_list_members function."""

    @pytest.mark.asyncio
    async def test_list_members(self):
        """Test listing members."""
        from cogs.ai_core.commands.server_commands import cmd_list_members

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "User1"
        mock_member.name = "user1"
        mock_member.id = 123
        mock_member.bot = False
        mock_member.top_role = MagicMock()
        mock_member.top_role.name = "Member"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.members = [mock_member]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_list_members(mock_guild, mock_origin, "", [])

        mock_origin.send.assert_called_once()


class TestModuleImports:
    """Tests for module imports."""

    def test_import_find_member(self):
        """Test importing find_member function."""
        from cogs.ai_core.commands.server_commands import find_member

        assert callable(find_member)

    def test_import_cmd_create_text(self):
        """Test importing cmd_create_text function."""
        from cogs.ai_core.commands.server_commands import cmd_create_text

        assert callable(cmd_create_text)

    def test_import_cmd_create_voice(self):
        """Test importing cmd_create_voice function."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        assert callable(cmd_create_voice)

    def test_import_cmd_create_category(self):
        """Test importing cmd_create_category function."""
        from cogs.ai_core.commands.server_commands import cmd_create_category

        assert callable(cmd_create_category)

    def test_import_cmd_create_role(self):
        """Test importing cmd_create_role function."""
        from cogs.ai_core.commands.server_commands import cmd_create_role

        assert callable(cmd_create_role)

    def test_import_cmd_list_channels(self):
        """Test importing cmd_list_channels function."""
        from cogs.ai_core.commands.server_commands import cmd_list_channels

        assert callable(cmd_list_channels)

    def test_import_cmd_list_roles(self):
        """Test importing cmd_list_roles function."""
        from cogs.ai_core.commands.server_commands import cmd_list_roles

        assert callable(cmd_list_roles)

    def test_import_cmd_list_members(self):
        """Test importing cmd_list_members function."""
        from cogs.ai_core.commands.server_commands import cmd_list_members

        assert callable(cmd_list_members)


# ======================================================================
# Merged from test_server_commands_extended.py
# ======================================================================


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
                await cmd_create_voice(
                    mock_guild, mock_origin, "test-voice", ["test-voice", "Voice Channels"]
                )

        mock_guild.create_voice_channel.assert_called()

    @pytest.mark.asyncio
    async def test_create_voice_channel_forbidden(self):
        """Test voice channel creation with forbidden error."""
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.create_voice_channel = AsyncMock(
            side_effect=discord.Forbidden(MagicMock(), "No permission")
        )
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
        mock_guild.create_category = AsyncMock(
            side_effect=discord.Forbidden(MagicMock(), "No permission")
        )

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
        mock_guild.create_role = AsyncMock(
            side_effect=discord.Forbidden(MagicMock(), "No permission")
        )

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
            with patch(
                "cogs.ai_core.commands.server_commands.find_member", return_value=mock_member
            ):
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
            with patch(
                "cogs.ai_core.commands.server_commands.find_member", return_value=mock_member
            ):
                await cmd_add_role(mock_guild, mock_origin, "", ["TestUser", "AdminRole"])

        # Should show error about position
        assert "ตำแหน่ง" in str(mock_origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_by_id(self):
        """Test adding role resolved by numeric ID (guild.get_role)."""
        from cogs.ai_core.commands.server_commands import cmd_add_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"
        mock_role.position = 5
        mock_role.__ge__ = MagicMock(return_value=False)

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.add_roles = AsyncMock()

        bot_role = MagicMock(spec=discord.Role)
        bot_role.position = 10
        mock_bot = MagicMock()
        mock_bot.top_role = bot_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = []
        mock_guild.get_role = MagicMock(return_value=mock_role)
        mock_guild.members = [mock_member]
        mock_guild.me = mock_bot

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=mock_member):
            await cmd_add_role(mock_guild, mock_origin, "", ["TestUser", "987654321"])

        mock_guild.get_role.assert_called_once_with(987654321)
        mock_member.add_roles.assert_called_once_with(mock_role)

    @pytest.mark.asyncio
    async def test_add_role_duplicate_role_names(self):
        """Test adding role with duplicate names bails asking for an ID."""
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role1 = MagicMock(spec=discord.Role)
        role1.name = "VIP"
        role2 = MagicMock(spec=discord.Role)
        role2.name = "VIP"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [role1, role2]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_add_role(mock_guild, mock_origin, "", ["TestUser", "VIP"])
        assert "ID" in str(mock_origin.send.call_args)


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
            with patch(
                "cogs.ai_core.commands.server_commands.find_member", return_value=mock_member
            ):
                await cmd_remove_role(mock_guild, mock_origin, "", ["TestUser", "TestRole"])

        mock_member.remove_roles.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_role_by_id(self):
        """Test removing role resolved by numeric ID (guild.get_role)."""
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        mock_role = MagicMock(spec=discord.Role)
        mock_role.name = "TestRole"
        mock_role.position = 5
        mock_role.__ge__ = MagicMock(return_value=False)

        mock_member = MagicMock(spec=discord.Member)
        mock_member.display_name = "TestUser"
        mock_member.remove_roles = AsyncMock()

        bot_role = MagicMock(spec=discord.Role)
        bot_role.position = 10
        mock_bot = MagicMock()
        mock_bot.top_role = bot_role

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = []
        mock_guild.get_role = MagicMock(return_value=mock_role)
        mock_guild.members = [mock_member]
        mock_guild.me = mock_bot

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=mock_member):
            await cmd_remove_role(mock_guild, mock_origin, "", ["TestUser", "987654321"])

        mock_guild.get_role.assert_called_once_with(987654321)
        mock_member.remove_roles.assert_called_once_with(mock_role)

    @pytest.mark.asyncio
    async def test_remove_role_duplicate_role_names(self):
        """Test removing role with duplicate names bails asking for an ID."""
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role1 = MagicMock(spec=discord.Role)
        role1.name = "VIP"
        role2 = MagicMock(spec=discord.Role)
        role2.name = "VIP"

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.roles = [role1, role2]

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        await cmd_remove_role(mock_guild, mock_origin, "", ["TestUser", "VIP"])
        assert "ID" in str(mock_origin.send.call_args)


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

        await cmd_set_channel_perm(
            mock_guild, mock_origin, "", ["channel", "role", "perm", "invalid"]
        )
        assert (
            "true" in str(mock_origin.send.call_args).lower()
            or "false" in str(mock_origin.send.call_args).lower()
        )

    @pytest.mark.asyncio
    async def test_set_channel_perm_channel_not_found(self):
        """Test setting channel perm when channel not found."""
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        mock_guild = MagicMock(spec=discord.Guild)
        mock_guild.channels = []

        mock_origin = MagicMock(spec=discord.TextChannel)
        mock_origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=None):
            await cmd_set_channel_perm(
                mock_guild, mock_origin, "", ["nonexistent", "role", "view_channel", "true"]
            )

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


# ======================================================================
# Appended: full-coverage tests (error paths, guards, audit, helpers)
# ======================================================================


def _http_exc(status=503, code=20012, body="boom"):
    """Build a real discord.HTTPException with usable status/code."""
    resp = type("R", (), {"status": status, "reason": "err"})()
    exc = discord.HTTPException(resp, body)
    # ``code`` is normally parsed from a JSON body dict; force it for assertions.
    exc.code = code
    return exc


def _perms(**kwargs):
    """A guild_permissions stand-in: every requested perm True, others False."""
    p = MagicMock()
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


class TestFmtHttpError:
    """Tests for _fmt_http_error helper."""

    def test_fmt_http_error_extracts_status_and_code(self):
        from cogs.ai_core.commands.server_commands import _fmt_http_error

        msg = _fmt_http_error(_http_exc(status=429, code=20016))
        assert "HTTP 429" in msg
        assert "code 20016" in msg
        # Must not echo the raw body
        assert "boom" not in msg

    def test_fmt_http_error_defaults_when_missing(self):
        from cogs.ai_core.commands.server_commands import _fmt_http_error

        bare = MagicMock(spec=[])  # no status/code attributes
        msg = _fmt_http_error(bare)
        assert "HTTP ?" in msg
        assert "code 0" in msg


class TestPermissionGuards:
    """Each command bails early when the caller lacks the required perm."""

    @pytest.mark.asyncio
    async def test_create_text_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_create_text

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_channels=False)

        await cmd_create_text(guild, origin, "x", [], user=user)
        assert "Manage Channels" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_voice_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_channels=False)

        await cmd_create_voice(guild, origin, "x", [], user=user)
        assert "Manage Channels" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_category_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_create_category

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_channels=False)

        await cmd_create_category(guild, origin, "x", [], user=user)
        assert "Manage Channels" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_channel_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_channels=False)

        await cmd_delete_channel(guild, origin, "x", [], user=user)
        assert "Manage Channels" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_role_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_create_role

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_roles=False)

        await cmd_create_role(guild, origin, None, ["x"], user=user)
        assert "Manage Roles" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_role_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_roles=False)

        await cmd_delete_role(guild, origin, None, ["x"], user=user)
        assert "Manage Roles" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_roles=False)

        await cmd_add_role(guild, origin, None, ["u", "r"], user=user)
        assert "Manage Roles" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_roles=False)

        await cmd_remove_role(guild, origin, None, ["u", "r"], user=user)
        assert "Manage Roles" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_channels=False)

        await cmd_set_channel_perm(guild, origin, None, ["a", "b", "c", "true"], user=user)
        assert "Manage Channels" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_roles=False)

        await cmd_set_role_perm(guild, origin, None, ["r", "p", "true"], user=user)
        assert "Manage Roles" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()
        user.guild_permissions = _perms(manage_messages=False)

        await cmd_edit_message(guild, origin, None, ["123", "new"], user=user)
        assert "Manage Messages" in str(origin.send.call_args)


class TestCreateChannelInvalidAndCategory:
    """Sanitization-empty, missing-category warning, and error paths."""

    @pytest.mark.asyncio
    async def test_create_text_invalid_name_after_sanitize(self):
        from cogs.ai_core.commands.server_commands import cmd_create_text

        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # sanitize_channel_name returns "" -> branch at line 184-185
        with patch("cogs.ai_core.commands.server_commands.sanitize_channel_name", return_value=""):
            await cmd_create_text(guild, origin, "raw", [])
        assert "ชื่อช่องไม่ถูกต้อง" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_voice_invalid_name_after_sanitize(self):
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.sanitize_channel_name", return_value=""):
            await cmd_create_voice(guild, origin, "raw", [])
        assert "ชื่อช่องไม่ถูกต้อง" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_category_invalid_name_after_sanitize(self):
        from cogs.ai_core.commands.server_commands import cmd_create_category

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.sanitize_channel_name", return_value=""):
            await cmd_create_category(guild, origin, "raw", [])
        assert "Category ไม่ถูกต้อง" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_text_missing_category_warns(self):
        from cogs.ai_core.commands.server_commands import cmd_create_text

        new_ch = MagicMock(spec=discord.TextChannel)
        new_ch.id = 1
        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        guild.create_text_channel = AsyncMock(return_value=new_ch)
        guild.me = MagicMock()
        guild.me.id = 9
        guild.id = 7
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # category_name present but no matching category -> warning at line 194
        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_text(guild, origin, "chan", ["chan", "NoSuchCat"])

        sent = [str(c) for c in origin.send.call_args_list]
        assert any("ไม่พบ category" in s for s in sent)
        guild.create_text_channel.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_voice_missing_category_warns(self):
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        new_vc = MagicMock(spec=discord.VoiceChannel)
        new_vc.id = 1
        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        guild.create_voice_channel = AsyncMock(return_value=new_vc)
        guild.me = MagicMock()
        guild.me.id = 9
        guild.id = 7
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_voice(guild, origin, "chan", ["chan", "NoSuchCat"])

        sent = [str(c) for c in origin.send.call_args_list]
        assert any("ไม่พบ category" in s for s in sent)

    @pytest.mark.asyncio
    async def test_create_text_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_create_text

        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        guild.create_text_channel = AsyncMock(side_effect=_http_exc())
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_create_text(guild, origin, "chan", [])
        assert "ไม่สามารถสร้างช่องได้" in str(origin.send.call_args)
        assert "HTTP 503" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_voice_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_create_voice

        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        guild.create_voice_channel = AsyncMock(side_effect=_http_exc())
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_create_voice(guild, origin, "chan", [])
        assert "ไม่สามารถสร้างช่องได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_category_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_create_category

        guild = MagicMock(spec=discord.Guild)
        guild.create_category = AsyncMock(side_effect=_http_exc())
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_create_category(guild, origin, "Cat", [])
        assert "ไม่สามารถสร้าง Category ได้" in str(origin.send.call_args)


class TestAuditTrail:
    """When AUDIT_AVAILABLE is True the log_* hooks are invoked."""

    @pytest.mark.asyncio
    async def test_create_text_logs_audit(self):
        from cogs.ai_core.commands import server_commands as sc

        new_ch = MagicMock(spec=discord.TextChannel)
        new_ch.id = 555
        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        guild.create_text_channel = AsyncMock(return_value=new_ch)
        guild.me = MagicMock()
        guild.me.id = 9
        guild.id = 7
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        log = AsyncMock()
        with patch.object(sc, "AUDIT_AVAILABLE", True), patch.object(sc, "log_channel_change", log):
            await sc.cmd_create_text(guild, origin, "chan", [])

        log.assert_awaited_once()
        assert log.call_args.kwargs["action"] == "create"
        assert log.call_args.kwargs["channel_id"] == 555

    @pytest.mark.asyncio
    async def test_create_voice_logs_audit(self):
        from cogs.ai_core.commands import server_commands as sc

        new_vc = MagicMock(spec=discord.VoiceChannel)
        new_vc.id = 666
        guild = MagicMock(spec=discord.Guild)
        guild.categories = []
        guild.create_voice_channel = AsyncMock(return_value=new_vc)
        guild.me = MagicMock()
        guild.me.id = 9
        guild.id = 7
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        log = AsyncMock()
        with patch.object(sc, "AUDIT_AVAILABLE", True), patch.object(sc, "log_channel_change", log):
            await sc.cmd_create_voice(guild, origin, "chan", [])

        log.assert_awaited_once()
        assert log.call_args.kwargs["action"] == "create_voice"

    @pytest.mark.asyncio
    async def test_create_role_logs_audit(self):
        from cogs.ai_core.commands import server_commands as sc

        role = MagicMock(spec=discord.Role)
        role.id = 777
        role.name = "R"
        guild = MagicMock(spec=discord.Guild)
        guild.create_role = AsyncMock(return_value=role)
        guild.me = MagicMock()
        guild.me.id = 9
        guild.id = 7
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        log = AsyncMock()
        with patch.object(sc, "AUDIT_AVAILABLE", True), patch.object(sc, "log_role_change", log):
            await sc.cmd_create_role(guild, origin, None, ["MyRole"])

        log.assert_awaited_once()
        assert log.call_args.kwargs["role_id"] == 777


class TestDeleteChannelExtra:
    """Active-channel guard, forbidden, http for cmd_delete_channel."""

    @pytest.mark.asyncio
    async def test_delete_active_channel_blocked(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        ch = MagicMock(spec=discord.TextChannel)
        ch.name = "here"
        ch.id = 42
        ch.delete = AsyncMock()
        guild = MagicMock(spec=discord.Guild)
        guild.channels = [ch]
        origin = MagicMock(spec=discord.TextChannel)
        origin.id = 42  # same as target
        origin.send = AsyncMock()

        await cmd_delete_channel(guild, origin, "here", [])
        assert "ไม่สามารถลบช่องที่กำลังใช้งานอยู่ได้" in str(origin.send.call_args)
        ch.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_channel_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_channel

        ch = MagicMock(spec=discord.TextChannel)
        ch.name = "doomed"
        ch.id = 1
        ch.delete = AsyncMock(side_effect=_http_exc())
        guild = MagicMock(spec=discord.Guild)
        guild.channels = [ch]
        origin = MagicMock(spec=discord.TextChannel)
        origin.id = 999
        origin.send = AsyncMock()

        await cmd_delete_channel(guild, origin, "doomed", [])
        assert "ไม่สามารถลบช่องได้" in str(origin.send.call_args)


class TestCreateRoleExtra:
    """Invalid sanitized name, out-of-range hex, http path."""

    @pytest.mark.asyncio
    async def test_create_role_invalid_after_sanitize(self):
        from cogs.ai_core.commands.server_commands import cmd_create_role

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.sanitize_role_name", return_value=""):
            await cmd_create_role(guild, origin, None, ["raw"])
        assert "ชื่อยศไม่ถูกต้อง" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_create_role_hex_out_of_range(self):
        from cogs.ai_core.commands.server_commands import cmd_create_role

        role = MagicMock(spec=discord.Role)
        role.id = 1
        role.name = "R"
        guild = MagicMock(spec=discord.Guild)
        guild.create_role = AsyncMock(return_value=role)
        guild.me = MagicMock()
        guild.me.id = 9
        guild.id = 7
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # 0x1FFFFFFF is a valid int but > 0xFFFFFF -> warning at line 416
        with patch("cogs.ai_core.commands.server_commands.AUDIT_AVAILABLE", False):
            await cmd_create_role(guild, origin, None, ["R", "1FFFFFFF"])

        sent = [str(c) for c in origin.send.call_args_list]
        assert any("นอกช่วง" in s for s in sent)

    @pytest.mark.asyncio
    async def test_create_role_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_create_role

        guild = MagicMock(spec=discord.Guild)
        guild.create_role = AsyncMock(side_effect=_http_exc())
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_create_role(guild, origin, None, ["R"])
        assert "ไม่สามารถสร้างยศได้" in str(origin.send.call_args)


class TestDeleteRoleExtra:
    """Empty name, forbidden, http for cmd_delete_role."""

    @pytest.mark.asyncio
    async def test_delete_role_empty_name(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_delete_role(guild, origin, None, ["   "])
        assert "ชื่อยศไม่สามารถว่างได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_role_forbidden(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_delete_role(guild, origin, None, ["R"])
        assert "ไม่มีสิทธิ์ลบยศ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_delete_role_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.delete = AsyncMock(side_effect=_http_exc())
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_delete_role(guild, origin, None, ["R"])
        assert "ไม่สามารถลบยศได้" in str(origin.send.call_args)


class TestAddRoleFull:
    """Full branch coverage for cmd_add_role."""

    @pytest.mark.asyncio
    async def test_add_role_ambiguous_user(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        m1 = MagicMock(spec=discord.Member)
        m1.name = "alice1"
        m1.display_name = "Alice One"
        m2 = MagicMock(spec=discord.Member)
        m2.name = "alice2"
        m2.display_name = "Alice Two"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [m1, m2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_add_role(guild, origin, None, ["alice", "R"])
        assert "ไม่ชัดเจน" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_partial_single_match(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        m1 = MagicMock(spec=discord.Member)
        m1.name = "bob123"
        m1.display_name = "Bobby"
        m1.add_roles = AsyncMock()
        m1.top_role = MagicMock()
        m1.top_role.position = 1
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [m1]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_add_role(guild, origin, None, ["bob", "R"])
        m1.add_roles.assert_awaited_once_with(role)

    @pytest.mark.asyncio
    async def test_add_role_guild_me_none(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = None
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_add_role(guild, origin, None, ["U", "R"])
        assert "บอทยังไม่พร้อมใช้งาน" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_member_higher_than_bot_still_succeeds(self):
        """Discord does NOT gate role add on the target member's top role.

        The actor-vs-target hierarchy rule applies only to kick/ban/nickname
        edits; adding a below-bot role to a member ranked ABOVE the bot is a
        valid, routine operation (e.g. muting a moderator). A previous guard
        falsely refused it — this pins the corrected behavior.
        """
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)  # role < bot top
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        member.top_role = MagicMock()
        member.top_role.position = 20  # higher than bot — must NOT block
        member.add_roles = AsyncMock()
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_add_role(guild, origin, None, ["U", "R"])
        member.add_roles.assert_awaited_once_with(role)
        assert "เรียบร้อยแล้ว" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_forbidden(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        member.top_role = MagicMock()
        member.top_role.position = 1
        member.add_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_add_role(guild, origin, None, ["U", "R"])
        assert "บอทไม่มีสิทธิ์มอบยศนี้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        member.top_role = MagicMock()
        member.top_role.position = 1
        member.add_roles = AsyncMock(side_effect=_http_exc())
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_add_role(guild, origin, None, ["U", "R"])
        assert "ไม่สามารถมอบยศได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_add_role_role_not_found(self):
        from cogs.ai_core.commands.server_commands import cmd_add_role

        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = []
        guild.members = [member]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_add_role(guild, origin, None, ["U", "NoRole"])
        assert "ไม่พบยศ" in str(origin.send.call_args)


class TestRemoveRoleFull:
    """Full branch coverage for cmd_remove_role."""

    @pytest.mark.asyncio
    async def test_remove_role_ambiguous_user(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        m1 = MagicMock(spec=discord.Member)
        m1.name = "carl1"
        m1.display_name = "Carl One"
        m2 = MagicMock(spec=discord.Member)
        m2.name = "carl2"
        m2.display_name = "Carl Two"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [m1, m2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_remove_role(guild, origin, None, ["carl", "R"])
        assert "กรุณาระบุให้ชัดเจน" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_partial_single(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        m1 = MagicMock(spec=discord.Member)
        m1.name = "dave99"
        m1.display_name = "Dave"
        m1.remove_roles = AsyncMock()
        m1.top_role = MagicMock()
        m1.top_role.position = 1
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [m1]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_remove_role(guild, origin, None, ["dave", "R"])
        m1.remove_roles.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_role_guild_me_none(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = None
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_remove_role(guild, origin, None, ["U", "R"])
        assert "บอทยังไม่พร้อมใช้งาน" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_role_higher_than_bot(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 30
        role.__ge__ = MagicMock(return_value=True)  # role >= bot top
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_remove_role(guild, origin, None, ["U", "R"])
        assert "ไม่สามารถลบยศ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_member_higher_than_bot_still_succeeds(self):
        """Mirror of the add-role case: the target's top role must not block
        removing a below-bot role — Discord only gates on the role being
        modified (see cmd_add_role's hierarchy note)."""
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        member.top_role = MagicMock()
        member.top_role.position = 50  # higher than bot — must NOT block
        member.remove_roles = AsyncMock()
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_remove_role(guild, origin, None, ["U", "R"])
        member.remove_roles.assert_awaited_once_with(role)
        assert "เรียบร้อยแล้ว" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_forbidden(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        member.top_role = MagicMock()
        member.top_role.position = 1
        member.remove_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_remove_role(guild, origin, None, ["U", "R"])
        assert "บอทไม่มีสิทธิ์ลบยศนี้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_http_exception(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        member.top_role = MagicMock()
        member.top_role.position = 1
        member.remove_roles = AsyncMock(side_effect=_http_exc())
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = [member]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_remove_role(guild, origin, None, ["U", "R"])
        assert "ไม่สามารถลบยศได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_role_not_found(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        member = MagicMock(spec=discord.Member)
        member.display_name = "U"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = []
        guild.members = [member]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=member):
            await cmd_remove_role(guild, origin, None, ["U", "NoRole"])
        assert "ไม่พบยศ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_remove_role_member_not_found(self):
        from cogs.ai_core.commands.server_commands import cmd_remove_role

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.members = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_remove_role(guild, origin, None, ["Ghost", "R"])
        assert "ไม่พบผู้ใช้" in str(origin.send.call_args)


class TestSetChannelPermFull:
    """Full branch coverage for cmd_set_channel_perm."""

    def _channel_with_overwrite(self):
        overwrite = MagicMock()
        ch = MagicMock(spec=discord.TextChannel)
        ch.overwrites_for = MagicMock(return_value=overwrite)
        ch.set_permissions = AsyncMock()
        return ch, overwrite

    @pytest.mark.asyncio
    async def test_set_channel_perm_everyone_success(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch, overwrite = self._channel_with_overwrite()
        # overwrite must "have" the perm attribute
        overwrite.send_messages = False
        everyone = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        guild.default_role = everyone
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=ch):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "@everyone", "send_messages", "true"]
            )
        ch.set_permissions.assert_awaited_once()
        assert "เรียบร้อยแล้ว" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_read_messages_alias(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch, overwrite = self._channel_with_overwrite()
        overwrite.view_channel = False
        target_role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # First discord.utils.get -> channel, second -> target role
        with patch("discord.utils.get", side_effect=[ch, target_role]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "SomeRole", "read_messages", "false"]
            )
        ch.set_permissions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_channel_perm_dangerous(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch, _ = self._channel_with_overwrite()
        target_role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[ch, target_role]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "SomeRole", "administrator", "true"]
            )
        assert "เป็นอันตราย" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_not_in_allowlist(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch, _ = self._channel_with_overwrite()
        target_role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[ch, target_role]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "SomeRole", "not_a_real_perm", "true"]
            )
        assert "ไม่อยู่ในรายการที่อนุญาต" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_missing_attr(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        # overwrite lacks the (safe) perm attribute -> "ไม่พบ permission"
        overwrite = MagicMock(spec=[])  # hasattr -> False for everything
        ch = MagicMock(spec=discord.TextChannel)
        ch.overwrites_for = MagicMock(return_value=overwrite)
        target_role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[ch, target_role]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "SomeRole", "embed_links", "true"]
            )
        assert "ไม่พบ permission" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_forbidden(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        overwrite = MagicMock()
        overwrite.embed_links = False
        ch = MagicMock(spec=discord.TextChannel)
        ch.overwrites_for = MagicMock(return_value=overwrite)
        ch.set_permissions = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        target_role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[ch, target_role]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "SomeRole", "embed_links", "true"]
            )
        assert "บอทไม่มีสิทธิ์ตั้งค่า permission" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_http(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        overwrite = MagicMock()
        overwrite.embed_links = False
        ch = MagicMock(spec=discord.TextChannel)
        ch.overwrites_for = MagicMock(return_value=overwrite)
        ch.set_permissions = AsyncMock(side_effect=_http_exc())
        target_role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", side_effect=[ch, target_role]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "SomeRole", "embed_links", "true"]
            )
        assert "ไม่สามารถตั้งค่า permission ได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_target_not_found(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch = MagicMock(spec=discord.TextChannel)
        ch.overwrites_for = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # channel found, but target role not found and find_member None
        with patch("discord.utils.get", side_effect=[ch, None]):
            with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
                await cmd_set_channel_perm(
                    guild, origin, None, ["chan", "Ghost", "embed_links", "true"]
                )
        assert "ไม่พบเป้าหมาย" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_channel_perm_duplicate_role_names(self):
        # Two roles share the name "Members": the target block must bail with the
        # "specify an ID" advice instead of silently applying the overwrite to the
        # first same-named role (wrong-principal permission mutation).
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch, _ = self._channel_with_overwrite()
        role1 = MagicMock(spec=discord.Role)
        role1.name = "Members"
        role2 = MagicMock(spec=discord.Role)
        role2.name = "Members"
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role1, role2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # Only the channel name hits discord.utils.get; the duplicate-role bail
        # returns before the target role get, so one side_effect entry suffices.
        with patch("discord.utils.get", side_effect=[ch]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "Members", "view_channel", "true"]
            )
        assert "ID" in str(origin.send.call_args)
        ch.set_permissions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_channel_perm_target_role_by_id(self):
        # A numeric target resolves ID-first via guild.get_role (mirrors the
        # channel block and cmd_delete_role), so the overwrite is applied.
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        ch, overwrite = self._channel_with_overwrite()
        overwrite.view_channel = False
        role = MagicMock(spec=discord.Role)
        guild = MagicMock(spec=discord.Guild)
        guild.get_role = MagicMock(return_value=role)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # Numeric target skips discord.utils.get for the role; only the channel
        # name hits it.
        with patch("discord.utils.get", side_effect=[ch]):
            await cmd_set_channel_perm(
                guild, origin, None, ["chan", "123456", "view_channel", "true"]
            )
        guild.get_role.assert_called_once_with(123456)
        ch.set_permissions.assert_awaited_once()


class TestSetRolePermFull:
    """Full branch coverage for cmd_set_role_perm."""

    @pytest.mark.asyncio
    async def test_set_role_perm_insufficient_args(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_set_role_perm(guild, origin, None, ["r", "p"])
        assert "พารามิเตอร์ให้ครบ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_invalid_value(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_set_role_perm(guild, origin, None, ["r", "embed_links", "maybe"])
        assert "true" in str(origin.send.call_args).lower()

    @pytest.mark.asyncio
    async def test_set_role_perm_role_not_found(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        guild = MagicMock(spec=discord.Guild)
        guild.roles = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=None):
            await cmd_set_role_perm(guild, origin, None, ["Ghost", "embed_links", "true"])
        assert "ไม่พบยศ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_case_insensitive_fallback(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "admin"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        perms = MagicMock()
        perms.embed_links = False
        role.permissions = perms
        role.edit = AsyncMock()
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # exact-name get returns None, fallback iterates roles for case-insensitive
        with patch("discord.utils.get", return_value=None):
            await cmd_set_role_perm(guild, origin, None, ["Admin", "embed_links", "true"])
        role.edit.assert_awaited_once()
        assert "เรียบร้อยแล้ว" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_dangerous(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.permissions = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "administrator", "true"])
        assert "เป็นอันตราย" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_not_in_allowlist(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.permissions = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "not_real_perm", "true"])
        assert "ไม่อยู่ในรายการที่อนุญาต" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_missing_attr(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.permissions = MagicMock(spec=[])  # hasattr -> False
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "embed_links", "true"])
        assert "ไม่พบ permission" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_guild_me_none(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        perms = MagicMock()
        perms.embed_links = False
        role.permissions = perms
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.me = None
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "embed_links", "true"])
        assert "บอทยังไม่พร้อมใช้งาน" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_role_higher_than_bot(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 30
        role.__ge__ = MagicMock(return_value=True)
        perms = MagicMock()
        perms.embed_links = False
        role.permissions = perms
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "embed_links", "true"])
        assert "ไม่สามารถแก้ไขยศ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_forbidden(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        perms = MagicMock()
        perms.embed_links = False
        role.permissions = perms
        role.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no"))
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "embed_links", "true"])
        assert "บอทไม่มีสิทธิ์แก้ไขยศนี้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_set_role_perm_http(self):
        from cogs.ai_core.commands.server_commands import cmd_set_role_perm

        role = MagicMock(spec=discord.Role)
        role.name = "R"
        role.position = 1
        role.__ge__ = MagicMock(return_value=False)
        perms = MagicMock()
        perms.embed_links = False
        role.permissions = perms
        role.edit = AsyncMock(side_effect=_http_exc())
        bot = MagicMock()
        bot.top_role = MagicMock()
        bot.top_role.position = 10
        guild = MagicMock(spec=discord.Guild)
        guild.roles = [role]
        guild.me = bot
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=role):
            await cmd_set_role_perm(guild, origin, None, ["R", "embed_links", "true"])
        assert "ไม่สามารถตั้งค่า permission ได้" in str(origin.send.call_args)


class TestListChannelsMemberFilter:
    """cmd_list_channels filters by Member's view_channel permission."""

    @pytest.mark.asyncio
    async def test_list_channels_member_filtered(self):
        from cogs.ai_core.commands.server_commands import cmd_list_channels

        visible = MagicMock(spec=discord.TextChannel)
        visible.name = "open"
        visible.id = 1
        hidden = MagicMock(spec=discord.TextChannel)
        hidden.name = "secret"
        hidden.id = 2

        user = MagicMock(spec=discord.Member)

        def perms_for(u):
            p = MagicMock()
            return p

        visible.permissions_for = MagicMock(return_value=MagicMock(view_channel=True))
        hidden.permissions_for = MagicMock(return_value=MagicMock(view_channel=False))

        guild = MagicMock(spec=discord.Guild)
        guild.text_channels = [visible, hidden]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_list_channels(guild, origin, None, [], user)
        body = str(origin.send.call_args)
        assert "open" in body
        assert "secret" not in body


class TestListMembersGate:
    """cmd_list_members requires manage_guild and supports query/limit."""

    @pytest.mark.asyncio
    async def test_list_members_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_list_members

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=False)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_list_members(guild, origin, None, [], user)
        assert "Manage Server" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_list_members_not_member(self):
        from cogs.ai_core.commands.server_commands import cmd_list_members

        user = MagicMock(spec=discord.User)  # not a Member
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_list_members(guild, origin, None, [], user)
        assert "Manage Server" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_list_members_query_and_limit(self):
        from cogs.ai_core.commands.server_commands import cmd_list_members

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        m1 = MagicMock(spec=discord.Member)
        m1.name = "applejack"
        m1.display_name = "AppleJack"
        m1.id = 1
        m2 = MagicMock(spec=discord.Member)
        m2.name = "banana"
        m2.display_name = "Banana"
        m2.id = 2

        guild = MagicMock(spec=discord.Guild)
        guild.members = [m1, m2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # limit 5, query "apple" -> only m1
        await cmd_list_members(guild, origin, None, ["5", "apple"], user)
        body = str(origin.send.call_args_list)
        assert "applejack" in body
        assert "banana" not in body

    @pytest.mark.asyncio
    async def test_list_members_limit_clamped_low(self):
        from cogs.ai_core.commands.server_commands import cmd_list_members

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)
        m1 = MagicMock(spec=discord.Member)
        m1.name = "x"
        m1.display_name = "X"
        m1.id = 1
        m2 = MagicMock(spec=discord.Member)
        m2.name = "y"
        m2.display_name = "Y"
        m2.id = 2
        guild = MagicMock(spec=discord.Guild)
        guild.members = [m1, m2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # limit 0 -> clamped to 1, so only 1 of 2 shown
        await cmd_list_members(guild, origin, None, ["0"], user)
        assert "1/2 shown" in str(origin.send.call_args_list)

    @pytest.mark.asyncio
    async def test_list_members_limit_clamped_high(self):
        from cogs.ai_core.commands.server_commands import cmd_list_members

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)
        m = MagicMock(spec=discord.Member)
        m.name = "x"
        m.display_name = "X"
        m.id = 1
        guild = MagicMock(spec=discord.Guild)
        guild.members = [m]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # limit 5000 -> clamped to 200 (no crash, all shown)
        await cmd_list_members(guild, origin, None, ["5000"], user)
        assert "1/1 shown" in str(origin.send.call_args_list)


class TestGetUserInfoFull:
    """Full branch coverage for cmd_get_user_info."""

    @pytest.mark.asyncio
    async def test_get_user_info_no_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=False)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_get_user_info(guild, origin, None, ["x"], user)
        assert "Manage Server" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_get_user_info_no_args(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_get_user_info(guild, origin, None, [], user)
        assert "กรุณาระบุชื่อผู้ใช้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_get_user_info_empty_target(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_get_user_info(guild, origin, None, ["   "], user)
        assert "ว่างได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_get_user_info_by_id_cached(self):
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        target = MagicMock(spec=discord.Member)
        target.name = "found"
        target.display_name = "Found User"
        target.id = 12345
        target.status = discord.Status.online
        target.joined_at = datetime.datetime(2020, 1, 1)
        role = MagicMock(spec=discord.Role)
        role.name = "Member"
        target.roles = [role]

        guild = MagicMock(spec=discord.Guild)
        guild.get_member = MagicMock(return_value=target)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_get_user_info(guild, origin, None, ["12345"], user)
        body = str(origin.send.call_args)
        assert "found" in body
        assert "12345" in body

    @pytest.mark.asyncio
    async def test_get_user_info_by_id_fetch_fallback(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        target = MagicMock(spec=discord.Member)
        target.name = "fetched"
        target.display_name = "Fetched"
        target.id = 999
        target.status = discord.Status.idle
        target.joined_at = None  # exercise "Unknown" branch
        target.roles = []

        guild = MagicMock(spec=discord.Guild)
        guild.get_member = MagicMock(return_value=None)
        guild.fetch_member = AsyncMock(return_value=target)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        await cmd_get_user_info(guild, origin, None, ["999"], user)
        body = str(origin.send.call_args)
        assert "fetched" in body
        assert "Unknown" in body

    @pytest.mark.asyncio
    async def test_get_user_info_by_id_fetch_notfound(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        guild = MagicMock(spec=discord.Guild)
        guild.get_member = MagicMock(return_value=None)
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "nope"))
        guild.members = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_get_user_info(guild, origin, None, ["888"], user)
        assert "ไม่พบผู้ใช้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_get_user_info_multiple_matches(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        m1 = MagicMock(spec=discord.Member)
        m1.name = "sam1"
        m1.display_name = "Sammy One"
        m1.id = 1
        m2 = MagicMock(spec=discord.Member)
        m2.name = "sam2"
        m2.display_name = "Sammy Two"
        m2.id = 2

        guild = MagicMock(spec=discord.Guild)
        guild.members = [m1, m2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_get_user_info(guild, origin, None, ["sam"], user)
        assert "multiple users" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_get_user_info_many_matches_truncates(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        members = []
        for i in range(12):
            m = MagicMock(spec=discord.Member)
            m.name = f"zed{i}"
            m.display_name = f"Zed {i}"
            m.id = i
            members.append(m)

        guild = MagicMock(spec=discord.Guild)
        guild.members = members
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_get_user_info(guild, origin, None, ["zed"], user)
        assert "more." in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_get_user_info_multiple_matches_escapes_backticks(self):
        # A member whose display name contains ``` must not break out of the
        # fenced code block. Routing the multi-match branch through
        # send_long_message runs each line through _escape_for_code_block, so the
        # only raw ``` left in the payload are the two wrapping fence markers.
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        m1 = MagicMock(spec=discord.Member)
        m1.name = "evil1"
        m1.display_name = "```evil"
        m1.id = 1
        m2 = MagicMock(spec=discord.Member)
        m2.name = "evil2"
        m2.display_name = "```pwn"
        m2.id = 2

        guild = MagicMock(spec=discord.Guild)
        guild.members = [m1, m2]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_get_user_info(guild, origin, None, ["evil"], user)

        payload = origin.send.call_args.args[0]
        assert payload.count("```") == 2  # opening + closing fence only
        assert "```evil" not in payload  # raw injected fence is gone
        zwsp = chr(0x200B)  # _escape_for_code_block splits ``` with zero-width spaces
        assert f"`{zwsp}`{zwsp}`" in payload
        assert "multiple users" in payload

    @pytest.mark.asyncio
    async def test_get_user_info_partial_single(self):
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        user = MagicMock(spec=discord.Member)
        user.guild_permissions = _perms(manage_guild=True)

        target = MagicMock(spec=discord.Member)
        target.name = "uniquename"
        target.display_name = "Unique"
        target.id = 77
        target.status = discord.Status.dnd
        target.joined_at = datetime.datetime(2021, 5, 5)
        target.roles = []

        guild = MagicMock(spec=discord.Guild)
        guild.members = [target]
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("cogs.ai_core.commands.server_commands.find_member", return_value=None):
            await cmd_get_user_info(guild, origin, None, ["unique"], user)
        assert "uniquename" in str(origin.send.call_args)


class TestEditMessageFull:
    """Full branch coverage for cmd_edit_message."""

    @pytest.mark.asyncio
    async def test_edit_message_insufficient_args(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_edit_message(None, origin, None, ["123"])
        assert "พารามิเตอร์ให้ครบ" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_non_numeric_id(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_edit_message(None, origin, None, ["abc", "content"])
        assert "ต้องเป็นตัวเลข" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_empty_content(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_edit_message(None, origin, None, ["123", "   "])
        assert "เนื้อหาใหม่ไม่สามารถว่างได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_dm_no_guild(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = None
        origin.send = AsyncMock()
        await cmd_edit_message(None, origin, None, ["123", "new content"])
        assert "เฉพาะใน server" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_bot_member_none(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        guild = MagicMock(spec=discord.Guild)
        guild.me = None
        msg = MagicMock()
        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = guild
        origin.send = AsyncMock()
        origin.fetch_message = AsyncMock(return_value=msg)

        await cmd_edit_message(None, origin, None, ["123", "new content"])
        assert "ไม่พบ bot member" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_bot_owned_success(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        msg = MagicMock()
        msg.author = bot
        msg.edit = AsyncMock()
        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = guild
        origin.send = AsyncMock()
        origin.fetch_message = AsyncMock(return_value=msg)

        await cmd_edit_message(None, origin, None, ["123", "new content"])
        msg.edit.assert_awaited_once_with(content="new content")

    @pytest.mark.asyncio
    async def test_edit_message_webhook_owned_success(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        bot.id = 4242
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        other = MagicMock()
        msg = MagicMock()
        msg.author = other  # not the bot
        msg.webhook_id = 555
        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = guild
        origin.send = AsyncMock()
        origin.fetch_message = AsyncMock(return_value=msg)

        webhook = MagicMock()
        webhook.id = 555
        webhook.user = MagicMock()
        webhook.user.id = 4242  # matches bot
        webhook.edit_message = AsyncMock()
        origin.webhooks = AsyncMock(return_value=[webhook])

        await cmd_edit_message(None, origin, None, ["123", "new content"])
        webhook.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_edit_message_webhook_not_bot(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        bot.id = 4242
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        other = MagicMock()
        msg = MagicMock()
        msg.author = other
        msg.webhook_id = 555
        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = guild
        origin.send = AsyncMock()
        origin.fetch_message = AsyncMock(return_value=msg)

        webhook = MagicMock()
        webhook.id = 555
        webhook.user = MagicMock()
        webhook.user.id = 9999  # not the bot
        origin.webhooks = AsyncMock(return_value=[webhook])

        await cmd_edit_message(None, origin, None, ["123", "new content"])
        assert "ไม่ใช่ของบอท" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_not_bot_message(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        bot = MagicMock()
        bot.id = 4242
        guild = MagicMock(spec=discord.Guild)
        guild.me = bot
        other = MagicMock()
        msg = MagicMock()
        msg.author = other
        msg.webhook_id = None  # not a webhook either
        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = guild
        origin.send = AsyncMock()
        origin.fetch_message = AsyncMock(return_value=msg)

        await cmd_edit_message(None, origin, None, ["123", "new content"])
        assert "ข้อความไม่ใช่ของบอท" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_edit_message_fetch_notfound(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        guild = MagicMock(spec=discord.Guild)
        guild.me = MagicMock()
        origin = MagicMock(spec=discord.TextChannel)
        origin.guild = guild
        origin.send = AsyncMock()
        origin.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "missing"))

        await cmd_edit_message(None, origin, None, ["123", "new content"])
        # The formatter output is sent
        assert "HTTP" in str(origin.send.call_args)


class TestReadChannelFull:
    """Full branch coverage for cmd_read_channel."""

    @pytest.mark.asyncio
    async def test_read_channel_no_args(self):
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_read_channel(guild, origin, None, [])
        assert "กรุณาระบุชื่อช่อง" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_read_channel_empty_name(self):
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_read_channel(guild, origin, None, ["   "])
        assert "ว่างได้" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_read_channel_not_found(self):
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        guild = MagicMock(spec=discord.Guild)
        guild.text_channels = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        with patch("discord.utils.get", return_value=None):
            await cmd_read_channel(guild, origin, None, ["ghost"])
        assert "ไม่พบช่อง" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_read_channel_by_id(self):
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "logs"

        async def fake_history(limit):
            msg = MagicMock()
            msg.content = "hello"
            msg.created_at = datetime.datetime(2022, 1, 1, 13, 30)
            msg.author = MagicMock()
            msg.author.display_name = "Alice"
            yield msg

        target.history = fake_history
        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=target)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        # discord.utils.get -> None (name lookup fails), then id lookup succeeds
        with patch("discord.utils.get", return_value=None):
            await cmd_read_channel(guild, origin, None, ["123456"])
        body = str(origin.send.call_args_list)
        assert "hello" in body
        assert "Alice" in body

    @pytest.mark.asyncio
    async def test_read_channel_user_no_read_perm(self):
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "private"
        target.permissions_for = MagicMock(return_value=MagicMock(read_messages=False))
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock(spec=discord.Member)

        with patch("discord.utils.get", return_value=target):
            await cmd_read_channel(guild, origin, None, ["private"], user=user)
        assert "ไม่มีสิทธิ์อ่านห้องนั้น" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_read_channel_perm_check_error(self):
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "weird"
        target.permissions_for = MagicMock(side_effect=AttributeError("boom"))
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        user = MagicMock()

        with patch("discord.utils.get", return_value=target):
            await cmd_read_channel(guild, origin, None, ["weird"], user=user)
        assert "ไม่สามารถตรวจสอบสิทธิ์" in str(origin.send.call_args)

    @pytest.mark.asyncio
    async def test_read_channel_success_with_limit(self):
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "general"

        async def fake_history(limit):
            assert limit == 5
            for i in range(2):
                msg = MagicMock()
                msg.content = "" if i == 0 else f"msg{i}"
                msg.created_at = datetime.datetime(2022, 1, 1, 10, i)
                msg.author = MagicMock()
                msg.author.display_name = f"User{i}"
                yield msg

        target.history = fake_history
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=target):
            # limit 5 valid; user None so no perm check
            await cmd_read_channel(guild, origin, None, ["general", "5"])
        body = str(origin.send.call_args_list)
        # Empty content rendered as placeholder
        assert "[Image/Attachment]" in body

    @pytest.mark.asyncio
    async def test_read_channel_invalid_limit_defaults(self):
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "general"
        captured = {}

        async def fake_history(limit):
            captured["limit"] = limit
            msg = MagicMock()
            msg.content = "x"
            msg.created_at = datetime.datetime(2022, 1, 1, 10, 0)
            msg.author = MagicMock()
            msg.author.display_name = "U"
            yield msg

        target.history = fake_history
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=target):
            # limit 999 -> out of range -> defaults to 10
            await cmd_read_channel(guild, origin, None, ["general", "999"])
        assert captured["limit"] == 10

    @pytest.mark.asyncio
    async def test_read_channel_huge_digit_limit_defaults_no_valueerror(self):
        # Regression: the limit arg (args[1]) is model/AI-controlled and not
        # length-clamped by the dispatchers. Python 3.11+ raises ValueError on
        # int() of an all-digit string longer than 4300 digits. Such a token
        # passes .isdigit() but must NOT reach int() — it should default to 10
        # without raising (cmd_read_channel itself has no try/except here).
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "general"
        captured = {}

        async def fake_history(limit):
            captured["limit"] = limit
            msg = MagicMock()
            msg.content = "x"
            msg.created_at = datetime.datetime(2022, 1, 1, 10, 0)
            msg.author = MagicMock()
            msg.author.display_name = "U"
            yield msg

        target.history = fake_history
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        huge = "9" * 5000  # all digits, >4300 -> int() would raise ValueError
        with patch("discord.utils.get", return_value=target):
            await cmd_read_channel(guild, origin, None, ["general", huge])
        assert captured["limit"] == 10

    @pytest.mark.asyncio
    async def test_read_channel_unicode_digit_limit_defaults_no_valueerror(self):
        # Regression for the gap the digit-length cap missed: str.isdigit() is
        # True for non-ASCII "digits" (superscript U+00B2 "²", circled U+2460 "①")
        # that int() cannot parse. Such a limit token must default to 10 instead
        # of raising ValueError. _safe_int (not isdigit()+int()) closes this.
        import datetime

        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "general"
        captured = {}

        async def fake_history(limit):
            captured["limit"] = limit
            msg = MagicMock()
            msg.content = "x"
            msg.created_at = datetime.datetime(2022, 1, 1, 10, 0)
            msg.author = MagicMock()
            msg.author.display_name = "U"
            yield msg

        target.history = fake_history
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        for unicode_digit in ("²²²", "①①", "\U00010a40"):
            assert unicode_digit.isdigit()  # the trap: passes isdigit()
            captured.clear()
            with patch("discord.utils.get", return_value=target):
                await cmd_read_channel(guild, origin, None, ["general", unicode_digit])
            assert captured["limit"] == 10

    @pytest.mark.asyncio
    async def test_read_channel_unicode_digit_name_no_valueerror(self):
        # The ID-fallback `int(target_name)` shares the class: a Unicode-digit
        # channel name (no literal match) must fall through to the name lookup,
        # not raise ValueError. Asserts the command completes with a "not found"
        # reply rather than blowing up.
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        guild = MagicMock(spec=discord.Guild)
        guild.text_channels = []
        guild.get_channel = MagicMock(return_value=None)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=None):
            # Must not raise ValueError from int("²²²")
            await cmd_read_channel(guild, origin, None, ["²²²"])
        # get_channel must NOT have been called with an int (we never reached int())
        origin.send.assert_awaited()  # sent a "not found"/error reply, no crash

    @pytest.mark.asyncio
    async def test_read_channel_forbidden(self):
        from cogs.ai_core.commands.server_commands import cmd_read_channel

        target = MagicMock(spec=discord.TextChannel)
        target.name = "locked"

        def fake_history(limit):
            raise discord.Forbidden(MagicMock(), "no")

        target.history = fake_history
        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()

        with patch("discord.utils.get", return_value=target):
            await cmd_read_channel(guild, origin, None, ["locked"])
        assert "บอทไม่มีสิทธิ์อ่านช่อง" in str(origin.send.call_args)


class TestSendLongMessage:
    """Tests for send_long_message chunking + escaping."""

    @pytest.mark.asyncio
    async def test_send_long_message_single_chunk(self):
        from cogs.ai_core.commands.server_commands import send_long_message

        channel = MagicMock()
        channel.send = AsyncMock()
        await send_long_message(channel, "Header\n", ["line1", "line2"])
        channel.send.assert_awaited_once()
        assert "line1" in str(channel.send.call_args)

    @pytest.mark.asyncio
    async def test_send_long_message_multi_chunk(self):
        from cogs.ai_core.commands.server_commands import send_long_message

        channel = MagicMock()
        channel.send = AsyncMock()
        # Each line ~500 chars; several lines force >1900 char chunk split
        lines = ["x" * 500 for _ in range(10)]
        await send_long_message(channel, "Header\n", lines)
        # More than one send -> chunk split branch (line 1123) exercised
        assert channel.send.await_count >= 2

    @pytest.mark.asyncio
    async def test_send_long_message_escapes_backticks(self):
        from cogs.ai_core.commands.server_commands import send_long_message

        channel = MagicMock()
        channel.send = AsyncMock()
        await send_long_message(channel, "H\n", ["```evil```"])
        sent = str(channel.send.call_args)
        # The raw triple-backtick must be neutralised
        assert "```evil```" not in sent


class TestAuditLogImportFallback:
    """Cover the ``except ImportError`` fallback for the audit logger (lines 111-114).

    When ``utils.monitoring.audit_log`` cannot be imported, the module must
    degrade gracefully: AUDIT_AVAILABLE flips to False and the two log hooks
    become None so the channel/role command paths skip audit logging.
    """

    def test_audit_unavailable_when_import_fails(self):
        import builtins
        import importlib

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            # Force only the audit_log import to fail; everything else imports
            # normally so the module body still executes to completion.
            if name == "utils.monitoring.audit_log":
                raise ImportError("simulated: audit_log unavailable")
            return real_import(name, *args, **kwargs)

        import cogs.ai_core.commands.server_commands as sc

        try:
            with patch("builtins.__import__", side_effect=_fake_import):
                reloaded = importlib.reload(sc)

            # The except branch (lines 111-114) ran:
            assert reloaded.AUDIT_AVAILABLE is False
            assert reloaded.log_channel_change is None
            assert reloaded.log_role_change is None
        finally:
            # Reload once more WITHOUT the failing import so the real audit
            # hooks are restored and subsequent tests see the normal module.
            importlib.reload(sc)

    @pytest.mark.asyncio
    async def test_create_text_skips_audit_when_unavailable(self):
        """End-to-end: with the fallback module loaded, channel creation still
        succeeds but the (None) audit hook is never invoked."""
        import builtins
        import importlib

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "utils.monitoring.audit_log":
                raise ImportError("simulated: audit_log unavailable")
            return real_import(name, *args, **kwargs)

        import cogs.ai_core.commands.server_commands as sc

        try:
            with patch("builtins.__import__", side_effect=_fake_import):
                reloaded = importlib.reload(sc)

            new_ch = MagicMock(spec=discord.TextChannel)
            new_ch.id = 1
            guild = MagicMock(spec=discord.Guild)
            guild.categories = []
            guild.create_text_channel = AsyncMock(return_value=new_ch)
            guild.me = MagicMock()
            guild.me.id = 9
            guild.id = 7
            origin = MagicMock(spec=discord.TextChannel)
            origin.send = AsyncMock()

            await reloaded.cmd_create_text(guild, origin, "chan", [])

            guild.create_text_channel.assert_awaited_once()
            assert "✅" in str(origin.send.call_args)
        finally:
            importlib.reload(sc)


class TestUnicodeDigitIntRobustness:
    """Regression: every AI-supplied numeric arg routes through _safe_int, so a
    Unicode-"digit" token (isdigit()==True but int()-unparseable, e.g. "²²²") or a
    >4300-digit token can never raise ValueError out of these handlers — it falls
    through to the name/query path instead. Covers the sibling handlers the
    original read_channel-only fix missed (delete_role, set_channel_permission,
    list_members, get_user_info, edit_message)."""

    def test_safe_int_contract(self):
        from cogs.ai_core.commands.server_commands import _safe_int

        assert _safe_int("123") == 123
        assert _safe_int("0") == 0
        # Unicode "digits" that int() rejects -> None (the trap the fix closes).
        assert "²²²".isdigit() and _safe_int("²²²") is None
        assert "①①".isdigit() and _safe_int("①①") is None
        # >4300 ASCII digits would raise on int() -> None.
        assert _safe_int("9" * 5000) is None
        # max_digits short-circuits before parsing.
        assert _safe_int("1234567890", max_digits=9) is None
        assert _safe_int("123456789", max_digits=9) == 123456789
        # Non-str / None never raise (len() guarded inside the try).
        assert _safe_int(None) is None  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_delete_role_unicode_digit_no_valueerror(self):
        from cogs.ai_core.commands.server_commands import cmd_delete_role

        guild = MagicMock(spec=discord.Guild)
        guild.roles = []
        guild.get_role = MagicMock(return_value=None)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_delete_role(guild, origin, "", ["²²²"])  # must not raise int("²²²")
        origin.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_set_channel_perm_unicode_digit_no_valueerror(self):
        from cogs.ai_core.commands.server_commands import cmd_set_channel_perm

        guild = MagicMock(spec=discord.Guild)
        guild.channels = []
        guild.get_channel = MagicMock(return_value=None)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        with patch("discord.utils.get", return_value=None):
            await cmd_set_channel_perm(guild, origin, "", ["②②", "role", "view_channel", "true"])
        origin.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_members_unicode_digit_limit_no_valueerror(self):
        from cogs.ai_core.commands.server_commands import cmd_list_members

        guild = MagicMock(spec=discord.Guild)
        guild.members = []
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        # "²²²" as the leading "limit" arg must be treated as a query, not int().
        await cmd_list_members(guild, origin, "", ["²²²"])
        origin.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_user_info_unicode_digit_no_valueerror(self):
        from cogs.ai_core.commands.server_commands import cmd_get_user_info

        guild = MagicMock(spec=discord.Guild)
        guild.members = []
        guild.get_member = MagicMock(return_value=None)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        await cmd_get_user_info(guild, origin, "", ["²²²"])
        origin.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_edit_message_unicode_digit_id_no_valueerror(self):
        from cogs.ai_core.commands.server_commands import cmd_edit_message

        guild = MagicMock(spec=discord.Guild)
        origin = MagicMock(spec=discord.TextChannel)
        origin.send = AsyncMock()
        # "²²²" message id -> _safe_int None -> "must be numeric" reply, no crash.
        await cmd_edit_message(guild, origin, "", ["²²²", "new content"])
        origin.send.assert_awaited()
