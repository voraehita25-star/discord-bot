-- Migration 018: Update default model to claude-opus-5
-- Rationale:
--   Claude Opus 5 shipped and is now the recommended default across the bot
--   (config.py, constants_env.py, dashboard_config.py, api_failover's health
--   probe). Migration 016 pinned DEFAULT 'claude-opus-4-8' on token_usage;
--   this migration rewrites that default without touching historical rows.
--   Data columns are intentionally NOT bulk-updated: past interactions were
--   served by 4.8 (or earlier) and should retain their actual model
--   attribution for cost analytics — only blank/NULL models are backfilled.
--
--   ai_analytics is deliberately absent: migration 017 dropped it along with
--   the dead analytics subsystem, and 016 already stripped its rebuild.
--
-- SQLite cannot ALTER COLUMN DEFAULT directly, so we recreate the table
-- following the same CREATE-RENAME-COPY pattern used in 007/011/012/016.
-- NOTE: no explicit BEGIN/COMMIT here — the migration runner
-- (utils/database/migrations.py) already wraps each file in a transaction
-- and commits atomically with the schema_version row.

-- -------- token_usage --------
-- Idempotent re-apply guard (mirroring 016): a crash between INSERT and
-- RENAME would otherwise orphan token_usage_new_v18 and break the rerun.
DROP TABLE IF EXISTS token_usage_new_v18;
CREATE TABLE token_usage_new_v18 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model TEXT DEFAULT 'claude-opus-5',
    cached BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO token_usage_new_v18 (
    id, user_id, channel_id, guild_id,
    input_tokens, output_tokens, model, cached, created_at
)
SELECT
    id, user_id, channel_id, guild_id,
    input_tokens, output_tokens,
    COALESCE(NULLIF(model, ''), 'claude-opus-5'),
    cached, created_at
FROM token_usage;

DROP TABLE IF EXISTS token_usage;
ALTER TABLE token_usage_new_v18 RENAME TO token_usage;

CREATE INDEX IF NOT EXISTS idx_token_usage_user
    ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_channel
    ON token_usage(channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_guild
    ON token_usage(guild_id, created_at DESC);
