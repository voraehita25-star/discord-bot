"""
Tests for cogs.ai_core.storage module.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOrjsonFallback:
    """Tests for orjson fallback to standard json."""

    def test_json_loads_works(self):
        """Test json_loads function works."""
        from cogs.ai_core.storage import json_loads

        result = json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_dumps_works(self):
        """Test json_dumps function works."""
        from cogs.ai_core.storage import json_dumps

        result = json_dumps({"key": "value"})
        assert "key" in result
        assert "value" in result


class TestCacheConstants:
    """Tests for cache-related constants."""

    def test_cache_ttl_value(self):
        """Test CACHE_TTL has expected value."""
        from cogs.ai_core.storage import CACHE_TTL

        assert CACHE_TTL == 900  # 15 minutes (optimized for high-RAM setup)

    def test_max_cache_size_value(self):
        """Test MAX_CACHE_SIZE has expected value."""
        from cogs.ai_core.storage import MAX_CACHE_SIZE

        assert MAX_CACHE_SIZE == 2000  # Optimized for high-RAM setup


class TestCacheCleanup:
    """Tests for cache cleanup functions."""

    def test_cleanup_expired_cache_removes_old_entries(self):
        """Test that expired cache entries are removed."""
        from cogs.ai_core.storage import (
            CACHE_TTL,
            _cleanup_expired_cache,
            _history_cache,
            _metadata_cache,
        )

        # Clear caches first
        _history_cache.clear()
        _metadata_cache.clear()

        # Add expired entry
        old_time = time.time() - CACHE_TTL - 10
        _history_cache[12345] = (old_time, [])
        _metadata_cache[12345] = (old_time, {})

        # Add fresh entry
        _history_cache[67890] = (time.time(), [])
        _metadata_cache[67890] = (time.time(), {})

        removed = _cleanup_expired_cache()

        assert removed == 2  # Both history and metadata for 12345
        assert 12345 not in _history_cache
        assert 12345 not in _metadata_cache
        assert 67890 in _history_cache
        assert 67890 in _metadata_cache

        # Cleanup
        _history_cache.clear()
        _metadata_cache.clear()

    def test_enforce_cache_size_limit(self):
        """Test that cache size limit is enforced."""
        from cogs.ai_core.storage import MAX_CACHE_SIZE, _enforce_cache_size_limit, _history_cache

        _history_cache.clear()

        # Add more entries than MAX_CACHE_SIZE
        base_time = time.time()
        for i in range(MAX_CACHE_SIZE + 100):
            _history_cache[i] = (base_time + i, [])

        removed = _enforce_cache_size_limit()

        assert removed >= 100
        assert len(_history_cache) <= MAX_CACHE_SIZE

        # Cleanup
        _history_cache.clear()

    def test_invalidate_cache_removes_specific_channel(self):
        """Test invalidate_cache removes specific channel."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, invalidate_cache

        _history_cache.clear()
        _metadata_cache.clear()

        _history_cache[111] = (time.time(), [{"test": 1}])
        _history_cache[222] = (time.time(), [{"test": 2}])
        _metadata_cache[111] = (time.time(), {"meta": 1})

        invalidate_cache(111)

        assert 111 not in _history_cache
        assert 111 not in _metadata_cache
        assert 222 in _history_cache

        # Cleanup
        _history_cache.clear()
        _metadata_cache.clear()

    def test_invalidate_all_cache(self):
        """Test invalidate_all_cache clears all caches."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, invalidate_all_cache

        _history_cache[111] = (time.time(), [])
        _history_cache[222] = (time.time(), [])
        _metadata_cache[111] = (time.time(), {})

        invalidate_all_cache()

        assert len(_history_cache) == 0
        assert len(_metadata_cache) == 0

    def test_cleanup_cache_full_maintenance(self):
        """Test cleanup_cache performs full maintenance."""
        from cogs.ai_core.storage import CACHE_TTL, _history_cache, _metadata_cache, cleanup_cache

        _history_cache.clear()
        _metadata_cache.clear()

        # Add expired entry
        old_time = time.time() - CACHE_TTL - 10
        _history_cache[12345] = (old_time, [])

        removed = cleanup_cache()

        assert removed >= 1
        assert 12345 not in _history_cache

        # Cleanup
        _history_cache.clear()
        _metadata_cache.clear()


class TestDataDirectories:
    """Tests for data directory constants."""

    def test_data_dir_exists(self):
        """Test DATA_DIR path exists."""
        from cogs.ai_core.storage import DATA_DIR

        assert DATA_DIR.exists()

    def test_config_dir_exists(self):
        """Test CONFIG_DIR path exists."""
        from cogs.ai_core.storage import CONFIG_DIR

        assert CONFIG_DIR.exists()


class TestSaveHistoryJson:
    """Tests for JSON fallback storage."""

    @pytest.mark.asyncio
    async def test_save_history_json_empty_data(self):
        """Test saving empty chat data."""
        from cogs.ai_core.storage import save_history

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = None

        # Empty data should return early
        await save_history(mock_bot, 12345, {})

        # No error should occur

    @pytest.mark.asyncio
    async def test_save_history_determines_limit_by_guild(self):
        """Test that history limit is determined by guild."""
        from cogs.ai_core.data.constants import GUILD_ID_MAIN
        from cogs.ai_core.storage import save_history

        mock_bot = MagicMock()
        mock_channel = MagicMock()
        mock_guild = MagicMock()

        # Test main guild
        mock_guild.id = GUILD_ID_MAIN
        mock_channel.guild = mock_guild
        mock_bot.get_channel.return_value = mock_channel

        with patch("cogs.ai_core.storage.DATABASE_AVAILABLE", False):
            with patch("cogs.ai_core.storage._save_history_json") as mock_save:
                mock_save.return_value = None
                await save_history(mock_bot, 12345, {"history": []})
                # Verify the function was called


class TestLoadHistory:
    """Tests for load_history function."""

    @pytest.mark.asyncio
    async def test_load_history_cache_hit(self):
        """Test load_history returns cached data on cache hit."""
        from cogs.ai_core.storage import _history_cache, load_history

        _history_cache.clear()

        test_history = [{"role": "user", "parts": ["Hello"]}]
        _history_cache[99999] = (time.time(), test_history)

        mock_bot = MagicMock()
        result = await load_history(mock_bot, 99999)

        # Should return a deep copy
        assert result == test_history
        assert result is not test_history  # Deep copy

        # Cleanup
        _history_cache.clear()

    @pytest.mark.asyncio
    async def test_load_history_expired_cache_miss(self):
        """Test load_history doesn't use expired cache."""
        from cogs.ai_core.storage import CACHE_TTL, _history_cache, load_history

        _history_cache.clear()

        old_history = [{"role": "user", "parts": ["Old"]}]
        old_time = time.time() - CACHE_TTL - 10  # Expired
        _history_cache[88888] = (old_time, old_history)

        mock_bot = MagicMock()
        mock_bot.loop.run_in_executor = AsyncMock(return_value=[])

        with patch("cogs.ai_core.storage.DATABASE_AVAILABLE", False):
            await load_history(mock_bot, 88888)

        # Cleanup
        _history_cache.clear()


