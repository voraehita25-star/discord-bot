"""
Session Mixin for ChatManager.
Handles session lifecycle, history management, and session configuration.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from .data import (
    FAUST_INSTRUCTION,
    GUILD_ID_RP,
    ROLEPLAY_ASSISTANT_INSTRUCTION,
    SERVER_LORE,
    UNRESTRICTED_MODE_INSTRUCTION,
)
from .storage import load_history, load_metadata, save_history

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from discord.ext.commands import Bot


class SessionMixin:
    """Mixin class providing session management functionality for ChatManager.

    This mixin requires the following attributes to be present on the class:
    - bot: Bot instance
    - client: Anthropic client
    - chats: dict[int, dict] - channel_id -> chat data
    - last_accessed: dict[int, float] - channel_id -> timestamp
    - seen_users: dict[int, set] - channel_id -> set of user keys
    - processing_locks: dict[int, asyncio.Lock]
    - pending_messages: dict[int, list]
    - cancel_flags: dict[int, bool]
    - streaming_enabled: dict[int, bool]
    - current_typing_msg: dict[int, Any] - channel_id -> typing message

    This mixin requires the following methods to be defined on the consuming class:
    - _enforce_channel_limit() -> None: Enforce max active channel limit
    """

    bot: Bot
    client: Any
    chats: dict[int, dict[str, Any]]
    last_accessed: dict[int, float]
    seen_users: dict[int, set[str]]
    processing_locks: dict[int, asyncio.Lock]
    pending_messages: dict[int, list]
    cancel_flags: dict[int, bool]
    streaming_enabled: dict[int, bool]
    current_typing_msg: dict[int, Any]

    def _enforce_channel_limit(self) -> int:
        """Enforce max active channel limit. Must be implemented by the consuming class."""
        raise NotImplementedError("Consuming class must implement _enforce_channel_limit")

    async def get_chat_session(
        self, channel_id: int, guild_id: int | None = None
    ) -> dict[str, Any] | None:
        """Get or create chat session data.

        Args:
            channel_id: Discord channel ID.
            guild_id: Optional guild ID for context.

        Returns:
            Chat session data dict or None if neither the SDK client nor
            the CLI subprocess backend is initialised.
        """
        # CLI mode has no SDK client (``self.client`` stays None) but the
        # CLI subprocess in ``discord_chat_claude_cli`` still answers, so
        # don't gate the session here on the SDK client. The original
        # check predates CLI mode and now produces a spurious
        # "Could not create chat session." error every Discord message
        # when CLAUDE_BACKEND=cli.
        if not self.client and not getattr(self, "cli_mode", False):
            return None

        if channel_id not in self.chats:
            # Select system instruction based on Guild.
            # DM mode previously used the brief FAUST_DM_INSTRUCTION
            # addendum (~600 chars) which dropped the full persona —
            # appearance, Gesellschaft, third-person speech, roleplay
            # format. Per user direction DM now uses the same full
            # FAUST_INSTRUCTION as guild channels so the AI's identity
            # is consistent across contexts. ``FAUST_DM_INSTRUCTION`` is
            # retained as an exported constant for backward compat with
            # downstream code/tests but no longer drives DM behaviour.
            system_instruction = FAUST_INSTRUCTION  # Default to Faust (also DM)

            if guild_id == GUILD_ID_RP:  # Roleplay Server
                system_instruction = ROLEPLAY_ASSISTANT_INSTRUCTION

            # Append server-specific lore if available
            if guild_id and guild_id in SERVER_LORE:
                lore = SERVER_LORE[guild_id]
                # Cap lore length to prevent exceeding API token limits
                MAX_LORE_LENGTH = 8000
                if len(lore) > MAX_LORE_LENGTH:
                    lore = lore[:MAX_LORE_LENGTH] + "\n[... lore truncated ...]"
                    logger.warning(
                        "Truncated server lore for guild %s (%d -> %d chars)",
                        guild_id,
                        len(SERVER_LORE[guild_id]),
                        MAX_LORE_LENGTH,
                    )
                system_instruction = system_instruction + "\n\n" + lore
                logger.info("Applied server lore for guild %s", guild_id)

            history = await load_history(self.bot, channel_id)

            # Load metadata (thinking_enabled, etc.) from file
            metadata = await load_metadata(self.bot, channel_id)

            self.chats[channel_id] = {
                "history": history,
                "system_instruction": system_instruction,
                "thinking_enabled": metadata.get("thinking_enabled", True),
                # Flag whether history came from DB so save_history can refuse
                # to dump the full in-memory history if a later DB read returns
                # empty (which would corrupt persisted history with duplicates).
                "_db_loaded": bool(history),
            }
        else:
            # Cached session exists - verify system_instruction is correct for guild
            cached_instruction = self.chats[channel_id].get("system_instruction", "")
            if guild_id == GUILD_ID_RP and ROLEPLAY_ASSISTANT_INSTRUCTION not in cached_instruction:
                logger.warning("⚠️ Correcting system_instruction for RP channel %s", channel_id)
                system_instruction = ROLEPLAY_ASSISTANT_INSTRUCTION
                # Mirror the cache-miss path's 8000-char cap so an
                # oversized lore entry can't bypass the API token limit
                # just because we hit the cache-correction branch.
                if guild_id in SERVER_LORE:
                    lore = SERVER_LORE[guild_id]
                    MAX_LORE_LENGTH = 8000
                    if len(lore) > MAX_LORE_LENGTH:
                        lore = lore[:MAX_LORE_LENGTH] + "\n[... lore truncated ...]"
                        logger.warning(
                            "Truncated server lore for guild %s on cache fixup (%d -> %d chars)",
                            guild_id,
                            len(SERVER_LORE[guild_id]),
                            MAX_LORE_LENGTH,
                        )
                    system_instruction = system_instruction + "\n\n" + lore
                self.chats[channel_id]["system_instruction"] = system_instruction

            # Force enable thinking mode for RP server
            if guild_id == GUILD_ID_RP and not self.chats[channel_id].get("thinking_enabled", True):
                logger.info("🧠 Force enabling thinking mode for RP channel %s", channel_id)
                self.chats[channel_id]["thinking_enabled"] = True

        # UNRESTRICTED MODE INJECTION — only for channels explicitly marked unrestricted
        # Also REMOVES the instruction when unrestricted mode is disabled.
        # We test for the actual injected text rather than a fixed marker so the
        # check works regardless of what UNRESTRICTED_MODE_INSTRUCTION's content
        # is (it's swapped between FAUST_SANDBOX and a fallback). A previous
        # version checked for a literal "[Private Creative Session]" substring
        # which never existed in the real instruction text — so the system
        # prompt grew unbounded on every get_chat_session call and the disable
        # path never ran.
        try:
            from .processing.guardrails import is_unrestricted

            # Re-read AFTER any RP-fix branch above so we don't clobber its update.
            current_instruction = self.chats[channel_id].get("system_instruction", "")
            already_injected = bool(
                UNRESTRICTED_MODE_INSTRUCTION
                and UNRESTRICTED_MODE_INSTRUCTION in current_instruction
            )
            if is_unrestricted(channel_id):
                if not already_injected and UNRESTRICTED_MODE_INSTRUCTION:
                    logger.info("🔓 Injecting UNRESTRICTED MODE for channel %s", channel_id)
                    self.chats[channel_id]["system_instruction"] = (
                        UNRESTRICTED_MODE_INSTRUCTION + current_instruction
                    )
            # Remove unrestricted instruction if it was previously injected
            elif already_injected:
                logger.info("🔒 Removing UNRESTRICTED MODE for channel %s", channel_id)
                self.chats[channel_id]["system_instruction"] = current_instruction.replace(
                    UNRESTRICTED_MODE_INSTRUCTION, ""
                )
        except ImportError:
            pass  # Guardrails not available, skip unrestricted injection

        # Update Last Accessed Time
        self.last_accessed[channel_id] = time.time()

        # Enforce channel limit to prevent unbounded memory growth
        self._enforce_channel_limit()

        return self.chats[channel_id]

    async def save_all_sessions(self) -> None:
        """Save all active sessions to persistent storage."""
        for channel_id in list(self.chats.keys()):
            # The session may be evicted by cleanup_inactive_sessions during an
            # await in a previous iteration — re-fetch and skip if it's gone so
            # a concurrent eviction can't KeyError out of the whole save loop.
            chat_data = self.chats.get(channel_id)
            if chat_data is None:
                continue
            await save_history(self.bot, channel_id, chat_data)
        logger.info("All AI sessions saved.")

    async def cleanup_inactive_sessions(self) -> None:
        """Background task to unload inactive chat sessions from RAM."""
        try:
            while not self.bot.is_closed():
                try:
                    current_time = time.time()
                    timeout = 3600  # 1 Hour Timeout

                    # Identify inactive channels (use list() snapshot to avoid RuntimeError)
                    inactive_channels = [
                        channel_id
                        for channel_id, last_time in list(self.last_accessed.items())
                        if current_time - last_time > timeout
                    ]

                    # Unload them
                    for channel_id in inactive_channels:
                        if channel_id in self.chats:
                            # Save before unloading (with timeout to prevent hanging)
                            save_succeeded = False
                            try:
                                save_succeeded = await asyncio.wait_for(
                                    save_history(self.bot, channel_id, self.chats[channel_id]),
                                    timeout=30,
                                )
                            except TimeoutError:
                                logger.warning(
                                    "Timeout saving session for channel %s during cleanup; "
                                    "keeping in memory to avoid data loss",
                                    channel_id,
                                )
                            except Exception:
                                logger.exception(
                                    "Save failed for channel %s during cleanup; "
                                    "keeping in memory to avoid data loss",
                                    channel_id,
                                )

                            # Only evict from memory if the save actually persisted.
                            # On timeout/error we leave the chat in self.chats so the
                            # next cleanup pass (or an explicit save) can retry without
                            # losing in-flight history.
                            if not save_succeeded:
                                continue

                            # Re-check after await: channel may have been re-accessed
                            if (
                                channel_id in self.last_accessed
                                and time.time() - self.last_accessed[channel_id] > timeout
                            ):
                                # Atomically remove all related state for this channel
                                self.chats.pop(channel_id, None)
                                self.last_accessed.pop(channel_id, None)
                                self.seen_users.pop(channel_id, None)
                                self.processing_locks.pop(channel_id, None)
                                self.pending_messages.pop(channel_id, None)
                                self.cancel_flags.pop(channel_id, None)
                                self.streaming_enabled.pop(channel_id, None)
                                self.current_typing_msg.pop(channel_id, None)
                            else:
                                # Channel was re-accessed during save, skip cleanup
                                continue

                            logger.info(
                                "Unloaded inactive AI session for channel %s from RAM.", channel_id
                            )

                except Exception:
                    logger.exception("Error in cleanup task")

                await asyncio.sleep(600)  # Check every 10 minutes
        except asyncio.CancelledError:
            logger.info("Session cleanup task cancelled")

    async def toggle_thinking(self, channel_id: int, enabled: bool) -> bool:
        """Toggle thinking mode for a specific channel session.

        Args:
            channel_id: Discord channel ID.
            enabled: Whether to enable thinking mode.

        Returns:
            True if toggled successfully, False otherwise.
        """
        chat_data = await self.get_chat_session(channel_id)
        if chat_data:
            chat_data["thinking_enabled"] = enabled
            # Re-save session to persist changes
            await save_history(self.bot, channel_id, chat_data)
            return True
        return False

    def toggle_streaming(self, channel_id: int, enabled: bool) -> bool:
        """Toggle streaming mode for a specific channel.

        When enabled, AI responses stream in real-time instead of waiting for completion.

        Args:
            channel_id: Discord channel ID.
            enabled: Whether to enable streaming.

        Returns:
            True if toggled successfully.
        """
        self.streaming_enabled[channel_id] = enabled
        logger.info(
            "🌊 Streaming %s for channel %s", "enabled" if enabled else "disabled", channel_id
        )
        return True

    def is_streaming_enabled(self, channel_id: int) -> bool:
        """Check if streaming is enabled for a channel.

        Args:
            channel_id: Discord channel ID.

        Returns:
            True if streaming is enabled for this channel.
        """
        return self.streaming_enabled.get(channel_id, False)
