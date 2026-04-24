-- Migration 002: Sync schema defaults with current code
-- Fixes schema drift caused by CREATE TABLE IF NOT EXISTS not updating existing tables.

-- Fix 1: token_usage.model default 'gemini-3-pro-preview' → 'gemini-3.1-pro-preview'
-- Table has 0 rows so safe to recreate.
DROP TABLE IF EXISTS token_usage;
CREATE TABLE token_usage (
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
CREATE INDEX IF NOT EXISTS idx_token_usage_user ON token_usage(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_channel ON token_usage(channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_guild ON token_usage(guild_id, created_at DESC);

-- Fix 2: conversation_summaries defaults drift (0 rows, safe to recreate)
DROP TABLE IF EXISTS conversation_summaries;
CREATE TABLE conversation_summaries (
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
CREATE INDEX IF NOT EXISTS idx_summaries_channel ON conversation_summaries(channel_id);

-- Note: user_facts has 2 rows so we preserve data with ALTER approach.
-- user_facts.category: DB nullable DEFAULT 'general', code NOT NULL (no default)
-- user_facts.importance: DB DEFAULT 1, code DEFAULT 2
-- These cannot be fixed via ALTER COLUMN in SQLite. The code always provides
-- explicit values so this drift is non-breaking. Documented here for reference.
