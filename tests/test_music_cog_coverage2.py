"""
Coverage-focused tests for cogs/music/cog.py (region lines ~1800-2653).

These exercise the music command callbacks and helpers in the second half of
the Music cog: the play-search error branches, skip/queue/stop/clear/leave,
volume, 24/7 toggle, shuffle, remove, seek, nowplaying, help, cleanup_cache,
clearcache, error handlers, and on_ready.

Everything is hermetic — discord.py, yt-dlp, voice clients and the filesystem
are mocked. No network, no real sleeps, no real voice.
"""

from __future__ import annotations

import collections
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import yt_dlp

from cogs.music.cog import Music

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_cog():
    """Create a Music cog with a mocked bot (Spotify lazily constructed)."""
    bot = MagicMock()
    bot.loop = MagicMock()
    bot.loop.is_running.return_value = True
    bot.loop.is_closed.return_value = False
    bot.voice_clients = []
    bot.change_presence = AsyncMock()
    with patch("cogs.spotify_handler.SpotifyHandler"):
        cog = Music(bot)
    # Avoid real DB / disk on save scheduling
    cog._schedule_queue_save = MagicMock()
    return cog


class _Typing:
    """Async context manager stand-in for ctx.typing()."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_ctx(guild_id: int = 111222333, *, voice_client=None, author_id: int = 42):
    """Build a mock command Context usable by the music callbacks."""
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.id = guild_id
    ctx.author = MagicMock()
    ctx.author.id = author_id
    ctx.author.display_name = "Tester"
    ctx.author.display_avatar.url = "http://avatar"
    ctx.channel = MagicMock()
    ctx.channel.id = 67890
    ctx.voice_client = voice_client
    ctx.send = AsyncMock()
    ctx.typing = MagicMock(return_value=_Typing())
    return ctx


def make_vc(*, playing=False, paused=False, channel=None):
    vc = MagicMock()
    vc.is_playing.return_value = playing
    vc.is_paused.return_value = paused
    vc.stop = MagicMock()
    vc.play = MagicMock()
    vc.disconnect = AsyncMock()
    vc.channel = channel or MagicMock()
    vc.source = None
    return vc


# ---------------------------------------------------------------------------
# play() — search-error except branches + final play_next gate (1800-1826)
# ---------------------------------------------------------------------------


class TestPlaySearchBranches:
    """Cover the YouTube-search exception handlers and the play_next gate."""

    def _prep_ctx_for_search(self, cog, query="some song"):
        """A ctx where play() reaches the YouTube search block."""
        channel = MagicMock()
        channel.name = "VC"
        perms = MagicMock(connect=True, speak=True)
        channel.permissions_for.return_value = perms
        ctx = make_ctx()
        ctx.author.voice = MagicMock()
        ctx.author.voice.channel = channel
        # Already connected, same channel — no connect/move
        vc = make_vc(playing=False, paused=False, channel=channel)
        ctx.voice_client = vc
        ctx.guild.me = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_search_success_then_starts_play_next(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()
        ctx = self._prep_ctx_for_search(cog)

        info = {
            "title": "Cool Song",
            "webpage_url": "http://yt/cool",
            "thumbnail": "http://thumb",
            "duration": 200,
            "uploader": "Chan",
        }
        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(return_value=info),
        ):
            await cog.play.callback(cog, ctx, query="cool song")

        # Track queued and a "Added to Queue" embed sent.
        assert len(cog._gs(ctx.guild.id).queue) == 1
        ctx.send.assert_awaited()
        # Not playing/paused -> play_next triggered (lines 1821-1826)
        cog.play_next.assert_awaited_once_with(ctx)

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()
        ctx = self._prep_ctx_for_search(cog)

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(return_value=None),
        ):
            # Long query to exercise the truncation path (>100 chars)
            await cog.play.callback(cog, ctx, query="x" * 150)

        ctx.send.assert_awaited()
        # returned before play_next gate
        cog.play_next.assert_not_called()
        assert len(cog._gs(ctx.guild.id).queue) == 0

    @pytest.mark.asyncio
    async def test_search_discord_exception(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()
        ctx = self._prep_ctx_for_search(cog)

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(side_effect=discord.DiscordException("boom")),
        ):
            await cog.play.callback(cog, ctx, query="song")

        ctx.send.assert_awaited()
        cog.play_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_os_error(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()
        ctx = self._prep_ctx_for_search(cog)

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(side_effect=OSError("disk")),
        ):
            await cog.play.callback(cog, ctx, query="song")

        ctx.send.assert_awaited()
        cog.play_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_download_error(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()
        ctx = self._prep_ctx_for_search(cog)

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(side_effect=yt_dlp.DownloadError("nope")),
        ):
            await cog.play.callback(cog, ctx, query="song")

        ctx.send.assert_awaited()
        cog.play_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_success_while_playing_no_play_next(self):
        """When already playing, the final gate must NOT call play_next."""
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()
        ctx = self._prep_ctx_for_search(cog)
        ctx.voice_client.is_playing.return_value = True

        with patch(
            "cogs.music.cog.YTDLSource.search_source",
            new=AsyncMock(return_value={"title": "T", "webpage_url": "u"}),
        ):
            await cog.play.callback(cog, ctx, query="song")

        cog.play_next.assert_not_called()


# ---------------------------------------------------------------------------
# skip (1828-1849)
# ---------------------------------------------------------------------------


class TestSkip:
    @pytest.mark.asyncio
    async def test_skip_while_playing(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        cog._gs(ctx.guild.id).loop = True
        cog._gs(ctx.guild.id).queue.extend([{"title": "a"}, {"title": "b"}])

        await cog.skip.callback(cog, ctx)

        assert cog._gs(ctx.guild.id).loop is False
        ctx.voice_client.stop.assert_called_once()
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_skip_while_paused(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=False, paused=True))
        await cog.skip.callback(cog, ctx)
        ctx.voice_client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_nothing_playing(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=None)
        await cog.skip.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# queue (1851-1902)
# ---------------------------------------------------------------------------


class TestQueueCommand:
    @pytest.mark.asyncio
    async def test_queue_empty(self):
        cog = make_cog()
        ctx = make_ctx()
        await cog.queue.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_queue_with_tracks_and_current(self):
        cog = make_cog()
        ctx = make_ctx()
        gs = cog._gs(ctx.guild.id)
        gs.loop = True
        gs.current_track = {"title": "Now Song"}
        # More than 10 tracks to hit the "+more" path, plus a non-dict item
        # to hit the else branch in the enumerate loop.
        items = [{"title": "T" * 50}] + [{"title": f"s{i}"} for i in range(10)]
        items.append("rawstringtrack" * 5)
        gs.queue.extend(items)

        await cog.queue.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_queue_non_dict_item_short(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.append("shorttrack")
        await cog.queue.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# stop (1904-1933)
# ---------------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_with_vc_and_task_last_client(self):
        cog = make_cog()
        vc = make_vc()
        ctx = make_ctx(voice_client=vc)
        cog.bot.voice_clients = [vc]  # length 1 -> change presence
        gs = cog._gs(ctx.guild.id)
        gs.queue.extend([{"title": "x"}])
        gs.loop = True
        gs.current_track = {"title": "y"}
        task = MagicMock()
        gs.auto_disconnect_task = task

        await cog.stop.callback(cog, ctx)

        assert len(gs.queue) == 0
        assert gs.loop is False
        assert gs.current_track is None
        task.cancel.assert_called_once()
        assert gs.auto_disconnect_task is None
        vc.stop.assert_called_once()
        cog.bot.change_presence.assert_awaited_once()
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_stop_no_vc_multiple_clients(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=None)
        # Two voice clients -> do NOT change presence
        cog.bot.voice_clients = [MagicMock(), MagicMock()]
        await cog.stop.callback(cog, ctx)
        cog.bot.change_presence.assert_not_called()
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# clear (1935-1950)
# ---------------------------------------------------------------------------


class TestClear:
    @pytest.mark.asyncio
    async def test_clear(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.extend([{"title": "a"}, {"title": "b"}])
        await cog.clear.callback(cog, ctx)
        assert len(cog._gs(ctx.guild.id).queue) == 0
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# leave (1952-1990)
# ---------------------------------------------------------------------------


class TestLeave:
    @pytest.mark.asyncio
    async def test_leave_connected_last_client(self):
        cog = make_cog()
        vc = make_vc()
        ctx = make_ctx(voice_client=vc)
        cog.bot.voice_clients = [vc]
        gs = cog._gs(ctx.guild.id)
        gs.queue.extend([{"title": "x"}])
        gs.loop = True
        gs.current_track = {"title": "y"}
        task = MagicMock()
        gs.auto_disconnect_task = task

        await cog.leave.callback(cog, ctx)

        assert len(gs.queue) == 0
        task.cancel.assert_called_once()
        assert gs.auto_disconnect_task is None
        vc.disconnect.assert_awaited_once()
        cog.bot.change_presence.assert_awaited_once()
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_leave_connected_multiple_clients_no_task(self):
        cog = make_cog()
        vc = make_vc()
        ctx = make_ctx(voice_client=vc)
        cog.bot.voice_clients = [vc, MagicMock()]
        await cog.leave.callback(cog, ctx)
        vc.disconnect.assert_awaited_once()
        cog.bot.change_presence.assert_not_called()

    @pytest.mark.asyncio
    async def test_leave_not_connected(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=None)
        await cog.leave.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# volume (1992-2028)
# ---------------------------------------------------------------------------


class TestVolume:
    @pytest.mark.asyncio
    async def test_volume_show_current(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).volume = 0.75
        await cog.volume.callback(cog, ctx, None)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_volume_out_of_range(self):
        cog = make_cog()
        ctx = make_ctx()
        await cog.volume.callback(cog, ctx, 500)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_volume_set_with_active_pcm_source(self):
        cog = make_cog()
        vc = make_vc(playing=True)
        # A real PCMVolumeTransformer instance so the isinstance check passes.
        src = MagicMock(spec=discord.PCMVolumeTransformer)
        src.volume = 0.5
        vc.source = src
        ctx = make_ctx(voice_client=vc)

        await cog.volume.callback(cog, ctx, 100)

        assert cog._gs(ctx.guild.id).volume == 1.0
        assert src.volume == 1.0
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_volume_set_no_source(self):
        cog = make_cog()
        vc = make_vc(playing=True)
        vc.source = None
        ctx = make_ctx(voice_client=vc)
        await cog.volume.callback(cog, ctx, 0)
        assert cog._gs(ctx.guild.id).volume == 0.0
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# 24/7 toggle + error handler (2030-2074)
# ---------------------------------------------------------------------------


class TestMode247:
    @pytest.mark.asyncio
    async def test_enable_with_pending_task(self):
        cog = make_cog()
        ctx = make_ctx()
        gs = cog._gs(ctx.guild.id)
        gs.mode_247 = False
        task = MagicMock()
        gs.auto_disconnect_task = task

        await cog.mode_247_toggle.callback(cog, ctx)

        assert gs.mode_247 is True
        task.cancel.assert_called_once()
        assert gs.auto_disconnect_task is None
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_enable_without_task(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).mode_247 = False
        cog._gs(ctx.guild.id).auto_disconnect_task = None
        await cog.mode_247_toggle.callback(cog, ctx)
        assert cog._gs(ctx.guild.id).mode_247 is True

    @pytest.mark.asyncio
    async def test_disable(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).mode_247 = True
        await cog.mode_247_toggle.callback(cog, ctx)
        assert cog._gs(ctx.guild.id).mode_247 is False
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_error_missing_permissions(self):
        from discord.ext import commands

        cog = make_cog()
        ctx = make_ctx()
        err = commands.MissingPermissions(["manage_channels"])
        await cog.mode_247_error(ctx, err)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_error_reraises_other(self):
        cog = make_cog()
        ctx = make_ctx()
        other = RuntimeError("x")
        with pytest.raises(RuntimeError):
            await cog.mode_247_error(ctx, other)


# ---------------------------------------------------------------------------
# shuffle (2076-2112)
# ---------------------------------------------------------------------------


class TestShuffle:
    @pytest.mark.asyncio
    async def test_shuffle_too_few(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.append({"title": "only"})
        await cog.shuffle.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_shuffle_many_with_preview_more(self):
        cog = make_cog()
        ctx = make_ctx()
        # 5 dict tracks (one long title) + a raw string track for the
        # isinstance else branch; >3 -> "...and N more".
        gs = cog._gs(ctx.guild.id)
        gs.queue.extend(
            [
                {"title": "L" * 40},
                {"title": "b"},
                {"title": "c"},
                {"title": "d"},
                "rawtrack",
            ]
        )
        with patch("cogs.music.cog.random.shuffle"):
            await cog.shuffle.callback(cog, ctx)
        assert len(gs.queue) == 5
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_shuffle_exactly_two(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.extend([{"title": "a"}, {"title": "b"}])
        with patch("cogs.music.cog.random.shuffle"):
            await cog.shuffle.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# remove (2114-2153)
# ---------------------------------------------------------------------------


class TestRemove:
    @pytest.mark.asyncio
    async def test_remove_no_position(self):
        cog = make_cog()
        ctx = make_ctx()
        await cog.remove.callback(cog, ctx, None)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_remove_empty_queue(self):
        cog = make_cog()
        ctx = make_ctx()
        await cog.remove.callback(cog, ctx, 1)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_remove_invalid_position(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.append({"title": "a"})
        await cog.remove.callback(cog, ctx, 5)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_remove_valid_dict(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.extend([{"title": "a"}, {"title": "b"}])
        await cog.remove.callback(cog, ctx, 1)
        assert len(cog._gs(ctx.guild.id).queue) == 1
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_remove_valid_string_item(self):
        cog = make_cog()
        ctx = make_ctx()
        cog._gs(ctx.guild.id).queue.append("rawtrack")
        await cog.remove.callback(cog, ctx, 1)
        assert len(cog._gs(ctx.guild.id).queue) == 0
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# seek (2155-2340)
# ---------------------------------------------------------------------------


class TestSeek:
    def _ctx_playing(self, cog, duration=300):
        vc = make_vc(playing=True)
        ctx = make_ctx(voice_client=vc)
        cog._gs(ctx.guild.id).current_track = {
            "title": "Song",
            "filename": "temp/song.mp3",
            "data": {"duration": duration},
        }
        cog._gs(ctx.guild.id).volume = 0.5
        return ctx

    @pytest.mark.asyncio
    async def test_seek_no_position(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        await cog.seek.callback(cog, ctx, None)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_nothing_playing(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=None)
        await cog.seek.callback(cog, ctx, "1:30")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_invalid_minutes_seconds(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog)
        # seconds >= 60 -> ValueError "Invalid time values"
        await cog.seek.callback(cog, ctx, "1:90")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_invalid_hms(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog)
        await cog.seek.callback(cog, ctx, "1:90:00")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_invalid_format_four_parts(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog)
        await cog.seek.callback(cog, ctx, "1:2:3:4")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_negative_seconds(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog)
        await cog.seek.callback(cog, ctx, "-5")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_non_numeric(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog)
        await cog.seek.callback(cog, ctx, "abc")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_no_track_info(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        cog._gs(ctx.guild.id).current_track = None
        await cog.seek.callback(cog, ctx, "30")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_unknown_duration(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        cog._gs(ctx.guild.id).current_track = {
            "title": "Song",
            "filename": "temp/song.mp3",
            "data": {"duration": None},
        }
        await cog.seek.callback(cog, ctx, "30")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_beyond_duration(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=100)
        await cog.seek.callback(cog, ctx, "200")
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_file_missing(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=300)
        with patch("pathlib.Path.exists", return_value=False):
            await cog.seek.callback(cog, ctx, "1:00")
        assert cog._gs(ctx.guild.id).fixing is False
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_success(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=300)
        cog._safe_run_coroutine = MagicMock()
        cog.play_next = AsyncMock()
        cog.safe_delete = AsyncMock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio"),
            patch("cogs.music.cog.YTDLSource") as MockSrc,
        ):
            player = MagicMock()
            MockSrc.return_value = player
            await cog.seek.callback(cog, ctx, "1:00")

        ctx.voice_client.play.assert_called_once()
        ctx.send.assert_awaited()
        # Exercise the after_seek callback that play() received.
        after = ctx.voice_client.play.call_args.kwargs["after"]
        # Live VC connected & not playing -> schedule play_next + delete
        ctx.guild.voice_client = ctx.voice_client
        ctx.voice_client.is_connected.return_value = True
        ctx.voice_client.is_playing.return_value = False
        ctx.voice_client.is_paused.return_value = False
        after(None)
        assert cog._gs(ctx.guild.id).fixing is False

    @pytest.mark.asyncio
    async def test_seek_after_callback_disconnected(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=300)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio"),
            patch("cogs.music.cog.YTDLSource", return_value=MagicMock()),
        ):
            await cog.seek.callback(cog, ctx, "1:00")

        after = ctx.voice_client.play.call_args.kwargs["after"]
        # No live VC -> deletion branch (loop=False) then return
        ctx.guild.voice_client = None
        # vc_seek (captured) reports disconnected
        ctx.voice_client.is_connected.return_value = False
        cog._gs(ctx.guild.id).loop = False
        after(None)
        cog._safe_run_coroutine.assert_called()

    @pytest.mark.asyncio
    async def test_seek_after_callback_already_playing_with_error(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=300)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()
        cog._gs(ctx.guild.id).loop = True  # skip deletion branch

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio"),
            patch("cogs.music.cog.YTDLSource", return_value=MagicMock()),
        ):
            await cog.seek.callback(cog, ctx, "1:00")

        after = ctx.voice_client.play.call_args.kwargs["after"]
        ctx.guild.voice_client = ctx.voice_client
        ctx.voice_client.is_connected.return_value = True
        ctx.voice_client.is_playing.return_value = True  # already playing -> return
        after("some error")
        # play_next must not be scheduled in this branch; but the error log path ran.
        cog._safe_run_coroutine.assert_not_called()

    @pytest.mark.asyncio
    async def test_seek_play_raises(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=300)
        ctx.voice_client.play.side_effect = RuntimeError("play fail")

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio"),
            patch("cogs.music.cog.YTDLSource") as MockSrc,
        ):
            player = MagicMock()
            MockSrc.return_value = player
            await cog.seek.callback(cog, ctx, "1:00")

        # play() failure -> cleanup + outer except -> error embed
        assert cog._gs(ctx.guild.id).fixing is False
        player.cleanup.assert_called_once()
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_seek_play_raises_cleanup_also_raises(self):
        cog = make_cog()
        ctx = self._ctx_playing(cog, duration=300)
        ctx.voice_client.play.side_effect = RuntimeError("play fail")

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio"),
            patch("cogs.music.cog.YTDLSource") as MockSrc,
        ):
            player = MagicMock()
            player.cleanup.side_effect = RuntimeError("cleanup fail")
            MockSrc.return_value = player
            await cog.seek.callback(cog, ctx, "1:00")

        assert cog._gs(ctx.guild.id).fixing is False
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# nowplaying (2342-2412)
# ---------------------------------------------------------------------------


class TestNowPlaying:
    @pytest.mark.asyncio
    async def test_np_no_track(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        cog._gs(ctx.guild.id).current_track = None
        await cog.nowplaying.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_np_nothing_playing(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=None)
        cog._gs(ctx.guild.id).current_track = {"title": "x", "data": {}}
        await cog.nowplaying.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_np_playing(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        cog._gs(ctx.guild.id).current_track = {
            "title": "Song",
            "start_time": 0,
            "data": {
                "duration": 300,
                "webpage_url": "http://yt",
                "thumbnail": "http://thumb",
            },
        }
        await cog.nowplaying.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_np_paused_with_pause_start(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=False, paused=True))
        gs = cog._gs(ctx.guild.id)
        gs.pause_start = 50.0
        gs.current_track = {
            "title": "Song",
            "start_time": 10.0,
            "data": {"duration": 300},
        }
        await cog.nowplaying.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_np_no_duration_no_thumbnail(self):
        cog = make_cog()
        ctx = make_ctx(voice_client=make_vc(playing=True))
        cog._gs(ctx.guild.id).current_track = {
            "title": "Song",
            "start_time": 0,
            "data": {},
        }
        await cog.nowplaying.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# _is_owner + help (2422-2504)
# ---------------------------------------------------------------------------


class TestHelpAndOwner:
    def test_is_owner_no_owner_configured(self):
        cog = make_cog()
        cog.OWNER_ID = 0
        ctx = make_ctx(author_id=123)
        assert cog._is_owner(ctx) is False

    def test_is_owner_match(self):
        cog = make_cog()
        cog.OWNER_ID = 555
        ctx = make_ctx(author_id=555)
        assert cog._is_owner(ctx) is True

    def test_is_owner_mismatch(self):
        cog = make_cog()
        cog.OWNER_ID = 555
        ctx = make_ctx(author_id=1)
        assert cog._is_owner(ctx) is False

    @pytest.mark.asyncio
    async def test_help_non_owner_with_avatar(self):
        cog = make_cog()
        cog.OWNER_ID = 0  # not owner
        ctx = make_ctx(author_id=1)
        cog.bot.user = MagicMock()
        cog.bot.user.display_avatar.url = "http://botavatar"
        await cog.help.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_help_owner_no_avatar(self):
        cog = make_cog()
        cog.OWNER_ID = 777
        ctx = make_ctx(author_id=777)
        cog.bot.user = None  # skip avatar branch
        await cog.help.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# cleanup_cache (2506-2581) + clearcache (2583-2603)
# ---------------------------------------------------------------------------


class TestCleanupCache:
    @pytest.mark.asyncio
    async def test_cleanup_cache_no_temp_dir(self):
        cog = make_cog()
        with patch("pathlib.Path.exists", return_value=False):
            count, freed = await cog.cleanup_cache()
        assert count == 0
        assert freed == 0

    @pytest.mark.asyncio
    async def test_cleanup_cache_deletes_and_skips(self, tmp_path, monkeypatch):
        """Real temp dir: in-use file skipped, dir skipped, stale file deleted,
        recent file kept, and a stat-failing file skipped."""
        import os
        import time as _time

        from cogs.music import cog as cog_module

        cog = make_cog()

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        # In-use file (registered as a guild's current_track)
        in_use = temp_dir / "inuse.mp3"
        in_use.write_text("x")
        cog._gs(1).current_track = {"filename": str(in_use)}

        # A subdirectory -> is_dir() skip branch
        (temp_dir / "subdir").mkdir()

        # Stale file -> should be deleted
        stale = temp_dir / "stale.mp3"
        stale.write_text("stale-content")

        # Recent file -> within grace window, kept
        recent = temp_dir / "recent.mp3"
        recent.write_text("recent")

        old = _time.time() - 1000
        os.utime(stale, (old, old))
        os.utime(in_use, (old, old))
        # leave `recent` mtime as "now" so it is skipped

        # Point the module's Path("temp") at our tmp dir.
        real_path = cog_module.Path

        def fake_path(arg="temp", *a, **k):
            if arg == "temp":
                return real_path(str(temp_dir))
            return real_path(arg, *a, **k)

        monkeypatch.setattr(cog_module, "Path", fake_path)

        count, freed = await cog.cleanup_cache()

        assert count >= 1
        assert freed > 0
        assert not stale.exists()
        assert recent.exists()
        assert in_use.exists()

    @pytest.mark.asyncio
    async def test_clearcache_bytes(self):
        cog = make_cog()
        ctx = make_ctx()
        cog.cleanup_cache = AsyncMock(return_value=(2, 500))
        await cog.clearcache.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_clearcache_kb(self):
        cog = make_cog()
        ctx = make_ctx()
        cog.cleanup_cache = AsyncMock(return_value=(3, 5000))
        await cog.clearcache.callback(cog, ctx)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_clearcache_mb(self):
        cog = make_cog()
        ctx = make_ctx()
        cog.cleanup_cache = AsyncMock(return_value=(1, 5 * 1024 * 1024))
        await cog.clearcache.callback(cog, ctx)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# join.error / play.error (2607-2635)
# ---------------------------------------------------------------------------


class TestErrorHandlers:
    @pytest.mark.asyncio
    async def test_join_error_bot_missing_perms(self):
        from discord.ext import commands

        cog = make_cog()
        ctx = make_ctx()
        err = commands.BotMissingPermissions(["connect", "speak"])
        await cog.join_error(ctx, err)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_join_error_reraise(self):
        cog = make_cog()
        ctx = make_ctx()
        with pytest.raises(ValueError):
            await cog.join_error(ctx, ValueError("x"))

    @pytest.mark.asyncio
    async def test_play_error_bot_missing_perms(self):
        from discord.ext import commands

        cog = make_cog()
        ctx = make_ctx()
        err = commands.BotMissingPermissions(["connect"])
        await cog.play_error(ctx, err)
        ctx.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_play_error_reraise(self):
        cog = make_cog()
        ctx = make_ctx()
        with pytest.raises(KeyError):
            await cog.play_error(ctx, KeyError("x"))


# ---------------------------------------------------------------------------
# on_ready (2637-2648) + setup (2651-2653)
# ---------------------------------------------------------------------------


class TestOnReadyAndSetup:
    @pytest.mark.asyncio
    async def test_on_ready_first_time_cleans(self):
        cog = make_cog()
        cog._cleaned_temp_once = False
        cog.cleanup_cache = AsyncMock(return_value=(1, 100))
        cog.bot.user = "BotName"
        await cog.on_ready()
        assert cog._cleaned_temp_once is True
        cog.cleanup_cache.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_ready_already_cleaned(self):
        cog = make_cog()
        cog._cleaned_temp_once = True
        cog.cleanup_cache = AsyncMock(return_value=(0, 0))
        cog.bot.user = "BotName"
        await cog.on_ready()
        cog.cleanup_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_adds_cog(self):
        from cogs.music.cog import setup

        bot = MagicMock()
        bot.add_cog = AsyncMock()
        with patch("cogs.spotify_handler.SpotifyHandler"):
            await setup(bot)
        bot.add_cog.assert_awaited_once()
        added = bot.add_cog.call_args.args[0]
        assert isinstance(added, Music)


# ===========================================================================
# RESIDUAL MOP-UP: scattered error/except + edge-case lines across the cog.
# Appended batch driving the lines other agents left uncovered.
# ===========================================================================


class TestPeriodicTempCleanupResidual:
    """_periodic_temp_cleanup inner helpers: bad-filename skip, resolve OSError,
    unlink PermissionError/OSError (lines 112, 115, 128-129, 140-141)."""

    @pytest.mark.asyncio
    async def test_collect_in_use_resolve_raises_skips(self, tmp_path, monkeypatch):
        """A guild current_track whose Path.resolve() raises is skipped in
        _collect_in_use (lines 112, 115)."""
        import asyncio as _a

        from cogs.music import cog as cogmod

        cog = make_cog()

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        # current_track filename whose resolve() will raise.
        cog._gs(1).current_track = {"filename": str(temp_dir / "bad.mp3")}

        real_path = cogmod.Path
        real_resolve = real_path.resolve

        def boom_resolve(self, *a, **k):
            if self.name == "bad.mp3":
                raise ValueError("reserved name")
            return real_resolve(self, *a, **k)

        def fake_path(arg="temp", *a, **k):
            if arg == "temp":
                return real_path(str(temp_dir))
            return real_path(arg, *a, **k)

        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with (
            patch.object(cogmod, "Path", side_effect=fake_path),
            patch("asyncio.sleep", new=fake_sleep),
            patch("pathlib.Path.resolve", boom_resolve),
        ):
            await cog._periodic_temp_cleanup()  # must not raise

    @pytest.mark.asyncio
    async def test_worker_resolve_oserror_and_unlink_error(self, tmp_path, monkeypatch):
        """Worker: a temp entry whose .resolve() raises OSError is skipped
        (lines 128-129); a stale file whose unlink raises is swallowed
        (lines 140-141)."""
        import asyncio as _a

        from cogs.music import cog as cogmod

        cog = make_cog()
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        # File whose resolve() raises OSError -> worker continue (128-129).
        weird = temp_dir / "weird.mp3"
        weird.write_text("x")

        # Stale file that passes resolve but whose unlink raises -> 140-141.
        stale = temp_dir / "stale.mp3"
        stale.write_text("data")
        import os

        os.utime(stale, (0, 0))  # epoch -> stale

        real_path = cogmod.Path
        real_resolve = real_path.resolve

        def boom_resolve(self, *a, **k):
            if self.name == "weird.mp3":
                raise OSError("cannot resolve")
            return real_resolve(self, *a, **k)

        def fake_path(arg="temp", *a, **k):
            if arg == "temp":
                return real_path(str(temp_dir))
            return real_path(arg, *a, **k)

        sleeps = {"n": 0}

        async def fake_sleep(_secs):
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise _a.CancelledError

        with (
            patch.object(cogmod, "Path", side_effect=fake_path),
            patch("asyncio.sleep", new=fake_sleep),
            patch("pathlib.Path.resolve", boom_resolve),
            patch("pathlib.Path.unlink", side_effect=OSError("busy")),
        ):
            await cog._periodic_temp_cleanup()

        # Both survive: weird skipped via resolve OSError, stale unlink blocked.
        assert weird.exists()
        assert stale.exists()


class TestSafeRunCoroutineResidual:
    """_safe_run_coroutine schedules on the loop (lines 250-251) and swallows
    RuntimeError/AttributeError (lines 252-254)."""

    def test_schedules_on_running_loop(self):
        cog = make_cog()
        fut = MagicMock()
        with patch("asyncio.run_coroutine_threadsafe", return_value=fut) as mock_run:

            async def _c():
                return None

            coro = _c()
            cog._safe_run_coroutine(coro)
            mock_run.assert_called_once()
            fut.add_done_callback.assert_called_once()
            coro.close()

    def test_runtime_error_swallowed(self):
        cog = make_cog()
        # bot.loop access raising RuntimeError -> except (RuntimeError,...) pass.
        type(cog.bot).loop = property(lambda self: (_ for _ in ()).throw(RuntimeError("loop gone")))
        try:

            async def _c():
                return None

            coro = _c()
            cog._safe_run_coroutine(coro)  # must not raise
            coro.close()
        finally:
            # Restore so other tests using this MagicMock class aren't affected.
            del type(cog.bot).loop


class TestSaveQueueJsonSyncResidual:
    """_save_queue_json_sync OSError on rename cleans up temp file (line 431)."""

    def test_write_then_rename_oserror_unlinks_tmp(self, tmp_path):
        from cogs.music import cog as cogmod

        cog = make_cog()
        gid = 4242
        snap = {"queue": [{"t": "x"}], "volume": 0.5, "loop": False, "mode_247": False}

        def fake_path(arg, *a, **k):
            return tmp_path / str(arg).replace("/", "_")

        # Pre-create the .tmp file so the cleanup unlink (line 431) executes.
        tmp_file = tmp_path / f"data_queue_{gid}.json.tmp"
        tmp_file.write_text("partial")

        with patch.object(cogmod, "Path", side_effect=fake_path):
            # Patch the real pathlib replace so the write succeeds but the
            # atomic rename raises OSError -> except block reconstructs the
            # tmp path and unlinks it (lines 425-431).
            with patch("pathlib.Path.replace", side_effect=OSError("rename fail")):
                cog._save_queue_json_sync(gid, snapshot=snap)

        # The temp file got cleaned up by the except block.
        assert not tmp_file.exists()


class TestOnVoiceStateUpdateResidual:
    """on_voice_state_update: the `if not bot_channel: continue` guard (line 611)
    when vc.channel becomes falsy after the someone-left check."""

    @pytest.mark.asyncio
    async def test_bot_channel_falsy_continues(self):
        cog = make_cog()
        cog.bot.user = MagicMock(id=42)
        gid = 500

        # vc.channel is a property that is truthy at the top-level guards but
        # the captured ``bot_channel = vc.channel`` reads falsy. We model this
        # with a channel that compares equal to before.channel yet is falsy in
        # a bool context after capture. Simplest: a channel object that is
        # truthy for the first guards (hasattr/channel checks use it directly)
        # and then make the captured value falsy by having __bool__ False.
        class FalsyChannel:
            members = []
            __hash__ = object.__hash__  # identity-equality below -> identity hash

            def __eq__(self, other):
                return other is self

            def __bool__(self):
                return False

        chan = FalsyChannel()

        vc = MagicMock()
        vc.guild = MagicMock(id=gid)
        vc.channel = chan
        cog.bot.voice_clients = [vc]
        cog._gs(gid).mode_247 = False

        member = MagicMock(id=100)
        member.guild = MagicMock(id=gid)
        before = MagicMock()
        before.channel = chan  # before == vc.channel
        after = MagicMock()
        after.channel = MagicMock()  # left bot's channel

        with patch("asyncio.create_task") as mock_create:
            await cog.on_voice_state_update(member, before, after)
        # bot_channel falsy -> continue before auto-disconnect arm.
        mock_create.assert_not_called()


def _play_ctx(cog, gid=900):
    """A ctx wired for _play_next_once (loop/queue paths)."""
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
    cm = MagicMock()
    cm.__aenter__ = AsyncMock()
    cm.__aexit__ = AsyncMock(return_value=False)
    ctx.typing = MagicMock(return_value=cm)
    return ctx, vc


class TestPlayNextLockResidual:
    """_play_next_once lock acquisition timeout/cancel + done-callback release
    (lines 838-850, 868-880)."""

    @pytest.mark.asyncio
    async def test_timeout_path_releases_abandoned_lock(self):
        """wait_for TimeoutError -> _abandoned_flag set, return False; then the
        still-pending helper acquires the (now-free) lock and the done-callback
        releases it because abandoned & no-exception (lines 868-872, 840-841,
        847-848)."""
        import asyncio as _a

        cog = make_cog()
        gid = 901
        ctx, vc = _play_ctx(cog, gid)
        lock = cog._gs(gid).play_lock
        # Pre-hold the lock so the helper cannot acquire during the call.
        await lock.acquire()

        real_wait_for = _a.wait_for

        async def fake_wait_for(awaitable, timeout):
            # Cancel the shield so the awaited future stops, but keep the inner
            # _acquire_task alive (shield semantics) and raise TimeoutError.
            if isinstance(awaitable, _a.Future):
                awaitable.cancel()
            raise TimeoutError

        with patch("cogs.music.cog.asyncio.wait_for", new=fake_wait_for):
            result = await cog._play_next_once(ctx)
        assert result is False

        # Release our hold so the pending helper task can acquire it.
        lock.release()
        # Let the helper run + its done-callback fire.
        for _ in range(5):
            await _a.sleep(0)
        # The done-callback should have released the abandoned lock.
        assert not lock.locked()
        _ = real_wait_for

    @pytest.mark.asyncio
    async def test_cancelled_path_reraises_and_releases(self):
        """wait_for CancelledError -> flag set + re-raise; helper later acquires
        and the abandoned-release callback frees it (lines 873-880)."""
        import asyncio as _a

        cog = make_cog()
        gid = 902
        ctx, vc = _play_ctx(cog, gid)
        lock = cog._gs(gid).play_lock
        await lock.acquire()

        async def fake_wait_for(awaitable, timeout):
            if isinstance(awaitable, _a.Future):
                awaitable.cancel()
            raise _a.CancelledError

        with patch("cogs.music.cog.asyncio.wait_for", new=fake_wait_for):
            with pytest.raises(_a.CancelledError):
                await cog._play_next_once(ctx)

        lock.release()
        for _ in range(5):
            await _a.sleep(0)
        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_helper_cancelled_callback_returns_early(self):
        """If the acquire helper task is cancelled before acquiring, the
        done-callback's ``if task.cancelled(): return`` (line 838) runs."""
        import asyncio as _a

        cog = make_cog()
        gid = 903
        ctx, vc = _play_ctx(cog, gid)
        lock = cog._gs(gid).play_lock
        # Hold the lock so the helper blocks on acquire().
        await lock.acquire()

        captured = {}
        real_create_task = _a.create_task

        def capture_create_task(coro, *a, **k):
            t = real_create_task(coro, *a, **k)
            captured["task"] = t
            return t

        async def fake_wait_for(awaitable, timeout):
            # Cancel the inner helper task itself (not just the shield) so the
            # task ends cancelled -> done-callback hits line 838.
            helper = captured.get("task")
            if helper is not None:
                helper.cancel()
            raise TimeoutError

        with (
            patch("cogs.music.cog.asyncio.create_task", side_effect=capture_create_task),
            patch("cogs.music.cog.asyncio.wait_for", new=fake_wait_for),
        ):
            result = await cog._play_next_once(ctx)
        assert result is False
        for _ in range(5):
            await _a.sleep(0)
        # Our hold is still active; helper was cancelled before acquiring.
        assert lock.locked()
        lock.release()

    @pytest.mark.asyncio
    async def test_helper_raises_after_acquire_releases(self):
        """Helper acquires the lock then raises -> callback's elif branch
        (lines 842-845) releases the held lock."""
        import asyncio as _a

        cog = make_cog()
        gid = 904
        ctx, vc = _play_ctx(cog, gid)
        lock = cog._gs(gid).play_lock

        captured = {}
        real_create_task = _a.create_task

        # Replace the acquire coroutine: acquire the real lock, then raise so
        # the task finishes with an exception while holding the lock.
        def capture_create_task(coro, *a, **k):
            # Close the original acquire helper coroutine; substitute ours.
            coro.close()

            async def acquire_then_raise():
                await lock.acquire()
                raise RuntimeError("post-acquire boom")

            t = real_create_task(acquire_then_raise())
            captured["task"] = t
            return t

        async def fake_wait_for(awaitable, timeout):
            # Let the helper actually run to completion (acquire + raise).
            helper = captured.get("task")
            if helper is not None:
                with contextlib.suppress(Exception):
                    await helper
            raise TimeoutError

        with (
            patch("cogs.music.cog.asyncio.create_task", side_effect=capture_create_task),
            patch("cogs.music.cog.asyncio.wait_for", new=fake_wait_for),
        ):
            result = await cog._play_next_once(ctx)
        assert result is False
        for _ in range(5):
            await _a.sleep(0)
        # The done-callback released the lock the helper had grabbed.
        assert not lock.locked()


