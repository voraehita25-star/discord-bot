-- Migration 007: Align token_usage.model default with runtime default model
-- The application now records Claude as the primary default model for token tracking.
-- Rebuild the table to update the column default while preserving existing data.

CREATE TABLE token_usage_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model TEXT DEFAULT 'claude-opus-4-6',
    cached BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO token_usage_new (
    id,
    user_id,
    channel_id,
    guild_id,
    input_tokens,
    output_tokens,
    model,
    cached,
    created_at
)
SELECT
    id,
    user_id,
    channel_id,
    guild_id,
    input_tokens,
    output_tokens,
    COALESCE(NULLIF(model, ''), 'claude-opus-4-6'),
    cached,
    created_at
FROM token_usage;

DROP TABLE token_usage;

ALTER TABLE token_usage_new RENAME TO token_usage;

CREATE INDEX IF NOT EXISTS idx_token_usage_user ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_channel ON token_usage(channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_guild ON token_usage(guild_id, created_at DESC);