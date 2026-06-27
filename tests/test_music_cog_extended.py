"""
Extended tests for Music Cog module.
Tests imports, constants, and configuration.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from tests.conftest import closing_create_task_mock


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
        """Test interaction_check returns True when user in voice with bot.

        interaction_check now also requires a connected voice_client and
        that the user shares its channel — without this guard the music
        controls would respond with stale state when the bot is no longer
        in any voice channel.
        """
        from cogs.music.cog import Music, MusicControlView

        mock_cog = MagicMock(spec=Music)
        view = MusicControlView(cog=mock_cog, guild_id=12345)

        # Bot is in a voice channel and the user is in the same one.
        shared_channel = MagicMock()
        mock_voice_client = MagicMock(channel=shared_channel)

        mock_interaction = MagicMock()
        mock_interaction.user = MagicMock(spec=discord.Member)
        mock_interaction.user.voice = MagicMock()
        mock_interaction.user.voice.channel = shared_channel
        mock_interaction.guild.voice_client = mock_voice_client
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
        """Test interaction_check when user shares the bot's voice channel.

        interaction_check now also returns False if the bot is not
        connected to voice — having a connected voice_client is now a
        prerequisite for the controls to be interactive.
        """
        from cogs.music.cog import MusicControlView

        mock_cog = MagicMock()
        view = MusicControlView(mock_cog, guild_id=123456)

        shared_channel = MagicMock()
        mock_voice_client = MagicMock(channel=shared_channel)

        mock_interaction = MagicMock()
        mock_interaction.user = MagicMock(spec=discord.Member)
        mock_interaction.user.voice = MagicMock()
        mock_interaction.user.voice.channel = shared_channel
        mock_interaction.guild.voice_client = mock_voice_client
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

        with patch("utils.database.db") as mock_db:
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

        with patch("utils.database.db") as mock_db:
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

        with patch("pathlib.Path.exists") as mock_exists:
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

        with patch("pathlib.Path.write_text") as mock_write:
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

        with patch("utils.database.db") as mock_db:
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

        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)

            with patch("pathlib.Path.exists") as mock_exists:
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
            "url": "https://example.com",
        }

        assert cog._gs(guild_id).current_track["title"] == "Test Song"

        # Remove current track
        cog._gs(guild_id).current_track = None
        assert cog._gs(guild_id).current_track is None


# ======================================================================
# Region 1-1000 coverage: helpers, connection/cleanup, listeners,
# auto-disconnect, save/load, play_next. Appended batch.
# ======================================================================


def _make_cog():
    """Build a Music cog with a mocked bot and stubbed spotify handler."""
    from cogs.music.cog import Music

    mock_bot = MagicMock()
    mock_bot.loop = MagicMock()
    mock_bot.loop.is_running.return_value = True
    mock_bot.loop.is_closed.return_value = False
    mock_bot.voice_clients = []
    mock_bot.change_presence = AsyncMock()
    cog = Music(mock_bot)
    return cog, mock_bot


class TestCogLoad:
    """cog_load starts the two background tasks (lines 87-88)."""

    @pytest.mark.asyncio
    async def test_cog_load_starts_tasks(self):
        cog, _ = _make_cog()
        with patch("asyncio.create_task") as mock_create:
            sentinel1 = MagicMock()
            sentinel2 = MagicMock()
            returns = [sentinel1, sentinel2]

            def _close_and_return(coro=None, *a, **k):
                # Close the real loop coroutine so it doesn't leak a
                # "never awaited" warning, but still hand back the sentinels
                # the assertions below check for.
                if asyncio.iscoroutine(coro):
                    coro.close()
                return returns.pop(0)

            mock_create.side_effect = _close_and_return
            await cog.cog_load()
        assert cog._temp_cleanup_task is sentinel1
        assert cog._queue_autosave_task is sentinel2
        assert mock_create.call_count == 2


class TestPeriodicTempCleanup:
    """_periodic_temp_cleanup loop body and inner sync helpers."""

    @pytest.mark.asyncio
    async def test_loop_runs_then_cancels(self, tmp_path, monkeypatch):
        """First sleep returns, cleanup runs and logs, second sleep cancels."""
        import asyncio as _a

        cog, _ = _make_cog()

        # A guild with a current_track file marks it in-use.
        in_use_file = tmp_path / "keep.mp3"
        in_use_file.write_text("x")
        cog._gs(1).current_track = {"filename": str(in_use_file)}
        # A guild with bad filename triggers the OSError/ValueError skip.
        cog._gs(2).current_track = {"filename": "\x00bad"}

        # Stale file to be deleted.
        stale = tmp_path / "stale.mp3"
        stale.write_text("y")
        # A directory entry (not a file) to hit the is_file() continue.
        (tmp_path / "subdir").mkdir()
        # A fresh file that should NOT be deleted (within threshold).
        fresh = tmp_path / "fresh.mp3"
        fresh.write_text("z")

        import os

        old = 0  # epoch -> definitely stale
        os.utime(stale, (old, old))

        monkeypatch.chdir(tmp_path.parent)

        # Patch Path("temp") to resolve to our tmp_path.
        from cogs.music import cog as cogmod

        real_path = cogmod.Path

        def fake_path(arg, *a, **k):
            if arg == "temp":
                return real_path(str(tmp_path))
            return real_path(arg, *a, **k)

        # Drive the while loop exactly once then cancel.
        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with (
            patch.object(cogmod, "Path", side_effect=fake_path),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            # to_thread should actually run the sync worker.
            await cog._periodic_temp_cleanup()

        # The stale file got deleted; in-use + fresh + subdir survive.
        assert not stale.exists()
        assert in_use_file.exists()
        assert fresh.exists()

    @pytest.mark.asyncio
    async def test_loop_swallows_generic_exception(self, monkeypatch):
        """Non-cancel exception in body is logged then loop continues to cancel."""
        import asyncio as _a

        cog, _ = _make_cog()
        calls = {"n": 0}

        async def fake_sleep(_secs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("boom")  # caught by generic handler
            raise _a.CancelledError

        with patch("asyncio.sleep", new=fake_sleep):
            await cog._periodic_temp_cleanup()
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_cleanup_sync_no_temp_dir_returns_zero(self, monkeypatch):
        """When temp dir doesn't exist the worker returns 0 (no log line)."""
        import asyncio as _a

        cog, _ = _make_cog()
        from cogs.music import cog as cogmod

        missing = cogmod.Path("definitely_not_a_temp_dir_zzz")

        def fake_path(arg, *a, **k):
            if arg == "temp":
                return missing
            return cogmod.Path.__wrapped__(arg) if hasattr(cogmod.Path, "__wrapped__") else missing

        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with (
            patch.object(cogmod, "Path", return_value=missing),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            await cog._periodic_temp_cleanup()


class TestPeriodicQueueSave:
    """_periodic_queue_save loop."""

    @pytest.mark.asyncio
    async def test_no_pending_continues(self, monkeypatch):
        """Empty pending set -> continue branch, then cancel."""
        import asyncio as _a

        cog, _ = _make_cog()
        cog.save_queue = AsyncMock()
        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with patch("asyncio.sleep", new=fake_sleep):
            await cog._periodic_queue_save()
        cog.save_queue.assert_not_called()

    @pytest.mark.asyncio
    async def test_saves_pending_guilds(self, monkeypatch):
        """Pending guilds with state get saved; missing state is skipped."""
        import asyncio as _a

        cog, _ = _make_cog()
        cog._gs(100)  # exists
        cog._queue_save_pending = {100, 999}  # 999 has no state
        cog.save_queue = AsyncMock()

        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with patch("asyncio.sleep", new=fake_sleep):
            await cog._periodic_queue_save()
        cog.save_queue.assert_awaited_once_with(100)
        assert cog._queue_save_pending == set()

    @pytest.mark.asyncio
    async def test_save_failure_requeues(self, monkeypatch):
        """A failing save re-queues that guild and logs a warning."""
        import asyncio as _a

        cog, _ = _make_cog()
        cog._gs(100)
        cog._queue_save_pending = {100}
        cog.save_queue = AsyncMock(side_effect=RuntimeError("db down"))

        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with patch("asyncio.sleep", new=fake_sleep):
            await cog._periodic_queue_save()
        # Guild re-queued for next tick.
        assert 100 in cog._queue_save_pending

    @pytest.mark.asyncio
    async def test_outer_exception_logged(self, monkeypatch):
        """An exception outside per-guild guard hits the outer handler."""
        import asyncio as _a

        cog, _ = _make_cog()

        calls = {"n": 0}

        async def fake_sleep(_secs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("outer boom")
            raise _a.CancelledError

        with patch("asyncio.sleep", new=fake_sleep):
            await cog._periodic_queue_save()
        assert calls["n"] == 2


class TestScheduleQueueSave:
    def test_schedule_marks_pending(self):
        cog, _ = _make_cog()
        cog._schedule_queue_save(42)
        assert 42 in cog._queue_save_pending


class TestSafeRunCoroutine:
    """_safe_run_coroutine threadsafe scheduling and error handling."""

    def test_schedules_when_loop_running(self):
        cog, mock_bot = _make_cog()
        fut = MagicMock()
        with patch("asyncio.run_coroutine_threadsafe", return_value=fut) as mock_run:

            async def _c():
                return None

            coro = _c()
            cog._safe_run_coroutine(coro)
            mock_run.assert_called_once()
            fut.add_done_callback.assert_called_once()
            coro.close()

    def test_done_callback_logs_exception(self):
        """The attached done-callback surfaces coroutine exceptions."""
        cog, mock_bot = _make_cog()
        captured = {}

        def fake_run(coro, loop):
            fut = MagicMock()

            def add_cb(cb):
                captured["cb"] = cb

            fut.add_done_callback.side_effect = add_cb
            return fut

        with patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run):

            async def _c():
                return None

            coro = _c()
            cog._safe_run_coroutine(coro)
            coro.close()

        # Invoke the captured callback with a future that raises.
        bad_fut = MagicMock()
        bad_fut.result.side_effect = RuntimeError("coro failed")
        captured["cb"](bad_fut)  # should not raise

    def test_no_schedule_when_loop_closed(self):
        cog, mock_bot = _make_cog()
        mock_bot.loop.is_running.return_value = False
        with patch("asyncio.run_coroutine_threadsafe") as mock_run:

            async def _c():
                return None

            coro = _c()
            cog._safe_run_coroutine(coro)
            mock_run.assert_not_called()
            coro.close()

    def test_attribute_error_swallowed(self):
        """RuntimeError/AttributeError on loop access is silently ignored."""
        cog, mock_bot = _make_cog()
        type(mock_bot).loop = property(
            lambda self: (_ for _ in ()).throw(AttributeError("no loop"))
        )

        async def _c():
            return None

        coro = _c()
        cog._safe_run_coroutine(coro)  # must not raise
        coro.close()


class TestCogUnloadFull:
    """cog_unload full path: cancel+await tasks, save, disconnect, spotify."""

    @pytest.mark.asyncio
    async def test_full_unload(self):
        cog, mock_bot = _make_cog()

        # Background tasks that need awaiting.
        async def _dummy():
            return None

        t1 = asyncio.ensure_future(_dummy())
        t2 = asyncio.ensure_future(_dummy())
        cog._temp_cleanup_task = t1
        cog._queue_autosave_task = t2

        # A guild with an auto-disconnect task and a voice client to disconnect.
        gid = 555
        adt = MagicMock()
        cog._gs(gid).auto_disconnect_task = adt

        cog.save_queue = AsyncMock()

        vc_managed = MagicMock()
        vc_managed.guild.id = gid
        vc_managed.disconnect = AsyncMock()
        vc_other = MagicMock()
        vc_other.guild.id = 999999  # not managed
        vc_other.disconnect = AsyncMock()
        mock_bot.voice_clients = [vc_managed, vc_other]

        cog.spotify = MagicMock()

        await cog.cog_unload()

        adt.cancel.assert_called_once()
        cog.save_queue.assert_awaited()
        vc_managed.disconnect.assert_awaited_once_with(force=True)
        vc_other.disconnect.assert_not_called()
        cog.spotify.cleanup.assert_called_once()
        assert cog._temp_cleanup_task is None
        assert cog._queue_autosave_task is None
        assert len(cog._guild_states) == 0

    @pytest.mark.asyncio
    async def test_unload_save_failure_logged(self):
        cog, mock_bot = _make_cog()
        cog._gs(7)
        cog.save_queue = AsyncMock(side_effect=RuntimeError("nope"))
        mock_bot.voice_clients = []
        cog.spotify = MagicMock()
        await cog.cog_unload()  # exception path logged, not raised
        assert len(cog._guild_states) == 0

    @pytest.mark.asyncio
    async def test_unload_disconnect_failure_logged(self):
        cog, mock_bot = _make_cog()
        gid = 12
        cog._gs(gid)
        cog.save_queue = AsyncMock()
        vc = MagicMock()
        vc.guild.id = gid
        vc.disconnect = AsyncMock(side_effect=RuntimeError("disc fail"))
        mock_bot.voice_clients = [vc]
        cog.spotify = MagicMock()
        await cog.cog_unload()  # logged, not raised
        assert len(cog._guild_states) == 0


class TestCleanupGuildDataExtra:
    """cleanup_guild_data: defer-while-fixing and keep_247 branches."""

    @pytest.mark.asyncio
    async def test_defers_when_fixing(self):
        cog, _ = _make_cog()
        gid = 31
        cog._gs(gid).fixing = True
        cog.save_queue = AsyncMock()
        await cog.cleanup_guild_data(gid)
        # State preserved, cleanup_pending flag set, save not called.
        assert cog._gs(gid).cleanup_pending is True
        cog.save_queue.assert_not_called()

    @pytest.mark.asyncio
    async def test_keep_247_replaces_state(self):
        cog, _ = _make_cog()
        gid = 32
        cog._gs(gid).mode_247 = True
        cog._gs(gid).loop = True  # should be reset to default
        cog.save_queue = AsyncMock()
        await cog.cleanup_guild_data(gid)
        # State still present (247 preserved) but reset to default otherwise.
        assert gid in cog._guild_states
        assert cog._gs(gid).mode_247 is True
        assert cog._gs(gid).loop is False


class TestSaveQueueImportFallback:
    """save_queue falls back to JSON when DB import fails."""

    @pytest.mark.asyncio
    async def test_import_error_uses_json(self):
        cog, _ = _make_cog()
        import collections

        cog._gs(5).queue = collections.deque([{"title": "a"}])
        cog._save_queue_json = AsyncMock()

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "utils.database":
                raise ImportError("no db")
            return real_import(name, *a, **k)

        with patch("builtins.__import__", side_effect=fake_import):
            await cog.save_queue(5)
        cog._save_queue_json.assert_awaited_once_with(5)


class TestSaveQueueJsonAsync:
    """_save_queue_json snapshots state then delegates to thread worker."""

    @pytest.mark.asyncio
    async def test_snapshot_passed_to_worker(self):
        cog, _ = _make_cog()
        import collections

        gid = 8
        cog._gs(gid).queue = collections.deque([{"title": "song"}])
        cog._gs(gid).volume = 0.7
        cog._gs(gid).loop = True
        cog._gs(gid).mode_247 = True

        captured = {}

        def fake_sync(g, snap):
            captured["g"] = g
            captured["snap"] = snap

        cog._save_queue_json_sync = fake_sync
        await cog._save_queue_json(gid)
        assert captured["g"] == gid
        assert captured["snap"]["volume"] == 0.7
        assert captured["snap"]["loop"] is True
        assert captured["snap"]["mode_247"] is True
        assert captured["snap"]["queue"] == [{"title": "song"}]


class TestSaveQueueJsonSyncBranches:
    """_save_queue_json_sync: snapshot=None path, empty-with-file unlink, error."""

    def test_snapshot_none_reads_gs(self, tmp_path, monkeypatch):
        cog, _ = _make_cog()
        import collections

        gid = 9
        cog._gs(gid).queue = collections.deque([{"title": "s"}])
        from cogs.music import cog as cogmod

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("/", "_")

        with patch.object(cogmod, "Path", side_effect=fake_path):
            cog._save_queue_json_sync(gid)  # snapshot=None branch
        written = tmp_path / f"data_queue_{gid}.json"
        assert written.exists()

    def test_empty_queue_unlinks_existing_file(self, tmp_path):
        cog, _ = _make_cog()
        gid = 10
        from cogs.music import cog as cogmod

        existing = tmp_path / f"data_queue_{gid}.json"
        existing.write_text("{}")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("/", "_")

        with patch.object(cogmod, "Path", side_effect=fake_path):
            cog._save_queue_json_sync(
                gid, snapshot={"queue": [], "volume": 0.5, "loop": False, "mode_247": False}
            )
        assert not existing.exists()

    def test_write_oserror_cleans_temp(self, tmp_path):
        import os as _os

        cog, _ = _make_cog()
        gid = 11
        from cogs.music import cog as cogmod

        snap = {"queue": [{"t": "x"}], "volume": 0.5, "loop": False, "mode_247": False}

        # write_text raises OSError to hit the except + temp-cleanup branch.
        def boom(self, *a, **k):
            raise OSError("disk full")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("/", "_")

        # The save path makes a unique temp file via tempfile.mkstemp; pin it to
        # a known path so the cleanup unlink runs deterministically. The mkstemp
        # name is chosen so fake_path maps it back onto tmp_file.
        tmp_file = tmp_path / f"data_queue_{gid}.json.tmp"
        fd = _os.open(tmp_file, _os.O_CREAT | _os.O_WRONLY)

        with patch.object(cogmod, "Path", side_effect=fake_path):
            with patch.object(
                cogmod.tempfile, "mkstemp", return_value=(fd, f"data/queue_{gid}.json.tmp")
            ):
                with patch.object(cogmod.Path, "write_text", boom):
                    cog._save_queue_json_sync(gid, snapshot=snap)
        # temp file cleaned up
        assert not tmp_file.exists()


class TestLoadQueueBranches:
    """load_queue: DB cap, DB-empty -> JSON path + migration variants."""

    @pytest.mark.asyncio
    async def test_db_caps_queue(self):
        from cogs.music.cog import Music
        from cogs.music.queue import MAX_QUEUE_SIZE

        cog, _ = _make_cog()
        big = [{"url": f"u{i}"} for i in range(MAX_QUEUE_SIZE + 50)]
        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=big)
            result = await cog.load_queue(1)
        assert result is True
        assert len(cog._gs(1).queue) == MAX_QUEUE_SIZE

    @pytest.mark.asyncio
    async def test_db_import_error_then_no_json(self, tmp_path, monkeypatch):
        cog, _ = _make_cog()
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "utils.database":
                raise ImportError("nodb")
            return real_import(name, *a, **k)

        with patch("builtins.__import__", side_effect=fake_import):
            with patch("pathlib.Path.exists", return_value=False):
                result = await cog.load_queue(2)
        assert result is False

    @pytest.mark.asyncio
    async def test_json_load_success_and_migration(self, tmp_path, monkeypatch):
        """DB empty -> read JSON, migrate to DB, verify, unlink."""
        cog, _ = _make_cog()
        gid = 3
        from cogs.music import cog as cogmod

        json_file = tmp_path / f"data_queue_{gid}.json"
        import json as _json

        json_file.write_text(
            _json.dumps({"queue": [{"url": "x"}], "volume": 0.8, "loop": True, "mode_247": True}),
            encoding="utf-8",
        )

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("data/", "data_")

        cog.save_queue = AsyncMock()

        with patch("utils.database.db") as mock_db:
            # load_queue calls db.load_music_queue twice on this path:
            #   1) the DB-first read -> None forces the JSON fallback branch
            #   2) the migration read-back -> truthy content confirms the
            #      round-trip so the source JSON gets unlinked.
            # Both calls hit the same patched object, so drive them with a
            # single side_effect sequence rather than overwriting the mock.
            mock_db.load_music_queue = AsyncMock(side_effect=[None, [{"url": "x"}]])
            with patch.object(cogmod, "Path", side_effect=fake_path):
                result = await cog.load_queue(gid)

        assert result is True
        assert cog._gs(gid).volume == 0.8
        assert cog._gs(gid).loop is True
        assert cog._gs(gid).mode_247 is True
        # JSON deleted after successful migration
        assert not json_file.exists()

    @pytest.mark.asyncio
    async def test_json_invalid_format_returns_false(self, tmp_path):
        cog, _ = _make_cog()
        gid = 4
        from cogs.music import cog as cogmod

        json_file = tmp_path / f"data_queue_{gid}.json"
        import json as _json

        json_file.write_text(_json.dumps(["not", "a", "dict"]), encoding="utf-8")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("data/", "data_")

        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)
            with patch.object(cogmod, "Path", side_effect=fake_path):
                result = await cog.load_queue(gid)
        assert result is False

    @pytest.mark.asyncio
    async def test_json_migration_db_empty_keeps_file(self, tmp_path):
        """Read-back empty -> keep JSON (warning), don't unlink."""
        cog, _ = _make_cog()
        gid = 13
        import json as _json

        from cogs.music import cog as cogmod

        json_file = tmp_path / f"data_queue_{gid}.json"
        json_file.write_text(_json.dumps({"queue": [{"url": "y"}]}), encoding="utf-8")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("data/", "data_")

        cog.save_queue = AsyncMock()
        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)
            with patch.object(cogmod, "Path", side_effect=fake_path):
                import utils.database as _udb

                _udb.db.load_music_queue = AsyncMock(return_value=[])  # empty read-back
                result = await cog.load_queue(gid)
        assert result is True
        assert json_file.exists()  # retained

    @pytest.mark.asyncio
    async def test_json_migration_save_exception_retains(self, tmp_path):
        """save_queue raising during migration leaves JSON in place."""
        cog, _ = _make_cog()
        gid = 14
        import json as _json

        from cogs.music import cog as cogmod

        json_file = tmp_path / f"data_queue_{gid}.json"
        json_file.write_text(_json.dumps({"queue": [{"url": "z"}]}), encoding="utf-8")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("data/", "data_")

        cog.save_queue = AsyncMock(side_effect=RuntimeError("save fail"))
        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)
            with patch.object(cogmod, "Path", side_effect=fake_path):
                result = await cog.load_queue(gid)
        assert result is True
        assert json_file.exists()

    @pytest.mark.asyncio
    async def test_json_migration_no_db_layer_keeps_json(self, tmp_path):
        """Inner db import fails -> keep JSON, return True early."""
        cog, _ = _make_cog()
        gid = 15
        import json as _json

        from cogs.music import cog as cogmod

        json_file = tmp_path / f"data_queue_{gid}.json"
        json_file.write_text(_json.dumps({"queue": [{"url": "w"}]}), encoding="utf-8")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("data/", "data_")

        cog.save_queue = AsyncMock()

        import builtins

        real_import = builtins.__import__
        state = {"outer_done": False}

        def fake_import(name, *a, **k):
            # Allow the outer DB import (returns None queue), fail the inner
            # `from utils.database import db as _db` (second occurrence).
            if name == "utils.database":
                if state["outer_done"]:
                    raise ImportError("inner no db")
                state["outer_done"] = True
                mod = real_import(name, *a, **k)
                return mod
            return real_import(name, *a, **k)

        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)
            with patch.object(cogmod, "Path", side_effect=fake_path):
                with patch("builtins.__import__", side_effect=fake_import):
                    result = await cog.load_queue(gid)
        assert result is True
        assert json_file.exists()

    @pytest.mark.asyncio
    async def test_json_read_oserror_returns_false(self, tmp_path):
        """A JSONDecodeError / OSError on read returns False."""
        cog, _ = _make_cog()
        gid = 16
        from cogs.music import cog as cogmod

        json_file = tmp_path / f"data_queue_{gid}.json"
        json_file.write_text("{ this is not json", encoding="utf-8")

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("data/", "data_")

        with patch("utils.database.db") as mock_db:
            mock_db.load_music_queue = AsyncMock(return_value=None)
            with patch.object(cogmod, "Path", side_effect=fake_path):
                result = await cog.load_queue(gid)
        assert result is False


