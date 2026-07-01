"""
Server Commands Module.
Provides Discord server management commands for AI tools.
"""

from __future__ import annotations

import logging
import unicodedata

import discord

from ..sanitization import sanitize_channel_name, sanitize_role_name

# Error messages below echo raw, user/AI-supplied identifiers (channel /
# role / user names, raw targets). The bot's global AllowedMentions allows
# user pings (users=True), so a ``<@id>`` slipped into one of those names
# would ping that user. Send all such echoes with mentions fully disabled.
_NO_MENTIONS = discord.AllowedMentions.none()


def _safe_int(value: str, *, max_digits: int | None = None) -> int | None:
    """Parse ``value`` as a base-10 int, returning None instead of raising.

    Gating an ``int()`` call on ``str.isdigit()`` is NOT crash-safe: ``isdigit()``
    is True for many non-ASCII digit characters (superscripts ``²``, circled
    digits ``①``, Kharoshthi, …) that ``int()`` cannot parse — and an
    all-ASCII-digit string longer than ``sys.get_int_max_str_digits()`` (4300)
    also raises ``ValueError``. Both forms are model/AI-reachable through the
    tool dispatch, so every AI-supplied numeric arg must convert through here
    rather than ``isdigit()`` + ``int()``. ``max_digits`` short-circuits absurd
    lengths before the parse (used for the unbounded ``limit`` arg).
    """
    try:
        if max_digits is not None and len(value) > max_digits:
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _fmt_http_error(e: discord.HTTPException) -> str:
    """Format a discord.HTTPException for safe display to end users.

    Returns only the HTTP status and Discord error code — never the raw
    response body, which can contain tokens, internal URLs, or user input
    echoed back from the API.
    """
    status = getattr(e, "status", "?")
    code = getattr(e, "code", 0)
    return f"(HTTP {status}, code {code})"


# Allowlist of safe permissions that the AI is allowed to set.
# Dangerous permissions (administrator, manage_guild, manage_roles, etc.) are excluded.
_SAFE_PERMISSIONS: frozenset[str] = frozenset(
    {
        # Channel-level permissions
        "view_channel",
        "read_messages",  # read_messages is alias for view_channel
        "send_messages",
        "send_messages_in_threads",
        "create_public_threads",
        "create_private_threads",
        "embed_links",
        "attach_files",
        "add_reactions",
        "use_external_emojis",
        "use_external_stickers",
        "read_message_history",
        "connect",
        "speak",
        "stream",
        "use_voice_activation",
        # ``manage_threads`` was previously here but it lets a holder
        # delete/lock threads owned by other users, including the
        # original poster's. Promote to ``_DANGEROUS_PERMISSIONS``
        # below so the AI can't grant it.
        "priority_speaker",
        "request_to_speak",
        "use_application_commands",
        "use_embedded_activities",
        "use_soundboard",
        "use_external_sounds",
        "send_voice_messages",
        "send_polls",
        "create_events",
        "manage_events",
        # General non-dangerous permissions
        "change_nickname",
        "manage_nicknames",
        "create_instant_invite",
        "external_emojis",
        "external_stickers",
    }
)

# Explicitly blocked dangerous permissions
_DANGEROUS_PERMISSIONS: frozenset[str] = frozenset(
    {
        "administrator",
        "manage_guild",
        "manage_roles",
        "manage_channels",
        "manage_webhooks",
        "manage_expressions",
        "kick_members",
        "ban_members",
        "mention_everyone",
        "view_audit_log",
        "view_guild_insights",
        "moderate_members",
        # Moved from _SAFE_PERMISSIONS: these are still risky for AI-controlled actions
        "manage_messages",
        "mute_members",
        "deafen_members",
        "move_members",
        # Promoted from _SAFE_PERMISSIONS — ``manage_threads`` lets the
        # holder delete/lock threads they don't own, including the
        # creator's. AI shouldn't be able to grant this without an
        # explicit operator workflow.
        "manage_threads",
    }
)

# Import Audit Logger for tracking admin actions
try:
    from utils.monitoring.audit_log import log_channel_change, log_role_change

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    log_channel_change = None  # type: ignore[assignment]
    log_role_change = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


def find_member(guild: discord.Guild, name: str) -> discord.Member | None:
    """Find a member by name, display_name, or partial match.

    Args:
        guild: The Discord guild to search in
        name: Name to search for

    Returns:
        Found member or None
    """
    # Order-preserving de-dup: try the exact-case spelling first, then the
    # lowercased form. A set literal here made the two-candidate iteration order
    # non-deterministic (hash randomization), so which member won when a guild
    # had distinct cased/lowercased matches could vary between runs.
    name_opts = [name] if name == name.lower() else [name, name.lower()]

    def _norm(s: str) -> str:
        # NFKC + lower so users typed with combining marks, full-width
        # latin, or other Unicode quirks still match. Plain ``.lower()``
        # alone would miss e.g. "ＡＢＣ" vs "abc".
        return unicodedata.normalize("NFKC", s).casefold()

    for n in name_opts:
        m = discord.utils.get(guild.members, display_name=n) or discord.utils.get(
            guild.members, name=n
        )
        if m:
            return m
        # Manual search (NFKC-folded for Unicode-aware comparison)
        n_norm = _norm(n)
        m = next((m for m in guild.members if _norm(m.display_name) == n_norm), None) or next(
            (m for m in guild.members if _norm(m.name) == n_norm), None
        )
        if m:
            return m
    return None


