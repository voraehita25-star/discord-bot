-- Migration 003: Fix user_facts schema drift
-- DB has: category TEXT DEFAULT 'general' (nullable), importance DEFAULT 1
-- Code has: category TEXT NOT NULL, importance DEFAULT 2
-- Uses SQLite table rebuild pattern to preserve existing 2 rows.

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

INSERT INTO user_facts_new
    SELECT id, user_id, channel_id,
           COALESCE(category, 'general'),
           content, importance,
           first_mentioned, last_confirmed,
           mention_count, confidence,
           source_message, is_active, is_user_defined, created_at
    FROM user_facts;

DROP TABLE user_facts;

ALTER TABLE user_facts_new RENAME TO user_facts;

CREATE INDEX IF NOT EXISTS idx_user_facts_user ON user_facts(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_user_facts_category ON user_facts(user_id, category);
