-- Migration 003: Fix user_facts schema drift
-- DB has: category TEXT DEFAULT 'general' (nullable), importance DEFAULT 1
-- Code has: category TEXT NOT NULL, importance DEFAULT 2
-- Uses SQLite table rebuild pattern to preserve existing 2 rows.

-- IF NOT EXISTS / DROP TABLE IF EXISTS makes this migration safe to
-- re-apply after a partial-crash. Without these guards, a power loss
-- between INSERT and RENAME would leave ``user_facts_new`` on disk and
-- the next migration attempt would fail with "table already exists",
-- requiring manual DB intervention.
DROP TABLE IF EXISTS user_facts_new;
CREATE TABLE user_facts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 2,
    first_mentioned DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_confirmed DATETIME DEFAULT CURRENT_TIMESTAMP,
    mention_count INTEGER DEFAULT 1,
    confidence REAL DEFAULT 1.0,
    source_message TEXT,
    is_active BOOLEAN DEFAULT 1,
    is_user_defined BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CAVEAT (legacy schema drift): this SELECT copies columns BY NAME, so the
-- source user_facts table must already contain every column listed below:
--   id, user_id, channel_id, category, content, importance,
--   first_mentioned, last_confirmed, mention_count, confidence,
--   source_message, is_active, is_user_defined, created_at
-- A pre-v3 DB whose user_facts predates one of these columns (e.g.
-- source_message / confidence / is_user_defined) makes this SELECT fail with
-- "no such column" and aborts the migration. init_schema's
-- `CREATE TABLE IF NOT EXISTS user_facts` is a no-op on an existing table and
-- does NOT backfill, and there is no _add_column_if_missing for user_facts, so
-- such a DB needs the missing column(s) added manually before running this
-- migration. SQLite has no dynamic-column SELECT, so this cannot be guarded in
-- pure migration SQL. Low risk in practice: v3 is historical and already
-- applied on the live DB; fresh installs build the full schema first.
INSERT INTO user_facts_new
    SELECT id, user_id, channel_id,
           COALESCE(category, 'general'),
           content, importance,
           first_mentioned, last_confirmed,
           mention_count, confidence,
           source_message, is_active, is_user_defined, created_at
    FROM user_facts;

DROP TABLE IF EXISTS user_facts;

ALTER TABLE user_facts_new RENAME TO user_facts;

CREATE INDEX IF NOT EXISTS idx_user_facts_user ON user_facts(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_user_facts_category ON user_facts(user_id, category);
-- Added: the DROP TABLE above would have removed this too, so re-create here
-- rather than relying on a later migration or the next startup's init_schema.
CREATE INDEX IF NOT EXISTS idx_user_facts_channel ON user_facts(channel_id);
