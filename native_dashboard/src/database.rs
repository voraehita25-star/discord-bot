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

impl DatabaseService {
    pub fn new(db_path: PathBuf) -> Self {
        Self { 
            db_path,
            conn_cache: Mutex::new(None),
        }
    }

    /// Get or create a cached database connection wrapped in RAII guard
    /// The guard automatically returns the connection to cache on drop (even on panic)
    fn get_connection(&self) -> Option<ConnectionGuard<'_>> {
        if !self.db_path.exists() {
            return None;
        }
        
        // Try to take the cached connection
        let mut cache = self.conn_cache.lock().unwrap_or_else(|poisoned| {
            eprintln!("WARNING: Database connection cache mutex was poisoned, recovering");
            poisoned.into_inner()
        });
        if let Some(conn) = cache.take() {
            // Verify connection is still valid
            if conn.execute("SELECT 1", []).is_ok() {
                return Some(ConnectionGuard { conn: Some(conn), cache: &self.conn_cache });
            }
        }
        
        // Create new connection if cache is empty or invalid
        Connection::open(&self.db_path).ok().map(|conn| {
            ConnectionGuard { conn: Some(conn), cache: &self.conn_cache }
        })
    }

    pub fn get_stats(&self) -> DbStats {
        let mut stats = DbStats::default();
        
        if let Some(guard) = self.get_connection() {
            let conn = guard.conn();
            
            // Query ai_history stats (always exists)
            if let Ok(row) = conn.query_row(
                "SELECT COUNT(*), COUNT(DISTINCT channel_id) FROM ai_history",
                [],
                |row| Ok((row.get::<_, i64>(0).unwrap_or(0), row.get::<_, i64>(1).unwrap_or(0)))
            ) {
                stats.total_messages = row.0;
                stats.active_channels = row.1;
            }
            
            // Query entity_memories (may not exist in older schemas)
            if let Ok(count) = conn.query_row(
                "SELECT COUNT(*) FROM entity_memories", [], |row| row.get::<_, i64>(0)
            ) {
                stats.total_entities = count;
            }
            
            // Query RAG memories — ai_long_term_memory is the actual RAG memory table,
            // knowledge_entries is structured knowledge (fallback for backward compatibility)
            for table in &["ai_long_term_memory", "knowledge_entries"] {
                if let Ok(count) = conn.query_row(
                    &format!("SELECT COUNT(*) FROM [{}]", table), [], |row| row.get::<_, i64>(0)
                ) {
                    stats.rag_memories = count;
                    break;
                }
            }
            // Connection returned to cache automatically when guard drops
        }
        
        stats
    }

    pub fn get_recent_channels(&self, limit: i32) -> Vec<ChannelInfo> {
        let mut channels = Vec::new();
        
        if let Some(guard) = self.get_connection() {
            let conn = guard.conn();
            let query = "SELECT channel_id, COUNT(*) as cnt, MAX(timestamp) as last_ts 
                         FROM ai_history 
                         GROUP BY channel_id 
                         ORDER BY last_ts DESC 
                         LIMIT ?";
            
            if let Ok(mut stmt) = conn.prepare(query) {
                if let Ok(rows) = stmt.query_map([limit], |row| {
                    Ok(ChannelInfo {
                        channel_id: row.get(0)?,
                        message_count: row.get(1)?,
                        last_active: row.get::<_, String>(2).unwrap_or_default(),
                    })
                }) {
                    channels = rows.filter_map(|r| r.ok()).collect();
                }
            }
            // Connection returned to cache automatically when guard drops
        }
        
        channels
    }

    pub fn get_top_users(&self, limit: i32) -> Vec<UserInfo> {
        let mut users = Vec::new();
        
        if let Some(guard) = self.get_connection() {
            let conn = guard.conn();
            let query = "SELECT user_id, COUNT(*) as cnt 
                         FROM ai_history 
                         WHERE role = 'user' AND user_id IS NOT NULL
                         GROUP BY user_id 
                         ORDER BY cnt DESC 
                         LIMIT ?";
            
            if let Ok(mut stmt) = conn.prepare(query) {
                if let Ok(rows) = stmt.query_map([limit], |row| {
                    Ok(UserInfo {
                        user_id: row.get(0)?,
                        message_count: row.get(1)?,
                    })
                }) {
                    users = rows.filter_map(|r| r.ok()).collect();
                }
            }
            // Connection returned to cache automatically when guard drops
        }
        
        users
    }

    pub fn clear_history(&self) -> Result<i32, String> {
        if let Some(guard) = self.get_connection() {
            let conn = guard.conn();
            conn.execute("DELETE FROM ai_history", [])
                .map(|count| count.min(i32::MAX as usize) as i32)
                .map_err(|e| format!("Failed to clear history: {}", e))
            // Connection returned to cache automatically when guard drops
        } else {
            Err("Database not found".to_string())
        }
    }

    /// Delete history for specific channel IDs
    pub fn delete_channels_history(&self, channel_ids: &[i64]) -> Result<i32, String> {
        if channel_ids.is_empty() {
            return Ok(0);
        }
        if let Some(guard) = self.get_connection() {
            let conn = guard.conn();
            // Build parameterized IN clause
            let placeholders: Vec<String> = channel_ids.iter().map(|_| "?".to_string()).collect();
            let query = format!("DELETE FROM ai_history WHERE channel_id IN ({})", placeholders.join(","));
            let params: Vec<Box<dyn rusqlite::types::ToSql>> = channel_ids
                .iter()
                .map(|id| Box::new(*id) as Box<dyn rusqlite::types::ToSql>)
                .collect();
            let param_refs: Vec<&dyn rusqlite::types::ToSql> = params.iter().map(|p| p.as_ref()).collect();
            conn.execute(&query, param_refs.as_slice())
                .map(|count| count.min(i32::MAX as usize) as i32)
                .map_err(|e| format!("Failed to delete channel history: {}", e))
        } else {
            Err("Database not found".to_string())
        }
    }
}
