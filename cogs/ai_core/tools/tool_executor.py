"""
Tool Executor Module.
Handles execution of Gemini AI function calls and server commands.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast

import discord
from discord.ext import commands

from ..commands.server_commands import (
    COMMAND_HANDLERS,
    cmd_add_role,
    cmd_create_category,
    cmd_create_role,
    cmd_create_text,
    cmd_create_voice,
    cmd_delete_channel,
    cmd_delete_role,
    cmd_get_user_info,
    cmd_list_channels,
    cmd_list_members,
    cmd_list_roles,
    cmd_read_channel,
    cmd_remove_role,
    cmd_set_channel_perm,
    cmd_set_role_perm,
)
from ..data import SERVER_AVATARS
from ..data.constants import MAX_CHANNEL_NAME_LENGTH
from ..memory.rag import rag_system
from ..response.webhook_cache import (
    get_cached_webhook,
    invalidate_webhook_cache,
    set_cached_webhook,
)
from ..sanitization import screen_memory_content

logger = logging.getLogger(__name__)

# Safety cap on the number of chunks ``_safe_split_message`` will emit
# before bailing out, even if the input is pathologically long. Prevents
# unbounded loops on adversarial or corrupted text.
_MAX_CHUNKS = 50

# Prefixes the cmd_* handlers use for a FAILED outcome (no permission, bot
# Forbidden, role hierarchy, not-found, duplicate-name bail, …). Their success
# path uses ``✅`` / ``🗑️``; an ambiguity warning uses ``⚠️`` which we treat as
# non-fatal (the action usually still proceeds). Kept in sync with the Thai
# status strings in ``commands/server_commands.py``.
_FAILURE_PREFIXES = ("❌", "⛔")


class _TeeChannel:
    """Wrap a real Discord channel, forwarding ``send`` to it while ALSO
    recording the text. Used by the mutation branches of ``execute_tool_call``
    so the model's returned string can reflect what the handler actually did
    (e.g. a ``❌ บอทไม่มีสิทธิ์`` Forbidden), instead of a blanket
    "Requested …" success regardless of outcome (audit py-aicore-tools-3).

    The status is STILL posted to the real channel (the user keeps their
    confirmation/error message); we only additionally capture it. Every other
    attribute delegates to the real channel, mirroring ``_CaptureChannel`` in
    ``api/ai_tools_ipc.py``."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self._sent: list[str] = []

    async def send(self, content: str = "", **kwargs: Any) -> Any:
        if content:
            self._sent.append(str(content))
        return await self._real.send(content, **kwargs)

    def failure(self) -> str | None:
        """Return the first captured failure-shaped status line, else None."""
        for line in self._sent:
            if line.startswith(_FAILURE_PREFIXES):
                return line
        return None

    def __getattr__(self, name: str) -> Any:
        # Reached only for attributes not set on the instance (.guild, .id,
        # .permissions_for, …) — delegate them to the real channel.
        return getattr(self._real, name)


def _mutation_outcome(tee: _TeeChannel, success_msg: str) -> str:
    """Pick the string returned to the model for a mutation tool.

    If the handler posted a failure-shaped status (``❌``/``⛔``), surface THAT to
    the model so it doesn't report a false success; otherwise return the
    optimistic ``success_msg``. When the handler posts nothing (e.g. it is mocked
    in unit tests), the optimistic message is returned unchanged."""
    failed = tee.failure()
    return failed if failed is not None else success_msg


def _safe_split_message(text: str, limit: int = 2000) -> list[str]:
    """Split a message into chunks without breaking mid-line or mid-Unicode.

    Args:
        text: Message text to split
        limit: Maximum chunk size

    Returns:
        List of message chunks
    """
    if limit <= 0:
        limit = 2000
    chunks: list[str] = []
    while text and len(chunks) < _MAX_CHUNKS:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at newline
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            # Try to split at space
            split_at = text.rfind(" ", 0, limit)
        if split_at <= 0:
            # Hard split at limit, but ensure we don't break a surrogate pair
            split_at = limit
            # Back up if we're in the middle of a surrogate pair
            while (
                split_at > 0 and text[split_at - 1] >= "\ud800" and text[split_at - 1] <= "\udbff"
            ):
                split_at -= 1
            if split_at <= 0:
                split_at = limit  # Fallback: force forward progress
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text and len(chunks) >= _MAX_CHUNKS:
        chunks.append(text[:limit])  # Append truncated remainder
    return chunks


