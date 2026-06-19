use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;

/// Serialize i64 as string to prevent JavaScript precision loss for Discord Snowflake IDs.
/// JS Number.MAX_SAFE_INTEGER = 2^53 - 1 = 9007199254740991, but Discord IDs exceed this.
fn serialize_i64_as_string<S: serde::Serializer>(val: &i64, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&val.to_string())
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct DbStats {
    pub total_messages: i64,
    pub active_channels: i64,
    pub total_entities: i64,
    pub rag_memories: i64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ChannelInfo {
    #[serde(serialize_with = "serialize_i64_as_string")]
    pub channel_id: i64,
    pub message_count: i64,
    pub last_active: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UserInfo {
    #[serde(serialize_with = "serialize_i64_as_string")]
    pub user_id: i64,
    pub message_count: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DashboardConversation {
    pub id: String,
    pub title: Option<String>,
    pub role_preset: String,
    pub thinking_enabled: bool,
    pub is_starred: bool,
    pub message_count: i64,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub ai_provider: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DashboardMessage {
    pub id: i64,
    pub role: String,
    pub content: String,
    pub created_at: String,
    pub images: Option<Vec<String>>,
    pub thinking: Option<String>,
    pub mode: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DashboardConversationDetail {
    pub conversation: DashboardConversation,
    pub messages: Vec<DashboardMessage>,
}

pub struct DatabaseService {
    db_path: PathBuf,
    /// Cached database connection for performance
    /// Wrapped in Mutex for thread-safe access
    conn_cache: Mutex<Option<Connection>>,
}

/// RAII guard that returns the connection to the cache on drop (even on panic)
struct ConnectionGuard<'a> {
    conn: Option<Connection>,
    cache: &'a Mutex<Option<Connection>>,
}

impl<'a> ConnectionGuard<'a> {
    fn conn(&self) -> &Connection {
        self.conn.as_ref().expect("ConnectionGuard used after take")
    }
}

impl<'a> Drop for ConnectionGuard<'a> {
    fn drop(&mut self) {
        if let Some(conn) = self.conn.take() {
            if let Ok(mut cache) = self.cache.lock() {
                *cache = Some(conn);
            }
        }
    }
}

/// Why a `get_connection()` call could not hand back a usable connection.
///
/// The previous design returned a bare `Option`, collapsing two very different
/// situations — "the DB file legitimately doesn't exist yet" and "the file is
/// there but SQLite failed to open it" — into the same `None`, which every
/// caller surfaced as the misleading "Database not found". Splitting them lets
/// callers branch (and surfaces a real open failure as a real error instead of
/// hiding it as a missing file).
#[derive(Debug)]
enum ConnectError {
    /// The database file does not exist on disk yet.
    Missing,
    /// The file exists but `Connection::open` failed (corruption, permissions,
    /// locked beyond the busy timeout, …).
    Open(rusqlite::Error),
}

impl std::fmt::Display for ConnectError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConnectError::Missing => write!(f, "Database not found"),
            ConnectError::Open(e) => write!(f, "Failed to open database: {}", e),
        }
    }
}

impl DatabaseService {
    pub fn new(db_path: PathBuf) -> Self {
        Self {
            db_path,
            conn_cache: Mutex::new(None),
        }
    }

    /// Get or create a cached database connection wrapped in RAII guard.
    /// The guard automatically returns the connection to cache on drop (even on
    /// panic).
    ///
    /// Returns [`ConnectError::Missing`] when the DB file doesn't exist yet, and
    /// [`ConnectError::Open`] when the file is present but SQLite can't open it —
    /// the two used to be conflated into a `None`/"Database not found", which hid
    /// genuine open failures behind a misleading message.
    fn get_connection(&self) -> Result<ConnectionGuard<'_>, ConnectError> {
        if !self.db_path.exists() {
            return Err(ConnectError::Missing);
        }

        // Try to take the cached connection
        let mut cache = self.conn_cache.lock().unwrap_or_else(|poisoned| {
            eprintln!("WARNING: Database connection cache mutex was poisoned, recovering");
            poisoned.into_inner()
        });
        if let Some(conn) = cache.take() {
            // Verify connection is still valid. Use query_row, NOT execute:
            // Connection::execute returns Err(ExecuteReturnedResults) for any
            // row-producing statement, so `execute("SELECT 1")` was ALWAYS Err
            // and the cached connection was discarded + reopened on every call
            // (the cache never hit). query_row succeeds for a healthy conn.
            if conn.query_row("SELECT 1", [], |_| Ok(())).is_ok() {
                return Ok(ConnectionGuard {
                    conn: Some(conn),
                    cache: &self.conn_cache,
                });
            }
        }

        // Create new connection if cache is empty or invalid. A real open
        // failure here (corruption/permissions/lock) is surfaced as
        // ConnectError::Open rather than swallowed as a missing file.
        match Connection::open(&self.db_path) {
            Ok(conn) => {
                // The bot opens this same DB in WAL mode and periodically runs
                // PRAGMA wal_checkpoint(TRUNCATE), which briefly takes the write
                // lock. rusqlite's default busy timeout is 0 (fail immediately),
                // so dashboard writes (clear/delete history) would intermittently
                // fail with SQLITE_BUSY ("database is locked") for no real fault.
                // Wait up to 5s for the lock instead. busy_timeout is
                // per-connection and persists across cached reuse (same
                // Connection object).
                let _ = conn.busy_timeout(std::time::Duration::from_secs(5));
                Ok(ConnectionGuard {
                    conn: Some(conn),
                    cache: &self.conn_cache,
                })
            }
            Err(e) => Err(ConnectError::Open(e)),
        }
    }

    pub fn get_stats(&self) -> Result<DbStats, String> {
        let mut stats = DbStats::default();

        // A not-yet-created DB is an empty state, not an error: a fresh install
        // opening the Database tab should see zeroes + "no data", NOT a red error
        // toast. Only a real open failure (ConnectError::Open) surfaces as Err.
        let guard = match self.get_connection() {
            Ok(guard) => guard,
            Err(ConnectError::Missing) => return Ok(DbStats::default()),
            Err(e @ ConnectError::Open(_)) => return Err(e.to_string()),
        };
        let conn = guard.conn();

        // Query ai_history stats (always exists) — propagate failure rather than
        // silently returning zeroed stats, which made a missing/locked DB look
        // like an empty one.
        let row = conn
            .query_row(
                "SELECT COUNT(*), COUNT(DISTINCT channel_id) FROM ai_history",
                [],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
            )
            .map_err(|e| format!("Failed to query ai_history stats: {}", e))?;
        stats.total_messages = row.0;
        stats.active_channels = row.1;

        // Query entity_memories (may not exist in older schemas) — keep the
        // graceful fallback: a missing table here is expected, not an error.
        if let Ok(count) = conn.query_row("SELECT COUNT(*) FROM entity_memories", [], |row| {
            row.get::<_, i64>(0)
        }) {
            stats.total_entities = count;
        }

        // Query RAG memories — ai_long_term_memory is the actual RAG memory table,
        // knowledge_entries is structured knowledge (fallback for backward compatibility).
        // Both are optional in older schemas, so a miss stays graceful.
        if let Ok(count) = conn.query_row("SELECT COUNT(*) FROM ai_long_term_memory", [], |row| {
            row.get::<_, i64>(0)
        }) {
            stats.rag_memories = count;
        } else if let Ok(count) =
            conn.query_row("SELECT COUNT(*) FROM knowledge_entries", [], |row| {
                row.get::<_, i64>(0)
            })
        {
            stats.rag_memories = count;
        }
        // Connection returned to cache automatically when guard drops

        Ok(stats)
    }

    pub fn get_recent_channels(&self, limit: i32) -> Result<Vec<ChannelInfo>, String> {
        // A missing DB is an empty state, not an error (see get_stats): return an
        // empty list so a fresh install shows "no data", not a red error toast.
        // Only a real open failure surfaces as Err.
        let guard = match self.get_connection() {
            Ok(guard) => guard,
            Err(ConnectError::Missing) => return Ok(vec![]),
            Err(e @ ConnectError::Open(_)) => return Err(e.to_string()),
        };
        let conn = guard.conn();
        let query = "SELECT channel_id, COUNT(*) as cnt, MAX(COALESCE(datetime(timestamp), timestamp)) as last_ts
                     FROM ai_history
                     GROUP BY channel_id
                     ORDER BY last_ts DESC
                     LIMIT ?";

        let mut stmt = conn
            .prepare(query)
            .map_err(|e| format!("Failed to prepare recent channels query: {}", e))?;
        let rows = stmt
            .query_map([limit], |row| {
                Ok(ChannelInfo {
                    channel_id: row.get(0)?,
                    message_count: row.get(1)?,
                    last_active: row.get::<_, String>(2).unwrap_or_default(),
                })
            })
            .map_err(|e| format!("Failed to query recent channels: {}", e))?;

        // Skip a malformed row instead of aborting the whole panel — graceful
        // degradation, consistent with get_dashboard_conversations/messages.
        let channels: Vec<ChannelInfo> = rows.filter_map(|r| r.ok()).collect();
        // Connection returned to cache automatically when guard drops

        Ok(channels)
    }

    pub fn get_top_users(&self, limit: i32) -> Result<Vec<UserInfo>, String> {
        // A missing DB is an empty state, not an error (see get_stats): return an
        // empty list so a fresh install shows "no data", not a red error toast.
        // Only a real open failure surfaces as Err.
        let guard = match self.get_connection() {
            Ok(guard) => guard,
            Err(ConnectError::Missing) => return Ok(vec![]),
            Err(e @ ConnectError::Open(_)) => return Err(e.to_string()),
        };
        let conn = guard.conn();
        let query = "SELECT user_id, COUNT(*) as cnt
                     FROM ai_history
                     WHERE role = 'user' AND user_id IS NOT NULL
                     GROUP BY user_id
                     ORDER BY cnt DESC
                     LIMIT ?";

        let mut stmt = conn
            .prepare(query)
            .map_err(|e| format!("Failed to prepare top users query: {}", e))?;
        let rows = stmt
            .query_map([limit], |row| {
                Ok(UserInfo {
                    user_id: row.get(0)?,
                    message_count: row.get(1)?,
                })
            })
            .map_err(|e| format!("Failed to query top users: {}", e))?;

        // Skip a malformed row instead of aborting the whole panel — graceful
        // degradation, consistent with get_dashboard_conversations/messages.
        let users: Vec<UserInfo> = rows.filter_map(|r| r.ok()).collect();
        // Connection returned to cache automatically when guard drops

        Ok(users)
    }

    pub fn clear_history(&self) -> Result<i32, String> {
        // Same `?`-based shape as the read paths: a missing DB or a real open
        // failure both flow through ConnectError's Display (the latter is no
        // longer swallowed as "Database not found").
        let guard = self.get_connection().map_err(|e| e.to_string())?;
        let conn = guard.conn();
        conn.execute("DELETE FROM ai_history", [])
            .map(|count| count.min(i32::MAX as usize) as i32)
            .map_err(|e| format!("Failed to clear history: {}", e))
        // Connection returned to cache automatically when guard drops
    }

    /// Delete history for specific channel IDs
    pub fn delete_channels_history(&self, channel_ids: &[i64]) -> Result<i32, String> {
        if channel_ids.is_empty() {
            return Ok(0);
        }
        // Same `?`-based shape as the read paths (see clear_history): distinguish
        // a missing DB from a real open failure via ConnectError's Display.
        let guard = self.get_connection().map_err(|e| e.to_string())?;
        let conn = guard.conn();
        // Build parameterized IN clause
        let placeholders: Vec<String> = channel_ids.iter().map(|_| "?".to_string()).collect();
        let query = format!(
            "DELETE FROM ai_history WHERE channel_id IN ({})",
            placeholders.join(",")
        );
        let params: Vec<Box<dyn rusqlite::types::ToSql>> = channel_ids
            .iter()
            .map(|id| Box::new(*id) as Box<dyn rusqlite::types::ToSql>)
            .collect();
        let param_refs: Vec<&dyn rusqlite::types::ToSql> =
            params.iter().map(|p| p.as_ref()).collect();
        conn.execute(&query, param_refs.as_slice())
            .map(|count| count.min(i32::MAX as usize) as i32)
            .map_err(|e| format!("Failed to delete channel history: {}", e))
    }

    pub fn get_dashboard_conversations(
        &self,
        limit: i32,
    ) -> Result<Vec<DashboardConversation>, String> {
        // A not-yet-created DB is an empty state, not an error — match get_stats/
        // get_recent_channels/get_top_users so a fresh install shows an empty
        // conversation list instead of a red "Database not found" toast while the
        // sibling panels render cleanly. Only a real open failure surfaces as Err.
        let guard = match self.get_connection() {
            Ok(guard) => guard,
            Err(ConnectError::Missing) => return Ok(vec![]),
            Err(e @ ConnectError::Open(_)) => return Err(e.to_string()),
        };
        let conn = guard.conn();
        let mut conversations = Vec::new();

        let query = r#"
            SELECT c.id,
                   c.title,
                   c.role_preset,
                   c.thinking_enabled,
                   c.is_starred,
                   c.created_at,
                   c.updated_at,
                   c.ai_provider,
                   (SELECT COUNT(*) FROM dashboard_messages WHERE conversation_id = c.id) AS message_count
            FROM dashboard_conversations c
            ORDER BY c.is_starred DESC, c.updated_at DESC
            LIMIT ?
        "#;

        let mut stmt = conn
            .prepare(query)
            .map_err(|e| format!("Failed to prepare dashboard conversation query: {}", e))?;

        let rows = stmt
            .query_map([limit], |row| {
                // Defensive mapping: the non-nullable columns (id, role_preset)
                // SHOULD never be NULL, but a single malformed/legacy row that
                // violates that would make a bare `row.get(N)?` return Err and
                // abort the ENTIRE conversation list (the collect-loop below
                // propagates the first row error). Fall back to a default so one
                // bad row degrades to a blank field instead of blanking the
                // whole list — consistent with the thinking_enabled/is_starred/
                // created_at/message_count columns already handled this way. The
                // genuinely nullable columns (title/updated_at/ai_provider) stay
                // `?`, which already maps SQL NULL -> None without erroring.
                Ok(DashboardConversation {
                    id: row.get::<_, String>(0).unwrap_or_default(),
                    title: row.get(1)?,
                    role_preset: row.get::<_, String>(2).unwrap_or_default(),
                    thinking_enabled: row.get::<_, i64>(3).unwrap_or(0) != 0,
                    is_starred: row.get::<_, i64>(4).unwrap_or(0) != 0,
                    created_at: row.get::<_, String>(5).unwrap_or_default(),
                    updated_at: row.get(6)?,
                    ai_provider: row.get(7)?,
                    message_count: row.get::<_, i64>(8).unwrap_or(0),
                })
            })
            .map_err(|e| format!("Failed to query dashboard conversations: {}", e))?;

        for row in rows {
            conversations.push(
                row.map_err(|e| format!("Failed to read dashboard conversation row: {}", e))?,
            );
        }

        Ok(conversations)
    }

    pub fn get_dashboard_conversation_detail(
        &self,
        conversation_id: &str,
    ) -> Result<Option<DashboardConversationDetail>, String> {
        // A missing DB means "no such conversation", not an error — return Ok(None)
        // (the same shape a real not-found returns) so a fresh install doesn't
        // surface "Database not found". Consistent with get_dashboard_conversations
        // and the get_stats sibling policy; a real open failure still errors.
        let guard = match self.get_connection() {
            Ok(guard) => guard,
            Err(ConnectError::Missing) => return Ok(None),
            Err(e @ ConnectError::Open(_)) => return Err(e.to_string()),
        };
        let conn = guard.conn();

        let conversation_query = r#"
            SELECT c.id,
                   c.title,
                   c.role_preset,
                   c.thinking_enabled,
                   c.is_starred,
                   c.created_at,
                   c.updated_at,
                   c.ai_provider,
                   (SELECT COUNT(*) FROM dashboard_messages WHERE conversation_id = c.id) AS message_count
            FROM dashboard_conversations c
            WHERE c.id = ?
        "#;

        let conversation = match conn.query_row(conversation_query, [conversation_id], |row| {
            // Same defensive mapping as get_dashboard_conversations: don't let a
            // single NULL/malformed non-nullable column turn into a hard error.
            Ok(DashboardConversation {
                id: row.get::<_, String>(0).unwrap_or_default(),
                title: row.get(1)?,
                role_preset: row.get::<_, String>(2).unwrap_or_default(),
                thinking_enabled: row.get::<_, i64>(3).unwrap_or(0) != 0,
                is_starred: row.get::<_, i64>(4).unwrap_or(0) != 0,
                created_at: row.get::<_, String>(5).unwrap_or_default(),
                updated_at: row.get(6)?,
                ai_provider: row.get(7)?,
                message_count: row.get::<_, i64>(8).unwrap_or(0),
            })
        }) {
            Ok(conversation) => conversation,
            Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(None),
            Err(e) => return Err(format!("Failed to load dashboard conversation: {}", e)),
        };

        let mut stmt = conn
            .prepare(
                r#"
                SELECT id, role, content, created_at, images, thinking, mode
                FROM dashboard_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, id ASC
            "#,
            )
            .map_err(|e| format!("Failed to prepare dashboard message query: {}", e))?;

        let rows = stmt
            .query_map([conversation_id], |row| {
                let images_json: Option<String> = row.get(4)?;
                let images = images_json.as_deref().and_then(|raw| {
                    // Distinguish "no images column" (None, silent) from
                    // "present-but-unparseable" (logged) so corrupted-image rows
                    // aren't silently indistinguishable from image-less ones.
                    match serde_json::from_str::<Vec<String>>(raw) {
                        Ok(v) => Some(v),
                        Err(e) => {
                            eprintln!(
                                "WARNING: malformed images JSON for dashboard message: {}",
                                e
                            );
                            None
                        }
                    }
                });

                // Defensive mapping (mirrors the conversation rows above): a
                // single malformed message row shouldn't abort the whole thread.
                // id/role/content SHOULD be NOT NULL; fall back to defaults so a
                // bad row degrades gracefully rather than failing the collect.
                Ok(DashboardMessage {
                    id: row.get::<_, i64>(0).unwrap_or_default(),
                    role: row.get::<_, String>(1).unwrap_or_default(),
                    content: row.get::<_, String>(2).unwrap_or_default(),
                    created_at: row.get::<_, String>(3).unwrap_or_default(),
                    images,
                    thinking: row.get(5)?,
                    mode: row.get(6)?,
                })
            })
            .map_err(|e| format!("Failed to query dashboard messages: {}", e))?;

        let mut messages = Vec::new();
        for row in rows {
            messages.push(row.map_err(|e| format!("Failed to read dashboard message row: {}", e))?);
        }

        Ok(Some(DashboardConversationDetail {
            conversation,
            messages,
        }))
    }
}

