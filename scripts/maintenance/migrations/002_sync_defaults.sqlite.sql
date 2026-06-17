-- Migration 002: Sync schema defaults with current code
-- Fixes schema drift caused by CREATE TABLE IF NOT EXISTS not updating existing tables.

-- Fix 1: token_usage.model default 'gemini-3-pro-preview' → 'gemini-3.1-pro-preview'
-- DATA PRESERVATION: a legacy (pre-migration-system) DB that ran the old
-- init_schema accumulates token_usage rows but still reports schema_version 0,
-- so this migration runs against a populated table. Use the same
-- CREATE-new / INSERT...SELECT / DROP / RENAME rebuild as 007/016 to update the
-- column default WITHOUT discarding existing rows. (A bare DROP/CREATE would
-- silently destroy that data.) Idempotent re-apply guards: a crash between the
-- INSERT and the RENAME would otherwise orphan token_usage_new_v2 on disk and
-- break the rerun with "table already exists".
DROP TABLE IF EXISTS token_usage_new_v2;
CREATE TABLE token_usage_new_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model TEXT DEFAULT 'gemini-3.1-pro-preview',
    cached BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Ensure the source table exists before the INSERT...SELECT below. On a FRESH
-- DB this migration historically WAS the table's first CREATE, so without this
-- guard the SELECT raises "no such table". IF NOT EXISTS is a no-op on a legacy
-- DB (its rows are preserved) and an empty create on a fresh DB (nothing to copy).
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    model TEXT DEFAULT 'gemini-3-pro-preview',
    cached BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO token_usage_new_v2 (
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
    COALESCE(NULLIF(model, ''), 'gemini-3.1-pro-preview'),
    cached,
    created_at
FROM token_usage;

DROP TABLE IF EXISTS token_usage;

ALTER TABLE token_usage_new_v2 RENAME TO token_usage;

CREATE INDEX IF NOT EXISTS idx_token_usage_user ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_channel ON token_usage(channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_guild ON token_usage(guild_id, created_at DESC);

-- Fix 2: conversation_summaries defaults drift
-- DATA PRESERVATION: conversation_summaries holds user-facing long-term memory
-- (written by memory_consolidator). On a legacy DB it too can be populated at
-- schema_version 0, so rebuild it with INSERT...SELECT instead of DROP/CREATE
-- to keep existing summaries. Same idempotent guard as above.
DROP TABLE IF EXISTS conversation_summaries_new_v2;
CREATE TABLE conversation_summaries_new_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    user_id INTEGER,
    summary TEXT NOT NULL,
    key_topics TEXT,
    key_decisions TEXT,
    start_time DATETIME,
    end_time DATETIME,
    message_count INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Same fresh-DB guard as token_usage above: conversation_summaries did not
-- exist before this migration on a fresh install, so create it (empty) if
-- absent — a no-op on a legacy DB whose summaries must be preserved.
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    user_id INTEGER,
    summary TEXT NOT NULL,
    key_topics TEXT,
    key_decisions TEXT,
    start_time DATETIME,
    end_time DATETIME,
    message_count INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO conversation_summaries_new_v2 (
    id,
    channel_id,
    user_id,
    summary,
    key_topics,
    key_decisions,
    start_time,
    end_time,
    message_count,
    created_at
)
SELECT
    id,
    channel_id,
    user_id,
    summary,
    key_topics,
    key_decisions,
    start_time,
    end_time,
    message_count,
    created_at
FROM conversation_summaries;

DROP TABLE IF EXISTS conversation_summaries;

ALTER TABLE conversation_summaries_new_v2 RENAME TO conversation_summaries;

CREATE INDEX IF NOT EXISTS idx_summaries_channel ON conversation_summaries(channel_id);

-- Note: user_facts has 2 rows so we preserve data with ALTER approach.
-- user_facts.category: DB nullable DEFAULT 'general', code NOT NULL (no default)
-- user_facts.importance: DB DEFAULT 1, code DEFAULT 2
-- These cannot be fixed via ALTER COLUMN in SQLite. The code always provides
-- explicit values so this drift is non-breaking. Documented here for reference.