async def cmd_create_text(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    name: str,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Create a text channel.

    Args:
        guild: The Discord guild to create the channel in
        origin_channel: The channel where the command was issued
        name: The name for the new channel
        args: Additional arguments (optional category name)
        user: The user who triggered the command (for permission checks)
    """
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_channels", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Channels", allowed_mentions=_NO_MENTIONS)
        return

    if not name:
        return

    # Sanitize channel name
    name = sanitize_channel_name(name)
    if not name:
        await origin_channel.send("❌ ชื่อช่องไม่ถูกต้อง", allowed_mentions=_NO_MENTIONS)
        return

    category_name = args[1] if len(args) > 1 else None
    category = discord.utils.get(guild.categories, name=category_name) if category_name else None
    # Surface a clear warning when the operator named a category that
    # doesn't exist instead of silently creating a top-level channel.
    # The user almost always wanted the category to exist, so failing
    # loudly beats a confusing "where did my channel go" support ticket.
    if category_name and category is None:
        await origin_channel.send(
            f"⚠️ ไม่พบ category **{category_name}** — กำลังสร้างช่องไว้ที่ top-level",
            allowed_mentions=_NO_MENTIONS,
        )

    try:
        channel = await guild.create_text_channel(name, category=category)
        logger.info("🛠️ AI Created Text Channel: %s", name)
        await origin_channel.send(
            f"✅ สร้างช่องข้อความ **#{name}** เรียบร้อยแล้ว", allowed_mentions=_NO_MENTIONS
        )

        # Log to audit trail
        if AUDIT_AVAILABLE and log_channel_change is not None:
            await log_channel_change(
                user_id=guild.me.id,  # Bot as actor
                guild_id=guild.id,
                action="create",
                channel_id=channel.id,
                channel_name=name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้างช่อง", allowed_mentions=_NO_MENTIONS)
    except discord.HTTPException as e:
        logger.error("Failed to create text channel: %s", e, exc_info=True)
        await origin_channel.send(
            f"❌ ไม่สามารถสร้างช่องได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
        )


async def cmd_create_voice(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    name: str,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Create a voice channel.

    Args:
        guild: The Discord guild to create the channel in
        origin_channel: The channel where the command was issued
        name: The name for the new channel
        args: Additional arguments (optional category name)
        user: The user who triggered the command (for permission checks)
    """
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_channels", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Channels", allowed_mentions=_NO_MENTIONS)
        return

    if not name:
        return

    # Sanitize channel name
    name = sanitize_channel_name(name)
    if not name:
        await origin_channel.send("❌ ชื่อช่องไม่ถูกต้อง", allowed_mentions=_NO_MENTIONS)
        return

    category_name = args[1] if len(args) > 1 else None
    category = discord.utils.get(guild.categories, name=category_name) if category_name else None
    if category_name and category is None:
        await origin_channel.send(
            f"⚠️ ไม่พบ category **{category_name}** — กำลังสร้างช่องไว้ที่ top-level",
            allowed_mentions=_NO_MENTIONS,
        )

    try:
        channel = await guild.create_voice_channel(name, category=category)
        logger.info("🛠️ AI Created Voice Channel: %s", name)
        await origin_channel.send(
            f"✅ สร้างช่องเสียง **{name}** เรียบร้อยแล้ว", allowed_mentions=_NO_MENTIONS
        )

        # Log to audit trail
        if AUDIT_AVAILABLE and log_channel_change is not None:
            await log_channel_change(
                user_id=guild.me.id,
                guild_id=guild.id,
                action="create_voice",
                channel_id=channel.id,
                channel_name=name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้างช่อง", allowed_mentions=_NO_MENTIONS)
    except discord.HTTPException as e:
        logger.error("Failed to create voice channel: %s", e, exc_info=True)
        await origin_channel.send(
            f"❌ ไม่สามารถสร้างช่องได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
        )


async def cmd_create_category(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    name: str,
    _args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Create a category.

    Args:
        guild: The Discord guild to create the category in
        origin_channel: The channel where the command was issued
        name: The name for the new category
        _args: Unused arguments
        user: The user who triggered the command (for permission checks)
    """
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_channels", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Channels", allowed_mentions=_NO_MENTIONS)
        return

    if not name:
        return

    # Sanitize category name
    name = sanitize_channel_name(name)
    if not name:
        await origin_channel.send("❌ ชื่อ Category ไม่ถูกต้อง", allowed_mentions=_NO_MENTIONS)
        return

    try:
        category = await guild.create_category(name)
        logger.info("🛠️ AI Created Category: %s", name)
        await origin_channel.send(
            f"✅ สร้าง Category **{name}** เรียบร้อยแล้ว", allowed_mentions=_NO_MENTIONS
        )
        # Log to audit trail
        if AUDIT_AVAILABLE and log_channel_change is not None:
            await log_channel_change(
                user_id=guild.me.id,
                guild_id=guild.id,
                action="create_category",
                channel_id=category.id,
                channel_name=name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้าง Category", allowed_mentions=_NO_MENTIONS)
    except discord.HTTPException as e:
        logger.exception("Failed to create category")
        await origin_channel.send(
            f"❌ ไม่สามารถสร้าง Category ได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
        )


async def cmd_delete_channel(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    name: str,
    _args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Delete a channel by name or ID.

    Args:
        guild: The Discord guild containing the channel
        origin_channel: The channel where the command was issued
        name: The name or ID of the channel to delete
        _args: Unused arguments
        user: The user who triggered the command (for permission checks)
    """
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_channels", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Channels", allowed_mentions=_NO_MENTIONS)
        return

    # If the input is purely numeric, prefer ID lookup — it's a more specific
    # signal of intent than a name match (Discord allows numeric channel
    # names, so a string "12345" could match either a channel literally
    # named "12345" or the channel with that snowflake ID; the user almost
    # always means the latter).
    # _safe_int (not isdigit()+int()): a Unicode-"digit" name like "²" is
    # isdigit()==True but int()-unparseable, and would raise here; instead it
    # returns None and falls through to the name match below.
    channel = None
    _cid = _safe_int(name)
    if _cid is not None:
        channel = guild.get_channel(_cid)

    if channel is None:
        matches = [ch for ch in guild.channels if ch.name.lower() == name.lower()]
        if len(matches) > 1:
            # ACTION-ABORTING bail: nothing is deleted. Prefix ❌ (in addition to
            # the ⚠️ warning text) so _TeeChannel.failure() in tool_executor
            # records it and the model receives the failure — NOT the optimistic
            # "Requested deletion …" success (audit py-aicore-tools-3).
            await origin_channel.send(
                f"❌ ⚠️ พบช่องชื่อ **{name}** จำนวน {len(matches)} ห้อง! กรุณาระบุ ID แทนเพื่อความปลอดภัย",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        channel = matches[0] if matches else None

    if channel:
        if channel.id == origin_channel.id:
            await origin_channel.send(
                "❌ ไม่สามารถลบช่องที่กำลังใช้งานอยู่ได้", allowed_mentions=_NO_MENTIONS
            )
            return
        try:
            await channel.delete()
            logger.info("🗑️ AI Deleted Channel: %s", name)
            await origin_channel.send(
                f"✅ ลบช่อง **{name}** เรียบร้อยแล้ว", allowed_mentions=_NO_MENTIONS
            )
        except discord.Forbidden:
            await origin_channel.send(
                f"❌ บอทไม่มีสิทธิ์ลบช่อง **{name}**", allowed_mentions=_NO_MENTIONS
            )
        except discord.HTTPException as e:
            logger.exception("Failed to delete channel")
            await origin_channel.send(
                f"❌ ไม่สามารถลบช่องได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
            )
    else:
        logger.warning("AI tried to delete non-existent channel: %s", name)
        await origin_channel.send(f"❌ ไม่พบช่อง: **{name}**", allowed_mentions=_NO_MENTIONS)


async def cmd_create_role(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Create a role with optional color."""
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_roles", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Roles", allowed_mentions=_NO_MENTIONS)
        return

    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อยศที่ต้องการสร้าง", allowed_mentions=_NO_MENTIONS)
        return

    role_name = args[0].strip()
    if not role_name:
        await origin_channel.send("❌ ชื่อยศไม่สามารถว่างได้", allowed_mentions=_NO_MENTIONS)
        return

    # Sanitize role name
    role_name = sanitize_role_name(role_name)
    if not role_name:
        await origin_channel.send("❌ ชื่อยศไม่ถูกต้อง", allowed_mentions=_NO_MENTIONS)
        return

    color_hex = args[1] if len(args) > 1 else None
    color = discord.Color.default()
    if color_hex:
        try:
            val = color_hex[1:] if color_hex.startswith("#") else color_hex
            int_val = int(val, 16)
            # Discord colors are 24-bit RGB; reject anything outside that
            # range so a 9-digit hex (or worse) can't crash discord.Color.
            if 0 <= int_val <= 0xFFFFFF:
                color = discord.Color(int_val)
            else:
                await origin_channel.send(
                    f"⚠️ ใช้สี default เพราะ hex `{color_hex}` อยู่นอกช่วง 0x000000-0xFFFFFF",
                    allowed_mentions=_NO_MENTIONS,
                )
        except ValueError:
            await origin_channel.send(
                f"⚠️ ใช้สี default เพราะ hex `{color_hex}` ไม่ถูกต้อง", allowed_mentions=_NO_MENTIONS
            )
    try:
        role = await guild.create_role(name=role_name, color=color)
        logger.info("🛠️ AI Created Role: %s", role_name)
        await origin_channel.send(
            f"✅ สร้างยศ **{role_name}** เรียบร้อยแล้ว", allowed_mentions=_NO_MENTIONS
        )

        # Log to audit trail
        if AUDIT_AVAILABLE and log_role_change is not None:
            await log_role_change(
                user_id=guild.me.id,
                guild_id=guild.id,
                action="create",
                role_id=role.id,
                role_name=role_name,
            )
    except discord.Forbidden:
        await origin_channel.send("❌ บอทไม่มีสิทธิ์สร้างยศ", allowed_mentions=_NO_MENTIONS)
    except discord.HTTPException as e:
        logger.exception("Failed to create role")
        await origin_channel.send(
            f"❌ ไม่สามารถสร้างยศได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
        )


async def cmd_delete_role(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Delete a role."""
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_roles", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Roles", allowed_mentions=_NO_MENTIONS)
        return

    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อยศที่ต้องการลบ", allowed_mentions=_NO_MENTIONS)
        return

    role_name = args[0].strip()
    if not role_name:
        await origin_channel.send("❌ ชื่อยศไม่สามารถว่างได้", allowed_mentions=_NO_MENTIONS)
        return

    # If the input is purely numeric, prefer ID lookup — it's a more specific
    # signal of intent than a name match (Discord allows numeric role names, so
    # a string "12345" could match either a role literally named "12345" or the
    # role with that snowflake ID; the user almost always means the latter).
    # Mirrors cmd_delete_channel's ID-first resolution.
    # _safe_int (not isdigit()+int()): a Unicode-"digit" role name falls through
    # to the name match instead of raising ValueError on int().
    role = None
    _rid = _safe_int(role_name)
    if _rid is not None:
        role = guild.get_role(_rid)

    if role is None:
        # Check for duplicate names
        matches = [r for r in guild.roles if r.name.lower() == role_name.lower()]
        if len(matches) > 1:
            # ACTION-ABORTING bail: nothing is deleted. Prefix ❌ so the model
            # gets the failure instead of an optimistic "Requested deletion …"
            # (audit py-aicore-tools-3).
            await origin_channel.send(
                f"❌ ⚠️ พบยศชื่อ **{role_name}** จำนวน {len(matches)} ยศ! กรุณาระบุ ID แทนเพื่อความปลอดภัย",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        role = matches[0] if matches else None

    if role:
        try:
            await role.delete()
            logger.info("🗑️ AI Deleted Role: %s", role_name)
            await origin_channel.send(
                f"✅ ลบยศ **{role_name}** เรียบร้อยแล้ว", allowed_mentions=_NO_MENTIONS
            )
        except discord.Forbidden:
            await origin_channel.send(
                f"❌ บอทไม่มีสิทธิ์ลบยศ **{role_name}**", allowed_mentions=_NO_MENTIONS
            )
        except discord.HTTPException as e:
            logger.exception("Failed to delete role")
            await origin_channel.send(
                f"❌ ไม่สามารถลบยศได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
            )
    else:
        logger.warning("AI tried to delete non-existent role: %s", role_name)
        await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**", allowed_mentions=_NO_MENTIONS)


async def cmd_add_role(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Add a role to a user."""
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_roles", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Roles", allowed_mentions=_NO_MENTIONS)
        return

    if len(args) < 2:
        return
    user_name = args[0].strip()
    role_name = args[1].strip()

    # Resolve the role ID-first, then fall back to a name match with a
    # duplicate-name guard, mirroring cmd_delete_role: Discord allows a numeric
    # role name AND multiple roles sharing a name. ID-first makes the "กรุณาระบุ ID
    # แทน" advice below actually resolve; the guard stops a bare first-match from
    # silently granting the wrong same-named role (the hierarchy check below only
    # blocks roles at/above the bot, not the wrong one below it).
    role = None
    _rid = _safe_int(role_name)
    if _rid is not None:
        role = guild.get_role(_rid)
    if role is None:
        role_matches = [r for r in guild.roles if r.name.lower() == role_name.lower()]
        if len(role_matches) > 1:
            # ACTION-ABORTING bail: no role is added. Prefix ❌ so the model gets the
            # failure instead of an optimistic "Requested adding role …" (audit
            # py-aicore-tools-3).
            await origin_channel.send(
                f"❌ ⚠️ พบยศชื่อ **{role_name}** จำนวน {len(role_matches)} ยศ! กรุณาระบุ ID แทนเพื่อความปลอดภัย",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        role = discord.utils.get(guild.roles, name=role_name) or (
            role_matches[0] if role_matches else None
        )

    member = find_member(guild, user_name)

    # Partial match fallback. If multiple users match, surface the ambiguity
    # to origin_channel instead of silently doing nothing — previously the
    # AI would receive no feedback and falsely report success to the user.
    if not member:
        matches = [
            m
            for m in guild.members
            if user_name.lower() in m.name.lower() or user_name.lower() in m.display_name.lower()
        ]
        if len(matches) == 1:
            member = matches[0]
        elif len(matches) > 1:
            preview = ", ".join(m.display_name for m in matches[:5])
            extra = "..." if len(matches) > 5 else ""
            await origin_channel.send(
                f"❌ ผู้ใช้ **{user_name}** ไม่ชัดเจน — ตรงกับ {len(matches)} คน: {preview}{extra}",
                allowed_mentions=_NO_MENTIONS,
            )
            return

    if role and member:
        # Pre-validation: Check role hierarchy before API call
        if guild.me is None:
            await origin_channel.send(
                "❌ บอทยังไม่พร้อมใช้งาน กรุณาลองใหม่อีกครั้ง", allowed_mentions=_NO_MENTIONS
            )
            return
        bot_top_role = guild.me.top_role
        if role >= bot_top_role:
            await origin_channel.send(
                f"❌ บอทไม่สามารถมอบยศ **{role.name}** ได้ "
                f"(ยศของบอทอยู่ที่ตำแหน่ง {bot_top_role.position}, "
                f"ยศที่จะมอบอยู่ที่ตำแหน่ง {role.position})",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        # Discord also requires the bot's top role to be above the TARGET
        # member's top role for any role-modification op (not just the role
        # being added). Without this check, ``add_roles`` raises 403 at
        # runtime even though our role-vs-bot check above passed. We use
        # ``getattr`` with explicit ints to defend against ``member.top_role``
        # being absent on partial fetches; an unparseable position falls
        # through and the API call's 403 surfaces below as before.
        member_top_pos = getattr(getattr(member, "top_role", None), "position", None)
        bot_top_pos = getattr(bot_top_role, "position", None)
        if (
            isinstance(member_top_pos, int)
            and isinstance(bot_top_pos, int)
            and member_top_pos >= bot_top_pos
        ):
            await origin_channel.send(
                f"❌ ไม่สามารถมอบยศให้ **{member.display_name}** ได้ (ยศของผู้ใช้สูงกว่าหรือเทียบเท่ายศของบอท)",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        try:
            await member.add_roles(role)
            logger.info("➕ AI Added Role %s to %s", role.name, member.display_name)
            await origin_channel.send(
                f"✅ มอบยศ **{role.name}** ให้กับ **{member.display_name}** เรียบร้อยแล้ว",
                allowed_mentions=_NO_MENTIONS,
            )
        except discord.Forbidden:
            await origin_channel.send(
                "❌ บอทไม่มีสิทธิ์มอบยศนี้ (ยศของบอทต้องอยู่สูงกว่ายศที่จะมอบ)", allowed_mentions=_NO_MENTIONS
            )
        except discord.HTTPException as e:
            logger.exception("Failed to add role")
            await origin_channel.send(
                f"❌ ไม่สามารถมอบยศได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
            )
    else:
        if not role:
            await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**", allowed_mentions=_NO_MENTIONS)
        if not member:
            await origin_channel.send(f"❌ ไม่พบผู้ใช้: **{user_name}**", allowed_mentions=_NO_MENTIONS)


async def cmd_remove_role(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Remove a role from a user."""
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_roles", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Roles", allowed_mentions=_NO_MENTIONS)
        return

    if len(args) < 2:
        return
    user_name = args[0].strip()
    role_name = args[1].strip()

    # Resolve the role ID-first, then fall back to a name match with a
    # duplicate-name guard, mirroring cmd_delete_role / cmd_add_role: when two
    # roles share a name a bare first-match could silently strip the wrong
    # same-named role, and ID-first makes the "กรุณาระบุ ID แทน" advice below
    # actually resolve.
    role = None
    _rid = _safe_int(role_name)
    if _rid is not None:
        role = guild.get_role(_rid)
    if role is None:
        role_matches = [r for r in guild.roles if r.name.lower() == role_name.lower()]
        if len(role_matches) > 1:
            # ACTION-ABORTING bail: no role is removed. Prefix ❌ so the model gets
            # the failure instead of an optimistic "Requested removing role …"
            # (audit py-aicore-tools-3).
            await origin_channel.send(
                f"❌ ⚠️ พบยศชื่อ **{role_name}** จำนวน {len(role_matches)} ยศ! กรุณาระบุ ID แทนเพื่อความปลอดภัย",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        role = discord.utils.get(guild.roles, name=role_name) or (
            role_matches[0] if role_matches else None
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
        elif len(matches) > 1:
            # Surface ambiguity instead of silently failing — same UX as
            # cmd_add_role above. Otherwise the AI tool gets a generic
            # "user not found" and may try to create a duplicate operation.
            # ACTION-ABORTING bail: no role is removed. Prefix ❌ so the model
            # gets the failure instead of an optimistic "Requested removing
            # role …" (audit py-aicore-tools-3).
            await origin_channel.send(
                f"❌ ⚠️ พบผู้ใช้ที่ตรงกับ **{user_name}** จำนวน {len(matches)} คน กรุณาระบุให้ชัดเจน",
                allowed_mentions=_NO_MENTIONS,
            )
            return

    if role and member:
        # Pre-validation: Check role hierarchy before API call
        if guild.me is None:
            await origin_channel.send(
                "❌ บอทยังไม่พร้อมใช้งาน กรุณาลองใหม่อีกครั้ง", allowed_mentions=_NO_MENTIONS
            )
            return
        bot_top_role = guild.me.top_role
        if role >= bot_top_role:
            await origin_channel.send(
                f"❌ บอทไม่สามารถลบยศ **{role.name}** ได้ "
                f"(ยศของบอทอยู่ที่ตำแหน่ง {bot_top_role.position}, "
                f"ยศที่จะลบอยู่ที่ตำแหน่ง {role.position})",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        # Same target-vs-bot hierarchy guard as cmd_add_role.
        member_top_pos = getattr(getattr(member, "top_role", None), "position", None)
        bot_top_pos = getattr(bot_top_role, "position", None)
        if (
            isinstance(member_top_pos, int)
            and isinstance(bot_top_pos, int)
            and member_top_pos >= bot_top_pos
        ):
            await origin_channel.send(
                f"❌ ไม่สามารถลบยศจาก **{member.display_name}** ได้ (ยศของผู้ใช้สูงกว่าหรือเทียบเท่ายศของบอท)",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        try:
            await member.remove_roles(role)
            logger.info("➖ AI Removed Role %s from %s", role_name, user_name)
            await origin_channel.send(
                f"✅ ลบยศ **{role.name}** ออกจาก **{member.display_name}** เรียบร้อยแล้ว",
                allowed_mentions=_NO_MENTIONS,
            )
        except discord.Forbidden:
            await origin_channel.send(
                "❌ บอทไม่มีสิทธิ์ลบยศนี้ (ยศของบอทต้องอยู่สูงกว่ายศที่จะลบ)", allowed_mentions=_NO_MENTIONS
            )
        except discord.HTTPException as err:
            logger.error("Failed to remove role: %s", err)
            await origin_channel.send(
                f"❌ ไม่สามารถลบยศได้ {_fmt_http_error(err)}", allowed_mentions=_NO_MENTIONS
            )
    else:
        if not role:
            await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**", allowed_mentions=_NO_MENTIONS)
        if not member:
            await origin_channel.send(f"❌ ไม่พบผู้ใช้: **{user_name}**", allowed_mentions=_NO_MENTIONS)


async def cmd_set_channel_perm(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Set permissions for a channel."""
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_channels", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Channels", allowed_mentions=_NO_MENTIONS)
        return

    if len(args) < 4:
        await origin_channel.send(
            "❌ กรุณาระบุพารามิเตอร์ให้ครบ: ช่อง|เป้าหมาย|สิทธิ์|ค่า", allowed_mentions=_NO_MENTIONS
        )
        return
    channel_name = args[0]
    target_name = args[1]
    # Strip both fields for parity with cmd_set_role_perm (lines 883-884) —
    # tool_executor builds the args list without stripping, so a model-supplied
    # value with surrounding whitespace would otherwise hit a false rejection.
    perm_name = args[2].lower().strip()
    value_str = args[3].lower().strip()
    value = {"true": True, "false": False}.get(value_str)
    if value is None:
        await origin_channel.send(
            "❌ ค่า permission ต้องเป็น 'true' หรือ 'false'", allowed_mentions=_NO_MENTIONS
        )
        return

    # Resolve the target channel ID-first with a duplicate-name guard, mirroring
    # cmd_delete_channel: Discord allows multiple channels sharing a name, so a
    # bare first-match could silently mutate the wrong channel's overwrites
    # (e.g. exposing a private "general" by toggling view_channel on a public one).
    # _safe_int (not isdigit()+int()): a Unicode-"digit" channel name falls
    # through to the name match instead of raising ValueError on int().
    channel = None
    _cid = _safe_int(channel_name)
    if _cid is not None:
        channel = guild.get_channel(_cid)
    if channel is None:
        try:
            same_name = [
                c
                for c in guild.channels
                if (getattr(c, "name", "") or "").lower() == channel_name.lower()
            ]
        except TypeError:
            same_name = []
        if len(same_name) > 1:
            # ACTION-ABORTING bail: no overwrite is set. Prefix ❌ so the model
            # gets the failure instead of an optimistic "Requested setting
            # channel permission …" (audit py-aicore-tools-3).
            await origin_channel.send(
                f"❌ ⚠️ พบช่องชื่อ **{channel_name}** จำนวน {len(same_name)} ห้อง! กรุณาระบุ ID แทนเพื่อความปลอดภัย",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        channel = discord.utils.get(guild.channels, name=channel_name)
    if not channel:
        await origin_channel.send(f"❌ ไม่พบช่อง: **{channel_name}**", allowed_mentions=_NO_MENTIONS)
        return

    target: discord.Role | discord.Member | None = None
    if target_name == "@everyone":
        target = guild.default_role
    else:
        # Resolve the target role ID-first with a duplicate-name guard, mirroring
        # the channel block above and cmd_delete_role / cmd_add_role / cmd_remove_role:
        # Discord allows multiple roles sharing a name, so a bare first-match could
        # silently apply the overwrite to the WRONG same-named role (e.g. exposing a
        # private channel to an unintended group by toggling view_channel), and the
        # "กรุณาระบุ ID แทน" advice the siblings emit was previously unresolvable here.
        # _safe_int (not isdigit()+int()): a Unicode-"digit" role name falls through
        # to the name match instead of raising ValueError on int().
        _tid = _safe_int(target_name)
        if _tid is not None:
            target = guild.get_role(_tid)
        if target is None:
            role_matches = [r for r in guild.roles if r.name.lower() == target_name.lower()]
            if len(role_matches) > 1:
                # ACTION-ABORTING bail: no overwrite is set. Prefix ❌ so the model
                # gets the failure instead of an optimistic "Requested setting
                # channel permission …" (audit py-aicore-tools-3).
                await origin_channel.send(
                    f"❌ ⚠️ พบยศชื่อ **{target_name}** จำนวน {len(role_matches)} ยศ! กรุณาระบุ ID แทนเพื่อความปลอดภัย",
                    allowed_mentions=_NO_MENTIONS,
                )
                return
            # Exact-case first, then the folded match, then a member fallback.
            # Role precedence over member is intentional (a perm overwrite is far
            # more commonly meant for a role) and matches the prior `or` ordering.
            target = (
                discord.utils.get(guild.roles, name=target_name)
                or (role_matches[0] if role_matches else None)
                or find_member(guild, target_name)
            )

    if channel and target:
        overwrite = channel.overwrites_for(target)
        if perm_name == "read_messages":
            perm_name = "view_channel"

        # Security: Only allow permissions in the safe allowlist
        if perm_name in _DANGEROUS_PERMISSIONS:
            await origin_channel.send(
                f"❌ ไม่อนุญาตให้ตั้งค่า **{perm_name}** ผ่าน AI (permission นี้เป็นอันตราย กรุณาตั้งค่าด้วยตนเอง)",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        if perm_name not in _SAFE_PERMISSIONS:
            await origin_channel.send(
                f"❌ Permission **{perm_name}** ไม่อยู่ในรายการที่อนุญาต", allowed_mentions=_NO_MENTIONS
            )
            return

        if hasattr(overwrite, perm_name):
            try:
                setattr(overwrite, perm_name, value)
                await channel.set_permissions(target, overwrite=overwrite)
                logger.info(
                    "🔒 AI Set Channel Perm: %s | %s | %s=%s",
                    channel_name,
                    target_name,
                    perm_name,
                    value,
                )
                await origin_channel.send(
                    f"✅ ตั้งค่า permission **{perm_name}** = **{value}** "
                    f"ให้กับ **{target_name}** ในช่อง **{channel_name}** เรียบร้อยแล้ว",
                    allowed_mentions=_NO_MENTIONS,
                )
            except discord.Forbidden:
                await origin_channel.send(
                    "❌ บอทไม่มีสิทธิ์ตั้งค่า permission", allowed_mentions=_NO_MENTIONS
                )
            except discord.HTTPException as e:
                logger.error("Failed to set channel permission: %s", e, exc_info=True)
                await origin_channel.send(
                    f"❌ ไม่สามารถตั้งค่า permission ได้ {_fmt_http_error(e)}",
                    allowed_mentions=_NO_MENTIONS,
                )
        else:
            await origin_channel.send(
                f"❌ ไม่พบ permission: **{perm_name}**", allowed_mentions=_NO_MENTIONS
            )
    elif not target:
        await origin_channel.send(
            f"❌ ไม่พบเป้าหมาย: **{target_name}**", allowed_mentions=_NO_MENTIONS
        )


async def cmd_set_role_perm(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    user: discord.Member | discord.User | None = None,
) -> None:
    """Set permissions for a role."""
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_roles", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Roles", allowed_mentions=_NO_MENTIONS)
        return

    if len(args) < 3:
        await origin_channel.send(
            "❌ กรุณาระบุพารามิเตอร์ให้ครบ: ยศ|สิทธิ์|ค่า", allowed_mentions=_NO_MENTIONS
        )
        return
    role_name = args[0].strip()
    perm_name = args[1].lower().strip()
    value_str = args[2].lower().strip()

    # Validate value first
    if value_str not in ("true", "false"):
        await origin_channel.send(
            "❌ ค่า permission ต้องเป็น 'true' หรือ 'false'", allowed_mentions=_NO_MENTIONS
        )
        return

    value = value_str == "true"

    # Try exact match first; fall back to case-insensitive match if
    # nothing found. ``cmd_delete_role`` already uses this pattern, so
    # mirror it here for consistency — without the fallback, a user
    # asking for ``Admin`` couldn't set perms on a role literally named
    # ``admin``.
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role_name_lower = role_name.lower()
        role = next(
            (r for r in guild.roles if r.name.lower() == role_name_lower),
            None,
        )
    if not role:
        await origin_channel.send(f"❌ ไม่พบยศ: **{role_name}**", allowed_mentions=_NO_MENTIONS)
        return

    perms = role.permissions

    # Security: Only allow permissions in the safe allowlist
    if perm_name in _DANGEROUS_PERMISSIONS:
        await origin_channel.send(
            f"❌ ไม่อนุญาตให้ตั้งค่า **{perm_name}** ผ่าน AI (permission นี้เป็นอันตราย กรุณาตั้งค่าด้วยตนเอง)",
            allowed_mentions=_NO_MENTIONS,
        )
        return
    if perm_name not in _SAFE_PERMISSIONS:
        await origin_channel.send(
            f"❌ Permission **{perm_name}** ไม่อยู่ในรายการที่อนุญาต", allowed_mentions=_NO_MENTIONS
        )
        return

    if hasattr(perms, perm_name):
        # Pre-validate role hierarchy. cmd_add_role / cmd_remove_role already
        # do this; without the same check here, role.edit() raises Forbidden
        # at the API and the user just sees a generic error. Surface the
        # specific cause so they understand WHY it was rejected.
        if guild.me is None:
            await origin_channel.send(
                "❌ บอทยังไม่พร้อมใช้งาน กรุณาลองใหม่อีกครั้ง", allowed_mentions=_NO_MENTIONS
            )
            return
        if role >= guild.me.top_role:
            await origin_channel.send(
                f"❌ บอทไม่สามารถแก้ไขยศ **{role.name}** ได้ "
                f"(ยศของบอทอยู่ที่ตำแหน่ง {guild.me.top_role.position}, "
                f"ยศเป้าหมายอยู่ที่ตำแหน่ง {role.position})",
                allowed_mentions=_NO_MENTIONS,
            )
            return
        try:
            setattr(perms, perm_name, value)
            await role.edit(permissions=perms)
            logger.info("🛡️ AI Set Role Perm: %s | %s=%s", role_name, perm_name, value)
            await origin_channel.send(
                f"✅ ตั้งค่า permission **{perm_name}** = **{value}** "
                f"ให้กับยศ **{role_name}** เรียบร้อยแล้ว",
                allowed_mentions=_NO_MENTIONS,
            )
        except discord.Forbidden:
            await origin_channel.send("❌ บอทไม่มีสิทธิ์แก้ไขยศนี้", allowed_mentions=_NO_MENTIONS)
        except discord.HTTPException as e:
            logger.error("Failed to set role permission: %s", e, exc_info=True)
            await origin_channel.send(
                f"❌ ไม่สามารถตั้งค่า permission ได้ {_fmt_http_error(e)}", allowed_mentions=_NO_MENTIONS
            )
    else:
        await origin_channel.send(
            f"❌ ไม่พบ permission: **{perm_name}**", allowed_mentions=_NO_MENTIONS
        )


async def cmd_list_channels(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    _args: list[str],
    _user: discord.Member | discord.User | None = None,
) -> None:
    """List text channels, filtered by caller's view permission.

    Without the filter, the AI tool path leaked private/staff channel
    names to any non-staff member who asked.
    """
    if isinstance(_user, discord.Member):
        channels = [
            f"#{ch.name} (ID: {ch.id})"
            for ch in guild.text_channels
            if ch.permissions_for(_user).view_channel
        ]
    else:
        # Fail CLOSED when we can't resolve the caller to a Member — the old
        # else dumped EVERY channel name unfiltered (private/staff included),
        # the inverse of cmd_read_channel's fail-closed handling.
        await origin_channel.send(
            "⛔ ไม่สามารถระบุสิทธิ์ผู้เรียกได้ จึงไม่แสดงรายชื่อช่อง",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return
    await send_long_message(origin_channel, "**📜 Server Text Channels:**\n", channels)


async def cmd_list_roles(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    _args: list[str],
    _user: discord.Member | discord.User | None = None,
) -> None:
    """List all roles.

    Intentionally unguarded by a per-caller check (unlike cmd_list_channels /
    cmd_list_members): a role's name and ID are non-sensitive and already
    visible to every member in Discord's own UI, so there's nothing to leak.
    The live AI-tool path is still administrator-gated upstream
    (tool_executor). Don't add a Member/manage_guild gate here — the sibling
    listing commands gate because channel visibility and the full member
    roster are privacy-relevant; roles are not.
    """
    roles = [f"{r.name} (ID: {r.id})" for r in reversed(guild.roles) if r.name != "@everyone"]
    await send_long_message(origin_channel, "**🎭 Server Roles:**\n", roles)


async def cmd_list_members(
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    _user: discord.Member | discord.User | None = None,
) -> None:
    """List members with optional query and limit.

    Gated to callers with ``manage_guild`` so the AI tool path can't be
    used by a regular member to enumerate the entire roster (which, in
    a large guild, is a privacy concern even though Discord's UI also
    exposes it). Channel-level perms aren't enough here because member
    visibility isn't scoped per-channel.
    """
    if not isinstance(_user, discord.Member) or not _user.guild_permissions.manage_guild:
        await origin_channel.send(
            "❌ คำสั่งนี้ต้องการสิทธิ์ Manage Server เท่านั้น", allowed_mentions=_NO_MENTIONS
        )
        return

    limit = 50  # Default limit
    query = None  # Default no query

    if args:
        # _safe_int (not isdigit()+int()): args[0] is AI-controlled and uncapped,
        # so a Unicode-"digit" or >4300-digit token would raise on int(). A
        # non-parseable leading token falls through to the query branch instead.
        _lim = _safe_int(args[0], max_digits=9)
        if _lim is not None:
            limit = _lim
            # Validate limit
            if limit < 1:
                limit = 1
            elif limit > 200:
                limit = 200  # Max limit to prevent huge responses
            if len(args) > 1 and args[1].strip():
                query = args[1].strip().lower()
        elif args[0].strip():
            # No leading numeric limit: a lone token is the search query.
            query = args[0].strip().lower()

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
    guild: discord.Guild,
    origin_channel: discord.TextChannel,
    _name: str | None,
    args: list[str],
    _user: discord.Member | discord.User | None = None,
) -> None:
    """Get detailed info about a user.

    Gated to callers with ``manage_guild`` — the output includes presence
    status, join date, and full role list, which is more than the AI
    tool path should be handing out to arbitrary guild members.
    """
    if not isinstance(_user, discord.Member) or not _user.guild_permissions.manage_guild:
        await origin_channel.send(
            "❌ คำสั่งนี้ต้องการสิทธิ์ Manage Server เท่านั้น", allowed_mentions=_NO_MENTIONS
        )
        return

    if not args or len(args) < 1:
        await origin_channel.send(
            "❌ กรุณาระบุชื่อผู้ใช้หรือ ID ที่ต้องการค้นหา", allowed_mentions=_NO_MENTIONS
        )
        return
    target = args[0].strip()
    if not target:
        await origin_channel.send("❌ ชื่อผู้ใช้ไม่สามารถว่างได้", allowed_mentions=_NO_MENTIONS)
        return
    # _safe_int (not isdigit()+int()): a Unicode-"digit" target falls through to
    # the name lookup instead of raising ValueError on int().
    member = None
    _uid = _safe_int(target)
    if _uid is not None:
        # Try cached members first; if not cached (members intent off,
        # large guild, or member only fetched on join) fall back to
        # ``fetch_member``. Without the fetch, lookups by ID fail
        # silently for users the bot has never seen send a message.
        member = guild.get_member(_uid)
        if member is None:
            try:
                member = await guild.fetch_member(_uid)
            except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                member = None
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
            # Route through send_long_message so display_name/name pass through
            # _escape_for_code_block — otherwise a member whose display name
            # contains ``` could break out of the fenced block and inject
            # markdown/links (the single-user path below already escapes).
            lines = [f"- {m.display_name} (@{m.name}) [ID: {m.id}]" for m in matches[:10]]
            if len(matches) > 10:
                lines.append(f"...and {len(matches) - 10} more.")
            await send_long_message(origin_channel, "**🔍 Found multiple users:**\n", lines)
            return

    if member:
        roles = ", ".join([r.name for r in member.roles if r.name != "@everyone"])
        # Note: no "Status" line — the bot doesn't enable the privileged
        # presences intent (bot.py uses Intents.default() + message_content +
        # members), so member.status is ALWAYS Status.offline and would
        # mislead every lookup. Re-add it only if presences is enabled.
        # A member with very many roles can push the info block past Discord's
        # 2000-char limit. Route through send_long_message (chunks to <1900,
        # hard-wraps over-long lines, disables mentions) instead of a single
        # fenced send that would 400 at Discord.
        info_lines = [
            f"Name: {member.name}",
            f"Display Name: {member.display_name}",
            f"ID: {member.id}",
            f"Joined: {member.joined_at.strftime('%Y-%m-%d') if member.joined_at else 'Unknown'}",
            f"Roles: {roles}",
        ]
        await send_long_message(origin_channel, "**👤 User Info:**\n", info_lines)
    else:
        await origin_channel.send(f"❌ ไม่พบผู้ใช้: {target}", allowed_mentions=_NO_MENTIONS)


async def cmd_edit_message(_guild, origin_channel, _name, args, user=None):
    """Edit a message owned by the bot."""
    # Require manage_messages: cmd_edit_message can edit any bot-owned or
    # bot-controlled webhook message in the channel, so it needs the same
    # permission Discord requires for editing/managing messages.
    if user is not None and not getattr(
        getattr(user, "guild_permissions", None), "manage_messages", False
    ):
        await origin_channel.send("❌ คุณไม่มีสิทธิ์ Manage Messages", allowed_mentions=_NO_MENTIONS)
        return

    if len(args) < 2:
        await origin_channel.send(
            "❌ กรุณาระบุพารามิเตอร์ให้ครบ: message_id | new_content", allowed_mentions=_NO_MENTIONS
        )
        return
    raw_msg_id = args[0].strip()
    # _safe_int (not isdigit()+int()): a Unicode-"digit" id is isdigit()==True but
    # int()-unparseable; _safe_int yields None so the guard below rejects it.
    msg_id = _safe_int(raw_msg_id)
    if msg_id is None:
        await origin_channel.send("❌ Message ID ต้องเป็นตัวเลขเท่านั้น", allowed_mentions=_NO_MENTIONS)
        return
    new_content = args[1].strip()
    if not new_content:
        await origin_channel.send("❌ เนื้อหาใหม่ไม่สามารถว่างได้", allowed_mentions=_NO_MENTIONS)
        return

    # `origin_channel.guild` is None in DMs — bail before dereferencing it.
    guild = getattr(origin_channel, "guild", None)
    if guild is None:
        await origin_channel.send("❌ คำสั่งนี้ใช้ได้เฉพาะใน server เท่านั้น", allowed_mentions=_NO_MENTIONS)
        return

    try:
        msg = await origin_channel.fetch_message(msg_id)
        bot = guild.me
        if bot is None:
            await origin_channel.send(
                "❌ ไม่พบ bot member ใน server นี้", allowed_mentions=_NO_MENTIONS
            )
            return
        if msg.author == bot:
            await msg.edit(content=new_content)
        elif msg.webhook_id:
            webhooks = await origin_channel.webhooks()
            webhook = next((w for w in webhooks if w.id == msg.webhook_id), None)
            if webhook and webhook.user and webhook.user.id == bot.id:  # Check bot ID
                await webhook.edit_message(msg_id, content=new_content)
            else:
                await origin_channel.send(
                    "❌ แก้ไขไม่ได้: Webhook นี้ไม่ใช่ของบอท", allowed_mentions=_NO_MENTIONS
                )
        else:
            await origin_channel.send(
                "❌ แก้ไขไม่ได้: ข้อความไม่ใช่ของบอท", allowed_mentions=_NO_MENTIONS
            )
    except (discord.NotFound, discord.HTTPException) as err:
        # `discord.HTTPException.__str__` can include the raw API response
        # body. Use the shared formatter (which strips internal metadata)
        # for parity with the rest of the file.
        await origin_channel.send(_fmt_http_error(err), allowed_mentions=_NO_MENTIONS)


async def cmd_read_channel(guild, origin_channel, _name, args, user=None):
    """Read the last N messages from a channel."""
    if not args or len(args) < 1:
        await origin_channel.send("❌ กรุณาระบุชื่อช่องที่ต้องการอ่าน", allowed_mentions=_NO_MENTIONS)
        return
    target_name = args[0].strip()
    if not target_name:
        await origin_channel.send("❌ ชื่อช่องไม่สามารถว่างได้", allowed_mentions=_NO_MENTIONS)
        return
    # `args[1]` (limit) is fully model/AI-controlled and is NOT length-clamped
    # by the dispatchers (only args[0]=name gets the len>100 check). Parse via
    # _safe_int so neither a >4300-ASCII-digit token NOR a Unicode-"digit"
    # token (isdigit()==True but int()-unparseable, e.g. "²²²") can raise — both
    # fall back to the default. max_digits=9 short-circuits absurd lengths; the
    # value is clamped to 1..100 just below anyway.
    _limit = _safe_int(args[1], max_digits=9) if len(args) > 1 else None
    limit = _limit if _limit is not None else 10
    # Validate limit
    if limit < 1 or limit > 100:
        limit = 10  # Default to 10 if invalid

    # Resolve ID-FIRST (then name fallback) to match the executor's read_channel
    # gate (tools/tool_executor.py), which validates the caller's permission on
    # the ID-resolved channel and passes that ID through here. Resolving name-first
    # here diverged from the gate: a channel literally NAMED with another channel's
    # snowflake string could make this handler read a DIFFERENT channel than the
    # gate validated (audit py-aicore-tools-2). The in-handler permission re-check
    # below still fails closed on whatever resolves, but aligning the order removes
    # the gate/action mismatch entirely. _safe_int (not isdigit()+int()) so a
    # Unicode-digit name like "²²²" falls through to the name match instead of
    # raising; max_digits=20 bounds it to the snowflake range like the gate does.
    target_channel = None
    _cid = _safe_int(target_name, max_digits=20)
    if _cid is not None:
        target_channel = guild.get_channel(_cid)
    if not target_channel:
        target_channel = discord.utils.get(guild.text_channels, name=target_name)

    if target_channel:
        # Privacy: only let the user read messages from a channel they
        # themselves can read. Without this, an admin could ask the bot to
        # echo private channel contents back into a public channel.
        if user is not None:
            try:
                # Require BOTH view (.read_messages) AND scrollback
                # (.read_message_history): a user denied history but granted
                # view could otherwise have the bot echo denied backlog.
                _perms = target_channel.permissions_for(user)
                if not (_perms.read_messages and _perms.read_message_history):
                    await origin_channel.send("❌ คุณไม่มีสิทธิ์อ่านห้องนั้น", allowed_mentions=_NO_MENTIONS)
                    return
            except (AttributeError, TypeError):
                # If we can't compute permissions (e.g. user is a User not a
                # Member), refuse rather than risk leaking.
                await origin_channel.send(
                    "❌ ไม่สามารถตรวจสอบสิทธิ์ของคุณได้", allowed_mentions=_NO_MENTIONS
                )
                return
        try:
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
        except discord.Forbidden:
            await origin_channel.send(
                f"❌ บอทไม่มีสิทธิ์อ่านช่อง **{target_channel.name}**", allowed_mentions=_NO_MENTIONS
            )
    else:
        await origin_channel.send(f"❌ ไม่พบช่อง: {target_name}", allowed_mentions=_NO_MENTIONS)


def _escape_for_code_block(s: str) -> str:
    """Neutralise triple-backticks in user-provided content so it can't
    break out of the surrounding ``` code block. Replaces with a similar-
    looking char (zero-width-space-separated) to preserve readability."""
    return s.replace("```", "`\u200b`\u200b`")


async def send_long_message(channel, header, lines):
    """Send a message that might exceed Discord's character limit.

    Header + lines may include user-controlled content (channel/role names);
    escape any ``` so an attacker can't break out of the wrapping code
    block to inject markdown / mentions / @everyone.
    """
    safe_header = _escape_for_code_block(header)
    # Hard-wrap any single line longer than the chunk budget FIRST — the
    # accumulator below only splits BETWEEN lines, so one ~2000-char history
    # line (cmd_read_channel renders each message as one line) previously
    # produced a >2000-char send that 400s at Discord.
    safe_lines = []
    for raw_line in (_escape_for_code_block(line) for line in lines):
        if len(raw_line) > 1800:
            safe_lines.extend(raw_line[i : i + 1800] for i in range(0, len(raw_line), 1800))
        else:
            safe_lines.append(raw_line)
    current_chunk = safe_header
    for line in safe_lines:
        if len(current_chunk) + len(line) + 5 > 1900:
            await channel.send(
                f"```\n{current_chunk}\n```",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        await channel.send(
            f"```\n{current_chunk}\n```",
            allowed_mentions=discord.AllowedMentions.none(),
        )


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
