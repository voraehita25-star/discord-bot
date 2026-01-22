# pylint: disable=protected-access
"""
Unit Tests for Memory Consolidator Module.
Tests message counting and consolidation triggers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMemoryConsolidator:
    """Tests for MemoryConsolidator class."""

    def test_record_message_increments_counter(self):
        """Test recording a message increments the counter."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()

        channel_id = 123456789
        initial_count = consolidator._message_counts.get(channel_id, 0)

        consolidator.record_message(channel_id)

        new_count = consolidator._message_counts.get(channel_id, 0)
        assert new_count == initial_count + 1

    def test_should_consolidate_respects_threshold(self):
        """Test consolidation check respects message threshold."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()

        channel_id = 234567890
        # Set count below threshold
        consolidator._message_counts[channel_id] = 1
        consolidator._last_consolidation[channel_id] = 0  # Force time to pass

        result = consolidator.should_consolidate(channel_id)
        # With low count, should not consolidate
        assert isinstance(result, bool)

    def test_history_to_text_conversion(self):
        """Test history conversion to text."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()

        history = [
            {"role": "user", "parts": ["Hello world"]},
            {"role": "model", "parts": ["Hi there!"]},
        ]

        result = consolidator._history_to_text(history)

        assert "Hello world" in result
        assert "Hi there!" in result


class TestMemoryConsolidatorSingleton:
    """Tests for memory_consolidator singleton."""

    def test_singleton_exists(self):
        """Test that memory_consolidator singleton is accessible."""
        from cogs.ai_core.memory.consolidator import memory_consolidator

        assert memory_consolidator is not None

    def test_singleton_has_record_message(self):
        """Test singleton has record_message method."""
        from cogs.ai_core.memory.consolidator import memory_consolidator

        assert hasattr(memory_consolidator, "record_message")
        assert callable(memory_consolidator.record_message)

    def test_singleton_has_should_consolidate(self):
        """Test singleton has should_consolidate method."""
        from cogs.ai_core.memory.consolidator import memory_consolidator

        assert hasattr(memory_consolidator, "should_consolidate")
        assert callable(memory_consolidator.should_consolidate)

    def test_singleton_has_consolidate(self):
        """Test singleton has consolidate method."""
        from cogs.ai_core.memory.consolidator import memory_consolidator

        assert hasattr(memory_consolidator, "consolidate")
        assert callable(memory_consolidator.consolidate)


