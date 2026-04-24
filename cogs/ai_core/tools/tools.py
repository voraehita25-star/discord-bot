"""
AI Tools Module for Discord Bot.

This module is a facade that re-exports all functions from the refactored submodules
for backward compatibility.

Submodules:
- sanitization: Input sanitization functions
- webhook_cache: Webhook caching system
- server_commands: Discord server management commands
- tool_definitions: Gemini API tool definitions
- tool_executor: Tool execution logic
"""

from __future__ import annotations

# Re-export server commands
from ..commands.server_commands import (
    COMMAND_HANDLERS,
    cmd_add_role,
    cmd_create_category,
    cmd_create_role,
    cmd_create_text,
    cmd_create_voice,
    cmd_delete_channel,
    cmd_delete_role,
    cmd_edit_message,
    cmd_get_user_info,
    cmd_list_channels,
    cmd_list_members,
    cmd_list_roles,
    cmd_read_channel,
    cmd_remove_role,
    cmd_set_channel_perm,
    cmd_set_role_perm,
    find_member,
    send_long_message,
)

# Re-export webhook cache functions
from ..response.webhook_cache import (
    WEBHOOK_CACHE_TTL,
    get_cached_webhook,
    invalidate_webhook_cache,
    invalidate_webhook_cache_on_channel_delete,
    set_cached_webhook,
    start_webhook_cache_cleanup,
    stop_webhook_cache_cleanup,
)

# Re-export sanitization functions
from ..sanitization import (
    sanitize_channel_name,
    sanitize_message_content,
    sanitize_role_name,
)

# Re-export tool definitions
from .tool_definitions import get_tool_definitions

# Re-export tool executor functions
from .tool_executor import (
    execute_server_command,
    execute_tool_call,
    send_as_webhook,
)

# Legacy aliases for private functions (for backward compatibility)
_get_cached_webhook = get_cached_webhook
_set_cached_webhook = set_cached_webhook
_invalidate_webhook_cache = invalidate_webhook_cache


__all__ = [
    # Server commands
    "COMMAND_HANDLERS",
    # Webhook cache
    "WEBHOOK_CACHE_TTL",
    # Legacy aliases
    "_get_cached_webhook",
    "_invalidate_webhook_cache",
    "_set_cached_webhook",
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
    # Tool executor
    "execute_server_command",
    "execute_tool_call",
    "find_member",
    "get_cached_webhook",
    # Tool definitions
    "get_tool_definitions",
    "invalidate_webhook_cache",
    "invalidate_webhook_cache_on_channel_delete",
    # Sanitization
    "sanitize_channel_name",
    "sanitize_message_content",
    "sanitize_role_name",
    "send_as_webhook",
    "send_long_message",
    "set_cached_webhook",
    "start_webhook_cache_cleanup",
    "stop_webhook_cache_cleanup",
]
