"""
Constants and configuration for the AI Core.

Environment-dependent values (IDs, API keys) live in constants_env.py
and are re-exported here for backward compatibility.
"""

from __future__ import annotations

# Re-export environment-dependent config (keeps all existing imports working)
from .constants_env import (
    ANTHROPIC_API_KEY,
    CHANNEL_ID_ALLOWED,
    CHANNEL_ID_RP_COMMAND,
    CHANNEL_ID_RP_OUTPUT,
    CLAUDE_EFFORT,
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

__all__ = [
    "ANTHROPIC_API_KEY",
    "CHANNEL_ID_ALLOWED",
    "CHANNEL_ID_RP_COMMAND",
    "CHANNEL_ID_RP_OUTPUT",
    "CLAUDE_EFFORT",
    "CLAUDE_MAX_TOKENS",
    "CLAUDE_MODEL",
    "CREATOR_ID",
    "DEFAULT_MODEL",
    "GEMINI_API_KEY",
    "GUILD_ID_COMMAND_ONLY",
    "GUILD_ID_MAIN",
    "GUILD_ID_RESTRICTED",
    "GUILD_ID_RP",
    "_safe_int_env",
]

# ==================== AI Processing Limits ====================
# Per-guild MESSAGE-COUNT retention caps. storage.save_history passes these
# straight to row-count checks and db.prune_ai_history (rows beyond the cap
# are deleted). Token-based API-context trimming is a separate mechanism —
# see memory/history_manager.smart_trim_by_tokens.
HISTORY_LIMIT_DEFAULT = 1500  # Max stored messages for regular channels
HISTORY_LIMIT_MAIN = 8000  # Max stored messages for main server (higher traffic)
HISTORY_LIMIT_RP = 30000  # Max stored messages for roleplay server (continuity)

# Processing timeouts (in seconds)
LOCK_TIMEOUT = 180.0  # Max wait time for lock acquisition (must exceed API_TIMEOUT so a slow API call doesn't drop queued messages)
API_TIMEOUT = 120.0  # Max wait time for Claude API response
STREAMING_TIMEOUT_INITIAL = 120.0  # Initial chunk timeout (wide enough for extended-thinking first-token latency on hard prompts)
STREAMING_TIMEOUT_CHUNK = (
    45.0  # Subsequent chunk timeout (raised so a slow-but-valid thoughtful reply isn't truncated)
)
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
# In-context conversation history fed to the model PER TURN (distinct from the
# on-disk retention caps HISTORY_LIMIT_* above). Env-driven; raised from 2000 so
# long threads keep far more context in front of the 1M-token Opus window.
MAX_HISTORY_ITEMS = _safe_int_env("MAX_HISTORY_ITEMS", 8000)  # Max items in chat history

# ==================== AI recall depth (env-tunable) ====================
# How many long-term RAG memories and entities are retrieved into the prompt
# each turn. Raised well above the old hard-coded 3 — recall was the dominant
# quality bottleneck and the 1M-token context easily absorbs a dozen+ short
# memory lines. Set RAG_TOP_K / ENTITY_TOP_K to tune (or lower for cost).
RAG_TOP_K = _safe_int_env("RAG_TOP_K", 15)  # Long-term memories retrieved per turn
ENTITY_TOP_K = _safe_int_env("ENTITY_TOP_K", 8)  # Entities retrieved per turn
# Dashboard (web UI) history window rendered into a fresh-session prompt.
DASHBOARD_HISTORY_MESSAGES = _safe_int_env("DASHBOARD_HISTORY_MESSAGES", 500)
MAX_TEXT_TRUNCATE_LENGTH = 10000  # Truncate text longer than this
TEXT_TRUNCATE_HEAD = 5000  # Keep first N chars when truncating
TEXT_TRUNCATE_TAIL = 3000  # Keep last N chars when truncating

# Performance tracking
PERFORMANCE_SAMPLES_MAX = 100  # Max samples to keep per metric

# ==================== Discord Limits ====================
DISCORD_MESSAGE_LIMIT = 2000  # Max characters per message
# (MAX_DISCORD_LENGTH alias removed — its only consumer, response_sender.py,
# no longer exists.)
# WEBHOOK_SEND_TIMEOUT is defined once above in "HTTP/External service timeouts"
DISCORD_WEBHOOK_LIMIT = 15  # Max webhooks per channel
MAX_CHANNEL_NAME_LENGTH = 100  # Max length for channel/category names
MAX_ROLE_NAME_LENGTH = 100  # Max length for role names
DEFAULT_LIST_MEMBERS_LIMIT = 50  # Default limit for list_members command

# ==================== AI Model Config ====================
SUMMARIZATION_MAX_OUTPUT_TOKENS = (
    1000  # Max tokens for summarization (richer summary retains more detail)
)
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
