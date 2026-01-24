"""
AI Response Cache Module
Caches common AI responses for improved performance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# Try to import numpy for semantic matching
try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


# Using slots=True for ~30% memory reduction and faster attribute access
@dataclass(slots=True)
class CacheEntry:
    """A single cache entry."""

    response: str
    created_at: float
    hits: int = 0
    context_hash: str = ""
    intent: str = ""
    normalized_message: str = ""  # For fuzzy matching
    embedding: Any | None = None  # For semantic matching
    ttl_multiplier: float = 1.0  # Adaptive TTL: increases with hits


@dataclass(slots=True)
class CacheStats:
    """Cache statistics."""

    total_entries: int
    hits: int
    misses: int
    hit_rate: float
    memory_estimate_kb: float
    semantic_hits: int = 0


class AICache:
    """
    LRU Cache with TTL for AI responses.

    Features:
    - Time-based expiration
    - LRU eviction
    - Normalized key generation
    - Context-aware caching
    - Semantic similarity matching (optional)
    - Fuzzy string matching for near-misses
    """

    DEFAULT_TTL = 28800  # 8 hours (optimized for 32GB RAM)
    DEFAULT_MAX_SIZE = 5000  # Increased for high-RAM systems
    SIMILARITY_THRESHOLD = 0.85  # For fuzzy matching
    SEMANTIC_THRESHOLD = 0.9  # For embedding-based matching

    # Patterns to normalize messages for caching
    NORMALIZE_PATTERNS = [
        # Remove timestamps
        (r"\[\d{4}-\d{2}-\d{2}.+?\]", ""),
        # Remove user mentions
        (r"<@!?\d+>", "[USER]"),
        # Remove channel mentions
        (r"<#\d+>", "[CHANNEL]"),
        # Remove extra whitespace
        (r"\s+", " "),
    ]

    def __init__(
        self, ttl: int = DEFAULT_TTL, max_size: int = DEFAULT_MAX_SIZE, enable_semantic: bool = True
    ):
        self.ttl = ttl
        self.max_size = max_size
        self.enable_semantic = enable_semantic and NUMPY_AVAILABLE
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._cache_lock = threading.Lock()  # Thread-safe lock for cache operations
        self.logger = logging.getLogger("AICache")

        # Stats
        self._hits = 0
        self._misses = 0
        self._semantic_hits = 0

        # Compile normalize patterns
        self._normalize_compiled = [
            (re.compile(pattern), repl) for pattern, repl in self.NORMALIZE_PATTERNS
        ]

    def _normalize_message(self, message: str) -> str:
        """Normalize message for consistent cache keys."""
        normalized = message.lower().strip()

        for pattern, repl in self._normalize_compiled:
            normalized = pattern.sub(repl, normalized)

        return normalized.strip()

    def _generate_key(
        self, message: str, context_hash: str | None = None, intent: str | None = None
    ) -> str:
        """Generate a cache key from message and context."""
        normalized = self._normalize_message(message)

        # Include context hash if provided
        key_parts = [normalized]
        if context_hash:
            key_parts.append(context_hash)
        if intent:
            key_parts.append(intent)

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _evict_lru(self) -> None:
        """Evict least recently used entries if cache is full."""
        while len(self.cache) >= self.max_size:
            # Pop the oldest item (first in OrderedDict)
            evicted_key, _ = self.cache.popitem(last=False)
            self.logger.debug("Evicted LRU entry: %s...", evicted_key[:8])

    def _calculate_similarity(self, msg1: str, msg2: str) -> float:
        """Calculate string similarity between two messages."""
        return SequenceMatcher(None, msg1, msg2).ratio()

    def _embedding_similarity(self, emb1: Any, emb2: Any) -> float:
        """Calculate cosine similarity between two embeddings."""
        if not NUMPY_AVAILABLE or emb1 is None or emb2 is None:
            return 0.0
        try:
            dot_product = np.dot(emb1, emb2)
            norm1 = np.linalg.norm(emb1)
            norm2 = np.linalg.norm(emb2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(dot_product / (norm1 * norm2))
        except (ValueError, TypeError, np.linalg.LinAlgError):
            return 0.0

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if cache entry has expired. Uses adaptive TTL."""
        effective_ttl = self.ttl * entry.ttl_multiplier
        return time.time() - entry.created_at > effective_ttl

    def _update_adaptive_ttl(self, entry: CacheEntry) -> None:
        """Update TTL multiplier based on hit count."""
        # Every 5 hits, increase TTL by 20% (max 3x)
        entry.ttl_multiplier = min(3.0, 1.0 + (entry.hits // 5) * 0.2)

    def find_similar(
        self, message: str, intent: str | None = None, threshold: float | None = None
    ) -> tuple[str, CacheEntry, float] | None:
        """
        Find similar cached entry using fuzzy matching.

        Args:
            message: User message to match
            intent: Detected intent (must match if provided)
            threshold: Minimum similarity threshold

        Returns:
            Tuple of (key, entry, similarity) or None
        """
        threshold = threshold or self.SIMILARITY_THRESHOLD
        normalized = self._normalize_message(message)

        best_match = None
        best_similarity = 0.0

        # Create snapshot of cache items to avoid RuntimeError during iteration
        for key, entry in list(self.cache.items()):
            # Skip expired entries
            if self._is_expired(entry):
                continue

            # Intent must match if specified
            if intent and entry.intent and entry.intent != intent:
                continue

            # Skip if no normalized message stored
            if not entry.normalized_message:
                continue

            # Calculate similarity
            similarity = self._calculate_similarity(normalized, entry.normalized_message)

            if similarity > best_similarity and similarity >= threshold:
                best_similarity = similarity
                best_match = (key, entry, similarity)

        return best_match

    async def find_semantic_match(
        self,
        message: str,
        embedding: Any = None,
        get_embedding_fn: Callable[[str], Awaitable[Any]] | None = None,
        threshold: float | None = None,
    ) -> tuple[str, CacheEntry, float] | None:
        """
        Find similar cached entry using embedding-based semantic matching.

        This provides better matching than fuzzy string matching for semantically
        similar but lexically different messages.

        Args:
            message: User message to match
            embedding: Pre-computed embedding (optional)
            get_embedding_fn: Function to compute embedding if not provided
            threshold: Minimum similarity threshold

        Returns:
            Tuple of (key, entry, similarity) or None
        """
        if not self.enable_semantic:
            return None

        threshold = threshold or self.SEMANTIC_THRESHOLD

        # Get embedding for query
        query_embedding = embedding
        if query_embedding is None and get_embedding_fn:
            try:
                query_embedding = await get_embedding_fn(message)
            except Exception as e:
                self.logger.debug("Failed to get embedding for semantic search: %s", e)
                return None

        if query_embedding is None:
            return None

        best_match = None
        best_similarity = 0.0

        # Create snapshot of cache items to avoid RuntimeError during iteration
        for key, entry in list(self.cache.items()):
            # Skip expired entries
            if self._is_expired(entry):
                continue

            # Skip if no embedding stored
            if entry.embedding is None:
                continue

            # Calculate semantic similarity
            similarity = self._embedding_similarity(query_embedding, entry.embedding)

            if similarity > best_similarity and similarity >= threshold:
                best_similarity = similarity
                best_match = (key, entry, similarity)

        if best_match:
            self.logger.debug("Semantic match found (%.3f similarity)", best_similarity)

        return best_match

    def get(
        self,
        message: str,
        context_hash: str | None = None,
        intent: str | None = None,
        use_fuzzy: bool = True,
    ) -> str | None:
        """
        Get cached response if available.

        Args:
            message: User message
            context_hash: Hash of conversation context
            intent: Detected intent
            use_fuzzy: Try fuzzy matching if exact match fails

        Returns:
            Cached response or None
        """
        key = self._generate_key(message, context_hash, intent)

        entry = self.cache.get(key)
        if entry is not None and not self._is_expired(entry):
            # Exact cache hit - move to end (most recently used)
            self.cache.move_to_end(key)
            entry.hits += 1
            self._update_adaptive_ttl(entry)
            self._hits += 1
            self.logger.debug("Cache hit (exact): %s... (hits: %d)", key[:8], entry.hits)
            return entry.response

        # Try fuzzy matching as fallback
        if use_fuzzy and self.enable_semantic:
            similar = self.find_similar(message, intent)
            if similar:
                similar_key, similar_entry, similarity = similar
                self.cache.move_to_end(similar_key)
                similar_entry.hits += 1
                self._hits += 1
                self._semantic_hits += 1
                self.logger.debug("Cache hit (fuzzy %.2f): %s...", similarity, similar_key[:8])
                return similar_entry.response

        self._misses += 1
        return None

    def set(
        self,
        message: str,
        response: str,
        context_hash: str | None = None,
        intent: str | None = None,
    ) -> None:
        """
        Store a response in cache.

        Args:
            message: Original user message
            response: AI response to cache
            context_hash: Hash of conversation context
            intent: Detected intent
        """
        # Don't cache very short or very long responses
        if len(response) < 10 or len(response) > 1500:
            return

        key = self._generate_key(message, context_hash, intent)

        # Evict if necessary
        self._evict_lru()

        # Store normalized message for fuzzy matching
        normalized = self._normalize_message(message)

        self.cache[key] = CacheEntry(
            response=response,
            created_at=time.time(),
            context_hash=context_hash or "",
            intent=intent or "",
            normalized_message=normalized,
        )

        self.logger.debug("Cached response: %s...", key[:8])

    async def get_or_generate(
        self,
        message: str,
        generate_fn: Callable[..., Awaitable[str]],
        context_hash: str | None = None,
        intent: str | None = None,
        use_cache: bool = True,
    ) -> tuple[str, bool]:
        """
        Get from cache or generate new response.

        Args:
            message: User message
            generate_fn: Async function to generate response
            context_hash: Hash of conversation context
            intent: Detected intent
            use_cache: Whether to use cache

        Returns:
            Tuple of (response, was_cached)
        """
        if use_cache:
            cached = self.get(message, context_hash, intent)
            if cached:
                return cached, True

        # Generate new response
        response = await generate_fn()

        # Store in cache
        if use_cache:
            self.set(message, response, context_hash, intent)

        return response, False

    def invalidate(self, pattern: str | None = None) -> int:
        """
        Invalidate cache entries.

        Args:
            pattern: If provided, only invalidate matching keys

        Returns:
            Number of entries invalidated
        """
        if pattern is None:
            count = len(self.cache)
            self.cache.clear()
            return count

        # Find and remove matching entries
        to_remove = [key for key in self.cache if pattern in key]
        for key in to_remove:
            del self.cache[key]

        return len(to_remove)

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        expired_keys = [
            key
            for key, entry in self.cache.items()
            if now - entry.created_at > self.ttl * entry.ttl_multiplier
        ]

        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            self.logger.info("Cleaned up %d expired cache entries", len(expired_keys))

        return len(expired_keys)

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        # Estimate memory usage
        memory_bytes = sum(
            len(entry.response) + len(entry.context_hash) + 100 for entry in self.cache.values()
        )

        return CacheStats(
            total_entries=len(self.cache),
            hits=self._hits,
            misses=self._misses,
            hit_rate=hit_rate,
            memory_estimate_kb=memory_bytes / 1024,
            semantic_hits=self._semantic_hits,
        )

    def reset_stats(self) -> None:
        """Reset hit/miss statistics."""
        self._hits = 0
        self._misses = 0


class ContextHasher:
    """Helper to generate context hashes for cache keys."""

    @staticmethod
    def hash_history(history: list[dict[str, Any]], last_n: int = 5) -> str:
        """
        Generate hash from recent history.

        Args:
            history: Conversation history
            last_n: Number of recent messages to include

        Returns:
            Hash string
        """
        recent = history[-last_n:] if len(history) > last_n else history

        # Extract just roles and first 50 chars of each message
        summary = []
        for msg in recent:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            text = parts[0][:50] if parts and isinstance(parts[0], str) else ""
            summary.append(f"{role}:{text}")

        return hashlib.md5("|".join(summary).encode()).hexdigest()[:16]


def _load_resource_config() -> dict:
    """Load resource configuration from JSON file."""
    config_path = Path(__file__).parent.parent.parent.parent / "data" / "resource_config.json"
    try:
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            logging.info("Loaded resource config from %s", config_path)
            return config
    except Exception as e:
        logging.warning("Failed to load resource config: %s", e)
    return {}


# Load config and create global instances
_resource_config = _load_resource_config()
_ai_config = _resource_config.get("ai_cache", {})

ai_cache = AICache(
    ttl=_ai_config.get("ttl_seconds", AICache.DEFAULT_TTL),
    max_size=_ai_config.get("max_entries", AICache.DEFAULT_MAX_SIZE),
)
context_hasher = ContextHasher()


def get_cache_stats() -> CacheStats:
    """Get global cache statistics."""
    return ai_cache.get_stats()