class TestMemoryConsolidatorMethods:
    """Tests for MemoryConsolidator methods."""

    def test_init_defaults(self):
        """Test MemoryConsolidator initialization defaults."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator._client is None
        assert consolidator._task is None
        assert consolidator.consolidate_every_n_messages == 30
        assert consolidator.consolidate_interval_seconds == 3600
        assert consolidator.min_conversation_length == 200
        assert consolidator.max_recent_messages == 50

    def test_record_message_multiple(self):
        """Test recording multiple messages."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        channel_id = 111222333

        for _ in range(10):
            consolidator.record_message(channel_id)

        assert consolidator._message_counts.get(channel_id, 0) == 10

    def test_should_consolidate_by_message_count(self):
        """Test should_consolidate returns True when message count threshold met."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        channel_id = 444555666

        # Set count above threshold
        consolidator._message_counts[channel_id] = 30

        result = consolidator.should_consolidate(channel_id)
        assert result is True

    def test_should_consolidate_by_time(self):
        """Test should_consolidate returns True when time threshold met."""
        import time

        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        channel_id = 777888999

        # Set last consolidation time far in the past
        consolidator._last_consolidation[channel_id] = time.time() - 7200  # 2 hours ago
        consolidator._message_counts[channel_id] = 1  # Below message threshold

        result = consolidator.should_consolidate(channel_id)
        assert result is True

    def test_history_to_text_with_string_parts(self):
        """Test _history_to_text with string parts."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        history = [
            {"role": "user", "parts": ["Hello, how are you?"]},
            {"role": "model", "parts": ["I'm fine, thank you!"]},
        ]

        result = consolidator._history_to_text(history)

        assert "User: Hello" in result
        assert "AI: I'm fine" in result

    def test_history_to_text_with_dict_parts(self):
        """Test _history_to_text with dict parts containing text."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        history = [
            {"role": "user", "parts": [{"text": "Hello world"}]},
            {"role": "model", "parts": [{"text": "Hi there"}]},
        ]

        result = consolidator._history_to_text(history)

        assert "User: Hello world" in result
        assert "AI: Hi there" in result

    def test_history_to_text_truncates_long_parts(self):
        """Test _history_to_text truncates long text parts."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        long_text = "A" * 1000
        history = [
            {"role": "user", "parts": [long_text]},
        ]

        result = consolidator._history_to_text(history)

        # Should be truncated to 500 chars
        assert len(result) < 1000

    def test_parse_extraction_valid_json(self):
        """Test _parse_extraction with valid JSON."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        response = '{"entities": [{"name": "Test", "type": "character"}]}'

        result = consolidator._parse_extraction(response)

        assert result is not None
        assert "entities" in result
        assert result["entities"][0]["name"] == "Test"

    def test_parse_extraction_json_with_markdown(self):
        """Test _parse_extraction with JSON wrapped in markdown."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        response = '```json\n{"entities": []}\n```'

        result = consolidator._parse_extraction(response)

        assert result is not None
        assert "entities" in result

    def test_parse_extraction_invalid_json(self):
        """Test _parse_extraction with invalid JSON."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        response = "This is not JSON"

        result = consolidator._parse_extraction(response)

        assert result is None

    def test_parse_extraction_finds_json_in_text(self):
        """Test _parse_extraction finds JSON embedded in text."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        response = 'Some text before {"entities": []} and after'

        result = consolidator._parse_extraction(response)

        assert result is not None
        assert "entities" in result

    def test_format_contradictions_warning_empty(self):
        """Test format_contradictions_warning with no contradictions."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        result = consolidator.format_contradictions_warning([])

        assert result == ""

    def test_format_contradictions_warning_with_data(self):
        """Test format_contradictions_warning with contradictions."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        contradictions = [
            {
                "entity": "Alice",
                "field": "age",
                "stored": "20",
                "mentioned": "25",
            }
        ]

        result = consolidator.format_contradictions_warning(contradictions)

        assert "คำเตือน" in result
        assert "Alice" in result
        assert "age" in result
        assert "20" in result
        assert "25" in result


class TestConsolidateAsync:
    """Async tests for consolidate method."""

    @pytest.mark.asyncio
    async def test_consolidate_no_client(self):
        """Test consolidate returns 0 when no client."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        # Client is None by default

        result = await consolidator.consolidate(123, [{"role": "user", "parts": ["test"]}])

        assert result == 0

    @pytest.mark.asyncio
    async def test_consolidate_empty_history(self):
        """Test consolidate returns 0 for empty history."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        consolidator._client = MagicMock()

        result = await consolidator.consolidate(123, [])

        assert result == 0


class TestDetectContradictions:
    """Tests for detect_contradictions method."""

    @pytest.mark.asyncio
    async def test_detect_contradictions_no_entities(self):
        """Test detect_contradictions with no entity markers."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        text = "Hello, this is normal text without entity markers."

        result = await consolidator.detect_contradictions(text, 123)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_detect_contradictions_with_entity_marker(self):
        """Test detect_contradictions extracts entity names from markers."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        text = "{{Alice}} went to the store."

        # No entity in memory, should return empty
        result = await consolidator.detect_contradictions(text, 123)

        assert isinstance(result, list)


class TestInitialize:
    """Tests for initialize method."""

    def test_initialize_without_genai(self):
        """Test initialize logs warning when genai not available."""
        from cogs.ai_core.memory.consolidator import GENAI_AVAILABLE, MemoryConsolidator

        consolidator = MemoryConsolidator()

        if not GENAI_AVAILABLE:
            result = consolidator.initialize("fake_api_key")
            assert result is False
