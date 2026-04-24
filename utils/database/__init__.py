"""Database utilities."""

from .database import Database, db, init_database

# Whitelist of known schema tables for export defense-in-depth.
# Both database.py (async export) and view_db.py (CLI export) use this.
KNOWN_TABLES: frozenset[str] = frozenset({
    "ai_history", "ai_metadata", "guild_settings", "user_stats",
    "music_queue", "error_logs", "ai_long_term_memory",
    "knowledge_entries", "audit_log", "ai_analytics", "token_usage",
    "dashboard_conversations", "dashboard_messages",
    "dashboard_user_profile", "dashboard_memories",
    "entity_memories",
    "user_facts", "conversation_summaries", "schema_version",
})
