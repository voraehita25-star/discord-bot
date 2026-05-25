-- Migration 010: Fix dashboard_conversations.ai_provider default to 'claude'
-- while preserving existing per-conversation provider choices.
--
-- IMPORTANT: Disable foreign_keys before DROP TABLE to prevent ON DELETE CASCADE
-- from wiping dashboard_messages (child rows referencing dashboard_conversations).

PRAGMA foreign_keys=OFF;

-- Idempotent re-apply guard: a crash between INSERT and RENAME below
-- would otherwise leave dashboard_conversations_new orphaned on disk
-- and the rerun would fail with "table already exists", requiring
-- manual DB intervention.
DROP TABLE IF EXISTS dashboard_conversations_new;
CREATE TABLE dashboard_conversations_new (
    id TEXT PRIMARY KEY,
    title TEXT,
    role_preset TEXT NOT NULL DEFAULT 'general',
    system_instruction TEXT,
    thinking_enabled BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_starred BOOLEAN DEFAULT 0,
    ai_provider TEXT NOT NULL DEFAULT 'claude'
);

INSERT INTO dashboard_conversations_new (
    id,
    title,
    role_preset,
    system_instruction,
    thinking_enabled,
    created_at,
    updated_at,
    is_starred,
    ai_provider
)
SELECT
    id,
    title,
    role_preset,
    system_instruction,
    thinking_enabled,
    created_at,
    updated_at,
    is_starred,
    COALESCE(NULLIF(ai_provider, ''), 'claude')
FROM dashboard_conversations;

DROP TABLE IF EXISTS dashboard_conversations;

ALTER TABLE dashboard_conversations_new RENAME TO dashboard_conversations;

CREATE INDEX IF NOT EXISTS idx_dashboard_conv_updated
    ON dashboard_conversations(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dashboard_conv_starred
    ON dashboard_conversations(is_starred, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dashboard_conv_role
    ON dashboard_conversations(role_preset, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dashboard_conv_provider
    ON dashboard_conversations(ai_provider, updated_at DESC);

PRAGMA foreign_keys=ON;
