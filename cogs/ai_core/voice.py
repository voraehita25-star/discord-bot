"""
Voice Channel Management Module.
Handles voice channel join/leave operations and status tracking.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from discord.ext.commands import Bot


class _VoiceLikeChannel(Protocol):
    id: int
    name: str
    guild: Any

    async def connect(self, *, timeout: float = ...) -> Any: ...


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
        if voice_client and voice_client.is_connected():
            if voice_client.channel and voice_client.channel.id == channel_id:
                return True, f"✅ อยู่ใน **{voice_channel.name}** อยู่แล้ว"
            # Move to new channel
            await voice_client.move_to(voice_channel)
            return True, f"✅ ย้ายมารอใน **{voice_channel.name}** แล้ว"

        # Stale client: discord.py may keep a non-connected VoiceClient in
        # _voice_clients, making connect() raise ClientException('Already
        # connected'). Force-disconnect it first so we can recover.
        if voice_client:
            await voice_client.disconnect(force=True)

        # Join voice channel (with timeout to prevent indefinite hang on gateway issues)
        await voice_channel.connect(timeout=30.0)
        logger.info("🎤 AI joined voice channel: %s", voice_channel.name)
        return True, f"✅ เข้าไปรอใน **{voice_channel.name}** แล้ว"

    except Exception:
        # Broad catch is intentional here: discord.py wraps voice errors
        # in many types (ClientException, OpusNotLoaded, ConnectionClosed,
        # OS-level socket errors) and we don't want to import discord at
        # module load time (this file is type-only). The
        # ``logger.exception`` captures the traceback so debugging isn't
        # blind even though the user sees a generic Thai message.
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

    # Join phrases that can only mean "join a voice channel" — they name the
    # voice channel explicitly, so they stand on their own with no id.
    join_explicit = ["join vc", "join voice", "เข้า vc", "เข้าห้องเสียง", "เข้าช่องเสียง"]

    # Join phrases that are also ordinary Thai. "เข้าห้อง" is *enter the room*
    # ("เข้าห้องน้ำ", "เข้าห้องเรียน"), "เข้ามาใน" is *come into* — the single
    # most common opening in RP narration — and "มารอใน" is *wait in*. Matched
    # as bare substrings they turned a DM like "เดี๋ยวเข้าห้องน้ำก่อนนะ" into a
    # voice-join attempt instead of a reply (measured). They still work, but
    # only when the message also names a channel id, which is what a real
    # command carries anyway.
    join_ambiguous = ["เข้ามารอใน", "เข้าไปรอใน", "มารอใน", "เข้าห้อง", "เข้ามาใน"]

    # Leave patterns. Same rule, and it matters more here because leave is
    # DESTRUCTIVE — it disconnects every voice client the bot holds — and takes
    # no channel id, so there is no second signal to confirm intent with. Only
    # phrases that name the voice channel qualify: bare "ออกจากห้อง" is *left
    # the room* ("ออกจากห้องน้ำแล้ว", "ออกจากห้องประชุม") and used to force a
    # disconnect from a passing remark. This is the same narrative-mention
    # hazard the word-boundary guard on "disconnect" below already covers; the
    # Thai side was simply never given it.
    leave_patterns = [
        "ออกจาก vc",
        "leave vc",
        "leave voice",
        "ออก vc",
        "ออกจากห้องเสียง",
        "ออกจากช่องเสียง",
    ]

    # Check for leave
    if any(pattern in msg_lower for pattern in leave_patterns) or re.search(
        r"\bdisconnect\b", msg_lower
    ):
        return "leave", None

    # Explicit join: act even without an id, so the caller can ask for one.
    if any(pattern in msg_lower for pattern in join_explicit):
        channel_match = PATTERN_CHANNEL_ID.search(message)
        return "join", int(channel_match.group(1)) if channel_match else None

    # Ambiguous join: the channel id IS the confirmation. Without one the
    # message falls through and is answered as chat, which is the right outcome
    # for narration and the recoverable one for a genuine command (say it again
    # with the id, or use "join vc").
    if any(pattern in msg_lower for pattern in join_ambiguous):
        channel_match = PATTERN_CHANNEL_ID.search(message)
        if channel_match:
            return "join", int(channel_match.group(1))

    return None, None


def _music_track_title(music_cog: Any, guild_id: int) -> str | None:
    """Safely resolve the current track title from the Music cog.

    Reaches into the Music cog's private ``_gs`` accessor, which is cross-cog
    coupling. Guard against a future rename or any exception from ``_gs`` so a
    missing/changed accessor degrades to a plain "playing" status instead of
    failing the entire voice-status string.
    """
    try:
        gs_fn = getattr(music_cog, "_gs", None)
        if not callable(gs_fn):
            return None
        gs = gs_fn(guild_id)
        track_info = getattr(gs, "current_track", None) or {}
        return cast("str", track_info.get("title", "Unknown"))
    except Exception:
        logger.debug("Failed to read current track from Music cog", exc_info=True)
        return None


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
                    track_title = _music_track_title(music_cog, guild_id)
                    if track_title:
                        status = f"กำลังเล่นเพลง: {track_title}"
            elif vc.is_paused():  # type: ignore[attr-defined]
                status = "หยุดชั่วคราว"
                # Get paused track info
                if music_cog and guild_id:
                    track_title = _music_track_title(music_cog, guild_id)
                    if track_title:
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
