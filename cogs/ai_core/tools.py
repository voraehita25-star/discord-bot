"""
AI Tools Module for Discord Bot.
Provides server management commands and webhook functionality for roleplay.
Optimized with webhook caching for better performance.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import discord

from .data.roleplay_data import SERVER_AVATARS
from .memory.rag import rag_system

# Import Audit Logger for tracking admin actions
try:
    from utils.monitoring.audit_log import log_admin_action, log_channel_change, log_role_change

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    log_channel_change = None
    log_role_change = None
    log_admin_action = None


# ==================== Input Sanitization ====================
# Protect against malicious input in AI-controlled operations

# Regex patterns for validation
_SAFE_CHANNEL_NAME = re.compile(r"[^a-zA-Z0-9\-_\u0E00-\u0E7F\s]")
_SAFE_ROLE_NAME = re.compile(r"[<>@#&]")


def sanitize_channel_name(name: str, max_length: int = 100) -> str:
    """Sanitize channel name to prevent injection attacks.

    Args:
        name: Raw channel name from AI
        max_length: Maximum allowed length

    Returns:
        Sanitized channel name
    """
    # Remove potentially dangerous characters
    cleaned = _SAFE_CHANNEL_NAME.sub("", name)
    # Normalize whitespace to dashes (Discord channel format)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    # Remove consecutive dashes
    cleaned = re.sub(r"-+", "-", cleaned)
    # Limit length and remove leading/trailing dashes
    return cleaned[:max_length].strip("-")


def sanitize_role_name(name: str, max_length: int = 100) -> str:
    """Sanitize role name to prevent mention injection.

    Args:
        name: Raw role name from AI
        max_length: Maximum allowed length

    Returns:
        Sanitized role name
    """
    # Remove characters that could be used for mention injection
    cleaned = _SAFE_ROLE_NAME.sub("", name)
    return cleaned.strip()[:max_length]


def sanitize_message_content(content: str, max_length: int = 2000) -> str:
    """Sanitize message content for safe sending.

    Args:
        content: Raw message content
        max_length: Maximum allowed length

    Returns:
        Sanitized message content
    """
    # Handle None input
    if content is None:
        return ""

    # Escape dangerous mentions by inserting zero-width space
    content = content.replace("@everyone", "@\u200beveryone")
    content = content.replace("@here", "@\u200bhere")

    # Limit length
    if len(content) > max_length:
        content = content[: max_length - 3] + "..."
    return content


# ==================== Webhook Cache ====================
# Cache webhooks to reduce API calls
_webhook_cache: dict[int, dict[str, discord.Webhook]] = {}  # channel_id -> {name: webhook}
_webhook_cache_time: dict[int, float] = {}  # channel_id -> last_update_time
WEBHOOK_CACHE_TTL = 600  # 10 minutes
_webhook_cache_cleanup_task: asyncio.Task | None = None  # Background cleanup task


def _get_cached_webhook(channel_id: int, webhook_name: str) -> discord.Webhook | None:
    """Get webhook from cache if valid."""
    now = time.time()
    if channel_id in _webhook_cache:
        if now - _webhook_cache_time.get(channel_id, 0) < WEBHOOK_CACHE_TTL:
            return _webhook_cache[channel_id].get(webhook_name)
    return None


async def _cleanup_expired_webhook_cache() -> None:
    """Background task to clean up expired webhook cache entries."""
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            now = time.time()
            expired_channels = [
                channel_id
                for channel_id, last_time in _webhook_cache_time.items()
                if now - last_time >= WEBHOOK_CACHE_TTL
            ]
            for channel_id in expired_channels:
                _webhook_cache.pop(channel_id, None)
                _webhook_cache_time.pop(channel_id, None)
            if expired_channels:
                logging.debug(
                    "🧹 Cleaned up %d expired webhook cache entries", len(expired_channels)
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            # Catch all exceptions to prevent task death, log and continue
            logging.error("Error in webhook cache cleanup: %s", e)
            await asyncio.sleep(60)  # Backoff on error before retrying


def start_webhook_cache_cleanup(bot) -> None:
    """Start the background webhook cache cleanup task."""
    global _webhook_cache_cleanup_task  # pylint: disable=global-statement
    if _webhook_cache_cleanup_task is None or _webhook_cache_cleanup_task.done():
        _webhook_cache_cleanup_task = bot.loop.create_task(_cleanup_expired_webhook_cache())
        logging.info("🧹 Started webhook cache cleanup task")


def stop_webhook_cache_cleanup() -> None:
    """Stop the background webhook cache cleanup task."""
    global _webhook_cache_cleanup_task  # pylint: disable=global-statement

    if _webhook_cache_cleanup_task and not _webhook_cache_cleanup_task.done():
        _webhook_cache_cleanup_task.cancel()
        _webhook_cache_cleanup_task = None
        logging.info("🧹 Stopped webhook cache cleanup task")

    # Clear cache on stop to free memory
    _webhook_cache.clear()
    _webhook_cache_time.clear()


def _set_cached_webhook(channel_id: int, webhook_name: str, webhook: discord.Webhook) -> None:
    """Store webhook in cache."""
    if channel_id not in _webhook_cache:
        _webhook_cache[channel_id] = {}
    _webhook_cache[channel_id][webhook_name] = webhook
    _webhook_cache_time[channel_id] = time.time()


def _invalidate_webhook_cache(channel_id: int, webhook_name: str | None = None) -> None:
    """Invalidate webhook cache for a channel.

    Call this when:
    - A channel is deleted
    - A webhook operation fails with 404
    - Cache needs to be refreshed

    Args:
        channel_id: The channel ID to invalidate
        webhook_name: Optional specific webhook name, or None to clear all for channel
    """
    if webhook_name:
        if channel_id in _webhook_cache:
            _webhook_cache[channel_id].pop(webhook_name, None)
    else:
        _webhook_cache.pop(channel_id, None)
        _webhook_cache_time.pop(channel_id, None)


def invalidate_webhook_cache_on_channel_delete(channel_id: int) -> None:
    """Public function to invalidate webhook cache when a channel is deleted.

    This should be called from an on_guild_channel_delete event listener.

    Args:
        channel_id: The ID of the deleted channel
    """
    _invalidate_webhook_cache(channel_id)
    logging.debug("🧹 Invalidated webhook cache for deleted channel %s", channel_id)


async def cmd_create_text(
    guild: discord.Guild, origin_channel: discord.TextChannel, name: str, args: list[str]
) -> None:
    """Create a text channel.

    Args:
        guild: The Discord guild to create the channel in
        origin_channel: The channel where the command was issued
        name: The name for the new channel
        args: Additional arguments (optional category name)
    """
    if not name:
        return

    # Sanitize channel name
    name = sanitize_channel_name(name)
    if not name:
        await origin_channel.send("❌ ชื่อช่องไม่ถูกต้อง")
        return

    category_name = args[1] if len(args) > 1 else None
    category = discord.utils.get(guild.categories, name=category_name) if category_name else None

    try:
        channel = await guild.create_text_channel(name, category=category)
        logging.info("🛠️ AI Created Text Channel: %s", name)
        await origin_channel.send(f"✅ สร้างช่องข้อความ **#{name}** เรียบร้อยแล้ว")

        # Log to audit trail
        if AUDIT_AVAILABLE and log_channel_change:
            await log_channel_change(
                user_id=guild.me.id,  # Bot as actor
                guild_id=guild.id,
                action="create",
                channel_id=channel.id,
                channel_name=name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้างช่อง")
    except discord.HTTPException as e:
        logging.error("Failed to create text channel: %s", e)
        await origin_channel.send(f"❌ ไม่สามารถสร้างช่องได้: {str(e)[:100]}")


async def cmd_create_voice(
    guild: discord.Guild, origin_channel: discord.TextChannel, name: str, args: list[str]
) -> None:
    """Create a voice channel.

    Args:
        guild: The Discord guild to create the channel in
        origin_channel: The channel where the command was issued
        name: The name for the new channel
        args: Additional arguments (optional category name)
    """
    if not name:
        return

    # Sanitize channel name
    name = sanitize_channel_name(name)
    if not name:
        await origin_channel.send("❌ ชื่อช่องไม่ถูกต้อง")
        return

    category_name = args[1] if len(args) > 1 else None
    category = discord.utils.get(guild.categories, name=category_name) if category_name else None

    try:
        channel = await guild.create_voice_channel(name, category=category)
        logging.info("🛠️ AI Created Voice Channel: %s", name)
        await origin_channel.send(f"✅ สร้างช่องเสียง **{name}** เรียบร้อยแล้ว")

        # Log to audit trail
        if AUDIT_AVAILABLE and log_channel_change:
            await log_channel_change(
                user_id=guild.me.id,
                guild_id=guild.id,
                action="create_voice",
                channel_id=channel.id,
                channel_name=name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้างช่อง")
    except discord.HTTPException as e:
        logging.error("Failed to create voice channel: %s", e)
        await origin_channel.send(f"❌ ไม่สามารถสร้างช่องได้: {str(e)[:100]}")


async def cmd_create_category(
    guild: discord.Guild, origin_channel: discord.TextChannel, name: str, _args: list[str]
) -> None:
    """Create a category.

    Args:
        guild: The Discord guild to create the category in
        origin_channel: The channel where the command was issued
        name: The name for the new category
        _args: Unused arguments
    """
    if not name:
        return

    # Sanitize category name
    name = sanitize_channel_name(name)
    if not name:
        await origin_channel.send("❌ ชื่อ Category ไม่ถูกต้อง")
        return

    try:
        await guild.create_category(name)
        logging.info("🛠️ AI Created Category: %s", name)
        await origin_channel.send(f"✅ สร้าง Category **{name}** เรียบร้อยแล้ว")
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้าง Category")
    except discord.HTTPException as e:
        logging.error("Failed to create category: %s", e)
        await origin_channel.send(f"❌ ไม่สามารถสร้าง Category ได้: {str(e)[:100]}")


async def cmd_delete_channel(
    guild: discord.Guild, origin_channel: discord.TextChannel, name: str, _args: list[str]
) -> None:
    """Delete a channel by name or ID.

    Args:
        guild: The Discord guild containing the channel
        origin_channel: The channel where the command was issued
        name: The name or ID of the channel to delete
        _args: Unused arguments
    """

    # Check for duplicate names
    matches = [ch for ch in guild.channels if ch.name.lower() == name.lower()]
    if len(matches) > 1:
        await origin_channel.send(
            f"⚠️ พบช่องชื่อ **{name}** จำนวน {len(matches)} ห้อง! กรุณาระบุ ID แทนเพื่อความปลอดภัย"
        )
        return

    channel = matches[0] if matches else None

    # Try ID if not found by name
    if not channel and name.isdigit():
        channel = guild.get_channel(int(name))

    if channel:
        try:
            await channel.delete()
            logging.info("🗑️ AI Deleted Channel: %s", name)
            await origin_channel.send(f"✅ ลบช่อง **{name}** เรียบร้อยแล้ว")
        except discord.Forbidden:
            await origin_channel.send(f"❌ บอทไม่มีสิทธิ์ลบช่อง **{name}**")
        except discord.HTTPException as e:
            logging.error("Failed to delete channel: %s", e)
            await origin_channel.send(f"❌ ไม่สามารถลบช่องได้: {str(e)[:100]}")
    else:
        logging.warning("AI tried to delete non-existent channel: %s", name)
        await origin_channel.send(f"❌ ไม่พบช่อง: **{name}**")


async def cmd_create_role(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Create a role with optional color."""
    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อยศที่ต้องการสร้าง")
        return

    role_name = args[0].strip()
    if not role_name:
        await origin_channel.send("❌ ชื่อยศไม่สามารถว่างได้")
        return

    # Sanitize role name
    role_name = sanitize_role_name(role_name)
    if not role_name:
        await origin_channel.send("❌ ชื่อยศไม่ถูกต้อง")
        return

    color_hex = args[1] if len(args) > 1 else None
    color = discord.Color.default()
    if color_hex:
        try:
            val = color_hex[1:] if color_hex.startswith("#") else color_hex
            color = discord.Color(int(val, 16))
        except ValueError:
            pass
    try:
        role = await guild.create_role(name=role_name, color=color)
        logging.info("🛠️ AI Created Role: %s", role_name)
        await origin_channel.send(f"✅ สร้างยศ **{role_name}** เรียบร้อยแล้ว")

        # Log to audit trail
        if AUDIT_AVAILABLE and log_role_change:
            await log_role_change(
                user_id=guild.me.id,
                guild_id=guild.id,
                action="create",
                role_id=role.id,
                role_name=role_name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้างยศ")
    except discord.HTTPException as e:
        logging.error("Failed to create role: %s", e)
        await origin_channel.send(f"❌ ไม่สามารถสร้างยศได้: {str(e)[:100]}")


async def cmd_delete_role(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Delete a role."""
    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อยศที่ต้องการลบ")
        return

    role_name = args[0]

    # Check for duplicate names
    matches = [r for r in guild.roles if r.name.lower() == role_name.lower()]
    if len(matches) > 1:
        await origin_channel.send(
            f"⚠️ พบยศชื่อ **{role_name}** จำนวน {len(matches)} ยศ! กรุณาระบุ ID แทนเพื่อความปลอดภัย"
        )
        return

    role = matches[0] if matches else None

    # Try ID
    if not role and role_name.isdigit():
        role = guild.get_role(int(role_name))
    if role:
        try:
            await role.delete()
            logging.info("🗑️ AI Deleted Role: %s", role_name)
            await origin_channel.send(f"✅ ลบยศ **{role_name}** เรียบร้อยแล้ว")
        except discord.Forbidden:
            await origin_channel.send(f"❌ บอทไม่มีสิทธิ์ลบยศ **{role_name}**")
        except discord.HTTPException as e:
            logging.error("Failed to delete role: %s", e)
            await origin_channel.send(f"❌ ไม่สามารถลบยศได้: {str(e)[:100]}")
    else:
        logging.warning("AI tried to delete non-existent role: %s", role_name)
        await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**")


def find_member(guild: discord.Guild, name: str) -> discord.Member | None:
    """Find a member by name, display_name, or partial match."""
    name_opts = [name, name.lower()]
    for n in name_opts:
        m = discord.utils.get(guild.members, display_name=n) or discord.utils.get(
            guild.members, name=n
        )
        if m:
            return m
        # Manual search
        m = next((m for m in guild.members if m.display_name.lower() == n.lower()), None) or next(
            (m for m in guild.members if m.name.lower() == n.lower()), None
        )
        if m:
            return m
    return None


async def cmd_add_role(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Add a role to a user."""
    if len(args) < 2:
        return
    user_name = args[0].strip()
    role_name = args[1].strip()

    role = discord.utils.get(guild.roles, name=role_name) or next(
        (r for r in guild.roles if r.name.lower() == role_name.lower()), None
    )

    member = find_member(guild, user_name)

    # Partial match fallback
    if not member:
        matches = [
            m
            for m in guild.members
            if user_name.lower() in m.name.lower() or user_name.lower() in m.display_name.lower()
        ]
        if len(matches) == 1:
            member = matches[0]

    if role and member:
        # Pre-validation: Check role hierarchy before API call
        if guild.me is None:
            await origin_channel.send("❌ บอทยังไม่พร้อมใช้งาน กรุณาลองใหม่อีกครั้ง")
            return
        bot_top_role = guild.me.top_role
        if role >= bot_top_role:
            await origin_channel.send(
                f"❌ บอทไม่สามารถมอบยศ **{role.name}** ได้ "
                f"(ยศของบอทอยู่ที่ตำแหน่ง {bot_top_role.position}, "
                f"ยศที่จะมอบอยู่ที่ตำแหน่ง {role.position})"
            )
            return
        try:
            await member.add_roles(role)
            logging.info("➕ AI Added Role %s to %s", role.name, member.display_name)
            await origin_channel.send(
                f"✅ มอบยศ **{role.name}** ให้กับ **{member.display_name}** เรียบร้อยแล้ว"
            )
        except discord.Forbidden:
            await origin_channel.send("❌ บอทไม่มีสิทธิ์มอบยศนี้ (ยศของบอทต้องอยู่สูงกว่ายศที่จะมอบ)")
        except discord.HTTPException as e:
            logging.error("Failed to add role: %s", e)
            await origin_channel.send(f"❌ ไม่สามารถมอบยศได้: {str(e)[:100]}")
    else:
        if not role:
            await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**")
        if not member:
            await origin_channel.send(f"❌ ไม่พบผู้ใช้: **{user_name}**")


async def cmd_remove_role(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Remove a role from a user."""
    if len(args) < 2:
        return
    user_name = args[0].strip()
    role_name = args[1].strip()

    role = discord.utils.get(guild.roles, name=role_name) or next(
        (r for r in guild.roles if r.name.lower() == role_name.lower()), None
    )

    member = find_member(guild, user_name)
    if not member:
        matches = [
            m
            for m in guild.members
            if user_name.lower() in m.name.lower() or user_name.lower() in m.display_name.lower()
        ]
        if len(matches) == 1:
            member = matches[0]

    if role and member:
        # Pre-validation: Check role hierarchy before API call
        if guild.me is None:
            await origin_channel.send("❌ บอทยังไม่พร้อมใช้งาน กรุณาลองใหม่อีกครั้ง")
            return
        bot_top_role = guild.me.top_role
        if role >= bot_top_role:
            await origin_channel.send(
                f"❌ บอทไม่สามารถลบยศ **{role.name}** ได้ "
                f"(ยศของบอทอยู่ที่ตำแหน่ง {bot_top_role.position}, "
                f"ยศที่จะลบอยู่ที่ตำแหน่ง {role.position})"
            )
            return
        try:
            await member.remove_roles(role)
            logging.info("➖ AI Removed Role %s from %s", role_name, user_name)
            await origin_channel.send(
                f"✅ ลบยศ **{role.name}** ออกจาก **{member.display_name}** เรียบร้อยแล้ว"
            )
        except discord.Forbidden:
            await origin_channel.send("❌ บอทไม่มีสิทธิ์ลบยศนี้ (ยศของบอทต้องอยู่สูงกว่ายศที่จะลบ)")
        except discord.HTTPException as err:
            logging.error("Failed to remove role: %s", err)
            await origin_channel.send(f"❌ ไม่สามารถลบยศได้: {str(err)[:100]}")
    else:
        if not role:
            await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**")
        if not member:
            await origin_channel.send(f"❌ ไม่พบผู้ใช้: **{user_name}**")


async def cmd_set_channel_perm(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Set permissions for a channel."""
    if len(args) < 4:
        await origin_channel.send("❌ กรุณาระบุพารามิเตอร์ให้ครบ: ช่อง|เป้าหมาย|สิทธิ์|ค่า")
        return
    channel_name = args[0]
    target_name = args[1]
    perm_name = args[2].lower()
    value_str = args[3].lower()
    value = True if value_str == "true" else False if value_str == "false" else None
    if value is None:
        await origin_channel.send("❌ ค่า permission ต้องเป็น 'true' หรือ 'false'")
        return

    channel = discord.utils.get(guild.channels, name=channel_name)
    if not channel:
        await origin_channel.send(f"❌ ไม่พบช่อง: **{channel_name}**")
        return

    target = None
    if target_name == "@everyone":
        target = guild.default_role
    else:
        target = discord.utils.get(guild.roles, name=target_name) or find_member(guild, target_name)

    if channel and target:
        overwrite = channel.overwrites_for(target)
        if perm_name == "read_messages":
            perm_name = "view_channel"

        if hasattr(overwrite, perm_name):
            try:
                setattr(overwrite, perm_name, value)
                await channel.set_permissions(target, overwrite=overwrite)
                logging.info(
                    "🔒 AI Set Channel Perm: %s | %s | %s=%s",
                    channel_name,
                    target_name,
                    perm_name,
                    value,
                )
                await origin_channel.send(
                    f"✅ ตั้งค่า permission **{perm_name}** = **{value}** "
                    f"ให้กับ **{target_name}** ในช่อง **{channel_name}** เรียบร้อยแล้ว"
                )
            except discord.Forbidden:
                await origin_channel.send("❌ บอทไม่มีสิทธิ์ตั้งค่า permission")
            except discord.HTTPException as e:
                logging.error("Failed to set channel permission: %s", e)
                await origin_channel.send(f"❌ ไม่สามารถตั้งค่า permission ได้: {str(e)[:100]}")
        else:
            await origin_channel.send(f"❌ ไม่พบ permission: **{perm_name}**")
    elif not target:
        await origin_channel.send(f"❌ ไม่พบเป้าหมาย: **{target_name}**")


async def cmd_set_role_perm(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Set permissions for a role."""
    if len(args) < 3:
        await origin_channel.send("❌ กรุณาระบุพารามิเตอร์ให้ครบ: ยศ|สิทธิ์|ค่า")
        return
    role_name = args[0].strip()
    perm_name = args[1].lower().strip()
    value_str = args[2].lower().strip()

    # Validate value first
    if value_str not in ("true", "false"):
        await origin_channel.send("❌ ค่า permission ต้องเป็น 'true' หรือ 'false'")
        return

    value = value_str == "true"

    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**")
        return

    perms = role.permissions
    if hasattr(perms, perm_name):
        try:
            setattr(perms, perm_name, value)
            await role.edit(permissions=perms)
            logging.info("🛡️ AI Set Role Perm: %s | %s=%s", role_name, perm_name, value)
            await origin_channel.send(
                f"✅ ตั้งค่า permission **{perm_name}** = **{value}** "
                f"ให้กับยศ **{role_name}** เรียบร้อยแล้ว"
            )
        except discord.Forbidden:
            await origin_channel.send("❌ บอทไม่มีสิทธิ์แก้ไขยศนี้")
        except discord.HTTPException as e:
            logging.error("Failed to set role permission: %s", e)
            await origin_channel.send(f"❌ ไม่สามารถตั้งค่า permission ได้: {str(e)[:100]}")
    else:
        await origin_channel.send(f"❌ ไม่พบ permission: **{perm_name}**")


async def cmd_list_channels(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, _args: list[str]
) -> None:
    """List all text channels."""
    channels = [f"#{ch.name} (ID: {ch.id})" for ch in guild.text_channels]
    await send_long_message(origin_channel, "**📜 Server Text Channels:**\n", channels)


async def cmd_list_roles(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, _args: list[str]
) -> None:
    """List all roles."""
    roles = [f"{r.name} (ID: {r.id})" for r in reversed(guild.roles) if r.name != "@everyone"]
    await send_long_message(origin_channel, "**🎭 Server Roles:**\n", roles)


async def cmd_list_members(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """List members with optional query and limit."""
    limit = 50  # Default limit
    query = None  # Default no query

    if args:
        if args[0].isdigit():
            limit = int(args[0])
            # Validate limit
            if limit < 1:
                limit = 1
            elif limit > 200:
                limit = 200  # Max limit to prevent huge responses
        if len(args) > 1 and args[1].strip():
            query = args[1].strip().lower()

    target_members = guild.members
    if query:
        target_members = [
            m for m in target_members if query in m.name.lower() or query in m.display_name.lower()
        ]

    display_list = [f"{m.display_name} ({m.name}) [ID: {m.id}]" for m in target_members]
    total = len(display_list)
    if len(display_list) > limit:
        display_list = display_list[:limit]

    await send_long_message(
        origin_channel,
        f"**👥 Server Members ({len(display_list)}/{total} shown):**\n",
        display_list,
    )


async def cmd_get_user_info(
    guild: discord.Guild, origin_channel: discord.TextChannel, _name: str, args: list[str]
) -> None:
    """Get detailed info about a user."""
    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อผู้ใช้หรือ ID ที่ต้องการค้นหา")
        return
    target = args[0].strip()
    if not target:
        await origin_channel.send("❌ ชื่อผู้ใช้ไม่สามารถว่างได้")
        return
    member = None
    if target.isdigit():
        member = guild.get_member(int(target))
    if not member:
        member = find_member(guild, target)

    # Partial
    if not member:
        matches = [
            m
            for m in guild.members
            if target.lower() in m.name.lower() or target.lower() in m.display_name.lower()
        ]
        if len(matches) == 1:
            member = matches[0]
        elif len(matches) > 1:
            info = "**🔍 Found multiple users:**\n" + "\n".join(
                [f"- {m.display_name} (@{m.name}) [ID: {m.id}]" for m in matches[:10]]
            )
            if len(matches) > 10:
                info += f"...and {len(matches) - 10} more."
            await origin_channel.send(f"```\n{info}\n```")
            return

    if member:
        roles = ", ".join([r.name for r in member.roles if r.name != "@everyone"])
        info = (
            f"**👤 User Info:**\n"
            f"Name: {member.name}\n"
            f"Display Name: {member.display_name}\n"
            f"ID: {member.id}\n"
            f"Status: {str(member.status).title()}\n"
            f"Joined: {member.joined_at.strftime('%Y-%m-%d')}\n"
            f"Roles: {roles}"
        )
        await origin_channel.send(f"```\n{info}\n```")
    else:
        await origin_channel.send(f"❌ ไม่พบผู้ใช้: {target}")


async def cmd_edit_message(_guild, origin_channel, _name, args):
    """Edit a message owned by the bot."""
    if len(args) < 2:
        await origin_channel.send("❌ กรุณาระบุพารามิเตอร์ให้ครบ: message_id | new_content")
        return
    msg_id = int(args[0].strip()) if args[0].strip().isdigit() else None
    if not msg_id:
        await origin_channel.send("❌ Message ID ต้องเป็นตัวเลขเท่านั้น")
        return
    new_content = args[1].strip()
    if not new_content:
        await origin_channel.send("❌ เนื้อหาใหม่ไม่สามารถว่างได้")
        return

    try:
        msg = await origin_channel.fetch_message(msg_id)
        bot = origin_channel.guild.me
        if msg.author == bot:
            await msg.edit(content=new_content)
        elif msg.webhook_id:
            webhooks = await origin_channel.webhooks()
            webhook = next((w for w in webhooks if w.id == msg.webhook_id), None)
            if webhook and webhook.user and webhook.user.id == bot.id:  # Check bot ID
                await webhook.edit_message(msg_id, content=new_content)
            else:
                await origin_channel.send("❌ แก้ไขไม่ได้: Webhook นี้ไม่ใช่ของบอท")
        else:
            await origin_channel.send("❌ แก้ไขไม่ได้: ข้อความไม่ใช่ของบอท")
    except (discord.NotFound, discord.HTTPException) as err:
        await origin_channel.send(f"❌ เกิดข้อผิดพลาด: {err}")


async def cmd_read_channel(guild, origin_channel, _name, args):
    """Read the last N messages from a channel."""
    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อช่องที่ต้องการอ่าน")
        return
    target_name = args[0].strip()
    if not target_name:
        await origin_channel.send("❌ ชื่อช่องไม่สามารถว่างได้")
        return
    limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
    # Validate limit
    if limit < 1 or limit > 100:
        limit = 10  # Default to 10 if invalid

    target_channel = discord.utils.get(guild.text_channels, name=target_name)
    if not target_channel and target_name.isdigit():
        target_channel = guild.get_channel(int(target_name))

    if target_channel:
        messages = []
        async for msg in target_channel.history(limit=limit):
            content = msg.content or "[Image/Attachment]"
            messages.append(
                f"[{msg.created_at.strftime('%H:%M')}] {msg.author.display_name}: {content}"
            )
        messages.reverse()
        await send_long_message(
            origin_channel, f"**📖 Reading Channel: #{target_channel.name}**\n", messages
        )
    else:
        await origin_channel.send(f"❌ ไม่พบช่อง: {target_name}")


async def send_long_message(channel, header, lines):
    """Send a message that might exceed Discord's character limit."""
    current_chunk = header
    for line in lines:
        if len(current_chunk) + len(line) + 5 > 1900:
            await channel.send(f"```\n{current_chunk}\n```")
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        await channel.send(f"```\n{current_chunk}\n```")


def get_tool_definitions() -> list[dict]:
    """Return tool definitions for Gemini."""
    return [
        {
            "function_declarations": [
                {
                    "name": "create_text_channel",
                    "description": "Create a new text channel in the server",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "Name of the channel"},
                            "category": {
                                "type": "STRING",
                                "description": "Name of the category to place the channel in",
                            },
                        },
                        "required": ["name"],
                    },
                },
                {
                    "name": "create_voice_channel",
                    "description": "Create a new voice channel in the server",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "Name of the channel"},
                            "category": {
                                "type": "STRING",
                                "description": "Name of the category to place the channel in",
                            },
                        },
                        "required": ["name"],
                    },
                },
                {
                    "name": "create_category",
                    "description": "Create a new category in the server",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "Name of the category"}
                        },
                        "required": ["name"],
                    },
                },
                {
                    "name": "delete_channel",
                    "description": "Delete a channel by name or ID",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "name_or_id": {
                                "type": "STRING",
                                "description": "Name or ID of the channel to delete",
                            }
                        },
                        "required": ["name_or_id"],
                    },
                },
                {
                    "name": "create_role",
                    "description": "Create a new role in the server",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "Name of the role"},
                            "color_hex": {
                                "type": "STRING",
                                "description": "Hex color code for the role (e.g. #FF0000)",
                            },
                        },
                        "required": ["name"],
                    },
                },
                {
                    "name": "delete_role",
                    "description": "Delete a role by name or ID",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "name_or_id": {
                                "type": "STRING",
                                "description": "Name or ID of the role to delete",
                            }
                        },
                        "required": ["name_or_id"],
                    },
                },
                {
                    "name": "add_role",
                    "description": "Add a role to a user",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "user_name": {"type": "STRING", "description": "Name of the user"},
                            "role_name": {"type": "STRING", "description": "Name of the role"},
                        },
                        "required": ["user_name", "role_name"],
                    },
                },
                {
                    "name": "remove_role",
                    "description": "Remove a role from a user",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "user_name": {"type": "STRING", "description": "Name of the user"},
                            "role_name": {"type": "STRING", "description": "Name of the role"},
                        },
                        "required": ["user_name", "role_name"],
                    },
                },
                {
                    "name": "set_channel_permission",
                    "description": "Set permissions for a channel",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "channel_name": {
                                "type": "STRING",
                                "description": "Name of the channel",
                            },
                            "target_name": {
                                "type": "STRING",
                                "description": "Name of user or role (@everyone)",
                            },
                            "permission": {
                                "type": "STRING",
                                "description": "Permission name (e.g. view_channel, send_messages)",
                            },
                            "value": {
                                "type": "BOOLEAN",
                                "description": "True to allow, False to deny",
                            },
                        },
                        "required": ["channel_name", "target_name", "permission", "value"],
                    },
                },
                {
                    "name": "set_role_permission",
                    "description": "Set permissions for a role",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "role_name": {"type": "STRING", "description": "Name of the role"},
                            "permission": {
                                "type": "STRING",
                                "description": "Permission name (e.g. administrator, manage_channels)",
                            },
                            "value": {
                                "type": "BOOLEAN",
                                "description": "True to allow, False to deny",
                            },
                        },
                        "required": ["role_name", "permission", "value"],
                    },
                },
                {
                    "name": "list_channels",
                    "description": "List all text channels in the server",
                    "parameters": {"type": "OBJECT", "properties": {}},
                },
                {
                    "name": "list_roles",
                    "description": "List all roles in the server",
                    "parameters": {"type": "OBJECT", "properties": {}},
                },
                {
                    "name": "list_members",
                    "description": "List members in the server",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "limit": {
                                "type": "INTEGER",
                                "description": "Number of members to list (default 50)",
                            },
                            "query": {
                                "type": "STRING",
                                "description": "Search query for filtering members",
                            },
                        },
                    },
                },
                {
                    "name": "get_user_info",
                    "description": "Get detailed info about a user",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {"type": "STRING", "description": "Name or ID of the user"}
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "read_channel",
                    "description": "Read last N messages from a channel",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "channel_name": {
                                "type": "STRING",
                                "description": "Name of the channel",
                            },
                            "limit": {
                                "type": "INTEGER",
                                "description": "Number of messages to read (default 10)",
                            },
                        },
                        "required": ["channel_name"],
                    },
                },
                {
                    "name": "remember",
                    "description": "Save important information to long-term memory",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "content": {
                                "type": "STRING",
                                "description": "The fact or information to remember",
                            }
                        },
                        "required": ["content"],
                    },
                },
                # NOTE: search_limbus_knowledge removed - using Google Search instead
                # NOTE: search_limbus_wiki also removed - Cloudflare blocks direct wiki access
            ]
        }
    ]


