"""
Tests for cogs.ai_core.memory.rag module.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


class TestRAGConstants:
    """Tests for RAG module constants."""

    def test_embedding_model(self):
        """Test EMBEDDING_MODEL constant."""
        from cogs.ai_core.memory.rag import EMBEDDING_MODEL

        assert EMBEDDING_MODEL == "models/text-embedding-004"

    def test_semantic_min_similarity_constant(self):
        """RAG_SEMANTIC_MIN_SIMILARITY is a clamped float in [0, 1]."""
        from cogs.ai_core.memory.rag import RAG_SEMANTIC_MIN_SIMILARITY

        assert isinstance(RAG_SEMANTIC_MIN_SIMILARITY, float)
        assert 0.0 <= RAG_SEMANTIC_MIN_SIMILARITY <= 1.0

    def test_semantic_floor_drops_low_cosine(self):
        """The relevance floor removes semantic hits below the cutoff."""
        from cogs.ai_core.memory.rag import MemorySystem

        out = MemorySystem._apply_semantic_floor([(1, 0.9), (2, 0.1), (3, 0.5)], 0.25)
        assert out == [(1, 0.9), (3, 0.5)]

    def test_semantic_floor_disabled_passthrough(self):
        """floor <= 0 disables the gate (results unchanged)."""
        from cogs.ai_core.memory.rag import MemorySystem

        data = [(1, 0.1), (2, 0.05)]
        assert MemorySystem._apply_semantic_floor(data, 0.0) == data

    def test_embedding_dim(self):
        """Test EMBEDDING_DIM constant."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM

        assert EMBEDDING_DIM == 768

    def test_time_decay_half_life(self):
        """Test TIME_DECAY_HALF_LIFE_DAYS constant."""
        from cogs.ai_core.memory.rag import TIME_DECAY_HALF_LIFE_DAYS

        assert TIME_DECAY_HALF_LIFE_DAYS == 30

    def test_linear_search_thresholds(self):
        """Test linear search thresholds."""
        from cogs.ai_core.memory.rag import (
            LINEAR_SEARCH_MIN_SIMILARITY,
            LINEAR_SEARCH_RELEVANCE_THRESHOLD,
        )

        assert LINEAR_SEARCH_MIN_SIMILARITY == 0.5
        assert LINEAR_SEARCH_RELEVANCE_THRESHOLD == 0.65

    def test_faiss_available_flag(self):
        """Test FAISS_AVAILABLE flag."""
        from cogs.ai_core.memory.rag import FAISS_AVAILABLE

        assert isinstance(FAISS_AVAILABLE, bool)


class TestMemoryResult:
    """Tests for MemoryResult dataclass."""

    def test_create_memory_result(self):
        """Test creating MemoryResult."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(content="Test content", score=0.85, memory_id=123, source="semantic")

        assert result.content == "Test content"
        assert result.score == 0.85
        assert result.memory_id == 123
        assert result.source == "semantic"

    def test_memory_result_default_age(self):
        """Test MemoryResult default age_days."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(content="Test", score=0.5, memory_id=1, source="keyword")

        assert result.age_days == 0

    def test_memory_result_with_age(self):
        """Test MemoryResult with age_days."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(content="Test", score=0.5, memory_id=1, source="hybrid", age_days=7.5)

        assert result.age_days == 7.5


class TestMemoryMetadata:
    """Tests for MemoryMetadata dataclass."""

    def test_create_memory_metadata(self):
        """Test creating MemoryMetadata."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=456)

        assert meta.memory_id == 456
        assert meta.access_count == 0
        assert meta.last_accessed == 0.0
        assert meta.boost_score == 0.0

    def test_memory_metadata_with_values(self):
        """Test MemoryMetadata with initial values."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(
            memory_id=1, access_count=5, last_accessed=time.time(), boost_score=0.5
        )

        assert meta.access_count == 5
        assert meta.boost_score == 0.5

    def test_calculate_importance_new_memory(self):
        """Test importance calculation for new memory."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=1)
        importance = meta.calculate_importance(age_days=0)

        assert importance > 0
        assert importance <= 2.0

    def test_calculate_importance_old_memory(self):
        """Test importance decreases with age."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=1)

        importance_new = meta.calculate_importance(age_days=0)
        importance_old = meta.calculate_importance(age_days=60)

        assert importance_old < importance_new

    def test_calculate_importance_with_access(self):
        """Test importance increases with access count."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta_low = MemoryMetadata(memory_id=1, access_count=0)
        meta_high = MemoryMetadata(memory_id=2, access_count=10)

        importance_low = meta_low.calculate_importance(age_days=0)
        importance_high = meta_high.calculate_importance(age_days=0)

        assert importance_high >= importance_low

    def test_calculate_importance_with_boost(self):
        """Test importance with manual boost."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=1, boost_score=0.5)
        importance = meta.calculate_importance(age_days=0)

        assert importance > 0


class TestFAISSIndex:
    """Tests for FAISS index paths."""

    def test_faiss_index_dir(self):
        """Test FAISS_INDEX_DIR path."""
        from pathlib import Path

        from cogs.ai_core.memory.rag import FAISS_INDEX_DIR

        assert isinstance(FAISS_INDEX_DIR, Path)
        assert "faiss" in str(FAISS_INDEX_DIR)

    def test_faiss_index_file(self):
        """Test FAISS_INDEX_FILE path."""
        from cogs.ai_core.memory.rag import FAISS_INDEX_FILE

        assert "index.bin" in str(FAISS_INDEX_FILE)

    def test_faiss_id_map_file(self):
        """Test FAISS_ID_MAP_FILE path."""
        from cogs.ai_core.memory.rag import FAISS_ID_MAP_FILE

        assert "id_map.npy" in str(FAISS_ID_MAP_FILE)


class TestCosineSimilarity:
    """Tests for cosine similarity calculation."""

    def test_identical_vectors(self):
        """Test similarity of identical vectors."""
        import numpy as np

        # Cosine similarity is inline in this module, test math directly
        vec = np.array([1.0, 2.0, 3.0])
        similarity = np.dot(vec, vec) / (np.linalg.norm(vec) * np.linalg.norm(vec))

        assert abs(similarity - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        """Test similarity of orthogonal vectors."""
        import numpy as np

        vec1 = np.array([1.0, 0.0, 0.0])
        vec2 = np.array([0.0, 1.0, 0.0])
        similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

        assert abs(similarity) < 0.001

    def test_similar_vectors(self):
        """Test similarity of similar vectors."""
        import numpy as np

        vec1 = np.array([1.0, 2.0, 3.0])
        vec2 = np.array([1.1, 2.1, 3.1])
        similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

        assert similarity > 0.99


class TestMemorySystemBasic:
    """Basic tests for MemorySystem class."""

    def test_memory_system_exists(self):
        """Test MemorySystem class exists."""
        from cogs.ai_core.memory.rag import MemorySystem

        assert MemorySystem is not None

    def test_memory_system_init(self):
        """Test MemorySystem initialization."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        assert ms is not None

    def test_memory_system_has_get_stats_method(self):
        """Test MemorySystem has get_stats method."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        assert hasattr(ms, "get_stats")
        assert callable(ms.get_stats)

    def test_memory_system_has_generate_embedding_method(self):
        """Test MemorySystem has generate_embedding method."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        assert hasattr(ms, "generate_embedding")
        assert callable(ms.generate_embedding)

    def test_memory_system_has_add_memory_method(self):
        """Test MemorySystem has add_memory method."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        assert hasattr(ms, "add_memory")
        assert callable(ms.add_memory)

    def test_get_stats_returns_dict(self):
        """Test get_stats returns dict with expected keys."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        stats = ms.get_stats()

        assert isinstance(stats, dict)
        assert "faiss_available" in stats
        assert "index_built" in stats
        assert "memories_cached" in stats


