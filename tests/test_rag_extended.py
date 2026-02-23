"""
Tests for cogs.ai_core.memory.rag module.
"""

import time


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

    def test_singleton_exists(self):
        """Test rag_system singleton exists."""
        from cogs.ai_core.memory.rag import rag_system

        assert rag_system is not None

    def test_singleton_is_memory_system(self):
        """Test singleton is MemorySystem instance."""
        from cogs.ai_core.memory.rag import MemorySystem, rag_system

        assert isinstance(rag_system, MemorySystem)