class TestOnGuildRemove:
    """on_guild_remove disconnects matching VCs and cleans data."""

    @pytest.mark.asyncio
    async def test_disconnects_matching_vc(self):
        cog, mock_bot = _make_cog()
        gid = 21
        vc = MagicMock()
        vc.guild.id = gid
        vc.disconnect = AsyncMock()
        # A VC without guild attr -> skipped via hasattr/None checks.
        vc_noguild = MagicMock()
        vc_noguild.guild = None
        # A VC for another guild -> skipped.
        vc_other = MagicMock()
        vc_other.guild.id = 99
        vc_other.disconnect = AsyncMock()
        mock_bot.voice_clients = [vc, vc_noguild, vc_other]
        cog.cleanup_guild_data = AsyncMock()

        mock_guild = MagicMock()
        mock_guild.id = gid
        await cog.on_guild_remove(mock_guild)

        vc.disconnect.assert_awaited_once_with(force=True)
        vc_other.disconnect.assert_not_called()
        cog.cleanup_guild_data.assert_awaited_once_with(gid)

    @pytest.mark.asyncio
    async def test_disconnect_failure_logged(self):
        cog, mock_bot = _make_cog()
        gid = 22
        vc = MagicMock()
        vc.guild.id = gid
        vc.disconnect = AsyncMock(side_effect=RuntimeError("fail"))
        mock_bot.voice_clients = [vc]
        cog.cleanup_guild_data = AsyncMock()
        mock_guild = MagicMock()
        mock_guild.id = gid
        await cog.on_guild_remove(mock_guild)
        cog.cleanup_guild_data.assert_awaited_once_with(gid)


