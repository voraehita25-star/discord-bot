"""
Memory Manager Module for Discord Bot.
Provides memory leak prevention with WeakRef caches, TTL-based cleanup, and monitoring.

Features:
- WeakRef-based caching that auto-releases when objects are garbage collected
- TTL (Time-To-Live) based automatic expiration
- Max size limits with LRU eviction
- Memory usage monitoring and alerts
- Background cleanup tasks
"""

from __future__ import annotations

import asyncio
import functools
import logging
import sys
import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")

# Sentinel object to distinguish "not in cache" from a cached None value
_CACHE_MISS = object()


@dataclass
class CacheStats:
    """Statistics for a cache instance."""

    name: str
    entries: int
    hits: int
    misses: int
    evictions: int
    expired: int
    memory_bytes: int
    hit_rate: float = field(init=False)

    def __post_init__(self):
        total = self.hits + self.misses
        self.hit_rate = self.hits / total if total > 0 else 0.0


@dataclass
class CacheEntry(Generic[V]):
    """Cache entry with TTL and metadata."""

    value: V
    created_at: float
    last_accessed: float
    hits: int = 0
    size_bytes: int = 0


class TTLCache(Generic[K, V]):
    """
    Thread-safe LRU cache with TTL expiration.

    Features:
    - Time-based expiration
    - LRU eviction when max size reached
    - Hit/miss statistics
    - Memory tracking

    Usage:
        cache = TTLCache[str, dict](ttl=300, max_size=1000, name="api_cache")
        cache.set("key", {"data": "value"})
        result = cache.get("key")
    """

    def __init__(
        self,
        ttl: float = 300.0,
        max_size: int = 1000,
        name: str = "cache",
        on_evict: Callable[[K, V], None] | None = None,
    ):
        """
        Initialize TTL cache.

        Args:
            ttl: Time-to-live in seconds
            max_size: Maximum number of entries
            name: Cache name for logging
            on_evict: Callback when entry is evicted
        """
        self.ttl = ttl
        self.max_size = max_size
        self.name = name
        self.on_evict = on_evict

        self._cache: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        # Thread-safe lock for compound operations (check-then-act patterns)
        # While Python's GIL protects individual dict operations, compound
        # operations like get-check-update need explicit synchronization
        self._lock = threading.Lock()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expired = 0

        self.logger = logging.getLogger(f"TTLCache.{name}")

    def _is_expired(self, entry: CacheEntry[V]) -> bool:
        """Check if entry has expired."""
        return time.time() - entry.created_at > self.ttl

    def _estimate_size(self, value: V) -> int:
        """Estimate memory size of value."""
        return sys.getsizeof(value)

    def get(self, key: K, default=None):
        """Get value from cache, returns default if not found or expired.

        Pass default=_CACHE_MISS to distinguish a cached None from a miss.
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return default

            if self._is_expired(entry):
                self._cache.pop(key, None)
                self._expired += 1
                self._misses += 1
                return default

            # Update access time and move to end (most recently used)
            entry.last_accessed = time.time()
            entry.hits += 1
            self._cache.move_to_end(key)
            self._hits += 1

            return entry.value

    def set(self, key: K, value: V) -> None:
        """Set value in cache, evicting LRU if necessary."""
        now = time.time()

        with self._lock:
            # Remove if exists to update position
            if key in self._cache:
                self._cache.pop(key)

            # Evict LRU if at max size
            while len(self._cache) >= self.max_size:
                evicted_key, evicted_entry = self._cache.popitem(last=False)
                self._evictions += 1
                if self.on_evict:
                    try:
                        self.on_evict(evicted_key, evicted_entry.value)
                    except Exception as e:
                        self.logger.warning("on_evict callback failed: %s", e)

            self._cache[key] = CacheEntry(
                value=value,
                created_at=now,
                last_accessed=now,
                size_bytes=self._estimate_size(value),
            )

    def delete(self, key: K) -> bool:
        """Delete entry from cache. Returns True if deleted."""
        with self._lock:
            entry = self._cache.pop(key, None)
            return entry is not None

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        with self._lock:
            now = time.time()
            expired_keys = [
                key for key, entry in self._cache.items() if now - entry.created_at > self.ttl
            ]

            for key in expired_keys:
                self._cache.pop(key, None)
                self._expired += 1

            if expired_keys:
                self.logger.debug("Cleaned up %d expired entries", len(expired_keys))

            return len(expired_keys)

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            memory_bytes = sum(e.size_bytes for e in self._cache.values())

            return CacheStats(
                name=self.name,
                entries=len(self._cache),
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                expired=self._expired,
                memory_bytes=memory_bytes,
            )

    def reset_stats(self) -> None:
        """Reset hit/miss statistics."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expired = 0

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: K) -> bool:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            return not self._is_expired(entry)


