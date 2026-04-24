-- Migration 008: Preserve historical ai_analytics.model values.
--
-- Existing analytics rows are historical records. Rewriting every 'gemini'
-- value to 'claude' destroys which model actually served those requests.
-- A later rebuild migration corrects the column default while preserving row data.

SELECT 1;
