"""
Server Commands Module.
Provides Discord server management commands for AI tools.
"""

from __future__ import annotations

import logging

import discord

from .sanitization import sanitize_channel_name, sanitize_role_name

# Import Audit Logger for tracking admin actions
try:
    from utils.monitoring.audit_log import log_admin_action, log_channel_change, log_role_change

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    log_channel_change = None
    log_role_change = None
    log_admin_action = None


def find_member(guild: discord.Guild, name: str) -> discord.Member | None:
    """Find a member by name, display_name, or partial match.

    Args:
        guild: The Discord guild to search in
        name: Name to search for

    Returns:
        Found member or None
    """
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


# Command Handler Mapping
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


__all__ = [
    "COMMAND_HANDLERS",
    "cmd_add_role",
    "cmd_create_category",
    "cmd_create_role",
    "cmd_create_text",
    "cmd_create_voice",
    "cmd_delete_channel",
    "cmd_delete_role",
    "cmd_edit_message",
    "cmd_get_user_info",
    "cmd_list_channels",
    "cmd_list_members",
    "cmd_list_roles",
    "cmd_read_channel",
    "cmd_remove_role",
    "cmd_set_channel_perm",
    "cmd_set_role_perm",
    "find_member",
    "send_long_message",
]
