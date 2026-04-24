"""
Environment-dependent configuration for the AI Core.

These values are loaded from environment variables at import time.
Separated from constants.py to make the env-dependency boundary explicit.
"""

from __future__ import annotations

import os

# Reuse the canonical implementation from config.py — one function, one behavior.
# config.py only depends on stdlib, so no circular-import risk.
from config import _safe_int_env as _config_safe_int_env


def _safe_int_env(key: str, default: int = 0) -> int:
    """Safely get integer from environment variable. Delegates to config._safe_int_env."""
    return _config_safe_int_env(key, default)


# Guild IDs
GUILD_ID_MAIN = _safe_int_env("GUILD_ID_MAIN")
GUILD_ID_RESTRICTED = _safe_int_env("GUILD_ID_RESTRICTED")
GUILD_ID_RP = _safe_int_env("GUILD_ID_RP")
GUILD_ID_COMMAND_ONLY = _safe_int_env("GUILD_ID_COMMAND_ONLY")

# Channel IDs
CHANNEL_ID_ALLOWED = _safe_int_env("CHANNEL_ID_ALLOWED")
CHANNEL_ID_RP_OUTPUT = _safe_int_env("CHANNEL_ID_RP_OUTPUT")
CHANNEL_ID_RP_COMMAND = _safe_int_env("CHANNEL_ID_RP_COMMAND")

# User IDs
CREATOR_ID = _safe_int_env("CREATOR_ID")

# API Configuration — Claude (primary AI for chat)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-7")
CLAUDE_MAX_TOKENS = _safe_int_env("CLAUDE_MAX_TOKENS", 128000)

# Default model name (use this constant instead of hardcoding)
DEFAULT_MODEL = CLAUDE_MODEL

# Gemini (kept for RAG embeddings only)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
