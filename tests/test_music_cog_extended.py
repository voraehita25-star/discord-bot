"""
Extended tests for Music Cog module.
Tests imports, constants, and configuration.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestMusicCogImports:
    """Tests for music cog module imports."""

    def test_ytdl_source_import(self):
        """Test YTDLSource is imported."""
        from cogs.music.cog import YTDLSource

        assert YTDLSource is not None

    def test_get_ffmpeg_options_import(self):
        """Test get_ffmpeg_options is imported."""
        from cogs.music.cog import get_ffmpeg_options

        assert callable(get_ffmpeg_options)

    def test_colors_import(self):
        """Test Colors is imported."""
        from cogs.music.cog import Colors

        assert Colors is not None

    def test_emojis_import(self):
        """Test Emojis is imported."""
        from cogs.music.cog import Emojis

        assert Emojis is not None


class TestMusicUtilsImports:
    """Tests for music utils imports."""

    def test_create_progress_bar_import(self):
        """Test create_progress_bar is imported."""
        from cogs.music.cog import create_progress_bar

        assert callable(create_progress_bar)

    def test_format_duration_import(self):
        """Test format_duration is imported."""
        from cogs.music.cog import format_duration

        assert callable(format_duration)


class TestMusicControlViewClass:
    """Tests for MusicControlView class."""

    def test_music_control_view_exists(self):
        """Test MusicControlView class exists."""
        from cogs.music.cog import MusicControlView

        assert MusicControlView is not None

    def test_music_control_view_is_view(self):
        """Test MusicControlView inherits from discord.ui.View."""
        import discord

        from cogs.music.cog import MusicControlView

        assert issubclass(MusicControlView, discord.ui.View)

    @pytest.mark.asyncio
    async def test_music_control_view_init(self):
        """Test MusicControlView initialization."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert view.cog == mock_cog
        assert view.guild_id == 12345


class TestMusicControlViewTimeout:
    """Tests for MusicControlView timeout."""

    @pytest.mark.asyncio
    async def test_default_timeout(self):
        """Test default timeout is 180 seconds."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert view.timeout == 180.0

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """Test custom timeout."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345, timeout=300.0)

        assert view.timeout == 300.0


class TestMusicClassExists:
    """Tests for Music class."""

    def test_music_class_exists(self):
        """Test Music class exists."""
        from cogs.music.cog import Music

        assert Music is not None

    def test_music_is_cog(self):
        """Test Music inherits from commands.Cog."""
        from discord.ext import commands

        from cogs.music.cog import Music

        assert issubclass(Music, commands.Cog)


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test music cog module has docstring."""
        from cogs.music import cog

        assert cog.__doc__ is not None

    def test_module_docstring_mentions_music(self):
        """Test music cog module docstring mentions music."""
        from cogs.music import cog

        assert "Music" in cog.__doc__ or "music" in cog.__doc__


class TestMusicControlViewInteractionCheck:
    """Tests for MusicControlView interaction_check method."""

    @pytest.mark.asyncio
    async def test_interaction_check_exists(self):
        """Test interaction_check method exists."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert hasattr(view, "interaction_check")

    @pytest.mark.asyncio
    async def test_interaction_check_no_voice(self):
        """Test interaction_check returns False when user not in voice."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        mock_interaction = MagicMock()
        mock_interaction.user.voice = None
        mock_interaction.response.send_message = AsyncMock()

        result = await view.interaction_check(mock_interaction)

        assert result is False

    @pytest.mark.asyncio
    async def test_interaction_check_with_voice(self):
        """Test interaction_check returns True when user in voice."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        mock_interaction = MagicMock()
        mock_interaction.user.voice = MagicMock()
        mock_interaction.user.voice.channel = MagicMock()  # User's voice channel
        mock_interaction.guild.voice_client = None  # Bot not in voice
        mock_interaction.response.send_message = AsyncMock()
        mock_interaction.response.edit_message = AsyncMock()

        result = await view.interaction_check(mock_interaction)

        assert result is True


class TestPathImport:
    """Tests for Path import."""

    def test_path_used_in_module(self):
        """Test Path is imported from pathlib."""
        from pathlib import Path as PathLib

        from cogs.music.cog import Path

        assert Path is PathLib


class TestAsyncioImport:
    """Tests for asyncio import."""

    def test_asyncio_used_in_module(self):
        """Test asyncio is imported."""

        from cogs.music import cog

        # Module should have asyncio-related code
        assert "asyncio" in dir(cog) or hasattr(cog, "asyncio")


class TestMusicControlViewAttributes:
    """Tests for MusicControlView attributes."""

    @pytest.mark.asyncio
    async def test_has_cog_attribute(self):
        """Test MusicControlView has cog attribute."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert hasattr(view, "cog")

    @pytest.mark.asyncio
    async def test_has_guild_id_attribute(self):
        """Test MusicControlView has guild_id attribute."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert hasattr(view, "guild_id")
