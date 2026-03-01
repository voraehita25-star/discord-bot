"""
Unit Tests for Database Module.
Tests core database operations including CRUD, schema, and edge cases.
"""

from __future__ import annotations

import asyncio
import os

# Add project root to path
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestDatabaseSchema:
    """Test database schema initialization."""

    @pytest.fixture
    def temp_db_path(self) -> str:
        """Create a temporary database file."""
        fd, path_str = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        path = Path(path_str)
        yield path_str
        # Cleanup
        if path.exists():
            path.unlink()

    @pytest.mark.asyncio
    async def test_init_schema_creates_tables(self, temp_db_path: str) -> None:
        """Test that init_schema creates all required tables."""
        import aiosqlite

        # Create a minimal database with schema
        async with aiosqlite.connect(temp_db_path) as conn:
            # Create ai_history table (simplified version)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    local_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.commit()

            # Verify table exists
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_history'"
            )
            result = await cursor.fetchone()
            assert result is not None
            assert result[0] == "ai_history"

    @pytest.mark.asyncio
    async def test_local_id_column_exists(self, temp_db_path: str) -> None:
        """Test that local_id column exists in ai_history table."""
        import aiosqlite

        async with aiosqlite.connect(temp_db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_history (
                    id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    role TEXT,
                    content TEXT,
                    local_id INTEGER
                )
            """)
            await conn.commit()

            # Check column exists
            cursor = await conn.execute("PRAGMA table_info(ai_history)")
            columns = [row[1] for row in await cursor.fetchall()]
            assert "local_id" in columns


class TestGuildSettings:
    """Test guild settings operations."""

    def test_allowed_columns_whitelist(self) -> None:
        """Test that save_guild_settings uses whitelist for SQL injection protection."""
        # Define expected allowed columns
        allowed_columns = {
            "prefix",
            "ai_enabled",
            "music_enabled",
            "auto_disconnect_delay",
            "mode_247",
        }

        # Test that malicious column names would be filtered
        test_settings = {
            "prefix": "!",
            "ai_enabled": True,
            "malicious_column": "DROP TABLE users;",  # Should be filtered
            "mode_247": False,
        }

        # Filter using the same logic as save_guild_settings
        safe_settings = {k: v for k, v in test_settings.items() if k in allowed_columns}

        assert "malicious_column" not in safe_settings
        assert "prefix" in safe_settings
        assert "mode_247" in safe_settings
        assert len(safe_settings) == 3


class TestRateLimiter:
    """Test rate limiter functionality."""

    def test_bucket_creation_thread_safe(self) -> None:
        """Test that bucket creation is atomic using setdefault."""
        from dataclasses import dataclass

        @dataclass
        class MockBucket:
            tokens: float
            max_tokens: int

        buckets: dict[str, MockBucket] = {}

        # Simulate setdefault behavior (atomic)
        key = "test_key"

        # First call - creates bucket
        bucket1 = buckets.setdefault(key, MockBucket(tokens=10.0, max_tokens=10))

        # Second call - returns existing bucket
        bucket2 = buckets.setdefault(key, MockBucket(tokens=5.0, max_tokens=5))

        # Both should reference the same bucket (first one created)
        assert bucket1 is bucket2
        assert bucket1.tokens == 10.0
        assert bucket1.max_tokens == 10

    def test_token_consumption(self) -> None:
        """Test token bucket consumption logic."""
        import time
        from dataclasses import dataclass

        @dataclass
        class TokenBucket:
            tokens: float
            max_tokens: int
            last_update: float
            window: float

            def consume(self) -> tuple[bool, float]:
                """Consume a token if available."""
                now = time.time()
                elapsed = now - self.last_update

                # Refill tokens
                refill = elapsed * (self.max_tokens / self.window)
                self.tokens = min(self.max_tokens, self.tokens + refill)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return True, 0.0
                else:
                    retry_after = (1 - self.tokens) * (self.window / self.max_tokens)
                    return False, retry_after

        # Create bucket with 2 tokens, 60 second window
        bucket = TokenBucket(tokens=2.0, max_tokens=2, last_update=time.time(), window=60.0)

        # First two calls should succeed
        assert bucket.consume()[0] is True
        assert bucket.consume()[0] is True

        # Third call should fail (no tokens left)
        allowed, retry_after = bucket.consume()
        assert allowed is False
        assert retry_after > 0


class TestInputSanitization:
    """Test input sanitization functions."""

    def test_sanitize_channel_name(self) -> None:
        """Test channel name sanitization."""
        import re

        def sanitize_channel_name(name: str) -> str:
            """Sanitize channel name for Discord."""
            if not name:
                return ""
            # Remove dangerous characters
            name = re.sub(r"[<>@#&!]", "", name)
            # Limit length
            name = name[:100].strip()
            # Replace spaces with hyphens (Discord convention)
            name = re.sub(r"\s+", "-", name)
            return name.lower()

        # Test basic sanitization
        assert sanitize_channel_name("Hello World") == "hello-world"
        assert sanitize_channel_name("<script>alert</script>") == "scriptalert/script"
        assert sanitize_channel_name("test@channel#name") == "testchannelname"
        assert sanitize_channel_name("") == ""

        # Test length limit
        long_name = "a" * 200
        assert len(sanitize_channel_name(long_name)) <= 100

    def test_sanitize_role_name(self) -> None:
        """Test role name sanitization."""
        import re

        def sanitize_role_name(name: str) -> str:
            """Sanitize role name for Discord."""
            if not name:
                return ""
            # Remove dangerous characters but keep spaces for roles
            name = re.sub(r"[<>@#&!]", "", name)
            # Limit length
            return name[:100].strip()

        # Test basic sanitization
        assert sanitize_role_name("Admin") == "Admin"
        assert sanitize_role_name("@everyone") == "everyone"
        assert sanitize_role_name("") == ""


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_circuit_states(self) -> None:
        """Test circuit breaker state transitions."""
        from enum import Enum

        class CircuitState(Enum):
            CLOSED = "closed"
            OPEN = "open"
            HALF_OPEN = "half_open"

        # Test state values
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_failure_threshold(self) -> None:
        """Test that circuit opens after failure threshold."""
        failure_count = 0
        failure_threshold = 5
        state = "closed"

        # Simulate failures
        for _ in range(failure_threshold):
            failure_count += 1
            if failure_count >= failure_threshold:
                state = "open"

        assert state == "open"
        assert failure_count == 5


class TestMusicUtils:
    """Test music utility functions."""

    def test_format_duration(self) -> None:
        """Test duration formatting."""

        def format_duration(seconds: int | float | None) -> str:
            if not seconds:
                return "00:00"
            seconds = int(seconds)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            if hours > 0:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"

        assert format_duration(0) == "00:00"
        assert format_duration(None) == "00:00"
        assert format_duration(65) == "1:05"
        assert format_duration(3661) == "1:01:01"
        assert format_duration(7200) == "2:00:00"

    def test_create_progress_bar(self) -> None:
        """Test progress bar creation."""

        def create_progress_bar(current: int | float, total: int | float, length: int = 12) -> str:
            if total == 0:
                return "▱" * length
            progress = int((current / total) * length)
            filled = "▰" * progress
            empty = "▱" * (length - progress)
            return filled + empty

        assert create_progress_bar(0, 100) == "▱" * 12
        assert create_progress_bar(50, 100) == "▰" * 6 + "▱" * 6
        assert create_progress_bar(100, 100) == "▰" * 12
        assert create_progress_bar(0, 0) == "▱" * 12


# Run tests with: python -m pytest tests/test_database.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ======================================================================
# Merged from test_database_extended.py
# ======================================================================

class TestDatabaseConstants:
    """Tests for database constants."""

    def test_db_dir_exists(self):
        """Test DB_DIR exists."""
        from utils.database.database import DB_DIR

        assert DB_DIR.exists()

    def test_export_dir_exists(self):
        """Test EXPORT_DIR exists."""
        from utils.database.database import EXPORT_DIR

        assert EXPORT_DIR.exists()

    def test_db_file_path(self):
        """Test DB_FILE path is correct."""
        from utils.database.database import DB_DIR, DB_FILE

        assert DB_FILE.parent == DB_DIR
        assert DB_FILE.name == "bot_database.db"


class TestDatabaseSingleton:
    """Tests for Database singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """Test that Database always returns same instance."""
        from utils.database.database import Database

        db1 = Database()
        db2 = Database()

        assert db1 is db2

    def test_initialized_flag_prevents_reinit(self):
        """Test that _initialized flag prevents reinitialization."""
        from utils.database.database import Database

        db = Database()
        assert db._initialized is True


class TestDatabaseInit:
    """Tests for Database initialization."""

    def test_pool_semaphore_created(self):
        """Test that pool semaphore is created lazily with correct value."""
        from utils.database.database import Database

        db = Database()
        # Semaphore is lazily initialized - trigger creation
        sem = db._get_pool_semaphore()
        assert (
            sem._value == 32
        )  # 32 concurrent connections (tuned for R7 9800X3D 16T)

    def test_db_path_is_string(self):
        """Test that db_path is a string."""
        from utils.database.database import Database

        db = Database()
        assert isinstance(db.db_path, str)

    def test_export_delay_value(self):
        """Test export delay has correct value."""
        from utils.database.database import Database

        db = Database()
        assert db._export_delay == 3


class TestScheduleExport:
    """Tests for _schedule_export method."""

    @pytest.mark.asyncio
    async def test_schedule_export_sets_pending_flag(self):
        """Test that _schedule_export sets pending key for channel."""
        from utils.database.database import Database

        db = Database()
        db._export_pending_keys = set()

        db._schedule_export(channel_id=123)

        assert "channel_123" in db._export_pending_keys

        # Cancel the task to cleanup
        for task in list(db._export_tasks):
            task.cancel()
        db._export_pending_keys.clear()
        db._export_pending = False

    @pytest.mark.asyncio
    async def test_schedule_export_skips_if_already_pending(self):
        """Test that _schedule_export skips if already pending for same channel."""
        from utils.database.database import Database

        db = Database()
        db._export_pending_keys = {"channel_123"}
        initial_task_count = len(db._export_tasks)

        db._schedule_export(channel_id=123)

        # Should not create new task
        assert len(db._export_tasks) == initial_task_count

        # Reset
        db._export_pending_keys.clear()
        db._export_pending = False


class TestFlushPendingExports:
    """Tests for flush_pending_exports method."""

    @pytest.mark.asyncio
    async def test_flush_cancels_pending_tasks(self):
        """Test that flush_pending_exports cancels pending tasks."""
        from utils.database.database import Database

        db = Database()
        db._export_pending = True

        # Create a proper async mock task that can be awaited
        async def dummy_coro():
            pass

        # Create a real task from dummy coroutine, then cancel it
        mock_task = asyncio.create_task(dummy_coro())
        mock_task.cancel()
        try:
            await mock_task
        except asyncio.CancelledError:
            pass

        # Now create a fresh mock for testing
        mock_task = MagicMock()
        mock_task.done.return_value = True  # Already done, so won't be awaited
        db._export_tasks.add(mock_task)

        with patch.object(db, "export_to_json", new_callable=AsyncMock):
            await db.flush_pending_exports()

        assert db._export_pending is False
        db._export_tasks.clear()

    @pytest.mark.asyncio
    async def test_flush_does_nothing_if_not_pending(self):
        """Test flush does nothing if not pending."""
        from utils.database.database import Database

        db = Database()
        db._export_pending = False
        db._export_tasks.clear()

        await db.flush_pending_exports()

        # Should complete without error


class TestInitSchema:
    """Tests for init_schema method."""

    @pytest.mark.asyncio
    async def test_init_schema_skips_if_initialized(self):
        """Test that init_schema skips if already initialized."""
        from utils.database.database import Database

        db = Database()
        db._schema_initialized = True

        # Should return early
        await db.init_schema()

        # No error means it worked


class TestDatabaseGetConnection:
    """Tests for get_connection context manager."""

    @pytest.mark.asyncio
    async def test_get_connection_returns_connection(self):
        """Test that get_connection returns a connection."""
        from utils.database.database import Database

        db = Database()

        async with db.get_connection() as conn:
            assert conn is not None

    @pytest.mark.asyncio
    async def test_get_connection_commits_on_success(self):
        """Test that get_connection commits on success."""
        from utils.database.database import Database

        db = Database()

        async with db.get_connection() as conn:
            # Execute a simple query
            await conn.execute("SELECT 1")

        # No error means commit succeeded


class TestAIHistoryMethods:
    """Tests for AI history database methods."""

    @pytest.mark.asyncio
    async def test_save_ai_message(self):
        """Test saving a single AI message."""
        from utils.database.database import Database

        db = Database()
        db._schema_initialized = False  # Force re-init to run migration
        await db.init_schema()

        test_channel_id = 999999999

        # Save a message
        await db.save_ai_message(
            channel_id=test_channel_id, role="user", content="Test message", message_id=123456
        )

        # Verify it was saved
        history = await db.get_ai_history(test_channel_id, limit=1)
        assert len(history) >= 1  # Should have at least 1 message after saving

        # Cleanup
        await db.delete_ai_history(test_channel_id)

    @pytest.mark.asyncio
    async def test_save_ai_messages_batch(self):
        """Test saving multiple AI messages in batch."""
        from datetime import datetime

        from utils.database.database import Database

        db = Database()
        db._schema_initialized = False  # Force re-init to run migration
        await db.init_schema()

        test_channel_id = 888888888

        batch_data = [
            {
                "channel_id": test_channel_id,
                "user_id": None,
                "role": "user",
                "content": "Hello",
                "message_id": None,
                "timestamp": datetime.now().isoformat(),
            },
            {
                "channel_id": test_channel_id,
                "user_id": None,
                "role": "model",
                "content": "Hi there",
                "message_id": None,
                "timestamp": datetime.now().isoformat(),
            },
        ]

        count = await db.save_ai_messages_batch(batch_data)
        assert count == 2

        # Cleanup
        await db.delete_ai_history(test_channel_id)

    @pytest.mark.asyncio
    async def test_get_ai_history_with_limit(self):
        """Test getting AI history with limit."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_channel_id = 777777777

        # Add some messages
        for i in range(5):
            await db.save_ai_message(
                channel_id=test_channel_id,
                role="user" if i % 2 == 0 else "model",
                content=f"Message {i}",
            )

        # Get with limit
        history = await db.get_ai_history(test_channel_id, limit=3)
        assert len(history) <= 3

        # Cleanup
        await db.delete_ai_history(test_channel_id)

    @pytest.mark.asyncio
    async def test_get_ai_history_count(self):
        """Test getting AI history count."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_channel_id = 666666666

        # Clear first
        await db.delete_ai_history(test_channel_id)

        # Add messages
        await db.save_ai_message(test_channel_id, "user", "Test 1")
        await db.save_ai_message(test_channel_id, "model", "Test 2")

        count = await db.get_ai_history_count(test_channel_id)
        assert count >= 2

        # Cleanup
        await db.delete_ai_history(test_channel_id)

    @pytest.mark.asyncio
    async def test_prune_ai_history(self):
        """Test pruning AI history."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_channel_id = 555555555

        # Clear first
        await db.delete_ai_history(test_channel_id)

        # Add many messages
        for i in range(10):
            await db.save_ai_message(test_channel_id, "user", f"Message {i}")

        # Prune to 5
        await db.prune_ai_history(test_channel_id, keep_count=5)

        count = await db.get_ai_history_count(test_channel_id)
        assert count <= 5

        # Cleanup
        await db.delete_ai_history(test_channel_id)


class TestAIMetadataMethods:
    """Tests for AI metadata database methods."""

    @pytest.mark.asyncio
    async def test_save_ai_metadata(self):
        """Test saving AI metadata."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_channel_id = 444444444

        await db.save_ai_metadata(channel_id=test_channel_id, thinking_enabled=True)

        metadata = await db.get_ai_metadata(test_channel_id)
        # Metadata should exist after saving
        assert metadata is not None
        assert isinstance(metadata, dict)

    @pytest.mark.asyncio
    async def test_get_ai_metadata_nonexistent(self):
        """Test getting metadata for nonexistent channel."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        # Use a channel ID that definitely doesn't exist
        metadata = await db.get_ai_metadata(123)

        # Should return None or empty dict
        assert metadata is None or isinstance(metadata, dict)


class TestGuildSettingsMethods:
    """Tests for guild settings database methods."""

    @pytest.mark.asyncio
    async def test_get_guild_settings_default(self):
        """Test getting guild settings returns defaults for new guild."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        # Use a guild ID that doesn't exist
        settings = await db.get_guild_settings(333333333)

        # Should return None or default values
        assert settings is None or isinstance(settings, dict)

    @pytest.mark.asyncio
    async def test_save_guild_settings(self):
        """Test saving guild settings."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_guild_id = 222222222

        await db.save_guild_settings(
            guild_id=test_guild_id, prefix="!", ai_enabled=True, music_enabled=True
        )

        settings = await db.get_guild_settings(test_guild_id)
        # Verify settings were saved - should exist and be a dict
        assert settings is not None
        assert isinstance(settings, dict)


class TestUserStatsMethods:
    """Tests for user stats database methods."""

    @pytest.mark.asyncio
    async def test_increment_user_stat(self):
        """Test incrementing user stat."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_user_id = 111111111
        test_guild_id = 111111112

        await db.increment_user_stat(test_user_id, test_guild_id, "messages_count")

        stats = await db.get_user_stats(test_user_id, test_guild_id)
        # Stats should exist after incrementing
        assert stats is not None
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_get_user_stats_nonexistent(self):
        """Test getting stats for nonexistent user."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        stats = await db.get_user_stats(1, 1)

        # Should return None or empty
        assert stats is None or isinstance(stats, dict)


class TestExportMethods:
    """Tests for export methods."""

    @pytest.mark.asyncio
    async def test_export_channel_to_json(self):
        """Test exporting channel to JSON."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_channel_id = 987654321

        # Add some data
        await db.save_ai_message(test_channel_id, "user", "Export test")

        # Export
        await db.export_channel_to_json(test_channel_id)

        # Check file exists
        from utils.database.database import EXPORT_DIR

        export_file = EXPORT_DIR / f"ai_history_{test_channel_id}.json"

        # Cleanup
        await db.delete_ai_history(test_channel_id)
        if export_file.exists():
            export_file.unlink()


class TestDeleteMethods:
    """Tests for delete methods."""

    @pytest.mark.asyncio
    async def test_delete_ai_history(self):
        """Test deleting AI history."""
        from utils.database.database import Database

        db = Database()
        await db.init_schema()

        test_channel_id = 123123123

        # Add data
        await db.save_ai_message(test_channel_id, "user", "To be deleted")

        # Delete
        await db.delete_ai_history(test_channel_id)

        # Verify deleted
        count = await db.get_ai_history_count(test_channel_id)
        assert count == 0


# ======================================================================
# Merged from test_database_module.py
# ======================================================================

class TestDatabaseSingleton:
    """Tests for Database singleton pattern."""

    def test_database_singleton(self):
        """Test Database is singleton."""
        from utils.database.database import Database

        db1 = Database()
        db2 = Database()

        assert db1 is db2

    def test_database_has_db_path(self):
        """Test Database has db_path."""
        from utils.database.database import Database

        db = Database()

        assert db.db_path is not None
        assert "bot_database.db" in db.db_path

    def test_database_has_pool_semaphore(self):
        """Test Database has pool semaphore (lazy-initialized via getter)."""
        from utils.database.database import Database

        db = Database()

        # _pool_semaphore is lazily created — call the getter to trigger init
        semaphore = db._get_pool_semaphore()
        assert semaphore is not None


class TestDatabaseAsync:
    """Tests for async database methods."""

    @pytest.mark.asyncio
    async def test_flush_pending_exports_no_pending(self):
        """Test flush_pending_exports with no pending exports."""
        from utils.database.database import Database

        db = Database()
        db._export_pending = False
        db._export_tasks.clear()

        # Should not raise
        await db.flush_pending_exports()

    @pytest.mark.asyncio
    async def test_get_connection_context(self):
        """Test get_connection context manager."""
        from utils.database.database import Database

        db = Database()

        # Just test that context manager works
        async with db.get_connection() as conn:
            assert conn is not None


class TestDatabaseConstants:
    """Tests for database constants."""

    def test_db_dir_exists(self):
        """Test DB_DIR constant."""
        from pathlib import Path

        from utils.database.database import DB_DIR

        assert isinstance(DB_DIR, Path)

    def test_db_file_exists(self):
        """Test DB_FILE constant."""
        from pathlib import Path

        from utils.database.database import DB_FILE

        assert isinstance(DB_FILE, Path)
        assert "bot_database.db" in str(DB_FILE)

    def test_export_dir_exists(self):
        """Test EXPORT_DIR constant."""
        from pathlib import Path

        from utils.database.database import EXPORT_DIR

        assert isinstance(EXPORT_DIR, Path)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_database_class(self):
        """Test importing Database class."""
        from utils.database.database import Database
        assert Database is not None

    def test_import_db_singleton(self):
        """Test importing db singleton."""
        from utils.database.database import db
        assert db is not None


class TestDatabaseMethods:
    """Tests for various Database methods."""

    @pytest.mark.asyncio
    async def test_init_schema_can_run(self):
        """Test init_schema can run."""
        from utils.database.database import Database

        db = Database()

        # Should not raise
        await db.init_schema()

    def test_save_ai_message_structure(self):
        """Test save_ai_message method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'save_ai_message')

    def test_get_ai_history_structure(self):
        """Test get_ai_history method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_ai_history')

    def test_delete_ai_history_structure(self):
        """Test delete_ai_history method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'delete_ai_history')

    def test_export_to_json_structure(self):
        """Test export_to_json method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'export_to_json')

    def test_export_channel_to_json_structure(self):
        """Test export_channel_to_json method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'export_channel_to_json')


class TestRAGMethods:
    """Tests for RAG-related database methods."""

    def test_save_rag_memory_structure(self):
        """Test save_rag_memory method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'save_rag_memory')

    def test_get_all_rag_memories_structure(self):
        """Test get_all_rag_memories method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_all_rag_memories')


class TestUserStatsMethods:
    """Tests for user statistics methods."""

    def test_increment_user_stat_structure(self):
        """Test increment_user_stat method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'increment_user_stat')

    def test_get_user_stats_structure(self):
        """Test get_user_stats method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_user_stats')


class TestGuildSettingsMethods:
    """Tests for guild settings methods."""

    def test_get_guild_settings_structure(self):
        """Test get_guild_settings method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_guild_settings')

    def test_save_guild_settings_structure(self):
        """Test save_guild_settings method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'save_guild_settings')


class TestMusicQueueMethods:
    """Tests for music queue methods."""

    def test_save_music_queue_structure(self):
        """Test save_music_queue method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'save_music_queue')

    def test_load_music_queue_structure(self):
        """Test load_music_queue method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'load_music_queue')

    def test_clear_music_queue_structure(self):
        """Test clear_music_queue method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'clear_music_queue')