async def execute_tool_call(_bot, origin_channel, user, tool_call):
    """Execute a function call from Gemini."""
    fname = tool_call.name
    args = tool_call.args

    # Map function names to internal command handlers
    # We will reuse the existing logic but adapt the arguments

    guild = origin_channel.guild

    # Permission check is already done in execute_server_command, but we can do it here too
    if not user.guild_permissions.administrator:
        return f"⛔ Permission denied: User {user.display_name} is not an Admin."

    try:
        if fname == "create_text_channel":
            await cmd_create_text(
                guild, origin_channel, args.get("name"), [None, args.get("category")]
            )
            return f"Requested creation of text channel '{args.get('name')}'"

        elif fname == "create_voice_channel":
            await cmd_create_voice(
                guild, origin_channel, args.get("name"), [None, args.get("category")]
            )
            return f"Requested creation of voice channel '{args.get('name')}'"

        elif fname == "create_category":
            await cmd_create_category(guild, origin_channel, args.get("name"), [])
            return f"Requested creation of category '{args.get('name')}'"

        elif fname == "delete_channel":
            await cmd_delete_channel(guild, origin_channel, args.get("name_or_id"), [])
            return f"Requested deletion of channel '{args.get('name_or_id')}'"

        elif fname == "create_role":
            cmd_args = [args.get("name")]
            if args.get("color_hex"):
                cmd_args.append(args.get("color_hex"))
            await cmd_create_role(guild, origin_channel, None, cmd_args)
            return f"Requested creation of role '{args.get('name')}'"

        elif fname == "delete_role":
            await cmd_delete_role(guild, origin_channel, None, [args.get("name_or_id")])
            return f"Requested deletion of role '{args.get('name_or_id')}'"

        elif fname == "add_role":
            await cmd_add_role(
                guild, origin_channel, None, [args.get("user_name"), args.get("role_name")]
            )
            return f"Requested adding role '{args.get('role_name')}' to '{args.get('user_name')}'"

        elif fname == "remove_role":
            await cmd_remove_role(
                guild, origin_channel, None, [args.get("user_name"), args.get("role_name")]
            )
            return (
                f"Requested removing role '{args.get('role_name')}' from '{args.get('user_name')}'"
            )

        elif fname == "set_channel_permission":
            await cmd_set_channel_perm(
                guild,
                origin_channel,
                None,
                [
                    args.get("channel_name"),
                    args.get("target_name"),
                    args.get("permission"),
                    str(args.get("value")),
                ],
            )
            return f"Requested setting channel permission for '{args.get('channel_name')}'"

        elif fname == "set_role_permission":
            await cmd_set_role_perm(
                guild,
                origin_channel,
                None,
                [args.get("role_name"), args.get("permission"), str(args.get("value"))],
            )
            return f"Requested setting role permission for '{args.get('role_name')}'"

        elif fname == "list_channels":
            await cmd_list_channels(guild, origin_channel, None, [])
            return "Listed channels"

        elif fname == "list_roles":
            await cmd_list_roles(guild, origin_channel, None, [])
            return "Listed roles"

        elif fname == "list_members":
            cmd_args = []
            if args.get("limit"):
                cmd_args.append(str(args.get("limit")))
            if args.get("query"):
                if not cmd_args:
                    cmd_args.append("50")
                cmd_args.append(args.get("query"))
            await cmd_list_members(guild, origin_channel, None, cmd_args)
            return "Listed members"

        elif fname == "get_user_info":
            await cmd_get_user_info(guild, origin_channel, None, [args.get("target")])
            return f"Requested info for '{args.get('target')}'"

        elif fname == "read_channel":
            cmd_args = [args.get("channel_name")]
            if args.get("limit"):
                cmd_args.append(str(args.get("limit")))
            await cmd_read_channel(guild, origin_channel, None, cmd_args)
            return f"Requested reading channel '{args.get('channel_name')}'"

        elif fname == "remember":
            content = args.get("content")
            if content:
                await rag_system.add_memory(content, channel_id=origin_channel.id)
            return f"✅ Saved to long-term memory: {content}"
            return "❌ Failed to save memory: Content is empty"

        # NOTE: search_limbus_knowledge and search_limbus_wiki handlers removed
        # Using Google Search grounding instead for Limbus Company data

        else:
            return f"Unknown function: {fname}"

    except (ValueError, discord.HTTPException) as e:
        logging.error("Tool execution error: %s", e)
        return f"Error executing {fname}: {e}"


