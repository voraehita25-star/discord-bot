"""
Python wrapper for Rust RAG Engine.

Provides fallback to pure Python implementation if Rust extension is not available.
"""

from __future__ import annotations

import importlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to import Rust extension dynamically to avoid Pylance warnings
RUST_AVAILABLE = False
RustRagEngine = None
MemoryEntry = None
SearchResult = None

try:
    _rag_module = importlib.import_module("rag_engine")
    RustRagEngine = getattr(_rag_module, "RagEngine", None)
    MemoryEntry = getattr(_rag_module, "MemoryEntry", None)
    SearchResult = getattr(_rag_module, "SearchResult", None)
    if RustRagEngine:
        RUST_AVAILABLE = True
        logger.info("✅ Rust RAG Engine loaded successfully")
except ImportError:
    logger.warning("⚠️ Rust RAG Engine not available, using Python fallback")


class RagEngineWrapper:
    """
    Wrapper for RAG Engine with automatic fallback to Python implementation.

    Usage:
        engine = RagEngineWrapper(dimension=384)
        engine.add("id1", "Some text", embedding_vector, importance=1.0)
        results = engine.search(query_embedding, top_k=5)
    """

    def __init__(self, dimension: int = 384, similarity_threshold: float = 0.7):
        self.dimension = dimension
        self.similarity_threshold = similarity_threshold
        self._use_rust = RUST_AVAILABLE

        if self._use_rust:
            self._engine = RustRagEngine(dimension, similarity_threshold)
        else:
            # Python fallback
            self._entries: dict[str, dict[str, Any]] = {}

    def add(
        self,
        entry_id: str,
        text: str,
        embedding: list[float],
        timestamp: float | None = None,
        importance: float = 1.0,
    ) -> None:
        """Add a memory entry."""
        if timestamp is None:
            timestamp = time.time()

        if self._use_rust:
            entry = MemoryEntry(entry_id, text, embedding, timestamp, importance)
            self._engine.add(entry)
        else:
            self._entries[entry_id] = {
                "id": entry_id,
                "text": text,
                "embedding": embedding,
                "timestamp": timestamp,
                "importance": importance,
            }

    def add_batch(self, entries: list[dict[str, Any]]) -> int:
        """Add multiple entries at once."""
        if self._use_rust:
            rust_entries = [
                MemoryEntry(
                    e["id"], e["text"], e["embedding"],
                    e.get("timestamp", time.time()),
                    e.get("importance", 1.0)
                )
                for e in entries
            ]
            return self._engine.add_batch(rust_entries)
        else:
            for e in entries:
                self.add(
                    e["id"], e["text"], e["embedding"],
                    e.get("timestamp"), e.get("importance", 1.0)
                )
            return len(entries)

    def remove(self, entry_id: str) -> bool:
        """Remove an entry by ID."""
        if self._use_rust:
            return self._engine.remove(entry_id)
        else:
            return self._entries.pop(entry_id, None) is not None

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        time_decay_factor: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search for similar entries."""
        if self._use_rust:
            results = self._engine.search(query_embedding, top_k, time_decay_factor)
            return [
                {"id": r.id, "text": r.text, "score": r.score, "timestamp": r.timestamp}
                for r in results
            ]
        else:
            return self._python_search(query_embedding, top_k, time_decay_factor)

    def _python_search(
        self,
        query_embedding: list[float],
        top_k: int,
        time_decay_factor: float,
    ) -> list[dict[str, Any]]:
        """Pure Python fallback for search."""
        current_time = time.time()
        results = []

        for entry in self._entries.values():
            base_score = self._cosine_similarity(query_embedding, entry["embedding"])

            if time_decay_factor > 0:
                age_hours = (current_time - entry["timestamp"]) / 3600.0
                decay = pow(2.718281828, -time_decay_factor * age_hours)
                score = base_score * decay * entry["importance"]
            else:
                score = base_score * entry["importance"]

            if score >= self.similarity_threshold:
                results.append({
                    "id": entry["id"],
                    "text": entry["text"],
                    "score": score,
                    "timestamp": entry["timestamp"],
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a * norm_b < 1e-10:
            return 0.0
        return dot / (norm_a * norm_b)

    def __len__(self) -> int:
        if self._use_rust:
            return self._engine.len()
        return len(self._entries)

    def clear(self) -> None:
        """Clear all entries."""
        if self._use_rust:
            self._engine.clear()
        else:
            self._entries.clear()

    def get_ids(self) -> list[str]:
        """Get all entry IDs."""
        if self._use_rust:
            return self._engine.get_ids()
        return list(self._entries.keys())

    def save(self, path: str | Path) -> None:
        """Save to JSON file."""
        path = Path(path)
        if self._use_rust:
            self._engine.save(str(path))
        else:
            with path.open("w", encoding="utf-8") as f:
                json.dump(list(self._entries.values()), f, ensure_ascii=False, indent=2)

    def load(self, path: str | Path) -> int:
        """Load from JSON file."""
        path = Path(path)
        if self._use_rust:
            return self._engine.load(str(path))
        else:
            with path.open(encoding="utf-8") as f:
                entries = json.load(f)
            for e in entries:
                self._entries[e["id"]] = e
            return len(entries)

    @property
    def is_rust(self) -> bool:
        """Check if using Rust backend."""
        return self._use_rust


# Convenience alias
RagEngine = RagEngineWrapper
