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

        result = MemoryResult(
            content="Test content",
            score=0.85,
            memory_id=123,
            source="semantic"
        )

        assert result.content == "Test content"
        assert result.score == 0.85
        assert result.memory_id == 123
        assert result.source == "semantic"

    def test_memory_result_default_age(self):
        """Test MemoryResult default age_days."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(
            content="Test",
            score=0.5,
            memory_id=1,
            source="keyword"
        )

        assert result.age_days == 0

    def test_memory_result_with_age(self):
        """Test MemoryResult with age_days."""
        from cogs.ai_core.memory.rag import MemoryResult

        result = MemoryResult(
            content="Test",
            score=0.5,
            memory_id=1,
            source="hybrid",
            age_days=7.5
        )

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
            memory_id=1,
            access_count=5,
            last_accessed=time.time(),
            boost_score=0.5
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
        assert hasattr(ms, 'get_stats')
        assert callable(ms.get_stats)

    def test_memory_system_has_generate_embedding_method(self):
        """Test MemorySystem has generate_embedding method."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        assert hasattr(ms, 'generate_embedding')
        assert callable(ms.generate_embedding)

    def test_memory_system_has_add_memory_method(self):
        """Test MemorySystem has add_memory method."""
        from cogs.ai_core.memory.rag import MemorySystem

        ms = MemorySystem()
        assert hasattr(ms, 'add_memory')
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

        with patch.object(MemorySystem, '__init__', lambda x: None):
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

        with patch.object(MemorySystem, '__init__', lambda x: None):
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

        with patch.object(MemorySystem, '__init__', lambda x: None):
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

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            decay = system._calculate_time_decay("invalid_date")

            # Should default to 1.0
            assert decay == 1.0

    def test_expand_query_simple(self):
        """Test query expansion with no synonyms."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            result = system.expand_query("hello world")

            assert "hello world" in result

    def test_expand_query_thai(self):
        """Test query expansion with Thai synonyms."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            result = system.expand_query("ชื่อ")

            assert "ชื่อ" in result
            # Should include synonyms
            assert "นาม" in result or "name" in result

    def test_expand_query_english(self):
        """Test query expansion with English synonyms."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            result = system.expand_query("work and home")

            assert "work" in result.lower()
            assert "home" in result.lower()

    def test_keyword_search_empty(self):
        """Test keyword search with empty memories."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            results = system._keyword_search("test query", [])

            assert results == []

    def test_keyword_search_no_match(self):
        """Test keyword search with no matches."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            memories = [{"id": 1, "content": "apple banana cherry"}]
            results = system._keyword_search("xyz abc", memories)

            assert results == []

    def test_keyword_search_partial_match(self):
        """Test keyword search with partial match."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            memories = [{"id": 1, "content": "hello world programming"}]
            results = system._keyword_search("hello programming", memories)

            assert len(results) >= 1
            assert results[0][0] == 1

    def test_keyword_search_exact_phrase(self):
        """Test keyword search with exact phrase match."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            memories = [
                {"id": 1, "content": "hello world"},
                {"id": 2, "content": "hello there world"}
            ]
            results = system._keyword_search("hello world", memories)

            # Exact phrase match should score higher
            assert len(results) >= 1

    def test_reciprocal_rank_fusion_empty(self):
        """Test RRF with empty inputs."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            results = system._reciprocal_rank_fusion([], [])

            assert results == []

    def test_reciprocal_rank_fusion_semantic_only(self):
        """Test RRF with semantic results only."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            semantic = [(1, 0.9), (2, 0.8)]
            results = system._reciprocal_rank_fusion(semantic, [])

            assert len(results) == 2

    def test_reciprocal_rank_fusion_combined(self):
        """Test RRF with both semantic and keyword results."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
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

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()
            system.client = None

            result = await system.generate_embedding("test")

            assert result is None

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_no_client(self):
        """Test batch embedding with no client."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()
            system.client = None

            results = await system.generate_embeddings_batch(["a", "b", "c"])

            assert results == [None, None, None]

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_empty(self):
        """Test batch embedding with empty list."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()
            system.client = MagicMock()

            results = await system.generate_embeddings_batch([])

            assert results == []

    @pytest.mark.asyncio
    async def test_search_memory_empty_results(self):
        """Test search_memory with no results."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()
            system._faiss_index = None
            system._index_built = False
            system._memories_cache = {}
            system.client = None

            with patch('cogs.ai_core.memory.rag.db') as mock_db:
                mock_db.get_all_rag_memories = AsyncMock(return_value=[])

                results = await system.search_memory("test query")

                assert results == []

    @pytest.mark.asyncio
    async def test_linear_search_raw_empty(self):
        """Test _linear_search_raw with empty memories."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            query_vec = np.random.rand(768).astype(np.float32)
            results = await system._linear_search_raw(query_vec, 5, [])

            assert results == []

    @pytest.mark.asyncio
    async def test_linear_search_with_valid_memory(self):
        """Test _linear_search_raw with valid memory."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
            system = MemorySystem()

            # Create a query vector and matching memory vector
            query_vec = np.random.rand(768).astype(np.float32)
            mem_vec = query_vec.copy()  # Same vector for high similarity

            memories = [{
                "id": 1,
                "content": "test memory",
                "embedding": mem_vec.tobytes()
            }]

            results = await system._linear_search_raw(query_vec, 5, memories)

            # Should find the matching memory
            assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_add_memory_no_embedding(self):
        """Test add_memory when embedding fails."""
        from cogs.ai_core.memory.rag import MemorySystem

        with patch.object(MemorySystem, '__init__', lambda x: None):
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

        with patch.object(MemorySystem, '__init__', lambda x: None):
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
            age_days=14.5
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

        result = MemoryResult(
            content="test",
            score=0.5,
            memory_id=1,
            source="keyword"
        )

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
            memory_id=200,
            access_count=10,
            last_accessed=current,
            boost_score=2.0
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

        result = MemoryResult(
            content="test", score=0.9, memory_id=1, source="semantic"
        )
        assert result.source == "semantic"

    def test_keyword_source(self):
        """Test keyword source type."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(
            content="test", score=0.8, memory_id=2, source="keyword"
        )
        assert result.source == "keyword"

    def test_hybrid_source(self):
        """Test hybrid source type."""
        try:
            from cogs.ai_core.memory.rag import MemoryResult
        except ImportError:
            pytest.skip("rag module not available")
            return

        result = MemoryResult(
            content="test", score=0.85, memory_id=3, source="hybrid"
        )
        assert result.source == "hybrid"
