-- Migration 004: Add dashboard_messages columns (thinking, mode) and
-- dashboard_user_profile.is_creator.
-- Previously handled inline in init_schema() via ALTER TABLE + try/except.
-- Moved here for proper migration tracking.
--
-- IDEMPOTENT: These columns are also added by init_schema() via try/except
-- (which runs BEFORE migrations). This migration only records that version 4
-- has been applied. The SELECT queries verify column presence without error.

-- dashboard_messages.thinking — added by init_schema() try/except;
-- verify presence via a no-fail SELECT.
SELECT COUNT(*) FROM pragma_table_info('dashboard_messages') WHERE name = 'thinking';

-- dashboard_messages.mode
SELECT COUNT(*) FROM pragma_table_info('dashboard_messages') WHERE name = 'mode';

-- dashboard_user_profile.is_creator
SELECT COUNT(*) FROM pragma_table_info('dashboard_user_profile') WHERE name = 'is_creator';
