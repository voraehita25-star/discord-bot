"""
Additional tests for RAG module dataclasses.
Tests MemoryResult and MemoryMetadata functionality.
"""

import pytest
from dataclasses import asdict
import time


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
