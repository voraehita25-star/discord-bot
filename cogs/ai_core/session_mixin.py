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

from .data.constants import GUILD_ID_RP
from .data.faust_data import FAUST_DM_INSTRUCTION, FAUST_INSTRUCTION, UNRESTRICTED_MODE_INSTRUCTION
from .data.roleplay_data import ROLEPLAY_ASSISTANT_INSTRUCTION, SERVER_LORE
from .storage import load_history, load_metadata, save_history

if TYPE_CHECKING:
    from discord.ext.commands import Bot


class SessionMixin:
    """Mixin class providing session management functionality for ChatManager.

    This mixin requires the following attributes to be present on the class:
    - bot: Bot instance
    - client: Gemini client
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

    def _enforce_channel_limit(self) -> None:
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
            Chat session data dict or None if client not initialized.
        """
        if not self.client:
            return None

        if channel_id not in self.chats:
            # Select system instruction based on Guild
            system_instruction = FAUST_INSTRUCTION  # Default to Faust

            if guild_id is None:  # DM - Use casual Faust mode
                system_instruction = FAUST_DM_INSTRUCTION
            elif guild_id == GUILD_ID_RP:  # Roleplay Server
                system_instruction = ROLEPLAY_ASSISTANT_INSTRUCTION

            # Append server-specific lore if available
            if guild_id and guild_id in SERVER_LORE:
                system_instruction = system_instruction + "\n\n" + SERVER_LORE[guild_id]
                logging.info("Applied server lore for guild %s", guild_id)

            history = await load_history(self.bot, channel_id)

            # Load metadata (thinking_enabled, etc.) from file
            metadata = await load_metadata(self.bot, channel_id)

            self.chats[channel_id] = {
                "history": history,
                "system_instruction": system_instruction,
                "thinking_enabled": metadata.get("thinking_enabled", True),
            }
        else:
            # Cached session exists - verify system_instruction is correct for guild
            cached_instruction = self.chats[channel_id].get("system_instruction", "")
            if guild_id == GUILD_ID_RP and ROLEPLAY_ASSISTANT_INSTRUCTION not in cached_instruction:
                logging.warning("⚠️ Correcting system_instruction for RP channel %s", channel_id)
                system_instruction = ROLEPLAY_ASSISTANT_INSTRUCTION
                if guild_id in SERVER_LORE:
                    system_instruction = system_instruction + "\n\n" + SERVER_LORE[guild_id]
                self.chats[channel_id]["system_instruction"] = system_instruction

            # Force enable thinking mode for RP server
            if guild_id == GUILD_ID_RP and not self.chats[channel_id].get("thinking_enabled", True):
                logging.info("🧠 Force enabling thinking mode for RP channel %s", channel_id)
                self.chats[channel_id]["thinking_enabled"] = True

        # UNRESTRICTED MODE INJECTION — only for channels explicitly marked unrestricted
        # Also REMOVES the instruction when unrestricted mode is disabled
        try:
            from .processing.guardrails import is_unrestricted
            current_instruction = self.chats[channel_id].get("system_instruction", "")
            if is_unrestricted(channel_id):
                if "[CREATIVE WRITING MODE - PRIVATE SESSION]" not in current_instruction:
                    logging.info("🔓 Injecting UNRESTRICTED MODE for channel %s", channel_id)
                    self.chats[channel_id]["system_instruction"] = (
                        UNRESTRICTED_MODE_INSTRUCTION + current_instruction
                    )
            # Remove unrestricted instruction if it was previously injected
            elif "[CREATIVE WRITING MODE - PRIVATE SESSION]" in current_instruction:
                logging.info("🔒 Removing UNRESTRICTED MODE for channel %s", channel_id)
                self.chats[channel_id]["system_instruction"] = (
                    current_instruction.replace(UNRESTRICTED_MODE_INSTRUCTION, "")
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
            await save_history(self.bot, channel_id, self.chats[channel_id])
        logging.info("All AI sessions saved.")

    async def cleanup_inactive_sessions(self) -> None:
        """Background task to unload inactive chat sessions from RAM."""
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
                        # Save before unloading
                        await save_history(self.bot, channel_id, self.chats[channel_id])
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

                        logging.info(
                            "Unloaded inactive AI session for channel %s from RAM.", channel_id
                        )

            except Exception as e:
                logging.error("Error in cleanup task: %s", e)

            await asyncio.sleep(600)  # Check every 10 minutes

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
        logging.info(
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
