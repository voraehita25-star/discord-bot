"""
Additional tests for Storage module.
Tests cache functions and storage operations.
"""

import time


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


class TestOrjsonStatus:
    """Tests for orjson availability."""

    def test_orjson_enabled_is_bool(self):
        """Test _ORJSON_ENABLED is boolean."""
        from cogs.ai_core.storage import _ORJSON_ENABLED

        assert isinstance(_ORJSON_ENABLED, bool)


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
