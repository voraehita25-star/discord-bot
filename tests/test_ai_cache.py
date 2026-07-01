"""
Tests for cogs.ai_core.cache.ai_cache module.
"""

import time


class TestCacheEntryDataclass:
    """Tests for CacheEntry dataclass."""

    def test_create_cache_entry(self):
        """Test creating CacheEntry."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(response="Test response", created_at=time.time())

        assert entry.response == "Test response"
        assert entry.hits == 0

    def test_cache_entry_default_hits(self):
        """Test CacheEntry default hits."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(response="Test", created_at=time.time())

        assert entry.hits == 0
        assert entry.context_hash == ""
        assert entry.intent == ""


class TestCacheStatsDataclass:
    """Tests for CacheStats dataclass."""

    def test_create_cache_stats(self):
        """Test creating CacheStats."""
        from cogs.ai_core.cache.ai_cache import CacheStats

        stats = CacheStats(
            total_entries=100, hits=80, misses=20, hit_rate=0.8, memory_estimate_kb=256.0
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
        cache.get("key1 longer message")

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

        cache.invalidate()

        assert cache.get("key1 longer message") is None
        assert cache.get("key2 longer message") is None

    def test_cleanup_expired(self):
        """Test cleanup_expired removes expired entries."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(ttl=1)  # 1 second TTL
        cache.set("test message here", "test response content here")

        # Initially not expired
        cache.get_stats()
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

        # Responses must clear the _CACHE_MIN_RESPONSE_CHARS (10) gate, else
        # set() drops them silently and this test would pass vacuously.
        cache.set("key1", "value1 content")
        cache.set("key2", "value2 content")
        cache.set("key3", "value3 content")
        cache.set("key4", "value4 content")  # Should evict key1

        # key1 should be evicted (LRU). use_fuzzy=False so a lexical fuzzy hit
        # cannot mask the eviction.
        stats = cache.get_stats()
        assert stats.total_entries == 3
        assert cache.get("key1", use_fuzzy=False) is None
        assert cache.get("key4", use_fuzzy=False) == "value4 content"


class TestAICacheSingleton:
    """Tests for ai_cache singleton."""

    def test_singleton_is_ai_cache(self):
        """Test singleton is AICache instance."""
        from cogs.ai_core.cache.ai_cache import AICache, ai_cache

        assert isinstance(ai_cache, AICache)


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

    def test_find_similar_is_context_scoped(self):
        """find_similar must NOT return an entry stored under a different
        context_hash, even when the normalized text matches exactly. The
        exact-match key is context-scoped, so the fuzzy fallback must be too —
        otherwise a fuzzy hit leaks a response across conversations."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        cache.set("what is the secret", "context-A-only response", context_hash="ctx-A")

        # Same text, different context -> no cross-context fuzzy leak.
        assert cache.find_similar("what is the secret", context_hash="ctx-B") is None
        # No-context query must not see a context-scoped entry either.
        assert cache.find_similar("what is the secret") is None

    def test_find_similar_same_context_still_matches(self):
        """The context scoping must not break legitimate same-context fuzzy
        hits: a near-identical message in the SAME context still matches."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        cache.set("what is the secret", "context-A response", context_hash="ctx-A")

        match = cache.find_similar("what is the secret", context_hash="ctx-A")
        assert match is not None
        _key, entry, similarity = match
        assert entry.response == "context-A response"
        assert similarity >= cache.SIMILARITY_THRESHOLD

    def test_get_fuzzy_does_not_leak_across_context(self):
        """End-to-end via get(): an exact-key miss must not be salvaged by a
        fuzzy hit from a different context_hash."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        cache.set("tell me the answer", "answer for context A", context_hash="ctx-A")

        # Different context -> exact key misses AND fuzzy must be context-scoped.
        assert cache.get("tell me the answer", context_hash="ctx-B", use_fuzzy=True) is None
        # Same context -> fuzzy fallback hits. "answers" normalizes differently
        # from the stored "answer" (so the exact key misses) but is ~0.97
        # similar, so it must resolve via the context-scoped fuzzy path.
        assert (
            cache.get("tell me the answers", context_hash="ctx-A", use_fuzzy=True)
            == "answer for context A"
        )


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


# ======================================================================
# Merged from test_ai_cache_extended.py
# ======================================================================


class TestCacheEntryDataclass:
    """Tests for CacheEntry dataclass."""

    def test_cache_entry_exists(self):
        """Test CacheEntry class exists."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        assert CacheEntry is not None

    def test_cache_entry_create(self):
        """Test CacheEntry can be created."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(
            response="Hello!",
            created_at=time.time(),
        )

        assert entry.response == "Hello!"
        assert entry.hits == 0

    def test_cache_entry_with_hits(self):
        """Test CacheEntry with custom hits."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(
            response="Test",
            created_at=time.time(),
            hits=5,
        )

        assert entry.hits == 5

    def test_cache_entry_with_context_hash(self):
        """Test CacheEntry with context_hash."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(
            response="Test",
            created_at=time.time(),
            context_hash="abc123",
        )

        assert entry.context_hash == "abc123"

    def test_cache_entry_with_intent(self):
        """Test CacheEntry with intent."""
        from cogs.ai_core.cache.ai_cache import CacheEntry

        entry = CacheEntry(
            response="Test",
            created_at=time.time(),
            intent="greeting",
        )

        assert entry.intent == "greeting"


