"""
Tests for cogs/ai_core/memory/memory_consolidator.py

Comprehensive tests for MemoryConsolidator and ConversationSummary classes.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConversationSummaryDataclass:
    """Tests for ConversationSummary dataclass."""

    def test_conversation_summary_defaults(self):
        """Test ConversationSummary default values."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary()

        assert summary.id is None
        assert summary.channel_id == 0
        assert summary.user_id is None
        assert summary.summary == ""
        assert summary.key_topics == []
        assert summary.key_decisions == []
        assert summary.start_time is None
        assert summary.end_time is None
        assert summary.message_count == 0
        assert summary.created_at is None

    def test_conversation_summary_with_values(self):
        """Test ConversationSummary with custom values."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        now = datetime.now()
        summary = ConversationSummary(
            id=1,
            channel_id=12345,
            user_id=67890,
            summary="Test summary",
            key_topics=["topic1", "topic2"],
            key_decisions=["decision1"],
            start_time=now,
            end_time=now,
            message_count=10,
            created_at=now,
        )

        assert summary.id == 1
        assert summary.channel_id == 12345
        assert summary.user_id == 67890
        assert summary.summary == "Test summary"
        assert len(summary.key_topics) == 2
        assert len(summary.key_decisions) == 1
        assert summary.message_count == 10

    def test_to_context_string_basic(self):
        """Test to_context_string with basic data."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(
            summary="This is a test summary",
            start_time=datetime(2024, 1, 15),
        )

        result = summary.to_context_string()

        assert "สรุปการสนทนา" in result
        assert "15/01/2024" in result
        assert "This is a test summary" in result

    def test_to_context_string_no_start_time(self):
        """Test to_context_string without start_time."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(summary="Test")
        result = summary.to_context_string()

        assert "N/A" in result
        assert "Test" in result

    def test_to_context_string_with_topics(self):
        """Test to_context_string with key topics."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(
            summary="Test",
            start_time=datetime.now(),
            key_topics=["Python", "AI", "Discord"],
        )

        result = summary.to_context_string()

        assert "หัวข้อ:" in result
        assert "Python" in result

    def test_to_context_string_limits_topics(self):
        """Test to_context_string limits topics to 3."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        summary = ConversationSummary(
            summary="Test",
            start_time=datetime.now(),
            key_topics=["Topic1", "Topic2", "Topic3", "Topic4", "Topic5"],
        )

        result = summary.to_context_string()

        # Should only include first 3
        assert "Topic1" in result
        assert "Topic2" in result
        assert "Topic3" in result


class TestMemoryConsolidatorInit:
    """Tests for MemoryConsolidator initialization."""

    def test_init(self):
        """Test MemoryConsolidator init."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()

        assert consolidator._consolidation_task is None
        assert consolidator.MIN_MESSAGES_TO_SUMMARIZE == 20
        assert consolidator.SUMMARY_AGE_THRESHOLD_HOURS == 24
        assert consolidator.MAX_SUMMARY_LENGTH == 500

    def test_has_logger(self):
        """Test MemoryConsolidator has logger."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        assert consolidator.logger is not None


class TestMemoryConsolidatorBackgroundTask:
    """Tests for background task methods."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_start_background_task(self):
        """Test start_background_task creates task."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()

        # Mock asyncio.create_task
        with patch("asyncio.create_task") as mock_create:
            mock_task = MagicMock()
            mock_create.return_value = mock_task

            consolidator.start_background_task(interval_hours=1.0)

            mock_create.assert_called_once()
            assert consolidator._consolidation_task is mock_task

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_start_background_task_already_running(self):
        """Test start_background_task does nothing if already running."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        consolidator._consolidation_task = mock_task

        with patch("asyncio.create_task") as mock_create:
            consolidator.start_background_task()

            mock_create.assert_not_called()

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_stop_background_task(self):
        """Test stop_background_task cancels task."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        mock_task = MagicMock()
        consolidator._consolidation_task = mock_task

        consolidator.stop_background_task()

        mock_task.cancel.assert_called_once()
        assert consolidator._consolidation_task is None

    def test_stop_background_task_no_task(self):
        """Test stop_background_task with no task."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        consolidator._consolidation_task = None

        # Should not raise
        consolidator.stop_background_task()


class TestMemoryConsolidatorInitSchema:
    """Tests for init_schema method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_init_schema_no_db(self):
        """Test init_schema when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()

        # Should not raise, just return early
        await consolidator.init_schema()


class TestMemoryConsolidatorConsolidateChannel:
    """Tests for consolidate_channel method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_consolidate_channel_no_db(self):
        """Test consolidate_channel when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        result = await consolidator.consolidate_channel(12345)

        assert result is None


class TestMemoryConsolidatorConsolidateAllChannels:
    """Tests for consolidate_all_channels method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_consolidate_all_channels_no_db(self):
        """Test consolidate_all_channels when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        result = await consolidator.consolidate_all_channels()

        assert result == 0


class TestMemoryConsolidatorGetChannelSummaries:
    """Tests for get_channel_summaries method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_get_channel_summaries_no_db(self):
        """Test get_channel_summaries when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        result = await consolidator.get_channel_summaries(12345)

        assert result == []


class TestMemoryConsolidatorGetContextSummaries:
    """Tests for get_context_summaries method."""

    @pytest.mark.asyncio
    @patch("cogs.ai_core.memory.memory_consolidator.DB_AVAILABLE", False)
    async def test_get_context_summaries_no_db(self):
        """Test get_context_summaries when DB not available."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        result = await consolidator.get_context_summaries(12345)

        assert result == ""


class TestMemoryConsolidatorGenerateSummary:
    """Tests for _generate_summary method."""

    @pytest.mark.asyncio
    async def test_generate_summary_empty_messages(self):
        """Test _generate_summary with empty messages."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        result = await consolidator._generate_summary([])

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_summary_with_messages(self):
        """Test _generate_summary with messages."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        consolidator = MemoryConsolidator()
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "model", "content": "I'm fine, thank you!"},
            {"role": "user", "content": "Tell me about Python"},
            {"role": "model", "content": "Python is a programming language"},
        ]

        result = await consolidator._generate_summary(messages)

        assert result is not None
        assert "text" in result


class TestModuleImports:
    """Tests for module imports."""

    def test_import_conversation_summary(self):
        """Test ConversationSummary can be imported."""
        from cogs.ai_core.memory.memory_consolidator import ConversationSummary

        assert ConversationSummary is not None

    def test_import_memory_consolidator(self):
        """Test MemoryConsolidator can be imported."""
        from cogs.ai_core.memory.memory_consolidator import MemoryConsolidator

        assert MemoryConsolidator is not None

    def test_db_available_flag_exists(self):
        """Test DB_AVAILABLE flag exists."""
        from cogs.ai_core.memory.memory_consolidator import DB_AVAILABLE

        assert isinstance(DB_AVAILABLE, bool)
