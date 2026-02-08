"""
Extended tests for AI Storage module.
Tests caching, history loading/saving, and utility functions.
"""

import time

import pytest


class TestJsonImplementation:
    """Tests for JSON implementation selection."""

    def test_orjson_enabled_defined(self):
        """Test _ORJSON_ENABLED is defined."""
        try:
            from cogs.ai_core.storage import _ORJSON_ENABLED
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert isinstance(_ORJSON_ENABLED, bool)

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

        result = _enforce_cache_size_limit()

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

    def test_module_has_docstring(self):
        """Test storage module has docstring."""
        try:
            from cogs.ai_core import storage
        except ImportError:
            pytest.skip("storage module not available")
            return

        assert storage.__doc__ is not None
        assert "Storage" in storage.__doc__ or "storage" in storage.__doc__.lower()


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
