"""
Extended tests for Music Cog module.
Tests imports, constants, and configuration.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_music_cog_queues_init(self):
        """Test Music cog initializes queues dict."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert hasattr(cog.queues, '__getitem__')
        assert len(cog.queues) == 0

    def test_music_cog_loops_init(self):
        """Test Music cog initializes loops dict."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert hasattr(cog.loops, '__getitem__')
        assert len(cog.loops) == 0

    def test_music_cog_volumes_init(self):
        """Test Music cog initializes volumes dict."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert hasattr(cog.volumes, '__getitem__')

    def test_music_cog_mode_247_init(self):
        """Test Music cog initializes mode_247 dict."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()

        cog = Music(mock_bot)

        assert hasattr(cog.mode_247, '__getitem__')

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
        cog.auto_disconnect_tasks[123] = mock_task

        await cog.cog_unload()

        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cog_unload_clears_queues(self):
        """Test cog_unload clears queues."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        cog.queues[123] = ["song1", "song2"]

        await cog.cog_unload()

        assert len(cog.queues) == 0

    @pytest.mark.asyncio
    async def test_cog_unload_clears_loops(self):
        """Test cog_unload clears loops."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        cog.loops[123] = True

        await cog.cog_unload()

        assert len(cog.loops) == 0


class TestMusicCogCleanupGuildData:
    """Tests for cleanup_guild_data method."""

    @pytest.mark.asyncio
    async def test_cleanup_guild_data_removes_queue(self):
        """Test cleanup removes guild queue."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        cog.queues[guild_id] = ["song1"]

        # Mock save_queue
        cog.save_queue = AsyncMock()

        await cog.cleanup_guild_data(guild_id)

        assert guild_id not in cog.queues

    @pytest.mark.asyncio
    async def test_cleanup_guild_data_removes_loop(self):
        """Test cleanup removes guild loop setting."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        cog.loops[guild_id] = True
        cog.save_queue = AsyncMock()

        await cog.cleanup_guild_data(guild_id)

        assert guild_id not in cog.loops

    @pytest.mark.asyncio
    async def test_cleanup_guild_data_cancels_auto_disconnect(self):
        """Test cleanup cancels auto-disconnect task."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        mock_task = MagicMock()
        cog.auto_disconnect_tasks[guild_id] = mock_task
        cog.save_queue = AsyncMock()

        await cog.cleanup_guild_data(guild_id)

        mock_task.cancel.assert_called_once()
        assert guild_id not in cog.auto_disconnect_tasks


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

        assert cog.last_text_channel[12345] == 67890


class TestMusicCogSaveQueue:
    """Tests for save_queue method."""

    @pytest.mark.asyncio
    async def test_save_queue_empty(self):
        """Test save_queue with empty queue."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        cog.queues[guild_id] = []

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
        queue = [{"title": "song1"}, {"title": "song2"}]
        cog.queues[guild_id] = queue

        with patch('utils.database.db') as mock_db:
            mock_db.save_music_queue = AsyncMock()
            await cog.save_queue(guild_id)
            mock_db.save_music_queue.assert_called_once_with(guild_id, queue)


class TestMusicCogSaveQueueJson:
    """Tests for _save_queue_json method."""

    def test_save_queue_json_empty(self):
        """Test _save_queue_json with empty queue."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        cog.queues[guild_id] = []

        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = False
            cog._save_queue_json(guild_id)
            # Should not raise

    def test_save_queue_json_with_tracks(self):
        """Test _save_queue_json_sync with tracks."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 12345
        cog.queues[guild_id] = [{"title": "song1"}]
        cog.volumes[guild_id] = 0.5
        cog.loops[guild_id] = False
        cog.mode_247[guild_id] = False

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
            assert len(cog.queues[guild_id]) == 1

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
        assert cog.loops.get(guild_id, False) is False

        # Set loop
        cog.loops[guild_id] = True
        assert cog.loops[guild_id] is True

        # Unset loop
        cog.loops[guild_id] = False
        assert cog.loops[guild_id] is False

    @pytest.mark.asyncio
    async def test_queue_manipulation(self):
        """Test queue manipulation in cog."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Add to queue
        cog.queues[guild_id] = ["song1", "song2", "song3"]
        assert len(cog.queues[guild_id]) == 3

        # Clear queue
        cog.queues[guild_id] = []
        assert len(cog.queues[guild_id]) == 0

    @pytest.mark.asyncio
    async def test_volume_range(self):
        """Test volume within valid range."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Set volume at different levels
        cog.volumes[guild_id] = 0.0
        assert cog.volumes[guild_id] == 0.0

        cog.volumes[guild_id] = 0.5
        assert cog.volumes[guild_id] == 0.5

        cog.volumes[guild_id] = 1.0
        assert cog.volumes[guild_id] == 1.0

    @pytest.mark.asyncio
    async def test_current_track_management(self):
        """Test current track management."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 123456

        # Set current track
        cog.current_track[guild_id] = {
            "title": "Test Song",
            "duration": 180,
            "url": "https://example.com"
        }

        assert cog.current_track[guild_id]["title"] == "Test Song"

        # Remove current track
        cog.current_track[guild_id] = None
        assert cog.current_track[guild_id] is None
