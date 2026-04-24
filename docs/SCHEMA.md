# Database Schema

SQLite database at `data/bot_database.db` — WAL mode, aiosqlite.

## Tables

### ai_history — AI Chat History

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| local_id | INTEGER | |
| channel_id | INTEGER | NOT NULL |
| user_id | INTEGER | |
| role | TEXT | NOT NULL, CHECK('user','model') |
| content | TEXT | NOT NULL |
| message_id | INTEGER | |
| timestamp | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_ai_history_channel(channel_id)`, `idx_ai_history_timestamp(channel_id, timestamp DESC)`, `idx_ai_history_local_id(channel_id, local_id)`, `idx_ai_history_user_id(user_id)`

### ai_metadata — AI Session Metadata

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| channel_id | INTEGER | PRIMARY KEY |
| thinking_enabled | BOOLEAN | DEFAULT 1 |
| system_instruction | TEXT | |
| last_accessed | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### guild_settings

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| guild_id | INTEGER | PRIMARY KEY |
| prefix | TEXT | DEFAULT '!' |
| ai_enabled | BOOLEAN | DEFAULT 1 |
| music_enabled | BOOLEAN | DEFAULT 1 |
| auto_disconnect_delay | INTEGER | DEFAULT 180 |
| mode_247 | BOOLEAN | DEFAULT 0 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### user_stats

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| user_id | INTEGER | NOT NULL, PK |
| guild_id | INTEGER | NOT NULL, PK |
| messages_count | INTEGER | DEFAULT 0 |
| commands_count | INTEGER | DEFAULT 0 |
| ai_interactions | INTEGER | DEFAULT 0 |
| music_requests | INTEGER | DEFAULT 0 |
| last_active | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### music_queue

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| guild_id | INTEGER | NOT NULL |
| position | INTEGER | NOT NULL |
| url | TEXT | NOT NULL |
| title | TEXT | |
| added_by | INTEGER | |
| added_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Index: `idx_music_queue_guild(guild_id, position)`

### error_logs

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| error_type | TEXT | NOT NULL |
| error_message | TEXT | |
| traceback | TEXT | |
| guild_id | INTEGER | |
| channel_id | INTEGER | |
| user_id | INTEGER | |
| command | TEXT | |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_error_logs_type(error_type, created_at DESC)`, `idx_error_logs_created(created_at DESC)`

### ai_long_term_memory — RAG Vector Store

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| channel_id | INTEGER | |
| content | TEXT | NOT NULL |
| embedding | BLOB | NOT NULL |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### knowledge_entries — Structured Knowledge (RAG)

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| domain | TEXT | NOT NULL |
| category | TEXT | NOT NULL |
| topic | TEXT | NOT NULL |
| content | TEXT | NOT NULL |
| games | TEXT | DEFAULT '[]' |
| tags | TEXT | DEFAULT '[]' |
| is_spoiler | BOOLEAN | DEFAULT 0 |
| confidence | REAL | DEFAULT 1.0 |
| source | TEXT | DEFAULT 'official' |
| embedding | BLOB | |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_knowledge_domain(domain)`, `idx_knowledge_category(category)`, `idx_knowledge_topic(domain, category, topic)`

### audit_log

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| action_type | TEXT | NOT NULL |
| guild_id | INTEGER | |
| user_id | INTEGER | |
| target_id | INTEGER | |
| details | TEXT | |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_audit_log_created(created_at DESC)`, `idx_audit_log_guild(guild_id)`, `idx_audit_log_guild_created(guild_id, created_at DESC)`

### ai_analytics

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| user_id | INTEGER | NOT NULL |
| channel_id | INTEGER | NOT NULL |
| guild_id | INTEGER | |
| input_length | INTEGER | |
| output_length | INTEGER | |
| response_time_ms | REAL | |
| intent | TEXT | |
| model | TEXT | DEFAULT 'claude-opus-4-7' |
| tool_calls | INTEGER | DEFAULT 0 |
| cache_hit | BOOLEAN | DEFAULT 0 |
| error | TEXT | |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_ai_analytics_user(user_id, created_at DESC)`, `idx_ai_analytics_guild(guild_id, created_at DESC)`

### token_usage

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| user_id | INTEGER | NOT NULL |
| channel_id | INTEGER | NOT NULL |
| guild_id | INTEGER | |
| input_tokens | INTEGER | NOT NULL |
| output_tokens | INTEGER | NOT NULL |
| model | TEXT | DEFAULT 'claude-opus-4-7' |
| cached | BOOLEAN | DEFAULT 0 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_token_usage_user(user_id, created_at DESC)`, `idx_token_usage_channel(channel_id, created_at DESC)`, `idx_token_usage_guild(guild_id, created_at DESC)`

### dashboard_conversations

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | TEXT | PRIMARY KEY |
| title | TEXT | |
| role_preset | TEXT | NOT NULL, DEFAULT 'general' |
| system_instruction | TEXT | |
| thinking_enabled | BOOLEAN | DEFAULT 0 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| is_starred | BOOLEAN | DEFAULT 0 |
| ai_provider | TEXT | DEFAULT 'gemini' |

