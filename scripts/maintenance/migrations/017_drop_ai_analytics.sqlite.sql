-- Migration 017: Drop the ai_analytics table.
--
-- The AI analytics subsystem (cogs/ai_core/cache/analytics.py) was dead-wired
-- — no production code path ever called log_ai_interaction, so the table only
-- ever held zero rows and the !ai_stats command / dashboard reported nothing.
-- The subsystem was removed; this migration removes its table (and indexes) on
-- existing databases. Fresh databases never create it (schema init no longer
-- does, and migrations 011/012/016 no longer rebuild it).
--
-- DROP ... IF EXISTS so this is a safe no-op on a fresh DB where the table was
-- never created.

DROP INDEX IF EXISTS idx_ai_analytics_user;
DROP INDEX IF EXISTS idx_ai_analytics_guild;
DROP INDEX IF EXISTS idx_ai_analytics_channel;
DROP TABLE IF EXISTS ai_analytics;
