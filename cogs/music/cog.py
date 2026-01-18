# pylint: disable=too-many-lines
"""
Music Cog Module for Discord Bot.
Provides music playback functionality with YouTube and Spotify support.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from cogs.spotify_handler import SpotifyHandler
from utils.media.ytdl_source import YTDLSource, get_ffmpeg_options

from .utils import Colors, Emojis, create_progress_bar, format_duration

if TYPE_CHECKING:
    from discord.ext.commands import Bot, Context


class MusicControlView(discord.ui.View):
    """Interactive music control buttons."""

    def __init__(self, cog: Music, guild_id: int, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user is in the same voice channel."""
        if not interaction.user.voice:
            await interaction.response.send_message("❌ คุณต้องอยู่ในห้องเสียงก่อน", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="music_pause")
    async def pause_resume_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Toggle pause/resume."""
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("❌ บอทไม่ได้เล่นเพลงอยู่", ephemeral=True)
            return

        if voice_client.is_paused():
            voice_client.resume()
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self)
        elif voice_client.is_playing():
            voice_client.pause()
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงให้หยุดชั่วคราว", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Skip current track."""
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            self.cog.loops[self.guild_id] = False  # Disable loop
            voice_client.stop()
            await interaction.response.send_message("⏭️ ข้ามเพลง", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงให้ข้าม", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stop playback and clear queue."""
        self.cog.queues[self.guild_id] = []
        self.cog.loops[self.guild_id] = False
        self.cog.current_track.pop(self.guild_id, None)

        voice_client = interaction.guild.voice_client
        if voice_client:
            voice_client.stop()

        await interaction.response.send_message("⏹️ หยุดเล่นและล้างคิวแล้ว", ephemeral=True)
        self.stop()  # Stop the view

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle loop mode."""
        current_loop = self.cog.loops.get(self.guild_id, False)
        self.cog.loops[self.guild_id] = not current_loop

        if self.cog.loops[self.guild_id]:
            button.style = discord.ButtonStyle.success
            await interaction.response.send_message("🔁 เปิดโหมดวนซ้ำ", ephemeral=True)
        else:
            button.style = discord.ButtonStyle.secondary
            await interaction.response.send_message("➡️ ปิดโหมดวนซ้ำ", ephemeral=True)

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for child in self.children:
            child.disabled = True


class Music(commands.Cog):
    """Music Cog - Provides music playback with YouTube and Spotify support."""

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.queues: dict[int, list[dict[str, Any]]] = {}  # Guild ID -> List of queries/urls
        self.loops: dict[int, bool] = {}  # Guild ID -> Boolean
        # Guild ID -> Track Info (cleaned version)
        self.current_track: dict[int, dict[str, Any]] = {}
        self.fixing: dict[int, bool] = {}  # Guild ID -> Boolean (Fixing state)
        self.pause_start: dict[int, float] = {}  # Guild ID -> Timestamp when paused
        self.play_locks: dict[int, asyncio.Lock] = {}  # Guild ID -> asyncio.Lock
        self.volumes: dict[int, float] = {}  # Guild ID -> Volume (0.0 - 2.0)
        self.auto_disconnect_tasks: dict[int, asyncio.Task] = {}  # Guild ID -> asyncio.Task
        self.mode_247: dict[int, bool] = {}  # Guild ID -> Boolean (24/7 mode enabled)
        self.last_text_channel: dict[int, int] = {}  # Guild ID -> Channel ID (last used)
        self.spotify: SpotifyHandler = SpotifyHandler(bot)
        self.auto_disconnect_delay: int = 180  # 3 minutes

    async def cog_unload(self) -> None:
        """Cleanup when cog is unloaded."""
        # Cancel all auto-disconnect tasks
        for task in self.auto_disconnect_tasks.values():
            task.cancel()
        # Clear all stored data to prevent memory leaks
        self.queues.clear()
        self.loops.clear()
        self.current_track.clear()
        self.fixing.clear()
        self.pause_start.clear()
        self.play_locks.clear()
        self.volumes.clear()
        self.auto_disconnect_tasks.clear()
        self.mode_247.clear()
        self.last_text_channel.clear()
        logging.info("🎵 Music Cog unloaded - all data cleaned up")

    async def cleanup_guild_data(self, guild_id: int) -> None:
        """Clean up all data for a specific guild."""
        # Save queue before cleanup for persistence
        await self.save_queue(guild_id)

        # Cancel auto-disconnect task if exists
        if guild_id in self.auto_disconnect_tasks:
            self.auto_disconnect_tasks[guild_id].cancel()
            self.auto_disconnect_tasks.pop(guild_id, None)
        self.queues.pop(guild_id, None)
        self.loops.pop(guild_id, None)
        self.current_track.pop(guild_id, None)
        self.fixing.pop(guild_id, None)
        self.pause_start.pop(guild_id, None)
        self.play_locks.pop(guild_id, None)
        self.volumes.pop(guild_id, None)
        # Note: We don't remove mode_247 here so 24/7 setting persists

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        """Called before every command - track last used text channel."""
        if ctx.guild:
            self.last_text_channel[ctx.guild.id] = ctx.channel.id

    async def save_queue(self, guild_id: int) -> None:
        """Save queue to database for persistence across restarts."""
        queue = self.queues.get(guild_id, [])

        # Import database only when needed
        try:
            from utils.database import db
        except ImportError:
            # Fallback to JSON if database not available
            self._save_queue_json(guild_id)
            return

        if not queue:
            # Clear queue from database if empty
            await db.clear_music_queue(guild_id)
            return

        # Save to database
        await db.save_music_queue(guild_id, queue)
        logging.info("💾 Saved queue for guild %s (%d tracks) to database", guild_id, len(queue))

    def _save_queue_json(self, guild_id: int) -> None:
        """Legacy JSON save as fallback."""
        queue = self.queues.get(guild_id, [])
        if not queue:
            filepath = Path(f"data/queue_{guild_id}.json")
            if filepath.exists():
                with contextlib.suppress(OSError):
                    filepath.unlink()
            return

        data = {
            "queue": queue,
            "volume": self.volumes.get(guild_id, 0.5),
            "loop": self.loops.get(guild_id, False),
            "mode_247": self.mode_247.get(guild_id, False),
        }

        try:
            filepath = Path(f"data/queue_{guild_id}.json")
            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            logging.error("Failed to save queue for guild %s: %s", guild_id, e)

    async def load_queue(self, guild_id: int) -> bool:
        """Load queue from database. Returns True if queue was loaded."""
        # Try database first
        try:
            from utils.database import db

            queue = await db.load_music_queue(guild_id)
            if queue:
                self.queues[guild_id] = queue
                logging.info(
                    "📂 Loaded queue for guild %s (%d tracks) from database", guild_id, len(queue)
                )
                return True
        except ImportError:
            pass

        # Fallback to JSON file
        filepath = Path(f"data/queue_{guild_id}.json")
        if not filepath.exists():
            return False

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))

            queue = data.get("queue", [])
            if queue:
                self.queues[guild_id] = queue
                self.volumes[guild_id] = data.get("volume", 0.5)
                self.loops[guild_id] = data.get("loop", False)
                self.mode_247[guild_id] = data.get("mode_247", False)
                logging.info(
                    "📂 Loaded queue for guild %s (%d tracks) from JSON", guild_id, len(queue)
                )

                # Remove file after loading (migrated to DB)
                filepath.unlink()
                return True
        except (OSError, json.JSONDecodeError) as e:
            logging.error("Failed to load queue for guild %s: %s", guild_id, e)

        return False

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Clean up when bot is removed from a guild."""
        await self.cleanup_guild_data(guild.id)
        logging.info("🧹 Cleaned up data for guild %s", guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Handle voice state changes for auto-disconnect and cleanup."""
        # Only process if bot is involved or member left bot's channel
        if not self.bot.user:
            return

        # Check all guilds where bot is connected
        for vc in self.bot.voice_clients:
            # Check if voice client has guild and channel
            if not vc.guild or not vc.channel:
                continue

            guild = vc.guild
            guild_id = guild.id

            # Bot was disconnected
            if member == self.bot.user and before.channel and not after.channel:
                logging.info("🔌 Bot disconnected from voice in guild %s - cleaning up", guild_id)
                await self.cleanup_guild_data(guild_id)
                continue

            # Bot was moved to another channel
            if member == self.bot.user and before.channel != after.channel and after.channel:
                # Cancel any pending auto-disconnect
                if guild_id in self.auto_disconnect_tasks:
                    self.auto_disconnect_tasks[guild_id].cancel()
                    self.auto_disconnect_tasks.pop(guild_id, None)
                continue

            # Check if someone left bot's channel
            if before.channel == vc.channel and after.channel != vc.channel:
                # Skip auto-disconnect if 24/7 mode is enabled
                if self.mode_247.get(guild_id, False):
                    continue

                # Count humans in channel (exclude bots) - check if channel exists
                if not vc.channel:
                    continue
                humans = [m for m in vc.channel.members if not m.bot]
                if len(humans) == 0:
                    # Start auto-disconnect countdown
                    if guild_id not in self.auto_disconnect_tasks:
                        self.auto_disconnect_tasks[guild_id] = asyncio.create_task(
                            self._auto_disconnect(guild_id, vc)
                        )
                        logging.info("⏳ Started auto-disconnect timer for guild %s", guild_id)

            # Check if someone joined bot's channel
            if after.channel == vc.channel and before.channel != vc.channel:
                # Cancel auto-disconnect if someone joins
                if guild_id in self.auto_disconnect_tasks:
                    self.auto_disconnect_tasks[guild_id].cancel()
                    self.auto_disconnect_tasks.pop(guild_id, None)
                    logging.info(
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
                if guild_id in self.last_text_channel:
                    last_channel_id = self.last_text_channel[guild_id]
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
                    await text_channel.send(embed=embed)

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

                    logging.info("👋 Auto-disconnected from guild %s due to inactivity", guild_id)

        except asyncio.CancelledError:
            # Task was cancelled (someone joined)
            pass
        except discord.DiscordException as e:
            logging.error("Auto-disconnect error: %s", e)
        finally:
            # Remove task from dict
            self.auto_disconnect_tasks.pop(guild_id, None)

    async def safe_delete(self, filename):
        """Safely delete a file with retries (Non-blocking)."""
        await asyncio.sleep(2)  # Wait for ffmpeg to fully release

        def _delete():
            filepath = Path(filename)
            for i in range(5):  # 5 retries with 1 second delay
                try:
                    if filepath.exists():
                        filepath.unlink()
                        logging.info("🗑️ Deleted %s", filename)
                    return True
                except PermissionError:
                    if i < 4:
                        time.sleep(1.0)  # Wait 1s between retries
                    else:
                        # Final retry failed
                        logging.warning(
                            "❌ Could not delete %s after %d retries (PermissionError)",
                            filename,
                            i + 1,
                        )
                        return False
                except OSError as e:
                    logging.warning("Failed to delete %s: %s", filename, e)
                    return False
            # Should not reach here, but just in case
            return False

        await self.bot.loop.run_in_executor(None, _delete)

    def get_queue(self, ctx) -> list[dict[str, Any]]:
        """Get or create queue for a guild."""
        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []
        return self.queues[ctx.guild.id]

    async def play_next(self, ctx: Context) -> None:
        """Play the next track in the queue."""
        # Check if voice_client exists
        if not ctx.voice_client:
            return

        if ctx.guild.id not in self.play_locks:
            self.play_locks[ctx.guild.id] = asyncio.Lock()

        # Prevent race condition: check if lock is already acquired
        if self.play_locks[ctx.guild.id].locked():
            logging.debug("play_next already in progress for guild %s", ctx.guild.id)
            return

        async with self.play_locks[ctx.guild.id]:
            # Check voice_client again inside lock
            if not ctx.voice_client:
                return

            # Double check if playing inside lock to prevent race conditions
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                return

            # 1. Check Loop Mode
            if self.loops.get(ctx.guild.id) and self.current_track.get(ctx.guild.id):
                # Replay current track
                track_info = self.current_track[ctx.guild.id]
                filename = track_info["filename"]
                data = track_info["data"]

                if Path(filename).exists():
                    try:
                        # Verify voice_client is still valid
                        if not ctx.voice_client or not ctx.voice_client.is_connected():
                            logging.warning("Voice client disconnected during loop replay")
                            return

                        # Recreate player from existing file
                        current_options = get_ffmpeg_options(stream=False)
                        player = YTDLSource(
                            discord.FFmpegPCMAudio(
                                filename, **current_options, executable="ffmpeg"
                            ),
                            data=data,
                            filename=filename,
                        )

                        # Update start time
                        self.current_track[ctx.guild.id]["start_time"] = time.time()

                        def after_playing_loop(error):
                            if self.fixing.get(ctx.guild.id):
                                return  # Skip if fixing

                            # Guard: Check if voice_client is still valid
                            if not ctx.voice_client or not ctx.voice_client.is_connected():
                                return

                            if not self.loops.get(ctx.guild.id):
                                # Loop disabled during play -> Delete file
                                asyncio.run_coroutine_threadsafe(
                                    self.safe_delete(filename), self.bot.loop
                                )

                            if error:
                                logging.error("Loop error: %s", error)

                            # Guard: Don't schedule if already playing or paused
                            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                                return

                            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

                        ctx.voice_client.play(player, after=after_playing_loop)

                        # Loop embed
                        embed = discord.Embed(
                            title=f"{Emojis.LOOP} Looping",
                            description=f"**{player.title}**",
                            color=Colors.LOOP,
                        )
                        embed.set_footer(text="Use !loop to disable • !skip to skip")
                        await ctx.send(embed=embed)
                        return
                    except (discord.DiscordException, OSError) as e:
                        logging.error("Loop replay failed: %s", e)
                        self.loops[ctx.guild.id] = False  # Disable loop on error

            # 2. Normal Queue Logic
            queue = self.get_queue(ctx)
            if len(queue) > 0:
                item = queue.pop(0)
                url = item.get("url") if isinstance(item, dict) else item

                try:
                    async with ctx.typing():
                        # Use Download Mode (stream=False)
                        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=False)

                        # Save current track info (only essential data)
                        self.current_track[ctx.guild.id] = {
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

                        def after_playing(error):
                            if self.fixing.get(ctx.guild.id):
                                return  # Skip if fixing

                            # Guard: Check if voice_client is still valid
                            if not ctx.voice_client or not ctx.voice_client.is_connected():
                                # Cleanup file even if disconnected
                                if player.filename and not self.loops.get(ctx.guild.id):
                                    asyncio.run_coroutine_threadsafe(
                                        self.safe_delete(player.filename), self.bot.loop
                                    )
                                return

                            # Cleanup: Delete file ONLY if loop is OFF
                            if not self.loops.get(ctx.guild.id):
                                if player.filename:
                                    asyncio.run_coroutine_threadsafe(
                                        self.safe_delete(player.filename), self.bot.loop
                                    )

                            if error:
                                logging.error("Player error: %s", error)

                            # Guard: Don't schedule if already playing or paused
                            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                                return

                            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

                        try:
                            ctx.voice_client.play(player, after=after_playing)
                        except (discord.DiscordException, OSError) as e:
                            logging.error("Failed to start playback: %s", e)
                            # Cleanup file on error
                            if player.filename and not self.loops.get(ctx.guild.id):
                                asyncio.run_coroutine_threadsafe(
                                    self.safe_delete(player.filename), self.bot.loop
                                )
                            # Try next track
                            await self.play_next(ctx)
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
                        if self.loops.get(ctx.guild.id)
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
                    await ctx.send(embed=embed, view=view)
                    await self.bot.change_presence(
                        activity=discord.Activity(
                            type=discord.ActivityType.listening, name=player.title
                        )
                    )
                except (discord.DiscordException, OSError) as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Playback Error",
                        description=f"Failed to play next track\n```{e}```",
                        color=Colors.ERROR,
                    )
                    await ctx.send(embed=embed)
                    logging.error("Play error: %s\n%s", e, traceback.format_exc())
                    await self.play_next(ctx)  # Try next one
            else:
                # Queue empty
                self.current_track.pop(ctx.guild.id, None)  # Clear track info
                await self.bot.change_presence(
                    activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
                )

    @commands.hybrid_command(name="loop", aliases=["l"])
    async def loop(self, ctx):
        """เปิด/ปิด โหมดวนซ้ำเพลงปัจจุบัน."""
        current = self.loops.get(ctx.guild.id, False)
        self.loops[ctx.guild.id] = not current

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

    @commands.hybrid_command(name="pause", aliases=["pa"])
    async def pause(self, ctx):
        """หยุดเล่นเพลงชั่วคราว."""
        if not ctx.voice_client:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Bot ไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            self.pause_start[ctx.guild.id] = time.time()

            # Get current track info for embed
            track_info = self.current_track.get(ctx.guild.id, {})
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

    @commands.hybrid_command(name="resume", aliases=["unpause"])
    async def resume(self, ctx):
        """เล่นเพลงต่อ."""
        if not ctx.voice_client:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Bot ไม่ได้อยู่ในห้องเสียง", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        if ctx.voice_client.is_paused():
            # Calculate paused duration
            if ctx.guild.id in self.pause_start:
                paused_duration = time.time() - self.pause_start[ctx.guild.id]
                # Shift start time forward
                if ctx.guild.id in self.current_track:
                    self.current_track[ctx.guild.id]["start_time"] += paused_duration
                self.pause_start.pop(ctx.guild.id, None)

            ctx.voice_client.resume()

            # Get current track info for embed
            track_info = self.current_track.get(ctx.guild.id, {})
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

    @commands.hybrid_command(name="fix", aliases=["f", "reconnect"])
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
        track_info = self.current_track.get(guild_id)
        if not track_info:
            embed = discord.Embed(description=f"{Emojis.CROSS} ไม่พบข้อมูลเพลง", color=Colors.ERROR)
            return await ctx.send(embed=embed)

        # 1. Calculate elapsed time
        start_time = track_info.get("start_time", 0)
        elapsed = 0
        if start_time > 0:
            if ctx.voice_client.is_paused() and guild_id in self.pause_start:
                # If paused, elapsed is time until pause
                elapsed = self.pause_start[guild_id] - start_time
            else:
                # If playing, elapsed is time until now
                elapsed = time.time() - start_time

        # 2. Stop and Disconnect (Set fixing flag)
        self.fixing[guild_id] = True

        # Clear pause state if exists (since we will resume playing)
        self.pause_start.pop(guild_id, None)

        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()

        try:
            # 3. Reconnect
            if ctx.message.author.voice:
                channel = ctx.message.author.voice.channel
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

            # Restore current_track (cleanup may have removed it during disconnect)
            self.current_track[guild_id] = track_info

            # Update start time to now - elapsed
            self.current_track[guild_id]["start_time"] = time.time() - elapsed

            def after_playing_fix(error):
                if self.fixing.get(guild_id):
                    return

                # Cleanup logic - use safe_delete
                if not self.loops.get(guild_id) and filename:
                    asyncio.run_coroutine_threadsafe(self.safe_delete(filename), self.bot.loop)

                if error:
                    logging.error("Fix player error: %s", error)
                asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

            ctx.voice_client.play(player, after=after_playing_fix)

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

        except (discord.DiscordException, OSError) as e:
            error_embed = discord.Embed(
                title=f"{Emojis.CROSS} แก้ไขไม่สำเร็จ", description=f"```{e}```", color=Colors.ERROR
            )
            await fix_msg.edit(embed=error_embed)
            logging.error("Fix failed: %s", e)
        finally:
            # Always reset fixing flag at the end
            self.fixing[guild_id] = False

    @commands.hybrid_command(name="join", aliases=["j", "connect"])
    async def join(self, ctx):
        """เข้าร่วมช่องเสียง."""
        if not ctx.message.author.voice:
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} คุณต้องอยู่ในห้องเสียงก่อน"), color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        channel = ctx.message.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
            embed = discord.Embed(
                description=f"{Emojis.CHECK} ย้ายไป **{channel.name}**", color=Colors.RESUMED
            )
            return await ctx.send(embed=embed)

        await channel.connect()
        embed = discord.Embed(
            title=f"{Emojis.HEADPHONES} เชื่อมต่อแล้ว",
            description=f"เข้าร่วม **{channel.name}**",
            color=Colors.RESUMED,
        )
        embed.set_footer(text="ใช้ !play <ชื่อเพลง> เพื่อเล่นเพลง")
        await ctx.send(embed=embed)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: Context, *, query: str | None = None) -> None:
        """เล่นเพลงจาก YouTube หรือ Spotify."""
        # Validate query parameter
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
            return await ctx.send(embed=embed)

        if not ctx.message.author.voice:
            embed = discord.Embed(
                description=(f"{Emojis.CROSS} คุณต้องอยู่ในห้องเสียงก่อน"), color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Connect if not connected
        if ctx.voice_client is None:
            try:
                await ctx.message.author.voice.channel.connect()
            except discord.DiscordException as e:
                embed = discord.Embed(
                    description=f"{Emojis.CROSS} เชื่อมต่อไม่สำเร็จ: {e}", color=Colors.ERROR
                )
                return await ctx.send(embed=embed)
        elif (
            ctx.voice_client.channel
            and ctx.voice_client.channel != ctx.message.author.voice.channel
        ):
            # Move to user's channel if in different channel
            await ctx.voice_client.move_to(ctx.message.author.voice.channel)

        queue = self.get_queue(ctx)

        # Check if Spotify URL
        if "open.spotify.com" in query and self.spotify.is_available():
            success = await self.spotify.process_spotify_url(ctx, query, queue)
            if not success:
                return
        else:
            # YouTube / Search
            async with ctx.typing():
                try:
                    # Use search_source to get info first
                    info = await YTDLSource.search_source(query, loop=self.bot.loop)
                    if info:
                        title = info.get("title", "Unknown Title")
                        url = info.get("webpage_url", query)
                        thumbnail = info.get("thumbnail", None)
                        duration = info.get("duration", 0)
                        uploader = info.get("uploader", "Unknown")

                        queue.append({"url": url, "title": title, "type": "url"})

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
                        embed = discord.Embed(
                            description=(f"{Emojis.CROSS} No results found for: `{query}`"),
                            color=Colors.ERROR,
                        )
                        await ctx.send(embed=embed)
                        return
                except (discord.DiscordException, OSError) as e:
                    embed = discord.Embed(
                        title=f"{Emojis.CROSS} Error", description=f"```{e}```", color=Colors.ERROR
                    )
                    await ctx.send(embed=embed)
                    logging.error("Search error: %s", e)
                    return

        # If not playing, start playing
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_next(ctx)

    @commands.hybrid_command(name="skip", aliases=["s"])
    async def skip(self, ctx):
        """ข้ามเพลงปัจจุบัน."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            # Disable loop when skipping
            self.loops[ctx.guild.id] = False
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
    async def queue(self, ctx):
        """แสดงรายการเพลงในคิว."""
        queue = self.get_queue(ctx)
        loop_status = f"{Emojis.CHECK}" if self.loops.get(ctx.guild.id) else f"{Emojis.CROSS}"

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
            current = self.current_track.get(ctx.guild.id, {})
            if current:
                now_playing = current.get("title", "Unknown")
                embed.add_field(
                    name=f"{Emojis.NOTES} Now Playing", value=f"**{now_playing}**", inline=False
                )

            # Queue List (with numbers)
            description = ""
            for i, item in enumerate(queue[:10], 1):
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

    @commands.hybrid_command(name="stop", aliases=["st"])
    async def stop(self, ctx):
        """หยุดเล่นและล้างคิว."""
        self.queues[ctx.guild.id] = []
        self.loops[ctx.guild.id] = False  # Disable loop
        self.current_track.pop(ctx.guild.id, None)

        if ctx.voice_client:
            ctx.voice_client.stop()

        await self.bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name="คำสั่งเพลง")
        )

        embed = discord.Embed(
            title=f"{Emojis.STOP} หยุดแล้ว", description="หยุดเล่นและล้างคิวแล้ว", color=Colors.STOP
        )
        await ctx.send(embed=embed)

    @commands.command(name="clear", aliases=["cl", "clr"])
    async def clear(self, ctx):
        """ล้างคิวเพลงทั้งหมด (แต่ไม่หยุดเพลงที่เล่นอยู่)."""
        cleared_count = len(self.queues.get(ctx.guild.id, []))
        self.queues[ctx.guild.id] = []

        embed = discord.Embed(
            title=f"{Emojis.CHECK} ล้างคิวแล้ว",
            description=f"ลบ **{cleared_count}** เพลงออกจากคิว",
            color=Colors.INFO,
        )
        embed.set_footer(text="เพลงปัจจุบันจะเล่นต่อ")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leave", aliases=["disconnect", "dc"])
    async def leave(self, ctx):
        """ออกจากช่องเสียง."""
        if ctx.voice_client:
            # Cleanup
            self.queues[ctx.guild.id] = []
            self.loops[ctx.guild.id] = False
            self.current_track.pop(ctx.guild.id, None)

            await ctx.voice_client.disconnect()
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
    async def volume(self, ctx, volume: int | None = None):
        """ปรับระดับเสียง (0-200%)."""
        if volume is None:
            current_vol = int(self.volumes.get(ctx.guild.id, 0.5) * 100)
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

        self.volumes[ctx.guild.id] = volume / 100.0

        # Apply to current player if playing
        if ctx.voice_client and ctx.voice_client.source:
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

    @commands.hybrid_command(name="247", aliases=["24/7", "stay", "nonstop"])
    @commands.has_permissions(manage_channels=True)
    async def mode_247_toggle(self, ctx):
        """เปิด/ปิดโหมด 24/7 - Bot อยู่ในห้องตลอดเวลา."""
        guild_id = ctx.guild.id
        current = self.mode_247.get(guild_id, False)

        # Toggle mode
        self.mode_247[guild_id] = not current
        new_state = self.mode_247[guild_id]

        if new_state:
            # Cancel any pending auto-disconnect
            if guild_id in self.auto_disconnect_tasks:
                self.auto_disconnect_tasks[guild_id].cancel()
                self.auto_disconnect_tasks.pop(guild_id, None)

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
    async def shuffle(self, ctx):
        """สุ่มลำดับเพลงในคิว."""
        queue = self.get_queue(ctx)

        if len(queue) < 2:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} Need at least 2 tracks in queue to shuffle",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        random.shuffle(queue)

        embed = discord.Embed(
            title=f"{Emojis.SPARKLES} Queue Shuffled!",
            description=f"Shuffled **{len(queue)}** tracks",
            color=Colors.PLAYING,
        )

        # Show first 3 tracks after shuffle
        preview = ""
        for i, item in enumerate(queue[:3], 1):
            title = item.get("title", "Unknown") if isinstance(item, dict) else str(item)
            title = title[:30] + "..." if len(title) > 30 else title
            preview += f"`{i}.` {title}\n"
        if len(queue) > 3:
            preview += f"*...and {len(queue) - 3} more*"

        embed.add_field(name="Up Next", value=preview, inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="remove", aliases=["rm", "del"])
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

        removed = queue.pop(position - 1)
        title = removed.get("title", "Unknown") if isinstance(removed, dict) else str(removed)

        embed = discord.Embed(
            title=f"{Emojis.CHECK} Track Removed",
            description=f"Removed **{title}** from position {position}",
            color=Colors.INFO,
        )
        embed.add_field(name="Queue", value=f"`{len(queue)}` tracks remaining", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="seek", aliases=["sk"])
    async def seek(self, ctx, position: str | None = None):
        """ข้ามไปยังเวลาที่ต้องการ (MM:SS หรือ seconds)."""
        if not position:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} ระบุเวลา: `!seek 1:30` หรือ `!seek 90`",
                color=Colors.ERROR,
            )
            return await ctx.send(embed=embed)

        if not ctx.voice_client or not ctx.voice_client.is_playing():
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
        track_info = self.current_track.get(guild_id)

        if not track_info:
            embed = discord.Embed(
                description=f"{Emojis.CROSS} No track info found", color=Colors.ERROR
            )
            return await ctx.send(embed=embed)

        # Get track duration
        duration = track_info.get("data", {}).get("duration", 0)
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
        self.fixing[guild_id] = True
        ctx.voice_client.stop()

        filename = track_info["filename"]
        data = track_info["data"]

        # Get ffmpeg options with seek
        current_options = get_ffmpeg_options(stream=False, start_time=seek_time)

        player = YTDLSource(
            discord.FFmpegPCMAudio(filename, **current_options, executable="ffmpeg"),
            data=data,
            filename=filename,
        )

        # Apply volume
        player.volume = self.volumes.get(guild_id, 0.5)

        # Update start time
        self.current_track[guild_id]["start_time"] = time.time() - seek_time

        def after_seek(error):
            # Reset fixing flag in callback to prevent race condition
            self.fixing[guild_id] = False
            if not self.loops.get(guild_id) and filename:
                asyncio.run_coroutine_threadsafe(self.safe_delete(filename), self.bot.loop)
            if error:
                logging.error("Seek player error: %s", error)
            asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

        ctx.voice_client.play(player, after=after_seek)

        embed = discord.Embed(
            title=f"{Emojis.PLAY} Seeking",
            description=f"Jumped to `{format_duration(seek_time)}`",
            color=Colors.RESUMED,
        )
        embed.add_field(
            name="Track", value=f"**{track_info.get('title', 'Unknown')}**", inline=False
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np", "current"])
    async def nowplaying(self, ctx):
        """แสดงเพลงที่กำลังเล่นอยู่พร้อม progress."""
        guild_id = ctx.guild.id
        track_info = self.current_track.get(guild_id)

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

        if ctx.voice_client.is_paused() and guild_id in self.pause_start:
            # If paused, use time when paused
            elapsed = self.pause_start[guild_id] - start_time
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
        current_vol = int(self.volumes.get(guild_id, 0.5) * 100)
        loop_status = "🔁 On" if self.loops.get(guild_id) else "🔁 Off"

        embed.add_field(name=f"{Emojis.VOLUME} Volume", value=f"`{current_vol}%`", inline=True)
        embed.add_field(name="Loop", value=f"`{loop_status}`", inline=True)

        # Queue info
        queue = self.get_queue(ctx)
        embed.add_field(name=f"{Emojis.QUEUE} Queue", value=f"`{len(queue)}` tracks", inline=True)

        embed.set_footer(text="Use !help for all commands")
        await ctx.send(embed=embed)

    # Owner ID for special commands visibility
    OWNER_ID = 781560793719636019

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

        if self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Music Bot v3.1 Pro • !h for help")

        await ctx.send(embed=embed)

    async def cleanup_cache(self):
        """Clean up unused files in temp directory."""
        temp_dir = Path("temp")
        if not temp_dir.exists():
            return 0, 0

        # Get list of files currently in use
        in_use_files = set()
        for _, track_info in self.current_track.items():
            if track_info and "filename" in track_info:
                # Normalize path to handle potential differences
                in_use_files.add(str(Path(track_info["filename"]).resolve()))

        deleted_count = 0
        freed_bytes = 0

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

                try:
                    # Get size before deleting
                    size = filepath.stat().st_size
                    filepath.unlink()
                    deleted_count += 1
                    freed_bytes += size
                except (OSError, PermissionError) as e:
                    logging.warning("Failed to delete unused file %s: %s", filepath, e)
            return deleted_count, freed_bytes

        return await self.bot.loop.run_in_executor(None, _cleanup)

    @commands.hybrid_command(name="clearcache", aliases=["cc", "clean"])
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

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready."""
        # Clean cache on startup
        count, size = await self.cleanup_cache()
        logging.info("🧹 Startup Cleanup: Removed %s files (%s bytes)", count, size)

        logging.info("ℹ️  %s is Online.", self.bot.user)
        await self.bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="Private Music Server 🔒"
            ),
            status=discord.Status.dnd,
        )


async def setup(bot):
    """Setup function to add the Music cog to the bot."""
    await bot.add_cog(Music(bot))
