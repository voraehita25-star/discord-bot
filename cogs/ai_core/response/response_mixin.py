"""
Response Mixin for ChatManager.
Handles response processing, history retrieval, and voice status.
Extracted from logic.py for better modularity.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ..data import SERVER_CHARACTER_NAMES
from ..storage import get_all_channels_summary, get_channel_history_preview

if TYPE_CHECKING:
    from discord.ext.commands import Bot

# Precompiled regex patterns
PATTERN_QUOTE = re.compile(r'^>\s*(["\'])', re.MULTILINE)
PATTERN_SPACED = re.compile(r'^>\s+(["\'])', re.MULTILINE)
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

        Returns:
            Formatted string describing voice connection status.
        """
        if not self.bot.voice_clients:
            return "Faust ไม่ได้เชื่อมต่อกับห้องเสียงใดๆ"

        music_cog = self.bot.get_cog("Music")
        voice_info = []

        for vc in self.bot.voice_clients:
            if vc.is_connected() and vc.channel:
                guild_name = vc.guild.name if vc.guild else "Unknown Server"
                guild_id = vc.guild.id if vc.guild else None
                channel_name = vc.channel.name

                # Get members in voice channel (excluding bots)
                members = [m.display_name for m in vc.channel.members if not m.bot]
                member_count = len(members)

                # Check if playing music and get track info
                if vc.is_playing():
                    status = "กำลังเล่นเพลง"
                    if music_cog and guild_id:
                        track_info = music_cog.current_track.get(guild_id, {})
                        track_title = track_info.get("title", "Unknown")
                        status = f"กำลังเล่นเพลง: {track_title}"
                elif vc.is_paused():
                    status = "หยุดชั่วคราว"
                    if music_cog and guild_id:
                        track_info = music_cog.current_track.get(guild_id, {})
                        track_title = track_info.get("title", "Unknown")
                        status = f"หยุดชั่วคราว: {track_title}"
                else:
                    status = "ว่าง (ไม่ได้เล่นเพลง)"

                if members:
                    member_list = ", ".join(members[:5])
                    if member_count > 5:
                        member_list += f" และอีก {member_count - 5} คน"
                    voice_info.append(
                        f"• Server: {guild_name} | Channel: {channel_name}\n"
                        f"  Status: {status}\n"
                        f"  Members: {member_list}"
                    )
                else:
                    voice_info.append(
                        f"• Server: {guild_name} | Channel: {channel_name}\n"
                        f"  Status: {status}\n"
                        f"  Members: ไม่มีใครในห้อง"
                    )

        if voice_info:
            return "Faust กำลังเชื่อมต่อกับห้องเสียง:\n" + "\n".join(voice_info)
        return "Faust ไม่ได้เชื่อมต่อกับห้องเสียงใดๆ"

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
        except OSError as e:
            logging.error("Failed to get chat history index: %s", e)
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
            # Permission check: verify requester has access to the target channel
            channel = self.bot.get_channel(channel_id)
            if channel and requester_id:
                member = None
                if hasattr(channel, "guild") and channel.guild:
                    member = channel.guild.get_member(requester_id)
                if member is not None:
                    perms = channel.permissions_for(member)
                    if not perms.read_messages:
                        return f"❌ คุณไม่มีสิทธิ์เข้าถึง channel {channel_id}"
                elif hasattr(channel, "guild") and channel.guild:
                    # User is not a member of the guild
                    return f"❌ คุณไม่มีสิทธิ์เข้าถึง channel {channel_id}"

            preview = await get_channel_history_preview(channel_id, limit=15)
            if not preview:
                return f"❌ ไม่พบประวัติแชทของ channel {channel_id}"

            channel = self.bot.get_channel(channel_id)
            if channel:
                guild_name = (
                    channel.guild.name if hasattr(channel, "guild") and channel.guild else "DM"
                )
                channel_name = channel.name if hasattr(channel, "name") else "Unknown"
                header = f"📜 {guild_name}/#{channel_name}"
            else:
                header = f"📜 Channel {channel_id}"

            lines = [header, f"({len(preview)} ข้อความล่าสุด)", "---"]

            for item in preview:
                role = "U" if item["role"] == "user" else "AI"
                content = item["content"]
                lines.append(f"[{role}] {content}")

            return "\n".join(lines)
        except OSError as e:
            logging.error("Failed to get requested history: %s", e)
            return f"❌ เกิดข้อผิดพลาดในการดึงประวัติแชท: {e}"

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
        # Post-processing: Fix > before dialogue
        response_text = PATTERN_QUOTE.sub(r"\1", response_text)
        response_text = PATTERN_SPACED.sub(r"\1", response_text)

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