class WeakRefCache(Generic[K, V]):
    """
    Cache using weak references for automatic memory management.

    Objects are automatically removed when they are no longer
    referenced elsewhere, preventing memory leaks.

    Usage:
        cache = WeakRefCache[int, MyClass]("user_cache")
        cache.set(user_id, user_obj)
        # When user_obj is no longer referenced elsewhere,
        # it will be automatically removed from cache
    """

    def __init__(self, name: str = "weak_cache"):
        self.name = name
        self._cache: dict[K, weakref.ref[V]] = {}
        # Use RLock (reentrant) because GC callbacks may fire while we hold the lock
        # (e.g., allocating a new weakref in set() triggers GC, which runs on_collected)
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._collected = 0
        self.logger = logging.getLogger(f"WeakRefCache.{name}")

    def _make_callback(self, key: K) -> Callable[[weakref.ref[V]], None]:
        """Create callback for when weak ref is collected."""

        def on_collected(ref: weakref.ref[V]) -> None:
            with self._lock:
                # Only remove if the stored ref is the same one being collected,
                # to prevent stale callbacks from deleting newer entries
                if self._cache.get(key) is ref:
                    del self._cache[key]
                    self._collected += 1
            self.logger.debug("Object collected for key: %s", key)

        return on_collected

    def get(self, key: K) -> V | None:
        """Get value from cache."""
        with self._lock:
            ref = self._cache.get(key)

            if ref is None:
                self._misses += 1
                return None

            value = ref()
            if value is None:
                # Object was garbage collected
                self._cache.pop(key, None)
                self._misses += 1
                return None

            self._hits += 1
            return value

    def set(self, key: K, value: V) -> bool:
        """
        Set value in cache.

        Returns False if value cannot be weakly referenced.
        """
        try:
            ref = weakref.ref(value, self._make_callback(key))
            with self._lock:
                self._cache[key] = ref
            return True
        except TypeError:
            # Object cannot be weakly referenced
            self.logger.warning("Cannot weakly reference object for key: %s", key)
            return False

    def delete(self, key: K) -> bool:
        """Delete entry from cache."""
        with self._lock:
            ref = self._cache.pop(key, None)
            return ref is not None

    def clear(self) -> int:
        """Clear all entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def cleanup(self) -> int:
        """Remove dead references. Returns count removed."""
        with self._lock:
            dead_keys = [key for key, ref in self._cache.items() if ref() is None]

            for key in dead_keys:
                self._cache.pop(key, None)

            return len(dead_keys)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            alive = sum(1 for ref in self._cache.values() if ref() is not None)

            return {
                "name": self.name,
                "total_refs": len(self._cache),
                "alive_refs": alive,
                "hits": self._hits,
                "misses": self._misses,
                "collected": self._collected,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


class MemoryMonitor:
    """
    Monitors memory usage and triggers cleanup when thresholds are exceeded.

    Usage:
        monitor = MemoryMonitor(warning_mb=500, critical_mb=800)
        monitor.register_cleanup("cache1", cache1.cleanup_expired)
        monitor.start()
    """

    def __init__(
        self,
        warning_mb: float = 500.0,
        critical_mb: float = 800.0,
        check_interval: float = 60.0,
    ):
        """
        Initialize memory monitor.

        Args:
            warning_mb: Warning threshold in MB
            critical_mb: Critical threshold in MB (triggers aggressive cleanup)
            check_interval: How often to check memory in seconds
        """
        self.warning_mb = warning_mb
        self.critical_mb = critical_mb
        self.check_interval = check_interval

        self._cleanup_callbacks: dict[str, Callable[[], int]] = {}
        self._monitor_task: asyncio.Task | None = None
        self._running = False

        self.logger = logging.getLogger("MemoryMonitor")

    def register_cleanup(self, name: str, callback: Callable[[], int]) -> None:
        """
        Register a cleanup callback.

        Args:
            name: Identifier for logging
            callback: Function that returns number of items cleaned
        """
        self._cleanup_callbacks[name] = callback
        self.logger.debug("Registered cleanup callback: %s", name)

    def unregister_cleanup(self, name: str) -> None:
        """Unregister a cleanup callback."""
        self._cleanup_callbacks.pop(name, None)

    def get_memory_mb(self) -> float:
        """Get current process memory usage in MB."""
        try:
            import psutil

            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0

    def _run_cleanups(self, aggressive: bool = False) -> dict[str, int]:
        """Run all registered cleanup callbacks."""
        results = {}

        for name, callback in self._cleanup_callbacks.items():
            try:
                cleaned = callback()
                results[name] = cleaned
            except Exception as e:
                self.logger.error("Cleanup callback %s failed: %s", name, e)
                results[name] = -1

        if aggressive:
            # Force garbage collection in a non-blocking way
            # gc.collect() can take 100-500ms, so we don't run it inline
            # Instead, we schedule it as a background task
            import gc

            gc.collect(generation=0)  # Fast collection of youngest generation only

        return results

    async def _run_cleanups_async(self, aggressive: bool = False) -> dict[str, int]:
        """Async version of cleanup that handles gc.collect properly."""
        results = self._run_cleanups(aggressive=False)  # Run sync cleanups

        if aggressive:
            # Run full gc.collect in executor to avoid blocking event loop
            import gc

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, gc.collect)

        return results

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)

                memory_mb = self.get_memory_mb()

                if memory_mb >= self.critical_mb:
                    self.logger.warning(
                        "🚨 CRITICAL memory usage: %.1f MB (threshold: %.1f MB)",
                        memory_mb,
                        self.critical_mb,
                    )
                    # Use async cleanup for aggressive mode to avoid blocking
                    results = await self._run_cleanups_async(aggressive=True)
                    total_cleaned = sum(v for v in results.values() if v > 0)
                    new_memory = self.get_memory_mb()
                    self.logger.info(
                        "🧹 Aggressive cleanup: removed %d items, memory: %.1f → %.1f MB",
                        total_cleaned,
                        memory_mb,
                        new_memory,
                    )

                elif memory_mb >= self.warning_mb:
                    self.logger.info(
                        "⚠️ High memory usage: %.1f MB (threshold: %.1f MB)",
                        memory_mb,
                        self.warning_mb,
                    )
                    results = self._run_cleanups(aggressive=False)
                    total_cleaned = sum(v for v in results.values() if v > 0)
                    if total_cleaned > 0:
                        self.logger.info("🧹 Cleanup: removed %d items", total_cleaned)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Memory monitor error: %s", e)

    def start(self) -> None:
        """Start background monitoring."""
        if self._running:
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info(
            "🧠 Memory monitor started (warning: %.0f MB, critical: %.0f MB)",
            self.warning_mb,
            self.critical_mb,
        )

    def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None

        self.logger.info("🧠 Memory monitor stopped")

    def get_status(self) -> dict[str, Any]:
        """Get current memory status."""
        memory_mb = self.get_memory_mb()

        if memory_mb >= self.critical_mb:
            status = "critical"
        elif memory_mb >= self.warning_mb:
            status = "warning"
        else:
            status = "healthy"

        return {
            "memory_mb": round(memory_mb, 2),
            "status": status,
            "warning_threshold_mb": self.warning_mb,
            "critical_threshold_mb": self.critical_mb,
            "registered_cleanups": list(self._cleanup_callbacks.keys()),
            "monitoring": self._running,
        }


def cached_with_ttl(
    ttl: float = 300.0,
    max_size: int = 100,
    key_fn: Callable[..., str] | None = None,
):
    """
    Decorator for caching function results with TTL.

    Usage:
        @cached_with_ttl(ttl=60, max_size=50)
        async def fetch_user_data(user_id: int) -> dict:
            return await api.get_user(user_id)
    """
    cache: TTLCache[str, Any] = TTLCache(ttl=ttl, max_size=max_size, name="decorator")

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate cache key
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"

            # Check cache (use sentinel to distinguish cached None from miss)
            cached = cache.get(key, _CACHE_MISS)
            if cached is not _CACHE_MISS:
                return cached

            # Call function
            result = await func(*args, **kwargs)

            # Cache result (including None to prevent stampede)
            cache.set(key, result)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"

            cached = cache.get(key, _CACHE_MISS)
            if cached is not _CACHE_MISS:
                return cached

            result = func(*args, **kwargs)
            cache.set(key, result)
            return result

        # Choose wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            async_wrapper.cache = cache  # type: ignore
            async_wrapper.cache_clear = cache.clear  # type: ignore
            async_wrapper.cache_stats = cache.get_stats  # type: ignore
            return async_wrapper
        else:
            sync_wrapper.cache = cache  # type: ignore
            sync_wrapper.cache_clear = cache.clear  # type: ignore
            sync_wrapper.cache_stats = cache.get_stats  # type: ignore
            return sync_wrapper

    return decorator


# Global memory monitor instance
memory_monitor = MemoryMonitor()


# Convenience function to get all cache stats
def get_all_cache_stats() -> dict[str, Any]:
    """Get statistics from all registered caches."""
    return {
        "memory_monitor": memory_monitor.get_status(),
    }