class TestLoopReplayAfterCallback:
    """The loop-replay branch's after_playing_loop callback + play() cleanup
    (lines 886, 906-907, 926-979, 961-962)."""

    def _loop_ctx(self, cog, gid=950):
        ctx, vc = _play_ctx(cog, gid)
        cog._gs(gid).loop = True
        cog._gs(gid).current_track = {
            "filename": "temp/loopme.mp3",
            "data": {"title": "L"},
        }
        cog._gs(gid).volume = 0.7
        return ctx, vc

    @pytest.mark.asyncio
    async def test_loop_replay_invokes_after_callback(self):
        cog = make_cog()
        gid = 950
        ctx, vc = self._loop_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()
        cog.play_next = AsyncMock()

        player = MagicMock()
        player.title = "L"

        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=True)),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            result = await cog._play_next_once(ctx)

        assert result is False
        vc.play.assert_called_once()
        after = vc.play.call_args.kwargs["after"]

        # Drive the after callback: live VC connected, not playing, loop OFF now
        # -> deletes file then schedules play_next (lines 935-950).
        cog._gs(gid).loop = False
        cog._gs(gid).fixing = False
        ctx.guild.voice_client = vc
        vc.is_connected.return_value = True
        vc.is_playing.return_value = False
        vc.is_paused.return_value = False
        after("an error")  # error branch (943-944) too
        # safe_delete + play_next both scheduled via _safe_run_coroutine
        assert cog._safe_run_coroutine.call_count >= 2

    @pytest.mark.asyncio
    async def test_loop_after_callback_fixing_skips(self):
        cog = make_cog()
        gid = 951
        ctx, vc = self._loop_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()

        player = MagicMock()
        player.title = "L"
        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=True)),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            await cog._play_next_once(ctx)
        after = vc.play.call_args.kwargs["after"]
        # fixing True -> early return (line 926-927)
        cog._gs(gid).fixing = True
        after(None)
        cog._safe_run_coroutine.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_after_callback_disconnected_returns(self):
        cog = make_cog()
        gid = 952
        ctx, vc = self._loop_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()

        player = MagicMock()
        player.title = "L"
        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=True)),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            await cog._play_next_once(ctx)
        after = vc.play.call_args.kwargs["after"]
        # Live VC None -> return at lines 935-937
        cog._gs(gid).fixing = False
        ctx.guild.voice_client = None
        after(None)
        cog._safe_run_coroutine.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_after_callback_already_playing_returns(self):
        cog = make_cog()
        gid = 953
        ctx, vc = self._loop_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()

        player = MagicMock()
        player.title = "L"
        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=True)),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            await cog._play_next_once(ctx)
        after = vc.play.call_args.kwargs["after"]
        cog._gs(gid).fixing = False
        cog._gs(gid).loop = True  # loop still on -> skip delete branch (939)
        ctx.guild.voice_client = vc
        vc.is_connected.return_value = True
        vc.is_playing.return_value = True  # already playing -> return (947-948)
        after(None)
        # play_next NOT scheduled (returned before line 950)
        cog._safe_run_coroutine.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_replay_play_raises_then_cleanup_raises(self):
        """play() raises -> player.cleanup() also raises -> logged (961-962),
        re-raised -> outer DiscordException handler disables loop (974-976)."""
        cog = make_cog()
        gid = 954
        ctx, vc = self._loop_ctx(cog, gid)
        vc.play.side_effect = discord.DiscordException("play fail")

        player = MagicMock()
        player.title = "L"
        player.cleanup.side_effect = RuntimeError("cleanup boom")
        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=True)),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            await cog._play_next_once(ctx)
        assert cog._gs(gid).loop is False

    @pytest.mark.asyncio
    async def test_loop_replay_oserror_disables_loop(self):
        """play() raises OSError -> cleanup + re-raise -> OSError handler (977-979)."""
        cog = make_cog()
        gid = 955
        ctx, vc = self._loop_ctx(cog, gid)
        vc.play.side_effect = OSError("audio fail")

        player = MagicMock()
        player.title = "L"
        with (
            patch("asyncio.to_thread", new=AsyncMock(return_value=True)),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            await cog._play_next_once(ctx)
        assert cog._gs(gid).loop is False

    @pytest.mark.asyncio
    async def test_loop_replay_vc_disconnected_before_play(self):
        """Inside loop branch, voice_client disconnected -> return False (906-907)."""
        cog = make_cog()
        gid = 956
        ctx, vc = self._loop_ctx(cog, gid)
        # voice_client is present at top but is_connected False inside replay.
        vc.is_connected.return_value = False
        with patch("asyncio.to_thread", new=AsyncMock(return_value=True)):
            result = await cog._play_next_once(ctx)
        assert result is False


class TestPlayNextHandoffCleanup:
    """Normal-queue play() OSError cleanup also-raises path (lines 1124-1125)."""

    @pytest.mark.asyncio
    async def test_play_oserror_cleanup_raises_logged(self):
        import collections as _c

        cog = make_cog()
        gid = 960
        ctx, vc = _play_ctx(cog, gid)
        cog._gs(gid).queue = _c.deque([{"url": "http://song"}])
        vc.play.side_effect = OSError("audio")

        player = MagicMock()
        player.filename = "f.mp3"
        player.title = "Song"
        player.cleanup.side_effect = RuntimeError("cleanup boom")
        player.data = {
            "title": "Song",
            "webpage_url": "u",
            "thumbnail": None,
            "duration": 1,
            "url": "u",
        }
        with patch("cogs.music.cog.YTDLSource.from_url", new=AsyncMock(return_value=player)):
            result = await cog._play_next_once(ctx)
        # OSError handler asked for retry.
        assert result is True


class TestFixResidual:
    """fix command success path + after_playing_fix callback + play cleanup
    (lines 1463-1490)."""

    def _fix_ctx(self, cog, gid=1000, *, paused=False):
        ctx = make_ctx(guild_id=gid)
        vc = make_vc(playing=not paused, paused=paused)
        vc.is_connected = MagicMock(return_value=True)
        ctx.voice_client = vc
        ctx.guild.me = MagicMock()
        ctx.guild.voice_client = vc
        # author in a voice channel for reconnect
        chan = MagicMock()
        chan.connect = AsyncMock()
        ctx.author.voice = MagicMock()
        ctx.author.voice.channel = chan
        cog._gs(gid).current_track = {
            "title": "Song",
            "filename": "temp/song.mp3",
            "data": {"title": "Song", "duration": 200},
            "start_time": 100.0,
        }
        cog._gs(gid).volume = 0.5
        return ctx, vc, chan

    @pytest.mark.asyncio
    async def test_fix_success_and_after_callback(self):
        cog = make_cog()
        gid = 1000
        ctx, vc, chan = self._fix_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()
        cog.play_next = AsyncMock()

        fix_msg = MagicMock()
        fix_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=fix_msg)

        with (
            patch("cogs.music.cog.Path") as MockPath,
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=MagicMock()),
        ):
            MockPath.return_value.exists.return_value = True
            await cog.fix.callback(cog, ctx)

        vc.play.assert_called_once()
        fix_msg.edit.assert_awaited()
        after = vc.play.call_args.kwargs["after"]

        # Drive after_playing_fix: fixing False, live vc connected, loop off
        # -> safe_delete + play_next (1466-1479).
        cog._gs(gid).fixing = False
        cog._gs(gid).loop = False
        ctx.guild.voice_client = vc
        vc.is_connected.return_value = True
        after("err")
        assert cog._safe_run_coroutine.call_count >= 2

    @pytest.mark.asyncio
    async def test_fix_after_callback_fixing_skips(self):
        cog = make_cog()
        gid = 1001
        ctx, vc, chan = self._fix_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()
        fix_msg = MagicMock()
        fix_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=fix_msg)

        with (
            patch("cogs.music.cog.Path") as MockPath,
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=MagicMock()),
        ):
            MockPath.return_value.exists.return_value = True
            await cog.fix.callback(cog, ctx)
        after = vc.play.call_args.kwargs["after"]
        cog._gs(gid).fixing = True  # -> early return (1463-1464)
        after(None)
        cog._safe_run_coroutine.assert_not_called()

    @pytest.mark.asyncio
    async def test_fix_after_callback_disconnected_deletes(self):
        cog = make_cog()
        gid = 1002
        ctx, vc, chan = self._fix_ctx(cog, gid)
        cog._safe_run_coroutine = MagicMock()
        cog.safe_delete = AsyncMock()
        fix_msg = MagicMock()
        fix_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=fix_msg)

        with (
            patch("cogs.music.cog.Path") as MockPath,
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=MagicMock()),
        ):
            MockPath.return_value.exists.return_value = True
            await cog.fix.callback(cog, ctx)
        after = vc.play.call_args.kwargs["after"]
        cog._gs(gid).fixing = False
        cog._gs(gid).loop = False
        ctx.guild.voice_client = None  # disconnected -> delete + return (1467-1471)
        after(None)
        cog._safe_run_coroutine.assert_called_once()

    @pytest.mark.asyncio
    async def test_fix_play_raises_cleanup_also_raises(self):
        """voice_client_fix.play() raises -> cleanup raises too (1489-1490) ->
        re-raise -> outer DiscordException handler edits error embed."""
        cog = make_cog()
        gid = 1003
        ctx, vc, chan = self._fix_ctx(cog, gid)
        vc.play.side_effect = discord.DiscordException("play fail")
        fix_msg = MagicMock()
        fix_msg.edit = AsyncMock()
        ctx.send = AsyncMock(return_value=fix_msg)

        player = MagicMock()
        player.cleanup.side_effect = RuntimeError("cleanup boom")
        with (
            patch("cogs.music.cog.Path") as MockPath,
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio", return_value=MagicMock()),
            patch("cogs.music.cog.YTDLSource", return_value=player),
        ):
            MockPath.return_value.exists.return_value = True
            await cog.fix.callback(cog, ctx)
        # Outer handler edited an error embed.
        fix_msg.edit.assert_awaited()
        assert cog._gs(gid).fixing is False


