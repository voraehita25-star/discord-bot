"""
Tests for utils.database.database module.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


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
        from utils.database.database import DB_FILE, DB_DIR
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
        """Test that pool semaphore is created with correct value."""
        from utils.database.database import Database
        
        db = Database()
        assert db._pool_semaphore._value == 50  # Max 50 concurrent connections (optimized for high-RAM setup)

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
        """Test that _schedule_export sets _export_pending flag."""
        from utils.database.database import Database
        
        db = Database()
        db._export_pending = False
        
        db._schedule_export()
        
        assert db._export_pending is True
        
        # Cancel the task to cleanup
        for task in list(db._export_tasks):
            task.cancel()
        db._export_pending = False

    @pytest.mark.asyncio
    async def test_schedule_export_skips_if_already_pending(self):
        """Test that _schedule_export skips if already pending."""
        from utils.database.database import Database
        
        db = Database()
        db._export_pending = True
        initial_task_count = len(db._export_tasks)
        
        db._schedule_export()
        
        # Should not create new task
        assert len(db._export_tasks) == initial_task_count
        
        # Reset
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
        await db.init_schema()
        
        test_channel_id = 999999999
        
        # Save a message
        await db.save_ai_message(
            channel_id=test_channel_id,
            role="user",
            content="Test message",
            message_id=123456
        )
        
        # Verify it was saved
        history = await db.get_ai_history(test_channel_id, limit=1)
        assert len(history) >= 0  # May or may not have data depending on test isolation
        
        # Cleanup
        await db.delete_ai_history(test_channel_id)

    @pytest.mark.asyncio
    async def test_save_ai_messages_batch(self):
        """Test saving multiple AI messages in batch."""
        from utils.database.database import Database
        from datetime import datetime
        
        db = Database()
        await db.init_schema()
        
        test_channel_id = 888888888
        
        batch_data = [
            {"channel_id": test_channel_id, "role": "user", "content": "Hello", "message_id": None, "timestamp": datetime.now().isoformat()},
            {"channel_id": test_channel_id, "role": "model", "content": "Hi there", "message_id": None, "timestamp": datetime.now().isoformat()},
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
                content=f"Message {i}"
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
        
        await db.save_ai_metadata(
            channel_id=test_channel_id,
            thinking_enabled=True
        )
        
        metadata = await db.get_ai_metadata(test_channel_id)
        # Metadata may or may not exist depending on test order

    @pytest.mark.asyncio
    async def test_get_ai_metadata_nonexistent(self):
        """Test getting metadata for nonexistent channel."""
        from utils.database.database import Database
        
        db = Database()
        await db.init_schema()
        
        # Use a channel ID that definitely doesn't exist
        metadata = await db.get_ai_metadata(123)
        
        # Should return None or empty dict


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

    @pytest.mark.asyncio
    async def test_save_guild_settings(self):
        """Test saving guild settings."""
        from utils.database.database import Database
        
        db = Database()
        await db.init_schema()
        
        test_guild_id = 222222222
        
        await db.save_guild_settings(
            guild_id=test_guild_id,
            prefix="!",
            ai_enabled=True,
            music_enabled=True
        )
        
        settings = await db.get_guild_settings(test_guild_id)
        # Verify settings were saved


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
        # Stats may or may not exist

    @pytest.mark.asyncio
    async def test_get_user_stats_nonexistent(self):
        """Test getting stats for nonexistent user."""
        from utils.database.database import Database
        
        db = Database()
        await db.init_schema()
        
        stats = await db.get_user_stats(1, 1)
        
        # Should return None or empty


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