# Dispatcher Table
COMMAND_HANDLERS = {
    "CREATE_TEXT": cmd_create_text,
    "CREATE_VOICE": cmd_create_voice,
    "CREATE_CATEGORY": cmd_create_category,
    "DELETE_CHANNEL": cmd_delete_channel,
    "CREATE_ROLE": cmd_create_role,
    "DELETE_ROLE": cmd_delete_role,
    "ADD_ROLE": cmd_add_role,
    "REMOVE_ROLE": cmd_remove_role,
    "SET_CHANNEL_PERM": cmd_set_channel_perm,
    "SET_ROLE_PERM": cmd_set_role_perm,
    "LIST_CHANNELS": cmd_list_channels,
    "LIST_ROLES": cmd_list_roles,
    "LIST_MEMBERS": cmd_list_members,
    "GET_USER_INFO": cmd_get_user_info,
    "EDIT_MESSAGE": cmd_edit_message,
    "READ_CHANNEL": cmd_read_channel,
}


async def execute_server_command(bot, origin_channel, user, cmd_type, cmd_args):  # pylint: disable=unused-argument
    """Execute server management commands using the dispatcher."""
    if not user.guild_permissions.administrator:
        logging.warning("⚠️ User %s tried Admin Command %s without perm.", user, cmd_type)
        await origin_channel.send(f"⛔ คำสั่งนี้สำหรับ Admin เท่านั้น ({user.display_name})")
        return

    try:
        # Check if channel has guild (should always be true for server commands)
        if not hasattr(origin_channel, "guild") or not origin_channel.guild:
            logging.warning("Server command called in non-guild channel")
            await origin_channel.send("❌ คำสั่งนี้ใช้ได้เฉพาะใน server เท่านั้น")
            return

        guild = origin_channel.guild

        # Validate cmd_args
        if not cmd_args:
            cmd_args = ""

        args = [arg.strip() for arg in cmd_args.split("|") if arg.strip()]
        name = args[0] if args else ""

        # Validation
        if name and len(name) > 100:
            await origin_channel.send("❌ ชื่อยาวเกินไป (สูงสุด 100 ตัวอักษร)")
            return

        # Dispatch
        handler = COMMAND_HANDLERS.get(cmd_type)
        if handler:
            await handler(guild, origin_channel, name, args)
        else:
            logging.warning("Unknown command type: %s", cmd_type)

    except (discord.DiscordException, ValueError) as err:
        logging.error("Failed to execute server command %s: %s", cmd_type, err)


