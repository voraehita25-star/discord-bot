"""
Tests for cogs/ai_core/memory/rag_rust.py

Comprehensive tests for RagEngineWrapper and Python fallback.
"""

import json
import os
import tempfile
from unittest.mock import patch


class TestRagEngineWrapperInit:
    """Tests for RagEngineWrapper initialization."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_init_python_fallback(self):
        """Test init with Python fallback."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=128)

        assert engine.dimension == 128
        assert engine.similarity_threshold == 0.7
        assert engine._use_rust is False
        assert engine._entries == {}

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_init_custom_threshold(self):
        """Test init with custom similarity threshold."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=256, similarity_threshold=0.5)

        assert engine.similarity_threshold == 0.5


class TestRagEngineWrapperAdd:
    """Tests for add method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_entry(self):
        """Test adding an entry."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("test1", "Hello world", [0.1, 0.2, 0.3], importance=0.8)

        assert "test1" in engine._entries
        assert engine._entries["test1"]["text"] == "Hello world"
        assert engine._entries["test1"]["importance"] == 0.8

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_entry_auto_timestamp(self):
        """Test add generates timestamp if not provided."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("test1", "Hello", [0.1, 0.2, 0.3])

        assert "timestamp" in engine._entries["test1"]
        assert engine._entries["test1"]["timestamp"] > 0

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_entry_custom_timestamp(self):
        """Test add with custom timestamp."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("test1", "Hello", [0.1, 0.2, 0.3], timestamp=12345.0)

        assert engine._entries["test1"]["timestamp"] == 12345.0


class TestRagEngineWrapperAddBatch:
    """Tests for add_batch method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_add_batch(self):
        """Test adding multiple entries."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        entries = [
            {"id": "a", "text": "First", "embedding": [0.1, 0.2, 0.3]},
            {"id": "b", "text": "Second", "embedding": [0.4, 0.5, 0.6]},
            {"id": "c", "text": "Third", "embedding": [0.7, 0.8, 0.9]},
        ]

        count = engine.add_batch(entries)

        assert count == 3
        assert len(engine) == 3
        assert "a" in engine._entries
        assert "b" in engine._entries
        assert "c" in engine._entries


class TestRagEngineWrapperRemove:
    """Tests for remove method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_remove_existing(self):
        """Test removing an existing entry."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("test1", "Hello", [0.1, 0.2, 0.3])

        result = engine.remove("test1")

        assert result is True
        assert "test1" not in engine._entries

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_remove_nonexistent(self):
        """Test removing a non-existent entry."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)

        result = engine.remove("nonexistent")

        assert result is False


class TestRagEngineWrapperSearch:
    """Tests for search method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_search_empty(self):
        """Test search on empty engine."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        results = engine.search([0.1, 0.2, 0.3], top_k=5)

        assert results == []

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_search_with_entries(self):
        """Test search with entries."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.0)
        engine.add("a", "First", [1.0, 0.0, 0.0])
        engine.add("b", "Second", [0.0, 1.0, 0.0])
        engine.add("c", "Third", [1.0, 0.0, 0.0])

        results = engine.search([1.0, 0.0, 0.0], top_k=5)

        assert len(results) >= 1
        # The most similar should be first
        assert results[0]["score"] >= results[-1]["score"]

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_search_respects_threshold(self):
        """Test search respects similarity threshold."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.99)
        engine.add("a", "First", [0.1, 0.2, 0.3])
        engine.add("b", "Second", [0.9, 0.0, 0.0])

        results = engine.search([1.0, 0.0, 0.0], top_k=5)

        # Only highly similar entries should match
        for r in results:
            assert r["score"] >= 0.99 or len(results) == 0

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_search_respects_top_k(self):
        """Test search respects top_k limit."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.0)
        for i in range(10):
            engine.add(f"entry{i}", f"Text {i}", [1.0, 0.0, 0.0])

        results = engine.search([1.0, 0.0, 0.0], top_k=3)

        assert len(results) <= 3


class TestRagEngineWrapperPythonSearch:
    """Tests for _python_search method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_python_search_time_decay(self):
        """Test search with time decay."""
        import time

        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.0)
        # Old entry
        engine.add("old", "Old text", [1.0, 0.0, 0.0], timestamp=time.time() - 86400)
        # New entry
        engine.add("new", "New text", [1.0, 0.0, 0.0], timestamp=time.time())

        results = engine.search([1.0, 0.0, 0.0], top_k=5, time_decay_factor=0.1)

        # With time decay, newer should score higher
        if len(results) >= 2:
            # Find old and new in results
            old_score = next((r["score"] for r in results if r["id"] == "old"), 0)
            new_score = next((r["score"] for r in results if r["id"] == "new"), 0)
            assert new_score >= old_score


