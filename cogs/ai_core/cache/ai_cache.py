"""
AI Response Cache Module
Caches common AI responses for improved performance.
Features L1 in-memory (OrderedDict) and L2 persistent (SQLite) cache layers.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# Cache size limits — short responses aren't worth the per-entry overhead;
# very long ones tend to be session-specific and dilute the hit rate.
_CACHE_MIN_RESPONSE_CHARS = 10
_CACHE_MAX_RESPONSE_CHARS = 1500


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
    semantic_hits: int = 0  # embedding-based matches
    fuzzy_hits: int = 0  # lexical (difflib SequenceMatcher) matches


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

    # Patterns to normalize messages for caching
    NORMALIZE_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        # Remove timestamps
        (r"\[\d{4}-\d{2}-\d{2}.+?\]", ""),
        # Remove user mentions
        (r"<@!?\d+>", "[USER]"),
        # Remove channel mentions
        (r"<#\d+>", "[CHANNEL]"),
        # Remove extra whitespace
        (r"\s+", " "),
    ]

    def __init__(self, ttl: int = DEFAULT_TTL, max_size: int = DEFAULT_MAX_SIZE):
        self.ttl = ttl
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._cache_lock = threading.Lock()  # Thread-safe lock for cache operations
        self.logger = logging.getLogger("AICache")

        # Clamp to sane minimums: a ttl <= 0 makes every entry instantly
        # expired (the cache serves nothing); a max_size <= 0 disables LRU
        # eviction (unbounded growth). A bad resource_config.json value
        # shouldn't silently break the cache — coerce + warn instead.
        if self.ttl <= 0:
            self.logger.warning("AICache ttl=%s invalid; using %s", self.ttl, self.DEFAULT_TTL)
            self.ttl = self.DEFAULT_TTL
        if self.max_size <= 0:
            self.logger.warning(
                "AICache max_size=%s invalid; using %s", self.max_size, self.DEFAULT_MAX_SIZE
            )
            self.max_size = self.DEFAULT_MAX_SIZE

        # Stats
        self._hits = 0
        self._misses = 0
        self._semantic_hits = 0  # embedding-based matches (currently unused)
        self._fuzzy_hits = 0  # difflib SequenceMatcher matches

        # Compile normalize patterns
        self._normalize_compiled = [
            (re.compile(pattern), repl) for pattern, repl in self.NORMALIZE_PATTERNS
        ]

    def warm_with_entries(self, entries: list[tuple[str, CacheEntry]]) -> int:
        """Bulk-load (key, CacheEntry) pairs into L1 from a persistent store.

        Public counterpart to the previous module-level warm-up that reached
        into ``_cache_lock`` and ``cache`` directly. Goes through a single
        lock acquisition, skips entries that are already present, and respects
        ``max_size`` so a corrupt L2 with many rows can't blow past the cap
        before the eviction path catches up.
        """
        added = 0
        with self._cache_lock:
            for key, entry in entries:
                if key in self.cache:
                    continue
                if len(self.cache) >= self.max_size:
                    # load_recent() delivers entries best-first (ORDER BY hits
                    # DESC), so once at capacity the *remaining* entries are the
                    # least valuable. Stop here instead of popitem(last=False),
                    # which would evict the highest-hit entries we just inserted.
                    break
                self.cache[key] = entry
                added += 1
        return added

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
        return hashlib.sha256(key_string.encode()).hexdigest()

    def _evict_lru(self) -> None:
        """Evict least recently used entries if cache is full."""
        if self.max_size <= 0:
            return
        while len(self.cache) >= self.max_size:
            # Pop the oldest item (first in OrderedDict)
            evicted_key, _ = self.cache.popitem(last=False)
            self.logger.debug("Evicted LRU entry: %s...", evicted_key[:8])

    def _calculate_similarity(self, msg1: str, msg2: str) -> float:
        """Calculate string similarity between two messages."""
        return SequenceMatcher(None, msg1, msg2).ratio()

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
        # Honor an explicit threshold=0.0 (match-anything) — `or` would treat
        # the legitimate 0.0 as falsy and silently substitute the default.
        threshold = self.SIMILARITY_THRESHOLD if threshold is None else threshold
        normalized = self._normalize_message(message)

        best_match = None
        best_similarity = 0.0

        # Create snapshot of cache items under lock to avoid RuntimeError during iteration
        with self._cache_lock:
            cache_snapshot = list(self.cache.items())

        for key, entry in cache_snapshot:
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

        with self._cache_lock:
            entry = self.cache.get(key)
            if entry is not None and not self._is_expired(entry):
                # Exact cache hit - move to end (most recently used)
                self.cache.move_to_end(key)
                entry.hits += 1
                self._update_adaptive_ttl(entry)
                self._hits += 1
                self.logger.debug("Cache hit (exact): %s... (hits: %d)", key[:8], entry.hits)
                return entry.response

        # Try fuzzy matching as fallback (OUTSIDE lock to avoid nested lock deadlock)
        # Note: find_similar uses difflib.SequenceMatcher (stdlib), does NOT require numpy
        if use_fuzzy:
            similar = self.find_similar(message, intent)
            if similar:
                similar_key, similar_entry, similarity = similar
                with self._cache_lock:
                    # Belt-and-braces: re-check the EXACT key first. The
                    # fuzzy scan released the lock for ~ms; another writer
                    # may have inserted/refreshed the exact entry while we
                    # were scanning, in which case the (stale) fuzzy match
                    # would shadow it. Prefer exact every time.
                    exact_fresh = self.cache.get(key)
                    if exact_fresh is not None and not self._is_expired(exact_fresh):
                        self.cache.move_to_end(key)
                        exact_fresh.hits += 1
                        self._update_adaptive_ttl(exact_fresh)
                        self._hits += 1
                        self.logger.debug(
                            "Cache hit (exact, post-fuzzy): %s... (hits: %d)",
                            key[:8],
                            exact_fresh.hits,
                        )
                        return exact_fresh.response
                    # Re-verify entry still exists AND is not expired after
                    # releasing and re-acquiring the lock — the entry may
                    # have ticked past its TTL during the fuzzy scan.
                    fresh = self.cache.get(similar_key)
                    if fresh is not None and not self._is_expired(fresh):
                        self.cache.move_to_end(similar_key)
                        fresh.hits += 1
                        self._update_adaptive_ttl(fresh)
                        self._hits += 1
                        # `find_similar` uses difflib SequenceMatcher (lexical),
                        # not embeddings — so this is a lexical-fuzzy hit, not
                        # semantic. Track it under a separate counter so the
                        # `semantic_hits` stat isn't inflated.
                        self._fuzzy_hits += 1
                        self.logger.debug(
                            "Cache hit (fuzzy %.2f): %s...", similarity, similar_key[:8]
                        )
                        return fresh.response

        with self._cache_lock:
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
        # Don't cache very short or very long responses. The 1500-char ceiling
        # is intentional for now — long answers are usually session-specific
        # and unlikely to recur — but operators want visibility into this
        # implicit drop, hence the debug log.
        if len(response) < _CACHE_MIN_RESPONSE_CHARS:
            return
        if len(response) > _CACHE_MAX_RESPONSE_CHARS:
            self.logger.debug(
                "Skipping cache.set: response %d chars > %d cap",
                len(response),
                _CACHE_MAX_RESPONSE_CHARS,
            )
            return

        key = self._generate_key(message, context_hash, intent)

        with self._cache_lock:
            # Store normalized message for fuzzy matching
            normalized = self._normalize_message(message)

            entry = CacheEntry(
                response=response,
                created_at=time.time(),
                context_hash=context_hash or "",
                intent=intent or "",
                normalized_message=normalized,
            )
            # Carry forward the hit count + adaptive-TTL multiplier from any
            # existing entry for this key. A refresh shouldn't demote a hot
            # entry back to cold — otherwise the adaptive-TTL feature (which
            # keys off ``hits``) never engages for exactly the frequently
            # re-set keys it's meant to keep alive longer.
            #
            # Read ``prev`` BEFORE evicting and only evict when this is a NEW
            # key: _evict_lru() pops from the front, and re-assigning an existing
            # OrderedDict key does NOT move it to the back, so evicting first
            # could pop the very key being refreshed (losing its carried-forward
            # hits/ttl). And a refresh is no net growth, so evicting an unrelated
            # oldest entry for it would needlessly shrink the cache by one.
            prev = self.cache.get(key)
            if prev is not None:
                entry.hits = prev.hits
                entry.ttl_multiplier = prev.ttl_multiplier
                self.cache[key] = entry
                # Re-assigning an existing OrderedDict key keeps its old position,
                # so promote the refreshed entry to most-recently-used — otherwise
                # a frequently-re-set-but-rarely-read key could be evicted ahead
                # of colder-but-recently-touched entries.
                self.cache.move_to_end(key)
            else:
                self._evict_lru()
                self.cache[key] = entry

            # Snapshot the (now possibly refresh-merged) entry while still
            # holding _cache_lock. On a refresh ``entry`` is the live object
            # stored in self.cache, so a concurrent get() can mutate its
            # hits/ttl_multiplier — pass an immutable copy to the hook so L2
            # persistence sees a consistent, torn-read-free snapshot.
            entry_snapshot = replace(entry)

        # Optional persistence hook (e.g. write-through to L2). Set on the
        # instance, not the class — that way subclasses, test instances, and
        # alternate caches don't all inherit the same persistence target via
        # a class-level monkey-patch.
        hook = getattr(self, "_post_set_hook", None)
        if hook is not None:
            try:
                hook(key, entry_snapshot)
            except Exception:
                self.logger.exception("AICache post_set_hook raised")

        self.logger.debug("Cached response: %s...", key[:8])

    def invalidate(self, pattern: str | None = None) -> int:
        """
        Invalidate cache entries.

        Args:
            pattern: If provided, only invalidate matching keys

        Returns:
            Total rows cleared across BOTH cache layers (L1 in-memory + L2
            persistent). On the production singleton every L1 entry is
            write-through-mirrored to L2 under the same key, so an entry
            present in both layers is counted twice — this is a rows-cleared
            total, not a distinct-key count, and the operator-facing
            "cleared N entries" message should be read that way.
        """
        with self._cache_lock:
            if pattern is None:
                count = len(self.cache)
                self.cache.clear()
            else:
                # Find and remove matching entries
                to_remove = [key for key in self.cache if pattern in key]
                for key in to_remove:
                    del self.cache[key]
                count = len(to_remove)

        # Purge the persistent L2 layer too — otherwise load_recent's 24h
        # warm-up resurrects the cleared entries at the next startup.
        with contextlib.suppress(Exception):
            count += _l2_cache.clear(pattern)

        return count

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed.

        Reuses ``_is_expired`` so the TTL formula stays in one place —
        previously this method duplicated the comparison and could drift
        from the canonical implementation (e.g. if adaptive TTL gained
        a min/max clamp).
        """
        with self._cache_lock:
            expired_keys = [key for key, entry in self.cache.items() if self._is_expired(entry)]
            for key in expired_keys:
                del self.cache[key]
            if expired_keys:
                self.logger.info("Cleaned up %d expired cache entries", len(expired_keys))
            return len(expired_keys)

    async def start_cleanup_loop(self, interval: float = 3600.0) -> None:
        """Background loop that periodically cleans up expired cache entries.

        Args:
            interval: Seconds between cleanup runs (default: 1 hour).
        """
        while True:
            try:
                await asyncio.sleep(interval)
                # Run the O(n) scan + deletes off the event loop: cleanup_expired()
                # acquires the same threading.Lock that get()/set() hold from
                # executor/handler threads, so doing it inline would briefly stall
                # the loop. It's already lock-safe, so to_thread only relocates it.
                removed = await asyncio.to_thread(self.cleanup_expired)
                if removed:
                    self.logger.info("🧹 Background cache cleanup: removed %d entries", removed)
            except asyncio.CancelledError:
                return
            except RuntimeError as e:
                if "Event loop is closed" in str(e):
                    self.logger.info("Cache cleanup stopped — event loop closed")
                    return
                self.logger.debug("Cache cleanup runtime error: %s", e)
            except Exception as e:
                self.logger.debug("Cache cleanup error: %s", e)

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._cache_lock:
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
                fuzzy_hits=self._fuzzy_hits,
            )

    def reset_stats(self) -> None:
        """Reset hit/miss statistics under the cache lock so a concurrent
        `get()` increment can't race with the reset and produce a negative
        hit count or lose an increment."""
        with self._cache_lock:
            self._hits = 0
            self._misses = 0
            self._semantic_hits = 0
            self._fuzzy_hits = 0


