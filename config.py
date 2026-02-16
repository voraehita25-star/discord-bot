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
        """Validate settings and ensure directories exist."""
        # Validate volume range
        self.default_volume = max(0.0, min(1.0, self.default_volume))

        # Only create dirs if we appear to be running as the bot (not test/import context)
        if os.environ.get("BOT_RUNNING") or os.environ.get("DISCORD_TOKEN"):
            for dir_path in [self.data_dir, self.temp_dir, self.logs_dir]:
                Path(dir_path).mkdir(parents=True, exist_ok=True)

    def validate_required_secrets(self) -> list[str]:
        """Validate that critical secrets are present. Returns list of errors."""
        errors: list[str] = []
        if not self.discord_token or self.discord_token == "your_token_here":
            errors.append("DISCORD_TOKEN is not set or is a placeholder")
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY is not set (AI features will be disabled)")
        return errors

    def get_secrets_summary(self) -> dict[str, bool]:
        """Get a summary of which optional secrets are configured."""
        return {
            "discord_token": bool(self.discord_token and self.discord_token != "your_token_here"),
            "gemini_api_key": bool(self.gemini_api_key),
            "spotify_credentials": bool(self.spotipy_client_id and self.spotipy_client_secret),
            "guild_id_main": self.guild_id_main != 0,
            "creator_id": self.creator_id != 0,
        }

    def __repr__(self) -> str:
        """Custom repr that redacts sensitive fields."""
        return (
            f"BotSettings(gemini_model={self.gemini_model!r}, "
            f"data_dir={self.data_dir!r}, "
            f"ai_history_limit_default={self.ai_history_limit_default})"
        )


class FeatureFlags:
    """Registry tracking which optional features loaded successfully.
    
    Exposed via the health API for debugging.
    """

    def __init__(self) -> None:
        self._flags: dict[str, bool] = {}

    def register(self, name: str, available: bool) -> None:
        """Register a feature and its availability status."""
        self._flags[name] = available

    def is_available(self, name: str) -> bool:
        """Check if a feature is available."""
        return self._flags.get(name, False)

    def get_all(self) -> dict[str, bool]:
        """Get all feature flags."""
        return dict(self._flags)

    def summary(self) -> str:
        """Get a human-readable summary of feature status."""
        lines = []
        for name, available in sorted(self._flags.items()):
            icon = "✅" if available else "❌"
            lines.append(f"  {icon} {name}")
        return "\n".join(lines)


# Global instances
settings = BotSettings()
feature_flags = FeatureFlags()
