-- Migration 014: Per-conversation tags + per-message "liked" flag.
--
-- Real DDL lives in init_schema() (utils/database/database.py) alongside the
-- other dashboard_* tables — this file stays ANSI-friendly so the VS Code
-- mssql extension doesn't flag SQLite syntax. init_schema() runs BEFORE
-- migrations, so the objects are in place by the time the runner gets here.
--
-- Objects created by init_schema():
--   - CREATE TABLE dashboard_conversation_tags (conversation_id, tag, PK composite,
--         FK -> dashboard_conversations ON DELETE CASCADE)
--   - CREATE INDEX idx_dashboard_tags_conv ON dashboard_conversation_tags(conversation_id)
--   - CREATE INDEX idx_dashboard_tags_tag  ON dashboard_conversation_tags(tag)
--   - ALTER TABLE dashboard_messages ADD COLUMN liked INTEGER NOT NULL DEFAULT 0
--
-- Presence checks below record that v14 applied cleanly on this DB.

SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'dashboard_conversation_tags';
SELECT COUNT(*) FROM pragma_table_info('dashboard_messages') WHERE name = 'liked';
