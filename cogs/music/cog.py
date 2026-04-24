# pylint: disable=too-many-lines
# pyright: reportAttributeAccessIssue=false
# pyright: reportArgumentType=false
"""
Music Cog Module for Discord Bot.
Provides music playback functionality with YouTube and Spotify support.

Note: Type checker warnings for VoiceProtocol/VoiceClient are suppressed
because discord.py's type stubs don't fully reflect runtime behavior.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
logger = logging.getLogger(__name__)
import random
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import discord
import yt_dlp
from discord.ext import commands

from cogs.ai_core.data.constants import CREATOR_ID
from utils.media.ytdl_source import YTDLSource, get_ffmpeg_options

from .utils import Colors, Emojis, create_progress_bar, format_duration
from .views import MusicControlView  # Import from views module to avoid duplication

if TYPE_CHECKING:
    from discord.ext.commands import Bot, Context


@dataclass
class MusicGuildState:
    """Per-guild music state, consolidating 11 scattered dicts into one object."""

    queue: collections.deque[dict[str, Any]] = field(default_factory=collections.deque)
    loop: bool = False
    current_track: dict[str, Any] | None = None
    fixing: bool = False
    pause_start: float | None = None
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    volume: float = 0.5
    auto_disconnect_task: asyncio.Task | None = None
    mode_247: bool = False
    last_text_channel: int | None = None
    play_retries: int = 0

    def reset(self) -> None:
        """Reset transient state (preserves mode_247 and play_lock)."""
        if self.auto_disconnect_task is not None:
            self.auto_disconnect_task.cancel()
            self.auto_disconnect_task = None
        self.queue.clear()
        self.loop = False
        self.current_track = None
        self.fixing = False
        self.pause_start = None
        self.volume = 0.5
        self.play_retries = 0


class Music(commands.Cog):
    """Music Cog - Provides music playback with YouTube and Spotify support."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        # Consolidated per-guild state accessed via self._gs(guild_id)
        self._guild_states: dict[int, MusicGuildState] = {}

        # Lazy import to avoid circular dependency with spotify_handler
        from cogs.spotify_handler import SpotifyHandler

        self.spotify: SpotifyHandler = SpotifyHandler(bot)
        self.auto_disconnect_delay: int = 180  # 3 minutes
        self._temp_cleanup_task: asyncio.Task | None = None
        self._queue_autosave_task: asyncio.Task | None = None
        self._queue_save_pending: set[int] = set()  # guild IDs with pending saves

    async def cog_load(self) -> None:
        """Called when the cog is loaded. Start background tasks."""
        self._temp_cleanup_task = asyncio.create_task(self._periodic_temp_cleanup())
        self._queue_autosave_task = asyncio.create_task(self._periodic_queue_save())

    async def _periodic_temp_cleanup(self) -> None:
        """Periodically clean up stale files in temp directory."""
        import time as _time
        temp_dir = Path("temp")
        stale_threshold = 3600  # 1 hour

        def _cleanup_sync() -> int:
            if not temp_dir.exists():
                return 0
            now = _time.time()
            cleaned = 0
            for f in temp_dir.iterdir():
                if f.is_file() and (now - f.stat().st_mtime) > stale_threshold:
                    try:
                        f.unlink()
                        cleaned += 1
                    except (PermissionError, OSError):
                        pass
            return cleaned

        while True:
            try:
                await asyncio.sleep(1800)  # Run every 30 minutes
                cleaned = await asyncio.to_thread(_cleanup_sync)
                if cleaned:
                    logger.info("🧹 Temp cleanup: removed %d stale files", cleaned)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Temp cleanup error: %s", e)

    async def _periodic_queue_save(self) -> None:
        """Periodically save all active queues to persist them across restarts."""
        from .queue import queue_manager

        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                saved = 0
                for guild_id, gs in list(self._guild_states.items()):
                    if gs.queue:
                        await queue_manager.save_queue(guild_id)
                        saved += 1
                self._queue_save_pending.clear()
                if saved:
                    logger.info("💾 Auto-saved queues for %d guilds", saved)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Queue auto-save error: %s", e)

    def _schedule_queue_save(self, guild_id: int) -> None:
        """Mark a guild's queue as needing save (debounced by periodic task)."""
        self._queue_save_pending.add(guild_id)

    # ----- Guild state helpers -----

    def _gs(self, guild_id: int) -> MusicGuildState:
        """Get or create per-guild state."""
        if guild_id not in self._guild_states:
            self._guild_states[guild_id] = MusicGuildState()
        return self._guild_states[guild_id]

    def _safe_run_coroutine(self, coro) -> None:
        """Safely run a coroutine in the bot's event loop.

        This handles the case where the event loop may be closed during shutdown.
        Uses self.bot.loop which always returns the bot's event loop (needed
        because this method is called from non-async callback threads where
        asyncio.get_event_loop() may return the wrong loop).
        """
        try:
            loop = self.bot.loop
            if loop and loop.is_running() and not loop.is_closed():
                asyncio.run_coroutine_threadsafe(coro, loop)
        except (RuntimeError, AttributeError):
            # Event loop closed or bot shutting down - silently ignore
            pass

    async def cog_unload(self) -> None:
        """Cleanup when cog is unloaded."""
        # Cancel temp cleanup task
        if self._temp_cleanup_task is not None:
            self._temp_cleanup_task.cancel()
        # Cancel queue auto-save task
        if self._queue_autosave_task is not None:
            self._queue_autosave_task.cancel()
        # Cancel all auto-disconnect tasks
        for gs in self._guild_states.values():
            if gs.auto_disconnect_task is not None:
                gs.auto_disconnect_task.cancel()
        # Save queues before clearing to preserve state across reloads
        for guild_id in list(self._guild_states.keys()):
            try:
                await self.save_queue(guild_id)
            except Exception:
                logger.debug("Failed to save queue for guild %s during unload", guild_id)
        # Disconnect all voice clients to prevent resource leaks
        for vc in list(self.bot.voice_clients):
            try:
                await vc.disconnect(force=True)
            except Exception:
                logger.debug("Failed to disconnect voice client during unload")
        # Cleanup Spotify handler
        if hasattr(self, "spotify") and self.spotify:
            self.spotify.cleanup()
        # Clear all stored data to prevent memory leaks
        self._guild_states.clear()
        logger.info("🎵 Music Cog unloaded - all data cleaned up")

    async def cleanup_guild_data(self, guild_id: int) -> None:
        """Clean up all data for a specific guild."""
        # Skip cleanup if the fix command is in progress (race condition prevention)
        if guild_id in self._guild_states and self._guild_states[guild_id].fixing:
            logger.debug("Skipping cleanup for guild %s - fix command in progress", guild_id)
            return

        # Save queue before cleanup for persistence
        await self.save_queue(guild_id)

        if guild_id in self._guild_states:
            gs = self._guild_states[guild_id]
            # Cancel auto-disconnect task
            if gs.auto_disconnect_task is not None:
                gs.auto_disconnect_task.cancel()
            # Preserve mode_247 setting across cleanup
            keep_247 = gs.mode_247
            # Remove the guild state entirely
            del self._guild_states[guild_id]
            # Re-create minimal state if 24/7 mode was enabled
            if keep_247:
                self._guild_states[guild_id] = MusicGuildState(mode_247=True)

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        """Called before every command - track last used text channel."""
        if ctx.guild:
            self._gs(ctx.guild.id).last_text_channel = ctx.channel.id

    async def save_queue(self, guild_id: int) -> None:
        """Save queue to database for persistence across restarts."""
        queue = self._gs(guild_id).queue

        # Import database only when needed
        try:
            from utils.database import db
        except ImportError:
            # Fallback to JSON if database not available
            await self._save_queue_json(guild_id)
            return

        if not queue:
            # Clear queue from database if empty
            await db.clear_music_queue(guild_id)
            return

        # Save to database (convert deque to list for serialization)
        await db.save_music_queue(guild_id, list(queue))
        logger.info("💾 Saved queue for guild %s (%d tracks) to database", guild_id, len(queue))

    async def _save_queue_json(self, guild_id: int) -> None:
        """Legacy JSON save as fallback. Runs blocking I/O in a thread."""
        await asyncio.to_thread(self._save_queue_json_sync, guild_id)

    def _save_queue_json_sync(self, guild_id: int) -> None:
        """Synchronous JSON save implementation."""
        queue = self._gs(guild_id).queue
        if not queue:
            filepath = Path(f"data/queue_{guild_id}.json")
            if filepath.exists():
                with contextlib.suppress(OSError):
                    filepath.unlink()
            return

        data = {
            "queue": list(queue),  # Convert deque to list for JSON serialization
            "volume": self._gs(guild_id).volume,
            "loop": self._gs(guild_id).loop,
            "mode_247": self._gs(guild_id).mode_247,
        }

        try:
            filepath = Path(f"data/queue_{guild_id}.json")
            temp_path = filepath.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(filepath)  # Atomic on POSIX; near-atomic on Windows
        except OSError:
            logger.exception("Failed to save queue for guild %s", guild_id)
            # Clean up temp file if rename failed
            with contextlib.suppress(OSError):
                temp_path = Path(f"data/queue_{guild_id}.json.tmp")
                if temp_path.exists():
                    temp_path.unlink()

    async def load_queue(self, guild_id: int) -> bool:
        """Load queue from database. Returns True if queue was loaded."""
        # Try database first
        try:
            from utils.database import db

            queue = await db.load_music_queue(guild_id)
            if queue:
                self._gs(guild_id).queue = collections.deque(queue)
                logger.info(
                    "📂 Loaded queue for guild %s (%d tracks) from database", guild_id, len(queue)
                )
                return True
        except ImportError:
            pass

        # Fallback to JSON file
        filepath = Path(f"data/queue_{guild_id}.json")
        if not await asyncio.to_thread(filepath.exists):
            return False

        try:
            # Use run_in_executor to avoid blocking the event loop on file I/O
            import asyncio as _asyncio
            raw = await _asyncio.get_running_loop().run_in_executor(
                None, filepath.read_text, "utf-8"
            )
            data = json.loads(raw)

            # Validate expected JSON structure
            if not isinstance(data, dict) or not isinstance(data.get("queue"), list):
                logger.warning("Invalid queue file format for guild %s — skipping", guild_id)
                return False
            queue = data["queue"]
            if queue:
                self._gs(guild_id).queue = collections.deque(queue[:500])  # Enforce max size
                self._gs(guild_id).volume = float(data.get("volume", 0.5))
                self._gs(guild_id).loop = bool(data.get("loop", False))
                self._gs(guild_id).mode_247 = bool(data.get("mode_247", False))
                logger.info(
                    "📂 Loaded queue for guild %s (%d tracks) from JSON", guild_id, len(queue)
                )

                # Remove file after loading (migrated to DB)
                await asyncio.to_thread(filepath.unlink)
                return True
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            logger.exception("Failed to load queue for guild %s", guild_id)

        return False

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Clean up when bot is removed from a guild."""
        # Disconnect voice client first to prevent resource leak
        if guild.voice_client:
            try:
                await guild.voice_client.disconnect(force=True)
            except Exception as e:
                logger.warning("Failed to disconnect voice client on guild remove: %s", e)

        await self.cleanup_guild_data(guild.id)
        logger.info("🧹 Cleaned up data for guild %s", guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Handle voice state changes for auto-disconnect and cleanup."""
        # Only process if bot is involved or member left bot's channel
        if not self.bot.user:
            return

        # Check all guilds where bot is connected
        # Create a copy to prevent RuntimeError if list changes during iteration
        for vc_proto in list(self.bot.voice_clients):
            # Cast to VoiceClient for proper type hints
            vc = cast(discord.VoiceClient, vc_proto)
            # Check if voice client has guild and channel
            if not hasattr(vc, "guild") or not vc.guild or not vc.channel:
                continue

            guild = vc.guild
            guild_id = guild.id

            # Bot was disconnected
            if member == self.bot.user and before.channel and not after.channel:
                logger.info("🔌 Bot disconnected from voice in guild %s - cleaning up", guild_id)
                await self.cleanup_guild_data(guild_id)
                continue

            # Bot was moved to another channel
            if member == self.bot.user and before.channel != after.channel and after.channel:
                # Cancel any pending auto-disconnect
                task = self._gs(guild_id).auto_disconnect_task
                if task is not None:
                    task.cancel()
                    self._gs(guild_id).auto_disconnect_task = None
                continue

            # Check if someone left bot's channel
            if before.channel == vc.channel and after.channel != vc.channel:
                # Skip auto-disconnect if 24/7 mode is enabled
                if self._gs(guild_id).mode_247:
                    continue

                # Capture channel reference once to avoid race condition
                bot_channel = vc.channel
                if not bot_channel or not hasattr(bot_channel, "members"):
                    continue
                humans = [m for m in bot_channel.members if not m.bot]
                if len(humans) == 0:
                    # Start auto-disconnect countdown
                    if self._gs(guild_id).auto_disconnect_task is None:
                        self._gs(guild_id).auto_disconnect_task = asyncio.create_task(
                            self._auto_disconnect(guild_id, vc)
                        )
                        logger.info("⏳ Started auto-disconnect timer for guild %s", guild_id)

            # Check if someone joined bot's channel
            if after.channel == vc.channel and before.channel != vc.channel:
                # Cancel auto-disconnect if someone joins
                task = self._gs(guild_id).auto_disconnect_task
                if task is not None:
                    task.cancel()
                    self._gs(guild_id).auto_disconnect_task = None
                    logger.info(
                        "✅ Cancelled auto-disconnect for guild %s - user joined", guild_id
                    )

    async def _auto_disconnect(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        """Auto-disconnect after delay when alone in voice channel."""
        try:
            # Send warning message
            if voice_client.is_connected() and voice_client.guild:
                guild = voice_client.guild
                text_channel = None

                # Try to use last used text channel first
                gs = self._gs(guild_id)
                if gs.last_text_channel is not None:
                    last_channel_id = gs.last_text_channel
                    last_channel = guild.get_channel(last_channel_id)
                    if (
                        last_channel
                        and guild.me
                        and last_channel.permissions_for(guild.me).send_messages
                    ):
                        text_channel = last_channel

                # Fallback: Find any text channel with send permission
                if not text_channel and guild.me:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            text_channel = channel
                            break

                if text_channel:
                    embed = discord.Embed(
                        title=f"{Emojis.WARNING} แจ้งเตือนออกอัตโนมัติ",
                        description=(
                            f"ไม่มีใครในห้องเสียง\n"
                            f"Bot จะออกใน **{self.auto_disconnect_delay // 60} นาที** "
                            "หากไม่มีคนเข้ามา"
                        ),
                        color=Colors.WARNING,
                    )
                    embed.set_footer(text="ใช้ !join เพื่อเชื่อมต่อใหม่")
                    await text_channel.send(embed=embed)  # type: ignore[union-attr]

            # Wait for the delay
            await asyncio.sleep(self.auto_disconnect_delay)

            # Double check if still alone
            if voice_client.is_connected() and voice_client.channel:
                humans = [m for m in voice_client.channel.members if not m.bot]
                if len(humans) == 0:
                    # Cleanup and disconnect
                    await self.cleanup_guild_data(guild_id)
                    await voice_client.disconnect()

                    # Update presence
                    await self.bot.change_presence(
                        activity=discord.Activity(
                            type=discord.ActivityType.listening, name="คำสั่งเพลง"
                        )
                    )

                    logger.info("👋 Auto-disconnected from guild %s due to inactivity", guild_id)

        except asyncio.CancelledError:
            # Task was cancelled (someone joined)
            pass
        except discord.DiscordException:
            logger.exception("Auto-disconnect error")
        finally:
            # Remove task from dict
            self._gs(guild_id).auto_disconnect_task = None

    async def safe_delete(self, filename):
        """Safely delete a file with exponential backoff (Non-blocking)."""
        filepath = await asyncio.to_thread(lambda: Path(filename).resolve())
        temp_root = await asyncio.to_thread(lambda: Path("temp").resolve())
        if not filepath.is_relative_to(temp_root):
            logger.warning("🛡️ Blocked file deletion outside temp directory: %s", filepath)
            return
        for attempt in range(8):  # 8 retries with exponential backoff
            if not await asyncio.to_thread(filepath.exists):
                return  # Already deleted
            try:
                await asyncio.to_thread(filepath.unlink)
                logger.info("🗑️ Deleted %s", filename)
                return
            except PermissionError:
                # Exponential backoff: 1s, 2s, 4s, 4s, 4s... (capped at 4s)
                delay = min(2 ** attempt, 4.0)
                if attempt < 7:
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "❌ Could not delete %s after %d retries (PermissionError)",
                        filename, attempt + 1,
                    )
            except OSError as e:
                logger.warning("Failed to delete %s: %s", filename, e)
                return

    def get_queue(self, ctx) -> collections.deque[dict[str, Any]]:
        """Get or create queue for a guild.

        Note: Caller must ensure ctx.guild is not None (use @commands.guild_only()).
        """
        if not ctx.guild:
            raise commands.NoPrivateMessage("This command can only be used in a server.")
        return self._gs(ctx.guild.id).queue

    async def play_next(self, ctx: Context) -> None:
        """Play the next track in the queue."""
        # Check if voice_client exists
        if not ctx.voice_client or not ctx.guild:
            return

        # Cast voice_client to VoiceClient for proper type hints
        voice_client = cast(discord.VoiceClient, ctx.voice_client)
        guild_id = ctx.guild.id

        # Use setdefault for atomic get-or-create to prevent race condition
        lock = self._gs(guild_id).play_lock

        # Atomic lock acquisition with timeout - avoids TOCTOU race condition
        # by not checking lock.locked() separately from acquire().
        # Uses shield + done_callback to avoid CPython #42130 deadlock.

        async def _acquire_lock():
            await lock.acquire()
            return True

        _acquire_task = asyncio.create_task(_acquire_lock())
        _timed_out_flag: list[bool] = [False]  # Use list to share state safely with callback

        def _release_if_timed_out(task: asyncio.Task) -> None:
            if _timed_out_flag[0] and not task.cancelled() and task.exception() is None:
                try:
                    lock.release()
                except RuntimeError:
                    pass

        _acquire_task.add_done_callback(_release_if_timed_out)

        try:
            acquired = await asyncio.wait_for(asyncio.shield(_acquire_task), timeout=0.1)
            if not acquired:
                logger.debug("play_next lock acquisition failed for guild %s", guild_id)
                return
        except TimeoutError:
            _timed_out_flag[0] = True
            # Another task is processing - skip this call
            logger.debug("play_next already in progress for guild %s", guild_id)
            return

        _retry_next = False
        try:
            # Check voice_client again inside lock
            if not ctx.voice_client:
                return

            # Re-cast after null check
            voice_client = cast(discord.VoiceClient, ctx.voice_client)

            # Double check if playing inside lock to prevent race conditions
            if voice_client.is_playing() or voice_client.is_paused():
                return

            # 1. Check Loop Mode
            track_info = self._gs(guild_id).current_track
            if self._gs(guild_id).loop and track_info is not None:
                # Replay current track
                filename = track_info["filename"]
                data = track_info["data"]

                if await asyncio.to_thread(lambda: Path(filename).exists()):
                    try:
                        # Verify voice_client is still valid
                        if not ctx.voice_client or not voice_client.is_connected():
                            logger.warning("Voice client disconnected during loop replay")
                            return

                        # Recreate player from existing file
                        current_options = get_ffmpeg_options(stream=False)
                        player = YTDLSource(
                            discord.FFmpegPCMAudio(
                                filename, **current_options, executable="ffmpeg"  # type: ignore[arg-type]
                            ),
                            data=data,
                            filename=filename,
                        )

                        # Preserve current volume across loop replay
                        player.volume = self._gs(guild_id).volume

                        # Update start time
                        track_info["start_time"] = time.time()

                        # Capture voice_client reference at callback definition time
                        voice_client_loop = voice_client

                        def after_playing_loop(error):
                            if self._gs(guild_id).fixing:
                                return  # Skip if fixing

                            # Guard: Check if voice_client is still valid
                            if not voice_client_loop or not voice_client_loop.is_connected():
                                return

                            if not self._gs(guild_id).loop:
                                # Loop disabled during play -> Delete file
                                self._safe_run_coroutine(self.safe_delete(filename))

                            if error:
                                logger.error("Loop error: %s", error)

                            # Guard: Don't schedule if already playing or paused
                            if voice_client_loop.is_playing() or voice_client_loop.is_paused():
                                return

                            self._safe_run_coroutine(self.play_next(ctx))

                        voice_client.play(player, after=after_playing_loop)

                        # Loop embed
                        embed = discord.Embed(
                            title=f"{Emojis.LOOP} Looping",
                            description=f"**{player.title}**",
                            color=Colors.LOOP,
                        )
                        embed.set_footer(text="Use !loop to disable • !skip to skip")
                        await ctx.send(embed=embed)
                        return
                    except discord.DiscordException:
                        logger.exception("Loop replay failed (Discord)")
                        self._gs(guild_id).loop = False  # Disable loop on error
                    except OSError:
                        logger.exception("Loop replay failed (audio/file)")
                        self._gs(guild_id).loop = False  # Disable loop on error

            # 2. Normal Queue Logic
            queue = self.get_queue(ctx)
            if len(queue) > 0:
                item = queue.popleft()
                url = item.get("url") if isinstance(item, dict) else item

                if not url:
                    return

                try:
                    async with ctx.typing():
                        # Use Download Mode (stream=False)
                        player = await YTDLSource.from_url(url, loop=asyncio.get_running_loop(), stream=False)

                        # Apply stored volume to new track
                        player.volume = self._gs(guild_id).volume

                        # Save current track info (only essential data)
                        self._gs(guild_id).current_track = {
                            "filename": player.filename,
                            "data": {
                                "title": player.data.get("title"),
                                "webpage_url": player.data.get("webpage_url"),
                                "thumbnail": player.data.get("thumbnail"),
                                "duration": player.data.get("duration"),
                                "url": player.data.get("url"),
                            },
                            "title": player.title,
                            "start_time": time.time(),
                        }

                        # Capture voice_client reference at callback definition time
                        # to avoid issues with ctx.voice_client becoming None
                        vc_callback = voice_client

                        def after_playing(error):
                            if self._gs(guild_id).fixing:
                                return  # Skip if fixing

                            # Guard: Check if voice_client is still valid
                            if not vc_callback or not vc_callback.is_connected():
                                # Cleanup file even if disconnected
                                if player.filename and not self._gs(guild_id).loop:
                                    self._safe_run_coroutine(self.safe_delete(player.filename))
                                return

                            # Cleanup: Delete file ONLY if loop is OFF
                            if not self._gs(guild_id).loop:
                                if player.filename:
                                    self._safe_run_coroutine(self.safe_delete(player.filename))

                            if error:
                                logger.error("Player error: %s", error)

                            # Guard: Don't schedule if already playing or paused
                            if vc_callback.is_playing() or vc_callback.is_paused():
                                return

                            self._safe_run_coroutine(self.play_next(ctx))

                        try:
                            voice_client.play(player, after=after_playing)
                            # Reset retry counter on successful playback start
                            self._gs(guild_id).play_retries = 0
                        except discord.DiscordException:
                            logger.exception("Failed to start playback (Discord)")
                            # Cleanup FFmpeg process
                            try:
                                player.cleanup()
                            except Exception as cleanup_err:
                                logger.debug(
                                    "Player cleanup failed (non-critical): %s", cleanup_err
                                )
                            # Cleanup file on error
                            if player.filename and not self._gs(ctx.guild.id).loop:
                                self._safe_run_coroutine(self.safe_delete(player.filename))
                            _retry_next = True
                            return
                        except OSError:
                            logger.exception("Failed to start playback (audio/file)")
                            try:
                                player.cleanup()
                            except Exception as cleanup_err:
                                logger.debug(
                                    "Player cleanup failed (non-critical): %s", cleanup_err
                                )
                            if player.filename and not self._gs(ctx.guild.id).loop:
                                self._safe_run_coroutine(self.safe_delete(player.filename))
                            _retry_next = True
                            return

                    # 🎨 PREMIUM NOW PLAYING EMBED
                    duration = player.data.get("duration", 0)
                    embed = discord.Embed(
                        title=f"{Emojis.NOTES} กำลังเล่น",
                        description=(f"**[{player.title}]({player.data.get('webpage_url')})**"),
                        color=Colors.PLAYING,
                    )

                    # Thumbnail
                    if player.data.get("thumbnail"):
                        embed.set_thumbnail(url=player.data.get("thumbnail"))

                    # Duration with progress bar (starts at 0)
                    progress_bar = create_progress_bar(0, duration)
                    embed.add_field(
                        name=f"{Emojis.CLOCK} Duration",
                        value=(f"`{progress_bar}`\n`00:00` / `{format_duration(duration)}`"),
                        inline=True,
                    )

                    # Audio Quality Badge
                    embed.add_field(
                        name=f"{Emojis.VOLUME} Audio",
                        value="`Premium HQ`\n`48kHz Stereo`",
                        inline=True,
                    )

                    # Loop Status
                    loop_status = (
                        f"{Emojis.LOOP} On"
                        if self._gs(ctx.guild.id).loop
                        else f"{Emojis.LOOP} Off"
                    )
                    embed.add_field(name="Loop", value=f"`{loop_status}`", inline=True)

                    embed.set_footer(
                        text=(
                            f"Requested by {ctx.author.display_name} • Use buttons below to control"
                        ),
                        icon_url=ctx.author.display_avatar.url,
                    )

                    # Send embed with interactive controls
                    view = MusicControlView(self, ctx.guild.id)
                    view.message = await ctx.send(embed=embed, view=view)
                    # Only update global presence if bot is in exactly one voice channel
                    if len(self.bot.voice_clients) <= 1:
                        await self.bot.change_presence(
                            activity=discord.Activity(
                                type=discord.ActivityType.listening, name=player.title
                            )
                        )
                except discord.DiscordException as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Playback Error",
                        description="ไม่สามารถเล่นเพลงถัดไปได้ กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    logger.error("Play error (Discord): %s\n%s", e, traceback.format_exc())
                    _retry_next = True
                except OSError as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Playback Error",
                        description="เกิดข้อผิดพลาดกับไฟล์เสียง กรุณาลองใหม่",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    logger.error("Play error (audio/file): %s\n%s", e, traceback.format_exc())
                    _retry_next = True
            else:
                # Queue empty
                self._gs(ctx.guild.id).current_track = None  # Clear track info
                # Only update global presence if bot has no other active voice clients
                if len(self.bot.voice_clients) <= 1:
                    await self.bot.change_presence(
                        activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
                    )
        finally:
            # Always release the lock
            lock.release()

        # Retry next track AFTER lock is released (avoids deadlock)
        if _retry_next:
            # Limit retries to prevent unbounded recursion (per-guild tracking)
            retry_count = self._gs(guild_id).play_retries
            if retry_count < 10:  # Max 10 retries to prevent stack overflow
                self._gs(guild_id).play_retries = retry_count + 1
                await self.play_next(ctx)
            else:
                logger.warning("play_next retry limit reached for guild %s", guild_id)
                self._gs(guild_id).play_retries = 0  # Reset for next session

    @commands.hybrid_command(name="loop", aliases=["l"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def loop(self, ctx):
        """เปิด/ปิด โหมดวนซ้ำเพลงปัจจุบัน."""
        current = self._gs(ctx.guild.id).loop
        self._gs(ctx.guild.id).loop = not current

        if not current:
            embed = discord.Embed(
                title=f"{Emojis.LOOP} เปิดโหมดวนซ้ำ",
                description="เพลงปัจจุบันจะเล่นซ้ำหลังจบ",
                color=Colors.LOOP,
            )
            embed.set_footer(text="ใช้ !loop อีกครั้งเพื่อปิด")
        else:
            embed = discord.Embed(
                title=f"{Emojis.LOOP} ปิดโหมดวนซ้ำ",
                description="เล่นเพลงถัดไปต่อตามคิว",
                color=Colors.STOP,
            )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="pause", aliases=["pa"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def pause(self, ctx):
        """หยุดเล่นเพลงชั่วคราว."""
        if not ctx.voice_client:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Bot ไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            self._gs(ctx.guild.id).pause_start = time.time()

            # Get current track info for embed
            track_info = (self._gs(ctx.guild.id).current_track or {})
            title = track_info.get("title", "Unknown Track")

            embed = discord.Embed(
                title=f"{Emojis.PAUSE} หยุดชั่วคราว", description=f"**{title}**", color=Colors.PAUSED
            )
            embed.set_footer(text="ใช้ !resume เพื่อเล่นต่อ")
            await ctx.send(embed=embed)
        elif ctx.voice_client.is_paused():
            embed = discord.Embed(
                description=(f"{Emojis.WARNING} หยุดอยู่แล้ว • ใช้ `!resume` เพื่อเล่นต่อ"),
                color=Colors.WARNING,
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงเล่นอยู่", color=Colors.ERROR)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="resume", aliases=["unpause"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def resume(self, ctx):
        """เล่นเพลงต่อ."""
        if not ctx.voice_client:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Bot ไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if ctx.voice_client.is_paused():
            # Calculate paused duration
            if self._gs(ctx.guild.id).pause_start is not None:
                paused_duration = time.time() - self._gs(ctx.guild.id).pause_start
                # Shift start time forward
                if self._gs(ctx.guild.id).current_track is not None:
                    self._gs(ctx.guild.id).current_track["start_time"] += paused_duration
                self._gs(ctx.guild.id).pause_start = None

            ctx.voice_client.resume()

            # Get current track info for embed
            track_info = (self._gs(ctx.guild.id).current_track or {})
            title = track_info.get("title", "Unknown Track")

            embed = discord.Embed(
                title=f"{Emojis.PLAY} เล่นต่อ", description=f"**{title}**", color=Colors.RESUMED
            )
            await ctx.send(embed=embed)
        elif ctx.voice_client.is_playing():
            embed = discord.Embed(
                description=f"{Emojis.WARNING} กำลังเล่นอยู่แล้ว", color=Colors.WARNING
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงให้เล่นต่อ", color=Colors.ERROR)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="fix", aliases=["f", "reconnect"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def fix(self, ctx):
        """แก้ไขอาการกระตุกโดยการเชื่อมต่อใหม่และเล่นต่อจากเดิม."""
        if not ctx.voice_client or (
            not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()
        ):
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงเล่นอยู่", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        fix_embed = discord.Embed(
            title=f"{Emojis.TOOLS} กำลังแก้ไขการเชื่อมต่อ",
            description="กำลังเชื่อมต่อใหม่และเล่นต่อ...",
            color=Colors.INFO,
        )
        fix_msg = await ctx.send(embed=fix_embed)

        guild_id = ctx.guild.id
        track_info = self._gs(guild_id).current_track
        if not track_info:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบข้อมูลเพลง", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        # 1. Calculate elapsed time
        start_time = track_info.get("start_time", 0)
        elapsed = 0
        if start_time > 0:
            if ctx.voice_client.is_paused() and self._gs(guild_id).pause_start is not None:
                # If paused, elapsed is time until pause
                elapsed = self._gs(guild_id).pause_start - start_time
            else:
                # If playing, elapsed is time until now
                elapsed = time.time() - start_time

        # 2. Stop and Disconnect (Set fixing flag)
        self._gs(guild_id).fixing = True

        # Clear pause state if exists (since we will resume playing)
        self._gs(guild_id).pause_start = None

        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()

        try:
            # 3. Reconnect
            if ctx.author.voice:
                channel = ctx.author.voice.channel
                await channel.connect()
            else:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} คุณไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
                )
                await ctx.send(embed=embed)
                return

            # 4. Resume
            filename = track_info["filename"]
            data = track_info["data"]

            # Seek to elapsed time
            current_options = get_ffmpeg_options(stream=False, start_time=elapsed)

            player = YTDLSource(
                discord.FFmpegPCMAudio(filename, **current_options, executable="ffmpeg"),
                data=data,
                filename=filename,
            )

            # Preserve current volume across fix/reconnect
            player.volume = self._gs(guild_id).volume

            # Restore current_track (cleanup may have removed it during disconnect)
            self._gs(guild_id).current_track = track_info

            # Update start time to now - elapsed
            self._gs(guild_id).current_track["start_time"] = time.time() - elapsed

            # Capture voice_client reference at callback definition time
            voice_client_fix = ctx.voice_client

            def after_playing_fix(error):
                if self._gs(guild_id).fixing:
                    return

                # Guard: Check if voice_client is still valid
                if not voice_client_fix or not voice_client_fix.is_connected():
                    # Cleanup file even if disconnected
                    if not self._gs(guild_id).loop and filename:
                        self._safe_run_coroutine(self.safe_delete(filename))
                    return

                # Cleanup logic - use safe_delete
                if not self._gs(guild_id).loop and filename:
                    self._safe_run_coroutine(self.safe_delete(filename))

                if error:
                    logger.error("Fix player error: %s", error)
                self._safe_run_coroutine(self.play_next(ctx))

            voice_client_fix.play(player, after=after_playing_fix)

            # Success embed
            success_embed = discord.Embed(
                title=f"{Emojis.CHECK} แก้ไขสำเร็จ!",
                description=f"เล่นต่อที่ `{format_duration(elapsed)}`",
                color=Colors.RESUMED,
            )
            success_embed.add_field(
                name="เพลง", value=f"**{track_info.get('title', 'Unknown')}**", inline=False
            )
            await fix_msg.edit(embed=success_embed)

        except discord.DiscordException as e:
            error_embed = discord.Embed(
                title=f"{Emojis.CROSS} แก้ไขไม่สำเร็จ", description="เกิดข้อผิดพลาดในการเชื่อมต่อใหม่ กรุณาลองอีกครั้ง", color=Colors.ERROR
            )
            await fix_msg.edit(embed=error_embed)
            logger.error("Fix failed (Discord): %s", e)
        except OSError as e:
            error_embed = discord.Embed(
                title=f"{Emojis.CROSS} แก้ไขไม่สำเร็จ", description="เกิดข้อผิดพลาดกับไฟล์เสียง กรุณาลองอีกครั้ง", color=Colors.ERROR
            )
            await fix_msg.edit(embed=error_embed)
            logger.error("Fix failed (audio/file): %s", e)
        finally:
            # Always reset fixing flag at the end
            self._gs(guild_id).fixing = False

    @commands.hybrid_command(name="join", aliases=["j", "connect"])  # type: ignore[arg-type]
    @commands.bot_has_guild_permissions(connect=True, speak=True)
    async def join(self, ctx):
        """เข้าร่วมช่องเสียง."""
        if not ctx.author.voice:
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} คุณต้องอยู่ในห้องเสียงก่อน"), color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return

        channel = ctx.author.voice.channel

        # Check channel-specific permissions
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.connect or not permissions.speak:
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ไม่มีสิทธิ์เข้าหรือพูดในห้อง **{channel.name}**\n"
                f"กรุณาให้สิทธิ์ `Connect` และ `Speak` แก่ Bot",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return

        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
            embed = discord.Embed(
                description=f"{Emojis.CHECK} ย้ายไป **{channel.name}**", color=Colors.RESUMED
            )
            await ctx.send(embed=embed)
            return

        await channel.connect()
        embed = discord.Embed(
            title=f"{Emojis.HEADPHONES} เชื่อมต่อแล้ว",
            description=f"เข้าร่วม **{channel.name}**",
            color=Colors.RESUMED,
        )
        embed.set_footer(text="ใช้ !play <ชื่อเพลง> เพื่อเล่นเพลง")
        await ctx.send(embed=embed)

    @commands.command(name="play", aliases=["p"])
    @commands.bot_has_guild_permissions(connect=True, speak=True)
    async def play(self, ctx: Context, *, query: str | None = None) -> None:
        """เล่นเพลงจาก YouTube หรือ Spotify."""
        # Validate query parameter
        if query:
            query = query[:500]  # Cap length to prevent DoS via extremely long queries
        if not query or not query.strip():
            embed = discord.Embed(
                title=f"{Emojis.MUSIC} วิธีเล่นเพลง",
                description="ใช้ `!play <ชื่อเพลง หรือ URL>`",
                color=Colors.INFO,
            )
            embed.add_field(
                name="ตัวอย่าง",
                value=(
                    "`!play shape of you`\n"
                    "`!play https://youtube.com/...`\n"
                    "`!play https://open.spotify.com/...`"
                ),
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        if not ctx.author.voice:  # type: ignore[union-attr]
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} คุณต้องอยู่ในห้องเสียงก่อน"), color=Colors.ERROR
            )
            await ctx.send(embed=embed)
            return

        # Check channel-specific permissions before connecting
        channel = ctx.author.voice.channel  # type: ignore[union-attr]
        if not channel or not ctx.guild:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบช่องเสียง", color=Colors.ERROR)
            await ctx.send(embed=embed)
            return

        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.connect or not permissions.speak:
            channel_name = channel.name if channel else "unknown"
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ไม่มีสิทธิ์เข้าหรือพูดในห้อง **{channel_name}**\n"
                f"กรุณาให้สิทธิ์ `Connect` และ `Speak` แก่ Bot",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return

        # Connect if not connected
        if ctx.voice_client is None:
            try:
                await channel.connect()
            except discord.ClientException as e:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} เชื่อมต่อไม่สำเร็จ: {e}", color=Colors.ERROR
                )
                await ctx.send(embed=embed)
                return
        elif ctx.voice_client.channel and ctx.voice_client.channel != channel:
            # Move to user's channel if in different channel
            await ctx.voice_client.move_to(channel)  # type: ignore[attr-defined]

        queue = self.get_queue(ctx)

        # Check if Spotify URL
        if "open.spotify.com" in query and self.spotify.is_available():
            success = await self.spotify.process_spotify_url(ctx, query, queue)  # type: ignore[arg-type]
            if not success:
                return
        else:
            # YouTube / Search
            async with ctx.typing():
                # Check queue size limit
                from .queue import MAX_QUEUE_SIZE

                if len(queue) >= MAX_QUEUE_SIZE:
                    embed = discord.Embed(
                        description=f"{Emojis.CROSS} Queue is full (max {MAX_QUEUE_SIZE} tracks)",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    return

                try:
                    # Use search_source to get info first
                    info = await YTDLSource.search_source(query, loop=asyncio.get_running_loop())
                    if info:
                        title = info.get("title", "Unknown Title")
                        url = info.get("webpage_url", query)
                        thumbnail = info.get("thumbnail", None)
                        duration = info.get("duration", 0)
                        uploader = info.get("uploader", "Unknown")

                        queue.append({"url": url, "title": title, "type": "url"})
                        self._schedule_queue_save(ctx.guild.id)

                        # 🎨 PREMIUM YOUTUBE EMBED
                        embed = discord.Embed(
                            title=f"{Emojis.MUSIC} Added to Queue",
                            description=f"**[{title}]({url})**",
                            color=Colors.YOUTUBE,
                        )
                        if thumbnail:
                            embed.set_thumbnail(url=thumbnail)

                        # Track Info
                        embed.add_field(
                            name=f"{Emojis.CLOCK} Duration",
                            value=f"`{format_duration(duration)}`",
                            inline=True,
                        )
                        embed.add_field(
                            name=f"{Emojis.QUEUE} Position", value=f"`#{len(queue)}`", inline=True
                        )
                        embed.add_field(
                            name=f"{Emojis.MICROPHONE} Channel", value=uploader[:20], inline=True
                        )

                        embed.set_footer(
                            text=f"Requested by {ctx.author.display_name}",
                            icon_url=ctx.author.display_avatar.url,
                        )

                        await ctx.send(embed=embed)
                    else:
                        # Truncate query for safe embed display
                        safe_query = query[:100] + "..." if len(query) > 100 else query
                        safe_query = discord.utils.escape_markdown(safe_query)
                        embed = discord.Embed(
                            description=(f"{Emojis.CROSS} No results found for: {safe_query}"),
                            color=Colors.ERROR,
                        )
                        await ctx.send(embed=embed)
                        return
                except discord.DiscordException as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error", description="เกิดข้อผิดพลาดในการค้นหา กรุณาลองใหม่", color=Colors.ERROR
                    )
                    await ctx.send(embed=embed)
                    logger.error("Search error (Discord): %s", e)
                    return
                except OSError as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error", description="เกิดข้อผิดพลาดกับไฟล์ กรุณาลองใหม่", color=Colors.ERROR
                    )
                    await ctx.send(embed=embed)
                    logger.error("Search error (file): %s", e)
                    return
                except yt_dlp.DownloadError as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error", description="ไม่สามารถดาวน์โหลดได้ กรุณาลองใหม่", color=Colors.ERROR
                    )
                    await ctx.send(embed=embed)
                    logger.error("Search error (download): %s", e)
                    return

        # If not playing, start playing
        if (
            ctx.voice_client
            and not ctx.voice_client.is_playing()  # type: ignore[attr-defined]
            and not ctx.voice_client.is_paused()  # type: ignore[attr-defined]
        ):
            await self.play_next(ctx)

    @commands.hybrid_command(name="skip", aliases=["s"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def skip(self, ctx):
        """ข้ามเพลงปัจจุบัน."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            # Disable loop when skipping
            self._gs(ctx.guild.id).loop = False
            ctx.voice_client.stop()

            queue = self.get_queue(ctx)
            embed = discord.Embed(
                title=f"{Emojis.SKIP} ข้ามเพลง",
                description=(f"ปิดโหมดวนซ้ำ • เหลือ **{len(queue)}** เพลงในคิว"),
                color=Colors.INFO,
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่มีเพลงให้ข้าม", color=Colors.ERROR)
            await ctx.send(embed=embed)

    @commands.command(name="queue", aliases=["q"])
    @commands.guild_only()
    async def queue(self, ctx):
        """แสดงรายการเพลงในคิว."""
        queue = self.get_queue(ctx)
        loop_status = f"{Emojis.CHECK}" if self._gs(ctx.guild.id).loop else f"{Emojis.CROSS}"

        if not queue:
            embed = discord.Embed(
                title=f"{Emojis.QUEUE} คิวว่าง",
                description="ไม่มีเพลงในคิว\nใช้ `!play <ชื่อเพลง>` เพื่อเพิ่มเพลง",
                color=Colors.STOP,
            )
            embed.add_field(name=f"{Emojis.LOOP} วนซ้ำ", value=loop_status, inline=True)
            await ctx.send(embed=embed)
        else:
            # Create fancy queue embed
            embed = discord.Embed(title=f"{Emojis.QUEUE} คิวเพลง", color=Colors.QUEUE)

            # Now Playing
            current = (self._gs(ctx.guild.id).current_track or {})
            if current:
                now_playing = current.get("title", "Unknown")
                embed.add_field(
                    name=f"{Emojis.NOTES} Now Playing", value=f"**{now_playing}**", inline=False
                )

            # Queue List (with numbers)
            description = ""
            for i, item in enumerate(list(queue)[:10], 1):
                if isinstance(item, dict):
                    title = item.get("title", "Unknown")
                    title = title[:40] + "..." if len(title) > 40 else title
                    description += f"`{i}.` {title}\n"
                else:
                    description += f"`{i}.` {item[:40]}\n"

            if len(queue) > 10:
                description += f"\n*...and **{len(queue) - 10}** more tracks*"

            embed.add_field(
                name=f"{Emojis.QUEUE} Up Next ({len(queue)} tracks)",
                value=description if description else "No tracks",
                inline=False,
            )

            embed.add_field(name=f"{Emojis.LOOP} Loop", value=loop_status, inline=True)
            embed.add_field(name=f"{Emojis.VOLUME} Audio", value="`Premium HQ`", inline=True)

            embed.set_footer(text="ใช้ !skip เพื่อข้าม • !clear เพื่อล้างคิว")
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="stop", aliases=["st"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def stop(self, ctx):
        """หยุดเล่นและล้างคิว."""
        self._gs(ctx.guild.id).queue = collections.deque()
        self._gs(ctx.guild.id).loop = False  # Disable loop
        self._gs(ctx.guild.id).current_track = None

        if ctx.voice_client:
            ctx.voice_client.stop()

        # Only change global presence if this is the last voice client
        if len(self.bot.voice_clients) <= 1:
            await self.bot.change_presence(
                activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
            )

        embed = discord.Embed(
            title=f"{Emojis.STOP} หยุดแล้ว", description="หยุดเล่นและล้างคิวแล้ว", color=Colors.STOP
        )
        await ctx.send(embed=embed)

    @commands.command(name="clear", aliases=["cl", "clr"])
    @commands.guild_only()
    async def clear(self, ctx):
        """ล้างคิวเพลงทั้งหมด (แต่ไม่หยุดเพลงที่เล่นอยู่)."""
        cleared_count = len(self._gs(ctx.guild.id).queue)
        self._gs(ctx.guild.id).queue = collections.deque()

        embed = discord.Embed(
            title=f"{Emojis.CHECK} ล้างคิวแล้ว",
            description=f"ลบ **{cleared_count}** เพลงออกจากคิว",
            color=Colors.INFO,
        )
        embed.set_footer(text="เพลงปัจจุบันจะเล่นต่อ")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leave", aliases=["disconnect", "dc"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def leave(self, ctx):
        """ออกจากช่องเสียง."""
        if ctx.voice_client:
            # Cleanup
            self._gs(ctx.guild.id).queue = collections.deque()
            self._gs(ctx.guild.id).loop = False
            self._gs(ctx.guild.id).current_track = None

            await ctx.voice_client.disconnect()
            # Only change global presence if this was the last voice client
            if len(self.bot.voice_clients) <= 1:
                await self.bot.change_presence(
                    activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
                )

            embed = discord.Embed(
                title=f"{Emojis.WAVE} Disconnected",
                description="Left the voice channel",
                color=Colors.STOP,
            )
            embed.set_footer(text="Use !join to reconnect")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} Not connected to any voice channel"),
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)

    @commands.command(name="volume", aliases=["vol", "v"])
    @commands.guild_only()
    async def volume(self, ctx, volume: int | None = None):
        """ปรับระดับเสียง (0-200%)."""
        if volume is None:
            current_vol = int(self._gs(ctx.guild.id).volume * 100)
            embed = discord.Embed(
                title=f"{Emojis.VOLUME} Current Volume",
                description=f"**{current_vol}%**\n\nUse `!volume <0-200>` to adjust",
                color=Colors.INFO,
            )
            return await ctx.send(embed=embed)

        if not 0 <= volume <= 200:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Volume must be between 0 and 200", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        self._gs(ctx.guild.id).volume = volume / 100.0

        # Apply to current player if playing
        if ctx.voice_client and ctx.voice_client.source:
            if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
                ctx.voice_client.source.volume = volume / 100.0

        # Volume bar visualization
        bar_length = 10
        filled = int((volume / 200) * bar_length)
        volume_bar = "█" * filled + "░" * (bar_length - filled)

        embed = discord.Embed(
            title=f"{Emojis.VOLUME} Volume Set",
            description=f"`[{volume_bar}]` **{volume}%**",
            color=Colors.RESUMED,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="247", aliases=["24/7", "stay", "nonstop"])  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def mode_247_toggle(self, ctx):
        """เปิด/ปิดโหมด 24/7 - Bot อยู่ในห้องตลอดเวลา."""
        guild_id = ctx.guild.id
        current = self._gs(guild_id).mode_247

        # Toggle mode
        self._gs(guild_id).mode_247 = not current
        new_state = self._gs(guild_id).mode_247

        if new_state:
            # Cancel any pending auto-disconnect
            task = self._gs(guild_id).auto_disconnect_task
            if task is not None:
                task.cancel()
                self._gs(guild_id).auto_disconnect_task = None

            embed = discord.Embed(
                title=f"{Emojis.CHECK} 24/7 Mode Enabled",
                description=("Bot จะอยู่ในห้องเสียงตลอดเวลา\nไม่ออกอัตโนมัติเมื่อไม่มีคน"),
                color=Colors.RESUMED,
            )
            embed.set_footer(text="Use !247 again to disable")
        else:
            embed = discord.Embed(
                title=f"{Emojis.CROSS} 24/7 Mode Disabled",
                description="Bot จะออกอัตโนมัติเมื่อไม่มีคนในห้อง",
                color=Colors.STOP,
            )

        await ctx.send(embed=embed)

    @mode_247_toggle.error
    async def mode_247_error(self, ctx, error):
        """Handle permission errors for 24/7 command."""
        if isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} คุณต้องมีสิทธิ์ `Manage Channels` ในการใช้คำสั่งนี้",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
        else:
            raise error

    @commands.command(name="shuffle", aliases=["sh", "mix"])
    @commands.guild_only()
    async def shuffle(self, ctx):
        """สุ่มลำดับเพลงในคิว."""
        queue = self.get_queue(ctx)

        if len(queue) < 2:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Need at least 2 tracks in queue to shuffle",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        # Convert deque to list for O(n) shuffle, then replace
        items = list(queue)
        random.shuffle(items)
        queue.clear()
        queue.extend(items)

        embed = discord.Embed(
            title=f"{Emojis.SPARKLES} Queue Shuffled!",
            description=f"Shuffled **{len(queue)}** tracks",
            color=Colors.PLAYING,
        )

        # Show first 3 tracks after shuffle
        preview = ""
        for i, item in enumerate(list(queue)[:3], 1):
            title = item.get("title", "Unknown") if isinstance(item, dict) else str(item)
            title = title[:30] + "..." if len(title) > 30 else title
            preview += f"`{i}.` {title}\n"
        if len(queue) > 3:
            preview += f"*...and {len(queue) - 3} more*"

        embed.add_field(name="Up Next", value=preview, inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="remove", aliases=["rm", "del"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def remove(self, ctx, position: int | None = None):
        """ลบเพลงออกจากคิวตามตำแหน่ง."""
        if position is None:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Please specify position: `!remove <position>`",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        queue = self.get_queue(ctx)

        if not queue:
            embed = discord.Embed(description=f"{Emojis.CROSS} Queue is empty", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        if position < 1 or position > len(queue):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Invalid position. Queue has {len(queue)} tracks",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        removed = queue[position - 1]
        del queue[position - 1]
        title = removed.get("title", "Unknown") if isinstance(removed, dict) else str(removed)

        embed = discord.Embed(
            title=f"{Emojis.CHECK} Track Removed",
            description=f"Removed **{title}** from position {position}",
            color=Colors.INFO,
        )
        embed.add_field(name="Queue", value=f"`{len(queue)}` tracks remaining", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="seek", aliases=["sk"])
    @commands.guild_only()
    async def seek(self, ctx, position: str | None = None):
        """ข้ามไปยังเวลาที่ต้องการ (MM:SS หรือ seconds)."""
        if not position:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ระบุเวลา: `!seek 1:30` หรือ `!seek 90`",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        if not ctx.voice_client or (not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Nothing is playing", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Parse time
        try:
            if ":" in position:
                parts = position.split(":")
                if len(parts) == 2:
                    minutes, seconds = map(int, parts)
                    if minutes < 0 or seconds < 0 or seconds >= 60:
                        raise ValueError("Invalid time values")
                    seek_time = minutes * 60 + seconds
                elif len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
                        raise ValueError("Invalid time values")
                    seek_time = hours * 3600 + minutes * 60 + seconds
                else:
                    raise ValueError("Invalid format")
            else:
                seek_time = int(position)
                if seek_time < 0:
                    raise ValueError("Time cannot be negative")
        except ValueError as e:
            error_msg = str(e)
            if "Invalid format" in error_msg or "invalid literal" in error_msg.lower():
                msg = f"{Emojis.CROSS} รูปแบบเวลาไม่ถูกต้อง ใช้: `1:30` หรือ `90`"
            else:
                msg = f"{Emojis.CROSS} ค่าเวลาไม่ถูกต้อง: {error_msg}"
            embed = discord.Embed(description=msg, color=Colors.ERROR)
            return await ctx.send(embed=embed)

        guild_id = ctx.guild.id
        track_info = self._gs(guild_id).current_track

        if not track_info:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} No track info found", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Get track duration
        duration = track_info.get("data", {}).get("duration", 0)
        if duration == 0:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Cannot seek in this track (unknown duration)",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)
        if seek_time > duration:
            embed = discord.Embed(
                description=(
                    f"{Emojis.CROSS} Cannot seek beyond track duration "
                    f"({format_duration(duration)})"
                ),
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        # Stop current playback and restart with seek
        self._gs(guild_id).fixing = True
        try:
            ctx.voice_client.stop()

            filename = track_info["filename"]
            data = track_info["data"]

            # Get ffmpeg options with seek
            current_options = get_ffmpeg_options(stream=False, start_time=seek_time)

            player = YTDLSource(
                discord.FFmpegPCMAudio(filename, **current_options, executable="ffmpeg"),  # type: ignore[arg-type]
                data=data,
                filename=filename,
            )

            # Apply volume
            player.volume = self._gs(guild_id).volume

            # Update start time
            track_info["start_time"] = time.time() - seek_time

            # Capture voice_client reference for callback
            vc_seek = ctx.voice_client

            def after_seek(error):
                # Reset fixing flag in callback to prevent race condition
                self._gs(guild_id).fixing = False

                # Guard: Check if voice_client is still valid
                if not vc_seek or not vc_seek.is_connected():
                    if not self._gs(guild_id).loop and filename:
                        self._safe_run_coroutine(self.safe_delete(filename))
                    return

                if not self._gs(guild_id).loop and filename:
                    self._safe_run_coroutine(self.safe_delete(filename))
                if error:
                    logger.error("Seek player error: %s", error)

                # Guard: Don't schedule if already playing or paused
                if vc_seek.is_playing() or vc_seek.is_paused():
                    return

                self._safe_run_coroutine(self.play_next(ctx))

            try:
                vc_seek.play(player, after=after_seek)
            except Exception as e:
                # Reset fixing flag if play() fails
                self._gs(guild_id).fixing = False
                logger.error("Seek play error: %s", e)
                raise
        except Exception as e:
            self._gs(guild_id).fixing = False
            logger.error("Seek failed: %s", e)
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Seek failed — กรุณาลองใหม่อีกครั้ง",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title=f"{Emojis.PLAY} Seeking",
            description=f"Jumped to `{format_duration(seek_time)}`",
            color=Colors.RESUMED,
        )
        embed.add_field(
            name="Track", value=f"**{track_info.get('title', 'Unknown')}**", inline=False
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np", "current"])  # type: ignore[arg-type]
    @commands.guild_only()
    async def nowplaying(self, ctx):
        """แสดงเพลงที่กำลังเล่นอยู่พร้อม progress."""
        guild_id = ctx.guild.id
        track_info = self._gs(guild_id).current_track

        if not track_info:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} No track is currently playing", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if not ctx.voice_client or (
            not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused()
        ):
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Nothing is playing", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Calculate current position
        start_time = track_info.get("start_time", time.time())
        duration = track_info.get("data", {}).get("duration", 0)

        if ctx.voice_client.is_paused() and self._gs(guild_id).pause_start is not None:
            # If paused, use time when paused
            elapsed = self._gs(guild_id).pause_start - start_time
        else:
            elapsed = time.time() - start_time

        elapsed = min(elapsed, duration) if duration else elapsed

        # Create progress bar
        progress_bar = create_progress_bar(elapsed, duration)

        embed = discord.Embed(
            title=f"{Emojis.NOTES} Now Playing",
            description=f"**[{track_info.get('title', 'Unknown')}]"
            f"({track_info.get('data', {}).get('webpage_url', '')})**",
            color=Colors.PLAYING,
        )

        # Thumbnail
        thumbnail = track_info.get("data", {}).get("thumbnail")
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # Progress bar
        status = "⏸️ Paused" if ctx.voice_client.is_paused() else "▶️ Playing"
        embed.add_field(
            name=status,
            value=(
                f"`{progress_bar}`\n`{format_duration(elapsed)}` / `{format_duration(duration)}`"
            ),
            inline=False,
        )

        # Volume and Loop info
        current_vol = int(self._gs(guild_id).volume * 100)
        loop_status = "🔁 On" if self._gs(guild_id).loop else "🔁 Off"

        embed.add_field(name=f"{Emojis.VOLUME} Volume", value=f"`{current_vol}%`", inline=True)
        embed.add_field(name="Loop", value=f"`{loop_status}`", inline=True)

        # Queue info
        queue = self.get_queue(ctx)
        embed.add_field(name=f"{Emojis.QUEUE} Queue", value=f"`{len(queue)}` tracks", inline=True)

        embed.set_footer(text="Use !help for all commands")
        await ctx.send(embed=embed)

    # Owner ID for special commands visibility - use config value
    OWNER_ID = CREATOR_ID

    @commands.command(name="help", aliases=["h"])
    async def help(self, ctx):
        """แสดงคำสั่งช่วยเหลือ."""
        embed = discord.Embed(
            title=f"{Emojis.STAR} Premium Music Bot",
            description="**High Quality Audio Streaming**\nPrefix: `!` • Premium HQ Audio",
            color=Colors.INFO,
        )

        # 🎧 Playback Controls
        embed.add_field(
            name=f"{Emojis.HEADPHONES} Playback Controls",
            value=(
                "`!play` `!p` - เล่นเพลง\n"
                "`!pause` `!pa` - หยุดชั่วคราว\n"
                "`!resume` - เล่นต่อ\n"
                "`!skip` `!s` - ข้ามเพลง\n"
                "`!stop` `!st` - หยุดเล่น\n"
                "`!seek` `!sk` - ข้ามไปเวลา\n"
                "`!loop` `!l` - วนซ้ำ\n"
                "`!fix` `!f` - แก้ไขเสียง"
            ),
            inline=True,
        )

        # 📜 Queue Management
        embed.add_field(
            name=f"{Emojis.QUEUE} Queue & Voice",
            value=(
                "`!queue` `!q` - ดูคิว\n"
                "`!shuffle` `!sh` - สุ่มคิว\n"
                "`!remove` `!rm` - ลบจากคิว\n"
                "`!clear` `!cl` - ล้างคิว\n"
                "`!np` - เพลงปัจจุบัน\n"
                "`!volume` `!v` - ปรับเสียง\n"
                "`!247` - โหมด 24/7\n"
                "`!join` `!j` - เข้าห้อง\n"
                "`!leave` `!dc` - ออก"
            ),
            inline=True,
        )

        # 🧠 AI Commands
        embed.add_field(
            name=f"{Emojis.SPARKLES} AI Assistant",
            value=(
                "`!chat` `!ask` - คุยกับ AI\n"
                "`!thinking` - เปิด/ปิด Thinking\n"
                "`!streaming` - เปิด/ปิด Streaming\n"
                "`!reset_ai` `!rst` - รีเซ็ต AI"
            ),
            inline=True,
        )

        # Audio Quality Info
        embed.add_field(
            name=f"{Emojis.VOLUME} Audio Quality",
            value=("```\n• Codec: Opus/AAC\n• Sample: 48kHz Stereo\n• Quality: Premium HQ\n```"),
            inline=False,
        )

        # 🔧 Owner-only commands (visible only to owner)
        if ctx.author.id == self.OWNER_ID:
            embed.add_field(
                name="🔧 Owner Commands",
                value=(
                    "`!link_memory` `!lm` - คัดลอกความจำ AI\n"
                    "`!move_memory` `!mm` - ย้ายความจำ AI\n"
                    "`!resend` `!rs` - ส่งข้อความ AI ใหม่\n"
                    "`!ratelimit` `!rl` - สถิติ Rate Limit"
                ),
                inline=False,
            )

        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Music Bot v3.2 Pro • !h for help")

        await ctx.send(embed=embed)

    async def cleanup_cache(self):
        """Clean up unused files in temp directory."""
        temp_dir = Path("temp")
        if not await asyncio.to_thread(temp_dir.exists):
            return 0, 0

        # Get list of files currently in use
        def _collect_in_use() -> set[str]:
            in_use: set[str] = set()
            for _, gs in self._guild_states.items():
                track_info = gs.current_track
                if track_info and "filename" in track_info:
                    # Normalize path to handle potential differences
                    in_use.add(str(Path(track_info["filename"]).resolve()))
            return in_use

        in_use_files = await asyncio.to_thread(_collect_in_use)

        deleted_count = 0
        freed_bytes = 0

        # Files modified within this grace window are assumed to be in-flight
        # downloads that haven't been registered as current_track yet.
        # Protects against deleting a file between yt-dlp finishing the download
        # and play_next() claiming it.
        mtime_grace_seconds = 120.0
        now_ts = time.time()

        # Run in executor to avoid blocking
        def _cleanup():
            nonlocal deleted_count, freed_bytes
            for filepath in temp_dir.iterdir():
                abs_path = str(filepath.resolve())

                # Skip directories
                if filepath.is_dir():
                    continue

                # Check if file is in use
                if abs_path in in_use_files:
                    continue

                # Skip recently-modified files (likely in-flight downloads)
                try:
                    if now_ts - filepath.stat().st_mtime < mtime_grace_seconds:
                        continue
                except OSError:
                    # File was removed between iterdir and stat — move on
                    continue

                try:
                    # Get size before deleting
                    size = filepath.stat().st_size
                    filepath.unlink()
                    deleted_count += 1
                    freed_bytes += size
                except PermissionError:
                    # File is locked by another process — skip silently
                    # This is normal for temp files used by active terminals/tests
                    pass
                except OSError as e:
                    logger.warning("Failed to delete unused file %s: %s", filepath, e)
            return deleted_count, freed_bytes

        return await asyncio.get_running_loop().run_in_executor(None, _cleanup)

    @commands.hybrid_command(name="clearcache", aliases=["cc", "clean"])  # type: ignore[arg-type]
    @commands.has_permissions(manage_guild=True)
    async def clearcache(self, ctx):
        """ล้างไฟล์ขยะที่ไม่ได้ใช้งาน."""
        async with ctx.typing():
            count, size = await self.cleanup_cache()

            # Format size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.2f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.2f} MB"

            embed = discord.Embed(
                title=f"{Emojis.TOOLS} Cache Cleaned",
                description=f"Removed **{count}** unused files\nFreed **{size_str}**",
                color=Colors.INFO,
            )
            await ctx.send(embed=embed)

    # ==================== Error Handlers ====================

    @join.error
    async def join_error(self, ctx, error):
        """Handle errors for join command."""
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ต้องมีสิทธิ์ `{missing}` เพื่อเข้าห้องเสียง\n"
                f"กรุณาตรวจสอบ Role ของ Bot ใน Server Settings",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
        else:
            raise error

    @play.error
    async def play_error(self, ctx, error):
        """Handle errors for play command."""
        if isinstance(error, commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=f"{Emojis.CROSS} ไม่มีสิทธิ์",
                description=f"Bot ต้องมีสิทธิ์ `{missing}` เพื่อเล่นเพลง\n"
                f"กรุณาตรวจสอบ Role ของ Bot ใน Server Settings",
                color=Colors.ERROR,
            )
            await ctx.send(embed=embed)
        else:
            raise error

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready."""
        # Clean cache on startup
        count, size = await self.cleanup_cache()
        logger.info("🧹 Startup Cleanup: Removed %s files (%s bytes)", count, size)

        logger.info("ℹ️  %s is Online.", self.bot.user)


async def setup(bot):
    """Setup function to add the Music cog to the bot."""
    await bot.add_cog(Music(bot))
