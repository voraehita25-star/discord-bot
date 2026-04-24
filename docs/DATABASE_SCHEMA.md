# Database Schema Documentation

## Overview

โปรเจคใช้ SQLite 2 ฐานข้อมูล ทำงานใน WAL mode สำหรับ concurrency:

| Database          | Tables | Purpose                                         |
| ----------------- | ------ | ----------------------------------------------- |
| `bot_database.db` | 19     | Main database (AI, music, dashboard, analytics) |
| `ai_cache_l2.db`  | 1      | Persistent L2 cache (survives restarts)         |

Connection Pool: 32 concurrent connections, 16-slot reuse queue, 30s acquire timeout

---

## bot_database.db (19 Tables)

### AI Chat

#### ai_history

ประวัติการสนทนา AI ต่อ channel

| Column     | Type     | Constraints                      |
| ---------- | -------- | -------------------------------- |
| id         | INTEGER  | PRIMARY KEY AUTOINCREMENT        |
| local_id   | INTEGER  |                                  |
| channel_id | INTEGER  | NOT NULL                         |
| user_id    | INTEGER  |                                  |
| role       | TEXT     | NOT NULL, CHECK ('user','model') |
| content    | TEXT     | NOT NULL                         |
| message_id | INTEGER  |                                  |
| timestamp  | DATETIME | DEFAULT CURRENT_TIMESTAMP        |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP        |

Indexes: `idx_ai_history_channel(channel_id)`, `idx_ai_history_timestamp(channel_id, timestamp DESC)`, `idx_ai_history_local_id(channel_id, local_id)`, `idx_ai_history_user_id(user_id)`

#### ai_metadata

การตั้งค่า AI ต่อ channel

| Column             | Type     | Constraints               |
| ------------------ | -------- | ------------------------- |
| channel_id         | INTEGER  | PRIMARY KEY               |
| thinking_enabled   | BOOLEAN  | DEFAULT 1                 |
| system_instruction | TEXT     |                           |
| last_accessed      | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| created_at         | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at         | DATETIME | DEFAULT CURRENT_TIMESTAMP |

### Memory System

#### ai_long_term_memory

Long-term memory (RAG vector embeddings)

| Column     | Type     | Constraints               |
| ---------- | -------- | ------------------------- |
| id         | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| channel_id | INTEGER  |                           |
| content    | TEXT     | NOT NULL                  |
| embedding  | BLOB     | NOT NULL                  |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

#### user_facts

ข้อเท็จจริงเกี่ยวกับผู้ใช้ที่ AI จดจำ

| Column          | Type     | Constraints               |
| --------------- | -------- | ------------------------- |
| id              | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| user_id         | INTEGER  | NOT NULL                  |
| channel_id      | INTEGER  |                           |
| category        | TEXT     | NOT NULL                  |
| content         | TEXT     | NOT NULL                  |
| importance      | INTEGER  | DEFAULT 2                 |
| first_mentioned | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| last_confirmed  | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| mention_count   | INTEGER  | DEFAULT 1                 |
| confidence      | REAL     | DEFAULT 1.0               |
| source_message  | TEXT     |                           |
| is_active       | BOOLEAN  | DEFAULT 1                 |
| is_user_defined | BOOLEAN  | DEFAULT 0                 |
| created_at      | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_user_facts_user(user_id, is_active)`, `idx_user_facts_category(user_id, category)`

#### entity_memories

ข้อมูล entities (คน, สถานที่, สิ่งของ) ที่ AI จดจำ

| Column       | Type    | Constraints               |
| ------------ | ------- | ------------------------- |
| id           | INTEGER | PRIMARY KEY AUTOINCREMENT |
| name         | TEXT    | NOT NULL                  |
| entity_type  | TEXT    | NOT NULL                  |
| facts        | TEXT    | NOT NULL                  |
| channel_id   | INTEGER |                           |
| guild_id     | INTEGER |                           |
| confidence   | REAL    | DEFAULT 1.0               |
| source       | TEXT    | DEFAULT 'user'            |
| created_at   | REAL    | NOT NULL                  |
| updated_at   | REAL    | NOT NULL                  |
| access_count | INTEGER | DEFAULT 0                 |

UNIQUE: `(name, channel_id, guild_id)`
Indexes: `idx_entity_name(name)`, `idx_entity_type(entity_type)`, `idx_entity_channel(channel_id)`, `idx_entity_guild(guild_id)`

#### conversation_summaries

สรุปบทสนทนาจาก memory consolidation

| Column        | Type     | Constraints               |
| ------------- | -------- | ------------------------- |
| id            | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| channel_id    | INTEGER  | NOT NULL                  |
| user_id       | INTEGER  |                           |
| summary       | TEXT     | NOT NULL                  |
| key_topics    | TEXT     |                           |
| key_decisions | TEXT     |                           |
| start_time    | DATETIME |                           |
| end_time      | DATETIME |                           |
| message_count | INTEGER  |                           |
| created_at    | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Index: `idx_summaries_channel(channel_id)`

#### knowledge_entries

ฐานความรู้สำหรับ RAG search

| Column     | Type     | Constraints               |
| ---------- | -------- | ------------------------- |
| id         | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| domain     | TEXT     | NOT NULL                  |
| category   | TEXT     | NOT NULL                  |
| topic      | TEXT     | NOT NULL                  |
| content    | TEXT     | NOT NULL                  |
| games      | TEXT     | DEFAULT '[]'              |
| tags       | TEXT     | DEFAULT '[]'              |
| is_spoiler | BOOLEAN  | DEFAULT 0                 |
| confidence | REAL     | DEFAULT 1.0               |
| source     | TEXT     | DEFAULT 'official'        |
| embedding  | BLOB     |                           |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_knowledge_domain(domain)`, `idx_knowledge_category(category)`, `idx_knowledge_topic(domain, category, topic)`