class TestMemorySystemSingleton:
    """Tests for rag_system singleton."""

    def test_singleton_is_memory_system(self):
        """Test singleton is MemorySystem instance."""
        from cogs.ai_core.memory.rag import MemorySystem, rag_system

        assert isinstance(rag_system, MemorySystem)


# ======================================================================
# Merged from test_rag_module.py
# ======================================================================


class TestMemoryResultDataclass:
    """Tests for MemoryResult dataclass."""

    def test_create_memory_result(self):
        """Test creating a MemoryResult."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(
            content="test content",
            score=0.95,
            memory_id=123,
            source="semantic",
        )

        assert result.content == "test content"
        assert result.score == 0.95
        assert result.memory_id == 123
        assert result.source == "semantic"
        assert result.age_days == 0  # Default

    def test_memory_result_with_age(self):
        """Test MemoryResult with age_days."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(
            content="old memory",
            score=0.5,
            memory_id=456,
            source="keyword",
            age_days=30.5,
        )

        assert result.age_days == 30.5


class TestMemoryMetadataDataclass:
    """Tests for MemoryMetadata dataclass."""

    def test_create_memory_metadata(self):
        """Test creating MemoryMetadata."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=123)

        assert meta.memory_id == 123
        assert meta.access_count == 0
        assert meta.last_accessed == 0.0
        assert meta.boost_score == 0.0

    def test_calculate_importance_new_memory(self):
        """Test importance calculation for new memory."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=123)
        importance = meta.calculate_importance(age_days=0)

        # New memory should have high importance (1.0 * 1.0 * ...)
        assert importance > 0
        assert importance <= 2.0

    def test_calculate_importance_old_memory(self):
        """Test importance calculation for old memory."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=123)
        importance_new = meta.calculate_importance(age_days=0)
        importance_old = meta.calculate_importance(age_days=60)

        # Old memory should have less importance due to time decay
        assert importance_old < importance_new

    def test_calculate_importance_with_access(self):
        """Test importance with high access count."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=123, access_count=100)
        importance = meta.calculate_importance(age_days=0)

        # High access should boost importance
        assert importance > 1.0

    def test_calculate_importance_with_boost(self):
        """Test importance with manual boost."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(memory_id=123, boost_score=0.5)
        importance = meta.calculate_importance(age_days=0)

        # Boost should increase importance
        assert importance > 1.0

    def test_calculate_importance_with_recent_access(self):
        """Test importance with recent last_accessed."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(
            memory_id=123,
            last_accessed=time.time() - 3600,  # 1 hour ago
        )
        importance = meta.calculate_importance(age_days=0)

        # Recent access should boost
        assert importance > 0

    def test_importance_capped_at_2(self):
        """Test importance is capped at 2.0."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        meta = MemoryMetadata(
            memory_id=123,
            access_count=1000,
            boost_score=5.0,
            last_accessed=time.time(),
        )
        importance = meta.calculate_importance(age_days=0)

        assert importance <= 2.0


class TestFAISSIndex:
    """Tests for FAISSIndex class."""

    def test_faiss_index_creation(self):
        """Test creating FAISSIndex."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISSIndex

        index = FAISSIndex()

        assert index.dimension == EMBEDDING_DIM
        assert index.index is None
        assert index.id_map == []
        assert not index.is_initialized

    def test_faiss_index_custom_dimension(self):
        """Test FAISSIndex with custom dimension."""
        from cogs.ai_core.memory.rag import FAISSIndex

        index = FAISSIndex(dimension=512)

        assert index.dimension == 512

    def test_faiss_index_build_empty(self):
        """Test building index with empty data."""
        from cogs.ai_core.memory.rag import FAISSIndex

        index = FAISSIndex()
        index.build(np.array([]), [])

        # Should not crash, but also not initialize
        assert not index.is_initialized or index.index is None

    def test_faiss_index_search_uninitialized(self):
        """Test search on uninitialized index."""
        from cogs.ai_core.memory.rag import FAISSIndex

        index = FAISSIndex()
        results = index.search(np.random.rand(768), k=5)

        assert results == []

    def test_faiss_index_search_zero_vector(self):
        """Test search with zero vector."""
        from cogs.ai_core.memory.rag import FAISSIndex

        index = FAISSIndex()
        # Even if not initialized, zero vector should return empty
        results = index.search(np.zeros(768), k=5)

        assert results == []


class TestMemorySystem:
    """Tests for MemorySystem class."""

    def test_memory_system_creation(self):
        """Test creating MemorySystem."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system._faiss_index = None
            system._index_built = False
            system._memories_cache = {}
            system._save_pending = False
            system._save_task = None
            system._periodic_save_task = None
            system.client = None

            stats = system.get_stats()

            assert stats["faiss_available"] is not None
            assert not stats["index_built"]
            assert stats["memories_cached"] == 0

    def test_calculate_time_decay_now(self):
        """Test time decay for recent memory."""
        from datetime import datetime

        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            # Test with current time
            now = datetime.now().isoformat()
            decay = system._calculate_time_decay(now)

            # Should be close to 1.0 for recent memory
            assert decay > 0.9

    def test_calculate_time_decay_old(self):
        """Test time decay for old memory."""
        from datetime import datetime, timedelta

        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            # Test with 60 days old
            old_date = (datetime.now() - timedelta(days=60)).isoformat()
            decay = system._calculate_time_decay(old_date)

            # Should be lower due to decay
            assert decay < 0.5
            assert decay >= 0.1  # Minimum threshold

    def test_calculate_time_decay_invalid(self):
        """Test time decay with invalid input."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            decay = system._calculate_time_decay("invalid_date")

            # Should default to 1.0
            assert decay == 1.0

    def test_expand_query_simple(self):
        """Test query expansion with no synonyms."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            result = system.expand_query("hello world")

            assert "hello world" in result

    def test_expand_query_thai(self):
        """Test query expansion with Thai synonyms."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            result = system.expand_query("ชื่อ")

            assert "ชื่อ" in result
            # Should include synonyms
            assert "นาม" in result or "name" in result

    def test_expand_query_english(self):
        """Test query expansion with English synonyms."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            result = system.expand_query("work and home")

            assert "work" in result.lower()
            assert "home" in result.lower()

    def test_keyword_search_empty(self):
        """Test keyword search with empty memories."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            results = system._keyword_search("test query", [])

            assert results == []

    def test_keyword_search_no_match(self):
        """Test keyword search with no matches."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            memories = [{"id": 1, "content": "apple banana cherry"}]
            results = system._keyword_search("xyz abc", memories)

            assert results == []

    def test_keyword_search_partial_match(self):
        """Test keyword search with partial match."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            memories = [{"id": 1, "content": "hello world programming"}]
            results = system._keyword_search("hello programming", memories)

            assert len(results) >= 1
            assert results[0][0] == 1

    def test_keyword_search_exact_phrase(self):
        """Test keyword search with exact phrase match."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            memories = [
                {"id": 1, "content": "hello world"},
                {"id": 2, "content": "hello there world"},
            ]
            results = system._keyword_search("hello world", memories)

            # Exact phrase match should score higher
            assert len(results) >= 1

    def test_reciprocal_rank_fusion_empty(self):
        """Test RRF with empty inputs."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            results = system._reciprocal_rank_fusion([], [])

            assert results == []

    def test_reciprocal_rank_fusion_semantic_only(self):
        """Test RRF with semantic results only."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            semantic = [(1, 0.9), (2, 0.8)]
            results = system._reciprocal_rank_fusion(semantic, [])

            assert len(results) == 2

    def test_reciprocal_rank_fusion_combined(self):
        """Test RRF with both semantic and keyword results."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            semantic = [(1, 0.9), (2, 0.8)]
            keyword = [(2, 0.7), (3, 0.6)]

            results = system._reciprocal_rank_fusion(semantic, keyword)

            # ID 2 should score highest (appears in both)
            assert len(results) == 3
            top_id = results[0][0]
            assert top_id == 2