class TestPlayMoveAndSpotifyParse:
    """play(): move-to perm denied (1690, 1697-1698) and urlparse except
    (1718-1719)."""

    @pytest.mark.asyncio
    async def test_move_to_perms_denied(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()

        # Destination channel: connect/speak True for the FIRST permission gate
        # (the one before the connect-vs-move branch), but the move branch
        # re-reads permissions and we make THAT one deny.
        dest = MagicMock()
        dest.name = "Dest"
        # permissions_for returns an object whose connect/speak are False.
        denied = MagicMock(connect=False, speak=False)
        # First check (line 1661) must pass; the move check (1688) must fail.
        # Both call channel.permissions_for(guild.me); use side_effect to
        # return allow first, deny second.
        allow = MagicMock(connect=True, speak=True)
        dest.permissions_for.side_effect = [allow, denied]

        ctx = make_ctx(guild_id=1100)
        ctx.author.voice = MagicMock()
        ctx.author.voice.channel = dest
        ctx.guild.me = MagicMock()

        # Already connected but in a DIFFERENT channel -> move branch.
        other_channel = MagicMock()
        vc = make_vc(playing=False)
        vc.channel = other_channel  # != dest
        ctx.voice_client = vc

        await cog.play.callback(cog, ctx, query="some song")

        ctx.send.assert_awaited()
        # Returned at the perm-denied branch; never queued.
        assert len(cog._gs(ctx.guild.id).queue) == 0
        cog.play_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_urlparse_exception_treated_non_spotify(self):
        cog = make_cog()
        cog.spotify.is_available = MagicMock(return_value=False)
        cog.play_next = AsyncMock()

        chan = MagicMock()
        chan.name = "VC"
        chan.permissions_for.return_value = MagicMock(connect=True, speak=True)
        ctx = make_ctx(guild_id=1101)
        ctx.author.voice = MagicMock()
        ctx.author.voice.channel = chan
        ctx.guild.me = MagicMock()
        vc = make_vc(playing=False, channel=chan)
        ctx.voice_client = vc

        info = {"title": "T", "webpage_url": "u"}
        with (
            patch("urllib.parse.urlparse", side_effect=ValueError("bad url")),
            patch("cogs.music.cog.YTDLSource.search_source", new=AsyncMock(return_value=info)),
        ):
            await cog.play.callback(cog, ctx, query="some plain search")

        # urlparse raised -> _spotify_host="" -> non-spotify YouTube path queued.
        assert len(cog._gs(ctx.guild.id).queue) == 1
        ctx.send.assert_awaited()


class TestSeekHmsValid:
    """seek with a valid H:MM:SS string reaches line 2187."""

    @pytest.mark.asyncio
    async def test_seek_valid_hms(self):
        cog = make_cog()
        vc = make_vc(playing=True)
        ctx = make_ctx(voice_client=vc)
        cog._gs(ctx.guild.id).current_track = {
            "title": "Song",
            "filename": "temp/song.mp3",
            "data": {"duration": 7200},  # 2 hours so 1:02:03 is within range
        }
        cog._gs(ctx.guild.id).volume = 0.5
        cog._safe_run_coroutine = MagicMock()
        cog.play_next = AsyncMock()
        cog.safe_delete = AsyncMock()

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("cogs.music.cog.get_ffmpeg_options", return_value={}),
            patch("cogs.music.cog.get_ffmpeg_executable", return_value="ffmpeg"),
            patch("cogs.music.cog.discord.FFmpegPCMAudio"),
            patch("cogs.music.cog.YTDLSource", return_value=MagicMock()),
        ):
            await cog.seek.callback(cog, ctx, "1:02:03")

        # Valid HMS parsed (line 2187) -> seek proceeded to play.
        ctx.voice_client.play.assert_called_once()
        ctx.send.assert_awaited()


