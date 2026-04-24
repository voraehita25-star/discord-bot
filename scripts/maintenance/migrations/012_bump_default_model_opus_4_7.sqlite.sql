-- Migration 012: Update default model to claude-opus-4-7
-- Rationale:
--   Claude Opus 4.7 was released and is now the recommended default.
--   Migrations 007 & 011 pinned DEFAULT 'claude-opus-4-6' on token_usage
--   and ai_analytics. This migration rewrites those defaults without
--   touching historical rows. Data columns are intentionally NOT bulk-
--   updated: past interactions were served by 4.6 and should retain
--   their actual model attribution for analytics.
--
-- SQLite cannot ALTER COLUMN DEFAULT directly, so we recreate the
-- tables following the same CREATE-RENAME-COPY pattern used in 007/011.
-- NOTE: no explicit BEGIN/COMMIT here — the migration runner
-- (utils/database/migrations.py) already wraps each file in a
-- transaction and commits atomically with the schema_version row.

-- -------- token_usage --------
CREATE TABLE token_usage_new_v12 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model TEXT DEFAULT 'claude-opus-4-7',
    cached BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO token_usage_new_v12 (
    id, user_id, channel_id, guild_id,
    input_tokens, output_tokens, model, cached, created_at
)
SELECT
    id, user_id, channel_id, guild_id,
    input_tokens, output_tokens,
    COALESCE(NULLIF(model, ''), 'claude-opus-4-7'),
    cached, created_at
FROM token_usage;

DROP TABLE token_usage;
ALTER TABLE token_usage_new_v12 RENAME TO token_usage;

CREATE INDEX IF NOT EXISTS idx_token_usage_user
    ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_channel
    ON token_usage(channel_id, created_at DESC);

-- -------- ai_analytics --------
CREATE TABLE ai_analytics_new_v12 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_length INTEGER,
    output_length INTEGER,
    response_time_ms REAL,
    intent TEXT,
    model TEXT DEFAULT 'claude-opus-4-7',
    tool_calls INTEGER DEFAULT 0,
    cache_hit BOOLEAN DEFAULT 0,
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO ai_analytics_new_v12 (
    id, user_id, channel_id, guild_id,
    input_length, output_length, response_time_ms, intent,
    model, tool_calls, cache_hit, error, created_at
)
SELECT
    id, user_id, channel_id, guild_id,
    input_length, output_length, response_time_ms, intent,
    COALESCE(NULLIF(model, ''), 'claude-opus-4-7'),
    tool_calls, cache_hit, error, created_at
FROM ai_analytics;

DROP TABLE ai_analytics;
ALTER TABLE ai_analytics_new_v12 RENAME TO ai_analytics;

CREATE INDEX IF NOT EXISTS idx_ai_analytics_user
    ON ai_analytics(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_analytics_guild
    ON ai_analytics(guild_id, created_at DESC);