def _resolve_project_root() -> Path:
    """Find the project root by walking upward looking for a marker file.

    The previous hard-coded ``Path(__file__).parent ... .parent`` chain
    silently returned the wrong directory when this module was loaded from
    a copy outside the canonical layout (e.g. an agent worktree, a wheel
    install). Walk upward instead, falling back to the parent-chain root if
    no marker is found so behaviour is no worse than before.
    """
    candidate = Path(__file__).resolve().parent
    for _ in range(8):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    # Last-resort fallback to the original anchor.
    return Path(__file__).resolve().parent.parent.parent.parent


def _load_resource_config() -> dict:
    """Load resource configuration from JSON file."""
    config_path = _resolve_project_root() / "data" / "resource_config.json"
    try:
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            logger.info("Loaded resource config from %s", config_path)
            return config  # type: ignore[no-any-return]
        logger.debug("Resource config not found at %s — using defaults", config_path)
    except Exception as e:
        logger.warning("Failed to load resource config: %s", e)
    return {}


# ==================== L2 Persistent Cache ====================


class L2SqliteCache:
    """
    SQLite-backed persistent cache layer (L2).

    Survives restarts and warms up the in-memory L1 cache on startup.
    """

    DB_PATH = _resolve_project_root() / "data" / "ai_cache_l2.db"
    MAX_ENTRIES = 20_000  # hard cap on disk rows

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Create DB and schema if needed."""
        try:
            self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.DB_PATH), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key       TEXT PRIMARY KEY,
                    response  TEXT NOT NULL,
                    intent    TEXT DEFAULT '',
                    norm_msg  TEXT DEFAULT '',
                    ctx_hash  TEXT DEFAULT '',
                    created   REAL NOT NULL,
                    hits      INTEGER DEFAULT 0
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_created ON cache_entries(created)"
            )
            self._conn.commit()
        except (sqlite3.DatabaseError, OSError) as e:
            # OSError included: mkdir/connect on a read-only or full disk
            # raises it, and this runs at IMPORT time via the module-level
            # singleton — letting it escape aborted the whole ai_core package
            # load (imports.py's fallback only catches ImportError).
            logger.warning("L2 cache init failed (non-fatal): %s", e)
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None

    def clear(self, pattern: str | None = None) -> int:
        """Delete persisted rows (all, or keys containing ``pattern``).

        Returns the number of rows removed. Needed so invalidate() can purge
        the L2 layer too — an L1-only clear let the 24h warm-up resurrect
        cleared (possibly poisoned) entries on the next restart.
        """
        if self._conn is None:
            return 0
        with self._lock:
            try:
                if pattern is None:
                    # An unqualified DELETE is truncate-optimized by SQLite, so
                    # cur.rowcount comes back 0/-1 and under-reports the rows
                    # cleared. Count first, then delete, and return that count.
                    count = int(
                        self._conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
                    )
                    self._conn.execute("DELETE FROM cache_entries")
                    self._conn.commit()
                    return count
                else:
                    # Substring match mirrors the L1 `pattern in key` filter.
                    cur = self._conn.execute(
                        "DELETE FROM cache_entries WHERE instr(key, ?) > 0",
                        (pattern,),
                    )
                self._conn.commit()
                return int(cur.rowcount)
            except sqlite3.DatabaseError:
                logger.warning("L2 cache clear failed", exc_info=True)
                return 0

    def store(self, key: str, entry: CacheEntry) -> None:
        """Persist a cache entry to SQLite."""
        if self._conn is None:
            return
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO cache_entries "
                    "(key, response, intent, norm_msg, ctx_hash, created, hits) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        entry.response,
                        entry.intent or "",
                        entry.normalized_message or "",
                        entry.context_hash or "",
                        entry.created_at,
                        entry.hits,
                    ),
                )
                self._conn.commit()
                self._evict_excess()
            except sqlite3.DatabaseError as e:
                logger.debug("L2 store failed: %s", e)

    def load_recent(
        self, limit: int = 1000, max_age: float = 86400
    ) -> list[tuple[str, CacheEntry]]:
        """Load recent entries for L1 warm-up."""
        if self._conn is None:
            return []
        cutoff = time.time() - max_age
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT key, response, intent, norm_msg, ctx_hash, created, hits "
                    "FROM cache_entries WHERE created > ? ORDER BY hits DESC, created DESC LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
                entries = []
                for key, response, intent, norm_msg, ctx_hash, created, hits in rows:
                    entry = CacheEntry(
                        response=response,
                        created_at=created,
                        context_hash=ctx_hash,
                        intent=intent,
                        normalized_message=norm_msg,
                        hits=hits,
                    )
                    entries.append((key, entry))
                return entries
            except sqlite3.DatabaseError as e:
                logger.warning("L2 load failed: %s", e)
                return []

    def _evict_excess(self) -> None:
        """Remove oldest entries if over MAX_ENTRIES."""
        if self._conn is None:
            return
        try:
            count = self._conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
            if count > self.MAX_ENTRIES:
                excess = count - self.MAX_ENTRIES
                self._conn.execute(
                    "DELETE FROM cache_entries WHERE key IN "
                    "(SELECT key FROM cache_entries ORDER BY created ASC LIMIT ?)",
                    (excess,),
                )
                self._conn.commit()
        except sqlite3.DatabaseError:
            logger.debug("Cache eviction error", exc_info=True)

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                logger.debug("Cache close error", exc_info=True)
            self._conn = None

    def checkpoint(self) -> None:
        """Flush the WAL into the main DB file (``PRAGMA wal_checkpoint(TRUNCATE)``).

        ``synchronous=NORMAL`` + WAL means a hard crash can lose commits still
        sitting in the WAL. Call this on graceful shutdown (after the pending
        writes have landed) so the last cache entries are durable — WITHOUT
        closing the connection, which would break L2 after a cog hot-reload
        since the module-global instance is reused.
        """
        if self._conn:
            try:
                # Hold the same lock store()/load_recent() use: a store() still
                # running in the executor thread pool at shutdown shares this
                # sqlite3.Connection (check_same_thread=False), and concurrent
                # use from two threads is unsupported.
                with self._lock:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                logger.debug("L2 cache checkpoint error", exc_info=True)


# ==================== Global Instances ====================

# Load config and create global instances
_resource_config = _load_resource_config()
_ai_config = _resource_config.get("ai_cache", {})

ai_cache = AICache(
    ttl=_ai_config.get("ttl_seconds", AICache.DEFAULT_TTL),
    max_size=_ai_config.get("max_entries", AICache.DEFAULT_MAX_SIZE),
)

# L2 persistent cache — warm up L1.
# Uses the public warm_with_entries method so import-time warm-up no longer
# reaches into AICache._cache_lock or .cache directly. The method also
# enforces max_size so a corrupt L2 row count can't blow past the cap.
_l2_cache = L2SqliteCache()
try:
    _warm_entries = _l2_cache.load_recent(limit=500)
    if _warm_entries:
        _added = ai_cache.warm_with_entries(_warm_entries)
        logger.info("L2 cache: warmed L1 with %d entries", _added)
except Exception as _e:
    logger.warning("L2 warm-up failed (non-fatal): %s", _e)


def _persist_to_l2(key: str, entry: CacheEntry) -> None:
    """Background persist a new entry to L2 (non-blocking via thread pool).

    Futures are tracked in ``_l2_pending_futures`` so shutdown hooks
    (see :func:`flush_l2_pending`) can await them before the event loop closes.
    Without tracking, ``run_in_executor`` returns a Future that may be
    garbage-collected mid-flight, losing L2 writes and emitting warnings.

    We hand the executor a fresh ``CacheEntry`` snapshot rather than the
    live L1 object — otherwise the worker thread would read mutable fields
    (`hits`, `ttl_multiplier`) without holding the L1 lock, producing
    torn values in the persisted row.
    """
    snapshot = CacheEntry(
        response=entry.response,
        created_at=entry.created_at,
        hits=entry.hits,
        context_hash=entry.context_hash,
        intent=entry.intent,
        normalized_message=entry.normalized_message,
        embedding=entry.embedding,
        ttl_multiplier=entry.ttl_multiplier,
    )
    try:
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, _l2_cache.store, key, snapshot)
        _l2_pending_futures.add(fut)
        # Remove on completion so the set doesn't grow unbounded
        fut.add_done_callback(_l2_pending_futures.discard)
    except RuntimeError:
        # No running event loop — fall back to synchronous
        _l2_cache.store(key, snapshot)


# Tracks outstanding background persist futures so they can be awaited during
# shutdown. Uses a set rather than a list so completed futures self-remove.
_l2_pending_futures: set[asyncio.Future[Any]] = set()


async def flush_l2_pending(timeout: float = 5.0) -> int:
    """Await outstanding L2 persists (call from shutdown path).

    Returns the number of futures flushed. Never raises — individual future
    exceptions are logged and swallowed so shutdown can proceed.
    """
    flushed = 0
    seen: set[asyncio.Future[Any]] = set()
    deadline = time.monotonic() + timeout
    # Re-snapshot until the set drains or the budget is exhausted: a
    # _persist_to_l2() call can submit a new future *after* an earlier
    # snapshot, so a single asyncio.wait would leave it unawaited. Each
    # future is only awaited once (tracked in ``seen``).
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            pending = [f for f in _l2_pending_futures if f not in seen]
            if not pending:
                break
            seen.update(pending)
            done, _pending_set = await asyncio.wait(pending, timeout=remaining)
            for fut in done:
                fut_exc = fut.exception()
                if fut_exc is not None:
                    logger.warning("L2 persist future raised: %s", fut_exc)
            flushed += len(done)
    except Exception as wait_exc:  # pragma: no cover — defensive
        logger.warning("flush_l2_pending: wait failed: %s", wait_exc)
    # Checkpoint the WAL so the just-flushed (and any earlier) writes are durable
    # before the loop closes — synchronous=NORMAL can otherwise lose them on a
    # hard crash. Run in a thread since it's a blocking sqlite call.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(_l2_cache.checkpoint)
    return flushed


# Install L2 persistence as a per-instance hook on the global ai_cache.
# Avoids the previous AICache.set monkey-patch which mutated the CLASS at
# import time — that affected every subclass / test instance / re-imported
# copy and could even cause infinite recursion if the module was loaded twice.
def _l2_post_set_hook(key: str, entry: CacheEntry) -> None:
    _persist_to_l2(key, entry)


ai_cache._post_set_hook = _l2_post_set_hook  # type: ignore[attr-defined]


def get_cache_stats() -> CacheStats:
    """Get global cache statistics."""
    return ai_cache.get_stats()