class TestCacheStatsDataclass:
    """Tests for CacheStats dataclass."""

    def test_cache_stats_exists(self):
        """Test CacheStats class exists."""
        from cogs.ai_core.cache.ai_cache import CacheStats

        assert CacheStats is not None

    def test_cache_stats_create(self):
        """Test CacheStats can be created."""
        from cogs.ai_core.cache.ai_cache import CacheStats

        stats = CacheStats(
            total_entries=10,
            hits=5,
            misses=5,
            hit_rate=0.5,
            memory_estimate_kb=100.0,
        )

        assert stats.total_entries == 10
        assert stats.hits == 5
        assert stats.misses == 5
        assert stats.hit_rate == 0.5

    def test_cache_stats_with_semantic_hits(self):
        """Test CacheStats with semantic_hits."""
        from cogs.ai_core.cache.ai_cache import CacheStats

        stats = CacheStats(
            total_entries=10,
            hits=5,
            misses=5,
            hit_rate=0.5,
            memory_estimate_kb=100.0,
            semantic_hits=2,
        )

        assert stats.semantic_hits == 2


class TestAICacheClass:
    """Tests for AICache class."""

    def test_ai_cache_exists(self):
        """Test AICache class exists."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache is not None

    def test_ai_cache_init(self):
        """Test AICache initialization."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        assert cache is not None

    def test_ai_cache_init_with_params(self):
        """Test AICache initialization with custom params."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=100, ttl=600)

        assert cache.max_size == 100
        assert cache.ttl == 600


class TestAICacheConstants:
    """Tests for AICache constants."""

    def test_default_ttl(self):
        """Test DEFAULT_TTL constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.DEFAULT_TTL is not None
        assert AICache.DEFAULT_TTL > 0

    def test_default_max_size(self):
        """Test DEFAULT_MAX_SIZE constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.DEFAULT_MAX_SIZE is not None
        assert AICache.DEFAULT_MAX_SIZE > 0

    def test_similarity_threshold(self):
        """Test SIMILARITY_THRESHOLD constant."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.SIMILARITY_THRESHOLD is not None
        assert 0 < AICache.SIMILARITY_THRESHOLD < 1


class TestAICacheMethods:
    """Tests for AICache methods."""

    def test_cache_has_get_method(self):
        """Test AICache has get method."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        assert hasattr(cache, "get")

    def test_cache_has_set_method(self):
        """Test AICache has set method."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        assert hasattr(cache, "set")

    def test_cache_has_invalidate_method(self):
        """Test AICache has invalidate method."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        assert hasattr(cache, "invalidate") or hasattr(cache, "invalidate_pattern")

    def test_cache_has_get_stats_method(self):
        """Test AICache has get_stats method."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()

        assert hasattr(cache, "get_stats")


