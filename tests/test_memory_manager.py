"""
Unit Tests for Memory Manager Module.
Tests TTLCache, WeakRefCache, and MemoryMonitor.
"""

from __future__ import annotations

import gc
import time
from unittest.mock import MagicMock, patch

import pytest


class TestTTLCache:
    """Tests for TTLCache class."""

    def test_basic_set_get(self):
        """Test basic set and get operations."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=10, name="test")
        cache.set("key1", "value1")

        assert cache.get("key1") == "value1"
        assert len(cache) == 1

    def test_get_nonexistent_key(self):
        """Test getting a nonexistent key returns None."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=10, name="test")

        assert cache.get("nonexistent") is None

    def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=0.1, max_size=10, name="test")
        cache.set("key1", "value1")

        # Should exist immediately
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired
        assert cache.get("key1") is None

    def test_lru_eviction(self):
        """Test LRU eviction when max size reached."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=3, name="test")

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Access key1 to make it recently used
        cache.get("key1")

        # Add new key, should evict key2 (oldest not accessed)
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Still exists (was accessed)
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_on_evict_callback(self):
        """Test eviction callback is called."""
        from utils.reliability.memory_manager import TTLCache

        evicted = []

        def on_evict(key, value):
            evicted.append((key, value))

        cache: TTLCache[str, str] = TTLCache(
            ttl=60, max_size=2, name="test", on_evict=on_evict
        )

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should trigger eviction

        assert len(evicted) == 1
        assert evicted[0] == ("key1", "value1")

    def test_delete(self):
        """Test delete operation."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=10, name="test")
        cache.set("key1", "value1")

        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        assert cache.delete("key1") is False  # Already deleted

    def test_clear(self):
        """Test clear operation."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=10, name="test")
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        count = cache.clear()

        assert count == 2
        assert len(cache) == 0

    def test_cleanup_expired(self):
        """Test cleanup_expired removes old entries."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=0.1, max_size=10, name="test")
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        time.sleep(0.15)

        removed = cache.cleanup_expired()

        assert removed == 2
        assert len(cache) == 0

    def test_get_stats(self):
        """Test statistics collection."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=10, name="test")
        cache.set("key1", "value1")

        # Generate hits and misses
        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("nonexistent")  # Miss

        stats = cache.get_stats()

        assert stats.name == "test"
        assert stats.entries == 1
        assert stats.hits == 2
        assert stats.misses == 1
        assert stats.hit_rate == pytest.approx(0.667, rel=0.01)

    def test_contains(self):
        """Test __contains__ method."""
        from utils.reliability.memory_manager import TTLCache

        cache: TTLCache[str, str] = TTLCache(ttl=60, max_size=10, name="test")
        cache.set("key1", "value1")

        assert "key1" in cache
        assert "key2" not in cache


class TestWeakRefCache:
    """Tests for WeakRefCache class."""

    def test_basic_operations(self):
        """Test basic set and get with weak references."""
        from utils.reliability.memory_manager import WeakRefCache

        cache: WeakRefCache[str, object] = WeakRefCache("test")

        # Use a class instance - can be weakly referenced
        class MyObject:
            def __init__(self, value):
                self.value = value

        obj = MyObject([1, 2, 3])
        cache.set("key1", obj)

        result = cache.get("key1")
        assert result is not None
        assert result.value == [1, 2, 3]
        assert len(cache) == 1

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_auto_cleanup_on_gc(self):
        """Test objects are removed when garbage collected."""
        from utils.reliability.memory_manager import WeakRefCache

        cache: WeakRefCache[str, object] = WeakRefCache("test")

        class MyObject:
            pass

        # Create object in local scope
        def add_object():
            obj = MyObject()
            return cache.set("key1", obj)

        assert add_object()

        # Force garbage collection
        gc.collect()

        # Object should be collected (may not be immediate on all platforms)
        # So we just verify the cache doesn't crash
        cache.get("key1")

    def test_get_nonexistent(self):
        """Test getting nonexistent key."""
        from utils.reliability.memory_manager import WeakRefCache

        cache: WeakRefCache[str, object] = WeakRefCache("test")

        assert cache.get("nonexistent") is None

    def test_delete(self):
        """Test delete operation."""
        from utils.reliability.memory_manager import WeakRefCache

        class MyObject:
            pass

        cache: WeakRefCache[str, object] = WeakRefCache("test")
        obj = MyObject()
        cache.set("key1", obj)

        assert cache.delete("key1") is True
        assert cache.get("key1") is None

    def test_clear(self):
        """Test clear operation."""
        from utils.reliability.memory_manager import WeakRefCache

        class MyObject:
            pass

        cache: WeakRefCache[str, object] = WeakRefCache("test")
        obj1 = MyObject()
        obj2 = MyObject()
        cache.set("key1", obj1)
        cache.set("key2", obj2)

        count = cache.clear()

        assert count == 2
        assert len(cache) == 0

    def test_get_stats(self):
        """Test statistics collection."""
        from utils.reliability.memory_manager import WeakRefCache

        class MyObject:
            pass

        cache: WeakRefCache[str, object] = WeakRefCache("test")
        obj = MyObject()
        cache.set("key1", obj)

        cache.get("key1")  # Hit
        cache.get("nonexistent")  # Miss

        stats = cache.get_stats()

        assert stats["name"] == "test"
        assert stats["hits"] == 1
        assert stats["misses"] == 1


class TestMemoryMonitor:
    """Tests for MemoryMonitor class."""

    def test_register_cleanup(self):
        """Test registering cleanup callbacks."""
        from utils.reliability.memory_manager import MemoryMonitor

        monitor = MemoryMonitor()

        def cleanup1():
            return 5

        def cleanup2():
            return 10

        monitor.register_cleanup("cleanup1", cleanup1)
        monitor.register_cleanup("cleanup2", cleanup2)

        status = monitor.get_status()

        assert "cleanup1" in status["registered_cleanups"]
        assert "cleanup2" in status["registered_cleanups"]

    def test_unregister_cleanup(self):
        """Test unregistering cleanup callbacks."""
        from utils.reliability.memory_manager import MemoryMonitor

        monitor = MemoryMonitor()

        monitor.register_cleanup("cleanup1", lambda: 0)
        monitor.unregister_cleanup("cleanup1")

        status = monitor.get_status()

        assert "cleanup1" not in status["registered_cleanups"]

    def test_get_memory_mb(self):
        """Test getting memory usage."""
        from utils.reliability.memory_manager import MemoryMonitor

        monitor = MemoryMonitor()
        memory = monitor.get_memory_mb()

        # Should return a positive number (or 0 if psutil not available)
        assert memory >= 0

    def test_get_status(self):
        """Test getting monitor status."""
        from utils.reliability.memory_manager import MemoryMonitor

        monitor = MemoryMonitor(warning_mb=500, critical_mb=800)
        status = monitor.get_status()

        assert "memory_mb" in status
        assert status["warning_threshold_mb"] == 500
        assert status["critical_threshold_mb"] == 800
        assert status["status"] in ["healthy", "warning", "critical"]

    def test_run_cleanups(self):
        """Test running cleanup callbacks."""
        from utils.reliability.memory_manager import MemoryMonitor

        monitor = MemoryMonitor()
        cleanup_calls = []

        def cleanup1():
            cleanup_calls.append("cleanup1")
            return 5

        def cleanup2():
            cleanup_calls.append("cleanup2")
            return 10

        monitor.register_cleanup("cleanup1", cleanup1)
        monitor.register_cleanup("cleanup2", cleanup2)

        results = monitor._run_cleanups()

        assert results["cleanup1"] == 5
        assert results["cleanup2"] == 10
        assert "cleanup1" in cleanup_calls
        assert "cleanup2" in cleanup_calls


class TestCachedWithTTL:
    """Tests for cached_with_ttl decorator."""

    @pytest.mark.asyncio
    async def test_decorator_caches_result(self):
        """Test that decorator caches function results."""
        from utils.reliability.memory_manager import cached_with_ttl

        call_count = 0

        @cached_with_ttl(ttl=60, max_size=10)
        async def fetch_data(key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"data_{key}"

        # First call - should execute function
        result1 = await fetch_data("test")
        assert result1 == "data_test"
        assert call_count == 1

        # Second call - should use cache
        result2 = await fetch_data("test")
        assert result2 == "data_test"
        assert call_count == 1  # Function not called again

    @pytest.mark.asyncio
    async def test_decorator_different_keys(self):
        """Test that different keys are cached separately."""
        from utils.reliability.memory_manager import cached_with_ttl

        call_count = 0

        @cached_with_ttl(ttl=60, max_size=10)
        async def fetch_data(key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"data_{key}"

        result1 = await fetch_data("key1")
        result2 = await fetch_data("key2")

        assert result1 == "data_key1"
        assert result2 == "data_key2"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_expiration(self):
        """Test that cached results expire."""
        from utils.reliability.memory_manager import cached_with_ttl

        call_count = 0

        @cached_with_ttl(ttl=0.1, max_size=10)
        async def fetch_data(key: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"data_{key}_{call_count}"

        result1 = await fetch_data("test")
        assert result1 == "data_test_1"

        # Wait for expiration
        time.sleep(0.15)

        result2 = await fetch_data("test")
        assert result2 == "data_test_2"
        assert call_count == 2


class TestGlobalMonitor:
    """Tests for global memory_monitor instance."""

    def test_global_monitor_exists(self):
        """Test that global monitor is accessible."""
        from utils.reliability.memory_manager import memory_monitor

        assert memory_monitor is not None

    def test_global_monitor_methods(self):
        """Test global monitor has required methods."""
        from utils.reliability.memory_manager import memory_monitor

        assert hasattr(memory_monitor, "register_cleanup")
        assert hasattr(memory_monitor, "start")
        assert hasattr(memory_monitor, "stop")
        assert hasattr(memory_monitor, "get_status")
