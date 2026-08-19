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

# Database timeouts (in seconds)
DB_CONNECTION_TIMEOUT = 30.0  # SQLite connection timeout

# HTTP/External service timeouts (in seconds)
HTTP_REQUEST_TIMEOUT = 10  # Default HTTP request timeout

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

# Performance tracking
PERFORMANCE_SAMPLES_MAX = 100  # Max samples to keep per metric

# ==================== Discord Limits ====================
DISCORD_WEBHOOK_LIMIT = 15  # Max webhooks per channel
MAX_CHANNEL_NAME_LENGTH = 100  # Max length for channel/category names

# ==================== AI Model Config ====================
SUMMARIZATION_MAX_OUTPUT_TOKENS = (
    1000  # Max tokens for summarization (richer summary retains more detail)
)

# ==================== Lock/Cache Settings ====================
MAX_CHANNELS = 5000  # Max channels to track in message queue
MAX_PENDING_PER_CHANNEL = 50  # Max pending messages per channel

# ==================== Memory Consolidation Settings ====================
# How often to consolidate (extract facts from conversation)
CONSOLIDATE_EVERY_N_MESSAGES = 30  # Consolidate after N messages
CONSOLIDATE_INTERVAL_SECONDS = 3600  # Or after N seconds (1 hour)
MIN_CONVERSATION_LENGTH = 200  # Minimum chars to extract facts from
MAX_RECENT_MESSAGES_FOR_EXTRACTION = 50  # Messages to consider for extraction
# Per-message truncation applied when rendering those messages into the
# extraction prompt. The old hard-coded 500 meant a long roleplay post was
# read only to its first quarter, so anything stated later in the post never
# became a remembered fact — silently, with no log line. Worst case per run
# is MAX_RECENT_MESSAGES_FOR_EXTRACTION * this; unlike the prompt-side knobs
# this one bills through the Anthropic SDK, so lower it if that matters.
# Clamped, unlike a bare _safe_int_env read: this value lands directly in a
# slice bound, where 0 renders every message as a bare "User: " label (still
# over MIN_CONVERSATION_LENGTH, so a real billed call fires on nothing) and a
# negative chops the TAIL off every message — the inverse of a cap, and the
# exact silent-truncation class this knob was added to remove.
EXTRACTION_MAX_CHARS_PER_MESSAGE = max(200, _safe_int_env("EXTRACTION_MAX_CHARS_PER_MESSAGE", 4000))

# ==================== Memory Cleanup Settings ====================
# State tracker cleanup (character states in roleplay)
STATE_CLEANUP_MAX_AGE_HOURS = 24  # Remove states older than N hours
STATE_CLEANUP_MAX_CHANNELS = 500  # Max channels to track states for

# Consolidator cleanup (tracking data for fact extraction)
CONSOLIDATOR_CLEANUP_MAX_AGE_SECONDS = 86400  # 24 hours
CONSOLIDATOR_CLEANUP_MAX_CHANNELS = 500  # Max channels to track

# ==================== Removed (dead) ====================
# These had no consumer anywhere in the tree — the only references were tests
# asserting the constants' own literal values. Recover from git history if a
# caller ever needs one: DB_QUERY_TIMEOUT, DEFAULT_LIST_MEMBERS_LIMIT,
# DISCORD_MESSAGE_LIMIT (ai_cog.py keeps its own _DISCORD_MAX_MESSAGE_LEN),
# HEALTH_CHECK_TIMEOUT, MAX_ROLE_NAME_LENGTH, MAX_STALL_TIME,
# MAX_TEXT_TRUNCATE_LENGTH, MUSIC_DISCONNECT_DELAY, MUSIC_LOCK_TIMEOUT,
# PROCESS_KILL_TIMEOUT, SHUTDOWN_TIMEOUT, STALE_LOCK_MAX_AGE_SECONDS,
# SUMMARIZATION_TEMPERATURE, TEXT_TRUNCATE_HEAD, TEXT_TRUNCATE_TAIL,
# UNUSED_LOCK_MAX_AGE_SECONDS, WEBHOOK_SEND_TIMEOUT.