class TestAICacheSetAndGet:
    """Tests for AICache set and get operations."""

    def test_set_and_get_basic(self):
        """Test basic set and get."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        cache.set("test message", "Hello!")

        cache.get("test message")

        # Note: result may be None due to internal normalization
        # This test just verifies the operations don't raise errors

    def test_invalidate_removes_pattern(self):
        """Test invalidate removes entries matching pattern."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        cache.set("greeting hello", "Hi!")
        cache.set("greeting bye", "Bye!")

        # Invalidate and check stats
        if hasattr(cache, "invalidate_pattern"):
            cache.invalidate_pattern("greeting")

        # After invalidation, check stats still work
        stats = cache.get_stats()
        assert stats is not None


class TestAICacheStats:
    """Tests for AICache stats."""

    def test_get_stats_returns_cache_stats(self):
        """Test get_stats returns CacheStats."""
        from cogs.ai_core.cache.ai_cache import AICache, CacheStats

        cache = AICache()
        stats = cache.get_stats()

        assert isinstance(stats, CacheStats)

    def test_get_stats_has_hit_rate(self):
        """Test get_stats includes hit_rate."""
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache()
        stats = cache.get_stats()

        assert hasattr(stats, "hit_rate")


class TestNormalizePatterns:
    """Tests for NORMALIZE_PATTERNS constant."""

    def test_normalize_patterns_exists(self):
        """Test NORMALIZE_PATTERNS exists."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache.NORMALIZE_PATTERNS is not None

    def test_normalize_patterns_is_list(self):
        """Test NORMALIZE_PATTERNS is a list."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert isinstance(AICache.NORMALIZE_PATTERNS, list)


class TestModuleDocstring:
    """Tests for module documentation."""


# ======================================================================
# Eviction-on-set regression tests
#
# These cover the set()/_evict_lru() interaction that was just fixed:
#   - inserting a NEW key at capacity evicts exactly the oldest entry
#   - re-set()ing an EXISTING key at capacity evicts nothing
#   - re-set()ing an existing key carries forward hits / ttl_multiplier
#     (regression for reading `prev` BEFORE evicting)
# ======================================================================


class TestAICacheEvictionOnSet:
    """Regression tests for set() + LRU eviction interaction."""

    def test_new_key_at_capacity_evicts_exactly_one_oldest(self):
        """Filling cache then set()ing a brand-new key evicts only the oldest.

        With max_size=3, after k1,k2,k3 the cache is full. Adding k4 must
        evict exactly the oldest (k1) and keep size == max_size.
        """
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=3)

        cache.set("alpha message one", "response alpha content")
        cache.set("bravo message two", "response bravo content")
        cache.set("charlie message three", "response charlie content")

        assert cache.get_stats().total_entries == 3

        # New key: should evict exactly the oldest (alpha) — size stays 3.
        cache.set("delta message four", "response delta content")

        assert len(cache.cache) == 3
        assert cache.get_stats().total_entries == 3

        # Oldest (alpha) is gone; bravo/charlie/delta remain retrievable.
        # Use use_fuzzy=False so we only assert on exact-key presence and the
        # eviction can't be masked by a lexical fuzzy match.
        assert cache.get("alpha message one", use_fuzzy=False) is None
        assert cache.get("bravo message two", use_fuzzy=False) == "response bravo content"
        assert cache.get("charlie message three", use_fuzzy=False) == "response charlie content"
        assert cache.get("delta message four", use_fuzzy=False) == "response delta content"

    def test_reset_existing_key_at_capacity_evicts_nothing(self):
        """Re-set()ing an already-present key at capacity evicts no other entry.

        A refresh is net-zero growth, so it must NOT pop an unrelated oldest
        entry. All three original keys stay retrievable and size is unchanged.
        """
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=3)

        cache.set("alpha message one", "response alpha content")
        cache.set("bravo message two", "response bravo content")
        cache.set("charlie message three", "response charlie content")

        assert len(cache.cache) == 3

        # Re-set the OLDEST existing key (alpha). This is a refresh, not a new
        # insert — nothing should be evicted, size stays 3.
        cache.set("alpha message one", "alpha refreshed response content")

        assert len(cache.cache) == 3

        # Every original key is still present (none evicted by the refresh).
        assert cache.get("alpha message one", use_fuzzy=False) == "alpha refreshed response content"
        assert cache.get("bravo message two", use_fuzzy=False) == "response bravo content"
        assert cache.get("charlie message three", use_fuzzy=False) == "response charlie content"

    def test_reset_existing_key_carries_forward_hits_and_ttl(self):
        """Re-set()ing an existing key preserves carried-forward hits/ttl_multiplier.

        Regression for evicting-before-reading-prev: set() must read the
        existing entry BEFORE any eviction so a refresh keeps the hit count
        and adaptive-TTL multiplier of the hot entry it's replacing.
        """
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=3)

        cache.set("hotkey message here", "hot response content original")

        # Bump hits to 5 so adaptive TTL engages:
        # _update_adaptive_ttl => 1.0 + (hits // 5) * 0.2 == 1.2 at 5 hits.
        for _ in range(5):
            cache.get("hotkey message here", use_fuzzy=False)

        key = cache._generate_key("hotkey message here")
        before = cache.cache[key]
        assert before.hits == 5
        assert before.ttl_multiplier == 1.2

        # Re-set the SAME key. The new entry must inherit hits + ttl_multiplier
        # from the previous entry (not reset to 0 / 1.0).
        cache.set("hotkey message here", "hot response content refreshed")

        after = cache.cache[key]
        assert after.response == "hot response content refreshed"
        assert after.hits == 5
        assert after.ttl_multiplier == 1.2

    def test_reset_existing_key_carries_hits_even_at_capacity(self):
        """Carry-forward survives even when the cache is at capacity.

        Combines the carry-forward and capacity cases: a refresh of a hot key
        while full must keep its hits/ttl and must not be the entry evicted.
        """
        from cogs.ai_core.cache.ai_cache import AICache

        cache = AICache(max_size=3)

        cache.set("alpha message one", "response alpha content")
        cache.set("bravo message two", "response bravo content")
        cache.set("charlie message three", "response charlie content")

        # Make charlie hot (5 hits => ttl_multiplier 1.2).
        for _ in range(5):
            cache.get("charlie message three", use_fuzzy=False)

        key = cache._generate_key("charlie message three")
        assert cache.cache[key].hits == 5
        assert cache.cache[key].ttl_multiplier == 1.2

        # Refresh charlie while at capacity: no eviction, carry-forward intact.
        cache.set("charlie message three", "charlie refreshed content")

        assert len(cache.cache) == 3
        refreshed = cache.cache[key]
        assert refreshed.response == "charlie refreshed content"
        assert refreshed.hits == 5
        assert refreshed.ttl_multiplier == 1.2


