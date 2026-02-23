-- Migration 001: Initial baseline
-- Records the existing schema as the baseline migration.
-- No actual schema changes - just marks the starting point.

-- This migration intentionally has no DDL statements.
-- The existing schema (ai_history, entity_memories, ai_long_term_memory, knowledge_entries, etc.)
-- is created by database.py's init_schema() method.
-- Future migrations will use ALTER TABLE / CREATE TABLE here.

SELECT 1;  -- No-op to prevent empty script error