### Dashboard

#### dashboard_conversations

| Column             | Type     | Constraints                 |
| ------------------ | -------- | --------------------------- |
| id                 | TEXT     | PRIMARY KEY                 |
| title              | TEXT     |                             |
| role_preset        | TEXT     | NOT NULL, DEFAULT 'general' |
| system_instruction | TEXT     |                             |
| thinking_enabled   | BOOLEAN  | DEFAULT 0                   |
| ai_provider        | TEXT     | DEFAULT 'gemini'            |
| created_at         | DATETIME | DEFAULT CURRENT_TIMESTAMP   |
| updated_at         | DATETIME | DEFAULT CURRENT_TIMESTAMP   |
| is_starred         | BOOLEAN  | DEFAULT 0                   |

Indexes: `idx_dashboard_conv_updated(updated_at DESC)`, `idx_dashboard_conv_starred(is_starred, updated_at DESC)`

#### dashboard_messages

| Column          | Type     | Constraints                                                  |
| --------------- | -------- | ------------------------------------------------------------ |
| id              | INTEGER  | PRIMARY KEY AUTOINCREMENT                                    |
| conversation_id | TEXT     | NOT NULL, FK → dashboard_conversations(id) ON DELETE CASCADE |
| role            | TEXT     | NOT NULL, CHECK ('user','assistant')                         |
| content         | TEXT     | NOT NULL                                                     |
| thinking        | TEXT     |                                                              |
| mode            | TEXT     |                                                              |
| images          | TEXT     |                                                              |
| created_at      | DATETIME | DEFAULT CURRENT_TIMESTAMP                                    |

Index: `idx_dashboard_msg_conv(conversation_id, created_at ASC)`

#### dashboard_user_profile

| Column       | Type     | Constraints                 |
| ------------ | -------- | --------------------------- |
| id           | INTEGER  | PRIMARY KEY, CHECK (id = 1) |
| display_name | TEXT     | DEFAULT 'User'              |
| bio          | TEXT     |                             |
| preferences  | TEXT     |                             |
| is_creator   | INTEGER  | DEFAULT 0                   |
| created_at   | DATETIME | DEFAULT CURRENT_TIMESTAMP   |
| updated_at   | DATETIME | DEFAULT CURRENT_TIMESTAMP   |

#### dashboard_memories

| Column     | Type     | Constraints               |
| ---------- | -------- | ------------------------- |
| id         | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| content    | TEXT     | NOT NULL                  |
| category   | TEXT     | DEFAULT 'general'         |
| importance | INTEGER  | DEFAULT 1                 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Index: `idx_dashboard_memories_category(category, importance DESC)`

### Guild & User

#### guild_settings

การตั้งค่าต่อ server

| Column                | Type     | Constraints               |
| --------------------- | -------- | ------------------------- |
| guild_id              | INTEGER  | PRIMARY KEY               |
| prefix                | TEXT     | DEFAULT '!'               |
| ai_enabled            | BOOLEAN  | DEFAULT 1                 |
| music_enabled         | BOOLEAN  | DEFAULT 1                 |
| auto_disconnect_delay | INTEGER  | DEFAULT 180               |
| mode_247              | BOOLEAN  | DEFAULT 0                 |
| created_at            | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| updated_at            | DATETIME | DEFAULT CURRENT_TIMESTAMP |

#### user_stats

สถิติการใช้งานต่อ user ต่อ guild

| Column          | Type     | Constraints               |
| --------------- | -------- | ------------------------- |
| user_id         | INTEGER  | NOT NULL                  |
| guild_id        | INTEGER  | NOT NULL                  |
| messages_count  | INTEGER  | DEFAULT 0                 |
| commands_count  | INTEGER  | DEFAULT 0                 |
| ai_interactions | INTEGER  | DEFAULT 0                 |
| music_requests  | INTEGER  | DEFAULT 0                 |
| last_active     | DATETIME | DEFAULT CURRENT_TIMESTAMP |
| created_at      | DATETIME | DEFAULT CURRENT_TIMESTAMP |

