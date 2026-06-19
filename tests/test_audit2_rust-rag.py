"""
Audit-2 regression tests for the rust-rag group.

Covers rust-rag-M2: importance must be non-negative. A negative importance is
finite but flips the sign of the final search score (score = base * importance),
so for an OPPOSITE-meaning memory (cosine base < 0) a negative weight produces a
POSITIVE score that can pass the similarity threshold and surface a maximally-
irrelevant hit. The Rust backend enforces this in lib.rs; these tests assert the
Python fallback (cogs/ai_core/memory/rag_rust.py) rejects it in lockstep.

The Rust-side regression tests live in rust_extensions/rag_engine/src/lib.rs
(#[cfg(test)]): add_rejects_negative_importance, add_batch_drops_negative_importance,
load_drops_negative_importance_entries.
"""

import json
from unittest.mock import patch

import pytest


class TestNegativeImportanceRejected:
    """rust-rag-M2: Python fallback must reject negative importance."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_rejects_negative_importance(self):
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        with pytest.raises(ValueError, match="non-negative"):
            engine.add("neg", "opposite", [0.1, 0.2, 0.3], importance=-0.5)
        # The bad entry must not have been stored.
        assert "neg" not in engine._entries

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_accepts_zero_importance(self):
        # Zero is the clamp lower bound and a valid weight — must still pass.
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("zero", "fine", [0.1, 0.2, 0.3], importance=0.0)
        assert engine._entries["zero"]["importance"] == 0.0

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_batch_silently_drops_negative_importance(self):
        # add_batch swallows per-entry ValueErrors (silent-skip contract), so a
        # negative-importance entry is dropped and only the valid one is counted.
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        added = engine.add_batch(
            [
                {"id": "ok", "text": "good", "embedding": [0.1, 0.2, 0.3], "importance": 0.5},
                {"id": "neg", "text": "bad", "embedding": [0.1, 0.2, 0.3], "importance": -1.0},
            ]
        )
        assert added == 1
        assert "ok" in engine._entries
        assert "neg" not in engine._entries

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_negative_importance_cannot_surface_opposite_memory(self):
        # Behavioural proof of the bug being fixed: previously, adding a memory
        # whose embedding is the semantic OPPOSITE of the query with a negative
        # importance produced a positive score (neg * neg) that passed the
        # threshold. With the guard, the entry is rejected at add() time, so it
        # can never appear in search results.
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.7)
        query = [1.0, 0.0, 0.0]
        opposite = [-1.0, 0.0, 0.0]  # cosine(query, opposite) == -1.0

        with pytest.raises(ValueError, match="non-negative"):
            engine.add("evil", "opposite-meaning", opposite, importance=-1.0)

        # Nothing was stored, so search returns no hits.
        results = engine.search(query, top_k=5)
        assert results == []


class TestLoadDropsNegativeImportance:
    """rust-rag-M2: Python fallback load() must reject negative-importance entries.

    Closes the gap where add()/add_batch() guarded importance but load() copied
    each entry dict wholesale after checking only 'id' + embedding dimension, so a
    hand-edited or stale JSON dump could reintroduce the sign-flip bug. Mirrors the
    Rust load() guard (lib.rs:579-586) for lockstep.
    """

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_load_skips_negative_importance_keeps_valid(self, tmp_path):
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        # A valid entry plus a negative-importance entry that, before the fix,
        # would load and (because its embedding is the query's opposite) surface
        # with a positive score: cosine([-1,0,0],[1,0,0]) * -1.0 == 1.0 >= 0.7.
        dump = [
            {"id": "good", "text": "valid", "embedding": [0.1, 0.2, 0.3], "importance": 0.5},
            {"id": "evil", "text": "opposite", "embedding": [-1.0, 0.0, 0.0], "importance": -1.0},
        ]
        path = tmp_path / "rag.json"
        path.write_text(json.dumps(dump), encoding="utf-8")

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.7)
        loaded = engine.load(path)

        # Only the valid entry is loaded; the negative-importance one is skipped.
        assert loaded == 1
        assert "good" in engine._entries
        assert "evil" not in engine._entries

        # And it can never surface in search (the original repro returned it
        # with score 1.0); searching the query its opposite was crafted against
        # yields no hit for the dropped entry.
        results = engine.search([1.0, 0.0, 0.0], top_k=5)
        assert all(r["id"] != "evil" for r in results)

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_load_skips_non_finite_importance(self, tmp_path):
        # JSON has no NaN/Inf literal, but json.loads accepts the non-standard
        # tokens by default, so a stale dump can carry them. They must be dropped
        # in lockstep with the Rust !imp.is_finite() guard (lib.rs:579).
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        raw = (
            "["
            '{"id": "good", "text": "valid", "embedding": [0.1, 0.2, 0.3], "importance": 1.0},'
            '{"id": "nan", "text": "bad", "embedding": [0.1, 0.2, 0.3], "importance": NaN},'
            '{"id": "inf", "text": "bad", "embedding": [0.1, 0.2, 0.3], "importance": Infinity}'
            "]"
        )
        path = tmp_path / "rag.json"
        path.write_text(raw, encoding="utf-8")

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.7)
        loaded = engine.load(path)

        assert loaded == 1
        assert "good" in engine._entries
        assert "nan" not in engine._entries
        assert "inf" not in engine._entries