async def _send_plain_fallback(channel: Any, name: str, message: str) -> Any:
    """Plain-text fallback send that honors Discord's 2000-char limit.

    Every fallback path previously sent ``**name**: message`` as ONE call —
    a long character message (or the prefix pushing a ~2000-char one over)
    400'd, and the surrounding except handler re-tried the same oversized
    send. Returns the last sent message (mirrors send_as_webhook's contract).
    """
    # ``name`` is AI-controlled (parsed from {{Name}} markers) with no upstream
    # length clamp. A pathologically long name would make len(prefix) >= 2000,
    # driving the per-chunk limit <= 0 — which _safe_split_message resets to
    # 2000 — so chunk0 (prefix + a full 2000-char chunk) would blow past
    # Discord's 2000-char body limit and 400. Clamp the name (Discord usernames
    # cap near 80 anyway) and floor the per-chunk limit.
    name = name[:80]
    prefix = f"**{name}**: "
    chunk_limit = max(256, 2000 - len(prefix))
    last = None
    for i, chunk in enumerate(_safe_split_message(message, chunk_limit)):
        last = await channel.send(
            (prefix if i == 0 else "") + chunk,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    return last


async def execute_tool_call(
    _bot: commands.Bot,
    origin_channel: discord.TextChannel,
    user: discord.Member | discord.User,
    tool_call: Any,
) -> str:
    """Execute a function call from Gemini.

    Args:
        _bot: The Discord bot instance (unused)
        origin_channel: The channel where the command was issued
        user: The user who triggered the command
        tool_call: The tool call object from Gemini

    Returns:
        String describing the result of the tool call
    """
    fname = tool_call.name
    # Anthropic ``tool_use`` blocks expose arguments on ``.input``; the legacy
    # Gemini function-call objects (and the test doubles) use ``.args``. Prefer
    # a dict-valued ``.input`` (Anthropic), else fall back to ``.args`` so this
    # dispatcher works for BOTH backends if/when Claude tool-use is wired into
    # the turn loop — without reading ``.input`` a Claude ToolUseBlock would
    # always see ``args == {}`` and bounce on the per-field "missing argument"
    # guards. The ``isinstance(dict)`` checks matter: a bare MagicMock
    # auto-creates a truthy ``.input`` that isn't real argument data, and a
    # tool_call with no inputs can arrive with the attribute absent/None.
    raw_args = getattr(tool_call, "input", None)
    if not isinstance(raw_args, dict):
        raw_args = getattr(tool_call, "args", None)
    args = raw_args if isinstance(raw_args, dict) else {}

    guild = origin_channel.guild

    # Input validation helper
    def validate_name(
        name: str | None, max_length: int = MAX_CHANNEL_NAME_LENGTH
    ) -> tuple[bool, str]:
        """Validate channel/category name from AI input.

        Args:
            name: The name to validate
            max_length: Maximum allowed length (default: MAX_CHANNEL_NAME_LENGTH)

        Returns:
            Tuple of (is_valid, cleaned_name_or_error_message)
        """
        if not name:
            return False, "❌ Name is required"
        name = str(name).strip()
        if len(name) > max_length:
            return False, f"❌ Name too long (max {max_length} chars)"
        if len(name) < 1:
            return False, "❌ Name cannot be empty"
        return True, name

    # Permission tiers. Mutating operations require administrator (creating
    # channels, deleting roles, granting permissions, etc.). Read-only tools
    # require only basic membership in the guild — they can't change server
    # state and gating them behind administrator made the AI unusable for
    # any non-admin user, which is over-restrictive.
    #
    # ``remember`` writes to the per-channel RAG store and is intentionally in
    # NEITHER tier — so on THIS path it fails CLOSED for non-admins: it is absent
    # from _READ_ONLY_TOOLS and _MANAGE_GUILD_TOOLS, so the gate at line ~209
    # returns "requires admin privileges" for any non-admin caller. (Gating it
    # behind admin here stops one member from poisoning every member's future AI
    # replies with planted "facts" via this executor path.) NOTE: this executor
    # branch is NOT the primary entry point on the default ``cli`` backend — the
    # model's ``remember`` call actually flows through
    # ``api/ai_tools_ipc._dispatch_memory``, which is user-scoped by ``ctx.user_id``
    # (no admin gate) and runs the SAME shared memory screen (sanitization.py)
    # before persisting. Both paths share that screen; they differ only in who may
    # invoke remember.
    #
    # ``list_members`` and ``get_user_info`` are intentionally NOT here either:
    # their handlers (cmd_list_members / cmd_get_user_info) require
    # ``manage_guild`` and fail CLOSED. Leaving them in this set let any
    # member pass the executor gate, so the executor returned a success-shaped
    # string ("Listed members" / "Requested info for ...") to the model while
    # the handler actually denied the request — telling the model the lookup
    # succeeded. They're gated on ``manage_guild`` below so the executor's
    # return value matches the handler outcome.
    _READ_ONLY_TOOLS = {
        "list_channels",
        "list_roles",
        "read_channel",
    }
    # Tools whose handlers require ``manage_guild`` and fail CLOSED. Mirror
    # that tier at the executor so a member without ``manage_guild`` gets a
    # denial string (not a false success) returned to the model.
    _MANAGE_GUILD_TOOLS = {
        "list_members",
        "get_user_info",
    }
    if not hasattr(user, "guild_permissions"):
        return f"⛔ Permission denied: User {getattr(user, 'display_name', 'Unknown')} has no guild membership."
    is_admin = user.guild_permissions.administrator
    is_read_only = fname in _READ_ONLY_TOOLS
    is_manage_guild_tool = fname in _MANAGE_GUILD_TOOLS
    if not is_admin and not is_read_only and not is_manage_guild_tool:
        return (
            f"⛔ Permission denied: User {getattr(user, 'display_name', 'Unknown')} "
            f"is not an Admin (tool '{fname}' requires admin privileges)."
        )
    # ``list_members`` / ``get_user_info`` need ``manage_guild`` (their handlers
    # fail CLOSED on it). Gate here so a member without ``manage_guild`` gets a
    # denial string instead of the handler's success-shaped return reaching the
    # model. Admins resolve to Permissions.all(), so they pass this too.
    if is_manage_guild_tool and not user.guild_permissions.manage_guild:
        return "⛔ Permission denied: requires manage_guild permission."

    # Fine-grained mutation gating: even an Administrator-tagged caller
    # should not invoke channel/role mutation tools without the matching
    # specific guild permission. Belt-and-braces against scenarios where
    # `is_admin` is True via a derived role flag but the user's *intent*
    # is constrained by missing manage_channels / manage_roles bits.
    _CHANNEL_MUTATION_TOOLS = {
        "create_text_channel",
        "create_voice_channel",
        "create_category",
        "delete_channel",
        "set_channel_permission",
    }
    _ROLE_MUTATION_TOOLS = {
        "create_role",
        "delete_role",
        "add_role",
        "remove_role",
        "set_role_permission",
    }
    # NOTE: no ``or is_admin`` here — non-admins already returned above, so
    # including it made both checks tautologically dead (the comment above
    # promises the OPPOSITE: that even an admin-tagged caller needs the
    # specific bit). For true administrators discord.py resolves
    # guild_permissions to Permissions.all() anyway, so this only bites
    # callers whose admin flag came from a derived/partial source.
    if fname in _CHANNEL_MUTATION_TOOLS and not user.guild_permissions.manage_channels:
        return "⛔ Permission denied: requires manage_channels permission."
    if fname in _ROLE_MUTATION_TOOLS and not user.guild_permissions.manage_roles:
        return "⛔ Permission denied: requires manage_roles permission."

    try:
        # Pass ``user=user`` through to every cmd_* so the per-command
        # permission check inside ``server_commands`` re-validates against
        # the actual caller. Previously these calls passed no user, leaving
        # the cmd_* ``if user is not None and not perm`` guard a no-op and
        # the protection relied entirely on the top-of-function admin/role
        # gating above. Defense-in-depth.
        # Mutation tools post their own ✅/❌/⚠️ status to the channel and return
        # None. Run each against a ``_TeeChannel`` so a handler FAILURE (Forbidden,
        # role hierarchy, not-found, duplicate-name bail) is surfaced to the model
        # via ``_mutation_outcome`` instead of an unconditional "Requested …"
        # success (audit py-aicore-tools-3). The status is still posted to chat.
        if fname == "create_text_channel":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            tee = _TeeChannel(origin_channel)
            await cmd_create_text(
                guild,
                cast(discord.TextChannel, tee),
                result,
                [result, args.get("category", "")],
                user=user,
            )
            return _mutation_outcome(tee, f"Requested creation of text channel '{result}'")

        elif fname == "create_voice_channel":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            tee = _TeeChannel(origin_channel)
            await cmd_create_voice(
                guild,
                cast(discord.TextChannel, tee),
                result,
                [result, args.get("category", "")],
                user=user,
            )
            return _mutation_outcome(tee, f"Requested creation of voice channel '{result}'")

        elif fname == "create_category":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            tee = _TeeChannel(origin_channel)
            await cmd_create_category(guild, cast(discord.TextChannel, tee), result, [], user=user)
            return _mutation_outcome(tee, f"Requested creation of category '{result}'")

        elif fname == "delete_channel":
            valid, result = validate_name(args.get("name_or_id"))
            if not valid:
                return result
            tee = _TeeChannel(origin_channel)
            await cmd_delete_channel(guild, cast(discord.TextChannel, tee), result, [], user=user)
            return _mutation_outcome(tee, f"Requested deletion of channel '{result}'")

        elif fname == "create_role":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            cmd_args = [result]
            # ``color_hex`` is model-controlled with no type coercion; a
            # non-string value would later hit ``color_hex.startswith("#")``
            # in cmd_create_role and raise AttributeError, aborting creation.
            # Guard with isinstance like the sibling branches so a non-string
            # falls through to the default color instead.
            ch = args.get("color_hex")
            if isinstance(ch, str) and ch.strip():
                cmd_args.append(ch)
            tee = _TeeChannel(origin_channel)
            await cmd_create_role(guild, cast(discord.TextChannel, tee), None, cmd_args, user=user)
            return _mutation_outcome(tee, f"Requested creation of role '{result}'")

        elif fname == "delete_role":
            valid, result = validate_name(args.get("name_or_id"))
            if not valid:
                return result
            tee = _TeeChannel(origin_channel)
            await cmd_delete_role(guild, cast(discord.TextChannel, tee), None, [result], user=user)
            return _mutation_outcome(tee, f"Requested deletion of role '{result}'")

        elif fname == "add_role":
            user_name = args.get("user_name")
            role_name = args.get("role_name")
            # ``args`` is model-controlled with no per-field coercion, so a
            # non-string here would later hit ``.strip()`` in the command and
            # raise an opaque AttributeError. Guard like the read branches.
            if (
                not isinstance(user_name, str)
                or not user_name.strip()
                or not isinstance(role_name, str)
                or not role_name.strip()
            ):
                return "❌ add_role requires both user_name and role_name as non-empty strings"
            tee = _TeeChannel(origin_channel)
            await cmd_add_role(
                guild, cast(discord.TextChannel, tee), None, [user_name, role_name], user=user
            )
            return _mutation_outcome(tee, f"Requested adding role '{role_name}' to '{user_name}'")

        elif fname == "remove_role":
            user_name = args.get("user_name")
            role_name = args.get("role_name")
            # Same isinstance guard as add_role: a non-string user_name/role_name
            # would otherwise surface as an opaque AttributeError downstream.
            if (
                not isinstance(user_name, str)
                or not user_name.strip()
                or not isinstance(role_name, str)
                or not role_name.strip()
            ):
                return "❌ remove_role requires both user_name and role_name as non-empty strings"
            tee = _TeeChannel(origin_channel)
            await cmd_remove_role(
                guild, cast(discord.TextChannel, tee), None, [user_name, role_name], user=user
            )
            return _mutation_outcome(
                tee, f"Requested removing role '{role_name}' from '{user_name}'"
            )

        elif fname == "set_channel_permission":
            channel_name = args.get("channel_name")
            target_name = args.get("target_name")
            permission = args.get("permission")
            value = args.get("value")
            # The string fields are passed straight to ``.strip()`` downstream;
            # isinstance-guard them like the read branches so a non-string gives
            # a clear message instead of an opaque AttributeError. ``value`` keeps
            # its str() coercion below and only needs a presence check.
            if (
                not isinstance(channel_name, str)
                or not channel_name.strip()
                or not isinstance(target_name, str)
                or not target_name.strip()
                or not isinstance(permission, str)
                or not permission.strip()
                or value is None
            ):
                return (
                    "Missing/invalid argument for set_channel_permission "
                    "(need channel_name, target_name, permission as non-empty "
                    "strings and value)."
                )
            tee = _TeeChannel(origin_channel)
            await cmd_set_channel_perm(
                guild,
                cast(discord.TextChannel, tee),
                None,
                [channel_name, target_name, permission, str(value)],
                user=user,
            )
            return _mutation_outcome(
                tee, f"Requested setting channel permission for '{channel_name}'"
            )

        elif fname == "set_role_permission":
            role_name = args.get("role_name")
            permission = args.get("permission")
            value = args.get("value")
            # isinstance-guard the string fields (passed to ``.strip()`` later);
            # ``value`` keeps its str() coercion below and only needs presence.
            if (
                not isinstance(role_name, str)
                or not role_name.strip()
                or not isinstance(permission, str)
                or not permission.strip()
                or value is None
            ):
                return (
                    "Missing/invalid argument for set_role_permission "
                    "(need role_name, permission as non-empty strings and value)."
                )
            tee = _TeeChannel(origin_channel)
            await cmd_set_role_perm(
                guild,
                cast(discord.TextChannel, tee),
                None,
                [role_name, permission, str(value)],
                user=user,
            )
            return _mutation_outcome(tee, f"Requested setting role permission for '{role_name}'")

        elif fname == "list_channels":
            # Thread the caller through so ``cmd_list_channels`` can filter
            # by view-permission and not leak private channel names via
            # the AI tool path.
            await cmd_list_channels(guild, origin_channel, None, [], _user=user)
            return "Listed channels"

        elif fname == "list_roles":
            await cmd_list_roles(guild, origin_channel, None, [], _user=user)
            return "Listed roles"

        elif fname == "list_members":
            # Gate by caller's view_channel permission on origin channel:
            # listing members of a server they can't see is an info-leak.
            # The DM-context guard at the top of this function ensures user is
            # a Member here; cast to Any so permissions_for's typeshed stub
            # (which only accepts Member|Role) doesn't reject the call.
            try:
                if not origin_channel.permissions_for(cast(Any, user)).view_channel:
                    return "⛔ Permission denied: you cannot view this channel."
            except (AttributeError, TypeError):
                # Fail CLOSED like the read_channel check below — failing
                # open here let an unresolvable permission state list every
                # member anyway.
                return "⛔ Permission denied: you cannot view this channel."
            cmd_args = []
            if args.get("limit"):
                cmd_args.append(str(args.get("limit")))
            # ``args`` is the model-controlled tool payload with no per-field
            # type coercion, so ``query`` can be any JSON type. cmd_list_members
            # calls ``args[1].strip()`` and would raise AttributeError on a
            # non-string (e.g. {"query": 123}), silently failing the turn.
            # Guard with isinstance like the get_user_info / read_channel
            # branches below rather than passing the raw value through.
            query = args.get("query")
            if isinstance(query, str) and query.strip():
                if not cmd_args:
                    cmd_args.append("50")
                cmd_args.append(query)
            await cmd_list_members(guild, origin_channel, None, cmd_args, _user=user)
            return "Listed members"

        elif fname == "get_user_info":
            target = args.get("target")
            if not isinstance(target, str) or not target.strip():
                return "❌ Failed: 'target' is required and must be a non-empty string"
            await cmd_get_user_info(guild, origin_channel, None, [target], _user=user)
            return f"Requested info for '{target}'"

        elif fname == "read_channel":
            channel_name = args.get("channel_name")
            if not isinstance(channel_name, str) or not channel_name.strip():
                return "❌ Failed: 'channel_name' is required and must be a non-empty string"
            # Resolve the target channel to verify the *caller* can see it —
            # without this check, a non-admin could ask the AI to read a
            # private staff/mod channel they have no access to (info-leak).
            #
            # Channel name resolution: ``discord.utils.get(..., name=X)``
            # returns the FIRST channel with that name. Discord allows
            # multiple channels with the same name across categories, so
            # an attacker who knows two ``general`` channels exist (one
            # public, one private) could ask for "general" and hit the
            # public one's permission check while the AI ends up reading
            # whichever ``cmd_read_channel`` resolves later. Prefer ID
            # resolution when the caller-supplied name is numeric;
            # otherwise document the first-match behaviour and rely on
            # the per-channel permission check below to fail-closed.
            stripped_name = channel_name.strip()
            target_channel: discord.TextChannel | None = None
            # ID resolution for numeric names. Guard int() with isascii() and a
            # length cap, NOT a bare isdigit(): str.isdigit() is True for Unicode
            # digits ("²", circled digits) that int() rejects, and an all-digit
            # string >4300 chars also raises — both are model-supplied here. A
            # snowflake is <=20 ASCII digits, so this stays exact while a
            # non-numeric/Unicode name simply falls through to the name match.
            if stripped_name.isascii() and stripped_name.isdigit() and len(stripped_name) <= 20:
                resolved = guild.get_channel(int(stripped_name))
                if isinstance(resolved, discord.TextChannel):
                    target_channel = resolved
            if target_channel is None:
                target_channel = discord.utils.get(guild.text_channels, name=stripped_name)
            # Fail-closed when channel can't be located — without this the
            # call would skip the read-permission check and let cmd_read_channel
            # decide on its own (info-leak hole noted in audit).
            if target_channel is None:
                return "⛔ Channel not found or not accessible."
            try:
                # User has been narrowed to Member by the DM-context guard at
                # the top of this function, but discord.py's typeshed types
                # permissions_for as Member|Role only — cast through Any to
                # avoid an unhelpful arg-type error here.
                # Require BOTH view (.read_messages) AND scrollback
                # (.read_message_history): a user denied history but granted
                # view could otherwise have the bot fetch & echo denied
                # backlog back into a channel they can see.
                perms = target_channel.permissions_for(cast(Any, user))
                if not (perms.read_messages and perms.read_message_history):
                    return "⛔ Permission denied to read that channel."
            except (AttributeError, TypeError):
                return "⛔ Permission denied to read that channel."
            # Pass the already-resolved channel ID (not the raw name) so
            # cmd_read_channel targets the EXACT channel this gate validated.
            # cmd_read_channel now also resolves ID-FIRST (then name fallback),
            # matching the order here, so it lands on this same target_channel
            # even if some other channel is literally named with this snowflake
            # string (audit py-aicore-tools-2 — the two resolvers are aligned).
            cmd_args = [str(target_channel.id)]
            if args.get("limit"):
                cmd_args.append(str(args.get("limit")))
            await cmd_read_channel(guild, origin_channel, None, cmd_args, user=user)
            return f"Requested reading channel '{channel_name}'"

        elif fname == "remember":
            # Funnel through the SHARED memory screen (sanitization.py) so this
            # path and the live ``cli`` IPC path (ai_tools_ipc._dispatch_memory)
            # enforce the SAME min-length + prompt-injection denylists + 5000-char
            # clamp. Previously this screen was inline here and DEAD on the cli
            # backend (audit py-aicore-tools-1/-M1); the helper is now the single
            # source of truth. ``content`` returned is stripped + clamped.
            ok, content = screen_memory_content(args.get("content"))
            if not ok:
                return f"❌ Failed to save memory: {content}"
            # Provenance: prefix the calling user so future RAG retrievals
            # carry attribution back into the prompt. Without this, any
            # member could plant unattributed "facts" that later look
            # authoritative when the AI cites them. Sanitize the display
            # name to keep markdown/control chars out of the stored line.
            user_display = getattr(user, "display_name", None) or getattr(user, "name", "user")
            user_id = getattr(user, "id", "?")
            safe_display = "".join(
                c for c in str(user_display) if c.isprintable() and c not in "\r\n"
            )[:32]
            attributed = f"[user {safe_display} (id={user_id})] {content}"
            saved = await rag_system.add_memory(attributed, channel_id=origin_channel.id)
            if not saved:
                # add_memory returns False when the DB/RAG store is
                # unavailable — reporting "Saved" anyway taught the model
                # (and the user) that a lost memory was persisted.
                return "❌ Failed to save memory: memory storage is unavailable"
            return f"✅ Saved to long-term memory: {content[:100]}{'...' if len(content) > 100 else ''}"

        else:
            return f"Unknown function: {fname}"

    except (
        ValueError,
        AttributeError,
        TypeError,
        KeyError,
        discord.HTTPException,
        # RAG/embedding paths can raise RuntimeError / OSError on disk
        # I/O failure; they were previously uncaught here, killing the
        # AI turn with a stack trace instead of returning the friendly
        # ``Error executing X`` string back to Claude.
        RuntimeError,
        OSError,
    ) as e:
        # Anthropic tool calls sometimes ship arguments with None/missing
        # fields; the per-fname guards above try to bounce those, but we
        # still want a backstop so a malformed payload doesn't kill the
        # whole AI turn.
        logger.error("Tool execution error: %s", e, exc_info=True)
        # Return only the exception TYPE to the AI turn, not str(e): a
        # discord.HTTPException's message can carry the raw API response body
        # (internal URLs, error metadata). Operators still get full detail via
        # the logger.error above with exc_info.
        return f"Error executing {fname}: {type(e).__name__}"


async def execute_server_command(bot, origin_channel, user, cmd_type, cmd_args):  # pylint: disable=unused-argument
    """Execute server management commands using the dispatcher.

    Args:
        bot: The Discord bot instance (unused)
        origin_channel: The channel where the command was issued
        user: The user who triggered the command
        cmd_type: The type of command to execute
        cmd_args: Arguments for the command
    """
    # In DMs `user` is a discord.User without `guild_permissions`, so a bare
    # attribute access used to crash with AttributeError before the DM guard
    # below kicked in. Reject DM invocations explicitly first.
    if not hasattr(user, "guild_permissions"):
        await origin_channel.send(
            "❌ คำสั่งนี้ใช้ได้เฉพาะใน server เท่านั้น",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return
    if not user.guild_permissions.administrator:
        logger.warning("⚠️ User %s tried Admin Command %s without perm.", user, cmd_type)
        # display_name is user-controlled (a nickname can embed <@id> text);
        # the bot default allows user pings, so disable mentions explicitly.
        await origin_channel.send(
            f"⛔ คำสั่งนี้สำหรับ Admin เท่านั้น ({user.display_name})",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    try:
        # Check if channel has guild (should always be true for server commands)
        if not hasattr(origin_channel, "guild") or not origin_channel.guild:
            logger.warning("Server command called in non-guild channel")
            await origin_channel.send(
                "❌ คำสั่งนี้ใช้ได้เฉพาะใน server เท่านั้น",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        guild = origin_channel.guild

        # Validate cmd_args
        if not cmd_args:
            cmd_args = ""

        args = [arg.strip() for arg in cmd_args.split("|") if arg.strip()]
        name = args[0] if args else ""

        # Validation
        if name and len(name) > 100:
            await origin_channel.send(
                "❌ ชื่อยาวเกินไป (สูงสุด 100 ตัวอักษร)",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        # Dispatch. Pass the requesting user so each handler can enforce a
        # per-action permission check (e.g. delete_channel requires the
        # user to have manage_channels, not just the bot's admin grant).
        #
        # COMMAND_HANDLERS is keyed entirely in UPPER_SNAKE ('CREATE_TEXT',
        # 'DELETE_CHANNEL', ...). Normalize the lookup so a caller passing a
        # lowercase cmd_type ('create_text') dispatches instead of silently
        # falling through to the unknown-command branch.
        handler = COMMAND_HANDLERS.get(str(cmd_type).upper()) if cmd_type else None
        if handler:
            await handler(guild, origin_channel, name, args, user)
        else:
            logger.warning("Unknown command type: %s", cmd_type)

    except (discord.DiscordException, ValueError) as err:
        logger.error("Failed to execute server command %s: %s", cmd_type, err)


async def send_as_webhook(bot, channel, name, message):
    """Send a message using a webhook to mimic Tupperbox with correct avatar.

    Uses caching to reduce API calls for better performance.

    Args:
        bot: The Discord bot instance
        channel: The channel to send the message to
        name: The display name for the webhook
        message: The message content

    Returns:
        The sent message object, or None if failed
    """
    try:
        # Sanitize dangerous mentions FIRST (before any send path). Negative
        # lookahead so repeated calls don't accumulate ZWS chars (the
        # original ``re.sub`` would turn ``@\u200beveryone`` into
        # ``@\u200b\u200beveryone`` on every additional pass).
        message = re.sub(r"@(?!\u200b)everyone", "@\u200beveryone", message, flags=re.IGNORECASE)
        message = re.sub(r"@(?!\u200b)here", "@\u200bhere", message, flags=re.IGNORECASE)
        message = re.sub(r"<@&(?!\u200b)(\d+)>", "<@&\u200b\\1>", message)  # Role mentions
        message = re.sub(r"<@!?(?!\u200b)(\d+)>", "<@\u200b\\1>", message)  # User mentions

        # Guard against DM channels (no guild/webhooks). Disable mentions on
        # all fallback paths — ``name`` is AI-controlled and may contain
        # raw ``<@everyone>``/``<@id>`` that the per-message regexes don't cover.
        if not hasattr(channel, "guild") or channel.guild is None:
            await _send_plain_fallback(channel, name, message)
            return None

        # Threads (and any other guild channel without webhook ownership)
        # have no .webhooks()/.create_webhook() — their webhooks live on the
        # parent channel. Reaching line `await channel.webhooks()` below with
        # a Thread raised AttributeError, which is NOT in the except clauses
        # and killed the whole AI turn.
        if not hasattr(channel, "webhooks"):
            await _send_plain_fallback(channel, name, message)
            return None

        # Check bot permissions first
        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            await _send_plain_fallback(channel, name, message)
            return None

        name = name[:80]
        webhook_name = f"AI: {name}"[:80]
        channel_id = channel.id

        # When a chunked cached-webhook send fails mid-loop, this carries the
        # exact UNDELIVERED chunks over to the find/create path below.
        pending_chunks: list[str] | None = None

        # Try cache first
        webhook = get_cached_webhook(channel_id, webhook_name)

        if webhook:
            sent_chunks = 0
            try:
                # Try sending with cached webhook
                sent_message = None
                limit = 2000
                if len(message) > limit:
                    chunks = _safe_split_message(message, limit)
                    for chunk in chunks:
                        sent_message = await webhook.send(
                            content=chunk,
                            username=name,
                            wait=True,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        sent_chunks += 1
                else:
                    sent_message = await webhook.send(
                        content=message,
                        username=name,
                        wait=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                logger.debug("🎭 AI spoke as %s (cached webhook)", name)
                return sent_message
            except discord.NotFound:
                # Webhook deleted, invalidate cache and continue to create new one
                invalidate_webhook_cache(channel_id, webhook_name)
                webhook = None
            except discord.HTTPException:
                # Other error, invalidate and continue
                invalidate_webhook_cache(channel_id, webhook_name)
                webhook = None
            if sent_chunks:
                # Resume from the first UNDELIVERED chunk, reusing the SAME
                # chunk list. (Re-splitting a ``"".join(...)`` reconstruction
                # glued newline-split chunks together — the splitter consumes
                # the newline at each boundary, so joining with "" lost it.)
                pending_chunks = chunks[sent_chunks:]
                if not pending_chunks:
                    return sent_message

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
                # Anchor to the repo root via __file__, NOT Path.cwd().
                # cwd can be anywhere depending on how the bot was launched
                # (a service that started in `/` would let `img_path =
                # "etc/passwd"` resolve outside the project). Going via
                # __file__ pins us to the known project tree.
                # Layout: cogs/ai_core/tools/tool_executor.py → 3 parents up
                # is the project root.
                project_root = Path(__file__).resolve().parents[3]
                # Reject absolute paths and `..` segments up front so a
                # crafted SERVER_AVATARS entry can't escape via /etc/passwd
                # or ../.. traversal.
                _candidate = Path(img_path)
                if _candidate.is_absolute() or any(p == ".." for p in _candidate.parts):
                    logger.error("Rejecting suspicious avatar path: %s", img_path)
                    full_path = None
                else:
                    full_path = (project_root / _candidate).resolve()
                    try:
                        full_path.relative_to(project_root)
                    except ValueError:
                        logger.error("Path traversal attempt blocked: %s", img_path)
                        full_path = None

                if full_path and full_path.exists():
                    try:
                        # Discord rejects webhook avatars over ~256 KB with a
                        # 400 "Invalid Form Body" — the previous 1 MB cap let
                        # the API call go through with a too-large image and
                        # silently fail webhook creation. Cap at 200 KB to
                        # leave headroom for the multipart wrapper.
                        AVATAR_CAP = 200 * 1024
                        file_size = full_path.stat().st_size
                        if file_size > AVATAR_CAP:
                            logger.warning(
                                "Avatar file too large (%d bytes > %d cap): %s — "
                                "webhook will be created without avatar",
                                file_size,
                                AVATAR_CAP,
                                full_path,
                            )
                        else:
                            avatar_bytes = full_path.read_bytes()
                    except OSError as err:
                        logger.error("Failed to read avatar file %s: %s", full_path, err)

        # Find existing webhook for this character
        webhooks = await channel.webhooks()

        # 1. Try to find specific character webhook
        for wh in webhooks:
            if wh.user and wh.user == bot.user and wh.name == webhook_name:
                webhook = wh
                break

        # 1b. Backfill avatar for webhooks created before the avatar file fit
        # Discord's size cap. Those were created with avatar=None and would
        # otherwise be reused avatar-less forever (the reuse path never re-sets
        # the avatar). Update once; afterwards ``webhook.avatar`` is non-None so
        # the next reuse skips this extra API call. Only the character-specific
        # webhook found above — never the shared "AI Tupper Proxy" fallback.
        if webhook is not None and avatar_bytes and webhook.avatar is None:
            try:
                await webhook.edit(avatar=avatar_bytes)
                logger.info("🩹 Backfilled missing avatar for webhook %s", webhook_name)
            except discord.HTTPException as err:
                logger.warning("Failed to backfill avatar for webhook %s: %s", webhook_name, err)

        # 2. If not found, create new one (if limit allows)
        DISCORD_WEBHOOK_LIMIT = 15  # Discord's max webhooks per channel
        if not webhook:
            if len(webhooks) < DISCORD_WEBHOOK_LIMIT:
                try:
                    webhook = await channel.create_webhook(name=webhook_name, avatar=avatar_bytes)
                    logger.info("🆕 Created new webhook for %s", name)
                    # Cache the freshly-created webhook so the next message
                    # for this character doesn't pay the channel.webhooks()
                    # round-trip again.
                    set_cached_webhook(channel_id, webhook_name, webhook)
                except discord.HTTPException as err:
                    logger.warning("Failed to create webhook for %s: %s", name, err)
            else:
                # Limit reached, try to reuse "AI Tupper Proxy" specifically.
                # We deliberately DO NOT fall back to "any webhook owned by
                # the bot" here — the previous fallback rendered messages
                # under another character's avatar (the username override on
                # webhook.send doesn't change the webhook avatar), creating
                # cross-identity confusion. Better to surface a clear failure.
                for wh in webhooks:
                    if wh.user and wh.user == bot.user and wh.name == "AI Tupper Proxy":
                        webhook = wh
                        break

                if not webhook:
                    logger.warning(
                        "Webhook limit (%d) reached in channel %s and no "
                        "fallback proxy found — character %s will fall back "
                        "to direct send",
                        DISCORD_WEBHOOK_LIMIT,
                        channel_id,
                        name,
                    )

        # 3. Send Message and cache webhook
        if webhook:
            # Only cache if the webhook name actually matches (don't cache reused webhooks)
            if webhook.name == webhook_name:
                set_cached_webhook(channel_id, webhook_name, webhook)

            sent_message = None
            # Send message (split safely if too long). ``pending_chunks``
            # takes priority: it is the undelivered tail of a chunked send
            # that failed on the cached webhook.
            limit = 2000
            if pending_chunks is not None:
                for chunk in pending_chunks:
                    sent_message = await webhook.send(
                        content=chunk,
                        username=name,
                        wait=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            elif len(message) > limit:
                chunks = _safe_split_message(message, limit)
                for chunk in chunks:
                    sent_message = await webhook.send(
                        content=chunk,
                        username=name,
                        wait=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            else:
                sent_message = await webhook.send(
                    content=message,
                    username=name,
                    wait=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            logger.info("🎭 AI spoke as %s", name)
            return sent_message

        # Fallback if no webhook could be found/created
        if pending_chunks is not None:
            message = "\n".join(pending_chunks)
        return await _send_plain_fallback(channel, name, message)

    except discord.Forbidden:
        # ``channel.name`` doesn't exist on DMChannel — evaluating it inside
        # this handler raised AttributeError and masked the original error.
        logger.warning(
            "No permission to manage webhooks in %s",
            getattr(channel, "name", f"channel:{getattr(channel, 'id', '?')}"),
        )
        return await _send_plain_fallback(channel, name, message)
    except discord.HTTPException as err:
        logger.error("Failed to send webhook: %s", err)
        return await _send_plain_fallback(channel, name, message)


__all__ = [
    "execute_server_command",
    "execute_tool_call",
    "send_as_webhook",
]
