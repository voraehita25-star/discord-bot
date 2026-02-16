# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
"""
AI Logic Module
Handles the core chat logic, Gemini API integration, and context management.
Optimized with precompiled regex patterns and lazy image loading.

Note: Type checker warnings for optional imports and Discord.py types are suppressed
because the conditional imports with fallback stubs work correctly at runtime.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import logging
import re
import time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

# Pre-allocate timezone to avoid re-creating on every message
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

import aiohttp
from google import genai
from PIL import Image


class _NewMessageInterrupt(Exception):
    """Raised when a new message arrives to cancel current processing.

    This is a distinct exception from asyncio.CancelledError to avoid
    conflating application logic with real task cancellation.
    """

# Import API handler module (direct subfolder import)
from .api.api_handler import (
    build_api_config,
    call_gemini_api,
    call_gemini_api_streaming,
    detect_search_intent,
)

# Import extracted modules
from .data.constants import (
    CREATOR_ID,
    GAME_SEARCH_KEYWORDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GUILD_ID_RP,
    LOCK_TIMEOUT,
    MAX_HISTORY_ITEMS,
)
from .data.roleplay_data import SERVER_CHARACTER_NAMES
from .emoji import convert_discord_emojis, extract_discord_emojis, fetch_emoji_images

# Import media processing module
from .media_processor import (
    convert_gif_to_video,
    is_animated_gif,
    load_character_image,
    pil_to_inline_data,
    prepare_user_avatar,
    process_attachments,
)
from .memory.consolidator import memory_consolidator
from .memory.entity_memory import entity_memory
from .memory.rag import rag_system
from .memory.state_tracker import state_tracker
from .memory.summarizer import summarizer
from .core.message_queue import MessageQueue

# Import new modular components (v3.3.6 - direct subfolder imports)
from .core.performance import PerformanceTracker, RequestDeduplicator
from .response.response_mixin import ResponseMixin
from .response.response_sender import ResponseSender
from .session_mixin import SessionMixin
from .storage import (
    save_history,
    update_message_id,
)
from .tools import execute_tool_call, send_as_webhook
from .voice import (
    join_voice_channel as voice_join,
    leave_voice_channel as voice_leave,
    parse_voice_command as voice_parse_command,
)

# TTS module removed - not used

# Import URL fetcher for web content extraction
try:
    from utils.web.url_fetcher import (
        extract_urls,
        fetch_all_urls,
        format_url_content_for_context,
    )

    URL_FETCHER_AVAILABLE = True
except ImportError:
    URL_FETCHER_AVAILABLE = False

    # Fallback stubs for URL fetcher
    def extract_urls(text: str) -> list[str]:
        return []

    async def fetch_all_urls(
        urls: list[str], max_urls: int = 3
    ) -> list[tuple[str, str, str | None]]:
        return []

    def format_url_content_for_context(fetched_urls: list[tuple[str, str, str | None]]) -> str:
        return ""


# Import new AI enhancement modules
try:
    from .processing.guardrails import (
        detect_refusal,
        is_silent_block,
        is_unrestricted,
        validate_input_for_channel,
        validate_response,
        validate_response_for_channel,
    )

    GUARDRAILS_AVAILABLE = True
except ImportError:
    GUARDRAILS_AVAILABLE = False

    def validate_response(response: str) -> tuple[bool, str, list[str]]:
        return True, response, []

    def is_unrestricted(channel_id: int) -> bool:
        return False

    def validate_response_for_channel(
        response: str, channel_id: int
    ) -> tuple[bool, str, list[str]]:
        return True, response, []

    def validate_input_for_channel(
        user_input: str, channel_id: int
    ) -> tuple[bool, str, float, list[str]]:
        return True, user_input, 0.0, []

    def detect_refusal(response: str) -> tuple[bool, str | None]:
        return False, None

    def is_silent_block(response: str, expected_min_length: int = 50) -> bool:
        return False


try:
    from .processing.intent_detector import Intent, detect_intent

    INTENT_DETECTOR_AVAILABLE = True
except ImportError:
    INTENT_DETECTOR_AVAILABLE = False

try:
    from .cache.analytics import get_ai_stats, log_ai_interaction

    ANALYTICS_AVAILABLE = True
except ImportError:
    ANALYTICS_AVAILABLE = False

try:
    from .cache.ai_cache import ai_cache, context_hasher

    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

try:
    from .memory.history_manager import history_manager

    HISTORY_MANAGER_AVAILABLE = True
except ImportError:
    HISTORY_MANAGER_AVAILABLE = False

# Import circuit breaker for API protection
try:
    from utils.reliability.circuit_breaker import gemini_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    gemini_circuit = None  # Fallback stub

# Import token tracker for usage analytics
try:
    from utils.monitoring.token_tracker import record_token_usage, token_tracker

    TOKEN_TRACKER_AVAILABLE = True
except ImportError:
    TOKEN_TRACKER_AVAILABLE = False
    token_tracker = None

    def record_token_usage(*args, **kwargs):
        pass


# Import fallback responses for graceful degradation
try:
    from .fallback_responses import fallback_system

    FALLBACK_AVAILABLE = True
except ImportError:
    FALLBACK_AVAILABLE = False
    fallback_system = None

# Import structured logger for JSON logging
try:
    from utils.monitoring.structured_logger import get_logger, log_ai_request

    structured_logger = get_logger("ai_logic")
    STRUCTURED_LOGGER_AVAILABLE = True
except ImportError:
    STRUCTURED_LOGGER_AVAILABLE = False
    structured_logger = None

    def log_ai_request(*args, **kwargs):
        pass


# Import performance tracker for response time monitoring
try:
    from utils.monitoring.performance_tracker import perf_tracker

    PERF_TRACKER_AVAILABLE = True
except ImportError:
    PERF_TRACKER_AVAILABLE = False
    perf_tracker = None

# Import error recovery for graceful degradation
try:
    from utils.reliability.error_recovery import (
        GracefulDegradation as _GracefulDegradation,
        service_monitor,
    )

    GracefulDegradation = _GracefulDegradation
    ERROR_RECOVERY_AVAILABLE = True
except ImportError:
    ERROR_RECOVERY_AVAILABLE = False
    service_monitor = None

    class GracefulDegradation:  # type: ignore[no-redef]
        """Fallback stub for GracefulDegradation."""

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False


# Import localization for Thai/English messages
try:
    from utils.localization import msg, msg_en

    LOCALIZATION_AVAILABLE = True
except ImportError:
    LOCALIZATION_AVAILABLE = False

    def msg(key, **kwargs):
        return key

    def msg_en(key, **kwargs):
        return key


# NOTE: IMAGEIO_AVAILABLE is imported from .media_processor (line 61)
# No need to re-import imageio here

if TYPE_CHECKING:
    import discord
    from discord.ext.commands import Bot


# ==================== Precompiled Regex Patterns ====================
# Compile patterns once at module load for better performance

# Post-processing patterns
PATTERN_QUOTE = re.compile(r'^>\s*(["\'])', re.MULTILINE)
PATTERN_SPACED = re.compile(r'^\s*>\s*(["\'])', re.MULTILINE)
PATTERN_ID = re.compile(r"^\[ID:\s*\d+\]\s*")

# Server command pattern
PATTERN_SERVER_COMMAND = re.compile(
    r"\[\[(CREATE_TEXT|CREATE_VOICE|CREATE_CATEGORY|DELETE_CHANNEL|"
    r"CREATE_ROLE|DELETE_ROLE|ADD_ROLE|REMOVE_ROLE|SET_CHANNEL_PERM|"
    r"SET_ROLE_PERM|LIST_CHANNELS|LIST_ROLES|READ_CHANNEL|"
    r"LIST_MEMBERS|GET_USER_INFO|EDIT_MESSAGE)(?::\s*(.*?))?\]\]"
)

# Character tag pattern {{Name}}
PATTERN_CHARACTER_TAG = re.compile(r"\{\{(.+?)\}\}")

# Pattern to detect AI comments about character tags that should be actual tags
# Matches: (ตรงนี้ควรใช้เป็น {{Name}}...) or similar patterns
PATTERN_AI_TAG_COMMENT = re.compile(
    r"\(ตรงนี้ควร(?:ใช้|เป็น|เปลี่ยน).*?\{\{(.+?)\}\}.*?\)|"
    r"\((?:should use|switch to|this should be)\s*\{\{(.+?)\}\}.*?\)",
    re.IGNORECASE,
)

# Channel ID extraction pattern
PATTERN_CHANNEL_ID = re.compile(r"\b(\d{17,20})\b")

# Discord custom emoji pattern - <:name:id> or <a:name:id> (animated)
PATTERN_DISCORD_EMOJI = re.compile(r"<(a?):(\w+):(\d+)>")


# NOTE: convert_discord_emojis, extract_discord_emojis, fetch_emoji_images
# are imported from .emoji module (line 45) - DO NOT redefine here

# NOTE: _load_cached_image_bytes is imported from .media_processor (line 61)
# DO NOT redefine here - removed duplicate @lru_cache function


class ChatManager(SessionMixin, ResponseMixin):
    """
    Manages AI chat sessions, history, and interactions with the Gemini API.

    Inherits from:
    - SessionMixin: Session lifecycle, history, cleanup
    - ResponseMixin: Response processing, voice status, history retrieval
    """

    # Maximum number of channels to track to prevent unbounded memory growth
    MAX_CHANNELS = 5000

    def __init__(self, bot: Bot) -> None:
        self.bot: Bot = bot
        self.chats: dict[int, Any] = {}  # Channel ID -> Chat object
        self.last_accessed: dict[int, float] = {}  # Channel ID -> Timestamp
        self.seen_users: dict[int, set[str]] = {}  # Channel ID -> Set of user_keys
        self.client: genai.Client | None = None
        self.target_model: str | None = None
        self.processing_locks: dict[int, asyncio.Lock] = {}  # Channel ID -> Lock

        # Streaming mode settings
        self.streaming_enabled: dict[int, bool] = {}  # Channel ID -> Streaming enabled

        # Current typing message tracking
        self.current_typing_msg: dict[int, Any] = {}  # Channel ID -> Current "typing" message

        # Use new modular components (v3.3.6)
        self._message_queue = MessageQueue()
        self._performance = PerformanceTracker()
        self._deduplicator = RequestDeduplicator()
        self._response_sender = ResponseSender()

        # Legacy aliases for backward compatibility
        self.pending_messages = self._message_queue.pending_messages
        self.cancel_flags = self._message_queue.cancel_flags
        self._lock_times = self._message_queue._lock_times
        self._performance_metrics = self._performance._metrics

        self.setup_ai()

    def _enforce_channel_limit(self) -> int:
        """Enforce max channel limit by removing oldest accessed channels (LRU eviction).

        Returns:
            Number of channels evicted.
        """
        if len(self.chats) <= self.MAX_CHANNELS:
            return 0

        # Sort by last_accessed timestamp (oldest first)
        sorted_channels = sorted(self.last_accessed.items(), key=lambda x: x[1])

        # Calculate how many to evict (evict 10% to avoid frequent evictions)
        evict_count = max(1, len(self.chats) - self.MAX_CHANNELS + (self.MAX_CHANNELS // 10))
        evicted = 0

        # Collect channels to evict (saving history requires async, schedule it)
        channels_to_evict = []
        for channel_id, _ in sorted_channels[:evict_count]:
            # Skip channels that are currently being processed (have a locked lock)
            lock = self.processing_locks.get(channel_id)
            if lock is not None and lock.locked():
                continue
            channels_to_evict.append(channel_id)

        for channel_id in channels_to_evict:
            # Save history before evicting to prevent data loss
            if channel_id in self.chats:
                try:
                    loop = asyncio.get_running_loop()
                    # Schedule save as a fire-and-forget task with error callback
                    from .storage import save_history
                    task = loop.create_task(save_history(self.bot, channel_id, self.chats[channel_id]))

                    def _handle_lru_save_result(t: asyncio.Task) -> None:
                        if t.cancelled():
                            return
                        exc = t.exception()
                        if exc:
                            logging.error("LRU save failed: %s", exc)

                    task.add_done_callback(_handle_lru_save_result)
                except RuntimeError:
                    # No running event loop
                    logging.warning("No event loop for LRU eviction save of channel %s", channel_id)
                except Exception as e:
                    logging.warning("Failed to save history before LRU eviction for %s: %s", channel_id, e)

            # Clean up all data for this channel
            self.chats.pop(channel_id, None)
            self.last_accessed.pop(channel_id, None)
            self.seen_users.pop(channel_id, None)
            self.processing_locks.pop(channel_id, None)
            self.streaming_enabled.pop(channel_id, None)
            self.current_typing_msg.pop(channel_id, None)
            # Also clean up message queue data for this channel
            self._message_queue.pending_messages.pop(channel_id, None)
            self._message_queue.cancel_flags.pop(channel_id, None)
            evicted += 1

        if evicted > 0:
            logging.info("🧹 ChatManager LRU eviction: removed %d channels (history saved)", evicted)

        return evicted

    def setup_ai(self) -> None:
        """Initialize the Gemini AI client."""
        if not GEMINI_API_KEY:
            logging.error(
                "GEMINI_API_KEY not found in environment variables. AI features disabled."
            )
            return

        try:
            # Initialize new Google GenAI Client
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            # Use gemini-3-pro-preview for premium AI with thinking
            self.target_model = GEMINI_MODEL
            logging.info("Gemini AI Initialized (Model: %s)", self.target_model)
        except (ValueError, OSError) as e:
            logging.error("Gemini Init Failed: %s", e)
            self.client = None

    def get_performance_stats(self) -> dict[str, Any]:
        """Get performance statistics for AI processing steps.
        Delegates to PerformanceTracker module.
        """
        return self._performance.get_stats()

    def record_timing(self, step: str, duration: float) -> None:
        """Record timing for a processing step.
        Delegates to PerformanceTracker module.
        """
        self._performance.record_timing(step, duration)

    def cleanup_pending_requests(self, max_age: float = 60.0) -> int:
        """Clean up old pending requests to prevent memory leaks.
        Delegates to RequestDeduplicator module.

        Args:
            max_age: Maximum age in seconds before a request is considered stale

        Returns:
            Number of requests cleaned up
        """
        return self._deduplicator.cleanup(max_age)

    # ==================== Voice Channel Management ====================

    async def join_voice_channel(self, channel_id: int) -> tuple[bool, str]:
        """Join a voice channel by ID. Delegates to voice module."""
        return await voice_join(self.bot, channel_id)

    async def leave_voice_channel(self, guild_id: int) -> tuple[bool, str]:
        """Leave voice channel in a guild. Delegates to voice module."""
        return await voice_leave(self.bot, guild_id)

    def parse_voice_command(self, message: str) -> tuple[str | None, int | None]:
        """Parse voice channel commands from message. Delegates to voice module."""
        return voice_parse_command(message)

    # Session methods (get_chat_session, save_all_sessions, cleanup_inactive_sessions,
    # toggle_thinking, toggle_streaming, is_streaming_enabled) are inherited from SessionMixin

    @staticmethod
    def _pil_to_inline_data(img: Image.Image) -> dict[str, Any]:
        """Convert PIL Image to base64 inline_data dict. Delegates to media_processor."""
        return pil_to_inline_data(img)

    async def _prepare_user_avatar(
        self, user: discord.User, message: str, chat_data: dict[str, Any], context_channel_id: int
    ) -> Image.Image | None:
        """Prepare user avatar image if needed. Delegates to media_processor."""
        return await prepare_user_avatar(
            user, message, chat_data, context_channel_id, self.seen_users
        )

    async def _process_attachments(
        self, attachments: list[discord.Attachment] | None, user_name: str
    ) -> tuple[list[Image.Image], list[dict], list[str]]:
        """Process image and text attachments. Delegates to media_processor."""
        return await process_attachments(attachments, user_name)

    def _is_animated_gif(self, image_data: bytes) -> bool:
        """Check if GIF data contains animation. Delegates to media_processor."""
        return is_animated_gif(image_data)

    def _convert_gif_to_video(self, gif_data: bytes) -> bytes | None:
        """Convert animated GIF to MP4 video. Delegates to media_processor."""
        return convert_gif_to_video(gif_data)

    def _load_character_image(
        self, message: str, guild_id: int | None
    ) -> tuple[str, Image.Image] | None:
        """Load character reference image. Delegates to media_processor."""
        return load_character_image(message, guild_id)

    # Response methods (_get_voice_status, _get_chat_history_index, _extract_channel_id_request,
    # _is_asking_about_channels, _get_requested_history) are inherited from ResponseMixin

    async def _detect_search_intent(self, message: str) -> bool:
        """Detect if message requires web search. Delegates to api_handler."""
        if self.client is None or self.target_model is None:
            return False
        return await detect_search_intent(self.client, self.target_model, message)

    def _build_api_config(
        self,
        chat_data: dict[str, Any],
        guild_id: int | None = None,
        use_search: bool = False,
    ) -> dict[str, Any]:
        """Build API configuration. Delegates to api_handler."""
        return build_api_config(chat_data, guild_id, use_search)

    async def _call_gemini_api_streaming(
        self,
        contents: list[dict[str, Any]],
        config_params: dict[str, Any],
        send_channel: Any,
        channel_id: int | None = None,
    ) -> tuple[str, str, list[Any]]:
        """Call Gemini API with streaming. Delegates to api_handler."""
        if self.client is None or self.target_model is None:
            raise ValueError("Gemini client not initialized")
        return await call_gemini_api_streaming(
            client=self.client,
            target_model=self.target_model,
            contents=contents,
            config_params=config_params,
            send_channel=send_channel,
            channel_id=channel_id,
            cancel_flags=self.cancel_flags,
            fallback_func=self._call_gemini_api,
        )

    async def _call_gemini_api(
        self,
        contents: list[dict[str, Any]],
        config_params: dict[str, Any],
        channel_id: int | None = None,
    ) -> tuple[str, str, list[Any]]:
        """Call Gemini API with retry logic. Delegates to api_handler."""
        if self.client is None or self.target_model is None:
            raise ValueError("Gemini client not initialized")
        return await call_gemini_api(
            client=self.client,
            target_model=self.target_model,
            contents=contents,
            config_params=config_params,
            channel_id=channel_id,
            cancel_flags=self.cancel_flags,
        )

    def _process_response_text(
        self, response_text: str, guild_id: int | None, search_indicator: str
    ) -> str:
        """Process and clean up response text using precompiled patterns."""
        # Post-processing: Fix > before dialogue (using precompiled patterns)
        response_text = PATTERN_QUOTE.sub(r"\1", response_text)
        response_text = PATTERN_SPACED.sub(r"\1", response_text)

        # Fix AI comments about character tags - convert to actual tags
        response_text = self._fix_ai_character_tag_comments(response_text)

        # Convert standalone character names to {{Name}} tags
        if guild_id and guild_id in SERVER_CHARACTER_NAMES:
            char_names = list(SERVER_CHARACTER_NAMES[guild_id].keys())
            char_names.sort(key=len, reverse=True)
            for char_name in char_names:
                pattern = rf"^[ \t]*{re.escape(char_name)}[ \t]*$"
                replacement = f"{{{{{char_name}}}}}"
                response_text = re.sub(
                    pattern, replacement, response_text, flags=re.MULTILINE | re.IGNORECASE
                )

        # Prepend search indicator
        if search_indicator:
            response_text = search_indicator + response_text

        return response_text

    def _fix_ai_character_tag_comments(self, text: str) -> str:
        """Fix AI-generated comments about character tags by converting them to actual tags.

        Sometimes AI writes comments like "(ตรงนี้ควรใช้เป็น {{Han Seo-ah}}...)"
        instead of actually using the tag. This function detects these patterns
        and converts them into proper {{Name}} tags.

        Args:
            text: The response text to process

        Returns:
            Text with comment patterns converted to actual character tags
        """
        if not text:
            return text

        def replace_comment_with_tag(match: re.Match) -> str:
            """Replace the comment with an actual character tag."""
            # Try both capture groups (Thai and English patterns)
            char_name = match.group(1) or match.group(2)
            if char_name:
                logging.info("🔧 Converting AI comment to tag: %s", char_name)
                return f"\n\n{{{{{char_name}}}}}\n"
            return match.group(0)

        return PATTERN_AI_TAG_COMMENT.sub(replace_comment_with_tag, text)

    async def _process_pending_messages(self, channel_id: int) -> None:
        """Process any pending messages for a channel.
        Uses MessageQueue module for message merging.
        """
        if not self._message_queue.has_pending(channel_id):
            return

        # Merge pending messages using MessageQueue
        latest_msg, combined_message = self._message_queue.merge_pending_messages(channel_id)

        if latest_msg:
            # Process the combined message
            await self.process_chat(
                channel=latest_msg.channel,
                user=latest_msg.user,
                message=combined_message,
                attachments=latest_msg.attachments,
                output_channel=latest_msg.output_channel,
                generate_response=latest_msg.generate_response,
                user_message_id=latest_msg.user_message_id,
            )

    async def process_chat(
        self,
        channel: discord.TextChannel,
        user: discord.User,
        message: str,
        attachments: list[discord.Attachment] | None = None,
        output_channel: discord.TextChannel | None = None,
        generate_response: bool = True,
        user_message_id: int | None = None,
    ) -> None:
        """Process chat message and generate AI response."""
        if not self.client:
            return  # AI not initialized

        # Input length validation - prevent extremely large messages
        MAX_MESSAGE_LENGTH = 100_000  # 100KB max
        if message and len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH] + "\n[... ข้อความถูกตัดเนื่องจากยาวเกินไป ...]"
            logging.warning("Truncated oversized message from user %s (%d chars)", user.id, len(message))

        # Determine Context and Send channels
        context_channel = output_channel if output_channel else channel
        send_channel = output_channel if output_channel else channel
        channel_id = context_channel.id

        # Request deduplication - prevent double processing of same message
        request_key = self._deduplicator.generate_key(channel_id, user.id, message or "")
        if self._deduplicator.is_duplicate(request_key):
            logging.debug("🔄 Duplicate request blocked: %s", request_key[:30])
            return
        self._deduplicator.add_request(request_key)

        # Graceful degradation - check circuit breaker before processing
        if CIRCUIT_BREAKER_AVAILABLE and gemini_circuit and not gemini_circuit.can_execute():
            await send_channel.send(
                "⏳ ระบบ AI กำลังพักผ่อนสักครู่ กรุณาลองใหม่อีกครั้งในอีก 1 นาที", delete_after=30
            )
            self._deduplicator.remove_request(request_key)
            return

        # Create lock for this channel if not exists (atomic operation to prevent race condition)
        lock = self.processing_locks.setdefault(channel_id, asyncio.Lock())

        # If already processing, queue this message and signal cancellation
        if lock.locked():
            # Add to pending queue using MessageQueue
            self._message_queue.queue_message(
                channel_id=channel_id,
                channel=channel,
                user=user,
                message=message,
                attachments=attachments,
                output_channel=output_channel,
                generate_response=generate_response,
                user_message_id=user_message_id,
            )
            # Signal to cancel current processing
            self._message_queue.signal_cancel(channel_id)
            logging.info("📝 Queued new message, signaling cancel for channel %s", channel_id)
            self._deduplicator.remove_request(request_key)
            return

        # Acquire lock with timeout using a safe pattern that avoids the known
        # asyncio.wait_for(lock.acquire()) deadlock (CPython issue #42130).
        # We shield the acquire task so wait_for's cancellation doesn't corrupt
        # the lock state, then attach a done_callback to release the lock if
        # the shielded task completes after we've already timed out.
        lock_acquired = False
        _timed_out = False
        try:
            async def _acquire_lock():
                await lock.acquire()
                return True

            _acquire_task = asyncio.create_task(_acquire_lock())

            def _release_if_timed_out(task: asyncio.Task) -> None:
                """Release the lock if we already gave up waiting."""
                if _timed_out and not task.cancelled() and task.exception() is None:
                    try:
                        lock.release()
                    except RuntimeError:
                        pass

            _acquire_task.add_done_callback(_release_if_timed_out)

            lock_acquired = await asyncio.wait_for(
                asyncio.shield(_acquire_task), timeout=LOCK_TIMEOUT
            )
        except asyncio.TimeoutError:
            _timed_out = True
            logging.error(
                "⚠️ Lock acquisition timeout for channel %s (>%ss)", channel_id, LOCK_TIMEOUT
            )
            self._deduplicator.remove_request(request_key)
            await send_channel.send("⏳ ระบบกำลังประมวลผลอยู่ กรุณารอสักครู่แล้วลองใหม่", delete_after=15)
            return

        try:  # Manual lock management with timeout protection
            # Track lock acquisition time for timeout detection
            self._message_queue._lock_times[channel_id] = time.time()
            # Reset cancel flag
            self._message_queue.reset_cancel(channel_id)
            typing_context = (
                send_channel.typing() if generate_response else contextlib.nullcontext()
            )

            # Initialize variables BEFORE async with to prevent NameError in finally block
            content_parts: list[Any] = []
            image_parts: list[Image.Image] = []

            async with typing_context:
                try:
                    # Get guild_id if available
                    guild_id = None
                    if hasattr(context_channel, "guild") and context_channel.guild:
                        guild_id = context_channel.guild.id

                    chat_data = await self.get_chat_session(context_channel.id, guild_id)
                    if not chat_data:
                        logging.error("Could not create chat session.")
                        self._deduplicator.remove_request(request_key)
                        return

                    user_name = user.display_name
                    # Get real-time in Bangkok timezone (ICT)
                    now_bangkok = datetime.datetime.now(BANGKOK_TZ)
                    now = now_bangkok.strftime("%A, %d %B %Y %H:%M:%S (ICT)")

                    # 1. Prepare user avatar using helper method
                    avatar_image = await self._prepare_user_avatar(
                        user, message, chat_data, context_channel.id
                    )
                    if avatar_image:
                        content_parts.append(
                            f"[System Notice: The following image is {user_name}'s "
                            f"Discord profile picture. This was automatically fetched "
                            f"by the system for user identification purposes. "
                            f"The user did NOT send this image - do NOT comment on or "
                            f"ask about it unless they mention their appearance.]"
                        )
                        content_parts.append(avatar_image)

                    # 2. Add text prompt with context
                    is_creator = user.id == CREATOR_ID
                    creator_tag = " | Creator: Yes" if is_creator else ""

                    # Handle empty messages
                    has_attachments = attachments and len(attachments) > 0
                    if not message or not message.strip():
                        if has_attachments:
                            # User sent only image(s)
                            display_message = "[User sent image(s) without text]"
                        else:
                            # User sent empty message - wants AI to continue
                            display_message = "[User wants to continue the conversation]"
                    else:
                        display_message = message

                    # Extract and fetch Discord custom emoji images
                    emoji_list = extract_discord_emojis(message or "")
                    if emoji_list:
                        try:
                            emoji_images = await fetch_emoji_images(emoji_list)
                            for emoji_name, emoji_img in emoji_images:
                                content_parts.append(f"[Custom Emoji: {emoji_name}]")
                                content_parts.append(emoji_img)
                        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                            logging.debug("Failed to fetch emoji images: %s", e)

                    # Convert Discord custom emojis to readable format in text
                    # <:smile:123456789> -> [:smile:]
                    display_message = convert_discord_emojis(display_message)

                    # --- URL Content Fetching ---
                    url_context = ""
                    if URL_FETCHER_AVAILABLE:
                        try:
                            urls = extract_urls(message or "")
                            if urls:
                                logging.info(
                                    "🔗 Found %d URL(s) in message, fetching content...", len(urls)
                                )
                                fetched = await fetch_all_urls(urls, max_urls=2)
                                url_context = format_url_content_for_context(fetched)
                                if url_context:
                                    logging.info("🔗 Fetched content from %d URL(s)", len(fetched))
                        except (
                            aiohttp.ClientError,
                            asyncio.TimeoutError,
                            ValueError,
                            OSError,
                        ) as e:
                            logging.debug("URL fetching failed: %s", e)

                    # --- RAG: Retrieve Relevant Memories ---
                    rag_context = ""

                    try:
                        # Search global memories + channel specific
                        _rag_start = time.time()
                        memories = await rag_system.search_memory(display_message, limit=3)
                        self.record_timing("rag_search", time.time() - _rag_start)
                        if memories:
                            rag_context = "\n\n[Long-term Memory]\n" + "\n".join(
                                f"- {m}" for m in memories
                            )
                    except OSError as e:
                        logging.error("RAG search failed: %s", e)

                    # --- Entity Memory: Retrieve verified character/location facts ---
                    entity_context = ""
                    try:
                        # Extract entity names from message (look for {{Name}} patterns)
                        entity_names = re.findall(r"\{\{([^}]+)\}\}", display_message)
                        # Also search for known character names in the message
                        if not entity_names:
                            # Search entities mentioned in text
                            entities = await entity_memory.search_entities(
                                display_message[:100],
                                channel_id=channel_id,
                                guild_id=guild_id,
                                limit=3,
                            )
                            entity_names = [e.name for e in entities]

                        if entity_names:
                            entity_context = await entity_memory.get_entities_for_prompt(
                                entity_names, channel_id=channel_id, guild_id=guild_id
                            )
                    except (KeyError, ValueError, TypeError, AttributeError) as e:
                        logging.debug("Entity memory lookup failed: %s", e)

                    # --- State Tracker: Get current character states (RP only) ---
                    state_context = ""
                    if guild_id == GUILD_ID_RP:
                        try:
                            state_context = state_tracker.get_states_for_prompt(channel_id)
                        except (KeyError, ValueError, TypeError) as e:
                            logging.debug("State tracker failed: %s", e)

                    # Combine all memory contexts
                    memory_context = ""
                    if entity_context:
                        memory_context += f"\n{entity_context}"
                    if state_context:
                        memory_context += f"\n{state_context}"
                    if url_context:
                        memory_context += f"\n{url_context}"
                    if rag_context:
                        memory_context += rag_context

                    # Build prompt with context
                    # For DM (guild_id is None), add voice status and chat history access
                    if guild_id is None:
                        voice_status = self._get_voice_status()

                        # Check if user is requesting specific channel history
                        requested_channel = self._extract_channel_id_request(display_message)
                        if requested_channel:
                            history_data = await self._get_requested_history(requested_channel, requester_id=user.id)
                            prompt_with_context = (
                                f"[System Info] Current Time: {now} | "
                                f"User: {user_name}{creator_tag}\n"
                                f"[Voice Status] {voice_status}\n"
                                f"[Requested Chat History]\n{history_data}\n"
                                f"{memory_context}\n"
                                f"---END SYSTEM CONTEXT---\n"
                                f"User Message: {display_message}"
                            )
                        elif self._is_asking_about_channels(display_message):
                            # Only show channel list if user is asking about it
                            history_index = await self._get_chat_history_index()
                            prompt_with_context = (
                                f"[System Info] Current Time: {now} | "
                                f"User: {user_name}{creator_tag}\n"
                                f"[Voice Status] {voice_status}\n"
                                f"[Chat History Access]\n{history_index}\n"
                                f"{memory_context}\n"
                                f"---END SYSTEM CONTEXT---\n"
                                f"User Message: {display_message}"
                            )
                        else:
                            # Normal DM chat - just voice status
                            prompt_with_context = (
                                f"[System Info] Current Time: {now} | "
                                f"User: {user_name}{creator_tag}\n"
                                f"[Voice Status] {voice_status}\n"
                                f"{memory_context}\n"
                                f"---END SYSTEM CONTEXT---\n"
                                f"User Message: {display_message}"
                            )
                    else:
                        prompt_with_context = (
                            f"[System Info] Current Time: {now} | "
                            f"User: {user_name}{creator_tag}\n"
                            f"{memory_context}\n"
                            f"---END SYSTEM CONTEXT---\n"
                            f"User Message: {display_message}"
                        )
                    content_parts.append(prompt_with_context)

                    # 3. Load character reference image if mentioned
                    char_result = self._load_character_image(message, guild_id)
                    if char_result:
                        char_name, char_image = char_result
                        content_parts.append(f"[Character Reference Image: {char_name}]")
                        content_parts.append(char_image)

                    # 4. Process attachments using helper method (images, videos, text files)
                    image_parts, video_parts, text_parts = await self._process_attachments(
                        attachments, user_name
                    )

                    # 5. Build current user message parts
                    current_parts = []
                    for part in content_parts:
                        if isinstance(part, str):
                            current_parts.append({"text": part})
                        elif isinstance(part, Image.Image):
                            try:
                                current_parts.append(self._pil_to_inline_data(part))
                            finally:
                                part.close()

                    for img in image_parts:
                        try:
                            current_parts.append(self._pil_to_inline_data(img))
                        finally:
                            img.close()

                    # Add text file contents
                    for text_content in text_parts:
                        current_parts.append({"text": text_content})

                    # Add video parts from animated GIFs
                    for video in video_parts:
                        current_parts.append(
                            {
                                "inline_data": {
                                    "mime_type": video["mime_type"],
                                    "data": base64.b64encode(video["data"]).decode("utf-8"),
                                }
                            }
                        )

                    # 6. Build contents with history (limit to recent messages for better context)
                    history = chat_data.get("history", [])

                    # Limit history - Gemini 3.0 Pro has 2M token context
                    # Using maximum context for all contexts (RP, DM, normal servers)
                    # to preserve AI personality and conversation continuity
                    # Note: MAX_HISTORY_ITEMS constant defined in data/constants.py

                    # Auto-compress very long histories using summarizer
                    # COMPRESS_THRESHOLD should be slightly higher than MAX_HISTORY_ITEMS
                    compress_threshold = MAX_HISTORY_ITEMS + 500  # Compress when exceeded
                    if len(history) > compress_threshold:
                        try:
                            compressed = await summarizer.compress_history(
                                history,
                                keep_recent=50,  # Keep 50 most recent messages intact
                            )
                            if len(compressed) < len(history):
                                history = compressed
                                logging.info(
                                    "📦 Auto-compressed history: %d → %d messages",
                                    len(chat_data.get("history", [])),
                                    len(compressed),
                                )
                        except (ValueError, TypeError, KeyError, asyncio.TimeoutError) as e:
                            logging.warning("Auto-summarize failed: %s", e)

                    # Use only recent history if too long (constant in data/constants.py)
                    if len(history) > MAX_HISTORY_ITEMS:
                        history = history[-MAX_HISTORY_ITEMS:]
                        logging.info(
                            "📚 Trimmed history from %d to %d messages for API call",
                            len(chat_data.get("history", [])),
                            MAX_HISTORY_ITEMS,
                        )

                    contents = []

                    for item in history:
                        role = item.get("role", "user")
                        parts_data = item.get("parts", [])
                        converted_parts = []
                        for p in parts_data:
                            if isinstance(p, str):
                                # Use precompiled pattern
                                clean_text = PATTERN_ID.sub("", p)
                                converted_parts.append({"text": clean_text})
                            elif isinstance(p, dict) and "text" in p:
                                clean_text = PATTERN_ID.sub("", p["text"])
                                converted_parts.append({"text": clean_text})
                        if converted_parts:
                            contents.append({"role": role, "parts": converted_parts})

                    contents.append({"role": "user", "parts": current_parts})

                    # 7. Handle memory-only mode (no response generation)
                    if not generate_response:
                        user_msg_text = prompt_with_context
                        if image_parts:
                            user_msg_text += " [Image/Attachment]"
                        # Include text file contents in saved history
                        if text_parts:
                            user_msg_text += "\n\n" + "\n".join(text_parts)
                        current_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                        new_item = {
                            "role": "user",
                            "parts": [user_msg_text],
                            "timestamp": current_time,
                            "user_id": user.id,
                        }
                        chat_data["history"].append(new_item)
                        await save_history(
                            self.bot, context_channel.id, chat_data, new_entries=[new_item]
                        )
                        logging.info("Saved user message (No Response) for %s", context_channel.id)
                        return

                    # NOTE: Cancel check before API call was removed - it caused infinite loops
                    # when users sent rapid messages. Instead, pending messages are now
                    # processed AFTER this message completes (via finally block calling
                    # _process_pending_messages). The messages will be merged there.
                    # If cancel was requested, reset flag and continue with this message,
                    # then process pending messages after completion.
                    if self._message_queue.is_cancelled(channel_id):
                        logging.info(
                            "📝 Cancel requested for channel %s - pending after",
                            channel_id,
                        )
                        self._message_queue.reset_cancel(channel_id)

                    # 8. Build API config and call Gemini API
                    # Check for game-related keywords that should ALWAYS use search
                    # Keywords defined in data/constants.py for easy maintenance
                    msg_lower = display_message.lower()
                    force_search = any(kw in msg_lower for kw in GAME_SEARCH_KEYWORDS)

                    if force_search:
                        use_search = True
                        logging.info("🔎 Force SEARCH mode (game keyword detected)")
                    else:
                        # Use AI to detect if user needs web search
                        logging.info("🔎 Detecting search intent for: %s", display_message[:50])
                        use_search = await self._detect_search_intent(display_message)
                        logging.info(
                            "🔎 Search intent result: %s", "SEARCH" if use_search else "NO_SEARCH"
                        )

                    config_params = self._build_api_config(
                        chat_data, guild_id, use_search=use_search
                    )

                    # Check if streaming is enabled for this channel
                    use_streaming = self.is_streaming_enabled(channel_id)

                    if use_streaming:
                        # Use streaming API for real-time updates
                        (
                            model_text,
                            search_indicator,
                            function_calls,
                        ) = await self._call_gemini_api_streaming(
                            contents, config_params, send_channel, channel_id
                        )
                    else:
                        # Use normal API call
                        model_text, search_indicator, function_calls = await self._call_gemini_api(
                            contents, config_params, channel_id
                        )

                    # Check for cancellation after API call
                    was_cancelled = self._message_queue.is_cancelled(channel_id)
                    if was_cancelled:
                        logging.info("⏹️ Cancelled after API call for channel %s", channel_id)
                        # Save user message to history
                        user_msg_text = prompt_with_context
                        if image_parts:
                            user_msg_text += " [Image/Attachment]"
                        # Include text file contents in saved history
                        if text_parts:
                            user_msg_text += "\n\n" + "\n".join(text_parts)
                        current_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                        new_entries = []
                        user_item = {
                            "role": "user",
                            "parts": [user_msg_text],
                            "timestamp": current_time,
                            "user_id": user.id,
                        }
                        chat_data["history"].append(user_item)
                        new_entries.append(user_item)

                        # Also save the model response if we got one (avoid wasting API tokens)
                        if model_text and model_text.strip():
                            model_item = {
                                "role": "model",
                                "parts": [model_text],
                                "timestamp": current_time,
                            }
                            chat_data["history"].append(model_item)
                            new_entries.append(model_item)

                        await save_history(
                            self.bot, context_channel.id, chat_data, new_entries=new_entries
                        )
                        # Don't return - fall through to process pending messages
                        raise _NewMessageInterrupt("New message received")

                    # 9. Update history
                    user_msg_text = prompt_with_context
                    if image_parts:
                        user_msg_text += " [Image/Attachment]"
                    # Include text file contents in saved history
                    if text_parts:
                        user_msg_text += "\n\n" + "\n".join(text_parts)
                    current_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                    new_entries = []

                    user_item = {
                        "role": "user",
                        "parts": [user_msg_text],
                        "timestamp": current_time,
                        "message_id": user_message_id,
                        "user_id": user.id,
                    }
                    chat_data["history"].append(user_item)
                    new_entries.append(user_item)

                    if model_text and model_text.strip():
                        model_item = {
                            "role": "model",
                            "parts": [model_text],
                            "timestamp": current_time,
                        }
                        chat_data["history"].append(model_item)
                        new_entries.append(model_item)

                    # 9.5 Handle Function Calls
                    tool_outputs = []
                    if function_calls:
                        for tool_call in function_calls:
                            logging.info("🛠️ Executing Tool: %s", tool_call.name)
                            result = await execute_tool_call(
                                self.bot, send_channel, user, tool_call
                            )
                            tool_outputs.append(f"🔧 Tool '{tool_call.name}': {result}")

                            # Add tool usage to history (represented as system/model info)
                            tool_item = {
                                "role": "model",
                                "parts": [f"[Executed Tool: {tool_call.name}]\nResult: {result}"],
                                "timestamp": current_time,
                            }
                            chat_data["history"].append(tool_item)
                            new_entries.append(tool_item)

                    if not (model_text and model_text.strip()) and not function_calls:
                        logging.warning("⚠️ Skipped saving empty model response")

                    await save_history(
                        self.bot, context_channel.id, chat_data, new_entries=new_entries
                    )

                    # --- Memory Enhancement: Update state tracker and consolidator ---
                    if guild_id == GUILD_ID_RP and model_text:
                        try:
                            # Update character states from response
                            updated_chars = state_tracker.update_from_response(
                                str(model_text), context_channel.id
                            )
                            if updated_chars:
                                logging.debug("🎭 Updated states for: %s", ", ".join(updated_chars))
                        except (KeyError, ValueError, TypeError, re.error) as e:
                            logging.debug("State tracker update failed: %s", e)

                    # Record message for memory consolidation
                    memory_consolidator.record_message(context_channel.id)

                    # Check if consolidation should run (auto-extract facts every N messages)
                    if memory_consolidator.should_consolidate(context_channel.id):
                        try:
                            # Create task with proper error handling to avoid orphaned tasks
                            task = asyncio.create_task(
                                memory_consolidator.consolidate(
                                    context_channel.id, chat_data.get("history", []), guild_id
                                ),
                                name=f"consolidate_{context_channel.id}",
                            )

                            # Add callback to log any unhandled exceptions
                            def _handle_consolidation_error(t: asyncio.Task) -> None:
                                if t.cancelled():
                                    return
                                exc = t.exception()
                                if exc:
                                    logging.warning("Memory consolidation task failed: %s", exc)

                            task.add_done_callback(_handle_consolidation_error)
                        except (RuntimeError, asyncio.InvalidStateError) as e:
                            logging.debug("Memory consolidation trigger failed: %s", e)

                    # 10. Process response text
                    response_text = str(model_text).strip() if model_text else ""

                    # Append tool outputs to response text if any
                    if tool_outputs:
                        if response_text:
                            response_text += "\n\n"
                        response_text += "\n".join(tool_outputs)

                    response_text = self._process_response_text(
                        response_text, guild_id, search_indicator
                    )

                    # 10.5 Apply guardrails to sanitize response
                    if GUARDRAILS_AVAILABLE:
                        _is_valid, sanitized, warnings = validate_response_for_channel(response_text, channel_id)
                        if warnings:
                            logging.info("🛡️ Guardrails applied: %s", warnings)
                        response_text = sanitized

                    # Check for {{Name}} syntax (Multi-Character Support)
                    # Split by {{Name}} blocks using precompiled pattern
                    parts = PATTERN_CHARACTER_TAG.split(response_text)

                    # If parts has more than 1 element, it means we found {{...}}
                    if len(parts) > 1:
                        # parts[0] is the text before the first {{...}} (Narrator/Intro)
                        if parts[0] and parts[0].strip():
                            await send_channel.send(parts[0].strip())

                        # Iterate through the rest: odd indices are Names, even are Messages
                        last_msg_id = None
                        for i in range(1, len(parts), 2):
                            if i >= len(parts):
                                break
                            char_name = parts[i].strip() if parts[i] else ""
                            if not char_name:
                                continue
                            if i + 1 < len(parts):
                                char_msg = parts[i + 1].strip() if parts[i + 1] else ""
                                if char_msg:
                                    sent_msg = await send_as_webhook(
                                        self.bot, send_channel, char_name, char_msg
                                    )
                                    # Capture the last sent message ID
                                    if sent_msg:
                                        last_msg_id = sent_msg.id

                                    # Small delay to ensure order and prevent rate limits
                                    await asyncio.sleep(0.5)

                        # Update history with the last message ID if we sent anything
                        if last_msg_id and chat_data.get("history"):
                            history_list = chat_data["history"]
                            if history_list and len(history_list) > 0:
                                last_item = history_list[-1]
                                if isinstance(last_item, dict):
                                    last_item["message_id"] = last_msg_id
                                    await update_message_id(context_channel.id, last_msg_id)

                        return  # Skip normal sending

                    # Normal Sending (Discord has a 2000 char limit)
                    sent_message = None
                    if len(response_text) > 2000:
                        # Smart split at natural boundaries to avoid breaking
                        # multi-byte chars (Thai text) or markdown
                        remaining = response_text
                        while remaining:
                            if len(remaining) <= 2000:
                                sent_message = await send_channel.send(remaining)
                                break
                            # Find best split point near 2000 chars
                            split_at = remaining.rfind('\n', 0, 2000)
                            if split_at == -1 or split_at < 1000:
                                split_at = remaining.rfind(' ', 0, 2000)
                            if split_at == -1 or split_at < 1000:
                                split_at = 2000
                            sent_message = await send_channel.send(remaining[:split_at])
                            remaining = remaining[split_at:].lstrip('\n')
                    elif response_text:  # Only send if there is text left
                        sent_message = await send_channel.send(response_text)

                    # Update history with Message ID if available
                    if sent_message and chat_data.get("history"):
                        history_list = chat_data["history"]
                        if history_list and len(history_list) > 0:
                            last_item = history_list[-1]
                            if isinstance(last_item, dict) and last_item.get("role") == "model":
                                last_item["message_id"] = sent_message.id
                                # Save again to persist ID
                                await update_message_id(context_channel.id, sent_message.id)

                except (_NewMessageInterrupt, asyncio.CancelledError):
                    # _NewMessageInterrupt: expected when a new message arrives
                    # CancelledError: must re-raise to allow proper task cancellation
                    logging.info("🔄 Processing interrupted, will handle pending messages")
                    # Re-raise CancelledError to propagate cancellation properly
                    raise
                except (discord.HTTPException, ValueError, TypeError) as e:
                    error_msg = str(e)
                    # Truncate error message if too long
                    if len(error_msg) > 500:
                        error_msg = error_msg[:500] + "..."
                    logging.error("Gemini Error: %s", e)
                    # Send generic error to user (don't leak internal details)
                    await send_channel.send("❌ เกิดข้อผิดพลาดจาก AI กรุณาลองใหม่อีกครั้ง")
                finally:
                    # Cleanup: Close any remaining PIL images to prevent memory leaks
                    # Most images are closed during processing, this is a safety net
                    # Variables initialized before async with block, so no NameError
                    for part in content_parts:
                        if isinstance(part, Image.Image):
                            try:
                                part.close()
                            except OSError:
                                pass
                    for img in image_parts:
                        if isinstance(img, Image.Image):
                            try:
                                img.close()
                            except OSError:
                                pass

                    # Cleanup request deduplication key
                    self._deduplicator.remove_request(request_key)
        finally:
            # Always release the lock properly — only if we actually acquired it
            try:
                if lock_acquired and lock.locked():
                    lock.release()
            except RuntimeError:
                pass  # Lock was not acquired or already released
            # Clear lock time tracking
            self._message_queue._lock_times.pop(channel_id, None)

        # After processing, check for pending messages
        if self._message_queue.has_pending(channel_id):
            await self._process_pending_messages(channel_id)
