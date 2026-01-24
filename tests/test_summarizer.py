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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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


class TestSummarizerInit:
    """Tests for ConversationSummarizer initialization."""

    def test_init_defaults(self):
        """Test initialization with default values."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        
        assert summarizer.model is not None
        # Client may or may not be initialized depending on API key

    def test_init_model_from_env(self):
        """Test model is configurable."""
        from cogs.ai_core.memory.summarizer import SUMMARIZATION_MODEL
        
        # Model should be set
        assert SUMMARIZATION_MODEL is not None


class TestHistoryToText:
    """Tests for _history_to_text method."""

    def test_history_to_text_string_parts(self):
        """Test with string parts."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [
            {"role": "user", "parts": ["Hello world"]}
        ]

        result = summarizer._history_to_text(history)

        assert "User: Hello world" in result

    def test_history_to_text_dict_parts(self):
        """Test with dict parts containing text."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [
            {"role": "user", "parts": [{"text": "Hello world"}]}
        ]

        result = summarizer._history_to_text(history)

        assert "User: Hello world" in result

    def test_history_to_text_truncates_long(self):
        """Test that long messages are truncated."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        long_text = "A" * 1000
        history = [
            {"role": "user", "parts": [long_text]}
        ]

        result = summarizer._history_to_text(history)

        # Should be truncated to 500 + ...
        assert len(result) < 1000
        assert "..." in result

    def test_history_to_text_model_role(self):
        """Test model role is converted to AI."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [
            {"role": "model", "parts": ["Response"]}
        ]

        result = summarizer._history_to_text(history)

        assert "AI: Response" in result


class TestShouldSummarize:
    """Tests for should_summarize method."""

    @pytest.mark.asyncio
    async def test_should_summarize_below_threshold(self):
        """Test should_summarize returns False below threshold."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [{"role": "user", "parts": ["msg"]}] * 50

        result = await summarizer.should_summarize(history, threshold=100)

        assert result is False

    @pytest.mark.asyncio
    async def test_should_summarize_at_threshold(self):
        """Test should_summarize returns True at threshold."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [{"role": "user", "parts": ["msg"]}] * 100

        result = await summarizer.should_summarize(history, threshold=100)

        assert result is True

    @pytest.mark.asyncio
    async def test_should_summarize_custom_threshold(self):
        """Test should_summarize with custom threshold."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [{"role": "user", "parts": ["msg"]}] * 25

        result = await summarizer.should_summarize(history, threshold=20)

        assert result is True


class TestSummarize:
    """Tests for summarize method."""

    @pytest.mark.asyncio
    async def test_summarize_no_client(self):
        """Test summarize returns None when no client."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        summarizer.client = None

        history = [{"role": "user", "parts": ["msg"]}] * 20

        result = await summarizer.summarize(history)

        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_short_history(self):
        """Test summarize returns None for short history."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        # Even with client, history too short
        summarizer.client = MagicMock()

        history = [{"role": "user", "parts": ["msg"]}] * 5

        result = await summarizer.summarize(history)

        assert result is None


class TestCompressHistory:
    """Tests for compress_history method."""

    @pytest.mark.asyncio
    async def test_compress_history_short_returns_original(self):
        """Test compress_history returns original for short history."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        history = [{"role": "user", "parts": ["msg"]}] * 15

        result = await summarizer.compress_history(history, keep_recent=10)

        assert result == history  # No compression

    @pytest.mark.asyncio
    async def test_compress_history_needs_compression(self):
        """Test compress_history with summarization failure returns original."""
        from cogs.ai_core.memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer()
        summarizer.client = None  # No client = summarization fails
        
        history = [{"role": "user", "parts": ["msg"]}] * 50

        result = await summarizer.compress_history(history, keep_recent=10)

        # Should return original since summarization fails
        assert result == history


class TestConstants:
    """Tests for module constants."""

    def test_summarization_model_defined(self):
        """Test SUMMARIZATION_MODEL is defined."""
        from cogs.ai_core.memory.summarizer import SUMMARIZATION_MODEL

        assert SUMMARIZATION_MODEL is not None
        assert isinstance(SUMMARIZATION_MODEL, str)

    def test_min_conversation_length_defined(self):
        """Test MIN_CONVERSATION_LENGTH is defined and matches constants."""
        from cogs.ai_core.data.constants import MIN_CONVERSATION_LENGTH as CONST_MIN_LEN
        from cogs.ai_core.memory.summarizer import MIN_CONVERSATION_LENGTH

        assert MIN_CONVERSATION_LENGTH == 200
        assert MIN_CONVERSATION_LENGTH == CONST_MIN_LEN  # Should match constants

    def test_summarize_prompt_defined(self):
        """Test SUMMARIZE_PROMPT is defined."""
        from cogs.ai_core.memory.summarizer import SUMMARIZE_PROMPT

        assert SUMMARIZE_PROMPT is not None
        assert "{conversation}" in SUMMARIZE_PROMPT