PRIMARY KEY: `(user_id, guild_id)`

### Music

#### music_queue

| Column   | Type     | Constraints               |
| -------- | -------- | ------------------------- |
| id       | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| guild_id | INTEGER  | NOT NULL                  |
| position | INTEGER  | NOT NULL                  |
| url      | TEXT     | NOT NULL                  |
| title    | TEXT     |                           |
| added_by | INTEGER  |                           |
| added_at | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Index: `idx_music_queue_guild(guild_id, position)`

### Analytics & Monitoring

#### ai_analytics

| Column           | Type     | Constraints               |
| ---------------- | -------- | ------------------------- |
| id               | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| user_id          | INTEGER  | NOT NULL                  |
| channel_id       | INTEGER  | NOT NULL                  |
| guild_id         | INTEGER  |                           |
| input_length     | INTEGER  |                           |
| output_length    | INTEGER  |                           |
| response_time_ms | REAL     |                           |
| intent           | TEXT     |                           |
| model            | TEXT     | DEFAULT 'gemini'          |
| tool_calls       | INTEGER  | DEFAULT 0                 |
| cache_hit        | BOOLEAN  | DEFAULT 0                 |
| error            | TEXT     |                           |
| created_at       | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_ai_analytics_user(user_id, created_at DESC)`, `idx_ai_analytics_guild(guild_id, created_at DESC)`

#### token_usage

| Column        | Type     | Constraints                      |
| ------------- | -------- | -------------------------------- |
| id            | INTEGER  | PRIMARY KEY AUTOINCREMENT        |
| user_id       | INTEGER  | NOT NULL                         |
| channel_id    | INTEGER  | NOT NULL                         |
| guild_id      | INTEGER  |                                  |
| input_tokens  | INTEGER  | NOT NULL                         |
| output_tokens | INTEGER  | NOT NULL                         |
| model         | TEXT     | DEFAULT 'claude-opus-4-7'        |
| cached        | BOOLEAN  | DEFAULT 0                        |
| created_at    | DATETIME | DEFAULT CURRENT_TIMESTAMP        |

Indexes: `idx_token_usage_user(user_id, created_at DESC)`, `idx_token_usage_channel(channel_id, created_at DESC)`, `idx_token_usage_guild(guild_id, created_at DESC)`

#### error_logs

| Column        | Type     | Constraints               |
| ------------- | -------- | ------------------------- |
| id            | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| error_type    | TEXT     | NOT NULL                  |
| error_message | TEXT     |                           |
| traceback     | TEXT     |                           |
| guild_id      | INTEGER  |                           |
| channel_id    | INTEGER  |                           |
| user_id       | INTEGER  |                           |
| command       | TEXT     |                           |
| created_at    | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_error_logs_type(error_type, created_at DESC)`, `idx_error_logs_created(created_at DESC)`

#### audit_log

| Column      | Type     | Constraints               |
| ----------- | -------- | ------------------------- |
| id          | INTEGER  | PRIMARY KEY AUTOINCREMENT |
| action_type | TEXT     | NOT NULL                  |
| guild_id    | INTEGER  |                           |
| user_id     | INTEGER  |                           |
| target_id   | INTEGER  |                           |
| details     | TEXT     |                           |
| created_at  | DATETIME | DEFAULT CURRENT_TIMESTAMP |

Indexes: `idx_audit_log_created(created_at DESC)`, `idx_audit_log_guild(guild_id)`, `idx_audit_log_guild_created(guild_id, created_at DESC)`

### System

#### schema_version

ติดตาม database migrations

| Column     | Type      | Constraints               |
| ---------- | --------- | ------------------------- |
| version    | INTEGER   | PRIMARY KEY               |
| filename   | TEXT      | NOT NULL                  |
| applied_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP |
| checksum   | TEXT      |                           |

---

## ai_cache_l2.db (1 Table)

### cache_entries

Persistent L2 cache — อุ่น L1 in-memory cache หลัง restart

| Column   | Type    | Constraints |
| -------- | ------- | ----------- |
| key      | TEXT    | PRIMARY KEY |
| response | TEXT    | NOT NULL    |
| intent   | TEXT    | DEFAULT ''  |
| norm_msg | TEXT    | DEFAULT ''  |
| ctx_hash | TEXT    | DEFAULT ''  |
| created  | REAL    | NOT NULL    |
| hits     | INTEGER | DEFAULT 0   |

Index: `idx_cache_created(created)`
Max entries: 20,000 (LRU eviction)

---

## Statistics

| Metric                 | Count                                            |
| ---------------------- | ------------------------------------------------ |
| Total tables           | 20                                               |
| Total indexes          | 33+                                              |
| Foreign keys           | 1 (dashboard_messages → dashboard_conversations) |
| Composite primary keys | 1 (user_stats)                                   |
| Unique constraints     | 1 (entity_memories)                              |
| WAL mode               | Both databases                                   |