class TestRagEngineWrapperCosineSimilarity:
    """Tests for _cosine_similarity method."""

    def test_cosine_similarity_identical(self):
        """Test cosine similarity of identical vectors."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        result = RagEngineWrapper._cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert abs(result - 1.0) < 0.0001

    def test_cosine_similarity_orthogonal(self):
        """Test cosine similarity of orthogonal vectors."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        result = RagEngineWrapper._cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        assert abs(result - 0.0) < 0.0001

    def test_cosine_similarity_opposite(self):
        """Test cosine similarity of opposite vectors."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        result = RagEngineWrapper._cosine_similarity([1.0, 0.0, 0.0], [-1.0, 0.0, 0.0])
        assert abs(result - (-1.0)) < 0.0001

    def test_cosine_similarity_zero_vector(self):
        """Test cosine similarity with zero vector."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        result = RagEngineWrapper._cosine_similarity([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert result == 0.0


class TestRagEngineWrapperLen:
    """Tests for __len__ method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_len_empty(self):
        """Test len of empty engine."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        assert len(engine) == 0

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_len_with_entries(self):
        """Test len with entries."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("a", "First", [0.1, 0.2, 0.3])
        engine.add("b", "Second", [0.4, 0.5, 0.6])

        assert len(engine) == 2


class TestRagEngineWrapperClear:
    """Tests for clear method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_clear(self):
        """Test clearing all entries."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("a", "First", [0.1, 0.2, 0.3])
        engine.add("b", "Second", [0.4, 0.5, 0.6])

        engine.clear()

        assert len(engine) == 0


class TestRagEngineWrapperGetIds:
    """Tests for get_ids method."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_get_ids_empty(self):
        """Test get_ids on empty engine."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        assert engine.get_ids() == []

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_get_ids_with_entries(self):
        """Test get_ids with entries."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("a", "First", [0.1, 0.2, 0.3])
        engine.add("b", "Second", [0.4, 0.5, 0.6])

        ids = engine.get_ids()

        assert len(ids) == 2
        assert "a" in ids
        assert "b" in ids


class TestRagEngineWrapperSaveLoad:
    """Tests for save and load methods."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_save_and_load(self):
        """Test saving and loading entries."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3, similarity_threshold=0.0)
        engine.add("a", "First", [0.1, 0.2, 0.3])
        engine.add("b", "Second", [0.4, 0.5, 0.6])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            engine.save(path)

            # Load into new engine
            engine2 = RagEngineWrapper(dimension=3, similarity_threshold=0.0)
            count = engine2.load(path)

            assert count == 2
            assert len(engine2) == 2
            assert "a" in engine2.get_ids()
            assert "b" in engine2.get_ids()

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_save_creates_json(self):
        """Test save creates valid JSON file."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        engine.add("test", "Test text", [0.1, 0.2, 0.3])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            engine.save(path)

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            assert isinstance(data, list)
            assert len(data) == 1


class TestRagEngineWrapperIsRust:
    """Tests for is_rust property."""

    @patch("cogs.ai_core.memory.rag_rust.RUST_AVAILABLE", False)
    def test_is_rust_false(self):
        """Test is_rust returns False when using Python."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        engine = RagEngineWrapper(dimension=3)
        assert engine.is_rust is False


class TestModuleImports:
    """Tests for module imports."""

    def test_import_rag_engine_wrapper(self):
        """Test RagEngineWrapper can be imported."""
        from cogs.ai_core.memory.rag_rust import RagEngineWrapper

        assert RagEngineWrapper is not None

    def test_import_rag_engine_alias(self):
        """Test RagEngine alias can be imported."""
        from cogs.ai_core.memory.rag_rust import RagEngine

        assert RagEngine is not None

    def test_rust_available_flag_exists(self):
        """Test RUST_AVAILABLE flag exists."""
        from cogs.ai_core.memory.rag_rust import RUST_AVAILABLE

        assert isinstance(RUST_AVAILABLE, bool)
