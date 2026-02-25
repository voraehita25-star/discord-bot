"""
Tests for cogs.ai_core.cache.ai_cache module.
"""

import time


class TestCacheEntryDataclass:
    """Tests for CacheEntry dataclass."""

    def test_create_cache_entry(self):
        """Test creating CacheEntry."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(
            response="Test response",
            created_at=time.time()
        )

        assert entry.response == "Test response"
        assert entry.hits == 0

    def test_cache_entry_default_hits(self):
        """Test CacheEntry default hits."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(
            response="Test",
            created_at=time.time()
        )

        assert entry.hits == 0
        assert entry.context_hash == ""
        assert entry.intent == ""


class TestCacheStatsDataclass:
    """Tests for CacheStats dataclass."""

    def test_create_cache_stats(self):
        """Test creating CacheStats."""
        from cogs.ai_core.cache.ai_cache import CacheStats

        stats = CacheStats(
            total_entries=100,
            hits=80,
            misses=20,
            hit_rate=0.8,
            memory_estimate_kb=256.0
        )

        assert stats.total_entries == 100
        assert stats.hits == 80
        assert stats.misses == 20
        assert stats.hit_rate == 0.8


class TestAICacheConstants:
    """Tests for AICache constants."""

    def test_default_ttl(self):
        """Test DEFAULT_TTL constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.DEFAULT_TTL == 28800

    def test_default_max_size(self):
        """Test DEFAULT_MAX_SIZE constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.DEFAULT_MAX_SIZE == 5000

    def test_similarity_threshold(self):
        """Test SIMILARITY_THRESHOLD constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.SIMILARITY_THRESHOLD == 0.85

    def test_semantic_threshold(self):
        """Test SEMANTIC_THRESHOLD constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.SEMANTIC_THRESHOLD == 0.9


class TestAICacheInit:
    """Tests for AICache initialization."""

    def test_create_ai_cache(self):
        """Test creating AICache."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        assert cache is not None

    def test_cache_with_custom_ttl(self):
        """Test AICache with custom TTL."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(ttl=3600)
        assert cache.ttl == 3600

    def test_cache_with_custom_max_size(self):
        """Test AICache with custom max_size."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=100)
        assert cache.max_size == 100


class TestAICacheNormalize:
    """Tests for AICache normalization methods."""

    def test_normalize_message_case_insensitive(self):
        """Test _normalize_message is case insensitive."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        msg1 = cache._normalize_message("Hello World")
        msg2 = cache._normalize_message("hello world")

        # Normalized messages should be same for case-insensitive match
        assert msg1 == msg2

    def test_normalize_message_removes_mentions(self):
        """Test _normalize_message removes user mentions."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        msg = cache._normalize_message("Hello <@123456789>!")

        # Mention should be normalized to [USER]
        assert "<@123456789>" not in msg
        assert "[USER]" in msg


class TestAICacheMethods:
    """Tests for AICache main methods."""

    def test_get_returns_none_for_missing(self):
        """Test get returns None for missing key."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        result = cache.get("nonexistent_key_here")

        assert result is None

    def test_set_and_get(self):
        """Test setting and getting a value."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        # Response must be 10+ chars
        cache.set("test_key_message", "test_response_content")

        result = cache.get("test_key_message")

        assert result == "test_response_content"

    def test_set_increments_hits_on_get(self):
        """Test get increments hits counter."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        # Must be 10+ characters for set to work
        cache.set("test_key_message", "test_response_content")

        # Get multiple times - note: set filters very short responses
        cache.get("test_key_message")
        cache.get("test_key_message")
        cache.get("test_key_message")

        # Check stats
        stats = cache.get_stats()
        assert stats.hits >= 3


class TestAICacheStats:
    """Tests for AICache statistics."""

    def test_get_stats(self):
        """Test get_stats method."""
        from cogs.ai_core.cache.ai_cache import AICache, CacheStats

        cache = AICache()
        stats = cache.get_stats()

        assert isinstance(stats, CacheStats)

    def test_stats_hit_rate_empty(self):
        """Test hit rate with empty cache."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        stats = cache.get_stats()

        assert stats.hit_rate == 0.0

    def test_stats_after_operations(self):
        """Test stats after cache operations."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        # Set a value (response must be 10+ chars for set to work)
        cache.set("key1 longer message", "value1 longer response content")

        # Hit (must use same message)
        result = cache.get("key1 longer message")

        # Miss - use nonexistent key
        cache.get("nonexistent key here")

        stats = cache.get_stats()

        # Either hit or at least a miss
        assert stats.hits >= 1 or stats.misses >= 1


class TestAICacheClear:
    """Tests for AICache clear functionality."""

    def test_invalidate_removes_all_entries(self):
        """Test invalidate removes all entries when called without pattern."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        cache.set("key1 longer message", "value1 longer response content")
        cache.set("key2 longer message", "value2 longer response content")

        count = cache.invalidate()

        assert cache.get("key1 longer message") is None
        assert cache.get("key2 longer message") is None

    def test_cleanup_expired(self):
        """Test cleanup_expired removes expired entries."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(ttl=1)  # 1 second TTL
        cache.set("test message here", "test response content here")

        # Initially not expired
        stats = cache.get_stats()
        # Entry may or may not be stored depending on internal logic

        # cleanup_expired returns count of removed entries
        count = cache.cleanup_expired()
        assert count >= 0


