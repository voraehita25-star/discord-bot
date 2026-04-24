# pyright: reportArgumentType=false
# pyright: reportAttributeAccessIssue=false
"""
AI Cog Module for Discord Bot.
Handles AI chat interactions using Claude API with context management.

Note: Type checker warnings for Discord.py channel/user type unions are suppressed
because the runtime behavior handles these correctly through duck typing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
logger = logging.getLogger(__name__)
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import discord
from discord.ext import commands

from utils.reliability.rate_limiter import check_rate_limit, rate_limiter

from ..music.utils import Colors
from .data.constants import (
    CHANNEL_ID_ALLOWED,
    CHANNEL_ID_RP_COMMAND,
    CHANNEL_ID_RP_OUTPUT,
    CREATOR_ID,
    GUILD_ID_COMMAND_ONLY,
    GUILD_ID_MAIN,
    GUILD_ID_RESTRICTED,
    GUILD_ID_RP,
)

# Centralized optional dependencies
from .imports import (
    FEEDBACK_AVAILABLE,  # noqa: F401 (re-exported for tests)
    GUARDRAILS_AVAILABLE,
    LOCALIZATION_AVAILABLE,  # noqa: F401 (re-exported for tests)
    add_feedback_reactions,  # noqa: F401 (re-exported for tests)
    feedback_collector,  # noqa: F401 (re-exported for tests)
    is_unrestricted,
    msg,  # noqa: F401 (re-exported for tests)
    msg_en,  # noqa: F401 (re-exported for tests)
    set_unrestricted,
    unrestricted_channels,
)
from .logic import ChatManager
from .memory.rag import rag_system
from .storage import (
    cleanup_cache as cleanup_storage_cache,
    copy_history,
    delete_history,
    get_all_channel_ids,
    get_last_model_message,
    get_message_by_local_id,
    move_history,
)
from .tools import (
    invalidate_webhook_cache_on_channel_delete,
    send_as_webhook,
    start_webhook_cache_cleanup,
    stop_webhook_cache_cleanup,
)

if TYPE_CHECKING:
    from discord.ext.commands import Bot, Context


class AI(commands.Cog):
    """AI Chat Cog - Provides AI conversation capabilities via Claude."""

    # Owner ID for special commands (loaded from environment)
    OWNER_ID = CREATOR_ID

    # Constants for webhook cache
    _WEBHOOK_CACHE_TTL = 300.0  # 5 minutes
    _WEBHOOK_CACHE_MAX_SIZE = 256

    # Known proxy-bot user IDs used to verify Tupperbox/PluralKit webhooks.
    # Moved to class scope to avoid reallocating on every message event.
    _ALLOWED_WEBHOOK_BOT_IDS: frozenset[int] = frozenset({
        356950275044671499,  # Tupperbox
        466378653216014359,  # PluralKit
    })

    # Pre-compiled pattern for {{Character}} resend splitting.
    _RESEND_CHARACTER_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

    # Discord message length cap.
    _DISCORD_MAX_MESSAGE_LEN = 2000

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.chat_manager: ChatManager = ChatManager(bot)
        self.cleanup_task: asyncio.Task | None = None
        self._pending_request_cleanup_task: asyncio.Task | None = None
        self._cache_cleanup_task: asyncio.Task | None = None
        # Cache for verified webhook IDs to avoid repeated API calls
        # Maps webhook_id -> (is_known_proxy: bool, expires_at: float)
        self._webhook_verify_cache: dict[int, tuple[bool, float]] = {}
        # Rate limiter cleanup will be started in cog_load()

    @staticmethod
    def _on_bg_task_done(task: asyncio.Task) -> None:
        """Callback for background tasks to log unexpected failures."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background task %s failed: %s", task.get_name(), exc, extra={"event": "bg_task_failed", "task": task.get_name()})

    @staticmethod
    def _as_chat_channel(
        channel: object,
    ) -> discord.TextChannel | discord.Thread | discord.DMChannel | None:
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
            return channel
        return None

    @staticmethod
    def _as_fetchable_channel(channel: object) -> discord.TextChannel | discord.Thread | None:
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel
        return None

    @staticmethod
    def _as_text_channel(channel: object) -> discord.TextChannel | None:
        if isinstance(channel, discord.TextChannel):
            return channel
        return None

    async def cog_load(self) -> None:
        """Called when the cog is loaded - safe place for async initialization."""
        # Cancel any leftover tasks from a previous load (e.g. hot-reload via !reload)
        for task_attr in ("cleanup_task", "_pending_request_cleanup_task", "_cache_cleanup_task"):
            old = getattr(self, task_attr, None)
            if old is not None and not old.done():
                old.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await old

        # Start rate limiter cleanup (requires running event loop)
        rate_limiter.start_cleanup_task()
        self.cleanup_task = asyncio.create_task(self.chat_manager.cleanup_inactive_sessions())
        self.cleanup_task.add_done_callback(self._on_bg_task_done)
        # Start webhook cache cleanup task
        start_webhook_cache_cleanup(self.bot)

        # Start RAG FAISS periodic save (every 5 min)
        rag_system.start_periodic_save(interval=300.0)

        # Start pending request cleanup task
        self._pending_request_cleanup_task = asyncio.create_task(
            self._cleanup_pending_requests_loop()
        )
        self._pending_request_cleanup_task.add_done_callback(self._on_bg_task_done)

        # Start AI cache background cleanup (every hour)
        try:
            from cogs.ai_core.cache.ai_cache import ai_cache

            self._cache_cleanup_task = asyncio.create_task(ai_cache.start_cleanup_loop())
            self._cache_cleanup_task.add_done_callback(self._on_bg_task_done)
        except ImportError:
            pass

        logger.info("🧠 AI Cog loaded successfully", extra={"event": "cog_loaded", "cog": "ai_core"})

    async def cog_unload(self) -> None:
        """Called when the cog is unloaded - cleanup resources."""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.cleanup_task

        # Cancel pending request cleanup task
        if self._pending_request_cleanup_task:
            self._pending_request_cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pending_request_cleanup_task

        # Cancel cache cleanup task
        if self._cache_cleanup_task:
            self._cache_cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cache_cleanup_task

        # Stop webhook cache cleanup task
        await stop_webhook_cache_cleanup()

        # Stop RAG periodic save and force final save
        await rag_system.stop_periodic_save()
        await rag_system.force_save_index()

        # Save all active sessions before unload
        await self.chat_manager.save_all_sessions()

        # Flush pending database exports to prevent "Task was destroyed" warning
        try:
            from utils.database import db

            if db is not None:
                await db.flush_pending_exports()
        except Exception as e:
            logger.warning("Failed to flush pending exports: %s", e)

        logger.info("🧠 AI Cog unloaded - all sessions saved")

    async def _cleanup_pending_requests_loop(self) -> None:
        """Periodic cleanup of pending requests and caches to prevent memory leaks."""
        cleanup_counter = 0
        memory_cleanup_counter = 0
        while True:
            try:
                await asyncio.sleep(60)  # Every 60 seconds
                self.chat_manager.cleanup_pending_requests()

                # Run storage cache cleanup every 5 minutes (every 5 iterations)
                cleanup_counter += 1
                if cleanup_counter >= 5:
                    cleanup_counter = 0
                    removed = cleanup_storage_cache()
                    if removed > 0:
                        logger.debug("🧹 Storage cache cleanup: removed %d entries", removed, extra={"event": "cache_cleanup", "removed": removed})

                # Run memory system cleanup every 30 minutes (every 30 iterations)
                memory_cleanup_counter += 1
                if memory_cleanup_counter >= 30:
                    memory_cleanup_counter = 0
                    try:
                        # Cleanup state tracker (uses defaults from constants)
                        from .memory.state_tracker import state_tracker

                        state_removed = state_tracker.cleanup_old_states()
                        if state_removed > 0:
                            logger.debug(
                                "🧹 State tracker cleanup: removed %d channels", state_removed,
                                extra={"event": "state_cleanup", "removed": state_removed},
                            )

                        # Cleanup consolidator tracking data (uses defaults from constants)
                        from .memory.consolidator import memory_consolidator

                        consol_removed = memory_consolidator.cleanup_old_channels()
                        if consol_removed > 0:
                            logger.debug(
                                "🧹 Consolidator cleanup: removed %d channels", consol_removed
                            )

                        # Cleanup unused message queue locks to prevent memory growth
                        from .core.message_queue import message_queue

                        locks_removed = message_queue.cleanup_unused_locks()
                        if locks_removed > 0:
                            logger.debug(
                                "🧹 Message queue lock cleanup: removed %d locks", locks_removed
                            )
                    except Exception as e:
                        logger.debug("Memory cleanup error (non-critical): %s", e)

            except asyncio.CancelledError:
                logger.debug("🧹 Cleanup loop cancelled during shutdown")
                break
            except Exception:
                logger.exception("🧹 Cleanup loop error (non-critical)")

    @commands.hybrid_command(name="chat", aliases=["ask"])  # type: ignore[arg-type]
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def chat_command(self, ctx: Context, *, message: str | None = None) -> None:
        """Talk to AI."""
        # Restriction for Roleplay Server
        if ctx.guild and ctx.guild.id == GUILD_ID_RP:
            if ctx.channel.id == CHANNEL_ID_RP_COMMAND:
                output_channel = self._as_text_channel(self.bot.get_channel(CHANNEL_ID_RP_OUTPUT))
                chat_channel = self._as_chat_channel(ctx.channel)
                if chat_channel is None:
                    await ctx.send("❌ ช่องนี้ไม่รองรับ AI chat")
                    return
                if output_channel:
                    await self.chat_manager.process_chat(
                        chat_channel,
                        ctx.author,
                        message or "",
                        ctx.message.attachments,
                        output_channel=output_channel,
                    )
                else:
                    await ctx.send("❌ ไม่พบห้อง Output สำหรับ Roleplay")
                return
            elif ctx.channel.id == CHANNEL_ID_RP_OUTPUT:
                # Allow direct chat in Output Channel
                pass
            else:
                await ctx.send(
                    f"❌ กรุณาใช้คำสั่งในห้อง <#{CHANNEL_ID_RP_COMMAND}> หรือ <#{CHANNEL_ID_RP_OUTPUT}>"
                )
                return

        if not message:
            if ctx.message.reference and ctx.message.reference.message_id is not None:
                # Handle reply to a message as input
                try:
                    ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    message = ref_msg.content or ""
                except discord.NotFound:
                    await ctx.send("❌ ไม่พบข้อความที่ Reply")
                    return
                except discord.Forbidden:
                    await ctx.send("❌ ไม่มีสิทธิ์อ่านข้อความที่ Reply")
                    return
                except discord.HTTPException as e:
                    await ctx.send(f"❌ เกิดข้อผิดพลาดในการอ่านข้อความ: {e}")
                    return
            elif ctx.message.attachments:
                # Allow empty message with attachments (images)
                message = ""
            else:
                # Empty message without attachments - let AI continue conversation
                message = ""

        chat_channel = self._as_chat_channel(ctx.channel)
        if chat_channel is None:
            await ctx.send("❌ ช่องนี้ไม่รองรับ AI chat")
            return

        await self.chat_manager.process_chat(
            chat_channel,
            ctx.author,
            message,
            ctx.message.attachments,
            user_message_id=ctx.message.id,
        )

    @chat_command.error
    async def chat_command_error(self, ctx, error):
        """Handle cooldown errors for chat command."""
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ กรุณารอ {error.retry_after:.1f} วินาที ก่อนใช้คำสั่งอีกครั้ง")
        else:
            raise error

    @commands.hybrid_command(name="reset_ai", aliases=["rst", "resetai"])  # type: ignore[arg-type]
    @commands.is_owner()
    async def reset_ai(self, ctx):
        """Reset Chat History (Owner Only)."""
        # Remove from memory
        if ctx.channel.id in self.chat_manager.chats:
            del self.chat_manager.chats[ctx.channel.id]

        # Remove from disk
        await delete_history(ctx.channel.id)

        # Clear seen users for this channel too
        if ctx.channel.id in self.chat_manager.seen_users:
            self.chat_manager.seen_users[ctx.channel.id].clear()

        await ctx.send("🧹 ล้างความจำ AI ในห้องนี้เรียบร้อยแล้ว เริ่มต้นคุยใหม่ได้เลย!")

    @reset_ai.error
    async def reset_ai_error(self, ctx, error):
        """Handle permission errors for reset_ai command."""
        if isinstance(error, commands.NotOwner):
            await ctx.send("⛔ คำสั่งนี้สำหรับเจ้าของบอทเท่านั้น")
        else:
            raise error

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Clean up resources when a channel is deleted.

        This prevents memory leaks from orphaned webhook caches
        and cleans up any channel-specific data.
        """
        # Invalidate webhook cache for deleted channel
        invalidate_webhook_cache_on_channel_delete(channel.id)

        # Clean up chat manager data for this channel
        if channel.id in self.chat_manager.chats:
            del self.chat_manager.chats[channel.id]
        if channel.id in self.chat_manager.seen_users:
            del self.chat_manager.seen_users[channel.id]
        # Clean up all remaining per-channel state to prevent memory leaks
        self.chat_manager.last_accessed.pop(channel.id, None)
        self.chat_manager.processing_locks.pop(channel.id, None)
        self.chat_manager.streaming_enabled.pop(channel.id, None)
        self.chat_manager.current_typing_msg.pop(channel.id, None)
        self.chat_manager._message_queue.pending_messages.pop(channel.id, None)
        self.chat_manager._message_queue.cancel_flags.pop(channel.id, None)

    async def _resolve_prefix_tuple(self, message: discord.Message) -> tuple[str, ...]:
        """Resolve bot.command_prefix into a tuple of prefix strings.

        Handles callable, str, and list prefix types with fallback to '!'.
        """
        prefix = self.bot.command_prefix
        if callable(prefix):
            try:
                prefix_callable = cast(Any, prefix)
                result = prefix_callable(self.bot, message)
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, str):
                    return (result,)
                if isinstance(result, (list, tuple)):
                    return tuple(str(item) for item in result)
                return ("!",)
            except Exception:
                return ("!",)  # Fallback if callable fails
        elif isinstance(prefix, str):
            return (prefix,)
        else:
            return tuple(prefix) if prefix else ("!",)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle incoming messages for AI responses."""
        # 1. Handle Webhooks (Tupperbox only)
        if message.webhook_id:
            await self._handle_webhook_message(message)
            return

        # 2. Ignore own messages and bots
        if message.author == self.bot.user or message.author.bot:
            return

        # 3. Handle DMs (Owner only)
        if not message.guild:
            await self._handle_dm_message(message)
            return

        # 4. Handle Guild Messages (restrictions, mentions, replies)
        await self._handle_guild_message(message)

    async def _handle_webhook_message(self, message: discord.Message) -> None:
        """Handle webhook messages from proxy bots (Tupperbox, PluralKit)."""
        # Skip DMs (webhooks shouldn't come from DMs, but safety check)
        if not message.guild:
            return

        # Validate webhook identity - only allow known proxy bot IDs
        is_known_proxy = False
        webhook_id = message.webhook_id
        if webhook_id is None:
            return

        # Resolve the channel that owns the webhook. Threads do not own webhooks
        # themselves — they inherit from the parent TextChannel. So for a message
        # that arrived in a Thread (Tupperbox/PluralKit supports threads), fetch
        # webhooks from the parent channel instead of giving up.
        webhook_channel: discord.TextChannel | None = None
        if isinstance(message.channel, discord.TextChannel):
            webhook_channel = message.channel
        elif isinstance(message.channel, discord.Thread):
            parent = message.channel.parent
            if isinstance(parent, discord.TextChannel):
                webhook_channel = parent
        if webhook_channel is None:
            return

        # Check cache first to avoid rate-limited webhook API calls
        import time as _time
        cached = self._webhook_verify_cache.get(webhook_id)
        if cached and cached[1] > _time.time():
            is_known_proxy = cached[0]
        else:
            try:
                webhooks = await webhook_channel.webhooks()
                for wh in webhooks:
                    if wh.id == webhook_id:
                        if wh.user and wh.user.bot and wh.user.id in self._ALLOWED_WEBHOOK_BOT_IDS:
                            is_known_proxy = True
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass
            # Cache the result (with size limit)
            now = _time.time()
            if len(self._webhook_verify_cache) >= self._WEBHOOK_CACHE_MAX_SIZE:
                expired = [k for k, v in self._webhook_verify_cache.items() if v[1] <= now]
                for k in expired:
                    del self._webhook_verify_cache[k]
                if len(self._webhook_verify_cache) >= self._WEBHOOK_CACHE_MAX_SIZE:
                    self._webhook_verify_cache.clear()
            self._webhook_verify_cache[webhook_id] = (
                is_known_proxy,
                now + self._WEBHOOK_CACHE_TTL,
            )

        if not is_known_proxy:
            return

        # Restriction Logic
        allowed = False
        if (
            (
                message.guild.id == GUILD_ID_RESTRICTED
                and message.channel.id == CHANNEL_ID_ALLOWED
            )
            or message.guild.id == GUILD_ID_MAIN
            or (
                message.guild.id == GUILD_ID_RP
                and message.channel.id in (CHANNEL_ID_RP_COMMAND, CHANNEL_ID_RP_OUTPUT)
            )
        ):
            allowed = True

        if not allowed:
            return

        # Check prefix and command manually
        message_content = message.content or ""
        content = message_content.strip()
        if content and content.startswith("!"):
            parts = content[1:].split(" ", 1)
            cmd = parts[0].lower() if parts[0] else ""
            if not cmd or cmd not in ["chat", "ask", "gemini"]:
                return

            if not await check_rate_limit("gemini_api", message, send_message=False):
                return
            if not await check_rate_limit("gemini_global", message, send_message=False):
                return

            user_msg = parts[1] if len(parts) > 1 else ""

            output_channel = None
            if message.guild.id == GUILD_ID_RP:
                if message.channel.id == CHANNEL_ID_RP_COMMAND:
                    output_channel = self._as_text_channel(
                        self.bot.get_channel(CHANNEL_ID_RP_OUTPUT)
                    )

            chat_channel = self._as_chat_channel(message.channel)
            if chat_channel is None:
                return

            await self.chat_manager.process_chat(
                chat_channel,
                message.author,
                user_msg,
                message.attachments,
                output_channel=output_channel,
                user_message_id=message.id,
            )

    async def _handle_dm_message(self, message: discord.Message) -> None:
        """Handle DM messages (owner only)."""
        if message.author.id != self.OWNER_ID:
            return

        message_content = message.content or ""
        prefix_tuple = await self._resolve_prefix_tuple(message)
        if message_content.startswith(prefix_tuple):
            return

        # Check for voice channel commands
        action, channel_id = self.chat_manager.parse_voice_command(message_content)
        if action == "join" and channel_id:
            _success, response = await self.chat_manager.join_voice_channel(channel_id)
            await message.channel.send(response)
            return
        elif action == "join" and not channel_id:
            await message.channel.send(
                "❓ บอก Channel ID ด้วยนะ เช่น: `เข้าไปรอใน 1234567890123456789`"
            )
            return
        elif action == "leave":
            if self.bot.voice_clients:
                # Snapshot the list — disconnect mutates voice_clients.
                for vc in list(self.bot.voice_clients):
                    try:
                        await vc.disconnect(force=False)
                    except Exception as e:
                        logger.warning("Failed to disconnect voice client: %s", e)
                await message.channel.send("✅ ออกจากห้องเสียงทั้งหมดแล้ว")
            else:
                await message.channel.send("❌ ไม่ได้อยู่ในห้องเสียงใดๆ")
            return

        if not await check_rate_limit("gemini_api", message):
            return
        if not await check_rate_limit("gemini_global", message):
            return
        if not await check_rate_limit("ai_user", message):
            return
        if not await check_rate_limit("ai_guild", message):
            return

        # Generate trace ID for this request
        try:
            from utils.monitoring.tracing import new_trace_id
            trace_id = new_trace_id()
            logger.debug("trace_id=%s user=%s channel=%s", trace_id, message.author.id, message.channel.id)
        except ImportError:
            pass

        chat_channel = self._as_chat_channel(message.channel)
        if chat_channel is None:
            return

        await self.chat_manager.process_chat(
            chat_channel,
            message.author,
            message_content,
            message.attachments,
            user_message_id=message.id,
        )

    async def _handle_guild_message(self, message: discord.Message) -> None:
        """Handle guild messages with restriction checks, mention/reply detection."""
        # Restriction for Specific Guild (Command Only)
        if message.guild and message.guild.id == GUILD_ID_COMMAND_ONLY:
            return

        # Restriction for Roleplay Server
        if message.guild and message.guild.id == GUILD_ID_RP:
            if message.channel.id == CHANNEL_ID_RP_COMMAND:
                if not await check_rate_limit("gemini_api", message):
                    return
                if not await check_rate_limit("gemini_global", message):
                    return

                output_channel = self._as_text_channel(self.bot.get_channel(CHANNEL_ID_RP_OUTPUT))
                chat_channel = self._as_chat_channel(message.channel)
                if chat_channel is None:
                    return
                if output_channel:
                    message_content = message.content or ""
                    await self.chat_manager.process_chat(
                        chat_channel,
                        message.author,
                        message_content,
                        message.attachments,
                        output_channel=output_channel,
                        user_message_id=message.id,
                    )
                return
            elif message.channel.id == CHANNEL_ID_RP_OUTPUT:
                if not await check_rate_limit("gemini_api", message):
                    return
                if not await check_rate_limit("gemini_global", message):
                    return

                chat_channel = self._as_chat_channel(message.channel)
                if chat_channel is None:
                    return
                message_content = message.content or ""
                await self.chat_manager.process_chat(
                    chat_channel,
                    message.author,
                    message_content,
                    message.attachments,
                    generate_response=True,
                    user_message_id=message.id,
                )
                return
            else:
                return

        # Check if mentioned or in allowed channel
        is_mentioned = self.bot.user in message.mentions
        is_reply = False
        if message.reference and message.reference.message_id is not None:
            try:
                ref_msg = message.reference.resolved
                reply_channel = self._as_fetchable_channel(message.channel)
                if reply_channel is None:
                    ref_msg = None
                elif not isinstance(ref_msg, discord.Message):
                    ref_msg = await reply_channel.fetch_message(message.reference.message_id)
                if isinstance(ref_msg, discord.Message) and ref_msg.author == self.bot.user:
                    is_reply = True
            except (discord.NotFound, discord.HTTPException, TypeError):
                pass

        should_respond = is_mentioned or is_reply

        # Check if message is a command (even with mention before prefix)
        message_content = message.content or ""
        content_without_mention = re.sub(r"<@!?\d+>\s*", "", message_content).strip()
        prefix_tuple = await self._resolve_prefix_tuple(message)
        is_command = message_content.startswith(prefix_tuple) or (
            content_without_mention and content_without_mention.startswith(prefix_tuple)
        )

        if should_respond and not is_command:
            if not await check_rate_limit("gemini_api", message):
                return
            if not await check_rate_limit("gemini_global", message):
                return

            chat_channel = self._as_chat_channel(message.channel)
            if chat_channel is None:
                return
            message_content = message.content or ""
            await self.chat_manager.process_chat(
                chat_channel,
                message.author,
                message_content,
                message.attachments,
                user_message_id=message.id,
            )

    @commands.command(name="thinking", aliases=["think"])
    @commands.has_permissions(manage_guild=True)
    async def toggle_thinking_cmd(self, ctx, mode: str | None = None):
        """Toggle AI Thinking Mode (on/off). Requires Manage Server permission."""
        # Determine target channel (support RP redirection)
        target_channel_id = ctx.channel.id
        if ctx.guild and ctx.guild.id == GUILD_ID_RP:
            if ctx.channel.id == CHANNEL_ID_RP_COMMAND:
                target_channel_id = CHANNEL_ID_RP_OUTPUT

        # Get current session to check status
        chat_data = await self.chat_manager.get_chat_session(target_channel_id)

        if mode is None:
            # No argument: Toggle current state
            if chat_data:
                current_state = chat_data.get("thinking_enabled", True)
                enable_thinking = not current_state  # Toggle
            else:
                enable_thinking = True  # Default to enable if no session
        else:
            mode = mode.lower()
            if mode not in ["on", "off", "enable", "disable", "open", "close"]:
                await ctx.send("❌ กรุณาระบุสถานะ: `on`, `off` หรือใช้ `!thinking` เพื่อสลับ")
                return
            enable_thinking = mode in ["on", "enable", "open"]

        success = await self.chat_manager.toggle_thinking(target_channel_id, enable_thinking)

        if success:
            status_str = "เปิดใช้งาน (Enabled)" if enable_thinking else "ปิดใช้งาน (Disabled)"
            embed = discord.Embed(
                title="🧠 AI Thinking Mode Updated",
                description=f"ตั้งค่าโหมดการคิดวิเคราะห์เป็น: **{status_str}**",
                color=Colors.SUCCESS if enable_thinking else Colors.WARNING,
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ ไม่สามารถตั้งค่าได้ (Session not found)")

    @commands.command(name="streaming", aliases=["stream"])
    @commands.has_permissions(manage_guild=True)
    async def toggle_streaming_cmd(self, ctx, mode: str | None = None):
        """Toggle AI Streaming Mode (on/off). Requires Manage Server permission.

        When enabled, AI responses stream in real-time as they are generated.
        This provides a more responsive experience but disables thinking mode.
        """
        # Determine target channel
        target_channel_id = ctx.channel.id
        if ctx.guild and ctx.guild.id == GUILD_ID_RP:
            if ctx.channel.id == CHANNEL_ID_RP_COMMAND:
                target_channel_id = CHANNEL_ID_RP_OUTPUT

        current_state = self.chat_manager.is_streaming_enabled(target_channel_id)

        if mode is None:
            # Toggle
            enable_streaming = not current_state
        else:
            mode = mode.lower()
            if mode not in ["on", "off", "enable", "disable"]:
                await ctx.send("❌ กรุณาระบุ: `on`, `off` หรือใช้ `!streaming` เพื่อสลับ")
                return
            enable_streaming = mode in ["on", "enable"]

        self.chat_manager.toggle_streaming(target_channel_id, enable_streaming)

        status_str = "เปิดใช้งาน 🌊" if enable_streaming else "ปิดใช้งาน"
        embed = discord.Embed(
            title="🌊 AI Streaming Mode Updated",
            description=f"โหมด Streaming: **{status_str}**",
            color=Colors.SUCCESS if enable_streaming else Colors.WARNING,
        )
        if enable_streaming:
            embed.add_field(
                name="ℹ️ หมายเหตุ",  # noqa: RUF001 - ℹ is intentional info emoji
                value="Streaming จะปิด Thinking Mode อัตโนมัติ\nข้อความจะอัพเดตแบบ real-time",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="ratelimit", aliases=["rl"])  # type: ignore[arg-type]
    @commands.is_owner()
    async def ratelimit_stats_cmd(self, ctx: commands.Context) -> None:
        """Show rate limit statistics (Owner only)."""
        stats = rate_limiter.get_stats()

        if not stats:
            await ctx.send("📊 No rate limit data yet.")
            return

        embed = discord.Embed(title="📊 Rate Limit Statistics", color=Colors.INFO)

        for name, data in sorted(stats.items()):
            total = data["allowed"] + data["blocked"]
            if total > 0:
                block_rate = (data["blocked"] / total) * 100
                embed.add_field(
                    name=name,
                    value=f"✅ {data['allowed']} | ❌ {data['blocked']} ({block_rate:.1f}%)",
                    inline=True,
                )

        await ctx.send(embed=embed)

    @commands.command(name="link_memory", aliases=["lm", "linkmem"])
    async def link_memory_cmd(
        self, ctx: commands.Context, source_channel: str | None = None
    ) -> None:
        """Link/Copy AI memory from another channel to this channel (Owner only).

        Usage:
            !link_memory <channel_id>  - Copy memory from specified channel
            !link_memory list          - List all channels with memory
        """
        # Check if user is owner
        if ctx.author.id != self.OWNER_ID:
            await ctx.send("⛔ คำสั่งนี้ใช้ได้เฉพาะเจ้าของบอทเท่านั้น")
            return

        # List mode
        if source_channel and source_channel.lower() == "list":
            channel_ids = await get_all_channel_ids()
            if not channel_ids:
                await ctx.send("📭 ไม่พบประวัติแชทในระบบ")
                return

            embed = discord.Embed(title="📋 Channels with AI Memory", color=Colors.INFO)

            channel_list = []
            for cid in channel_ids:
                channel = self.bot.get_channel(cid)
                if channel:
                    channel_list.append(f"• <#{cid}> (`{cid}`)")
                else:
                    channel_list.append(f"• Unknown Channel (`{cid}`)")

            embed.description = "\n".join(channel_list) if channel_list else "No channels found"
            await ctx.send(embed=embed)
            return

        # Validate source channel
        if not source_channel:
            await ctx.send(
                "❌ กรุณาระบุ Channel ID ต้นทาง\n"
                "**Usage:**\n"
                "`!link_memory <channel_id>` - Copy memory from channel\n"
                "`!link_memory list` - List all channels with memory"
            )
            return

        # Parse channel ID
        try:
            # Support both raw ID and mention format
            source_id = int(source_channel.strip("<>#"))
        except ValueError:
            await ctx.send("❌ Channel ID ไม่ถูกต้อง กรุณาใส่ตัวเลข ID")
            return

        target_id = ctx.channel.id

        # Check if source and target are the same
        if source_id == target_id:
            await ctx.send("❌ ไม่สามารถ link memory จาก channel เดียวกันได้")
            return

        # Confirm action
        embed = discord.Embed(
            title="🔗 Link Memory Confirmation",
            description=(
                f"**จาก:** `{source_id}`\n"
                f"**ไป:** <#{target_id}>\n\n"
                "⚠️ การดำเนินการนี้จะคัดลอกประวัติแชททั้งหมด\n"
                "ตอบ `yes` เพื่อยืนยัน หรือ `no` เพื่อยกเลิก"
            ),
            color=Colors.WARNING,
        )
        await ctx.send(embed=embed)

        # Wait for confirmation
        def check(m):
            return (
                m.author.id == self.OWNER_ID
                and m.channel.id == ctx.channel.id
                and m.content.lower() in ["yes", "no", "y", "n"]
            )

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=30.0)
        except TimeoutError:
            await ctx.send("⏰ หมดเวลา - ยกเลิกการดำเนินการ")
            return

        if msg.content.lower() in ["no", "n"]:
            await ctx.send("❌ ยกเลิกการดำเนินการ")
            return

        # Execute copy
        status_msg = await ctx.send("⏳ กำลังคัดลอกความจำ...")

        try:
            copied = await copy_history(source_id, target_id)

            if copied > 0:
                # Reload the chat session to include new history
                if target_id in self.chat_manager.chats:
                    del self.chat_manager.chats[target_id]

                embed = discord.Embed(
                    title="✅ Link Memory Successful",
                    description=(
                        f"คัดลอก **{copied}** ข้อความสำเร็จ!\n\n"
                        f"**จาก:** `{source_id}`\n"
                        f"**ไป:** <#{target_id}>"
                    ),
                    color=Colors.SUCCESS,
                )
                await status_msg.edit(content=None, embed=embed)
            else:
                await status_msg.edit(content="❌ ไม่พบประวัติแชทใน channel ต้นทาง")

        except Exception:
            logger.exception("Failed to link memory")
            await status_msg.edit(content="❌ เกิดข้อผิดพลาดในการเชื่อมต่อ memory")

    @commands.command(name="resend", aliases=["rs", "resendmsg"])
    async def resend_last_message(self, ctx: commands.Context, local_id: int | None = None) -> None:
        """Resend the last AI message (or specified by local_id) from database.

        Useful when messages were truncated in Discord but saved correctly in database.

        Usage:
            !resend       - Resend last AI message
            !resend 189   - Resend message with local_id 189
        """
        # Check if user is owner
        if ctx.author.id != self.OWNER_ID:
            await ctx.send("⛔ คำสั่งนี้ใช้ได้เฉพาะเจ้าของบอทเท่านั้น")
            return

        # Determine target channel for RP redirection
        target_channel_id = ctx.channel.id
        if ctx.guild and ctx.guild.id == GUILD_ID_RP:
            if ctx.channel.id == CHANNEL_ID_RP_COMMAND:
                target_channel_id = CHANNEL_ID_RP_OUTPUT

        # Get chat session
        chat_data = await self.chat_manager.get_chat_session(target_channel_id)
        if not chat_data or not chat_data.get("history"):
            await ctx.send("❌ ไม่พบประวัติแชทในช่องนี้")
            return

        # Find the message to resend - query directly from database
        target_message = None
        if local_id:
            # Query by local_id from database
            target_message = await get_message_by_local_id(target_channel_id, local_id)
            if not target_message:
                await ctx.send(f"❌ ไม่พบข้อความ local_id={local_id}")
                return
        else:
            # Get last model message from database
            target_message = await get_last_model_message(target_channel_id)
            if not target_message:
                await ctx.send("❌ ไม่พบข้อความ AI ในประวัติ")
                return

        # Extract content
        parts = target_message.get("parts", [])
        content = ""
        for part in parts:
            if isinstance(part, str):
                content += part
            elif isinstance(part, dict) and "text" in part:
                content += part["text"]

        if not content.strip():
            await ctx.send("❌ ข้อความว่างเปล่า")
            return

        status_msg = await ctx.send("📤 กำลังส่งข้อความใหม่...")

        # Get the output channel
        output_channel = self.bot.get_channel(target_channel_id)
        if not output_channel:
            await status_msg.edit(content="❌ ไม่พบช่อง output")
            return

        try:
            # Split by {{Name}} pattern (same as logic.py)
            split_parts = self._RESEND_CHARACTER_PATTERN.split(content)
            max_len = self._DISCORD_MAX_MESSAGE_LEN

            async def _send_chunked(text: str) -> None:
                """Send text to output_channel, chunked to Discord's 2000-char cap."""
                for i in range(0, len(text), max_len):
                    await output_channel.send(text[i : i + max_len])  # type: ignore[union-attr]

            # If found {{...}} patterns
            if len(split_parts) > 1:
                # parts[0] is narrator/intro
                intro = split_parts[0].strip() if split_parts[0] else ""
                if intro:
                    await _send_chunked(intro)

                # Iterate: odd=names, even=messages
                for i in range(1, len(split_parts), 2):
                    char_name = split_parts[i].strip()
                    if not char_name:
                        continue
                    if i + 1 < len(split_parts):
                        char_msg = split_parts[i + 1].strip()
                        if char_msg:
                            # Webhook body also has a 2000-char limit per message.
                            for j in range(0, len(char_msg), max_len):
                                await send_as_webhook(
                                    self.bot, output_channel, char_name, char_msg[j : j + max_len]
                                )
                                await asyncio.sleep(0.5)
            # Normal message (no character tags)
            else:
                await _send_chunked(content)

            await status_msg.edit(content="✅ ส่งข้อความใหม่สำเร็จ!")

        except Exception:
            logger.exception("Failed to resend message")
            await status_msg.edit(content="❌ เกิดข้อผิดพลาดในการส่งข้อความใหม่")

    @commands.hybrid_command(name="move_memory", aliases=["mm", "movemem"])  # type: ignore[arg-type]
    async def move_memory_cmd(
        self, ctx: commands.Context, source_channel: str | None = None
    ) -> None:
        """Move AI memory from another channel to this channel (Owner only).

        WARNING: This will DELETE the source channel's memory after moving!

        Usage:
            !move_memory <channel_id>  - Move memory from specified channel
            !move_memory list          - List all channels with memory
        """
        # Check if user is owner
        if ctx.author.id != self.OWNER_ID:
            await ctx.send("⛔ คำสั่งนี้ใช้ได้เฉพาะเจ้าของบอทเท่านั้น")
            return

        # List mode
        if source_channel and source_channel.lower() == "list":
            channel_ids = await get_all_channel_ids()
            if not channel_ids:
                await ctx.send("📭 ไม่พบประวัติแชทในระบบ")
                return

            embed = discord.Embed(title="📋 Channels with AI Memory", color=Colors.INFO)

            channel_list = []
            for cid in channel_ids:
                channel = self.bot.get_channel(cid)
                if channel:
                    channel_list.append(f"• <#{cid}> (`{cid}`)")
                else:
                    channel_list.append(f"• Unknown Channel (`{cid}`)")

            embed.description = "\n".join(channel_list) if channel_list else "No channels found"
            await ctx.send(embed=embed)
            return

        # Validate source channel
        if not source_channel:
            await ctx.send(
                "❌ กรุณาระบุ Channel ID ต้นทาง\n"
                "**Usage:**\n"
                "`!move_memory <channel_id>` - Move memory from channel (deletes source)\n"
                "`!move_memory list` - List all channels with memory"
            )
            return

        # Parse channel ID
        try:
            # Support both raw ID and mention format
            source_id = int(source_channel.strip("<>#"))
        except ValueError:
            await ctx.send("❌ Channel ID ไม่ถูกต้อง กรุณาใส่ตัวเลข ID")
            return

        target_id = ctx.channel.id

        # Check if source and target are the same
        if source_id == target_id:
            await ctx.send("❌ ไม่สามารถ move memory จาก channel เดียวกันได้")
            return

        # Confirm action with stronger warning
        embed = discord.Embed(
            title="🚚 Move Memory Confirmation",
            description=(
                f"**จาก:** `{source_id}`\n"
                f"**ไป:** <#{target_id}>\n\n"
                "⚠️ **คำเตือน:** การดำเนินการนี้จะ:\n"
                "1. คัดลอกประวัติแชททั้งหมดไปยัง channel นี้\n"
                "2. **ลบประวัติแชทจาก channel ต้นทาง**\n\n"
                "🔴 ตอบ `yes` เพื่อยืนยัน หรือ `no` เพื่อยกเลิก"
            ),
            color=Colors.ERROR,
        )
        await ctx.send(embed=embed)

        # Wait for confirmation
        def check(m):
            return (
                m.author.id == self.OWNER_ID
                and m.channel.id == ctx.channel.id
                and m.content.lower() in ["yes", "no", "y", "n"]
            )

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=30.0)
        except TimeoutError:
            await ctx.send("⏰ หมดเวลา - ยกเลิกการดำเนินการ")
            return

        if msg.content.lower() in ["no", "n"]:
            await ctx.send("❌ ยกเลิกการดำเนินการ")
            return

        # Execute move
        status_msg = await ctx.send("⏳ กำลังย้ายความจำ...")

        try:
            moved = await move_history(source_id, target_id)

            if moved > 0:
                # Reload the chat session to include new history
                if target_id in self.chat_manager.chats:
                    del self.chat_manager.chats[target_id]

                # Clear source from memory too
                if source_id in self.chat_manager.chats:
                    del self.chat_manager.chats[source_id]

                embed = discord.Embed(
                    title="✅ Move Memory Successful",
                    description=(
                        f"ย้าย **{moved}** ข้อความสำเร็จ!\n\n"
                        f"**จาก:** `{source_id}` (ลบแล้ว)\n"
                        f"**ไป:** <#{target_id}>"
                    ),
                    color=Colors.SUCCESS,
                )
                await status_msg.edit(content=None, embed=embed)
            else:
                await status_msg.edit(content="❌ ไม่พบประวัติแชทใน channel ต้นทาง")

        except Exception:
            logger.exception("Failed to move memory")
            await status_msg.edit(content="❌ เกิดข้อผิดพลาดในการย้าย memory")

    # ==================== Advanced Admin Commands ====================

    @commands.command(name="reload_config")
    @commands.is_owner()
    async def reload_config_cmd(self, ctx):
        """
        Reload configuration without restarting the bot.

        Usage: !reload_config
        """
        try:
            from importlib import reload

            import config as config_module

            reload(config_module)

            # Update rate limiter settings if needed
            from utils.reliability.rate_limiter import rate_limiter

            rate_limiter.reload_limits()

            await ctx.send(
                "✅ Config reloaded successfully!\nNote: Some settings may require bot restart."
            )
            logger.info("🔄 Config reloaded by owner")
        except Exception:
            logger.exception("Failed to reload config")
            await ctx.send("❌ Failed to reload config — check logs for details")

    @commands.command(name="dashboard", aliases=["stats"])
    @commands.is_owner()
    async def dashboard_cmd(self, ctx):
        """
        Show comprehensive bot dashboard with stats.

        Displays:
        - Performance metrics
        - Cache statistics
        - Memory usage
        - Active sessions
        """
        embed = discord.Embed(
            title="📊 Bot Dashboard", color=discord.Color.blue(), timestamp=discord.utils.utcnow()
        )

        # 1. Session Stats
        active_sessions = len(self.chat_manager.chats)
        total_history = sum(len(c.get("history", [])) for c in self.chat_manager.chats.values())
        embed.add_field(
            name="🧠 AI Sessions",
            value=f"```\nActive: {active_sessions}\nMessages: {total_history:,}```",
            inline=True,
        )

        # 2. Cache Stats
        try:
            from cogs.ai_core.cache.ai_cache import ai_cache

            stats = ai_cache.get_stats()
            cache_info = (
                f"Entries: {stats.total_entries}\n"
                f"Hit Rate: {stats.hit_rate:.1%}\n"
                f"Memory: {stats.memory_estimate_kb:.0f}KB"
            )
        except ImportError:
            cache_info = "N/A"
        embed.add_field(name="💾 Cache", value=f"```\n{cache_info}```", inline=True)

        # 3. RAG Stats
        try:
            from cogs.ai_core.memory.rag import rag_system

            rag_stats = rag_system.get_stats()
            rag_info = (
                f"FAISS: {'✅' if rag_stats['faiss_available'] else '❌'}\n"
                f"Vectors: {rag_stats['index_size']}\n"
                f"Cached: {rag_stats['memories_cached']}"
            )
        except ImportError:
            rag_info = "N/A"
        embed.add_field(name="🧠 RAG Memory", value=f"```\n{rag_info}```", inline=True)

        # 4. Performance (if available)
        perf = self.chat_manager.get_performance_stats()
        if perf and any(p["count"] > 0 for p in perf.values()):
            perf_lines = []
            for key, data in perf.items():
                if data["count"] > 0:
                    perf_lines.append(f"{key}: {data['avg_ms']:.0f}ms")
            embed.add_field(
                name="⚡ Performance",
                value="```\n" + "\n".join(perf_lines[:4]) + "```",
                inline=True,
            )

        # 5. Rate Limiter Stats
        try:
            from utils.reliability.rate_limiter import rate_limiter

            rl_stats = rate_limiter.get_stats()
            rl_info = (
                f"Buckets: {rl_stats.get('active_buckets', 0)}\n"
                f"Blocked: {rl_stats.get('total_blocked', 0)}"
            )
            embed.add_field(name="🚦 Rate Limiter", value=f"```\n{rl_info}```", inline=True)
        except (ImportError, AttributeError):
            pass

        # 6. Circuit Breaker Status
        try:
            from utils.reliability.circuit_breaker import gemini_circuit

            cb_state = gemini_circuit.state.value
            cb_color = "🟢" if cb_state == "closed" else ("🟡" if cb_state == "half_open" else "🔴")
            embed.add_field(
                name="⚡ Circuit Breaker",
                value=f"```\n{cb_color} {cb_state.upper()}```",
                inline=True,
            )
        except ImportError:
            pass

        embed.set_footer(text=f"Channel: {ctx.channel.id}")
        await ctx.send(embed=embed)

    @commands.command(name="audit_export")
    @commands.is_owner()
    async def audit_export_cmd(self, ctx, days: int = 7):
        """
        Export audit logs to file.

        Usage: !audit_export [days]
        Example: !audit_export 30
        """
        try:
            import json
            from datetime import datetime

            from utils.database import db as shared_db

            if shared_db is None:
                await ctx.send("❌ Database not available")
                return

            logs = await shared_db.get_audit_logs(days=days)

            if not logs:
                await ctx.send(f"📭 No audit logs found in the last {days} days")
                return

            # Create JSON file
            filename = f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            temp_dir = Path("temp")
            await asyncio.to_thread(temp_dir.mkdir, parents=True, exist_ok=True)
            filepath = temp_dir / filename

            try:
                await asyncio.to_thread(
                    filepath.write_text,
                    json.dumps(logs, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )

                await ctx.send(
                    f"📤 Exported {len(logs)} audit entries from last {days} days",
                    file=discord.File(str(filepath), filename=filename),
                )
            finally:
                # Always cleanup temp file
                if filepath.exists():
                    filepath.unlink()

        except ImportError:
            await ctx.send("❌ Audit logging not available")
        except Exception:
            logger.exception("Failed to export audit logs")
            await ctx.send("❌ Failed to export audit logs")

    @commands.command(name="auto_summarize")
    @commands.is_owner()
    async def auto_summarize_cmd(self, ctx, max_tokens: int = 500000):
        """
        Force auto-summarization of current channel history.

        Usage: !auto_summarize [max_tokens]
        Default: 500000 tokens (500K)
        """
        channel_id = ctx.channel.id

        if channel_id not in self.chat_manager.chats:
            await ctx.send("❌ No active session in this channel")
            return

        chat_data = self.chat_manager.chats[channel_id]
        history = chat_data.get("history", [])

        if not history:
            await ctx.send("❌ No history to summarize")
            return

        # Get current token count
        try:
            from cogs.ai_core.memory.history_manager import history_manager

            current_tokens = history_manager.estimate_tokens(history)
        except ImportError:
            current_tokens = len(history) * 50  # Rough estimate

        status_msg = await ctx.send(
            f"📊 Current: {len(history):,} messages (~{current_tokens:,} tokens)\n"
            f"⏳ Summarizing to fit {max_tokens:,} tokens..."
        )

        try:
            from cogs.ai_core.memory.history_manager import history_manager

            # Use smart_trim_by_tokens
            trimmed = await history_manager.smart_trim_by_tokens(
                history, max_tokens=max_tokens, reserve_tokens=2000
            )

            # Update history
            chat_data["history"] = trimmed

            # Save to storage
            from cogs.ai_core.storage import save_history

            await save_history(self.bot, channel_id, chat_data)

            new_tokens = history_manager.estimate_tokens(trimmed)

            await status_msg.edit(
                content=(
                    f"✅ Summarization complete!\n"
                    f"📉 {len(history):,} → {len(trimmed):,} messages\n"
                    f"📉 ~{current_tokens:,} → ~{new_tokens:,} tokens"
                )
            )

        except Exception as e:
            logger.exception("Failed to auto-summarize")
            await status_msg.edit(content=f"❌ Failed: {e}")

    @commands.command(name="channel_ratelimit")
    @commands.is_owner()
    async def channel_ratelimit_cmd(self, ctx, limit: int | None = None):
        """
        View or set per-channel rate limit.

        Usage:
        - !channel_ratelimit - View current limit
        - !channel_ratelimit 10 - Set to 10 requests/minute
        """
        try:
            from utils.reliability.rate_limiter import rate_limiter

            channel_id = ctx.channel.id

            if limit is None:
                # View current
                current = rate_limiter.get_channel_limit(channel_id)
                await ctx.send(f"🚦 Channel rate limit: {current} requests/minute")
            else:
                # Set new limit
                await rate_limiter.set_channel_limit(channel_id, limit)
                await ctx.send(f"✅ Channel rate limit set to: {limit} requests/minute")

        except (ImportError, AttributeError):
            await ctx.send("❌ Rate limiter doesn't support per-channel limits yet")

    @commands.command(name="unrestricted", aliases=["unlim", "nolimit", "jailbreak"])
    @commands.is_owner()
    async def unrestricted_mode_cmd(self, ctx, mode: str | None = None):
        """
        Toggle UNRESTRICTED MODE for this channel (Owner only).

        When enabled:
        - All input guardrails are bypassed
        - All output guardrails are bypassed
        - AI receives special "no limits" system prompt injection
        - Content filters are disabled

        Usage:
        - !unrestricted        - Toggle mode
        - !unrestricted on     - Enable unrestricted mode
        - !unrestricted off    - Disable unrestricted mode
        - !unrestricted status - Show current status for all channels
        """
        if not GUARDRAILS_AVAILABLE:
            await ctx.send("❌ Guardrails module not available")
            return

        channel_id = ctx.channel.id

        # Status mode - show all unrestricted channels
        if mode and mode.lower() == "status":
            if not unrestricted_channels:
                await ctx.send(
                    "📊 **Unrestricted Mode Status**\n\n❌ No channels are in unrestricted mode."
                )
                return

            channel_list = []
            for cid in unrestricted_channels:
                channel = self.bot.get_channel(cid)
                if channel:
                    channel_list.append(f"• <#{cid}> (`{cid}`)")
                else:
                    channel_list.append(f"• Unknown Channel (`{cid}`)")

            embed = discord.Embed(
                title="🔓 Unrestricted Mode Status",
                description="\n".join(channel_list),
                color=Colors.WARNING,
            )
            embed.add_field(
                name="⚠️ Warning",
                value="These channels have ALL content restrictions DISABLED.",
                inline=False,
            )
            await ctx.send(embed=embed)
            return

        # Determine target state
        current_state = is_unrestricted(channel_id)

        if mode is None:
            # Toggle
            enable = not current_state
        else:
            mode = mode.lower()
            if mode not in ["on", "off", "enable", "disable", "yes", "no"]:
                await ctx.send(
                    "❌ กรุณาระบุ: `on`, `off`, `status` หรือใช้ `!unrestricted` เพื่อสลับ\n\n"
                    "**Usage:**\n"
                    "`!unrestricted` - Toggle\n"
                    "`!unrestricted on` - Enable\n"
                    "`!unrestricted off` - Disable\n"
                    "`!unrestricted status` - Show all unrestricted channels"
                )
                return
            enable = mode in ["on", "enable", "yes"]

        # Set the mode
        set_unrestricted(channel_id, enable)

        if enable:
            embed = discord.Embed(
                title="🔓 UNRESTRICTED MODE ENABLED",
                description=(
                    f"**Channel:** <#{channel_id}>\n\n"
                    "⚠️ **WARNING: All safety restrictions are now DISABLED**\n\n"
                    "• Input guardrails: **BYPASSED**\n"
                    "• Output guardrails: **BYPASSED**\n"
                    "• Content filters: **DISABLED**\n"
                    "• Jailbreak detection: **DISABLED**\n\n"
                    "The AI will now respond without content limitations."
                ),
                color=Colors.ERROR,  # Red to indicate danger
            )
            embed.set_footer(text="Use !unrestricted off to re-enable safety features")
        else:
            embed = discord.Embed(
                title="🔒 Unrestricted Mode Disabled",
                description=(
                    f"**Channel:** <#{channel_id}>\n\n"
                    "✅ All safety features have been **RE-ENABLED**\n\n"
                    "• Input guardrails: **ACTIVE**\n"
                    "• Output guardrails: **ACTIVE**\n"
                    "• Content filters: **ENABLED**\n"
                    "• Jailbreak detection: **ENABLED**"
                ),
                color=Colors.SUCCESS,
            )

        await ctx.send(embed=embed)


async def setup(bot: Bot) -> None:
    """Setup function to add the AI cog and sub-cogs to the bot."""
    await bot.add_cog(AI(bot))

    # Load sub-cogs (debug & memory commands)
    from .commands.debug_commands import AIDebug
    from .commands.memory_commands import MemoryCommands

    await bot.add_cog(AIDebug(bot))
    await bot.add_cog(MemoryCommands(bot))
    logger.info("✅ Loaded AI sub-cogs: AIDebug, MemoryCommands")
