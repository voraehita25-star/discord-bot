# pylint: disable=invalid-name
"""
Centralized Configuration Module for Discord Bot.
Uses dataclass for settings management with environment variable support.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _safe_int_env(key: str, default: int) -> int:
    """Safely parse integer from environment variable with fallback."""
    try:
        value = os.getenv(key)
        if value:
            return int(value)
        return default
    except (ValueError, TypeError):
        logger.warning("Invalid integer value for %s, using default: %d", key, default)
        return default


def _first_env(*keys: str) -> str | None:
    """Return the first non-empty environment variable from the provided keys."""
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


@dataclass
class BotSettings:
    """Bot configuration settings loaded from environment variables."""

    # Discord
    discord_token: str = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""), repr=False)

    # Claude AI (primary)
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"), repr=False
    )
    anthropic_base_url: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL"))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-4-8"))

    # Gemini AI (used for RAG embeddings only)
    gemini_api_key: str | None = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY"), repr=False
    )

    # Spotify
    spotipy_client_id: str | None = field(
        default_factory=lambda: _first_env("SPOTIPY_CLIENT_ID", "SPOTIFY_CLIENT_ID"),
        repr=False,
    )
    spotipy_client_secret: str | None = field(
        default_factory=lambda: _first_env("SPOTIPY_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET"),
        repr=False,
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

    # AI Settings
    ai_session_timeout: int = 3600  # 1 hour

    # Paths — anchored to project root to avoid CWD dependency
    data_dir: str = field(default_factory=lambda: str(Path(__file__).parent / "data"))
    temp_dir: str = field(default_factory=lambda: str(Path(__file__).parent / "temp"))
    logs_dir: str = field(default_factory=lambda: str(Path(__file__).parent / "logs"))

    def __post_init__(self) -> None:
        """Validate settings and ensure directories exist."""
        # Validate volume range
        self.default_volume = max(0.0, min(1.0, self.default_volume))

        # Only create dirs if we appear to be running as the bot (not test/import context).
        # Tests set DISCORD_TOKEN via monkeypatch without BOT_RUNNING - respect that by
        # requiring BOT_RUNNING specifically for directory creation.
        if os.environ.get("BOT_RUNNING"):
            for dir_path in [self.data_dir, self.temp_dir, self.logs_dir]:
                try:
                    Path(dir_path).mkdir(parents=True, exist_ok=True)
                except PermissionError as exc:
                    logger.warning("Could not create %s: %s", dir_path, exc)
                except OSError as exc:
                    logger.warning("Error creating %s: %s", dir_path, exc)

    def validate_required_secrets(self) -> list[str]:
        """Validate that critical secrets are present. Returns list of hard errors."""
        errors: list[str] = []
        if not self.discord_token or self.discord_token == "your_token_here":
            errors.append("DISCORD_TOKEN is not set or is a placeholder")
        if (
            self.anthropic_api_key
            and not self.anthropic_api_key.startswith("sk-ant-")
            and not self.anthropic_base_url
        ):
            errors.append(
                "ANTHROPIC_API_KEY does not start with 'sk-ant-'. "
                "If you're using a proxy, set ANTHROPIC_BASE_URL to its endpoint; "
                "if you intended a direct Anthropic key, double-check the value."
            )
        return errors

    def validate_optional_secrets(self) -> list[str]:
        """Validate optional secrets. Returns list of warnings (non-fatal)."""
        warnings: list[str] = []
        if not self.anthropic_api_key:
            warnings.append("ANTHROPIC_API_KEY is not set (AI features will be disabled)")
        return warnings

    def __repr__(self) -> str:
        """Custom repr that redacts sensitive fields."""
        return f"BotSettings(claude_model={self.claude_model!r}, data_dir={self.data_dir!r})"


class FeatureFlags:
    """Registry tracking which optional features loaded successfully.

    Exposed via the health API for debugging.
    """

    def __init__(self) -> None:
        self._flags: dict[str, bool] = {}

    def register(self, name: str, available: bool) -> None:
        """Register a feature and its availability status."""
        self._flags[name] = available

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
