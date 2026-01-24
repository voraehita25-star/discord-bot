"""
RAG (Retrieval-Augmented Generation) Module
Handles long-term memory using vector embeddings and cosine similarity.
Enhanced with hybrid search (semantic + keyword) and Reciprocal Rank Fusion.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from google import genai

from utils.database import db

from ..data.constants import GEMINI_API_KEY

# Index persistence path
FAISS_INDEX_DIR = Path("data/faiss")
FAISS_INDEX_FILE = FAISS_INDEX_DIR / "index.bin"
FAISS_ID_MAP_FILE = FAISS_INDEX_DIR / "id_map.npy"

# Try to import FAISS for optimized vector search
try:
    import os as _os_faiss

    import faiss

    FAISS_AVAILABLE = True
    # Enable multi-threading for faster search (use all CPU cores)
    _faiss_threads = _os_faiss.cpu_count() or 4
    faiss.omp_set_num_threads(_faiss_threads)
    logging.info("🚀 FAISS available - using optimized vector search (%d threads)", _faiss_threads)
except ImportError:
    FAISS_AVAILABLE = False
    logging.info("ℹ️ FAISS not installed - using linear scan fallback")

# Embedding Model
EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768  # text-embedding-004 produces 768-dim vectors

# Time decay settings
TIME_DECAY_HALF_LIFE_DAYS = 30  # Memories lose half importance after 30 days

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
        return min(2.0, max(0.0, importance))


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
        logging.debug("🔍 Built FAISS index with %d vectors", len(ids))

    def search(self, query_vector: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
        """Search for k nearest neighbors. Returns list of (id, similarity)."""
        if not self._initialized or self.index is None:
            return []

        # Normalize query
        norm = np.linalg.norm(query_vector)
        if norm == 0:
            return []
        query_normalized = (query_vector / norm).reshape(1, -1).astype(np.float32)

        with self._lock:
            # Search
            k = min(k, self.index.ntotal)
            similarities, indices = self.index.search(query_normalized, k)

            # Map indices back to memory IDs
            results = []
            for i, idx in enumerate(indices[0]):
                if idx >= 0 and idx < len(self.id_map):
                    results.append((self.id_map[idx], float(similarities[0][i])))

        return results

    @property
    def is_initialized(self) -> bool:
        """Check if the index has been initialized."""
        return self._initialized

    def add_single(self, vector: np.ndarray, memory_id: int) -> None:
        """Add a single vector to the index."""
        with self._lock:
            if not self._initialized:
                # First vector - initialize index
                norm = np.linalg.norm(vector)
                if norm > 0:
                    normalized = (vector / norm).reshape(1, -1).astype(np.float32)
                    self.index = faiss.IndexFlatIP(self.dimension)
                    self.index.add(normalized)
                    self.id_map = [memory_id]
                    self._initialized = True
            else:
                # Add to existing index
                norm = np.linalg.norm(vector)
                if norm > 0:
                    normalized = (vector / norm).reshape(1, -1).astype(np.float32)
                    self.index.add(normalized)
                    self.id_map.append(memory_id)

    def save_to_disk(self) -> bool:
        """Save FAISS index to disk for persistence.

        Uses atomic write pattern: write to temp files, then rename.
        This prevents inconsistent state if one write fails.
        """
        if not self._initialized or not FAISS_AVAILABLE:
            return False

        try:
            FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

            # Atomic write pattern: write to temp, then rename
            temp_index = FAISS_INDEX_FILE.with_suffix(".tmp")
            temp_id_map = FAISS_ID_MAP_FILE.with_suffix(".tmp.npy")

            # Write to temp files first
            faiss.write_index(self.index, str(temp_index))
            np.save(str(temp_id_map), np.array(self.id_map))

            # Rename to final paths (atomic on most filesystems)
            temp_index.replace(FAISS_INDEX_FILE)
            temp_id_map.replace(FAISS_ID_MAP_FILE)

            logging.info("💾 Saved FAISS index to disk (%d vectors)", len(self.id_map))
            return True
        except Exception as e:
            logging.error("Failed to save FAISS index: %s", e)
            # Clean up temp files on failure
            for temp_file in [
                FAISS_INDEX_FILE.with_suffix(".tmp"),
                FAISS_ID_MAP_FILE.with_suffix(".tmp.npy"),
            ]:
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                except Exception as cleanup_error:
                    logging.debug("Failed to cleanup temp file %s: %s", temp_file, cleanup_error)
            return False

    def load_from_disk(self) -> bool:
        """Load FAISS index from disk."""
        if not FAISS_AVAILABLE:
            return False

        if not FAISS_INDEX_FILE.exists() or not FAISS_ID_MAP_FILE.exists():
            return False

        try:
            self.index = faiss.read_index(str(FAISS_INDEX_FILE))
            self.id_map = np.load(str(FAISS_ID_MAP_FILE)).tolist()
            self._initialized = True
            logging.info("📂 Loaded FAISS index from disk (%d vectors)", len(self.id_map))
            return True
        except Exception as e:
            logging.error("Failed to load FAISS index: %s", e)
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

    def __init__(self):
        self.client = None
        self._faiss_index: FAISSIndex | None = None
        self._index_built = False
        self._memories_cache: dict[int, dict] = {}  # id -> memory dict

        # Debounced save state
        self._save_pending = False
        self._save_task: asyncio.Task | None = None
        self._periodic_save_task: asyncio.Task | None = None

        if GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
            except Exception as e:
                logging.error("Failed to init Gemini Client for RAG: %s", e)

    def _evict_cache_if_needed(self) -> None:
        """Evict oldest entries from cache if over MAX_CACHE_SIZE."""
        if len(self._memories_cache) <= self.MAX_CACHE_SIZE:
            return

        # Sort by created_at (oldest first) and evict 10% of max size
        evict_count = self.MAX_CACHE_SIZE // 10
        sorted_ids = sorted(
            self._memories_cache.keys(),
            key=lambda mid: self._memories_cache[mid].get("created_at", 0),
        )
        for mem_id in sorted_ids[:evict_count]:
            self._memories_cache.pop(mem_id, None)
        logging.debug("🗑️ Evicted %d old entries from RAG cache", evict_count)

    def get_stats(self) -> dict:
        """Get RAG system statistics."""
        return {
            "faiss_available": FAISS_AVAILABLE,
            "index_built": self._index_built,
            "memories_cached": len(self._memories_cache),
            "index_size": len(self._faiss_index.id_map) if self._faiss_index else 0,
            "client_ready": self.client is not None,
        }

    async def generate_embedding(self, text: str) -> np.ndarray | None:
        """Generate vector embedding for text using Gemini API."""
        if not self.client:
            return None

        try:
            result = await self.client.aio.models.embed_content(
                model=EMBEDDING_MODEL, contents=text
            )

            if result.embeddings:
                return np.array(result.embeddings[0].values, dtype=np.float32)
            return None
        except Exception as e:
            logging.error("Embedding generation failed: %s", e)
            return None

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 10
    ) -> list[np.ndarray | None]:
        """
        Generate embeddings for multiple texts in batches.
        More efficient than generating one at a time.
        """
        if not self.client or not texts:
            return [None] * len(texts)

        results: list[np.ndarray | None] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                # Process batch concurrently
                tasks = [
                    self.client.aio.models.embed_content(model=EMBEDDING_MODEL, contents=text)
                    for text in batch
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in batch_results:
                    if isinstance(result, Exception):
                        results.append(None)
                    elif result.embeddings:
                        results.append(np.array(result.embeddings[0].values, dtype=np.float32))
                    else:
                        results.append(None)

            except Exception as e:
                logging.error("Batch embedding failed: %s", e)
                results.extend([None] * len(batch))

        return results

    async def _ensure_index(self, channel_id: int | None = None) -> None:
        """Build FAISS index from database if not already built."""
        if not FAISS_AVAILABLE or self._index_built:
            return

        # Try to load from disk first (fast path)
        if self._faiss_index is None:
            self._faiss_index = FAISSIndex(EMBEDDING_DIM)
            if self._faiss_index.load_from_disk():
                self._index_built = True
                # Load memories cache from DB
                all_memories = await db.get_all_rag_memories(channel_id)
                for mem in all_memories:
                    mem_id = mem.get("id")
                    if mem_id:
                        self._memories_cache[mem_id] = mem
                self._evict_cache_if_needed()
                return

        # Build from database (slow path)
        all_memories = await db.get_all_rag_memories(channel_id)
        if not all_memories:
            return

        vectors = []
        ids = []

        for mem in all_memories:
            try:
                vec = np.frombuffer(mem["embedding"], dtype=np.float32)
                if len(vec) == EMBEDDING_DIM:
                    vectors.append(vec)
                    mem_id = mem.get("id", len(ids))
                    ids.append(mem_id)
                    self._memories_cache[mem_id] = mem
            except (ValueError, TypeError, KeyError) as e:
                logging.debug("Skipping invalid memory embedding: %s", e)
                continue

        if vectors:
            self._faiss_index = FAISSIndex(EMBEDDING_DIM)
            self._faiss_index.build(np.array(vectors), ids)
            self._index_built = True
            # Save to disk for next restart
            self._faiss_index.save_to_disk()
            self._evict_cache_if_needed()
            logging.info("🚀 FAISS index built with %d memories", len(vectors))

    def _schedule_index_save(self, delay: float = 30.0) -> None:
        """Schedule a debounced save of FAISS index (non-blocking)."""
        if self._save_pending:
            return  # Already scheduled

        self._save_pending = True

        async def do_save():
            await asyncio.sleep(delay)
            self._save_pending = False
            if self._faiss_index and self._index_built:
                self._faiss_index.save_to_disk()

        self._save_task = asyncio.create_task(do_save())

    def start_periodic_save(self, interval: float = 300.0) -> None:
        """Start background task to save FAISS index periodically (every 5 min)."""

        async def save_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    if self._faiss_index and self._index_built:
                        self._faiss_index.save_to_disk()
                except asyncio.CancelledError:
                    # Task was cancelled, exit gracefully
                    break
                except Exception as e:
                    logging.error("❌ Error in periodic FAISS save: %s", e)
                    # Continue running to try again next interval

        if self._periodic_save_task is None or self._periodic_save_task.done():
            self._periodic_save_task = asyncio.create_task(save_loop())
            logging.info("🔄 Started periodic FAISS save task (every %.0fs)", interval)

    def stop_periodic_save(self) -> None:
        """Stop the periodic save task."""
        if self._periodic_save_task and not self._periodic_save_task.done():
            self._periodic_save_task.cancel()
            self._periodic_save_task = None

    async def force_save_index(self) -> bool:
        """Force immediate save of FAISS index (useful for shutdown)."""
        if self._faiss_index and self._index_built:
            return self._faiss_index.save_to_disk()
        return False

    async def add_memory(self, content: str, channel_id: int | None = None) -> bool:
        """Add a text chunk to long-term memory."""
        embedding = await self.generate_embedding(content)
        if embedding is None:
            return False

        embedding_bytes = embedding.tobytes()

        # Save to DB and get ID
        result = await db.save_rag_memory(
            content=content, embedding_bytes=embedding_bytes, channel_id=channel_id
        )

        # Add to FAISS index if available
        if FAISS_AVAILABLE and self._faiss_index and self._index_built:
            self._faiss_index.add_single(embedding, result if isinstance(result, int) else 0)
            # Schedule debounced save instead of saving immediately (performance)
            self._schedule_index_save()

        logging.info("🧠 Saved RAG memory: %s...", content[:30])
        return True

    def _calculate_time_decay(self, created_at_str: str) -> float:
        """
        Calculate time decay factor for a memory.
        Returns value between 0 and 1, where 1 is most recent.
        """
        try:
            from datetime import datetime

            created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            age_days = (now - created).total_seconds() / 86400

            # Exponential decay with half-life
            decay = 0.5 ** (age_days / TIME_DECAY_HALF_LIFE_DAYS)
            return max(0.1, decay)  # Minimum 10% weight
        except (ValueError, TypeError, AttributeError) as e:
            logging.debug("Time decay calculation failed: %s", e)
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
            content = mem.get("content", "").lower()
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
                    scored.append((mem.get("id", 0), jaccard))

        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _reciprocal_rank_fusion(
        self,
        semantic_results: list[tuple[int, float]],
        keyword_results: list[tuple[int, float]],
        k: int = 60,
    ) -> list[tuple[int, float]]:
        """
        Merge results from semantic and keyword search using RRF.
        Returns list of (memory_id, combined_score).
        """
        rrf_scores: dict[int, float] = {}

        # Process semantic results
        for rank, (mem_id, _) in enumerate(semantic_results):
            rrf_scores[mem_id] = rrf_scores.get(mem_id, 0) + 1 / (k + rank + 1)

        # Process keyword results
        for rank, (mem_id, _) in enumerate(keyword_results):
            rrf_scores[mem_id] = rrf_scores.get(mem_id, 0) + 1 / (k + rank + 1)

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
        # Get all memories for keyword search
        all_memories = await db.get_all_rag_memories(channel_id)
        if not all_memories:
            return []

        # Update cache
        for mem in all_memories:
            self._memories_cache[mem.get("id", 0)] = mem
        self._evict_cache_if_needed()

        # Semantic search
        semantic_results = []
        query_vec = await self.generate_embedding(query)

        if query_vec is not None:
            if FAISS_AVAILABLE:
                await self._ensure_index(channel_id)
                if self._faiss_index and self._faiss_index.is_initialized:
                    semantic_results = self._faiss_index.search(query_vec, k=limit * 2)

            # Fallback to linear if FAISS unavailable or not built
            if not semantic_results:
                semantic_results = await self._linear_search_raw(query_vec, limit * 2, all_memories)

        # Keyword search
        keyword_results = self._keyword_search(query, all_memories, limit * 2)

        # Merge using RRF
        if semantic_results and keyword_results:
            merged = self._reciprocal_rank_fusion(semantic_results, keyword_results)
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

            mem = self._memories_cache.get(mem_id)
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
                    from datetime import datetime

                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
                    age_days = (now - created).days
                except (ValueError, TypeError, AttributeError):
                    pass  # Invalid or missing datetime format

            results.append(
                MemoryResult(
                    content=mem["content"],
                    score=final_score,
                    memory_id=mem_id,
                    source=source,
                    age_days=age_days,
                )
            )

        # Sort by final score
        results.sort(key=lambda x: x.score, reverse=True)

        if results:
            logging.info("🧠 Hybrid search found %d memories (source: %s)", len(results), source)

        return results

    async def search_memory(
        self, query: str, limit: int = 3, channel_id: int | None = None
    ) -> list[str]:
        """
        Search for relevant memories (backwards compatible API).
        Uses hybrid search internally.
        """
        results = await self.hybrid_search(query, limit, channel_id)
        return [r.content for r in results if r.score > 0.1]

    async def _linear_search_raw(
        self, query_vec: np.ndarray, limit: int, memories: list[dict]
    ) -> list[tuple[int, float]]:
        """Linear scan search returning (id, similarity) pairs."""
        scored = []

        for mem in memories:
            try:
                mem_vec = np.frombuffer(mem["embedding"], dtype=np.float32)

                dot_product = np.dot(query_vec, mem_vec)
                norm_a = np.linalg.norm(query_vec)
                norm_b = np.linalg.norm(mem_vec)

                similarity = 0 if norm_a == 0 or norm_b == 0 else dot_product / (norm_a * norm_b)

                if similarity > LINEAR_SEARCH_MIN_SIMILARITY:
                    scored.append((mem.get("id", 0), similarity))
            except (ValueError, TypeError, KeyError) as e:
                logging.debug("Skipping invalid memory in linear search: %s", e)
                continue

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def _linear_search(
        self, query_vec: np.ndarray, limit: int, channel_id: int | None
    ) -> list[str]:
        """Fallback linear scan search (legacy method)."""
        all_memories = await db.get_all_rag_memories(channel_id)

        if not all_memories:
            return []

        results = await self._linear_search_raw(query_vec, limit, all_memories)

        relevant = []
        for mem_id, similarity in results:
            if similarity > LINEAR_SEARCH_RELEVANCE_THRESHOLD:
                for mem in all_memories:
                    if mem.get("id") == mem_id:
                        relevant.append(mem["content"])
                        break

        if relevant:
            logging.info("🧠 Linear scan found %d relevant memories", len(relevant))

        return relevant[:limit]


# Global instance
rag_system = MemorySystem()