class TestOnVoiceStateUpdate:
    """on_voice_state_update branches."""

    def _vc(self, guild_id, channel):
        vc = MagicMock()
        vc.guild.id = guild_id
        vc.guild = MagicMock(id=guild_id)
        vc.channel = channel
        return vc

    @pytest.mark.asyncio
    async def test_no_bot_user_returns(self):
        cog, mock_bot = _make_cog()
        mock_bot.user = None
        member = MagicMock()
        before = MagicMock()
        after = MagicMock()
        await cog.on_voice_state_update(member, before, after)  # early return

    @pytest.mark.asyncio
    async def test_skip_vc_without_guild_or_channel(self):
        cog, mock_bot = _make_cog()
        mock_bot.user = MagicMock(id=1)
        vc = MagicMock()
        vc.guild = None  # triggers continue
        mock_bot.voice_clients = [vc]
        member = MagicMock()
        member.guild.id = 5
        await cog.on_voice_state_update(member, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_skip_vc_other_guild(self):
        cog, mock_bot = _make_cog()
        mock_bot.user = MagicMock(id=1)
        chan = MagicMock()
        vc = MagicMock()
        vc.guild = MagicMock(id=77)
        vc.channel = chan
        mock_bot.voice_clients = [vc]
        member = MagicMock()
        member.guild.id = 5  # different guild
        await cog.on_voice_state_update(member, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_bot_disconnected_cleans_up(self):
        cog, mock_bot = _make_cog()
        bot_user = MagicMock(id=42)
        mock_bot.user = bot_user
        gid = 5
        chan = MagicMock()
        vc = MagicMock()
        vc.guild = MagicMock(id=gid)
        vc.channel = chan
        mock_bot.voice_clients = [vc]

        member = MagicMock(id=42)  # the bot itself
        member.guild = MagicMock(id=gid)
        before = MagicMock()
        before.channel = chan
        after = MagicMock()
        after.channel = None  # disconnected

        cog.cleanup_guild_data = AsyncMock()
        await cog.on_voice_state_update(member, before, after)
        cog.cleanup_guild_data.assert_awaited_once_with(gid)

    @pytest.mark.asyncio
    async def test_bot_moved_cancels_autodisconnect(self):
        cog, mock_bot = _make_cog()
        bot_user = MagicMock(id=42)
        mock_bot.user = bot_user
        gid = 6
        chan_old = MagicMock()
        chan_new = MagicMock()
        vc = MagicMock()
        vc.guild = MagicMock(id=gid)
        vc.channel = chan_new
        mock_bot.voice_clients = [vc]

        task = MagicMock()
        cog._gs(gid).auto_disconnect_task = task

        member = MagicMock(id=42)
        member.guild = MagicMock(id=gid)
        before = MagicMock()
        before.channel = chan_old
        after = MagicMock()
        after.channel = chan_new
        await cog.on_voice_state_update(member, before, after)
        task.cancel.assert_called_once()
        assert cog._gs(gid).auto_disconnect_task is None

    @pytest.mark.asyncio
    async def test_human_left_starts_autodisconnect(self):
        cog, mock_bot = _make_cog()
        bot_user = MagicMock(id=42)
        mock_bot.user = bot_user
        gid = 7
        bot_channel = MagicMock()
        # Only bots remain in the channel -> humans == 0.
        botmember = MagicMock(bot=True)
        bot_channel.members = [botmember]
        vc = MagicMock()
        vc.guild = MagicMock(id=gid)
        vc.channel = bot_channel
        mock_bot.voice_clients = [vc]

        cog._gs(gid).mode_247 = False
        cog._gs(gid).auto_disconnect_task = None

        member = MagicMock(id=100)  # a human leaving
        member.guild = MagicMock(id=gid)
        before = MagicMock()
        before.channel = bot_channel
        after = MagicMock()
        other_channel = MagicMock()
        after.channel = other_channel

        sentinel_task = MagicMock()

        def _close_and_return(coro=None, *a, **k):
            # Close the _auto_disconnect coroutine so it doesn't leak a
            # "never awaited" warning, while still returning the sentinel
            # task the assertions below check for.
            if asyncio.iscoroutine(coro):
                coro.close()
            return sentinel_task

        with patch("asyncio.create_task", side_effect=_close_and_return) as mock_create:
            await cog.on_voice_state_update(member, before, after)
        mock_create.assert_called_once()
        assert cog._gs(gid).auto_disconnect_task is sentinel_task

    @pytest.mark.asyncio
    async def test_human_left_skipped_when_247(self):
        cog, mock_bot = _make_cog()
        mock_bot.user = MagicMock(id=42)
        gid = 8
        bot_channel = MagicMock()
        bot_channel.members = []
        vc = MagicMock()
        vc.guild = MagicMock(id=gid)
        vc.channel = bot_channel
        mock_bot.voice_clients = [vc]
        cog._gs(gid).mode_247 = True

        member = MagicMock(id=100)
        member.guild = MagicMock(id=gid)
        before = MagicMock()
        before.channel = bot_channel
        after = MagicMock()
        after.channel = MagicMock()
        with patch("asyncio.create_task") as mock_create:
            await cog.on_voice_state_update(member, before, after)
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_someone_joined_cancels_autodisconnect(self):
        cog, mock_bot = _make_cog()
        mock_bot.user = MagicMock(id=42)
        gid = 9
        bot_channel = MagicMock()
        bot_channel.members = [MagicMock(bot=False)]
        vc = MagicMock()
        vc.guild = MagicMock(id=gid)
        vc.channel = bot_channel
        mock_bot.voice_clients = [vc]

        task = MagicMock()
        cog._gs(gid).auto_disconnect_task = task

        member = MagicMock(id=100)  # human joining
        member.guild = MagicMock(id=gid)
        before = MagicMock()
        before.channel = MagicMock()  # was elsewhere
        after = MagicMock()
        after.channel = bot_channel
        await cog.on_voice_state_update(member, before, after)
        task.cancel.assert_called_once()
        assert cog._gs(gid).auto_disconnect_task is None


class TestAutoDisconnect:
    """_auto_disconnect timer flow."""

    @pytest.mark.asyncio
    async def test_full_disconnect_flow(self, monkeypatch):
        cog, mock_bot = _make_cog()
        gid = 71
        guild = MagicMock()
        guild.me = MagicMock()

        # last_text_channel resolves and has send perm.
        text_chan = MagicMock()
        text_chan.permissions_for.return_value.send_messages = True
        text_chan.send = AsyncMock()
        guild.get_channel.return_value = text_chan
        cog._gs(gid).last_text_channel = 12345

        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.guild = guild
        # After the sleep, still alone.
        empty_channel = MagicMock()
        empty_channel.members = [MagicMock(bot=True)]
        vc.channel = empty_channel
        # Real discord.py removes the VC from bot.voice_clients during
        # disconnect(); the presence guard counts the list AFTER that.
        vc.disconnect = AsyncMock(side_effect=lambda *a, **k: mock_bot.voice_clients.remove(vc))

        cog.cleanup_guild_data = AsyncMock()
        mock_bot.voice_clients = [vc]  # removed by disconnect -> 0 left -> presence resets

        with patch("asyncio.sleep", new=AsyncMock()):
            await cog._auto_disconnect(gid, vc)

        text_chan.send.assert_awaited_once()
        vc.disconnect.assert_awaited_once()
        cog.cleanup_guild_data.assert_awaited_once_with(gid)
        mock_bot.change_presence.assert_awaited()
        assert cog._gs(gid).auto_disconnect_task is None

    @pytest.mark.asyncio
    async def test_fallback_text_channel(self, monkeypatch):
        """No last_text_channel -> walk text_channels for send perm."""
        cog, mock_bot = _make_cog()
        gid = 72
        guild = MagicMock()
        guild.me = MagicMock()
        guild.get_channel.return_value = None
        cog._gs(gid).last_text_channel = None

        good_chan = MagicMock()
        good_chan.permissions_for.return_value.send_messages = True
        good_chan.send = AsyncMock()
        bad_chan = MagicMock()
        bad_chan.permissions_for.return_value.send_messages = False
        guild.text_channels = [bad_chan, good_chan]

        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.guild = guild
        chan = MagicMock()
        chan.members = [MagicMock(bot=True)]
        vc.channel = chan
        vc.disconnect = AsyncMock()
        cog.cleanup_guild_data = AsyncMock()
        mock_bot.voice_clients = [vc, MagicMock()]  # >1 so presence NOT reset

        with patch("asyncio.sleep", new=AsyncMock()):
            await cog._auto_disconnect(gid, vc)
        good_chan.send.assert_awaited_once()
        mock_bot.change_presence.assert_not_called()

    @pytest.mark.asyncio
    async def test_247_enabled_during_wait_cancels(self, monkeypatch):
        cog, mock_bot = _make_cog()
        gid = 73
        guild = MagicMock()
        guild.me = MagicMock()
        guild.get_channel.return_value = None
        guild.text_channels = []
        cog._gs(gid).last_text_channel = None
        cog._gs(gid).mode_247 = True  # set BEFORE sleep so post-sleep check returns

        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.guild = guild
        vc.channel = MagicMock()
        vc.disconnect = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await cog._auto_disconnect(gid, vc)
        vc.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_alone_after_wait(self, monkeypatch):
        """Someone present after wait -> don't disconnect."""
        cog, mock_bot = _make_cog()
        gid = 74
        guild = MagicMock()
        guild.me = MagicMock()
        guild.get_channel.return_value = None
        guild.text_channels = []
        cog._gs(gid).last_text_channel = None

        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.guild = guild
        chan = MagicMock()
        chan.members = [MagicMock(bot=False)]  # a human present
        vc.channel = chan
        vc.disconnect = AsyncMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await cog._auto_disconnect(gid, vc)
        vc.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_connected_skips_warning(self, monkeypatch):
        """vc not connected initially -> skip warning embed, then sleep path."""
        cog, mock_bot = _make_cog()
        gid = 75
        vc = MagicMock()
        vc.is_connected.return_value = False  # skips both blocks
        vc.guild = MagicMock()
        with patch("asyncio.sleep", new=AsyncMock()):
            await cog._auto_disconnect(gid, vc)
        assert cog._gs(gid).auto_disconnect_task is None

    @pytest.mark.asyncio
    async def test_cancelled_during_sleep(self, monkeypatch):
        """CancelledError during sleep -> swallowed, finally clears task."""
        import asyncio as _a

        cog, mock_bot = _make_cog()
        gid = 76
        vc = MagicMock()
        vc.is_connected.return_value = False
        vc.guild = MagicMock()

        async def cancel_sleep(_s):
            raise _a.CancelledError

        with patch("asyncio.sleep", new=cancel_sleep):
            await cog._auto_disconnect(gid, vc)
        assert cog._gs(gid).auto_disconnect_task is None

    @pytest.mark.asyncio
    async def test_discord_exception_logged(self, monkeypatch):
        """A DiscordException is caught and logged."""
        cog, mock_bot = _make_cog()
        gid = 77
        guild = MagicMock()
        guild.me = MagicMock()
        text_chan = MagicMock()
        text_chan.permissions_for.return_value.send_messages = True
        text_chan.send = AsyncMock(side_effect=discord.DiscordException("send fail"))
        guild.get_channel.return_value = text_chan
        cog._gs(gid).last_text_channel = 1

        vc = MagicMock()
        vc.is_connected.return_value = True
        vc.guild = guild
        vc.channel = MagicMock()

        with patch("asyncio.sleep", new=AsyncMock()):
            await cog._auto_disconnect(gid, vc)
        assert cog._gs(gid).auto_disconnect_task is None


class TestSafeDelete:
    """safe_delete path-confinement and retry behavior."""

    @pytest.mark.asyncio
    async def test_blocks_outside_temp(self, monkeypatch):
        cog, _ = _make_cog()
        # A path outside temp should be blocked.
        from pathlib import Path as RealPath

        outside = str(RealPath.cwd() / "not_temp_file.mp3")
        # patch unlink so we can assert it is never called
        with patch("pathlib.Path.unlink") as mock_unlink:
            await cog.safe_delete(outside)
            mock_unlink.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_deleted_returns(self, tmp_path, monkeypatch):
        cog, _ = _make_cog()
        from cogs.music import cog as cogmod

        temp_root = tmp_path / "temp"
        temp_root.mkdir()
        target = temp_root / "gone.mp3"  # doesn't exist

        real_path = cogmod.Path

        def fake_path(arg, *a, **k):
            if arg == "temp":
                return real_path(str(temp_root))
            return real_path(arg, *a, **k)

        with patch.object(cogmod, "Path", side_effect=fake_path):
            await cog.safe_delete(str(target))  # exists() False -> return

    @pytest.mark.asyncio
    async def test_successful_delete(self, tmp_path):
        cog, _ = _make_cog()
        from cogs.music import cog as cogmod

        temp_root = tmp_path / "temp"
        temp_root.mkdir()
        target = temp_root / "song.mp3"
        target.write_text("data")

        real_path = cogmod.Path

        def fake_path(arg, *a, **k):
            if arg == "temp":
                return real_path(str(temp_root))
            return real_path(arg, *a, **k)

        with patch.object(cogmod, "Path", side_effect=fake_path):
            await cog.safe_delete(str(target))
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_oserror_returns(self, tmp_path):
        cog, _ = _make_cog()
        from cogs.music import cog as cogmod

        temp_root = tmp_path / "temp"
        temp_root.mkdir()
        target = temp_root / "song.mp3"
        target.write_text("data")

        real_path = cogmod.Path

        def fake_path(arg, *a, **k):
            if arg == "temp":
                return real_path(str(temp_root))
            return real_path(arg, *a, **k)

        with patch.object(cogmod, "Path", side_effect=fake_path):
            with patch("pathlib.Path.unlink", side_effect=OSError("locked")):
                await cog.safe_delete(str(target))  # OSError -> logged + return

    @pytest.mark.asyncio
    async def test_permission_error_retries_then_gives_up(self, tmp_path, monkeypatch):
        cog, _ = _make_cog()
        from cogs.music import cog as cogmod

        temp_root = tmp_path / "temp"
        temp_root.mkdir()
        target = temp_root / "song.mp3"
        target.write_text("data")

        real_path = cogmod.Path

        def fake_path(arg, *a, **k):
            if arg == "temp":
                return real_path(str(temp_root))
            return real_path(arg, *a, **k)

        with patch.object(cogmod, "Path", side_effect=fake_path):
            with patch("pathlib.Path.unlink", side_effect=PermissionError("locked")):
                with patch("asyncio.sleep", new=AsyncMock()):
                    await cog.safe_delete(str(target))  # 8 retries then give up
        assert target.exists()


class TestGetQueue:
    """get_queue raises in DMs, returns deque otherwise."""

    def test_no_guild_raises(self):
        from discord.ext import commands

        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.guild = None
        with pytest.raises(commands.NoPrivateMessage):
            cog.get_queue(ctx)

    def test_with_guild_returns_deque(self):
        import collections

        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.guild.id = 88
        result = cog.get_queue(ctx)
        assert isinstance(result, collections.deque)


class TestPlayNextWrapper:
    """play_next iterative wrapper + early returns."""

    @pytest.mark.asyncio
    async def test_no_voice_client_returns(self):
        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.voice_client = None
        await cog.play_next(ctx)  # early return, no error

    @pytest.mark.asyncio
    async def test_no_guild_returns(self):
        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.voice_client = MagicMock()
        ctx.guild = None
        await cog.play_next(ctx)

    @pytest.mark.asyncio
    async def test_single_pass_no_retry(self):
        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.voice_client = MagicMock()
        ctx.guild = MagicMock(id=90)
        cog._play_next_once = AsyncMock(return_value=False)
        await cog.play_next(ctx)
        cog._play_next_once.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_until_limit(self):
        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.voice_client = MagicMock()
        ctx.guild = MagicMock(id=91)
        # Always asks to retry -> stops at max_retries cap.
        cog._play_next_once = AsyncMock(return_value=True)
        await cog.play_next(ctx)
        # 1 initial + 10 retries = 11 calls
        assert cog._play_next_once.await_count == 11


class TestPlayNextOnce:
    """_play_next_once: lock, loop replay, queue dispatch, error branches."""

    def _ctx(self, gid=200):
        ctx = MagicMock()
        ctx.guild = MagicMock(id=gid)
        ctx.author.display_name = "User"
        ctx.author.display_avatar.url = "http://avatar"
        ctx.send = AsyncMock()
        vc = MagicMock()
        vc.is_playing.return_value = False
        vc.is_paused.return_value = False
        vc.is_connected.return_value = True
        ctx.voice_client = vc
        ctx.guild.voice_client = vc
        # typing() async context manager. __aexit__ must return a falsy
        # value: the real ctx.typing() does NOT suppress exceptions, and an
        # AsyncMock's default (truthy MagicMock) return would silently swallow
        # an error raised inside the `async with ctx.typing()` block, letting
        # execution fall through to NOW-PLAYING code with player still None.
        cm = MagicMock()
        cm.__aenter__ = AsyncMock()
        cm.__aexit__ = AsyncMock(return_value=False)
        ctx.typing = MagicMock(return_value=cm)
        return ctx, vc

    @pytest.mark.asyncio
    async def test_no_voice_client_returns_false(self):
        cog, _ = _make_cog()
        ctx = MagicMock()
        ctx.voice_client = None
        ctx.guild = MagicMock(id=1)
        result = await cog._play_next_once(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_already_playing_returns_false(self):
        cog, _ = _make_cog()
        ctx, vc = self._ctx(201)
        vc.is_playing.return_value = True
        result = await cog._play_next_once(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_queue_clears_track(self):
        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(202)
        cog._gs(202).current_track = {"title": "old"}
        mock_bot.voice_clients = [vc]  # <=1 -> presence reset
        result = await cog._play_next_once(ctx)
        assert result is False
        assert cog._gs(202).current_track is None
        mock_bot.change_presence.assert_awaited()

    @pytest.mark.asyncio
    async def test_drops_entry_without_url(self):
        import collections

        cog, _ = _make_cog()
        ctx, vc = self._ctx(203)
        cog._gs(203).queue = collections.deque([{"title": "no url"}])
        result = await cog._play_next_once(ctx)
        # Drop-and-continue: returns True so the play_next wrapper re-enters and
        # tries the next track, instead of halting (which would strand every
        # still-valid track queued behind a url-less entry).
        assert result is True
        # Entry dropped.
        assert len(cog._gs(203).queue) == 0

    @pytest.mark.asyncio
    async def test_normal_queue_plays(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(204)
        mock_bot.voice_clients = [vc]
        cog._gs(204).queue = collections.deque([{"url": "http://song"}])

        player = MagicMock()
        player.filename = "f.mp3"
        player.title = "Song"
        player.data = {
            "title": "Song",
            "webpage_url": "http://song",
            "thumbnail": "http://t",
            "duration": 120,
            "url": "http://song",
        }

        with patch("cogs.music.cog.YTDLSource.from_url", new=AsyncMock(return_value=player)):
            with patch("cogs.music.cog.MusicControlView") as mock_view_cls:
                mock_view = MagicMock()
                mock_view_cls.return_value = mock_view
                result = await cog._play_next_once(ctx)

        vc.play.assert_called_once()
        assert cog._gs(204).current_track is not None
        assert result is False

    @pytest.mark.asyncio
    async def test_search_item_resolved(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(205)
        mock_bot.voice_clients = [vc]
        cog._gs(205).queue = collections.deque(
            [{"url": "a song name", "type": "search", "title": "A Song"}]
        )

        player = MagicMock()
        player.filename = "f.mp3"
        player.title = "Song"
        player.data = {
            "title": "Song",
            "webpage_url": "u",
            "thumbnail": None,
            "duration": 60,
            "url": "u",
        }

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(return_value={"webpage_url": "http://resolved"}),
        ):
            with patch("cogs.music.cog.YTDLSource.from_url", new=AsyncMock(return_value=player)):
                with patch("cogs.music.cog.MusicControlView"):
                    result = await cog._play_next_once(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_search_resolution_fails_retries(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(206)
        cog._gs(206).queue = collections.deque(
            [{"url": "bad search", "type": "search", "title": "X"}]
        )

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(return_value=None),
        ):
            result = await cog._play_next_once(ctx)
        assert result is True  # asks to retry next track

    @pytest.mark.asyncio
    async def test_loop_replay_success(self):
        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(207)
        cog._gs(207).loop = True
        cog._gs(207).current_track = {
            "filename": "loop.mp3",
            "data": {"title": "L"},
        }

        player = MagicMock()
        player.title = "L"

        with patch("asyncio.to_thread", new=AsyncMock(return_value=True)):
            with patch("cogs.music.cog.get_ffmpeg_options", return_value={}):
                with patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"):
                    with patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()):
                        with patch("cogs.music.cog.YTDLSource", return_value=player):
                            result = await cog._play_next_once(ctx)
        vc.play.assert_called_once()
        assert result is False

    @pytest.mark.asyncio
    async def test_loop_replay_file_missing_falls_through_to_queue(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(208)
        mock_bot.voice_clients = [vc]
        cog._gs(208).loop = True
        cog._gs(208).current_track = {"filename": "gone.mp3", "data": {"title": "L"}}
        # Empty queue too -> after the missing-file branch falls to queue logic.
        with patch("asyncio.to_thread", new=AsyncMock(return_value=False)):
            result = await cog._play_next_once(ctx)
        assert result is False
        # current_track cleared by empty-queue branch
        assert cog._gs(208).current_track is None

    @pytest.mark.asyncio
    async def test_loop_replay_discord_exception_disables_loop(self):
        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(209)
        mock_bot.voice_clients = [vc]
        cog._gs(209).loop = True
        cog._gs(209).current_track = {"filename": "loop.mp3", "data": {"title": "L"}}

        player = MagicMock()
        player.title = "L"
        # play() raises DiscordException -> cleanup + re-raise -> outer handler
        vc.play.side_effect = discord.DiscordException("play fail")

        # The loop-replay error path schedules safe_delete via
        # _safe_run_coroutine; with the mocked bot loop the coroutine would
        # otherwise leak a "never awaited" warning. Close it on schedule.
        with patch("asyncio.run_coroutine_threadsafe", new=closing_create_task_mock()):
            with patch("asyncio.to_thread", new=AsyncMock(return_value=True)):
                with patch("cogs.music.cog.get_ffmpeg_options", return_value={}):
                    with patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"):
                        with patch(
                            "cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()
                        ):
                            with patch("cogs.music.cog.YTDLSource", return_value=player):
                                await cog._play_next_once(ctx)
        # loop disabled on error
        assert cog._gs(209).loop is False

    @pytest.mark.asyncio
    async def test_play_discord_exception_retries(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(210)
        cog._gs(210).queue = collections.deque([{"url": "http://song"}])

        player = MagicMock()
        player.filename = "f.mp3"
        player.title = "Song"
        player.data = {
            "title": "Song",
            "webpage_url": "u",
            "thumbnail": None,
            "duration": 1,
            "url": "u",
        }
        vc.play.side_effect = discord.DiscordException("nope")

        # The play-error path schedules safe_delete via _safe_run_coroutine;
        # close that coroutine on schedule so it doesn't leak a "never
        # awaited" warning under the mocked bot loop.
        with patch("asyncio.run_coroutine_threadsafe", new=closing_create_task_mock()):
            with patch("cogs.music.cog.YTDLSource.from_url", new=AsyncMock(return_value=player)):
                result = await cog._play_next_once(ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_play_oserror_retries(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(211)
        cog._gs(211).queue = collections.deque([{"url": "http://song"}])

        player = MagicMock()
        player.filename = "f.mp3"
        player.title = "Song"
        player.data = {
            "title": "Song",
            "webpage_url": "u",
            "thumbnail": None,
            "duration": 1,
            "url": "u",
        }
        vc.play.side_effect = OSError("audio")

        # The play-error path schedules safe_delete via _safe_run_coroutine;
        # close that coroutine on schedule so it doesn't leak a "never
        # awaited" warning under the mocked bot loop.
        with patch("asyncio.run_coroutine_threadsafe", new=closing_create_task_mock()):
            with patch("cogs.music.cog.YTDLSource.from_url", new=AsyncMock(return_value=player)):
                result = await cog._play_next_once(ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_from_url_download_error_retries(self):
        import collections

        cog, mock_bot = _make_cog()
        ctx, vc = self._ctx(212)
        cog._gs(212).queue = collections.deque([{"url": "http://song"}])

        import yt_dlp

        with patch(
            "cogs.music.cog.YTDLSource.from_url",
            new=AsyncMock(side_effect=yt_dlp.DownloadError("dl fail")),
        ):
            result = await cog._play_next_once(ctx)
        assert result is True


# ======================================================================
# Regression: shared mark_pause / mark_resume bookkeeping (button-pause bug)
# ======================================================================


class TestMarkPauseResume:
    """Regression tests for Music.mark_pause / Music.mark_resume.

    A button-initiated pause never set ``pause_start``, so resume /
    nowplaying elapsed math (``time.time() - start_time``) kept advancing
    past the real audio position while paused. ``mark_pause`` /
    ``mark_resume`` are the shared helpers used by BOTH the text command
    and the ``MusicControlView`` button; these tests pin their contract.
    """

    def test_mark_pause_records_pause_start(self):
        """mark_pause() must set pause_start — the invariant the bug violated."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 555001
        gs = cog._gs(guild_id)
        t0 = 1000.0
        gs.current_track = {
            "title": "Test Song",
            "url": "https://example.com",
            "start_time": t0,
        }
        gs.pause_start = None

        # Freeze the clock so the recorded instant is exact.
        with patch("cogs.music.cog.time.time", return_value=1234.5):
            cog.mark_pause(guild_id)

        # Without the fix, a button-pause left pause_start as None.
        assert gs.pause_start is not None
        assert gs.pause_start == 1234.5

    def test_mark_resume_shifts_start_time_by_paused_interval(self):
        """mark_resume() advances start_time by the paused duration and clears pause_start."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 555002
        gs = cog._gs(guild_id)
        t0 = 1000.0
        gs.current_track = {
            "title": "Test Song",
            "url": "https://example.com",
            "start_time": t0,
        }
        gs.pause_start = None

        # Deterministic clock: pause at t=1100, resume at t=1130 -> 30s paused.
        clock = iter([1100.0, 1130.0])
        with patch("cogs.music.cog.time.time", side_effect=lambda: next(clock)):
            cog.mark_pause(guild_id)
            assert gs.pause_start == 1100.0
            cog.mark_resume(guild_id)

        # start_time shifted forward by exactly the 30s paused interval, so
        # subsequent (time.time() - start_time) math excludes the pause.
        assert gs.current_track["start_time"] == t0 + 30.0
        assert gs.pause_start is None

    def test_mark_pause_is_idempotent(self):
        """A second mark_pause() must not move the recorded pause_start."""
        from cogs.music.cog import Music

        mock_bot = MagicMock()
        cog = Music(mock_bot)

        guild_id = 555003
        gs = cog._gs(guild_id)
        gs.current_track = {
            "title": "Test Song",
            "url": "https://example.com",
            "start_time": 1000.0,
        }
        gs.pause_start = None

        # First call at t=2000 records the instant; second call at t=2050
        # must be a no-op so the paused interval isn't shrunk.
        clock = iter([2000.0, 2050.0])
        with patch("cogs.music.cog.time.time", side_effect=lambda: next(clock)):
            cog.mark_pause(guild_id)
            first = gs.pause_start
            cog.mark_pause(guild_id)

        assert first == 2000.0
        assert gs.pause_start == 2000.0
