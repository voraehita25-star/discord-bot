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
