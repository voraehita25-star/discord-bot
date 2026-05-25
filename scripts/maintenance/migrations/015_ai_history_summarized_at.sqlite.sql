-- Migration 015: Per-row ``summarized_at`` flag on ai_history.
--
-- Real DDL lives in init_schema() (utils/database/database.py) — this file
-- stays plain SQL for ANSI-friendly editors, mirroring the pattern used by
-- migration 014. init_schema() runs BEFORE migrations, so the column and
-- partial index are in place by the time the runner reaches this file.
--
-- Objects added by init_schema():
--   - ALTER TABLE ai_history ADD COLUMN summarized_at DATETIME
--     (idempotent via _add_column_if_missing pragma_table_info pre-check)
--   - CREATE INDEX idx_ai_history_pending_summary
--       ON ai_history(channel_id, timestamp) WHERE summarized_at IS NULL
--     (partial index — only rows that still need consolidation are indexed,
--      so the consolidator's sweep cost scales with backlog, not history)
--
-- Why:
--   memory_consolidator previously hard-deleted source rows after the
--   summary row committed. A crash between save and delete left the source
--   rows live, so the next consolidation pass re-summarised the same
--   content and produced a duplicate summary. With summarized_at:
--   - default path now MARKs rows instead of deleting them; lossless and
--     idempotent across re-runs.
--   - CONSOLIDATOR_DELETE_ORIGINALS=1 still hard-deletes when set, for
--     operators who want the storage reclaim.
--
-- Presence checks below record that v15 applied cleanly on this DB.

SELECT COUNT(*) FROM pragma_table_info('ai_history') WHERE name = 'summarized_at';
SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'idx_ai_history_pending_summary';
