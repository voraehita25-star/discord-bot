"""
Extended tests for Music Cog module.
Tests imports, constants, and configuration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
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

        assert hasattr(view, 'interaction_check')

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
        mock_interaction.user = MagicMock(spec=discord.Member)
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
        assert 'asyncio' in dir(cog) or hasattr(cog, 'asyncio')


class TestMusicControlViewAttributes:
    """Tests for MusicControlView attributes."""

    @pytest.mark.asyncio
    async def test_has_cog_attribute(self):
        """Test MusicControlView has cog attribute."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert hasattr(view, 'cog')

    @pytest.mark.asyncio
    async def test_has_guild_id_attribute(self):
        """Test MusicControlView has guild_id attribute."""
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        assert hasattr(view, 'guild_id')


# ======================================================================
# Merged from test_music_cog_module.py
# ======================================================================

class TestMusicControlViewBasic:
    """Basic tests for MusicControlView class without event loop."""

    def test_music_control_view_import(self):
        """Test MusicControlView can be imported."""
        from cogs.music.cog import MusicControlView
        assert MusicControlView is not None

    @pytest.mark.asyncio
    async def test_music_control_view_creation_async(self):
        """Test MusicControlView can be created in async context."""
        from cogs.music.cog import MusicControlView

        mock_cog = MagicMock()

        view = MusicControlView(mock_cog, guild_id=123456)

        assert view.cog is mock_cog
        assert view.guild_id == 123456

    @pytest.mark.asyncio
    async def test_music_control_view_default_timeout_async(self):
        """Test MusicControlView default timeout."""
        from cogs.music.cog import MusicControlView

        mock_cog = MagicMock()

        view = MusicControlView(mock_cog, guild_id=123456)

        assert view.timeout == 180.0

    @pytest.mark.asyncio
    async def test_interaction_check_no_voice(self):
        """Test interaction_check when user not in voice."""
        from cogs.music.cog import MusicControlView

        mock_cog = MagicMock()
        view = MusicControlView(mock_cog, guild_id=123456)

        mock_interaction = MagicMock()
        mock_interaction.user.voice = None
        mock_interaction.response.send_message = AsyncMock()

        result = await view.interaction_check(mock_interaction)

        assert result is False
        mock_interaction.response.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_interaction_check_in_voice(self):
        """Test interaction_check when user is in voice."""
        from cogs.music.cog import MusicControlView

        mock_cog = MagicMock()
        view = MusicControlView(mock_cog, guild_id=123456)

        mock_interaction = MagicMock()
        mock_interaction.user = MagicMock(spec=discord.Member)
        mock_interaction.user.voice = MagicMock()
        mock_interaction.user.voice.channel = MagicMock()  # User's voice channel
        mock_interaction.guild.voice_client = None  # Bot not in voice
        mock_interaction.response.send_message = AsyncMock()
        mock_interaction.response.edit_message = AsyncMock()

        result = await view.interaction_check(mock_interaction)

        assert result is True

    @pytest.mark.asyncio
    async def test_on_timeout_disables_buttons(self):
        """Test on_timeout disables all buttons."""
        from cogs.music.cog import MusicControlView

        mock_cog = MagicMock()
        view = MusicControlView(mock_cog, guild_id=123456)

        # Add mock buttons that pass isinstance check for discord.ui.Button
        mock_button1 = MagicMock(spec=discord.ui.Button)
        mock_button1.disabled = False
        mock_button2 = MagicMock(spec=discord.ui.Button)
        mock_button2.disabled = False
        view._children = [mock_button1, mock_button2]

        await view.on_timeout()

        assert mock_button1.disabled is True
        assert mock_button2.disabled is True


class TestMusicCogInit:
    """Tests for Music Cog initialization."""

    def test_music_cog_creation(self):
        """Test Music cog can be created."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert cog.bot is mock_bot

    def test_music_cog_guild_states_init(self):
        """Test Music cog initializes _guild_states dict."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert isinstance(cog._guild_states, dict)
        assert len(cog._guild_states) == 0

    def test_music_cog_gs_defaults(self):
        """Test _gs() returns a state with correct defaults."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        gs = cog._gs(12345)
        assert len(gs.queue) == 0
        assert gs.loop is False
        assert gs.volume == 0.5
        assert gs.mode_247 is False

    def test_music_cog_auto_disconnect_delay(self):
        """Test Music cog auto disconnect delay."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert cog.auto_disconnect_delay == 180  # 3 minutes