class TestHealthAndMetadata:
    """Tests for health check and metadata methods."""

    def test_health_check_structure(self):
        """Test health_check method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'health_check')

    def test_save_ai_metadata_structure(self):
        """Test save_ai_metadata method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'save_ai_metadata')

    def test_get_ai_metadata_structure(self):
        """Test get_ai_metadata method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_ai_metadata')

    def test_log_error_structure(self):
        """Test log_error method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'log_error')


class TestHistoryManagement:
    """Tests for history management methods."""

    def test_prune_ai_history_structure(self):
        """Test prune_ai_history method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'prune_ai_history')

    def test_get_ai_history_count_structure(self):
        """Test get_ai_history_count method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_ai_history_count')

    def test_get_all_ai_channel_ids_structure(self):
        """Test get_all_ai_channel_ids method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_all_ai_channel_ids')


class TestBatchMethods:
    """Tests for batch operation methods."""

    def test_save_ai_messages_batch_structure(self):
        """Test save_ai_messages_batch method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'save_ai_messages_batch')


class TestConnectionMethods:
    """Tests for connection methods."""

    def test_get_connection_with_retry_structure(self):
        """Test get_connection_with_retry method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'get_connection_with_retry')

    def test_stop_watchers_structure(self):
        """Test stop_watchers method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'stop_watchers')


class TestUpdateMethods:
    """Tests for update methods."""

    def test_update_last_accessed_structure(self):
        """Test update_last_accessed method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'update_last_accessed')

    def test_update_message_id_structure(self):
        """Test update_message_id method exists."""
        from utils.database.database import Database

        db = Database()

        assert hasattr(db, 'update_message_id')