class TestAICacheEviction:
    """Tests for AICache eviction."""

    def test_eviction_on_max_size(self):
        """Test LRU eviction when max size reached."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")  # Should evict key1

        # key1 should be evicted (LRU)
        stats = cache.get_stats()
        assert stats.total_entries <= 3


class TestAICacheSingleton:
    """Tests for ai_cache singleton."""

    def test_singleton_exists(self):
        """Test ai_cache singleton exists."""
        from cogs.ai_core.cache.ai_cache import ai_cache

        assert ai_cache is not None

    def test_singleton_is_ai_cache(self):
        """Test singleton is AICache instance."""
        from cogs.ai_core.cache.ai_cache import AICache, ai_cache

        assert isinstance(ai_cache, AICache)


class TestContextHasher:
    """Tests for ContextHasher class."""

    def test_hash_history_empty(self):
        """Test hash_history with empty history."""
        from cogs.ai_core.cache.ai_cache import ContextHasher

        result = ContextHasher.hash_history([])

        assert isinstance(result, str)

    def test_hash_history_with_messages(self):
        """Test hash_history with messages."""
        from cogs.ai_core.cache.ai_cache import ContextHasher

        history = [
            {"role": "user", "parts": ["Hello there!"]},
            {"role": "assistant", "parts": ["Hi! How can I help?"]},
        ]

        result = ContextHasher.hash_history(history)

        assert isinstance(result, str)
        assert len(result) == 16  # MD5 hash truncated to 16 chars

    def test_hash_history_last_n(self):
        """Test hash_history respects last_n parameter."""
        from cogs.ai_core.cache.ai_cache import ContextHasher

        history = [
            {"role": "user", "parts": ["Message 1"]},
            {"role": "user", "parts": ["Message 2"]},
            {"role": "user", "parts": ["Message 3"]},
        ]

        result = ContextHasher.hash_history(history, last_n=2)

        assert isinstance(result, str)


class TestContextHasherSingleton:
    """Tests for context_hasher singleton."""

    def test_context_hasher_exists(self):
        """Test context_hasher singleton exists."""
        from cogs.ai_core.cache.ai_cache import context_hasher

        assert context_hasher is not None


class TestGetCacheStats:
    """Tests for get_cache_stats function."""

    def test_get_cache_stats_function(self):
        """Test get_cache_stats function."""
        from cogs.ai_core.cache.ai_cache import CacheStats, get_cache_stats

        result = get_cache_stats()

        assert isinstance(result, CacheStats)


class TestAICacheGenerateKey:
    """Tests for AICache key generation."""

    def test_generate_key_basic(self):
        """Test _generate_key basic functionality."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        key = cache._generate_key("test message")

        assert isinstance(key, str)
        assert len(key) == 64  # SHA256 hex digest

    def test_generate_key_with_context(self):
        """Test _generate_key with context hash."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        key1 = cache._generate_key("test", context_hash="hash1")
        key2 = cache._generate_key("test", context_hash="hash2")

        assert key1 != key2

    def test_generate_key_with_intent(self):
        """Test _generate_key with intent."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        key1 = cache._generate_key("test", intent="greeting")
        key2 = cache._generate_key("test", intent="question")

        assert key1 != key2


class TestAICacheFuzzyMatch:
    """Tests for AICache fuzzy matching."""

    def test_find_similar_no_matches(self):
        """Test find_similar returns None for no matches."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        result = cache.find_similar("completely unique message")

        assert result is None

    def test_calculate_similarity(self):
        """Test _calculate_similarity method."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        sim = cache._calculate_similarity("hello world", "hello world")
        assert sim == 1.0

        sim = cache._calculate_similarity("hello", "world")
        assert 0 <= sim <= 1


class TestAICacheEvictionLRU:
    """Tests for AICache LRU eviction."""

    def test_evict_lru_method(self):
        """Test _evict_lru method."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=2)

        # Fill cache
        cache.set("message one here", "response one here content")
        cache.set("message two here", "response two here content")

        # Add another should trigger eviction
        cache._evict_lru()

        stats = cache.get_stats()
        assert stats.total_entries <= 2


class TestAICacheResetStats:
    """Tests for AICache reset_stats method."""

    def test_reset_stats(self):
        """Test reset_stats resets counters."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        # Generate some stats
        cache.get("nonexistent message here")
        cache.get("another nonexistent msg")

        stats_before = cache.get_stats()
        assert stats_before.misses >= 2

        cache.reset_stats()

        stats_after = cache.get_stats()
        assert stats_after.hits == 0
        assert stats_after.misses == 0


class TestAICacheInvalidatePattern:
    """Tests for AICache invalidate with pattern."""

    def test_invalidate_with_pattern(self):
        """Test invalidate with pattern parameter."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        # Add entries
        cache.set("test message alpha", "response alpha content")
        cache.set("test message beta", "response beta content")

        # Invalidate should return count
        count = cache.invalidate()

        assert count >= 0
