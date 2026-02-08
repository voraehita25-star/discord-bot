"""Extended tests for database module."""


import pytest


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
        """Test Database has pool semaphore."""
        from utils.database.database import Database

        db = Database()

        assert db._pool_semaphore is not None


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
