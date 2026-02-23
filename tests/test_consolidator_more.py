"""
Extended tests for Memory Consolidator module.
Tests consolidation configuration and constants.
"""

from unittest.mock import patch


class TestMemoryConsolidatorInit:
    """Tests for MemoryConsolidator initialization."""

    def test_consolidator_init_creates_instance(self):
        """Test MemoryConsolidator creates instance."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator is not None

    def test_consolidator_has_client_none(self):
        """Test MemoryConsolidator client is None initially."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator._client is None

    def test_consolidator_has_task_none(self):
        """Test MemoryConsolidator task is None initially."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator._task is None

    def test_consolidator_has_message_counts_dict(self):
        """Test MemoryConsolidator has message_counts dict."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert isinstance(consolidator._message_counts, dict)

    def test_consolidator_has_last_consolidation_dict(self):
        """Test MemoryConsolidator has last_consolidation dict."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert isinstance(consolidator._last_consolidation, dict)


class TestMemoryConsolidatorSettings:
    """Tests for MemoryConsolidator default settings."""

    def test_consolidate_every_n_messages_default(self):
        """Test consolidate_every_n_messages default value."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator.consolidate_every_n_messages == 30

    def test_consolidate_interval_seconds_default(self):
        """Test consolidate_interval_seconds default value."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator.consolidate_interval_seconds == 3600

    def test_min_conversation_length_default(self):
        """Test min_conversation_length default value."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator.min_conversation_length == 200

    def test_max_recent_messages_default(self):
        """Test max_recent_messages default value."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator.max_recent_messages == 50

    def test_model_is_set(self):
        """Test model is set from constants."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator.model is not None


class TestGenaiAvailable:
    """Tests for GENAI_AVAILABLE constant."""

    def test_genai_available_is_bool(self):
        """Test GENAI_AVAILABLE is boolean."""
        from cogs.ai_core.memory.consolidator import GENAI_AVAILABLE

        assert isinstance(GENAI_AVAILABLE, bool)


class TestFactExtractionPrompt:
    """Tests for FACT_EXTRACTION_PROMPT constant."""

    def test_fact_extraction_prompt_exists(self):
        """Test FACT_EXTRACTION_PROMPT exists."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert FACT_EXTRACTION_PROMPT is not None

    def test_fact_extraction_prompt_is_string(self):
        """Test FACT_EXTRACTION_PROMPT is string."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert isinstance(FACT_EXTRACTION_PROMPT, str)

    def test_fact_extraction_prompt_contains_json(self):
        """Test FACT_EXTRACTION_PROMPT mentions JSON."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert "JSON" in FACT_EXTRACTION_PROMPT

    def test_fact_extraction_prompt_contains_entities(self):
        """Test FACT_EXTRACTION_PROMPT contains entities structure."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert "entities" in FACT_EXTRACTION_PROMPT

    def test_fact_extraction_prompt_has_placeholder(self):
        """Test FACT_EXTRACTION_PROMPT has conversation placeholder."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert "{conversation}" in FACT_EXTRACTION_PROMPT


class TestInitializeMethod:
    """Tests for initialize method."""

    def test_initialize_returns_bool(self):
        """Test initialize returns a boolean."""
        from cogs.ai_core.memory.consolidator import GENAI_AVAILABLE, MemoryConsolidator

        consolidator = MemoryConsolidator()

        if not GENAI_AVAILABLE:
            result = consolidator.initialize("test_api_key")
            assert result is False
        else:
            # When genai is available, it would try to use the API
            # We just check the return type
            with patch("cogs.ai_core.memory.consolidator.genai"):
                result = consolidator.initialize("test_api_key")
                assert isinstance(result, bool)


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test consolidator module has docstring."""
        from cogs.ai_core.memory import consolidator

        assert consolidator.__doc__ is not None


class TestEmptyDictsOnInit:
    """Tests for empty dictionaries on initialization."""

    def test_message_counts_empty(self):
        """Test message_counts is empty on init."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert len(consolidator._message_counts) == 0

    def test_last_consolidation_empty(self):
        """Test last_consolidation is empty on init."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert len(consolidator._last_consolidation) == 0


class TestSettingsTypes:
    """Tests for settings types."""

    def test_consolidate_every_n_is_int(self):
        """Test consolidate_every_n_messages is int."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert isinstance(consolidator.consolidate_every_n_messages, int)

    def test_interval_seconds_is_int(self):
        """Test consolidate_interval_seconds is int."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert isinstance(consolidator.consolidate_interval_seconds, int)

    def test_min_conversation_is_int(self):
        """Test min_conversation_length is int."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert isinstance(consolidator.min_conversation_length, int)

    def test_max_recent_is_int(self):
        """Test max_recent_messages is int."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert isinstance(consolidator.max_recent_messages, int)
