-- Migration 011: Fix ai_analytics.model default to Claude while preserving
-- historical per-row model values.

CREATE TABLE ai_analytics_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_length INTEGER,
    output_length INTEGER,
    response_time_ms REAL,
    intent TEXT,
    model TEXT DEFAULT 'claude-opus-4-6',
    tool_calls INTEGER DEFAULT 0,
    cache_hit BOOLEAN DEFAULT 0,
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO ai_analytics_new (
    id,
    user_id,
    channel_id,
    guild_id,
    input_length,
    output_length,
    response_time_ms,
    intent,
    model,
    tool_calls,
    cache_hit,
    error,
    created_at
)
SELECT
    id,
    user_id,
    channel_id,
    guild_id,
    input_length,
    output_length,
    response_time_ms,
    intent,
    COALESCE(NULLIF(model, ''), 'claude-opus-4-6'),
    tool_calls,
    cache_hit,
    error,
    created_at
FROM ai_analytics;

DROP TABLE ai_analytics;

ALTER TABLE ai_analytics_new RENAME TO ai_analytics;

CREATE INDEX IF NOT EXISTS idx_ai_analytics_user
    ON ai_analytics(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_analytics_guild
    ON ai_analytics(guild_id, created_at DESC);