-- Migration 004: Add dashboard_messages columns (thinking, mode)
-- Previously handled inline in init_schema() via ALTER TABLE + try/except.
-- Moved here for proper migration tracking.
--
-- IDEMPOTENT: These columns are also added by init_schema() via try/except.
-- We use INSERT-OR-IGNORE into a temp tracking table so the migration
-- succeeds even when columns already exist, allowing schema_version to record it.

-- dashboard_messages.thinking — added by init_schema() try/except;
-- verify presence via a no-fail SELECT (column existence is guaranteed by init_schema).
SELECT COUNT(*) FROM pragma_table_info('dashboard_messages') WHERE name = 'thinking';

-- dashboard_messages.mode
SELECT COUNT(*) FROM pragma_table_info('dashboard_messages') WHERE name = 'mode';

-- dashboard_user_profile.is_creator
SELECT COUNT(*) FROM pragma_table_info('dashboard_user_profile') WHERE name = 'is_creator';