class TestAsyncMethods:
    """Tests for async methods in MemorySystem."""

    @pytest.mark.asyncio
    async def test_generate_embedding_no_client(self):
        """Test generate_embedding with no client."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system.client = None

            result = await system.generate_embedding("test")

            assert result is None

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_no_client(self):
        """Test batch embedding with no client."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system.client = None

            results = await system.generate_embeddings_batch(["a", "b", "c"])

            assert results == [None, None, None]

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_empty(self):
        """Test batch embedding with empty list."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system.client = MagicMock()

            results = await system.generate_embeddings_batch([])

            assert results == []

    @pytest.mark.asyncio
    async def test_search_memory_empty_results(self):
        """Test search_memory with no results."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system._faiss_index = None
            system._index_built = False
            system._memories_cache = {}
            system.client = None

            with patch("cogs.ai_core.memory.rag.db") as mock_db:
                mock_db.get_all_rag_memories = AsyncMock(return_value=[])

                results = await system.search_memory("test query")

                assert results == []

    @pytest.mark.asyncio
    async def test_linear_search_raw_empty(self):
        """Test _linear_search_raw with empty memories."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            query_vec = np.random.rand(768).astype(np.float32)
            results = await system._linear_search_raw(query_vec, 5, [])

            assert results == []

    @pytest.mark.asyncio
    async def test_linear_search_with_valid_memory(self):
        """Test _linear_search_raw with valid memory."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()

            # Create a query vector and matching memory vector
            query_vec = np.random.rand(768).astype(np.float32)
            mem_vec = query_vec.copy()  # Same vector for high similarity

            memories = [{"id": 1, "content": "test memory", "embedding": mem_vec.tobytes()}]

            results = await system._linear_search_raw(query_vec, 5, memories)

            # Should find the matching memory
            assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_add_memory_no_embedding(self):
        """Test add_memory when embedding fails."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system.client = None
            system._faiss_index = None
            system._index_built = False

            result = await system.add_memory("test content")

            assert result is False

    @pytest.mark.asyncio
    async def test_force_save_index_not_built(self):
        """Test force_save_index when index not built."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, "__init__", lambda x: None):
            system = MemorySystem()
            system._faiss_index = None
            system._index_built = False

            result = await system.force_save_index()

            assert result is False


class TestModuleImports:
    """Tests for module imports and constants."""

    def test_import_memory_result(self):
        """Test importing MemoryResult."""
        from cogs.ai_core.memory.rag import MemoryResult

        assert MemoryResult is not None

    def test_import_memory_metadata(self):
        """Test importing MemoryMetadata."""
        from cogs.ai_core.memory.rag import MemoryMetadata

        assert MemoryMetadata is not None

    def test_import_faiss_index(self):
        """Test importing FAISSIndex."""
        from cogs.ai_core.memory.rag import FAISSIndex

        assert FAISSIndex is not None

    def test_import_memory_system(self):
        """Test importing MemorySystem."""
        from cogs.ai_core.memory.rag import MemorySystem

        assert MemorySystem is not None

    def test_import_rag_system(self):
        """Test importing global rag_system."""
        from cogs.ai_core.memory.rag import rag_system

        assert rag_system is not None

    def test_embedding_constants(self):
        """Test embedding constants."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, EMBEDDING_MODEL

        assert EMBEDDING_MODEL is not None
        assert EMBEDDING_DIM == 768

    def test_time_decay_constant(self):
        """Test time decay constant."""
        from cogs.ai_core.memory.rag import TIME_DECAY_HALF_LIFE_DAYS

        assert TIME_DECAY_HALF_LIFE_DAYS == 30

    def test_linear_search_constants(self):
        """Test linear search thresholds."""
        from cogs.ai_core.memory.rag import (
            LINEAR_SEARCH_MIN_SIMILARITY,
            LINEAR_SEARCH_RELEVANCE_THRESHOLD,
        )

        assert LINEAR_SEARCH_MIN_SIMILARITY == 0.5
        assert LINEAR_SEARCH_RELEVANCE_THRESHOLD == 0.65


# ======================================================================
# Merged from test_rag_more.py
# ======================================================================


class TestMemoryResultDataclass:
    """Tests for MemoryResult dataclass."""

    def test_memory_result_all_fields(self):
        """Test MemoryResult with all fields."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(
            content="Test memory content",
            score=0.85,
            memory_id=123,
            source="semantic",
            age_days=14.5,
        )

        assert result.content == "Test memory content"
        assert result.score == 0.85
        assert result.memory_id == 123
        assert result.source == "semantic"
        assert result.age_days == 14.5

    def test_memory_result_age_default(self):
        """Test MemoryResult age_days defaults to 0."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(content="test", score=0.5, memory_id=1, source="keyword")

        assert result.age_days == 0


class TestMemoryMetadataDataclass:
    """Tests for MemoryMetadata dataclass."""

    def test_memory_metadata_all_defaults(self):
        """Test MemoryMetadata with all defaults."""
        try:
            from cogs.ai_core.memory.rag import MemoryMetadata
        except ImportError:
            pytest.skip("rag module not available")
            return

        meta = MemoryMetadata(memory_id=100)

        assert meta.memory_id == 100
        assert meta.access_count == 0
        assert meta.last_accessed == 0.0
        assert meta.boost_score == 0.0

    def test_memory_metadata_custom_values(self):
        """Test MemoryMetadata with custom values."""
        try:
            from cogs.ai_core.memory.rag import MemoryMetadata
        except ImportError:
            pytest.skip("rag module not available")
            return

        current = time.time()
        meta = MemoryMetadata(
            memory_id=200, access_count=10, last_accessed=current, boost_score=2.0
        )

        assert meta.access_count == 10
        assert meta.last_accessed == current
        assert meta.boost_score == 2.0


class TestRagModuleConstants:
    """Tests for RAG module constants."""

    def test_embedding_dim_is_768(self):
        """Test embedding dimension is 768."""
        try:
            from cogs.ai_core.memory.rag import EMBEDDING_DIM
        except ImportError:
            pytest.skip("rag module not available")
            return

        assert EMBEDDING_DIM == 768

    def test_time_decay_half_life_30_days(self):
        """Test time decay half life is 30 days."""
        try:
            from cogs.ai_core.memory.rag import TIME_DECAY_HALF_LIFE_DAYS
        except ImportError:
            pytest.skip("rag module not available")
            return

        assert TIME_DECAY_HALF_LIFE_DAYS == 30


class TestRagSearchThresholds:
    """Tests for RAG search thresholds."""

    def test_min_similarity_is_0_5(self):
        """Test minimum similarity threshold."""
        try:
            from cogs.ai_core.memory.rag import LINEAR_SEARCH_MIN_SIMILARITY
        except ImportError:
            pytest.skip("rag module not available")
            return

        assert LINEAR_SEARCH_MIN_SIMILARITY == 0.5

    def test_relevance_threshold_is_0_65(self):
        """Test relevance threshold."""
        try:
            from cogs.ai_core.memory.rag import LINEAR_SEARCH_RELEVANCE_THRESHOLD
        except ImportError:
            pytest.skip("rag module not available")
            return

        assert LINEAR_SEARCH_RELEVANCE_THRESHOLD == 0.65


class TestRagPathConfig:
    """Tests for RAG path configuration."""

    def test_faiss_index_dir_path(self):
        """Test FAISS index directory path."""
        try:
            from cogs.ai_core.memory.rag import FAISS_INDEX_DIR
        except ImportError:
            pytest.skip("rag module not available")
            return

        assert "faiss" in str(FAISS_INDEX_DIR).lower()

    def test_faiss_index_file_is_bin(self):
        """Test FAISS index file has .bin extension."""
        try:
            from cogs.ai_core.memory.rag import FAISS_INDEX_FILE
        except ImportError:
            pytest.skip("rag module not available")
            return

        assert str(FAISS_INDEX_FILE).endswith(".bin")


class TestImportanceCalculation:
    """Tests for importance calculation."""

    def test_importance_non_negative(self):
        """Test calculated importance is non-negative."""
        try:
            from cogs.ai_core.memory.rag import MemoryMetadata
        except ImportError:
            pytest.skip("rag module not available")
            return

        meta = MemoryMetadata(memory_id=1, access_count=0)
        importance = meta.calculate_importance(age_days=0)

        assert importance >= 0

    def test_importance_with_boost(self):
        """Test importance calculation with boost."""
        try:
            from cogs.ai_core.memory.rag import MemoryMetadata
        except ImportError:
            pytest.skip("rag module not available")
            return

        meta = MemoryMetadata(memory_id=1, access_count=5, boost_score=1.0)
        importance = meta.calculate_importance(age_days=7)

        assert importance >= 0


class TestMemorySourceTypes:
    """Tests for memory result source types."""

    def test_semantic_source(self):
        """Test semantic source type."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(content="test", score=0.9, memory_id=1, source="semantic")
        assert result.source == "semantic"

    def test_keyword_source(self):
        """Test keyword source type."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(content="test", score=0.8, memory_id=2, source="keyword")
        assert result.source == "keyword"

    def test_hybrid_source(self):
        """Test hybrid source type."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(content="test", score=0.85, memory_id=3, source="hybrid")
        assert result.source == "hybrid"


