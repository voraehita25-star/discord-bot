"""
RAG (Retrieval-Augmented Generation) Module
Handles long-term memory using vector embeddings and cosine similarity.
Enhanced with hybrid search (semantic + keyword) and Reciprocal Rank Fusion.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

logger = logging.getLogger(__name__)

import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Guard the google-genai import — when the project runs in CLI-only mode the
# google-genai package may not be installed (it's only required for the
# embedding-based RAG path). An ImportError here would otherwise take down
# the entire memory layer, including the in-memory fallbacks that don't
# need embeddings at all.
try:
    from google import genai

    _GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore[assignment]
    _GENAI_AVAILABLE = False
    logger.warning(
        "google-genai not installed; RAG embedding generation will be disabled "
        "(install with `pip install google-genai` to re-enable)"
    )

try:
    from utils.database import db

    _DB_AVAILABLE = True
except ImportError:
    db = None  # type: ignore[assignment]
    _DB_AVAILABLE = False
    logger.warning("Database not available for RAG module")

from datetime import datetime, timezone

from ..data.constants import GEMINI_API_KEY

# Index persistence path. Anchor to the project root so the bot can be
# started from any cwd (systemd, scheduled task, IDE) without spawning a
# fresh empty FAISS index every restart and burning embedding API quota.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
FAISS_INDEX_DIR = _PROJECT_ROOT / "data" / "faiss"
FAISS_INDEX_FILE = FAISS_INDEX_DIR / "index.bin"
# JSON sidecar replaces the legacy ``.npy`` (which used
# ``allow_pickle=True``). ``load_from_disk`` still reads the legacy file
# for one cycle so existing deployments migrate transparently on first
# save, but the canonical path is JSON to remove the pickle RCE surface.
FAISS_ID_MAP_FILE = FAISS_INDEX_DIR / "id_map.json"
_LEGACY_FAISS_ID_MAP_FILE = FAISS_INDEX_DIR / "id_map.npy"

# Try to import FAISS for optimized vector search
try:
    import os as _os_faiss

    import faiss

    FAISS_AVAILABLE = True
    # Cap FAISS threads at half of available CPU (min 2) to avoid starving
    # the rest of the bot (event loop, ffmpeg, discord.py gateway, etc.).
    _faiss_cpu = _os_faiss.cpu_count() or 4
    _faiss_threads = max(2, _faiss_cpu // 2)
    faiss.omp_set_num_threads(_faiss_threads)
    logger.info("🚀 FAISS available - using optimized vector search (%d threads)", _faiss_threads)
except ImportError:
    FAISS_AVAILABLE = False
    logger.info("ℹ️ FAISS not installed - using linear scan fallback")


# Embedding Model
EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768  # text-embedding-004 produces 768-dim vectors

# Time decay settings
TIME_DECAY_HALF_LIFE_DAYS = 30  # Memories lose half importance after 30 days

# Database query timeout (seconds) to prevent indefinite blocking
_DB_QUERY_TIMEOUT = 30

# Cap on how many RAG rows we will rebuild the FAISS index from in one pass.
# Prevents loading a multi-million-row table fully into RAM during rebuild.
MAX_RAG_REBUILD = 100_000

# Linear search similarity thresholds
LINEAR_SEARCH_MIN_SIMILARITY = 0.5  # Minimum similarity to include in results
LINEAR_SEARCH_RELEVANCE_THRESHOLD = 0.65  # Threshold for relevance filtering


@dataclass
class MemoryResult:
    """Result of a memory search."""

    content: str
    score: float
    memory_id: int
    source: str  # 'semantic', 'keyword', or 'hybrid'
    age_days: float = 0


@dataclass
class MemoryMetadata:
    """Metadata for tracking memory importance over time."""

    memory_id: int
    access_count: int = 0
    last_accessed: float = 0.0  # timestamp
    boost_score: float = 0.0  # manual importance boost

    def calculate_importance(self, age_days: float) -> float:
        """
        Calculate combined importance score based on:
        - Access frequency (more access = more important)
        - Recency of last access
        - Time decay (natural aging)
        - Manual boost

        Returns value between 0.0 and 2.0
        """
        import math

        # Base time decay (half-life of 30 days)
        time_decay = 0.5 ** (age_days / 30.0)
        time_decay = max(0.1, time_decay)  # Minimum 10%

        # Access frequency boost (logarithmic)
        access_boost = 1.0 + (math.log(self.access_count + 1) * 0.1)
        access_boost = min(1.5, access_boost)  # Cap at 1.5x

        # Recency of last access boost
        if self.last_accessed > 0:
            days_since_access = (time.time() - self.last_accessed) / 86400
            recency_boost = 0.5 ** (days_since_access / 7.0)  # 7-day half-life
        else:
            recency_boost = 0.5

        # Combine factors
        importance = time_decay * access_boost * (1.0 + recency_boost * 0.3) + self.boost_score
        return min(2.0, max(0.0, importance))  # type: ignore[no-any-return]


class FAISSIndex:
    """FAISS index wrapper for efficient similarity search."""

    def __init__(self, dimension: int = EMBEDDING_DIM):
        self.dimension = dimension
        self.index: faiss.IndexFlatIP | None = None  # Inner product (cosine after norm)
        self.id_map: list[int] = []  # Maps index position to memory ID
        self._initialized = False
        self._lock = threading.Lock()  # Thread-safe lock for index modifications

    def build(self, vectors: np.ndarray, ids: list[int]) -> None:
        """Build index from vectors and their IDs."""
        if not FAISS_AVAILABLE or len(vectors) == 0:
            return

        # Normalize vectors for cosine similarity via inner product
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        normalized = vectors / norms

        with self._lock:
            # Create index (IndexFlatIP = flat inner product)
            self.index = faiss.IndexFlatIP(self.dimension)
            self.index.add(normalized.astype(np.float32))
            self.id_map = ids
            self._initialized = True
        logger.debug("🔍 Built FAISS index with %d vectors", len(ids))

    def search(self, query_vector: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
        """Search for k nearest neighbors. Returns list of (id, similarity).

        Note: This is a synchronous method. For async contexts, use search_async().
        """
        # Normalize query first (outside lock for performance)
        norm = np.linalg.norm(query_vector)
        if norm == 0:
            return []
        query_normalized = (query_vector / norm).reshape(1, -1).astype(np.float32)

        with self._lock:
            # Check initialization inside lock to avoid race condition
            if not self._initialized or self.index is None:
                return []

            # Search — guard against k=0 (FAISS may raise on empty queries)
            # and against an empty index.
            if self.index.ntotal == 0:
                return []
            k = min(k, self.index.ntotal)
            if k <= 0:
                return []
            similarities, indices = self.index.search(query_normalized, k)

            # Map indices back to memory IDs
            results = []
            for i, idx in enumerate(indices[0]):
                if idx >= 0 and idx < len(self.id_map):
                    results.append((self.id_map[idx], float(similarities[0][i])))

        return results

    async def search_async(self, query_vector: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
        """Async version of search that runs in executor to avoid blocking event loop."""
        return await asyncio.to_thread(self.search, query_vector, k)

    @property
    def is_initialized(self) -> bool:
        """Check if the index has been initialized."""
        return self._initialized

    def add_single(self, vector: np.ndarray, memory_id: int) -> None:
        """Add a single vector to the index."""
        # Validate dimension up front so a wrong-shape vector raises a clear
        # error instead of producing an opaque FAISS native crash later.
        if vector.size != self.dimension:
            raise ValueError(f"add_single: vector dim {vector.size} != index dim {self.dimension}")
        # Reject zero-norm vectors loudly. Silently skipping them used to
        # leave the DB row in place with no matching FAISS entry, which made
        # the memory unfindable on any future search.
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise ValueError(f"add_single: cannot add zero-norm vector for memory_id={memory_id}")
        with self._lock:
            normalized = (vector / norm).reshape(1, -1).astype(np.float32)
            if not self._initialized:
                # First vector - initialize index. Append to id_map BEFORE
                # the FAISS add so a MemoryError on append leaves the index
                # untouched. (FAISS.add can also fail; on either path the
                # invariant `index.ntotal == len(id_map)` must hold.)
                self.id_map = [memory_id]
                try:
                    self.index = faiss.IndexFlatIP(self.dimension)
                    self.index.add(normalized)
                except Exception:
                    self.id_map = []
                    self.index = None
                    raise
                self._initialized = True
            else:
                # Append to id_map first; if FAISS.add raises, roll the
                # id_map entry back so the lengths stay aligned.
                self.id_map.append(memory_id)
                try:
                    self.index.add(normalized)  # type: ignore[union-attr]
                except Exception:
                    self.id_map.pop()
                    raise

    def add_batch(self, vectors: list[np.ndarray], memory_ids: list[int]) -> int:
        """Add many vectors in a single lock acquisition.

        Used by reconcile paths where calling ``add_single`` per row would
        starve concurrent searches by holding the lock thousands of times.
        Returns the number of vectors actually added (skips wrong-dim and
        zero-norm entries).
        """
        if not vectors:
            return 0
        if len(vectors) != len(memory_ids):
            raise ValueError("add_batch: vectors and memory_ids length mismatch")

        # Validate + normalize outside the lock so search isn't blocked
        # during a multi-thousand-row reconcile.
        good_vecs: list[np.ndarray] = []
        good_ids: list[int] = []
        for vec, mem_id in zip(vectors, memory_ids, strict=True):
            if vec.size != self.dimension:
                continue
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            good_vecs.append((vec / norm).astype(np.float32))
            good_ids.append(mem_id)

        if not good_vecs:
            return 0

        stacked = np.vstack(good_vecs)
        with self._lock:
            if not self._initialized or self.index is None:
                self.index = faiss.IndexFlatIP(self.dimension)
                self.id_map = list(good_ids)
                try:
                    self.index.add(stacked)
                except Exception:
                    self.id_map = []
                    self.index = None
                    raise
                self._initialized = True
            else:
                prev_len = len(self.id_map)
                self.id_map.extend(good_ids)
                try:
                    self.index.add(stacked)
                except Exception:
                    # Roll the id_map back so ntotal == len(id_map) invariant holds.
                    del self.id_map[prev_len:]
                    raise
        return len(good_ids)

    def save_to_disk(self) -> bool:
        """Save FAISS index to disk for persistence.

        Uses atomic write pattern with transaction marker:
        1. Write to temp files
        2. Write completion marker
        3. Rename to final paths

        Each save also writes a per-save UUID into both the index sidecar
        AND the id_map sidecar. ``load_from_disk`` cross-validates: if
        the two UUIDs disagree, a torn save (crash between the two
        ``replace(...)`` calls) is detected even when row counts happen
        to coincide. Without the marker, an old id_map paired with a
        new same-length index silently returns wrong memory_ids.
        """
        if not self._initialized or not FAISS_AVAILABLE:
            return False

        with self._lock:
            try:
                FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

                # Atomic write pattern: write to temp, then rename
                temp_index = FAISS_INDEX_FILE.with_suffix(".tmp")
                temp_id_map = FAISS_ID_MAP_FILE.with_suffix(".tmp.json")
                transaction_marker = FAISS_INDEX_DIR / ".save_in_progress"
                # Save-pairing UUID: written next to BOTH artefacts so a
                # torn rename can be detected even when ntotal happens to
                # match the stale id_map.
                save_uuid_path = FAISS_INDEX_DIR / "save.uuid"
                temp_uuid = save_uuid_path.with_suffix(".tmp")
                save_uuid = uuid.uuid4().hex

                # Create transaction marker
                transaction_marker.write_text(str(time.time()), encoding="utf-8")

                # Write to temp files first; embed the UUID into the
                # id_map sidecar via JSON. The previous numpy-pickle format
                # (``np.save(... allow_pickle=True)`` + ``np.load(...
                # allow_pickle=True)``) was a pickle-deserialization vector:
                # anyone who could write to ``data/faiss`` could ship
                # arbitrary Python code that executed on the next save/load
                # cycle. JSON is bounded to data and removes that surface.
                faiss.write_index(self.index, str(temp_index))
                temp_id_map.write_text(
                    json.dumps(
                        {"save_uuid": save_uuid, "id_map": list(self.id_map)},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                temp_uuid.write_text(save_uuid, encoding="utf-8")

                # Both files written successfully - now rename atomically
                # Backup old files first (if they exist)
                backup_index = FAISS_INDEX_FILE.with_suffix(".bak")
                backup_id_map = FAISS_ID_MAP_FILE.with_suffix(".bak.json")
                backup_uuid = save_uuid_path.with_suffix(".bak")

                if FAISS_INDEX_FILE.exists():
                    FAISS_INDEX_FILE.replace(backup_index)
                if FAISS_ID_MAP_FILE.exists():
                    FAISS_ID_MAP_FILE.replace(backup_id_map)
                if save_uuid_path.exists():
                    save_uuid_path.replace(backup_uuid)

                # Rename temp to final
                temp_index.replace(FAISS_INDEX_FILE)
                temp_id_map.replace(FAISS_ID_MAP_FILE)
                temp_uuid.replace(save_uuid_path)

                # Remove transaction marker and backups on success
                transaction_marker.unlink(missing_ok=True)
                backup_index.unlink(missing_ok=True)
                backup_id_map.unlink(missing_ok=True)
                backup_uuid.unlink(missing_ok=True)
                # Remove the legacy pickled .npy now that we successfully
                # wrote the JSON sidecar; one migration is enough.
                _LEGACY_FAISS_ID_MAP_FILE.unlink(missing_ok=True)

                logger.info("💾 Saved FAISS index to disk (%d vectors)", len(self.id_map))
                return True
            except Exception:
                logger.exception("Failed to save FAISS index")
                # Clean up temp files on failure
                for temp_file in [
                    FAISS_INDEX_FILE.with_suffix(".tmp"),
                    FAISS_ID_MAP_FILE.with_suffix(".tmp.json"),
                    (FAISS_INDEX_DIR / "save.uuid").with_suffix(".tmp"),
                    FAISS_INDEX_DIR / ".save_in_progress",
                ]:
                    try:
                        if temp_file.exists():
                            temp_file.unlink()
                    except Exception as cleanup_error:
                        logger.debug("Failed to cleanup temp file %s: %s", temp_file, cleanup_error)
                return False

    def load_from_disk(self) -> bool:
        """Load FAISS index from disk."""
        if not FAISS_AVAILABLE:
            return False

        # Recovery: check for backup files from interrupted save
        backup_index = FAISS_INDEX_FILE.with_suffix(".bak")
        backup_id_map = FAISS_ID_MAP_FILE.with_suffix(".bak.json")
        save_uuid_path = FAISS_INDEX_DIR / "save.uuid"
        backup_uuid = save_uuid_path.with_suffix(".bak")
        if not FAISS_INDEX_FILE.exists() and backup_index.exists():
            logger.warning("🔄 Recovering FAISS index from backup (interrupted save detected)")
            try:
                backup_index.replace(FAISS_INDEX_FILE)
                if backup_id_map.exists():
                    backup_id_map.replace(FAISS_ID_MAP_FILE)
                if backup_uuid.exists():
                    backup_uuid.replace(save_uuid_path)
            except OSError:
                logger.exception("Failed to recover FAISS backup")

        # Pick the freshest id_map source: prefer the canonical JSON, but
        # fall back to the legacy ``.npy`` (pickle) one cycle so existing
        # deployments migrate transparently. The legacy file is deleted on
        # the next successful save.
        id_map_path: Path | None = None
        legacy_pickle_load = False
        if FAISS_ID_MAP_FILE.exists():
            id_map_path = FAISS_ID_MAP_FILE
        elif _LEGACY_FAISS_ID_MAP_FILE.exists():
            if os.getenv("RAG_ALLOW_LEGACY_PICKLE", "").strip().lower() not in ("1", "true", "yes"):
                logger.error(
                    "🚫 Legacy FAISS id_map .npy detected but RAG_ALLOW_LEGACY_PICKLE not set. "
                    "Refusing to deserialize untrusted pickle. "
                    "Delete %s to force a rebuild, or set RAG_ALLOW_LEGACY_PICKLE=1 if you trust the file.",
                    _LEGACY_FAISS_ID_MAP_FILE,
                )
                return False
            id_map_path = _LEGACY_FAISS_ID_MAP_FILE
            legacy_pickle_load = True
            logger.warning(
                "🔄 Loading FAISS id_map from legacy .npy (pickle) — RAG_ALLOW_LEGACY_PICKLE opt-in. "
                "It will be rewritten as JSON on the next save."
            )

        if not FAISS_INDEX_FILE.exists() or id_map_path is None:
            return False

        try:
            self.index = faiss.read_index(str(FAISS_INDEX_FILE))
            id_map_uuid: str | None = None
            if legacy_pickle_load:
                # ``allow_pickle=True`` is the deserialization vector we are
                # migrating AWAY from. Keep it gated to the one-time legacy
                # path; new saves use JSON. The FAISS dir is already a
                # private bot data directory, but pickle on any file an
                # operator could touch is still a needless RCE surface.
                raw_id_map = np.load(str(id_map_path), allow_pickle=True)
                try:
                    payload = raw_id_map.item()
                except (ValueError, AttributeError):
                    payload = None
                if isinstance(payload, dict) and "id_map" in payload:
                    self.id_map = list(payload["id_map"])
                    id_map_uuid = payload.get("save_uuid")
                else:
                    self.id_map = raw_id_map.tolist()
            else:
                try:
                    payload = json.loads(id_map_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    logger.exception("Failed to parse FAISS id_map JSON")
                    return False
                if isinstance(payload, dict) and isinstance(payload.get("id_map"), list):
                    self.id_map = list(payload["id_map"])
                    raw_uuid = payload.get("save_uuid")
                    id_map_uuid = raw_uuid if isinstance(raw_uuid, str) else None
                elif isinstance(payload, list):
                    self.id_map = list(payload)
                else:
                    logger.error("FAISS id_map JSON has unexpected shape — rebuilding")
                    return False

            # Cross-check the per-save UUID. If the index file was
            # renamed but the id_map rename didn't complete (or vice
            # versa), the sidecar UUID will mismatch even when ntotal
            # happens to coincide with len(id_map). The marker is the
            # only way to catch that class of corruption.
            on_disk_uuid: str | None = None
            if save_uuid_path.exists():
                try:
                    on_disk_uuid = save_uuid_path.read_text(encoding="utf-8").strip() or None
                except OSError:
                    on_disk_uuid = None
            if id_map_uuid is not None and on_disk_uuid is not None and id_map_uuid != on_disk_uuid:
                logger.error(
                    "🔥 FAISS save UUID mismatch (id_map=%s, sidecar=%s) — "
                    "torn save detected; discarding on-disk state and rebuilding",
                    id_map_uuid,
                    on_disk_uuid,
                )
                self.index = None
                self.id_map = []
                return False

            # Validate length match — a partial-rename crash between
            # save_to_disk's two ``temp_*.replace(...)`` calls leaves a new
            # index pointing at an old id_map (or vice versa). Detecting
            # this here forces a rebuild instead of silently returning
            # wrong memory ids on every future search.
            if self.index.ntotal != len(self.id_map):
                logger.error(
                    "🔥 FAISS index/id_map length mismatch (%d vs %d) — "
                    "discarding on-disk state and rebuilding from DB",
                    self.index.ntotal,
                    len(self.id_map),
                )
                self.index = None
                self.id_map = []
                return False
            self._initialized = True
            logger.info("📂 Loaded FAISS index from disk (%d vectors)", len(self.id_map))
            return True
        except Exception:
            logger.exception("Failed to load FAISS index")
            return False


class MemorySystem:
    """
    Manages RAG operations: embedding generation, storage, and retrieval.

    Enhanced Features:
    - Hybrid search (semantic + keyword)
    - Reciprocal Rank Fusion for merging results
    - Time decay for older memories
    - Importance scoring
    - Debounced FAISS index persistence
    """

    # Maximum cache size to prevent unbounded memory growth
    MAX_CACHE_SIZE = 10000

    # Per-channel snapshot of `get_all_rag_memories(channel_id)` so a
    # busy channel doesn't re-pull the entire table on every hybrid
    # search. The TTL is short enough that newly stored facts surface
    # in the next query without operator action.
    _ALL_MEMORIES_TTL_SECONDS = 30.0
    # Bound the per-channel snapshot cache (each value can hold thousands of
    # rows) so a bot spanning many guilds doesn't retain them all forever.
    _ALL_MEMORIES_MAX_CHANNELS = 256

    def __init__(self):
        self.client = None
        self._faiss_index: FAISSIndex | None = None
        self._index_built = False
        self._memories_cache: dict[int, dict] = {}  # id -> memory dict
        # channel_id -> (expiry_monotonic, rows)
        self._all_memories_cache: dict[int, tuple[float, list[Any]]] = {}

        # Debounced save state
        self._save_task: asyncio.Task | None = None
        self._periodic_save_task: asyncio.Task | None = None

        # Lock for index building to prevent race conditions
        self._index_lock = asyncio.Lock()

        # Skip Gemini client init under CLAUDE_BACKEND=cli. Gemini is
        # paid-API-only; with the client unset, ``generate_embedding``
        # returns None and ``hybrid_search`` falls through to its
        # keyword-only path. New memories can still be stored — they
        # just won't get a vector and won't show up in semantic search
        # until the user re-enables CLAUDE_BACKEND=api.
        if os.getenv("CLAUDE_BACKEND", "cli").strip().lower() == "cli":
            logger.info(
                "🚫 RAG embedding (Gemini) disabled (CLAUDE_BACKEND=cli) — "
                "hybrid search degrades to keyword-only; new memories "
                "won't be vector-indexed."
            )
        elif GEMINI_API_KEY and _GENAI_AVAILABLE:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
            except Exception:
                logger.exception("Failed to init Gemini Client for RAG")
        elif GEMINI_API_KEY and not _GENAI_AVAILABLE:
            logger.warning(
                "GEMINI_API_KEY is set but google-genai is not installed; "
                "RAG embeddings will be disabled."
            )

    def _evict_cache_if_needed(self) -> None:
        """Evict oldest entries from cache if over MAX_CACHE_SIZE."""
        if len(self._memories_cache) < self.MAX_CACHE_SIZE:
            return

        # Sort by created_at (oldest first) and evict 10% of max size
        evict_count = max(1, self.MAX_CACHE_SIZE // 10)
        # Snapshot keys to avoid RuntimeError from concurrent modification
        snapshot = list(self._memories_cache.items())
        # Coerce created_at to str so a mix of str (ISO timestamps) and int
        # (legacy epoch values) doesn't raise TypeError on comparison.
        snapshot.sort(key=lambda pair: str(pair[1].get("created_at") or ""))
        for mem_id, _ in snapshot[:evict_count]:
            self._memories_cache.pop(mem_id, None)
        logger.debug("🗑️ Evicted %d old entries from RAG cache", evict_count)

    def get_stats(self) -> dict:
        """Get RAG system statistics."""
        return {
            "faiss_available": FAISS_AVAILABLE,
            "index_built": self._index_built,
            "memories_cached": len(self._memories_cache),
            "index_size": len(self._faiss_index.id_map) if self._faiss_index else 0,
            "client_ready": self.client is not None,
        }

    async def _get_all_memories_cached(self, channel_id: int | None) -> list[Any]:
        """Return ``get_all_rag_memories(channel_id)`` with a TTL cache.

        Hot channels were re-fetching every memory row on every search
        before — even back-to-back queries pulled the same 10K rows. The
        TTL is short enough that newly-stored memories show up in the
        next query without operator action.

        ``channel_id=None`` skips the cache because that path crosses
        every channel and a single shared snapshot would let one channel
        starve out fresh reads for all the others.
        """
        now = time.monotonic()
        if channel_id is not None:
            cached = self._all_memories_cache.get(channel_id)
            if cached is not None and cached[0] > now:
                # Return a SHALLOW COPY of the cached list so callers
                # that mutate the result (filter/sort in place) don't
                # corrupt the cache for the next reader. The previous
                # shape returned the live cache list and a single
                # in-place ``.sort()`` would persist into every future
                # cache hit.
                return list(cached[1])

        try:
            rows = await asyncio.wait_for(
                db.get_all_rag_memories(channel_id), timeout=_DB_QUERY_TIMEOUT
            )
        except TimeoutError:
            logger.warning("⏱️ RAG hybrid_search DB query timed out after %ds", _DB_QUERY_TIMEOUT)
            return []
        rows = list(rows or [])
        if channel_id is not None:
            self._all_memories_cache[channel_id] = (now + self._ALL_MEMORIES_TTL_SECONDS, rows)
            self._evict_all_memories_cache_if_needed(now)
        # Same defensive copy on cache-miss return so callers can mutate
        # freely without aliasing into the cache.
        return list(rows)

    def invalidate_all_memories_cache(self, channel_id: int | None = None) -> None:
        """Drop the cached `get_all_rag_memories` snapshot.

        Called after a write so the next read picks up new rows
        immediately rather than waiting for the TTL to expire.
        """
        if channel_id is None:
            self._all_memories_cache.clear()
        else:
            self._all_memories_cache.pop(channel_id, None)

    def _evict_all_memories_cache_if_needed(self, now: float) -> None:
        """Bound the per-channel snapshot cache.

        Each value can hold thousands of memory rows, so an unbounded dict
        keyed by every channel ever searched leaks memory in a bot spanning
        many guilds. Drop expired entries first, then evict the entries
        expiring soonest until back under the cap.
        """
        cache = self._all_memories_cache
        if len(cache) <= self._ALL_MEMORIES_MAX_CHANNELS:
            return
        for cid in [c for c, (exp, _rows) in cache.items() if exp <= now]:
            cache.pop(cid, None)
        while len(cache) > self._ALL_MEMORIES_MAX_CHANNELS:
            oldest = min(cache, key=lambda c: cache[c][0])
            cache.pop(oldest, None)

    async def generate_embedding(self, text: str) -> np.ndarray | None:
        """Generate vector embedding for text using Gemini API."""
        if not self.client:
            return None
        # Skip empty / whitespace-only payloads — they always yield a useless
        # near-zero vector but still cost an API call against the embedding
        # quota. Cheap guard up front saves quota on long-tail noisy inputs.
        if not text or not text.strip():
            return None

        try:
            result = await self.client.aio.models.embed_content(
                model=EMBEDDING_MODEL, contents=text
            )

            # Validate the embedding shape before indexing — the API may
            # return an empty list, an embedding object with no .values,
            # or a vector whose length differs from EMBEDDING_DIM (model
            # change, partial response). Any of those used to either
            # IndexError or silently corrupt the FAISS index.
            embeddings = getattr(result, "embeddings", None)
            if not embeddings:
                logger.warning("Embedding API returned no embeddings")
                return None
            values = getattr(embeddings[0], "values", None)
            if not values:
                return None
            vec = np.array(values, dtype=np.float32)
            if vec.size != EMBEDDING_DIM:
                logger.warning(
                    "Embedding dim mismatch: expected %d, got %d (model %s)",
                    EMBEDDING_DIM,
                    vec.size,
                    EMBEDDING_MODEL,
                )
                return None
            return vec
        except Exception:
            logger.exception("Embedding generation failed")
            return None

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 10
    ) -> list[np.ndarray | None]:
        """
        Generate embeddings for multiple texts in batches.
        More efficient than generating one at a time.

        Each batch is capped to ``batch_size`` concurrent in-flight requests
        via a semaphore so a caller passing batch_size=1000 can't fan out
        1000 simultaneous API calls and trigger 429s / IP bans.
        """
        if not self.client or not texts:
            return [None] * len(texts)

        results: list[np.ndarray | None] = []
        # Hard ceiling on concurrency regardless of batch_size — Gemini's
        # default rate limits get unhappy past ~30 concurrent calls.
        concurrency_limit = min(max(1, batch_size), 16)
        sem = asyncio.Semaphore(concurrency_limit)

        async def _embed_one(text: str):
            async with sem:
                return await self.client.aio.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=text,
                )

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Pre-filter empty/whitespace entries — they always yield useless
            # near-zero vectors but still cost an API call. Single-text guard
            # in generate_embedding() does the same; mirror it here so batch
            # callers don't burn quota on noise.
            send_indices = [j for j, t in enumerate(batch) if t and t.strip()]
            if not send_indices:
                results.extend([None] * len(batch))
                continue
            send_texts = [batch[j] for j in send_indices]
            try:
                # Process batch concurrently — semaphore caps inflight.
                tasks = [_embed_one(text) for text in send_texts]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Re-expand results to match original batch shape; positions
                # whose text was empty stay None.
                expanded: list[np.ndarray | None] = [None] * len(batch)
                for src_idx, result in zip(send_indices, batch_results, strict=False):
                    if isinstance(result, Exception):
                        expanded[src_idx] = None
                        continue
                    embs = getattr(result, "embeddings", None)
                    if not embs:
                        expanded[src_idx] = None
                        continue
                    values = getattr(embs[0], "values", None)
                    # Mirror the single-item `generate_embedding` guards: a
                    # `None` or wrong-dimensionality vector silently corrupts
                    # the FAISS index when added later.
                    if not values:
                        expanded[src_idx] = None
                        continue
                    expanded[src_idx] = np.array(values, dtype=np.float32)
                results.extend(expanded)

            except Exception:
                logger.exception("Batch embedding failed")
                results.extend([None] * len(batch))

        return results

    async def _ensure_index(self, channel_id: int | None = None) -> None:
        """Build FAISS index from database if not already built.

        Uses lock to prevent race conditions from concurrent calls.
        """
        if not FAISS_AVAILABLE or self._index_built:
            return

        # Use lock to prevent multiple concurrent index builds
        async with self._index_lock:
            # Double-check after acquiring lock (another task may have built it)
            if self._index_built:
                return

            # Try to load from disk first (fast path)
            if self._faiss_index is None:
                self._faiss_index = FAISSIndex(EMBEDDING_DIM)
                if self._faiss_index.load_from_disk():
                    self._index_built = True
                    # Load memories cache from DB. Cap to MAX_CACHE_SIZE
                    # so a multi-million-row table doesn't OOM startup —
                    # entries beyond the cap get pulled lazily on demand.
                    if _DB_AVAILABLE and db is not None:
                        try:
                            all_memories = await asyncio.wait_for(
                                db.get_all_rag_memories(None),
                                timeout=_DB_QUERY_TIMEOUT,
                            )
                        except TimeoutError:
                            # FAISS already loaded from disk — _index_built stays True.
                            # Cache stays cold; lazy-load fills it on first hit.
                            logger.warning(
                                "RAG cache eager-load timed out; falling back to lazy population"
                            )
                            return
                        eager_load_cap = max(self.MAX_CACHE_SIZE, 1000)
                        for mem in all_memories[:eager_load_cap]:
                            mem_id = mem.get("id")
                            if mem_id:
                                self._memories_cache[mem_id] = mem
                        if len(all_memories) > eager_load_cap:
                            logger.info(
                                "RAG cache eager-load capped at %d entries "
                                "(table has %d). Remainder loaded lazily.",
                                eager_load_cap,
                                len(all_memories),
                            )
                        self._evict_cache_if_needed()

                        # Reconcile DB rows that are absent from the on-disk FAISS
                        # index — happens when add_memory ran between the last
                        # periodic save and a restart/crash. Without this, those
                        # rows live in DB forever but are unreachable via search.
                        # Run the per-vector add in a thread so we don't pin the
                        # event loop on a large reconcile (100k orphans times
                        # locked add_single previously blocked for seconds).
                        # Capture a non-None local so the worker thread doesn't
                        # have to re-narrow self._faiss_index, and to defend
                        # against an unrelated reset clearing the attribute
                        # mid-reconcile.
                        faiss_index = self._faiss_index
                        existing_ids = set(faiss_index.id_map)

                        def _reconcile_sync() -> int:
                            # Collect all orphan vectors first WITHOUT touching
                            # the FAISS lock. Then add them all in one batch
                            # so search threads only see a single brief lock
                            # hold instead of N per-row holds.
                            orphan_vecs: list[np.ndarray] = []
                            orphan_ids: list[int] = []
                            for mem in all_memories:
                                mem_id = mem.get("id")
                                if mem_id is None or mem_id in existing_ids:
                                    continue
                                try:
                                    vec = np.frombuffer(mem["embedding"], dtype=np.float32)
                                except (ValueError, TypeError, KeyError) as e:
                                    logger.debug("Skipping unreconcilable memory %s: %s", mem_id, e)
                                    continue
                                orphan_vecs.append(vec)
                                orphan_ids.append(mem_id)
                            if not orphan_vecs:
                                return 0
                            try:
                                return faiss_index.add_batch(orphan_vecs, orphan_ids)
                            except Exception:
                                logger.exception("FAISS batch reconcile failed")
                                return 0

                        reconciled = await asyncio.to_thread(_reconcile_sync)
                        if reconciled:
                            logger.info(
                                "🔧 Reconciled %d RAG memories that were in DB "
                                "but missing from FAISS",
                                reconciled,
                            )
                            # Persist the reconciled state so we don't redo this
                            # work on the next restart.
                            self._schedule_index_save()
                    return

            # Build from database (slow path)
            # Load ALL memories (not just one channel) since FAISS index is global
            if not _DB_AVAILABLE or db is None:
                # Mark the index as "built" with whatever empty/in-memory
                # state we have so the next ``_ensure_index`` call
                # doesn't re-enter this branch on every search. Without
                # this flag flip, every single hybrid_search call
                # re-acquired the lock + re-checked DB availability,
                # busy-looping the lock at search rate.
                self._index_built = True
                return

            try:
                all_memories = await asyncio.wait_for(
                    db.get_all_rag_memories(None), timeout=_DB_QUERY_TIMEOUT
                )
            except TimeoutError:
                # Mark as "built" with empty state so we don't re-enter this
                # branch on every search and re-time-out. The next periodic
                # rebuild (or an explicit ``_invalidate_index``) gets us back.
                logger.warning(
                    "RAG full-rebuild DB query timed out; marking index as built-empty"
                )
                self._index_built = True
                return
            if not all_memories:
                # Same flag flip — empty DB is a valid "built" state.
                self._index_built = True
                return

            if len(all_memories) > MAX_RAG_REBUILD:
                logger.warning(
                    "RAG rebuild capped: %d rows in DB, only loading first %d",
                    len(all_memories),
                    MAX_RAG_REBUILD,
                )
                all_memories = all_memories[:MAX_RAG_REBUILD]

            vectors = []
            ids: list[Any] = []

            for mem in all_memories:
                try:
                    vec = np.frombuffer(mem["embedding"], dtype=np.float32)
                    if len(vec) != EMBEDDING_DIM:
                        continue
                    mem_id = mem.get("id")
                    if mem_id is None:
                        # Skip rows without an id — falling back to len(ids) here
                        # would collide with real auto-increment ids and route
                        # search hits to the wrong memory. hybrid_search already
                        # uses the same skip-on-missing-id guard.
                        continue
                    vectors.append(vec)
                    ids.append(mem_id)
                    self._memories_cache[mem_id] = mem
                except (ValueError, TypeError, KeyError) as e:
                    logger.debug("Skipping invalid memory embedding: %s", e)
                    continue

            if vectors:
                self._faiss_index = FAISSIndex(EMBEDDING_DIM)
                self._faiss_index.build(np.array(vectors), ids)
                self._index_built = True
                # Save to disk for next restart
                self._faiss_index.save_to_disk()
                self._evict_cache_if_needed()
                logger.info("🚀 FAISS index built with %d memories", len(vectors))

    def _schedule_index_save(self, delay: float = 30.0) -> None:
        """Schedule a debounced save of FAISS index (non-blocking)."""
        # Cancel any existing save task before creating a new one
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()

        async def do_save():
            try:
                await asyncio.sleep(delay)
                if self._faiss_index and self._index_built:
                    # Run the synchronous save on a worker thread —
                    # ``save_to_disk`` calls ``faiss.write_index`` and
                    # ``np.save`` which can block the event loop for
                    # 100-500ms on large indices.
                    await asyncio.to_thread(self._faiss_index.save_to_disk)
            except asyncio.CancelledError:
                raise  # Re-raise to properly handle cancellation

        self._save_task = asyncio.create_task(do_save())

    def start_periodic_save(self, interval: float = 300.0) -> None:
        """Start background task to save FAISS index periodically (every 5 min)."""

        async def save_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    if self._faiss_index and self._index_built:
                        await asyncio.to_thread(self._faiss_index.save_to_disk)
                except asyncio.CancelledError:
                    # Task was cancelled, exit gracefully
                    break
                except Exception:
                    logger.exception("❌ Error in periodic FAISS save")
                    # Continue running to try again next interval

        if self._periodic_save_task is None or self._periodic_save_task.done():
            self._periodic_save_task = asyncio.create_task(save_loop())
            logger.info("🔄 Started periodic FAISS save task (every %.0fs)", interval)

    async def stop_periodic_save(self) -> None:
        """Stop the periodic save task (async to properly await cancellation)."""
        # Cancel the debounced save task
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._save_task
            self._save_task = None

        # Cancel the periodic save task
        if self._periodic_save_task and not self._periodic_save_task.done():
            self._periodic_save_task.cancel()
            # Properly await the cancelled task to avoid 'Task was destroyed' warning
            try:
                await self._periodic_save_task
            except asyncio.CancelledError:
                pass  # Expected when cancelling
            self._periodic_save_task = None

    async def force_save_index(self) -> bool:
        """Force immediate save of FAISS index (useful for shutdown)."""
        if self._faiss_index and self._index_built:
            return await asyncio.to_thread(self._faiss_index.save_to_disk)
        return False

    async def add_memory(self, content: str, channel_id: int | None = None) -> bool:
        """Add a text chunk to long-term memory."""
        if not _DB_AVAILABLE or db is None:
            logger.warning("Database not available for RAG add_memory")
            return False

        embedding = await self.generate_embedding(content)
        if embedding is None:
            return False

        # Validate the embedding BEFORE writing to DB so a wrong-shape or
        # zero-norm vector doesn't produce a permanent DB orphan that fails
        # to re-index on every subsequent rebuild.
        if embedding.size != EMBEDDING_DIM:
            logger.warning(
                "add_memory: embedding dim %d != expected %d — refusing to save",
                embedding.size,
                EMBEDDING_DIM,
            )
            return False
        if float(np.linalg.norm(embedding)) == 0.0:
            logger.warning("add_memory: embedding is zero-norm — refusing to save")
            return False

        embedding_bytes = embedding.tobytes()

        # DB save is the slow op (sqlite WAL fsync); run it WITHOUT the
        # index lock so concurrent search/_ensure_index calls aren't
        # blocked by disk I/O. Then take the lock for the brief FAISS
        # update.
        #
        # Race note: a concurrent ``_ensure_index`` rebuild can run
        # between the DB save and the FAISS add. That's safe because
        # ``_ensure_index`` reads ALL rows from the DB — the just-saved
        # row will be included, so the rebuild picks it up. The
        # FAISS add below would then add a duplicate entry. ``add_single``
        # does NOT dedupe (it unconditionally appends to keep the
        # ``ntotal == len(id_map)`` invariant cheap), so the dup persists
        # until the next full rebuild — at worst a memory ranks via two FAISS
        # hits, which the RRF merge + result cap make benign. (The previous
        # "hold lock across both" shape blocked search for the entire DB write
        # window — that consistency win wasn't worth the latency hit.)
        result = await db.save_rag_memory(
            content=content, embedding_bytes=embedding_bytes, channel_id=channel_id
        )

        async with self._index_lock:
            if FAISS_AVAILABLE and self._faiss_index and self._index_built:
                memory_id = result if isinstance(result, int) and result > 0 else None
                if memory_id is not None:
                    try:
                        self._faiss_index.add_single(embedding, memory_id)
                        # Schedule debounced save instead of saving immediately (performance)
                        self._schedule_index_save()
                    except (ValueError, RuntimeError) as e:
                        # FAISS rejected the vector (e.g. zero-norm, wrong dim).
                        # The DB row is already committed; mark the index as
                        # un-built so the next _ensure_index call rebuilds from
                        # DB and picks up this orphan. Without this it would
                        # remain unreachable to search forever.
                        logger.warning(
                            "FAISS add_single failed for memory %s: %s "
                            "(scheduling rebuild on next access)",
                            memory_id,
                            e,
                        )
                        self._index_built = False
                else:
                    logger.warning("⚠️ RAG memory saved to DB but got invalid ID: %s", result)

        # Drop the cached snapshot so the next hybrid_search picks up
        # this row instead of waiting for the TTL.
        if channel_id is not None:
            self.invalidate_all_memories_cache(channel_id)

        logger.info("🧠 Saved RAG memory: %s...", content[:30])
        return True

    def _calculate_time_decay(self, created_at_str: str) -> float:
        """
        Calculate time decay factor for a memory.
        Returns value between 0 and 1, where 1 is most recent.
        """
        try:
            created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            # Always use timezone.utc for consistent comparison, avoiding timezone issues
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_days = (now - created).total_seconds() / 86400

            # Exponential decay with half-life
            decay = 0.5 ** (age_days / TIME_DECAY_HALF_LIFE_DAYS)
            return max(0.1, decay)  # type: ignore[no-any-return]
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug("Time decay calculation failed: %s", e)
            return 1.0  # Default to full weight on error

    def expand_query(self, query: str) -> str:
        """
        Expand query with synonyms for better search coverage.
        Supports Thai and English terms.
        """
        # Synonym mappings for common terms
        synonyms = {
            # Thai synonyms
            "ชื่อ": ["นาม", "ชื่อเล่น", "name"],
            "อายุ": ["วัย", "อายุปี", "age"],
            "บ้าน": ["ที่อยู่", "ที่พัก", "home", "house"],
            "งาน": ["อาชีพ", "ทำงาน", "work", "job"],
            "ชอบ": ["รัก", "โปรด", "like", "love"],
            "เกลียด": ["ไม่ชอบ", "hate", "dislike"],
            "เพื่อน": ["มิตร", "friend"],
            "ครอบครัว": ["พ่อแม่", "พี่น้อง", "family"],
            # English synonyms
            "name": ["ชื่อ", "called"],
            "age": ["อายุ", "years old"],
            "home": ["บ้าน", "house", "address"],
            "work": ["งาน", "job", "occupation"],
            "like": ["ชอบ", "love", "enjoy"],
            "friend": ["เพื่อน", "buddy"],
        }

        query_lower = query.lower()
        expanded_terms = [query]

        for term, related in synonyms.items():
            if term in query_lower:
                # Add first 2 synonyms to avoid over-expansion
                expanded_terms.extend(related[:2])

        # Return unique terms joined
        unique_terms = list(dict.fromkeys(expanded_terms))
        return " ".join(unique_terms[:5])  # Limit expansion

    def _keyword_search(
        self, query: str, memories: list[dict], limit: int = 10
    ) -> list[tuple[int, float]]:
        """
        Perform keyword-based search on memories.
        Returns list of (memory_id, score).
        """
        # Tokenize query
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return []

        scored = []
        for mem in memories:
            content = (mem.get("content") or "").lower()
            content_tokens = set(re.findall(r"\w+", content))

            if not content_tokens:
                continue

            # Calculate Jaccard similarity
            intersection = len(query_tokens & content_tokens)
            union = len(query_tokens | content_tokens)

            if union > 0:
                jaccard = intersection / union

                # Boost for exact phrase matches
                if query.lower() in content:
                    jaccard += 0.3

                if jaccard > 0:
                    # Skip rows with a missing id — using -1 as a fallback key
                    # would collide every unknown row into one bucket and the
                    # subsequent merge could pick the wrong content.
                    mem_id = mem.get("id")
                    if mem_id is None or mem_id == -1:
                        continue
                    scored.append((mem_id, jaccard))

        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _reciprocal_rank_fusion(
        self,
        semantic_results: list[tuple[int, float]],
        keyword_results: list[tuple[int, float]],
        k: int = 60,
        semantic_weight: float = 1.0,
        keyword_weight: float = 1.0,
    ) -> list[tuple[int, float]]:
        """
        Merge results from semantic and keyword search using weighted RRF.
        Returns list of (memory_id, combined_score).

        ``semantic_weight`` / ``keyword_weight`` scale each source's
        contribution; default 1.0/1.0 is plain RRF.
        """
        rrf_scores: dict[int, float] = {}

        # Process semantic results
        for rank, (mem_id, _) in enumerate(semantic_results):
            rrf_scores[mem_id] = rrf_scores.get(mem_id, 0) + semantic_weight / (k + rank + 1)

        # Process keyword results
        for rank, (mem_id, _) in enumerate(keyword_results):
            rrf_scores[mem_id] = rrf_scores.get(mem_id, 0) + keyword_weight / (k + rank + 1)

        # Sort by combined score
        results = list(rrf_scores.items())
        results.sort(key=lambda x: x[1], reverse=True)

        return results

    async def hybrid_search(
        self,
        query: str,
        limit: int = 15,  # Increased for 2M context
        channel_id: int | None = None,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        use_time_decay: bool = True,
    ) -> list[MemoryResult]:
        """
        Perform hybrid search combining semantic and keyword search.

        Args:
            query: Search query
            limit: Maximum results to return
            channel_id: Optional channel filter
            semantic_weight: Weight for semantic results (0-1)
            keyword_weight: Weight for keyword results (0-1)
            use_time_decay: Whether to apply time decay

        Returns:
            List of MemoryResult objects
        """
        if not _DB_AVAILABLE or db is None:
            return []

        # Get all memories for keyword search. Cached per-channel with
        # a short TTL — a chatty channel was previously re-pulling the
        # entire RAG table on every query, which dominated the search
        # path for high-memory channels.
        all_memories = await self._get_all_memories_cached(channel_id)
        if not all_memories:
            return []

        # Update cache (batch with size limit to prevent memory spike).
        # Skip rows with a missing id — using -1 as a fallback key would
        # collapse multiple anonymous rows onto the same slot and silently
        # overwrite each other.
        MAX_CACHE_BATCH = 500
        for mem in all_memories[:MAX_CACHE_BATCH]:
            mem_id = mem.get("id")
            if mem_id is None:
                continue
            self._memories_cache[mem_id] = mem
        # Evict AFTER the bulk insert — the previous order let a steady
        # stream of queries keep the cache permanently above the cap by
        # always inserting more than was reclaimed.
        self._evict_cache_if_needed()

        # Semantic search
        semantic_results = []
        query_vec = await self.generate_embedding(query)

        if query_vec is not None:
            if FAISS_AVAILABLE:
                await self._ensure_index(channel_id)
                if self._faiss_index and self._faiss_index.is_initialized:
                    # Request extra results to compensate for possible cache misses
                    # (FAISS index may contain IDs evicted from _memories_cache)
                    semantic_results = await self._faiss_index.search_async(query_vec, k=limit * 3)

            # Fallback to linear if FAISS unavailable or not built
            if not semantic_results:
                semantic_results = await self._linear_search_raw(query_vec, limit * 2, all_memories)

        # Build a channel-local id→row map from all_memories (every row for
        # this channel — the query has no LIMIT). Used to (1) scope semantic
        # hits to this channel and (2) resolve result rows that fell outside
        # the 500-row _memories_cache batch below.
        _chan_by_id = {m.get("id"): m for m in all_memories if m.get("id") is not None}

        # Scope semantic hits to THIS channel. The FAISS index is global
        # (built from get_all_rag_memories(None)), so search_async can return
        # IDs belonging to OTHER channels — a cross-channel memory leak. The
        # keyword and linear paths already operate on the channel-filtered
        # all_memories; mirror that here. channel_id is None means an
        # intentional cross-channel search — skip the filter.
        if semantic_results and channel_id is not None:
            semantic_results = [
                (mid, score) for (mid, score) in semantic_results if mid in _chan_by_id
            ]

        # Keyword search
        keyword_results = self._keyword_search(query, all_memories, limit * 2)

        # Merge using RRF, honouring caller-supplied weights so a
        # `semantic_weight=0.9` actually emphasises semantic ranking
        # rather than silently producing the same result as 0.5/0.5.
        if semantic_results and keyword_results:
            merged = self._reciprocal_rank_fusion(
                semantic_results,
                keyword_results,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
            )
            source = "hybrid"
        elif semantic_results:
            merged = semantic_results
            source = "semantic"
        elif keyword_results:
            merged = keyword_results
            source = "keyword"
        else:
            return []

        # Build final results
        results: list[MemoryResult] = []
        for mem_id, score in merged:
            if len(results) >= limit:
                break

            # Resolve from the global LRU cache first, then fall back to the
            # full channel snapshot — a FAISS/keyword hit whose row sat beyond
            # the 500-row _memories_cache batch above would otherwise be
            # silently dropped from the results.
            mem = self._memories_cache.get(mem_id) or _chan_by_id.get(mem_id)
            if not mem:
                continue

            # Apply time decay
            final_score = score
            age_days = 0
            if use_time_decay:
                created_at = mem.get("created_at", "")
                decay = self._calculate_time_decay(created_at)
                final_score *= decay
                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    # Coerce naive timestamps (legacy rows written before
                    # the tz-aware migration) to UTC so we don't raise
                    # TypeError on `now - created` and silently lose age.
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    now = datetime.now(created.tzinfo)
                    age_days = (now - created).days
                except (ValueError, TypeError, AttributeError):
                    pass  # Invalid or missing datetime format

            results.append(
                MemoryResult(
                    # Use ``.get`` with an empty-string default so a row
                    # missing the ``content`` key (e.g. a corrupted historic
                    # record) doesn't raise KeyError and abort the entire
                    # hybrid-search response.
                    content=mem.get("content", ""),
                    score=final_score,
                    memory_id=mem_id,
                    source=source,
                    age_days=age_days,
                )
            )

        # Sort by final score
        results.sort(key=lambda x: x.score, reverse=True)

        if results:
            logger.info("🧠 Hybrid search found %d memories (source: %s)", len(results), source)

        return results

    async def search_memory(
        self, query: str, limit: int = 3, channel_id: int | None = None
    ) -> list[str]:
        """
        Search for relevant memories (backwards compatible API).
        Uses hybrid search internally.
        """
        results = await self.hybrid_search(query, limit, channel_id)
        # No score threshold here: hybrid_search already does ranking +
        # time-decay + result-count cap. RRF scores are inherently small
        # (~1/(60+rank)) so a 0.1 cutoff dropped every hybrid-only result.
        return [r.content for r in results]

    def _linear_search_raw_sync(
        self, query_vec: np.ndarray, limit: int, memories: list[dict]
    ) -> list[tuple[int, float]]:
        """Linear scan search returning (id, similarity) pairs (sync, runs in thread)."""
        scored = []

        for mem in memories:
            try:
                mem_vec = np.frombuffer(mem["embedding"], dtype=np.float32)
                # Guard against shape mismatch — np.dot on differing dims
                # raises and we'd skip via the except below, but bail
                # explicitly so the message is clearer in logs.
                if mem_vec.shape != query_vec.shape:
                    continue

                dot_product = float(np.dot(query_vec, mem_vec))
                norm_a = float(np.linalg.norm(query_vec))
                norm_b = float(np.linalg.norm(mem_vec))

                similarity = 0.0 if norm_a == 0 or norm_b == 0 else dot_product / (norm_a * norm_b)

                # Drop NaN / Inf scores — a corrupted embedding can produce
                # one and silently torpedo every later sort/threshold check.
                import math as _math

                if not _math.isfinite(similarity):
                    continue

                if similarity > LINEAR_SEARCH_MIN_SIMILARITY:
                    scored.append((mem.get("id", -1), similarity))
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Skipping invalid memory in linear search: %s", e)
                continue

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def _linear_search_raw(
        self, query_vec: np.ndarray, limit: int, memories: list[dict]
    ) -> list[tuple[int, float]]:
        """Linear scan search returning (id, similarity) pairs."""
        return await asyncio.to_thread(self._linear_search_raw_sync, query_vec, limit, memories)

    async def _linear_search(
        self, query_vec: np.ndarray, limit: int, channel_id: int | None
    ) -> list[str]:
        """Fallback linear scan search (legacy method)."""
        if not _DB_AVAILABLE or db is None:
            return []

        try:
            all_memories = await asyncio.wait_for(
                db.get_all_rag_memories(channel_id), timeout=_DB_QUERY_TIMEOUT
            )
        except TimeoutError:
            logger.warning("⏱️ RAG linear_search DB query timed out after %ds", _DB_QUERY_TIMEOUT)
            return []

        if not all_memories:
            return []

        results = await self._linear_search_raw(query_vec, limit, all_memories)

        # Build an id→memory lookup so the post-filter is O(N), not the
        # original O(results × all_memories) which got expensive once
        # MAX_RAG_REBUILD started returning tens of thousands of rows.
        by_id = {m.get("id"): m for m in all_memories if m.get("id") is not None}
        relevant = []
        for mem_id, similarity in results:
            if similarity > LINEAR_SEARCH_RELEVANCE_THRESHOLD:
                mem = by_id.get(mem_id)
                if mem and "content" in mem:
                    relevant.append(mem["content"])

        if relevant:
            logger.info("🧠 Linear scan found %d relevant memories", len(relevant))

        return relevant[:limit]


# Global instance
rag_system = MemorySystem()
