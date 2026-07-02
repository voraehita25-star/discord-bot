"""
Python wrapper for Rust RAG Engine.

Provides fallback to pure Python implementation if Rust extension is not available.
"""

from __future__ import annotations

import importlib
import itertools
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Per-process atomic counter for save()'s temp filenames — see save().
_SAVE_TMP_COUNTER = itertools.count()

# Try to import Rust extension dynamically to avoid Pylance warnings
RUST_AVAILABLE = False
RustRagEngine = None
MemoryEntry = None
SearchResult = None

try:
    # The built .pyd sits next to this wrapper (cogs/ai_core/memory/
    # rag_engine.pyd), so the package-qualified import is the one that
    # resolves; the bare top-level name only works if the extension was
    # installed into the environment.
    try:
        _rag_module = importlib.import_module("cogs.ai_core.memory.rag_engine")
    except ImportError:
        _rag_module = importlib.import_module("rag_engine")
    RustRagEngine = getattr(_rag_module, "RagEngine", None)
    MemoryEntry = getattr(_rag_module, "MemoryEntry", None)
    SearchResult = getattr(_rag_module, "SearchResult", None)
    # Gate on ALL required symbols: a partial .pyd that exposes RagEngine but
    # not MemoryEntry/SearchResult would otherwise set _use_rust=True yet crash
    # in add() (None(...) -> TypeError) instead of degrading to Python fallback.
    if RustRagEngine and MemoryEntry and SearchResult:
        RUST_AVAILABLE = True
        logger.info("✅ Rust RAG Engine loaded successfully")
except ImportError:
    logger.warning("⚠️ Rust RAG Engine not available, using Python fallback")


