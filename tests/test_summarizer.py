# pylint: disable=protected-access
"""
Unit Tests for Conversation Summarizer Module.
Tests summarization logic and history compression.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConversationSummarizer:
    """Tests for ConversationSummarizer class."""

    def test_history_to_text_conversion(self):
        """Test converting history list to readable text."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()

        history = [
            {"role": "user", "parts": ["Hello, how are you?"]},
            {"role": "model", "parts": ["I'm doing well, thank you!"]},
            {"role": "user", "parts": ["Great!"]},
        ]

        result = summarizer._history_to_text(history)

        # The implementation uses "AI" for model role
        assert "User:" in result or "user:" in result.lower()
        assert "AI:" in result or "ai:" in result.lower()
        assert "Hello, how are you?" in result
        assert "I'm doing well, thank you!" in result

    async def test_should_summarize_false_for_short_history(self):
        """Test that short history doesn't need summarization."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()

        short_history = [
            {"role": "user", "parts": ["Hello"]},
            {"role": "model", "parts": ["Hi!"]},
        ]

        # should_summarize is async
        result = await summarizer.should_summarize(short_history)
        assert result is False

    async def test_should_summarize_true_for_long_history(self):
        """Test that long history needs summarization."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()

        # Create a history exceeding threshold (100)
        long_history = []
        for i in range(105):
            long_history.append({"role": "user", "parts": [f"Message {i}"]})

        result = await summarizer.should_summarize(long_history)
        assert result is True


class TestSummarizerSingleton:
    """Tests for summarizer singleton instance."""

    def test_singleton_exists(self):
        """Test that summarizer singleton is accessible."""
        from cogs.ai_core.memory.summarizer import summarizer

        assert summarizer is not None

    def test_singleton_is_correct_type(self):
        """Test that singleton is ConversationSummarizer instance."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer, summarizer

        assert isinstance(summarizer, ConversationSummarizer)

    def test_singleton_has_compress_history(self):
        """Test that singleton has compress_history method."""
        from cogs.ai_core.memory.summarizer import summarizer

        assert hasattr(summarizer, "compress_history")
        assert callable(summarizer.compress_history)
