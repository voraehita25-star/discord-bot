"""
Constants and configuration for the AI Core.

Environment-dependent values (IDs, API keys) live in constants_env.py
and are re-exported here for backward compatibility.
"""

from __future__ import annotations

# Re-export environment-dependent config (keeps all existing imports working)
from .constants_env import (  # noqa: F401
    ANTHROPIC_API_KEY,
    CHANNEL_ID_ALLOWED,
    CHANNEL_ID_RP_COMMAND,
    CHANNEL_ID_RP_OUTPUT,
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    CREATOR_ID,
    DEFAULT_MODEL,
    GEMINI_API_KEY,
    GUILD_ID_COMMAND_ONLY,
    GUILD_ID_MAIN,
    GUILD_ID_RESTRICTED,
    GUILD_ID_RP,
    _safe_int_env,
)

# ==================== AI Processing Limits ====================
# History limits (number of messages to keep per channel type)
# NOTE: These are token-based limits for API context, not message counts
# For actual message storage limits, see config.py BotSettings class
HISTORY_LIMIT_DEFAULT = 1500  # Token limit for regular channels
HISTORY_LIMIT_MAIN = 8000  # Token limit for main server (higher traffic)
HISTORY_LIMIT_RP = 30000  # Token limit for roleplay server (critical for continuity)

# Processing timeouts (in seconds)
LOCK_TIMEOUT = 30.0  # Max wait time for lock acquisition (API timeout handles the actual call)
API_TIMEOUT = 120.0  # Max wait time for Claude API response
STREAMING_TIMEOUT_INITIAL = 30.0  # Initial chunk timeout
STREAMING_TIMEOUT_CHUNK = 10.0  # Subsequent chunk timeout
MAX_STALL_TIME = 60.0  # Max time before considering stream stalled

# Database timeouts (in seconds)
DB_CONNECTION_TIMEOUT = 30.0  # SQLite connection timeout
DB_QUERY_TIMEOUT = 10.0  # Individual query timeout

# HTTP/External service timeouts (in seconds)
HTTP_REQUEST_TIMEOUT = 10  # Default HTTP request timeout
HEALTH_CHECK_TIMEOUT = 5.0  # Health check endpoint timeout
WEBHOOK_SEND_TIMEOUT = 10.0  # Discord webhook send timeout

# Music playback timeouts (in seconds)
MUSIC_LOCK_TIMEOUT = 0.1  # Lock acquisition for play_next
MUSIC_DISCONNECT_DELAY = 180  # Auto-disconnect after inactivity (3 min)

# Shutdown timeouts (in seconds)
SHUTDOWN_TIMEOUT = 30.0  # Global shutdown timeout
PROCESS_KILL_TIMEOUT = 5.0  # Wait time before force-killing process

# Content limits
MAX_HISTORY_ITEMS = 2000  # Max items in chat history
MAX_TEXT_TRUNCATE_LENGTH = 10000  # Truncate text longer than this
TEXT_TRUNCATE_HEAD = 5000  # Keep first N chars when truncating
TEXT_TRUNCATE_TAIL = 3000  # Keep last N chars when truncating

# Performance tracking
PERFORMANCE_SAMPLES_MAX = 100  # Max samples to keep per metric

# ==================== Discord Limits ====================
DISCORD_MESSAGE_LIMIT = 2000  # Max characters per message
DISCORD_WEBHOOK_LIMIT = 15  # Max webhooks per channel
MAX_CHANNEL_NAME_LENGTH = 100  # Max length for channel/category names
MAX_ROLE_NAME_LENGTH = 100  # Max length for role names
DEFAULT_LIST_MEMBERS_LIMIT = 50  # Default limit for list_members command

# ==================== AI Model Config ====================
SUMMARIZATION_MAX_OUTPUT_TOKENS = 300  # Max tokens for summarization
SUMMARIZATION_TEMPERATURE = 0.3  # Temperature for consistent summaries

# ==================== Lock/Cache Settings ====================
STALE_LOCK_MAX_AGE_SECONDS = 300.0  # 5 minutes - max age for stale locks
UNUSED_LOCK_MAX_AGE_SECONDS = 3600.0  # 1 hour - max age for unused locks
MAX_CHANNELS = 5000  # Max channels to track in message queue
MAX_PENDING_PER_CHANNEL = 50  # Max pending messages per channel

# ==================== Memory Consolidation Settings ====================
# How often to consolidate (extract facts from conversation)
CONSOLIDATE_EVERY_N_MESSAGES = 30  # Consolidate after N messages
CONSOLIDATE_INTERVAL_SECONDS = 3600  # Or after N seconds (1 hour)
MIN_CONVERSATION_LENGTH = 200  # Minimum chars to extract facts from
MAX_RECENT_MESSAGES_FOR_EXTRACTION = 50  # Messages to consider for extraction

# ==================== Memory Cleanup Settings ====================
# State tracker cleanup (character states in roleplay)
STATE_CLEANUP_MAX_AGE_HOURS = 24  # Remove states older than N hours
STATE_CLEANUP_MAX_CHANNELS = 500  # Max channels to track states for

# Consolidator cleanup (tracking data for fact extraction)
CONSOLIDATOR_CLEANUP_MAX_AGE_SECONDS = 86400  # 24 hours
CONSOLIDATOR_CLEANUP_MAX_CHANNELS = 500  # Max channels to track

# ==================== Conversation Branch Settings ====================
# Checkpoint and branch cleanup
BRANCH_MAX_CHECKPOINTS_PER_CHANNEL = 20  # Max checkpoints per channel
BRANCH_AUTO_CHECKPOINT_INTERVAL = 10  # Auto checkpoint every N messages
BRANCH_CLEANUP_MAX_AGE_HOURS = 48  # Remove branches older than N hours
BRANCH_CLEANUP_INTERVAL_HOURS = 6  # Run cleanup every N hours

# Game-specific keywords that should force Google Search for accurate data
GAME_SEARCH_KEYWORDS = [
    # Limbus Company
    "limbus",
    "identity",
    "identities",
    "e.g.o",
    "ego",
    "sinner",
    "sinners",
    "canto",
    "dante",
    "faust",
    "don quixote",
    "yi sang",
    "ishmael",
    "heathcliff",
    "rodion",
    "meursault",
    "hong lu",
    "outis",
    "gregor",
    "ryoshu",
    "sinclair",
    "skill",
    "passive",
    "stats",
    "rarity",
    "00",
    "000",
    "☆",
    "project moon",
    "library of ruina",
    "lobotomy corp",
    # Search indicators
    "wiki",
    "price",
    "cost",
    "damage",
    "passive skill",
    "ตัวละคร",
    "สกิล",
    "แพสซีฟ",
    "สเตตัส",
]