class TestMusicCogUnload:
    """Tests for Music Cog unload."""

    @pytest.mark.asyncio
    async def test_cog_unload_cancels_tasks(self):
        """Test cog_unload cancels auto-disconnect tasks."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        # Add mock task
        mock_task = MagicMock()
        cog._gs(123).auto_disconnect_task = mock_task

        await cog.cog_unload()

        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_unload_clears_guild_states(self):
        """Test cog_unload clears all guild states."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        import collections
        cog._gs(123).queue = collections.deque(["song1", "song2"])
        cog._gs(456).loop = True

        await cog.cog_unload()

        assert len(cog._guild_states) == 0


class TestMusicCogCleanupGuildData:
    """Tests for cleanup_guild_data method."""

    @pytest.mark.asyncio
    async def test_cleanup_guild_data_removes_queue(self):
        """Test cleanup removes guild queue."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        import collections
        cog._gs(guild_id).queue = collections.deque(["song1"])

        # Mock save_queue
        cog.save_queue = AsyncMock()

        await cog.cleanup_guild_data(guild_id)

        assert guild_id not in cog._guild_states

    @pytest.mark.asyncio
    async def test_cleanup_guild_data_removes_loop(self):
        """Test cleanup removes guild loop setting."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        cog._gs(guild_id).loop = True
        cog.save_queue = AsyncMock()

        await cog.cleanup_guild_data(guild_id)

        assert guild_id not in cog._guild_states

    @pytest.mark.asyncio
    async def test_cleanup_guild_data_cancels_auto_disconnect(self):
        """Test cleanup cancels auto-disconnect task."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        mock_task = MagicMock()
        cog._gs(guild_id).auto_disconnect_task = mock_task
        cog.save_queue = AsyncMock()

        await cog.cleanup_guild_data(guild_id)

        mock_task.cancel.assert_called_once()
        assert guild_id not in cog._guild_states


class TestMusicCogBeforeInvoke:
    """Tests for cog_before_invoke method."""

    @pytest.mark.asyncio
    async def test_before_invoke_tracks_channel(self):
        """Test cog_before_invoke tracks last used channel."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        mock_ctx = MagicMock()
        mock_ctx.guild.id = 12345
        mock_ctx.channel.id = 67890

        await cog.cog_before_invoke(mock_ctx)

        assert cog._gs(12345).last_text_channel == 67890


class TestMusicCogSaveQueue:
    """Tests for save_queue method."""

    @pytest.mark.asyncio
    async def test_save_queue_empty(self):
        """Test save_queue with empty queue."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        # queue is already empty by default via _gs()

        with patch('utils.database.db') as mock_db:
            mock_db.clear_music_queue = AsyncMock()
            await cog.save_queue(guild_id)
            mock_db.clear_music_queue.assert_called_once_with(guild_id)

    @pytest.mark.asyncio
    async def test_save_queue_with_tracks(self):
        """Test save_queue with tracks."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        import collections
        queue = [{"title": "song1"}, {"title": "song2"}]
        cog._gs(guild_id).queue = collections.deque(queue)

        with patch('utils.database.db') as mock_db:
            mock_db.save_music_queue = AsyncMock()
            await cog.save_queue(guild_id)
            mock_db.save_music_queue.assert_called_once_with(guild_id, queue)


class TestMusicCogSaveQueueJson:
    """Tests for _save_queue_json method."""

    def test_save_queue_json_empty(self):
        """Test _save_queue_json_sync with empty queue (no file written when empty)."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        # queue is already empty by default via _gs()

        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = False
            cog._save_queue_json_sync(guild_id)
            # Should not raise

    def test_save_queue_json_with_tracks(self):
        """Test _save_queue_json_sync with tracks."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        import collections
        cog._gs(guild_id).queue = collections.deque([{"title": "song1"}])
        cog._gs(guild_id).volume = 0.5
        cog._gs(guild_id).loop = False
        cog._gs(guild_id).mode_247 = False

        with patch('pathlib.Path.write_text') as mock_write:
            cog._save_queue_json_sync(guild_id)
            mock_write.assert_called_once()


class TestMusicCogLoadQueue:
    """Tests for load_queue method."""

    @pytest.mark.asyncio
    async def test_load_queue_from_database(self):
        """Test load_queue from database."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345

        with patch('utils.database.db') as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=[{"title": "song1"}])
            result = await cog.load_queue(guild_id)

            assert result is True
            assert len(cog._gs(guild_id).queue) == 1

    @pytest.mark.asyncio
    async def test_load_queue_empty_database(self):
        """Test load_queue with empty database result."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345

        with patch('utils.database.db') as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)

            with patch('pathlib.Path.exists') as mock_exists:
                mock_exists.return_value = False
                result = await cog.load_queue(guild_id)

                assert result is False