class TestCleanupCacheStatUnlinkErrors:
    """cleanup_cache stat/unlink error branches (2556-2558, 2568-2569,
    2573, 2576-2578)."""

    def _patch_module_path(self, cog_module, temp_dir, monkeypatch):
        real_path = cog_module.Path

        def fake_path(arg="temp", *a, **k):
            if arg == "temp":
                return real_path(str(temp_dir))
            return real_path(arg, *a, **k)

        monkeypatch.setattr(cog_module, "Path", fake_path)

    @pytest.mark.asyncio
    async def test_stat_oserror_on_mtime_check(self, tmp_path, monkeypatch):
        """First stat() (mtime) raising OSError -> continue (2556-2558)."""
        from cogs.music import cog as cog_module

        cog = make_cog()
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        f = temp_dir / "boom.mp3"
        f.write_text("x")
        self._patch_module_path(cog_module, temp_dir, monkeypatch)

        real_stat = type(f).stat

        def boom_stat(self, *a, **k):
            if self.name == "boom.mp3":
                raise OSError("stat fail")
            return real_stat(self, *a, **k)

        with patch("pathlib.Path.stat", boom_stat):
            count, freed = await cog.cleanup_cache()
        assert count == 0
        assert f.exists()  # never deleted (skipped via OSError continue)

    @pytest.mark.asyncio
    async def test_size_stat_filenotfound(self, tmp_path, monkeypatch):
        """Second stat() (size) raising FileNotFoundError -> continue (2568-2569)."""
        import time as _t

        from cogs.music import cog as cog_module

        cog = make_cog()
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        f = temp_dir / "gone.mp3"
        f.write_text("x")
        old = _t.time() - 1000
        import os

        os.utime(f, (old, old))  # pass the mtime grace check
        self._patch_module_path(cog_module, temp_dir, monkeypatch)

        real_stat = type(f).stat
        calls = {"n": 0}

        def stat_side(self, *a, **k):
            if self.name == "gone.mp3":
                calls["n"] += 1
                if calls["n"] == 1:
                    # mtime check: return a real stat (old mtime -> proceeds)
                    return real_stat(self, *a, **k)
                # size check: file "vanished"
                raise FileNotFoundError("gone")
            return real_stat(self, *a, **k)

        with patch("pathlib.Path.stat", stat_side):
            count, freed = await cog.cleanup_cache()
        assert count == 0
        assert f.exists()  # skipped because size stat failed

    @pytest.mark.asyncio
    async def test_unlink_permission_error(self, tmp_path, monkeypatch):
        """unlink() raising PermissionError -> skipped silently (2573)."""
        import time as _t

        from cogs.music import cog as cog_module

        cog = make_cog()
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        f = temp_dir / "locked.mp3"
        f.write_text("xxxx")
        import os

        old = _t.time() - 1000
        os.utime(f, (old, old))
        self._patch_module_path(cog_module, temp_dir, monkeypatch)

        with patch("pathlib.Path.unlink", side_effect=PermissionError("locked")):
            count, freed = await cog.cleanup_cache()
        assert count == 0
        assert f.exists()

    @pytest.mark.asyncio
    async def test_unlink_oserror_logged(self, tmp_path, monkeypatch):
        """unlink() raising generic OSError -> warning logged (2577-2578)."""
        import time as _t

        from cogs.music import cog as cog_module

        cog = make_cog()
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        f = temp_dir / "stubborn.mp3"
        f.write_text("xxxx")
        import os

        old = _t.time() - 1000
        os.utime(f, (old, old))
        self._patch_module_path(cog_module, temp_dir, monkeypatch)

        with patch("pathlib.Path.unlink", side_effect=OSError("device busy")):
            count, freed = await cog.cleanup_cache()
        assert count == 0
        assert f.exists()


# Keep contextlib referenced (used implicitly by cog under test); silence lint.
_ = contextlib
_ = collections
