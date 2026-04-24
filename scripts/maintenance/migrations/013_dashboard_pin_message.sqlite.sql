-- Migration 013: Mark dashboard_messages.is_pinned as expected column.
--
-- The column is added by init_schema() via try/except ALTER TABLE (runs
-- BEFORE migrations) — same pattern used by migration 004 for
-- thinking/mode/images. The partial index `idx_dashboard_messages_pinned`
-- is also created in init_schema() next to the other dashboard_messages
-- indexes, so this migration file stays plain ANSI-friendly SQL.
--
-- This file only records that version 13 has been applied; the SELECT
-- below verifies the column is present without risking a failed ALTER.

SELECT COUNT(*) FROM pragma_table_info('dashboard_messages') WHERE name = 'is_pinned';
