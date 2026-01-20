"""
Constants and configuration for the AI Core.
"""
import os


def _safe_int_env(key: str, default: int = 0) -> int:
    """Safely get integer from environment variable."""
    value = os.getenv(key, "")
    if value.isdigit():
        return int(value)
    return default


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

# API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")

# ==================== AI Processing Limits ====================
# History limits (number of messages to keep per channel type)
HISTORY_LIMIT_DEFAULT = 1500  # Default for regular channels
HISTORY_LIMIT_MAIN = 8000  # Main server (higher traffic)
HISTORY_LIMIT_RP = 30000  # Roleplay server (critical for continuity)

# Processing timeouts (in seconds)
LOCK_TIMEOUT = 120.0  # Max wait time for lock acquisition
API_TIMEOUT = 120.0  # Max wait time for Gemini API response
STREAMING_TIMEOUT_INITIAL = 30.0  # Initial chunk timeout
STREAMING_TIMEOUT_CHUNK = 10.0  # Subsequent chunk timeout
MAX_STALL_TIME = 60.0  # Max time before considering stream stalled

# Content limits
MAX_HISTORY_ITEMS = 2000  # Max items in chat history
MAX_TEXT_TRUNCATE_LENGTH = 10000  # Truncate text longer than this
TEXT_TRUNCATE_HEAD = 5000  # Keep first N chars when truncating
TEXT_TRUNCATE_TAIL = 3000  # Keep last N chars when truncating

# Performance tracking
PERFORMANCE_SAMPLES_MAX = 100  # Max samples to keep per metric

# Game-specific keywords that should force Google Search for accurate data
GAME_SEARCH_KEYWORDS = [
    # Limbus Company
    "limbus", "identity", "identities", "e.g.o", "ego",
    "sinner", "sinners", "canto", "dante", "faust", "don quixote",
    "yi sang", "ishmael", "heathcliff", "rodion", "meursault",
    "hong lu", "outis", "gregor", "ryoshu", "sinclair",
    "skill", "passive", "stats", "rarity", "00", "000", "☆",
    "project moon", "library of ruina", "lobotomy corp",
    # Search indicators
    "wiki", "stats", "price", "cost", "damage", "passive skill",
    "ตัวละคร", "สกิล", "แพสซีฟ", "สเตตัส",
]
