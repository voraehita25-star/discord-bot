-- Migration 005: Preserve existing ai_provider values.
--
-- Rewriting 'gemini' -> 'claude' here would corrupt historical conversation
-- settings because SQLite cannot distinguish a user-selected provider from an
-- old column default. The column default itself is corrected by a later rebuild
-- migration without mutating existing rows.

SELECT 1;
