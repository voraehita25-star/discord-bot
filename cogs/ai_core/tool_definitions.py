"""
Tool Definitions Module.
Provides Gemini API tool definitions for AI function calling.
"""

from __future__ import annotations


def get_tool_definitions() -> list[dict]:
    """Return tool definitions for Gemini.

    Returns:
        List of tool definition dictionaries for Gemini API
    """
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


__all__ = ["get_tool_definitions"]