Indexes: `idx_dashboard_conv_updated(updated_at DESC)`, `idx_dashboard_conv_starred(is_starred, updated_at DESC)`, `idx_dashboard_conv_role(role_preset, updated_at DESC)`, `idx_dashboard_conv_provider(ai_provider, updated_at DESC)`

### dashboard_messages

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| conversation_id | TEXT | NOT NULL, FK → dashboard_conversations ON DELETE CASCADE |
| role | TEXT | NOT NULL, CHECK('user','assistant') |
| content | TEXT | NOT NULL |
| thinking | TEXT | |
| mode | TEXT | |
| images | TEXT | JSON array of base64 image strings |
| is_pinned | INTEGER | NOT NULL DEFAULT 0 — user-marked important message (migration 013) |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes:

- `idx_dashboard_msg_conv(conversation_id, created_at ASC)` — conversation history scan
- `idx_dashboard_messages_pinned(conversation_id, is_pinned) WHERE is_pinned = 1` — partial index for fast "fetch pinned only" queries

### dashboard_user_profile — Singleton

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY CHECK (id = 1) |
| display_name | TEXT | DEFAULT 'User' |
| bio | TEXT | |
| preferences | TEXT | |
| is_creator | INTEGER | DEFAULT 0 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### dashboard_memories

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| content | TEXT | NOT NULL |
| category | TEXT | DEFAULT 'general' |
| importance | INTEGER | DEFAULT 1 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Index: `idx_dashboard_memories_category(category, importance DESC)`

### user_facts — Per-user Memory

| Column | Type | Constraints |
| -------- | ------ | ------------- ||| -------- | ------ | ------------- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| user_id | INTEGER | NOT NULL |
| channel_id | INTEGER | |
| category | TEXT | NOT NULL |
| content | TEXT | NOT NULL |
| importance | INTEGER | DEFAULT 2 |
| first_mentioned | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| last_confirmed | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| mention_count | INTEGER | DEFAULT 1 |
| confidence | REAL | DEFAULT 1.0 |
| source_message | TEXT | |
| is_active | BOOLEAN | DEFAULT 1 |
| is_user_defined | BOOLEAN | DEFAULT 0 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_user_facts_user(user_id, is_active)`, `idx_user_facts_category(user_id, category)`, `idx_user_facts_channel(channel_id)`

## Database Configuration

- **WAL mode** + `mmap_size=2GB` + `wal_autocheckpoint=2000`
- **Connection pool:** 32 semaphore slots, 16 reusable connections
- **PRAGMAs:** `synchronous=NORMAL`, `cache_size=250000`, `temp_store=MEMORY`, `foreign_keys=ON`
- **Write lock:** `asyncio.Lock` prevents concurrent writers
- **WAL checkpoint:** Every 10 minutes (TRUNCATE)
- **Auto-export:** Debounced JSON export to `data/db_export/`

## Migrations

Versioned SQL migrations in `scripts/maintenance/migrations/`. Auto-backup before migration (keeps last 5).

File extension is `.sqlite.sql` (not `.sql`) — the VS Code mssql extension flags SQLite-specific syntax (`CREATE INDEX IF NOT EXISTS`, partial indexes, `pragma_table_info`, `ALTER TABLE ... RENAME TO`) as T-SQL errors. `.vscode/settings.json` maps `**/*.sqlite.sql` to `plaintext` to bypass that. The runner (`utils/database/migrations.py`) accepts both `*.sqlite.sql` and legacy `*.sql` names.

| Migration | Purpose |
|---|---|
| 001_baseline.sqlite.sql | Initial schema (no-op marker) |
| 002_sync_defaults.sqlite.sql | Rebuild token_usage/conversation_summaries with correct defaults |
| 003_fix_user_facts.sqlite.sql | Rebuild user_facts with category NOT NULL, importance default 2 |
| 004_dashboard_columns.sqlite.sql | Verify dashboard thinking/mode/images + is_creator columns |
| 005_update_ai_provider_default.sqlite.sql | Documentation-only (no data mutation) |
| 006_drop_character_profiles.sqlite.sql | Drop unused dashboard_character_profiles table |
| 007_fix_token_usage_default.sqlite.sql | Rebuild token_usage with model DEFAULT 'claude-opus-4-6' |
| 008_fix_analytics_model_default.sqlite.sql | Documentation-only |
| 009_add_performance_indexes.sqlite.sql | Verification of performance indexes (actual DDL in init_schema) |
| 010_fix_dashboard_provider_default.sqlite.sql | Rebuild dashboard_conversations with ai_provider DEFAULT 'claude' |
| 011_fix_ai_analytics_default.sqlite.sql | Rebuild ai_analytics with model DEFAULT 'claude-opus-4-6' |
| 012_bump_default_model_opus_4_7.sqlite.sql | Bump default model to claude-opus-4-7 on token_usage + ai_analytics |
| 013_dashboard_pin_message.sqlite.sql | Record is_pinned column + partial index for dashboard_messages |
