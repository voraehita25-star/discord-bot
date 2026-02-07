use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct DbStats {
    pub total_messages: i64,
    pub active_channels: i64,
    pub total_entities: i64,
    pub rag_memories: i64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ChannelInfo {
    pub channel_id: i64,
    pub message_count: i64,
    pub last_active: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UserInfo {
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
        let mut cache = self.conn_cache.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
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
            // Combined query for better performance - single query instead of 4
            let combined_query = r#"
                SELECT 
                    (SELECT COUNT(*) FROM ai_history),
                    (SELECT COUNT(DISTINCT channel_id) FROM ai_history),
                    (SELECT COUNT(*) FROM entity_memories),
                    (SELECT COUNT(*) FROM rag_memories)
            "#;
            
            if let Ok(row) = conn.query_row(combined_query, [], |row| {
                Ok((
                    row.get::<_, i64>(0).unwrap_or(0),
                    row.get::<_, i64>(1).unwrap_or(0),
                    row.get::<_, i64>(2).unwrap_or(0),
                    row.get::<_, i64>(3).unwrap_or(0),
                ))
            }) {
                stats.total_messages = row.0;
                stats.active_channels = row.1;
                stats.total_entities = row.2;
                stats.rag_memories = row.3;
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
                         WHERE role = 'user'
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
                .map(|count| count as i32)
                .map_err(|e| format!("Failed to clear history: {}", e))
            // Connection returned to cache automatically when guard drops
        } else {
            Err("Database not found".to_string())
        }
    }
}