# ======================================================================
# Deepened coverage — uncovered FAISSIndex / MemorySystem behaviour.
# Appended; do not modify tests above this line.
# ======================================================================


def _new_system():
    """Build a MemorySystem without running __init__ (no Gemini client).

    Matches the existing convention of patching __init__ to a no-op and
    wiring up only the attributes a given test exercises.
    """
    from cogs.ai_core.memory.rag import MemorySystem

    with patch.object(MemorySystem, "__init__", lambda x: None):
        system = MemorySystem()
    return system


def _unit_vec(seed: int, dim: int = 768) -> "np.ndarray":
    """Deterministic non-zero float32 vector of the right embedding dim."""
    rng = np.random.default_rng(seed)
    return rng.random(dim).astype(np.float32)


class TestFAISSIndexBuildSearch:
    """FAISSIndex.build / search / add_single / add_batch real-index behaviour."""

    def test_build_then_search_maps_ids(self):
        """build() indexes vectors; search() maps positions back to memory IDs."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        v1 = _unit_vec(1)
        v2 = _unit_vec(2)
        idx.build(np.array([v1, v2]), [101, 202])

        assert idx.is_initialized
        # Querying with v1 should return id 101 as the top (similarity ~1.0) hit.
        results = idx.search(v1, k=2)
        assert results, "expected at least one hit"
        top_id, top_score = results[0]
        assert top_id == 101
        assert top_score > 0.99

    def test_build_normalizes_zero_norm_without_crash(self):
        """build() replaces zero-norm rows' divisor with 1 (no NaN, no crash)."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        zero = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        good = _unit_vec(3)
        idx.build(np.array([zero, good]), [1, 2])
        # Index built with both rows; ntotal stays aligned with id_map.
        assert idx.index.ntotal == len(idx.id_map) == 2

    def test_search_caps_k_at_ntotal(self):
        """search() with k larger than ntotal still returns at most ntotal hits."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(4)]), [7])
        results = idx.search(_unit_vec(4), k=50)
        assert len(results) == 1
        assert results[0][0] == 7

    def test_add_single_initializes_then_appends(self):
        """add_single bootstraps the index then appends keeping invariants."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        idx.add_single(_unit_vec(10), 1)
        assert idx.is_initialized
        assert idx.id_map == [1]
        idx.add_single(_unit_vec(11), 2)
        assert idx.id_map == [1, 2]
        assert idx.index.ntotal == 2

    def test_add_single_rejects_wrong_dim(self):
        """add_single raises ValueError on a wrong-dimension vector."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISSIndex

        idx = FAISSIndex(EMBEDDING_DIM)
        with pytest.raises(ValueError, match="vector dim"):
            idx.add_single(np.ones(10, dtype=np.float32), 1)

    def test_add_single_rejects_zero_norm(self):
        """add_single raises ValueError on a zero-norm vector."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISSIndex

        idx = FAISSIndex(EMBEDDING_DIM)
        with pytest.raises(ValueError, match="zero-norm"):
            idx.add_single(np.zeros(EMBEDDING_DIM, dtype=np.float32), 5)

    def test_add_single_rollback_on_first_add_failure(self):
        """If FAISS.add fails on the FIRST vector, id_map+index reset to empty."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)

        class _Boom:
            def add(self, *_a, **_k):
                raise RuntimeError("faiss add failed")

        with patch("cogs.ai_core.memory.rag.faiss.IndexFlatIP", return_value=_Boom()):
            with pytest.raises(RuntimeError):
                idx.add_single(_unit_vec(20), 99)
        # Invariant: a failed bootstrap leaves the index uninitialized.
        assert idx.id_map == []
        assert idx.index is None
        assert not idx.is_initialized

    def test_add_single_rollback_on_append_failure(self):
        """If FAISS.add fails on a SUBSEQUENT vector, the id_map entry is popped."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        idx.add_single(_unit_vec(30), 1)  # bootstrap succeeds

        with patch.object(idx.index, "add", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                idx.add_single(_unit_vec(31), 2)
        # id_map rolled back to its pre-append state.
        assert idx.id_map == [1]


class TestFAISSIndexAddBatch:
    """FAISSIndex.add_batch validation + batching behaviour."""

    def test_add_batch_empty_returns_zero(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISSIndex

        idx = FAISSIndex(EMBEDDING_DIM)
        assert idx.add_batch([], []) == 0

    def test_add_batch_length_mismatch_raises(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISSIndex

        idx = FAISSIndex(EMBEDDING_DIM)
        with pytest.raises(ValueError, match="length mismatch"):
            idx.add_batch([_unit_vec(1)], [1, 2])

    def test_add_batch_skips_bad_vectors(self):
        """Wrong-dim and zero-norm vectors are silently skipped; count = good ones."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        vecs = [
            _unit_vec(1),
            np.zeros(EMBEDDING_DIM, dtype=np.float32),  # zero-norm -> skip
            np.ones(5, dtype=np.float32),  # wrong dim -> skip
            _unit_vec(2),
        ]
        added = idx.add_batch(vecs, [10, 20, 30, 40])
        assert added == 2
        assert idx.id_map == [10, 40]
        assert idx.index.ntotal == 2

    def test_add_batch_all_bad_returns_zero(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISSIndex

        idx = FAISSIndex(EMBEDDING_DIM)
        added = idx.add_batch([np.zeros(EMBEDDING_DIM, dtype=np.float32)], [1])
        assert added == 0
        assert not idx.is_initialized

    def test_add_batch_appends_to_existing(self):
        """A second add_batch extends an already-initialized index."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        idx.add_batch([_unit_vec(1)], [1])
        idx.add_batch([_unit_vec(2), _unit_vec(3)], [2, 3])
        assert idx.id_map == [1, 2, 3]
        assert idx.index.ntotal == 3

    def test_add_batch_rolls_back_idmap_on_add_failure(self):
        """If FAISS.add raises on the append path, id_map is truncated back."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = FAISSIndex(EMBEDDING_DIM)
        idx.add_batch([_unit_vec(1)], [1])
        with patch.object(idx.index, "add", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                idx.add_batch([_unit_vec(2)], [2])
        assert idx.id_map == [1]


class TestFAISSIndexPersistence:
    """save_to_disk / load_from_disk round-trip + corruption guards (hermetic)."""

    def _redirect_paths(self, monkeypatch, tmp_path):
        import cogs.ai_core.memory.rag as rag

        d = tmp_path / "faiss"
        monkeypatch.setattr(rag, "FAISS_INDEX_DIR", d)
        monkeypatch.setattr(rag, "FAISS_INDEX_FILE", d / "index.bin")
        monkeypatch.setattr(rag, "FAISS_ID_MAP_FILE", d / "id_map.json")
        monkeypatch.setattr(rag, "_LEGACY_FAISS_ID_MAP_FILE", d / "id_map.npy")
        return rag, d

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        """A saved index reloads with the same id_map and is searchable."""
        rag, _d = self._redirect_paths(monkeypatch, tmp_path)
        if not rag.FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(1), _unit_vec(2)]), [11, 22])
        assert idx.save_to_disk() is True

        loaded = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert loaded.load_from_disk() is True
        assert loaded.id_map == [11, 22]
        assert loaded.index.ntotal == 2

    def test_save_uninitialized_returns_false(self, tmp_path, monkeypatch):
        rag, _d = self._redirect_paths(monkeypatch, tmp_path)
        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert idx.save_to_disk() is False

    def test_load_missing_files_returns_false(self, tmp_path, monkeypatch):
        rag, _d = self._redirect_paths(monkeypatch, tmp_path)
        if not rag.FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")
        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert idx.load_from_disk() is False

    def test_load_detects_length_mismatch(self, tmp_path, monkeypatch):
        """An id_map longer than ntotal is rejected and triggers a rebuild."""
        import json

        rag, d = self._redirect_paths(monkeypatch, tmp_path)
        if not rag.FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(1)]), [11])
        assert idx.save_to_disk() is True

        # Corrupt the id_map sidecar so its length disagrees with the index.
        payload = json.loads(rag.FAISS_ID_MAP_FILE.read_text(encoding="utf-8"))
        payload["id_map"] = [11, 22, 33]
        rag.FAISS_ID_MAP_FILE.write_text(json.dumps(payload), encoding="utf-8")

        loaded = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert loaded.load_from_disk() is False
        assert loaded.id_map == []
        assert loaded.index is None

    def test_load_detects_save_uuid_mismatch(self, tmp_path, monkeypatch):
        """A torn save (sidecar UUID != id_map UUID) is detected and rebuilt."""
        rag, d = self._redirect_paths(monkeypatch, tmp_path)
        if not rag.FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(1)]), [11])
        assert idx.save_to_disk() is True

        # Rewrite the standalone save.uuid sidecar to a different value while
        # leaving the id_map's embedded UUID intact -> mismatch.
        (d / "save.uuid").write_text("deadbeef", encoding="utf-8")

        loaded = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert loaded.load_from_disk() is False
        assert loaded.id_map == []

    def test_load_bad_json_returns_false(self, tmp_path, monkeypatch):
        """Unparseable id_map JSON is caught and forces a rebuild."""
        rag, d = self._redirect_paths(monkeypatch, tmp_path)
        if not rag.FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(1)]), [11])
        assert idx.save_to_disk() is True
        rag.FAISS_ID_MAP_FILE.write_text("{not valid json", encoding="utf-8")

        loaded = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert loaded.load_from_disk() is False

    def test_load_legacy_pickle_blocked_without_optin(self, tmp_path, monkeypatch):
        """Legacy .npy id_map is refused unless RAG_ALLOW_LEGACY_PICKLE is set."""
        rag, d = self._redirect_paths(monkeypatch, tmp_path)
        if not rag.FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        # Write a valid index but only a legacy .npy id_map (no JSON sidecar).
        idx = rag.FAISSIndex(rag.EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(1)]), [11])
        d.mkdir(parents=True, exist_ok=True)
        import cogs.ai_core.memory.rag as _rag

        _rag.faiss.write_index(idx.index, str(rag.FAISS_INDEX_FILE))
        np.save(str(rag._LEGACY_FAISS_ID_MAP_FILE), np.array([11]))

        monkeypatch.delenv("RAG_ALLOW_LEGACY_PICKLE", raising=False)
        loaded = rag.FAISSIndex(rag.EMBEDDING_DIM)
        assert loaded.load_from_disk() is False


class TestEvictCache:
    """_evict_cache_if_needed cache-bounding behaviour."""

    def test_no_eviction_under_cap(self):
        system = _new_system()
        system._memories_cache = {1: {"created_at": "2020"}}
        system._evict_cache_if_needed()
        assert 1 in system._memories_cache

    def test_evicts_oldest_when_over_cap(self):
        from cogs.ai_core.memory.rag import MemorySystem

        system = _new_system()
        # Fill above the cap; created_at ascending so id 0 is oldest.
        system._memories_cache = {
            i: {"created_at": f"{i:06d}"} for i in range(MemorySystem.MAX_CACHE_SIZE + 5)
        }
        before = len(system._memories_cache)
        system._evict_cache_if_needed()
        after = len(system._memories_cache)
        assert after < before
        # The very oldest entry must be gone.
        assert 0 not in system._memories_cache

    def test_eviction_handles_mixed_created_at_types(self):
        """A mix of str and int created_at must not raise on comparison."""
        from cogs.ai_core.memory.rag import MemorySystem

        system = _new_system()
        cache = {}
        for i in range(MemorySystem.MAX_CACHE_SIZE + 3):
            cache[i] = {"created_at": i if i % 2 else f"iso-{i}"}
        system._memories_cache = cache
        system._evict_cache_if_needed()  # must not raise TypeError
        assert len(system._memories_cache) < MemorySystem.MAX_CACHE_SIZE + 3


class TestAllMemoriesCache:
    """_get_all_memories_cached TTL cache + invalidation + bounding."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_copy(self, monkeypatch):
        """A live cache entry returns a fresh list (not the cached object)."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._all_memories_cache = {}
        rows = [{"id": 1, "content": "a"}]

        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        first = await system._get_all_memories_cached(42)
        assert first == rows
        assert mock_db.get_all_rag_memories.await_count == 1

        # Second call hits the cache (no new DB call) and returns a copy.
        second = await system._get_all_memories_cached(42)
        assert mock_db.get_all_rag_memories.await_count == 1
        assert second == rows
        assert second is not system._all_memories_cache[42][1]

    @pytest.mark.asyncio
    async def test_none_channel_skips_cache(self, monkeypatch):
        """channel_id=None never caches and re-queries every time."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._all_memories_cache = {}
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=[{"id": 1}])
        monkeypatch.setattr(rag, "db", mock_db)

        await system._get_all_memories_cached(None)
        await system._get_all_memories_cached(None)
        assert mock_db.get_all_rag_memories.await_count == 2
        assert system._all_memories_cache == {}

    @pytest.mark.asyncio
    async def test_db_timeout_returns_empty(self, monkeypatch):
        """A DB timeout yields [] rather than raising."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._all_memories_cache = {}
        mock_db = MagicMock()

        async def _slow(_cid):
            raise TimeoutError

        mock_db.get_all_rag_memories = _slow
        monkeypatch.setattr(rag, "db", mock_db)

        # Force wait_for to surface a TimeoutError immediately.
        async def _instant_timeout(awaitable, timeout):
            awaitable.close()
            raise TimeoutError

        monkeypatch.setattr(rag.asyncio, "wait_for", _instant_timeout)
        result = await system._get_all_memories_cached(7)
        assert result == []

    def test_invalidate_specific_channel(self):
        system = _new_system()
        system._all_memories_cache = {1: (999, []), 2: (999, [])}
        system.invalidate_all_memories_cache(1)
        assert 1 not in system._all_memories_cache
        assert 2 in system._all_memories_cache

    def test_invalidate_all_channels(self):
        system = _new_system()
        system._all_memories_cache = {1: (999, []), 2: (999, [])}
        system.invalidate_all_memories_cache(None)
        assert system._all_memories_cache == {}

    def test_evict_all_memories_cache_drops_expired_then_oldest(self):
        from cogs.ai_core.memory.rag import MemorySystem

        system = _new_system()
        cap = MemorySystem._ALL_MEMORIES_MAX_CHANNELS
        now = 1000.0
        cache = {}
        # One expired entry plus (cap+1) live entries with ascending expiry.
        cache[-1] = (now - 5, [])  # expired
        for i in range(cap + 1):
            cache[i] = (now + 100 + i, [])
        system._all_memories_cache = cache
        system._evict_all_memories_cache_if_needed(now)
        assert -1 not in system._all_memories_cache  # expired dropped first
        assert len(system._all_memories_cache) <= cap


class TestGenerateEmbedding:
    """generate_embedding happy path + shape/error guards."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self):
        system = _new_system()
        system.client = MagicMock()
        assert await system.generate_embedding("   ") is None

    @pytest.mark.asyncio
    async def test_happy_path_returns_vector(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM

        system = _new_system()
        values = list(_unit_vec(1))
        emb_obj = MagicMock()
        emb_obj.values = values
        result_obj = MagicMock()
        result_obj.embeddings = [emb_obj]

        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(return_value=result_obj)
        system.client = client

        vec = await system.generate_embedding("hello")
        assert vec is not None
        assert vec.size == EMBEDDING_DIM
        assert vec.dtype == np.float32

    @pytest.mark.asyncio
    async def test_no_embeddings_returns_none(self):
        system = _new_system()
        result_obj = MagicMock()
        result_obj.embeddings = []
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(return_value=result_obj)
        system.client = client
        assert await system.generate_embedding("hi") is None

    @pytest.mark.asyncio
    async def test_wrong_dim_returns_none(self):
        system = _new_system()
        emb_obj = MagicMock()
        emb_obj.values = [0.1, 0.2, 0.3]  # not EMBEDDING_DIM
        result_obj = MagicMock()
        result_obj.embeddings = [emb_obj]
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(return_value=result_obj)
        system.client = client
        assert await system.generate_embedding("hi") is None

    @pytest.mark.asyncio
    async def test_api_exception_returns_none(self):
        system = _new_system()
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(side_effect=RuntimeError("api down"))
        system.client = client
        assert await system.generate_embedding("hi") is None


class TestGenerateEmbeddingsBatch:
    """generate_embeddings_batch concurrency + per-item guards."""

    @pytest.mark.asyncio
    async def test_filters_empty_entries(self):
        """Whitespace-only entries become None without an API call."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM

        system = _new_system()
        emb_obj = MagicMock()
        emb_obj.values = list(_unit_vec(1))
        result_obj = MagicMock()
        result_obj.embeddings = [emb_obj]
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(return_value=result_obj)
        system.client = client

        out = await system.generate_embeddings_batch(["good", "   ", ""], batch_size=10)
        assert len(out) == 3
        assert out[0] is not None and out[0].size == EMBEDDING_DIM
        assert out[1] is None
        assert out[2] is None
        # Only the one non-empty text triggered an API call.
        assert client.aio.models.embed_content.await_count == 1

    @pytest.mark.asyncio
    async def test_all_empty_batch_returns_none_list(self):
        system = _new_system()
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock()
        system.client = client
        out = await system.generate_embeddings_batch(["", "  "], batch_size=5)
        assert out == [None, None]
        client.aio.models.embed_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_item_exception_becomes_none(self):
        """One failing embed call yields None for that slot, vector for the other."""
        from cogs.ai_core.memory.rag import EMBEDDING_DIM

        system = _new_system()
        emb_obj = MagicMock()
        emb_obj.values = list(_unit_vec(2))
        ok_result = MagicMock()
        ok_result.embeddings = [emb_obj]

        calls = {"n": 0}

        async def _embed(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return ok_result

        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(side_effect=_embed)
        system.client = client

        out = await system.generate_embeddings_batch(["x", "y"], batch_size=10)
        assert out[0] is None
        assert out[1] is not None and out[1].size == EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_wrong_dim_item_becomes_none(self):
        system = _new_system()
        emb_obj = MagicMock()
        emb_obj.values = [0.5, 0.5]  # wrong dim
        result_obj = MagicMock()
        result_obj.embeddings = [emb_obj]
        client = MagicMock()
        client.aio.models.embed_content = AsyncMock(return_value=result_obj)
        system.client = client
        out = await system.generate_embeddings_batch(["a"], batch_size=4)
        assert out == [None]


class TestKeywordSearchEdges:
    """_keyword_search edge branches not covered by the basic suite."""

    def test_empty_query_returns_empty(self):
        system = _new_system()
        assert system._keyword_search("", [{"id": 1, "content": "x"}]) == []

    def test_skips_empty_content_rows(self):
        system = _new_system()
        memories = [{"id": 1, "content": ""}, {"id": 2, "content": "hello world"}]
        results = system._keyword_search("hello", memories)
        ids = [mid for mid, _ in results]
        assert 1 not in ids
        assert 2 in ids

    def test_skips_rows_with_missing_or_sentinel_id(self):
        """Rows whose id is None or -1 are not emitted even if they match."""
        system = _new_system()
        memories = [
            {"id": None, "content": "match token"},
            {"id": -1, "content": "match token"},
            {"id": 9, "content": "match token"},
        ]
        results = system._keyword_search("match token", memories)
        assert [mid for mid, _ in results] == [9]

    def test_exact_phrase_outranks_partial(self):
        system = _new_system()
        memories = [
            {"id": 1, "content": "alpha beta gamma delta"},
            {"id": 2, "content": "alpha beta"},
        ]
        results = system._keyword_search("alpha beta", memories)
        # id 2 (exact phrase, fewer tokens -> higher Jaccard + phrase boost) wins.
        assert results[0][0] == 2

    def test_respects_limit(self):
        system = _new_system()
        memories = [{"id": i, "content": "common word"} for i in range(20)]
        results = system._keyword_search("common word", memories, limit=3)
        assert len(results) == 3


class TestReciprocalRankFusionWeights:
    """_reciprocal_rank_fusion weighting semantics."""

    def test_semantic_weight_dominates(self):
        system = _new_system()
        # Disjoint ids so weighting alone decides order.
        merged = system._reciprocal_rank_fusion(
            [(1, 0.9)], [(2, 0.9)], semantic_weight=5.0, keyword_weight=0.1
        )
        assert merged[0][0] == 1

    def test_keyword_weight_dominates(self):
        system = _new_system()
        merged = system._reciprocal_rank_fusion(
            [(1, 0.9)], [(2, 0.9)], semantic_weight=0.1, keyword_weight=5.0
        )
        assert merged[0][0] == 2

    def test_shared_id_accumulates(self):
        system = _new_system()
        merged = system._reciprocal_rank_fusion([(1, 0.9), (2, 0.8)], [(2, 0.7)])
        # id 2 appears in both lists so it accumulates and ranks first.
        assert merged[0][0] == 2


class TestLinearSearchRaw:
    """_linear_search_raw_sync finite / threshold / shape guards."""

    def test_skips_shape_mismatch(self):
        system = _new_system()
        q = _unit_vec(1)
        memories = [{"id": 1, "embedding": np.ones(10, dtype=np.float32).tobytes()}]
        assert system._linear_search_raw_sync(q, 5, memories) == []

    def test_below_threshold_dropped(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM

        system = _new_system()
        q = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        q[0] = 1.0
        orth = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        orth[1] = 1.0  # cosine 0 -> below 0.5 floor
        memories = [{"id": 1, "embedding": orth.tobytes()}]
        assert system._linear_search_raw_sync(q, 5, memories) == []

    def test_above_threshold_kept(self):
        system = _new_system()
        q = _unit_vec(5)
        memories = [{"id": 7, "embedding": q.tobytes()}]
        out = system._linear_search_raw_sync(q, 5, memories)
        assert out and out[0][0] == 7
        assert out[0][1] > 0.99

    def test_nonfinite_similarity_skipped(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM

        system = _new_system()
        q = _unit_vec(6)
        nan_vec = np.full(EMBEDDING_DIM, np.nan, dtype=np.float32)
        memories = [{"id": 1, "embedding": nan_vec.tobytes()}]
        assert system._linear_search_raw_sync(q, 5, memories) == []

    def test_corrupt_embedding_skipped(self):
        system = _new_system()
        q = _unit_vec(7)
        memories = [{"id": 1, "embedding": "not-bytes"}]
        # frombuffer raises -> caught -> row skipped, no crash.
        assert system._linear_search_raw_sync(q, 5, memories) == []


class TestLinearSearchLegacy:
    """_linear_search legacy wrapper: DB unavailability, timeout, threshold filter."""

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", False)
        monkeypatch.setattr(rag, "db", None)
        assert await system._linear_search(_unit_vec(1), 5, None) == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock()
        monkeypatch.setattr(rag, "db", mock_db)

        async def _to(awaitable, timeout):
            awaitable.close()
            raise TimeoutError

        monkeypatch.setattr(rag.asyncio, "wait_for", _to)
        assert await system._linear_search(_unit_vec(1), 5, None) == []

    @pytest.mark.asyncio
    async def test_filters_by_relevance_threshold(self, monkeypatch):
        """Only memories above LINEAR_SEARCH_RELEVANCE_THRESHOLD are returned."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)

        q = _unit_vec(11)
        # high-sim row (identical vec) + low-sim row (orthogonal-ish)
        low = np.zeros(rag.EMBEDDING_DIM, dtype=np.float32)
        low[0] = 1.0
        rows = [
            {"id": 1, "content": "relevant", "embedding": q.tobytes()},
            {"id": 2, "content": "noise", "embedding": low.tobytes()},
        ]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        out = await system._linear_search(q, 5, None)
        assert "relevant" in out
        assert "noise" not in out


class TestHybridSearch:
    """hybrid_search end-to-end branches: db guard, keyword-only, hybrid, decay."""

    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", False)
        monkeypatch.setattr(rag, "db", None)
        assert await system.hybrid_search("q") == []

    @pytest.mark.asyncio
    async def test_no_memories_returns_empty(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._memories_cache = {}
        system._all_memories_cache = {}
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=[])
        monkeypatch.setattr(rag, "db", mock_db)
        assert await system.hybrid_search("q", channel_id=5) == []

    @pytest.mark.asyncio
    async def test_keyword_only_when_no_embedding(self, monkeypatch):
        """With no Gemini client, query_vec is None -> keyword-only source."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system.client = None  # generate_embedding -> None
        system._memories_cache = {}
        system._all_memories_cache = {}
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)

        rows = [
            {"id": 1, "content": "the quick brown fox", "created_at": ""},
            {"id": 2, "content": "totally unrelated", "created_at": ""},
        ]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        results = await system.hybrid_search("quick brown fox", channel_id=5, use_time_decay=False)
        assert results
        assert all(r.source == "keyword" for r in results)
        assert results[0].memory_id == 1

    @pytest.mark.asyncio
    async def test_time_decay_lowers_old_memory_score(self, monkeypatch):
        """An old created_at reduces the final score via time decay."""
        from datetime import datetime, timedelta, timezone

        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system.client = None
        system._memories_cache = {}
        system._all_memories_cache = {}
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)

        old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        rows = [{"id": 1, "content": "alpha beta", "created_at": old_ts}]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        decayed = await system.hybrid_search("alpha beta", channel_id=5, use_time_decay=True)
        plain = await system.hybrid_search("alpha beta", channel_id=5, use_time_decay=False)
        assert decayed and plain
        assert decayed[0].score < plain[0].score
        assert decayed[0].age_days >= 100

    @pytest.mark.asyncio
    async def test_semantic_path_scopes_to_channel(self, monkeypatch):
        """A FAISS hit whose id is not in this channel's rows is filtered out."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._memories_cache = {}
        system._all_memories_cache = {}
        system._index_built = True
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)

        q = _unit_vec(50)
        # channel rows contain only id 1; FAISS returns id 999 (other channel)
        rows = [{"id": 1, "content": "alpha beta", "created_at": ""}]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        # Embedding present so the semantic branch runs.
        system.generate_embedding = AsyncMock(return_value=q)

        fake_index = MagicMock()
        fake_index.is_initialized = True
        fake_index.search_async = AsyncMock(return_value=[(999, 0.95), (1, 0.9)])
        system._faiss_index = fake_index

        async def _noop_ensure(_cid=None):
            return None

        system._ensure_index = _noop_ensure

        results = await system.hybrid_search("alpha beta", channel_id=5, use_time_decay=False)
        # id 999 (cross-channel) must not appear; id 1 (in keyword + scoped semantic) does.
        ids = {r.memory_id for r in results}
        assert 999 not in ids
        assert 1 in ids

    @pytest.mark.asyncio
    async def test_search_memory_returns_contents(self, monkeypatch):
        """search_memory unwraps hybrid_search MemoryResults to content strings."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system.client = None
        system._memories_cache = {}
        system._all_memories_cache = {}
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        rows = [{"id": 1, "content": "remember this", "created_at": ""}]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        out = await system.search_memory("remember this", limit=3, channel_id=5)
        assert "remember this" in out


class TestAddMemory:
    """add_memory validation + DB/FAISS interaction branches."""

    @pytest.mark.asyncio
    async def test_no_db_returns_false(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", False)
        monkeypatch.setattr(rag, "db", None)
        assert await system.add_memory("hi") is False

    @pytest.mark.asyncio
    async def test_zero_norm_embedding_refused(self, monkeypatch):
        """A zero-norm embedding is rejected before any DB write."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        mock_db = MagicMock()
        mock_db.save_rag_memory = AsyncMock(return_value=1)
        monkeypatch.setattr(rag, "db", mock_db)

        system.generate_embedding = AsyncMock(
            return_value=np.zeros(rag.EMBEDDING_DIM, dtype=np.float32)
        )
        assert await system.add_memory("hi") is False
        mock_db.save_rag_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_dim_embedding_refused(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        mock_db = MagicMock()
        mock_db.save_rag_memory = AsyncMock(return_value=1)
        monkeypatch.setattr(rag, "db", mock_db)
        system.generate_embedding = AsyncMock(return_value=np.ones(10, dtype=np.float32))
        assert await system.add_memory("hi") is False
        mock_db.save_rag_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_saves_and_invalidates_cache(self, monkeypatch):
        """A valid embedding is saved to DB and the channel cache is invalidated."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._faiss_index = None
        system._index_built = False
        system._index_lock = __import__("asyncio").Lock()
        system._all_memories_cache = {5: (10**12, [{"id": 1}])}
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", False)

        mock_db = MagicMock()
        mock_db.save_rag_memory = AsyncMock(return_value=123)
        monkeypatch.setattr(rag, "db", mock_db)
        system.generate_embedding = AsyncMock(return_value=_unit_vec(99))

        ok = await system.add_memory("a new fact", channel_id=5)
        assert ok is True
        mock_db.save_rag_memory.assert_awaited_once()
        # Cache for channel 5 dropped so next search sees the new row.
        assert 5 not in system._all_memories_cache

    @pytest.mark.asyncio
    async def test_faiss_add_failure_marks_rebuild(self, monkeypatch):
        """If add_single rejects the vector, index is marked un-built for rebuild."""
        import asyncio as _asyncio

        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._index_lock = _asyncio.Lock()
        system._index_built = True
        system._all_memories_cache = {}
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)

        mock_db = MagicMock()
        mock_db.save_rag_memory = AsyncMock(return_value=55)
        monkeypatch.setattr(rag, "db", mock_db)
        system.generate_embedding = AsyncMock(return_value=_unit_vec(7))

        fake_index = MagicMock()
        fake_index.add_single = MagicMock(side_effect=ValueError("bad vec"))
        system._faiss_index = fake_index

        ok = await system.add_memory("fact", channel_id=None)
        assert ok is True  # DB row committed
        assert system._index_built is False  # scheduled for rebuild


class TestEnsureIndex:
    """_ensure_index build-from-DB branches (FAISS available)."""

    @pytest.mark.asyncio
    async def test_no_db_marks_built(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._faiss_index = rag.FAISSIndex(rag.EMBEDDING_DIM)
        # Force load_from_disk to report nothing on disk so we reach the
        # build-from-DB branch.
        system._faiss_index.load_from_disk = lambda: False
        system._index_built = False
        system._index_lock = __import__("asyncio").Lock()
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)
        monkeypatch.setattr(rag, "_DB_AVAILABLE", False)
        monkeypatch.setattr(rag, "db", None)

        await system._ensure_index(None)
        assert system._index_built is True

    @pytest.mark.asyncio
    async def test_empty_db_marks_built(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._faiss_index = rag.FAISSIndex(rag.EMBEDDING_DIM)
        system._faiss_index.load_from_disk = lambda: False
        system._index_built = False
        system._index_lock = __import__("asyncio").Lock()
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=[])
        monkeypatch.setattr(rag, "db", mock_db)

        await system._ensure_index(None)
        assert system._index_built is True

    @pytest.mark.asyncio
    async def test_builds_from_valid_rows(self, monkeypatch):
        """Valid embeddings from DB produce an initialized, searchable index."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._faiss_index = rag.FAISSIndex(rag.EMBEDDING_DIM)
        system._faiss_index.load_from_disk = lambda: False
        system._index_built = False
        system._memories_cache = {}
        system._index_lock = __import__("asyncio").Lock()
        system._save_task = None
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)

        v1 = _unit_vec(60)
        v2 = _unit_vec(61)
        rows = [
            {"id": 1, "content": "a", "embedding": v1.tobytes()},
            {"id": 2, "content": "b", "embedding": v2.tobytes()},
        ]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)
        # Avoid touching disk during the build's save_to_disk call.
        monkeypatch.setattr(rag.FAISSIndex, "save_to_disk", lambda self: True)

        await system._ensure_index(None)
        assert system._index_built is True
        assert system._faiss_index.is_initialized
        assert sorted(system._faiss_index.id_map) == [1, 2]

    @pytest.mark.asyncio
    async def test_all_invalid_rows_marks_built_empty(self, monkeypatch):
        """A non-empty table with only invalid embeddings still marks built."""
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._faiss_index = rag.FAISSIndex(rag.EMBEDDING_DIM)
        system._faiss_index.load_from_disk = lambda: False
        system._index_built = False
        system._memories_cache = {}
        system._index_lock = __import__("asyncio").Lock()
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)
        monkeypatch.setattr(rag, "_DB_AVAILABLE", True)

        rows = [
            {"id": 1, "content": "a", "embedding": np.ones(10, dtype=np.float32).tobytes()},
            {"id": 2, "content": "b", "embedding": "corrupt"},
        ]
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=rows)
        monkeypatch.setattr(rag, "db", mock_db)

        await system._ensure_index(None)
        assert system._index_built is True
        # No valid vectors -> index never got initialized.
        assert not system._faiss_index.is_initialized

    @pytest.mark.asyncio
    async def test_already_built_is_noop(self, monkeypatch):
        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._index_built = True
        system._index_lock = __import__("asyncio").Lock()
        monkeypatch.setattr(rag, "FAISS_AVAILABLE", True)
        mock_db = MagicMock()
        mock_db.get_all_rag_memories = AsyncMock(return_value=[{"id": 1}])
        monkeypatch.setattr(rag, "db", mock_db)
        await system._ensure_index(None)
        # No DB read because the early return fired.
        mock_db.get_all_rag_memories.assert_not_called()


