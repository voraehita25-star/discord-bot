"""
Voice Channel Management Module.
Handles voice channel join/leave operations and status tracking.
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
import re
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, cast

if TYPE_CHECKING:
    from discord.ext.commands import Bot


class _VoiceLikeChannel(Protocol):
    id: int
    name: str
    guild: Any

    async def connect(self) -> Any: ...


def _is_voice_like_channel(channel: object) -> TypeGuard[_VoiceLikeChannel]:
    """Return True when the object behaves like a Discord voice/stage channel."""
    return all(hasattr(channel, attr) for attr in ("connect", "guild", "name", "id"))

# Channel ID extraction pattern
PATTERN_CHANNEL_ID = re.compile(r"\b(\d{17,20})\b")


async def join_voice_channel(bot: Bot, channel_id: int) -> tuple[bool, str]:
    """Join a voice channel by ID.

    Args:
        bot: Discord bot instance
        channel_id: Discord voice channel ID

    Returns:
        (success, message) tuple
    """
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            return False, "❌ ไม่พบช่องเสียงที่ระบุ"

        if not _is_voice_like_channel(channel):
            return False, "❌ นี่ไม่ใช่ช่องเสียง"

        voice_channel = cast(_VoiceLikeChannel, channel)

        # Ensure channel has a guild (DM channels don't)
        guild = getattr(voice_channel, "guild", None)
        if not guild:
            return False, "❌ ไม่สามารถใช้งานในข้อความส่วนตัว"

        # Check if already connected to this channel
        voice_client = guild.voice_client
        if voice_client:
            if voice_client.channel and voice_client.channel.id == channel_id:
                return True, f"✅ อยู่ใน **{voice_channel.name}** อยู่แล้ว"
            # Move to new channel
            await voice_client.move_to(voice_channel)
            return True, f"✅ ย้ายมารอใน **{voice_channel.name}** แล้ว"

        # Join voice channel
        await voice_channel.connect()
        logger.info("🎤 AI joined voice channel: %s", voice_channel.name)
        return True, f"✅ เข้าไปรอใน **{voice_channel.name}** แล้ว"

    except Exception:
        logger.exception("Failed to join voice channel")
        return False, "❌ ไม่สามารถเข้าช่องเสียงได้ กรุณาลองใหม่อีกครั้ง"


async def leave_voice_channel(bot: Bot, guild_id: int) -> tuple[bool, str]:
    """Leave voice channel in a guild.

    Args:
        bot: Discord bot instance
        guild_id: Discord guild ID

    Returns:
        (success, message) tuple
    """
    try:
        guild = bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            return False, "❌ ไม่ได้อยู่ในช่องเสียง"

        channel_name = guild.voice_client.channel.name if guild.voice_client.channel else "Unknown"  # type: ignore[attr-defined]
        await guild.voice_client.disconnect(force=True)
        logger.info("🎤 AI left voice channel: %s", channel_name)
        return True, f"✅ ออกจาก **{channel_name}** แล้ว"

    except Exception:
        logger.exception("Failed to leave voice channel")
        return False, "❌ ไม่สามารถออกจากช่องเสียงได้ กรุณาลองใหม่อีกครั้ง"


def parse_voice_command(message: str) -> tuple[str | None, int | None]:
    """Parse voice channel commands from message.

    Returns:
        (action, channel_id) - action is 'join', 'leave', or None
    """
    msg_lower = message.lower()

    # Join patterns
    join_patterns = [
        "เข้ามารอใน",
        "เข้าไปรอใน",
        "join vc",
        "join voice",
        "เข้า vc",
        "มารอใน",
        "เข้าห้อง",
        "เข้ามาใน",
    ]

    # Leave patterns
    leave_patterns = ["ออกจาก vc", "leave vc", "leave voice", "ออกจากห้อง", "ออก vc", "disconnect"]

    # Check for leave
    for pattern in leave_patterns:
        if pattern in msg_lower:
            return "leave", None

    # Check for join - extract channel ID
    for pattern in join_patterns:
        if pattern in msg_lower:
            # Try to find channel ID in message
            channel_match = PATTERN_CHANNEL_ID.search(message)
            if channel_match:
                return "join", int(channel_match.group(1))
            return "join", None

    return None, None


def get_voice_status(bot: Bot) -> str:
    """Get current voice connection status for all servers."""
    if not bot.voice_clients:
        return "Faust ไม่ได้เชื่อมต่อกับห้องเสียงใดๆ"

    # Try to get Music cog for track info
    music_cog = bot.get_cog("Music")

    voice_info = []
    for vc in bot.voice_clients:
        if vc.is_connected() and vc.channel:  # type: ignore[attr-defined]
            guild_name = vc.guild.name if vc.guild else "Unknown Server"  # type: ignore[attr-defined]
            guild_id = vc.guild.id if vc.guild else None  # type: ignore[attr-defined]
            channel_name = vc.channel.name  # type: ignore[attr-defined]

            # Get members in voice channel (excluding bots)
            members = [m.display_name for m in vc.channel.members if not m.bot]  # type: ignore[attr-defined]
            member_count = len(members)

            # Check if playing music and get track info
            if vc.is_playing():  # type: ignore[attr-defined]
                status = "กำลังเล่นเพลง"
                # Get current track info from Music cog
                if music_cog and guild_id:
                    track_info = music_cog.current_track.get(guild_id, {})  # type: ignore[attr-defined]
                    track_title = track_info.get("title", "Unknown")
                    status = f"กำลังเล่นเพลง: {track_title}"
            elif vc.is_paused():  # type: ignore[attr-defined]
                status = "หยุดชั่วคราว"
                # Get paused track info
                if music_cog and guild_id:
                    track_info = music_cog.current_track.get(guild_id, {})  # type: ignore[attr-defined]
                    track_title = track_info.get("title", "Unknown")
                    status = f"หยุดชั่วคราว: {track_title}"
            else:
                status = "ว่าง (ไม่ได้เล่นเพลง)"

            if members:
                member_list = ", ".join(members[:5])  # Show max 5 members
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
