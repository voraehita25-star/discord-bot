# pylint: disable=invalid-name
"""
Centralized Configuration Module for Discord Bot.
Uses dataclass for settings management with environment variable support.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _safe_int_env(key: str, default: int) -> int:
    """Safely parse integer from environment variable with fallback."""
    try:
        value = os.getenv(key)
        if value:
            return int(value)
        return default
    except (ValueError, TypeError):
        import logging
        logging.warning("Invalid integer value for %s, using default: %d", key, default)
        return default


@dataclass
class BotSettings:
    """Bot configuration settings loaded from environment variables."""

    # Discord
    discord_token: str = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""), repr=False)

    # Gemini AI
    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY"), repr=False)
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")
    )

    # Spotify
    spotipy_client_id: str | None = field(default_factory=lambda: os.getenv("SPOTIPY_CLIENT_ID"), repr=False)
    spotipy_client_secret: str | None = field(
        default_factory=lambda: os.getenv("SPOTIPY_CLIENT_SECRET"), repr=False
    )

    # Guild IDs
    guild_id_main: int = field(default_factory=lambda: _safe_int_env("GUILD_ID_MAIN", 0))
    guild_id_restricted: int = field(
        default_factory=lambda: _safe_int_env("GUILD_ID_RESTRICTED", 0)
    )
    guild_id_rp: int = field(default_factory=lambda: _safe_int_env("GUILD_ID_RP", 0))
    guild_id_command_only: int = field(
        default_factory=lambda: _safe_int_env("GUILD_ID_COMMAND_ONLY", 0)
    )

    # Channel IDs
    channel_id_allowed: int = field(default_factory=lambda: _safe_int_env("CHANNEL_ID_ALLOWED", 0))
    channel_id_rp_output: int = field(
        default_factory=lambda: _safe_int_env("CHANNEL_ID_RP_OUTPUT", 0)
    )
    channel_id_rp_command: int = field(
        default_factory=lambda: _safe_int_env("CHANNEL_ID_RP_COMMAND", 0)
    )

    # User IDs
    creator_id: int = field(default_factory=lambda: _safe_int_env("CREATOR_ID", 0))

    # Music Settings
    auto_disconnect_delay: int = 180  # 3 minutes
    default_volume: float = 0.5
    max_queue_size: int = 500

    # AI Settings - optimized for Gemini 2M context window
    # NOTE: These are message storage limits, not token limits
    # For token-based context limits, see cogs/ai_core/data/constants.py
    ai_history_limit_default: int = 5000  # 5k messages for regular channels
    ai_history_limit_main: int = 10000  # 10k for main server
    ai_history_limit_rp: int = 20000  # 20k for roleplay (critical for continuity)
    ai_session_timeout: int = 3600  # 1 hour

    # Paths
    data_dir: str = "data"
    temp_dir: str = "temp"
    logs_dir: str = "logs"

    def __post_init__(self):
        """Ensure directories exist (only when running as main bot, not on import)."""
        # Only create dirs if we appear to be running as the bot (not test/import context)
        for dir_path in [self.data_dir, self.temp_dir, self.logs_dir]:
            Path(dir_path).mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        """Custom repr that redacts sensitive fields."""
        return (
            f"BotSettings(gemini_model={self.gemini_model!r}, "
            f"data_dir={self.data_dir!r}, "
            f"ai_history_limit_default={self.ai_history_limit_default})"
        )


# Global settings instance
settings = BotSettings()