class TestSaveTasks:
    """Debounced + periodic save scheduling and teardown (no real sleeps)."""

    @pytest.mark.asyncio
    async def test_schedule_index_save_runs_after_delay(self, monkeypatch):
        import asyncio as _asyncio

        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._save_task = None
        system._index_built = True
        fake_index = MagicMock()
        fake_index.save_to_disk = MagicMock(return_value=True)
        system._faiss_index = fake_index

        # Collapse the debounce sleep so the test doesn't actually wait.
        async def _no_sleep(_secs):
            return None

        monkeypatch.setattr(rag.asyncio, "sleep", _no_sleep)

        system._schedule_index_save(delay=999)
        await system._save_task  # let the task run to completion
        fake_index.save_to_disk.assert_called_once()

    @pytest.mark.asyncio
    async def test_schedule_index_save_cancels_previous(self, monkeypatch):
        import asyncio as _asyncio
        import contextlib as _contextlib

        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._index_built = True
        system._faiss_index = MagicMock()

        # First task sleeps "forever"; scheduling a second must cancel it.
        async def _long_sleep(_secs):
            await _asyncio.Event().wait()

        monkeypatch.setattr(rag.asyncio, "sleep", _long_sleep)
        system._save_task = None
        system._schedule_index_save(delay=1)
        first = system._save_task
        system._schedule_index_save(delay=1)
        second = system._save_task

        # Drain BOTH tasks so neither lingers into session teardown (a
        # pending task keeps the event loop alive and hangs pytest on
        # Windows). The first was cancelled by the scheduler; cancel the
        # second ourselves. Await each so their cancellation fully settles.
        second.cancel()
        for task in (first, second):
            with _contextlib.suppress(_asyncio.CancelledError):
                await task
        assert first.cancelled()
        assert second.cancelled()

    @pytest.mark.asyncio
    async def test_stop_periodic_save_cancels_tasks(self, monkeypatch):
        import asyncio as _asyncio

        import cogs.ai_core.memory.rag as rag

        system = _new_system()
        system._index_built = True
        system._faiss_index = MagicMock()

        async def _forever():
            await _asyncio.Event().wait()

        system._save_task = _asyncio.create_task(_forever())
        system._periodic_save_task = _asyncio.create_task(_forever())
        await system.stop_periodic_save()
        assert system._save_task is None
        assert system._periodic_save_task is None

    @pytest.mark.asyncio
    async def test_force_save_index_runs_save(self, monkeypatch):
        system = _new_system()
        system._index_built = True
        fake_index = MagicMock()
        fake_index.save_to_disk = MagicMock(return_value=True)
        system._faiss_index = fake_index
        assert await system.force_save_index() is True
        fake_index.save_to_disk.assert_called_once()


class TestGetStatsDeep:
    """get_stats reflects live index state."""

    def test_stats_reflect_index(self):
        from cogs.ai_core.memory.rag import EMBEDDING_DIM, FAISS_AVAILABLE, FAISSIndex

        if not FAISS_AVAILABLE:
            pytest.skip("FAISS not installed")

        system = _new_system()
        system.client = object()
        system._index_built = True
        system._memories_cache = {1: {}, 2: {}}
        idx = FAISSIndex(EMBEDDING_DIM)
        idx.build(np.array([_unit_vec(1)]), [1])
        system._faiss_index = idx

        stats = system.get_stats()
        assert stats["index_built"] is True
        assert stats["memories_cached"] == 2
        assert stats["index_size"] == 1
        assert stats["client_ready"] is True
