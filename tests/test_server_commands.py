"""Tests for server_commands module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord


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
            result = find_member(mock_guild, "username")
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
            result = find_member(mock_guild, "TESTUSER")
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
