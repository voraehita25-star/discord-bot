"""
Response Mixin for ChatManager.
Handles response processing, history retrieval, and voice status.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import TYPE_CHECKING

from ..character_tags import replace_character_names
from ..storage import get_all_channels_summary, get_channel_history_preview

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from discord.ext.commands import Bot

# Precompiled regex patterns — MUST mirror the canonical copies in
# cogs/ai_core/logic.py (the production path runs those; only unit tests run
# these). PATTERN_SPACED had drifted to r'^>\s+…' (a dead strict-subset of
# PATTERN_QUOTE, which runs first), so an indented blockquote like
# '  > "Hello"' was stripped in production but untouched here — tests were
# pinning divergent behavior.
PATTERN_QUOTE = re.compile(r'^>\s*(["\'])', re.MULTILINE)
PATTERN_SPACED = re.compile(r'^\s*>\s*(["\'])', re.MULTILINE)
PATTERN_CHANNEL_ID = re.compile(r"\b(\d{17,20})\b")

# Keywords for history requests
HISTORY_KEYWORDS = [
    "ประวัติ",
    "history",
    "ดู",
    "อ่าน",
    "ข้อความ",
    "แชท",
    "chat",
    "memory",
    "ความจำ",
    "channel",
    "ช่อง",
    "log",
    "ดึง",
    "โชว์",
    "show",
]

# Keywords for channel list requests
LIST_KEYWORDS = [
    "มีช่องไหน",
    "channel ไหน",
    "ช่องไหนบ้าง",
    "มี channel",
    "รายการ",
    "list",
    "ทั้งหมด",
    "all channel",
    "ดูรายการ",
    "มีประวัติ",
    "มี history",
    "ความจำมี",
    "memory มี",
    "ช่องที่มี",
    "channel ที่มี",
    "ดู channel",
    "โชว์ channel",
]


class ResponseMixin:
    """Mixin class providing response processing functionality for ChatManager.

    This mixin requires the following attributes to be present on the class:
    - bot: Bot instance
    """

    bot: Bot

    def _get_voice_status(self) -> str:
        """Get current voice connection status for all servers.

        Thin wrapper that delegates to the canonical implementation in
        ``cogs.ai_core.voice.get_voice_status``. Two near-identical
        implementations were drifting silently — keeping the logic in
        one place stops bug fixes from landing in only one of them.
        """
        # Local import to dodge a circular dependency at module load
        # (voice.py imports from this package's __init__).
        from ..voice import get_voice_status as _voice_status_impl

        return _voice_status_impl(self.bot)

    async def _get_chat_history_index(self) -> str:
        """Get index of all channels with chat history for DM context.

        Returns:
            Formatted string listing all channels with chat history.
        """
        try:
            summaries = await get_all_channels_summary()
            if not summaries:
                return "ไม่มีประวัติแชทในระบบ"

            lines = ["📚 รายการ Channel ที่มีประวัติแชท AI:"]
            for s in summaries:
                cid = s["channel_id"]
                count = s["message_count"]
                channel = self.bot.get_channel(cid)
                if channel:
                    guild_name = (
                        channel.guild.name if hasattr(channel, "guild") and channel.guild else "DM"
                    )
                    channel_name = channel.name if hasattr(channel, "name") else "Unknown"
                    lines.append(f"• {cid} ({guild_name}/#{channel_name}): {count} ข้อความ")
                else:
                    lines.append(f"• {cid}: {count} ข้อความ")

            lines.append("\n💡 พูดถึง channel ID เพื่อขอดูประวัติแชท เช่น 'ดูประวัติ 1234567890'")
            return "\n".join(lines)
        except (OSError, RuntimeError, sqlite3.Error):
            # ``sqlite3.Error`` covers ``aiosqlite.Error`` (subclass of
            # ``sqlite3.Error``, NOT ``RuntimeError`` — the earlier comment
            # claiming RuntimeError covered them was wrong).
            logger.exception("Failed to get chat history index")
            return "ไม่สามารถดึงข้อมูลประวัติแชทได้"
        except Exception:  # pragma: no cover — last-resort safety for DB driver errors
            logger.exception("Unexpected error in chat history index")
            return "ไม่สามารถดึงข้อมูลประวัติแชทได้"

    def _extract_channel_id_request(self, message: str) -> int | None:
        """Extract channel ID from message if user is requesting history.

        Args:
            message: User's message text.

        Returns:
            Channel ID if found, None otherwise.
        """
        message_lower = message.lower()
        has_keyword = any(kw in message_lower for kw in HISTORY_KEYWORDS)

        if not has_keyword:
            return None

        match = PATTERN_CHANNEL_ID.search(message)
        if match:
            return int(match.group(1))
        return None

    def _is_asking_about_channels(self, message: str) -> bool:
        """Check if user is asking about available channels/history list.

        Args:
            message: User's message text.

        Returns:
            True if user is asking about channel list.
        """
        message_lower = message.lower()
        return any(kw in message_lower for kw in LIST_KEYWORDS)

    async def _get_requested_history(self, channel_id: int, requester_id: int | None = None) -> str:
        """Get formatted history preview for requested channel (compact).

        Args:
            channel_id: Discord channel ID.
            requester_id: ID of the user requesting the history (for permission check).

        Returns:
            Formatted history preview string.
        """
        try:
            # Permission check: require requester_id
            if requester_id is None:
                return "❌ ไม่สามารถตรวจสอบสิทธิ์ได้ กรุณาระบุผู้ร้องขอ"

            # Permission check: verify requester has access to the target channel
            channel = self.bot.get_channel(channel_id)
            if channel:
                # DM channels have no guild — deny cross-user history access entirely.
                # Only the DM participant may view their own DM history, but that path
                # goes through a different handler; here we refuse.
                guild = getattr(channel, "guild", None)
                if guild is None:
                    return f"❌ ไม่สามารถดูประวัติแชทของ DM channel {channel_id} ผ่านทางนี้ได้"
                member = guild.get_member(requester_id)
                if member is not None:
                    perms = channel.permissions_for(member)  # type: ignore[union-attr]
                    if not perms.read_messages:
                        return f"❌ คุณไม่มีสิทธิ์เข้าถึง channel {channel_id}"
                else:
                    # User is not a member of the guild
                    return f"❌ คุณไม่มีสิทธิ์เข้าถึง channel {channel_id}"
            else:
                # Bot can't see the channel — deny access to prevent info leak
                return f"❌ ไม่พบ channel {channel_id} หรือคุณไม่มีสิทธิ์เข้าถึง"

            preview = await get_channel_history_preview(channel_id, limit=15)
            if not preview:
                return f"❌ ไม่พบประวัติแชทของ channel {channel_id}"

            # Reuse the already-validated `channel` from the permission check
            # above (guaranteed non-None there — the not-found case returned) —
            # no need to re-fetch via get_channel a second time.
            guild_name = channel.guild.name if hasattr(channel, "guild") and channel.guild else "DM"
            channel_name = channel.name if hasattr(channel, "name") else "Unknown"
            header = f"📜 {guild_name}/#{channel_name}"

            lines = [header, f"({len(preview)} ข้อความล่าสุด)", "---"]

            for item in preview:
                role = "U" if item["role"] == "user" else "AI"
                content = item["content"]
                lines.append(f"[{role}] {content}")

            return "\n".join(lines)
        except (OSError, RuntimeError, sqlite3.Error):
            logger.exception("Failed to get requested history")
            return "❌ เกิดข้อผิดพลาดในการดึงประวัติแชท"
        except Exception:  # pragma: no cover — last-resort safety for DB driver errors
            logger.exception("Unexpected error in requested history")
            return "❌ เกิดข้อผิดพลาดในการดึงประวัติแชท"

    def _process_response_text(
        self, response_text: str, guild_id: int | None, search_indicator: str
    ) -> str:
        """Process and clean up response text using precompiled patterns.

        Args:
            response_text: Raw response text from API.
            guild_id: Guild ID for character tag conversion.
            search_indicator: Search indicator prefix to add.

        Returns:
            Processed response text.
        """
        # NOTE: on the live path this method is SHADOWED by
        # ChatManager._process_response_text (cogs/ai_core/logic.py), which is the
        # canonical copy — production runs that one, only the unit tests run this.
        # Keep the two in sync: any behavior-affecting edit must also go to logic.py.

        # Post-processing: Fix > before dialogue
        response_text = PATTERN_QUOTE.sub(r"\1", response_text)
        response_text = PATTERN_SPACED.sub(r"\1", response_text)

        # Fix AI comments about character tags → actual tags, mirroring the
        # ChatManager copy (this step used to be missing here, so the mixin and
        # ChatManager diverged). Guarded with getattr so lightweight test hosts
        # that mix in ResponseMixin without this method still work.
        fixer = getattr(self, "_fix_ai_character_tag_comments", None)
        if callable(fixer):
            response_text = fixer(response_text)

        # Convert standalone character names to {{Name}} tags
        response_text = replace_character_names(response_text, guild_id)

        # Prepend search indicator
        if search_indicator:
            response_text = search_indicator + response_text

        return response_text
