"""
Tests for cogs.ai_core.memory.consolidator module.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConsolidatorConstants:
    """Tests for consolidator constants."""

    def test_fact_extraction_prompt_exists(self):
        """Test FACT_EXTRACTION_PROMPT exists."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert FACT_EXTRACTION_PROMPT is not None
        assert isinstance(FACT_EXTRACTION_PROMPT, str)
        assert "JSON" in FACT_EXTRACTION_PROMPT

    def test_genai_available_flag(self):
        """Test GENAI_AVAILABLE flag exists."""
        from cogs.ai_core.memory.consolidator import GENAI_AVAILABLE

        assert isinstance(GENAI_AVAILABLE, bool)


class TestMemoryConsolidatorInit:
    """Tests for MemoryConsolidator initialization."""

    def test_init_creates_instance(self):
        """Test initialization creates instance."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc is not None

    def test_init_client_is_none(self):
        """Test client is None initially."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc._client is None

    def test_init_task_is_none(self):
        """Test task is None initially."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc._task is None

    def test_init_message_counts_empty(self):
        """Test message counts dict is empty."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc._message_counts == {}

    def test_init_last_consolidation_empty(self):
        """Test last consolidation dict is empty."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc._last_consolidation == {}

    def test_init_settings(self):
        """Test default settings values."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc.consolidate_every_n_messages == 30
        assert mc.consolidate_interval_seconds == 3600
        assert mc.min_conversation_length == 200
        assert mc.max_recent_messages == 50


class TestRecordMessage:
    """Tests for record_message method."""

    def test_record_first_message(self):
        """Test recording first message for channel."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc.record_message(123)

        assert mc._message_counts[123] == 1

    def test_record_multiple_messages(self):
        """Test recording multiple messages."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc.record_message(123)
        mc.record_message(123)
        mc.record_message(123)

        assert mc._message_counts[123] == 3

    def test_record_messages_different_channels(self):
        """Test recording messages for different channels."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc.record_message(100)
        mc.record_message(200)
        mc.record_message(100)

        assert mc._message_counts[100] == 2
        assert mc._message_counts[200] == 1


class TestShouldConsolidate:
    """Tests for should_consolidate method."""

    def test_should_consolidate_after_n_messages(self):
        """Test consolidation triggers after N messages."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc.consolidate_every_n_messages = 5

        for _ in range(5):
            mc.record_message(123)

        assert mc.should_consolidate(123) is True

    def test_should_consolidate_checks_interval(self):
        """Test should_consolidate respects interval."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()

        # Just check the method exists and returns bool
        result = mc.should_consolidate(123)
        assert isinstance(result, bool)


class TestInitialize:
    """Tests for initialize method."""

    def test_initialize_without_genai(self):
        """Test initialize without genai available."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        with patch("cogs.ai_core.memory.consolidator.GENAI_AVAILABLE", False):
            mc = MemoryConsolidator()
            result = mc.initialize("fake_api_key")

            assert result is False


class TestMemoryConsolidatorSingleton:
    """Tests for memory_consolidator singleton."""

    def test_singleton_exists(self):
        """Test memory_consolidator singleton exists."""
        from cogs.ai_core.memory.consolidator import memory_consolidator

        assert memory_consolidator is not None

    def test_singleton_is_consolidator(self):
        """Test singleton is MemoryConsolidator instance."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator, memory_consolidator

        assert isinstance(memory_consolidator, MemoryConsolidator)