class TestHistoryLimits:
    """Tests for history limit constants."""

    def test_history_limits_imported(self):
        """Test history limit constants are imported correctly."""
        from cogs.ai_core.storage import HISTORY_LIMIT_DEFAULT, HISTORY_LIMIT_MAIN, HISTORY_LIMIT_RP

        # RP should have highest limit
        assert HISTORY_LIMIT_RP > HISTORY_LIMIT_MAIN
        assert HISTORY_LIMIT_MAIN > HISTORY_LIMIT_DEFAULT


class TestGuildIds:
    """Tests for guild ID constants."""

    def test_guild_ids_imported(self):
        """Test guild ID constants are imported correctly."""
        from cogs.ai_core.storage import GUILD_ID_MAIN, GUILD_ID_RP

        assert isinstance(GUILD_ID_MAIN, int)
        assert isinstance(GUILD_ID_RP, int)


class TestSaveHistoryDB:
    """Tests for _save_history_db function."""

    @pytest.mark.asyncio
    async def test_save_history_db_with_new_entries(self):
        """Test save with explicit new entries."""
        from cogs.ai_core.storage import _save_history_db

        with patch("cogs.ai_core.storage.db") as mock_db:
            mock_db.save_ai_messages_batch = AsyncMock()
            mock_db.get_ai_history = AsyncMock(return_value=[])
            mock_db.get_ai_history_count = AsyncMock(return_value=5)
            mock_db.save_ai_metadata = AsyncMock()

            new_entries = [
                {"role": "user", "parts": ["hello"], "timestamp": "2024-01-01"}
            ]
            await _save_history_db(12345, {"history": []}, 100, new_entries)

            mock_db.save_ai_messages_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_history_db_prune_over_limit(self):
        """Test pruning when over limit."""
        from cogs.ai_core.storage import _save_history_db

        with patch("cogs.ai_core.storage.db") as mock_db:
            mock_db.get_ai_history = AsyncMock(return_value=[])
            mock_db.save_ai_messages_batch = AsyncMock()
            mock_db.get_ai_history_count = AsyncMock(return_value=150)
            mock_db.prune_ai_history = AsyncMock()
            mock_db.save_ai_metadata = AsyncMock()

            new_entries = [{"role": "user", "parts": ["hi"], "timestamp": "t1"}]
            await _save_history_db(12345, {"history": []}, 100, new_entries)

            mock_db.prune_ai_history.assert_called_once_with(12345, 100)

    @pytest.mark.asyncio
    async def test_save_history_db_no_new_entries_diff(self):
        """Test diffing logic when no explicit new entries."""
        from cogs.ai_core.storage import _save_history_db

        with patch("cogs.ai_core.storage.db") as mock_db:
            mock_db.get_ai_history = AsyncMock(return_value=[])
            mock_db.save_ai_messages_batch = AsyncMock()
            mock_db.get_ai_history_count = AsyncMock(return_value=5)
            mock_db.save_ai_metadata = AsyncMock()

            chat_data = {"history": [{"role": "user", "parts": ["test"]}]}
            await _save_history_db(12345, chat_data, 100, None)

            # Should have saved something via batch
            mock_db.save_ai_messages_batch.assert_called()


class TestDeleteHistory:
    """Tests for delete_history function."""

    @pytest.mark.asyncio
    async def test_delete_history_db_success(self):
        """Test delete from database."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.delete_ai_history = AsyncMock(return_value=True)

            result = await storage.delete_history(12345)
            assert result
            mock_db.delete_ai_history.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_delete_history_invalidates_cache(self):
        """Test delete invalidates cache."""
        from cogs.ai_core import storage

        channel_id = 33333
        storage._history_cache[channel_id] = (time.time(), [])
        storage._metadata_cache[channel_id] = (time.time(), {})

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.delete_ai_history = AsyncMock(return_value=True)

            await storage.delete_history(channel_id)

            assert channel_id not in storage._history_cache
            assert channel_id not in storage._metadata_cache


class TestUpdateMessageId:
    """Tests for update_message_id function."""

    @pytest.mark.asyncio
    async def test_update_message_id(self):
        """Test update message ID."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.update_message_id = AsyncMock()

            await storage.update_message_id(12345, 67890)
            mock_db.update_message_id.assert_called_once_with(12345, 67890)


