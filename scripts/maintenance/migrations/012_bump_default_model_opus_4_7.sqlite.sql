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
-- Idempotent re-apply guards (mirroring 003/007/010): a crash between
-- INSERT and RENAME would otherwise orphan token_usage_new_v12 and break
-- the rerun.
DROP TABLE IF EXISTS token_usage_new_v12;
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

DROP TABLE IF EXISTS token_usage;
ALTER TABLE token_usage_new_v12 RENAME TO token_usage;

CREATE INDEX IF NOT EXISTS idx_token_usage_user
    ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_channel
    ON token_usage(channel_id, created_at DESC);
-- Migration 007 created idx_token_usage_guild; the table-rebuild swap
-- here drops it along with the old table. Recreate it explicitly so
-- guild-scoped analytics queries don't fall back to a full-table scan.
CREATE INDEX IF NOT EXISTS idx_token_usage_guild
    ON token_usage(guild_id, created_at DESC);

-- -------- ai_analytics --------
-- (removed) This migration originally also rebuilt ai_analytics to bump its
-- model default. That table and its analytics subsystem were removed; on a
-- fresh DB it no longer exists, so the rebuild was stripped to avoid a
-- "no such table" failure. Migration 017 drops it on existing databases.
