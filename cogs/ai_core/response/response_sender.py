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
from typing import Any

import discord

# Import constants
try:
    from ..data.constants import (  # type: ignore[attr-defined]
        MAX_DISCORD_LENGTH,
        WEBHOOK_SEND_TIMEOUT,
    )
except ImportError:
    MAX_DISCORD_LENGTH = 2000
    WEBHOOK_SEND_TIMEOUT = 10.0


logger = logging.getLogger(__name__)

# Precompiled regex patterns
CHARACTER_TAG_PATTERN = re.compile(r"^\[([^\]]+)\]:\s*")
URL_PATTERN = re.compile(r"https?://\S+")
MENTION_PATTERN = re.compile(r"<@!?(\d+)>")
# Patterns for dangerous mentions that should be sanitized in webhook messages
DANGEROUS_MENTION_PATTERN = re.compile(r"@(everyone|here)", re.IGNORECASE)


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

        except (TimeoutError, discord.HTTPException, discord.Forbidden, discord.NotFound) as e:
            logger.exception("Send response error")
            return SendResult(success=False, error=str(e))

    def _sanitize_webhook_content(self, content: str) -> str:
        """Sanitize content for webhook sending.

        Webhooks bypass ``allowed_mentions`` for ``@everyone`` and
        ``@here``, so those must be escaped manually. We also escape
        user and role mentions so a chunk going via the webhook path
        can't accidentally ping every mentioned id when the caller
        forgot to set ``allowed_mentions``. Mirrors the full mention
        defense in ``tool_executor.send_as_webhook``.

        Args:
            content: Content to sanitize

        Returns:
            Sanitized content with all mention types neutralised
        """
        # Replace @everyone and @here with escaped versions
        # Use zero-width space to break the mention. Replacement strings must
        # NOT be raw \u2014 `r"\u200b"` is six literal chars, not the ZWS code point.
        sanitized = DANGEROUS_MENTION_PATTERN.sub("@\u200b\\1", content)
        # User mentions: <@123> / <@!123>
        sanitized = re.sub(r"<@!?(\d+)>", "<@\u200b\\1>", sanitized)
        # Role mentions: <@&456>
        sanitized = re.sub(r"<@&(\d+)>", "<@&\u200b\\1>", sanitized)
        return sanitized

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
            content = content[match.end() :]
            return character_name, content
        return None, content

    def split_content(self, content: str, max_length: int = MAX_DISCORD_LENGTH) -> list[str]:
        """Split content into chunks that fit Discord's limit.

        Args:
            content: Content to split
            max_length: Maximum length per chunk

        Returns:
            List of content chunks
        """
        if max_length <= 0:
            max_length = MAX_DISCORD_LENGTH

        if len(content) <= max_length:
            return [content]

        chunks: list[str] = []
        remaining = content
        max_chunks = 20  # Safety limit to prevent unbounded chunking
        # Track which fenced-code-block we're currently inside so the next chunk
        # can re-open it. Without this, splitting in the middle of a ```python
        # block leaves the first chunk with a stray opening fence (no close)
        # and the second chunk with a stray closing fence (no open) — both
        # render broken in Discord.
        open_fence_lang: str | None = None

        while remaining and len(chunks) < max_chunks:
            if len(remaining) <= max_length:
                chunk = remaining
                if open_fence_lang is not None:
                    chunk = f"```{open_fence_lang}\n" + chunk
                chunks.append(chunk)
                break

            # Find a good split point. Reserve enough headroom for the
            # potential reopen prefix (```lang\n) and close suffix (\n```).
            # Without this, a chunk that needs both wrappers can exceed
            # max_length by ~10-20 chars and Discord rejects with HTTP 400.
            wrap_overhead = 0
            if open_fence_lang is not None:
                wrap_overhead += len(open_fence_lang) + 4  # "```lang\n"
            wrap_overhead += 4  # "\n```" close on this chunk if still open
            effective_max = max(1, max_length - wrap_overhead)
            split_at = self._find_split_point(remaining, effective_max)
            if split_at <= 0:
                split_at = effective_max  # Ensure forward progress
            raw_piece = remaining[:split_at]
            # Detect on the RAW piece (no reopen prefix) so the prefix's own
            # ``` doesn't get re-interpreted as a closing fence — passing
            # prior_open already tells _detect_open_fence we entered inside
            # a fence. Calling it on the prefixed piece produced silent
            # misdetection: every iteration after the first cleared
            # open_fence_lang, breaking the truncation reopen path.
            new_open_fence = self._detect_open_fence(raw_piece, open_fence_lang)
            piece = raw_piece
            # Re-open carry from prior chunk
            if open_fence_lang is not None:
                piece = f"```{open_fence_lang}\n" + piece
            if new_open_fence is not None:
                # Close the fence at end of this chunk so Discord doesn't
                # render a half-formed code block.
                if not piece.endswith("\n"):
                    piece += "\n"
                piece += "```"
            open_fence_lang = new_open_fence
            chunks.append(piece)
            # Strip only leading newlines, not all whitespace — inside an open
            # code fence the next chunk's first line may be indented (Python
            # def/if blocks) and `.lstrip()` would corrupt the code.
            remaining = remaining[split_at:].lstrip("\n")

        if remaining and len(chunks) >= max_chunks:
            # Append truncation notice. If the previous chunk ended inside an
            # open fence, prepend the reopen so the truncated content doesn't
            # render as plain text outside any code block.
            reopen = f"```{open_fence_lang}\n" if open_fence_lang is not None else ""
            close = "\n```" if open_fence_lang is not None else ""
            budget = max_length - len(reopen) - len(close) - 3  # "..."
            budget = max(budget, 1)
            chunks.append(reopen + remaining[:budget] + "..." + close)

        return chunks

    @staticmethod
    def _detect_open_fence(piece: str, prior_open: str | None) -> str | None:
        """Return the language of the still-open code fence at end of `piece`,
        or None if no fence is open. Treats triple-backticks at line start as
        fence markers, ignoring inline `code`."""
        # Walk lines; track whether we're inside a fenced block. The language
        # tag on the most-recent opener is what the next chunk needs to reopen.
        in_fence = prior_open is not None
        current_lang: str | None = prior_open
        for line in piece.split("\n"):
            stripped = line.lstrip()
            if not stripped.startswith("```"):
                continue
            if in_fence:
                in_fence = False
                current_lang = None
            else:
                in_fence = True
                # Lang tag = chars after ``` until whitespace/EOL.
                tag = stripped[3:].split(maxsplit=1)
                current_lang = tag[0] if tag else ""
        return current_lang if in_fence else None

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

        return False

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
        # Track how many chunks succeeded for fallback in except block.
        # Must be declared before the try so the except handler can reference it
        # even if an exception is raised before the inner assignment runs.
        chunks_sent = 0

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
                    # Add small delay between chunks to prevent rate limiting
                    if i > 0:
                        await asyncio.sleep(0.3)

                    # Sanitize dangerous mentions in webhook messages
                    # (webhooks bypass allowed_mentions for @everyone/@here)
                    sanitized_chunk = self._sanitize_webhook_content(chunk)

                    msg = await asyncio.wait_for(
                        webhook.send(
                            sanitized_chunk,
                            username=avatar_name or "AI",
                            avatar_url=avatar_url,
                            wait=True,
                            allowed_mentions=allowed_mentions,
                        ),
                        timeout=WEBHOOK_SEND_TIMEOUT,
                    )
                    last_message_id = msg.id if msg else None
                    chunks_sent += 1
                except TimeoutError:
                    logger.warning(
                        "Webhook send timeout for chunk %d — assuming in-flight, "
                        "skipping it on direct retry to avoid duplicate delivery",
                        i + 1,
                    )
                    # The webhook send timed out but the message may already
                    # have been queued upstream by Discord. Re-sending the
                    # same chunk via the direct path was producing visible
                    # duplicates. Resume from the NEXT chunk; if the
                    # in-flight one was lost the user sees a small gap, a
                    # better outcome than two copies of the same content.
                    chunks_sent += 1  # count the in-flight chunk as best-effort sent
                    return await self._send_remaining_direct(
                        channel, chunks[i + 1 :], reference, allowed_mentions, i + 1
                    )

            elapsed = time.time() - start_time
            logger.debug("Webhook send completed in %.2fs", elapsed)

            return SendResult(
                success=True,
                message_id=last_message_id,
                sent_via="webhook",
                character_name=avatar_name,
                chunk_count=len(chunks),
            )

        except Exception as e:
            logger.exception("Webhook send error")
            # Only fall back for unsent chunks to avoid duplicate messages
            remaining = chunks[chunks_sent:] if chunks_sent < len(chunks) else []
            if remaining:
                return await self._send_direct(channel, remaining, reference, allowed_mentions)
            return SendResult(success=False, error=str(e))

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
        except Exception:
            logger.exception("Get webhook error")
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

                # Add delay between chunks to avoid Discord rate limits
                if i > 0:
                    await asyncio.sleep(0.3)

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
            logger.exception("Direct send error")
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
        # Total = number of chunks sent before this fallback (start_index)
        # plus the count we attempted via direct send (len(chunks)). The
        # previous form `start_index + result.chunk_count` undercounted on
        # partial failures because `_send_direct` only counts successful
        # sends in `chunk_count`.
        result.chunk_count = start_index + len(chunks)
        return result

    async def send_typing(self, channel: Any) -> None:
        """Send a one-shot typing indicator to the channel.

        Discord's typing indicator decays after ~10s if not refreshed; this
        method sends a single typing payload and returns. Callers that need
        the indicator to persist for the duration of an in-flight response
        should use ``async with channel.typing():`` directly around the
        long-running work instead of calling this method, which only fires
        the start-of-typing notification.
        """
        try:
            send_typing = getattr(channel, "_state", None)
            if send_typing is not None and hasattr(send_typing, "http"):
                # discord.py 2.x: send a single Typing payload via the HTTP
                # API. This avoids opening + immediately closing a
                # ``channel.typing()`` async context (which sends one packet
                # then cancels the indicator within milliseconds), and
                # avoids the dead ``trigger_typing`` branch that doesn't
                # exist on Messageable in discord.py 2.x.
                await send_typing.http.send_typing(channel.id)
            elif hasattr(channel, "typing"):
                # Last-resort: open the context manager. This sends the
                # typing payload via __aenter__ and __aexit__ doesn't
                # actively cancel it, so the 10s decay still applies.
                async with channel.typing():
                    pass
        except Exception as e:
            logger.debug("Typing indicator error: %s", e)

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
            # Truncate if too long. If the truncation would leave a code
            # fence half-open, close it so Discord doesn't render every
            # subsequent message as code.
            if len(content) > MAX_DISCORD_LENGTH:
                truncated = content[: MAX_DISCORD_LENGTH - 3] + "..."
                # Count fences in truncated text — odd count means we
                # opened more than we closed, so append a closing fence.
                fence_count = truncated.count("```")
                if fence_count % 2 == 1:
                    # Reserve room for the close fence inside the cap.
                    truncated = content[: MAX_DISCORD_LENGTH - 7] + "...\n```"
                content = truncated

            await message.edit(content=content)
            return True
        except Exception:
            logger.exception("Edit message error")
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
        content = "\n".join(line.rstrip() for line in content.split("\n"))

        # Remove excessive newlines (more than 2 in a row)
        content = re.sub(r"\n{3,}", "\n\n", content)

        return content.strip()


# Module-level instance for easy access
response_sender = ResponseSender()
