"""
Tool Executor Module.
Handles execution of Gemini AI function calls and server commands.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

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

logger = logging.getLogger(__name__)


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
    max_chunks = 50  # Safety limit to prevent infinite loops
    while text and len(chunks) < max_chunks:
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
    if text and len(chunks) >= max_chunks:
        chunks.append(text[:limit])  # Append truncated remainder
    return chunks


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
    args = tool_call.args

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
    # ``remember`` writes to the per-channel RAG store and is intentionally
    # NOT in this set — letting any user invoke it would let one member
    # poison every member's future AI replies with planted "facts". The
    # ``remember`` branch below scopes the write to the calling user.
    _READ_ONLY_TOOLS = {
        "list_channels",
        "list_roles",
        "list_members",
        "get_user_info",
        "read_channel",
    }
    if not hasattr(user, "guild_permissions"):
        return f"⛔ Permission denied: User {getattr(user, 'display_name', 'Unknown')} has no guild membership."
    is_admin = user.guild_permissions.administrator
    is_read_only = fname in _READ_ONLY_TOOLS
    if not is_admin and not is_read_only:
        return (
            f"⛔ Permission denied: User {getattr(user, 'display_name', 'Unknown')} "
            f"is not an Admin (tool '{fname}' requires admin privileges)."
        )

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
    if fname in _CHANNEL_MUTATION_TOOLS and not (
        user.guild_permissions.manage_channels or is_admin
    ):
        return "⛔ Permission denied: requires manage_channels permission."
    if fname in _ROLE_MUTATION_TOOLS and not (user.guild_permissions.manage_roles or is_admin):
        return "⛔ Permission denied: requires manage_roles permission."

    try:
        if fname == "create_text_channel":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            await cmd_create_text(guild, origin_channel, result, [result, args.get("category", "")])
            return f"Requested creation of text channel '{result}'"

        elif fname == "create_voice_channel":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            await cmd_create_voice(
                guild, origin_channel, result, [result, args.get("category", "")]
            )
            return f"Requested creation of voice channel '{result}'"

        elif fname == "create_category":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            await cmd_create_category(guild, origin_channel, result, [])
            return f"Requested creation of category '{result}'"

        elif fname == "delete_channel":
            valid, result = validate_name(args.get("name_or_id"))
            if not valid:
                return result
            await cmd_delete_channel(guild, origin_channel, result, [])
            return f"Requested deletion of channel '{result}'"

        elif fname == "create_role":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            cmd_args = [result]
            if args.get("color_hex"):
                cmd_args.append(args.get("color_hex"))
            await cmd_create_role(guild, origin_channel, None, cmd_args)
            return f"Requested creation of role '{result}'"

        elif fname == "delete_role":
            valid, result = validate_name(args.get("name_or_id"))
            if not valid:
                return result
            await cmd_delete_role(guild, origin_channel, None, [result])
            return f"Requested deletion of role '{result}'"

        elif fname == "add_role":
            user_name = args.get("user_name")
            role_name = args.get("role_name")
            if not user_name or not role_name:
                return "❌ add_role requires both user_name and role_name"
            await cmd_add_role(guild, origin_channel, None, [user_name, role_name])
            return f"Requested adding role '{role_name}' to '{user_name}'"

        elif fname == "remove_role":
            user_name = args.get("user_name")
            role_name = args.get("role_name")
            if not user_name or not role_name:
                return "❌ remove_role requires both user_name and role_name"
            await cmd_remove_role(guild, origin_channel, None, [user_name, role_name])
            return f"Requested removing role '{role_name}' from '{user_name}'"

        elif fname == "set_channel_permission":
            channel_name = args.get("channel_name")
            target_name = args.get("target_name")
            permission = args.get("permission")
            value = args.get("value")
            if not channel_name or not target_name or not permission or value is None:
                return (
                    "Missing required argument for set_channel_permission "
                    "(need channel_name, target_name, permission, value)."
                )
            await cmd_set_channel_perm(
                guild,
                origin_channel,
                None,
                [channel_name, target_name, permission, str(value)],
            )
            return f"Requested setting channel permission for '{channel_name}'"

        elif fname == "set_role_permission":
            role_name = args.get("role_name")
            permission = args.get("permission")
            value = args.get("value")
            if not role_name or not permission or value is None:
                return (
                    "Missing required argument for set_role_permission "
                    "(need role_name, permission, value)."
                )
            await cmd_set_role_perm(
                guild,
                origin_channel,
                None,
                [role_name, permission, str(value)],
            )
            return f"Requested setting role permission for '{role_name}'"

        elif fname == "list_channels":
            await cmd_list_channels(guild, origin_channel, None, [])
            return "Listed channels"

        elif fname == "list_roles":
            await cmd_list_roles(guild, origin_channel, None, [])
            return "Listed roles"

        elif fname == "list_members":
            # Gate by caller's view_channel permission on origin channel:
            # listing members of a server they can't see is an info-leak.
            try:
                if not origin_channel.permissions_for(user).view_channel:
                    return "⛔ Permission denied: you cannot view this channel."
            except (AttributeError, TypeError):
                pass
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
            target = args.get("target")
            if not isinstance(target, str) or not target.strip():
                return "❌ Failed: 'target' is required and must be a non-empty string"
            await cmd_get_user_info(guild, origin_channel, None, [target])
            return f"Requested info for '{target}'"

        elif fname == "read_channel":
            channel_name = args.get("channel_name")
            if not isinstance(channel_name, str) or not channel_name.strip():
                return "❌ Failed: 'channel_name' is required and must be a non-empty string"
            # Resolve the target channel to verify the *caller* can see it —
            # without this check, a non-admin could ask the AI to read a
            # private staff/mod channel they have no access to (info-leak).
            target_channel = discord.utils.get(guild.text_channels, name=channel_name.strip())
            if not target_channel and channel_name.strip().isdigit():
                target_channel = guild.get_channel(int(channel_name.strip()))
            if target_channel is not None:
                try:
                    if not target_channel.permissions_for(user).read_messages:
                        return "⛔ Permission denied to read that channel."
                except (AttributeError, TypeError):
                    return "⛔ Permission denied to read that channel."
            cmd_args = [channel_name]
            if args.get("limit"):
                cmd_args.append(str(args.get("limit")))
            await cmd_read_channel(guild, origin_channel, None, cmd_args)
            return f"Requested reading channel '{channel_name}'"

        elif fname == "remember":
            content = args.get("content")
            if not isinstance(content, str):
                return "❌ Failed to save memory: Content must be a string"
            content = content.strip()
            # Reject implausibly short payloads — the model occasionally
            # tries to "remember" a single word, polluting RAG with noise.
            if len(content) < 8:
                return "❌ Failed to save memory: Content is too short"
            # Reject content that looks like a stored prompt-injection
            # payload — prevents future RAG retrievals from echoing
            # ``[SYSTEM] ignore previous instructions`` back into prompts.
            _suspicious = (
                "[system]",
                "[inst]",
                "ignore previous",
                "ignore the previous",
                "<system>",
                "<inst>",
                "</system>",
                "</inst>",
            )
            _content_lower = content.lower()
            if any(marker in _content_lower for marker in _suspicious):
                return "❌ Failed to save memory: Content contains restricted markers"
            # Defense-in-depth against Unicode-normalisation bypasses:
            # NFKD-decompose, drop non-ASCII, then lowercase before matching.
            # This catches fullwidth / homoglyph / combining-mark variants of
            # "[SYSTEM] ignore previous" that the literal substring check above
            # would let through (e.g. "[ＳＹＳＴＥＭ] ignore previous").
            _normalized = (
                unicodedata.normalize("NFKD", content)
                .encode("ascii", "ignore")
                .decode("ascii")
                .lower()
            )
            _forbidden_normalized = (
                "[system]",
                "ignore previous",
                "pretend",
                "you are now",
                "system:",
                "override",
                "jailbreak",
                "disregard",
            )
            if any(f in _normalized for f in _forbidden_normalized):
                return "❌ Failed to save memory: Content contains restricted markers"
            # Limit memory content size to prevent abuse.
            max_memory_size = 5000
            if len(content) > max_memory_size:
                content = content[:max_memory_size]
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
            await rag_system.add_memory(attributed, channel_id=origin_channel.id)
            return f"✅ Saved to long-term memory: {content[:100]}{'...' if len(content) > 100 else ''}"

        else:
            return f"Unknown function: {fname}"

    except (ValueError, AttributeError, TypeError, KeyError, discord.HTTPException) as e:
        # Anthropic tool calls sometimes ship arguments with None/missing
        # fields; the per-fname guards above try to bounce those, but we
        # still want a backstop so a malformed payload doesn't kill the
        # whole AI turn.
        logger.error("Tool execution error: %s", e, exc_info=True)
        return f"Error executing {fname}: {e}"


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
        await origin_channel.send("❌ คำสั่งนี้ใช้ได้เฉพาะใน server เท่านั้น")
        return
    if not user.guild_permissions.administrator:
        logger.warning("⚠️ User %s tried Admin Command %s without perm.", user, cmd_type)
        await origin_channel.send(f"⛔ คำสั่งนี้สำหรับ Admin เท่านั้น ({user.display_name})")
        return

    try:
        # Check if channel has guild (should always be true for server commands)
        if not hasattr(origin_channel, "guild") or not origin_channel.guild:
            logger.warning("Server command called in non-guild channel")
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

        # Dispatch. Pass the requesting user so each handler can enforce a
        # per-action permission check (e.g. delete_channel requires the
        # user to have manage_channels, not just the bot's admin grant).
        handler = COMMAND_HANDLERS.get(cmd_type)
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
        # Sanitize dangerous mentions FIRST (before any send path)
        message = re.sub(r"@everyone", "@\u200beveryone", message, flags=re.IGNORECASE)
        message = re.sub(r"@here", "@\u200bhere", message, flags=re.IGNORECASE)
        message = re.sub(r"<@&(\d+)>", "<@&\u200b\\1>", message)  # Role mentions
        message = re.sub(r"<@!?(\d+)>", "<@\u200b\\1>", message)  # User mentions

        # Guard against DM channels (no guild/webhooks)
        if not hasattr(channel, "guild") or channel.guild is None:
            await channel.send(f"**{name}**: {message}")
            return None

        # Check bot permissions first
        if not channel.permissions_for(channel.guild.me).manage_webhooks:
            await channel.send(f"**{name}**: {message}")
            return None

        webhook_name = f"AI: {name}"
        channel_id = channel.id

        # Try cache first
        webhook = get_cached_webhook(channel_id, webhook_name)

        if webhook:
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

        # 2. If not found, create new one (if limit allows)
        DISCORD_WEBHOOK_LIMIT = 15  # Discord's max webhooks per channel
        if not webhook:
            if len(webhooks) < DISCORD_WEBHOOK_LIMIT:
                try:
                    webhook = await channel.create_webhook(name=webhook_name, avatar=avatar_bytes)
                    logger.info("🆕 Created new webhook for %s", name)
                except discord.HTTPException as err:
                    logger.warning("Failed to create webhook for %s: %s", name, err)
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
            # Only cache if the webhook name actually matches (don't cache reused webhooks)
            if webhook.name == webhook_name:
                set_cached_webhook(channel_id, webhook_name, webhook)

            sent_message = None
            # Send message (split safely if too long)
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
        return await channel.send(f"**{name}**: {message}")

    except discord.Forbidden:
        logger.warning("No permission to manage webhooks in %s", channel.name)
        return await channel.send(f"**{name}**: {message}")
    except discord.HTTPException as err:
        logger.error("Failed to send webhook: %s", err)
        return await channel.send(f"**{name}**: {message}")


__all__ = [
    "execute_server_command",
    "execute_tool_call",
    "send_as_webhook",
]
