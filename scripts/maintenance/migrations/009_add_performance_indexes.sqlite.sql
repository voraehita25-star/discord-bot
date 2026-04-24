-- Migration 009: Record that the performance indexes are in place.
--
-- The actual CREATE INDEX statements live in init_schema()
-- (utils/database/database.py) next to their owning tables:
--   - idx_entity_guild_channel     on entity_memories(guild_id, channel_id)
--   - idx_user_facts_channel       on user_facts(channel_id)
--   - idx_dashboard_conv_role      on dashboard_conversations(role_preset, updated_at DESC)
--   - idx_dashboard_conv_provider  on dashboard_conversations(ai_provider, updated_at DESC)
--
-- init_schema() runs BEFORE migrations and uses `CREATE INDEX IF NOT EXISTS`,
-- so it's safe across fresh installs and re-runs. Keeping only SELECTs here
-- means this file stays ANSI-friendly (some IDE SQL linters, e.g. the MSSQL
-- VS Code extension, don't understand SQLite's `IF NOT EXISTS` on CREATE INDEX
-- or partial-index WHERE clauses and flag them as parse errors).
--
-- Each SELECT below is a no-fail presence check: 1 = index exists, 0 = missing
-- (the migration runner does not gate on the value, only on statement success).

SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'idx_entity_guild_channel';
SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'idx_user_facts_channel';
SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'idx_dashboard_conv_role';
SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'idx_dashboard_conv_provider';