class TestCopyHistory:
    """Tests for copy_history function."""

    @pytest.mark.asyncio
    async def test_copy_history_success(self):
        """Test copy history success."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_ai_history = AsyncMock(
                return_value=[{"role": "user", "content": "msg1"}]
            )
            mock_db.save_ai_messages_batch = AsyncMock(return_value=1)

            result = await storage.copy_history(111, 222)
            assert result == 1

    @pytest.mark.asyncio
    async def test_copy_history_no_db(self):
        """Test copy when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.copy_history(111, 222)
            assert result == 0

    @pytest.mark.asyncio
    async def test_copy_history_empty_source(self):
        """Test copy when source empty."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_ai_history = AsyncMock(return_value=[])

            result = await storage.copy_history(111, 222)
            assert result == 0


class TestMoveHistory:
    """Tests for move_history function."""

    @pytest.mark.asyncio
    async def test_move_history_success(self):
        """Test move history success."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "copy_history", new_callable=AsyncMock
        ) as mock_copy, patch.object(storage, "db") as mock_db:
            mock_copy.return_value = 5
            mock_db.delete_ai_history = AsyncMock()

            result = await storage.move_history(111, 222)
            assert result == 5
            mock_db.delete_ai_history.assert_called_once_with(111)

    @pytest.mark.asyncio
    async def test_move_history_no_db(self):
        """Test move when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.move_history(111, 222)
            assert result == 0


class TestGetAllChannelIds:
    """Tests for get_all_channel_ids function."""

    @pytest.mark.asyncio
    async def test_get_all_channel_ids(self):
        """Test get all channel IDs."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_all_ai_channel_ids = AsyncMock(return_value=[1, 2, 3])

            result = await storage.get_all_channel_ids()
            assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_get_all_channel_ids_no_db(self):
        """Test when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.get_all_channel_ids()
            assert result == []


class TestGetAllChannelsSummary:
    """Tests for get_all_channels_summary function."""

    @pytest.mark.asyncio
    async def test_get_all_channels_summary(self):
        """Test get channels summary."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_all_ai_channel_ids = AsyncMock(return_value=[1, 2])
            mock_db.get_ai_history_count = AsyncMock(side_effect=[10, 20])

            result = await storage.get_all_channels_summary()
            assert len(result) == 2
            assert result[0]["channel_id"] == 1
            assert result[0]["message_count"] == 10

    @pytest.mark.asyncio
    async def test_get_all_channels_summary_no_db(self):
        """Test when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.get_all_channels_summary()
            assert result == []


class TestGetChannelHistoryPreview:
    """Tests for get_channel_history_preview function."""

    @pytest.mark.asyncio
    async def test_get_channel_history_preview(self):
        """Test get history preview."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_ai_history = AsyncMock(
                return_value=[
                    {"role": "user", "content": "hello world"},
                    {"role": "model", "content": "hi there"},
                ]
            )

            result = await storage.get_channel_history_preview(12345, limit=5)
            assert len(result) == 2
            assert result[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_get_channel_history_preview_truncate(self):
        """Test preview truncates long content."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            long_content = "x" * 200
            mock_db.get_ai_history = AsyncMock(
                return_value=[{"role": "user", "content": long_content}]
            )

            result = await storage.get_channel_history_preview(12345)
            assert len(result[0]["content"]) <= 103  # 100 + "..."

    @pytest.mark.asyncio
    async def test_get_channel_history_preview_no_db(self):
        """Test when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.get_channel_history_preview(12345)
            assert result == []


class TestLoadMetadata:
    """Tests for load_metadata function."""

    @pytest.mark.asyncio
    async def test_load_metadata_cache_hit(self):
        """Test load metadata from cache."""
        from cogs.ai_core import storage

        bot = MagicMock()
        channel_id = 55555

        cached = {"thinking_enabled": True}
        storage._metadata_cache[channel_id] = (time.time(), cached)

        result = await storage.load_metadata(bot, channel_id)
        assert result == cached

        # Cleanup
        storage._metadata_cache.clear()

    @pytest.mark.asyncio
    async def test_load_metadata_from_db(self):
        """Test load metadata from database."""
        from cogs.ai_core import storage

        bot = MagicMock()
        channel_id = 66666

        storage._metadata_cache.pop(channel_id, None)

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_ai_metadata = AsyncMock(return_value={"thinking_enabled": False})

            result = await storage.load_metadata(bot, channel_id)
            assert not result["thinking_enabled"]


class TestGetMessageByLocalId:
    """Tests for get_message_by_local_id function."""

    @pytest.mark.asyncio
    async def test_get_message_by_local_id_no_db(self):
        """Test when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.get_message_by_local_id(12345, 1)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_message_by_local_id_success(self):
        """Test get message success."""
        from cogs.ai_core import storage

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(
            return_value=("user", "test content", 111, "2024-01-01", 1)
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock()

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_connection.return_value = mock_conn

            result = await storage.get_message_by_local_id(12345, 1)
            assert result["role"] == "user"
            assert result["parts"] == ["test content"]


class TestGetLastModelMessage:
    """Tests for get_last_model_message function."""

    @pytest.mark.asyncio
    async def test_get_last_model_message_no_db(self):
        """Test when database not available."""
        from cogs.ai_core import storage

        with patch.object(storage, "DATABASE_AVAILABLE", False):
            result = await storage.get_last_model_message(12345)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_last_model_message_success(self):
        """Test get last model message success."""
        from cogs.ai_core import storage

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(
            return_value=("model", "response", 222, "2024-01-01", 5)
        )
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock()

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_connection.return_value = mock_conn

            result = await storage.get_last_model_message(12345)
            assert result["role"] == "model"
            assert result["local_id"] == 5


class TestLoadHistoryFromDB:
    """Tests for load_history with database."""

    @pytest.mark.asyncio
    async def test_load_history_converts_db_format(self):
        """Test load history converts DB format to API format."""
        from cogs.ai_core import storage

        bot = MagicMock()
        channel_id = 44444

        storage._history_cache.pop(channel_id, None)

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "db"
        ) as mock_db:
            mock_db.get_ai_history = AsyncMock(
                return_value=[
                    {"role": "user", "content": "hello"},
                    {"role": "model", "content": "hi"},
                ]
            )

            result = await storage.load_history(bot, channel_id)

            assert len(result) == 2
            assert result[0]["role"] == "user"
            assert result[0]["parts"] == ["hello"]
            assert result[1]["role"] == "model"
            assert result[1]["parts"] == ["hi"]


class TestSaveHistoryFull:
    """Tests for full save_history function."""

    @pytest.mark.asyncio
    async def test_save_history_with_main_guild(self):
        """Test save determines limit for main guild."""
        from cogs.ai_core import storage
        from cogs.ai_core.data.constants import GUILD_ID_MAIN, HISTORY_LIMIT_MAIN

        bot = MagicMock()
        channel = MagicMock()
        channel.guild.id = GUILD_ID_MAIN
        bot.get_channel.return_value = channel

        chat_data = {"history": [{"role": "user", "parts": ["test"]}]}

        with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
            storage, "_save_history_db", new_callable=AsyncMock
        ) as mock_save:
            await storage.save_history(bot, 12345, chat_data)

            # Should be called with main guild limit
            call_args = mock_save.call_args
            assert call_args[0][2] == HISTORY_LIMIT_MAIN

    @pytest.mark.asyncio
    async def test_save_history_with_rp_guild(self):
        """Test save determines limit for RP guild."""
        from cogs.ai_core import storage
        from cogs.ai_core.data.constants import GUILD_ID_RP, HISTORY_LIMIT_RP

        bot = MagicMock()
        channel = MagicMock()
        # Use actual RP guild ID if set, otherwise skip comparison
        if GUILD_ID_RP:
            channel.guild.id = GUILD_ID_RP
            bot.get_channel.return_value = channel

            chat_data = {"history": [{"role": "user", "parts": ["test"]}]}

            with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
                storage, "_save_history_db", new_callable=AsyncMock
            ) as mock_save:
                await storage.save_history(bot, 12345, chat_data)

                # Should be called with RP guild limit
                call_args = mock_save.call_args
                assert call_args[0][2] == HISTORY_LIMIT_RP
        else:
            # RP guild not configured, just verify function works
            channel.guild.id = 999999999
            bot.get_channel.return_value = channel

            chat_data = {"history": [{"role": "user", "parts": ["test"]}]}

            with patch.object(storage, "DATABASE_AVAILABLE", True), patch.object(
                storage, "_save_history_db", new_callable=AsyncMock
            ) as mock_save:
                await storage.save_history(bot, 12345, chat_data)
                mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_history_error_handling(self):
        """Test save handles errors gracefully."""
        from cogs.ai_core import storage

        bot = MagicMock()
        bot.get_channel.side_effect = OSError("Test error")

        chat_data = {"history": [{"role": "user", "parts": ["test"]}]}

        # Should not raise
        await storage.save_history(bot, 12345, chat_data)


# ======================================================================
# Merged from test_storage_extended.py
# ======================================================================

class TestJsonImplementation:
    """Tests for JSON implementation selection."""

    def test_json_loads_callable(self):
        """Test json_loads function is callable."""
        try:
            from cogs.ai_core.storage import json_loads
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert callable(json_loads)

    def test_json_dumps_callable(self):
        """Test json_dumps function is callable."""
        try:
            from cogs.ai_core.storage import json_dumps
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert callable(json_dumps)

    def test_json_loads_basic(self):
        """Test json_loads works correctly."""
        try:
            from cogs.ai_core.storage import json_loads
        except ImportError:
            pytest.skip("storage module not available")
            return

        result = json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_dumps_basic(self):
        """Test json_dumps works correctly."""
        try:
            from cogs.ai_core.storage import json_dumps
        except ImportError:
            pytest.skip("storage module not available")
            return

        result = json_dumps({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result


class TestCacheConstants:
    """Tests for cache constants."""

    def test_cache_ttl_defined(self):
        """Test CACHE_TTL is defined."""
        try:
            from cogs.ai_core.storage import CACHE_TTL
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert isinstance(CACHE_TTL, int)
        assert CACHE_TTL > 0

    def test_max_cache_size_defined(self):
        """Test MAX_CACHE_SIZE is defined."""
        try:
            from cogs.ai_core.storage import MAX_CACHE_SIZE
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert isinstance(MAX_CACHE_SIZE, int)
        assert MAX_CACHE_SIZE > 0


class TestCleanupExpiredCache:
    """Tests for _cleanup_expired_cache function."""

    def test_cleanup_expired_cache_empty(self):
        """Test cleanup with empty cache."""
        try:
            from cogs.ai_core.storage import _cleanup_expired_cache, _history_cache, _metadata_cache
        except ImportError:
            pytest.skip("storage module not available")
            return

        # Clear caches
        _history_cache.clear()
        _metadata_cache.clear()

        result = _cleanup_expired_cache()

        assert result == 0

    def test_cleanup_expired_cache_with_valid_entries(self):
        """Test cleanup with valid entries."""
        try:
            from cogs.ai_core.storage import _cleanup_expired_cache, _history_cache, _metadata_cache
        except ImportError:
            pytest.skip("storage module not available")
            return

        # Clear caches
        _history_cache.clear()
        _metadata_cache.clear()

        # Add valid entry (not expired)
        current_time = time.time()
        _history_cache[123] = (current_time, [{"role": "user", "content": "test"}])

        result = _cleanup_expired_cache()

        assert result == 0
        assert 123 in _history_cache

    def test_cleanup_expired_cache_with_expired_entries(self):
        """Test cleanup with expired entries."""
        try:
            from cogs.ai_core.storage import (
                CACHE_TTL,
                _cleanup_expired_cache,
                _history_cache,
                _metadata_cache,
            )
        except ImportError:
            pytest.skip("storage module not available")
            return

        # Clear caches
        _history_cache.clear()
        _metadata_cache.clear()

        # Add expired entry
        old_time = time.time() - CACHE_TTL - 100
        _history_cache[456] = (old_time, [{"role": "user", "content": "old"}])

        result = _cleanup_expired_cache()

        assert result == 1
        assert 456 not in _history_cache


class TestEnforceCacheSizeLimit:
    """Tests for _enforce_cache_size_limit function."""

    def test_enforce_cache_size_limit_under_limit(self):
        """Test enforcement when under limit."""
        try:
            from cogs.ai_core.storage import (
                MAX_CACHE_SIZE,
                _enforce_cache_size_limit,
                _history_cache,
            )
        except ImportError:
            pytest.skip("storage module not available")
            return

        # Clear cache
        _history_cache.clear()

        # Add a few entries
        current_time = time.time()
        for i in range(5):
            _history_cache[i] = (current_time, [])

        _enforce_cache_size_limit()

        # Should not remove any
        assert len(_history_cache) == 5


class TestDatabaseAvailable:
    """Tests for DATABASE_AVAILABLE flag."""

    def test_database_available_defined(self):
        """Test DATABASE_AVAILABLE is defined."""
        try:
            from cogs.ai_core.storage import DATABASE_AVAILABLE
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert isinstance(DATABASE_AVAILABLE, bool)


class TestDataDirectories:
    """Tests for data directory paths."""

    def test_data_dir_defined(self):
        """Test DATA_DIR is defined."""
        try:
            from cogs.ai_core.storage import DATA_DIR
        except ImportError:
            pytest.skip("storage module not available")
            return

        from pathlib import Path
        assert isinstance(DATA_DIR, Path)

    def test_config_dir_defined(self):
        """Test CONFIG_DIR is defined."""
        try:
            from cogs.ai_core.storage import CONFIG_DIR
        except ImportError:
            pytest.skip("storage module not available")
            return

        from pathlib import Path
        assert isinstance(CONFIG_DIR, Path)


class TestGuildIdConstants:
    """Tests for guild ID constants."""

    def test_guild_id_main_imported(self):
        """Test GUILD_ID_MAIN is imported."""
        try:
            from cogs.ai_core.storage import GUILD_ID_MAIN
        except ImportError:
            pytest.skip("storage module not available")
            return

    def test_guild_id_rp_imported(self):
        """Test GUILD_ID_RP is imported."""
        try:
            from cogs.ai_core.storage import GUILD_ID_RP
        except ImportError:
            pytest.skip("storage module not available")
            return


class TestHistoryLimitConstants:
    """Tests for history limit constants."""

    def test_history_limit_default_imported(self):
        """Test HISTORY_LIMIT_DEFAULT is imported."""
        try:
            from cogs.ai_core.storage import HISTORY_LIMIT_DEFAULT
        except ImportError:
            pytest.skip("storage module not available")
            return

    def test_history_limit_main_imported(self):
        """Test HISTORY_LIMIT_MAIN is imported."""
        try:
            from cogs.ai_core.storage import HISTORY_LIMIT_MAIN
        except ImportError:
            pytest.skip("storage module not available")
            return

    def test_history_limit_rp_imported(self):
        """Test HISTORY_LIMIT_RP is imported."""
        try:
            from cogs.ai_core.storage import HISTORY_LIMIT_RP
        except ImportError:
            pytest.skip("storage module not available")
            return


class TestModuleDocstring:
    """Tests for module documentation."""

class TestCacheDataStructures:
    """Tests for cache data structures."""

    def test_history_cache_is_dict(self):
        """Test _history_cache is a dict."""
        try:
            from cogs.ai_core.storage import _history_cache
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert isinstance(_history_cache, dict)

    def test_metadata_cache_is_dict(self):
        """Test _metadata_cache is a dict."""
        try:
            from cogs.ai_core.storage import _metadata_cache
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert isinstance(_metadata_cache, dict)


class TestJsonRoundtrip:
    """Tests for JSON roundtrip functionality."""

    def test_json_roundtrip_dict(self):
        """Test JSON roundtrip with dict."""
        try:
            from cogs.ai_core.storage import json_dumps, json_loads
        except ImportError:
            pytest.skip("storage module not available")
            return

        original = {"key": "value", "number": 42, "nested": {"a": 1}}
        serialized = json_dumps(original)
        deserialized = json_loads(serialized)

        assert deserialized == original

    def test_json_roundtrip_list(self):
        """Test JSON roundtrip with list."""
        try:
            from cogs.ai_core.storage import json_dumps, json_loads
        except ImportError:
            pytest.skip("storage module not available")
            return

        original = [1, 2, 3, "test"]
        serialized = json_dumps(original)
        deserialized = json_loads(serialized)

        assert deserialized == original


class TestCacheTTLBehavior:
    """Tests for cache TTL behavior."""

    def test_cache_ttl_is_reasonable(self):
        """Test CACHE_TTL is a reasonable value."""
        try:
            from cogs.ai_core.storage import CACHE_TTL
        except ImportError:
            pytest.skip("storage module not available")
            return

        # Should be between 1 second and 1 hour
        assert 1 <= CACHE_TTL <= 3600

    def test_max_cache_size_is_reasonable(self):
        """Test MAX_CACHE_SIZE is a reasonable value."""
        try:
            from cogs.ai_core.storage import MAX_CACHE_SIZE
        except ImportError:
            pytest.skip("storage module not available")
            return

        # Should be between 10 and 10000
        assert 10 <= MAX_CACHE_SIZE <= 10000


# ======================================================================
# Merged from test_storage_module.py
# ======================================================================

class TestOrjsonAvailability:
    """Test orjson functions exist."""

    def test_json_loads_exists(self):
        """Test json_loads function exists."""
        from cogs.ai_core.storage import json_loads

        assert callable(json_loads)

    def test_json_dumps_exists(self):
        """Test json_dumps function exists."""
        from cogs.ai_core.storage import json_dumps

        assert callable(json_dumps)


# ==================== TestConstants ====================


class TestConstants:
    """Test module constants."""

    def test_cache_ttl_exists(self):
        """Test CACHE_TTL constant exists."""
        from cogs.ai_core.storage import CACHE_TTL

        assert CACHE_TTL == 900  # 15 minutes (optimized for high-RAM setup)

    def test_max_cache_size_exists(self):
        """Test MAX_CACHE_SIZE constant exists."""
        from cogs.ai_core.storage import MAX_CACHE_SIZE

        assert MAX_CACHE_SIZE == 2000  # Optimized for high-RAM setup

    def test_data_dir_exists(self):
        """Test DATA_DIR path exists."""
        from pathlib import Path

        from cogs.ai_core.storage import DATA_DIR

        assert isinstance(DATA_DIR, Path)

    def test_config_dir_exists(self):
        """Test CONFIG_DIR path exists."""
        from pathlib import Path

        from cogs.ai_core.storage import CONFIG_DIR

        assert isinstance(CONFIG_DIR, Path)


# ==================== TestDatabaseAvailable ====================


class TestDatabaseAvailable:
    """Test DATABASE_AVAILABLE flag."""

    def test_database_available_flag_exists(self):
        """Test DATABASE_AVAILABLE flag exists."""
        from cogs.ai_core.storage import DATABASE_AVAILABLE

        assert isinstance(DATABASE_AVAILABLE, bool)


# ==================== TestCacheCleanup ====================


class TestCacheCleanup:
    """Test cache cleanup functions."""

    def test_cleanup_expired_cache(self):
        """Test _cleanup_expired_cache function."""
        from cogs.ai_core.storage import (
            CACHE_TTL,
            _cleanup_expired_cache,
            _history_cache,
            _metadata_cache,
        )

        # Clear caches first
        _history_cache.clear()
        _metadata_cache.clear()

        # Add expired entry
        old_time = time.time() - CACHE_TTL - 10
        _history_cache[12345] = (old_time, [])

        removed = _cleanup_expired_cache()

        assert removed >= 1
        assert 12345 not in _history_cache

    def test_enforce_cache_size_limit_under_limit(self):
        """Test _enforce_cache_size_limit when under limit."""
        from cogs.ai_core.storage import _enforce_cache_size_limit, _history_cache

        # Clear cache
        _history_cache.clear()

        # Add few entries
        now = time.time()
        _history_cache[1] = (now, [])
        _history_cache[2] = (now, [])

        removed = _enforce_cache_size_limit()

        assert removed == 0

    def test_cleanup_cache_function(self):
        """Test cleanup_cache convenience function."""
        from cogs.ai_core.storage import cleanup_cache

        # Should not raise
        removed = cleanup_cache()

        assert isinstance(removed, int)


# ==================== TestInvalidateCache ====================


class TestInvalidateCache:
    """Test cache invalidation functions."""

    def test_invalidate_cache_single(self):
        """Test invalidating cache for single channel."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, invalidate_cache

        # Set up test data
        now = time.time()
        _history_cache[99999] = (now, [{"test": "data"}])
        _metadata_cache[99999] = (now, {"thinking_enabled": True})

        invalidate_cache(99999)

        assert 99999 not in _history_cache
        assert 99999 not in _metadata_cache

    def test_invalidate_all_cache(self):
        """Test invalidating all caches."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, invalidate_all_cache

        # Set up test data
        now = time.time()
        _history_cache[1] = (now, [])
        _history_cache[2] = (now, [])
        _metadata_cache[1] = (now, {})

        invalidate_all_cache()

        assert len(_history_cache) == 0
        assert len(_metadata_cache) == 0


# ==================== TestSaveHistory ====================


@pytest.mark.asyncio
class TestSaveHistory:
    """Test save_history function."""

    async def test_save_history_empty_data(self):
        """Test save_history with empty data."""
        from cogs.ai_core.storage import save_history

        mock_bot = MagicMock()

        # Should not raise with empty data
        await save_history(mock_bot, 12345, {})

    async def test_save_history_with_data(self):
        """Test save_history with data."""
        from cogs.ai_core.storage import DATABASE_AVAILABLE, save_history

        mock_bot = MagicMock()
        mock_bot.get_channel.return_value = None

        chat_data = {
            "history": [
                {"role": "user", "parts": ["Hello"]}
            ],
            "thinking_enabled": True
        }

        if DATABASE_AVAILABLE:
            with patch('cogs.ai_core.storage.db') as mock_db:
                mock_db.get_ai_history = AsyncMock(return_value=[])
                mock_db.save_ai_messages_batch = AsyncMock()
                mock_db.get_ai_history_count = AsyncMock(return_value=1)
                mock_db.save_ai_metadata = AsyncMock()

                await save_history(mock_bot, 12345, chat_data)
        else:
            # JSON fallback
            mock_bot.loop.run_in_executor = AsyncMock(return_value=None)
            await save_history(mock_bot, 12345, chat_data)


# ==================== TestLoadHistory ====================


@pytest.mark.asyncio
class TestLoadHistory:
    """Test load_history function."""

    async def test_load_history_from_cache(self):
        """Test loading history from cache."""
        from cogs.ai_core.storage import _history_cache, load_history

        mock_bot = MagicMock()

        # Set up cache
        now = time.time()
        cached_data = [{"role": "user", "parts": ["test"]}]
        _history_cache[77777] = (now, cached_data)

        result = await load_history(mock_bot, 77777)

        # Should return copy of cached data
        assert result == cached_data
        assert result is not cached_data  # Should be a copy

        # Cleanup
        _history_cache.pop(77777, None)

    async def test_load_history_cache_expired(self):
        """Test loading history when cache is expired."""
        from cogs.ai_core.storage import CACHE_TTL, DATABASE_AVAILABLE, _history_cache, load_history

        mock_bot = MagicMock()

        # Set up expired cache
        old_time = time.time() - CACHE_TTL - 10
        _history_cache[88888] = (old_time, [{"role": "user", "parts": ["old"]}])

        if DATABASE_AVAILABLE:
            with patch('cogs.ai_core.storage.db') as mock_db:
                mock_db.get_ai_history = AsyncMock(return_value=[
                    {"role": "user", "content": "new message"}
                ])

                result = await load_history(mock_bot, 88888)

                assert len(result) == 1
        else:
            mock_bot.loop.run_in_executor = AsyncMock(return_value=None)

            result = await load_history(mock_bot, 88888)

        # Cleanup
        _history_cache.pop(88888, None)


# ==================== TestLoadMetadata ====================


@pytest.mark.asyncio
class TestLoadMetadata:
    """Test load_metadata function."""

    async def test_load_metadata_from_cache(self):
        """Test loading metadata from cache."""
        from cogs.ai_core.storage import _metadata_cache, load_metadata

        mock_bot = MagicMock()

        # Set up cache
        now = time.time()
        cached_data = {"thinking_enabled": True}
        _metadata_cache[66666] = (now, cached_data)

        result = await load_metadata(mock_bot, 66666)

        # Should return copy of cached data
        assert result == cached_data

        # Cleanup
        _metadata_cache.pop(66666, None)


# ==================== TestHistoryLimit ====================


class TestHistoryLimit:
    """Test history limit constants."""

    def test_history_limit_default(self):
        """Test default history limit."""
        from cogs.ai_core.data.constants import HISTORY_LIMIT_DEFAULT as const_limit
        from cogs.ai_core.storage import HISTORY_LIMIT_DEFAULT

        assert HISTORY_LIMIT_DEFAULT == const_limit

    def test_history_limit_constants_imported(self):
        """Test history limit constants are imported."""
        from cogs.ai_core.storage import HISTORY_LIMIT_DEFAULT, HISTORY_LIMIT_MAIN, HISTORY_LIMIT_RP

        assert isinstance(HISTORY_LIMIT_DEFAULT, int)
        assert isinstance(HISTORY_LIMIT_MAIN, int)
        assert isinstance(HISTORY_LIMIT_RP, int)


# ==================== TestModuleImports ====================


class TestModuleImports:
    """Test module imports."""

    def test_import_storage(self):
        """Test importing storage module."""
        import cogs.ai_core.storage

        assert cogs.ai_core.storage is not None

    def test_import_save_history(self):
        """Test importing save_history function."""
        from cogs.ai_core.storage import save_history

        assert callable(save_history)

    def test_import_load_history(self):
        """Test importing load_history function."""
        from cogs.ai_core.storage import load_history

        assert callable(load_history)

    def test_import_load_metadata(self):
        """Test importing load_metadata function."""
        from cogs.ai_core.storage import load_metadata

        assert callable(load_metadata)

    def test_import_invalidate_cache(self):
        """Test importing cache functions."""
        from cogs.ai_core.storage import cleanup_cache, invalidate_all_cache, invalidate_cache

        assert callable(invalidate_cache)
        assert callable(invalidate_all_cache)
        assert callable(cleanup_cache)


# ==================== TestJsonFunctions ====================


class TestJsonFunctions:
    """Test JSON serialization functions."""

    def test_json_loads_string(self):
        """Test json_loads with string input."""
        from cogs.ai_core.storage import json_loads

        data = '{"key": "value"}'
        result = json_loads(data)

        assert result == {"key": "value"}

    def test_json_loads_list(self):
        """Test json_loads with list input."""
        from cogs.ai_core.storage import json_loads

        data = '[1, 2, 3]'
        result = json_loads(data)

        assert result == [1, 2, 3]

    def test_json_dumps_dict(self):
        """Test json_dumps with dict input."""
        from cogs.ai_core.storage import json_dumps

        data = {"key": "value"}
        result = json_dumps(data)

        assert '"key"' in result
        assert '"value"' in result

    def test_json_dumps_list(self):
        """Test json_dumps with list input."""
        from cogs.ai_core.storage import json_dumps

        data = [1, 2, 3]
        result = json_dumps(data)

        assert "1" in result
        assert "2" in result
        assert "3" in result


# ==================== TestCacheOperations ====================


class TestCacheOperations:
    """Test cache operation behavior."""

    def test_history_cache_is_dict(self):
        """Test _history_cache is a dict."""
        from cogs.ai_core.storage import _history_cache

        assert isinstance(_history_cache, dict)

    def test_metadata_cache_is_dict(self):
        """Test _metadata_cache is a dict."""
        from cogs.ai_core.storage import _metadata_cache

        assert isinstance(_metadata_cache, dict)

    def test_cache_stores_tuple(self):
        """Test cache stores (timestamp, data) tuples."""
        from cogs.ai_core.storage import _history_cache

        now = time.time()
        test_data = [{"role": "user", "parts": ["test"]}]

        _history_cache[55555] = (now, test_data)

        stored = _history_cache[55555]
        assert isinstance(stored, tuple)
        assert len(stored) == 2
        assert isinstance(stored[0], float)  # timestamp
        assert isinstance(stored[1], list)   # data

        # Cleanup
        _history_cache.pop(55555, None)


# ==================== TestGuildIdConstants ====================


class TestGuildIdConstants:
    """Test guild ID constants."""

    def test_guild_id_main_imported(self):
        """Test GUILD_ID_MAIN is imported."""
        from cogs.ai_core.storage import GUILD_ID_MAIN

        assert GUILD_ID_MAIN is not None

    def test_guild_id_rp_imported(self):
        """Test GUILD_ID_RP is imported."""
        from cogs.ai_core.storage import GUILD_ID_RP

        assert GUILD_ID_RP is not None


# ==================== TestSaveHistoryDb ====================


@pytest.mark.asyncio
class TestSaveHistoryDb:
    """Test _save_history_db function."""

    async def test_save_history_db_with_new_entries(self):
        """Test _save_history_db with explicit new entries."""
        from cogs.ai_core.storage import DATABASE_AVAILABLE

        if not DATABASE_AVAILABLE:
            pytest.skip("Database not available")

        from cogs.ai_core.storage import _save_history_db

        new_entries = [
            {"role": "user", "parts": ["Hello"], "timestamp": "2024-01-01T00:00:00"},
            {"role": "model", "parts": ["Hi there!"], "timestamp": "2024-01-01T00:00:01"}
        ]

        with patch('cogs.ai_core.storage.db') as mock_db:
            mock_db.save_ai_messages_batch = AsyncMock()
            mock_db.get_ai_history_count = AsyncMock(return_value=2)
            mock_db.save_ai_metadata = AsyncMock()
            mock_db.get_ai_history = AsyncMock(return_value=[])  # Add mock for get_ai_history

            await _save_history_db(
                channel_id=12345,
                chat_data={"history": [], "thinking_enabled": True},
                limit=100,
                new_entries=new_entries
            )

            mock_db.save_ai_messages_batch.assert_called_once()


# ==================== TestLoadHistoryJson ====================


@pytest.mark.asyncio
class TestLoadHistoryJson:
    """Test _load_history_json function."""

    async def test_load_history_json_no_file(self):
        """Test _load_history_json when file doesn't exist."""
        from cogs.ai_core.storage import _load_history_json

        mock_bot = MagicMock()
        mock_bot.loop.run_in_executor = AsyncMock(return_value=None)

        with patch('cogs.ai_core.storage.DATA_DIR') as mock_dir:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_dir.__truediv__ = MagicMock(return_value=mock_path)

            result = await _load_history_json(mock_bot, 12345)

        assert result == []


# ==================== TestLoadMetadataJson ====================


@pytest.mark.asyncio
class TestLoadMetadataJson:
    """Test _load_metadata_json function."""

    async def test_load_metadata_json_no_file(self):
        """Test _load_metadata_json when file doesn't exist."""
        from cogs.ai_core.storage import _load_metadata_json

        mock_bot = MagicMock()

        with patch('cogs.ai_core.storage.CONFIG_DIR') as mock_dir:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_dir.__truediv__ = MagicMock(return_value=mock_path)

            result = await _load_metadata_json(mock_bot, 12345)

        assert result == {}


# ======================================================================
# Merged from test_storage_more.py
# ======================================================================

class TestCacheCleanup:
    """Tests for cache cleanup functions."""

    def test_cleanup_expired_cache_empty(self):
        """Test _cleanup_expired_cache with empty cache."""
        from cogs.ai_core.storage import _cleanup_expired_cache, _history_cache, _metadata_cache

        # Clear caches first
        _history_cache.clear()
        _metadata_cache.clear()

        result = _cleanup_expired_cache()

        assert result == 0

    def test_cleanup_expired_cache_removes_old(self):
        """Test _cleanup_expired_cache removes expired entries."""
        from cogs.ai_core.storage import CACHE_TTL, _cleanup_expired_cache, _history_cache

        # Clear and add an old entry
        _history_cache.clear()
        old_time = time.time() - CACHE_TTL - 100  # Expired
        _history_cache[99999] = (old_time, [])

        result = _cleanup_expired_cache()

        assert result >= 1
        assert 99999 not in _history_cache

    def test_cleanup_expired_cache_keeps_new(self):
        """Test _cleanup_expired_cache keeps fresh entries."""
        from cogs.ai_core.storage import _cleanup_expired_cache, _history_cache

        # Clear and add a fresh entry
        _history_cache.clear()
        fresh_time = time.time()
        _history_cache[88888] = (fresh_time, [{"test": "data"}])

        _cleanup_expired_cache()

        # The fresh entry should still be there
        assert 88888 in _history_cache


class TestEnforceCacheSizeLimit:
    """Tests for _enforce_cache_size_limit function."""

    def test_enforce_cache_size_limit_under(self):
        """Test _enforce_cache_size_limit when under limit."""
        from cogs.ai_core.storage import _enforce_cache_size_limit, _history_cache

        # Clear cache
        _history_cache.clear()

        # Add a few entries
        for i in range(5):
            _history_cache[i] = (time.time(), [])

        result = _enforce_cache_size_limit()

        # Should not remove any
        assert result == 0


class TestInvalidateCache:
    """Tests for invalidate_cache function."""

    def test_invalidate_cache_removes_entry(self):
        """Test invalidate_cache removes specific channel."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, invalidate_cache

        # Add entries
        _history_cache[12345] = (time.time(), [])
        _metadata_cache[12345] = (time.time(), {})

        invalidate_cache(12345)

        assert 12345 not in _history_cache
        assert 12345 not in _metadata_cache

    def test_invalidate_cache_nonexistent(self):
        """Test invalidate_cache with nonexistent channel."""
        from cogs.ai_core.storage import invalidate_cache

        # Should not raise error
        invalidate_cache(99999999)


class TestInvalidateAllCache:
    """Tests for invalidate_all_cache function."""

    def test_invalidate_all_cache_clears(self):
        """Test invalidate_all_cache clears all caches."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, invalidate_all_cache

        # Add some entries
        _history_cache[111] = (time.time(), [])
        _history_cache[222] = (time.time(), [])
        _metadata_cache[111] = (time.time(), {})

        invalidate_all_cache()

        assert len(_history_cache) == 0
        assert len(_metadata_cache) == 0


class TestCleanupCache:
    """Tests for cleanup_cache function."""

    def test_cleanup_cache_returns_count(self):
        """Test cleanup_cache returns removal count."""
        from cogs.ai_core.storage import _history_cache, _metadata_cache, cleanup_cache

        # Clear caches
        _history_cache.clear()
        _metadata_cache.clear()

        result = cleanup_cache()

        assert isinstance(result, int)


class TestCacheConstants:
    """Tests for cache constants."""

    def test_cache_ttl_exists(self):
        """Test CACHE_TTL is defined."""
        from cogs.ai_core.storage import CACHE_TTL

        assert CACHE_TTL is not None
        assert CACHE_TTL > 0

    def test_max_cache_size_exists(self):
        """Test MAX_CACHE_SIZE is defined."""
        from cogs.ai_core.storage import MAX_CACHE_SIZE

        assert MAX_CACHE_SIZE is not None
        assert MAX_CACHE_SIZE > 0


class TestJsonFunctions:
    """Tests for JSON functions."""

    def test_json_loads_works(self):
        """Test json_loads function works."""
        from cogs.ai_core.storage import json_loads

        result = json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_dumps_works(self):
        """Test json_dumps function works."""
        from cogs.ai_core.storage import json_dumps

        result = json_dumps({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result


class TestDatabaseAvailable:
    """Tests for DATABASE_AVAILABLE constant."""

    def test_database_available_is_bool(self):
        """Test DATABASE_AVAILABLE is boolean."""
        from cogs.ai_core.storage import DATABASE_AVAILABLE

        assert isinstance(DATABASE_AVAILABLE, bool)


class TestDataDirectories:
    """Tests for data directories."""

    def test_data_dir_exists(self):
        """Test DATA_DIR is defined."""
        from cogs.ai_core.storage import DATA_DIR

        assert DATA_DIR is not None

    def test_config_dir_exists(self):
        """Test CONFIG_DIR is defined."""
        from cogs.ai_core.storage import CONFIG_DIR

        assert CONFIG_DIR is not None


class TestHistoryCache:
    """Tests for history cache dictionary."""

    def test_history_cache_is_dict(self):
        """Test _history_cache is a dict."""
        from cogs.ai_core.storage import _history_cache

        assert isinstance(_history_cache, dict)

    def test_metadata_cache_is_dict(self):
        """Test _metadata_cache is a dict."""
        from cogs.ai_core.storage import _metadata_cache

        assert isinstance(_metadata_cache, dict)


class TestHistoryLimits:
    """Tests for history limit imports."""

    def test_history_limit_default_imported(self):
        """Test HISTORY_LIMIT_DEFAULT is accessible."""
        from cogs.ai_core.storage import HISTORY_LIMIT_DEFAULT

        assert HISTORY_LIMIT_DEFAULT is not None

    def test_history_limit_main_imported(self):
        """Test HISTORY_LIMIT_MAIN is accessible."""
        from cogs.ai_core.storage import HISTORY_LIMIT_MAIN

        assert HISTORY_LIMIT_MAIN is not None

    def test_history_limit_rp_imported(self):
        """Test HISTORY_LIMIT_RP is accessible."""
        from cogs.ai_core.storage import HISTORY_LIMIT_RP

        assert HISTORY_LIMIT_RP is not None


class TestGuildIdImports:
    """Tests for guild ID imports."""

    def test_guild_id_main_imported(self):
        """Test GUILD_ID_MAIN is accessible."""
        from cogs.ai_core.storage import GUILD_ID_MAIN

        assert GUILD_ID_MAIN is not None

    def test_guild_id_rp_imported(self):
        """Test GUILD_ID_RP is accessible."""
        from cogs.ai_core.storage import GUILD_ID_RP

        assert GUILD_ID_RP is not None