class RagEngineWrapper:
    """
    Wrapper for RAG Engine with automatic fallback to Python implementation.

    Usage:
        engine = RagEngineWrapper(dimension=768)  # gemini-embedding-2 (768-dim)
        engine.add("id1", "Some text", embedding_vector, importance=1.0)
        results = engine.search(query_embedding, top_k=5)
    """

    def __init__(self, dimension: int = 768, similarity_threshold: float = 0.7):
        self.dimension = dimension
        self.similarity_threshold = similarity_threshold
        self._use_rust = RUST_AVAILABLE

        if self._use_rust:
            self._engine = RustRagEngine(dimension, similarity_threshold)  # type: ignore[misc]
        else:
            # Python fallback
            self._entries: dict[str, dict[str, Any]] = {}
            # Protect _entries against concurrent add/remove/clear/search.
            # Without this, _python_search iterating self._entries.values()
            # while another thread mutates the dict raises RuntimeError.
            self._entries_lock = threading.RLock()

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
            entry = MemoryEntry(entry_id, text, embedding, timestamp, importance)  # type: ignore[misc]
            self._engine.add(entry)
        else:
            # Mirror the Rust add()'s validation (lib.rs:127-151) so both
            # backends fail identically: reject wrong-dimension embeddings and
            # any non-finite importance / embedding value. Without this the
            # Python fallback stored bad entries silently, then either skipped
            # them on every search (wrong-dim ValueError swallowed) or produced
            # NaN scores (NaN/Inf vectors), diverging from the .pyd path.
            if len(embedding) != self.dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.dimension}, got {len(embedding)}"
                )
            if not math.isfinite(importance):
                raise ValueError("importance must be a finite number")
            # Importance is a non-negative weight: a negative value flips the sign
            # of the final score in _python_search (score = base * importance) and
            # can rank an opposite-meaning memory above the threshold. Mirror the
            # Rust add()'s '< 0' rejection (lib.rs) so both backends stay in lockstep.
            if importance < 0.0:
                raise ValueError("importance must be non-negative")
            if any(not math.isfinite(v) for v in embedding):
                raise ValueError("embedding contains non-finite values (NaN/Inf)")
            with self._entries_lock:
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
            # Silent-skip contract parity: build MemoryEntry objects per entry so
            # a single dict missing a required key (KeyError) or holding a wrong-
            # typed value (TypeError/ValueError from PyO3 conversion) drops only
            # that entry instead of aborting the whole batch. Dimension / finite /
            # non-negative-importance validation is left to the Rust add_batch
            # (lib.rs:215), which silently skips those too.
            rust_entries: list[Any] = []
            for e in entries:
                try:
                    rust_entries.append(
                        MemoryEntry(  # type: ignore[misc]
                            e["id"],
                            e["text"],
                            e["embedding"],
                            e.get("timestamp", time.time()),
                            e.get("importance", 1.0),
                        )
                    )
                except (ValueError, KeyError, TypeError):
                    logger.debug("Skipping malformed RAG entry in add_batch", exc_info=True)
                    continue
            return self._engine.add_batch(rust_entries)  # type: ignore[no-any-return]
        else:
            # Silent-skip contract: mirror Rust add_batch (lib.rs:153-175),
            # which drops any entry failing validation and returns only the
            # count actually inserted. Since add() now raises on bad input, we
            # swallow that ValueError per entry instead of aborting the batch.
            added = 0
            for e in entries:
                try:
                    # Count only net-new ids: add() overwrites an existing id via
                    # dict assignment (no signal), so a duplicate id must not
                    # inflate the count. Compare stored size across the add() to
                    # match the Rust backend, which reports actual stored count.
                    with self._entries_lock:
                        before = len(self._entries)
                    self.add(
                        e["id"],
                        e["text"],
                        e["embedding"],
                        e.get("timestamp"),
                        e.get("importance", 1.0),
                    )
                    with self._entries_lock:
                        if len(self._entries) > before:
                            added += 1
                except (ValueError, KeyError, TypeError):
                    logger.debug("Skipping malformed RAG entry in add_batch", exc_info=True)
                    continue
            return added

    def remove(self, entry_id: str) -> bool:
        """Remove an entry by ID."""
        if self._use_rust:
            return self._engine.remove(entry_id)  # type: ignore[no-any-return]
        else:
            with self._entries_lock:
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
        # Reject non-finite query vectors up front to match the Rust search()
        # contract (lib.rs:204-208). An Inf in the query yields an Inf score
        # that passes the threshold filter and corrupts rank order; without
        # this check the fallback would instead return silently-empty results.
        if any(not math.isfinite(v) for v in query_embedding):
            raise ValueError("query_embedding contains non-finite values (NaN/Inf)")

        current_time = time.time()
        results = []

        # Snapshot entries under the lock so concurrent mutators can't trip
        # "dictionary changed size during iteration" while we score.
        with self._entries_lock:
            entries_snapshot = list(self._entries.values())

        for entry in entries_snapshot:
            try:
                base_score = self._cosine_similarity(query_embedding, entry["embedding"])

                if time_decay_factor > 0:
                    # Mirror the Rust backend's clamps (lib.rs:228-232): a
                    # future-dated timestamp must not inflate the score, and a
                    # hugely negative age would overflow math.exp entirely.
                    factor = min(time_decay_factor, 1.0)
                    age_hours = max(0.0, (current_time - entry["timestamp"]) / 3600.0)
                    decay = math.exp(-factor * age_hours)
                    score = base_score * decay * entry["importance"]
                else:
                    score = base_score * entry["importance"]

                if score >= self.similarity_threshold:
                    results.append(
                        {
                            "id": entry["id"],
                            "text": entry["text"],
                            "score": score,
                            "timestamp": entry["timestamp"],
                        }
                    )
            except (ValueError, KeyError, TypeError, OverflowError):
                # Skip a single malformed entry rather than crashing the whole
                # search. The whole per-entry body is guarded because load()
                # only validates "id" — timestamp/importance/text can be absent
                # in a hand-edited JSON file. Logged at debug to avoid log spam.
                logger.debug("Skipping malformed RAG entry", exc_info=True)
                continue

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
        return dot / (norm_a * norm_b)  # type: ignore[no-any-return]

    def __len__(self) -> int:
        if self._use_rust:
            return self._engine.len()  # type: ignore[no-any-return]
        with self._entries_lock:
            return len(self._entries)

    def clear(self) -> None:
        """Clear all entries."""
        if self._use_rust:
            self._engine.clear()
        else:
            with self._entries_lock:
                self._entries.clear()

    def get_ids(self) -> list[str]:
        """Get all entry IDs."""
        if self._use_rust:
            return self._engine.get_ids()  # type: ignore[no-any-return]
        with self._entries_lock:
            return list(self._entries.keys())

    def save(self, path: str | Path) -> None:
        """Save to JSON file."""
        path = Path(path)
        if self._use_rust:
            self._engine.save(str(path))
        else:
            # Snapshot under lock so concurrent writers can't trigger
            # "dictionary changed size during iteration" while we serialise.
            with self._entries_lock:
                entries_snapshot = list(self._entries.values())
            # Atomic write: write to sibling tmp file, fsync, then replace.
            # Prevents corruption if the process crashes mid-write.
            # Per-call unique temp name (pid + atomic counter): the previous
            # fixed '<path>.tmp' let two concurrent save() calls on the same
            # path interleave writes into ONE shared tmp file — the first
            # replace() published the interleaved garbage and the loser raised
            # FileNotFoundError. Same race the Rust backend fixed
            # (lib.rs:412-430); keeps the fallback in lockstep.
            tmp_path = path.with_suffix(
                path.suffix + f".tmp.{os.getpid()}.{next(_SAVE_TMP_COUNTER)}"
            )
            try:
                with tmp_path.open("w", encoding="utf-8") as f:
                    json.dump(entries_snapshot, f, ensure_ascii=False, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        # fsync is best-effort; platforms without fsync still get atomic replace
                        pass
                tmp_path.replace(path)
            except Exception:
                # Clean up stale tmp on failure so the next save is unaffected
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

    def load(self, path: str | Path) -> int:
        """Load from JSON file.

        Replaces existing entries (does not merge). Calling load() twice on
        different files used to silently merge them, which surprised callers.
        """
        path = Path(path)
        if self._use_rust:
            return self._engine.load(str(path))  # type: ignore[no-any-return]
        else:
            try:
                with path.open(encoding="utf-8") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.exception("Failed to load RAG data from %s", path)
                return 0
            # A valid-JSON top-level scalar (null/42/true) parses but is not
            # iterable; iterating it would raise an uncaught TypeError. Degrade
            # a non-list file to a no-op so a corrupt-but-parseable file keeps
            # existing data instead of crashing the caller.
            if not isinstance(entries, list):
                logger.error("RAG file %s is not a JSON list; keeping existing data", path)
                return 0
            # Validate into a fresh dict FIRST. Clearing before validation
            # meant a parseable-but-wrong-shaped file (JSON object, list of
            # non-dicts) silently destroyed all in-memory entries; the Rust
            # backend explicitly refuses to replace data on a zero-match load.
            new_entries: dict[str, dict[str, Any]] = {}
            for entry in entries:
                if isinstance(entry, dict) and "id" in entry:
                    # Reject entries written for a different embedding dimension.
                    # Without this a stale wrong-dim file loads silently and every
                    # later _python_search raises a dimension-mismatch ValueError
                    # that is swallowed per-entry, so search returns zero results
                    # with no error surfaced.
                    embedding = entry.get("embedding")
                    if not isinstance(embedding, list) or len(embedding) != self.dimension:
                        logger.warning(
                            "Skipping RAG entry %r: embedding dimension %s != expected %d",
                            entry.get("id"),
                            len(embedding) if isinstance(embedding, list) else "missing",
                            self.dimension,
                        )
                        continue
                    # Reject non-numeric / non-finite embedding VALUES, matching
                    # the Rust load() guard (lib.rs:592-598). json.load parses
                    # NaN/Infinity tokens by default, and a NaN component makes
                    # _python_search's score NaN — ``score >= threshold`` is
                    # False for NaN, so the entry would be silently
                    # unsearchable (no exception fires, so the per-entry debug
                    # skip never triggers), and a later save() re-serializes
                    # the NaN into a file the Rust backend then rejects
                    # WHOLESALE. add() already blocks these values; load() was
                    # the one ingestion gap.
                    if not all(
                        isinstance(v, (int, float)) and math.isfinite(v) for v in embedding
                    ):
                        logger.warning(
                            "Skipping RAG entry %r: embedding contains non-numeric or "
                            "non-finite values",
                            entry.get("id"),
                        )
                        continue
                    # Reject negative/non-finite importance on load, matching the
                    # Rust load() guard (lib.rs:579-586). Without this a hand-edited
                    # or stale JSON dump could reintroduce the sign-flip bug that
                    # add()/add_batch() already block: a negative weight flips the
                    # sign of the final score in _python_search (score = base *
                    # importance) and can rank an opposite-meaning memory above the
                    # threshold. Skip (log + continue) rather than store.
                    imp = entry.get("importance", 1.0)
                    if not isinstance(imp, (int, float)) or not math.isfinite(imp) or imp < 0.0:
                        logger.warning(
                            "Skipping RAG entry %r: importance %r is not a finite non-negative number",
                            entry.get("id"),
                            imp,
                        )
                        continue
                    # Backend parity: Rust load() also drops entries whose
                    # timestamp is non-finite. A NaN/Inf timestamp cannot corrupt
                    # the score (the decay path uses max(0.0, age)), but it would
                    # leak into the returned result dict and break any consumer
                    # that sorts or does arithmetic on timestamp. Skip a present-
                    # but-non-finite timestamp for full lockstep with the Rust load.
                    ts = entry.get("timestamp")
                    if ts is not None and (
                        not isinstance(ts, (int, float)) or not math.isfinite(ts)
                    ):
                        logger.warning(
                            "Skipping RAG entry %r: timestamp %r is not finite",
                            entry.get("id"),
                            ts,
                        )
                        continue
                    new_entries[entry["id"]] = entry
            if not new_entries and entries:
                logger.error("No valid entries in %s; keeping existing data (Rust parity)", path)
                return 0
            with self._entries_lock:
                self._entries = new_entries
            return len(new_entries)

    @property
    def is_rust(self) -> bool:
        """Check if using Rust backend."""
        return self._use_rust


# Convenience alias
RagEngine = RagEngineWrapper
