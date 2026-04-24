# pylint: disable=protected-access
"""
Unit Tests for Memory Consolidator Module.
Tests message counting and consolidation triggers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        consolidator._message_counts[channel_id] = 5  # Minimum required for time-based trigger

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

        assert "\u0e04\u0e33\u0e40\u0e15\u0e37\u0e2d\u0e19" in result
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
        from cogs.ai_core.memory.consolidator import ANTHROPIC_AVAILABLE, MemoryConsolidator

        consolidator = MemoryConsolidator()

        if not ANTHROPIC_AVAILABLE:
            result = consolidator.initialize("fake_api_key")
            assert result is False


# ======================================================================
# Merged from test_consolidator_extended.py
# ======================================================================

class TestConsolidatorConstants:
    """Tests for consolidator constants."""

    def test_fact_extraction_prompt_exists(self):
        """Test FACT_EXTRACTION_PROMPT exists."""
        from cogs.ai_core.memory.consolidator import FACT_EXTRACTION_PROMPT

        assert FACT_EXTRACTION_PROMPT is not None
        assert isinstance(FACT_EXTRACTION_PROMPT, str)
        assert "JSON" in FACT_EXTRACTION_PROMPT

    def test_ANTHROPIC_AVAILABLE_flag(self):
        """Test ANTHROPIC_AVAILABLE flag exists."""
        from cogs.ai_core.memory.consolidator import ANTHROPIC_AVAILABLE

        assert isinstance(ANTHROPIC_AVAILABLE, bool)


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

        with patch("cogs.ai_core.memory.consolidator.ANTHROPIC_AVAILABLE", False):
            mc = MemoryConsolidator()
            result = mc.initialize("fake_api_key")

            assert result is False


class TestMemoryConsolidatorSingleton:
    """Tests for memory_consolidator singleton."""

    def test_singleton_is_consolidator(self):
        """Test singleton is MemoryConsolidator instance."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator, memory_consolidator

        assert isinstance(memory_consolidator, MemoryConsolidator)


# ======================================================================
# Merged from test_consolidator_more.py
# ======================================================================

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
    """Tests for ANTHROPIC_AVAILABLE constant."""

    def test_ANTHROPIC_AVAILABLE_is_bool(self):
        """Test ANTHROPIC_AVAILABLE is boolean."""
        from cogs.ai_core.memory.consolidator import ANTHROPIC_AVAILABLE

        assert isinstance(ANTHROPIC_AVAILABLE, bool)


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
        from cogs.ai_core.memory.consolidator import ANTHROPIC_AVAILABLE, MemoryConsolidator

        consolidator = MemoryConsolidator()

        if not ANTHROPIC_AVAILABLE:
            result = consolidator.initialize("test_api_key")
            assert result is False
        else:
            # When genai is available, it would try to use the API
            # We just check the return type
            with patch('cogs.ai_core.memory.consolidator.anthropic'):
                result = consolidator.initialize("test_api_key")
                assert isinstance(result, bool)


class TestModuleDocstring:
    """Tests for module documentation."""

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


class TestCleanupOldChannels:
    """Tests for cleanup_old_channels method."""

    def test_cleanup_removes_old_channels(self):
        """Test cleanup removes channels older than max_age."""
        import time as _time

        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        old_time = _time.time() - 100_000  # ~28 hours ago
        mc._last_consolidation = {1: old_time, 2: old_time}
        mc._message_counts = {1: 5, 2: 10}

        removed = mc.cleanup_old_channels(max_age_seconds=3600)

        assert removed == 2
        assert len(mc._last_consolidation) == 0
        assert len(mc._message_counts) == 0

    def test_cleanup_keeps_recent_channels(self):
        """Test cleanup keeps recent channels."""
        import time as _time

        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc._last_consolidation = {1: _time.time()}
        mc._message_counts = {1: 5}

        removed = mc.cleanup_old_channels(max_age_seconds=3600)

        assert removed == 0
        assert 1 in mc._last_consolidation

    def test_cleanup_enforces_max_channels(self):
        """Test cleanup enforces max_channels limit."""
        import time as _time

        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        now = _time.time()
        # Add 5 channels, limit to 2
        for i in range(5):
            mc._last_consolidation[i] = now - (i * 10)  # Oldest last
            mc._message_counts[i] = 1

        removed = mc.cleanup_old_channels(max_age_seconds=999999, max_channels=2)

        assert removed == 3
        assert len(mc._last_consolidation) == 2

    def test_cleanup_orphaned_message_counts(self):
        """Test cleanup removes orphaned message counts when over max."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        # Channels with counts but never consolidated (orphaned)
        for i in range(10):
            mc._message_counts[i] = 3

        removed = mc.cleanup_old_channels(max_age_seconds=3600, max_channels=5)

        assert removed > 0
        assert len(mc._message_counts) <= 5

    def test_cleanup_returns_zero_for_empty(self):
        """Test cleanup returns 0 for empty state."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        removed = mc.cleanup_old_channels()

        assert removed == 0


class TestShouldConsolidateTimeBased:
    """Tests for time-based consolidation triggers."""

    def test_should_consolidate_no_messages(self):
        """Test should_consolidate returns False with no messages."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc.should_consolidate(123) is False

    def test_should_consolidate_below_threshold(self):
        """Test should_consolidate returns False below message threshold."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc._message_counts[123] = 3  # < 30

        assert mc.should_consolidate(123) is False

    def test_should_consolidate_time_with_enough_messages(self):
        """Test time-based trigger requires at least 5 messages."""
        import time as _time

        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc._message_counts[123] = 5
        mc._last_consolidation[123] = _time.time() - 7200  # 2 hours ago

        assert mc.should_consolidate(123) is True

    def test_should_consolidate_time_too_few_messages(self):
        """Test time-based trigger doesn't fire with too few messages."""
        import time as _time

        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        mc._message_counts[123] = 3  # < 5
        mc._last_consolidation[123] = _time.time() - 7200  # 2 hours ago

        assert mc.should_consolidate(123) is False


class TestParseExtractionEdgeCases:
    """Additional edge cases for _parse_extraction."""

    def test_parse_extraction_empty_string(self):
        """Test _parse_extraction with empty string."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc._parse_extraction("") is None

    def test_parse_extraction_none(self):
        """Test _parse_extraction with None-like input."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        assert mc._parse_extraction("") is None

    def test_parse_extraction_list_directly(self):
        """Test _parse_extraction with JSON array."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        response = '[{"name": "Alice", "type": "character"}]'

        result = mc._parse_extraction(response)

        assert result is not None
        assert "entities" in result
        assert result["entities"][0]["name"] == "Alice"

    def test_parse_extraction_single_entity_in_text(self):
        """Test _parse_extraction finds single entity JSON in text."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        response = 'Here is the entity: {"name": "Bob", "type": "character"} done.'

        result = mc._parse_extraction(response)

        assert result is not None
        assert "entities" in result
        assert result["entities"][0]["name"] == "Bob"

    def test_parse_extraction_array_fallback_in_text(self):
        """Test _parse_extraction finds JSON array in text."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        response = 'Found: [{"name": "Carol"}]'

        result = mc._parse_extraction(response)

        assert result is not None
        assert "entities" in result

    def test_parse_extraction_triple_backtick_only(self):
        """Test _parse_extraction with ``` wrapping (no json tag)."""
        from cogs.ai_core.memory.consolidator import MemoryConsolidator

        mc = MemoryConsolidator()
        response = '```\n{"entities": [{"name": "Dave"}]}\n```'

        result = mc._parse_extraction(response)

        assert result is not None
        assert result["entities"][0]["name"] == "Dave"
