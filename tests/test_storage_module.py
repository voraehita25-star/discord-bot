"""
Tests for cogs/ai_core/storage.py module.
Tests chat history storage, caching, and persistence.
"""

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ==================== TestOrjsonAvailability ====================


class TestOrjsonAvailability:
    """Test orjson availability flag."""

    def test_orjson_enabled_flag_exists(self):
        """Test _ORJSON_ENABLED flag exists."""
        from cogs.ai_core.storage import _ORJSON_ENABLED
        
        assert isinstance(_ORJSON_ENABLED, bool)
    
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
        
        assert CACHE_TTL == 300  # 5 minutes
    
    def test_max_cache_size_exists(self):
        """Test MAX_CACHE_SIZE constant exists."""
        from cogs.ai_core.storage import MAX_CACHE_SIZE
        
        assert MAX_CACHE_SIZE == 1000
    
    def test_data_dir_exists(self):
        """Test DATA_DIR path exists."""
        from cogs.ai_core.storage import DATA_DIR
        from pathlib import Path
        
        assert isinstance(DATA_DIR, Path)
    
    def test_config_dir_exists(self):
        """Test CONFIG_DIR path exists."""
        from cogs.ai_core.storage import CONFIG_DIR
        from pathlib import Path
        
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
            _cleanup_expired_cache,
            _history_cache,
            _metadata_cache,
            CACHE_TTL
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
        from cogs.ai_core.storage import (
            _enforce_cache_size_limit,
            _history_cache,
            MAX_CACHE_SIZE
        )
        
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
        from cogs.ai_core.storage import (
            invalidate_cache,
            _history_cache,
            _metadata_cache
        )
        
        # Set up test data
        now = time.time()
        _history_cache[99999] = (now, [{"test": "data"}])
        _metadata_cache[99999] = (now, {"thinking_enabled": True})
        
        invalidate_cache(99999)
        
        assert 99999 not in _history_cache
        assert 99999 not in _metadata_cache
    
    def test_invalidate_all_cache(self):
        """Test invalidating all caches."""
        from cogs.ai_core.storage import (
            invalidate_all_cache,
            _history_cache,
            _metadata_cache
        )
        
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
        from cogs.ai_core.storage import save_history, DATABASE_AVAILABLE
        
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
        from cogs.ai_core.storage import load_history, _history_cache
        
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
        from cogs.ai_core.storage import (
            load_history,
            _history_cache,
            CACHE_TTL,
            DATABASE_AVAILABLE
        )
        
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
        from cogs.ai_core.storage import load_metadata, _metadata_cache
        
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
        from cogs.ai_core.storage import HISTORY_LIMIT_DEFAULT
        from cogs.ai_core.data.constants import HISTORY_LIMIT_DEFAULT as const_limit
        
        assert HISTORY_LIMIT_DEFAULT == const_limit
    
    def test_history_limit_constants_imported(self):
        """Test history limit constants are imported."""
        from cogs.ai_core.storage import (
            HISTORY_LIMIT_DEFAULT,
            HISTORY_LIMIT_MAIN,
            HISTORY_LIMIT_RP
        )
        
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
        from cogs.ai_core.storage import invalidate_cache, invalidate_all_cache, cleanup_cache
        
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
