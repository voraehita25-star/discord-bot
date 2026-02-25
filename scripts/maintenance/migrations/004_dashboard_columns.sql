-- Migration 004: Add dashboard_messages columns (thinking, mode)
-- Previously handled inline in init_schema() via ALTER TABLE + try/except
-- Moved here for proper migration tracking.

ALTER TABLE dashboard_messages ADD COLUMN thinking TEXT;
ALTER TABLE dashboard_messages ADD COLUMN mode TEXT;

-- Add is_creator to dashboard_user_profile if not exists
ALTER TABLE dashboard_user_profile ADD COLUMN is_creator INTEGER DEFAULT 0;