async def send_as_webhook(bot, channel, name, message):
    """Send a message using a webhook to mimic Tupperbox with correct avatar.
    Uses caching to reduce API calls for better performance.
    """
    try:
        # Check bot permissions first
        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            await channel.send(f"**{name}**: {message}")
            return None

        webhook_name = f"AI: {name}"
        channel_id = channel.id

        # Try cache first
        webhook = _get_cached_webhook(channel_id, webhook_name)

        if webhook:
            try:
                # Try sending with cached webhook
                sent_message = None
                limit = 2000
                if len(message) > limit:
                    for i in range(0, len(message), limit):
                        sent_message = await webhook.send(
                            content=message[i : i + limit], username=name, wait=True
                        )
                else:
                    sent_message = await webhook.send(content=message, username=name, wait=True)
                logging.debug("🎭 AI spoke as %s (cached webhook)", name)
                return sent_message
            except discord.NotFound:
                # Webhook deleted, invalidate cache and continue to create new one
                _invalidate_webhook_cache(channel_id, webhook_name)
                webhook = None
            except discord.HTTPException:
                # Other error, invalidate and continue
                _invalidate_webhook_cache(channel_id, webhook_name)
                webhook = None

        # Determine Avatar
        avatar_bytes = None
        # Use server_avatars for Webhooks (Profile Images)
        if channel.guild.id in SERVER_AVATARS:
            char_map = SERVER_AVATARS[channel.guild.id]
            # Try exact match or case-insensitive
            img_path = char_map.get(name)
            if not img_path:
                # Try finding key case-insensitive
                for key, path in char_map.items():
                    if key.lower() == name.lower():
                        img_path = path
                        break

            if img_path:
                # Fix path resolution: Use current working directory (bot root)
                full_path = Path.cwd() / img_path
                if full_path.exists():
                    try:
                        avatar_bytes = full_path.read_bytes()
                    except OSError as err:
                        logging.error("Failed to read avatar file %s: %s", full_path, err)

        # Find existing webhook for this character
        webhooks = await channel.webhooks()

        # 1. Try to find specific character webhook
        for wh in webhooks:
            if wh.user and wh.user == bot.user and wh.name == webhook_name:
                webhook = wh
                break

        # 2. If not found, create new one (if limit allows)
        if not webhook:
            if len(webhooks) < 15:  # Discord's webhook limit is 15 per channel
                try:
                    webhook = await channel.create_webhook(name=webhook_name, avatar=avatar_bytes)
                    logging.info("🆕 Created new webhook for %s", name)
                except discord.HTTPException as err:
                    logging.warning("Failed to create webhook for %s: %s", name, err)
            else:
                # Limit reached, try to reuse "AI Tupper Proxy" or oldest
                for wh in webhooks:
                    if wh.user and wh.user == bot.user and wh.name == "AI Tupper Proxy":
                        webhook = wh
                        break

                # If still no webhook, just pick the first one owned by bot
                if not webhook:
                    for wh in webhooks:
                        if wh.user and wh.user == bot.user:
                            webhook = wh
                            break

        # 3. Send Message and cache webhook
        if webhook:
            # Cache the webhook for future use
            _set_cached_webhook(channel_id, webhook_name, webhook)

            sent_message = None
            # Send message (truncate if too long)
            limit = 2000
            if len(message) > limit:
                for i in range(0, len(message), limit):
                    sent_message = await webhook.send(
                        content=message[i : i + limit], username=name, wait=True
                    )
            else:
                sent_message = await webhook.send(content=message, username=name, wait=True)
            logging.info("🎭 AI spoke as %s", name)
            return sent_message

        # Fallback if no webhook could be found/created
        return await channel.send(f"**{name}**: {message}")

    except discord.Forbidden:
        logging.warning("No permission to manage webhooks in %s", channel.name)
        return await channel.send(f"**{name}**: {message}")
    except discord.HTTPException as err:
        logging.error("Failed to send webhook: %s", err)
        return await channel.send(f"**{name}**: {message}")
