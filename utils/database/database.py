"""
Database Module for Discord Bot (Async Version)
Provides async SQLite database connection using aiosqlite.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

# Database file path
DB_DIR = Path("data")
DB_FILE = DB_DIR / "bot_database.db"
EXPORT_DIR = DB_DIR / "db_export"

# Ensure data directories exist
DB_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)


class Database:
    """Async SQLite Database Manager using aiosqlite."""

    _instance: Database | None = None

    def __new__(cls) -> Database:
        """Singleton pattern - only one database instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize database settings."""
        if self._initialized:
            return

        self._initialized = True
        self.db_path = str(DB_FILE)
        self._schema_initialized = False
        self._export_pending = False
        self._export_delay = 3  # seconds
        # Track multiple export tasks to prevent task destruction warnings
        self._export_tasks: set[asyncio.Task] = set()
        # Connection pool semaphore - increased for high-performance machines
        self._pool_semaphore = asyncio.Semaphore(50)  # Max 50 concurrent connections
        self._connection_count = 0
        logging.info("💾 Async Database manager created: %s (pool=50)", self.db_path)

    def _schedule_export(self, channel_id: int | None = None) -> None:
        """Schedule a debounced export with retry logic (non-blocking)."""
        if self._export_pending:
            return

        self._export_pending = True
        max_retries = 3

        async def do_export():
            await asyncio.sleep(self._export_delay)
            self._export_pending = False

            for attempt in range(max_retries):
                try:
                    if channel_id:
                        await self.export_channel_to_json(channel_id)
                    else:
                        await self.export_to_json()
                    return  # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        logging.warning(
                            "Auto-export attempt %d/%d failed: %s. Retrying...",
                            attempt + 1,
                            max_retries,
                            e,
                        )
                        await asyncio.sleep(2**attempt)  # Exponential backoff
                    else:
                        logging.error("Auto-export failed after %d attempts: %s", max_retries, e)

        # Create and track the task
        task = asyncio.create_task(do_export())
        self._export_tasks.add(task)
        # Auto-remove task when done
        task.add_done_callback(self._export_tasks.discard)

    async def flush_pending_exports(self) -> None:
        """Flush any pending exports immediately (call during shutdown).

        This ensures data is exported before the bot shuts down,
        bypassing the debounce delay and properly cancelling pending tasks.
        """
        # Cancel all pending export tasks to prevent "Task was destroyed" warning
        for task in list(self._export_tasks):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # Expected when we cancel the task
        self._export_tasks.clear()

        if self._export_pending:
            logging.info("💾 Flushing pending database exports...")
            self._export_pending = False
            try:
                await self.export_to_json()
                logging.info("💾 Database export completed during shutdown")
            except Exception as e:
                logging.error("Failed to export during shutdown: %s", e)

    async def init_schema(self) -> None:
        """Initialize database schema (call once at startup)."""
        if self._schema_initialized:
            return

        async with self.get_connection() as conn:
            # AI Chat History Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    local_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'model')),
                    content TEXT NOT NULL,
                    message_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ai_history_channel
                ON ai_history(channel_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ai_history_timestamp
                ON ai_history(channel_id, timestamp DESC)
            """)

            # AI Session Metadata Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_metadata (
                    channel_id INTEGER PRIMARY KEY,
                    thinking_enabled BOOLEAN DEFAULT 1,
                    system_instruction TEXT,
                    last_accessed DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Guild Settings Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    prefix TEXT DEFAULT '!',
                    ai_enabled BOOLEAN DEFAULT 1,
                    music_enabled BOOLEAN DEFAULT 1,
                    auto_disconnect_delay INTEGER DEFAULT 180,
                    mode_247 BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # User Statistics Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    messages_count INTEGER DEFAULT 0,
                    commands_count INTEGER DEFAULT 0,
                    ai_interactions INTEGER DEFAULT 0,
                    music_requests INTEGER DEFAULT 0,
                    last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)

            # Music Queue Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS music_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    added_by INTEGER,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_music_queue_guild
                ON music_queue(guild_id, position)
            """)

            # Error Log Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_type TEXT NOT NULL,
                    error_message TEXT,
                    traceback TEXT,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    user_id INTEGER,
                    command TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # RAG Memory Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Audit Log Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    guild_id INTEGER,
                    user_id INTEGER,
                    target_id INTEGER,
                    details TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # AI Analytics Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER,
                    input_length INTEGER,
                    output_length INTEGER,
                    response_time_ms REAL,
                    intent TEXT,
                    model TEXT DEFAULT 'gemini',
                    tool_calls INTEGER DEFAULT 0,
                    cache_hit BOOLEAN DEFAULT 0,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ai_analytics_user
                ON ai_analytics(user_id, created_at DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ai_analytics_guild
                ON ai_analytics(guild_id, created_at DESC)
            """)

            # Token Usage Tracking Table (Phase 1 Enhancement)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    model TEXT DEFAULT 'gemini-3-pro-preview',
                    cached BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_user
                ON token_usage(user_id, created_at DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_channel
                ON token_usage(channel_id, created_at DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_guild
                ON token_usage(guild_id, created_at DESC)
            """)

            await conn.commit()
            self._schema_initialized = True
            logging.info("💾 Database schema initialized (async)")

    @asynccontextmanager
    async def get_connection(self):
        """Get an async database connection with pooling and optimizations."""
        # Acquire semaphore slot (limits concurrent connections)
        async with self._pool_semaphore:
            self._connection_count += 1
            conn = await aiosqlite.connect(self.db_path, timeout=30.0)
            conn.row_factory = aiosqlite.Row

            # Performance optimizations for high-RAM machines
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=100000")  # ~400MB cache
            await conn.execute("PRAGMA temp_store=MEMORY")
            await conn.execute("PRAGMA mmap_size=1073741824")  # 1GB memory-mapped I/O
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA page_size=8192")  # Larger pages
            await conn.execute("PRAGMA wal_autocheckpoint=1000")  # Checkpoint every 1000 pages

            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                await conn.close()
                self._connection_count -= 1

    async def health_check(self) -> bool:
        """
        Verify database connection is healthy.

        Performs a simple query to confirm the database is responsive.
        If the check fails, attempts to reinitialize the connection pool.

        Returns:
            True if database is healthy, False otherwise
        """
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                return bool(result and result[0] == 1)
        except Exception as e:
            logging.error("💔 Database health check failed: %s", e)
            # Attempt recovery
            try:
                await self._reinitialize_pool()
                # Retry once after reinitialization
                async with self.get_connection() as conn:
                    await conn.execute("SELECT 1")
                    logging.info("💚 Database recovered after reinitialization")
                    return True
            except Exception as reinit_error:
                logging.error("💀 Database reinitialization failed: %s", reinit_error)
                return False

    async def _reinitialize_pool(self) -> None:
        """
        Reinitialize the connection pool.

        This is called when health check fails to attempt recovery.
        Resets the semaphore and schema flag to allow fresh connections.
        """
        logging.warning("🔄 Reinitializing database connection pool...")

        # Wait for existing connections to close (with timeout)
        max_wait = 10  # seconds
        waited = 0
        while self._connection_count > 0 and waited < max_wait:
            await asyncio.sleep(0.5)
            waited += 0.5

        if self._connection_count > 0:
            logging.warning(
                "⚠️ %d connections still active during reinitialization", self._connection_count
            )

        # Recreate the semaphore (resets available slots)
        self._pool_semaphore = asyncio.Semaphore(50)

        # Re-ensure schema on next connection
        self._schema_initialized = False

        # Verify database file exists
        if not Path(self.db_path).exists():
            logging.warning("⚠️ Database file missing, will be recreated on next access")

        logging.info("🔄 Connection pool reinitialized")

    @asynccontextmanager
    async def get_connection_with_retry(self, max_retries: int = 3):
        """
        Get a connection with automatic retry on failure.

        Args:
            max_retries: Maximum number of retry attempts

        Yields:
            Database connection

        Note:
            Uses @asynccontextmanager to ensure proper cleanup even if
            the consumer code raises an exception.
        """
        last_error = None
        conn = None

        for attempt in range(max_retries):
            try:
                # Acquire semaphore slot
                async with self._pool_semaphore:
                    self._connection_count += 1
                    conn = await aiosqlite.connect(self.db_path, timeout=30.0)
                    conn.row_factory = aiosqlite.Row

                    # Performance optimizations
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA synchronous=NORMAL")
                    await conn.execute("PRAGMA cache_size=100000")
                    await conn.execute("PRAGMA temp_store=MEMORY")
                    await conn.execute("PRAGMA mmap_size=1073741824")
                    await conn.execute("PRAGMA foreign_keys=ON")
                    await conn.execute("PRAGMA page_size=8192")
                    await conn.execute("PRAGMA wal_autocheckpoint=1000")

                    try:
                        yield conn
                        await conn.commit()
                        return  # Success, exit
                    except Exception:
                        await conn.rollback()
                        raise
                    finally:
                        await conn.close()
                        self._connection_count -= 1

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    logging.warning(
                        "⚠️ Database connection attempt %d/%d failed: %s. Retrying in %ds...",
                        attempt + 1,
                        max_retries,
                        e,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    # Try reinitializing on subsequent failures
                    if attempt >= 1:
                        await self._reinitialize_pool()

        logging.error("💀 All database connection attempts failed")
        raise last_error

    # ==================== RAG Operations ====================

    async def save_rag_memory(
        self, content: str, embedding_bytes: bytes, channel_id: int | None = None
    ) -> int:
        """Save a new memory with vector embedding."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO ai_long_term_memory (channel_id, content, embedding) VALUES (?, ?, ?)",
                (channel_id, content, embedding_bytes),
            )
            return cursor.lastrowid

    async def get_all_rag_memories(self, channel_id: int | None = None) -> list[Any]:
        """Get all memories for similarity search."""
        async with self.get_connection() as conn:
            if channel_id:
                cursor = await conn.execute(
                    "SELECT id, content, embedding, created_at FROM ai_long_term_memory WHERE channel_id = ?",
                    (channel_id,),
                )
            else:
                cursor = await conn.execute(
                    "SELECT id, content, embedding, created_at FROM ai_long_term_memory"
                )
            return await cursor.fetchall()

    # ==================== AI History Operations ====================

    async def save_ai_message(
        self,
        channel_id: int,
        role: str,
        content: str,
        message_id: int | None = None,
        timestamp: str | None = None,
    ) -> int:
        """Save a single AI message to history."""
        async with self.get_connection() as conn:
            ts = timestamp or datetime.now().isoformat()

            # Get next local_id for this channel
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(local_id), 0) + 1 FROM ai_history WHERE channel_id = ?",
                (channel_id,),
            )
            row = await cursor.fetchone()
            next_local_id = row[0] if row else 1

            cursor = await conn.execute(
                """INSERT INTO ai_history (channel_id, role, content, message_id, timestamp, local_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (channel_id, role, content, message_id, ts, next_local_id),
            )
            lastrowid = cursor.lastrowid

        # Trigger auto-export
        self._schedule_export(channel_id)
        return lastrowid

    async def save_ai_messages_batch(self, messages: list[dict[str, Any]]) -> int:
        """Batch insert AI messages for better performance."""
        if not messages:
            return 0

        # Group messages by channel_id
        by_channel: dict[int, list[dict[str, Any]]] = {}
        for msg in messages:
            ch = msg.get("channel_id")
            if ch:
                if ch not in by_channel:
                    by_channel[ch] = []
                by_channel[ch].append(msg)

        async with self.get_connection() as conn:
            for channel_id, channel_messages in by_channel.items():
                # Get next local_id for this channel
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(local_id), 0) FROM ai_history WHERE channel_id = ?",
                    (channel_id,),
                )
                row = await cursor.fetchone()
                next_local_id = (row[0] or 0) + 1

                # Add local_id to each message
                for msg in channel_messages:
                    msg["local_id"] = next_local_id
                    next_local_id += 1

                await conn.executemany(
                    """INSERT INTO ai_history (channel_id, role, content, message_id, timestamp, local_id)
                       VALUES (:channel_id, :role, :content, :message_id, :timestamp, :local_id)""",
                    channel_messages,
                )

        # Trigger auto-export for each channel
        for channel_id in by_channel:
            self._schedule_export(channel_id)

        return len(messages)

    async def get_ai_history(
        self, channel_id: int, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get AI chat history for a channel."""
        async with self.get_connection() as conn:
            if limit:
                cursor = await conn.execute(
                    """SELECT id, role, content, message_id, timestamp
                       FROM ai_history WHERE channel_id = ?
                       ORDER BY id ASC LIMIT ?""",
                    (channel_id, limit),
                )
            else:
                cursor = await conn.execute(
                    """SELECT id, role, content, message_id, timestamp
                       FROM ai_history WHERE channel_id = ?
                       ORDER BY id ASC""",
                    (channel_id,),
                )

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_ai_history_count(self, channel_id: int) -> int:
        """Get count of messages in AI history."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM ai_history WHERE channel_id = ?", (channel_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def delete_ai_history(self, channel_id: int) -> int:
        """Delete all AI history for a channel."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM ai_history WHERE channel_id = ?", (channel_id,)
            )
            deleted = cursor.rowcount

        # Also delete the export file
        export_file = EXPORT_DIR / "ai_history" / f"{channel_id}.json"
        if export_file.exists():
            try:
                export_file.unlink()
                logging.info("🗑️ Deleted export file: %s", export_file)
            except OSError as e:
                logging.warning("Failed to delete export file: %s", e)

        return deleted

    async def prune_ai_history(self, channel_id: int, keep_count: int) -> int:
        """Prune old messages, keeping only the most recent keep_count messages."""
        async with self.get_connection() as conn:
            # Delete older messages, keeping the most recent ones
            cursor = await conn.execute(
                """DELETE FROM ai_history
                   WHERE channel_id = ? AND id NOT IN (
                       SELECT id FROM ai_history
                       WHERE channel_id = ?
                       ORDER BY id DESC
                       LIMIT ?
                   )""",
                (channel_id, channel_id, keep_count),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                logging.info("🗑️ Pruned %d old messages from channel %d", deleted, channel_id)
            return deleted

    async def update_message_id(self, channel_id: int, message_id: int) -> bool:
        """Update the message_id for the last model response."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """UPDATE ai_history SET message_id = ?
                   WHERE id = (SELECT MAX(id) FROM ai_history
                               WHERE channel_id = ? AND role = 'model')""",
                (message_id, channel_id),
            )
            return cursor.rowcount > 0

    async def get_all_ai_channel_ids(self) -> list[int]:
        """Get all channel IDs that have AI chat history."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("SELECT DISTINCT channel_id FROM ai_history")
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    # ==================== AI Metadata Operations ====================

    async def get_ai_metadata(self, channel_id: int) -> dict[str, Any]:
        """Get AI session metadata."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT thinking_enabled, system_instruction, last_accessed
                   FROM ai_metadata WHERE channel_id = ?""",
                (channel_id,),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "thinking_enabled": bool(row[0]),
                    "system_instruction": row[1],
                    "last_accessed": row[2],
                }
            return {"thinking_enabled": True, "system_instruction": None}

    async def save_ai_metadata(
        self, channel_id: int, thinking_enabled: bool = True, system_instruction: str | None = None
    ) -> None:
        """Save or update AI session metadata."""
        async with self.get_connection() as conn:
            await conn.execute(
                """INSERT INTO ai_metadata (channel_id, thinking_enabled, system_instruction, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel_id) DO UPDATE SET
                   thinking_enabled = excluded.thinking_enabled,
                   system_instruction = excluded.system_instruction,
                   updated_at = CURRENT_TIMESTAMP""",
                (channel_id, thinking_enabled, system_instruction),
            )

    async def update_last_accessed(self, channel_id: int) -> None:
        """Update last accessed time for a channel."""
        async with self.get_connection() as conn:
            await conn.execute(
                """INSERT INTO ai_metadata (channel_id, last_accessed)
                   VALUES (?, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel_id) DO UPDATE SET
                   last_accessed = CURRENT_TIMESTAMP""",
                (channel_id,),
            )

    # ==================== Guild Settings ====================

    async def get_guild_settings(self, guild_id: int) -> dict[str, Any]:
        """Get settings for a guild."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {
                "guild_id": guild_id,
                "prefix": "!",
                "ai_enabled": True,
                "music_enabled": True,
                "auto_disconnect_delay": 180,
                "mode_247": False,
            }

    async def save_guild_settings(self, guild_id: int, **settings) -> None:
        """Save or update guild settings."""
        # Whitelist of allowed column names to prevent SQL injection
        allowed_columns = {
            "prefix",
            "ai_enabled",
            "music_enabled",
            "auto_disconnect_delay",
            "mode_247",
        }

        # Filter settings to only allowed columns
        safe_settings = {k: v for k, v in settings.items() if k in allowed_columns}

        if not safe_settings:
            return

        async with self.get_connection() as conn:
            columns = ["guild_id", *list(safe_settings.keys())]
            values = [guild_id, *list(safe_settings.values())]
            placeholders = ",".join(["?" for _ in values])

            col_str = ",".join(columns)
            update_str = ",".join([f"{k}=excluded.{k}" for k in safe_settings])

            await conn.execute(
                f"""INSERT INTO guild_settings ({col_str}) VALUES ({placeholders})
                    ON CONFLICT(guild_id) DO UPDATE SET {update_str}, updated_at=CURRENT_TIMESTAMP""",
                values,
            )

    # ==================== User Statistics ====================

    async def increment_user_stat(
        self, user_id: int, guild_id: int, stat_name: str, amount: int = 1
    ) -> None:
        """Increment a user statistic."""
        valid_stats = ["messages_count", "commands_count", "ai_interactions", "music_requests"]
        if stat_name not in valid_stats:
            return

        async with self.get_connection() as conn:
            await conn.execute(
                f"""INSERT INTO user_stats (user_id, guild_id, {stat_name}, last_active)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, guild_id) DO UPDATE SET
                    {stat_name} = {stat_name} + ?,
                    last_active = CURRENT_TIMESTAMP""",
                (user_id, guild_id, amount, amount),
            )

    async def get_user_stats(self, user_id: int, guild_id: int) -> dict[str, Any]:
        """Get statistics for a user in a guild."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM user_stats WHERE user_id = ? AND guild_id = ?", (user_id, guild_id)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {
                "messages_count": 0,
                "commands_count": 0,
                "ai_interactions": 0,
                "music_requests": 0,
            }

    # ==================== Error Logging ====================

    async def log_error(
        self,
        error_type: str,
        error_message: str,
        traceback: str | None = None,
        guild_id: int | None = None,
        channel_id: int | None = None,
        user_id: int | None = None,
        command: str | None = None,
    ) -> int:
        """Log an error to the database."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO error_logs
                   (error_type, error_message, traceback, guild_id, channel_id, user_id, command)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (error_type, error_message, traceback, guild_id, channel_id, user_id, command),
            )
            return cursor.lastrowid

    # ==================== Music Queue ====================

    async def save_music_queue(self, guild_id: int, queue: list[dict]) -> bool:
        """Save music queue to database."""
        try:
            async with self.get_connection() as conn:
                # Clear existing queue
                await conn.execute("DELETE FROM music_queue WHERE guild_id = ?", (guild_id,))

                # Insert new queue
                for i, track in enumerate(queue):
                    await conn.execute(
                        """INSERT INTO music_queue (guild_id, position, url, title, added_by)
                           VALUES (?, ?, ?, ?, ?)""",
                        (guild_id, i, track.get("url"), track.get("title"), track.get("added_by")),
                    )
                return True
        except Exception as e:
            logging.error("Failed to save music queue: %s", e)
            return False

    async def load_music_queue(self, guild_id: int) -> list[dict]:
        """Load music queue from database."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """SELECT url, title, added_by FROM music_queue
                       WHERE guild_id = ? ORDER BY position""",
                    (guild_id,),
                )
                rows = await cursor.fetchall()
                return [{"url": r[0], "title": r[1], "added_by": r[2]} for r in rows]
        except Exception as e:
            logging.error("Failed to load music queue: %s", e)
            return []

    async def clear_music_queue(self, guild_id: int) -> bool:
        """Clear music queue from database."""
        try:
            async with self.get_connection() as conn:
                await conn.execute("DELETE FROM music_queue WHERE guild_id = ?", (guild_id,))
                return True
        except Exception as e:
            logging.error("Failed to clear music queue: %s", e)
            return False

    # ==================== Export ====================

    async def export_to_json(self) -> None:
        """Export database tables to JSON files (AI history is exported per channel)."""
        try:
            async with self.get_connection() as conn:
                # Get all tables
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [row[0] for row in await cursor.fetchall()]

                summary = {}
                for table in tables:
                    # Special handling for ai_history - export per channel
                    if table == "ai_history":
                        ai_history_dir = EXPORT_DIR / "ai_history"
                        ai_history_dir.mkdir(exist_ok=True)

                        # Get all channel IDs
                        cursor = await conn.execute("SELECT DISTINCT channel_id FROM ai_history")
                        channel_ids = [row[0] for row in await cursor.fetchall()]

                        total_messages = 0
                        for channel_id in channel_ids:
                            cursor = await conn.execute(
                                """SELECT local_id, channel_id, role, content, message_id,
                                          timestamp, created_at
                                   FROM ai_history WHERE channel_id = ?
                                   ORDER BY local_id ASC""",
                                (channel_id,),
                            )
                            rows = await cursor.fetchall()
                            data = []
                            for row in rows:
                                item = dict(row)
                                item["id"] = item.pop("local_id")  # Rename local_id to id
                                data.append(item)

                            if data:
                                output_file = ai_history_dir / f"{channel_id}.json"
                                output_file.write_text(
                                    json.dumps(data, ensure_ascii=False, indent=2, default=str),
                                    encoding="utf-8",
                                )
                                total_messages += len(data)

                        summary[table] = {"channels": len(channel_ids), "messages": total_messages}
                        continue

                    # Normal tables - export as before
                    cursor = await conn.execute(f"SELECT * FROM {table}")
                    rows = await cursor.fetchall()
                    data = [dict(row) for row in rows]
                    summary[table] = len(data)

                    output_file = EXPORT_DIR / f"{table}.json"
                    output_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )

                summary["exported_at"] = datetime.now().isoformat()
                (EXPORT_DIR / "_summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                logging.info("📤 Exported database to JSON (AI history per channel)")
        except Exception as e:
            logging.error("Export failed: %s", e)

    async def export_channel_to_json(self, channel_id: int) -> None:
        """Export a single channel's AI history to JSON."""
        try:
            # Create ai_history subdirectory
            ai_history_dir = EXPORT_DIR / "ai_history"
            ai_history_dir.mkdir(exist_ok=True)

            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """SELECT local_id, channel_id, role, content, message_id,
                              timestamp, created_at
                       FROM ai_history WHERE channel_id = ?
                       ORDER BY local_id ASC""",
                    (channel_id,),
                )
                rows = await cursor.fetchall()

                # Use local_id as 'id' in the export
                data = []
                for row in rows:
                    item = dict(row)
                    item["id"] = item.pop("local_id")  # Rename local_id to id
                    data.append(item)

                if data:
                    output_file = ai_history_dir / f"{channel_id}.json"
                    output_file.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )

                    logging.debug("📤 Exported %d messages for channel %d", len(data), channel_id)
        except Exception as e:
            logging.error("Channel export failed: %s", e)

    def stop_watchers(self) -> None:
        """Stop all watchers (compatibility method)."""
        pass  # No watchers in async version


# Global singleton instance
db = Database()


async def init_database() -> Database:
    """Initialize database and return instance."""
    await db.init_schema()
    return db