// ============================================================================
// Unit tests for the DB read/write policy. Uses the bundled SQLite (rusqlite
// `bundled` feature) + a tempfile-backed DB file so each test gets an isolated
// on-disk database the `DatabaseService` opens through its normal path. Run
// with `cargo test`.
// ============================================================================
#[cfg(test)]
mod tests {
    use super::*;

    /// Create the minimal `ai_history` schema the dashboard queries against,
    /// matching the bot's definition in `utils/database/database.py`. `STRICT`
    /// is intentionally NOT used so a test can insert a type-mismatched value
    /// (see the row-degradation test).
    fn create_ai_history(conn: &Connection) {
        conn.execute_batch(
            "CREATE TABLE ai_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_id INTEGER,
                channel_id INTEGER NOT NULL,
                user_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                message_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                summarized_at DATETIME
            );",
        )
        .expect("create ai_history");
    }

    /// A `DatabaseService` pointing at a fresh `bot_database.db` inside a temp
    /// dir, with the connection already created (`f` runs the schema/seed). The
    /// `TempDir` is returned so it outlives the service.
    fn service_with_db(f: impl FnOnce(&Connection)) -> (tempfile::TempDir, DatabaseService) {
        let dir = tempfile::tempdir().expect("tempdir");
        let db_path = dir.path().join("bot_database.db");
        {
            let conn = Connection::open(&db_path).expect("open db");
            f(&conn);
        }
        (dir, DatabaseService::new(db_path))
    }

    // ------- ConnectError::Missing policy (#3): benign empty state, not Err ----

    #[test]
    fn missing_db_yields_default_stats_not_error() {
        let dir = tempfile::tempdir().expect("tempdir");
        // Point at a file that was never created.
        let svc = DatabaseService::new(dir.path().join("does_not_exist.db"));
        let stats = svc.get_stats().expect("missing DB must not error");
        assert_eq!(stats.total_messages, 0);
        assert_eq!(stats.active_channels, 0);
        assert_eq!(stats.total_entities, 0);
        assert_eq!(stats.rag_memories, 0);
    }

    #[test]
    fn missing_db_yields_empty_lists_not_error() {
        let dir = tempfile::tempdir().expect("tempdir");
        let svc = DatabaseService::new(dir.path().join("does_not_exist.db"));
        assert!(svc.get_recent_channels(10).expect("no error").is_empty());
        assert!(svc.get_top_users(10).expect("no error").is_empty());
    }

    // Regression (audit dash-rust-4): the dashboard-conversation read paths used
    // to surface a missing DB as Err("Database not found") while the sibling
    // panels treated it as empty state. They must now match the siblings: an
    // empty list and Ok(None), NOT an Err.
    #[test]
    fn missing_db_yields_empty_conversations_not_error() {
        let dir = tempfile::tempdir().expect("tempdir");
        let svc = DatabaseService::new(dir.path().join("does_not_exist.db"));
        assert!(
            svc.get_dashboard_conversations(50)
                .expect("missing DB must not error for conversations")
                .is_empty(),
            "missing DB should yield an empty conversation list, not an error",
        );
    }

    #[test]
    fn missing_db_yields_none_conversation_detail_not_error() {
        let dir = tempfile::tempdir().expect("tempdir");
        let svc = DatabaseService::new(dir.path().join("does_not_exist.db"));
        assert!(
            svc.get_dashboard_conversation_detail("any-id")
                .expect("missing DB must not error for detail")
                .is_none(),
            "missing DB should yield Ok(None) for a conversation detail, not an error",
        );
    }

    // ------- get_stats returns 0 on an empty (but present) ai_history (#2) -----

    #[test]
    fn get_stats_is_zero_when_ai_history_empty() {
        let (_dir, svc) = service_with_db(create_ai_history);
        let stats = svc.get_stats().expect("stats");
        assert_eq!(stats.total_messages, 0);
        assert_eq!(stats.active_channels, 0);
    }

    #[test]
    fn get_stats_counts_messages_and_channels() {
        let (_dir, svc) = service_with_db(|conn| {
            create_ai_history(conn);
            conn.execute_batch(
                "INSERT INTO ai_history (channel_id, user_id, role, content) VALUES
                    (100, 1, 'user', 'a'),
                    (100, 2, 'model', 'b'),
                    (200, 1, 'user', 'c');",
            )
            .expect("seed");
        });
        let stats = svc.get_stats().expect("stats");
        assert_eq!(stats.total_messages, 3);
        assert_eq!(stats.active_channels, 2);
    }

    // ------- malformed row degrades to skip, doesn't abort the list (#3) -------

    #[test]
    fn recent_channels_skips_malformed_row_keeps_good_ones() {
        let (_dir, svc) = service_with_db(|conn| {
            create_ai_history(conn);
            // One healthy channel...
            conn.execute(
                "INSERT INTO ai_history (channel_id, user_id, role, content) VALUES (100, 1, 'user', 'a')",
                [],
            )
            .expect("seed good");
            // ...and one row whose channel_id holds a TEXT value that cannot be
            // read as i64. INTEGER affinity stores a non-numeric string verbatim,
            // so `row.get::<_, i64>(0)` errors for this group and filter_map skips
            // it instead of aborting the whole query.
            conn.execute(
                "INSERT INTO ai_history (channel_id, user_id, role, content) VALUES ('not_a_number', 2, 'user', 'b')",
                [],
            )
            .expect("seed bad");
        });
        let channels = svc.get_recent_channels(10).expect("recent channels");
        assert_eq!(channels.len(), 1, "malformed group should be skipped");
        assert_eq!(channels[0].channel_id, 100);
    }

    // ------- delete_channels_history: parameterized bind + scope (#4) ----------

    #[test]
    fn delete_channels_history_only_deletes_targeted_channels() {
        let (_dir, svc) = service_with_db(|conn| {
            create_ai_history(conn);
            conn.execute_batch(
                "INSERT INTO ai_history (channel_id, user_id, role, content) VALUES
                    (100, 1, 'user', 'a'),
                    (100, 1, 'user', 'b'),
                    (200, 1, 'user', 'c');",
            )
            .expect("seed");
        });
        let deleted = svc.delete_channels_history(&[100]).expect("delete");
        assert_eq!(deleted, 2, "both channel-100 rows removed");
        // Channel 200 untouched.
        let stats = svc.get_stats().expect("stats");
        assert_eq!(stats.total_messages, 1);
        assert_eq!(stats.active_channels, 1);
    }

    #[test]
    fn delete_channels_history_empty_input_is_noop() {
        let (_dir, svc) = service_with_db(|conn| {
            create_ai_history(conn);
            conn.execute(
                "INSERT INTO ai_history (channel_id, user_id, role, content) VALUES (100, 1, 'user', 'a')",
                [],
            )
            .expect("seed");
        });
        assert_eq!(svc.delete_channels_history(&[]).expect("noop"), 0);
        assert_eq!(svc.get_stats().expect("stats").total_messages, 1);
    }

    #[test]
    fn delete_channels_history_binds_ids_as_params_not_sql() {
        // The signature takes `&[i64]`, so a string like "100 OR 1=1" can never
        // reach the query — it wouldn't parse to i64 upstream. This asserts the
        // bound integer matches ONLY that channel and the IN-clause expansion is
        // value-parameterized (no other channel is collaterally deleted).
        let (_dir, svc) = service_with_db(|conn| {
            create_ai_history(conn);
            conn.execute_batch(
                "INSERT INTO ai_history (channel_id, user_id, role, content) VALUES
                    (100, 1, 'user', 'a'),
                    (999, 1, 'user', 'b');",
            )
            .expect("seed");
        });
        // Deleting a channel id that exists removes exactly its rows; the other
        // channel survives, proving the id was bound as a parameter (an injected
        // `OR 1=1` would have wiped both).
        let deleted = svc.delete_channels_history(&[100]).expect("delete");
        assert_eq!(deleted, 1);
        assert_eq!(svc.get_stats().expect("stats").total_messages, 1);
        // And the surviving row is channel 999.
        let channels = svc.get_recent_channels(10).expect("recent");
        assert_eq!(channels.len(), 1);
        assert_eq!(channels[0].channel_id, 999);
    }
}
