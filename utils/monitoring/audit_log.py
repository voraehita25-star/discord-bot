"""
Audit Logging Module
Tracks administrative actions for security and accountability.
"""

from __future__ import annotations

import logging
from typing import Any

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class AuditLogger:
    """Async-compatible logger for tracking administrative actions."""

    async def log_action(
        self,
        user_id: int,
        action: str,
        guild_id: int | None = None,
        target_type: str | None = None,
        target_id: int | None = None,
        details: str | None = None,
    ) -> bool:
        """Log an administrative action.

        Args:
            user_id: ID of the user performing the action
            action: Type of action (e.g., 'channel_create', 'role_assign', 'ban')
            guild_id: Guild where action occurred
            target_type: Type of target (e.g., 'channel', 'role', 'user')
            target_id: ID of the target
            details: Additional details as JSON string

        Returns:
            True if logged successfully
        """
        if not DB_AVAILABLE:
            logging.info(
                "📋 AUDIT: [%s] %s (target: %s:%s) - %s",
                guild_id,
                action,
                target_type,
                target_id,
                details,
            )
            return True

        try:
            # Embed target_type into details JSON if provided
            import json

            full_details = details or "{}"
            if target_type:
                try:
                    d = json.loads(full_details) if full_details != "{}" else {}
                    d["target_type"] = target_type
                    full_details = json.dumps(d, ensure_ascii=False)
                except json.JSONDecodeError:
                    # If details is not valid JSON, wrap it
                    full_details = json.dumps({"original": details, "target_type": target_type})

            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_log (guild_id, user_id, action_type, target_id, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (guild_id, user_id, action, target_id, full_details),
                )

            logging.debug("📋 Logged audit action: %s by user %s", action, user_id)
            return True

        except Exception as e:
            logging.error("Failed to log audit action: %s", e)
            return False

    async def get_recent_actions(self, guild_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent actions for a guild.

        Args:
            guild_id: Guild ID to query
            limit: Maximum number of entries to return

        Returns:
            List of audit log entries
        """
        if not DB_AVAILABLE:
            return []

        try:
            async with db.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT id, user_id, action_type, target_id, details, created_at
                    FROM audit_log
                    WHERE guild_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (guild_id, limit),
                )

                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

        except Exception as e:
            logging.error("Failed to get audit log: %s", e)
            return []


# Global audit logger instance
audit = AuditLogger()


# Convenience async functions
async def log_admin_action(
    user_id: int, action: str, guild_id: int | None = None, **kwargs
) -> bool:
    """Log an administrative action (convenience function)."""
    return await audit.log_action(user_id, action, guild_id, **kwargs)


async def log_channel_change(
    user_id: int, guild_id: int, action: str, channel_id: int, channel_name: str
) -> bool:
    """Log a channel-related action."""
    return await audit.log_action(
        user_id=user_id,
        action=f"channel_{action}",
        guild_id=guild_id,
        target_type="channel",
        target_id=channel_id,
        details=f'{{"name": "{channel_name}"}}',
    )


async def log_role_change(
    user_id: int,
    guild_id: int,
    action: str,
    role_id: int,
    role_name: str,
    target_user_id: int | None = None,
) -> bool:
    """Log a role-related action."""
    details = f'{{"name": "{role_name}"'
    if target_user_id:
        details += f', "target_user": {target_user_id}'
    details += "}"

    return await audit.log_action(
        user_id=user_id,
        action=f"role_{action}",
        guild_id=guild_id,
        target_type="role",
        target_id=role_id,
        details=details,
    )