class TestMusicCogListeners:
    """Tests for Music Cog event listeners."""

    @pytest.mark.asyncio
    async def test_on_guild_remove(self):
        """Test on_guild_remove cleans up data."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        mock_guild = MagicMock()
        mock_guild.id = 12345

        cog.cleanup_guild_data = AsyncMock()

        await cog.on_guild_remove(mock_guild)

        cog.cleanup_guild_data.assert_called_once_with(12345)


class TestMusicCogUtils:
    """Tests for Music cog utility imports."""

    def test_import_colors(self):
        """Test Colors can be imported."""
        from cogs.music.utils import Colors
        assert Colors is not None

    def test_import_emojis(self):
        """Test Emojis can be imported."""
        from cogs.music.utils import Emojis
        assert Emojis is not None

    def test_import_create_progress_bar(self):
        """Test create_progress_bar can be imported."""
        from cogs.music.utils import create_progress_bar
        assert create_progress_bar is not None

    def test_import_format_duration(self):
        """Test format_duration can be imported."""
        from cogs.music.utils import format_duration
        assert format_duration is not None


class TestFormatDuration:
    """Tests for format_duration utility."""

    def test_format_duration_seconds(self):
        """Test format_duration with seconds only."""
        from cogs.music.utils import format_duration

        result = format_duration(45)

        assert "45" in result

    def test_format_duration_minutes(self):
        """Test format_duration with minutes."""
        from cogs.music.utils import format_duration

        result = format_duration(125)  # 2:05

        assert "2" in result
        assert "05" in result

    def test_format_duration_hours(self):
        """Test format_duration with hours."""
        from cogs.music.utils import format_duration

        result = format_duration(3665)  # 1:01:05

        assert "1" in result


class TestCreateProgressBar:
    """Tests for create_progress_bar utility."""

    def test_create_progress_bar_0_percent(self):
        """Test progress bar at 0%."""
        from cogs.music.utils import create_progress_bar

        result = create_progress_bar(0, 100)

        assert isinstance(result, str)

    def test_create_progress_bar_50_percent(self):
        """Test progress bar at 50%."""
        from cogs.music.utils import create_progress_bar

        result = create_progress_bar(50, 100)

        assert isinstance(result, str)

    def test_create_progress_bar_100_percent(self):
        """Test progress bar at 100%."""
        from cogs.music.utils import create_progress_bar

        result = create_progress_bar(100, 100)

        assert isinstance(result, str)


class TestMusicButtonStates:
    """Tests for button state management."""

    @pytest.mark.asyncio
    async def test_loop_state_toggle(self):
        """Test loop state can be toggled in cog."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Initially no loop
        assert cog._gs(guild_id).loop is False

        # Set loop
        cog._gs(guild_id).loop = True
        assert cog._gs(guild_id).loop is True

        # Unset loop
        cog._gs(guild_id).loop = False
        assert cog._gs(guild_id).loop is False

    @pytest.mark.asyncio
    async def test_queue_manipulation(self):
        """Test queue manipulation in cog."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Add to queue
        import collections
        cog._gs(guild_id).queue = collections.deque(["song1", "song2", "song3"])
        assert len(cog._gs(guild_id).queue) == 3

        # Clear queue
        cog._gs(guild_id).queue = collections.deque()
        assert len(cog._gs(guild_id).queue) == 0

    @pytest.mark.asyncio
    async def test_volume_range(self):
        """Test volume within valid range."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Set volume at different levels
        cog._gs(guild_id).volume = 0.0
        assert cog._gs(guild_id).volume == 0.0

        cog._gs(guild_id).volume = 0.5
        assert cog._gs(guild_id).volume == 0.5

        cog._gs(guild_id).volume = 1.0
        assert cog._gs(guild_id).volume == 1.0

    @pytest.mark.asyncio
    async def test_current_track_management(self):
        """Test current track management."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Set current track
        cog._gs(guild_id).current_track = {
            "title": "Test Song",
            "duration": 180,
            "url": "https://example.com"
        }

        assert cog._gs(guild_id).current_track["title"] == "Test Song"

        # Remove current track
        cog._gs(guild_id).current_track = None
        assert cog._gs(guild_id).current_track is None
