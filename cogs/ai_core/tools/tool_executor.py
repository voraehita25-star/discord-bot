"""
Tool Executor Module.
Handles execution of Gemini AI function calls and server commands.
"""

from __future__ import annotations

import logging
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
from ..data.roleplay_data import SERVER_AVATARS
from ..memory.rag import rag_system
from ..response.webhook_cache import (
    get_cached_webhook,
    invalidate_webhook_cache,
    set_cached_webhook,
)
from ..data.constants import MAX_CHANNEL_NAME_LENGTH


async def execute_tool_call(
    _bot: commands.Bot,
    origin_channel: discord.TextChannel,
    user: discord.Member,
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
    def validate_name(name: str | None, max_length: int = MAX_CHANNEL_NAME_LENGTH) -> tuple[bool, str]:
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

    # Permission check
    if not user.guild_permissions.administrator:
        return f"⛔ Permission denied: User {user.display_name} is not an Admin."

    try:
        if fname == "create_text_channel":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            await cmd_create_text(
                guild, origin_channel, result, [None, args.get("category")]
            )
            return f"Requested creation of text channel '{result}'"

        elif fname == "create_voice_channel":
            valid, result = validate_name(args.get("name"))
            if not valid:
                return result
            await cmd_create_voice(
                guild, origin_channel, result, [None, args.get("category")]
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

        else:
            return f"Unknown function: {fname}"

    except (ValueError, discord.HTTPException) as e:
        logging.error("Tool execution error: %s", e)
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

    Args:
        bot: The Discord bot instance
        channel: The channel to send the message to
        name: The display name for the webhook
        message: The message content

    Returns:
        The sent message object, or None if failed
    """
    try:
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
                # Fix path resolution: Use current working directory (bot root)
                # Security: Validate path is within expected directory to prevent path traversal
                base_dir = Path.cwd().resolve()
                full_path = (base_dir / img_path).resolve()
                
                # Ensure the resolved path is still within the base directory
                if not str(full_path).startswith(str(base_dir)):
                    logging.error("Path traversal attempt blocked: %s", img_path)
                elif full_path.exists():
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
        DISCORD_WEBHOOK_LIMIT = 15  # Discord's max webhooks per channel
        if not webhook:
            if len(webhooks) < DISCORD_WEBHOOK_LIMIT:
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
            set_cached_webhook(channel_id, webhook_name, webhook)

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


__all__ = [
    "execute_server_command",
    "execute_tool_call",
    "send_as_webhook",
]
