"""
Response Sender Module
Handles sending AI responses including webhooks, chunking, and character tags.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Import constants
try:
    from ..data.constants import (
        MAX_DISCORD_LENGTH,
        WEBHOOK_SEND_TIMEOUT,
    )
except ImportError:
    MAX_DISCORD_LENGTH = 2000
    WEBHOOK_SEND_TIMEOUT = 10.0

# Precompiled regex patterns
CHARACTER_TAG_PATTERN = re.compile(r"^\[([^\]]+)\]:\s*")
URL_PATTERN = re.compile(r"https?://\S+")
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


@dataclass
class SendResult:
    """Result of sending a message."""

    success: bool
    message_id: int | None = None
    error: str | None = None
    sent_via: str = "direct"  # "direct", "webhook", "chunked"
    character_name: str | None = None
    chunk_count: int = 1


class ResponseSender:
    """Handles sending AI responses to Discord."""

    def __init__(
        self,
        webhook_cache: Any = None,
        avatar_manager: Any = None,
    ) -> None:
        """Initialize the response sender.

        Args:
            webhook_cache: Webhook cache for webhook sends
            avatar_manager: Avatar manager for character avatars
        """
        self.webhook_cache = webhook_cache
        self.avatar_manager = avatar_manager

    async def send_response(
        self,
        channel: Any,  # discord.TextChannel
        content: str,
        avatar_name: str | None = None,
        avatar_url: str | None = None,
        reference: Any = None,  # discord.Message
        use_webhook: bool = True,
        allowed_mentions: Any = None,
    ) -> SendResult:
        """Send a response to a Discord channel.

        Args:
            channel: Discord channel
            content: Message content
            avatar_name: Bot display name
            avatar_url: Bot avatar URL
            reference: Message to reply to
            use_webhook: Whether to use webhook for sending
            allowed_mentions: Allowed mentions

        Returns:
            SendResult with send status
        """
        if not content or not content.strip():
            return SendResult(success=False, error="Empty content")

        # Check for character tags in content
        char_name, content = self.extract_character_tag(content)
        if char_name:
            avatar_name = char_name

        # Split content if too long
        chunks = self.split_content(content)

        try:
            # Try webhook first if available and enabled
            if use_webhook and self.webhook_cache and await self._can_use_webhook(channel):
                return await self._send_via_webhook(
                    channel,
                    chunks,
                    avatar_name,
                    avatar_url,
                    reference,
                    allowed_mentions,
                )

            # Fall back to direct send
            return await self._send_direct(
                channel,
                chunks,
                reference,
                allowed_mentions,
            )

        except Exception as e:
            logging.error("Send response error: %s", e)
            return SendResult(success=False, error=str(e))

    def extract_character_tag(self, content: str) -> tuple[str | None, str]:
        """Extract character tag from content.

        Args:
            content: Message content

        Returns:
            Tuple of (character name or None, content without tag)
        """
        match = CHARACTER_TAG_PATTERN.match(content)
        if match:
            character_name = match.group(1)
            content = content[match.end():]
            return character_name, content
        return None, content

    def split_content(
        self, content: str, max_length: int = MAX_DISCORD_LENGTH
    ) -> list[str]:
        """Split content into chunks that fit Discord's limit.

        Args:
            content: Content to split
            max_length: Maximum length per chunk

        Returns:
            List of content chunks
        """
        if len(content) <= max_length:
            return [content]

        chunks = []
        remaining = content

        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break

            # Find a good split point
            split_at = self._find_split_point(remaining, max_length)
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()

        return chunks

    def _find_split_point(self, text: str, max_length: int) -> int:
        """Find a good point to split text.

        Args:
            text: Text to split
            max_length: Maximum length

        Returns:
            Index to split at
        """
        # Prefer splitting at paragraph breaks
        para_break = text.rfind("\n\n", 0, max_length)
        if para_break > max_length // 2:
            return para_break + 2

        # Then try sentence breaks
        for punct in [". ", "! ", "? ", "。", "！", "？"]:
            sentence_break = text.rfind(punct, 0, max_length)
            if sentence_break > max_length // 2:
                return sentence_break + len(punct)

        # Then try line breaks
        line_break = text.rfind("\n", 0, max_length)
        if line_break > max_length // 2:
            return line_break + 1

        # Then try word breaks
        word_break = text.rfind(" ", 0, max_length)
        if word_break > max_length // 2:
            return word_break + 1

        # Last resort: hard break
        return max_length

    async def _can_use_webhook(self, channel: Any) -> bool:
        """Check if webhook can be used for channel.

        Args:
            channel: Discord channel

        Returns:
            True if webhook can be used
        """
        if not self.webhook_cache:
            return False

        # Check channel permissions
        if hasattr(channel, "permissions_for"):
            guild = getattr(channel, "guild", None)
            if guild and hasattr(guild, "me"):
                perms = channel.permissions_for(guild.me)
                return getattr(perms, "manage_webhooks", False)

        return True

    async def _send_via_webhook(
        self,
        channel: Any,
        chunks: list[str],
        avatar_name: str | None,
        avatar_url: str | None,
        reference: Any,
        allowed_mentions: Any,
    ) -> SendResult:
        """Send message via webhook.

        Args:
            channel: Discord channel
            chunks: Content chunks
            avatar_name: Bot display name
            avatar_url: Bot avatar URL
            reference: Message to reply to
            allowed_mentions: Allowed mentions

        Returns:
            SendResult with send status
        """
        try:
            start_time = time.time()

            # Get webhook
            webhook = await self._get_webhook(channel)
            if not webhook:
                # Fall back to direct send
                return await self._send_direct(channel, chunks, reference, allowed_mentions)

            # Send chunks
            last_message_id = None
            for i, chunk in enumerate(chunks):
                try:
                    msg = await asyncio.wait_for(
                        webhook.send(
                            chunk,
                            username=avatar_name or "AI",
                            avatar_url=avatar_url,
                            wait=True,
                            allowed_mentions=allowed_mentions,
                        ),
                        timeout=WEBHOOK_SEND_TIMEOUT,
                    )
                    last_message_id = msg.id if msg else None
                except asyncio.TimeoutError:
                    logging.warning("Webhook send timeout for chunk %d", i + 1)
                    # Continue with direct send for remaining chunks
                    return await self._send_remaining_direct(
                        channel, chunks[i:], reference, allowed_mentions, i
                    )

            elapsed = time.time() - start_time
            logging.debug("Webhook send completed in %.2fs", elapsed)

            return SendResult(
                success=True,
                message_id=last_message_id,
                sent_via="webhook",
                character_name=avatar_name,
                chunk_count=len(chunks),
            )

        except Exception as e:
            logging.error("Webhook send error: %s", e)
            # Fall back to direct send
            return await self._send_direct(channel, chunks, reference, allowed_mentions)

    async def _get_webhook(self, channel: Any) -> Any:
        """Get or create webhook for channel.

        Args:
            channel: Discord channel

        Returns:
            Webhook or None
        """
        if not self.webhook_cache:
            return None

        try:
            if hasattr(self.webhook_cache, "get_webhook"):
                return await self.webhook_cache.get_webhook(channel)
            elif hasattr(self.webhook_cache, "get"):
                return await self.webhook_cache.get(channel.id)
            return None
        except Exception as e:
            logging.error("Get webhook error: %s", e)
            return None

    async def _send_direct(
        self,
        channel: Any,
        chunks: list[str],
        reference: Any,
        allowed_mentions: Any,
    ) -> SendResult:
        """Send message directly to channel.

        Args:
            channel: Discord channel
            chunks: Content chunks
            reference: Message to reply to
            allowed_mentions: Allowed mentions

        Returns:
            SendResult with send status
        """
        try:
            last_message_id = None
            for i, chunk in enumerate(chunks):
                # Only reply to first chunk
                ref = reference if i == 0 else None

                msg = await channel.send(
                    chunk,
                    reference=ref,
                    allowed_mentions=allowed_mentions,
                )
                last_message_id = msg.id

            return SendResult(
                success=True,
                message_id=last_message_id,
                sent_via="direct" if len(chunks) == 1 else "chunked",
                chunk_count=len(chunks),
            )

        except Exception as e:
            logging.error("Direct send error: %s", e)
            return SendResult(success=False, error=str(e))

    async def _send_remaining_direct(
        self,
        channel: Any,
        chunks: list[str],
        reference: Any,
        allowed_mentions: Any,
        start_index: int,
    ) -> SendResult:
        """Send remaining chunks directly after webhook failure.

        Args:
            channel: Discord channel
            chunks: Remaining content chunks
            reference: Message to reply to
            allowed_mentions: Allowed mentions
            start_index: Original chunk index

        Returns:
            SendResult with send status
        """
        result = await self._send_direct(channel, chunks, reference, allowed_mentions)
        result.sent_via = "chunked"
        result.chunk_count = start_index + result.chunk_count
        return result

    async def send_typing(self, channel: Any) -> None:
        """Send typing indicator to channel.

        Args:
            channel: Discord channel
        """
        try:
            if hasattr(channel, "typing"):
                async with channel.typing():
                    pass
            elif hasattr(channel, "trigger_typing"):
                await channel.trigger_typing()
        except Exception as e:
            logging.debug("Typing indicator error: %s", e)

    async def edit_message(
        self,
        message: Any,  # discord.Message
        content: str,
    ) -> bool:
        """Edit an existing message.

        Args:
            message: Message to edit
            content: New content

        Returns:
            True if edit was successful
        """
        try:
            # Truncate if too long
            if len(content) > MAX_DISCORD_LENGTH:
                content = content[: MAX_DISCORD_LENGTH - 3] + "..."

            await message.edit(content=content)
            return True
        except Exception as e:
            logging.error("Edit message error: %s", e)
            return False

    def sanitize_content(self, content: str) -> str:
        """Sanitize content for sending.

        Args:
            content: Content to sanitize

        Returns:
            Sanitized content
        """
        if not content:
            return ""

        # Remove null characters
        content = content.replace("\x00", "")

        # Strip excessive whitespace
        content = "\n".join(
            line.rstrip() for line in content.split("\n")
        )

        # Remove excessive newlines (more than 2 in a row)
        while "\n\n\n" in content:
            content = content.replace("\n\n\n", "\n\n")

        return content.strip()


# Module-level instance for easy access
response_sender = ResponseSender()
