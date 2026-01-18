use rusqlite::{Connection, Result as SqliteResult};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

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
}

impl DatabaseService {
    pub fn new(db_path: PathBuf) -> Self {
        Self { db_path }
    }

    fn connect(&self) -> Option<Connection> {
        if !self.db_path.exists() {
            return None;
        }
        Connection::open(&self.db_path).ok()
    }

    pub fn get_stats(&self) -> DbStats {
        let mut stats = DbStats::default();
        
        if let Some(conn) = self.connect() {
            stats.total_messages = self.query_count(&conn, "SELECT COUNT(*) FROM ai_history").unwrap_or(0);
            stats.active_channels = self.query_count(&conn, "SELECT COUNT(DISTINCT channel_id) FROM ai_history").unwrap_or(0);
            stats.total_entities = self.query_count(&conn, "SELECT COUNT(*) FROM entity_memories").unwrap_or(0);
            stats.rag_memories = self.query_count(&conn, "SELECT COUNT(*) FROM rag_memories").unwrap_or(0);
        }
        
        stats
    }

    fn query_count(&self, conn: &Connection, query: &str) -> SqliteResult<i64> {
        conn.query_row(query, [], |row| row.get(0))
    }

    pub fn get_recent_channels(&self, limit: i32) -> Vec<ChannelInfo> {
        let mut channels = Vec::new();
        
        if let Some(conn) = self.connect() {
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
        }
        
        channels
    }

    pub fn get_top_users(&self, limit: i32) -> Vec<UserInfo> {
        let mut users = Vec::new();
        
        if let Some(conn) = self.connect() {
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
        }
        
        users
    }

    pub fn clear_history(&self) -> Result<i32, String> {
        if let Some(conn) = self.connect() {
            conn.execute("DELETE FROM ai_history", [])
                .map(|count| count as i32)
                .map_err(|e| format!("Failed to clear history: {}", e))
        } else {
            Err("Database not found".to_string())
        }
    }
}