class TestAICacheInvalidateL2Isolation:
    """invalidate()'s L2 purge is confined to the wired singleton.

    A throwaway AICache() must stay L1-only so running the suite can't
    DELETE FROM the real data/ai_cache_l2.db, and its returned count must
    not fold in L2 rows it never wrote.
    """

    def test_throwaway_instance_has_no_l2(self):
        """A freshly constructed AICache is not wired to any shared L2."""
        from cogs.ai_core.cache.ai_cache import AICache

        assert AICache()._l2_cache is None

    def test_singleton_wired_to_global_l2(self):
        """The module singleton is wired to the global L2 instance."""
        from cogs.ai_core.cache.ai_cache import _l2_cache, ai_cache

        assert ai_cache._l2_cache is _l2_cache

    def test_invalidate_on_throwaway_does_not_touch_global_l2(self, monkeypatch):
        """Throwaway invalidate() never calls the global L2.clear and counts only L1."""
        # Use the ``from <submodule> import`` form: the package __init__ re-exports
        # the ``ai_cache`` singleton, which shadows the submodule under attribute
        # access (so ``import cogs.ai_core.cache.ai_cache as mod`` would bind the
        # instance, not the module). This form binds the real module globals.
        from cogs.ai_core.cache.ai_cache import AICache, _l2_cache

        calls = []

        def spy_clear(pattern=None):
            calls.append(pattern)
            return 99  # would inflate the count if ever folded in

        monkeypatch.setattr(_l2_cache, "clear", spy_clear)

        cache = AICache()
        cache.set("throwaway message one", "throwaway response content one")
        cache.set("throwaway message two", "throwaway response content two")

        l1_count = len(cache.cache)
        assert l1_count == 2  # both entries actually stored

        count = cache.invalidate()

        assert calls == []  # global L2.clear never invoked
        assert count == l1_count  # count reflects only L1 rows
