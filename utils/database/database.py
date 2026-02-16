"""
Database Module for Discord Bot (Async Version)
Provides async SQLite database connection using aiosqlite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import contextlib
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

# Database timeout configuration (in seconds)
# Can be overridden via environment variable
DB_CONNECTION_TIMEOUT = float(os.getenv("DB_CONNECTION_TIMEOUT", "30.0"))

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
    _instance_lock = threading.Lock()  # Thread-safe singleton creation

    def __new__(cls) -> Database:
        """Singleton pattern - only one database instance (thread-safe)."""
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check locking pattern
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
        # Connection pool semaphore - reduced for better SQLite compatibility with WAL mode
        # SQLite doesn't handle high concurrent writes well, 20 is a good balance
        self._pool_semaphore = asyncio.Semaphore(20)  # Max 20 concurrent connections (was 50)
        self._connection_count = 0
        # Persistent connection pool for reuse (avoids open/close overhead)
        self._conn_pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(maxsize=5)
        self._pool_initialized = False
        self._dashboard_export_pending: set[str] = set()  # Track pending dashboard exports
        self._export_lock = asyncio.Lock()  # Lock for export scheduling
        logging.info("💾 Async Database manager created: %s (pool=20, WAL mode)", self.db_path)

    def _schedule_export(self, channel_id: int | None = None) -> None:
        """Schedule a debounced export with retry logic (non-blocking)."""
        # Use a per-channel pending key to avoid dropping exports for different channels
        pending_key = f"channel_{channel_id}" if channel_id else "__global__"
        if not hasattr(self, "_export_pending_keys"):
            self._export_pending_keys: set[str] = set()

        if pending_key in self._export_pending_keys:
            return

        self._export_pending_keys.add(pending_key)
        max_retries = 3

        async def do_export():
            await asyncio.sleep(self._export_delay)
            self._export_pending_keys.discard(pending_key)
            # Also clear legacy flag for backward compat
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
        try:
            task = asyncio.create_task(do_export())
            self._export_tasks.add(task)
            # Auto-remove task when done
            task.add_done_callback(self._export_tasks.discard)
        except RuntimeError:
            # No running event loop (e.g., during init)
            self._export_pending_keys.discard(pending_key)
            logging.debug("Cannot schedule export: no running event loop")

    def _schedule_dashboard_export(self, conversation_id: str) -> None:
        """Schedule a debounced export for a dashboard conversation (non-blocking)."""
        if conversation_id in self._dashboard_export_pending:
            return

        self._dashboard_export_pending.add(conversation_id)

        async def do_export():
            await asyncio.sleep(self._export_delay)
            self._dashboard_export_pending.discard(conversation_id)

            try:
                await self.export_dashboard_conversation_to_json(conversation_id)
            except Exception as e:
                logging.warning("Dashboard export failed for %s: %s", conversation_id, e)

        try:
            task = asyncio.create_task(do_export())
            self._export_tasks.add(task)
            task.add_done_callback(self._export_tasks.discard)
        except RuntimeError:
            # No running event loop (e.g., during init)
            self._dashboard_export_pending.discard(conversation_id)
            logging.debug("Cannot schedule dashboard export: no running event loop")

    async def export_dashboard_conversation_to_json(self, conversation_id: str) -> None:
        """Export a single dashboard conversation to JSON file."""
        try:
            # Validate conversation_id to prevent path traversal
            import re as _re
            if not _re.match(r'^[a-zA-Z0-9_\-]+$', conversation_id):
                logging.warning("Invalid conversation_id rejected: %s", conversation_id[:50])
                return

            dashboard_export_dir = EXPORT_DIR / "dashboard_chats"
            dashboard_export_dir.mkdir(exist_ok=True)

            conversation = await self.get_dashboard_conversation(conversation_id)
            if not conversation:
                return

            messages = await self.get_dashboard_messages(conversation_id)

            export_data = {
                "conversation": conversation,
                "messages": messages,
            }

            output_file = dashboard_export_dir / f"{conversation_id}.json"
            output_file.write_text(
                json.dumps(export_data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logging.debug("📤 Exported dashboard conversation: %s", conversation_id)
        except Exception as e:
            logging.error("Failed to export dashboard conversation %s: %s", conversation_id, e)

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

        # Always run final export on shutdown to ensure data safety
        has_pending = (
            self._export_pending
            or (hasattr(self, '_export_pending_keys') and self._export_pending_keys)
            or self._dashboard_export_pending
        )
        if has_pending:
            logging.info("💾 Flushing pending database exports...")
            self._export_pending = False
            if hasattr(self, '_export_pending_keys'):
                self._export_pending_keys.clear()
            self._dashboard_export_pending.clear()
        
        # Always export on shutdown for data safety
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
            # One-time database-wide PRAGMAs (only need to be set once per DB file)
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA mmap_size=2147483648")
            await conn.execute("PRAGMA wal_autocheckpoint=2000")

            # AI Chat History Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    local_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER,
                    role TEXT NOT NULL CHECK(role IN ('user', 'model')),
                    content TEXT NOT NULL,
                    message_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add user_id column if missing (existing databases)
            try:
                cursor = await conn.execute("PRAGMA table_info(ai_history)")
                columns = {row[1] for row in await cursor.fetchall()}
                if "user_id" not in columns:
                    await conn.execute("ALTER TABLE ai_history ADD COLUMN user_id INTEGER")
                    logging.info("🔄 Migrated ai_history: added user_id column")
            except Exception as e:
                logging.warning("Migration check for user_id failed: %s", e)

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

            # ==================== Dashboard Chat Tables ====================

            # Dashboard Conversations Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    role_preset TEXT NOT NULL DEFAULT 'general',
                    system_instruction TEXT,
                    thinking_enabled BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_starred BOOLEAN DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dashboard_conv_updated
                ON dashboard_conversations(updated_at DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dashboard_conv_starred
                ON dashboard_conversations(is_starred, updated_at DESC)
            """)

            # Dashboard Messages Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    thinking TEXT,
                    mode TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES dashboard_conversations(id) ON DELETE CASCADE
                )
            """)

            # Add thinking column if not exists (migration)
            try:
                await conn.execute("ALTER TABLE dashboard_messages ADD COLUMN thinking TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists

            # Add mode column if not exists (migration)
            try:
                await conn.execute("ALTER TABLE dashboard_messages ADD COLUMN mode TEXT")
            except aiosqlite.OperationalError:
                pass  # Column already exists
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dashboard_msg_conv
                ON dashboard_messages(conversation_id, created_at ASC)
            """)

            # Dashboard User Profile Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_user_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    display_name TEXT DEFAULT 'User',
                    bio TEXT,
                    preferences TEXT,
                    is_creator INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: add is_creator column if not exists
            try:
                await conn.execute(
                    "ALTER TABLE dashboard_user_profile ADD COLUMN is_creator INTEGER DEFAULT 0"
                )
            except aiosqlite.OperationalError:
                pass  # Column already exists

            # Dashboard Long-term Memory Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    importance INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dashboard_memories_category
                ON dashboard_memories(category, importance DESC)
            """)

            await conn.commit()
            self._schema_initialized = True
            logging.info("💾 Database schema initialized (async)")

            # Run versioned migrations
            try:
                from utils.database.migrations import run_migrations
                await run_migrations(conn)
            except Exception as e:
                logging.warning("Migration system error (non-fatal): %s", e)

    @asynccontextmanager
    async def get_connection(self):
        """Get an async database connection from the persistent pool.
        
        Connections are reused across requests to avoid the overhead of
        opening/closing a new aiosqlite connection for each query.
        When the pool is empty, a new connection is created on the fly.
        """
        # Acquire semaphore slot (limits concurrent connections)
        async with self._pool_semaphore:
            conn = None
            from_pool = False
            
            # Try to get a connection from the pool
            try:
                conn = self._conn_pool.get_nowait()
                from_pool = True
                # Validate the pooled connection is still alive
                try:
                    await conn.execute("SELECT 1")
                except Exception:
                    # Connection is stale, close and create a new one
                    try:
                        await conn.close()
                    except Exception:
                        pass
                    conn = None
                    from_pool = False
            except asyncio.QueueEmpty:
                pass
            
            # Create a new connection if needed
            if conn is None:
                self._connection_count += 1
                conn = await aiosqlite.connect(self.db_path, timeout=DB_CONNECTION_TIMEOUT)
                conn.row_factory = aiosqlite.Row

                # Performance optimizations — per-connection PRAGMAs only
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA cache_size=250000")
                await conn.execute("PRAGMA temp_store=MEMORY")
                await conn.execute("PRAGMA foreign_keys=ON")

            try:
                yield conn
                await conn.commit()
            except (aiosqlite.Error, asyncio.CancelledError):
                with contextlib.suppress(Exception):
                    await conn.rollback()
                raise
            finally:
                # Return connection to pool instead of closing
                try:
                    self._conn_pool.put_nowait(conn)
                except asyncio.QueueFull:
                    # Pool is full, close this connection
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

        # Drain and close all pooled connections to prevent stale connections
        drained = 0
        while not self._conn_pool.empty():
            try:
                old_conn = self._conn_pool.get_nowait()
                try:
                    await old_conn.close()
                except Exception:
                    pass
                drained += 1
            except asyncio.QueueEmpty:
                break

        if drained:
            logging.info("Drained %d stale connections from pool", drained)
            self._connection_count = max(0, self._connection_count - drained)

        # Reset the semaphore safely.
        # Creating a new semaphore is simpler and more reliable than drain/refill.
        # Existing waiters on the old semaphore will get an error, but this only
        # runs during reinitialization after failures, so that's acceptable.
        try:
            self._pool_semaphore = asyncio.Semaphore(20)
            logging.info("Reset pool semaphore to 20 slots")
        except Exception as e:
            logging.warning("Failed to reset semaphore: %s", e)
            self._pool_semaphore = asyncio.Semaphore(20)

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
            Retry logic only applies to connection establishment, NOT
            to errors from the caller's code after yield.
        """
        last_error = None
        conn = None

        # Retry logic only for establishing the connection (before yield)
        for attempt in range(max_retries):
            conn = None
            try:
                await self._pool_semaphore.acquire()
                self._connection_count += 1
                try:
                    conn = await aiosqlite.connect(self.db_path, timeout=DB_CONNECTION_TIMEOUT)
                    conn.row_factory = aiosqlite.Row

                    # Performance optimizations — per-connection PRAGMAs only
                    # DB-wide PRAGMAs (WAL, mmap_size, page_size, wal_autocheckpoint)
                    # are set once during init_schema() — no need to repeat here.
                    await conn.execute("PRAGMA synchronous=NORMAL")
                    await conn.execute("PRAGMA cache_size=100000")
                    await conn.execute("PRAGMA temp_store=MEMORY")
                    await conn.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    if conn is not None:
                        await conn.close()
                        conn = None
                    self._connection_count -= 1
                    self._pool_semaphore.release()
                    raise

                # Connection established successfully - break out of retry loop
                break

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
        else:
            # All retries exhausted
            logging.error("💀 All database connection attempts failed")
            if last_error is not None:
                raise last_error
            raise RuntimeError("Unknown database error occurred during connection")

        # Yield exactly once - let caller exceptions propagate naturally
        try:
            yield conn
            await conn.commit()
        except aiosqlite.Error:
            await conn.rollback()
            raise
        finally:
            if conn is not None:
                await conn.close()
            self._connection_count -= 1
            self._pool_semaphore.release()

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
            rowid = cursor.lastrowid
            return int(rowid) if rowid is not None else 0

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
            rows = await cursor.fetchall()
            return list(rows)

    # ==================== AI History Operations ====================

    async def save_ai_message(
        self,
        channel_id: int,
        role: str,
        content: str,
        message_id: int | None = None,
        timestamp: str | None = None,
        user_id: int | None = None,
    ) -> int:
        """Save a single AI message to history."""
        async with self.get_connection() as conn:
            ts = timestamp or datetime.now().isoformat()

            # Atomic local_id generation + insert in a single statement
            # Prevents race condition where two concurrent saves get the same local_id
            cursor = await conn.execute(
                """INSERT INTO ai_history (channel_id, user_id, role, content, message_id, timestamp, local_id)
                   VALUES (?, ?, ?, ?, ?, ?,
                       (SELECT COALESCE(MAX(local_id), 0) + 1 FROM ai_history WHERE channel_id = ?))""",
                (channel_id, user_id, role, content, message_id, ts, channel_id),
            )
            lastrowid = cursor.lastrowid

        # Trigger auto-export
        self._schedule_export(channel_id)
        return lastrowid if lastrowid is not None else 0

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
                # Use atomic subquery for local_id to prevent race condition
                # when concurrent calls target the same channel_id
                for msg in channel_messages:
                    msg["channel_id"] = channel_id
                    await conn.execute(
                        """INSERT INTO ai_history (channel_id, user_id, role, content, message_id, timestamp, local_id)
                           VALUES (:channel_id, :user_id, :role, :content, :message_id, :timestamp,
                               (SELECT COALESCE(MAX(local_id), 0) + 1 FROM ai_history WHERE channel_id = :channel_id))""",
                        msg,
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
            rowid = cursor.lastrowid
            return int(rowid) if rowid is not None else 0

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

    # ==================== Audit Logs ====================

    async def get_audit_logs(
        self,
        days: int = 7,
        guild_id: int | None = None,
        action_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Get audit logs from database.

        Args:
            days: Number of days to look back (default 7)
            guild_id: Filter by guild ID (optional)
            action_type: Filter by action type (optional)
            limit: Maximum number of records to return (default 1000)

        Returns:
            List of audit log entries as dictionaries
        """
        try:
            async with self.get_connection() as conn:
                conn.row_factory = aiosqlite.Row

                # Build query with optional filters
                query = """
                    SELECT id, action_type, guild_id, user_id, target_id, details, created_at
                    FROM audit_log
                    WHERE created_at >= datetime('now', ?)
                """
                params: list[Any] = [f"-{days} days"]

                if guild_id is not None:
                    query += " AND guild_id = ?"
                    params.append(guild_id)

                if action_type is not None:
                    query += " AND action_type = ?"
                    params.append(action_type)

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor = await conn.execute(query, params)
                rows = await cursor.fetchall()

                return [dict(row) for row in rows]
        except Exception as e:
            logging.error("Failed to get audit logs: %s", e)
            return []

    async def log_audit(
        self,
        action_type: str,
        guild_id: int | None = None,
        user_id: int | None = None,
        target_id: int | None = None,
        details: str | None = None,
    ) -> int:
        """
        Log an audit entry to the database.

        Args:
            action_type: Type of action (e.g., "channel_create", "role_delete")
            guild_id: Guild where action occurred
            user_id: User who performed the action
            target_id: Target of the action (channel ID, role ID, etc.)
            details: Additional details as JSON string or text

        Returns:
            ID of the created audit log entry
        """
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """INSERT INTO audit_log
                       (action_type, guild_id, user_id, target_id, details)
                       VALUES (?, ?, ?, ?, ?)""",
                    (action_type, guild_id, user_id, target_id, details),
                )
                # Note: get_connection() auto-commits on success, no explicit commit needed
                rowid = cursor.lastrowid
                return int(rowid) if rowid is not None else 0
        except Exception as e:
            logging.error("Failed to log audit entry: %s", e)
            return 0

    # ==================== Dashboard Conversations ====================

    async def create_dashboard_conversation(
        self,
        conversation_id: str,
        role_preset: str = "general",
        thinking_enabled: bool = False,
        title: str | None = None,
        system_instruction: str | None = None,
    ) -> str:
        """Create a new dashboard conversation."""
        async with self.get_connection() as conn:
            await conn.execute(
                """INSERT INTO dashboard_conversations
                   (id, title, role_preset, system_instruction, thinking_enabled)
                   VALUES (?, ?, ?, ?, ?)""",
                (conversation_id, title, role_preset, system_instruction, thinking_enabled),
            )
        return conversation_id

    async def get_dashboard_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get all dashboard conversations ordered by most recent."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM dashboard_messages WHERE conversation_id = c.id) as message_count
                   FROM dashboard_conversations c
                   ORDER BY c.is_starred DESC, c.updated_at DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["is_starred"] = bool(d.get("is_starred"))
                results.append(d)
            return results

    async def get_dashboard_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Get a specific dashboard conversation."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM dashboard_conversations WHERE id = ?",
                (conversation_id,),
            )
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                d["is_starred"] = bool(d.get("is_starred"))
                return d
            return None

    async def update_dashboard_conversation(self, conversation_id: str, **updates) -> bool:
        """Update a dashboard conversation."""
        allowed_columns = {
            "title",
            "role_preset",
            "system_instruction",
            "thinking_enabled",
            "is_starred",
        }
        safe_updates = {k: v for k, v in updates.items() if k in allowed_columns}

        if not safe_updates:
            return False

        async with self.get_connection() as conn:
            # Defense-in-depth: validate column names are simple identifiers
            # even though they're already filtered by allowed_columns
            for col in safe_updates:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                    logging.error("Invalid column name rejected: %s", col)
                    return False
            set_clause = ", ".join([f"[{k}] = ?" for k in safe_updates])
            values = [*list(safe_updates.values()), conversation_id]

            await conn.execute(
                f"UPDATE dashboard_conversations SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            return True

    async def update_dashboard_conversation_star(self, conversation_id: str, starred: bool) -> bool:
        """Update the starred status of a conversation."""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE dashboard_conversations SET is_starred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if starred else 0, conversation_id),
            )
            return True

    async def rename_dashboard_conversation(self, conversation_id: str, title: str) -> bool:
        """Rename a dashboard conversation."""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE dashboard_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, conversation_id),
            )
            return True

    async def delete_dashboard_conversation(self, conversation_id: str) -> bool:
        """Delete a dashboard conversation and all its messages."""
        # Security: Validate conversation_id to prevent path traversal
        import re as _re
        if not _re.match(r'^[a-zA-Z0-9_-]+$', conversation_id):
            logging.warning("Rejected invalid conversation_id: %s", conversation_id[:50])
            return False

        async with self.get_connection() as conn:
            # Messages will be deleted automatically due to ON DELETE CASCADE
            await conn.execute(
                "DELETE FROM dashboard_conversations WHERE id = ?",
                (conversation_id,),
            )

            # Delete the exported JSON file if it exists
            try:
                export_dir = Path("data/db_export/dashboard_chats")
                json_file = export_dir / f"{conversation_id}.json"
                if json_file.exists():
                    json_file.unlink()
                    logging.info("🗑️ Deleted exported JSON: %s", json_file.name)
            except Exception as e:
                logging.warning("Failed to delete exported JSON for %s: %s", conversation_id, e)

            return True

    async def save_dashboard_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        thinking: str | None = None,
        mode: str | None = None,
    ) -> int:
        """Save a message to a dashboard conversation."""
        from datetime import datetime

        local_now = datetime.now().isoformat()

        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO dashboard_messages (conversation_id, role, content, thinking, mode, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conversation_id, role, content, thinking, mode, local_now),
            )
            # Update conversation's updated_at
            await conn.execute(
                "UPDATE dashboard_conversations SET updated_at = ? WHERE id = ?",
                (local_now, conversation_id),
            )

            msg_id = cursor.lastrowid

        # Auto-export this conversation to JSON (realtime)
        self._schedule_dashboard_export(conversation_id)

        return msg_id if msg_id is not None else 0

    async def get_dashboard_messages(
        self, conversation_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get messages for a dashboard conversation."""
        async with self.get_connection() as conn:
            if limit:
                cursor = await conn.execute(
                    """SELECT id, role, content, thinking, mode, created_at
                       FROM dashboard_messages
                       WHERE conversation_id = ?
                       ORDER BY created_at ASC
                       LIMIT ?""",
                    (conversation_id, limit),
                )
            else:
                cursor = await conn.execute(
                    """SELECT id, role, content, thinking, mode, created_at
                       FROM dashboard_messages
                       WHERE conversation_id = ?
                       ORDER BY created_at ASC""",
                    (conversation_id,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def export_dashboard_conversation(
        self, conversation_id: str, export_format: str = "json"
    ) -> str:
        """Export a dashboard conversation to JSON or Markdown."""
        conversation = await self.get_dashboard_conversation(conversation_id)
        messages = await self.get_dashboard_messages(conversation_id)

        if not conversation:
            return ""

        if export_format == "markdown":
            lines = [
                f"# {conversation.get('title', 'Untitled Conversation')}",
                "",
                f"**Role:** {conversation.get('role_preset', 'general')}",
                f"**Created:** {conversation.get('created_at', '')}",
                f"**Thinking Mode:** {'Enabled' if conversation.get('thinking_enabled') else 'Disabled'}",
                "",
                "---",
                "",
            ]
            for msg in messages:
                role_label = "👤 User" if msg["role"] == "user" else "🤖 Assistant"
                lines.append(f"### {role_label}")
                lines.append(f"*{msg.get('created_at', '')}*")
                lines.append("")
                lines.append(msg["content"])
                lines.append("")
            return "\n".join(lines)
        else:
            # JSON format
            return json.dumps(
                {
                    "conversation": conversation,
                    "messages": messages,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )

    async def export_all_dashboard_conversations(self) -> None:
        """Export all dashboard conversations to JSON files."""
        try:
            dashboard_export_dir = EXPORT_DIR / "dashboard_chats"
            dashboard_export_dir.mkdir(exist_ok=True)

            conversations = await self.get_dashboard_conversations(limit=1000)

            for conv in conversations:
                conv_id = conv["id"]
                messages = await self.get_dashboard_messages(conv_id)

                export_data = {
                    "conversation": conv,
                    "messages": messages,
                }

                output_file = dashboard_export_dir / f"{conv_id}.json"
                output_file.write_text(
                    json.dumps(export_data, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )

            logging.info("📤 Exported %d dashboard conversations", len(conversations))
        except Exception as e:
            logging.error("Failed to export dashboard conversations: %s", e)

    # ==================== Dashboard Memory Operations ====================

    async def save_dashboard_memory(
        self, content: str, category: str = "general", importance: int = 1
    ) -> int:
        """Save a memory to dashboard long-term storage."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO dashboard_memories (content, category, importance) VALUES (?, ?, ?)",
                (content, category, importance),
            )
            rowid = cursor.lastrowid
            return int(rowid) if rowid is not None else 0

    async def get_dashboard_memories(
        self, category: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get dashboard memories, optionally filtered by category."""
        async with self.get_connection() as conn:
            if category:
                cursor = await conn.execute(
                    """SELECT id, content, category, importance, created_at
                       FROM dashboard_memories
                       WHERE category = ?
                       ORDER BY importance DESC, created_at DESC
                       LIMIT ?""",
                    (category, limit),
                )
            else:
                cursor = await conn.execute(
                    """SELECT id, content, category, importance, created_at
                       FROM dashboard_memories
                       ORDER BY importance DESC, created_at DESC
                       LIMIT ?""",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "content": r[1],
                    "category": r[2],
                    "importance": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]

    async def delete_dashboard_memory(self, memory_id: int) -> bool:
        """Delete a specific memory."""
        async with self.get_connection() as conn:
            await conn.execute("DELETE FROM dashboard_memories WHERE id = ?", (memory_id,))
            return True

    async def get_dashboard_user_profile(self) -> dict[str, Any] | None:
        """Get dashboard user profile."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT display_name, bio, preferences, is_creator FROM dashboard_user_profile WHERE id = 1"
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "display_name": row[0],
                    "bio": row[1],
                    "preferences": row[2],
                    "is_creator": bool(row[3]),
                }
            return None

    async def save_dashboard_user_profile(
        self,
        display_name: str,
        bio: str | None = None,
        preferences: str | None = None,
        is_creator: bool | None = None,
    ) -> None:
        """Save or update dashboard user profile.
        
        When is_creator is None (default), the existing value is preserved.
        Pass True/False explicitly only when you intend to change it.
        """
        async with self.get_connection() as conn:
            if is_creator is not None:
                await conn.execute(
                    """INSERT INTO dashboard_user_profile (id, display_name, bio, preferences, is_creator)
                       VALUES (1, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                       display_name = excluded.display_name,
                       bio = excluded.bio,
                       preferences = excluded.preferences,
                       is_creator = excluded.is_creator,
                       updated_at = CURRENT_TIMESTAMP""",
                    (display_name, bio, preferences, 1 if is_creator else 0),
                )
            else:
                await conn.execute(
                    """INSERT INTO dashboard_user_profile (id, display_name, bio, preferences)
                       VALUES (1, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                       display_name = excluded.display_name,
                       bio = excluded.bio,
                       preferences = excluded.preferences,
                       updated_at = CURRENT_TIMESTAMP""",
                    (display_name, bio, preferences),
                )

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

                    # Normal tables - export with validated table name
                    # Validate table name against known schema tables for safety
                    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
                        logging.warning("Skipping table with invalid name: %s", table)
                        continue
                    cursor = await conn.execute(f"SELECT * FROM [{table}]")
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
    # Initialize user_facts table for long-term memory persistence
    try:
        from cogs.ai_core.memory.long_term_memory import long_term_memory
        await long_term_memory.init_schema()
    except Exception:
        pass  # Module may not be available in all environments
    return db
